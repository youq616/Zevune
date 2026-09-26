#!/usr/bin/env python3
"""Offline, create-only installation of a pinned NO-FUNDS inspector source bundle.

Run this tool and its verifier from trusted source, outside the received bundle.
No Git, network, payload import, backend, wallet operation or automatic launch.
An installation is a verified copy, not code approval or atomic deployment.
"""
from __future__ import annotations

import sys
if __name__ == "__main__":
    sys.dont_write_bytecode = True

import argparse
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path

import inspector_source_bundle as delivery


@dataclass(frozen=True)
class Snapshot:
    source: Path
    chain: tuple
    root_stamp: tuple
    # Fixed-name bytes and path metadata; at most the existing 4 MiB + manifest.
    files: tuple[tuple[str, bytes, tuple], ...]


def _pins(manifest_sha256: str, source_commit: str) -> None:
    delivery.require(delivery.identity(manifest_sha256, delivery.DIGEST)
                     and delivery.identity(source_commit, delivery.OID), "independent_pins_required")


def _absolute(path: Path) -> None:
    delivery.require(isinstance(path, Path) and path.is_absolute() and ".." not in path.parts
                     and len(str(path).encode("utf-8")) <= 4096, "bounded_absolute_path_required")


def _metadata_unchanged(snapshot: Snapshot) -> None:
    delivery.require(delivery.directory_chain(snapshot.source) == snapshot.chain
                     and delivery.stamp(snapshot.source.lstat()) == snapshot.root_stamp,
                     "install_source_directory_changed")
    delivery.names_in(snapshot.source)
    for name, _, before in snapshot.files:
        delivery.require(delivery.stamp((snapshot.source / name).lstat()) == before,
                         "install_source_changed")
    delivery.require(delivery.directory_chain(snapshot.source) == snapshot.chain
                     and delivery.stamp(snapshot.source.lstat()) == snapshot.root_stamp,
                     "install_source_directory_changed")


def _confirm(snapshot: Snapshot) -> None:
    """Re-read known, bounded files; ordinary concurrent change is a failure."""
    delivery.require(delivery.directory_chain(snapshot.source) == snapshot.chain
                     and delivery.stamp(snapshot.source.lstat()) == snapshot.root_stamp,
                     "install_source_directory_changed")
    delivery.names_in(snapshot.source)
    for name, expected, before in snapshot.files:
        limit = delivery.MAX_MANIFEST if name == delivery.MANIFEST else delivery.MAX_FILE
        data, after = delivery.read_plain(snapshot.source / name, limit)
        delivery.require(data == expected and after == before, "install_source_changed")
    delivery.names_in(snapshot.source)
    delivery.require(delivery.directory_chain(snapshot.source) == snapshot.chain
                     and delivery.stamp(snapshot.source.lstat()) == snapshot.root_stamp,
                     "install_source_directory_changed")


def _capture(source: Path, manifest_sha256: str, source_commit: str) -> Snapshot:
    chain = delivery.directory_chain(source)
    root_stamp = delivery.stamp(source.lstat())
    delivery.verify(source, manifest_sha256, source_commit)
    raw, manifest_stamp = delivery.read_plain(source / delivery.MANIFEST, delivery.MAX_MANIFEST)
    delivery.require(hashlib.sha256(raw).hexdigest() == manifest_sha256, "manifest_digest_mismatch")
    manifest = delivery.decode_manifest(raw, source_commit)
    entries, total = [], 0
    for entry in manifest["files"]:
        data, before = delivery.read_plain(source / entry["name"], delivery.MAX_FILE)
        total += len(data)
        delivery.require(total <= delivery.MAX_TOTAL and len(data) == entry["size"]
                         and hashlib.sha256(data).hexdigest() == entry["sha256"]
                         and delivery.blob_id(data) == entry["git_blob"], "install_payload_mismatch")
        entries.append((entry["name"], data, before))
    entries.sort(key=lambda item: item[0])
    # Preserve the original manifest bytes and external pin, not a new receipt.
    entries.append((delivery.MANIFEST, raw, manifest_stamp))
    snapshot = Snapshot(source, chain, root_stamp, tuple(entries))
    _confirm(snapshot)
    return snapshot


