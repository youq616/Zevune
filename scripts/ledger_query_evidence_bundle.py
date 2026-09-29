#!/usr/bin/env python3
"""NO-FUNDS portable task/report bundles: pack, verify, unpack into NEW directory.

Only original canonical task/report bytes are allowed. No filenames, executable
paths, wallet data or commands enter the envelope. An external digest is still
required: bundled hashes are integrity metadata, not signatures or approval.
"""
from __future__ import annotations

import sys
if __name__ == '__main__':
    sys.dont_write_bytecode = True

import argparse
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path

import ledger_query_evidence_compare as evidence

task, reports = evidence.task, evidence.reports
files = task.files
FORMAT = 'zevune-query-evidence-bundle-1'
MAX_ITEMS = 32
MAX_BUNDLE_BYTES = 1100000
MAX_OUTPUT_BYTES = 32768


@dataclass(frozen=True)
class Entry:
    kind: str
    sha256: str
    raw: bytes


def entry(kind: str, sha256: str, raw: bytes) -> Entry:
    files.require(type(kind) is str and kind in evidence.KINDS, 'explicit_bundle_entry_kind')
    # The original decoders enforce individual byte bounds and all schemas.
    decoder = task.decode if kind == 'task' else reports.decode
    decoder(raw, sha256)
    return Entry(kind, sha256, raw)


def encode(entries: tuple[Entry, ...]) -> bytes:
    files.require(type(entries) is tuple and 1 <= len(entries) <= MAX_ITEMS, 'bounded_bundle_entries')
    seen, values = set(), []
    for item in entries:
        files.require(type(item) is Entry, 'invalid_bundle_entry')
        entry(item.kind, item.sha256, item.raw)
        identity = (item.kind, item.sha256)
        files.require(identity not in seen, 'duplicate_bundle_entry')
        seen.add(identity)
        values.append(dict(kind=item.kind, sha256=item.sha256, data_hex=item.raw.hex()))
    raw = files.canonical(dict(format=FORMAT, entries=values, execution_performed=False,
                               signature_verified=False, real_funds_allowed=False))
    files.require(len(raw) <= MAX_BUNDLE_BYTES, 'bundle_size_limit')
    return raw


def decode(raw: bytes, expected_sha256: str) -> tuple[Entry, ...]:
    task.digest(expected_sha256)
    files.require(type(raw) is bytes and 0 < len(raw) <= MAX_BUNDLE_BYTES, 'bounded_bundle_required')
    files.require(hashlib.sha256(raw).hexdigest() == expected_sha256, 'bundle_digest_mismatch')
    def unique(pairs):
        out = {}
        for key, value in pairs:
            files.require(key not in out, 'duplicate_bundle_field')
            out[key] = value
        return out
    def nonfinite(_):
        raise ValueError('nonfinite_bundle_value')
    data = json.loads(raw.decode('utf-8'), object_pairs_hook=unique, parse_constant=nonfinite)
    fields = {'format', 'entries', 'execution_performed', 'signature_verified', 'real_funds_allowed'}
    files.require(type(data) is dict and set(data) == fields and data['format'] == FORMAT
                  and all(data[key] is False for key in fields - {'format', 'entries'})
                  and type(data['entries']) is list and 1 <= len(data['entries']) <= MAX_ITEMS,
                  'invalid_bundle_document')
    items = []
    for item in data['entries']:
        files.require(type(item) is dict and set(item) == {'kind', 'sha256', 'data_hex'}, 'bundle_entry_fields')
        text = item['data_hex']
        files.require(type(text) is str and 0 < len(text) <= 2 * reports.MAX_REPORT_BYTES
                      and len(text) % 2 == 0, 'bundle_payload_extent')
        payload = bytes.fromhex(text)
        files.require(payload.hex() == text, 'canonical_bundle_hex_required')
        items.append(entry(item['kind'], item['sha256'], payload))
    result = tuple(items)
    files.require(raw == encode(result), 'noncanonical_bundle')
    return result


@dataclass(frozen=True)
class Snapshot:
    path: Path
    raw: bytes
    identity: tuple
    parent_chain: tuple
    entries: tuple[Entry, ...]


