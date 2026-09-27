#!/usr/bin/env python3
"""NO-FUNDS historical transaction lookup in an independently pinned PUBLIC archive.

A fresh original Rust verify-active replay is mandatory before locating bytes.
No wallet, network, transaction submission, persistent index or retry permission.
An inclusion here is historical ledger evidence, never consensus finality.
"""
from __future__ import annotations

import sys
if __name__ == '__main__':
    sys.dont_write_bytecode = True

from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import subprocess
import time

import reconciliation_ledger_check as checked
from wallet_backup_backend import Backend, metadata_identity

files, ledger, view = checked.files, checked.ledger, checked.view
Checkpoint = view.Checkpoint
LOOKUP_SECONDS = 300
MAX_TRANSACTIONS = 16
MAX_TRANSACTION_BYTES = 28134  # Existing LAB2/IPC4 limit, checked against native contracts.
MAX_RECORD_BYTES = 114 + MAX_TRANSACTIONS * (4 + MAX_TRANSACTION_BYTES)
FIELDS = ('journal', 'checkpoint', 'genesis_sha256', 'txid', 'backend', 'backend_sha256')


@dataclass(frozen=True)
class Intent:
    journal: Path
    checkpoint: str
    genesis_sha256: str
    txid: str
    backend: Path
    backend_sha256: str


def prepare(values: dict[str, str]) -> Intent:
    """Pure checks of all caller inputs; neither paths nor pins come from a file."""
    files.require(type(values) is dict and set(values) == set(FIELDS), 'incomplete_lookup_input')
    paths = {}
    for name in ('journal', 'backend'):
        text = view.bounded(values[name], 'directory')
        path = Path(text)
        files.require(path.is_absolute() and '..' not in path.parts
                      and len(text.encode('utf-8')) <= 4096, 'bounded_absolute_path_required')
        paths[name] = path
    Checkpoint.parse(values['checkpoint'])
    for name in ('genesis_sha256', 'backend_sha256', 'txid'):
        text = values[name]
        files.require(type(text) is str and files.HEX.fullmatch(text) is not None, 'independent_lookup_digest_required')
        if name != 'txid':
            files.require(text != '0' * 64, 'nonzero_lookup_domain_and_backend_required')
    return Intent(paths['journal'], values['checkpoint'], values['genesis_sha256'], values['txid'],
                  paths['backend'], values['backend_sha256'])


class SingleLinkBackend(Backend):
    """Keep the original digest/handle gate, additionally reject alternate links.

    The inherited transport invokes this gate both before process creation and
    after process exit. This is an identity check, not a lock against hostile IO.
    """
    def _check(self):
        before = self.path.lstat()
        files.require(before.st_nlink == 1, 'single_link_lookup_backend_required')
        identity = super()._check()
        after = self.path.lstat()
        files.require(after.st_nlink == 1 and metadata_identity(before) == identity == metadata_identity(after),
                      'lookup_backend_changed')
        return identity


class LookupVerifier(checked.LedgerVerifier):
    def __init__(self, executable: Path, digest: str, journal: Path, pin):
        super().__init__(executable, digest, journal, pin)
        self.binary = SingleLinkBackend(executable, digest)


@dataclass(frozen=True)
class Occurrence:
    height: int
    record_block_id: str
    transaction_index: int  # Zero based in the stored block, not a wallet index.
    segment: str
    record_offset: int  # Offset of the u32 frame prefix within this physical segment.
    transaction_bytes: int


@dataclass(frozen=True)
class Scan:
    """Public byte-location result only. Constructing this never grants verification."""
    records: int
    transactions: int
    match: Occurrence | None


