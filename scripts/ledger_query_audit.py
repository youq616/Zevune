#!/usr/bin/env python3
"""NO-FUNDS reproducible task-content audit, export, verify and source recheck.

No query execution, backend path, ledger input, signature or funds permission.
A portable report describes pinned content; it is not an execution-event log.
"""
from __future__ import annotations

import sys
if __name__ == '__main__':
    sys.dont_write_bytecode = True

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path

import ledger_query_request as task

files = task.files
FORMAT = 'zevune-ledger-query-audit-1'
MAX_REPORT_BYTES = 16384
MAX_OUTPUT_BYTES = 32768


def report_for(request: task.Request, request_sha256: str) -> dict:
    """Derive every report field from validated canonical public task bytes."""
    task.digest(request_sha256)
    raw = task.encode(request)
    files.require(hashlib.sha256(raw).hexdigest() == request_sha256, 'audit_request_digest_mismatch')
    checkpoint = task.once.single.Checkpoint.parse(request.checkpoint)
    return dict(format=FORMAT, scope='task_content_only', request_sha256=request_sha256,
                request_bytes=len(raw), query_count=len(request.txids), checkpoint_height=checkpoint.height,
                request=request.document(), query_executed=False, signature_verified=False,
                backend_verified=False, ledger_replayed=False, retry_authorized=False,
                real_funds_allowed=False)


def encode(request: task.Request, request_sha256: str) -> bytes:
    raw = files.canonical(report_for(request, request_sha256))
    files.require(len(raw) <= MAX_REPORT_BYTES, 'audit_report_size_limit')
    return raw


def decode(raw: bytes, expected_sha256: str) -> tuple[task.Request, str]:
    """Verify the external report digest BEFORE JSON; recompute all derived fields."""
    task.digest(expected_sha256)
    files.require(type(raw) is bytes and 0 < len(raw) <= MAX_REPORT_BYTES, 'bounded_audit_report_required')
    files.require(hashlib.sha256(raw).hexdigest() == expected_sha256, 'audit_digest_mismatch')
    def unique(pairs):
        result = {}
        for key, value in pairs:
            files.require(key not in result, 'duplicate_audit_field')
            result[key] = value
        return result
    def nonfinite(_):
        raise ValueError('nonfinite_audit_number')
    document = json.loads(raw.decode('utf-8'), object_pairs_hook=unique, parse_constant=nonfinite)
    files.require(type(document) is dict and type(document.get('request')) is dict,
                  'invalid_audit_document')
    request_sha256 = task.digest(document.get('request_sha256'))
    # The original decoder owns the task schema, ID order, profile and bounds.
    request = task.decode(files.canonical(document['request']), request_sha256)
    # Exact canonical bytes enforce all fields AND bool/int distinctions. Merely
    # comparing dicts would erroneously accept e.g. 0 in place of False.
    files.require(raw == encode(request, request_sha256), 'noncanonical_or_inconsistent_audit')
    return request, request_sha256


@dataclass(frozen=True)
class AuditSnapshot:
    path: Path
    request: task.Request
    request_sha256: str
    raw: bytes
    identity: tuple
    parent_chain: tuple


def unchanged(snapshot: AuditSnapshot) -> None:
    files.require(task.view._chain(snapshot.path.parent) == snapshot.parent_chain, 'audit_parent_changed')
    files.require(files.read_file(snapshot.path, MAX_REPORT_BYTES) == (snapshot.raw, snapshot.identity),
                  'audit_file_changed')
    files.require(task.view._chain(snapshot.path.parent) == snapshot.parent_chain, 'audit_parent_changed')


def _source_metadata_unchanged(snapshot: task.Snapshot) -> None:
    # Final metadata check after report IO. This is not an atomic cross-file lock.
    files.require(task.view._chain(snapshot.path.parent) == snapshot.parent_chain
                  and files.identity(snapshot.path.lstat()) == snapshot.identity, 'audit_source_changed')


def load(path: Path, expected_sha256: str) -> AuditSnapshot:
    task.digest(expected_sha256)
    task.absolute(path)
    chain = task.view._chain(path.parent)
    raw, identity = files.read_file(path, MAX_REPORT_BYTES)
    request, request_sha256 = decode(raw, expected_sha256)
    captured = AuditSnapshot(path, request, request_sha256, raw, identity, chain)
    unchanged(captured)
    return captured


def inspect_task(path: Path, request_sha256: str) -> dict:
    """Read the pinned source, but never touch a ledger or execute its task."""
    snapshot = task.load(path, request_sha256)
    report = report_for(snapshot.request, request_sha256)
    task.unchanged(snapshot)
    return dict(operation='query_task_audit', source_file_rechecked=True,
                audit_sha256=hashlib.sha256(files.canonical(report)).hexdigest(), report=report)


