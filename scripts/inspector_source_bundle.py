#!/usr/bin/env python3
"""Build/verify a fixed, source-only NO-FUNDS inspector delivery directory.

Run THIS tool from trusted source, outside an unverified delivery. Verification
never imports or executes payloads. A trusted manifest digest is not a signature,
code review, secure installation, or a lock protecting subsequent execution.
"""
from __future__ import annotations

import sys
if __name__ == "__main__":
    sys.dont_write_bytecode = True

import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess

MANIFEST = "INSPECTOR-SOURCE.json"
FORMAT = "zevune-inspector-source-1"
MAX_FILE = 512 * 1024
MAX_TOTAL = 4 * 1024 * 1024
MAX_MANIFEST = 32 * 1024
OID = re.compile(r"[0-9a-f]{40}\Z")
DIGEST = re.compile(r"[0-9a-f]{64}\Z")
# Versioned closed contract: no discovery of arbitrary wallet-named source/data.
SOURCES = {name + ".py": "scripts/" + name + ".py" for name in (
    "wallet_inspector_desktop", "wallet_reconcile", "wallet_health",
    "wallet_backup_backend", "wallet_backup", "wallet_archive",
    "ledger_restore", "ledger_recovery_backend", "zevune_wallet")}
SOURCES["WALLET_INSPECTOR_DESKTOP.zh-CN.md"] = "docs/WALLET_INSPECTOR_DESKTOP.zh-CN.md"


def require(condition: bool, code: str) -> None:
    if not condition:
        raise ValueError(code)


def identity(value: str, pattern: re.Pattern) -> bool:
    return type(value) is str and pattern.fullmatch(value) is not None


def linked(info: os.stat_result) -> bool:
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0)
        & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


def stamp(info: os.stat_result) -> tuple:
    return (info.st_dev, info.st_ino, info.st_mode, info.st_nlink,
            info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def directory_chain(path: Path) -> tuple:
    require(isinstance(path, Path) and path.is_absolute() and ".." not in path.parts,
            "explicit_absolute_directory_required")
    chain = []
    for part in (*reversed(path.parents), path):
        info = part.lstat()
        require(not linked(info) and stat.S_ISDIR(info.st_mode), "plain_directory_required")
        chain.append((str(part), info.st_dev, info.st_ino, info.st_mode))
    return tuple(chain)


def read_plain(path: Path, maximum: int) -> tuple[bytes, tuple]:
    before = path.lstat()
    require(not linked(before) and stat.S_ISREG(before.st_mode) and before.st_nlink == 1
            and 0 < before.st_size <= maximum, "bounded_single_link_file_required")
    # NONBLOCK also avoids hanging on a FIFO substituted between lstat/open.
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    fd = os.open(path, flags)
    try:
        require(stamp(os.fstat(fd)) == stamp(before), "file_identity_changed")
        data = bytearray()
        while True:
            chunk = os.read(fd, min(65536, maximum + 1 - len(data)))
            if not chunk:
                break
            data.extend(chunk)
            require(len(data) <= maximum, "file_grew_past_limit")
        require(stamp(os.fstat(fd)) == stamp(before) and len(data) == before.st_size,
                "file_changed_during_read")
    finally:
        os.close(fd)
    require(stamp(path.lstat()) == stamp(before), "file_replaced_during_read")
    return bytes(data), stamp(before)


def names_in(folder: Path) -> set[str]:
    names = set()
    with os.scandir(folder) as entries:
        for entry in entries:
            require(entry.name in set(SOURCES) | {MANIFEST}, "extra_delivery_entry")
            names.add(entry.name)
            require(len(names) <= len(SOURCES) + 1, "delivery_entry_limit")
    require(names == set(SOURCES) | {MANIFEST}, "missing_delivery_entry")
    return names


def unique(pairs: list) -> dict:
    out = {}
    for key, value in pairs:
        require(key not in out, "duplicate_manifest_key")
        out[key] = value
    return out


def blob_id(data: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(data)).encode("ascii") + b"\0" + data).hexdigest()


