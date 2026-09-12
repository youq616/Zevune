#!/usr/bin/env python3
"""Verify a local lab bundle against an independently trusted manifest SHA-256.

No program is launched and no file is changed. A checksum is not a signature,
security audit, license clearance, or protection against a compromised machine.
Run this verifier from trusted source, not from an unverified download.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
from typing import Any

MANIFEST = "BUNDLE-MANIFEST.json"
MAX_MANIFEST_BYTES = 64 * 1024
MAX_FILE_BYTES = 128 * 1024 * 1024
HEX256 = re.compile(r"[0-9a-f]{64}\Z")
HEX160 = re.compile(r"[0-9a-f]{40}\Z")


def linked(info: os.stat_result) -> bool:
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0)
        & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


def fingerprint(path: Path, maximum: int, capture: bool = False) -> tuple[int, str, bytes]:
    before = path.lstat()
    if linked(before) or not stat.S_ISREG(before.st_mode) or not 0 <= before.st_size <= maximum:
        raise ValueError("nonregular_or_oversized_file")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    digest, total = hashlib.sha256(), 0
    contents = bytearray()
    with os.fdopen(descriptor, "rb") as file:
        opened = os.fstat(file.fileno())
        if not os.path.samestat(before, opened) or not stat.S_ISREG(opened.st_mode):
            raise ValueError("file_identity_changed")
        while True:
            chunk = file.read(min(1024 * 1024, maximum - total + 1))
            if not chunk:
                break
            total += len(chunk)
            if total > maximum:
                raise ValueError("file_grew_past_limit")
            digest.update(chunk)
            if capture:
                contents.extend(chunk)
        after = os.fstat(file.fileno())
    current = path.lstat()
    if (total != before.st_size or after.st_size != before.st_size
            or after.st_mtime_ns != before.st_mtime_ns
            or linked(current) or not os.path.samestat(before, current)):
        raise ValueError("file_changed_during_check")
    return total, digest.hexdigest(), bytes(contents)


def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            raise ValueError("duplicate_manifest_field")
        out[key] = value
    return out


def required_files(windows: bool) -> set[str]:
    suffix = ".exe" if windows else ""
    return {name + suffix for name in ("zevune-network", "zevune-pool-worker", "zevune-wallet-local")} | {
        "zevune_wallet.py", "LOCAL_NETWORK_OPERATOR.zh-CN.md"}


def verify(folder: Path, manifest_sha256: str, source_commit: str | None = None) -> dict[str, Any]:
    if not isinstance(manifest_sha256, str) or not HEX256.fullmatch(manifest_sha256):
        raise ValueError("independent_manifest_digest_required")
    if source_commit is not None and not HEX160.fullmatch(source_commit):
        raise ValueError("invalid_expected_commit")
    info = folder.lstat()
    if not folder.is_absolute() or linked(info) or not stat.S_ISDIR(info.st_mode):
        raise ValueError("explicit_regular_bundle_directory_required")
    _, digest, raw = fingerprint(folder / MANIFEST, MAX_MANIFEST_BYTES, capture=True)
    if digest != manifest_sha256:
        raise ValueError("manifest_digest_mismatch")
    manifest = json.loads(raw.decode("utf-8"), object_pairs_hook=unique)
    fields = {"format", "source_commit", "source_tree", "build_source", "real_funds_allowed",
              "public_network_supported", "network_anonymity_implemented", "scope", "toolchains", "files"}
    if not isinstance(manifest, dict) or set(manifest) != fields:
        raise ValueError("unsupported_manifest_fields")
    if (manifest["format"] != "zevune-local-bundle-2"
            or manifest["scope"] != "single_machine_fixed_validator_test_lab"
            or manifest["build_source"] != "isolated_exact_git_blobs"
            or any(manifest[k] is not False for k in ("real_funds_allowed", "public_network_supported", "network_anonymity_implemented"))):
        raise ValueError("unsupported_bundle_policy")
    if any(not isinstance(manifest[k], str) or not HEX160.fullmatch(manifest[k])
           for k in ("source_commit", "source_tree")):
        raise ValueError("invalid_source_identity")
    if source_commit is not None and manifest["source_commit"] != source_commit:
        raise ValueError("source_commit_mismatch")
    versions = manifest["toolchains"]
    if (not isinstance(versions, dict) or set(versions) != {"go", "rust"}
            or any(not isinstance(v, str) or len(v) > 256 for v in versions.values())
            or not versions["go"].startswith("go version go1.27.1 ")
            or not versions["rust"].startswith("rustc 1.98.1 ")):
        raise ValueError("unexpected_toolchains")
    entries = manifest["files"]
    if not isinstance(entries, list) or len(entries) != 5:
        raise ValueError("unexpected_file_count")
    names: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {"name", "size", "sha256"}:
            raise ValueError("invalid_file_entry")
        name, size, checksum = entry["name"], entry["size"], entry["sha256"]
        if (not isinstance(name, str) or name in names
                or name not in required_files(False) | required_files(True)
                or type(size) is not int or not 1 <= size <= MAX_FILE_BYTES
                or not isinstance(checksum, str) or not HEX256.fullmatch(checksum)):
            raise ValueError("invalid_file_identity")
        names.add(name)
    if names not in (required_files(False), required_files(True)):
        raise ValueError("mixed_or_missing_platform_files")
    if {p.name for p in folder.iterdir()} != names | {MANIFEST}:
        raise ValueError("unlisted_or_missing_bundle_files")
    for entry in entries:
        size, checksum, _ = fingerprint(folder / entry["name"], MAX_FILE_BYTES)
        if size != entry["size"] or checksum != entry["sha256"]:
            raise ValueError("file_digest_or_size_mismatch")
    # Recheck the pin after reading files; verification is not a future-use lock.
    if fingerprint(folder / MANIFEST, MAX_MANIFEST_BYTES)[1] != digest:
        raise ValueError("manifest_changed_during_check")
    return {"integrity_verified": True, "source_commit": manifest["source_commit"],
            "source_tree": manifest["source_tree"], "files_checked": len(entries),
            "code_signature_verified": False, "real_funds_allowed": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--source-commit")
    args = parser.parse_args()
    try:
        result = verify(args.bundle.absolute(), args.manifest_sha256, args.source_commit)
    except (OSError, ValueError, RecursionError):
        print("Bundle integrity verification failed; nothing was executed or modified.", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
