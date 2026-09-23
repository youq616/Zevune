#!/usr/bin/env python3
"""NO-FUNDS read-only wallet identity/capacity desktop, not an online wallet.

Original native op9 only. No scan, signing, export, broadcast, recovery or write.
One non-daemon worker owns authentication; only the main thread touches Tk.
Closing waits for that read-only job to return, rather than claiming cancellation.
"""
from __future__ import annotations

import sys
if __name__ == "__main__":
    sys.dont_write_bytecode = True

import argparse
from dataclasses import dataclass
from pathlib import Path
import queue
import threading
import unicodedata

import wallet_reconcile as reconcile
import wallet_health as health
from wallet_backup_backend import Backend
from zevune_wallet import checked_storage_status

FIELDS = {"wallet": 4096, "ancestor": 144, "backend": 4096, "backend_sha256": 64,
          "reserve": 19, "saves": 3, "warn": 3}
NOTICE = "NO-FUNDS｜只认证当前本地文件并检查容量；不扫描、不签名、不广播、不修改钱包。"
FAILURE = "核查未完成。请保留原文件和独立回执，核对输入；没有执行恢复、签名或付款。"
ISSUES = {"wallet_record_limit": "钱包保存额度不足", "wallet_record_headroom_low": "钱包剩余保存额度偏低",
          "filesystem_read_only": "采样文件系统为只读", "directory_entry_budget_insufficient": "目录项预算不足",
          "payload_space_low": "数据空间不足", "disk_reserve_low": "未满足指定保留空间"}
LEVELS = {"nominal": "本次未触发容量预警（不是写入保证）", "warning": "容量预警", "critical": "严重容量告警"}


def text(value: str, field: str) -> str:
    reconcile.files.require(type(value) is str and 0 < len(value) <= FIELDS[field]
                            and not any(unicodedata.category(c) in {"Cc", "Cf", "Cs", "Zl", "Zp"} for c in value),
                            "invalid_inspector_field")
    return value


def absolute(value: str) -> Path:
    path = Path(value)
    reconcile.files.require(path.is_absolute() and len(value.encode("utf-8")) <= 4096,
                            "explicit_bounded_absolute_path_required")
    return path


@dataclass(frozen=True)
class Intent:
    wallet: Path
    ancestor: str
    backend: Path
    backend_sha256: str
    reserve: int
    saves: int
    warn: int

    def review(self) -> str:
        return (f"只读钱包文件\n{self.wallet}\n\n独立保留的祖先回执\n{self.ancestor}\n\n"
                f"批准的原生后端\n{self.backend}\n后端 SHA256\n{self.backend_sha256}\n\n"
                f"预计保存次数：{self.saves}；预警余量：{self.warn}；保留字节：{self.reserve}\n\n{NOTICE}")


def prepare(values: dict[str, str]) -> Intent:
    """Validate ALL text without touching files or prompting for credentials."""
    reconcile.files.require(type(values) is dict and set(values) == set(FIELDS), "incomplete_inspector_form")
    clean = {key: text(values[key], key) for key in FIELDS}
    wallet, backend = absolute(clean["wallet"]), absolute(clean["backend"])
    ancestor = reconcile.files.receipt(clean["ancestor"])
    digest = clean["backend_sha256"]
    reconcile.files.require(reconcile.files.HEX.fullmatch(digest) is not None, "independent_backend_digest_required")
    reserve = health.decimal(clean["reserve"])
    saves, warn = health.decimal(clean["saves"], 256), health.decimal(clean["warn"], 255)
    reconcile.files.require(saves > 0, "positive_save_count_required")
    return Intent(wallet, ancestor, backend, digest, reserve, saves, warn)


def password_bytes(value: str) -> bytes:
    # Same UTF-8 bounds as the original console; no normalization or trimming.
    reconcile.files.require(type(value) is str and len(value) <= 1024, "invalid_hidden_password")
    raw = value.encode("utf-8")
    reconcile.files.require(16 <= len(raw) <= 1024, "invalid_hidden_password")
    return raw


class ReadOnlyBackend(Backend):
    def call(self, op, password, paths, receipt):
        reconcile.files.require(type(op) is int and op == 9, "read_only_inspector_operation_required")
        return super().call(op, password, paths, receipt)


