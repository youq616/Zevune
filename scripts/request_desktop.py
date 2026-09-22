#!/usr/bin/env python3
"""NO-FUNDS offline request desktop: create/inspect, never sign or broadcast.

Uses the accepted payment_request implementation and unchanged wire format.
No wallet path, password, backend, recent-file store or background worker exists.
Tk is loaded only when opening the desktop; --help works without Tk/display.
"""
from __future__ import annotations

import sys
if __name__ == "__main__":
    sys.dont_write_bytecode = True

import argparse
import unicodedata
from dataclasses import dataclass
from pathlib import Path

import payment_request as request

NOTICE = "NO-FUNDS｜请求是明文意图，不是签名、发票认证或付款凭证。"
LIMITS = {"genesis": 4096, "genesis_pin": 64, "recipient": 256,
          "amount": 20, "expiry": 20, "target": 4096, "source": 4096, "request_pin": 64}
FAILURE = "操作未完成。请核对输入；保留可能已经创建的文件，不覆盖、不自动重试。"
UNTRUSTED = "仅检查格式、网络标签及独立摘要；未认证收款人，未核对当前高度，不防重复付款。"


def bounded(value: str, name: str) -> str:
    # Use the running Python Unicode database, not a partial bidi blacklist.
    # Reject controls, format controls, lone surrogates and line/paragraph
    # separators. Preserve visible Unicode and combining marks exactly; this
    # is not a general confusable-character detector or filename normalization.
    request.storage.require(type(value) is str and 0 < len(value) <= LIMITS[name]
                            and not any(unicodedata.category(c) in {"Cc", "Cf", "Cs", "Zl", "Zp"} for c in value),
                            "invalid_desktop_field")
    return value


def absolute(value: str, name: str) -> Path:
    path = Path(bounded(value, name))
    request.storage.require(path.is_absolute(), "explicit_absolute_desktop_path_required")
    return path


@dataclass(frozen=True)
class Intent:
    genesis: Path
    genesis_pin: str
    target: Path
    recipient: str
    amount: str
    expiry: str

    def review(self) -> str:
        return (f"网络 SHA256\n{self.genesis_pin}\n\n收款地址\n{self.recipient}\n\n"
                f"测试金额（整数单位）：{self.amount}\n到期区块高度：{self.expiry}\n\n"
                f"新请求文件\n{self.target}\n\n{NOTICE}\n{UNTRUSTED}")


def prepare_intent(values: dict[str, str]) -> Intent:
    """Read/validate for confirmation without creating a file or trusting a hash alone."""
    genesis = absolute(values["genesis"], "genesis")
    domain = request.digest(bounded(values["genesis_pin"], "genesis_pin"))
    target = request.storage.new_file(absolute(values["target"], "target"))
    request.network(genesis, domain)
    recipient = request.checked_recipient(bounded(values["recipient"], "recipient"), domain)
    amount, _, expiry = request.checked_payment_numbers(bounded(values["amount"], "amount"), "1",
                                                       bounded(values["expiry"], "expiry"))
    return Intent(genesis, domain, target, recipient, amount, expiry)


def save_intent(intent: Intent) -> dict:
    # Confirmation grants no persistent permission: revalidate source network,
    # recipient, numbers, directory and create-only output in the existing API.
    return request.create_request(intent.target, intent.genesis, intent.genesis_pin,
                                  intent.recipient, intent.amount, intent.expiry)


def inspect_values(values: dict[str, str]) -> dict:
    return request.inspect_request(absolute(values["source"], "source"),
                                   request.digest(bounded(values["request_pin"], "request_pin")),
                                   absolute(values["genesis"], "genesis"),
                                   request.digest(bounded(values["genesis_pin"], "genesis_pin")))


