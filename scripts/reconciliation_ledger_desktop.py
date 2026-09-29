#!/usr/bin/env python3
"""NO-FUNDS desktop for the original replay-backed reconciliation check.

An explicit frozen-input review admits one non-daemon worker. Only the main
thread touches Tk. Closing waits for actual completion, not simulated cancel.
No password, signing, broadcast, restore, automatic retry or persistent settings.
"""
from __future__ import annotations

import sys
if __name__ == '__main__':
    sys.dont_write_bytecode = True

from dataclasses import dataclass
import queue
import threading

import reconciliation_ledger_check as checker

NOTICE = 'NO-FUNDS｜仅重放并核对指定历史账本；不是付款确认，不签名、不广播、不重试。'
FAILURE = '复核未完成。保留原报告、钱包和账本；不要重签、清除预留或重试支付。'
OBSERVATION_FAILURE = '完成状态观察中断，原任务仍被持有。点击关闭继续收尾；持续失败时请结束本应用进程。'
START_FAILURE = '线程启动未确认，已撤回未准入请求。等待收尾；若始终未启动，请结束本应用进程。'
LABELS = ('对账结果目录', '独立报告 SHA256', '独立账本检查点', '独立创世文件 SHA256（签名域）',
          '停止写入的活动账本目录', '批准的原生恢复程序', '独立程序 SHA256')


def review_text(intent: checker.Intent) -> str:
    values = (intent.evidence.directory, intent.evidence.report_sha256, intent.evidence.checkpoint,
              intent.evidence.genesis_sha256, intent.journal, intent.backend, intent.backend_sha256)
    return '\n\n'.join(f'{label}\n{value}' for label, value in zip(LABELS, values)) + (
        '\n\n仅执行原 verify-active；单次检查沿用原300秒预算，系统IO/收尾可能更久。\n'
        '请先停止其他写入。核验通过也不证明交易已入账；取消不会启动原生程序。')


@dataclass(frozen=True)
class DisplayResult:
    text: str
    txid: str | None


def present(result: dict, intent: checker.Intent) -> DisplayResult:
    """A display boundary, never a substitute for native verification."""
    pin = checker.view.Checkpoint.parse(intent.evidence.checkpoint)
    fixed = dict(format='zevune-reconciliation-ledger-check-1',
                 checkpoint_height=pin.height, ledger_bytes=pin.length, ledger_segments=pin.segments,
                 checkpoint_genesis_commitment=pin.genesis,
                 report_sha256=intent.evidence.report_sha256, checkpoint=intent.evidence.checkpoint,
                 genesis_sha256=intent.evidence.genesis_sha256, native_backend_sha256=intent.backend_sha256,
                 native_operation='verify-active', file_integrity_verified=True, ledger_replayed=True,
                 checkpoint_domain_relation_verified=True, source_files_unchanged=True, read_only=True,
                 wallet_authenticated=False, transaction_authorization_verified=False,
                 pending_transaction_inclusion_verified=False, genesis_manifest_validated=False,
                 original_recovery_success_verified=False, original_source_presence_verified=False,
                 finality_verified=False, retry_authorized=False, real_funds_allowed=False,
                 current_chain_height=None, broadcast_status='unknown', settlement_status='unknown')
    checker.files.require(type(result) is dict and all(key in result and type(result[key]) is type(value)
                          and result[key] == value for key, value in fixed.items()), 'unexpected_desktop_scope')
    txid = result.get('txid')
    checker.files.require((txid is None and result.get('pending_file_present') is False) or
                          (type(txid) is str and checker.files.HEX.fullmatch(txid) is not None
                           and result.get('pending_file_present') is True), 'unexpected_desktop_txid')
    text = checker.render(result)
    checker.files.require(type(text) is str and 0 < len(text) <= 8192, 'bounded_desktop_result_required')
    return DisplayResult(text, txid)


@dataclass(frozen=True)
class Completion:
    result: DisplayResult | None


def _execute(channel, released, completed, request):
    intent = result = None
    outcome = Completion(None)
    try:
        released.wait()
        intent, request[0] = request[0], None
        if intent is not None:
            result = checker.check(intent)  # Always the unchanged real checker.
            outcome = Completion(present(result, intent))
    except BaseException:
        pass  # Fixed failure, no exception/traceback/paths sent to Tk or logs.
    finally:
        intent = result = None
        request[0] = None
        try:
            channel.put_nowait(outcome)
        except BaseException:
            pass  # Completion without queue data is a failure, not lost ownership.
        finally:
            completed.set()