@dataclass(frozen=True)
class Inspection:
    receipt: str
    used: int
    remaining: int
    file_bytes: int
    available_bytes: int
    severity: str
    issues: tuple[str, ...]
    observed_at: str

    def render(self) -> str:
        issues = "、".join(ISSUES[code] for code in self.issues) or "无容量告警"
        return (f"{LEVELS[self.severity]}\n\n已认证保存记录：{self.used} / 256\n"
                f"剩余保存次数：{self.remaining}（不是付款笔数）\n钱包文件：{self.file_bytes} 字节\n"
                f"调用者可用空间采样：{self.available_bytes} 字节\n告警：{issues}\n"
                f"采样时间：{self.observed_at}\n\n未扫描历史，未查询余额或待发送状态；不认定最新版本、"
                "广播结果或最终性。可用空间未预留，也不证明后续写入一定成功。")


def inspect_wallet(intent: Intent, password: bytes) -> Inspection:
    """Combine two accepted read-only APIs ONLY for the exact same source bytes."""
    reconcile.files.require(type(intent) is Intent and type(password) is bytes and 16 <= len(password) <= 1024,
                            "invalid_inspector_request")
    # API users cannot bypass pure-field bounds by constructing the dataclass.
    reconcile.files.require(prepare(dict(wallet=str(intent.wallet), ancestor=intent.ancestor,
                            backend=str(intent.backend), backend_sha256=intent.backend_sha256,
                            reserve=str(intent.reserve), saves=str(intent.saves), warn=str(intent.warn))) == intent,
                            "invalid_inspector_intent")
    parent = health.directory_id(intent.wallet.parent)
    backend = ReadOnlyBackend(intent.backend, intent.backend_sha256)
    tip, before = reconcile.authenticate_descendant(intent.wallet, intent.ancestor, password, backend)
    report = health.inspect(intent.wallet, tip, password, backend, reserve_bytes=intent.reserve,
                            saves=intent.saves, warn_records=intent.warn)
    reconcile.files.require(reconcile.files.read_file(intent.wallet, reconcile.files.MAX_WALLET) == before
                            and health.directory_id(intent.wallet.parent) == parent, "inspection_source_changed")
    capacity = checked_storage_status(report)
    reconcile.files.require(report["authenticated"] is True and report["read_only"] is True
                            and report["requires_rescan"] is True and report["latest_not_inferred"] is True
                            and report["operation_executed"] is False and report["space_reserved"] is False
                            and report["real_funds_allowed"] is False and report["plan"] is None
                            and capacity["records_used"] == int(tip[64:80], 16), "unexpected_inspection_scope")
    level, issues = report["severity"], report["source"]["issues"]
    reconcile.files.require(level in LEVELS and report["exit_code"] == health.EXIT_CODES[level]
                            and type(issues) is list and all(code in ISSUES for code in issues), "invalid_inspection_severity")
    available = health.bounded(report["source"]["disk"]["available_bytes"])
    return Inspection(tip, capacity["records_used"], capacity["records_remaining"], capacity["file_bytes"],
                      available, level, tuple(issues), report["observed_at"])


@dataclass(frozen=True)
class Completion:
    result: Inspection | None  # Failure is fixed data, never an exception/traceback.


def _execute(channel, released, request, completed):
    intent = password = payload = None
    try:
        # Thread creation is not admission. A late bootstrap after an interrupted
        # Thread.start must observe withdrawn credentials, not run native auth.
        released.wait()
        payload, request[0] = request[0], None
        if payload is None:
            outcome = Completion(None)
        else:
            intent, password = payload
            result = inspect_wallet(intent, password)
            outcome = Completion(result if type(result) is Inspection else None)
    except BaseException:
        outcome = Completion(None)  # Never invoke threading.excepthook with secrets.
    finally:
        intent = password = payload = None  # Reference release, not secure wiping.
        request[0] = None
    channel.put_nowait(outcome)
    completed.set()  # Explicit worker acknowledgement; ident=None proves nothing.


class InspectionJob:
    """An admission-gated operation with explicit completion ownership."""
    def __init__(self, intent, password):
        self.channel = queue.Queue(maxsize=1)
        self.released, self.completed = threading.Event(), threading.Event()
        self.request = [(intent, password)]
        self.thread = threading.Thread(target=_execute,
                                       args=(self.channel, self.released, self.request, self.completed),
                                       name="zevune-read-only-inspection", daemon=False)
        self.start_attempted = False
        self.consumed = False

    def withdraw_start(self):
        # Only withdraw an unconfirmed startup, not an already executing op9.
        # If admission raced with an interruption, the UI still owns the job
        # until the explicit completion acknowledgement below.
        self.request[0] = None
        self.released.set()

    def start(self):
        reconcile.files.require(not self.start_attempted, "inspection_start_already_attempted")
        self.start_attempted = True
        try:
            self.thread.start()
            self.released.set()
        except BaseException:
            self.withdraw_start()
            raise

    def poll(self):
        if not self.completed.is_set() or self.thread.is_alive():
            return None
        if self.thread.ident is not None:
            self.thread.join(timeout=0)
        if self.consumed:
            return None
        self.consumed = True
        try:
            return self.channel.get_nowait()
        except queue.Empty:
            return Completion(None)


