#!/usr/bin/env python3
"""NO-FUNDS offline task/report comparison desktop; never executes a query.

Bounded local-file IO is synchronous. No worker, timer or nested event pumping
is introduced; a blocked filesystem can block the UI. Results are observations,
not continuing file monitoring, signatures, approvals or payment evidence.
"""
from __future__ import annotations

import sys
if __name__ == '__main__':
    sys.dont_write_bytecode = True

from dataclasses import dataclass
from pathlib import Path

import ledger_query_evidence_compare as comparison

task = comparison.task
FIELDS = tuple(f'{side}_{field}' for side in ('before', 'after') for field in ('kind', 'path', 'sha256'))
NOTICE = 'NO-FUNDS｜只比较已固定的文件内容；不运行查询、后端或付款。'
FAILURE = '文件比较未完成；没有有效结果。保留两个输入，核对类型与独立摘要后重新比较。'


@dataclass(frozen=True)
class Intent:
    before: comparison.Source
    after: comparison.Source
    details: bool


def prepare(values: dict[str, str], details: bool = False) -> Intent:
    """All six fields and explicit disclosure choice are checked before any IO."""
    task.files.require(type(values) is dict and set(values) == set(FIELDS) and type(details) is bool,
                       'incomplete_evidence_form')
    sources = []
    for side in ('before', 'after'):
        text = task.view.bounded(values[f'{side}_path'], 'directory')
        source = comparison.Source(values[f'{side}_kind'], Path(text), values[f'{side}_sha256'])
        comparison.validate_source(source)
        sources.append(source)
    return Intent(*sources, details)


def validate(intent: Intent) -> None:
    task.files.require(type(intent) is Intent and type(intent.details) is bool, 'invalid_comparison_intent')
    comparison.validate_source(intent.before)
    comparison.validate_source(intent.after)


@dataclass(frozen=True)
class Display:
    intent: Intent
    text: str


def inspect(intent: Intent) -> Display:
    validate(intent)
    # Exactly the original C29 API: no new decoders, default-kind fallback,
    # inferred source availability, algorithm or report-import trust boundary.
    result = comparison.compare(intent.before, intent.after, details=intent.details)
    text = comparison.render(result)
    task.files.require(len(text.encode('utf-8')) <= comparison.MAX_OUTPUT_BYTES, 'bounded_comparison_display')
    return Display(intent, text)


