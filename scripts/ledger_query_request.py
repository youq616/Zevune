#!/usr/bin/env python3
"""NO-FUNDS portable historical query requests: create, inspect, explicit run.

Requests contain independent public pins and IDs, never executable/ledger paths.
A digest is integrity, not a signature or permission to skip a fresh replay.
"""
from __future__ import annotations

import sys
if __name__ == '__main__':
    sys.dont_write_bytecode = True

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import subprocess

import ledger_transaction_batch_once as once

files, view = once.single.files, once.single.view
FORMAT = 'zevune-ledger-query-request-1'
PROFILE = 'zevune-ledger-transaction-batch-once-1'
MAX_REQUEST_BYTES = 8192
MAX_OUTPUT_BYTES = once.MAX_OUTPUT_BYTES + MAX_REQUEST_BYTES
FIELDS = {'format', 'query_profile', 'checkpoint', 'genesis_sha256',
          'backend_sha256', 'txids', 'real_funds_allowed'}


def digest(value: str) -> str:
    files.require(type(value) is str and files.HEX.fullmatch(value) is not None, 'independent_request_digest_required')
    return value


def absolute(value: Path) -> Path:
    files.require(isinstance(value, Path), 'request_path_type')
    text = view.bounded(str(value), 'directory')
    files.require(value.is_absolute() and '..' not in value.parts and len(text.encode('utf-8')) <= 4096,
                  'absolute_bounded_request_path_required')
    return value


@dataclass(frozen=True)
class Request:
    checkpoint: str
    genesis_sha256: str
    backend_sha256: str
    txids: tuple[str, ...]

    def document(self) -> dict:
        return dict(format=FORMAT, query_profile=PROFILE, checkpoint=self.checkpoint,
                    genesis_sha256=self.genesis_sha256, backend_sha256=self.backend_sha256,
                    txids=list(self.txids), real_funds_allowed=False)


def prepare(checkpoint: str, genesis_sha256: str, backend_sha256: str, txids) -> Request:
    """Pure public-input validation. No paths, native call, normalization or sort."""
    once.single.Checkpoint.parse(checkpoint)
    for value in (genesis_sha256, backend_sha256):
        files.require(digest(value) != '0' * 64, 'nonzero_request_domain_and_backend_required')
    files.require(type(txids) in (list, tuple) and 1 <= len(txids) <= once.batch.MAX_TXIDS,
                  'bounded_request_ids_required')
    files.require(all(type(item) is str and files.HEX.fullmatch(item) is not None for item in txids),
                  'invalid_request_transaction_id')
    files.require(len(set(txids)) == len(txids), 'duplicate_request_transaction_id')
    return Request(checkpoint, genesis_sha256, backend_sha256, tuple(txids))


def encode(request: Request) -> bytes:
    files.require(type(request) is Request and type(request.txids) is tuple, 'invalid_request_object')
    files.require(prepare(request.checkpoint, request.genesis_sha256, request.backend_sha256, request.txids) == request,
                  'invalid_request_object')
    raw = files.canonical(request.document())
    files.require(len(raw) <= MAX_REQUEST_BYTES, 'request_size_limit')
    return raw


def decode(raw: bytes, expected_sha256: str) -> Request:
    digest(expected_sha256)
    files.require(type(raw) is bytes and 0 < len(raw) <= MAX_REQUEST_BYTES, 'bounded_request_required')
    files.require(hashlib.sha256(raw).hexdigest() == expected_sha256, 'request_digest_mismatch')
    def unique(pairs):
        result = {}
        for key, value in pairs:
            files.require(key not in result, 'duplicate_request_field')
            result[key] = value
        return result
    def nonfinite(_):
        raise ValueError('nonfinite_request_value')
    data = json.loads(raw.decode('utf-8'), object_pairs_hook=unique, parse_constant=nonfinite)
    files.require(type(data) is dict and set(data) == FIELDS, 'request_fields_mismatch')
    files.require(data['format'] == FORMAT and data['query_profile'] == PROFILE
                  and data['real_funds_allowed'] is False and type(data['txids']) is list,
                  'request_profile_mismatch')
    request = prepare(data['checkpoint'], data['genesis_sha256'], data['backend_sha256'], data['txids'])
    files.require(raw == encode(request), 'noncanonical_request')
    return request


@dataclass(frozen=True)
class Snapshot:
    path: Path
    request: Request
    raw: bytes
    identity: tuple
    parent_chain: tuple


