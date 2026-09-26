#!/usr/bin/env python3
"""NO-FUNDS reconciliation evidence bound to a freshly replayed PUBLIC ledger.

Only the original verify-active command is permitted. No wallet authentication,
transaction submission, recovery, signing, output directory or automatic retry.
Trusted stopped inputs are required; this is not an atomic snapshot or finality.
"""
from __future__ import annotations

import sys
if __name__ == '__main__':
    sys.dont_write_bytecode = True

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import time

import reconciliation_view as view
import ledger_restore as ledger
from ledger_recovery_backend import RecoveryBackend, remaining, validate_reply

files = view.files
CHECK_SECONDS = 300
FIELDS = {**view.FIELDS, 'journal': 4096, 'backend': 4096, 'backend_sha256': 64}


@dataclass(frozen=True)
class Intent:
    evidence: view.Intent
    journal: Path
    backend: Path
    backend_sha256: str


def prepare(values: dict[str, str]) -> Intent:
    """Every input is checked before opening files or starting a native process."""
    files.require(type(values) is dict and set(values) == set(FIELDS), 'incomplete_ledger_check_input')
    evidence = view.prepare({key: values[key] for key in view.FIELDS})
    paths = []
    for key in ('journal', 'backend'):
        value = view.bounded(values[key], 'directory')
        path = Path(value)
        files.require(path.is_absolute() and '..' not in path.parts
                      and len(value.encode('utf-8')) <= FIELDS[key], 'bounded_absolute_path_required')
        paths.append(path)
    digest = view.bounded(values['backend_sha256'], 'report_sha256')
    files.require(files.HEX.fullmatch(digest) is not None and digest != '0' * 64,
                  'independent_backend_digest_required')
    files.require(not paths[0].is_relative_to(evidence.directory)
                  and not evidence.directory.is_relative_to(paths[0]), 'distinct_evidence_and_ledger_required')
    return Intent(evidence, *paths, digest)


class LedgerVerifier(RecoveryBackend):
    """Constrain the inherited fixed transport to exactly one read-only command."""
    def __init__(self, executable: Path, digest: str, journal: Path, pin):
        super().__init__(executable, digest)
        self.journal, self.pin = journal, pin

    def _run(self, args, pin, base, deadline):
        expected = ['verify-active', '--no-real-funds', '--source', str(self.journal),
                    '--checkpoint', self.pin.encoded]
        files.require(type(args) is list and args == expected and pin == self.pin and base is None,
                      'read_only_ledger_verification_required')
        return super()._run(args, pin, base, deadline)


def header_domain(raw: bytes, pin, manifest_digest: str) -> None:
    """Public framing precheck only. Original Rust still authenticates the ledger.

    Existing ActiveSegmentsV1 header: magic[0:8], network[8:40], signing domain
    [40:72], u32 commitment count[72:76], commitments[76:]. Not a genesis parser.
    """
    files.require(type(raw) is bytes and len(raw) == pin.header and len(raw) >= 76
                  and raw[:8] == b'ZVOPOL03'
                  and raw[8:40] == hashlib.sha256(b'zevune-orchard-lab-1').digest()
                  and raw[40:72].hex() == manifest_digest and manifest_digest != '0' * 64,
                  'ledger_signing_domain_mismatch')
    count = int.from_bytes(raw[72:76], 'big')
    files.require(count <= 65536 and len(raw) == 76 + 32 * count, 'invalid_active_header_extent')


@dataclass(frozen=True)
class EvidenceSnapshot:
    chain: tuple
    directory_stamp: tuple
    items: tuple


def evidence_snapshot(directory: Path, deadline: float) -> EvidenceSnapshot:
    remaining(deadline)
    chain = view._chain(directory)
    stamp = files.identity(directory.lstat())
    names = {'RECONCILE.json', 'wallet.journal'}
    # This only selects bounded IO; the viewer independently verifies pending
    # semantics and refuses symlinks, extra/missing files and wrong pins.
    if (directory / 'pending.tx').exists():
        names.add('pending.tx')
    ledger.names(directory, names, deadline=deadline)
    limits = {'RECONCILE.json': files.MAX_MANIFEST, 'wallet.journal': files.MAX_WALLET,
              'pending.tx': view.reconciliation.MAX_PAYMENT}
    items = tuple((name, ledger.snapshot(directory / name, limits[name], deadline=deadline))
                  for name in sorted(names))
    result = EvidenceSnapshot(chain, stamp, items)
    evidence_unchanged(directory, result, deadline)
    return result


def evidence_unchanged(directory: Path, before: EvidenceSnapshot, deadline: float) -> None:
    remaining(deadline)
    ledger.names(directory, {name for name, _ in before.items}, deadline=deadline)
    for name, captured in before.items:
        files.require(files.identity((directory / name).lstat()) == captured[0], 'evidence_changed')
    files.require(view._chain(directory) == before.chain
                  and files.identity(directory.lstat()) == before.directory_stamp, 'evidence_directory_changed')
    remaining(deadline)


