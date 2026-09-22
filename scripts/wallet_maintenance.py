#!/usr/bin/env python3
"""Explicit NO-FUNDS backup-first compaction into a new, verifiable handover.

Never replaces or deletes an active wallet, releases reservations, signs, or
broadcasts. An error may leave partial OR complete output: retain, do not retry.
"""
from __future__ import annotations

import sys
if __name__ == "__main__":
    sys.dont_write_bytecode = True

import argparse
import getpass
import hashlib
import os
from pathlib import Path
import stat
import subprocess

import wallet_backup as catalog
import wallet_health as health
from wallet_backup_backend import Backend
from zevune_wallet import checked_compaction, encode_request, hidden_password

MANIFEST = "HANDOVER.json"
FILES = {"backup.journal", "compacted.journal", MANIFEST}
FORMAT = "zevune-wallet-maintenance-1"
FIELDS = {"format", "source_receipt", "target_receipt", "source_sha256", "target_sha256",
          "source_bytes", "target_bytes", "requires_rescan", "source_not_revoked", "real_funds_allowed"}
COMPACT_BYTES = catalog.HEADER + catalog.RECORD
MAX_MANIFEST = catalog.MAX_MANIFEST


class MaintenanceBackend(Backend):
    def compact(self, source: Path, target: Path, expected: str, password: bytes):
        # Fixed original op10 through the existing bounded, pinned transport;
        # the catalog Backend.call whitelist is deliberately not widened.
        result = self._exchange(encode_request(10, password, [str(source), str(target)], expected))
        catalog.require(set(result) == {"ok", "scope", "result", "receipt", "source_receipt",
                        "source_retained", "requires_rescan", "wallet_storage"},
                        "unexpected_compaction_response")
        return checked_compaction(result, expected)


def directory_marker(path: Path):
    path = catalog.directory(path)
    info = path.stat()
    if os.name == "posix":
        catalog.require(info.st_uid == os.geteuid() and stat.S_IMODE(info.st_mode) & 0o077 == 0,
                        "private_handover_directory_required")
    return info.st_dev, info.st_ino


def inventory(root: Path):
    names = set()
    with os.scandir(root) as entries:
        for entry in entries:
            catalog.require(entry.name in FILES and entry.name not in names, "unexpected_handover_entry")
            names.add(entry.name)
    catalog.require(names == FILES, "incomplete_handover")


def fingerprint(path: Path):
    raw, marker = catalog.read_file(path, MAX_MANIFEST)
    return hashlib.sha256(raw).hexdigest(), marker


def validate_manifest(data: dict, expected: str):
    catalog.receipt(expected)
    catalog.require(type(data) is dict and set(data) == FIELDS and data["format"] == FORMAT,
                    "invalid_handover_schema")
    catalog.require(data["requires_rescan"] is True and data["source_not_revoked"] is True
                    and data["real_funds_allowed"] is False, "invalid_handover_policy")
    catalog.require(data["source_receipt"] == expected, "handover_source_mismatch")
    target = catalog.receipt(data["target_receipt"])
    catalog.require(target[:64] != expected[:64] and int(target[64:80], 16) == 1,
                    "invalid_target_ancestry")
    for key in ("source_sha256", "target_sha256"):
        catalog.require(type(data[key]) is str and catalog.HEX.fullmatch(data[key]) is not None,
                        "invalid_handover_digest")
    for key, size in (("source_bytes", catalog.HEADER + int(expected[64:80], 16) * catalog.RECORD),
                      ("target_bytes", COMPACT_BYTES)):
        catalog.require(type(data[key]) is int and data[key] == size, "invalid_handover_extent")
    return target


