#!/usr/bin/env python3
"""Required real Python/Rust backup-catalog interoperability test, NO-FUNDS only.

Uses temporary random passwords and actual encrypted wallets/proofs. No mock
backend, secrets in argv/env, networking, broadcast or retained test wallets.
Missing executable is failure, never an ignored test.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
import secrets
import sys
import tempfile

import wallet_backup as backup
from zevune_wallet import encode_request, invoke


def run(executable: Path):
    executable = executable.absolute()
    digest = hashlib.sha256(executable.read_bytes()).hexdigest()
    native = backup.Backend(executable, digest)
    password = secrets.token_bytes(32)
    with tempfile.TemporaryDirectory(prefix="zevune-backup-interop-") as home:
        root = Path(home).resolve()
        source, peer, ledger, genesis = (root / name for name in ("active.wallet", "peer.wallet", "pool", "genesis"))
        catalog = root / "catalog"
        def call(op, paths, pin=None):
            return invoke(executable, encode_request(op, password, [str(p) for p in paths], pin), digest)
        created = call(0, [source])
        first = created["receipt"]
        backup.init(catalog)
        original = source.read_bytes()
        result = backup.create(catalog, source, first, password, native)
        assert result["source_retained"] and result["requires_rescan"]
        assert source.read_bytes() == original
        backup.verify(catalog, first, password, native)
        backup.restore(catalog, root / "gen1-restored", first, password, native)
        assert (root / "gen1-restored").read_bytes() == original

        initialized = call(7, [source, ledger, genesis])
        domain = initialized["genesis_sha256"]
        status = call(3, [source, ledger, genesis, domain])
        second = status["receipt"]
        assert second != first and int(second[64:80], 16) == 2
        backup.create(catalog, source, second, password, native)
        call(0, [peer])
        receiver = call(8, [peer, ledger, genesis, domain, "0"])["address"]
        payment_file = root / "payment"
        payment = call(4, [source, ledger, genesis, domain, receiver, "25000", "1000", "10", payment_file], second)
        third = payment["receipt"]
        assert int(third[64:80], 16) == 3
        assert source.read_bytes() != original
        saved_pending = source.read_bytes()
        backup.create(catalog, source, third, password, native)
        info = backup.verify(catalog, third, password, native)
        assert info["wallet_storage"]["records_used"] == 3 and info["requires_rescan"] is True
        restored = root / "pending-restored"
        backup.restore(catalog, restored, third, password, native)
        assert restored.read_bytes() == saved_pending == source.read_bytes()
        exported = root / "pending-export"
        pending = call(5, [restored, ledger, genesis, domain, exported], third)
        assert exported.read_bytes() == payment_file.read_bytes()
        assert pending["txid"] == payment["txid"] and pending["receipt"] == third
        synced = call(3, [restored, ledger, genesis, domain], third)
        assert synced["pending"] is True and synced["available"] == 0
        assert synced["balance"] == 100_000

        listing = backup.list_versions(catalog)
        assert len(listing["versions"]) == 3
        assert {item["generation"] for item in listing["versions"]} == {1, 2, 3}
        assert all(item["metadata_complete"] and not item["authenticated"] for item in listing["versions"])
        assert listing["latest_not_inferred"] is True
        all_files = {p: p.read_bytes() for p in catalog.rglob("*") if p.is_file()}
        active_before = source.read_bytes()
        rejected = [
            lambda: backup.create(catalog, source, first, password, native),
            lambda: backup.create(catalog, source, third, password, native),
            lambda: backup.verify(catalog, third, secrets.token_bytes(32), native),
            lambda: backup.restore(catalog, restored, third, password, native),
            lambda: backup.restore(catalog, root / "wrong-password", third, secrets.token_bytes(32), native),
            lambda: backup.restore(catalog, catalog / "forbidden", third, password, native),
        ]
        for operation in rejected:
            try:
                operation()
            except (ValueError, RuntimeError, OSError):
                pass
            else:
                raise AssertionError("backup negative was accepted")
            assert source.read_bytes() == active_before
            assert {p: p.read_bytes() for p in catalog.rglob("*") if p.is_file()} == all_files
        assert not (root / "wrong-password").exists()
        # A forged metadata+hash change still cannot substitute for independent
        # receipt and native AEAD. Preserve the changed object instead of repair.
        target = catalog / backup.version_id(third) / "wallet.journal"
        damaged = bytearray(target.read_bytes())
        damaged[backup.HEADER + 80] ^= 1
        target.write_bytes(damaged)
        try:
            backup.verify(catalog, third, password, native)
        except (ValueError, RuntimeError, OSError):
            pass
        else:
            raise AssertionError("damaged backup accepted")
        assert target.read_bytes() == damaged
        assert source.read_bytes() == active_before
        assert not (catalog / "forbidden").exists()
    print("Wallet backup catalog real-backend lifecycle passed: 3 versions, exact pending bytes/reservation, six safe refusals, corruption refusal; no broadcast or wallet artifacts retained.")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Exactly one trusted local wallet executable is required")
    run(Path(sys.argv[1]))
