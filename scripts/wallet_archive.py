#!/usr/bin/env python3
"""Portable encrypted-wallet backups: export, inspect and import, NO-FUNDS only.

Fixed framing, no compression or archive-controlled paths. An independently
retained wallet receipt AND archive digest are required when reading a package.
Inspection is not AEAD authentication. Import authenticates with the real pinned
Rust backend before publishing a catalog manifest; failures retain partial data.
"""
from __future__ import annotations

import argparse
import getpass
import hashlib
from pathlib import Path
import struct
import subprocess
import sys
import json

import wallet_backup as catalog
from wallet_backup_backend import Backend
from zevune_wallet import hidden_password

MAGIC = b"ZVWBPK01"
FRAME = struct.Struct(">8sII")
MAX_ARCHIVE = FRAME.size + catalog.MAX_MANIFEST + catalog.MAX_WALLET


def archive_digest(value: str) -> str:
    catalog.require(type(value) is str and catalog.HEX.fullmatch(value) is not None,
                    "independent_archive_digest_required")
    return value


def manifest_for(expected: str, summary: dict) -> dict:
    return {"format": "zevune-wallet-backup-1", "receipt": expected,
            "wallet_sha256": summary["sha256"], "wallet_bytes": summary["bytes"],
            "requires_rescan": True, "real_funds_allowed": False}


def decode(raw: bytes, expected: str, expected_digest: str):
    """Parse at most one bounded ciphertext, with no writes or backend calls.

    All manifest values are derivable from the externally pinned receipt and
    verified public wallet bytes. Exact canonical comparison rejects unknown,
    duplicate or noncanonical JSON without interpreting arbitrary input fields.
    Public hash chains cannot validate the encrypted records' AEAD tags.
    """
    expected = catalog.receipt(expected)
    archive_digest(expected_digest)
    catalog.require(type(raw) is bytes and FRAME.size <= len(raw) <= MAX_ARCHIVE,
                    "invalid_archive_extent")
    catalog.require(hashlib.sha256(raw).hexdigest() == expected_digest,
                    "archive_digest_mismatch")
    magic, manifest_size, wallet_size = FRAME.unpack_from(raw)
    catalog.require(magic == MAGIC and 0 < manifest_size <= catalog.MAX_MANIFEST
                    and catalog.HEADER + catalog.RECORD <= wallet_size <= catalog.MAX_WALLET
                    and FRAME.size + manifest_size + wallet_size == len(raw),
                    "invalid_archive_framing")
    start = FRAME.size + manifest_size
    wallet = raw[start:]
    summary = catalog.wallet_bytes_summary(wallet, expected)
    manifest = manifest_for(expected, summary)
    catalog.require(raw[FRAME.size:start] == catalog.canonical(manifest),
                    "archive_manifest_mismatch")
    return wallet, summary, manifest


def read_archive(source: Path, expected: str, expected_digest: str):
    raw, marker = catalog.read_file(source, MAX_ARCHIVE)
    wallet, summary, manifest = decode(raw, expected, expected_digest)
    return wallet, summary, manifest, marker, len(raw)


def unchanged_archive(source: Path, marker, expected_digest: str):
    raw, observed = catalog.read_file(source, MAX_ARCHIVE)
    catalog.require(observed == marker and hashlib.sha256(raw).hexdigest() == expected_digest,
                    "archive_changed")


def public_result(result: str, expected: str, digest: str, size: int, authenticated: bool):
    return {"result": result, "format": "zevune-wallet-package-1",
            "archive_sha256": digest, "archive_bytes": size,
            "version": catalog.version_id(expected), "receipt": expected,
            "generation": int(expected[64:80], 16), "authenticated": authenticated,
            "requires_rescan": True, "latest_not_inferred": True,
            "real_funds_allowed": False}


def export_archive(root: Path, target: Path, expected: str, password: bytes, backend: Backend):
    """Authenticate one immutable catalog version and create one new package."""
    expected = catalog.receipt(expected)
    with catalog.Catalog(root) as store:
        target = catalog.new_file(target)
        catalog.require(not target.is_relative_to(store.root), "archive_must_be_outside_catalog")
        source, before, retained_manifest = store.load(expected)
        catalog.authenticate(backend, source, expected, password)
        store.unchanged(expected, source, before, retained_manifest)
        ciphertext, observed = catalog.read_file(source, catalog.MAX_WALLET)
        summary = catalog.wallet_bytes_summary(ciphertext, expected)
        catalog.require({**summary, "identity": observed} == before, "backup_changed")
        manifest = catalog.canonical(manifest_for(expected, summary))
        raw = FRAME.pack(MAGIC, len(manifest), len(ciphertext)) + manifest + ciphertext
        catalog.require(len(raw) <= MAX_ARCHIVE, "invalid_archive_extent")
        digest = hashlib.sha256(raw).hexdigest()
        # create-only: never replace a source, existing package or partial file.
        catalog.write_new(target, raw)
        saved, _, _, marker, size = read_archive(target, expected, digest)
        catalog.require(saved == ciphertext and size == len(raw), "archive_bytes_changed")
        catalog.sync_directory(target.parent)
        unchanged_archive(target, marker, digest)
        store.unchanged(expected, source, before, retained_manifest)
    return public_result("archive_exported_not_synced", expected, digest, size, True)


