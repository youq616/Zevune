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
       "prepare": 4, "pending": 5, "restore": 6, "init-test-ledger": 7,
       "network-address": 8, "storage": 9, "compact": 10}
COUNTS = {0: 1, 1: 2, 2: 2, 3: 4, 4: 9, 5: 5, 6: 2, 7: 3, 8: 5, 9: 1, 10: 2}


def encode_request(op: int, password: bytes, fields: list[str], pin: str | None = None) -> bytes:
    if op not in COUNTS or len(fields) != COUNTS[op] or not 16 <= len(password) <= 1024:
        raise ValueError("Invalid request bounds")
    if pin is not None and (op == 0 or re.fullmatch(r"[0-9a-f]{144}", pin) is None):
        raise ValueError("Invalid independently saved wallet receipt")
    if op == 10 and pin is None:
        raise ValueError("Compaction requires the exact current source receipt")
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
    """Presentation/checksum only; Rust separately checks the Orchard receiver."""
    if not isinstance(text, str):
        raise ValueError("Invalid address type")
    if re.fullmatch(r"zvlab:[0-9a-f]{86}:[0-9a-f]{8}", text):
        _, body, checksum = text.split(":")
        payload = b"ZEVUNE-LOCAL-ADDRESS\0\x01" + bytes.fromhex(body)
        length = 8
    elif re.fullmatch(r"zvlab2:[0-9a-f]{64}:[0-9a-f]{86}:[0-9a-f]{16}", text):
        _, domain, body, checksum = text.split(":")
        if domain == "0" * 64:
            raise ValueError("Zero payment domain")
        payload = b"ZEVUNE-LOCAL-ADDRESS\0\x02" + bytes.fromhex(domain + body)
        length = 16
    else:
        raise ValueError("Invalid experimental local address")
    if hashlib.sha256(payload).hexdigest()[:length] != checksum:
        raise ValueError("Local address checksum mismatch")
    return text


class NetworkMismatch(ValueError):
    """No recipient details in diagnostics."""


def checked_recipient(text: str, expected_domain: str | None) -> str:
    checked_address(text)
    actual = text.split(":")[1] if text.startswith("zvlab2:") else None
    if actual != expected_domain:
        raise NetworkMismatch("Recipient belongs to another payment domain or legacy profile")
    return text


def genesis_identity(file: Path, expected_sha: str) -> dict:
    """Read-only public-frame precheck; not note verification or chain finality.

    The independently retained pin, not the recipient or a remote reply, selects
    the identity. The Rust backend independently decodes the complete manifest.
    """
    if re.fullmatch(r"[0-9a-f]{64}", expected_sha) is None or expected_sha == "0" * 64:
        raise ValueError("A nonzero independently pinned genesis digest is required")
    before = file.lstat()
    if (not stat.S_ISREG(before.st_mode) or not 165 <= before.st_size <= 1922
            or getattr(before, "st_file_attributes", 0) & 0x400):
        raise ValueError("Invalid public genesis file")
    with file.open("rb") as stream:
        opened = os.fstat(stream.fileno())
        if not os.path.samestat(before, opened) or not stat.S_ISREG(opened.st_mode):
            raise ValueError("Genesis file changed")
        raw = stream.read(1923)
    current = file.lstat()
    if (not os.path.samestat(before, current) or current.st_size != before.st_size
            or current.st_mtime_ns != before.st_mtime_ns
            or hashlib.sha256(raw).hexdigest() != expected_sha):
        raise ValueError("Genesis pin or file identity mismatch")
    magic = raw[:8]
    if magic not in {b"ZVTGEN01", b"ZVTGEN02", b"ZVTGEN03"}:
        raise ValueError("Unknown genesis profile")
    # 03 selects fixed active storage while retaining the LAB2 payment format.
    # Its complete pinned manifest gives it a different signing domain from 02.
    bound = magic in {b"ZVTGEN02", b"ZVTGEN03"}
    count = int.from_bytes(raw[48:50], "big")
    header = 82 if bound else 50
    if (not 1 <= count <= 16 or len(raw) != header + 115 * count
            or raw[8:40] != hashlib.sha256(b"zevune-orchard-lab-1").digest()
            or int.from_bytes(raw[40:48], "big") != 100_000
            or (bound and raw[50:82] == bytes(32))):
        raise ValueError("Malformed genesis identity")
    remaining = 100_000
    for offset in range(header, len(raw), 115):
        value = int.from_bytes(raw[offset + 43:offset + 51], "big")
        if not 1 <= value <= remaining:
            raise ValueError("Invalid public test allocation")
        remaining -= value
    if remaining:
        raise ValueError("Invalid public test supply")
    return {"payment_profile": "LAB2" if bound else "LAB1",
            "signing_domain": expected_sha if bound else None,
            "genesis_sha256": expected_sha}


