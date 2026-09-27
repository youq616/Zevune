#!/usr/bin/env python3
"""NO-FUNDS batch historical lookup GUI; fresh native verification, never payment.

Reuse the existing worker admission and observation lifecycle. Multiline edits
are synchronized at action boundaries as well as through Tk's modified event.
No shared globals are replaced and no original batch/scanner rules are changed.
"""
from __future__ import annotations

import sys
if __name__ == '__main__':
    sys.dont_write_bytecode = True

from dataclasses import dataclass, replace
import queue
import threading

import ledger_transaction_batch as batch
import ledger_transaction_desktop as single_ui

lifecycle = single_ui.lifecycle
files = batch.single.files
MAX_TEXT_CHARS = batch.MAX_TXIDS * 66  # 32 ASCII IDs, CRLF separators and one terminal CRLF.
NOTICE = 'NO-FUNDS｜批量查询指定历史；全部完成才显示，不是付款或重试许可。'
FAILURE = '批量历史查询未完成；没有有效的完整批次结果。保留原文件，不要重签或重试付款。'


def parse_ids(text: str) -> tuple[str, ...]:
    """Accept one ID per LF/CRLF line, optionally one final newline; no trimming."""
    files.require(type(text) is str and 0 < len(text) <= MAX_TEXT_CHARS, 'bounded_batch_text_required')
    normalized = text.replace('\r\n', '\n')
    if normalized.endswith('\n'):
        normalized = normalized[:-1]
    ids = tuple(normalized.split('\n'))
    files.require(1 <= len(ids) <= batch.MAX_TXIDS and all(files.HEX.fullmatch(item) is not None for item in ids),
                  'one_complete_transaction_id_per_line_required')
    files.require(len(set(ids)) == len(ids), 'duplicate_batch_transaction_id')
    return ids


def prepare(values: dict[str, str], text: str) -> batch.Intent:
    files.require(type(values) is dict and set(values) == set(batch.COMMON_FIELDS), 'incomplete_batch_form')
    return batch.prepare(dict(values, txids=parse_ids(text)))


def review_text(intent: batch.Intent) -> str:
    labels = dict(zip(batch.single.FIELDS, single_ui.LABELS))
    fields = '\n\n'.join(f'{labels[name]}\n{getattr(intent.source, name)}' for name in batch.COMMON_FIELDS)
    ids = '\n'.join(f'{index + 1:02d}  {txid}' for index, txid in enumerate(intent.txids))
    return (fields + f'\n\n完整冻结的查询清单（{len(intent.txids)}项，顺序不变）\n' + ids +
            '\n\n默认取消。确认后只执行一次原 verify-active，再逐ID完整扫描。'
            '\n整批共用300秒预算；不是一次扫描索引，系统IO/收尾可能更久。'
            '\n任一失败使整批失败；没有部分成功、自动重试或付款授权。')


@dataclass(frozen=True)
class BatchDisplay(lifecycle.DisplayResult):
    # Base txid is always None; copy uses this immutable ordered collection.
    txids: tuple[str, ...]


