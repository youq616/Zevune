#!/usr/bin/env python3
"""Collect bounded OS memory evidence for the fixed NO-FUNDS payment test.

Linux RSS accounting can be approximate; Windows working sets include shared
pages. Neither is a private heap measurement. OS peaks belong to one process
lifetime, not to an individual payment or checkpoint. No command lines,
environment values, wallets or transaction contents are read. Names present
in OS identity records are discarded and never included in evidence.

Definitions: https://docs.kernel.org/filesystems/proc.html and
https://learn.microsoft.com/en-us/windows/win32/api/psapi/ns-psapi-process_memory_counters
"""
from __future__ import annotations

import ctypes
from dataclasses import asdict, dataclass
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import select
import signal
import stat
import subprocess
import sys
import tempfile
import time


MEMORY_BUDGET_BYTES = 1 << 30
SEGMENT_BYTES = 1 << 20
MAX_PID = (1 << 32) - 1
MAX_UINT64 = (1 << 64) - 1
MAX_EVENT_BYTES = 16384
MAX_PROGRESS_BYTES = 65536
MAX_PROGRESS_RECORDS = 2048
SUPERVISOR_TIMEOUT_SECONDS = 1230
WALLET_HEADER_BYTES = 72
WALLET_RECORD_BYTES = 32948
PHASES = (
    ("genesis", 0, 1),
    ("payment_8", 8, 1),
    ("payment_16", 16, 1),
    ("payment_24", 24, 1),
    ("payment_32", 32, 1),
    ("worker_reopened_32", 32, 2),
    ("wallet_recovered_32", 32, 2),
    ("pending_restored_33", 32, 2),
    ("complete_33", 33, 2),
)
CORE_OPERATIONS = ("prepare", "candidate", "worker_commit", "scenario_apply", "wallet_sync")


def expected_operations() -> tuple[tuple[str, int, int, int], ...]:
    """The fixed Go execution order: operation, payment, start/end count.

    Recovery must finish before preparing payment 33, and its newly created
    outbox must be restored before that payment enters candidate selection.
    A multiset of successful operations cannot establish those dependencies.
    """
    operations = [("scenario_start", 0, 0, 0), ("worker_create", 0, 0, 0),
                  ("wallet_sync", 0, 0, 0)]
    for payment in range(1, 34):
        previous = payment - 1
        if payment == 33:
            operations.extend((operation, 0, 32, 32) for operation in
                              ("worker_close", "disk_check", "worker_reopen", "wallet_recover"))
        operations.append(("prepare", payment, previous, previous))
        if payment == 33:
            operations.append(("outbox_restore", 33, 32, 32))
        operations.extend((("candidate", payment, previous, previous),
                           ("worker_commit", payment, previous, payment),
                           ("scenario_apply", payment, payment, payment),
                           ("wallet_sync", payment, payment, payment)))
        if payment in (8, 16, 24, 32, 33):
            operations.append(("duplicate_rejection", 0, payment, payment))
    operations.extend((operation, 0, 33, 33) for operation in
                      ("worker_close", "disk_check", "finish"))
    return tuple(operations)


EXPECTED_OPERATIONS = expected_operations()
CHECKS = {
    "genuine_payments", "summary_agreement", "capacity_accounting", "wallet_records",
    "wallet_file_bytes", "physical_frames", "worker_full_replay", "scenario_full_replay",
    "wallet_backup_recovery", "post_recovery_payment", "exact_outbox_recovery",
    "rejection_nonmutation", "pending_commit_preserved", "pending_cleared",
}


class MeasurementError(RuntimeError):
    """A fixed public failure code; never embeds untrusted input or secrets."""


def checked_uint(value: object, maximum: int = MAX_UINT64,
                 minimum: int = 0) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise MeasurementError("invalid_unsigned_integer")
    return value


def exact_keys(value: object, keys: set[str]) -> dict:
    if not isinstance(value, dict) or set(value) != keys:
        raise MeasurementError("invalid_object_fields")
    return value


def decode_json(raw: bytes, maximum: int = MAX_EVENT_BYTES) -> dict:
    if not raw or len(raw) > maximum:
        raise MeasurementError("invalid_json_size")

    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise MeasurementError("duplicate_json_field")
            result[key] = value
        return result

    def constant(_value):
        raise MeasurementError("invalid_json_number")

    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs,
                           parse_constant=constant)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise MeasurementError("invalid_json") from exc
    if not isinstance(value, dict):
        raise MeasurementError("invalid_json_object")
    return value


