#!/usr/bin/env python3
"""NO-FUNDS GUI for a fresh native-verified historical transaction lookup.

The existing ledger desktop owns thread admission and observation/close logic.
This module supplies a different immutable intent, strict display contract and
UI; it never mutates module globals or substitutes the original verifier.
"""
from __future__ import annotations

import sys
if __name__ == '__main__':
    sys.dont_write_bytecode = True

import queue
import threading

import ledger_transaction_lookup as lookup
import reconciliation_ledger_desktop as lifecycle

DisplayResult, Completion = lifecycle.DisplayResult, lifecycle.Completion
NOTICE = 'NO-FUNDS｜查询指定历史账本是否包含交易；不是当前结算证明，不付款、不重试。'
FAILURE = '历史查询未完成。没有产生找到或未找到结论；保留原文件，不要重签或重试付款。'
START_FAILURE = lifecycle.START_FAILURE
LABELS = ('停止写入的账本目录', '独立账本检查点', '独立创世文件 SHA256（签名域）',
          '独立交易 ID', '批准的原生恢复程序（单链接）', '独立程序 SHA256')


def review_text(intent: lookup.Intent) -> str:
    return '\n\n'.join(f'{label}\n{getattr(intent, key)}'
                         for label, key in zip(LABELS, lookup.FIELDS)) + (
        '\n\n每次先执行原 verify-active 完整重放，再查找完整交易字节。'
        '\n沿用单次300秒预算；系统IO及收尾可能更久。请先停止其他写入。'
        '\n未找到不授权重复付款；默认取消，只有明确确认才启动原生程序。')


def present(result: dict, intent: lookup.Intent) -> DisplayResult:
    """Validate public presentation metadata only; NOT native verification.

    All successful production calls reach here only through lookup.lookup().
    Reject unknown fields, type confusion and a result for a different request.
    """
    files = lookup.files
    files.require(type(intent) is lookup.Intent, 'invalid_lookup_display_intent')
    pin = lookup.Checkpoint.parse(intent.checkpoint)
    fixed = dict(format='zevune-ledger-transaction-lookup-1', txid=intent.txid,
                 checkpoint=pin.encoded, checkpoint_height=pin.height, checkpoint_app_hash=pin.app_hash,
                 genesis_sha256=intent.genesis_sha256, native_backend_sha256=intent.backend_sha256,
                 ledger_bytes=pin.length, scanned_records=pin.height, ledger_replayed=True,
                 historical_search_complete=True, current_chain_height=None, broadcast_status='unknown',
                 settlement_status='unknown', wallet_authenticated=False, recipient_or_amount_verified=False,
                 finality_verified=False, retry_authorized=False, portable_proof_generated=False,
                 source_files_unchanged=True, real_funds_allowed=False)
    variable = {'historical_inclusion_verified', 'state', 'occurrence',
                'subsequent_record_count', 'scanned_transactions'}
    files.require(type(result) is dict and set(result) == set(fixed) | variable,
                  'unexpected_lookup_display_fields')
    files.require(all(type(result[key]) is type(value) and result[key] == value
                      for key, value in fixed.items()), 'lookup_display_scope_or_pin_mismatch')
    total = result['scanned_transactions']
    included = result['historical_inclusion_verified']
    files.require(type(total) is int and 0 <= total <= pin.height * lookup.MAX_TRANSACTIONS
                  and type(included) is bool, 'invalid_lookup_display_counts')
    occurrence = result['occurrence']
    if included:
        files.require(result['state'] == 'included_in_verified_history' and total > 0
                      and type(occurrence) is dict and set(occurrence) == {
                          'height', 'record_block_id', 'transaction_index', 'segment',
                          'record_offset', 'transaction_bytes'}, 'invalid_lookup_occurrence')
        for key in ('height', 'transaction_index', 'record_offset', 'transaction_bytes'):
            files.require(type(occurrence[key]) is int, 'invalid_lookup_occurrence_integer')
        files.require(1 <= occurrence['height'] <= pin.height
                      and 0 <= occurrence['transaction_index'] < min(lookup.MAX_TRANSACTIONS, total)
                      and 0 <= occurrence['record_offset'] <= lookup.ledger.SEGMENT_BYTES - 150
                      and 0 < occurrence['transaction_bytes'] <= lookup.MAX_TRANSACTION_BYTES,
                      'invalid_lookup_occurrence_extent')
        block_id, segment = occurrence['record_block_id'], occurrence['segment']
        files.require(type(block_id) is str and files.HEX.fullmatch(block_id) is not None,
                      'invalid_lookup_record_id')
        files.require(type(segment) is str and len(segment) == 16 and segment.endswith('.journal')
                      and segment[:8].isascii() and segment[:8].isdigit()
                      and int(segment[:8]) < pin.segments, 'invalid_lookup_occurrence_segment')
        files.require(type(result['subsequent_record_count']) is int
                      and result['subsequent_record_count'] == pin.height - occurrence['height'],
                      'invalid_lookup_subsequent_count')
    else:
        files.require(result['state'] == 'absent_from_verified_history' and occurrence is None
                      and result['subsequent_record_count'] is None, 'invalid_lookup_absence')
    text = lookup.render(result) + '\n这是最近一次核验的历史观察，不会后台监控文件或链状态。'
    files.require(type(text) is str and 0 < len(text) <= 8192, 'bounded_lookup_display_required')
    return DisplayResult(text, intent.txid)


