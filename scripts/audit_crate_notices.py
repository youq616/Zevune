"""Inventory Rust dependency notices from checksum-pinned .crate archives.

Offline only. This checks archive identity and notice presence, not license
compatibility or permission to distribute Zevune. No wallet directories are read.
Requires Python 3.11+. Missing notices cause a nonzero exit; they are not invented.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import stat
import tarfile
import tomllib
from pathlib import Path, PurePosixPath
from typing import Any

MAX_LOCK_BYTES = 4 * 1024 * 1024
MAX_ARCHIVE_BYTES = 64 * 1024 * 1024
MAX_TAR_BYTES = 256 * 1024 * 1024
MAX_DOCUMENT_BYTES = 512 * 1024
MAX_MEMBERS = 20_000
MAX_PACKAGES = 2_000
TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.+-]{0,127}\Z")
CHECKSUM = re.compile(r"[0-9a-f]{64}\Z")
NOTICE = re.compile(r"(?:licen[cs]e|copying|copyright|notice)(?:[._-][A-Za-z0-9_.+-]{1,80})?\Z", re.I)


class AuditError(ValueError):
    """A fixed diagnostic code, without file contents or private paths."""


def read_regular(path: Path, limit: int) -> bytes:
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or before.st_size > limit:
        raise AuditError("nonregular_or_oversized_file")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    with os.fdopen(descriptor, "rb") as stream:
        opened = os.fstat(stream.fileno())
        if not stat.S_ISREG(opened.st_mode) or not os.path.samestat(before, opened):
            raise AuditError("file_identity_changed")
        data = stream.read(limit + 1)
        after = os.fstat(stream.fileno())
    if len(data) != before.st_size or len(data) > limit or after.st_size != before.st_size:
        raise AuditError("file_size_changed")
    return data


def locked_packages(raw: bytes) -> list[dict[str, str]]:
    if len(raw) > MAX_LOCK_BYTES:
        raise AuditError("oversized_lockfile")
    try:
        document = tomllib.loads(raw.decode("utf-8"))
    except (UnicodeError, tomllib.TOMLDecodeError) as exc:
        raise AuditError("invalid_lockfile") from exc
    packages = document.get("package")
    if not isinstance(packages, list) or len(packages) > MAX_PACKAGES:
        raise AuditError("invalid_package_list")
    selected = []
    seen = set()
    for package in packages:
        if not isinstance(package, dict):
            raise AuditError("invalid_package")
        source = package.get("source")
        if source is None:
            continue  # Workspace and path crates are a separate review.
        name, version = package.get("name"), package.get("version")
        if not all(isinstance(v, str) and TOKEN.fullmatch(v) for v in (name, version)):
            raise AuditError("invalid_package_identity")
        if not isinstance(source, str):
            raise AuditError("invalid_package_source")
        identity = (name, version, source)
        if identity in seen:
            raise AuditError("duplicate_package_identity")
        seen.add(identity)
        checksum = package.get("checksum", "")
        if source.startswith("registry+") and (not isinstance(checksum, str) or not CHECKSUM.fullmatch(checksum)):
            raise AuditError("missing_registry_checksum")
        selected.append({"name": name, "version": version, "source": source, "checksum": checksum})
    return sorted(selected, key=lambda p: (p["name"], p["version"], p["source"]))


class LimitedReader:
    def __init__(self, stream: Any, limit: int) -> None:
        self.stream = stream
        self.left = limit

    def read(self, size: int = -1) -> bytes:
        if size < 0:
            size = self.left + 1
        result = self.stream.read(min(size, self.left + 1))
        self.left -= len(result)
        if self.left < 0:
            raise AuditError("expanded_archive_exceeds_limit")
        return result


def archive_notices(raw: bytes, package: dict[str, str]) -> tuple[str | None, dict[str, bytes]]:
    if len(raw) > MAX_ARCHIVE_BYTES or hashlib.sha256(raw).hexdigest() != package["checksum"]:
        raise AuditError("archive_checksum_mismatch")
    prefix = f"{package['name']}-{package['version']}"
    names: set[str] = set()
    notices: dict[str, bytes] = {}
    manifest = None
    # Bound decompressed data, including GNU/PAX extension records, not just
    # ordinary member sizes. Never extract archive paths to the filesystem.
    import gzip
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(raw)) as compressed:
            reader = LimitedReader(compressed, MAX_TAR_BYTES)
            with tarfile.open(fileobj=reader, mode="r|") as archive:
                for index, entry in enumerate(archive):
                    if index >= MAX_MEMBERS:
                        raise AuditError("too_many_archive_members")
                    path = PurePosixPath(entry.name)
                    if "\\" in entry.name or path.is_absolute() or any(v in (".", "..") for v in entry.name.split("/")):
                        raise AuditError("unsafe_archive_path")
                    if not path.parts or path.parts[0] != prefix:
                        raise AuditError("foreign_archive_root")
                    if entry.name in names:
                        raise AuditError("duplicate_archive_member")
                    names.add(entry.name)
                    if len(path.parts) != 2:
                        continue
                    basename = path.parts[1]
                    wanted = basename == "Cargo.toml" or NOTICE.fullmatch(basename)
                    if not wanted:
                        continue
                    if not entry.isfile() or entry.size > MAX_DOCUMENT_BYTES:
                        raise AuditError("nonregular_or_oversized_notice")
                    stream = archive.extractfile(entry)
                    if stream is None:
                        raise AuditError("missing_notice_stream")
                    data = stream.read(MAX_DOCUMENT_BYTES + 1)
                    if len(data) != entry.size or len(data) > MAX_DOCUMENT_BYTES:
                        raise AuditError("invalid_notice_length")
                    data.decode("utf-8")
                    if basename == "Cargo.toml":
                        manifest = tomllib.loads(data.decode("utf-8"))
                    else:
                        notices[basename] = data
    except AuditError:
        raise
    except (tarfile.TarError, OSError, EOFError, UnicodeError, tomllib.TOMLDecodeError) as exc:
        raise AuditError("invalid_crate_archive") from exc
    metadata = manifest.get("package", {}) if isinstance(manifest, dict) else {}
    if not isinstance(metadata, dict) or metadata.get("name") != package["name"] or metadata.get("version") != package["version"]:
        raise AuditError("archive_package_identity_mismatch")
    declared = metadata.get("license")
    if declared is not None and not isinstance(declared, str):
        raise AuditError("invalid_license_metadata")
    return declared, notices


def inventory(lock: Path, caches: list[Path]) -> tuple[dict[str, Any], dict[str, bytes]]:
    if not caches or len(caches) > 16:
        raise AuditError("explicit_crate_caches_required")
    for cache in caches:
        if not cache.is_absolute() or not stat.S_ISDIR(cache.lstat().st_mode):
            raise AuditError("cache_must_be_explicit_regular_directory")
    raw_lock = read_regular(lock, MAX_LOCK_BYTES)
    packages = locked_packages(raw_lock)
    report: dict[str, Any] = {
        "schema": "zevune-crate-notice-inventory-1", "cargo_lock_sha256": hashlib.sha256(raw_lock).hexdigest(),
        "scope": "locked_registry_crates_only", "distribution_approved": False,
        "workspace_and_path_dependencies_reviewed": False, "license_compatibility_reviewed": False,
        "complete": True, "packages": [],
    }
    documents: dict[str, bytes] = {}
    for package in packages:
        record: dict[str, Any] = dict(package)
        record["documents"] = []
        try:
            if not package["source"].startswith("registry+"):
                raise AuditError("nonregistry_source_requires_separate_review")
            candidates = [cache / f"{package['name']}-{package['version']}.crate" for cache in caches]
            existing = [p for p in candidates if p.exists() or p.is_symlink()]
            if not existing:
                raise AuditError("missing_crate_archive")
            archives = [read_regular(p, MAX_ARCHIVE_BYTES) for p in existing]
            matches = [data for data in archives if hashlib.sha256(data).hexdigest() == package["checksum"]]
            if not matches:
                raise AuditError("archive_checksum_mismatch")
            license_name, notes = archive_notices(matches[0], package)
            record["declared_license"] = license_name
            record["archive_checksum_verified"] = True
            if not notes:
                raise AuditError("missing_license_notice_documents")
            for basename, content in sorted(notes.items()):
                relative = f"notices/{package['name']}-{package['version']}-{package['checksum'][:16]}/{basename}"
                if relative in documents and documents[relative] != content:
                    raise AuditError("notice_output_collision")
                documents[relative] = content
                record["documents"].append({"path": relative, "sha256": hashlib.sha256(content).hexdigest(), "size": len(content)})
            record["status"] = "archive_and_notice_presence_checked_not_legal_clearance"
        except (AuditError, OSError) as exc:
            record["status"] = str(exc) if isinstance(exc, AuditError) else "archive_io_error"
            report["complete"] = False
        report["packages"].append(record)
    if not packages:
        report["complete"] = False
        report["error"] = "no_external_packages_selected"
    return report, documents


def write_inventory(output: Path, report: dict[str, Any], documents: dict[str, bytes]) -> None:
    if not output.is_absolute():
        raise AuditError("absolute_output_directory_required")
    output.mkdir(mode=0o700)
    for relative, data in sorted(documents.items()):
        path = output / relative
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        with path.open("xb") as stream:
            stream.write(data)
    with (output / "NOTICE-INVENTORY.json").open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(report, stream, ensure_ascii=True, sort_keys=True, indent=2)
        stream.write("\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lock", type=Path, required=True)
    parser.add_argument("--crate-cache", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        report, documents = inventory(args.lock, args.crate_cache)
        write_inventory(args.output, report, documents)
    except (AuditError, OSError) as exc:
        code = str(exc) if isinstance(exc, AuditError) else "inventory_io_error"
        print(json.dumps({"complete": False, "error": code, "distribution_approved": False}))
        return 2
    print(json.dumps({"complete": report["complete"], "packages": len(report["packages"]), "distribution_approved": False}))
    return 0 if report["complete"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
