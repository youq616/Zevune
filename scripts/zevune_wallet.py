#!/usr/bin/env python3
"""NO-FUNDS wallet console. Network sync is explicit; never auto-broadcast.

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
       "network-address": 8, "storage": 9, "compact": 10, "status-at-checkpoint": 11, "prepare-at-checkpoint": 12, "pending-at-checkpoint": 13}
COUNTS = {0: 1, 1: 2, 2: 2, 3: 4, 4: 9, 5: 5, 6: 2, 7: 3, 8: 5, 9: 1, 10: 2, 11: 6, 12: 11, 13: 7}


def encode_request(op: int, password: bytes, fields: list[str], pin: str | None = None) -> bytes:
    if op not in COUNTS or len(fields) != COUNTS[op] or not 16 <= len(password) <= 1024:
        raise ValueError("Invalid request bounds")
    if pin is not None and (op == 0 or re.fullmatch(r"[0-9a-f]{144}", pin) is None):
        raise ValueError("Invalid independently saved wallet receipt")
    if op == 10 and pin is None:
        raise ValueError("Compaction requires the exact current source receipt")
    if op == 11:
        checked_checkpoint(fields[4], fields[5], pin)
    if op == 12:
        checked_preparation_checkpoint(fields[9], fields[10], pin)
        checked_preparation_numbers(fields[5], fields[6], fields[7])
        checked_address(fields[4])
    if op == 13:
        checked_preparation_checkpoint(fields[5], fields[6], pin)
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


def checked_checkpoint(height: str, app_hash: str, pin: str | None) -> tuple[str, str]:
    """Validate an independently obtained local checkpoint, not its authority."""
    if not isinstance(height, str) or len(height) > 20:
        raise ValueError("Invalid checkpoint height")
    height = integer(height)
    if (not isinstance(app_hash, str) or re.fullmatch(r"[0-9a-f]{64}", app_hash) is None
            or app_hash == "0" * 64):
        raise ValueError("A nonzero exact reference checkpoint is required")
    if (not isinstance(pin, str) or re.fullmatch(r"[0-9a-f]{144}", pin) is None
            or not 1 <= int(pin[64:80], 16) <= 256):
        raise ValueError("An independently retained wallet receipt is required")
    return height, app_hash


def checked_checkpoint_status(response: dict, height: str, app_hash: str) -> dict:
    """The Rust guard runs BEFORE wallet mutation. This checks its reply only.

    Never display this response as finality, as an independently authenticated
    network checkpoint, or as proof that the peer supplied the latest history.
    """
    keys = {"ok", "scope", "result", "checkpoint_matched", "payment_profile",
            "signing_domain", "genesis_sha256", "height", "app_hash", "balance",
            "available", "pending", "receipt"}
    if (not isinstance(response, dict) or set(response) != keys
            or response["ok"] is not True
            or response["scope"] != "local_journal_only_no_funds"
            or response["result"] != "checkpoint_matched_wallet_scanned"
            or response["checkpoint_matched"] is not True
            or type(response["height"]) is not int or response["height"] != int(integer(height))
            or response["app_hash"] != app_hash or type(response["pending"]) is not bool):
        raise RuntimeError("Unexpected checkpoint scan response; reconcile saved wallet state")
    checked_checkpoint(height, app_hash, response["receipt"])
    if (any(type(response[k]) is not int for k in ("balance", "available"))
            or not 0 <= response["available"] <= response["balance"] <= 100_000):
        raise RuntimeError("Invalid bounded checkpoint wallet amounts")
    genesis = response["genesis_sha256"]
    if (not isinstance(genesis, str) or re.fullmatch(r"[0-9a-f]{64}", genesis) is None
            or genesis == "0" * 64 or not isinstance(response["payment_profile"], str)
            or response["payment_profile"] not in {"LAB1", "LAB2"}
            or response["signing_domain"] != (genesis if response["payment_profile"] == "LAB2" else None)):
        raise RuntimeError("Invalid checkpoint wallet network identity")
    return response


def checked_preparation_checkpoint(height: str, app_hash: str, pin: str | None) -> tuple[str, str]:
    value = checked_checkpoint(height, app_hash, pin)
    if pin[:64] == "0" * 64 or pin[80:] == "0" * 64:
        raise ValueError("Invalid independently saved preparation receipt")
    return value


def checked_preparation_numbers(amount: str, fee: str, expiry: str) -> tuple[str, str, str]:
    """New NO-FUNDS intent guard only; not a consensus or market fee policy."""
    if any(not isinstance(v, str) or len(v) > 20 for v in (amount, fee, expiry)):
        raise ValueError("Invalid preparation intent")
    values = checked_payment_numbers(amount, fee, expiry)
    if int(fee) > min(100, max(1, int(amount) // 100)):
        raise ValueError("Abnormal local test fee; preparation rejected")
    return values


def checked_preparation_backend(backend: Path, expected: str | None) -> None:
    """Pre-secret check; invoke repeats its original digest check before exec.

    Like the original console, this assumes a trusted local host, not an OS
    sandbox or an executable-file locking primitive across process creation.
    """
    if (not isinstance(expected, str) or re.fullmatch(r"[0-9a-f]{64}", expected) is None
            or expected == "0" * 64):
        raise ValueError("Preparation requires a pinned local wallet executable")
    meta = backend.lstat()
    if (not stat.S_ISREG(meta.st_mode) or not 0 < meta.st_size <= 512 * 1024 * 1024
            or getattr(meta, "st_file_attributes", 0) & 0x400):
        raise ValueError("Invalid preparation backend")
    digest = hashlib.sha256()
    with backend.open("rb") as stream:
        if not os.path.samestat(meta, os.fstat(stream.fileno())):
            raise ValueError("Preparation backend changed")
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    after = backend.lstat()
    if (not os.path.samestat(meta, after) or after.st_size != meta.st_size
            or after.st_mtime_ns != meta.st_mtime_ns or digest.hexdigest() != expected):
        raise ValueError("Preparation backend digest or identity mismatch")


def checked_checkpoint_preparation(response: dict, height: str, app_hash: str, pin: str) -> dict:
    """Check a local saved-payment receipt, never authenticate a remote tip."""
    checked_preparation_checkpoint(height, app_hash, pin)
    keys = {"ok", "scope", "result", "checkpoint_matched", "payment_profile",
            "signing_domain", "genesis_sha256", "height", "app_hash", "txid", "receipt", "broadcast"}
    if (not isinstance(response, dict) or set(response) != keys
            or response["ok"] is not True or response["scope"] != "local_journal_only_no_funds"
            or response["result"] != "checkpoint_payment_saved_not_broadcast"
            or response["checkpoint_matched"] is not True or response["broadcast"] is not False
            or type(response["height"]) is not int or response["height"] != int(height)
            or response["app_hash"] != app_hash
            or not isinstance(response["txid"], str)
            or re.fullmatch(r"[0-9a-f]{64}", response["txid"]) is None):
        raise RuntimeError("Unexpected checked preparation response; reconcile before any retry")
    current = response["receipt"]
    checked_preparation_checkpoint(height, app_hash, current)
    # The supplied pin can be an ancestor, not necessarily the last generation.
    if current[:64] != pin[:64] or int(current[64:80], 16) <= int(pin[64:80], 16):
        raise RuntimeError("Unexpected saved-payment ancestry")
    genesis = response["genesis_sha256"]
    if (not isinstance(genesis, str) or re.fullmatch(r"[0-9a-f]{64}", genesis) is None
            or genesis == "0" * 64 or not isinstance(response["payment_profile"], str)
            or response["payment_profile"] not in {"LAB1", "LAB2"}
            or response["signing_domain"] != (genesis if response["payment_profile"] == "LAB2" else None)):
        raise RuntimeError("Invalid preparation network identity")
    return response


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


# Network-to-wallet orchestration uses the EXISTING verifier in zevune-network.
# No peer/caller hash or serialized receipt can enter as an authenticated tip.
SYNC_FIELDS = {"scope", "height", "app_hash", "root", "new_blocks",
               "observed_signed_tip", "caught_up_to_observed_tip",
               "real_funds_allowed", "base_checkpoint_matched"}


def _sync_hash(value: str) -> str:
    if (not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None
            or value == "0" * 64):
        raise ValueError("Independent nonzero digest required")
    return value


def _sync_json(raw: bytes, limit: int) -> dict:
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate field")
            result[key] = value
        return result

    def number(text):
        if len(text) > 20:
            raise ValueError("Integer out of bounds")
        return int(text)

    def not_number(_):
        raise ValueError("Noninteger JSON number")

    if type(raw) is not bytes or not 1 <= len(raw) <= limit:
        raise ValueError("Invalid bounded response")
    try:
        result = json.loads(raw.decode("utf-8"), object_pairs_hook=unique,
                            parse_int=number, parse_float=not_number,
                            parse_constant=not_number)
    except (RecursionError, UnicodeError) as error:
        raise ValueError("Invalid bounded JSON") from error
    if type(result) is not dict:
        raise ValueError("Expected one JSON object")
    return result


def _sync_path(value: Path) -> Path:
    if (not isinstance(value, Path) or not value.is_absolute() or ".." in value.parts
            or not 1 <= len(str(value).encode("utf-8")) <= 4096
            or any(ord(c) < 32 or ord(c) == 127 for c in str(value))):
        raise ValueError("Invalid absolute sync path")
    return value


def _sync_pinned_file(path: Path, pin: str, limit: int, *, contents=False):
    """Fixed local source and same-route metadata; no cross-API time equality."""
    _sync_hash(pin)
    _sync_path(path)

    def identity(info):
        return (info.st_dev, info.st_ino, info.st_size, info.st_mode, info.st_nlink,
                info.st_mtime_ns, info.st_ctime_ns,
                getattr(info, "st_file_attributes", 0) & 0x400)

    before = path.lstat()
    if (not stat.S_ISREG(before.st_mode) or not 1 <= before.st_size <= limit
            or getattr(before, "st_file_attributes", 0) & 0x400
            or path.resolve(strict=True) != path):
        raise ValueError("Invalid pinned sync file")
    digest, size, result = hashlib.sha256(), 0, bytearray()
    with path.open("rb") as stream:
        opened = os.fstat(stream.fileno())
        if (not os.path.samestat(before, opened) or not stat.S_ISREG(opened.st_mode)
                or opened.st_size != before.st_size):
            raise ValueError("Pinned file changed")
        while size <= limit:
            part = stream.read(min(1024 * 1024, limit + 1 - size))
            if not part:
                break
            size += len(part)
            digest.update(part)
            if contents:
                result.extend(part)
        if identity(os.fstat(stream.fileno())) != identity(opened):
            raise ValueError("Pinned file changed")
    if (size != before.st_size or size > limit or identity(path.lstat()) != identity(before)
            or digest.hexdigest() != pin):
        raise ValueError("Pinned file changed or digest mismatch")
    return bytes(result), identity(before)


def checked_network_sync(raw: bytes, *, limit: int, maximum: int, create: bool) -> dict:
    """Validate the local verifier's result shape; NOT a public certificate API.

    This parser alone authenticates nothing. Only sync_network's actual pinned
    executable invocation supplies its input. No RPC node result is fed here.
    """
    value = _sync_json(raw, 4096)
    if (set(value) != SYNC_FIELDS or value["scope"] != "fixed_validator_local_test_network"
            or value["real_funds_allowed"] is not False
            or value["base_checkpoint_matched"] is not False
            or type(value["caught_up_to_observed_tip"]) is not bool
            or any(type(value[k]) is not int for k in ("height", "new_blocks", "observed_signed_tip"))):
        raise ValueError("Unexpected network verifier result")
    height, blocks, tip = value["height"], value["new_blocks"], value["observed_signed_tip"]
    if (not 2 <= tip <= maximum or not 1 <= height < tip
            or not 0 <= blocks <= min(limit, height)
            or value["caught_up_to_observed_tip"] != (height + 1 == tip)
            or (create and blocks != height)):
        raise ValueError("Inconsistent verified sync range")
    _sync_hash(value["app_hash"])
    _sync_hash(value["root"])
    return value


def _sync_network_process(command: list[str]) -> bytes:
    """No pipe-reader tasks; only the pinned network program knows this stdout.

    The original program emits a fixed bounded public SyncResult or failure.
    A private temporary *public-only* spool avoids unbounded memory capture and
    pipe shutdown deadlocks. The 4KiB read limit is NOT a filesystem quota.
    """
    import tempfile
    environment = {k: v for k, v in os.environ.items()
                   if k.upper() in {"SYSTEMROOT", "WINDIR", "TEMP", "TMP"}}
    environment["RAYON_NUM_THREADS"] = "2"
    with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as diagnostic:
        proc = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=output,
                                stderr=diagnostic, cwd=Path(command[0]).parent,
                                env=environment, shell=False)
        try:
            code = proc.wait(timeout=300)
        finally:
            if proc.poll() is None:
                try:
                    proc.kill()
                except OSError:
                    pass
                proc.wait(timeout=5)
        output.seek(0)
        raw = output.read(4097)
        diagnostic.seek(0)
        if code != 0 or diagnostic.read(1) or len(raw) > 4096:
            raise RuntimeError("Network sync failed; preserve reference and wallet state")
        return raw


def _verified_network_reference(args):
    """Private verifier invocation shared by scan and explicit preparation.

    No caller result is accepted here; preserves the original PR42 checks.
    """
    # Freeze public options before any I/O. No caller-supplied resulting tip.
    o = vars(args).copy()
    for name in ("backend_sha256", "network_backend_sha256", "worker_sha256",
                 "config_sha256", "genesis_sha256"):
        _sync_hash(o[name])
    checked_checkpoint("0", o["genesis_sha256"], o["pin"])  # receipt syntax only
    paths = ("backend", "network_backend", "worker", "config", "genesis", "wallet", "journal")
    for name in paths:
        o[name] = _sync_path(o[name])
    if (o.get("no_real_funds") is not True or type(o["create_reference"]) is not bool
            or type(o["limit"]) is not str or len(o["limit"]) > 3
            or not 1 <= int(integer(o["limit"], 128)) <= 128):
        raise ValueError("Invalid sync bounds")
    for name in ("endpoint", "socks_proxy"):
        value = o[name]
        if value is None and name == "socks_proxy":
            continue
        if (not isinstance(value, str) or not 1 <= len(value) <= 256
                or any(ord(c) < 33 or ord(c) > 126 for c in value)):
            raise ValueError("Invalid explicit route")
    if (o["wallet"] == o["journal"] or o["wallet"].is_relative_to(o["journal"])
            or any(o["journal"] == o[k] or o[k].is_relative_to(o["journal"])
                   for k in ("config", "genesis", "backend", "network_backend", "worker"))):
        raise ValueError("Overlapping reference paths")
    # The network process receives no wallet path, receipt, password or secret.
    config_before = _sync_pinned_file(o["config"], o["config_sha256"], 16 * 1024, contents=True)
    config = _sync_json(config_before[0], 16 * 1024)
    if (set(config) != {"version", "chain_id", "asset_genesis_sha256", "consensus_genesis_sha256", "node_ids"}
            or type(config["version"]) is not int or config["version"] not in (1, 2)
            or config["chain_id"] != "zevune-orchard-lab-1"
            or config["asset_genesis_sha256"] != o["genesis_sha256"]):
        raise ValueError("Network and wallet genesis differ")
    # Go Load still verifies all canonical configuration, consensus genesis and
    # validator fields. This is only cross-backend identity binding, not a clone.
    genesis_before = _sync_pinned_file(o["genesis"], o["genesis_sha256"], 1922, contents=True)
    identity = genesis_identity(o["genesis"], o["genesis_sha256"])
    active = genesis_before[0][:8] == b"ZVTGEN03"
    if identity["payment_profile"] != "LAB2" or config["version"] != (2 if active else 1):
        raise ValueError("Unsupported or mismatched network profile")
    program_names = ("network_backend", "worker", "backend")
    programs = {k: _sync_pinned_file(o[k], o[k + "_sha256"], 512 * 1024 * 1024)
                for k in program_names}

    def unchanged():
        if (_sync_pinned_file(o["config"], o["config_sha256"], 16 * 1024, contents=True) != config_before
                or _sync_pinned_file(o["genesis"], o["genesis_sha256"], 1922, contents=True) != genesis_before
                or any(_sync_pinned_file(o[k], o[k + "_sha256"], 512 * 1024 * 1024) != programs[k]
                       for k in program_names)):
            raise RuntimeError("Pinned sync inputs changed; reconcile state")

    command = [str(o["network_backend"]), "sync", "--no-real-funds",
               "--worker", str(o["worker"]), "--worker-sha256", o["worker_sha256"],
               "--config", str(o["config"]), "--config-sha256", o["config_sha256"],
               "--endpoint", o["endpoint"], "--journal", str(o["journal"]), "--limit", o["limit"]]
    if o["socks_proxy"] is not None:
        command += ["--socks-proxy", o["socks_proxy"]]
    if o["create_reference"]:
        command += ["--create"]
    network = checked_network_sync(_sync_network_process(command), limit=int(o["limit"]),
                                   maximum=1_000_000 if active else 10_000, create=o["create_reference"])
    unchanged()
    return o, network, identity, unchanged, (1_000_000 if active else 10_000)


def sync_network(args) -> dict:
    """One actual authenticated sync, then the existing exact-checkpoint scan.

    Password input and the wallet backend are not reached on network failure.
    A later failure may leave authenticated reference blocks or a saved wallet
    update. Neither phase is retried, rolled back, or replaced by legacy status.
    """
    o, network, identity, unchanged, _ = _verified_network_reference(args)
    height, app_hash = str(network["height"]), network["app_hash"]
    fields = [str(o["wallet"]), str(o["journal"]), str(o["genesis"]), o["genesis_sha256"], height, app_hash]
    # Public request framing is checked before asking for the actual secret.
    encode_request(11, bytes(16), fields, o["pin"])
    password = hidden_password(False)
    unchanged()
    response = invoke(o["backend"], encode_request(11, password, fields, o["pin"]), o["backend_sha256"])
    checked_checkpoint_status(response, height, app_hash)
    if (any(response[k] != v for k, v in identity.items())
            or response["receipt"][:64] != o["pin"][:64]
            or int(response["receipt"][64:80], 16) < int(o["pin"][64:80], 16)
            or (response["receipt"][64:80] == o["pin"][64:80] and response["receipt"] != o["pin"])
            or (not response["pending"] and response["available"] != response["balance"])):
        raise RuntimeError("Wallet sync result mismatch; reconcile saved state")
    unchanged()
    return {"result": "network_verified_wallet_scanned", "scope": "fixed_validator_wallet_sync_no_funds",
            "config_sha256": o["config_sha256"], "network": network, "wallet": response,
            "real_funds_allowed": False, "broadcast": False, "latest_verified": False,
            "retry_authorized": False}


def _prepare_network_output(o: dict) -> tuple[int, int]:
    """Only a new output outside every input tree, in a stable real directory.

    Not a filesystem sandbox: trusted local files/parents remain a prerequisite.
    The Rust operation still performs create_new while holding both stores.
    """
    output = _sync_path(o["output"])
    for key in ("wallet", "journal", "config", "genesis", "backend", "network_backend", "worker"):
        other = _sync_path(o[key])
        if output == other or output.is_relative_to(other) or other.is_relative_to(output):
            raise ValueError("Preparation output overlaps an input")
    parent = output.parent
    info = parent.lstat()
    if (not stat.S_ISDIR(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400
            or parent.resolve(strict=True) != parent):
        raise ValueError("Preparation output parent is not a real directory")
    try:
        output.lstat()
    except FileNotFoundError:
        return info.st_dev, info.st_ino
    raise ValueError("Preparation output must not exist")


def prepare_network(args) -> dict:
    """Authenticate this call's reference, then invoke the EXISTING opcode12 once.

    No caller-supplied checkpoint/result, preceding wallet sync, or broadcast.
    A failed wallet invocation or lost output may already have saved a payment;
    neither an error nor a parser failure authorizes deletion or retry.
    """
    o = vars(args).copy()
    checked_preparation_checkpoint("0", o["genesis_sha256"], o["pin"])
    window = o["expiry_blocks"]
    if (not isinstance(window, str) or not 1 <= len(window) <= 3
            or not 1 <= int(integer(window, 100)) <= 100):
        raise ValueError("Expiry window must be 1 through 100 blocks")
    parent_identity = _prepare_network_output(o)
    # Use only frozen options. The helper has no checkpoint argument and always
    # invokes the original pinned network verifier; it never opens a wallet.
    o, network, identity, unchanged, maximum = _verified_network_reference(argparse.Namespace(**o))
    if not network["caught_up_to_observed_tip"]:
        raise ValueError("Reference catchup incomplete; no payment was prepared")
    expiry = network["height"] + int(window)
    if expiry > maximum:
        raise ValueError("Expiry exceeds the fixed profile height bound")
    height, app_hash = str(network["height"]), network["app_hash"]
    print("Pinned payment network: " + json.dumps(identity, sort_keys=True), file=sys.stderr)
    print("Reference verified through observed tip-1 at height " + height
          + "; not global latest state or finality. Expiry height: " + str(expiry)
          + ". This command never broadcasts.", file=sys.stderr)
    destination = checked_recipient(input("Recipient address for the displayed network: "), identity["signing_domain"])
    amount = input("Amount in integer test units: ")
    fee = input("Fee in integer test units: ")
    amount, fee, expiry_text = checked_preparation_numbers(amount, fee, str(expiry))
    fields = [str(o["wallet"]), str(o["journal"]), str(o["genesis"]), o["genesis_sha256"],
              destination, amount, fee, expiry_text, str(o["output"]), height, app_hash]
    encode_request(12, bytes(16), fields, o["pin"])
    if input("Type PREPARE to sign locally (no broadcast): ") != "PREPARE":
        raise ValueError("Payment not approved")
    unchanged()
    if _prepare_network_output(o) != parent_identity:
        raise ValueError("Preparation output parent changed")
    password = hidden_password(False)
    unchanged()
    if _prepare_network_output(o) != parent_identity:
        raise ValueError("Preparation output parent changed")
    response = invoke(o["backend"], encode_request(12, password, fields, o["pin"]), o["backend_sha256"])
    checked_checkpoint_preparation(response, height, app_hash, o["pin"])
    if any(response[k] != value for k, value in identity.items()):
        raise RuntimeError("Prepared payment network mismatch; reconcile saved state")
    unchanged()
    return {"result": "network_verified_payment_prepared_not_broadcast",
            "scope": "fixed_validator_wallet_preparation_no_funds", "config_sha256": o["config_sha256"],
            "network": network, "wallet": response, "real_funds_allowed": False,
            "broadcast": False, "latest_verified": False, "retry_authorized": False}


def checked_checkpoint_recovery(response: dict, height: str, app_hash: str, pin: str) -> dict:
    """Validate a no-wallet-write export receipt, never certify a remote tip."""
    checked_preparation_checkpoint(height, app_hash, pin)
    keys = {"ok", "scope", "result", "checkpoint_matched", "wallet_unchanged", "payment_profile",
            "signing_domain", "genesis_sha256", "height", "app_hash", "txid", "receipt", "broadcast"}
    if (not isinstance(response, dict) or set(response) != keys
            or response["ok"] is not True or response["scope"] != "local_journal_only_no_funds"
            or response["result"] != "checkpoint_pending_exported_not_broadcast"
            or response["checkpoint_matched"] is not True or response["wallet_unchanged"] is not True
            or response["broadcast"] is not False or type(response["height"]) is not int
            or response["height"] != int(height) or response["app_hash"] != app_hash
            or not isinstance(response["txid"], str)
            or re.fullmatch(r"[0-9a-f]{64}", response["txid"]) is None):
        raise RuntimeError("Unexpected recovery reply; do not re-sign or retry")
    current = response["receipt"]
    checked_preparation_checkpoint(height, app_hash, current)
    if (current[:64] != pin[:64] or int(current[64:80], 16) < int(pin[64:80], 16)
            or (current[64:80] == pin[64:80] and current != pin)):
        raise RuntimeError("Recovered outbox has an unexpected wallet ancestry")
    genesis = response["genesis_sha256"]
    if (not isinstance(genesis, str) or re.fullmatch(r"[0-9a-f]{64}", genesis) is None
            or genesis == "0" * 64 or not isinstance(response["payment_profile"], str)
            or response["payment_profile"] not in {"LAB1", "LAB2"}
            or response["signing_domain"] != (genesis if response["payment_profile"] == "LAB2" else None)):
        raise RuntimeError("Invalid recovery network identity")
    return response


def pending_at_checkpoint(args) -> dict:
    """An independently supplied constraint; this command does NOT authenticate it."""
    o = vars(args).copy()
    if o.get("no_real_funds") is not True:
        raise ValueError("Recovery is available only in the no-funds laboratory")
    height, app_hash = checked_preparation_checkpoint(o["expected_height"], o["expected_app_hash"], o["pin"])
    for key in ("wallet", "journal", "genesis", "backend", "output"):
        o[key] = _sync_path(o[key])
    _sync_hash(o["genesis_sha256"])
    _sync_hash(o["backend_sha256"])
    # Reuse the original new-output path policy. Only genesis/backend exist in
    # this direct command, so repeated references stand in for absent network
    # inputs; this dictionary is used for path checks ONLY, never a child call.
    output_paths = dict(o, config=o["genesis"], network_backend=o["backend"], worker=o["backend"])
    parent_identity = _prepare_network_output(output_paths)
    genesis_before = _sync_pinned_file(o["genesis"], o["genesis_sha256"], 1922, contents=True)
    backend_before = _sync_pinned_file(o["backend"], o["backend_sha256"], 512 * 1024 * 1024)
    identity = genesis_identity(o["genesis"], o["genesis_sha256"])

    def unchanged():
        if (_sync_pinned_file(o["genesis"], o["genesis_sha256"], 1922, contents=True) != genesis_before
                or _sync_pinned_file(o["backend"], o["backend_sha256"], 512 * 1024 * 1024) != backend_before):
            raise RuntimeError("Pinned recovery inputs changed")

    fields = [str(o["wallet"]), str(o["journal"]), str(o["genesis"]), o["genesis_sha256"],
              str(o["output"]), height, app_hash]
    encode_request(13, bytes(16), fields, o["pin"])
    print("Pinned local network: " + json.dumps(identity, sort_keys=True)
          + "; supplied checkpoint is not a network certificate. No new signature or broadcast.", file=sys.stderr)
    if input("Type RECOVER to export the SAME saved pending bytes: ") != "RECOVER":
        raise ValueError("Recovery not approved")
    unchanged()
    if _prepare_network_output(output_paths) != parent_identity:
        raise ValueError("Recovery output parent changed")
    password = hidden_password(False)
    unchanged()
    if _prepare_network_output(output_paths) != parent_identity:
        raise ValueError("Recovery output parent changed")
    response = invoke(o["backend"], encode_request(13, password, fields, o["pin"]), o["backend_sha256"])
    checked_checkpoint_recovery(response, height, app_hash, o["pin"])
    if any(response[k] != value for k, value in identity.items()):
        raise RuntimeError("Recovered payment network mismatch")
    unchanged()
    return response


def recover_pending_network(args) -> dict:
    """One real authenticated sync, then opcode13 once; no intermediate wallet scan.

    An export may be complete or partial even if the response is lost. Never
    delete the target, sign again, update the wallet, retry, or broadcast here.
    """
    o = vars(args).copy()
    checked_preparation_checkpoint("0", o["genesis_sha256"], o["pin"])
    parent_identity = _prepare_network_output(o)
    o, network, identity, unchanged, _ = _verified_network_reference(argparse.Namespace(**o))
    if not network["caught_up_to_observed_tip"]:
        raise ValueError("Reference catchup incomplete; pending was not recovered")
    height, app_hash = str(network["height"]), network["app_hash"]
    fields = [str(o["wallet"]), str(o["journal"]), str(o["genesis"]), o["genesis_sha256"],
              str(o["output"]), height, app_hash]
    encode_request(13, bytes(16), fields, o["pin"])
    print("Pinned recovery network: " + json.dumps(identity, sort_keys=True)
          + "; verified through observed tip-1 at height " + height
          + ", not global latest or finality. No new signature or broadcast.", file=sys.stderr)
    if input("Type RECOVER to export the SAME saved pending bytes: ") != "RECOVER":
        raise ValueError("Recovery not approved")
    unchanged()
    if _prepare_network_output(o) != parent_identity:
        raise ValueError("Recovery output parent changed")
    password = hidden_password(False)
    unchanged()
    if _prepare_network_output(o) != parent_identity:
        raise ValueError("Recovery output parent changed")
    response = invoke(o["backend"], encode_request(13, password, fields, o["pin"]), o["backend_sha256"])
    checked_checkpoint_recovery(response, height, app_hash, o["pin"])
    if any(response[k] != value for k, value in identity.items()):
        raise RuntimeError("Recovered payment network mismatch")
    unchanged()
    return {"result": "network_verified_pending_recovered_not_broadcast",
            "scope": "fixed_validator_pending_recovery_no_funds", "config_sha256": o["config_sha256"],
            "network": network, "wallet": response, "real_funds_allowed": False,
            "broadcast": False, "latest_verified": False, "retry_authorized": False}


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
        sub = commands.add_parser(command, allow_abbrev=command != "pending-at-checkpoint")
        sub.add_argument("wallet", type=Path)
        if command in {"backup", "restore", "prepare", "pending", "compact", "prepare-at-checkpoint", "pending-at-checkpoint"}:
            sub.add_argument("output", type=Path)
        if command in {"address", "network-address"}:
            sub.add_argument("--index", default="0")
        if command in {"status", "prepare", "pending", "init-test-ledger", "network-address", "status-at-checkpoint", "prepare-at-checkpoint", "pending-at-checkpoint"}:
            sub.add_argument("--journal", type=Path, required=True)
            sub.add_argument("--genesis", type=Path, required=True)
        if command in {"status", "prepare", "pending", "network-address", "status-at-checkpoint", "prepare-at-checkpoint", "pending-at-checkpoint"}:
            sub.add_argument("--genesis-sha256", required=True)
        if command in {"status-at-checkpoint", "prepare-at-checkpoint", "pending-at-checkpoint"}:
            sub.add_argument("--expected-height", required=True)
            sub.add_argument("--expected-app-hash", required=True)
    for kind in ("sync-network", "prepare-network", "recover-pending-network", "submit-pending-network"):
        online = commands.add_parser(kind, allow_abbrev=False)
        online.add_argument("wallet", type=Path)
        for name in ("journal", "genesis", "config", "network-backend", "worker"):
            online.add_argument("--" + name, type=Path, required=True)
        for name in ("genesis-sha256", "config-sha256", "network-backend-sha256", "worker-sha256", "endpoint"):
            online.add_argument("--" + name, required=True)
        online.add_argument("--socks-proxy")
        online.add_argument("--create-reference", action="store_true")
        online.add_argument("--limit", default="128")
        if kind in {"prepare-network", "recover-pending-network"}:
            online.add_argument("output", type=Path)
        if kind == "prepare-network":
            online.add_argument("--expiry-blocks", default="20")
    args = parser.parse_args(argv)
    try:
        if args.command in {"sync-network", "prepare-network", "recover-pending-network", "submit-pending-network"}:
            # Do not allow duplicate flags or abbreviated global pins for this
            # new operation. Old operation parsing/numbering remains unchanged.
            tokens = list(sys.argv[1:] if argv is None else argv)
            seen = set()
            known = {"no-real-funds", "backend", "backend-sha256", "pin", "journal", "genesis",
                     "config", "network-backend", "worker", "genesis-sha256", "config-sha256",
                     "network-backend-sha256", "worker-sha256", "endpoint", "socks-proxy",
                     "create-reference", "limit"}
            if args.command == "prepare-network":
                known.add("expiry-blocks")
            for token in tokens:
                if token.startswith("--"):
                    name = token[2:].split("=", 1)[0]
                    if name not in known or name in seen:
                        raise ValueError("Ambiguous sync flags")
                    seen.add(name)
            if args.command == "submit-pending-network":
                from wallet_submission import submit_pending_network
                try:
                    response = submit_pending_network(args, sys.modules[__name__])
                    print(json.dumps(response, ensure_ascii=True, indent=2))
                    return 0
                except (Exception, KeyboardInterrupt):
                    # Includes output publication failure AFTER a successful send.
                    # Do not echo transaction/path/peer details or infer no send.
                    print("Submission not completed; outcome may be unknown. Preserve pending and independently reconcile; no automatic retry or re-sign.", file=sys.stderr)
                    return 1
            operations = {"sync-network": sync_network, "prepare-network": prepare_network,
                          "recover-pending-network": recover_pending_network}
            response = operations[args.command](args)
            print(json.dumps(response, ensure_ascii=True, indent=2))
            return 0
        if args.command == "pending-at-checkpoint":
            tokens = list(sys.argv[1:] if argv is None else argv)
            seen = set()
            known = {"no-real-funds", "backend", "backend-sha256", "pin", "journal", "genesis",
                     "genesis-sha256", "expected-height", "expected-app-hash"}
            for token in tokens:
                if token.startswith("--"):
                    name = token[2:].split("=", 1)[0]
                    if name not in known or name in seen:
                        raise ValueError("Ambiguous checkpoint recovery flags")
                    seen.add(name)
            response = pending_at_checkpoint(args)
            print(json.dumps(response, ensure_ascii=True, indent=2))
            return 0
        if args.command == "prepare-at-checkpoint":
            checked_preparation_checkpoint(args.expected_height, args.expected_app_hash, args.pin)
            checked_preparation_backend(args.backend.absolute(), args.backend_sha256)
            try:
                args.output.lstat()
            except FileNotFoundError:
                pass
            else:
                raise ValueError("Preparation output must not exist")
        if args.command == "status-at-checkpoint":
            # Reject missing/empty pins before file access or secret input.
            checked_checkpoint(args.expected_height, args.expected_app_hash, args.pin)
            if (args.backend_sha256 is None
                    or re.fullmatch(r"[0-9a-f]{64}", args.backend_sha256) is None
                    or args.backend_sha256 == "0" * 64):
                raise ValueError("The checkpoint scan requires a pinned wallet executable")
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
        if args.command in {"status", "prepare", "pending", "init-test-ledger", "network-address", "status-at-checkpoint", "prepare-at-checkpoint"}:
            fields.extend([str(args.journal.absolute()), str(args.genesis.absolute())])
        if args.command in {"status", "prepare", "pending", "network-address", "status-at-checkpoint", "prepare-at-checkpoint"}:
            if re.fullmatch(r"[0-9a-f]{64}", args.genesis_sha256) is None:
                raise ValueError("A pinned public genesis digest is required")
            fields.append(args.genesis_sha256)
            identity = genesis_identity(args.genesis.absolute(), args.genesis_sha256)
            print("Pinned local payment network: " + json.dumps(identity, sort_keys=True), file=sys.stderr)
        if args.command == "network-address":
            fields.append(integer(args.index, (1 << 32) - 1))
        if args.command in {"prepare", "prepare-at-checkpoint"}:
            # Private intent is prompted, never placed in shell arguments/history.
            destination = checked_recipient(input("Recipient address for the displayed network: "), identity["signing_domain"])
            amount = integer(input("Amount in integer test units: "))
            fee = integer(input("Fee in integer test units: "))
            expiry = integer(input("Expiry block height: "))
            amount, fee, expiry = checked_payment_numbers(amount, fee, expiry)
            if args.command == "prepare-at-checkpoint":
                amount, fee, expiry = checked_preparation_numbers(amount, fee, expiry)
            if input("Type PREPARE to sign locally (no broadcast): ") != "PREPARE":
                raise ValueError("Payment not approved")
            fields.extend([destination, amount, fee, expiry])
        if args.command in {"prepare", "pending", "prepare-at-checkpoint"}:
            fields.append(str(args.output.absolute()))
        if args.command in {"status-at-checkpoint", "prepare-at-checkpoint"}:
            fields.extend([args.expected_height, args.expected_app_hash])
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
        if args.command == "status-at-checkpoint":
            checked_checkpoint_status(response, args.expected_height, args.expected_app_hash)
        if args.command == "prepare-at-checkpoint":
            checked_checkpoint_preparation(response, args.expected_height, args.expected_app_hash, args.pin)
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
