#!/usr/bin/env python3
"""Real native reconciliation lifecycle. No accepting verifier or production fault flag.

The original wallet generates test note openings; only this fixture selects the
03 active-profile marker BEFORE the unsynced source first scans any history.
Every ledger/header/record and checkpoint is created/verified by original Rust.
All signing belongs to this isolated test fixture, never the recovery module.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch

import wallet_reconcile as reconcile
from ledger_recovery_backend import Checkpoint, RecoveryBackend
from zevune_wallet import encode_request, invoke


def inventory(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() if p.is_file() else None for p in root.rglob("*")}


def reject(action):
    try:
        action()
    except (ValueError, RuntimeError, OSError):
        return
    raise AssertionError("unsafe reconciliation accepted")


def split_frames(raw):
    result = []
    while raw:
        assert len(raw) >= 4
        size = int.from_bytes(raw[:4], "big")
        assert 0 < size <= 2 * 1024 * 1024 and len(raw) >= size + 4
        result.append(raw[4:4 + size])
        raw = raw[4 + size:]
    return result


class LostCopyReply(reconcile.ReconcileBackend):
    def call(self, op, password, paths, receipt):
        result = super().call(op, password, paths, receipt)
        if op == 2:
            raise RuntimeError("test_only_lost_successful_copy_reply")
        return result


class LostPendingReply(reconcile.ReconcileBackend):
    def pending(self, password, paths, receipt):
        super().pending(password, paths, receipt)
        raise RuntimeError("test_only_lost_successful_export_reply")


def run(wallet, worker, recovery):
    wallet, worker, recovery = (p.resolve(strict=True) for p in (wallet, worker, recovery))
    digests = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in (wallet, worker, recovery)}
    backend = reconcile.ReconcileBackend(wallet, digests[wallet])
    native = RecoveryBackend(recovery, digests[recovery])
    password = secrets.token_bytes(32)
    start = time.monotonic()
    completed = []
    def progress(stage):
        print("NATIVE_RECONCILIATION_STAGE " + stage, flush=True)
    progress("start")
    with tempfile.TemporaryDirectory(prefix="zevune-reconcile-native-") as temporary:
        root = Path(temporary).resolve()
        source, generator, peer = (root / name for name in ("source.wallet", "generator.wallet", "peer.wallet"))
        genesis2, genesis3 = root / "original.genesis", root / "active.genesis"
        journal = root / "active"

        def wallet_call(op, paths, pin=None):
            return invoke(wallet, encode_request(op, password, [str(p) for p in paths], pin), digests[wallet])

        progress("creating_wallets_and_history")
        initial = wallet_call(0, [source])["receipt"]
        wallet_call(2, [source, generator], initial)
        wallet_call(7, [generator, root / "legacy", genesis2])
        public = genesis2.read_bytes()
        assert public[:8] == b"ZVTGEN02"
        genesis3.write_bytes(b"ZVTGEN03" + public[8:])
        domain = hashlib.sha256(genesis3.read_bytes()).hexdigest()

        def worker_call(mode, path, operations):
            requests = [b"ZVPLREQ1" + i.to_bytes(8, "big") + bytes([op]) + body
                        for i, (op, body) in enumerate(operations, 1)]
            framed = b"".join(len(req).to_bytes(4, "big") + req for req in requests)
            process = subprocess.run([str(worker), mode, str(path), str(genesis3), domain],
                                     input=framed, capture_output=True, timeout=60)
            assert process.returncode == 0 and not process.stderr, "native worker failed"
            frames = split_frames(process.stdout)
            expected = b"ZEVUNE-POOL-IPC-4:zevune-orchard-lab-1:16:28134:selection-64:active-segments-1:1000000:1073741824"
            assert frames[0] == b"ZVPLHEL1" + hashlib.sha256(expected).digest()
            assert len(frames) == len(requests) + 1
            for i, (request, response) in enumerate(zip(requests, frames[1:]), 1):
                assert len(response) == 145 and response[:8] == b"ZVPLRSP1"
                assert response[8:16] == i.to_bytes(8, "big") and response[16] == 0, "native worker refused"
                assert response[17:49] == hashlib.sha256(request).digest()
            return frames[-1][49:]

        def checkpoint(path, state):
            out = subprocess.run([str(recovery), "checkpoint-active", "--no-real-funds", "--source", str(path),
                                  "--genesis", str(genesis3), "--genesis-sha256", domain,
                                  "--height", str(int.from_bytes(state[:8], "big")), "--app-hash", state[8:40].hex()],
                                 capture_output=True, timeout=60)
            assert out.returncode == 0 and not out.stderr, "native checkpoint failed"
            result = json.loads(out.stdout)
            assert result["replay_verified"] is True and result["real_funds_allowed"] is False
            Checkpoint.parse(result["checkpoint"])
            return result["checkpoint"]

        state0 = worker_call("create", journal, [(0, b"")])
        pin0 = checkpoint(journal, state0)
        old_pin = wallet_call(3, [source, journal, genesis3, domain], initial)["receipt"]
        empty_bytes = source.read_bytes()
        wallet_call(0, [peer])
        recipient = wallet_call(8, [peer, journal, genesis3, domain, "0"])["address"]
        payment_file = root / "original.tx"
        progress("prepare_real_payment")
        paid = wallet_call(4, [source, journal, genesis3, domain, recipient, "60000", "1000", "10", payment_file], old_pin)
        tip, original, signed = paid["receipt"], source.read_bytes(), payment_file.read_bytes()
        ledger_before = inventory(journal)
        assert int(old_pin[64:80], 16) == 2 and int(tip[64:80], 16) == 3
        progress("discover_authenticated_ancestor")
        assert reconcile.discover(source, old_pin, password, backend)["receipt"] == tip

        def recover(label, *, src=source, ancestor=old_pin, passcode=password, transport=backend,
                    ledger_path=journal, ledger_pin=pin0, domain_pin=domain):
            return reconcile.recover(src, root / label, ancestor, passcode, transport, journal=ledger_path,
                                     checkpoint=ledger_pin, genesis=genesis3, genesis_sha256=domain_pin,
                                     recovery_backend=native, reserve_bytes=0)

        progress("recover_exact_pending")
        result = recover("pending")
        assert result["result"] == "pending_recovered_not_broadcast" and result["txid"] == paid["txid"]
        assert result["retry_authorized"] is False and result["broadcast_status"] == "unknown"
        assert (root / "pending/pending.tx").read_bytes() == signed
        assert (root / "pending/wallet.journal").read_bytes() == original
        assert source.read_bytes() == original and inventory(journal) == ledger_before
        completed.append("ancestor_authenticated_exact_pending_recovered")
        progress("ancestor_authenticated_exact_pending_recovered")

        retained = inventory(root / "pending")
        reject(lambda: recover("pending"))
        assert inventory(root / "pending") == retained
        malformed_pin = bytearray.fromhex(pin0)
        malformed_pin[48] ^= 1
        for label, parameters in (("wrong-password", {"passcode": secrets.token_bytes(32)}),
                                   ("wrong-ancestor", {"ancestor": old_pin[:80] + "8" * 64}),
                                   ("wrong-genesis", {"domain_pin": "0" * 64}),
                                   ("wrong-checkpoint", {"ledger_pin": malformed_pin.hex()})):
            reject(lambda label=label, parameters=parameters: recover(label, **parameters))
            assert not (root / label).exists()
        assert source.read_bytes() == original and inventory(journal) == ledger_before
        completed.append("wrong_inputs_refused_without_output")
        progress("wrong_inputs_refused_without_output")

        forged = bytearray(original)
        offset = reconcile.files.HEADER + 2 * reconcile.files.RECORD
        forged[offset + 100] ^= 1
        forged[-32:] = hashlib.sha256(forged[offset:-32]).digest()
        forged_file = root / "forged.wallet"
        forged_file.write_bytes(forged)
        assert reconcile.public_tip(bytes(forged), old_pin) != tip
        reject(lambda: reconcile.discover(forged_file, old_pin, password, backend))
        assert forged_file.read_bytes() == forged
        completed.append("rehashed_ciphertext_refused_by_native_authentication")
        progress("rehashed_ciphertext_refused_by_native_authentication")

        for label, transport, has_transaction in (("lost-copy", LostCopyReply(wallet, digests[wallet]), False),
                                                  ("lost-export", LostPendingReply(wallet, digests[wallet]), True)):
            reject(lambda: recover(label, transport=transport))
            out = root / label
            assert not (out / reconcile.MARKER).exists()
            assert (out / "wallet.journal").read_bytes() == original
            if has_transaction:
                assert (out / "pending.tx").read_bytes() == signed
            before = inventory(out)
            reject(lambda: recover(label))
            assert inventory(out) == before and source.read_bytes() == original
        completed.append("lost_native_replies_retain_exact_outputs_no_retry")
        progress("lost_native_replies_retain_exact_outputs_no_retry")

        # Controlled marker write fault, after real wallet copy/scan/export.
        # Never substitute an accepting backend or delete a completed output.
        write_new = reconcile.files.write_new
        def partial_report(path, raw):
            if path.name == reconcile.MARKER:
                write_new(path, raw[:len(raw) // 2])
                raise OSError("test_only_partial_report")
            return write_new(path, raw)
        with patch.object(reconcile.files, "write_new", side_effect=partial_report):
            reject(lambda: recover("partial-report"))
        partial = root / "partial-report"
        assert (partial / "wallet.journal").read_bytes() == original
        assert (partial / "pending.tx").read_bytes() == signed
        assert set(p.name for p in partial.iterdir()) == {"wallet.journal", "pending.tx", reconcile.MARKER}
        try:
            json.loads((partial / reconcile.MARKER).read_bytes())
        except json.JSONDecodeError:
            pass
        else:
            raise AssertionError("partial marker was treated as complete")
        retained = inventory(partial)
        reject(lambda: recover("partial-report"))
        assert inventory(partial) == retained and source.read_bytes() == original
        assert inventory(journal) == ledger_before
        completed.append("partial_report_preserves_signed_output_and_refuses_resume")
        progress("partial_report_preserves_signed_output_and_refuses_resume")

        empty = root / "empty.wallet"
        empty.write_bytes(empty_bytes)
        result = recover("empty-result", src=empty)
        assert result["result"] == "no_pending_not_settlement_proof" and result["txid"] is None
        assert not (root / "empty-result/pending.tx").exists() and empty.read_bytes() == empty_bytes
        completed.append("empty_wallet_not_misreported_as_paid")
        progress("empty_wallet_not_misreported_as_paid")

        body = (1).to_bytes(8, "big") + bytes([1]) * 32 + (1).to_bytes(2, "big") + len(signed).to_bytes(4, "big") + signed
        state1 = worker_call("open", journal, [(2, body), (3, hashlib.sha256(body).digest())])
        pin1 = checkpoint(journal, state1)
        ledger_after = inventory(journal)
        included = recover("included", ledger_pin=pin1)
        assert included["result"] == "no_pending_not_settlement_proof" and included["retry_authorized"] is False
        assert not (root / "included/pending.tx").exists()
        copied = root / "included/wallet.journal"
        status = wallet_call(3, [copied, journal, genesis3, domain], included["copy_receipt"])
        assert status["pending"] is False and status["available"] == 39000
        assert source.read_bytes() == original and inventory(journal) == ledger_after
        completed.append("included_copy_scans_without_mutating_original_or_claiming_finality")
        progress("included_copy_scans_without_mutating_original_or_claiming_finality")

        fork = root / "expired-history"
        fork0 = worker_call("create", fork, [(0, b"")])
        forkpin = checkpoint(fork, fork0)
        copied_before = copied.read_bytes()
        reject(lambda: recover("rollback-refused", src=copied, ledger_path=fork, ledger_pin=forkpin))
        assert copied.read_bytes() == copied_before
        assert (root / "rollback-refused/wallet.journal").read_bytes() == copied_before
        assert not (root / "rollback-refused" / reconcile.MARKER).exists()
        completed.append("rollback_rejected_with_unmodified_source_and_retained_copy")
        progress("rollback_rejected_with_unmodified_source_and_retained_copy")

        # Same-height fork is independently valid, but not the copy's saved history.
        block = (1).to_bytes(8, "big") + bytes([4]) * 32 + bytes(2)
        fork1 = worker_call("open", fork, [(2, block), (3, hashlib.sha256(block).digest())])
        forkpin1 = checkpoint(fork, fork1)
        assert Checkpoint.parse(forkpin1).height == Checkpoint.parse(pin1).height
        assert Checkpoint.parse(forkpin1).app_hash != Checkpoint.parse(pin1).app_hash
        fork1_before = inventory(fork)
        reject(lambda: recover("same-height-fork", src=copied, ledger_path=fork, ledger_pin=forkpin1))
        assert copied.read_bytes() == copied_before
        assert (root / "same-height-fork/wallet.journal").read_bytes() == copied_before
        assert not (root / "same-height-fork" / reconcile.MARKER).exists()
        assert inventory(fork) == fork1_before
        completed.append("individually_valid_same_height_fork_refused")
        progress("individually_valid_same_height_fork_refused")

        operations = []
        for height in range(2, 12):
            height_bytes = height.to_bytes(8, "big")
            block = height_bytes + height_bytes + bytes([2]) * 24 + bytes(2)
            operations.extend([(2, block), (3, hashlib.sha256(block).digest())])
        state11 = worker_call("open", fork, operations)
        pin11 = checkpoint(fork, state11)
        fork_before = inventory(fork)
        expired = recover("expired", ledger_path=fork, ledger_pin=pin11)
        assert expired["result"] == "no_pending_not_settlement_proof" and expired["retry_authorized"] is False
        assert expired["broadcast_status"] == "unknown" and not (root / "expired/pending.tx").exists()
        assert source.read_bytes() == original and inventory(fork) == fork_before
        completed.append("expired_copy_not_confused_with_confirmed_or_retry_permission")
        progress("expired_copy_not_confused_with_confirmed_or_retry_permission")
    assert not root.exists()
    assert all(hashlib.sha256(path.read_bytes()).hexdigest() == digest for path, digest in digests.items())
    print(json.dumps({"native_reconciliation_checks_completed": completed, "case_count": len(completed),
                      "elapsed_seconds": round(time.monotonic() - start, 3), "fixtures_removed": True,
                      "real_funds_allowed": False}, sort_keys=True))


if __name__ == "__main__":
    if len(sys.argv) != 4:
        raise SystemExit("Three trusted native executables required: wallet, worker, recovery")
    run(*(Path(value) for value in sys.argv[1:]))