def install(source: Path, destination: Path, manifest_sha256: str, source_commit: str) -> dict:
    """Validate everything before mkdir; never overwrite, activate or roll back.

Trusted host/parents and stopped external writers are required. Identity checks
are not directory locks or a hostile-filesystem race guarantee. Errors preserve
partial OR complete new output; even a valid leftover is not a successful call.
"""
    _pins(manifest_sha256, source_commit)
    _absolute(source)
    _absolute(destination)
    source_chain = delivery.directory_chain(source)
    parent_chain = delivery.directory_chain(destination.parent)
    delivery.require(not destination.is_relative_to(source), "installation_outside_bundle_required")
    source_id = source_chain[-1][1:3]
    delivery.require(all(item[1:3] != source_id for item in parent_chain),
                     "installation_outside_bundle_required")
    delivery.require(not os.path.lexists(destination), "installation_destination_exists")
    snapshot = _capture(source, manifest_sha256, source_commit)
    delivery.require(snapshot.chain == source_chain, "install_source_directory_changed")
    delivery.require(delivery.directory_chain(destination.parent) == parent_chain,
                     "install_parent_changed")
    destination.mkdir(mode=0o700, parents=False, exist_ok=False)
    owned = delivery.directory_chain(destination)
    for name, data, _ in snapshot.files:
        delivery.require(delivery.directory_chain(destination) == owned, "install_target_changed")
        if name == delivery.MANIFEST:
            _confirm(snapshot)  # Do not publish the manifest after a source change.
            delivery.require(delivery.directory_chain(destination) == owned, "install_target_changed")
        delivery.write_new(destination / name, data)
    _confirm(snapshot)
    # This must follow the last full source read: otherwise a target modified
    # during that read could be reported using an already-stale verification.
    result = delivery.verify(destination, manifest_sha256, source_commit)
    _metadata_unchanged(snapshot)  # Detect source changes during final target IO.
    delivery.require(delivery.directory_chain(destination) == owned, "install_target_changed")
    result.update(operation="install_source", installed=True, source_unchanged=True,
                  automatic_launch=False, existing_installation_modified=False)
    return result


class Parser(argparse.ArgumentParser):
    def __init__(self, *args, **kwargs):
        kwargs["allow_abbrev"] = False
        super().__init__(*args, **kwargs)

    def error(self, message):
        self.exit(64, "Invalid installer arguments. Use --help; never supply wallet secrets.\n")


def main(argv=None) -> int:
    parser = Parser(description=__doc__)
    parser.add_argument("--no-real-funds", required=True, action="store_true")
    commands = parser.add_subparsers(dest="command", required=True, parser_class=Parser)
    make = commands.add_parser("install", help="verify and copy to a NEW directory; never launch")
    check = commands.add_parser("verify", help="verify installed bytes without executing them")
    for command in (make, check):
        command.add_argument("--bundle", required=True, type=Path)
        command.add_argument("--manifest-sha256", required=True)
        command.add_argument("--source-commit", required=True)
    make.add_argument("--destination", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "install":
            result = install(args.bundle, args.destination, args.manifest_sha256, args.source_commit)
        else:
            _pins(args.manifest_sha256, args.source_commit)
            _absolute(args.bundle)
            result = delivery.verify(args.bundle, args.manifest_sha256, args.source_commit)
            result["operation"] = "verify_source_installation"
        print(json.dumps(result, sort_keys=True))
        return 0
    except (OSError, ValueError, TypeError, KeyError, RecursionError):
        print("Source installation/check failed. No payload was executed; preserve existing and partial output.",
              file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Source installation/check interrupted. No payload was executed; preserve partial output.",
              file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
