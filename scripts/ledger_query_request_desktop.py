#!/usr/bin/env python3
"""NO-FUNDS task-file desktop: inspect, review, explicitly execute original query.

Only the small pinned request is read on review. Confirmation admits one worker;
its source identity is bound to the reviewed file, not just a later equal hash.
No task creation/editing, automatic execution, wallet operation or new lifecycle.
"""
from __future__ import annotations

import sys
if __name__ == '__main__':
    sys.dont_write_bytecode = True

from dataclasses import dataclass
from pathlib import Path
import queue
import threading

import ledger_query_request as task
import ledger_transaction_batch_once_desktop as once_ui

previous, lifecycle = once_ui.previous, once_ui.lifecycle
files = task.files
FIELDS = ('request', 'request_sha256', 'journal', 'backend')
LABELS = ('查询任务文件', '独立任务 SHA256', '停止写入的账本目录', '批准的原生恢复程序')
NOTICE = 'NO-FUNDS｜核验任务后明确确认才查询；文件不是脚本，历史结果不是付款凭证。'
FAILURE = '任务核验或执行未完成；没有有效批次结果。保留原文件，不要重签或重试付款。'


@dataclass(frozen=True)
class Form:
    request: Path
    request_sha256: str
    journal: Path
    backend: Path


def prepare(values: dict[str, str]) -> Form:
    """Validate every local field before touching the request file."""
    files.require(type(values) is dict and set(values) == set(FIELDS), 'incomplete_task_form')
    digest = task.digest(values['request_sha256'])
    paths = {}
    for key in ('request', 'journal', 'backend'):
        text = task.view.bounded(values[key], 'directory')
        paths[key] = task.absolute(Path(text))
    return Form(paths['request'], digest, paths['journal'], paths['backend'])


def validate_form(form: Form) -> None:
    files.require(type(form) is Form, 'invalid_task_form')
    values = {key: getattr(form, key) if key == 'request_sha256' else str(getattr(form, key)) for key in FIELDS}
    files.require(prepare(values) == form, 'invalid_task_form')


@dataclass(frozen=True)
class Approval:
    form: Form
    snapshot: task.Snapshot


def validate_approval(approval: Approval) -> None:
    """Pure checks only; job construction must not start IO or a native process."""
    files.require(type(approval) is Approval, 'invalid_task_approval')
    validate_form(approval.form)
    snap = approval.snapshot
    files.require(type(snap) is task.Snapshot and snap.path == approval.form.request
                  and type(snap.identity) is tuple and type(snap.parent_chain) is tuple,
                  'invalid_reviewed_snapshot')
    files.require(task.decode(snap.raw, approval.form.request_sha256) == snap.request,
                  'reviewed_request_mismatch')


def approve(form: Form) -> Approval:
    validate_form(form)
    approval = Approval(form, task.load(form.request, form.request_sha256))
    validate_approval(approval)
    return approval


def native_intent(approval: Approval):
    validate_approval(approval)
    form, request = approval.form, approval.snapshot.request
    return task.once.prepare(dict(journal=str(form.journal), backend=str(form.backend),
                                  checkpoint=request.checkpoint, genesis_sha256=request.genesis_sha256,
                                  backend_sha256=request.backend_sha256, txids=request.txids))


def review_text(approval: Approval) -> str:
    intent = native_intent(approval)
    return (f'已按独立摘要核验任务文件（尚未执行）\n{approval.form.request}\n'
            f'任务 SHA256：{approval.form.request_sha256}\n'
            '摘要不是签名；文件不提供本机路径或自动执行权限。\n\n' + once_ui.review_text(intent) +
            '\n\n确认绑定本次读到的任务文件身份；同字节替换也必须重新核对。'
            '\n原核心300秒预算不变；任务读取在其之外，文件系统阻塞不受硬实时保证。')


@dataclass(frozen=True)
class RequestDisplay(previous.BatchDisplay):
    request_sha256: str