class Workbench:
    def __init__(self, root):
        import tkinter as tk
        from tkinter import ttk, filedialog
        self.root, self.tk, self.ttk, self.filedialog = root, tk, ttk, filedialog
        self.busy = self.closed = False
        self.revision = 0
        self.active_revision = -1
        self.last = None
        self.values = {key: tk.StringVar(root) for key in FIELDS}
        self.disclosure = tk.BooleanVar(root, False)
        self._observed = self._raw()
        self.status = tk.StringVar(root, '分别选择 task（任务）或 report（审计报告），并填入各自独立摘要。')
        self.controls, self.entries = [], {}
        root.title('Zevune｜任务与报告变更比较 · NO-FUNDS')
        root.geometry('1120x780')
        root.minsize(850, 600)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(0, weight=1)
        root.protocol('WM_DELETE_WINDOW', self.close)
        root.report_callback_exception = self.callback_error
        body = ttk.Frame(root, padding=16)
        body.grid(sticky='nsew')
        body.columnconfigure(0, weight=1)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(4, weight=1)
        ttk.Label(body, text=NOTICE, wraplength=1050).grid(row=0, column=0, columnspan=2, sticky='w', pady=(0, 12))
        for column, (side, title) in enumerate((('before', '前项：比较起点（不证明时间先后）'),
                                                ('after', '后项：比较终点（不证明更加可信）'))):
            frame = ttk.LabelFrame(body, text=title, padding=10)
            frame.grid(row=1, column=column, sticky='nsew', padx=(0, 8) if column == 0 else (8, 0))
            frame.columnconfigure(0, weight=1)
            ttk.Label(frame, text='输入类型（必须明确选择）').grid(row=0, sticky='w')
            kind = ttk.Combobox(frame, textvariable=self.values[f'{side}_kind'], values=comparison.KINDS,
                                state='readonly', exportselection=False)
            kind.grid(row=1, sticky='ew', pady=(2, 8))
            self.controls.append((kind, 'readonly'))
            self.entries[f'{side}_kind'] = kind
            for row, field, label in ((2, 'path', '本机文件绝对路径'), (4, 'sha256', '此输入文件的独立 SHA256')):
                ttk.Label(frame, text=label).grid(row=row, sticky='w')
                entry = ttk.Entry(frame, textvariable=self.values[f'{side}_{field}'], exportselection=False)
                entry.grid(row=row + 1, sticky='ew', pady=(2, 8))
                self.controls.append((entry, 'normal'))
                self.entries[f'{side}_{field}'] = entry
            button = ttk.Button(frame, text='选择文件（不读取、不计算摘要）…', command=lambda s=side: self.choose(s))
            button.grid(row=6, sticky='w')
            self.controls.append((button, 'normal'))
        actions = ttk.Frame(body)
        actions.grid(row=2, column=0, columnspan=2, sticky='ew', pady=12)
        self.details_choice = ttk.Checkbutton(actions, text='明确显示完整公开 ID 和信任依据（可能关联交易）',
                                              variable=self.disclosure)
        self.details_choice.pack(side='left')
        self.compare_button = ttk.Button(actions, text='校验并比较（不执行任务）', command=self.begin)
        self.compare_button.pack(side='right')
        self.swap_button = ttk.Button(actions, text='交换前后', command=self.swap)
        self.swap_button.pack(side='right', padx=8)
        self.controls.extend(((self.details_choice, 'normal'), (self.compare_button, 'normal'), (self.swap_button, 'normal')))
        ttk.Label(body, textvariable=self.status, wraplength=1050).grid(row=3, column=0, columnspan=2, sticky='w', pady=(0, 8))
        output = ttk.Frame(body)
        output.grid(row=4, column=0, columnspan=2, sticky='nsew')
        output.columnconfigure(0, weight=1)
        output.rowconfigure(0, weight=1)
        self.output = tk.Text(output, wrap='word', state='disabled', exportselection=False, height=16)
        self.output.grid(row=0, column=0, sticky='nsew')
        scroll = ttk.Scrollbar(output, command=self.output.yview)
        scroll.grid(row=0, column=1, sticky='ns')
        self.output.configure(yscrollcommand=scroll.set)
        footer = ttk.Frame(body)
        footer.grid(row=5, column=0, columnspan=2, sticky='ew', pady=10)
        self.copy_button = ttk.Button(footer, text='复制当前显示（非凭证）', command=self.copy, state='disabled')
        self.copy_button.pack(side='right')
        self.clear_button = ttk.Button(footer, text='清除输入与显示', command=self.clear)
        self.clear_button.pack(side='right', padx=8)
        self.controls.append((self.clear_button, 'normal'))
        ttk.Label(body, text='报告输入不会复查原任务是否仍存在。读取文件时磁盘阻塞可能暂停界面；本工具无后台任务。',
                  wraplength=1050).grid(row=6, column=0, columnspan=2, sticky='w')
        for value in (*self.values.values(), self.disclosure):
            value.trace_add('write', self.changed)

    def _raw(self):
        return (*[self.values[key].get() for key in FIELDS], self.disclosure.get())

    def sync(self):
        """A missed variable notification cannot authorize stale input or details."""
        raw = self._raw()
        if raw != self._observed:
            self._observed = raw
            self.changed()
        return raw

    def discard(self):
        self.last = None  # Drop copy permission before any potentially failing Tk call.
        self.copy_button.configure(state='disabled')
        self.output.configure(state='normal')
        self.output.delete('1.0', 'end')
        self.output.configure(state='disabled')

    def changed(self, *_):
        self.revision += 1
        self.discard()
        self.status.set('输入、方向或明细选择已变化；旧结果已撤销，请重新比较。')

    def enable(self, enabled):
        for widget, normal in self.controls:
            widget.configure(state=normal if enabled else 'disabled')

    def begin(self):
        if self.busy or self.closed:
            return
        self.last = None
        self.busy = True
        try:
            raw = self.sync()
            self.discard()
            intent = prepare(dict(zip(FIELDS, raw[:-1])), raw[-1])
            self.active_revision = self.revision
            self.enable(False)
            shown = inspect(intent)  # No update(), timers, threads or nested event loop.
            current = self.sync()
            if current != raw or self.active_revision != self.revision:
                return
            task.files.require(type(shown) is Display and shown.intent == intent, 'comparison_display_binding')
            self.output.configure(state='normal')
            self.output.insert('1.0', shown.text)
            self.output.configure(state='disabled')
            self.status.set('本次文件比较完成；不证明执行、时间先后、链关系或当前结算。')
            # Tcl variable notifications run synchronously, even without nested
            # event pumping. Never restore a display invalidated while rendering.
            if self.sync() != raw or self.active_revision != self.revision:
                self.discard()
                return
            self.copy_button.configure(state='normal')
            self.last = shown
        except BaseException:
            self.last = None
            self.revision += 1
            self.discard()
            self.status.set(FAILURE)
        finally:
            self.busy = False
            if not self.closed:
                self.enable(True)

    def choose(self, side):
        if self.busy or self.closed or side not in ('before', 'after'):
            return
        value = self.filedialog.askopenfilename(parent=self.root, title='选择任务或审计报告')
        if value and not self.busy and not self.closed:
            self.values[f'{side}_path'].set(value)
            self.sync()  # The type and independent digest are never inferred.

    def swap(self):
        if self.busy or self.closed:
            return
        raw = self.sync()
        self.last = None
        for key, value in zip(FIELDS, (*raw[3:6], *raw[:3])):
            self.values[key].set(value)
        self.sync()

    def clear(self):
        if self.busy or self.closed:
            return
        self.last = None
        for value in self.values.values():
            value.set('')
        self.disclosure.set(False)
        self.sync()
        self.discard()

    def copy(self):
        if self.busy or self.closed:
            return
        try:
            raw = self.sync()
            shown = self.last
            if type(shown) is not Display or self.active_revision != self.revision:
                return
            if shown.intent != prepare(dict(zip(FIELDS, raw[:-1])), raw[-1]):
                self.discard()
                return
            self.root.clipboard_clear()
            self.root.clipboard_append(shown.text)  # Only the explicitly displayed observation.
        except BaseException:
            self.callback_error()

    def callback_error(self, *_):
        self.last = None
        self.revision += 1
        if not self.closed:
            self.discard()
            self.status.set(FAILURE)

    def close(self):
        if self.busy or self.closed:
            return  # A synchronous filesystem call cannot be force-cancelled here.
        self.last = None
        self.discard()
        self.root.destroy()  # A failed destroy leaves close retryable.
        self.closed = True


def main(argv=None):
    parser = comparison.Parser(description=__doc__)
    parser.add_argument('--no-real-funds', required=True, action='store_true')
    parser.parse_args(argv)
    try:
        import tkinter as tk
        root = tk.Tk()
        Workbench(root)
        root.mainloop()
        return 0
    except Exception:
        print('Evidence desktop failed. Preserve inputs; no query or permission was issued.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