def budget(parent: Path, parent_id, source_bytes: int, reserve_bytes: int):
    """Conservative simultaneous budget: full backup + new journal + marker.

    No source bytes are reclaimed. The new directory and its three files need
    four entries. Metadata/COW/ACL/concurrent changes remain unmeasured.
    """
    health.bounded(source_bytes, catalog.MAX_WALLET)
    health.bounded(reserve_bytes)
    sample = health.probe(parent, expected_identity=parent_id)
    unit = sample["allocation_unit_bytes"]
    sizes = (source_bytes, COMPACT_BYTES, MAX_MANIFEST)
    payload = health.bounded(sum(((n + unit - 1) // unit) * unit if unit else n for n in sizes))
    required = health.bounded(payload + reserve_bytes)
    catalog.require(sample["read_only"] is not True, "handover_filesystem_read_only")
    catalog.require(sample["available_inodes"] is None or sample["available_inodes"] >= 4,
                    "handover_directory_entries_insufficient")
    catalog.require(sample["available_bytes"] >= required, "handover_space_budget_insufficient")
    return required


def unchanged_parent(parent: Path, marker):
    catalog.require(health.directory_id(parent) == marker, "handover_parent_changed")


def verify(root: Path, expected: str, manifest_sha256: str, password: bytes, backend: Backend):
    """Authenticate two exact files under an INDEPENDENT handover digest.

    The pinned receipt pair is an operator handover, not a proof of lineage.
    Native op10 compared complete plaintext/outbox on creation. No rescan here.
    """
    expected = catalog.receipt(expected)
    catalog.require(type(manifest_sha256) is str and catalog.HEX.fullmatch(manifest_sha256) is not None,
                    "independent_handover_digest_required")
    root = catalog.directory(root)
    root_id = directory_marker(root)
    inventory(root)
    digest, marker = fingerprint(root / MANIFEST)
    catalog.require(digest == manifest_sha256, "handover_digest_mismatch")
    data, parsed_marker = catalog.json_file(root / MANIFEST)
    catalog.require(parsed_marker == marker, "handover_changed")
    target_pin = validate_manifest(data, expected)
    retained = []
    for name, prefix, pin in (("backup.journal", "source", expected),
                              ("compacted.journal", "target", target_pin)):
        path = root / name
        before = catalog.wallet_snapshot(path, pin)
        catalog.require(before["sha256"] == data[prefix + "_sha256"]
                        and before["bytes"] == data[prefix + "_bytes"]
                        and before["identity"][0] == root_id[0], "handover_wallet_mismatch")
        catalog.authenticate(backend, path, pin, password)
        catalog.same_wallet(path, pin, before)
        retained.append((path, pin, before))
    for path, pin, before in retained:
        catalog.same_wallet(path, pin, before)
    inventory(root)
    catalog.require(fingerprint(root / MANIFEST) == (digest, marker)
                    and directory_marker(root) == root_id, "handover_changed")
    return {"result": "handover_authenticated_not_activated", "handover_sha256": digest,
            "target_receipt": target_pin, "requires_rescan": True, "source_not_revoked": True,
            "active_wallet_replaced": False, "real_funds_allowed": False}


def compact(source: Path, destination: Path, expected: str, password: bytes,
            backend: MaintenanceBackend, *, reserve_bytes: int):
    expected = catalog.receipt(expected)
    health.bounded(reserve_bytes)
    source = source.absolute()
    destination = catalog.new_file(destination)
    parent = destination.parent
    parent_id = health.directory_id(parent)
    source_parent_id = health.directory_id(source.parent)
    before = catalog.wallet_snapshot(source, expected)
    catalog.authenticate(backend, source, expected, password)
    catalog.same_wallet(source, expected, before)
    budget(parent, parent_id, before["bytes"], reserve_bytes)
    unchanged_parent(source.parent, source_parent_id)
    unchanged_parent(parent, parent_id)
    destination.mkdir(mode=0o700)  # exclusive claim; never resume/reuse a folder
    root_id = directory_marker(destination)
    catalog.require(root_id[0] == parent_id[0], "handover_volume_changed")
    backup, target = destination / "backup.journal", destination / "compacted.journal"
    # No cleanup handler: write/ack failures retain bounded evidence for an
    # explicit decision. No complete manifest is fabricated on an error.
    catalog.copied(backend.call(2, password, [str(source), str(backup)], expected), expected)
    saved = catalog.wallet_snapshot(backup, expected)
    catalog.require((saved["bytes"], saved["sha256"]) == (before["bytes"], before["sha256"]),
                    "backup_differs_from_source")
    catalog.authenticate(backend, backup, expected, password)
    catalog.same_wallet(source, expected, before)
    catalog.same_wallet(backup, expected, saved)
    # Compact the newly authenticated BACKUP, never the active source. The
    # original Rust op10 compares the entire snapshot and exact signed outbox.
    response = backend.compact(backup, target, expected, password)
    target_pin = catalog.receipt(response["receipt"])
    result = catalog.wallet_snapshot(target, target_pin)
    catalog.require(result["bytes"] == COMPACT_BYTES, "unexpected_compacted_extent")
    catalog.authenticate(backend, target, target_pin, password)
    catalog.same_wallet(target, target_pin, result)
    catalog.same_wallet(backup, expected, saved)
    catalog.same_wallet(source, expected, before)
    unchanged_parent(source.parent, source_parent_id)
    unchanged_parent(parent, parent_id)
    catalog.require(directory_marker(destination) == root_id, "handover_directory_changed")
    data = dict(format=FORMAT, source_receipt=expected, target_receipt=target_pin,
                source_sha256=before["sha256"], target_sha256=result["sha256"],
                source_bytes=before["bytes"], target_bytes=result["bytes"],
                requires_rescan=True, source_not_revoked=True, real_funds_allowed=False)
    validate_manifest(data, expected)
    raw = catalog.canonical(data)
    catalog.require(len(raw) <= MAX_MANIFEST, "handover_manifest_too_large")
    digest = hashlib.sha256(raw).hexdigest()
    catalog.write_new(destination / MANIFEST, raw)
    catalog.sync_directory(destination)
    catalog.sync_directory(parent)
    checked = verify(destination, expected, digest, password, backend)
    catalog.same_wallet(source, expected, before)
    unchanged_parent(source.parent, source_parent_id)
    unchanged_parent(parent, parent_id)
    return {**checked, "result": "backup_and_compaction_verified_not_activated", "source_retained": True}


class Parser(argparse.ArgumentParser):
    def error(self, message):
        self.exit(64, "Invalid maintenance command. Use --help; do not put passwords in arguments.\n")


def main(argv=None):
    parser = Parser(description=__doc__)
    parser.add_argument("--no-real-funds", action="store_true", required=True)
    subs = parser.add_subparsers(dest="command", required=True)
    for name in ("compact", "verify"):
        sub = subs.add_parser(name)
        sub.add_argument("directory", type=Path)
        sub.add_argument("--pin", required=True, help="Independently retained EXACT original source receipt")
        sub.add_argument("--backend", required=True, type=Path)
        sub.add_argument("--backend-sha256", required=True)
        if name == "compact":
            sub.add_argument("--source", type=Path, required=True)
            sub.add_argument("--reserve-bytes", required=True)
        else:
            sub.add_argument("--handover-sha256", required=True, help="Independently retained handover digest")
    args = parser.parse_args(argv)
    try:
        pin = catalog.receipt(args.pin)
        backend = MaintenanceBackend(args.backend, args.backend_sha256)
        backend._check()
        if args.command == "compact":
            reserve = health.decimal(args.reserve_bytes)
            catalog.new_file(args.directory)
            catalog.wallet_snapshot(args.source.absolute(), pin)
            print("Create a verified backup and compacted NEW copy. Keep originals offline. No active-wallet switch, signing or reservation release occurs.", file=sys.stderr)
            catalog.require(input("Type MAINTAIN to create the handover: ") == "MAINTAIN", "maintenance_not_approved")
            password = hidden_password(False)
            result = compact(args.source, args.directory, pin, password, backend, reserve_bytes=reserve)
        else:
            catalog.require(type(args.handover_sha256) is str and catalog.HEX.fullmatch(args.handover_sha256) is not None,
                            "independent_handover_digest_required")
            password = hidden_password(False)
            result = verify(args.directory, pin, args.handover_sha256, password, backend)
        import json
        print(json.dumps(result, ensure_ascii=True, indent=2))
        return 0
    except (ValueError, OSError, RuntimeError, subprocess.SubprocessError,
            getpass.GetPassWarning, EOFError, KeyboardInterrupt):
        print("Maintenance not completed. Retain original, partial/complete outputs and independent receipts. Do not retry blindly, replace the active wallet or clear reservations.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
