#!/usr/bin/env python3
"""Real encrypted-wallet portable migration and refusal coverage, no broadcasts.

This test calls the actual pinned Rust backend. No accepting doubles, retained
wallet artifacts or secret-bearing output. A missing executable is failure.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
import secrets
import sys
import tempfile

import wallet_archive as archive
import wallet_backup as catalog
from zevune_wallet import encode_request, invoke


def files(root: Path):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def rejected(operation):
    try:
        operation()
    except (ValueError, RuntimeError, OSError):
        return
    raise AssertionError("unsafe archive operation accepted")


def run(executable: Path):
    executable = executable.absolute()
    digest = hashlib.sha256(executable.read_bytes()).hexdigest()
    backend = archive.Backend(executable, digest)
    password = secrets.token_bytes(32)
    with tempfile.TemporaryDirectory(prefix="zevune-archive-interop-") as temporary:
        root = Path(temporary).resolve()
        source, peer, pool, genesis = (root / name for name in ("source.wallet", "peer.wallet", "pool", "genesis"))
        origin, destination = root / "origin", root / "destination"
        catalog.init(origin)
        catalog.init(destination)

        def call(op, paths, pin=None):
            return invoke(executable, encode_request(op, password, [str(p) for p in paths], pin), digest)

        first = call(0, [source])["receipt"]
        catalog.create(origin, source, first, password, backend)
        initialized = call(7, [source, pool, genesis])
        domain = initialized["genesis_sha256"]
        second = call(3, [source, pool, genesis, domain])["receipt"]
        call(0, [peer])
        recipient = call(8, [peer, pool, genesis, domain, "0"])["address"]
        payment_file = root / "payment.tx"
        payment = call(4, [source, pool, genesis, domain, recipient, "25000", "1000", "10", payment_file], second)
        pin = payment["receipt"]
        assert int(pin[64:80], 16) == 3
        original_wallet = source.read_bytes()
        catalog.create(origin, source, pin, password, backend)
        origin_before = files(origin)

        # Both the pre-network generation1 and pending generation3 are explicit
        # versions; no "latest" selection, reinterpretation or broadcast occurs.
        for retained in (first, pin):
            package = root / (catalog.version_id(retained) + ".zvbackup")
            result = archive.export_archive(origin, package, retained, password, backend)
            sha = result["archive_sha256"]
            assert sha == hashlib.sha256(package.read_bytes()).hexdigest()
            assert result["authenticated"] is True and result["requires_rescan"] is True
            inspected = archive.inspect_archive(package, retained, sha)
            assert inspected["authenticated"] is False and inspected["latest_not_inferred"] is True
            imported = archive.import_archive(destination, package, retained, sha, password, backend)
            assert imported["authenticated"] is True and imported["active_wallet_replaced"] is False
            catalog.verify(destination, retained, password, backend)
            assert files(origin) == origin_before
            assert source.read_bytes() == original_wallet
        assert len(catalog.list_versions(destination)["versions"]) == 2

        restored = root / "restored.wallet"
        catalog.restore(destination, restored, pin, password, backend)
        assert restored.read_bytes() == original_wallet
        pending_file = root / "restored.tx"
        pending = call(5, [restored, pool, genesis, domain, pending_file], pin)
        assert pending["txid"] == payment["txid"] and pending["receipt"] == pin
        assert pending_file.read_bytes() == payment_file.read_bytes()
        status = call(3, [restored, pool, genesis, domain], pin)
        assert status["pending"] is True and status["available"] == 0 and status["balance"] == 100000
        assert restored.read_bytes() == original_wallet

        package = root / (catalog.version_id(pin) + ".zvbackup")
        raw = package.read_bytes()
        sha = hashlib.sha256(raw).hexdigest()
        twin = root / "twin.zvbackup"
        assert archive.export_archive(origin, twin, pin, password, backend)["archive_sha256"] == sha
        assert twin.read_bytes() == raw  # deterministic container; ciphertext unchanged
        before = files(destination)
        for operation in (
            lambda: archive.export_archive(origin, package, pin, password, backend),
            lambda: archive.export_archive(origin, root / "bad-password.zvbackup", pin, secrets.token_bytes(32), backend),
            lambda: archive.export_archive(origin, origin / "illegal", pin, password, backend),
            lambda: archive.import_archive(destination, package, pin, sha, password, backend),
            lambda: archive.import_archive(destination, package, pin, "0" * 64, password, backend),
            lambda: archive.import_archive(destination, package, second, sha, password, backend),
        ):
            rejected(operation)
            assert files(origin) == origin_before and files(destination) == before
            assert source.read_bytes() == original_wallet and package.read_bytes() == raw
        assert not (root / "bad-password.zvbackup").exists()
        assert not (origin / "illegal").exists()

        # An import authentication failure keeps only an incomplete, encrypted
        # version. It never publishes a manifest or overwrites on a second try.
        failed = root / "failed"
        catalog.init(failed)
        rejected(lambda: archive.import_archive(failed, package, pin, sha, secrets.token_bytes(32), backend))
        partial = failed / catalog.version_id(pin)
        assert {p.name for p in partial.iterdir()} == {"wallet.journal"}
        assert (partial / "wallet.journal").read_bytes() == original_wallet
        assert catalog.list_versions(failed)["versions"][0]["metadata_complete"] is False
        rejected(lambda: archive.import_archive(failed, package, pin, sha, password, backend))
        assert {p.name for p in partial.iterdir()} == {"wallet.journal"}

        # A self-consistent public hash chain still does not authenticate AEAD.
        # Corrupt the last encrypted record and recompute ONLY public checksums.
        damaged = bytearray(original_wallet)
        start = catalog.HEADER + 2 * catalog.RECORD
        damaged[start + 80] ^= 1
        damaged[-32:] = hashlib.sha256(damaged[start:-32]).digest()
        forged_pin = pin[:80] + bytes(damaged[-32:]).hex()
        summary = catalog.wallet_bytes_summary(bytes(damaged), forged_pin)
        metadata = catalog.canonical(archive.manifest_for(forged_pin, summary))
        bad_raw = archive.FRAME.pack(archive.MAGIC, len(metadata), len(damaged)) + metadata + damaged
        forged = root / "forged.zvbackup"
        forged.write_bytes(bad_raw)
        forged_sha = hashlib.sha256(bad_raw).hexdigest()
        assert archive.inspect_archive(forged, forged_pin, forged_sha)["authenticated"] is False
        rejected(lambda: archive.import_archive(failed, forged, forged_pin, forged_sha, password, backend))
        assert not (failed / catalog.version_id(forged_pin) / "MANIFEST.json").exists()
        assert source.read_bytes() == original_wallet and package.read_bytes() == raw
        assert files(origin) == origin_before and files(destination) == before
    print("Wallet archive real-backend lifecycle passed: two explicit versions, deterministic ciphertext container, exact restored pending bytes and reservation, safe refusals, incomplete import retained and AEAD forgery rejected. No broadcast or retained wallet artifacts.")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Exactly one trusted native wallet executable is required")
    run(Path(sys.argv[1]))