def checked_wallets(value: object, seq: int) -> list[dict]:
    if not isinstance(value, list) or len(value) != 2:
        raise MeasurementError("invalid_wallets")
    height = PHASES[seq - 1][1]
    expected = [2 + height + (height + 1) // 2, 2 + height + height // 2]
    if seq == 8:  # The 33rd pending payment is saved, but not yet committed.
        expected[0] += 1
    for wallet, records in zip(value, expected):
        exact_keys(wallet, {"records_used", "file_bytes"})
        if checked_uint(wallet["records_used"], 256, 1) != records:
            raise MeasurementError("unexpected_wallet_records")
        if checked_uint(wallet["file_bytes"]) != (
                WALLET_HEADER_BYTES + records * WALLET_RECORD_BYTES):
            raise MeasurementError("unexpected_wallet_bytes")
    return value


def checked_state(value: object, height: int) -> dict:
    exact_keys(value, {"commitments", "nullifiers", "fees", "logical_bytes",
                       "segments", "tail_bytes"})
    for key, expected in (("commitments", 2 + 2 * height),
                          ("nullifiers", 2 * height), ("fees", 1000 * height)):
        if checked_uint(value[key]) != expected:
            raise MeasurementError("unexpected_committed_state")
    logical = checked_uint(value["logical_bytes"], MEMORY_BUDGET_BYTES, 140)
    segments = checked_uint(value["segments"], 2048)
    tail = checked_uint(value["tail_bytes"], SEGMENT_BYTES)
    if height == 0:
        if (logical, segments, tail) != (140, 0, 0):
            raise MeasurementError("unexpected_genesis_capacity")
    elif (segments == 0 or segments > height or tail < 150
          or logical < 140 + height * 150
          or logical > 140 + (segments - 1) * SEGMENT_BYTES + tail
          or logical < 140 + (segments - 1) * 150 + tail):
        raise MeasurementError("inconsistent_capacity")
    return value


def checked_event(value: object, seq: int) -> dict:
    checked_uint(seq, len(PHASES), 1)
    exact_keys(value, {"schema_version", "seq", "phase", "height",
                       "paid_blocks", "processes", "state", "wallets",
                       "elapsed_ms"})
    if checked_uint(value["schema_version"]) != 1:
        raise MeasurementError("unsupported_event_schema")
    phase, height, worker_generation = PHASES[seq - 1]
    if (checked_uint(value["seq"]) != seq or value["phase"] != phase
            or checked_uint(value["height"]) != height
            or checked_uint(value["paid_blocks"]) != height):
        raise MeasurementError("unexpected_checkpoint")
    checked_uint(value["elapsed_ms"], 1_200_000)
    processes = value["processes"]
    if not isinstance(processes, list) or len(processes) != 2:
        raise MeasurementError("invalid_processes")
    seen_roles, seen_pids = set(), set()
    for process in processes:
        exact_keys(process, {"role", "generation", "pid"})
        role = process["role"]
        if not isinstance(role, str) or role not in {"worker", "scenario"}:
            raise MeasurementError("unexpected_process_role")
        generation = worker_generation if role == "worker" else 1
        if checked_uint(process["generation"]) != generation:
            raise MeasurementError("unexpected_process_generation")
        pid = checked_uint(process["pid"], MAX_PID, 1)
        if role in seen_roles or pid in seen_pids:
            raise MeasurementError("duplicate_process_identity")
        seen_roles.add(role)
        seen_pids.add(pid)
    checked_state(value["state"], height)
    checked_wallets(value["wallets"], seq)
    return value


def checked_progress(value: object, seq: int, pending: dict | None) -> dict:
    checked_uint(seq, MAX_PROGRESS_RECORDS, 1)
    if not isinstance(value, dict) or not isinstance(value.get("status"), str) or value["status"] not in {"started", "completed"}:
        raise MeasurementError("invalid_progress_status")
    keys = {"schema_version", "seq", "operation", "payment_index", "committed_blocks", "status"}
    if value["status"] == "completed":
        keys.add("duration_ms")
    exact_keys(value, keys)
    if checked_uint(value["schema_version"]) != 1 or checked_uint(value["seq"]) != seq:
        raise MeasurementError("invalid_progress_sequence")
    operation = value["operation"]
    if not isinstance(operation, str):
        raise MeasurementError("invalid_progress_operation")
    payment = checked_uint(value["payment_index"], 33)
    committed = checked_uint(value["committed_blocks"], 33)
    if seq > 2 * len(EXPECTED_OPERATIONS):
        raise MeasurementError("unexpected_progress_step")
    name, expected_payment, before, after = EXPECTED_OPERATIONS[(seq - 1) // 2]
    expected_status = "started" if seq % 2 else "completed"
    expected_count = before if seq % 2 else after
    if (operation != name or payment != expected_payment or committed != expected_count
            or value["status"] != expected_status):
        raise MeasurementError("unexpected_progress_step")
    if value["status"] == "started":
        if pending is not None:
            raise MeasurementError("overlapping_progress_operations")
    else:
        checked_uint(value["duration_ms"], 1_200_000)
        if pending is None:
            raise MeasurementError("unpaired_progress_completion")
        # Recheck the exact preceding start record as well, so a direct call
        # cannot pair a valid completion with an unrelated or malformed start.
        checked_progress(pending, seq - 1, None)
    return value


def checked_result(value: object, events: list[dict], progress: list[dict]) -> dict:
    exact_keys(value, {"schema_version", "complete", "paid_blocks", "height",
                       "actions_per_payment", "commitments", "nullifiers", "fees",
                       "logical_bytes", "segments", "tail_bytes", "wallet_records",
                       "wallet_bytes", "checks", "timings"})
    if len(events) != 9 or not isinstance(progress, list) or len(progress) != 2 * len(EXPECTED_OPERATIONS):
        raise MeasurementError("incomplete_checkpoint_or_progress_sequence")
    pending = None
    for seq, entry in enumerate(progress, 1):
        checked_progress(entry, seq, pending)
        pending = entry if entry["status"] == "started" else None
    for key, expected in (("schema_version", 1), ("paid_blocks", 33), ("height", 33),
                          ("actions_per_payment", 2), ("commitments", 68),
                          ("nullifiers", 66), ("fees", 33000)):
        if checked_uint(value[key]) != expected:
            raise MeasurementError("unexpected_final_result")
    if value["complete"] is not True:
        raise MeasurementError("result_not_complete")
    for key in ("logical_bytes", "segments", "tail_bytes"):
        if checked_uint(value[key]) != events[-1]["state"][key]:
            raise MeasurementError("result_capacity_disagrees")
    for key, field in (("wallet_records", "records_used"), ("wallet_bytes", "file_bytes")):
        if not isinstance(value[key], list) or len(value[key]) != 2:
            raise MeasurementError("invalid_result_wallets")
        if [checked_uint(x) for x in value[key]] != [w[field] for w in events[-1]["wallets"]]:
            raise MeasurementError("result_wallets_disagree")
    exact_keys(value["checks"], CHECKS)
    if any(item is not True for item in value["checks"].values()):
        raise MeasurementError("result_check_not_passed")
    timings = exact_keys(value["timings"], {"total_ms", "operations"})
    total = checked_uint(timings["total_ms"], 1_200_000)
    completed = [entry for entry in progress if entry["status"] == "completed"]
    if json.dumps(timings["operations"], sort_keys=True) != json.dumps(completed, sort_keys=True):
        raise MeasurementError("result_progress_disagrees")
    if total < sum(entry["duration_ms"] for entry in completed) or total < events[-1]["elapsed_ms"]:
        raise MeasurementError("inconsistent_total_duration")
    return value


@dataclass(frozen=True)
class ProcessIdentity:
    pid: int
    parent_pid: int
    creation_identity: str
    creation_identity_kind: str


@dataclass(frozen=True)
class MemorySample:
    identity: ProcessIdentity
    current_bytes: int
    os_lifetime_peak_bytes: int
    method: str

    def public(self) -> dict:
        return asdict(self)


def checked_memory(current: int, peak: int) -> tuple[int, int]:
    checked_uint(current, MAX_UINT64, 1)
    checked_uint(peak, MAX_UINT64, 1)
    if peak < current:
        raise MeasurementError("inconsistent_memory_counters")
    return current, peak


def check_budget(sample: MemorySample) -> None:
    # Keep the valid sample before applying this acceptance threshold.
    checked_memory(sample.current_bytes, sample.os_lifetime_peak_bytes)
    if max(sample.current_bytes, sample.os_lifetime_peak_bytes) > MEMORY_BUDGET_BYTES:
        raise MeasurementError("resident_memory_budget_exceeded")


def linux_identity(raw: str, expected_pid: int) -> ProcessIdentity:
    # comm may itself contain spaces and parentheses; field 3 starts only after
    # the last ')'. Never retain the comm value or the remaining stat fields.
    start = re.match(r"([0-9]+) \(", raw)
    end = raw.rfind(")")
    if start is None or end < start.end() or raw[end + 1:end + 2] != " ":
        raise MeasurementError("malformed_linux_stat")
    fields = raw[end + 2:].split()
    if len(fields) < 20 or len(fields[0]) != 1:
        raise MeasurementError("malformed_linux_stat")
    if fields[0] not in {"R", "S", "D", "T", "t", "K", "W", "P", "I"}:
        raise MeasurementError("process_not_live")
    if not re.fullmatch(r"[0-9]+", fields[1]) or not re.fullmatch(r"[0-9]+", fields[19]):
        raise MeasurementError("malformed_linux_stat")
    pid = checked_uint(int(start[1]), MAX_PID, 1)
    parent = checked_uint(int(fields[1]), MAX_PID)
    creation = checked_uint(int(fields[19]), MAX_UINT64, 1)
    if pid != expected_pid:
        raise MeasurementError("process_identity_changed")
    return ProcessIdentity(pid, parent, str(creation), "linux_proc_starttime_ticks")


def linux_memory(raw: str) -> tuple[int, int]:
    values = {}
    for line in raw.splitlines():
        name, separator, value = line.partition(":")
        if name not in {"VmRSS", "VmHWM"}:
            continue
        if name in values or not separator:
            raise MeasurementError("malformed_linux_memory")
        parsed = re.fullmatch(r"\s*([0-9]+)\s+kB\s*", value)
        if parsed is None:
            raise MeasurementError("malformed_linux_memory")
        values[name] = checked_uint(int(parsed[1]), MAX_UINT64 // 1024, 1) * 1024
    if set(values) != {"VmRSS", "VmHWM"}:
        raise MeasurementError("missing_linux_memory")
    return checked_memory(values["VmRSS"], values["VmHWM"])


class LinuxProcessProbe:
    def __init__(self, pid: int, parent_pid: int, proc_root: Path = Path("/proc")):
        self.fd = None
        self.pidfd = None
        self.pid = checked_uint(pid, MAX_PID, 1)
        checked_uint(parent_pid, MAX_PID, 1)
        try:
            # A pinned proc directory does not point at a replacement process
            # after exit/PID reuse. Dead proc descriptors instead fail to read.
            self.fd = os.open(proc_root / str(pid), os.O_RDONLY | os.O_DIRECTORY)
            self.identity = self._identity()
            if self.identity.parent_pid != parent_pid:
                raise MeasurementError("unexpected_parent_process")
            if proc_root == Path("/proc") and hasattr(os, "pidfd_open"):
                self.pidfd = os.pidfd_open(pid)
                self.verify()
        except (OSError, ValueError, MeasurementError) as exc:
            self.close()
            if isinstance(exc, MeasurementError):
                raise
            raise MeasurementError("process_open_failed") from exc

    def _read(self, name: str) -> str:
        try:
            fd = os.open(name, os.O_RDONLY, dir_fd=self.fd)
            with os.fdopen(fd, "r", encoding="utf-8") as stream:
                raw = stream.read(65537)
        except (OSError, ValueError, UnicodeError) as exc:
            raise MeasurementError("process_read_failed") from exc
        if len(raw) > 65536:
            raise MeasurementError("process_field_too_large")
        return raw

    def _identity(self) -> ProcessIdentity:
        return linux_identity(self._read("stat"), self.pid)

    def sample(self) -> MemorySample:
        if self.fd is None:
            raise MeasurementError("process_probe_closed")
        before = self._identity()
        current, peak = linux_memory(self._read("status"))
        after = self._identity()
        if before != self.identity or after != self.identity:
            raise MeasurementError("process_identity_changed")
        return MemorySample(self.identity, current, peak, "linux_proc_VmRSS_VmHWM")

    def verify(self) -> None:
        if self.fd is None or self._identity() != self.identity:
            raise MeasurementError("process_identity_changed")

    def terminate(self) -> None:
        if self.pidfd is None or not hasattr(signal, "pidfd_send_signal"):
            raise MeasurementError("safe_process_termination_unavailable")
        try:
            signal.pidfd_send_signal(self.pidfd, signal.SIGKILL)
        except ProcessLookupError:
            pass

    def is_alive(self) -> bool:
        if self.pidfd is None:
            raise MeasurementError("safe_process_liveness_unavailable")
        if select.select([self.pidfd], [], [], 0)[0]:
            return False
        self.verify()
        return True

    def close(self) -> None:
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None
        if self.pidfd is not None:
            os.close(self.pidfd)
            self.pidfd = None


class WindowsProcessProbe:
    def __init__(self, pid: int, parent_pid: int):
        from ctypes import wintypes

        self.handle = None
        self.pid = checked_uint(pid, MAX_PID, 1)
        checked_uint(parent_pid, MAX_PID, 1)
        self.api = ctypes.WinDLL("kernel32", use_last_error=True)
        pointer = ctypes.c_size_t

        class ProcessEntry(ctypes.Structure):
            _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                        ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", pointer),
                        ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                        ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", wintypes.LONG),
                        ("dwFlags", wintypes.DWORD), ("szExeFile", wintypes.WCHAR * 260)]

        class MemoryCounters(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + [
                (name, pointer) for name in ("PeakWorkingSetSize", "WorkingSetSize",
                                             "QuotaPeakPagedPoolUsage", "QuotaPagedPoolUsage",
                                             "QuotaPeakNonPagedPoolUsage", "QuotaNonPagedPoolUsage",
                                             "PagefileUsage", "PeakPagefileUsage")]

        self.ProcessEntry = ProcessEntry
        self.MemoryCounters = MemoryCounters
        self.FILETIME = wintypes.FILETIME
        signatures = {
            "OpenProcess": ([wintypes.DWORD, wintypes.BOOL, wintypes.DWORD], wintypes.HANDLE),
            "CloseHandle": ([wintypes.HANDLE], wintypes.BOOL),
            "WaitForSingleObject": ([wintypes.HANDLE, wintypes.DWORD], wintypes.DWORD),
            "TerminateProcess": ([wintypes.HANDLE, wintypes.UINT], wintypes.BOOL),
            "GetProcessTimes": ([wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4, wintypes.BOOL),
            "K32GetProcessMemoryInfo": ([wintypes.HANDLE, ctypes.POINTER(MemoryCounters), wintypes.DWORD], wintypes.BOOL),
            "CreateToolhelp32Snapshot": ([wintypes.DWORD, wintypes.DWORD], wintypes.HANDLE),
            "Process32FirstW": ([wintypes.HANDLE, ctypes.POINTER(ProcessEntry)], wintypes.BOOL),
            "Process32NextW": ([wintypes.HANDLE, ctypes.POINTER(ProcessEntry)], wintypes.BOOL),
        }
        try:
            for name, (arguments, result) in signatures.items():
                function = getattr(self.api, name)
                function.argtypes, function.restype = arguments, result
            # Query plus SYNCHRONIZE permits a real liveness check on the retained
            # handle. Exit code 259 alone cannot prove that a process is alive.
            # TERMINATE is used only to clean up this test's verified children
            # on failure. A retained handle cannot target a reused PID.
            self.handle = self.api.OpenProcess(0x1000 | 0x100000 | 0x1, False, pid)
            if not self.handle:
                raise MeasurementError("process_open_failed")
            creation = self._creation()
            actual_parent = self._parent()
            if actual_parent != parent_pid:
                raise MeasurementError("unexpected_parent_process")
            if self._creation() != creation:
                raise MeasurementError("process_identity_changed")
            self.identity = ProcessIdentity(pid, actual_parent, str(creation),
                                            "windows_creation_filetime_100ns")
        except (OSError, AttributeError, MeasurementError) as exc:
            self.close()
            if isinstance(exc, MeasurementError):
                raise
            raise MeasurementError("windows_process_api_failed") from exc

    def _live(self) -> None:
        # WAIT_TIMEOUT means the process object is not signalled (still live).
        if not self.handle or self.api.WaitForSingleObject(self.handle, 0) != 0x102:
            raise MeasurementError("process_not_live")

    def _creation(self) -> int:
        self._live()
        values = [self.FILETIME() for _ in range(4)]
        if not self.api.GetProcessTimes(self.handle, *(ctypes.byref(x) for x in values)):
            raise MeasurementError("process_identity_read_failed")
        creation = (values[0].dwHighDateTime << 32) | values[0].dwLowDateTime
        self._live()
        return checked_uint(creation, MAX_UINT64, 1)

    def _parent(self) -> int:
        snapshot = self.api.CreateToolhelp32Snapshot(0x2, 0)
        if snapshot == ctypes.c_void_p(-1).value or not snapshot:
            raise MeasurementError("process_parent_read_failed")
        try:
            entry = self.ProcessEntry()
            entry.dwSize = ctypes.sizeof(entry)
            if not self.api.Process32FirstW(snapshot, ctypes.byref(entry)):
                raise MeasurementError("process_parent_read_failed")
            while True:
                if entry.th32ProcessID == self.pid:
                    return checked_uint(entry.th32ParentProcessID, MAX_PID, 1)
                if not self.api.Process32NextW(snapshot, ctypes.byref(entry)):
                    raise MeasurementError("process_parent_not_found")
        finally:
            if not self.api.CloseHandle(snapshot):
                raise MeasurementError("process_handle_close_failed")

    def sample(self) -> MemorySample:
        before = self._creation()
        counters = self.MemoryCounters()
        counters.cb = ctypes.sizeof(counters)
        if not self.api.K32GetProcessMemoryInfo(self.handle, ctypes.byref(counters), counters.cb):
            raise MeasurementError("process_memory_read_failed")
        after = self._creation()
        if str(before) != self.identity.creation_identity or after != before:
            raise MeasurementError("process_identity_changed")
        current, peak = checked_memory(counters.WorkingSetSize, counters.PeakWorkingSetSize)
        return MemorySample(self.identity, current, peak,
                            "windows_GetProcessMemoryInfo_WorkingSetSize_PeakWorkingSetSize")

    def verify(self) -> None:
        if str(self._creation()) != self.identity.creation_identity:
            raise MeasurementError("process_identity_changed")

    def terminate(self) -> None:
        if self.api.WaitForSingleObject(self.handle, 0) == 0:
            return
        self.verify()
        if not self.api.TerminateProcess(self.handle, 1):
            raise MeasurementError("process_termination_failed")

    def is_alive(self) -> bool:
        status = self.api.WaitForSingleObject(self.handle, 0)
        if status == 0:
            return False
        if status != 0x102:
            raise MeasurementError("process_liveness_failed")
        self.verify()
        return True

    def close(self) -> None:
        if self.handle:
            handle, self.handle = self.handle, None
            if not self.api.CloseHandle(handle):
                raise MeasurementError("process_handle_close_failed")


def open_process(pid: int, parent_pid: int):
    if sys.platform == "linux":
        return LinuxProcessProbe(pid, parent_pid)
    if sys.platform == "win32":
        return WindowsProcessProbe(pid, parent_pid)
    raise MeasurementError("unsupported_memory_platform")


def read_public_json(path: Path, maximum: int) -> tuple[dict, str]:
    try:
        before = path.lstat()
        if not stat.S_ISREG(before.st_mode) or before.st_size > maximum:
            raise MeasurementError("invalid_protocol_file")
        with path.open("rb") as stream:
            actual = os.fstat(stream.fileno())
            if not os.path.samestat(before, actual):
                raise MeasurementError("protocol_file_changed")
            raw = stream.read(maximum + 1)
        after = path.lstat()
        if not os.path.samestat(before, after) or after.st_size != before.st_size:
            raise MeasurementError("protocol_file_changed")
    except OSError as exc:
        raise MeasurementError("protocol_file_read_failed") from exc
    return decode_json(raw, maximum), hashlib.sha256(raw).hexdigest()


class EvidenceFile:
    """Own one newly created public report; never overwrite a preexisting path."""
    def __init__(self, path: Path, evidence: dict):
        self.path = path
        self.identity = None
        try:
            with path.open("x", encoding="utf-8", newline="\n") as output:
                output.write(json.dumps(evidence, sort_keys=True, indent=2) + "\n")
                output.flush()
                os.fsync(output.fileno())
                opened_identity = os.fstat(output.fileno())
            # Windows may finalize last-write timestamps only when the write
            # handle closes. Pin the closed file, not a pre-close timestamp.
            self.identity = path.lstat()
            if not os.path.samestat(opened_identity, self.identity):
                raise MeasurementError("output_identity_changed")
        except FileExistsError as exc:
            raise MeasurementError("output_already_exists") from exc
        except OSError as exc:
            raise MeasurementError("evidence_save_failed") from exc

    def save(self, evidence: dict) -> None:
        temporary = None
        try:
            actual = self.path.lstat()
            if (self.identity is None or not os.path.samestat(actual, self.identity)
                    or actual.st_size != self.identity.st_size
                    or actual.st_mtime_ns != self.identity.st_mtime_ns):
                raise MeasurementError("output_identity_changed")
            fd, name = tempfile.mkstemp(prefix=self.path.name + ".", suffix=".tmp", dir=self.path.parent)
            temporary = Path(name)
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as output:
                output.write(json.dumps(evidence, sort_keys=True, indent=2) + "\n")
                output.flush()
                os.fsync(output.fileno())
                opened_identity = os.fstat(output.fileno())
            identity = temporary.lstat()
            if not os.path.samestat(opened_identity, identity):
                raise MeasurementError("output_identity_changed")
            os.replace(temporary, self.path)
            temporary = None
            self.identity = identity
        except OSError as exc:
            raise MeasurementError("evidence_save_failed") from exc
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)


def fixed_command(arguments: list[str], root: Path) -> str:
    try:
        result = subprocess.run(arguments, cwd=root, stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                timeout=15, check=True)
        value = result.stdout.decode("ascii").strip()
    except (OSError, UnicodeError, subprocess.SubprocessError) as exc:
        raise MeasurementError("metadata_command_failed") from exc
    if len(value) > 512 or any(ord(character) < 32 for character in value):
        raise MeasurementError("invalid_metadata_output")
    return value


def collect_metadata(root: Path, source_head: str) -> dict:
    if not re.fullmatch(r"[0-9a-f]{40}", source_head):
        raise MeasurementError("invalid_source_head")
    checkout = fixed_command(["git", "rev-parse", "HEAD"], root)
    checkout_tree = fixed_command(["git", "rev-parse", "HEAD^{tree}"], root)
    source = fixed_command(["git", "rev-parse", "--verify", source_head + "^{commit}"], root)
    source_tree = fixed_command(["git", "rev-parse", source_head + "^{tree}"], root)
    if any(re.fullmatch(r"[0-9a-f]{40}", item) is None
           for item in (checkout, checkout_tree, source, source_tree)):
        raise MeasurementError("invalid_git_identity")
    if source != source_head or checkout_tree != source_tree:
        raise MeasurementError("checkout_source_tree_mismatch")
    if fixed_command(["git", "status", "--porcelain", "--untracked-files=no"], root):
        raise MeasurementError("tracked_source_changed")
    versions = {
        "go": fixed_command(["go", "version"], root),
        "rustc": fixed_command(["rustc", "+1.98.1", "--version"], root),
        "cargo": fixed_command(["cargo", "+1.98.1", "--version"], root),
        "python": platform.python_version(),
    }
    if not versions["go"].startswith("go version go1.27.1 ") or not versions["rustc"].startswith("rustc 1.98.1 "):
        raise MeasurementError("unexpected_toolchain_version")
    return {"source_head": source, "source_tree": source_tree, "checkout_commit": checkout,
            "checkout_tree": checkout_tree, "toolchains": versions}


def executable_identity(path: Path) -> str:
    try:
        if not path.is_absolute() or not stat.S_ISREG(path.lstat().st_mode):
            raise MeasurementError("invalid_executable")
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1 << 20), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError as exc:
        raise MeasurementError("executable_read_failed") from exc


class ProtocolCollector:
    def __init__(self, directory: Path, evidence: dict, writer: EvidenceFile,
                 coordinator_pid: int, probe_factory=open_process):
        self.directory = directory
        self.evidence = evidence
        self.writer = writer
        self.coordinator_pid = coordinator_pid
        self.probe_factory = probe_factory
        self.parent = probe_factory(coordinator_pid, os.getpid())
        self.probes = {}
        self.identities = {}
        self.hashes = {}
        self.pending = None
        self.result_seen = False

    def save(self) -> None:
        self.evidence["unfinished_operation"] = self.pending
        self.evidence["last_confirmed_committed_blocks"] = max(
            (entry["committed_blocks"] for entry in self.evidence["progress"]), default=None)
        self.evidence["commit_outcome_uncertain"] = bool(
            self.pending is not None and self.pending["operation"] == "worker_commit")
        self.evidence["cleanup"]["registered_processes"] = len(self.probes)
        self.evidence["cleanup"]["initial_roles_registered"] = all(
            (role, 1) in self.probes for role in ("worker", "scenario"))
        self.writer.save(self.evidence)

    def acknowledge(self, seq: int, error_code: str | None = None) -> None:
        result = {"schema_version": 1, "seq": seq, "ok": error_code is None}
        if error_code is not None:
            result["error_code"] = error_code
        path = self.directory / f"ack-{seq:02d}.json"
        temporary = self.directory / f"ack-{seq:02d}.tmp"
        try:
            with temporary.open("x", encoding="utf-8") as output:
                json.dump(result, output, sort_keys=True)
                output.flush()
                os.fsync(output.fileno())
            if path.exists():
                raise MeasurementError("ack_already_exists")
            temporary.rename(path)
        except OSError as exc:
            raise MeasurementError("ack_save_failed") from exc

    def progress(self) -> None:
        while len(self.evidence["progress"]) < MAX_PROGRESS_RECORDS:
            seq = len(self.evidence["progress"]) + 1
            path = self.directory / f"progress-{seq:04d}.json"
            if not path.exists():
                break
            value, digest = read_public_json(path, MAX_PROGRESS_BYTES)
            checked_progress(value, seq, self.pending)
            self.evidence["progress"].append(value)
            self.hashes[path.name] = digest
            self.pending = value if value["status"] == "started" else None
            self.save()

    def _sample(self, process: dict) -> MemorySample:
        self.parent.verify()
        key = (process["role"], process["generation"])
        if key not in self.probes:
            probe = self.probe_factory(process["pid"], self.coordinator_pid)
            try:
                identity = probe.identity
                parent = self.parent.identity
                if (identity.creation_identity_kind != parent.creation_identity_kind
                        or int(identity.creation_identity) < int(parent.creation_identity)
                        or identity in self.identities.values()):
                    raise MeasurementError("process_creation_identity_invalid")
                self.probes[key] = probe
                self.identities[key] = identity
            except BaseException:
                probe.close()
                raise
        elif self.identities[key].pid != process["pid"]:
            raise MeasurementError("process_generation_changed_pid")
        sample = self.probes[key].sample()
        if sample.identity != self.identities[key]:
            raise MeasurementError("process_identity_changed")
        self.parent.verify()
        return sample

    def events(self) -> None:
        seq = len(self.evidence["events"]) + 1
        if seq > len(PHASES):
            return
        path = self.directory / f"event-{seq:02d}.json"
        if not path.exists():
            return
        try:
            value, digest = read_public_json(path, MAX_EVENT_BYTES)
            checked_event(value, seq)
            previous = self.evidence["events"][-1] if self.evidence["events"] else None
            if previous is not None:
                if value["elapsed_ms"] < previous["elapsed_ms"]:
                    raise MeasurementError("checkpoint_clock_reversed")
                if value["height"] == previous["height"] and value["state"] != previous["state"]:
                    raise MeasurementError("checkpoint_recovery_changed_state")
                if value["height"] > previous["height"] and value["state"]["logical_bytes"] <= previous["state"]["logical_bytes"]:
                    raise MeasurementError("checkpoint_history_did_not_grow")
            # A validated checkpoint remains available if either process sample
            # subsequently fails. It is explicitly marked measurement_complete.
            self.evidence["events"].append(value)
            self.hashes[path.name] = digest
            recorded = {"seq": seq, "phase": value["phase"], "measurement_complete": False, "samples": []}
            self.evidence["memory_checkpoints"].append(recorded)
            self.save()
            for process in value["processes"]:
                sample = self._sample(process)
                public = sample.public()
                public.update({"role": process["role"], "generation": process["generation"]})
                recorded["samples"].append(public)
                self.save()
                check_budget(sample)
            recorded["measurement_complete"] = True
            self.save()
            self.acknowledge(seq)
        except MeasurementError as exc:
            try:
                self.acknowledge(seq, str(exc))
            except MeasurementError:
                pass
            raise

    def check_names(self, final: bool = False) -> None:
        try:
            names = {item.name for item in self.directory.iterdir()}
        except OSError as exc:
            raise MeasurementError("protocol_directory_read_failed") from exc
        for prefix, digits, limit, collected in (("event", 2, 9, len(self.evidence["events"])),
                                                 ("progress", 4, MAX_PROGRESS_RECORDS, len(self.evidence["progress"]))):
            sequence = []
            for name in names:
                if not name.startswith(prefix + "-") or not name.endswith(".json"):
                    continue
                match = re.fullmatch(prefix + r"-([0-9]{" + str(digits) + r"})\.json", name)
                if match is None or not 1 <= int(match[1]) <= limit:
                    raise MeasurementError("invalid_protocol_filename")
                sequence.append(int(match[1]))
            if sequence and sorted(sequence) != list(range(1, max(sequence) + 1)):
                raise MeasurementError("protocol_sequence_gap")
            if final and len(sequence) != collected:
                raise MeasurementError("uncollected_protocol_record")
        if final:
            for name, expected in self.hashes.items():
                maximum = MAX_EVENT_BYTES if name.startswith("event-") else MAX_PROGRESS_BYTES
                _value, actual = read_public_json(self.directory / name, maximum)
                if actual != expected:
                    raise MeasurementError("immutable_protocol_record_changed")

    def finish(self) -> None:
        self.progress()
        self.check_names(final=True)
        if len(self.evidence["memory_checkpoints"]) != 9 or any(
                item["measurement_complete"] is not True for item in self.evidence["memory_checkpoints"]):
            raise MeasurementError("incomplete_memory_measurement")
        value, digest = read_public_json(self.directory / "result.json", 1 << 20)
        checked_result(value, self.evidence["events"], self.evidence["progress"])
        if any(probe.is_alive() for probe in self.probes.values()):
            raise MeasurementError("child_still_alive_after_test")
        self.evidence["result"] = value
        self.evidence["result_sha256"] = digest
        self.result_seen = True
        self.save()

    def close(self) -> None:
        errors = []
        for probe in [*self.probes.values(), self.parent]:
            try:
                probe.close()
            except (OSError, MeasurementError):
                errors.append("process_handle_close_failed")
        if errors:
            raise MeasurementError(errors[0])


def initial_evidence() -> dict:
    return {
        "schema_version": 1, "scope": "fixed_32_plus_1_no_funds_payment_resource_baseline",
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "running", "platform": sys.platform,
        "machine": platform.machine(), "metadata": None, "executables_sha256": {},
        "targets": {"paid_blocks_before_recovery": 32, "paid_blocks_final": 33,
                    "resident_lifetime_peak_budget_bytes_per_process": MEMORY_BUDGET_BYTES,
                    "roles": ["worker", "scenario"], "worker_generations": 2,
                    "go_test_timeout_seconds": 1200, "supervisor_timeout_seconds": 1230,
                    "handshake_timeout_seconds": 15, "worker_start_timeout_seconds": 60,
                    "worker_request_timeout_seconds": 60, "scenario_response_timeout_seconds": 90},
        "measurement_limits": [
            "OS reported resident or working set; not private heap or total machine memory",
            "Linux RSS accounting can be approximate; no cross-platform ratio claim",
            "OS lifetime peak is per process generation, never a phase peak",
            "Python supervisor and Go coordinator excluded from measured roles",
            "scenario includes prover, authorization cache, history, both wallets and Argon2",
            "no memory allocation enforcement; final cleanup follows the observation window",
            "no production throughput, network finality, cold disk or full capacity claim",
        ],
        "progress": [], "unfinished_operation": None, "events": [],
        "last_confirmed_committed_blocks": None, "commit_outcome_uncertain": False,
        "memory_checkpoints": [], "result": None, "go_exit_code": None, "failures": [],
        "cleanup": {"registered_processes": 0, "registered_children_exit_confirmed": False,
                    "initial_roles_registered": False,
                    "precheckpoint_child_tree_cleanup_confirmed": False,
                    "scope": "retained_identities_and_normal_Go_cleanup_not_a_process_sandbox"},
    }


def stop_test(process: subprocess.Popen, collector: ProtocolCollector | None) -> None:
    """Stop only this supervised test's verified processes after a failure."""
    deadline = getattr(process, "_zevune_cleanup_deadline", None)
    if not isinstance(deadline, (int, float)):
        deadline = time.monotonic() + 30
        process._zevune_cleanup_deadline = deadline

    def remaining(maximum):
        return max(0, min(maximum, deadline - time.monotonic()))

    if process.poll() is None:
        # Give Go's normal failure cleanup a short opportunity first, including
        # a negative ACK. A hanging test still has a fixed outer bound.
        try:
            process.wait(timeout=remaining(2))
        except subprocess.TimeoutExpired:
            pass
    if collector is not None:
        for probe in collector.probes.values():
            try:
                probe.terminate()
            except (OSError, MeasurementError):
                collector.evidence["failures"].append({"error_code": "verified_child_cleanup_failed"})
    if sys.platform == "linux":
        if process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
    elif sys.platform == "win32":
        # taskkill's /T is scoped to the directly spawned live coordinator, not
        # an executable-name search. The retained probes still protect samples.
        if process.poll() is None:
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                           stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, timeout=remaining(10), check=False)
    if process.poll() is None:
        process.kill()
    process.wait(timeout=remaining(10))
    if collector is not None:
        children = list(collector.probes.values())
        collector.evidence["cleanup"]["registered_processes"] = len(children)
        # Termination requests can be asynchronous on Windows. Confirm exit
        # only against retained objects, with the remainder of the fixed bound.
        until = time.monotonic() + remaining(5)
        while children and any(probe.is_alive() for probe in children):
            if time.monotonic() >= until:
                collector.evidence["failures"].append({"error_code": "verified_child_exit_not_confirmed"})
                break
            time.sleep(0.02)
        collector.evidence["cleanup"]["registered_children_exit_confirmed"] = bool(
            children and all(not probe.is_alive() for probe in children))


def run(test_executable: Path, worker: Path, scenario: Path, output: Path) -> int:
    evidence = initial_evidence()
    writer = EvidenceFile(output, evidence)
    collector = None
    process = None
    started = time.monotonic()
    process_started = None
    root = Path(__file__).resolve().parents[1]
    try:
        evidence["metadata"] = collect_metadata(root, os.environ.get("ZEVUNE_RESOURCE_SOURCE_HEAD", ""))
        for role, path in (("go_test", test_executable), ("worker", worker), ("scenario", scenario)):
            evidence["executables_sha256"][role] = executable_identity(path)
        writer.save(evidence)
        with tempfile.TemporaryDirectory(prefix="zevune-payment-resource-") as temporary:
            directory = Path(temporary)
            environment = os.environ.copy()
            environment.update({"ZEVUNE_RESOURCE_HANDSHAKE_DIR": str(directory),
                                "ZEVUNE_POOL_WORKER": str(worker),
                                "ZEVUNE_FUNDED_SCENARIO": str(scenario), "RAYON_NUM_THREADS": "2"})
            process = subprocess.Popen([str(test_executable),
                                        "-test.run=^TestActivePaymentResources32AndRecovery$",
                                        "-test.v", "-test.timeout=20m"], cwd=root, env=environment,
                                       stdin=subprocess.DEVNULL, start_new_session=sys.platform == "linux")
            process_started = time.monotonic()
            # Every retry/finally cleanup shares the original 1230-second
            # deadline; a late failure never buys a second cleanup allowance.
            process._zevune_cleanup_deadline = started + SUPERVISOR_TIMEOUT_SECONDS
            try:
                collector = ProtocolCollector(directory, evidence, writer, process.pid)
                while True:
                    collector.progress()
                    collector.events()
                    collector.check_names()
                    result = process.poll()
                    if result is not None:
                        evidence["go_exit_code"] = result
                        collector.progress()
                        collector.check_names(final=True)
                        if result != 0:
                            raise MeasurementError("go_test_failed")
                        collector.finish()
                        break
                    # The workload has 20 minutes; bounded cleanup has the
                    # remaining 30 seconds, rather than starting another wait
                    # after an already elapsed 1230-second supervision window.
                    if time.monotonic() - started > SUPERVISOR_TIMEOUT_SECONDS - 30:
                        raise MeasurementError("supervisor_timeout")
                    time.sleep(0.02)
            except BaseException:
                # No raw exception or Go stdout is copied into the public JSON.
                if collector is not None:
                    try:
                        collector.progress()
                    except MeasurementError:
                        pass
                try:
                    stop_test(process, collector)
                except (OSError, MeasurementError, subprocess.SubprocessError):
                    evidence["failures"].append({"error_code": "coordinator_cleanup_failed"})
                evidence["go_exit_code"] = process.returncode
                if collector is not None:
                    try:
                        collector.progress()
                    except MeasurementError:
                        pass
                raise
        if fixed_command(["git", "status", "--porcelain", "--untracked-files=no"], root):
            raise MeasurementError("tracked_source_changed")
        evidence["status"] = "passed"
        evidence["cleanup"]["registered_processes"] = len(collector.probes)
        evidence["cleanup"]["registered_children_exit_confirmed"] = True
    except (Exception, KeyboardInterrupt) as exc:
        code = str(exc) if isinstance(exc, MeasurementError) else (
            "supervisor_interrupted" if isinstance(exc, KeyboardInterrupt) else "supervisor_operation_failed")
        evidence["status"] = "failed"
        evidence["failures"].append({"error_code": code})
    finally:
        if process is not None and process.poll() is None:
            try:
                stop_test(process, collector)
            except (OSError, MeasurementError, subprocess.SubprocessError):
                evidence["status"] = "failed"
                evidence["failures"].append({"error_code": "coordinator_cleanup_failed"})
            evidence["go_exit_code"] = process.returncode
        if collector is not None:
            evidence["unfinished_operation"] = collector.pending
            evidence["commit_outcome_uncertain"] = bool(
                collector.pending is not None and collector.pending["operation"] == "worker_commit")
            try:
                collector.close()
            except MeasurementError as exc:
                evidence["status"] = "failed"
                evidence["failures"].append({"error_code": str(exc)})
        evidence["supervisor_elapsed_ms"] = int((time.monotonic() - started) * 1000)
        if process_started is not None:
            evidence["supervised_process_elapsed_ms"] = int((time.monotonic() - process_started) * 1000)
        evidence["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
        writer.save(evidence)
    return 0 if evidence["status"] == "passed" else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--test-executable", type=Path, required=True)
    parser.add_argument("--worker", type=Path, required=True)
    parser.add_argument("--scenario", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    try:
        code = run(arguments.test_executable.absolute(), arguments.worker.absolute(),
                   arguments.scenario.absolute(), arguments.output.absolute())
    except MeasurementError as exc:
        print("PAYMENT_RESOURCE_RESULT failed error_code=" + str(exc))
        return 1
    print("PAYMENT_RESOURCE_RESULT " + ("passed" if code == 0 else "failed"))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