def metadata_unchanged(snapshot) -> None:
    files.require(task.view._chain(snapshot.path.parent) == snapshot.parent_chain
                  and files.regular(snapshot.path.lstat())
                  and files.identity(snapshot.path.lstat()) == snapshot.identity, 'bundle_input_changed')


def unchanged(snapshot: Snapshot) -> None:
    metadata_unchanged(snapshot)
    files.require(files.read_file(snapshot.path, MAX_BUNDLE_BYTES) == (snapshot.raw, snapshot.identity),
                  'bundle_changed')
    metadata_unchanged(snapshot)


def load(path: Path, expected_sha256: str) -> Snapshot:
    task.digest(expected_sha256)
    task.absolute(path)
    chain = task.view._chain(path.parent)
    raw, identity = files.read_file(path, MAX_BUNDLE_BYTES)
    entries = decode(raw, expected_sha256)
    snapshot = Snapshot(path, raw, identity, chain, entries)
    unchanged(snapshot)
    return snapshot


def filename(index: int, kind: str) -> str:
    files.require(type(index) is int and 0 <= index < MAX_ITEMS and type(kind) is str
                  and kind in evidence.KINDS, 'invalid_bundle_slot')
    return f'{index + 1:02d}-{kind}.json'


def summary(snapshot: Snapshot, operation: str) -> dict:
    items = []
    for index, item in enumerate(snapshot.entries):
        if item.kind == 'task':
            request, request_sha = task.decode(item.raw, item.sha256), item.sha256
        else:
            request, request_sha = reports.decode(item.raw, item.sha256)
        items.append(dict(filename=filename(index, item.kind), kind=item.kind, sha256=item.sha256,
                          bytes=len(item.raw), request_sha256=request_sha, query_count=len(request.txids)))
    return dict(operation=operation, bundle_sha256=hashlib.sha256(snapshot.raw).hexdigest(),
                bundle_bytes=len(snapshot.raw), entry_count=len(items), entries=items,
                bundle_integrity_verified=True, original_inputs_rechecked=False,
                execution_performed=False, signature_verified=False, ledger_replayed=False,
                approval_reusable=False, retry_authorized=False, real_funds_allowed=False)


def pack(sources: tuple[evidence.Source, ...], destination: Path) -> dict:
    files.require(type(sources) is tuple and 1 <= len(sources) <= MAX_ITEMS, 'bounded_bundle_sources')
    task.absolute(destination)
    for source in sources:
        evidence.validate_source(source)
        files.require(source.path != destination, 'bundle_output_is_source')
    files.require(len({(s.kind, s.sha256) for s in sources}) == len(sources), 'duplicate_bundle_source')
    captured = tuple(evidence._load(source) for source in sources)
    raw = encode(tuple(entry(s.source.kind, s.source.sha256, s.snapshot.raw) for s in captured))
    parent = task.view._chain(destination.parent)
    for source in captured:
        source.unchanged()
    files.write_new(destination, raw)  # Exclusive create + file fsync; partial outputs are retained.
    saved = load(destination, hashlib.sha256(raw).hexdigest())
    files.require(saved.parent_chain == parent and saved.raw == raw, 'bundle_output_changed')
    result = summary(saved, 'evidence_bundle_pack')
    for source in captured:
        source.unchanged()
    unchanged(saved)
    for source in captured:
        source.metadata_unchanged()
    # Only the selected files, not the original task behind a report, were read.
    result.update(created=True, selected_input_files_rechecked=True)
    return result


def verify(path: Path, expected_sha256: str) -> dict:
    saved = load(path, expected_sha256)
    result = summary(saved, 'evidence_bundle_verify')
    unchanged(saved)
    return result


def directory_snapshot(directory: Path, entries: tuple[Entry, ...]) -> tuple:
    chain = task.view._chain(directory)
    stamp = files.identity(directory.lstat())
    names = {filename(i, item.kind) for i, item in enumerate(entries)}
    task.once.single.ledger.names(directory, names)
    captured = []
    for i, item in enumerate(entries):
        name = filename(i, item.kind)
        raw, identity = files.read_file(directory / name, reports.MAX_REPORT_BYTES)
        files.require(raw == item.raw, 'unpacked_bytes_mismatch')
        captured.append((name, identity))
    result = (chain, stamp, tuple(captured))
    directory_unchanged(directory, result)
    return result


