#!/usr/bin/env python3
"""NO-FUNDS batch historical lookup: one fresh native replay, bounded full scans.

Reuse the original scanner for each requested txid, not a new ledger parser.
No persistent verification cache, partial batch success, wallet or network IO.
"""
from __future__ import annotations

import sys
if __name__ == '__main__':
    sys.dont_write_bytecode = True

import argparse
from dataclasses import asdict, dataclass, replace
import hashlib
import json
from pathlib import Path
import subprocess
import time

import ledger_transaction_lookup as single

MAX_TXIDS = 32  # Application batch bound, not a protocol or per-block limit.
BATCH_SECONDS = 300
MAX_OUTPUT_BYTES = 65536
COMMON_FIELDS = tuple(name for name in single.FIELDS if name != 'txid')


@dataclass(frozen=True)
class Intent:
    source: single.Intent
    txids: tuple[str, ...]


def prepare(values: dict) -> Intent:
    """Freeze all IDs and independent pins before any file access; no deduping."""
    single.files.require(type(values) is dict and set(values) == set(COMMON_FIELDS) | {'txids'},
                         'incomplete_batch_input')
    txids = values['txids']
    single.files.require(type(txids) in (tuple, list) and 1 <= len(txids) <= MAX_TXIDS,
                         'one_to_32_transaction_ids_required')
    single.files.require(all(type(item) is str and single.files.HEX.fullmatch(item) is not None
                             for item in txids), 'invalid_batch_transaction_id')
    single.files.require(len(set(txids)) == len(txids), 'duplicate_batch_transaction_id')
    common = {name: values[name] for name in COMMON_FIELDS}
    source = single.prepare(dict(common, txid=txids[0]))
    return Intent(source, tuple(txids))


def scan_requests(intent: Intent, pin, captured, header: bytes, deadline: float) -> tuple[single.Scan, ...]:
    """Framing-only helper; it never asserts native replay or grants authority.

    Reuse the exact existing full-archive scanner, including its external layout
    pin and all checks after a match. Time/IO is O(ids * archive bytes), not a
    one-pass index; all scans share the same absolute deadline and fingerprints.
    """
    scans = []
    for txid in intent.txids:
        single.checked.remaining(deadline)
        scan = single.scan_archive(replace(intent.source, txid=txid), pin, captured, header, deadline)
        single.files.require(type(scan) is single.Scan, 'invalid_batch_scan')
        if scans:
            single.files.require((scan.records, scan.transactions) == (scans[0].records, scans[0].transactions),
                                 'inconsistent_batch_history')
        scans.append(scan)
    single.checked.remaining(deadline)
    return tuple(scans)