def export_audit(path: Path, request_sha256: str, destination: Path) -> dict:
    """Create a NEW report only; preserve inputs and partial output on all failures."""
    task.digest(request_sha256)
    task.absolute(path)
    task.absolute(destination)
    files.require(path != destination, 'audit_output_must_differ_from_source')
    source = task.load(path, request_sha256)
    raw = encode(source.request, request_sha256)
    parent = task.view._chain(destination.parent)
    task.unchanged(source)
    files.write_new(destination, raw)  # Existing exclusive create + file fsync, no cleanup/retry.
    audit_sha256 = hashlib.sha256(raw).hexdigest()
    saved = load(destination, audit_sha256)
    files.require(saved.parent_chain == parent and saved.raw == raw, 'audit_output_changed')
    task.unchanged(source)
    unchanged(saved)  # After the source reread: do not return an earlier target verification.
    _source_metadata_unchanged(source)
    return dict(operation='query_audit_export', audit_sha256=audit_sha256, audit_bytes=len(raw),
                request_sha256=request_sha256, query_count=len(source.request.txids),
                created=True, source_file_rechecked=True, query_executed=False,
                signature_verified=False, real_funds_allowed=False)


def verify_audit(path: Path, expected_sha256: str) -> dict:
    """Check portable report integrity only; original file may no longer exist."""
    saved = load(path, expected_sha256)
    return dict(operation='query_audit_verify', audit_sha256=expected_sha256,
                audit_integrity_verified=True, source_file_rechecked=False,
                report=report_for(saved.request, saved.request_sha256))


def recheck(path: Path, expected_sha256: str, source: Path, request_sha256: str) -> dict:
    """Require BOTH independent pins; reread the actual source without executing it."""
    task.digest(expected_sha256)
    task.digest(request_sha256)
    task.absolute(path)
    task.absolute(source)
    saved = load(path, expected_sha256)
    files.require(saved.request_sha256 == request_sha256, 'audit_source_pin_mismatch')
    captured = task.load(source, request_sha256)
    files.require(encode(captured.request, request_sha256) == saved.raw, 'audit_source_content_mismatch')
    task.unchanged(captured)
    unchanged(saved)
    _source_metadata_unchanged(captured)
    return dict(operation='query_audit_recheck', audit_sha256=expected_sha256,
                request_sha256=request_sha256, audit_integrity_verified=True,
                source_file_rechecked=True, query_count=len(captured.request.txids),
                query_executed=False, signature_verified=False, backend_verified=False,
                ledger_replayed=False, retry_authorized=False, real_funds_allowed=False)


class Parser(task.Parser):
    def error(self, message):
        self.exit(64, 'Invalid task-audit arguments. Use --help; never supply wallet secrets.\n')


def main(argv=None) -> int:
    parser = Parser(description=__doc__)
    parser.add_argument('--no-real-funds', required=True, action='store_true')
    commands = parser.add_subparsers(dest='command', required=True, parser_class=Parser)
    inspect = commands.add_parser('inspect', help='audit current task content; do not execute')
    export = commands.add_parser('export', help='save a NEW audit report; do not execute')
    verify = commands.add_parser('verify', help='verify the report alone, not the original file')
    fresh = commands.add_parser('recheck', help='verify the report AND reread the independently pinned task')
    for command in (inspect, export, fresh):
        command.add_argument('--request', required=True, type=Path)
        command.add_argument('--request-sha256', required=True)
    export.add_argument('--destination', required=True, type=Path)
    for command in (verify, fresh):
        command.add_argument('--audit', required=True, type=Path)
        command.add_argument('--audit-sha256', required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == 'inspect':
            result = inspect_task(args.request, args.request_sha256)
        elif args.command == 'export':
            result = export_audit(args.request, args.request_sha256, args.destination)
        elif args.command == 'verify':
            result = verify_audit(args.audit, args.audit_sha256)
        else:
            result = recheck(args.audit, args.audit_sha256, args.request, args.request_sha256)
        text = json.dumps(result, sort_keys=True)
        files.require(len(text.encode('utf-8')) <= MAX_OUTPUT_BYTES, 'audit_output_limit')
        task.view.write_output(text)
        return 0
    except KeyboardInterrupt:
        print('Task audit interrupted. Preserve inputs and partial output; no complete audit result.', file=sys.stderr)
        return 130
    except (ValueError, OSError, RuntimeError, TypeError, KeyError, RecursionError):
        print('Task audit failed. Preserve inputs and partial output; no query or permission was issued.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
