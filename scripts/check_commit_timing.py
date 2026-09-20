"""Validate public in-process commit timing evidence, never authorize a ledger.

No network, wallet access, decoding transactions or performance acceptance.
A valid report still requires the exact native CI job to have succeeded.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any

PHASES = (
    "preflight", "reexecute", "encode_frame", "append_bounds",
    "tail_identity_and_rotation_decision", "rotation_prepare", "seek",
    "write_frame", "file_sync", "directory_sync", "postwrite_identity",
    "journal_metadata_publish", "state_publish",
)
BLOCKS = 8192
LIMIT = 16 * 1024


def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in items:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def read(path: Path, bound: int) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > bound:
        raise ValueError("invalid evidence file")
    with path.open("rb") as stream:
        raw = stream.read(bound + 1)
    if len(raw) > bound:
        raise ValueError("evidence exceeds bound")
    data = json.loads(raw, object_pairs_hook=pairs,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite number")))
    if type(data) is not dict:
        raise ValueError("evidence is not an object")
    return data


def number(value: Any, limit: int = 3_600_000_000_000_000_000) -> int:
    if type(value) is not int or not 0 <= value <= limit:
        raise ValueError("invalid bounded integer")
    return value


def validate(data: dict[str, Any]) -> dict[str, Any]:
    if (set(data) != {"blocks", "control_bytes_equal", "replay_and_continuation", "real_funds_allowed", "profile"}
            or number(data["blocks"]) != BLOCKS
            or data["control_bytes_equal"] is not True
            or data["replay_and_continuation"] is not True
            or data["real_funds_allowed"] is not False):
        raise ValueError("incomplete native experiment")
    p = data["profile"]
    if (type(p) is not dict or set(p) != {
            "schema_version", "scope", "valid", "attempts", "accepted", "failed",
            "last_accepted_height", "paid", "rotated", "accepted_commit_total_ns",
            "accepted_commit_max_ns", "phases", "last_failed_attempt"}):
        raise ValueError("invalid profile schema")
    if (number(p["schema_version"]) != 1
            or p["scope"] != "test_store_internal_not_worker_ipc" or p["valid"] is not True
            or number(p["attempts"]) != BLOCKS or number(p["accepted"]) != BLOCKS
            or number(p["failed"]) != 0 or number(p["last_accepted_height"]) != BLOCKS
            or number(p["paid"]) != 2 or number(p["rotated"]) != 2
            or p["last_failed_attempt"] is not None):
        raise ValueError("incomplete profile")
    total = number(p["accepted_commit_total_ns"])
    maximum = number(p["accepted_commit_max_ns"])
    if total == 0 or maximum > total or total > maximum * BLOCKS:
        raise ValueError("invalid total timing")
    phases = p["phases"]
    if type(phases) is not list or len(phases) != len(PHASES):
        raise ValueError("incomplete phase inventory")
    summed = 0
    for name, item in zip(PHASES, phases):
        if type(item) is not dict or set(item) != {"name", "ordinary_count", "ordinary_total_ns", "ordinary_max_ns", "rotating_count", "rotating_total_ns", "rotating_max_ns"} or item["name"] != name:
            raise ValueError("invalid phase schema/order")
        ordinary = 0 if name in ("rotation_prepare", "directory_sync") else BLOCKS - 2
        for group, expected in (("ordinary", ordinary), ("rotating", 2)):
            count = number(item[group + "_count"])
            duration = number(item[group + "_total_ns"])
            largest = number(item[group + "_max_ns"])
            if count != expected or largest > duration or duration > largest * count or largest > maximum:
                raise ValueError("invalid phase count/timing")
            summed += duration
    if summed > total:
        raise ValueError("overlapping phase aggregates")
    return p


def oid(value: str) -> str:
    if not re.fullmatch(r"[0-9a-f]{40}", value):
        raise ValueError("invalid Git identity")
    return value


def identity() -> dict[str, Any]:
    def git(ref: str) -> str:
        return oid(subprocess.check_output(["git", "--no-replace-objects", "rev-parse", ref], text=True).strip())
    run, attempt = os.environ["GITHUB_RUN_ID"], os.environ["GITHUB_RUN_ATTEMPT"]
    if not all(re.fullmatch(r"[1-9][0-9]{0,19}", n) for n in (run, attempt)):
        raise ValueError("invalid run identity")
    if sys.platform not in ("linux", "win32"):
        raise ValueError("unsupported platform")
    return dict(schema_version=1, source_head=oid(os.environ["ZEVUNE_TIMING_SOURCE_HEAD"]),
                checkout_commit=git("HEAD"), checkout_tree=git("HEAD^{tree}"),
                run_id=int(run), run_attempt=int(attempt), platform=sys.platform,
                scope="in_process_storage_experiment", real_funds_allowed=False)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("setup", "verify"))
    args = parser.parse_args()
    try:
        folder = Path(os.environ["RUNNER_TEMP"]) / "zevune-commit-timing"
        if args.mode == "setup":
            folder.mkdir(mode=0o700)
            raw = json.dumps(identity(), sort_keys=True).encode() + b"\n"
            if len(raw) > 2048:
                raise ValueError("identity exceeds bound")
            with (folder / "setup.json").open("xb") as stream:
                stream.write(raw)
            with open(os.environ["GITHUB_ENV"], "a", encoding="utf-8") as env:
                env.write("ZEVUNE_COMMIT_TIMING_DIR=" + str(folder) + "\n")
        else:
            if folder.is_symlink() or not folder.is_dir():
                raise ValueError("invalid evidence directory")
            if set(p.name for p in folder.iterdir()) != {"setup.json", "profile.json"}:
                raise ValueError("missing or extra evidence files")
            actual, expected = read(folder / "setup.json", 2048), identity()
            if (actual != expected or set(actual) != set(expected)
                    or any(type(actual[key]) is not type(value) for key, value in expected.items())):
                raise ValueError("source/run identity changed")
            validate(read(folder / "profile.json", LIMIT))
            print("COMMIT_TIMING_EVIDENCE_VALIDATED (not a CI-success or fund-safety certificate)")
        return 0
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError):
        print("COMMIT_TIMING_EVIDENCE_REJECTED", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
