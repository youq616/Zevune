#!/usr/bin/env python3
"""Read-only NO-FUNDS wallet capacity warnings and explicit maintenance plans.

Authenticates an externally pinned exact wallet tip with the existing Rust
backend. Disk observations and payload estimates are advisory, never a space
reservation, write permission, payment authorization or a latest-state claim.
"""
from __future__ import annotations

import sys

if __name__ == "__main__":
    sys.dont_write_bytecode = True

import argparse
import datetime
import getpass
import json
import os
from pathlib import Path
import subprocess

import wallet_backup as catalog
import wallet_archive as archive
from wallet_backup_backend import Backend
from zevune_wallet import checked_storage_status, hidden_password

MAX_NUMBER = (1 << 63) - 1
OPERATIONS = ("wallet-copy", "catalog-backup", "archive-export", "compact-copy")
EXIT_CODES = {"nominal": 0, "warning": 10, "critical": 20}


def bounded(value, maximum=MAX_NUMBER):
    catalog.require(type(value) is int and 0 <= value <= maximum, "invalid_health_integer")
    return value


def decimal(value: str, maximum=MAX_NUMBER):
    catalog.require(type(value) is str and len(value) <= 19
                    and (value == "0" or value.isascii() and value.isdecimal() and not value.startswith("0")),
                    "canonical_decimal_required")
    return bounded(int(value), maximum)


def directory_id(path: Path):
    info = catalog.directory(path).stat()
    # Directory mtime changes with unrelated names; identity is not its mtime.
    return info.st_dev, info.st_ino


def windows_capacity(path: Path) -> tuple[int, int]:
    """Query the quota-aware caller fields explicitly, not volume-wide free.

    shutil.disk_usage does not provide this output-parameter contract. Request
    only the first two GetDiskFreeSpaceExW outputs; use 64-bit storage and never
    fall back to an unqualified free-space value on query failure.
    """
    import ctypes
    from ctypes import wintypes

    query = ctypes.WinDLL("kernel32", use_last_error=True).GetDiskFreeSpaceExW
    pointer = ctypes.POINTER(ctypes.c_ulonglong)
    query.argtypes = [wintypes.LPCWSTR, pointer, pointer, pointer]
    query.restype = wintypes.BOOL
    available, total = ctypes.c_ulonglong(), ctypes.c_ulonglong()
    if not query(str(path), ctypes.byref(available), ctypes.byref(total), None):
        raise OSError("windows_capacity_query_failed")
    return bounded(total.value), bounded(available.value)


def probe(directory: Path, *, expected_identity: tuple[int, int] | None = None) -> dict:
    """Read caller-available bytes; no write probe, recursive walk or cache.

    Linux f_bavail excludes reserved blocks; Windows explicitly queries the
    caller's quota-aware free/total bytes. ACLs and future writes are not tested.
    """
    path = catalog.directory(directory)
    before = directory_id(path)
    catalog.require(expected_identity is None or before == expected_identity, "volume_directory_changed")
    catalog.require(sys.platform in ("linux", "win32"), "unsupported_health_platform")
    if sys.platform == "linux":
        descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            opened = os.fstat(descriptor)
            catalog.require((opened.st_dev, opened.st_ino) == before, "volume_directory_changed")
            stats = os.fstatvfs(descriptor)
        finally:
            os.close(descriptor)
        unit = bounded(stats.f_frsize, 1 << 31)
        blocks, free, available = (bounded(n) for n in (stats.f_blocks, stats.f_bfree, stats.f_bavail))
        catalog.require(unit > 0 and 0 <= available <= free <= blocks, "invalid_volume_sample")
        total, available_bytes = bounded(blocks * unit), bounded(available * unit)
        count = bounded(stats.f_files)
        # Some filesystems do not report a finite inode inventory.
        inodes = bounded(stats.f_favail) if count else None
        catalog.require(inodes is None or inodes <= count, "invalid_inode_sample")
        readonly = bool(stats.f_flag & os.ST_RDONLY)
        method = "linux_fstatvfs_unprivileged_available"
    else:
        total, available_bytes = windows_capacity(path)
        catalog.require(available_bytes <= total, "invalid_volume_sample")
        unit = inodes = readonly = None
        method = "windows_getdiskfreespaceex_caller_available"
    catalog.require(directory_id(path) == before, "volume_directory_changed")
    return {"method": method, "total_bytes": total, "available_bytes": available_bytes,
            "allocation_unit_bytes": unit, "available_inodes": inodes, "read_only": readonly}