def lookup_batch(intent: Intent) -> dict:
    """One actual native verifier call per successful batch. Never return a prefix."""
    single.files.require(type(intent) is Intent and type(intent.source) is single.Intent
                         and type(intent.txids) is tuple, 'invalid_batch_intent')
    values = {name: str(getattr(intent.source, name)) if name in ('journal', 'backend')
              else getattr(intent.source, name) for name in COMMON_FIELDS}
    single.files.require(prepare(dict(values, txids=intent.txids)) == intent, 'invalid_batch_intent')
    deadline = time.monotonic() + BATCH_SECONDS
    source = intent.source
    pin = single.Checkpoint.parse(source.checkpoint)
    chain = single.view._chain(source.journal)
    root_stamp = single.files.identity(source.journal.lstat())
    captured = single.ledger.archive_snapshot(source.journal, pin, deadline=deadline)
    header, identity = single.files.read_file(source.journal / 'genesis', pin.header)
    digest = hashlib.sha256(header).hexdigest()
    single.files.require((identity, digest) == captured[1]['genesis'] and digest == pin.genesis,
                         'batch_genesis_changed')
    single.checked.header_domain(header, pin, source.genesis_sha256)
    single.view._chain(source.backend.parent)
    single.checked.remaining(deadline)
    verifier = single.LookupVerifier(source.backend, source.backend_sha256, source.journal, pin)
    reply = verifier.active(source.journal, pin, deadline)
    single.checked.validate_reply(reply, 'verify-active', pin)
    single.checked.remaining(deadline)
    scans = scan_requests(intent, pin, captured, header, deadline)
    single.files.require(single.ledger.archive_snapshot(source.journal, pin, deadline=deadline) == captured,
                         'batch_archive_changed')
    single.ledger.names(source.journal, set(captured[1]), deadline=deadline)
    for name, before in captured[1].items():
        single.files.require(single.files.identity((source.journal / name).lstat()) == before[0],
                             'batch_archive_changed')
    single.files.require(single.view._chain(source.journal) == chain
                         and single.files.identity(source.journal.lstat()) == root_stamp,
                         'batch_directory_changed')
    single.checked.remaining(deadline)
    results = []
    for txid, scan in zip(intent.txids, scans):
        included = scan.match is not None
        results.append(dict(txid=txid, historical_inclusion_verified=included,
                            state='included_in_verified_history' if included else 'absent_from_verified_history',
                            occurrence=asdict(scan.match) if included else None,
                            subsequent_record_count=pin.height - scan.match.height if included else None))
    included_count = sum(row['historical_inclusion_verified'] for row in results)
    answer = dict(format='zevune-ledger-transaction-batch-1', checkpoint=pin.encoded,
                  checkpoint_height=pin.height, checkpoint_app_hash=pin.app_hash,
                  genesis_sha256=source.genesis_sha256, native_backend_sha256=source.backend_sha256,
                  query_count=len(intent.txids), included_count=included_count,
                  absent_count=len(intent.txids) - included_count, results=results,
                  batch_complete=True, ledger_replayed=True, native_replay_count=1,
                  history_scan_count=len(scans), historical_search_complete=True,
                  scanned_records_per_query=scans[0].records, scanned_transactions_per_query=scans[0].transactions,
                  ledger_bytes=pin.length, source_files_unchanged=True,
                  current_chain_height=None, broadcast_status='unknown', settlement_status='unknown',
                  wallet_authenticated=False, recipient_or_amount_verified=False, finality_verified=False,
                  retry_authorized=False, portable_proof_generated=False, real_funds_allowed=False)
    single.files.require(len(json.dumps(answer, sort_keys=True).encode('utf-8')) <= MAX_OUTPUT_BYTES,
                         'batch_output_limit')
    single.checked.remaining(deadline)
    return answer


def render(result: dict) -> str:
    lines = [f"历史批量核查完成：{result['query_count']}笔，纳入{result['included_count']}笔，缺席{result['absent_count']}笔。",
             '一次原生重放；每个交易ID分别完整扫描。不是付款凭证或共识最终性。']
    for row in result['results']:
        lines.append(single.render(dict(row, checkpoint_height=result['checkpoint_height'])))
    return '\n\n'.join(lines)


class Parser(single.view.Parser):
    def error(self, message):
        self.exit(64, 'Invalid batch lookup arguments. Use --help; never supply wallet secrets.\n')


class BoundedTxids(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        current = getattr(namespace, self.dest, None) or ()
        if len(current) >= MAX_TXIDS:
            parser.error('too many transaction ids')
        setattr(namespace, self.dest, (*current, values))


def main(argv=None) -> int:
    parser = Parser(description=__doc__)
    parser.add_argument('--no-real-funds', required=True, action='store_true')
    for name in COMMON_FIELDS:
        parser.add_argument('--' + name.replace('_', '-'), required=True)
    parser.add_argument('--txid', dest='txids', required=True, action=BoundedTxids,
                        help='repeat for 1-32 distinct transaction IDs; caller order is preserved')
    parser.add_argument('--text', action='store_true')
    args = parser.parse_args(argv)
    try:
        result = lookup_batch(prepare({name: getattr(args, name) for name in (*COMMON_FIELDS, 'txids')}))
        text = render(result) if args.text else json.dumps(result, sort_keys=True)
        single.files.require(len(text.encode('utf-8')) <= MAX_OUTPUT_BYTES, 'batch_output_limit')
        single.view.write_output(text)
        return 0
    except KeyboardInterrupt:
        print('Batch lookup interrupted. No complete batch result; do not retry payment.', file=sys.stderr)
        return 130
    except (ValueError, OSError, RuntimeError, TypeError, KeyError, RecursionError, subprocess.SubprocessError):
        print('Batch lookup failed. No complete batch result or retry permission; preserve inputs.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
