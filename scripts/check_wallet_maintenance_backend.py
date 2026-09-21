#!/usr/bin/env python3
"""Real backup-first compaction, independent handover verification and failures.

Every accepted crypto operation uses the pinned original Rust backend. Lost
acknowledgements and partial manifest writes are controlled I/O faults, not real
ENOSPC, process-kill, Windows quota or physical power-loss experiments.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import secrets
import sys
import tempfile
from unittest.mock import patch

import wallet_maintenance as maintenance
from zevune_wallet import encode_request, invoke


def inventory(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() if p.is_file() else None for p in root.rglob("*")}


def rejected(operation):
    try:
        operation()
    except (ValueError, RuntimeError, OSError):
        return
    raise AssertionError("unsafe maintenance was accepted")


class ObservedBackend(maintenance.MaintenanceBackend):
    def call(self, op, password, paths, receipt):
        assert op in (2, 9), "maintenance tried a non-maintenance operation"
        return super().call(op, password, paths, receipt)


class LostCompactionReply(ObservedBackend):
    def compact(self, source, target, expected, password):
        super().compact(source, target, expected, password)
        raise RuntimeError("test_only_ack_lost_after_real_compaction")


class LostBackupReply(ObservedBackend):
    def call(self, op, password, paths, receipt):
        result = super().call(op, password, paths, receipt)
        if op == 2:
            raise RuntimeError("test_only_ack_lost_after_real_backup")
        return result


def run(executable):
    executable = executable.absolute()
    digest = hashlib.sha256(executable.read_bytes()).hexdigest()
    backend = ObservedBackend(executable, digest)
    password = secrets.token_bytes(32)
    with tempfile.TemporaryDirectory(prefix="zevune-maintenance-") as temporary:
        root = Path(temporary).resolve()
        source, peer, pool, genesis = (root / name for name in ("source.wallet", "peer.wallet", "pool", "genesis"))
        def call(op, paths, pin=None):
            return invoke(executable, encode_request(op, password, [str(p) for p in paths], pin), digest)
        initial = call(0, [source])["receipt"]
        original = source.read_bytes()
        empty = maintenance.compact(source, root / "empty", initial, password, backend, reserve_bytes=0)
        assert empty["requires_rescan"] is True and empty["active_wallet_replaced"] is False
        assert empty["target_receipt"][:64] != initial[:64] and source.read_bytes() == original
        assert maintenance.verify(root / "empty", initial, empty["handover_sha256"], password, backend)["target_receipt"] == empty["target_receipt"]

        domain = call(7, [source, pool, genesis])["genesis_sha256"]
        synced = call(3, [source, pool, genesis, domain])["receipt"]
        call(0, [peer])
        recipient = call(8, [peer, pool, genesis, domain, "0"])["address"]
        payment_file = root / "payment.tx"
        payment = call(4, [source, pool, genesis, domain, recipient, "25000", "1000", "10", payment_file], synced)
        pin, original = payment["receipt"], source.read_bytes()
        assert int(pin[64:80], 16) == 3
        before = inventory(root)
        for action in (
            lambda: maintenance.compact(source, root / "refused", initial, password, backend, reserve_bytes=0),
            lambda: maintenance.compact(source, root / "refused", pin, secrets.token_bytes(32), backend, reserve_bytes=0),
            lambda: maintenance.compact(source, root / "refused", pin, password, backend, reserve_bytes=maintenance.health.probe(root)["total_bytes"]),
        ):
            rejected(action)
            assert inventory(root) == before
        output = root / "pending"
        result = maintenance.compact(source, output, pin, password, backend, reserve_bytes=0)
        assert result["source_retained"] is True and result["real_funds_allowed"] is False
        assert source.read_bytes() == original and (output / "backup.journal").read_bytes() == original
        assert set(p.name for p in output.iterdir()) == maintenance.FILES
        target_pin = result["target_receipt"]
        assert int(target_pin[64:80], 16) == 1
        assert (output / "compacted.journal").stat().st_size == maintenance.COMPACT_BYTES
        stable = inventory(root)
        verified = maintenance.verify(output, pin, result["handover_sha256"], password, backend)
        assert verified["target_receipt"] == target_pin and inventory(root) == stable
        for action in (
            lambda: maintenance.verify(output, pin, "0" * 64, password, backend),
            lambda: maintenance.verify(output, initial, result["handover_sha256"], password, backend),
            lambda: maintenance.verify(output, pin, result["handover_sha256"], secrets.token_bytes(32), backend),
            lambda: maintenance.compact(source, output, pin, password, backend, reserve_bytes=0),
        ):
            rejected(action)
            assert inventory(root) == stable
        # Only the validation fixture scans/exports pending. The new module's
        # allowlist cannot invoke these operations or sign/broadcast a payment.
        pending_file = root / "pending.tx"
        target = output / "compacted.journal"
        recovered = call(5, [target, pool, genesis, domain, pending_file], target_pin)
        assert recovered["txid"] == payment["txid"] and pending_file.read_bytes() == payment_file.read_bytes()
        state = call(3, [target, pool, genesis, domain], target_pin)
        assert state["pending"] is True and state["available"] == 0 and state["receipt"] == target_pin
        assert source.read_bytes() == original

        for label, transport, expected_files in (
            ("lost-backup", LostBackupReply(executable, digest), {"backup.journal"}),
            ("lost-compaction", LostCompactionReply(executable, digest), {"backup.journal", "compacted.journal"}),
        ):
            dest = root / label
            rejected(lambda: maintenance.compact(source, dest, pin, password, transport, reserve_bytes=0))
            assert set(p.name for p in dest.iterdir()) == expected_files
            assert (dest / "backup.journal").read_bytes() == original and source.read_bytes() == original
            retained = inventory(dest)
            rejected(lambda: maintenance.compact(source, dest, pin, password, backend, reserve_bytes=0))
            assert inventory(dest) == retained
            rejected(lambda: maintenance.verify(dest, pin, "0" * 64, password, backend))

        partial = root / "partial-marker"
        write_new = maintenance.catalog.write_new
        def partial_marker(path, data):
            if path.name == maintenance.MANIFEST:
                write_new(path, data[:len(data) // 2])
                raise OSError("test_only_partial_handover_write")
            return write_new(path, data)
        with patch.object(maintenance.catalog, "write_new", side_effect=partial_marker):
            rejected(lambda: maintenance.compact(source, partial, pin, password, backend, reserve_bytes=0))
        assert set(p.name for p in partial.iterdir()) == maintenance.FILES
        partial_hash = hashlib.sha256((partial / maintenance.MANIFEST).read_bytes()).hexdigest()
        rejected(lambda: maintenance.verify(partial, pin, partial_hash, password, backend))
        assert source.read_bytes() == original

        # Tamper real target ciphertext, recompute ALL public hashes and rebind
        # the fixture's supplied manifest digest. Genuine AEAD still must refuse.
        raw = bytearray(target.read_bytes())
        raw[maintenance.catalog.HEADER + 100] ^= 1
        new_digest = hashlib.sha256(raw[maintenance.catalog.HEADER:-32]).digest()
        raw[-32:] = new_digest
        target.write_bytes(raw)
        forged = target_pin[:80] + new_digest.hex()
        manifest_path = output / maintenance.MANIFEST
        data = json.loads(manifest_path.read_bytes())
        data.update(target_receipt=forged, target_sha256=hashlib.sha256(raw).hexdigest())
        manifest_path.write_bytes(maintenance.catalog.canonical(data))
        forged_manifest_hash = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
        # Prove it reaches auth instead of merely failing a public-byte check.
        calls = []
        authenticate = maintenance.catalog.authenticate
        def observe_auth(*args):
            calls.append(args[1])
            return authenticate(*args)
        with patch.object(maintenance.catalog, "authenticate", side_effect=observe_auth):
            rejected(lambda: maintenance.verify(output, pin, forged_manifest_hash, password, backend))
        assert calls == [output / "backup.journal", target]
        assert source.read_bytes() == original
    print("Maintenance real-backend lifecycle passed: backup-first compaction, exact pending/reservation, independent verification, lost replies, partial marker and real AEAD refusal. No active-wallet switch or broadcast.")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("One trusted native wallet executable required")
    run(Path(sys.argv[1]))