def present(result: dict, approval: Approval) -> RequestDisplay:
    """Validate the outer task receipt and the entire original one-pass result."""
    intent = native_intent(approval)
    fixed = dict(operation='query_request_run', request_sha256=approval.form.request_sha256,
                 request_file_unchanged=True, signature_verified=False, real_funds_allowed=False)
    files.require(type(result) is dict and set(result) == set(fixed) | {'result'}, 'invalid_task_result_fields')
    files.require(all(type(result[key]) is type(value) and result[key] == value for key, value in fixed.items()),
                  'task_result_binding_mismatch')
    display = once_ui.present(result['result'], intent)
    text = (f'本次明确执行的任务 SHA256：{approval.form.request_sha256}\n'
            '这是执行结束时的历史观察；不会持续监控文件变化。\n\n' + display.text)
    files.require(len(text.encode('utf-8')) <= task.MAX_OUTPUT_BYTES, 'bounded_task_display_required')
    return RequestDisplay(text, None, display.txids, approval.form.request_sha256)


def execute(approval: Approval) -> RequestDisplay:
    validate_approval(approval)
    task.unchanged(approval.snapshot)  # Refuse a replaced reviewed file BEFORE any native execution.
    form = approval.form
    result = task.run_request(form.request, form.request_sha256, form.journal, form.backend)
    task.unchanged(approval.snapshot)  # Also bind the original review across the entire real query.
    return present(result, approval)


def _execute(channel, released, completed, request):
    approval = result = None
    outcome = lifecycle.Completion(None)
    try:
        released.wait()
        approval, request[0] = request[0], None
        if approval is not None:
            result = execute(approval)
            outcome = lifecycle.Completion(result)
    except BaseException:
        pass  # Fixed failure only; no exception, native payload or path in the queue.
    finally:
        approval = result = None
        request[0] = None
        try:
            channel.put_nowait(outcome)
        except BaseException:
            pass
        finally:
            completed.set()


class RequestJob(lifecycle.LedgerJob):
    """Original admission, interrupted-start ownership and actual-exit polling."""
    def __init__(self, approval: Approval):
        validate_approval(approval)
        self.channel = queue.Queue(maxsize=1)
        self.released, self.completed = threading.Event(), threading.Event()
        self.request = [approval]
        self.start_attempted = self.consumed = False
        self.thread = threading.Thread(target=_execute,
                                       args=(self.channel, self.released, self.completed, self.request),
                                       name='zevune-pinned-task-query', daemon=False)