def integer(text: str, maximum: int = (1 << 64) - 1) -> str:
    if re.fullmatch(r"0|[1-9][0-9]*", text) is None or not 0 <= int(text) <= maximum:
        raise ValueError("Expected an unsigned canonical integer")
    return text


def checked_payment_numbers(amount: str, fee: str, expiry: str) -> tuple[str, str, str]:
    """Cheap public bounds only. Rust checks spendability against scanned state."""
    values = tuple(integer(value) for value in (amount, fee, expiry))
    a, f, e = map(int, values)
    if a == 0 or f == 0 or e == 0 or a + f > (1 << 63) - 1:
        raise ValueError("Invalid bounded test payment intent")
    return values


PREPARE_STAGES = {"setup_and_sync", "intent_preflight", "prover_parameters",
                  "prove_sign_verify_persist", "export"}


def checked_prepare_timing(response: dict) -> dict:
    """Validate local diagnostics, never a payment or confirmation certificate.

    Invalid clock samples explicitly carry nulls. Do not turn them into zeroes,
    latency promises or a reason to prepare another payment.
    """
    timing = response.get("local_timing")
    if (not isinstance(timing, dict)
            or set(timing) != {"format", "scope", "unit", "valid", "stages", "total"}
            or timing["format"] != "zevune-prepare-timing-1"
            or timing["scope"] != "local_prepare_not_finality"
            or timing["unit"] != "microseconds" or type(timing["valid"]) is not bool
            or not isinstance(timing["stages"], dict)
            or set(timing["stages"]) != PREPARE_STAGES):
        raise RuntimeError("Unexpected local timing schema; reconcile saved payment state")
    values = [*timing["stages"].values(), timing["total"]]
    if timing["valid"]:
        if any(type(v) is not int or not 0 <= v <= (1 << 64) - 1 for v in values):
            raise RuntimeError("Invalid timing values; reconcile saved payment state")
        remainder = timing["total"] - sum(timing["stages"].values())
        if not 0 <= remainder < len(PREPARE_STAGES):
            raise RuntimeError("Inconsistent stage timing; reconcile saved payment state")
    elif any(v is not None for v in values):
        raise RuntimeError("Invalid clock sample must be explicit; reconcile saved payment state")
    return timing


def checked_storage_status(response: dict) -> dict:
    """A validated bounded local-file report, never an up-to-date balance claim."""
    status = response.get("wallet_storage")
    fields = {"format", "records_used", "records_remaining", "max_records",
              "file_bytes", "max_file_bytes", "can_append"}
    if (not isinstance(status, dict) or set(status) != fields
            or status["format"] != "zevune-wallet-capacity-1"):
        raise RuntimeError("Unexpected wallet capacity schema")
    for key in fields - {"format", "can_append"}:
        if type(status[key]) is not int:
            raise RuntimeError("Invalid wallet capacity value")
    # These are existing ZVWJNL01 bounds, not configurable limits or repair hints.
    header, record, limit = 72, 32_948, 256
    used = status["records_used"]
    remaining = status["records_remaining"]
    if (status["max_records"] != limit or not 1 <= used <= limit
            or remaining != limit - used
            or status["file_bytes"] != header + used * record
            or status["max_file_bytes"] != header + limit * record
            or type(status["can_append"]) is not bool
            or status["can_append"] != (remaining > 0)):
        raise RuntimeError("Inconsistent wallet capacity report")
    return status