def estimate(files: list[int], sample: dict, reserve_bytes: int, new_entries: int) -> dict:
    """Pure data-byte accounting, not an OS allocation or metadata guarantee."""
    bounded(reserve_bytes)
    bounded(new_entries, 3)
    catalog.require(type(files) is list and 1 <= len(files) <= 2, "invalid_payload_inventory")
    for size in files:
        bounded(size)
    unit = sample["allocation_unit_bytes"]
    available = bounded(sample["available_bytes"])
    if unit is not None:
        bounded(unit, 1 << 31)
        catalog.require(unit > 0, "invalid_allocation_unit")
    payload = bounded(sum(files))
    rounded = bounded(sum(((n + unit - 1) // unit) * unit if unit else n for n in files))
    required = bounded(rounded + reserve_bytes)
    inodes = sample["available_inodes"]
    if inodes is not None:
        bounded(inodes)
    return {"payload_bytes": payload, "payload_estimate_bytes": rounded,
            "estimate_basis": "rounded_data_bytes" if unit else "logical_data_bytes_allocation_unknown",
            "reserve_bytes": reserve_bytes, "required_with_reserve_bytes": required,
            "available_bytes_observed": available, "shortfall_bytes": max(0, required - available),
            "new_directory_entries": new_entries,
            "inode_check": "unknown" if inodes is None else "sufficient" if inodes >= new_entries else "insufficient",
            "read_only": sample["read_only"], "meets_byte_budget_at_observation": available >= required,
            "space_reserved": False, "write_success_guaranteed": False}


def assessment(remaining: int, saves: int, warn_records: int, budget: dict, *, source=True):
    """Stable issue codes for automation; never interpret them as permission."""
    bounded(remaining, 255)
    bounded(saves, 256)
    bounded(warn_records, 255)
    catalog.require(saves > 0, "positive_save_count_required")
    issues = []
    if source:
        if remaining < saves:
            issues.append("wallet_record_limit")
        elif remaining - saves <= warn_records:
            issues.append("wallet_record_headroom_low")
    if budget["read_only"] is True:
        issues.append("filesystem_read_only")
    if budget["inode_check"] == "insufficient":
        issues.append("directory_entry_budget_insufficient")
    if budget["available_bytes_observed"] < budget["payload_estimate_bytes"]:
        issues.append("payload_space_low")
    elif not budget["meets_byte_budget_at_observation"]:
        issues.append("disk_reserve_low")
    critical = {"wallet_record_limit", "filesystem_read_only", "directory_entry_budget_insufficient", "payload_space_low"}
    severity = "critical" if critical.intersection(issues) else "warning" if issues else "nominal"
    return {"severity": severity, "issues": issues, "exit_code": EXIT_CODES[severity]}


def operation_payload(operation: str, expected: str, snapshot: dict):
    catalog.require(operation in OPERATIONS, "unknown_maintenance_operation")
    manifest_bytes = len(catalog.canonical(archive.manifest_for(expected, snapshot)))
    size = snapshot["bytes"]
    if operation == "wallet-copy":
        return [size], 1, ["choose_new_output", "copy_with_original_backend", "retain_original_and_pin", "rescan_trusted_history"]
    if operation == "catalog-backup":
        return [size, manifest_bytes], 3, ["initialize_or_verify_catalog", "create_exact_version", "authenticate_backup", "retain_independent_pin"]
    if operation == "archive-export":
        return [archive.FRAME.size + manifest_bytes + size], 1, ["verify_catalog_version", "export_new_archive", "retain_independent_archive_digest_and_pin"]
    # A compacted journal has one authenticated record. It does NOT delete the
    # old journal or revoke old copies; no reclaimed bytes are credited here.
    return [catalog.HEADER + catalog.RECORD], 1, ["authenticate_pinned_backup_first", "compact_to_new_file", "retain_new_independent_pin", "rescan_and_compare_pending", "explicitly_select_one_active_copy"]


def inspect(wallet: Path, expected: str, password: bytes, backend: Backend, *, reserve_bytes: int,
            saves: int = 1, warn_records: int = 16, operation: str | None = None,
            target_directory: Path | None = None) -> dict:
    """Authenticate once, sample volumes, and recheck the original exact bytes.

    Only op9 is invoked. No balance, transaction, outbox, private path, receipt,
    digest identifying the wallet, or command to be executed is returned.
    """
    bounded(reserve_bytes)
    bounded(saves, 256)
    bounded(warn_records, 255)
    catalog.require(saves > 0 and ((operation is None) == (target_directory is None)), "invalid_health_request")
    if operation is not None:
        catalog.require(operation in OPERATIONS, "unknown_maintenance_operation")
    expected = catalog.receipt(expected)
    wallet = wallet.absolute()
    parent_id = directory_id(wallet.parent)
    target = catalog.directory(target_directory) if target_directory is not None else None
    target_id = directory_id(target) if target is not None else None
    before = catalog.wallet_snapshot(wallet, expected)
    # A regular file can be mounted from a different filesystem without being
    # a symlink. Never attribute its append budget to its parent volume.
    catalog.require(before["identity"][0] == parent_id[0], "wallet_parent_filesystem_mismatch")
    status = catalog.authenticate(backend, wallet, expected, password)
    checked_storage_status({"wallet_storage": status})
    catalog.require(status["file_bytes"] == before["bytes"], "wallet_capacity_changed")
    catalog.same_wallet(wallet, expected, before)
    source_disk = probe(wallet.parent, expected_identity=parent_id)
    source_budget = estimate([catalog.RECORD * saves], source_disk, reserve_bytes, 0)
    state = assessment(status["records_remaining"], saves, warn_records, source_budget)
    report = {"format": "zevune-wallet-health-1", "scope": "authenticated_file_capacity_only",
              "observed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
              "authenticated": True, "wallet_storage": status,
              "policy": {"requested_saves": saves, "warn_records": warn_records, "reserve_bytes": reserve_bytes},
              "source": {"disk": source_disk, "budget": source_budget, **state},
              "plan": None, "severity": state["severity"], "exit_code": state["exit_code"],
              "read_only": True, "requires_rescan": True, "latest_not_inferred": True,
              "operation_executed": False, "space_reserved": False, "real_funds_allowed": False}
    if operation is not None:
        # Equal directory inode/device does not identify per-mount policy.
        # In particular, a read-only bind alias needs its own path observation.
        disk = probe(target, expected_identity=target_id)
        files, entries, steps = operation_payload(operation, expected, before)
        budget = estimate(files, disk, reserve_bytes, entries)
        # A full source journal can still be copied/compacted. Its append alarm
        # stays visible separately; target suitability is assessed independently.
        target_state = assessment(status["records_remaining"], saves, warn_records, budget, source=False)
        report["plan"] = {"operation": operation, "disk": disk, "budget": budget, **target_state,
                          "ordered_steps": steps, "source_retained": True, "source_bytes_reclaimed": 0,
                          "alternative_not_cumulative": True, "destination_validated": False,
                          "permissions_validated": False, "catalog_slots_validated": False}
        report["exit_code"] = max(state["exit_code"], target_state["exit_code"])
        report["severity"] = next(k for k, v in EXIT_CODES.items() if v == report["exit_code"])
    catalog.same_wallet(wallet, expected, before)
    catalog.require(directory_id(wallet.parent) == parent_id
                    and (target is None or directory_id(target) == target_id), "volume_directory_changed")
    return report


class Parser(argparse.ArgumentParser):
    def error(self, message):
        # Do not echo unknown arguments, which may contain accidental secrets.
        self.exit(64, "Invalid health command. Use --help; passwords must not be arguments.\n")


def main(argv=None):
    parser = Parser(description=__doc__)
    parser.add_argument("--no-real-funds", action="store_true", required=True)
    subs = parser.add_subparsers(dest="command", required=True)
    for name in ("check", "plan"):
        sub = subs.add_parser(name)
        sub.add_argument("wallet", type=Path)
        sub.add_argument("--pin", required=True, help="Independently retained EXACT wallet receipt")
        sub.add_argument("--backend", required=True, type=Path)
        sub.add_argument("--backend-sha256", required=True)
        sub.add_argument("--reserve-bytes", required=True, help="Explicit advisory cushion, canonical nonnegative integer")
        sub.add_argument("--saves", default="1", help="Requested additional saves (not payments), 1..256")
        sub.add_argument("--warn-records", default="16", help="Warn at this remaining headroom after requested saves, 0..255")
        if name == "plan":
            sub.add_argument("--operation", choices=OPERATIONS, required=True)
            sub.add_argument("--target-directory", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        expected = catalog.receipt(args.pin)
        reserve, saves, warn = decimal(args.reserve_bytes), decimal(args.saves, 256), decimal(args.warn_records, 255)
        catalog.require(saves > 0, "positive_save_count_required")
        # Reject malformed inputs before prompting; authentication still uses
        # the real backend, never a hash-only fallback.
        catalog.wallet_snapshot(args.wallet.absolute(), expected)
        if args.command == "plan":
            catalog.directory(args.target_directory)
        backend = Backend(args.backend, args.backend_sha256)
        backend._check()
        password = hidden_password(False)
        result = inspect(args.wallet, expected, password, backend, reserve_bytes=reserve,
                         saves=saves, warn_records=warn,
                         operation=getattr(args, "operation", None), target_directory=getattr(args, "target_directory", None))
        print(json.dumps(result, ensure_ascii=True, indent=2))
        return result["exit_code"]
    except (ValueError, OSError, RuntimeError, subprocess.SubprocessError,
            getpass.GetPassWarning, EOFError, KeyboardInterrupt):
        print("Wallet capacity inspection not completed. No maintenance was executed. Preserve files and independent receipts; do not retry payments or clear reservations.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
