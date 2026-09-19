"""Materialize bounded, exact Git blobs, never checkout/untracked build inputs.

Trusted Git binary and object database are prerequisites. This is source
provenance isolation, not a sandbox for compilers or dependency build scripts.
"""
from __future__ import annotations

import hashlib
from pathlib import Path, PurePosixPath
import re
import subprocess

MAX_FILES = 4096
MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_SOURCE_BYTES = 32 * 1024 * 1024
OID = re.compile(r"[0-9a-f]{40}\Z")
WINDOWS_DEVICES = {"CON", "PRN", "AUX", "NUL"} | {
    prefix + digit for prefix in ("COM", "LPT") for digit in "123456789¹²³"}


def git_bytes(root: Path, *args: str, data: bytes | None = None) -> bytes:
    return subprocess.run(["git", "--no-replace-objects", *args], cwd=root,
                          input=data, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, check=True, timeout=60).stdout


def export_source(root: Path, commit: str, destination: Path) -> str:
    """Create a new directory from one captured commit; return its tree ID.

    File bytes are read without Git smudge/EOL filters and verified against the
    recorded blob ID. Symlinks, submodules, unsafe paths and oversized trees fail.
    """
    return _export_source(root, commit, destination, build_inputs=False)


def export_build_source(root: Path, commit: str, destination: Path) -> str:
    """Export exact build inputs, excluding only the root reports/ Git tree.

    Reports are retained in Git but are not compiler or bundle inputs. All other
    tracked files are included, irrespective of extension, with the same count,
    individual-size and total-size limits as export_source. The returned ID is
    the original commit's full tree, not a tree of the materialized subset.
    """
    return _export_source(root, commit, destination, build_inputs=True)


def _check_path(path: str, spellings: dict[str, str], files: set[str]) -> None:
    parts = path.split("/")
    if (PurePosixPath(path).is_absolute() or "\\" in path or ":" in path
            or any(p in ("", ".", "..") or p.lower() == ".git"
                   or p.split(".", 1)[0].rstrip(" ").upper() in WINDOWS_DEVICES
                   or p.endswith((".", " ")) for p in parts)):
        raise ValueError("unsupported_source_entry")
    # Check every ancestor too: Dir/a and dir/b would merge on Windows even
    # though their complete file paths do not have the same case-folded value.
    for index in range(1, len(parts) + 1):
        prefix = "/".join(parts[:index])
        folded = prefix.casefold()
        if (folded in files or (folded in spellings and
                (spellings[folded] != prefix or index == len(parts)))):
            raise ValueError("unsupported_source_entry")
        spellings[folded] = prefix
    files.add(path.casefold())


def _build_entries(root: Path, commit: str) -> list[bytes]:
    # ls-tree has no exclude pathspec support. Validate a nonrecursive root
    # listing first, then enumerate exact literal roots other than reports/.
    # The one excluded tree consumes no recursive metadata, file or byte budget.
    raw = git_bytes(root, "ls-tree", "-lz", "--full-tree", commit)
    roots = [entry for entry in raw.split(b"\0") if entry]
    if not roots or len(roots) > MAX_FILES + 1:
        raise ValueError("source_file_count_exceeded")
    spellings: dict[str, str] = {}
    names: set[str] = set()
    selected = []
    for entry in roots:
        meta, encoded = entry.split(b"\t", 1)
        mode, kind, oid, length = meta.split()
        path = encoded.decode("utf-8")
        if (not OID.fullmatch(oid.decode("ascii")) or "/" in path
                or not ((mode == b"040000" and kind == b"tree" and length == b"-")
                        or (mode in (b"100644", b"100755") and kind == b"blob"))):
            raise ValueError("unsupported_source_entry")
        _check_path(path, spellings, names)
        if not (path == "reports" and kind == b"tree"):
            selected.append(path)
    if not selected or len(selected) > MAX_FILES:
        raise ValueError("source_file_count_exceeded")
    # Bound each argument batch below Windows command-line limits. Literal
    # pathspecs ensure tracked names containing wildcard characters stay exact.
    batches: list[list[str]] = [[]]
    argument_bytes = 0
    for path in selected:
        size = len(path.encode("utf-8")) + 1
        if size > 8192:
            raise ValueError("unsupported_source_entry")
        if argument_bytes + size > 8192:
            batches.append([])
            argument_bytes = 0
        batches[-1].append(path)
        argument_bytes += size
    entries = []
    for batch in batches:
        raw = git_bytes(root, "--literal-pathspecs", "ls-tree", "-rlz",
                        "--full-tree", commit, "--", *batch)
        entries.extend(entry for entry in raw.split(b"\0") if entry)
        if len(entries) > MAX_FILES:
            raise ValueError("source_file_count_exceeded")
    return entries


def _export_source(root: Path, commit: str, destination: Path, *, build_inputs: bool) -> str:
    if not OID.fullmatch(commit):
        raise ValueError("invalid_source_commit")
    if build_inputs:
        entries = _build_entries(root, commit)
    else:
        raw = git_bytes(root, "ls-tree", "-rlz", commit)
        entries = [entry for entry in raw.split(b"\0") if entry]
    if not entries or len(entries) > MAX_FILES:
        raise ValueError("source_file_count_exceeded")
    tree = git_bytes(root, "rev-parse", commit + "^{tree}").decode("ascii").strip()
    if not OID.fullmatch(tree):
        raise ValueError("invalid_source_tree")
    records = []
    spellings: dict[str, str] = {}
    files: set[str] = set()
    total = 0
    for entry in entries:
        meta, encoded = entry.split(b"\t", 1)
        mode, kind, oid, length = meta.split()
        path = encoded.decode("utf-8")
        if (mode not in (b"100644", b"100755") or kind != b"blob"
                or not OID.fullmatch(oid.decode("ascii"))):
            raise ValueError("unsupported_source_entry")
        _check_path(path, spellings, files)
        size = int(length)
        total += size
        if not 0 <= size <= MAX_FILE_BYTES or total > MAX_SOURCE_BYTES:
            raise ValueError("source_size_exceeded")
        records.append((mode, oid, size, path))
    # Sizes and count are checked before asking for blob contents. No textconv,
    # filters, replacement refs, or object expressions are accepted in the batch.
    batch = git_bytes(root, "cat-file", "--batch",
                      data=b"".join(oid + b"\n" for _, oid, _, _ in records))
    destination.mkdir(mode=0o700, parents=False, exist_ok=False)
    cursor = 0
    for mode, oid, size, path in records:
        end = batch.find(b"\n", cursor)
        expected = oid + b" blob " + str(size).encode("ascii")
        if end < 0 or batch[cursor:end] != expected:
            raise ValueError("source_batch_header_mismatch")
        cursor = end + 1
        payload = batch[cursor:cursor + size]
        cursor += size
        if len(payload) != size or batch[cursor:cursor + 1] != b"\n":
            raise ValueError("source_batch_truncated")
        cursor += 1
        identity = hashlib.sha1(b"blob " + str(size).encode("ascii") + b"\0" + payload).hexdigest()
        if identity != oid.decode("ascii"):
            raise ValueError("source_blob_mismatch")
        out = destination.joinpath(*path.split("/"))
        out.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        with out.open("xb") as file:
            file.write(payload)
        out.chmod(0o700 if mode == b"100755" else 0o600)
    if cursor != len(batch):
        raise ValueError("source_batch_trailing_data")
    return tree
