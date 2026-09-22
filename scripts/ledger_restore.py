#!/usr/bin/env python3
"""Restore a fixed independently pinned PUBLIC ledger chain into a NEW workspace.

One base plus at most eight strictly growing incremental packages. Retain every
stage on success or failure; never activate a validator, modify a signer, prune,
resume, infer a latest checkpoint or import a trusted state snapshot.
"""
from __future__ import annotations

import sys
if __name__ == "__main__":
    sys.dont_write_bytecode = True

import argparse
import hashlib
import os
from pathlib import Path
import subprocess
import time

import wallet_backup as files
import wallet_health as space
from wallet_backup_backend import file_object_identity
from ledger_recovery_backend import (Checkpoint, RecoveryBackend, MAX_BYTES, MAX_PACKAGE,
                                     SEGMENT_BYTES, ordered, remaining, require)

MARKER = "RECOVERY.json"
CHAIN_SECONDS = 1800


def stage(index):
    require(type(index) is int and 0 <= index <= 8, "invalid_stage")
    return f"stage-{index:02}"


def check_time(deadline):
    if deadline is not None:
        remaining(deadline)


def snapshot(path, maximum, *, deadline=None):
    """Bounded damage/identity fingerprint, never authorization or a file lock."""
    check_time(deadline)
    path = path.absolute()
    files.directory(path.parent)
    before = path.lstat()
    require(files.regular(before) and 0 <= before.st_size <= maximum, "invalid_recovery_file")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_BINARY", 0)
    digest, prefix, length = hashlib.sha256(), bytearray(), 0
    with os.fdopen(os.open(path, flags), "rb") as stream:
        opened = os.fstat(stream.fileno())
        require(file_object_identity(opened) == file_object_identity(before), "recovery_input_changed")
        while True:
            check_time(deadline)
            chunk = stream.read(min(65536, maximum-length+1))
            check_time(deadline)
            if not chunk:
                break
            length += len(chunk)
            require(length <= maximum, "recovery_input_grew")
            digest.update(chunk)
            prefix.extend(chunk[:max(0, 268-len(prefix))])
        require(files.identity(opened) == files.identity(os.fstat(stream.fileno())), "recovery_input_changed")
    require(files.identity(path.lstat()) == files.identity(before) and length == before.st_size,
            "recovery_input_changed")
    check_time(deadline)
    return files.identity(before), digest.hexdigest(), bytes(prefix)


def names(root, expected, *, deadline=None):
    check_time(deadline)
    seen = set()
    with os.scandir(root) as entries:
        for entry in entries:
            check_time(deadline)
            require(entry.name in expected and entry.name not in seen, "unexpected_recovery_entry")
            seen.add(entry.name)
    require(seen == expected, "incomplete_recovery_inventory")
    check_time(deadline)


def archive_snapshot(path, pin, *, deadline=None):
    check_time(deadline)
    path = files.directory(path)
    identity = space.directory_id(path)
    expected = {"genesis"} | {f"{i:08}.journal" for i in range(pin.segments)}
    names(path, expected, deadline=deadline)
    captured, length = {}, 0
    for name in sorted(expected):
        limit = pin.header if name == "genesis" else SEGMENT_BYTES
        info, digest, _ = snapshot(path / name, limit, deadline=deadline)
        size = info[2]
        require(size == pin.header if name == "genesis" else 150 <= size <= SEGMENT_BYTES,
                "invalid_archive_extent")
        length += size
        captured[name] = (info, digest)
    names(path, expected, deadline=deadline)
    require(length == pin.length and space.directory_id(path) == identity, "archive_changed")
    check_time(deadline)
    return identity, captured


def package_snapshot(path, base, pin, *, deadline=None):
    result = snapshot(path, MAX_PACKAGE, deadline=deadline)
    identity, _, prefix = result
    require(len(prefix) == 268 and prefix[:8] == b"ZVAIPK01"
            and prefix[8:136].hex() == base.encoded and prefix[136:264].hex() == pin.encoded,
            "package_does_not_match_independent_pins")
    count = int.from_bytes(prefix[264:268], "big")
    require(1 <= count <= 2048 and identity[2] == 268+12*count+pin.length-base.length,
            "package_extent_mismatch")
    check_time(deadline)
    return result