def decode_manifest(raw: bytes, expected_commit: str) -> dict:
    manifest = json.loads(raw.decode("utf-8"), object_pairs_hook=unique)
    fields = {"format", "source_commit", "source_tree", "source_kind", "entrypoint",
              "native_backend_included", "real_funds_allowed", "accepted", "files"}
    require(type(manifest) is dict and set(manifest) == fields, "invalid_manifest_fields")
    require(manifest["format"] == FORMAT and manifest["source_kind"] == "fixed_exact_git_blobs"
            and manifest["entrypoint"] == "wallet_inspector_desktop.py"
            and all(manifest[key] is False for key in ("native_backend_included", "real_funds_allowed", "accepted")),
            "invalid_manifest_policy")
    require(identity(manifest["source_commit"], OID) and identity(manifest["source_tree"], OID)
            and manifest["source_commit"] == expected_commit, "source_identity_mismatch")
    entries = manifest["files"]
    require(type(entries) is list and len(entries) == len(SOURCES), "invalid_manifest_count")
    seen, total = set(), 0
    for entry in entries:
        require(type(entry) is dict and set(entry) == {"name", "source_path", "size", "sha256", "git_blob"},
                "invalid_manifest_entry")
        name = entry["name"]
        require(type(name) is str and name in SOURCES and name not in seen, "invalid_manifest_name")
        require(entry["source_path"] == SOURCES[name] and type(entry["size"]) is int
                and 0 < entry["size"] <= MAX_FILE and identity(entry["sha256"], DIGEST)
                and identity(entry["git_blob"], OID), "invalid_manifest_file")
        total += entry["size"]
        require(total <= MAX_TOTAL, "delivery_total_limit")
        seen.add(name)
    require(seen == set(SOURCES), "invalid_manifest_set")
    return manifest


def verify(folder: Path, manifest_sha256: str, source_commit: str) -> dict:
    """Read a fixed flat directory; never run Git, Tk, a backend or payload."""
    require(identity(manifest_sha256, DIGEST) and identity(source_commit, OID), "independent_pins_required")
    chain = directory_chain(folder)
    root_stamp = stamp(folder.lstat())
    names_in(folder)
    raw, manifest_stamp = read_plain(folder / MANIFEST, MAX_MANIFEST)
    require(hashlib.sha256(raw).hexdigest() == manifest_sha256, "manifest_digest_mismatch")
    manifest = decode_manifest(raw, source_commit)
    observed = {}
    for entry in manifest["files"]:
        data, observed[entry["name"]] = read_plain(folder / entry["name"], MAX_FILE)
        require(len(data) == entry["size"] and hashlib.sha256(data).hexdigest() == entry["sha256"]
                and blob_id(data) == entry["git_blob"], "payload_identity_mismatch")
    # Detect ordinary concurrent changes after each file was read. This is not
    # an atomic snapshot or protection against a malicious host/filesystem.
    names_in(folder)
    for name, before in observed.items():
        require(stamp((folder / name).lstat()) == before, "payload_changed_after_read")
    again, after = read_plain(folder / MANIFEST, MAX_MANIFEST)
    require(again == raw and after == manifest_stamp and stamp(folder.lstat()) == root_stamp
            and directory_chain(folder) == chain, "delivery_changed_during_check")
    return {"integrity_verified": True, "manifest_sha256": manifest_sha256,
            "source_commit": source_commit, "source_tree": manifest["source_tree"],
            "payload_files": len(SOURCES), "payload_executed": False,
            "code_signature_verified": False, "accepted": False, "real_funds_allowed": False}


def git_bytes(root: Path, *args: str, maximum: int = MAX_FILE) -> bytes:
    # Ignore inherited alternate repository/pathspec/tracing settings. Do not
    # lazily fetch missing objects from a promisor remote in this offline tool.
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull, GIT_NO_REPLACE_OBJECTS="1",
               GIT_NO_LAZY_FETCH="1", GIT_ALLOW_PROTOCOL="", GIT_TERMINAL_PROMPT="0", GIT_OPTIONAL_LOCKS="0",
               GIT_CONFIG_COUNT="1", GIT_CONFIG_KEY_0="protocol.allow", GIT_CONFIG_VALUE_0="never")
    result = subprocess.run(["git", "--no-replace-objects", "--literal-pathspecs", *args], cwd=root,
                            env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, timeout=60, check=True)
    # Object sizes are checked before cat-file. Git and its database remain
    # trusted; this post-check is not an OS-level subprocess memory sandbox.
    require(len(result.stdout) <= maximum, "git_output_limit")
    return result.stdout


def check_static_imports(payloads: dict[str, bytes]) -> None:
    """Catch missing ordinary imports, not dynamic execution or malicious code."""
    modules = {name[:-3] for name in SOURCES if name.endswith(".py")}
    for name, data in payloads.items():
        if not name.endswith(".py"):
            continue
        for node in ast.walk(ast.parse(data, filename=name)):
            targets = []
            if isinstance(node, ast.Import):
                targets = [item.name.split(".")[0] for item in node.names]
            elif isinstance(node, ast.ImportFrom):
                require(node.level == 0 and node.module is not None, "relative_payload_import")
                targets = [node.module.split(".")[0]]
            require(all(item in modules or item in sys.stdlib_module_names for item in targets),
                    "payload_import_not_delivered")


