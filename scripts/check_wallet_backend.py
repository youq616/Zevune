#!/usr/bin/env python3
"""Exercise the Python/Rust boundary with ephemeral NO-FUNDS encrypted wallets.

This is a test runner, not an alternative password or real-wallet input method.
The executable is required. Missing prerequisites fail rather than skip tests.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import secrets
import sys
import tempfile

from zevune_wallet import checked_address, checked_prepare_timing, checked_recipient, checked_storage_status, encode_request, genesis_identity, invoke


def run(backend: Path) -> None:
    # Only a disposable test password; never accepted from command arguments/env.
    password = secrets.token_bytes(32)
    executable_hash = hashlib.sha256(backend.read_bytes()).hexdigest()
    with tempfile.TemporaryDirectory(prefix="zevune-python-rust-test-") as home:
        root = Path(home).absolute()
        owner, backup, restored = (str(root / name) for name in
                                   ("owner.zwallet", "backup.zwallet", "restored.zwallet"))
        created = invoke(backend, encode_request(0, password, [owner]), executable_hash)
        address = checked_address(created["address"])
        receipt = created["receipt"]
        saved = Path(owner).read_bytes()
        inspected = invoke(backend, encode_request(9, password, [owner], receipt), executable_hash)
        capacity = checked_storage_status(inspected)
        assert capacity["records_used"] == 1 and capacity["can_append"] is True
        assert inspected["result"] == "storage_inspected_not_synced"
        assert inspected["receipt"] == receipt
        assert all(k not in inspected for k in ("balance", "confirmed", "signing_domain"))
        assert Path(owner).read_bytes() == saved
        again = invoke(backend, encode_request(1, password, [owner, "0"], receipt))
        assert again["address"] == address
        invoke(backend, encode_request(2, password, [owner, backup], receipt))
        invoke(backend, encode_request(6, password, [backup, restored], receipt))
        assert Path(owner).read_bytes() == Path(backup).read_bytes() == Path(restored).read_bytes()
        recovered = invoke(backend, encode_request(1, password, [restored, "0"], receipt))
        assert recovered["address"] == address
        manifest, journal = str(root / "genesis.bin"), str(root / "pool.journal")
        initialized = invoke(backend, encode_request(7, password, [restored, journal, manifest]))
        status = invoke(backend, encode_request(3, password, [
            restored, journal, manifest, initialized["genesis_sha256"],
        ]))
        assert status["balance"] == status["available"] == 100_000
        assert status["height"] == 0 and status["pending"] is False
        pin = initialized["genesis_sha256"]
        identity = genesis_identity(Path(manifest), pin)
        assert all(status[k] == v for k, v in identity.items())
        receive = invoke(backend, encode_request(8, password, [restored, journal, manifest, pin, "0"]))
        checked_recipient(receive["address"], pin)
        assert receive["address"] == initialized["address"]
        assert receive["address_network_bound"] is True
        peer = str(root / "peer.zwallet")
        invoke(backend, encode_request(0, password, [peer]))
        peer_address = invoke(backend, encode_request(8, password, [peer, journal, manifest, pin, "3"]))["address"]
        checked_recipient(peer_address, pin)
        parts = peer_address.split(":")
        parts[1] = "02" * 32 if pin != "02" * 32 else "03" * 32
        parts[3] = hashlib.sha256(b"ZEVUNE-LOCAL-ADDRESS\0\x02" + bytes.fromhex(parts[1] + parts[2])).hexdigest()[:16]
        different_network = ":".join(parts)
        checked_address(different_network)  # valid checksum, but wrong network
        before = {name: Path(name).read_bytes() for name in [restored, journal, manifest]}
        output = str(root / "payment.bin")
        # Directly exercise the backend, bypassing all Python frontend checks.
        for invalid_address in [address, different_network, peer_address + ":extra"]:
            raw = encode_request(4, password, [restored, journal, manifest, pin,
                invalid_address, "25000", "1000", "10", output])
            try:
                invoke(backend, raw)
            except RuntimeError:
                pass
            else:
                raise AssertionError("Backend signed an invalid or wrong-network recipient")
            assert not Path(output).exists()
            assert all(Path(name).read_bytes() == data for name, data in before.items())
        # Canonical but impossible numbers are rejected by the backend itself,
        # before a wallet sync/prover/export. Frontend filtering is not authority.
        for amount, fee, expiry in [("0", "1", "10"), ("1", "0", "10"),
                ("1", "1", "0"), ("18446744073709551615", "1", "10"),
                ("9223372036854775807", "1", "10")]:
            request = encode_request(4, password, [restored, journal, manifest, pin,
                peer_address, amount, fee, expiry, output])
            try:
                invoke(backend, request)
            except RuntimeError:
                pass
            else:
                raise AssertionError("Backend accepted an invalid bounded intent")
            assert not Path(output).exists()
            assert all(Path(name).read_bytes() == data for name, data in before.items())
        payment = invoke(backend, encode_request(4, password, [restored, journal, manifest, pin,
            peer_address, "25000", "1000", "10", output]))
        timing = checked_prepare_timing(payment)
        assert timing["valid"] is True, "Discard invalid clock sample; no latency claim"
        raw_payment = Path(output).read_bytes()
        assert raw_payment[:8] == b"ZVORLAB2" and raw_payment[8:40].hex() == pin
        assert hashlib.sha256(raw_payment).hexdigest() == payment["txid"]
        assert all(payment[k] == v for k, v in identity.items())
        paid_backup = str(root / "paid-backup.zwallet")
        invoke(backend, encode_request(2, password, [restored, paid_backup], payment["receipt"]))
        recovered_output = str(root / "same-payment.bin")
        pending = invoke(backend, encode_request(5, password,
            [paid_backup, journal, manifest, pin, recovered_output], payment["receipt"]))
        assert "local_timing" not in pending, "Outbox export is not a second payment measurement"
        assert pending["txid"] == payment["txid"]
        assert Path(recovered_output).read_bytes() == raw_payment
        saved = Path(paid_backup).read_bytes()
        inspected = invoke(backend, encode_request(9, password, [paid_backup], pending["receipt"]))
        checked_storage_status(inspected)
        assert inspected["receipt"] == pending["receipt"]
        assert Path(paid_backup).read_bytes() == saved
        # LAB1 remains readable and explicitly unbound; no silent LAB2 downgrade.
        legacy = bytearray(Path(manifest).read_bytes())
        legacy[:8] = b"ZVTGEN01"
        del legacy[50:82]
        legacy_file = root / "legacy-public-genesis.bin"
        legacy_file.write_bytes(legacy)
        assert genesis_identity(legacy_file, hashlib.sha256(legacy).hexdigest())["signing_domain"] is None
        original = Path(restored).read_bytes()
        for raw in [encode_request(1, secrets.token_bytes(32), [restored, "0"]),
                    encode_request(1, password, [restored, "0"]) + b"\0"]:
            try:
                invoke(backend, raw)
            except RuntimeError:
                pass
            else:
                raise AssertionError("Invalid private-input frame was accepted")
        assert Path(restored).read_bytes() == original
    # Only an ephemeral test measurement, never addresses, receipts or secrets.
    print(json.dumps({"measurement_scope": "single_local_prepare_sample_not_end_to_end",
                      "samples": 1, "timing": timing}, sort_keys=True))
    print("Python/Rust local-wallet interop and domain-checked payment/outbox recovery passed; no broadcast, secrets or wallet artifacts retained.")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("A locally built test backend executable is required")
    run(Path(sys.argv[1]).absolute())
