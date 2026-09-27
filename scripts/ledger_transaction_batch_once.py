#!/usr/bin/env python3
"""NO-FUNDS multi-ID history lookup with one native replay and one record pass.

Pre/post fingerprints and native replay still read the archive separately.
One record pass does NOT mean only one physical read, an index or finality.
The original batch CLI and desktops retain their existing result contracts.
"""
from __future__ import annotations

import sys
if __name__ == '__main__':
    sys.dont_write_bytecode = True

from dataclasses import asdict
import hashlib
import json
import subprocess
import time

import ledger_transaction_batch as batch

single = batch.single
Intent = batch.Intent
prepare = batch.prepare
ONCE_SECONDS = 300
MAX_OUTPUT_BYTES = batch.MAX_OUTPUT_BYTES


def scan_once(intent: Intent, pin, captured, header: bytes, deadline: float) -> tuple[single.Scan, ...]:
    """Public framing only: no replay authorization or partial batch result.

    Share the original segment decoder, hash each transaction once and look up
    its digest in a bounded ID set. Continue through the whole pinned layout.
    """
    single.checked.remaining(deadline)
    single.files.require(type(intent) is Intent and type(intent.txids) is tuple
                         and 1 <= len(intent.txids) <= batch.MAX_TXIDS
                         and all(type(x) is str and single.files.HEX.fullmatch(x) is not None for x in intent.txids)
                         and len(set(intent.txids)) == len(intent.txids), 'invalid_once_scan_request')
    requested = frozenset(intent.txids)
    layout = hashlib.sha256(b'ZVARLY01' + len(header).to_bytes(4, 'big') + header
                            + pin.segments.to_bytes(4, 'big'))
    height, total, previous_hash, previous_size = 0, 0, None, None
    matches = {}
    for index in range(pin.segments):
        single.checked.remaining(deadline)
        name = f'{index:08}.journal'
        raw, identity = single.files.read_file(intent.source.journal / name, single.ledger.SEGMENT_BYTES)
        single.files.require((identity, hashlib.sha256(raw).hexdigest()) == captured[1][name],
                             'once_segment_changed')
        layout.update(index.to_bytes(4, 'big') + len(raw).to_bytes(4, 'big'))
        layout.update(raw)
        height, count, found, previous_hash, first_size = single.scan_segment_many(
            raw, name, height, previous_hash, requested, deadline)
        if previous_size is not None:
            single.files.require(previous_size + first_size > single.ledger.SEGMENT_BYTES, 'once_early_rotation')
        previous_size = len(raw)
        single.files.require(height <= pin.height, 'once_height_exceeded')
        total += count
        for txid, occurrence in found.items():
            single.files.require(txid not in matches, 'ambiguous_lookup_transaction')
            matches[txid] = occurrence
    single.files.require(height == pin.height and (height == 0 or previous_hash.hex() == pin.app_hash),
                         'once_tip_mismatch')
    single.files.require(layout.hexdigest() == pin.encoded[192:256], 'once_layout_mismatch')
    single.checked.remaining(deadline)
    return tuple(single.Scan(height, total, matches.get(txid)) for txid in intent.txids)


