#!/usr/bin/env python3
"""Reconcile an uncertain LOCAL wallet result without re-signing or broadcasting.

Authenticate a separately retained ancestor. Scan only a new copy against a
separately pinned stopped active ledger. Missing outbox is not settlement proof
or permission to retry. Preserve inputs and every partial/complete failed output.
"""
from __future__ import annotations

import sys
if __name__ == "__main__":
    sys.dont_write_bytecode = True

import argparse
import getpass
import hashlib
from pathlib import Path
import subprocess
import time

import wallet_backup as files
import wallet_health as space
import ledger_restore as ledger
from ledger_recovery_backend import Checkpoint, RecoveryBackend
from wallet_backup_backend import Backend
from zevune_wallet import encode_request, genesis_identity, hidden_password, checked_storage_status

FORMAT = "zevune-wallet-reconciliation-1"
MARKER = "RECONCILE.json"
MAX_PAYMENT = 32768
SCOPE = "local_journal_only_no_funds"


class ReconcileBackend(Backend):
    # Fixed original scan/outbox operations only. Shared catalog allowlist is
    # unchanged. Neither this module nor its CLI exposes prepare/sign (op4).
    def status(self, password, paths, pin):
        return self._exchange(encode_request(3, password, paths, pin))

    def pending(self, password, paths, pin):
        return self._exchange(encode_request(5, password, paths, pin))


def public_tip(raw: bytes, ancestor: str) -> str:
    """Check public framing/ancestry only; this is NOT authenticated discovery."""
    ancestor = files.receipt(ancestor)
    files.require(type(raw) is bytes and len(raw) <= files.MAX_WALLET, "invalid_wallet_bytes")
    count, tail = divmod(len(raw) - files.HEADER, files.RECORD)
    files.require(1 <= count <= 256 and tail == 0, "partial_or_oversized_wallet")
    candidate = (hashlib.sha256(raw[:files.HEADER]).digest() + count.to_bytes(8, "big") + raw[-32:]).hex()
    files.wallet_bytes_summary(raw, candidate)
    generation = int(ancestor[64:80], 16)
    end = files.HEADER + generation * files.RECORD
    files.require(generation <= count and candidate[:64] == ancestor[:64]
                  and raw[end - 32:end].hex() == ancestor[80:], "ancestor_receipt_mismatch")
    return candidate


def authenticate_descendant(source: Path, ancestor: str, password: bytes, backend: Backend):
    ancestor = files.receipt(ancestor)
    source = source.absolute()
    before = files.read_file(source, files.MAX_WALLET)
    candidate = public_tip(before[0], ancestor)
    # Pass the caller's independent ANCESTOR to the original Rust implementation,
    # not the unauthenticated tip extracted from the file. It verifies ancestry
    # and authenticates the final encrypted snapshot before returning its tip.
    response = backend.call(9, password, [str(source)], ancestor)
    files.require(type(response) is dict and set(response) == {"ok", "scope", "result", "receipt", "wallet_storage"}
                  and response["ok"] is True and response["scope"] == SCOPE
                  and response["result"] == "storage_inspected_not_synced"
                  and response["receipt"] == candidate, "unexpected_ancestry_authentication")
    status = checked_storage_status(response)
    files.require(status["records_used"] == int(candidate[64:80], 16), "unexpected_generation")
    files.require(files.read_file(source, files.MAX_WALLET) == before, "source_changed")
    return candidate, before


def discover(source: Path, ancestor: str, password: bytes, backend: Backend):
    tip, _ = authenticate_descendant(source, ancestor, password, backend)
    return dict(format=FORMAT, result="local_tip_authenticated_not_synced", receipt=tip,
                independent_ancestor=ancestor, history_scanned=False, latest_inferred=False,
                retry_authorized=False, broadcast_status="unknown", finality_verified=False,
                real_funds_allowed=False)


def checked_status(response: dict, identity: dict, checkpoint: Checkpoint, source_tip: str) -> str:
    fields = {"ok", "scope", "height", "balance", "available", "pending", "receipt"} | set(identity)
    files.require(type(response) is dict and set(response) == fields and response["ok"] is True
                  and response["scope"] == SCOPE, "invalid_scan_response")
    files.require(all(type(response[k]) is type(v) and response[k] == v for k, v in identity.items()),
                  "scan_network_mismatch")
    files.require(type(response["height"]) is int and response["height"] == checkpoint.height
                  and type(response["pending"]) is bool, "scan_checkpoint_mismatch")
    files.require(type(response["balance"]) is int and type(response["available"]) is int
                  and 0 <= response["available"] <= response["balance"] <= 100000,
                  "invalid_scan_amounts")
    files.require(response["pending"] or response["available"] == response["balance"],
                  "reservation_without_pending")
    source_tip = files.receipt(source_tip)
    tip = files.receipt(response["receipt"])
    generation = int(source_tip[64:80], 16)
    files.require(tip[:64] == source_tip[:64]
                  and generation <= int(tip[64:80], 16) <= min(256, generation + 1),
                  "scan_receipt_mismatch")
    files.require(int(tip[64:80], 16) != generation or tip == source_tip,
                  "same_generation_receipt_changed")
    return tip


