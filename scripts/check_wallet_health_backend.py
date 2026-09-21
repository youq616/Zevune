#!/usr/bin/env python3
"""Real pinned Rust authentication and read-only wallet health/plan lifecycle.

No accepting doubles, payment broadcasts or retained private artifacts. Disk
samples come from the actual test directories. A reserve exceeding the actual
sample tests warnings, not an actual disk-full or quota enforcement scenario.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
import secrets
import sys
import tempfile

import wallet_health as health
from zevune_wallet import encode_request, invoke


def rejected(operation):
    try:
        operation()
    except (ValueError, RuntimeError, OSError):
        return
    raise AssertionError("invalid health inspection accepted")


def inventory(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() if p.is_file() else None for p in root.rglob("*")}


class ObservedBackend(health.Backend):
    """Still executes the real backend; asserts the diagnostic never writes."""
    calls = 0

    def call(self, op, password, paths, receipt):
        assert op == 9 and len(paths) == 1
        self.calls += 1
        return super().call(op, password, paths, receipt)


def run(executable):
    executable = executable.absolute()
    digest = hashlib.sha256(executable.read_bytes()).hexdigest()
    backend = ObservedBackend(executable, digest)
    password = secrets.token_bytes(32)
    with tempfile.TemporaryDirectory(prefix="zevune-wallet-health-") as temporary:
        root = Path(temporary).resolve()
        source, peer, pool, genesis = (root / n for n in ("source.wallet", "peer.wallet", "pool", "genesis"))
        target = root / "target"
        target.mkdir()

        def call(op, paths, pin=None):
            return invoke(executable, encode_request(op, password, [str(p) for p in paths], pin), digest)

        first = call(0, [source])["receipt"]
        before = inventory(root)
        report = health.inspect(source, first, password, backend, reserve_bytes=0)
        assert report["authenticated"] is True and report["read_only"] is True
        assert report["wallet_storage"]["records_used"] == 1
        assert report["source"]["disk"]["available_bytes"] >= 0
        assert report["operation_executed"] is False and report["space_reserved"] is False
        assert inventory(root) == before

        domain = call(7, [source, pool, genesis])["genesis_sha256"]
        synced = call(3, [source, pool, genesis, domain])["receipt"]
        call(0, [peer])
        recipient = call(8, [peer, pool, genesis, domain, "0"])["address"]
        payment_path = root / "payment.tx"
        payment = call(4, [source, pool, genesis, domain, recipient, "25000", "1000", "10", payment_path], synced)
        pin = payment["receipt"]
        before = inventory(root)
        for operation in health.OPERATIONS:
            report = health.inspect(source, pin, password, backend, reserve_bytes=0,
                                    operation=operation, target_directory=target)
            plan = report["plan"]
            assert plan["operation"] == operation and plan["source_retained"] is True
            assert plan["source_bytes_reclaimed"] == 0 and plan["destination_validated"] is False
            assert report["wallet_storage"]["records_used"] == 3
            assert report["real_funds_allowed"] is False and report["requires_rescan"] is True
            assert inventory(root) == before
        # Deterministic record warnings with actual authenticated generation3.
        report = health.inspect(source, pin, password, backend, reserve_bytes=0, warn_records=255)
        assert "wallet_record_headroom_low" in report["source"]["issues"]
        assert report["exit_code"] in (10, 20)
        report = health.inspect(source, pin, password, backend, reserve_bytes=0, saves=254)
        assert "wallet_record_limit" in report["source"]["issues"] and report["exit_code"] == 20
        # A real sampled filesystem cannot meet a cushion of its entire capacity
        # plus a data payload; no filler writes or test-only errno injection.
        reserve = health.probe(root)["total_bytes"]
        report = health.inspect(source, pin, password, backend, reserve_bytes=reserve)
        assert not report["source"]["budget"]["meets_byte_budget_at_observation"]
        assert report["exit_code"] in (10, 20)
        assert inventory(root) == before
        for operation in (
            lambda: health.inspect(source, first, password, backend, reserve_bytes=0),
            lambda: health.inspect(source, pin, secrets.token_bytes(32), backend, reserve_bytes=0),
            lambda: health.inspect(source, pin, password, health.Backend(executable, "0" * 64), reserve_bytes=0),
            lambda: health.inspect(source, pin, password, backend, reserve_bytes=0, operation="wallet-copy", target_directory=root / "missing"),
        ):
            rejected(operation)
            assert inventory(root) == before
        # Ordinary read-only authentication cannot rescan or change reservations.
        pending_path = root / "pending.tx"
        pending = call(5, [source, pool, genesis, domain, pending_path], pin)
        assert pending["txid"] == payment["txid"] and pending_path.read_bytes() == payment_path.read_bytes()
        status = call(3, [source, pool, genesis, domain], pin)
        assert status["pending"] is True and status["available"] == 0 and status["receipt"] == pin
        assert source.read_bytes() == before["source.wallet"]
        assert backend.calls >= 8
    print("Wallet health real-backend lifecycle passed: exact authenticated capacity, four read-only plans, actual disk samples, explicit record/reserve warnings, safe refusals and unchanged signed pending/reservation. No maintenance or disk filling performed.")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Exactly one trusted native wallet executable is required")
    run(Path(sys.argv[1]))
