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


def git_bytes(root: Path, *args: str, data: bytes | None = None) -> bytes:
    return subprocess.run(["git", "--no-replace-objects", *args], cwd=root,
                          input=data, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, check=True, timeout=60).stdout


def export_source(root: Path, commit: str, destination: Path) -> str:
    """Create a new directory from one captured commit; return its tree ID.

    File bytes are read without Git smudge/EOL filters and verified against the
    recorded blob ID. Symlinks, submodules, unsafe paths and oversized trees fail.
    """
    if not OID.fullmatch(commit):
        raise ValueError("invalid_source_commit")
    raw = git_bytes(root, "ls-tree", "-rlz", commit)
    entries = [entry for entry in raw.split(b"\0") if entry]
    if not entries or len(entries) > MAX_FILES:
        raise ValueError("source_file_count_exceeded")
    tree = git_bytes(root, "rev-parse", commit + "^{tree}").decode("ascii").strip()
    if not OID.fullmatch(tree):
        raise ValueError("invalid_source_tree")
    records = []
    seen = set()
    total = 0
    for entry in entries:
        meta, encoded = entry.split(b"\t", 1)
        mode, kind, oid, length = meta.split()
        path = encoded.decode("utf-8")
        parts = path.split("/")
        if (mode not in (b"100644", b"100755") or kind != b"blob"
                or not OID.fullmatch(oid.decode("ascii"))
                or PurePosixPath(path).is_absolute() or "\\" in path or ":" in path
                or any(p in ("", ".", "..") or p.lower() == ".git"
                       or p.endswith((".", " ")) for p in parts)
                or path.casefold() in seen):
            raise ValueError("unsupported_source_entry")
        size = int(length)
        total += size
        if not 0 <= size <= MAX_FILE_BYTES or total > MAX_SOURCE_BYTES:
            raise ValueError("source_size_exceeded")
        seen.add(path.casefold())
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