def scan_segment(raw: bytes, name: str, start_height: int, previous_hash: bytes | None,
                 txid: str, deadline: float):
    """Parse ONLY the existing Record framing. No Orchard decoder or authorization.

    Every frame is consumed, including bytes after a match. Keep one segment and
    at most one match, rather than accumulating history or trusting an index.
    """
    checked.remaining(deadline)
    files.require(type(raw) is bytes and 150 <= len(raw) <= ledger.SEGMENT_BYTES, 'invalid_lookup_segment')
    cursor, height, count, match, first_size = 0, start_height, 0, None, None
    data = memoryview(raw)
    while cursor < len(raw):
        checked.remaining(deadline)
        files.require(len(raw) - cursor >= 4, 'truncated_lookup_frame')
        size = int.from_bytes(data[cursor:cursor + 4], 'big')
        end = cursor + 4 + size + 32
        files.require(114 <= size <= MAX_RECORD_BYTES and end <= len(raw), 'invalid_lookup_frame_size')
        if first_size is None:
            first_size = size + 36
        body = data[cursor + 4:cursor + 4 + size]
        files.require(body[:8] == b'ZVOBLK01'
                      and hashlib.sha256(body).digest() == data[end - 32:end], 'lookup_frame_damage')
        height += 1
        files.require(int.from_bytes(body[8:16], 'big') == height, 'lookup_height_gap')
        if previous_hash is not None:
            files.require(body[48:80] == previous_hash, 'lookup_history_disconnected')
        previous_hash = bytes(body[80:112])
        number = int.from_bytes(body[112:114], 'big')
        files.require(number <= MAX_TRANSACTIONS, 'lookup_transaction_count')
        position = 114
        for index in range(number):
            checked.remaining(deadline)
            files.require(position + 4 <= size, 'truncated_lookup_transaction_length')
            length = int.from_bytes(body[position:position + 4], 'big')
            position += 4
            files.require(length <= MAX_TRANSACTION_BYTES and position + length <= size,
                          'invalid_lookup_transaction_extent')
            transaction = body[position:position + length]
            if hashlib.sha256(transaction).hexdigest() == txid:
                files.require(match is None, 'ambiguous_lookup_transaction')
                match = Occurrence(height, bytes(body[16:48]).hex(), index, name, cursor, length)
            position += length
        files.require(position == size, 'lookup_record_trailing_bytes')
        count += number
        cursor = end
    checked.remaining(deadline)
    return height, count, match, previous_hash, first_size


def scan_archive(intent: Intent, pin, captured, header: bytes, deadline: float) -> Scan:
    """Locate a txid while recomputing the exact independently pinned layout hash."""
    layout = hashlib.sha256(b'ZVARLY01' + len(header).to_bytes(4, 'big') + header
                            + pin.segments.to_bytes(4, 'big'))
    height, total, match, previous_hash, previous_size = 0, 0, None, None, None
    for index in range(pin.segments):
        checked.remaining(deadline)
        name = f'{index:08}.journal'
        raw, identity = files.read_file(intent.journal / name, ledger.SEGMENT_BYTES)
        files.require((identity, hashlib.sha256(raw).hexdigest()) == captured[1][name], 'lookup_segment_changed')
        layout.update(index.to_bytes(4, 'big') + len(raw).to_bytes(4, 'big'))
        layout.update(raw)
        height, count, found, previous_hash, first_size = scan_segment(
            raw, name, height, previous_hash, intent.txid, deadline)
        if previous_size is not None:
            files.require(previous_size + first_size > ledger.SEGMENT_BYTES, 'lookup_early_rotation')
        previous_size = len(raw)
        files.require(height <= pin.height, 'lookup_height_exceeded')
        total += count
        if found is not None:
            files.require(match is None, 'ambiguous_lookup_transaction')
            match = found
    files.require(height == pin.height and (height == 0 or previous_hash.hex() == pin.app_hash), 'lookup_tip_mismatch')
    files.require(layout.hexdigest() == pin.encoded[192:256], 'lookup_layout_mismatch')
    checked.remaining(deadline)
    return Scan(height, total, match)