def inspect_archive(source: Path, expected: str, expected_digest: str):
    """Read-only public integrity checks. Never ask for passwords or run code."""
    source = source.absolute()
    _, _, _, marker, size = read_archive(source, expected, expected_digest)
    unchanged_archive(source, marker, expected_digest)
    return public_result("archive_integrity_only", expected, expected_digest, size, False)


def import_archive(root: Path, source: Path, expected: str, expected_digest: str,
                   password: bytes, backend: Backend):
    """Create/authenticate a new catalog version; do not restore an active wallet.

    A wrong password/backend or write failure can leave an incomplete version
    directory. Never remove it, complete its manifest speculatively or overwrite
    it on retry. The original catalog and package are retained on every path.
    """
    expected = catalog.receipt(expected)
    source = source.absolute()
    archive_digest(expected_digest)
    # Refuse a changed/unapproved executable before allocating a destination.
    backend._check()
    with catalog.Catalog(root) as store:
        catalog.require(not source.is_relative_to(store.root), "archive_must_be_outside_catalog")
        ciphertext, summary, manifest, marker, size = read_archive(source, expected, expected_digest)
        entries = store.entries()
        key = catalog.version_id(expected)
        catalog.require(key not in entries, "destination_already_exists")
        catalog.require(len(entries) < catalog.MAX_ENTRIES, "catalog_full")
        folder = catalog.new_file(store.root / key)
        folder.mkdir(mode=0o700)
        folder_info = folder.stat()
        folder_id = folder_info.st_dev, folder_info.st_ino
        target = folder / "wallet.journal"
        catalog.write_new(target, ciphertext)
        before = catalog.wallet_snapshot(target, expected)
        catalog.require((before["bytes"], before["sha256"]) == (summary["bytes"], summary["sha256"]),
                        "imported_bytes_mismatch")
        # The public digest/pin is NOT enough: use existing Rust op9 for AEAD.
        catalog.authenticate(backend, target, expected, password)
        catalog.same_wallet(target, expected, before)
        unchanged_archive(source, marker, expected_digest)
        store.check()
        current = catalog.directory(folder).stat()
        catalog.require((current.st_dev, current.st_ino) == folder_id, "version_directory_changed")
        # Presence of a canonical manifest marks a complete catalog version.
        # It is written only after native authentication and immutable-source checks.
        catalog.write_new(folder / "MANIFEST.json", catalog.canonical(manifest))
        catalog.sync_directory(folder)
        catalog.sync_directory(store.root)
        path, saved, retained_manifest = store.load(expected)
        catalog.require(saved == before, "imported_wallet_changed")
        store.unchanged(expected, path, saved, retained_manifest)
        unchanged_archive(source, marker, expected_digest)
    result = public_result("archive_imported_not_synced", expected, expected_digest, size, True)
    result.update(source_retained=True, active_wallet_replaced=False)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-real-funds", action="store_true", required=True)
    subs = parser.add_subparsers(dest="command", required=True)
    for name in ("export", "inspect", "import"):
        sub = subs.add_parser(name)
        if name != "inspect":
            sub.add_argument("catalog", type=Path)
        sub.add_argument("archive", type=Path)
        sub.add_argument("--pin", required=True, help="Independently retained EXACT wallet receipt")
        if name != "export":
            sub.add_argument("--archive-sha256", required=True, help="Digest from an independent trusted channel")
        if name != "inspect":
            sub.add_argument("--backend", type=Path, required=True)
            sub.add_argument("--backend-sha256", required=True, help="Independently verified native executable SHA256")
    args = parser.parse_args(argv)
    try:
        expected = catalog.receipt(args.pin)
        if args.command == "inspect":
            result = inspect_archive(args.archive, expected, args.archive_sha256)
        else:
            backend = Backend(args.backend, args.backend_sha256)
            backend._check()
            if args.command == "import":
                # Fail malformed packages before asking for a password/confirmation.
                inspect_archive(args.archive, expected, args.archive_sha256)
                print("Import only creates a backup version, not an active wallet. Retain the package and independent receipts. Never spend from concurrent copies; restore explicitly and rescan trusted history.", file=sys.stderr)
                catalog.require(input("Type IMPORT to create the catalog version: ") == "IMPORT", "import_not_approved")
            else:
                catalog.new_file(args.archive)
            password = hidden_password(False)
            if args.command == "export":
                result = export_archive(args.catalog, args.archive, expected, password, backend)
            else:
                result = import_archive(args.catalog, args.archive, expected, args.archive_sha256, password, backend)
        print(json.dumps(result, ensure_ascii=True, indent=2))
        return 0
    except (ValueError, OSError, RuntimeError, subprocess.SubprocessError,
            getpass.GetPassWarning, EOFError, KeyboardInterrupt):
        print("Archive operation not completed. Preserve partial outputs and independent pins. Do not overwrite, retry blindly, clear reservations or sign a replacement payment.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
