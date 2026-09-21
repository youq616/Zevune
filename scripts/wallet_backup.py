#!/usr/bin/env python3
"""Immutable NO-FUNDS wallet backup catalog: init, list, create, verify, restore.

An independently saved exact wallet receipt is mandatory for authenticated
operations. Metadata listings are NOT authenticated, newest or finality claims.
No networking, signing, automatic retry, pruning or source replacement occurs.
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
import subprocess
import sys

from wallet_backup_backend import Backend, file_object_identity, metadata_identity
from zevune_wallet import hidden_password, checked_storage_status

HEADER = 72
RECORD = 32948
MAX_WALLET = HEADER + 256 * RECORD
MAX_ENTRIES = 256
MAX_MANIFEST = 4096
LOCK_BYTES = b"ZVWBCAT1\n"
CATALOG = {"format": "zevune-wallet-catalog-1", "real_funds_allowed": False}
MANIFEST_FIELDS = {"format", "receipt", "wallet_sha256", "wallet_bytes", "requires_rescan", "real_funds_allowed"}
HEX = re.compile(r"[0-9a-f]{64}\Z")
PIN = re.compile(r"[0-9a-f]{144}\Z")


class CatalogError(ValueError):
    pass


def require(condition: bool, code: str):
    if not condition:
        raise CatalogError(code)


def canonical(data: dict) -> bytes:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode() + b"\n"


def receipt(value: str) -> str:
    require(type(value) is str and PIN.fullmatch(value) is not None, "independent_receipt_required")
    require(1 <= int(value[64:80], 16) <= 256, "invalid_receipt_generation")
    return value


def version_id(pin: str) -> str:
    return hashlib.sha256(b"ZEVUNE-WALLET-BACKUP-V1\0" + bytes.fromhex(receipt(pin))).hexdigest()


def regular(info):
    return (stat.S_ISREG(info.st_mode) and info.st_nlink == 1
            and not getattr(info, "st_file_attributes", 0) & 0x400)


def identity(info):
    return metadata_identity(info)


def directory(path: Path) -> Path:
    absolute = path.absolute()
    info = absolute.lstat()
    require(stat.S_ISDIR(info.st_mode) and not getattr(info, "st_file_attributes", 0) & 0x400
            and absolute.resolve(strict=True) == absolute, "canonical_directory_required")
    return absolute


def new_file(path: Path) -> Path:
    absolute = path.absolute()
    directory(absolute.parent)
    try:
        absolute.lstat()
    except FileNotFoundError:
        return absolute
    raise CatalogError("destination_already_exists")


def read_file(path: Path, maximum: int):
    directory(path.parent)
    before = path.lstat()
    require(regular(before) and 0 <= before.st_size <= maximum, "invalid_catalog_file")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_BINARY", 0)
    fd = os.open(path, flags)
    with os.fdopen(fd, "rb") as stream:
        opened = os.fstat(stream.fileno())
        require(regular(opened) and file_object_identity(opened) == file_object_identity(before), "file_changed")
        data = stream.read(maximum + 1)
        after = os.fstat(stream.fileno())
    require(len(data) <= maximum and len(data) == before.st_size and identity(opened) == identity(after)
            and identity(path.lstat()) == identity(before), "file_changed")
    return data, identity(before)


def json_file(path: Path):
    raw, marker = read_file(path, MAX_MANIFEST)
    def pairs(items):
        data = {}
        for key, value in items:
            require(key not in data, "duplicate_manifest_field")
            data[key] = value
        return data
    try:
        data = json.loads(raw, object_pairs_hook=pairs,
                          parse_constant=lambda _: (_ for _ in ()).throw(CatalogError("nonfinite_manifest")))
    except (UnicodeError, json.JSONDecodeError, RecursionError) as error:
        raise CatalogError("invalid_manifest") from error
    require(type(data) is dict and raw == canonical(data), "noncanonical_manifest")
    return data, marker


def sync_directory(path: Path):
    # Windows file fsync remains, but no Unix-equivalent directory durability
    # or physical power-loss guarantee is implied on either platform.
    if os.name == "posix":
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def write_new(path: Path, data: bytes):
    new_file(path)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    descriptor = os.open(path, flags, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    # Never delete partial output after an error; it may already be durable.


def wallet_bytes_summary(raw: bytes, expected: str):
    """Bounded public framing/exact-tip check, NOT decryption or authorization."""
    require(type(raw) is bytes and len(raw) <= MAX_WALLET, "invalid_wallet_bytes")
    pin = bytes.fromhex(receipt(expected))
    count, remainder = divmod(len(raw) - HEADER, RECORD)
    require(raw[:8] == b"ZVWJNL01" and 1 <= count <= 256 and not remainder
            and count == int.from_bytes(pin[32:40], "big"), "wallet_tip_or_framing_mismatch")
    previous = hashlib.sha256(raw[:HEADER]).digest()
    require(previous == pin[:32], "wallet_identity_mismatch")
    for index in range(1, count + 1):
        record = raw[HEADER + (index - 1) * RECORD:HEADER + index * RECORD]
        digest = hashlib.sha256(record[:-32]).digest()
        require(record[:8] == index.to_bytes(8, "big") and record[8:40] == previous
                and record[-32:] == digest, "wallet_public_chain_mismatch")
        previous = digest
    require(previous == pin[40:], "wallet_tip_or_framing_mismatch")
    return {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}


def wallet_snapshot(path: Path, expected: str):
    """Read a stable file and check public framing; authentication is separate."""
    raw, marker = read_file(path, MAX_WALLET)
    return {**wallet_bytes_summary(raw, expected), "identity": marker}


def same_wallet(path: Path, expected: str, before: dict):
    require(wallet_snapshot(path, expected) == before, "wallet_changed")


def authenticate(backend: Backend, path: Path, expected: str, password: bytes):
    response = backend.call(9, password, [str(path)], expected)
    require(set(response) == {"ok", "scope", "result", "receipt", "wallet_storage"}
            and response["result"] == "storage_inspected_not_synced"
            and response["receipt"] == expected, "unexpected_wallet_authentication")
    checked_storage_status(response)
    require(response["wallet_storage"]["records_used"] == int(expected[64:80], 16), "unexpected_wallet_generation")
    return response["wallet_storage"]


def copied(response: dict, expected: str):
    require(set(response) == {"ok", "scope", "result", "receipt"}
            and response.get("ok") is True and response.get("scope") == "local_journal_only_no_funds"
            and response.get("result") == "encrypted_copy_created"
            and response.get("receipt") == expected, "copy_result_unknown_reconcile_files")


class Catalog:
    def __init__(self, root: Path):
        self.root = directory(root)
        info = self.root.stat()
        if os.name == "posix":
            require(info.st_uid == os.geteuid() and stat.S_IMODE(info.st_mode) & 0o077 == 0, "private_catalog_required")
        self.root_id = (info.st_dev, info.st_ino)
        self.lock = None

    def _root(self):
        path = directory(self.root)
        info = path.stat()
        require((info.st_dev, info.st_ino) == self.root_id, "catalog_directory_changed")

    def __enter__(self):
        self._root()
        data, self.catalog_marker = json_file(self.root / "CATALOG.json")
        require(data == CATALOG and type(data.get("real_funds_allowed")) is bool, "unknown_catalog_format")
        path = self.root / ".lock"
        info = path.lstat()
        require(regular(info) and info.st_size == len(LOCK_BYTES), "invalid_catalog_lock")
        fd = os.open(path, os.O_RDWR | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0))
        self.lock = os.fdopen(fd, "r+b", buffering=0)
        try:
            opened = os.fstat(fd)
            require(file_object_identity(opened) == file_object_identity(info), "catalog_lock_changed")
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            elif os.name == "posix":
                import fcntl
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            else:
                raise CatalogError("unsupported_lock_platform")
            require(self.lock.read(len(LOCK_BYTES) + 1) == LOCK_BYTES, "invalid_catalog_lock")
            self.lock_marker = identity(info)
            self.lock_handle_marker = identity(opened)
            self.check()
            return self
        except BaseException:
            self.lock.close()
            self.lock = None
            raise

    def check(self):
        self._root()
        require(identity((self.root / ".lock").lstat()) == self.lock_marker
                and identity(os.fstat(self.lock.fileno())) == self.lock_handle_marker, "catalog_lock_changed")
        data, marker = json_file(self.root / "CATALOG.json")
        require(data == CATALOG and marker == self.catalog_marker, "catalog_changed")

    def __exit__(self, kind, error, trace):
        try:
            if kind is None:
                self.check()
        finally:
            self.lock.close()  # OS lock released even on failure; file retained.
            self.lock = None

    def entries(self):
        self.check()
        entries = []
        with os.scandir(self.root) as iterator:
            for entry in iterator:
                if entry.name in {"CATALOG.json", ".lock"}:
                    continue
                require(len(entries) < MAX_ENTRIES and HEX.fullmatch(entry.name) is not None, "catalog_inventory_invalid_or_full")
                directory(Path(entry.path))
                entries.append(entry.name)
        return sorted(entries)

    def manifest(self, key: str):
        require(HEX.fullmatch(key) is not None, "invalid_version")
        folder = directory(self.root / key)
        # A bounded scan rejects hidden alternate payloads and incomplete files.
        names = set()
        with os.scandir(folder) as iterator:
            for item in iterator:
                require(item.name in {"wallet.journal", "MANIFEST.json"}, "unexpected_backup_file")
                names.add(item.name)
        require(names == {"wallet.journal", "MANIFEST.json"}, "incomplete_backup")
        data, marker = json_file(folder / "MANIFEST.json")
        require(set(data) == MANIFEST_FIELDS and data["format"] == "zevune-wallet-backup-1"
                and data["requires_rescan"] is True and data["real_funds_allowed"] is False
                and type(data["wallet_bytes"]) is int and type(data["wallet_sha256"]) is str
                and HEX.fullmatch(data["wallet_sha256"]) is not None, "invalid_backup_manifest")
        receipt(data["receipt"])
        require(version_id(data["receipt"]) == key and data["wallet_bytes"] == HEADER + int(data["receipt"][64:80], 16) * RECORD,
                "backup_manifest_identity_mismatch")
        return data, marker

    def load(self, expected: str):
        key = version_id(expected)
        require(key in self.entries(), "backup_not_found")
        data, marker = self.manifest(key)
        require(data["receipt"] == expected, "backup_receipt_mismatch")
        path = self.root / key / "wallet.journal"
        snapshot = wallet_snapshot(path, expected)
        require(snapshot["sha256"] == data["wallet_sha256"] and snapshot["bytes"] == data["wallet_bytes"], "backup_digest_mismatch")
        return path, snapshot, (data, marker)

    def unchanged(self, expected, path, snapshot, manifest):
        same_wallet(path, expected, snapshot)
        require(self.manifest(version_id(expected)) == manifest, "backup_manifest_changed")
        self.check()


def init(root: Path):
    target = new_file(root)
    target.mkdir(mode=0o700)
    write_new(target / ".lock", LOCK_BYTES)
    write_new(target / "CATALOG.json", canonical(CATALOG))
    sync_directory(target)
    sync_directory(target.parent)
    with Catalog(target):
        pass
    return {"result": "catalog_created", "real_funds_allowed": False}


def list_versions(root: Path):
    with Catalog(root) as catalog:
        result = []
        for key in catalog.entries():
            try:
                data, _ = catalog.manifest(key)
                item = {"version": key, "receipt": data["receipt"], "generation": int(data["receipt"][64:80], 16),
                        "metadata_complete": True, "authenticated": False}
            except (ValueError, OSError):
                item = {"version": key, "metadata_complete": False, "authenticated": False}
            result.append(item)
    return {"result": "metadata_only", "latest_not_inferred": True, "versions": result, "real_funds_allowed": False}


def create(root: Path, source: Path, expected: str, password: bytes, backend: Backend):
    expected = receipt(expected)
    source = source.absolute()
    with Catalog(root) as catalog:
        require(not source.is_relative_to(catalog.root), "active_wallet_must_be_outside_catalog")
        before = wallet_snapshot(source, expected)
        authenticate(backend, source, expected, password)
        same_wallet(source, expected, before)
        require(len(catalog.entries()) < MAX_ENTRIES, "catalog_full")
        key = version_id(expected)
        folder = new_file(catalog.root / key)
        folder.mkdir(mode=0o700)
        target = folder / "wallet.journal"
        # A failure after mkdir leaves an explicit incomplete entry, not a
        # silently reusable/overwritten destination. No files are auto-deleted.
        copied(backend.call(2, password, [str(source), str(target)], expected), expected)
        copied_snapshot = wallet_snapshot(target, expected)
        require((copied_snapshot["sha256"], copied_snapshot["bytes"]) == (before["sha256"], before["bytes"]), "backup_bytes_mismatch")
        authenticate(backend, target, expected, password)
        same_wallet(target, expected, copied_snapshot)
        same_wallet(source, expected, before)
        data = {"format": "zevune-wallet-backup-1", "receipt": expected,
                "wallet_sha256": copied_snapshot["sha256"], "wallet_bytes": copied_snapshot["bytes"],
                "requires_rescan": True, "real_funds_allowed": False}
        write_new(folder / "MANIFEST.json", canonical(data))
        sync_directory(folder)
        sync_directory(catalog.root)
        path, saved, manifest = catalog.load(expected)
        require(saved == copied_snapshot, "backup_changed")
        catalog.unchanged(expected, path, saved, manifest)
    return {"result": "backup_created_not_synced", "version": key, "receipt": expected,
            "source_retained": True, "requires_rescan": True, "real_funds_allowed": False}


def verify(root: Path, expected: str, password: bytes, backend: Backend):
    expected = receipt(expected)
    with Catalog(root) as catalog:
        path, before, manifest = catalog.load(expected)
        status = authenticate(backend, path, expected, password)
        catalog.unchanged(expected, path, before, manifest)
    return {"result": "backup_authenticated_not_synced", "version": version_id(expected), "receipt": expected,
            "wallet_storage": status, "requires_rescan": True, "real_funds_allowed": False}


def restore(root: Path, target: Path, expected: str, password: bytes, backend: Backend):
    expected = receipt(expected)
    with Catalog(root) as catalog:
        target = new_file(target)
        require(not target.is_relative_to(catalog.root), "restore_must_be_outside_catalog")
        source, before, manifest = catalog.load(expected)
        authenticate(backend, source, expected, password)
        catalog.unchanged(expected, source, before, manifest)
        copied(backend.call(6, password, [str(source), str(target)], expected), expected)
        restored = wallet_snapshot(target, expected)
        require((restored["sha256"], restored["bytes"]) == (before["sha256"], before["bytes"]), "restored_bytes_mismatch")
        authenticate(backend, target, expected, password)
        same_wallet(target, expected, restored)
        catalog.unchanged(expected, source, before, manifest)
        sync_directory(target.parent)
    return {"result": "restored_not_synced", "version": version_id(expected), "receipt": expected,
            "source_retained": True, "requires_rescan": True, "real_funds_allowed": False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-real-funds", action="store_true", required=True)
    subs = parser.add_subparsers(dest="command", required=True)
    for name in ("init", "list", "create", "verify", "restore"):
        sub = subs.add_parser(name)
        sub.add_argument("catalog", type=Path)
        if name in {"create", "restore"}:
            sub.add_argument("wallet", type=Path)
        if name in {"create", "verify", "restore"}:
            sub.add_argument("--pin", required=True, help="Exact independently retained wallet receipt, NOT one trusted only from this catalog")
            sub.add_argument("--backend", type=Path, required=True)
            sub.add_argument("--backend-sha256", required=True, help="Independently verified local backend SHA256")
    args = parser.parse_args(argv)
    try:
        if args.command == "init":
            result = init(args.catalog)
        elif args.command == "list":
            result = list_versions(args.catalog)
        else:
            expected = receipt(args.pin)
            backend = Backend(args.backend, args.backend_sha256)
            backend._check()
            if args.command == "restore":
                new_file(args.wallet)
                print("Restore only to a new file. Keep backups offline; never spend concurrently from copies. Rescan trusted history and reconcile pending payments before signing.", file=sys.stderr)
                require(input("Type RESTORE to create a new copy: ") == "RESTORE", "restore_not_approved")
            password = hidden_password(False)
            if args.command == "create":
                result = create(args.catalog, args.wallet, expected, password, backend)
            elif args.command == "verify":
                result = verify(args.catalog, expected, password, backend)
            else:
                result = restore(args.catalog, args.wallet, expected, password, backend)
        print(json.dumps(result, ensure_ascii=True, indent=2))
        return 0
    except (ValueError, OSError, RuntimeError, subprocess.SubprocessError, getpass.GetPassWarning, EOFError, KeyboardInterrupt):
        print("Backup operation not completed. Preserve partial files and independent receipts; do not retry blindly, remove reservations or replace an active wallet.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