def lookup(intent: Intent) -> dict:
    files.require(type(intent) is Intent, 'invalid_lookup_intent')
    values = {name: str(getattr(intent, name)) if name in ('journal', 'backend') else getattr(intent, name)
              for name in FIELDS}
    files.require(prepare(values) == intent, 'invalid_lookup_intent')
    deadline = time.monotonic() + LOOKUP_SECONDS
    pin = Checkpoint.parse(intent.checkpoint)
    chain, root_stamp = view._chain(intent.journal), files.identity(intent.journal.lstat())
    captured = ledger.archive_snapshot(intent.journal, pin, deadline=deadline)
    header, identity = files.read_file(intent.journal / 'genesis', pin.header)
    files.require((identity, hashlib.sha256(header).hexdigest()) == captured[1]['genesis']
                  and hashlib.sha256(header).hexdigest() == pin.genesis, 'lookup_genesis_changed')
    checked.header_domain(header, pin, intent.genesis_sha256)
    view._chain(intent.backend.parent)
    checked.remaining(deadline)
    backend = LookupVerifier(intent.backend, intent.backend_sha256, intent.journal, pin)
    reply = backend.active(intent.journal, pin, deadline)
    checked.validate_reply(reply, 'verify-active', pin)
    checked.remaining(deadline)
    # There is no path from a framing-only scan or a cached result to success.
    scan = scan_archive(intent, pin, captured, header, deadline)
    files.require(ledger.archive_snapshot(intent.journal, pin, deadline=deadline) == captured, 'lookup_archive_changed')
    ledger.names(intent.journal, set(captured[1]), deadline=deadline)
    for name, before in captured[1].items():
        files.require(files.identity((intent.journal / name).lstat()) == before[0], 'lookup_archive_changed')
    files.require(view._chain(intent.journal) == chain and files.identity(intent.journal.lstat()) == root_stamp,
                  'lookup_directory_changed')
    checked.remaining(deadline)
    included = scan.match is not None
    return dict(format='zevune-ledger-transaction-lookup-1', txid=intent.txid, checkpoint=pin.encoded,
                checkpoint_height=pin.height, checkpoint_app_hash=pin.app_hash, genesis_sha256=intent.genesis_sha256,
                native_backend_sha256=intent.backend_sha256, ledger_replayed=True, historical_search_complete=True,
                historical_inclusion_verified=included,
                state='included_in_verified_history' if included else 'absent_from_verified_history',
                occurrence=asdict(scan.match) if included else None,
                subsequent_record_count=pin.height - scan.match.height if included else None,
                scanned_records=scan.records, scanned_transactions=scan.transactions, ledger_bytes=pin.length,
                current_chain_height=None, broadcast_status='unknown', settlement_status='unknown',
                wallet_authenticated=False, recipient_or_amount_verified=False, finality_verified=False,
                retry_authorized=False, portable_proof_generated=False, source_files_unchanged=True,
                real_funds_allowed=False)


def render(result: dict) -> str:
    occurrence = result['occurrence']
    status = ('该交易字节已纳入指定历史账本。\n'
              f"记录高度：{occurrence['height']}；块内序号（从0开始）：{occurrence['transaction_index']}\n"
              f"记录文件：{occurrence['segment']}；帧偏移：{occurrence['record_offset']}\n"
              if occurrence is not None else '指定历史账本中没有该交易；不能据此重试付款。\n')
    return (status + f"检查点高度：{result['checkpoint_height']}；交易ID：{result['txid']}\n"
            '当前链高度、广播和结算状态仍未知。后续记录数不是共识确认数。\n'
            '没有验证收款人、金额或钱包；没有生成可独立验证的纳入证明。NO-FUNDS。')


def main(argv=None) -> int:
    parser = view.Parser(description=__doc__)
    parser.add_argument('--no-real-funds', required=True, action='store_true')
    for name in FIELDS:
        parser.add_argument('--' + name.replace('_', '-'), required=True)
    parser.add_argument('--text', action='store_true')
    args = parser.parse_args(argv)
    try:
        result = lookup(prepare({name: getattr(args, name) for name in FIELDS}))
        view.write_output(render(result) if args.text else json.dumps(result, sort_keys=True))
        return 0
    except KeyboardInterrupt:
        print('Historical lookup interrupted; no retry permission. Preserve all inputs.', file=sys.stderr)
        return 130
    except (ValueError, OSError, RuntimeError, TypeError, KeyError, RecursionError, subprocess.SubprocessError):
        print('Historical lookup failed; no inclusion or settlement claim. Preserve all inputs.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