def lookup_batch_once(intent: Intent) -> dict:
    """Fresh original verification, complete bounded scan, then freshness checks."""
    single.files.require(type(intent) is Intent and type(intent.source) is single.Intent
                         and type(intent.txids) is tuple, 'invalid_once_intent')
    values = {name: str(getattr(intent.source, name)) if name in ('journal', 'backend')
              else getattr(intent.source, name) for name in batch.COMMON_FIELDS}
    single.files.require(prepare(dict(values, txids=intent.txids)) == intent, 'invalid_once_intent')
    deadline = time.monotonic() + ONCE_SECONDS
    source = intent.source
    pin = single.Checkpoint.parse(source.checkpoint)
    chain, root_stamp = single.view._chain(source.journal), single.files.identity(source.journal.lstat())
    captured = single.ledger.archive_snapshot(source.journal, pin, deadline=deadline)
    header, identity = single.files.read_file(source.journal / 'genesis', pin.header)
    digest = hashlib.sha256(header).hexdigest()
    single.files.require((identity, digest) == captured[1]['genesis'] and digest == pin.genesis,
                         'once_genesis_changed')
    single.checked.header_domain(header, pin, source.genesis_sha256)
    single.view._chain(source.backend.parent)
    single.checked.remaining(deadline)
    verifier = single.LookupVerifier(source.backend, source.backend_sha256, source.journal, pin)
    reply = verifier.active(source.journal, pin, deadline)
    single.checked.validate_reply(reply, 'verify-active', pin)
    single.checked.remaining(deadline)
    scans = scan_once(intent, pin, captured, header, deadline)
    single.files.require(single.ledger.archive_snapshot(source.journal, pin, deadline=deadline) == captured,
                         'once_archive_changed')
    single.ledger.names(source.journal, set(captured[1]), deadline=deadline)
    for name, before in captured[1].items():
        single.files.require(single.files.identity((source.journal / name).lstat()) == before[0],
                             'once_archive_changed')
    single.files.require(single.view._chain(source.journal) == chain
                         and single.files.identity(source.journal.lstat()) == root_stamp, 'once_directory_changed')
    single.checked.remaining(deadline)
    results = []
    for txid, scan in zip(intent.txids, scans):
        included = scan.match is not None
        results.append(dict(txid=txid, historical_inclusion_verified=included,
                            state='included_in_verified_history' if included else 'absent_from_verified_history',
                            occurrence=asdict(scan.match) if included else None,
                            subsequent_record_count=pin.height - scan.match.height if included else None))
    included_count = sum(row['historical_inclusion_verified'] for row in results)
    answer = dict(format='zevune-ledger-transaction-batch-once-1', checkpoint=pin.encoded,
                  checkpoint_height=pin.height, checkpoint_app_hash=pin.app_hash,
                  genesis_sha256=source.genesis_sha256, native_backend_sha256=source.backend_sha256,
                  query_count=len(intent.txids), included_count=included_count,
                  absent_count=len(intent.txids) - included_count, results=results,
                  batch_complete=True, ledger_replayed=True, native_replay_count=1, history_scan_count=1,
                  historical_search_complete=True, scanned_records=scans[0].records,
                  scanned_transactions=scans[0].transactions, ledger_bytes=pin.length,
                  source_files_unchanged=True, current_chain_height=None,
                  broadcast_status='unknown', settlement_status='unknown', wallet_authenticated=False,
                  recipient_or_amount_verified=False, finality_verified=False, retry_authorized=False,
                  portable_proof_generated=False, real_funds_allowed=False)
    single.files.require(len(json.dumps(answer, sort_keys=True).encode('utf-8')) <= MAX_OUTPUT_BYTES,
                         'once_output_limit')
    single.checked.remaining(deadline)
    return answer


def render(result: dict) -> str:
    lines = [f"单遍历史核查完成：{result['query_count']}笔，纳入{result['included_count']}笔，缺席{result['absent_count']}笔。",
             '一次原生重放＋一次记录扫描；前后指纹复验另行读盘。不是结算或最终性证明。']
    for row in result['results']:
        lines.append(single.render(dict(row, checkpoint_height=result['checkpoint_height'])))
    return '\n\n'.join(lines)


def main(argv=None) -> int:
    parser = batch.Parser(description=__doc__)
    parser.add_argument('--no-real-funds', required=True, action='store_true')
    for name in batch.COMMON_FIELDS:
        parser.add_argument('--' + name.replace('_', '-'), required=True)
    parser.add_argument('--txid', dest='txids', required=True, action=batch.BoundedTxids)
    parser.add_argument('--text', action='store_true')
    args = parser.parse_args(argv)
    try:
        result = lookup_batch_once(prepare({name: getattr(args, name) for name in (*batch.COMMON_FIELDS, 'txids')}))
        text = render(result) if args.text else json.dumps(result, sort_keys=True)
        single.files.require(len(text.encode('utf-8')) <= MAX_OUTPUT_BYTES, 'once_output_limit')
        single.view.write_output(text)
        return 0
    except KeyboardInterrupt:
        print('One-pass lookup interrupted. No complete result or retry permission.', file=sys.stderr)
        return 130
    except (ValueError, OSError, RuntimeError, TypeError, KeyError, RecursionError, subprocess.SubprocessError):
        print('One-pass lookup failed. No complete result or retry permission; preserve inputs.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