class LedgerJob:
    def __init__(self, intent: checker.Intent):
        checker.files.require(type(intent) is checker.Intent, 'invalid_desktop_job')
        self.channel = queue.Queue(maxsize=1)
        self.released, self.completed = threading.Event(), threading.Event()
        self.request = [intent]
        self.start_attempted = self.consumed = False
        self.thread = threading.Thread(target=_execute,
                                       args=(self.channel, self.released, self.completed, self.request),
                                       name='zevune-ledger-reconciliation', daemon=False)

    def withdraw_start(self):
        self.request[0] = None
        self.released.set()

    def start(self):
        checker.files.require(not self.start_attempted, 'desktop_job_already_started')
        self.start_attempted = True
        try:
            self.thread.start()
            self.released.set()
        except BaseException:
            self.withdraw_start()
            raise

    def poll(self):
        # ident=None is not proof that OS-thread creation failed.
        if not self.completed.is_set() or self.thread.is_alive() or self.consumed:
            return None
        if self.thread.ident is not None:
            self.thread.join(timeout=0)
        self.consumed = True
        try:
            outcome = self.channel.get_nowait()
            return outcome if type(outcome) is Completion else Completion(None)
        except queue.Empty:
            return Completion(None)


class Workbench:
    def __init__(self, root):
        import tkinter as tk
        from tkinter import ttk, filedialog
        self.root, self.tk, self.ttk, self.filedialog = root, tk, ttk, filedialog
        self.phase = 'idle'
        self.job = self.intent = self.last = None
        self.poll_ticket = self.poll_token = None
        self.revision = self.active_revision = self.callback_errors = 0
        self.values = {key: tk.StringVar(root) for key in checker.FIELDS}
        self.status = tk.StringVar(root, '填写独立信任输入。先核对，再明确确认；不会读取或猜测可信摘要。')
        self.entries, self.controls = {}, []
        root.title('Zevune｜账本绑定复核桌面 · NO-FUNDS')
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
        for row, (key, label) in enumerate(zip(checker.FIELDS, LABELS)):
            ttk.Label(form, text=label).grid(row=row, column=0, sticky='w', padx=(0, 10), pady=3)
            entry = ttk.Entry(form, textvariable=self.values[key], exportselection=False)
            entry.grid(row=row, column=1, sticky='ew', pady=3)
            self.entries[key] = entry
            self.controls.append(entry)
            if key in ('directory', 'journal', 'backend'):
                button = ttk.Button(form, text='选择…', command=lambda name=key: self.choose(name))
                button.grid(row=row, column=2, padx=(8, 0))
                self.controls.append(button)
        self.review_button = ttk.Button(form, text='核对输入…', command=self.review)
        self.review_button.grid(row=7, column=1, sticky='e', pady=(8, 0))
        self.controls.append(self.review_button)
        ttk.Label(body, textvariable=self.status, wraplength=1030).grid(row=2, sticky='w', pady=10)
        output = ttk.LabelFrame(body, text='2  冻结输入确认 / 本次历史复核结果', padding=8)
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
        self.confirm_button = ttk.Button(footer, text='确认仅执行账本复核', command=self.confirm, state='disabled')
        self.confirm_button.pack(side='left', padx=8)
        self.copy_button = ttk.Button(footer, text='复制本次交易ID', command=self.copy, state='disabled')
        self.copy_button.pack(side='right')
        self.clear_button = ttk.Button(footer, text='清除输入', command=self.clear)
        self.clear_button.pack(side='right', padx=8)
        self.controls.append(self.clear_button)
        ttk.Label(body, text='不保存密码、路径或报告。关闭会等待原任务结束；不是强制取消原生进程。',
                  wraplength=1030).grid(row=5, sticky='w', pady=(10, 0))
        root.bind('<Escape>', lambda _: self.cancel_review())
        for value in self.values.values():
            value.trace_add('write', self.changed)

    @property
    def busy(self):
        return self.phase in ('review', 'running', 'closing')

    def set_details(self, text):
        self.details.configure(state='normal')
        self.details.delete('1.0', 'end')
        self.details.insert('1.0', text)
        self.details.configure(state='disabled')

    def discard(self):
        self.last = None
        self.copy_button.configure(state='disabled')
        self.set_details('')

    def enable(self, enabled):
        for control in self.controls:
            control.configure(state='normal' if enabled else 'disabled')
        self.confirm_button.configure(state='disabled')
        self.cancel_button.configure(state='disabled')

    def changed(self, *_):
        self.revision += 1
        self.discard()
        if self.phase == 'review':
            self.intent = None
            self.phase = 'idle'
            self.enable(True)
        self.status.set('输入已改变，旧结果已撤销；运行中的任务不会自动重启。')

    def choose(self, name):
        if self.phase != 'idle':
            return
        if name == 'backend':
            value = self.filedialog.askopenfilename(parent=self.root, title='选择独立批准的原生恢复程序')
        else:
            value = self.filedialog.askdirectory(parent=self.root, mustexist=True, title='选择已停止写入的本地目录')
        if value:
            self.values[name].set(value)

    def review(self):
        if self.phase != 'idle':
            return
        self.discard()
        try:
            intent = checker.prepare({key: value.get() for key, value in self.values.items()})
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

    def cancel_review(self):
        if self.phase != 'review':
            return
        self.intent, self.phase = None, 'idle'
        self.discard()
        self.enable(True)
        self.status.set('已取消确认，没有启动原生复核。')

    def confirm(self):
        if self.phase != 'review' or self.intent is None or self.active_revision != self.revision:
            return
        self.phase = 'running'
        try:
            self.enable(False)
            self.discard()
            self.job = LedgerJob(self.intent)
            self.job.start()
            self.status.set('正在重放并复核历史账本；界面可响应，关闭请求将等待原任务收尾。')
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

    def cancel_poll(self):
        self.poll_ticket = None
        token, self.poll_token = self.poll_token, None
        if token is not None:
            try:
                self.root.after_cancel(token)
            except BaseException:
                pass  # Unknown registered callback is inert after ticket revocation.

    def schedule_poll(self):
        if self.job is None or self.poll_ticket is not None:
            return
        ticket, job = object(), self.job
        self.poll_ticket = ticket
        def ready():
            if self.poll_ticket is not ticket or self.job is not job:
                return
            self.poll_ticket = self.poll_token = None
            self.poll()
        try:
            token = self.root.after(50, ready)
            if self.poll_ticket is ticket:
                self.poll_token = token
        except BaseException:
            self.cancel_poll()
            self.revision += 1
            self.discard()
            self.status.set(OBSERVATION_FAILURE)

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
        self.status.set('历史账本重放与绑定复核完成；广播、结算和重试许可仍未确认。')
        self.last = outcome.result
        if self.last.txid is not None:
            self.copy_button.configure(state='normal')

    def copy(self):
        if self.phase != 'idle' or self.last is None or self.last.txid is None or self.active_revision != self.revision:
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(self.last.txid)

    def clear(self):
        if self.phase != 'idle':
            return
        for value in self.values.values():
            value.set('')
        self.discard()

    def callback_error(self, *_):
        self.callback_errors += 1
        self.revision += 1
        self.discard()
        if self.phase == 'review':
            self.intent, self.phase = None, 'idle'
            self.enable(True)
        self.status.set(FAILURE)

    def close(self):
        if self.phase == 'closed':
            return
        self.intent = None
        self.phase = 'closing'
        self.discard()
        self.enable(False)
        if self.job is None:
            self.cancel_poll()
            self.root.destroy()
            self.phase = 'closed'
        else:
            self.status.set('已请求关闭；等待本次原生复核真正结束，不接受新任务。')
            if self.poll_ticket is None:
                self.poll()  # Repeated Close resumes observation, never native execution.


def main(argv=None):
    parser = checker.view.Parser(description=__doc__)
    parser.add_argument('--no-real-funds', required=True, action='store_true')
    parser.parse_args(argv)
    try:
        import tkinter as tk
        root = tk.Tk()
        Workbench(root)
        root.mainloop()
        return 0
    except Exception:
        print('Ledger desktop could not finish. Preserve inputs; no payment retry is authorized.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