class Workbench(previous.Workbench):
    """Reuse confirm/poll/copy and the original lifecycle, with a four-field form.

    The inherited action hook is named _sync_text; here it synchronizes actual
    StringVar values instead of a multiline editor. No shared globals change.
    """
    def __init__(self, root):
        import tkinter as tk
        from tkinter import ttk, filedialog
        self.root, self.tk, self.ttk, self.filedialog = root, tk, ttk, filedialog
        self.phase = 'idle'
        self.job = self.intent = self.last = None
        self.poll_ticket = self.poll_token = None
        self.revision = self.active_revision = self.callback_errors = 0
        self.values = {key: tk.StringVar(root) for key in FIELDS}
        self._observed_values = tuple('' for _ in FIELDS)
        self._display_binding = None
        self.status = tk.StringVar(root, '选择任务并输入独立摘要与本机路径。先核验并核对，再明确确认。')
        self.entries, self.controls = {}, []
        root.title('Zevune｜离线查询任务桌面 · NO-FUNDS')
        root.geometry('1100x820')
        root.minsize(850, 620)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(0, weight=1)
        root.report_callback_exception = self.callback_error
        root.protocol('WM_DELETE_WINDOW', self.close)
        body = ttk.Frame(root, padding=16)
        body.grid(sticky='nsew')
        body.columnconfigure(0, weight=1)
        body.rowconfigure(3, weight=1)
        ttk.Label(body, text=NOTICE, wraplength=1030).grid(row=0, sticky='w', pady=(0, 10))
        form = ttk.LabelFrame(body, text='1  任务文件 / 独立摘要 / 本机路径', padding=10)
        form.grid(row=1, sticky='ew')
        form.columnconfigure(1, weight=1)
        for row, (key, label) in enumerate(zip(FIELDS, LABELS)):
            ttk.Label(form, text=label).grid(row=row, column=0, sticky='w', padx=(0, 10), pady=3)
            entry = ttk.Entry(form, textvariable=self.values[key], exportselection=False)
            entry.grid(row=row, column=1, sticky='ew', pady=3)
            self.entries[key] = entry
            self.controls.append(entry)
            if key != 'request_sha256':
                button = ttk.Button(form, text='选择…', command=lambda name=key: self.choose(name))
                button.grid(row=row, column=2, padx=(8, 0))
                self.controls.append(button)
        self.review_button = ttk.Button(form, text='核验任务并核对…', command=self.review)
        self.review_button.grid(row=len(FIELDS), column=1, sticky='e', pady=(8, 0))
        self.controls.append(self.review_button)
        ttk.Label(body, textvariable=self.status, wraplength=1030).grid(row=2, sticky='w', pady=10)
        output = ttk.LabelFrame(body, text='2  完整任务确认 / 单次历史结果', padding=8)
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
        self.confirm_button = ttk.Button(footer, text='确认执行此任务（非付款）', command=self.confirm, state='disabled')
        self.confirm_button.pack(side='left', padx=8)
        self.copy_button = ttk.Button(footer, text='复制本次查询ID（非凭证）', command=self.copy, state='disabled')
        self.copy_button.pack(side='right')
        self.clear_button = ttk.Button(footer, text='清除输入', command=self.clear)
        self.clear_button.pack(side='right', padx=8)
        self.controls.append(self.clear_button)
        ttk.Label(body, text='核验只读最多8KiB任务，磁盘阻塞仍可能等待。确认后查询在线程中执行；关闭等待真实结束。',
                  wraplength=1030).grid(row=5, sticky='w', pady=(10, 0))
        root.bind('<Escape>', lambda _: self.cancel_review())
        for value in self.values.values():
            value.trace_add('write', self.changed)

    def _sync_text(self):
        observed = tuple(self.values[key].get() for key in FIELDS)
        if observed != self._observed_values:
            self._observed_values = observed
            self.changed()
        return observed

    def _new_job(self, approval):
        return RequestJob(approval)

    def _valid_display(self, result):
        return (type(result) is RequestDisplay
                and (result.request_sha256, result.txids) == self._display_binding)

    def review(self):
        if self.phase != 'idle':
            return
        self.discard()
        try:
            self._sync_text()
            form = prepare({key: value.get() for key, value in self.values.items()})
            self.active_revision = self.revision
            self.phase = 'review'  # No confirmation is possible while intent is still None.
            self.enable(False)
            self.intent = None
            approval = approve(form)  # Bounded request IO only; no native, ledger read or nested event loop.
            self._sync_text()
            if self.phase != 'review' or self.active_revision != self.revision:
                return
            self.intent = approval
            self._display_binding = (form.request_sha256, approval.snapshot.request.txids)
            self.set_details(review_text(approval))
            self.status.set('任务文件已核验，尚未执行。核对全部ID、独立依据和本机路径；默认取消。')
            self.confirm_button.configure(state='normal')
            self.cancel_button.configure(state='normal')
            self.cancel_button.focus_set()
        except BaseException:
            self.intent, self.phase = None, 'idle'
            self.discard()
            self.enable(True)
            self.status.set(FAILURE)

    def choose(self, name):
        if self.phase != 'idle':
            return
        if name == 'journal':
            value = self.filedialog.askdirectory(parent=self.root, mustexist=True, title='选择停止写入的本地账本')
        elif name in ('request', 'backend'):
            value = self.filedialog.askopenfilename(parent=self.root, title='选择任务文件' if name == 'request' else '选择批准程序')
        else:
            return
        if value:
            self.values[name].set(value)  # Selecting a file never loads or executes it.

    def clear(self):
        if self.phase != 'idle':
            return
        for value in self.values.values():
            value.set('')
        self._sync_text()
        self._display_binding = None
        self.discard()

    def callback_error(self, *_):
        super().callback_error()
        self.status.set(FAILURE)


def main(argv=None):
    parser = task.Parser(description=__doc__)
    parser.add_argument('--no-real-funds', required=True, action='store_true')
    parser.parse_args(argv)
    try:
        import tkinter as tk
        root = tk.Tk()
        Workbench(root)
        root.mainloop()
        return 0
    except Exception:
        print('Task desktop could not finish. Preserve inputs; no payment retry is authorized.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
