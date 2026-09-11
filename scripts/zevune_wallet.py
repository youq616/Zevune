#!/usr/bin/env python3
"""NO-FUNDS local wallet console. No networking, installations or auto-broadcast.

Requires Python 3.10+ and a locally built zevune-wallet-local binary. Passwords
and payment intent are sent only through the child's stdin, never argv or env.
Python/OS memory copies are not covered by a secure-erasure guarantee.
"""
from __future__ import annotations

import argparse
import getpass
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import struct
import subprocess
import sys
import warnings

MAGIC = b"ZVWCLI01"
MAX_REQUEST = 16_384
OPS = {"create": 0, "address": 1, "backup": 2, "status": 3,
       "prepare": 4, "pending": 5, "restore": 6, "init-test-ledger": 7}
COUNTS = {0: 1, 1: 2, 2: 2, 3: 4, 4: 9, 5: 5, 6: 2, 7: 3}


def encode_request(op: int, password: bytes, fields: list[str], pin: str | None = None) -> bytes:
    if op not in COUNTS or len(fields) != COUNTS[op] or not 16 <= len(password) <= 1024:
        raise ValueError("Invalid request bounds")
    if pin is not None and (op == 0 or re.fullmatch(r"[0-9a-f]{144}", pin) is None):
        raise ValueError("Invalid independently saved wallet receipt")
    data = bytearray(MAGIC + bytes([op]) + struct.pack(">H", len(password)) + password)
    data.append(int(pin is not None))
    if pin is not None:
        data.extend(bytes.fromhex(pin))
    data.append(len(fields))
    for field in fields:
        value = field.encode("utf-8")
        if not 1 <= len(value) <= 4096 or b"\0" in value:
            raise ValueError("Invalid request field")
        data.extend(struct.pack(">H", len(value)))
        data.extend(value)
    if len(data) > MAX_REQUEST:
        raise ValueError("Request too large")
    return bytes(data)


def hidden_password(confirm: bool) -> bytes:
    with warnings.catch_warnings():
        # getpass otherwise allows echoing fallback. Refuse that fallback.
        warnings.simplefilter("error", getpass.GetPassWarning)
        password = getpass.getpass("Wallet password (hidden): ")
        if confirm and password != getpass.getpass("Repeat password (hidden): "):
            raise ValueError("Passwords differ")
    result = password.encode("utf-8")
    if not 16 <= len(result) <= 1024:
        raise ValueError("Password must contain 16 to 1024 UTF-8 bytes; length alone is not strength")
    return result


def checked_address(text: str) -> str:
    if re.fullmatch(r"zvlab:[0-9a-f]{86}:[0-9a-f]{8}", text) is None:
        raise ValueError("Invalid experimental local address")
    _, body, checksum = text.split(":")
    expected = hashlib.sha256(b"ZEVUNE-LOCAL-ADDRESS\0\x01" + bytes.fromhex(body)).hexdigest()[:8]
    if checksum != expected:
        raise ValueError("Local address checksum mismatch")
    return text


def integer(text: str, maximum: int = (1 << 64) - 1) -> str:
    if re.fullmatch(r"0|[1-9][0-9]*", text) is None or not 0 <= int(text) <= maximum:
        raise ValueError("Expected an unsigned canonical integer")
    return text