def marker(pins):
    # Determined solely by caller pins and fixed fields, NOT parsed trust input.
    raw = files.canonical(dict(format="zevune-ledger-recovery-chain-1",
                               checkpoints=[p.encoded for p in pins],
                               snapshot_imported=False, finality_verified=False,
                               validator_ready=False, real_funds_allowed=False))
    require(len(raw) <= files.MAX_MANIFEST, "recovery_receipt_bounds")
    return raw


def budget(parent, parent_id, pins, reserve, *, deadline=None):
    check_time(deadline)
    space.bounded(reserve)
    sample = space.probe(parent, expected_identity=parent_id)
    unit = sample["allocation_unit_bytes"]
    count = sum(p.segments+1 for p in pins)
    # Segment lengths are not all encoded in pins. Round conservatively by
    # charging at most unit-1 extra bytes for EACH retained physical file.
    amount = sum(p.length for p in pins) + (count*(unit-1) if unit else 0)
    amount += ((files.MAX_MANIFEST+unit-1)//unit)*unit if unit else files.MAX_MANIFEST
    required = space.bounded(amount+reserve)
    entries = count+len(pins)+2  # files, stage directories, workspace, marker
    require(sample["read_only"] is not True and sample["available_bytes"] >= required,
            "recovery_space_budget_insufficient")
    require(sample["available_inodes"] is None or sample["available_inodes"] >= entries,
            "recovery_entries_insufficient")
    check_time(deadline)
    return required


def verify_archives(root, pins, backend, deadline, complete):
    check_time(deadline)
    root = files.directory(root)
    root_id = space.directory_id(root)
    expected = {stage(i) for i in range(len(pins))} | ({MARKER} if complete else set())
    names(root, expected, deadline=deadline)
    captured = [archive_snapshot(root / stage(i), p, deadline=deadline) for i, p in enumerate(pins)]
    for i, pin in enumerate(pins):
        check_time(deadline)
        backend.active(root / stage(i), pin, deadline)
        check_time(deadline)
        if i:
            # Independently prove byte-prefix relation again during verification,
            # not merely that both unrelated endpoints are valid ledgers.
            backend.incremental(root / stage(i-1), pins[i-1], root / stage(i), pin, deadline)
    for i, pin in enumerate(pins):
        require(archive_snapshot(root / stage(i), pin, deadline=deadline) == captured[i], "recovered_archive_changed")
    names(root, expected, deadline=deadline)
    require(space.directory_id(root) == root_id, "recovery_workspace_changed")
    check_time(deadline)
    return captured


def report(pins, operation):
    return dict(operation=operation, format="zevune-ledger-recovery-chain-1",
                completed=True, checkpoints=[p.encoded for p in pins],
                final_stage=stage(len(pins)-1), height=pins[-1].height,
                app_hash=pins[-1].app_hash, retained_logical_bytes=sum(p.length for p in pins),
                input_sources_rechecked=operation == "restore", snapshot_imported=False,
                finality_verified=False, validator_ready=False, real_funds_allowed=False)


def verify(root, checkpoints, backend):
    deadline = time.monotonic()+CHAIN_SECONDS
    check_time(deadline)
    pins = ordered(checkpoints)
    root = files.directory(root)
    raw, identity = files.read_file(root / MARKER, files.MAX_MANIFEST)
    check_time(deadline)
    require(raw == marker(pins), "independent_chain_checkpoint_mismatch")
    verify_archives(root, pins, backend, deadline, True)
    require(files.read_file(root / MARKER, files.MAX_MANIFEST) == (raw, identity), "recovery_receipt_changed")
    check_time(deadline)
    return report(pins, "verify")


def restore(base, base_checkpoint, steps, output, backend, *, reserve_bytes):
    deadline = time.monotonic()+CHAIN_SECONDS
    check_time(deadline)
    require(type(steps) is list and len(steps) <= 8
            and all(type(item) in (tuple, list) and len(item) == 2 for item in steps), "invalid_recovery_steps")
    pins = ordered([base_checkpoint]+[item[1] for item in steps])
    space.bounded(reserve_bytes)
    base = files.directory(base)
    output = files.new_file(output)
    require(base != output.parent and base not in output.parent.parents, "output_inside_base")
    parent_id = space.directory_id(output.parent)
    packages = [Path(item[0]).absolute() for item in steps]
    saved_base = archive_snapshot(base, pins[0], deadline=deadline)
    saved_packages = [package_snapshot(p, pins[i], pins[i+1], deadline=deadline) for i, p in enumerate(packages)]
    check_time(deadline)
    backend.active(base, pins[0], deadline)
    budget(output.parent, parent_id, pins, reserve_bytes, deadline=deadline)
    require(archive_snapshot(base, pins[0], deadline=deadline) == saved_base
            and space.directory_id(output.parent) == parent_id, "recovery_inputs_changed")
    check_time(deadline)
    output.mkdir(mode=0o700)  # exclusive claim: no resume, overwrite or cleanup
    root_id = space.directory_id(output)
    check_time(deadline)
    backend.active(base, pins[0], deadline, output / stage(0))
    for i, package in enumerate(packages, 1):
        check_time(deadline)
        require(space.directory_id(output) == root_id, "recovery_workspace_changed")
        names(output, {stage(j) for j in range(i)}, deadline=deadline)
        require(package_snapshot(package, pins[i-1], pins[i], deadline=deadline) == saved_packages[i-1], "increment_changed")
        backend.incremental(output / stage(i-1), pins[i-1], package, pins[i], deadline, output / stage(i))
    verified_outputs = verify_archives(output, pins, backend, deadline, False)
    check_time(deadline)
    backend.active(base, pins[0], deadline)
    check_time(deadline)
    require(archive_snapshot(base, pins[0], deadline=deadline) == saved_base, "base_archive_changed")
    for i, package in enumerate(packages):
        require(package_snapshot(package, pins[i], pins[i+1], deadline=deadline) == saved_packages[i], "increment_changed")
    require(space.directory_id(output) == root_id and space.directory_id(output.parent) == parent_id,
            "recovery_workspace_changed")
    raw = marker(pins)
    check_time(deadline)
    files.write_new(output / MARKER, raw)
    check_time(deadline)
    files.sync_directory(output)
    check_time(deadline)
    files.sync_directory(output.parent)
    check_time(deadline)
    observed, _ = files.read_file(output / MARKER, files.MAX_MANIFEST)
    names(output, {stage(i) for i in range(len(pins))} | {MARKER}, deadline=deadline)
    require(observed == raw and space.directory_id(output) == root_id, "recovery_receipt_changed")
    for i, pin in enumerate(pins):
        require(archive_snapshot(output / stage(i), pin, deadline=deadline) == verified_outputs[i], "recovered_archive_changed")
    check_time(deadline)
    return report(pins, "restore")


class Parser(argparse.ArgumentParser):
    def error(self, message):
        self.exit(64, "Invalid ledger recovery arguments. Use --help.\n")


def main(argv=None):
    parser = Parser(description=__doc__)
    parser.add_argument("--no-real-funds", required=True, action="store_true")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("restore", "verify"):
        cmd = commands.add_parser(name)
        cmd.add_argument("directory", type=Path)
        cmd.add_argument("--backend", type=Path, required=True)
        cmd.add_argument("--backend-sha256", required=True)
        if name == "restore":
            cmd.add_argument("--base", type=Path, required=True)
            cmd.add_argument("--base-checkpoint", required=True)
            cmd.add_argument("--step", nargs=2, action="append", default=[], metavar=("PACKAGE", "CHECKPOINT"))
            cmd.add_argument("--reserve-bytes", required=True)
        else:
            cmd.add_argument("--checkpoint", action="append", required=True)
    args = parser.parse_args(argv)
    try:
        backend = RecoveryBackend(args.backend, args.backend_sha256)
        if args.command == "restore":
            ordered([args.base_checkpoint]+[item[1] for item in args.step])
            reserve = space.decimal(args.reserve_bytes)
            files.new_file(args.directory)
            print("Restore PUBLIC ledger archives only. Keep all originals and every output; no validator or signer is activated.", file=sys.stderr)
            print("Type RESTORE-CHAIN to create a NEW workspace: ", end="", file=sys.stderr, flush=True)
            require(input() == "RESTORE-CHAIN", "recovery_not_confirmed")
            result = restore(args.base, args.base_checkpoint, args.step, args.directory, backend, reserve_bytes=reserve)
        else:
            result = verify(args.directory, args.checkpoint, backend)
        sys.stdout.write(files.canonical(result).decode("ascii"))
        return 0
    except (ValueError, OSError, RuntimeError, RecursionError, subprocess.SubprocessError, EOFError, KeyboardInterrupt):
        print("Ledger recovery not completed. Retain original and partial/complete outputs. Do not retry blindly, activate a validator, or reset signer state.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