def present(result: dict, intent: batch.Intent) -> BatchDisplay:
    """Strict public presentation contract, not a replacement native verifier."""
    files.require(type(intent) is batch.Intent and type(intent.source) is batch.single.Intent,
                  'invalid_batch_display_intent')
    values = {name: str(getattr(intent.source, name)) if name in ('journal', 'backend')
              else getattr(intent.source, name) for name in batch.COMMON_FIELDS}
    files.require(batch.prepare(dict(values, txids=intent.txids)) == intent, 'invalid_batch_display_intent')
    pin = batch.single.Checkpoint.parse(intent.source.checkpoint)
    fixed = dict(format='zevune-ledger-transaction-batch-1', checkpoint=pin.encoded,
                 checkpoint_height=pin.height, checkpoint_app_hash=pin.app_hash,
                 genesis_sha256=intent.source.genesis_sha256, native_backend_sha256=intent.source.backend_sha256,
                 query_count=len(intent.txids), batch_complete=True, ledger_replayed=True, native_replay_count=1,
                 history_scan_count=len(intent.txids), historical_search_complete=True,
                 scanned_records_per_query=pin.height, ledger_bytes=pin.length, source_files_unchanged=True,
                 current_chain_height=None, broadcast_status='unknown', settlement_status='unknown',
                 wallet_authenticated=False, recipient_or_amount_verified=False, finality_verified=False,
                 retry_authorized=False, portable_proof_generated=False, real_funds_allowed=False)
    variable = {'included_count', 'absent_count', 'results', 'scanned_transactions_per_query'}
    files.require(type(result) is dict and set(result) == set(fixed) | variable, 'invalid_batch_display_fields')
    files.require(all(type(result[key]) is type(value) and result[key] == value for key, value in fixed.items()),
                  'batch_display_scope_or_pin_mismatch')
    for name in ('included_count', 'absent_count'):
        files.require(type(result[name]) is int and 0 <= result[name] <= len(intent.txids), 'invalid_batch_counts')
    files.require(result['included_count'] + result['absent_count'] == len(intent.txids), 'incomplete_batch_counts')
    rows = result['results']
    files.require(type(rows) is list and len(rows) == len(intent.txids), 'incomplete_batch_rows')
    total = result['scanned_transactions_per_query']
    files.require(type(total) is int and 0 <= total <= pin.height * batch.single.MAX_TRANSACTIONS,
                  'invalid_batch_scan_count')
    row_fields = {'txid', 'historical_inclusion_verified', 'state', 'occurrence', 'subsequent_record_count'}
    # Reuse the exact single-query presentation validator for each occurrence.
    # This is metadata validation, not a second query, replay or proof algorithm.
    common = {key: result[key] for key in (
        'checkpoint', 'checkpoint_height', 'checkpoint_app_hash', 'genesis_sha256', 'native_backend_sha256',
        'ledger_bytes', 'ledger_replayed', 'historical_search_complete', 'current_chain_height', 'broadcast_status',
        'settlement_status', 'wallet_authenticated', 'recipient_or_amount_verified', 'finality_verified',
        'retry_authorized', 'portable_proof_generated', 'source_files_unchanged', 'real_funds_allowed')}
    for txid, row in zip(intent.txids, rows):
        files.require(type(row) is dict and set(row) == row_fields, 'invalid_batch_row_fields')
        single_result = dict(common, **row, format='zevune-ledger-transaction-lookup-1',
                             scanned_records=pin.height, scanned_transactions=total)
        single_ui.present(single_result, replace(intent.source, txid=txid))
    files.require(sum(row['historical_inclusion_verified'] for row in rows) == result['included_count'],
                  'batch_counts_disagree_with_rows')
    text = batch.render(result) + '\n\n这是一次历史观察，不会后台刷新文件或链状态。复制清单不是付款凭证。'
    files.require(len(text.encode('utf-8')) <= batch.MAX_OUTPUT_BYTES, 'bounded_batch_display_required')
    return BatchDisplay(text, None, intent.txids)


def _execute(channel, released, completed, request):
    intent = result = None
    outcome = lifecycle.Completion(None)
    try:
        released.wait()
        intent, request[0] = request[0], None
        if intent is not None:
            result = batch.lookup_batch(intent)  # Actual original batch and native path only.
            outcome = lifecycle.Completion(present(result, intent))
    except BaseException:
        pass  # Fixed failure only, never exception objects, traces or native output.
    finally:
        intent = result = None
        request[0] = None
        try:
            channel.put_nowait(outcome)
        except BaseException:
            pass
        finally:
            completed.set()


class BatchJob(lifecycle.LedgerJob):
    """Inherit admission, interrupted-start ownership and actual-exit polling."""
    def __init__(self, intent: batch.Intent):
        files.require(type(intent) is batch.Intent, 'invalid_batch_job')
        self.channel = queue.Queue(maxsize=1)
        self.released, self.completed = threading.Event(), threading.Event()
        self.request = [intent]
        self.start_attempted = self.consumed = False
        self.thread = threading.Thread(target=_execute,
                                       args=(self.channel, self.released, self.completed, self.request),
                                       name='zevune-batch-historical-lookup', daemon=False)