def invoke(backend: Path, request: bytes, expected_sha: str | None = None) -> dict:
    backend = backend.absolute()
    metadata = backend.lstat()
    if not stat.S_ISREG(metadata.st_mode) or not 0 < metadata.st_size <= 512 * 1024 * 1024:
        raise ValueError("Backend must be a regular locally trusted executable")
    if expected_sha is not None:
        if re.fullmatch(r"[0-9a-f]{64}", expected_sha) is None:
            raise ValueError("Invalid executable digest")
        digest = hashlib.sha256()
        with backend.open("rb") as file:
            for chunk in iter(lambda: file.read(1024 * 1024), b""):
                digest.update(chunk)
        if digest.hexdigest() != expected_sha:
            raise ValueError("Backend digest mismatch")
    env = {key: value for key, value in os.environ.items()
           if key.upper() in {"SYSTEMROOT", "WINDIR", "TEMP", "TMP"}}
    env["RAYON_NUM_THREADS"] = "2"
    result = subprocess.run(
        [str(backend), "--no-real-funds"], input=request,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        cwd=backend.parent, env=env, timeout=300, check=False, shell=False,
    )
    if result.returncode != 0 or len(result.stdout) > 4096:
        raise RuntimeError("Wallet operation failed; saved payment state may need reconciliation")
    response = json.loads(result.stdout)
    if not isinstance(response, dict) or response.get("ok") is not True or response.get("scope") != "local_journal_only_no_funds":
        raise RuntimeError("Unexpected wallet response")
    return response


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-real-funds", action="store_true", required=True)
    default = Path(__file__).resolve().parent.parent / "integration/orchard/target/release"
    default /= "zevune-wallet-local.exe" if os.name == "nt" else "zevune-wallet-local"
    parser.add_argument("--backend", type=Path, default=default)
    parser.add_argument("--backend-sha256")
    parser.add_argument("--pin", help="Independently saved 144-character receipt; not a finality proof")
    commands = parser.add_subparsers(dest="command", required=True)
    for command in OPS:
        sub = commands.add_parser(command)
        sub.add_argument("wallet", type=Path)
        if command in {"backup", "restore", "prepare", "pending"}:
            sub.add_argument("output", type=Path)
        if command == "address":
            sub.add_argument("--index", default="0")
        if command in {"status", "prepare", "pending", "init-test-ledger"}:
            sub.add_argument("--journal", type=Path, required=True)
            sub.add_argument("--genesis", type=Path, required=True)
        if command in {"status", "prepare", "pending"}:
            sub.add_argument("--genesis-sha256", required=True)
    args = parser.parse_args(argv)
    try:
        fields = [str(args.wallet.absolute())]
        if args.command == "address":
            fields.append(integer(args.index, (1 << 32) - 1))
        if args.command in {"backup", "restore"}:
            fields.append(str(args.output.absolute()))
        if args.command in {"status", "prepare", "pending", "init-test-ledger"}:
            fields.extend([str(args.journal.absolute()), str(args.genesis.absolute())])
        if args.command in {"status", "prepare", "pending"}:
            if re.fullmatch(r"[0-9a-f]{64}", args.genesis_sha256) is None:
                raise ValueError("A pinned public genesis digest is required")
            fields.append(args.genesis_sha256)
        if args.command == "prepare":
            # Private intent is prompted, never placed in shell arguments/history.
            destination = checked_address(input("Local recipient address: "))
            amount = integer(input("Amount in integer test units: "))
            fee = integer(input("Fee in integer test units: "))
            expiry = integer(input("Expiry block height: "))
            if input("Type PREPARE to sign locally (no broadcast): ") != "PREPARE":
                raise ValueError("Payment not approved")
            fields.extend([destination, amount, fee, expiry])
        if args.command in {"prepare", "pending"}:
            fields.append(str(args.output.absolute()))
        print("NO-FUNDS local laboratory. Local journal state is not a consensus certificate.", file=sys.stderr)
        password = hidden_password(args.command == "create")
        request = encode_request(OPS[args.command], password, fields, args.pin)
        response = invoke(args.backend, request, args.backend_sha256)
        print(json.dumps(response, ensure_ascii=True, indent=2))
        return 0
    except (ValueError, OSError, RuntimeError, getpass.GetPassWarning, EOFError, subprocess.TimeoutExpired):
        print("Operation not completed. No automatic retry or reset. Check trusted local files and reconcile pending transactions before signing again.", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Interrupted; reconcile saved wallet state before signing again.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