def capture(root: Path, source_commit: str) -> tuple[str, dict[str, bytes]]:
    require(identity(source_commit, OID), "exact_commit_required")
    chain = directory_chain(root)
    top = Path(git_bytes(root, "rev-parse", "--show-toplevel", maximum=16384).decode("utf-8").strip())
    require(top == root, "repository_root_required")
    require(git_bytes(root, "cat-file", "-t", source_commit, maximum=32) == b"commit\n", "commit_object_required")
    tree = git_bytes(root, "rev-parse", "--verify", source_commit + "^{tree}", maximum=64).decode("ascii").strip()
    require(identity(tree, OID), "invalid_git_tree")
    payloads, total = {}, 0
    for name, path in sorted(SOURCES.items()):
        raw = git_bytes(root, "ls-tree", "-lz", "--full-tree", source_commit, "--", path, maximum=1024)
        parts = raw.split(b"\0")
        require(len(parts) == 2 and parts[1] == b"", "missing_or_multiple_source_entries")
        meta, found_path = parts[0].split(b"\t")
        mode, kind, oid, size_text = meta.split()
        require(mode in (b"100644", b"100755") and kind == b"blob" and found_path == path.encode()
                and identity(oid.decode("ascii"), OID), "plain_git_blob_required")
        size = int(size_text)
        total += size
        require(0 < size <= MAX_FILE and total <= MAX_TOTAL, "source_size_limit")
        data = git_bytes(root, "cat-file", "blob", oid.decode("ascii"), maximum=size)
        require(len(data) == size and blob_id(data) == oid.decode("ascii"), "git_blob_mismatch")
        payloads[name] = data
    check_static_imports(payloads)
    require(directory_chain(root) == chain, "source_directory_changed")
    return tree, payloads


def write_new(path: Path, data: bytes) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
                 | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        view = memoryview(data)
        while view:
            written = os.write(fd, view)
            require(written > 0, "short_output_write")
            view = view[written:]
        os.fsync(fd)
    finally:
        os.close(fd)


def build(root: Path, source_commit: str, destination: Path) -> dict:
    """Export only pinned Git bytes to a NEW flat directory; leave failures."""
    require(isinstance(destination, Path) and destination.is_absolute() and ".." not in destination.parts,
            "explicit_destination_required")
    require(identity(source_commit, OID), "exact_commit_required")
    directory_chain(root)
    parent_chain = directory_chain(destination.parent)
    require(not destination.is_relative_to(root), "delivery_outside_source_required")
    require(not os.path.lexists(destination), "destination_already_exists")
    tree, payloads = capture(root, source_commit)
    manifest = {"format": FORMAT, "source_commit": source_commit, "source_tree": tree,
                "source_kind": "fixed_exact_git_blobs", "entrypoint": "wallet_inspector_desktop.py",
                "native_backend_included": False, "real_funds_allowed": False, "accepted": False,
                "files": [{"name": name, "source_path": SOURCES[name], "size": len(data),
                           "sha256": hashlib.sha256(data).hexdigest(), "git_blob": blob_id(data)}
                          for name, data in sorted(payloads.items())]}
    raw = (json.dumps(manifest, sort_keys=True, ensure_ascii=True, indent=2) + "\n").encode("utf-8")
    require(len(raw) <= MAX_MANIFEST, "manifest_size_limit")
    decode_manifest(raw, source_commit)
    require(directory_chain(destination.parent) == parent_chain, "destination_parent_changed")
    destination.mkdir(mode=0o700, parents=False, exist_ok=False)
    owned = directory_chain(destination)
    for name, data in sorted(payloads.items()):
        require(directory_chain(destination) == owned, "destination_directory_changed")
        write_new(destination / name, data)
    require(directory_chain(destination) == owned, "destination_directory_changed")
    write_new(destination / MANIFEST, raw)  # Last; never delete a partial output.
    result = verify(destination, hashlib.sha256(raw).hexdigest(), source_commit)
    require(directory_chain(destination) == owned, "destination_directory_changed")
    return result


class Parser(argparse.ArgumentParser):
    def error(self, message):
        self.exit(64, "Invalid source-delivery arguments. Use --help; do not provide wallet secrets.\n")


def main(argv=None) -> int:
    parser = Parser(description=__doc__)
    parser.add_argument("--no-real-funds", action="store_true", required=True)
    commands = parser.add_subparsers(dest="command", required=True, parser_class=Parser)
    make = commands.add_parser("build", help="export one exact commit; never overwrite")
    make.add_argument("--repository", type=Path, required=True)
    make.add_argument("--source-commit", required=True)
    make.add_argument("--output", type=Path, required=True)
    check = commands.add_parser("verify", help="read only; no payload is launched")
    check.add_argument("--bundle", type=Path, required=True)
    check.add_argument("--source-commit", required=True)
    check.add_argument("--manifest-sha256", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "build":
            result = build(args.repository, args.source_commit, args.output)
        else:
            result = verify(args.bundle, args.manifest_sha256, args.source_commit)
    except (OSError, ValueError, TypeError, KeyError, RecursionError, SyntaxError, subprocess.SubprocessError):
        print("Source delivery failed. No payload was executed; preserve any existing or partial output.", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Source delivery interrupted. No payload was executed; preserve any partial output.", file=sys.stderr)
        return 130
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