def checked_compaction(response: dict, expected_source: str) -> dict:
    """Verify handover diagnostics; this is not a signed ancestry certificate."""
    if (not isinstance(expected_source, str)
            or re.fullmatch(r"[0-9a-f]{144}", expected_source) is None
            or not 1 <= int(expected_source[64:80], 16) <= 256):
        raise RuntimeError("Invalid source receipt; inspect copies before further use")
    target = response.get("receipt")
    if (response.get("result") != "compacted_copy_not_synced"
            or response.get("source_receipt") != expected_source
            or response.get("source_retained") is not True
            or response.get("requires_rescan") is not True
            or any(k in response for k in ("balance", "available", "confirmed", "txid"))
            or not isinstance(target, str) or re.fullmatch(r"[0-9a-f]{144}", target) is None
            or target[:64] == expected_source[:64]
            or int(target[64:80], 16) != 1):
        raise RuntimeError("Unexpected compaction handover; inspect copies before further use")
    capacity = checked_storage_status(response)
    if capacity["records_used"] != 1:
        raise RuntimeError("Unexpected target capacity; inspect copies before further use")
    return response

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
        if command in {"backup", "restore", "prepare", "pending", "compact"}:
            sub.add_argument("output", type=Path)
        if command in {"address", "network-address"}:
            sub.add_argument("--index", default="0")
        if command in {"status", "prepare", "pending", "init-test-ledger", "network-address"}:
            sub.add_argument("--journal", type=Path, required=True)
            sub.add_argument("--genesis", type=Path, required=True)
        if command in {"status", "prepare", "pending", "network-address"}:
            sub.add_argument("--genesis-sha256", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "compact":
            # Validate before asking for a password or starting any child. No
            # overwriting, in-place truncation, automatic retry or file deletion.
            if args.pin is None or re.fullmatch(r"[0-9a-f]{144}", args.pin) is None:
                raise ValueError("Compaction requires the exact current source receipt")
            if not 1 <= int(args.pin[64:80], 16) <= 256:
                raise ValueError("Invalid source generation")
            try:
                args.output.lstat()
            except FileNotFoundError:
                pass
            else:
                raise ValueError("Compaction target must not exist")
            print("Create a new wallet copy; retain the source OFFLINE. Never operate both copies. Save the NEW receipt and rescan before spending.", file=sys.stderr)
            if input("Type COMPACT to create the new copy without changing the source: ") != "COMPACT":
                raise ValueError("Compaction not approved")
        identity = None
        fields = [str(args.wallet.absolute())]
        if args.command == "address":
            fields.append(integer(args.index, (1 << 32) - 1))
        if args.command in {"backup", "restore", "compact"}:
            fields.append(str(args.output.absolute()))
        if args.command in {"status", "prepare", "pending", "init-test-ledger", "network-address"}:
            fields.extend([str(args.journal.absolute()), str(args.genesis.absolute())])
        if args.command in {"status", "prepare", "pending", "network-address"}:
            if re.fullmatch(r"[0-9a-f]{64}", args.genesis_sha256) is None:
                raise ValueError("A pinned public genesis digest is required")
            fields.append(args.genesis_sha256)
            identity = genesis_identity(args.genesis.absolute(), args.genesis_sha256)
            print("Pinned local payment network: " + json.dumps(identity, sort_keys=True), file=sys.stderr)
        if args.command == "network-address":
            fields.append(integer(args.index, (1 << 32) - 1))
        if args.command == "prepare":
            # Private intent is prompted, never placed in shell arguments/history.
            destination = checked_recipient(input("Recipient address for the displayed network: "), identity["signing_domain"])
            amount = integer(input("Amount in integer test units: "))
            fee = integer(input("Fee in integer test units: "))
            expiry = integer(input("Expiry block height: "))
            amount, fee, expiry = checked_payment_numbers(amount, fee, expiry)
            if input("Type PREPARE to sign locally (no broadcast): ") != "PREPARE":
                raise ValueError("Payment not approved")
            fields.extend([destination, amount, fee, expiry])
        if args.command in {"prepare", "pending"}:
            fields.append(str(args.output.absolute()))
        print("NO-FUNDS local laboratory. Local journal state is not a consensus certificate.", file=sys.stderr)
        password = hidden_password(args.command == "create")
        request = encode_request(OPS[args.command], password, fields, args.pin)
        response = invoke(args.backend, request, args.backend_sha256)
        if identity is not None and any(response.get(k) != v or k not in response for k, v in identity.items()):
            raise RuntimeError("Backend network identity mismatch; reconcile saved state")
        if args.command == "network-address":
            checked_recipient(response.get("address", ""), identity["signing_domain"])
        if args.command == "prepare":
            checked_prepare_timing(response)
        if args.command == "compact":
            checked_compaction(response, args.pin)
        if args.command == "storage":
            checked_storage_status(response)
            if response.get("result") != "storage_inspected_not_synced":
                raise RuntimeError("Unexpected storage operation result")
        print(json.dumps(response, ensure_ascii=True, indent=2))
        return 0
    except NetworkMismatch:
        print("Recipient network mismatch. Obtain an address for the displayed pinned network; do not relabel an address or sign again blindly.", file=sys.stderr)
        return 1
    except (ValueError, OSError, RuntimeError, getpass.GetPassWarning, EOFError, subprocess.TimeoutExpired):
        print("Operation not completed. No automatic retry or reset. Check trusted local files and reconcile pending transactions before signing again.", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Interrupted; reconcile saved wallet state before signing again.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