def unchanged(snapshot: Snapshot) -> None:
    files.require(view._chain(snapshot.path.parent) == snapshot.parent_chain, 'request_parent_changed')
    files.require(files.read_file(snapshot.path, MAX_REQUEST_BYTES) == (snapshot.raw, snapshot.identity),
                  'request_file_changed')
    files.require(view._chain(snapshot.path.parent) == snapshot.parent_chain, 'request_parent_changed')


def load(path: Path, expected_sha256: str) -> Snapshot:
    digest(expected_sha256)
    absolute(path)
    chain = view._chain(path.parent)
    raw, identity = files.read_file(path, MAX_REQUEST_BYTES)
    request = decode(raw, expected_sha256)
    snapshot = Snapshot(path, request, raw, identity, chain)
    unchanged(snapshot)
    return snapshot


def create(request: Request, destination: Path) -> dict:
    raw = encode(request)  # Validate all content before accessing a path.
    absolute(destination)
    chain = view._chain(destination.parent)
    files.write_new(destination, raw)  # Exclusive creation, original file fsync; never delete partial output.
    expected = hashlib.sha256(raw).hexdigest()
    captured = load(destination, expected)
    files.require(captured.parent_chain == chain and captured.raw == raw, 'request_output_changed')
    return dict(operation='query_request_create', request_sha256=expected, request_bytes=len(raw),
                query_count=len(request.txids), created=True, execution_performed=False,
                signature_verified=False, real_funds_allowed=False)


def inspect_request(path: Path, expected_sha256: str) -> dict:
    snapshot = load(path, expected_sha256)
    return dict(operation='query_request_inspect', request_sha256=expected_sha256,
                request_integrity_verified=True, request=snapshot.request.document(),
                execution_performed=False, signature_verified=False, real_funds_allowed=False)


def run_request(path: Path, expected_sha256: str, journal: Path, backend: Path) -> dict:
    """Explicit run only: the file cannot select a path, bypass pins or cache success.

    The unchanged native core retains its own 300-second budget. Bounded request
    reads occur outside that budget; no new whole-command hard deadline is claimed.
    """
    digest(expected_sha256)
    for value in (path, journal, backend):
        absolute(value)
    snapshot = load(path, expected_sha256)
    request = snapshot.request
    intent = once.prepare(dict(journal=str(journal), backend=str(backend), checkpoint=request.checkpoint,
                               genesis_sha256=request.genesis_sha256, backend_sha256=request.backend_sha256,
                               txids=request.txids))
    unchanged(snapshot)
    result = once.lookup_batch_once(intent)  # Every success requires the real original native verifier.
    unchanged(snapshot)  # Even a completed query must not authorize a changed task file.
    return dict(operation='query_request_run', request_sha256=expected_sha256, request_file_unchanged=True,
                signature_verified=False, real_funds_allowed=False, result=result)


class Parser(once.batch.Parser):
    def error(self, message):
        self.exit(64, 'Invalid query-request arguments. Use --help; never supply wallet secrets.\n')


def main(argv=None) -> int:
    parser = Parser(description=__doc__)
    parser.add_argument('--no-real-funds', required=True, action='store_true')
    commands = parser.add_subparsers(dest='command', required=True, parser_class=Parser)
    make = commands.add_parser('create', help='write a NEW path-free task; never execute it')
    for name in ('checkpoint', 'genesis-sha256', 'backend-sha256'):
        make.add_argument('--' + name, required=True)
    make.add_argument('--txid', dest='txids', required=True, action=once.batch.BoundedTxids)
    make.add_argument('--destination', required=True, type=Path)
    inspect = commands.add_parser('inspect', help='check the external digest and show the task without execution')
    run = commands.add_parser('run', help='explicitly perform a fresh verified query using local paths')
    for command in (inspect, run):
        command.add_argument('--request', required=True, type=Path)
        command.add_argument('--request-sha256', required=True)
    run.add_argument('--journal', required=True, type=Path)
    run.add_argument('--backend', required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == 'create':
            result = create(prepare(args.checkpoint, args.genesis_sha256, args.backend_sha256, args.txids), args.destination)
        elif args.command == 'inspect':
            result = inspect_request(args.request, args.request_sha256)
        else:
            result = run_request(args.request, args.request_sha256, args.journal, args.backend)
        text = json.dumps(result, sort_keys=True)
        files.require(len(text.encode('utf-8')) <= MAX_OUTPUT_BYTES, 'request_output_limit')
        view.write_output(text)
        return 0
    except KeyboardInterrupt:
        print('Query request interrupted. Preserve existing and partial output; no complete result.', file=sys.stderr)
        return 130
    except (ValueError, OSError, RuntimeError, TypeError, KeyError, RecursionError, subprocess.SubprocessError):
        print('Query request failed. Preserve inputs and partial output; no complete result or retry permission.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
