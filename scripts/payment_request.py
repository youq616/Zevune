#!/usr/bin/env python3
"""Create, inspect and explicitly prepare NO-FUNDS offline payment requests.

Requests contain PLAINTEXT intent, not signatures or payment receipts. A trusted
request digest and genesis pin are mandatory when reading; never broadcast or
retry. The original Rust wallet remains responsible for signing and persistence.
"""
from __future__ import annotations

import sys
if __name__ == "__main__":
    sys.dont_write_bytecode = True

import argparse
import getpass
import hashlib
import json
from pathlib import Path
import re
import secrets
import subprocess

import wallet_backup as storage
from wallet_backup_backend import Backend
from zevune_wallet import (checked_payment_numbers, checked_prepare_timing,
                           checked_recipient, encode_request, genesis_identity,
                           hidden_password)

FORMAT = "zevune-payment-request-1"
MAX_REQUEST = 2048
MAX_PAYMENT = 32768  # File-read bound only, not a new accepted wire-format limit.
FIELDS = {"format", "genesis_sha256", "recipient", "amount", "expiry_height", "nonce", "real_funds_allowed"}


def digest(value: str) -> str:
    storage.require(type(value) is str and storage.HEX.fullmatch(value) is not None,
                    "independent_digest_required")
    return value


def validate(data: dict, domain: str) -> dict:
    digest(domain)
    storage.require(domain != "0" * 64 and type(data) is dict and set(data) == FIELDS,
                    "invalid_payment_request_schema")
    storage.require(data["format"] == FORMAT and data["real_funds_allowed"] is False
                    and data["genesis_sha256"] == domain, "request_network_or_policy_mismatch")
    storage.require(type(data["amount"]) is int and 0 < data["amount"] < (1 << 63) - 1
                    and type(data["expiry_height"]) is int and 0 < data["expiry_height"] < 1 << 64,
                    "invalid_request_numbers")
    storage.require(type(data["nonce"]) is str and re.fullmatch(r"[0-9a-f]{32}", data["nonce"]) is not None,
                    "invalid_request_nonce")
    checked_recipient(data["recipient"], domain)
    return data