class Confirmation:
    """Actual modal Tk window; cancel is the default, never auto-confirmed."""
    def __init__(self, app, intent):
        tk, ttk = app.tk, app.ttk
        self.accepted = False
        self.window = tk.Toplevel(app.root)
        self.window.title("核对明文请求 — 不会付款")
        self.window.transient(app.root)
        self.window.geometry("760x510")
        self.window.minsize(640, 430)
        self.window.columnconfigure(0, weight=1)
        self.window.rowconfigure(0, weight=1)
        frame = ttk.Frame(self.window, padding=16)
        frame.grid(sticky="nsew")
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        text = tk.Text(frame, wrap="word", height=19, width=65, padx=10, pady=10)
        text.grid(row=0, column=0, sticky="nsew")
        bar = ttk.Scrollbar(frame, orient="vertical", command=text.yview)
        bar.grid(row=0, column=1, sticky="ns")
        text.configure(yscrollcommand=bar.set)
        text.insert("1.0", intent.review())
        text.configure(state="disabled")
        buttons = ttk.Frame(frame, padding=(0, 14, 0, 0))
        buttons.grid(row=1, column=0, columnspan=2, sticky="e")
        self.cancel = ttk.Button(buttons, text="取消", command=lambda: self.finish(False))
        self.cancel.pack(side="left", padx=6)
        self.confirm = ttk.Button(buttons, text="确认创建新文件", command=lambda: self.finish(True))
        self.confirm.pack(side="left")
        self.window.protocol("WM_DELETE_WINDOW", lambda: self.finish(False))
        self.window.bind("<Escape>", lambda _: self.finish(False))
        self.window.grab_set()
        self.cancel.focus_set()

    def finish(self, accepted):
        self.accepted = accepted is True
        self.window.destroy()


