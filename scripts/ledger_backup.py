#!/usr/bin/env python3
"""Create an independently pinned PUBLIC baseline plus up to eight incrementals.

Read stopped source archives; create a new delivery directory; retain all inputs
and partial outputs. Inspection is public-byte consistency, not native replay.
No wallet, signer, validator activation, latest inference, pruning or retry.
"""
from __future__ import annotations

import sys
if __name__ == "__main__":
    sys.dont_write_bytecode = True

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import time

import ledger_restore as recovery
from ledger_recovery_backend import RecoveryBackend, ordered, remaining, require

FORMAT = "zevune-ledger-backup-set-1"
MARKER = "BACKUP.json"
BASE = "base"
SET_SECONDS = 1800


def increment(index):
    require(type(index) is int and 1 <= index <= 8, "invalid_backup_increment")
    return f"increment-{index:02}.zvaipk"


def layout(captured):
    # Names and lengths are part of this damage fingerprint. This digest never
    # replaces the independently supplied checkpoint or native authorization.
    files = [[name, info[2], digest] for name, (info, digest) in sorted(captured[1].items())]
    return hashlib.sha256(recovery.files.canonical(files)).hexdigest()


def capture(root, pins, deadline, *, complete):
    remaining(deadline)
    root = recovery.files.directory(root)
    identity = recovery.space.directory_id(root)
    expected = {BASE} | {increment(i) for i in range(1, len(pins))}
    if complete:
        expected.add(MARKER)
    recovery.names(root, expected, deadline=deadline)
    baseline = recovery.archive_snapshot(root / BASE, pins[0], deadline=deadline)
    packages = [recovery.package_snapshot(root / increment(i), pins[i-1], pins[i], deadline=deadline)
                for i in range(1, len(pins))]
    recovery.names(root, expected, deadline=deadline)
    require(recovery.space.directory_id(root) == identity, "backup_set_changed")
    remaining(deadline)
    return identity, baseline, packages


def marker(pins, baseline, packages):
    raw = recovery.files.canonical(dict(
        format=FORMAT, checkpoints=[p.encoded for p in pins],
        baseline_bytes=pins[0].length, baseline_layout_sha256=layout(baseline),
        increments=[dict(bytes=p[0][2], sha256=p[1]) for p in packages],
        snapshot_imported=False, finality_verified=False, validator_ready=False,
        real_funds_allowed=False))
    require(len(raw) <= recovery.files.MAX_MANIFEST, "backup_marker_bounds")
    return raw