class PasswordDialog:
    def __init__(self):
        # Establish an owned holder before any fallible Tk construction. The
        # workbench can then discard even a partially built credential window.
        self.password = self.window = self.entry = None

    def open(self, app, intent):
        tk, ttk = app.tk, app.ttk
        self.window = tk.Toplevel(app.root)
        self.window.title("确认只读核查并输入隐藏密码")
        self.window.transient(app.root)
        self.window.geometry("780x600")
        self.window.minsize(640, 500)
        self.window.columnconfigure(0, weight=1)
        self.window.rowconfigure(0, weight=1)
        body = ttk.Frame(self.window, padding=16)
        body.grid(sticky="nsew")
        body.columnconfigure(0, weight=1)
        body.rowconfigure(0, weight=1)
        review = tk.Text(body, wrap="word", height=17, padx=8, pady=8, exportselection=False)
        review.grid(row=0, column=0, columnspan=2, sticky="nsew")
        review.insert("1.0", intent.review())
        review.configure(state="disabled")
        ttk.Label(body, text="密码（仅交给原后端认证；不会自动保存）").grid(row=1, column=0, sticky="w", pady=(12, 4))
        self.entry = ttk.Entry(body, show="●", exportselection=False)
        self.entry.grid(row=2, column=0, columnspan=2, sticky="ew")
        self.message = tk.StringVar(self.window, "密码必须为16—1024个UTF-8字节；取消是默认操作。")
        ttk.Label(body, textvariable=self.message, wraplength=710).grid(row=3, column=0, columnspan=2, sticky="w", pady=10)
        self.cancel = ttk.Button(body, text="取消", command=lambda: self.finish(False))
        self.cancel.grid(row=4, column=0, sticky="e", padx=8)
        self.confirm = ttk.Button(body, text="确认只读核查", command=lambda: self.finish(True))
        self.confirm.grid(row=4, column=1, sticky="e")
        self.window.protocol("WM_DELETE_WINDOW", lambda: self.finish(False))
        self.window.bind("<Escape>", lambda _: self.finish(False))
        # Prevent normal widget copy/cut commands; paste remains useful for a
        # password manager. A compromised OS or clipboard history is not covered.
        self.entry.bind("<<Copy>>", lambda _: "break")
        self.entry.bind("<<Cut>>", lambda _: "break")
        self.window.grab_set()
        self.cancel.focus_set()

    def _dismiss(self):
        # Destroying the owned window also releases its local grab. Do not
        # release a different dialog's grab or touch the global clipboard.
        if self.entry is not None:
            try:
                if self.entry.winfo_exists():
                    self.entry.delete(0, "end")
            except BaseException:
                pass  # Still attempt destruction if the entry operation fails.
        if self.window is None:
            return True
        try:
            if self.window.winfo_exists():
                self.window.destroy()
            return not self.window.winfo_exists()
        except BaseException:
            return False  # Unknown cleanup is not permission for another prompt.

    def discard(self):
        self.password = None
        return self._dismiss()

    def finish(self, accepted):
        candidate = None
        self.password = None
        try:
            if accepted is True:
                try:
                    candidate = password_bytes(self.entry.get())
                except (ValueError, UnicodeError):
                    try:
                        self.entry.delete(0, "end")
                        self.message.set("密码输入无效，已清除。请重新输入或取消。")
                    except BaseException:
                        self.discard()
                    return
            if self._dismiss():
                # Release a confirmed password only after the input widget and
                # modal grab are gone. An aborted wait discards this reference.
                self.password = candidate
        finally:
            candidate = None  # Reference release, not secure-memory erasure.