class Workbench:
    def __init__(self, root):
        import tkinter as tk
        from tkinter import ttk, filedialog
        self.tk, self.ttk, self.filedialog = tk, ttk, filedialog
        self.root, self.confirmation = root, None
        self.busy = self.closing = False
        self.revision, self.callback_errors = 0, 0
        self.last_result = None
        self.controls, self.entries, self.actions = [], {}, {}
        self.values = {name: tk.StringVar(root) for name in LIMITS}
        self.status = tk.StringVar(root, "请选择可信本地创世文件，并输入独立保存的网络 SHA256。")
        self.digest = tk.StringVar(root)
        root.title("Zevune｜离线收款请求工作台 v1 · NO-FUNDS")
        root.geometry("1040x800")
        root.minsize(920, 740)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(0, weight=1)
        root.report_callback_exception = self._callback_error
        root.protocol("WM_DELETE_WINDOW", self.close)
        body = ttk.Frame(root, padding=18)
        body.grid(sticky="nsew")
        body.columnconfigure(0, weight=1)
        body.rowconfigure(5, weight=1)
        ttk.Label(body, text="离线收款请求工作台", font=("TkDefaultFont", 18, "bold")).grid(row=0, sticky="w")
        ttk.Label(body, text=NOTICE + " 本界面不接触钱包或密码。", wraplength=970).grid(row=1, sticky="w", pady=(6, 14))
        network = ttk.LabelFrame(body, text="1  选择网络（不会自动信任文件内部信息）", padding=10)
        network.grid(row=2, sticky="ew", pady=(0, 12))
        network.columnconfigure(1, weight=1)
        self._field(network, 0, "genesis", "创世文件", "open")
        self._field(network, 1, "genesis_pin", "独立网络 SHA256")
        self.tabs = ttk.Notebook(body)
        self.tabs.grid(row=3, sticky="ew")
        create, inspect = ttk.Frame(self.tabs, padding=12), ttk.Frame(self.tabs, padding=12)
        self.tabs.add(create, text="2A  创建收款请求")
        self.tabs.add(inspect, text="2B  检查已有请求")
        for frame in (create, inspect):
            frame.columnconfigure(1, weight=1)
        for row, (key, label, pick) in enumerate((("recipient", "LAB2 收款地址", None),
                                                ("amount", "测试金额（整数单位）", None),
                                                ("expiry", "到期区块高度（非日期）", None),
                                                ("target", "全新请求文件", "save"))):
            self._field(create, row, key, label, pick)
        self.actions["create"] = self._button(create, "核对后创建…", self.create)
        self.actions["create"].grid(row=4, column=1, sticky="e", pady=(10, 0))
        self._field(inspect, 0, "source", "已有请求文件", "open")
        self._field(inspect, 1, "request_pin", "独立请求 SHA256")
        ttk.Label(inspect, text=UNTRUSTED, wraplength=720).grid(row=2, column=0, columnspan=3, sticky="w", pady=10)
        self.actions["inspect"] = self._button(inspect, "只读检查", self.inspect)
        self.actions["inspect"].grid(row=3, column=1, sticky="e")
        ttk.Label(body, textvariable=self.status, wraplength=970).grid(row=4, sticky="w", pady=12)
        result = ttk.LabelFrame(body, text="3  本次结果（修改输入后自动清除）", padding=10)
        result.grid(row=5, sticky="nsew")
        result.rowconfigure(0, weight=1)
        result.columnconfigure(0, weight=1)
        self.details = tk.Text(result, state="disabled", wrap="word", height=9, padx=8, pady=8)
        self.details.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(result, orient="vertical", command=self.details.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.details.configure(yscrollcommand=scrollbar.set)
        ttk.Label(result, text="请求 SHA256（请通过可信渠道独立保存）").grid(row=1, column=0, sticky="w", pady=(10, 4))
        ttk.Entry(result, textvariable=self.digest, state="readonly").grid(row=2, column=0, sticky="ew")
        self.copy_button = ttk.Button(result, text="复制摘要", state="disabled", command=self.copy_digest)
        self.copy_button.grid(row=2, column=1, padx=(8, 0))
        footer = ttk.Frame(body)
        footer.grid(row=6, sticky="ew", pady=(12, 0))
        ttk.Label(footer, text="无自动保存、无联网同步；请求明文和剪贴板历史须自行保护。", wraplength=730).pack(side="left")
        self.actions["clear"] = self._button(footer, "清除界面输入", self.clear)
        self.actions["clear"].pack(side="right")
        for variable in self.values.values():
            variable.trace_add("write", self._changed)
        self.tabs.bind("<<NotebookTabChanged>>", lambda _: self._changed() if self.last_result is not None else None)

    def _button(self, parent, text, command):
        button = self.ttk.Button(parent, text=text, command=command)
        self.controls.append(button)
        return button

    def _field(self, parent, row, key, label, pick=None):
        self.ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=(0, 10), pady=4)
        entry = self.ttk.Entry(parent, textvariable=self.values[key])
        entry.grid(row=row, column=1, sticky="ew", pady=4)
        self.entries[key] = entry
        self.controls.append(entry)
        if pick:
            self._button(parent, "选择…", lambda: self.choose(key, pick)).grid(row=row, column=2, padx=(8, 0))

    def _text(self, text):
        self.details.configure(state="normal")
        self.details.delete("1.0", "end")
        self.details.insert("1.0", text)
        self.details.configure(state="disabled")

    def _changed(self, *_):
        self.revision += 1
        self.last_result = None
        self.digest.set("")
        self.copy_button.configure(state="disabled")
        self._text("")
        self.status.set("输入或页面已变更，请重新操作；原结果不再代表当前输入。")

    def _callback_error(self, *_):
        # Tk's default prints a traceback. Do not expose paths/intents to logs.
        self.callback_errors += 1
        self._changed()
        self.status.set(FAILURE)
        if self.confirmation is not None:
            self.confirmation.finish(False)

    def _enable(self, enabled):
        for control in self.controls:
            control.configure(state="normal" if enabled else "disabled")

    def choose(self, key, mode):
        if self.busy:
            return
        options = dict(parent=self.root, filetypes=[("Zevune request", "*.zvrequest"), ("All files", "*")])
        if key == "genesis":
            options["filetypes"] = [("All files", "*")]
        try:
            if mode == "save":
                value = self.filedialog.asksaveasfilename(**options, title="选择新文件；已有文件拒绝覆盖",
                                                         defaultextension=".zvrequest", confirmoverwrite=False)
            else:
                value = self.filedialog.askopenfilename(**options, title="选择可信本地文件")
            if value:
                self.values[key].set(value)
        except (OSError, ValueError, self.tk.TclError):
            self._changed()
            self.status.set(FAILURE)

    def _perform(self, action):
        if self.busy:
            return
        self._changed()
        self.busy = True
        revision = self.revision
        self._enable(False)
        self.status.set("正在核对；已有文件不会被覆盖。")
        try:
            action(revision)
        except (ValueError, OSError, RuntimeError, self.tk.TclError):
            self._changed()
            self.status.set(FAILURE)
        finally:
            self.confirmation = None
            self.busy = False
            if self.closing:
                self.root.destroy()
            else:
                self._enable(True)

    def create(self):
        def action(revision):
            intent = prepare_intent({k: v.get() for k, v in self.values.items()})
            self.confirmation = Confirmation(self, intent)
            self.root.wait_window(self.confirmation.window)
            if not self.confirmation.accepted or self.closing:
                self.status.set("已取消；本次没有创建文件。")
                return
            request.storage.require(self.revision == revision, "desktop_input_changed_during_confirmation")
            result = save_intent(intent)
            self.last_result = result
            self.digest.set(result["request_sha256"])
            self._text(intent.review())
            self.status.set("请求文件已创建：未签名、未广播、未付款。请独立保存摘要。")
            self.copy_button.configure(state="normal")
        self._perform(action)

    def inspect(self):
        def action(revision):
            result = inspect_values({k: v.get() for k, v in self.values.items()})
            data = result["request"]
            self.last_result = result
            self.digest.set(result["request_sha256"])
            self._text(f"网络 SHA256\n{data['genesis_sha256']}\n\n收款地址\n{data['recipient']}\n\n"
                       f"测试金额（整数单位）：{data['amount']}\n到期区块高度：{data['expiry_height']}\n\n{UNTRUSTED}")
            self.status.set("公开字节一致性检查通过，不是认证、确认或付款许可。")
            self.copy_button.configure(state="normal")
        self._perform(action)

    def copy_digest(self):
        if self.busy or self.last_result is None:
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(self.digest.get())
        self.status.set("仅请求摘要已复制；系统剪贴板历史可能保留它。未自动复制地址或金额。")

    def clear(self):
        if self.busy:
            return
        for variable in self.values.values():
            variable.set("")
        self._changed()
        self.status.set("界面已清除；没有删除文件，也没有清除系统剪贴板。")

    def close(self):
        if self.busy:
            self.closing = True
            if self.confirmation is not None:
                self.confirmation.finish(False)
        else:
            self.root.destroy()


class Parser(argparse.ArgumentParser):
    def error(self, message):
        self.exit(64, "Invalid desktop arguments. Use --help; no passwords or payment details belong in arguments.\n")


def main(argv=None):
    parser = Parser(description=__doc__)
    parser.add_argument("--no-real-funds", action="store_true", required=True)
    parser.parse_args(argv)
    root = None
    try:
        import tkinter as tk
        if sys.platform not in ("linux", "win32"):
            raise RuntimeError("unsupported_desktop_platform")
        root = tk.Tk()
        Workbench(root)
        root.mainloop()
        return 0
    except (ImportError, OSError, RuntimeError):
        print("Desktop unavailable. Use trusted Python with Tk and a graphical session. No operation was retried.", file=sys.stderr)
        return 1
    except Exception:
        # Tk startup/backend errors must not disclose raw paths to a console.
        print("Desktop stopped unexpectedly. Retain any output; do not retry blindly.", file=sys.stderr)
        return 1
    finally:
        if root is not None:
            try:
                root.destroy()
            except Exception:
                pass


if __name__ == "__main__":
    raise SystemExit(main())