def budget(parent, identity, baseline, package_sizes, reserve, deadline):
    remaining(deadline)
    recovery.space.bounded(reserve)
    sample = recovery.space.probe(parent, expected_identity=identity)
    unit = sample["allocation_unit_bytes"]
    sizes = [info[2] for info, _ in baseline[1].values()] + package_sizes + [recovery.files.MAX_MANIFEST]
    total = sum(((size + unit-1)//unit)*unit if unit else size for size in sizes)
    required = recovery.space.bounded(total + reserve)
    # Each payload/marker, plus the delivery directory and its baseline child.
    entries = len(sizes) + 2
    require(sample["read_only"] is not True and sample["available_bytes"] >= required,
            "backup_space_budget_insufficient")
    require(sample["available_inodes"] is None or sample["available_inodes"] >= entries,
            "backup_directory_entries_insufficient")
    remaining(deadline)
    return required


def report(pins, packages, operation):
    return dict(format=FORMAT, operation=operation, completed=True,
                checkpoints=[p.encoded for p in pins], height=pins[-1].height,
                package_count=len(packages), stored_logical_bytes=pins[0].length + sum(p[0][2] for p in packages),
                replay_verified=operation == "create", inspection_is_authentication=False,
                source_inputs_rechecked=operation == "create", snapshot_imported=False,
                finality_verified=False, validator_ready=False, real_funds_allowed=False)


def inspect(root, checkpoints):
    deadline = time.monotonic() + SET_SECONDS
    pins = ordered(checkpoints)
    root = recovery.files.directory(root)
    # The marker supplies neither trust, paths nor backend commands: reconstruct
    # the one canonical value from EXTERNAL pins and bounded public bytes.
    before = capture(root, pins, deadline, complete=True)
    raw, identity = recovery.files.read_file(root / MARKER, recovery.files.MAX_MANIFEST)
    remaining(deadline)
    require(raw == marker(pins, before[1], before[2]), "backup_marker_mismatch")
    require(capture(root, pins, deadline, complete=True) == before, "backup_set_changed")
    require(recovery.files.read_file(root / MARKER, recovery.files.MAX_MANIFEST) == (raw, identity),
            "backup_marker_changed")
    remaining(deadline)
    return report(pins, before[2], "inspect")


def create(sources, output, backend, *, reserve_bytes):
    deadline = time.monotonic() + SET_SECONDS
    require(type(sources) is list and 1 <= len(sources) <= 9
            and all(type(item) in (tuple, list) and len(item) == 2 for item in sources),
            "one_to_nine_pinned_sources_required")
    pins = ordered([item[1] for item in sources])
    paths = [recovery.files.directory(Path(item[0])) for item in sources]
    require(len(set(paths)) == len(paths), "duplicate_backup_source")
    output = recovery.files.new_file(output)
    require(all(path != output.parent and path not in output.parent.parents for path in paths),
            "backup_output_inside_source")
    parent_id = recovery.space.directory_id(output.parent)
    originals = [recovery.archive_snapshot(path, pin, deadline=deadline) for path, pin in zip(paths, pins)]
    sizes = []
    for i, (path, pin) in enumerate(zip(paths, pins)):
        backend.active(path, pin, deadline)
        if i:
            plan = backend.incremental(paths[i-1], pins[i-1], path, pin, deadline)
            sizes.append(268 + 12*len(plan["ranges"]) + pin.length-pins[i-1].length)
    # Finish every authentic pairwise-prefix check BEFORE claiming an output.
    budget(output.parent, parent_id, originals[0], sizes, reserve_bytes, deadline)
    for path, pin, original in zip(paths, pins, originals):
        require(recovery.archive_snapshot(path, pin, deadline=deadline) == original, "backup_source_changed")
    require(recovery.space.directory_id(output.parent) == parent_id, "backup_parent_changed")
    remaining(deadline)
    output.mkdir(mode=0o700)
    root_id = recovery.space.directory_id(output)
    backend.backup(paths[0], pins[0], deadline, output / BASE)
    saved_baseline = recovery.archive_snapshot(output / BASE, pins[0], deadline=deadline)
    require(layout(saved_baseline) == layout(originals[0]), "backup_baseline_changed")
    saved_packages = []
    for i in range(1, len(pins)):
        remaining(deadline)
        require(recovery.space.directory_id(output) == root_id, "backup_set_changed")
        recovery.names(output, {BASE} | {increment(j) for j in range(1, i)}, deadline=deadline)
        backend.package(paths[i-1], pins[i-1], paths[i], pins[i], deadline, output / increment(i))
        saved = recovery.package_snapshot(output / increment(i), pins[i-1], pins[i], deadline=deadline)
        backend.package(paths[i-1], pins[i-1], output / increment(i), pins[i], deadline)
        require(recovery.package_snapshot(output / increment(i), pins[i-1], pins[i], deadline=deadline) == saved,
                "backup_package_changed")
        saved_packages.append(saved)
    backend.active(output / BASE, pins[0], deadline)
    captured = capture(output, pins, deadline, complete=False)
    require(captured == (root_id, saved_baseline, saved_packages), "backup_verified_outputs_changed")
    require([p[0][2] for p in captured[2]] == sizes, "backup_package_extent_changed")
    for path, pin, original in zip(paths, pins, originals):
        require(recovery.archive_snapshot(path, pin, deadline=deadline) == original, "backup_source_changed")
    require(recovery.space.directory_id(output.parent) == parent_id, "backup_parent_changed")
    remaining(deadline)
    raw = marker(pins, captured[1], captured[2])
    recovery.files.write_new(output / MARKER, raw)
    remaining(deadline)
    recovery.files.sync_directory(output)
    remaining(deadline)
    recovery.files.sync_directory(output.parent)
    remaining(deadline)
    observed, _ = recovery.files.read_file(output / MARKER, recovery.files.MAX_MANIFEST)
    require(observed == raw and capture(output, pins, deadline, complete=True) == captured,
            "backup_set_changed")
    for path, pin, original in zip(paths, pins, originals):
        require(recovery.archive_snapshot(path, pin, deadline=deadline) == original, "backup_source_changed")
    require(recovery.space.directory_id(output.parent) == parent_id, "backup_parent_changed")
    remaining(deadline)
    return report(pins, captured[2], "create")


class Parser(argparse.ArgumentParser):
    def error(self, message):
        self.exit(64, "Invalid ledger backup arguments. Use --help.\n")


def main(argv=None):
    parser = Parser(description=__doc__)
    parser.add_argument("--no-real-funds", required=True, action="store_true")
    commands = parser.add_subparsers(dest="command", required=True)
    write = commands.add_parser("create")
    write.add_argument("directory", type=Path)
    write.add_argument("--source", nargs=2, action="append", required=True, metavar=("ARCHIVE", "CHECKPOINT"))
    write.add_argument("--backend", type=Path, required=True)
    write.add_argument("--backend-sha256", required=True)
    write.add_argument("--reserve-bytes", required=True)
    read = commands.add_parser("inspect")
    read.add_argument("directory", type=Path)
    read.add_argument("--checkpoint", action="append", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "create":
            ordered([item[1] for item in args.source])
            reserve = recovery.space.decimal(args.reserve_bytes)
            recovery.files.new_file(args.directory)
            backend = RecoveryBackend(args.backend, args.backend_sha256)
            print("Create PUBLIC ledger backups only. Stop writers and retain all checkpoints/inputs. No validator is activated.", file=sys.stderr)
            print("Type BACKUP-CHAIN to create a NEW backup set: ", end="", file=sys.stderr, flush=True)
            require(input() == "BACKUP-CHAIN", "backup_not_confirmed")
            result = create(args.source, args.directory, backend, reserve_bytes=reserve)
        else:
            result = inspect(args.directory, args.checkpoint)
        print(json.dumps(result, separators=(",", ":")))
        return 0
    except (ValueError, OSError, RuntimeError, subprocess.SubprocessError, EOFError, KeyboardInterrupt):
        print("Ledger backup not completed. Retain inputs and partial/complete outputs; do not retry blindly or activate a validator.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
