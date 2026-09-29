#!/usr/bin/env python3
"""NO-FUNDS evidence receiver: frozen review, explicit create-only restore/check.

The original worker admission and actual-exit lifecycle are retained. Review
performs bounded synchronous IO; writes/checks run off Tk after confirmation.
"""
from __future__ import annotations

import sys
if __name__ == '__main__':
    sys.dont_write_bytecode = True

import queue
import threading

import ledger_query_bundle_receive as receive
import reconciliation_ledger_desktop as lifecycle

FAILURE = '操作未完成或结果已失效。保留包和目标目录（可能含部分文件）；不要自动续装、删除或重试。'
WAITING = '等待已启动操作实际结束；不接受新操作，不强行取消写入。'


def _execute(channel, released, completed, request):
    outcome = lifecycle.Completion(None)
    approval = None
    try:
        released.wait()
        approval, request[0] = request[0], None
        if approval is not None:
            outcome = lifecycle.Completion(receive.execute(approval))
    except BaseException:
        pass  # Queue only a fixed failure, never exception text or file contents.
    finally:
        approval = None
        request[0] = None
        try:
            channel.put_nowait(outcome)
        except BaseException:
            pass
        finally:
            completed.set()


class ReceiveJob(lifecycle.LedgerJob):
    def __init__(self, approval):
        receive.validate(approval)
        self.channel = queue.Queue(maxsize=1)
        self.released, self.completed = threading.Event(), threading.Event()
        self.request = [approval]
        self.start_attempted = self.consumed = False
        self.thread = threading.Thread(target=_execute, args=(self.channel, self.released, self.completed, self.request),
                                       name='zevune-evidence-receive', daemon=False)