def directory_unchanged(directory: Path, captured: tuple) -> None:
    chain, stamp, items = captured
    task.once.single.ledger.names(directory, {name for name, _ in items})
    for name, identity in items:
        info = (directory / name).lstat()
        files.require(files.regular(info) and files.identity(info) == identity, 'unpacked_file_changed')
    files.require(task.view._chain(directory) == chain and files.identity(directory.lstat()) == stamp,
                  'unpacked_directory_changed')


def verify_directory(path: Path, expected_sha256: str, directory: Path) -> dict:
    task.digest(expected_sha256)
    task.absolute(path)
    task.absolute(directory)
    saved = load(path, expected_sha256)
    result = summary(saved, 'evidence_bundle_verify_directory')
    captured = directory_snapshot(directory, saved.entries)
    unchanged(saved)
    directory_unchanged(directory, captured)
    metadata_unchanged(saved)
    result.update(directory_bytes_verified=True, unpack_call_success_verified=False)
    return result


def unpack(path: Path, expected_sha256: str, destination: Path) -> dict:
    task.digest(expected_sha256)
    task.absolute(path)
    task.absolute(destination)
    saved = load(path, expected_sha256)  # Validate every entry BEFORE any target creation.
    parent = task.view._chain(destination.parent)
    result = summary(saved, 'evidence_bundle_unpack')
    unchanged(saved)
    destination.mkdir(mode=0o700, parents=False, exist_ok=False)
    root_chain = task.view._chain(destination)
    written = []
    for index, item in enumerate(saved.entries):
        files.require(task.view._chain(destination) == root_chain, 'unpack_target_replaced')
        target = destination / filename(index, item.kind)
        files.write_new(target, item.raw)
        raw, identity = files.read_file(target, reports.MAX_REPORT_BYTES)
        files.require(raw == item.raw, 'unpack_write_mismatch')
        written.append((target.name, identity))
    captured = directory_snapshot(destination, saved.entries)
    files.require(captured[0] == root_chain and captured[2] == tuple(written), 'unpack_output_replaced')
    unchanged(saved)
    directory_unchanged(destination, captured)
    files.require(task.view._chain(destination.parent) == parent, 'unpack_parent_changed')
    metadata_unchanged(saved)
    result.update(created=True, directory_bytes_verified=True)
    return result


class Parser(task.Parser):
    def error(self, message):
        self.exit(64, 'Invalid evidence-bundle arguments. Use --help; never supply secrets.\n')


class Entries(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        old = getattr(namespace, self.dest, None) or ()
        if len(old) >= MAX_ITEMS:
            parser.error('too many entries')
        kind, path, sha = values
        setattr(namespace, self.dest, (*old, evidence.Source(kind, Path(path), sha)))


def main(argv=None) -> int:
    parser = Parser(description=__doc__)
    parser.add_argument('--no-real-funds', required=True, action='store_true')
    actions = parser.add_subparsers(dest='operation', required=True, parser_class=Parser)
    make = actions.add_parser('pack')
    make.add_argument('--entry', nargs=3, action=Entries, required=True, metavar=('KIND', 'PATH', 'SHA256'))
    make.add_argument('--destination', type=Path, required=True)
    for name in ('verify', 'unpack', 'verify-directory'):
        command = actions.add_parser(name)
        command.add_argument('--bundle', type=Path, required=True)
        command.add_argument('--bundle-sha256', required=True)
        if name != 'verify':
            command.add_argument('--destination', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.operation == 'pack':
            result = pack(args.entry, args.destination)
        elif args.operation == 'verify':
            result = verify(args.bundle, args.bundle_sha256)
        elif args.operation == 'unpack':
            result = unpack(args.bundle, args.bundle_sha256, args.destination)
        else:
            result = verify_directory(args.bundle, args.bundle_sha256, args.destination)
        text = json.dumps(result, sort_keys=True)
        files.require(len(text.encode('utf-8')) <= MAX_OUTPUT_BYTES, 'bundle_output_limit')
        task.view.write_output(text)
        return 0
    except KeyboardInterrupt:
        print('Evidence bundle interrupted. Preserve inputs and partial output; no complete result.', file=sys.stderr)
        return 130
    except (ValueError, OSError, RuntimeError, TypeError, KeyError, RecursionError):
        print('Evidence bundle failed. Preserve inputs and partial output; no result or execution permission.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
