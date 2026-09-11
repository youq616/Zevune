#!/usr/bin/env python3
"""Exercise the Python/Rust boundary with ephemeral NO-FUNDS encrypted wallets.

This is a test runner, not an alternative password or real-wallet input method.
The executable is required. Missing prerequisites fail rather than skip tests.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
import secrets
import sys
import tempfile

from zevune_wallet import checked_address, encode_request, invoke


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
    print("Python/Rust local-wallet interop passed; no secrets or wallet artifacts retained.")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("A locally built test backend executable is required")
    run(Path(sys.argv[1]).absolute())