def budget(parent: Path, parent_id, wallet_bytes: int, reserve: int):
    space.bounded(reserve)
    files.require(type(wallet_bytes) is int and files.HEADER + files.RECORD <= wallet_bytes <= files.MAX_WALLET
                  and (wallet_bytes - files.HEADER) % files.RECORD == 0, "invalid_source_extent")
    sample = space.probe(parent, expected_identity=parent_id)
    unit = sample["allocation_unit_bytes"]
    sizes = (min(files.MAX_WALLET, wallet_bytes + files.RECORD), MAX_PAYMENT, files.MAX_MANIFEST)
    total = sum(((n + unit - 1) // unit) * unit if unit else n for n in sizes)
    needed = space.bounded(total + reserve)
    files.require(sample["read_only"] is not True and sample["available_bytes"] >= needed,
                  "reconciliation_space_insufficient")
    files.require(sample["available_inodes"] is None or sample["available_inodes"] >= 4,
                  "reconciliation_entries_insufficient")
    return needed


def recover(source: Path, output: Path, ancestor: str, password: bytes, backend: ReconcileBackend,
            *, journal: Path, checkpoint: str, genesis: Path, genesis_sha256: str,
            recovery_backend: RecoveryBackend, reserve_bytes: int):
    ancestor = files.receipt(ancestor)
    space.bounded(reserve_bytes)
    pin = Checkpoint.parse(checkpoint)
    source, genesis = source.absolute(), genesis.absolute()
    journal = files.directory(journal)
    output = files.new_file(output)
    files.require(not output.is_relative_to(journal), "output_inside_ledger")
    parent_id, source_parent_id = space.directory_id(output.parent), space.directory_id(source.parent)
    network_before = files.read_file(genesis, 1922)
    identity = genesis_identity(genesis, genesis_sha256)
    files.require(network_before[0][:8] == b"ZVTGEN03" and identity["payment_profile"] == "LAB2",
                  "active_genesis_required")
    history_before = ledger.archive_snapshot(journal, pin)
    tip, source_before = authenticate_descendant(source, ancestor, password, backend)
    recovery_backend.active(journal, pin, time.monotonic() + 300)
    budget(output.parent, parent_id, len(source_before[0]), reserve_bytes)

    def unchanged_inputs():
        files.require(files.read_file(source, files.MAX_WALLET) == source_before
                      and space.directory_id(source.parent) == source_parent_id, "source_changed")
        files.require(files.read_file(genesis, 1922) == network_before
                      and ledger.archive_snapshot(journal, pin) == history_before, "history_changed")
        files.require(space.directory_id(output.parent) == parent_id, "output_parent_changed")

    unchanged_inputs()
    output.mkdir(mode=0o700)
    output_id = space.directory_id(output)
    copy = output / "wallet.journal"
    # All later writes are confined to this exclusively claimed new directory.
    # Retain every partial/complete result on error. No cleanup/resume/retry.
    files.copied(backend.call(2, password, [str(source), str(copy)], tip), tip)
    files.require(files.read_file(copy, files.MAX_WALLET)[0] == source_before[0], "source_copy_mismatch")
    files.authenticate(backend, copy, tip, password)
    unchanged_inputs()
    paths = [str(copy), str(journal), str(genesis), genesis_sha256]
    state = backend.status(password, paths, tip)
    final_tip = checked_status(state, identity, pin, tip)
    current = files.read_file(copy, files.MAX_WALLET)
    files.require(current[0].startswith(source_before[0]), "copy_prefix_changed")
    files.wallet_bytes_summary(current[0], final_tip)
    unchanged_inputs()
    transaction = None
    txid = None
    expected = {"wallet.journal"}
    if state["pending"]:
        reply = backend.pending(password, paths + [str(output / "pending.tx")], final_tip)
        fields = {"ok", "scope", "result", "receipt", "txid"} | set(identity)
        files.require(type(reply) is dict and set(reply) == fields and reply["ok"] is True
                      and reply["scope"] == SCOPE and reply["receipt"] == final_tip
                      and reply["result"] == "signed_transaction_exported_not_broadcast"
                      and all(type(reply[k]) is type(v) and reply[k] == v for k, v in identity.items()),
                      "pending_export_response_mismatch")
        txid = reply["txid"]
        files.require(type(txid) is str and files.HEX.fullmatch(txid) is not None, "invalid_pending_identifier")
        transaction = files.read_file(output / "pending.tx", MAX_PAYMENT)
        raw = transaction[0]
        files.require(len(raw) >= 98 and raw[:8] == b"ZVORLAB2" and raw[8:40].hex() == genesis_sha256
                      and hashlib.sha256(raw).hexdigest() == txid, "pending_bytes_mismatch")
        again = backend.status(password, paths, final_tip)
        checked_status(again, identity, pin, final_tip)
        files.require(again == state, "pending_reservation_changed")
        expected.add("pending.tx")
    files.authenticate(backend, copy, final_tip, password)
    recovery_backend.active(journal, pin, time.monotonic() + 300)

    def unchanged_outputs():
        ledger.names(output, expected)
        files.require(space.directory_id(output) == output_id
                      and files.read_file(copy, files.MAX_WALLET) == current, "reconciliation_changed")
        if transaction is not None:
            files.require(files.read_file(output / "pending.tx", MAX_PAYMENT) == transaction,
                          "pending_file_changed")

    unchanged_inputs()
    unchanged_outputs()
    result = dict(format=FORMAT, result="pending_recovered_not_broadcast" if state["pending"]
                  else "no_pending_not_settlement_proof", independent_ancestor=ancestor,
                  source_receipt=tip, copy_receipt=final_tip, checkpoint=checkpoint,
                  genesis_sha256=genesis_sha256, height=pin.height, txid=txid,
                  pending=state["pending"], broadcast_status="unknown", source_retained=True,
                  active_wallet_replaced=False, retry_authorized=False, latest_inferred=False,
                  finality_verified=False, real_funds_allowed=False)
    raw = files.canonical(result)
    files.require(len(raw) <= files.MAX_MANIFEST, "reconciliation_report_bounds")
    files.write_new(output / MARKER, raw)
    files.sync_directory(output)
    files.sync_directory(output.parent)
    expected.add(MARKER)
    unchanged_inputs()
    unchanged_outputs()
    files.require(files.read_file(output / MARKER, files.MAX_MANIFEST)[0] == raw, "reconciliation_report_changed")
    return {**result, "report_sha256": hashlib.sha256(raw).hexdigest()}


class Parser(argparse.ArgumentParser):
    def error(self, message):
        self.exit(64, "Invalid reconciliation arguments. Use --help; never put passwords in arguments.\n")


def main(argv=None):
    parser = Parser(description=__doc__)
    parser.add_argument("--no-real-funds", required=True, action="store_true")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("discover", "recover"):
        command = commands.add_parser(name)
        command.add_argument("source", type=Path)
        command.add_argument("--pin", required=True)
        command.add_argument("--backend", type=Path, required=True)
        command.add_argument("--backend-sha256", required=True)
        if name == "recover":
            command.add_argument("directory", type=Path)
            command.add_argument("--journal", type=Path, required=True)
            command.add_argument("--checkpoint", required=True)
            command.add_argument("--genesis", type=Path, required=True)
            command.add_argument("--genesis-sha256", required=True)
            command.add_argument("--recovery-backend", type=Path, required=True)
            command.add_argument("--recovery-backend-sha256", required=True)
            command.add_argument("--reserve-bytes", required=True)
    args = parser.parse_args(argv)
    try:
        ancestor = files.receipt(args.pin)
        backend = ReconcileBackend(args.backend, args.backend_sha256)
        backend._check()
        if args.command == "discover":
            result = discover(args.source, ancestor, hidden_password(False), backend)
        else:
            reserve = space.decimal(args.reserve_bytes)
            Checkpoint.parse(args.checkpoint)
            files.new_file(args.directory)
            native = RecoveryBackend(args.recovery_backend, args.recovery_backend_sha256)
            print("Scan a NEW wallet copy only. Do not retry signing, broadcast or treat absence as settlement.", file=sys.stderr)
            print("Type RECOVER-PENDING to create the private copy: ", end="", file=sys.stderr, flush=True)
            files.require(input() == "RECOVER-PENDING", "reconciliation_not_approved")
            result = recover(args.source, args.directory, ancestor, hidden_password(False), backend,
                             journal=args.journal, checkpoint=args.checkpoint, genesis=args.genesis,
                             genesis_sha256=args.genesis_sha256, recovery_backend=native, reserve_bytes=reserve)
        print(files.canonical(result).decode("ascii"), end="")
        return 0
    except (ValueError, OSError, RuntimeError, RecursionError, subprocess.SubprocessError,
            getpass.GetPassWarning, EOFError, KeyboardInterrupt):
        print("Reconciliation not completed. Retain inputs and all partial/complete outputs. Do not re-sign, clear reservations or retry blindly.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