class Workbench:
    def __init__(self, root):
        import tkinter as tk
        from tkinter import ttk, filedialog
        self.tk, self.ttk, self.filedialog, self.root = tk, ttk, filedialog, root
        self.busy = self.closing = self.prompt_active = False
        self.dialog = self.job = self.last_result = self.poll_token = None
        self.revision = self.active_revision = self.callback_errors = 0
        self.values = {key: tk.StringVar(root) for key in FIELDS}
        self.values["saves"].set("1")
        self.values["warn"].set("16")
        self.entries, self.controls = {}, []
        self.status = tk.StringVar(root, "请选择本地钱包和批准后端，并输入独立保存的回执及后端摘要。")
        self.receipt = tk.StringVar(root)
        root.title("Zevune｜只读钱包核查桌面 v1 · NO-FUNDS")
        root.geometry("1080x800")
        root.minsize(960, 740)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(0, weight=1)
        root.report_callback_exception = self.callback_error
        root.protocol("WM_DELETE_WINDOW", self.close)
        body = ttk.Frame(root, padding=18)
        body.grid(sticky="nsew")
        body.columnconfigure(0, weight=1)
        body.rowconfigure(4, weight=1)
        ttk.Label(body, text="只读钱包核查", font=("TkDefaultFont", 19, "bold")).grid(row=0, sticky="w")
        ttk.Label(body, text=NOTICE, wraplength=1000).grid(row=1, sticky="w", pady=(6, 12))
        form = ttk.LabelFrame(body, text="1  独立信任输入与容量策略", padding=10)
        form.grid(row=2, sticky="ew")
        form.columnconfigure(1, weight=1)
        labels = ("钱包文件", "独立旧回执或当前回执", "批准的原生后端", "独立后端 SHA256",
                  "保留空间（字节，可明确填0）", "预计保存次数（1—256）", "预警余量（0—255）")
        for row, (key, label) in enumerate(zip(FIELDS, labels)):
            ttk.Label(form, text=label).grid(row=row, column=0, sticky="w", padx=(0, 10), pady=4)
            entry = ttk.Entry(form, textvariable=self.values[key], exportselection=False)
            entry.grid(row=row, column=1, sticky="ew", pady=4)
            self.entries[key] = entry
            self.controls.append(entry)
            if key in ("wallet", "backend"):
                button = ttk.Button(form, text="选择…", command=lambda name=key: self.choose(name))
                button.grid(row=row, column=2, padx=(8, 0))
                self.controls.append(button)
        self.inspect_button = ttk.Button(form, text="核对输入并开始只读核查…", command=self.begin)
        self.inspect_button.grid(row=7, column=1, sticky="e", pady=(10, 0))
        self.controls.append(self.inspect_button)
        ttk.Label(body, textvariable=self.status, wraplength=1000).grid(row=3, sticky="w", pady=12)
        output = ttk.LabelFrame(body, text="2  本次结果（输入变化后失效；不包含余额或交易）", padding=10)
        output.grid(row=4, sticky="nsew")
        output.columnconfigure(0, weight=1)
        output.rowconfigure(0, weight=1)
        self.details = tk.Text(output, wrap="word", state="disabled", height=10, padx=8, pady=8, exportselection=False)
        self.details.grid(row=0, column=0, sticky="nsew")
        bar = ttk.Scrollbar(output, command=self.details.yview)
        bar.grid(row=0, column=1, sticky="ns")
        self.details.configure(yscrollcommand=bar.set)
        ttk.Label(output, text="本文件已认证回执（可关联钱包；仅在需要时明确复制并独立保管）").grid(row=1, sticky="w", pady=(10, 4))
        ttk.Entry(output, textvariable=self.receipt, state="readonly", exportselection=False).grid(row=2, sticky="ew")
        self.copy_button = ttk.Button(output, text="复制回执", state="disabled", command=self.copy)
        self.copy_button.grid(row=2, column=1, padx=(8, 0))
        footer = ttk.Frame(body)
        footer.grid(row=5, sticky="ew", pady=(12, 0))
        ttk.Label(footer, text="不保存密码、最近文件或核查报告。停止其他钱包写入；剪贴板历史由操作者管理。", wraplength=820).pack(side="left")
        self.clear_button = ttk.Button(footer, text="清除输入", command=self.clear)
        self.clear_button.pack(side="right")
        self.controls.append(self.clear_button)
        for value in self.values.values():
            value.trace_add("write", self.changed)

    def discard(self):
        self.last_result = None
        self.receipt.set("")
        self.copy_button.configure(state="disabled")
        self.details.configure(state="normal")
        self.details.delete("1.0", "end")
        self.details.configure(state="disabled")

    def changed(self, *_):
        self.revision += 1
        self.discard()
        if not self.busy:
            self.status.set("输入已改变，请重新核查；旧结果不再代表当前输入。")

    def enable(self, enabled):
        for widget in self.controls:
            widget.configure(state="normal" if enabled else "disabled")

    def choose(self, name):
        if self.busy or self.closing:
            return
        value = self.filedialog.askopenfilename(parent=self.root, title="选择现有本地文件（不会自动信任摘要）")
        if value:
            self.values[name].set(value)

    def begin(self):
        if self.busy or self.closing:
            return
        self.discard()
        try:
            intent = prepare({key: value.get() for key, value in self.values.items()})
        except (ValueError, KeyError, UnicodeError):
            self.status.set(FAILURE)
            return
        self.busy = True
        self.active_revision = self.revision
        self.enable(False)
        password = dialog = None
        try:
            self.dialog = dialog = PasswordDialog()
            self.prompt_active = True
            dialog.open(self, intent)
            self.root.wait_window(dialog.window)
            password, dialog.password = dialog.password, None
            # Keep ownership until finally, including a wait which is interrupted
            # after confirmation but before its returned password is consumed.
            self.prompt_active = False
            if self.closing or self.revision != self.active_revision or password is None:
                self.status.set("已取消或输入已变化，没有启动核查。")
                return
            self.job = InspectionJob(intent, password)
            self.job.start()
            self.status.set("正在只读认证与采样，界面可响应；关闭请求会等待本次核查结束。")
        except BaseException:
            self.status.set(FAILURE)
            self.revision += 1
            if self.job is not None:
                self.job.withdraw_start()
                if not self.job.start_attempted:
                    self.job = None  # Definitively no start call was attempted.
                else:
                    # No portable way to distinguish a failed OS creation from
                    # a created thread whose bootstrap has not set ident yet.
                    # Retain ownership; polling only trusts worker completion.
                    self.status.set("线程启动未确认，已撤回尚未开始的认证请求。等待线程收尾；若始终未启动，请结束本应用进程后重开。")
        finally:
            password = None
            self.prompt_active = False
            dialog_closed = self.dialog is None or self.dialog.discard()
            if dialog_closed:
                self.dialog = None
            dialog = None
            if self.job is not None:
                self.poll_token = self.root.after(50, self.poll)
            elif not dialog_closed:
                self.busy = True
                self.status.set("密码窗口清理未确认，禁止新核查。请关闭本应用；若无法关闭，请结束进程后重开。")
            else:
                self.busy = False
                if self.closing:
                    self.root.destroy()
                else:
                    self.enable(True)

    def poll(self):
        self.poll_token = None
        completion = self.job.poll()
        if completion is None:
            self.poll_token = self.root.after(50, self.poll)
            return
        self.job = None
        self.busy = False
        if self.closing:
            self.discard()
            self.root.destroy()
            return
        self.enable(True)
        if self.active_revision != self.revision or completion.result is None:
            self.discard()
            self.status.set(FAILURE)
            return
        self.last_result = completion.result
        self.status.set(LEVELS[self.last_result.severity])
        self.receipt.set(self.last_result.receipt)
        self.details.configure(state="normal")
        self.details.insert("1.0", self.last_result.render())
        self.details.configure(state="disabled")
        self.copy_button.configure(state="normal")

    def copy(self):
        if self.busy or self.closing or self.last_result is None or self.active_revision != self.revision:
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(self.last_result.receipt)

    def clear(self):
        if self.busy or self.closing:
            return
        for value in self.values.values():
            value.set("")
        self.values["saves"].set("1")
        self.values["warn"].set("16")
        self.discard()

    def callback_error(self, *_):
        self.callback_errors += 1
        self.revision += 1
        self.discard()
        self.status.set(FAILURE)
        if self.dialog is not None:
            self.dialog.discard()

    def close(self):
        if self.closing:
            return
        self.closing = True
        self.discard()
        self.enable(False)
        if self.dialog is not None:
            cleaned = self.dialog.discard()
            if cleaned and not self.prompt_active and self.job is None:
                self.dialog = None
                self.busy = False
                self.root.destroy()
            elif not cleaned:
                self.status.set("密码窗口清理未确认，请结束本应用进程后重开。未启动新的核查。")
        elif self.job is not None:
            self.status.set("已请求关闭；正在等待本次只读核查收尾，不接受新操作。")
        else:
            self.root.destroy()


class Parser(argparse.ArgumentParser):
    def error(self, message):
        self.exit(64, "Invalid read-only desktop arguments. Use --help; never put passwords in arguments.\n")


def main(argv=None):
    parser = Parser(description=__doc__)
    parser.add_argument("--no-real-funds", required=True, action="store_true")
    parser.parse_args(argv)
    try:
        import tkinter as tk
        root = tk.Tk()
        Workbench(root)
        root.mainloop()
        return 0
    except Exception:
        print("Read-only desktop could not finish. Preserve original files and independent receipts.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