class Workbench(single_ui.Workbench):
    """Reuse the existing layout and lifecycle; replace only the batch boundary."""
    def __init__(self, root):
        super().__init__(root)
        root.title('Zevune｜批量历史交易核查桌面 · NO-FUNDS')
        root.geometry('1100x950')
        old = self.entries.pop('txid')
        form, position = old.master, old.grid_info()
        self.controls.remove(old)
        old.destroy()
        variable = self.values.pop('txid')
        for mode, name in variable.trace_info():
            variable.trace_remove(mode, name)
        self.txids = self.tk.Text(form, height=4, wrap='none', exportselection=False, undo=False)
        self.txids.grid(row=position['row'], column=position['column'], sticky='ew', pady=3)
        scroll = self.ttk.Scrollbar(form, command=self.txids.yview)
        scroll.grid(row=position['row'], column=2, sticky='ns', padx=(8, 0))
        self.txids.configure(yscrollcommand=scroll.set)
        for label in form.grid_slaves(row=position['row'], column=0):
            label.configure(text='交易ID清单（每行一个，最多32行）')
        self.controls.append(self.txids)
        self._observed_text = ''
        self.txids.edit_modified(False)
        self.txids.bind('<<Modified>>', self._text_changed)
        body = form.master
        for notice in body.grid_slaves(row=0):
            notice.configure(text=NOTICE)
        self.details.master.configure(text='2  整批输入确认 / 完整批次结果')
        self.confirm_button.configure(text='确认仅批量核查历史')
        self.copy_button.configure(text='复制本批查询ID（非付款凭证）')
        self.status.set('逐行填写1—32个互异交易ID及独立依据；先核对，再明确确认。')

    def _review_description(self, intent):
        return review_text(intent)

    def _new_job(self, intent):
        return BatchJob(intent)

    def _valid_display(self, result):
        return type(result) is BatchDisplay

    def _sync_text(self):
        """Synchronize even before a queued Modified event can run.

        Bound materialization before get(); this does not promise that Tk can
        store arbitrary pasted text at no memory cost. Oversized input is refused.
        """
        dirty = bool(self.txids.edit_modified())
        if dirty:
            self.txids.edit_modified(False)
        bounded = self.txids.compare('end-1c', '<=', f'1.0+{MAX_TEXT_CHARS}c')
        text = self.txids.get('1.0', 'end-1c') if bounded else None
        if dirty or text != self._observed_text:
            self._observed_text = text
            self.changed()
        return text

    def _text_changed(self, *_):
        if self.phase != 'closed':
            self._sync_text()

    def review(self):
        if self.phase != 'idle':
            return
        try:
            text = self._sync_text()
            self.discard()
            intent = prepare({key: value.get() for key, value in self.values.items()}, text)
            self.active_revision = self.revision
            self.intent, self.phase = intent, 'review'
            self.enable(False)
            self.set_details(self._review_description(intent))
            self.status.set('请核对全部ID及独立依据。默认取消；确认只启动一次完整批次。')
            self.confirm_button.configure(state='normal')
            self.cancel_button.configure(state='normal')
            self.cancel_button.focus_set()
        except BaseException:
            self.intent, self.phase = None, 'idle'
            self.discard()
            self.enable(True)
            self.status.set(FAILURE)

    def confirm(self):
        if self.phase != 'review':
            return
        try:
            self._sync_text()
        except BaseException:
            self.callback_error()
            return
        if self.phase != 'review' or self.intent is None or self.active_revision != self.revision:
            return
        self.phase = 'running'
        try:
            self.enable(False)
            self.discard()
            self.job = self._new_job(self.intent)
            self.job.start()
            self.status.set('正在核验完整批次；不会显示部分结果，关闭将等待原任务结束。')
        except BaseException:
            self.revision += 1
            if self.job is not None:
                self.job.withdraw_start()
                if not self.job.start_attempted:
                    self.job = None
            self.status.set(lifecycle.START_FAILURE if self.job is not None else FAILURE)
        finally:
            self.intent = None
            if self.job is not None:
                self.schedule_poll()
            else:
                self.phase = 'idle'
                self.enable(True)

    def poll(self):
        if self.job is None:
            self.cancel_poll()
            return
        self._sync_text()
        outcome = self.job.poll()
        if outcome is None:
            self.schedule_poll()
            return
        self.cancel_poll()
        self.job = None
        self.discard()
        if self.phase == 'closing':
            self.root.destroy()
            self.phase = 'closed'
            return
        self.phase = 'idle'
        self.enable(True)
        if self.active_revision != self.revision or not self._valid_display(outcome.result):
            self.status.set(FAILURE)
            return
        self.set_details(outcome.result.text)
        self.status.set('完整批次查询完成；请逐项区分历史纳入与缺席，均不是结算或重试许可。')
        self.last = outcome.result
        self.copy_button.configure(state='normal')

    def copy(self):
        if self.phase != 'idle':
            return
        self._sync_text()
        if not self._valid_display(self.last) or self.active_revision != self.revision:
            return
        self.root.clipboard_clear()
        self.root.clipboard_append('\n'.join(self.last.txids))

    def clear(self):
        if self.phase != 'idle':
            return
        super().clear()
        self.txids.delete('1.0', 'end')
        self._sync_text()

    def callback_error(self, *_):
        super().callback_error()
        self.status.set(FAILURE)


def main(argv=None):
    parser = batch.Parser(description=__doc__)
    parser.add_argument('--no-real-funds', required=True, action='store_true')
    parser.parse_args(argv)
    try:
        import tkinter as tk
        root = tk.Tk()
        Workbench(root)
        root.mainloop()
        return 0
    except Exception:
        print('Batch desktop could not finish. Preserve inputs; no payment retry is authorized.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