def _execute(channel, released, completed, request):
    intent = result = None
    outcome = Completion(None)
    try:
        released.wait()
        intent, request[0] = request[0], None
        if intent is not None:
            result = lookup.lookup(intent)  # Real native replay is still mandatory.
            outcome = Completion(present(result, intent))
    except BaseException:
        pass  # Send no exception objects, native output or tracebacks to the UI.
    finally:
        intent = result = None
        request[0] = None
        try:
            channel.put_nowait(outcome)
        except BaseException:
            pass
        finally:
            completed.set()


class LookupJob(lifecycle.LedgerJob):
    """Reuse admission, interrupted-start ownership and actual-exit polling."""
    def __init__(self, intent: lookup.Intent):
        lookup.files.require(type(intent) is lookup.Intent, 'invalid_lookup_job')
        self.channel = queue.Queue(maxsize=1)
        self.released, self.completed = threading.Event(), threading.Event()
        self.request = [intent]
        self.start_attempted = self.consumed = False
        self.thread = threading.Thread(target=_execute,
                                       args=(self.channel, self.released, self.completed, self.request),
                                       name='zevune-historical-transaction-lookup', daemon=False)


class Workbench(lifecycle.Workbench):
    """Reuse the existing lifecycle, not its checker or its result semantics.

    Inherited methods manage edit revision, timers, close, clipboard and clear.
    Their shared regression cases are exercised on this actual new Workbench.
    """
    def __init__(self, root):
        import tkinter as tk
        from tkinter import ttk, filedialog
        self.root, self.tk, self.ttk, self.filedialog = root, tk, ttk, filedialog
        self.phase = 'idle'
        self.job = self.intent = self.last = None
        self.poll_ticket = self.poll_token = None
        self.revision = self.active_revision = self.callback_errors = 0
        self.values = {key: tk.StringVar(root) for key in lookup.FIELDS}
        self.status = tk.StringVar(root, '填写独立信任输入。先核对，再明确确认；不会读取或猜测可信摘要。')
        self.entries, self.controls = {}, []
        root.title('Zevune｜历史交易纳入查询桌面 · NO-FUNDS')
        root.geometry('1100x880')
        root.minsize(860, 680)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(0, weight=1)
        root.report_callback_exception = self.callback_error
        root.protocol('WM_DELETE_WINDOW', self.close)
        body = ttk.Frame(root, padding=16)
        body.grid(sticky='nsew')
        body.columnconfigure(0, weight=1)
        body.rowconfigure(3, weight=1)
        ttk.Label(body, text=NOTICE, wraplength=1030).grid(row=0, sticky='w', pady=(0, 10))
        form = ttk.LabelFrame(body, text='1  输入与独立信任依据', padding=10)
        form.grid(row=1, sticky='ew')
        form.columnconfigure(1, weight=1)
        for row, (key, label) in enumerate(zip(lookup.FIELDS, LABELS)):
            ttk.Label(form, text=label).grid(row=row, column=0, sticky='w', padx=(0, 10), pady=3)
            entry = ttk.Entry(form, textvariable=self.values[key], exportselection=False)
            entry.grid(row=row, column=1, sticky='ew', pady=3)
            self.entries[key] = entry
            self.controls.append(entry)
            if key in ('journal', 'backend'):
                button = ttk.Button(form, text='选择…', command=lambda name=key: self.choose(name))
                button.grid(row=row, column=2, padx=(8, 0))
                self.controls.append(button)
        self.review_button = ttk.Button(form, text='核对输入…', command=self.review)
        self.review_button.grid(row=len(lookup.FIELDS), column=1, sticky='e', pady=(8, 0))
        self.controls.append(self.review_button)
        ttk.Label(body, textvariable=self.status, wraplength=1030).grid(row=2, sticky='w', pady=10)
        output = ttk.LabelFrame(body, text='2  冻结输入确认 / 本次历史查询结果', padding=8)
        output.grid(row=3, sticky='nsew')
        output.columnconfigure(0, weight=1)
        output.rowconfigure(0, weight=1)
        self.details = tk.Text(output, wrap='word', height=15, state='disabled', exportselection=False)
        self.details.grid(row=0, column=0, sticky='nsew')
        scroll = ttk.Scrollbar(output, command=self.details.yview)
        scroll.grid(row=0, column=1, sticky='ns')
        self.details.configure(yscrollcommand=scroll.set)
        footer = ttk.Frame(body)
        footer.grid(row=4, sticky='ew', pady=(10, 0))
        self.cancel_button = ttk.Button(footer, text='取消确认', command=self.cancel_review, state='disabled')
        self.cancel_button.pack(side='left')
        self.confirm_button = ttk.Button(footer, text='确认仅查询历史交易', command=self.confirm, state='disabled')
        self.confirm_button.pack(side='left', padx=8)
        self.copy_button = ttk.Button(footer, text='复制查询交易ID', command=self.copy, state='disabled')
        self.copy_button.pack(side='right')
        self.clear_button = ttk.Button(footer, text='清除输入', command=self.clear)
        self.clear_button.pack(side='right', padx=8)
        self.controls.append(self.clear_button)
        ttk.Label(body, text='不保存密码、路径或报告。关闭会等待原任务结束；不是强制取消原生进程。',
                  wraplength=1030).grid(row=5, sticky='w', pady=(10, 0))
        root.bind('<Escape>', lambda _: self.cancel_review())
        for value in self.values.values():
            value.trace_add('write', self.changed)


    def review(self):
        if self.phase != 'idle':
            return
        self.discard()
        try:
            intent = lookup.prepare({key: value.get() for key, value in self.values.items()})
            self.active_revision = self.revision
            self.intent, self.phase = intent, 'review'
            self.enable(False)
            self.set_details(review_text(intent))
            self.status.set('请逐项核对冻结输入。默认取消；必须明确点击确认才会执行原生程序。')
            self.confirm_button.configure(state='normal')
            self.cancel_button.configure(state='normal')
            self.cancel_button.focus_set()
        except BaseException:
            self.intent, self.phase = None, 'idle'
            self.discard()
            self.enable(True)
            self.status.set(FAILURE)


    def confirm(self):
        if self.phase != 'review' or self.intent is None or self.active_revision != self.revision:
            return
        self.phase = 'running'
        try:
            self.enable(False)
            self.discard()
            self.job = LookupJob(self.intent)
            self.job.start()
            self.status.set('正在验证并查询历史账本；界面可响应，关闭请求将等待原任务收尾。')
        except BaseException:
            self.revision += 1
            if self.job is not None:
                self.job.withdraw_start()
                if not self.job.start_attempted:
                    self.job = None
            self.status.set(START_FAILURE if self.job is not None else FAILURE)
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
        if self.active_revision != self.revision or outcome.result is None:
            self.status.set(FAILURE)
            return
        self.set_details(outcome.result.text)
        self.status.set('历史查询完成；请区分找到与未找到，两者都不是最终结算或重试许可。')
        self.last = outcome.result
        if self.last.txid is not None:
            self.copy_button.configure(state='normal')


    def callback_error(self, *_):
        self.callback_errors += 1
        self.revision += 1
        self.discard()
        if self.phase == 'review':
            self.intent, self.phase = None, 'idle'
            self.enable(True)
        self.status.set(FAILURE)



def main(argv=None):
    parser = lookup.view.Parser(description=__doc__)
    parser.add_argument('--no-real-funds', required=True, action='store_true')
    parser.parse_args(argv)
    try:
        import tkinter as tk
        root = tk.Tk()
        Workbench(root)
        root.mainloop()
        return 0
    except Exception:
        print('Historical lookup desktop could not finish. Preserve inputs; do not retry payment.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
