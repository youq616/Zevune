#!/usr/bin/env python3
"""NO-FUNDS local reconciliation viewer; no password, backend or wallet changes.

This small local-file view is synchronous and does not promise responsive UI
while filesystem IO blocks. It never pumps a nested event loop during inspection.
"""
import sys
if __name__ == "__main__":
    sys.dont_write_bytecode = True

import reconciliation_view as view


class Workbench:
    def __init__(self, root):
        import tkinter as tk
        from tkinter import ttk, filedialog
        self.root, self.tk, self.ttk, self.filedialog = root, tk, ttk, filedialog
        self.busy = self.closed = False
        self.revision = self.active_revision = 0
        self.last = None
        self.values = {key: tk.StringVar(root) for key in view.FIELDS}
        self.status = tk.StringVar(root, "输入恢复目录、独立报告摘要、检查点及网络摘要。")
        self.controls, self.entries = [], {}
        root.title("Zevune｜付款对账结果查看器 · NO-FUNDS")
        root.geometry("1040x760")
        root.minsize(760, 540)
        root.report_callback_exception = self.callback_error
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(0, weight=1)
        body = ttk.Frame(root, padding=16)
        body.grid(sticky="nsew")
        body.columnconfigure(1, weight=1)
        body.rowconfigure(7, weight=1)
        ttk.Label(body, text=view.NOTICE, wraplength=940).grid(row=0, column=0, columnspan=3, sticky="w", pady=8)
        labels = ("恢复结果目录", "独立报告 SHA256", "独立账本检查点", "独立网络 SHA256")
        for row, (key, label) in enumerate(zip(view.FIELDS, labels), 1):
            ttk.Label(body, text=label).grid(row=row, column=0, sticky="w", padx=(0, 12))
            entry = ttk.Entry(body, textvariable=self.values[key], exportselection=False)
            entry.grid(row=row, column=1, columnspan=2, sticky="ew", pady=5)
            self.entries[key] = entry
            self.controls.append(entry)
        self.choose_button = ttk.Button(body, text="选择目录…", command=self.choose)
        self.choose_button.grid(row=5, column=0, sticky="w", pady=8)
        self.inspect_button = ttk.Button(body, text="核验并查看（不会付款）", command=self.begin)
        self.inspect_button.grid(row=5, column=1, sticky="e")
        self.clear_button = ttk.Button(body, text="清除显示", command=self.clear)
        self.clear_button.grid(row=5, column=2, sticky="e")
        self.controls.extend((self.choose_button, self.inspect_button, self.clear_button))
        ttk.Label(body, textvariable=self.status, wraplength=940).grid(row=6, column=0, columnspan=3, sticky="w", pady=8)
        self.details = tk.Text(body, wrap="word", state="disabled", exportselection=False, height=16)
        self.details.grid(row=7, column=0, columnspan=2, sticky="nsew")
        scroll = ttk.Scrollbar(body, command=self.details.yview)
        scroll.grid(row=7, column=2, sticky="ns")
        self.details.configure(yscrollcommand=scroll.set)
        self.copy_button = ttk.Button(body, text="复制本次交易ID", command=self.copy, state="disabled")
        self.copy_button.grid(row=8, column=1, sticky="e", pady=8)
        ttk.Label(body, text="仅显示历史文件快照；不是实时监控。读取本地磁盘时界面可能短暂等待。",
                  wraplength=940).grid(row=9, column=0, columnspan=3, sticky="w")
        for value in self.values.values():
            value.trace_add("write", self.changed)

    def discard(self):
        self.last = None
        self.copy_button.configure(state="disabled")
        self.details.configure(state="normal")
        self.details.delete("1.0", "end")
        self.details.configure(state="disabled")

    def changed(self, *_):
        self.revision += 1
        self.discard()
        self.status.set("输入已改变；旧核验结果已清除。")

    def choose(self):
        if self.busy or self.closed:
            return
        chosen = self.filedialog.askdirectory(parent=self.root, mustexist=True)
        if chosen:
            self.values["directory"].set(chosen)

    def begin(self):
        if self.busy or self.closed:
            return
        self.discard()
        self.busy = True
        self.active_revision = self.revision
        try:
            for control in self.controls:
                control.configure(state="disabled")
            intent = view.prepare({key: value.get() for key, value in self.values.items()})
            result = view.inspect(intent)  # No update()/wait_window(): no nested event processing.
            if self.active_revision != self.revision or self.closed:
                self.status.set("输入已改变；本次结果未显示。")
                return
            self.details.configure(state="normal")
            self.details.insert("1.0", result.render())
            self.details.configure(state="disabled")
            self.status.set("本次文件完整性核验完成；广播和结算状态仍未知。")
            self.last = result
            if result.txid is not None:
                self.copy_button.configure(state="normal")
        except BaseException:
            self.revision += 1
            self.discard()
            self.status.set(view.FAILURE)
        finally:
            self.busy = False
            if not self.closed:
                for control in self.controls:
                    control.configure(state="normal")

    def copy(self):
        if self.busy or self.closed or self.last is None or self.last.txid is None or self.active_revision != self.revision:
            return
        # Explicit copying of the observed historical identifier, not revalidation.
        self.root.clipboard_clear()
        self.root.clipboard_append(self.last.txid)

    def clear(self):
        if self.busy or self.closed:
            return
        for value in self.values.values():
            value.set("")
        self.discard()

    def callback_error(self, *_):
        self.revision += 1
        self.discard()
        self.status.set(view.FAILURE)

    def close(self):
        if self.busy or self.closed:
            return
        self.discard()
        self.closed = True
        self.root.destroy()


def main(argv=None):
    parser = view.Parser(description=__doc__)
    parser.add_argument("--no-real-funds", action="store_true", required=True)
    parser.parse_args(argv)
    try:
        import tkinter as tk
        root = tk.Tk()
        Workbench(root)
        root.mainloop()
        return 0
    except Exception:
        print("Reconciliation viewer could not finish. Original files are not modified.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