def decode(raw: bytes, domain: str, expected_sha256: str) -> dict:
    digest(expected_sha256)
    storage.require(type(raw) is bytes and 0 < len(raw) <= MAX_REQUEST, "request_size_exceeded")
    storage.require(hashlib.sha256(raw).hexdigest() == expected_sha256, "request_digest_mismatch")
    def unique(pairs):
        result = {}
        for key, value in pairs:
            storage.require(key not in result, "duplicate_request_field")
            result[key] = value
        return result
    try:
        data = json.loads(raw, object_pairs_hook=unique,
                          parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite_request")))
    except (UnicodeError, RecursionError) as error:
        raise ValueError("invalid_request_encoding") from error
    validate(data, domain)
    storage.require(raw == storage.canonical(data), "noncanonical_request")
    return data


def network(path: Path, expected: str):
    path = path.absolute()
    raw, marker = storage.read_file(path, 1922)
    identity = genesis_identity(path, digest(expected))
    storage.require(identity["payment_profile"] == "LAB2" and identity["signing_domain"] == expected,
                    "request_requires_lab2")
    storage.require(storage.read_file(path, 1922) == (raw, marker), "genesis_changed")
    return path, raw, marker


def unchanged(path: Path, snapshot, maximum: int):
    storage.require(storage.read_file(path, maximum) == snapshot, "request_input_changed")


def create_request(target: Path, genesis: Path, genesis_sha256: str,
                   recipient: str, amount: str, expiry: str) -> dict:
    target = storage.new_file(target)
    genesis, raw_genesis, marker = network(genesis, genesis_sha256)
    # The payer selects the fee; reserve at least one integer unit in the bound.
    amount, _, expiry = checked_payment_numbers(amount, "1", expiry)
    data = validate(dict(format=FORMAT, genesis_sha256=genesis_sha256, recipient=recipient,
                         amount=int(amount), expiry_height=int(expiry), nonce=secrets.token_hex(16),
                         real_funds_allowed=False), genesis_sha256)
    raw = storage.canonical(data)
    storage.require(len(raw) <= MAX_REQUEST, "request_size_exceeded")
    pin = hashlib.sha256(raw).hexdigest()
    unchanged(genesis, (raw_genesis, marker), 1922)
    storage.write_new(target, raw)
    storage.sync_directory(target.parent)
    saved, _ = storage.read_file(target, MAX_REQUEST)
    storage.require(saved == raw, "request_output_changed")
    unchanged(genesis, (raw_genesis, marker), 1922)
    return {"result": "request_created_not_signed", "request_sha256": pin,
            "request_bytes": len(raw), "authenticated": False, "real_funds_allowed": False}


def load_request(source: Path, request_sha256: str, genesis: Path, genesis_sha256: str):
    genesis, raw_genesis, marker = network(genesis, genesis_sha256)
    source = source.absolute()
    raw, identity = storage.read_file(source, MAX_REQUEST)
    data = decode(raw, genesis_sha256, request_sha256)
    unchanged(genesis, (raw_genesis, marker), 1922)
    return data, source, (raw, identity), genesis, (raw_genesis, marker)


def inspect_request(source: Path, request_sha256: str, genesis: Path, genesis_sha256: str):
    data, source, snapshot, genesis, net_snapshot = load_request(source, request_sha256, genesis, genesis_sha256)
    unchanged(source, snapshot, MAX_REQUEST)
    unchanged(genesis, net_snapshot, 1922)
    return {"result": "request_integrity_only", "request_sha256": request_sha256,
            "request": data, "authenticated": False, "expiry_checked_against_ledger": False,
            "single_use_enforced": False, "real_funds_allowed": False}


class RequestBackend(Backend):
    """Only one new explicit operation; catalog.call keeps its old allowlist."""
    def prepare(self, password: bytes, paths: list[str], pin: str):
        return self._exchange(encode_request(4, password, paths, pin))


def prepare_request(source: Path, request_sha256: str, genesis: Path, genesis_sha256: str,
                    wallet: Path, wallet_pin: str, journal: Path, output: Path, fee: str,
                    password: bytes, backend: RequestBackend):
    """Sign once through the real wallet; any uncertain outcome needs reconciliation.

    Pre/post snapshots detect observed changes, not a malicious-filesystem race
    barrier. Stop other wallet writers. Existing Rust locking and authorization
    remain the authority; the request nonce is not on-chain replay protection.
    """
    data, source, snapshot, genesis, net_snapshot = load_request(source, request_sha256, genesis, genesis_sha256)
    amount, fee, expiry = checked_payment_numbers(str(data["amount"]), fee, str(data["expiry_height"]))
    output = storage.new_file(output)
    wallet = wallet.absolute()
    wallet_pin = storage.receipt(wallet_pin)
    original, original_marker = storage.read_file(wallet, storage.MAX_WALLET)
    storage.wallet_bytes_summary(original, wallet_pin)
    journal = journal.absolute()
    storage.require(journal.resolve(strict=True) == journal, "canonical_journal_required")
    # An exported transaction must never become an unexpected active-ledger
    # member after a successful prepare; keep active directory contents exact.
    if journal.is_dir():
        storage.require(not output.is_relative_to(journal), "output_inside_active_ledger")
    storage.authenticate(backend, wallet, wallet_pin, password)
    unchanged(wallet, (original, original_marker), storage.MAX_WALLET)
    unchanged(source, snapshot, MAX_REQUEST)
    unchanged(genesis, net_snapshot, 1922)
    storage.new_file(output)
    # All paths and executable selection come from the caller, never the file.
    response = backend.prepare(password, [str(wallet), str(journal.absolute()), str(genesis),
                               genesis_sha256, data["recipient"], amount, fee, expiry, str(output)], wallet_pin)
    expected_fields = {"ok", "scope", "payment_profile", "signing_domain", "genesis_sha256",
                       "result", "txid", "receipt", "local_timing"}
    storage.require(type(response) is dict and set(response) == expected_fields
                    and response["ok"] is True and response["scope"] == "local_journal_only_no_funds"
                    and response["payment_profile"] == "LAB2"
                    and response["signing_domain"] == response["genesis_sha256"] == genesis_sha256
                    and response["result"] == "signed_transaction_exported_not_broadcast",
                    "prepare_result_unknown_reconcile_wallet")
    checked_prepare_timing(response)
    final_pin = storage.receipt(response["receipt"])
    storage.require(final_pin[:64] == wallet_pin[:64]
                    and int(final_pin[64:80], 16) > int(wallet_pin[64:80], 16), "wallet_receipt_not_advanced")
    transaction, tx_marker = storage.read_file(output, MAX_PAYMENT)
    storage.require(len(transaction) >= 98 and transaction[:8] == b"ZVORLAB2"
                    and transaction[8:40].hex() == genesis_sha256
                    and int.from_bytes(transaction[40:48], "big") == int(expiry)
                    and int.from_bytes(transaction[48:56], "big") == int(fee)
                    and hashlib.sha256(transaction).hexdigest() == digest(response["txid"]),
                    "export_result_unknown_reconcile_wallet")
    # Public hashes bind bytes only. Native authentication of the final wallet
    # independently verifies the durable record; never infer plaintext amount.
    storage.authenticate(backend, wallet, final_pin, password)
    final, final_marker = storage.read_file(wallet, storage.MAX_WALLET)
    storage.wallet_bytes_summary(final, final_pin)
    storage.require(final.startswith(original), "wallet_prefix_changed")
    unchanged(source, snapshot, MAX_REQUEST)
    unchanged(genesis, net_snapshot, 1922)
    unchanged(output, (transaction, tx_marker), MAX_PAYMENT)
    unchanged(wallet, (final, final_marker), storage.MAX_WALLET)
    return {"result": "request_prepared_not_broadcast", "request_sha256": request_sha256,
            "txid": response["txid"], "receipt": final_pin, "genesis_sha256": genesis_sha256,
            "local_timing": response["local_timing"], "broadcast": False,
            "single_use_enforced": False, "real_funds_allowed": False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-real-funds", action="store_true", required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("create", "inspect", "prepare"):
        sub = commands.add_parser(name)
        sub.add_argument("request", type=Path)
        sub.add_argument("--genesis", type=Path, required=True)
        sub.add_argument("--genesis-sha256", required=True)
        if name != "create":
            sub.add_argument("--request-sha256", required=True)
        if name == "prepare":
            sub.add_argument("output", type=Path)
            sub.add_argument("--wallet", type=Path, required=True)
            sub.add_argument("--wallet-pin", required=True)
            sub.add_argument("--journal", type=Path, required=True)
            sub.add_argument("--backend", type=Path, required=True)
            sub.add_argument("--backend-sha256", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "create":
            network(args.genesis, args.genesis_sha256)
            storage.new_file(args.request)
            print("Request files contain PLAINTEXT recipient, amount and expiry. Share only deliberately. No signature or recipient authentication.", file=sys.stderr)
            recipient = input("LAB2 recipient: ")
            amount = input("Amount in integer test units: ")
            expiry = input("Expiry block height: ")
            storage.require(input("Type CREATE to save plaintext intent: ") == "CREATE", "creation_not_approved")
            result = create_request(args.request, args.genesis, args.genesis_sha256, recipient, amount, expiry)
        else:
            result = inspect_request(args.request, args.request_sha256, args.genesis, args.genesis_sha256)
            if args.command == "prepare":
                backend = RequestBackend(args.backend, args.backend_sha256)
                backend._check()
                storage.new_file(args.output)
                wallet = args.wallet.absolute()
                storage.wallet_snapshot(wallet, storage.receipt(args.wallet_pin))
                print(json.dumps(result, ensure_ascii=True, indent=2), file=sys.stderr)
                fee = input("Payer-selected fee in integer test units: ")
                checked_payment_numbers(str(result["request"]["amount"]), fee, str(result["request"]["expiry_height"]))
                print("NO-FUNDS local signing only. This nonce is NOT single-use enforcement. Stop other writers; reconcile any earlier payment before signing.", file=sys.stderr)
                storage.require(input("Type PREPARE to sign exactly this request and fee: ") == "PREPARE", "prepare_not_approved")
                password = hidden_password(False)
                result = prepare_request(args.request, args.request_sha256, args.genesis, args.genesis_sha256,
                                         args.wallet, args.wallet_pin, args.journal, args.output, fee, password, backend)
        print(json.dumps(result, ensure_ascii=True, indent=2))
        return 0
    except (ValueError, OSError, RuntimeError, RecursionError, getpass.GetPassWarning,
            EOFError, KeyboardInterrupt, subprocess.SubprocessError):
        print("Request operation not completed. Preserve files and receipts; reconcile the wallet's existing pending payment. Never retry blindly, clear reservations or infer that signing did not occur.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