def check(intent: Intent) -> dict:
    """Fresh native replay is mandatory for every success; no cached authority.

    The 300-second budget includes pre/post checks and transport. OS IO/cleanup
    can overrun wall time, but an expired budget never becomes a successful call.
    """
    files.require(type(intent) is Intent, 'invalid_ledger_check_intent')
    values = dict(directory=str(intent.evidence.directory), report_sha256=intent.evidence.report_sha256,
                  checkpoint=intent.evidence.checkpoint, genesis_sha256=intent.evidence.genesis_sha256,
                  journal=str(intent.journal), backend=str(intent.backend), backend_sha256=intent.backend_sha256)
    files.require(prepare(values) == intent, 'invalid_ledger_check_intent')
    deadline = time.monotonic() + CHECK_SECONDS
    before = evidence_snapshot(intent.evidence.directory, deadline)
    result = view.inspect(intent.evidence)
    evidence_unchanged(intent.evidence.directory, before, deadline)
    pin = view.Checkpoint.parse(intent.evidence.checkpoint)
    journal_chain = view._chain(intent.journal)
    journal_stamp = files.identity(intent.journal.lstat())
    history = ledger.archive_snapshot(intent.journal, pin, deadline=deadline)
    header = files.read_file(intent.journal / 'genesis', pin.header)
    files.require(header[1] == history[1]['genesis'][0]
                  and hashlib.sha256(header[0]).hexdigest() == history[1]['genesis'][1], 'ledger_header_changed')
    header_domain(header[0], pin, intent.evidence.genesis_sha256)
    # Reject linked executable parents before using the existing hash/identity
    # gate. No output path, shell, wallet secret or environment override exposed.
    view._chain(intent.backend.parent)
    remaining(deadline)
    backend = LedgerVerifier(intent.backend, intent.backend_sha256, intent.journal, pin)
    reply = backend.active(intent.journal, pin, deadline)
    validate_reply(reply, 'verify-active', pin)  # Reject malformed/inconsistent responses again at this boundary.
    remaining(deadline)
    files.require(ledger.archive_snapshot(intent.journal, pin, deadline=deadline) == history, 'ledger_changed')
    files.require(evidence_snapshot(intent.evidence.directory, deadline) == before, 'evidence_changed')
    # Recheck early-read ledger entries after the final evidence IO; neither
    # side gets a mutable verification cache or a promise of future immutability.
    ledger.names(intent.journal, set(history[1]), deadline=deadline)
    for name, captured in history[1].items():
        files.require(files.identity((intent.journal / name).lstat()) == captured[0], 'ledger_changed')
    files.require(view._chain(intent.journal) == journal_chain
                  and files.identity(intent.journal.lstat()) == journal_stamp, 'ledger_directory_changed')
    evidence_unchanged(intent.evidence.directory, before, deadline)
    remaining(deadline)
    summary = result.summary()
    summary.update(format='zevune-reconciliation-ledger-check-1', ledger_replayed=True,
                   checkpoint_domain_relation_verified=True, native_operation='verify-active',
                   native_backend_sha256=intent.backend_sha256, ledger_bytes=pin.length,
                   ledger_segments=pin.segments, genesis_manifest_validated=False,
                   pending_transaction_inclusion_verified=False, original_recovery_success_verified=False,
                   source_files_unchanged=True)
    return summary


def render(result: dict) -> str:
    return ('原生账本重放与对账检查点／签名域绑定核验完成。\n'
            f"历史检查点高度：{result['checkpoint_height']}\n"
            f"账本逻辑字节：{result['ledger_bytes']}；记录段数：{result['ledger_segments']}\n"
            f"待发送交易ID：{result['txid'] or '无；不是付款证明'}\n"
            '这只确认指定历史账本和报告的网络绑定，不证明该交易已入账。\n'
            '未认证钱包、未验证待发送交易授权、未验证创世文件分配；当前高度未知。\n'
            '广播和结算仍未知，不授权重新签名、清除预留或重试。NO-FUNDS。')


def main(argv=None) -> int:
    parser = view.Parser(description=__doc__)
    parser.add_argument('--no-real-funds', required=True, action='store_true')
    for name in FIELDS:
        parser.add_argument('--' + name.replace('_', '-'), required=True)
    parser.add_argument('--text', action='store_true')
    args = parser.parse_args(argv)
    try:
        result = check(prepare({key: getattr(args, key) for key in FIELDS}))
        view.write_output(render(result) if args.text else json.dumps(result, sort_keys=True))
        return 0
    except KeyboardInterrupt:
        print('Ledger check interrupted. Inputs retained; do not retry payment.', file=sys.stderr)
        return 130
    except (ValueError, OSError, RuntimeError, TypeError, KeyError, RecursionError):
        print('Ledger check failed. No settlement or retry permission; preserve all inputs.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