class Workbench(lifecycle.Workbench):
    """Keep original poll-ticket/closing ownership; specialize action/result text."""
    def __init__(self, root):
        import tkinter as tk
        from tkinter import ttk, filedialog
        self.root, self.tk, self.ttk, self.filedialog = root, tk, ttk, filedialog
        self.phase = 'idle'
        self.job = self.intent = self.last = None
        self.poll_ticket = self.poll_token = None
        self.revision = self.active_revision = self.callback_errors = 0
        self.values = {key: tk.StringVar(root) for key in receive.FIELDS}
        self._observed = tuple('' for _ in receive.FIELDS)
        self._result_form = None
        self.status = tk.StringVar(root, '选择操作，填写包路径、独立包摘要及目标目录。先核验清单，再明确确认。')
        self.controls, self.entries = [], {}
        root.title('Zevune｜证据包接收 · NO-FUNDS')
        root.geometry('1120x800')
        root.minsize(860, 620)
        root.columnconfigure(0, weight=1); root.rowconfigure(0, weight=1)
        root.report_callback_exception = self.callback_error
        root.protocol('WM_DELETE_WINDOW', self.close)
        body = ttk.Frame(root, padding=16); body.grid(sticky='nsew')
        body.columnconfigure(0, weight=1); body.rowconfigure(3, weight=1)
        ttk.Label(body, text='NO-FUNDS｜只还原证据文件或核验目录；不导入钱包、不执行任务。',
                  wraplength=1050).grid(row=0, sticky='w', pady=(0, 10))
        form = ttk.LabelFrame(body, text='1  本机输入与独立信任依据', padding=10); form.grid(row=1, sticky='ew')
        form.columnconfigure(1, weight=1)
        labels = ('操作：unpack 新目录 / verify-directory 只读', '证据包绝对路径', '独立包 SHA256', '目标目录绝对路径')
        for row, (key, label) in enumerate(zip(receive.FIELDS, labels)):
            ttk.Label(form, text=label).grid(row=row, column=0, sticky='w', padx=(0, 10), pady=4)
            widget = (ttk.Combobox(form, values=receive.OPERATIONS, state='readonly', exportselection=False,
                                   textvariable=self.values[key]) if key == 'operation' else
                      ttk.Entry(form, textvariable=self.values[key], exportselection=False))
            widget.grid(row=row, column=1, sticky='ew', pady=4)
            self.entries[key] = widget; self.controls.append(widget)
        choose = ttk.Button(form, text='选择包文件…', command=self.choose)
        choose.grid(row=1, column=2, padx=8); self.controls.append(choose)
        self.review_button = ttk.Button(form, text='核验包并核对完整清单', command=self.review)
        self.review_button.grid(row=4, column=1, sticky='e', pady=8); self.controls.append(self.review_button)
        ttk.Label(body, textvariable=self.status, wraplength=1050).grid(row=2, sticky='w', pady=10)
        output = ttk.Frame(body); output.grid(row=3, sticky='nsew')
        output.columnconfigure(0, weight=1); output.rowconfigure(0, weight=1)
        self.details = tk.Text(output, wrap='word', state='disabled', exportselection=False)
        self.details.grid(row=0, column=0, sticky='nsew')
        scroll = ttk.Scrollbar(output, command=self.details.yview); scroll.grid(row=0, column=1, sticky='ns')
        self.details.configure(yscrollcommand=scroll.set)
        footer = ttk.Frame(body); footer.grid(row=4, sticky='ew', pady=10)
        self.cancel_button = ttk.Button(footer, text='取消确认', command=self.cancel_review, state='disabled')
        self.cancel_button.pack(side='left')
        self.confirm_button = ttk.Button(footer, text='确认所选操作（非付款）', command=self.confirm, state='disabled')
        self.confirm_button.pack(side='left', padx=8)
        self.copy_button = ttk.Button(footer, text='复制已核验包摘要', command=self.copy, state='disabled')
        self.copy_button.pack(side='right')
        clear = ttk.Button(footer, text='清除输入', command=self.clear); clear.pack(side='right', padx=8)
        self.controls.append(clear)
        ttk.Label(body, text='还原目标必须不存在（包括空目录）。失败保留残留；关闭等待结束。核验包时磁盘阻塞可能暂停界面。',
                  wraplength=1050).grid(row=5, sticky='w')
        root.bind('<Escape>', lambda _: self.cancel_review())
        for value in self.values.values(): value.trace_add('write', self.changed)

    def sync(self):
        raw = tuple(self.values[key].get() for key in receive.FIELDS)
        if raw != self._observed:
            self._observed = raw
            self.changed()
        return raw

    def enable(self, enabled):
        super().enable(enabled)
        if enabled: self.entries['operation'].configure(state='readonly')

    def changed(self, *_):
        super().changed()
        self.status.set('输入变化，旧确认与结果已撤销；已启动的文件操作仍会继续，失败残留须保留。')

    def choose(self):
        if self.phase != 'idle': return
        path = self.filedialog.askopenfilename(parent=self.root, title='选择证据包（不读取、不计算摘要）')
        if path and self.phase == 'idle': self.values['bundle'].set(path)

    def review(self):
        if self.phase != 'idle': return
        try:
            raw = self.sync(); self.discard()
            form = receive.prepare(dict(zip(receive.FIELDS, raw)))
            self.active_revision = self.revision
            self.intent = None; self.phase = 'review'; self.enable(False)
            approval = receive.approve(form)
            text = receive.review_text(approval)
            if self.sync() != raw or self.phase != 'review' or self.revision != self.active_revision: return
            self.set_details(text)
            self.status.set('完整包已核验，尚未写入。核对操作、清单及目录；默认取消，回车不执行。')
            if self.sync() != raw or self.phase != 'review' or self.revision != self.active_revision: return
            self.intent = approval; self._result_form = form
            self.confirm_button.configure(state='normal'); self.cancel_button.configure(state='normal')
            self.cancel_button.focus_set()
        except BaseException:
            self.intent = None; self.phase = 'idle'; self.discard(); self.enable(True); self.status.set(FAILURE)

    def cancel_review(self):
        if self.phase == 'review':
            super().cancel_review()
            self.status.set('已取消确认；没有开始还原或目录核验。')

    def confirm(self):
        if self.phase != 'review': return
        try:
            self.sync()
            if self.phase != 'review' or self.intent is None or self.active_revision != self.revision: return
            approval = self.intent
            self.enable(False); self.discard(); self.sync()
            if self.phase != 'review' or self.intent is not approval or self.active_revision != self.revision: return
            self.phase = 'running'
            self.job = ReceiveJob(approval)
            self.job.start()
            self.status.set(WAITING)
        except BaseException:
            self.revision += 1
            if self.job is not None:
                self.job.withdraw_start()
                if not self.job.start_attempted: self.job = None
            self.status.set(FAILURE if self.job is None else WAITING + ' 启动状态未确认；持续失败时结束本应用。')
        finally:
            self.intent = None
            if self.job is not None: self.schedule_poll()
            elif self.phase != 'closed': self.phase = 'idle'; self.enable(True)

    def poll(self):
        if self.job is None: self.cancel_poll(); return
        self.sync()
        outcome = self.job.poll()
        if outcome is None: self.schedule_poll(); return
        self.cancel_poll(); self.job = None; self.discard()
        if self.phase == 'closing': self.root.destroy(); self.phase = 'closed'; return
        self.phase = 'idle'; self.enable(True)
        shown = outcome.result
        if (self.active_revision != self.revision or type(shown) is not receive.Display
                or shown.form != self._result_form): self.status.set(FAILURE); return
        self.set_details(shown.text)
        self.status.set('所选操作完成；这不是执行任务、原件存在或付款证明。')
        self.sync()
        if self.active_revision != self.revision: self.discard(); return
        self.copy_button.configure(state='normal'); self.last = shown

    def copy(self):
        if self.phase != 'idle': return
        try:
            raw = self.sync(); shown = self.last
            if type(shown) is not receive.Display or self.active_revision != self.revision: return
            if shown.form != receive.prepare(dict(zip(receive.FIELDS, raw))): self.discard(); return
            self.root.clipboard_clear(); self.root.clipboard_append(shown.form.bundle_sha256)
        except BaseException: self.callback_error()

    def clear(self):
        if self.phase != 'idle': return
        super().clear(); self.sync(); self._result_form = None

    def callback_error(self, *_):
        super().callback_error()
        self.status.set(FAILURE)

    def close(self):
        super().close()
        if self.phase == 'closing': self.status.set(WAITING)


def main(argv=None):
    parser = receive.bundle.Parser(description=__doc__)
    parser.add_argument('--no-real-funds', required=True, action='store_true')
    parser.parse_args(argv)
    try:
        import tkinter as tk
        root = tk.Tk(); Workbench(root); root.mainloop()
        return 0
    except Exception:
        print('Evidence receiver failed. Preserve bundle and partial output; no complete result.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
