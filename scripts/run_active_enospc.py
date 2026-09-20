#!/usr/bin/env python3
"""Run an explicit Linux tmpfs ENOSPC suite; never compile or fill a host disk.

The ordinary runner owns compilation. Privilege is used only in a fresh mount
and PID namespace to mount, supervise and normally unmount a bounded tmpfs.
The tracer and already-built test binary run with the runner's reduced identity.
Raw subprocess output stays bounded in memory and is never printed or uploaded.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import selectors
import signal
import shutil
import stat
import subprocess
import sys
import tempfile
import time

import wallet_prepare_evidence

CASES = {
    "active_tail_enospc_preserves_state_and_recovers": "source/00000000.journal",
    "active_new_segment_enospc_preserves_state_and_recovers": "source/00000001.journal",
}
WALLET_CASES = {
    "wallet_sync_enospc_preserves_outbox_and_recovers": "source/wallet.journal",
    "wallet_compact_enospc_preserves_source_and_recovers": "compacted/wallet.journal",
}
SUITE_CASES = {"active": CASES, "wallet": WALLET_CASES, "wallet_prepare": wallet_prepare_evidence.CASES}
SUITE_TEST_FILES = {"active": "active_enospc.rs", "wallet": "wallet_enospc.rs",
                    "wallet_prepare": "wallet_prepare_enospc.rs"}
TMPFS_BYTES = 8 * 1024 * 1024
TMPFS_INODES = 256
CASE_SECONDS = 180
NAMESPACE_SECONDS = 420
OUTER_SECONDS = 450
WATCHDOG_SECONDS = 430
HEX = re.compile(r"[0-9a-f]{64}\Z")
OID = re.compile(r"[0-9a-f]{40}\Z")
TRACE_OPTIONS = ["-f", "-qq", "-I", "2", "-e", "trace=write,writev,pwrite64,fsync,fdatasync",
                 "-e", "raw=write,writev,pwrite64", "-e", "status=failed", "-e", "signal=none"]
BOOL_FIELDS = {"commit_storage", "store_unavailable", "reopen_rejected",
               "committed_prefix_preserved", "no_new_summary_published", "backup_unchanged",
               "rejected_source_unchanged", "restored_replay", "continuation_done"}
INTEGER_FIELDS = {"target_dev", "target_ino", "target_nlink", "before_len", "after_len",
                  "frame_len", "changed_suffix_len", "checkpoint_height", "filler_errno", "filler_bytes"}
RECEIPT_FIELDS = BOOL_FIELDS | INTEGER_FIELDS | {
    "schema_version", "case", "profile", "filesystem", "target_rel", "before_sha256",
    "after_sha256", "checkpoint_apphash", "checkpoint_pin_sha256"}
WALLET_HEADER_BYTES = 72
WALLET_RECORD_BYTES = 32948
WALLET_BOOL_FIELDS = {"wallet_io", "reopen_rejected", "source_prefix_preserved", "backup_unchanged",
                      "rejected_target_unchanged", "exact_pending_recovered", "continuation_done",
                      "retained_receipt_unchanged", "new_target_receipt_verified"}
WALLET_INTEGER_FIELDS = {"target_dev", "target_ino", "target_nlink", "before_len", "after_len",
                         "frame_len", "changed_suffix_len", "receipt_generation", "recovered_receipt_generation",
                         "backup_len", "filler_errno", "filler_bytes"}
WALLET_RECEIPT_FIELDS = WALLET_BOOL_FIELDS | WALLET_INTEGER_FIELDS | {
    "schema_version", "case", "profile", "filesystem", "target_rel", "before_sha256", "after_sha256",
    "receipt_pin_sha256", "recovered_receipt_pin_sha256", "backup_sha256", "store_unavailable",
    "source_retired_after_success"}


def suite_cases(suite: str) -> dict:
    if suite not in SUITE_CASES:
        raise ValueError("unsupported_enospc_suite")
    return SUITE_CASES[suite]


def utc() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def failure_code(error: Exception) -> str:
    # Only our fixed, lowercase diagnostic identifiers may enter evidence.
    # OS and decoder messages may contain paths or input bytes.
    if type(error) is ValueError and re.fullmatch(r"[a-z_]{1,80}", str(error)):
        return str(error)
    return type(error).__name__


def source_identity() -> dict:
    repository = Path(__file__).resolve().parents[1]
    def git(expression: str) -> str:
        value = subprocess.check_output(["git", "--no-replace-objects", "rev-parse", expression],
                                        cwd=repository, text=True, timeout=10).strip()
        if not OID.fullmatch(value):
            raise ValueError("invalid_source_identity")
        return value
    checkout = git("HEAD")
    source = os.environ.get("ZEVUNE_ENOSPC_SOURCE_HEAD", checkout)
    if not OID.fullmatch(source):
        raise ValueError("invalid_source_head")
    return {"source_head": source, "checkout_commit": checkout, "checkout_tree": git("HEAD^{tree}")}


def public_summary(report: dict) -> dict:
    """Only fixed labels, digests, counters and booleans may enter CI logs."""
    summary = {"kind": report["kind"], "completed": report.get("completed") is True,
               "cleanup_unknown": report.get("cleanup_unknown", True) is True,
               "namespace_exit_confirmed": report.get("namespace_exit_confirmed") is True,
               "control_directory_retained": report.get("control_directory_retained") is True}
    for field in ("source_head", "checkout_commit", "checkout_tree"):
        value = report.get(field)
        if isinstance(value, str) and OID.fullmatch(value):
            summary[field] = value
    kernel = report.get("kernel_release")
    if isinstance(kernel, str) and re.fullmatch(r"[A-Za-z0-9._+\-]{1,128}", kernel):
        summary["kernel_release"] = kernel
    version = report.get("strace_version")
    if isinstance(version, str) and re.fullmatch(r"strace -- version [0-9]+\.[0-9]+(?:\.[0-9]+)?", version):
        summary["strace_version"] = version
    if report["kind"] == "root_watchdog_probe":
        for field in ("root_euid", "watchdog_exit", "namespace_members_after", "watchdog_timeout_seconds", "kill_after_seconds"):
            if type(report.get(field)) is int:
                summary[field] = report[field]
        summary["payload_ignored_sigterm"] = report.get("payload_ignored_sigterm") is True
    else:
        suite = report.get("suite")
        cases = SUITE_CASES.get(suite, {}) if isinstance(suite, str) else {}
        if isinstance(suite, str) and suite in SUITE_CASES:
            summary["suite"] = suite
        summary["cases"] = []
        for case in report.get("cases", []):
            name = case.get("case")
            if name not in cases or case.get("target_rel") != cases[name]:
                continue
            item = {"case": name, "target_rel": cases[name], "completed": case.get("completed") is True,
                    "ordinary_unmount_succeeded": case.get("ordinary_unmount_succeeded") is True}
            for field in ("failure_stage", "failure"):
                value = case.get(field)
                if isinstance(value, str) and re.fullmatch(r"[A-Za-z_]{1,80}", value):
                    item[field] = value
            for section, fields in (("receipt", ("filler_errno", "filler_bytes", "before_len", "after_len")),
                                    ("syscall_evidence", ("write_enospc_count",)),
                                    ("mount", ("total_blocks", "free_blocks_before", "available_blocks_before", "free_inodes_before",
                                               "free_blocks_after", "available_blocks_after", "free_inodes_after"))):
                for field in fields:
                    value = case.get(section, {}).get(field)
                    if type(value) is int and 0 <= value < 2**64:
                        item[field] = value
            digest = case.get("syscall_evidence", {}).get("trace_sha256")
            if isinstance(digest, str) and HEX.fullmatch(digest):
                item["trace_sha256"] = digest
            if item.get("write_enospc_count", 0) > 0:
                item["journal_errno"] = 28
            counts = case.get("syscall_evidence", {}).get("syscall_counts", {})
            item["syscall_counts"] = {name: counts[name] for name in ("write", "writev", "pwrite64", "fsync", "fdatasync")
                                      if type(counts.get(name)) is int and 0 <= counts[name] <= 65536}
            location = case.get("rust_test_location", {})
            if location.get("file") == SUITE_TEST_FILES[suite] and type(location.get("line")) is int:
                item["rust_test_line"] = location["line"]
            summary["cases"].append(item)
    for field in ("failure", "failure_stage", "controller_failure"):
        value = report.get(field)
        if isinstance(value, str) and re.fullmatch(r"[A-Za-z_]{1,80}", value):
            summary[field] = value
    return summary


def unique(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_json_field")
        result[key] = value
    return result


def file_identity(path: Path, maximum: int, *, capture: bool = False) -> tuple[os.stat_result, str, bytes]:
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or not 0 <= before.st_size <= maximum:
        raise ValueError("nonregular_or_oversized_input")
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    digest, contents, total = hashlib.sha256(), bytearray(), 0
    with os.fdopen(descriptor, "rb") as handle:
        if not os.path.samestat(before, os.fstat(handle.fileno())):
            raise ValueError("input_identity_changed")
        while chunk := handle.read(min(65536, maximum - total + 1)):
            total += len(chunk)
            if total > maximum:
                raise ValueError("input_grew_past_limit")
            digest.update(chunk)
            if capture:
                contents.extend(chunk)
        after = os.fstat(handle.fileno())
    current = path.lstat()
    if (not os.path.samestat(before, current) or before.st_size != total
            or after.st_size != total or before.st_mtime_ns != after.st_mtime_ns):
        raise ValueError("input_changed_during_read")
    return before, digest.hexdigest(), bytes(contents)


def signal_group(process: subprocess.Popen, signum: int) -> bool:
    try:
        os.killpg(process.pid, signum)
    except ProcessLookupError:
        pass
    except PermissionError:
        return False
    return True


def exited_without_reaping(process: subprocess.Popen) -> bool:
    # Retain the leader's PID until all required group signals are finished.
    # Popen.poll() reaps it and permits a stale PGID to be reused by another job.
    return os.waitid(os.P_PID, process.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT) is not None


def run_bounded(command: list[str], *, timeout: float, env: dict | None = None,
                cwd: Path | None = None, trace_pipe: tuple[int, int] | None = None,
                privileged_watchdog: bool = False) -> dict:
    """Drain bounded pipes and reap a whole process group within fixed deadlines."""
    buffers = {"stdout": bytearray(), "stderr": bytearray(), "trace": bytearray()}
    limits = {"stdout": 64 * 1024, "stderr": 16 * 1024, "trace": 64 * 1024}
    process = None
    selector = selectors.DefaultSelector()
    descriptors = []
    timed_out = overflow = leaked_output = signal_denied = reap_started = False
    try:
        process = subprocess.Popen(command, cwd=cwd, env=env, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, bufsize=0, start_new_session=True,
                                   pass_fds=() if trace_pipe is None else (trace_pipe[1],))
        if trace_pipe is not None:
            os.close(trace_pipe[1])
            descriptors.append(trace_pipe[0])
        streams = [(process.stdout.fileno(), "stdout"), (process.stderr.fileno(), "stderr")]
        if trace_pipe is not None:
            streams.append((trace_pipe[0], "trace"))
        for descriptor, name in streams:
            os.set_blocking(descriptor, False)
            selector.register(descriptor, selectors.EVENT_READ, name)
        deadline = time.monotonic() + timeout
        stopping = exited = None
        killed = False
        while True:
            now = time.monotonic()
            if exited is None and exited_without_reaping(process):
                exited = now
            if exited is not None and not selector.get_map():
                break
            if now >= deadline:
                timed_out = True
            if exited is not None and selector.get_map() and now - exited >= 3:
                leaked_output = True
            if (timed_out or overflow or leaked_output) and stopping is None:
                stopping = now
                signal_denied |= not signal_group(process, signal.SIGTERM)
            if stopping is not None and now - stopping >= 2 and not killed:
                signal_denied |= not signal_group(process, signal.SIGKILL)
                killed = True
            if stopping is not None and now - stopping >= 5:
                break
            for key, _ in selector.select(0.05):
                try:
                    chunk = os.read(key.fd, 8192)
                except BlockingIOError:
                    continue
                if not chunk:
                    selector.unregister(key.fd)
                    continue
                name = key.data
                remaining = limits[name] - len(buffers[name])
                if len(chunk) > remaining:
                    overflow = True
                buffers[name].extend(chunk[:remaining])
        # Even a successful leader can leave descendants which closed every
        # pipe. The unreaped leader still reserves this PGID for final cleanup.
        if process.returncode is None and (not privileged_watchdog or timed_out or overflow or leaked_output):
            signal_denied |= not signal_group(process, signal.SIGKILL)
        reap_started = True
        process.wait(timeout=3)
        return {"returncode": process.returncode, "timed_out": timed_out,
                "overflow": overflow, "leaked_output": leaked_output, "signal_permission_denied": signal_denied,
                **{name: bytes(value) for name, value in buffers.items()}}
    finally:
        try:
            if process is not None:
                # Never signal an already-reaped leader's old PGID, including
                # interruption after wait() updated returncode.
                if not reap_started and process.returncode is None:
                    signal_group(process, signal.SIGKILL)
                try:
                    reap_started = True
                    process.wait(timeout=3)
                finally:
                    process.stdout.close()
                    process.stderr.close()
            elif trace_pipe is not None:
                os.close(trace_pipe[1])
                descriptors.append(trace_pipe[0])
        finally:
            selector.close()
            for descriptor in descriptors:
                os.close(descriptor)


def require_process(result: dict) -> None:
    if (result["returncode"] != 0 or result["timed_out"] or result["overflow"]
            or result["leaked_output"] or result.get("signal_permission_denied", False)):
        raise ValueError("subprocess_not_completed")


def trace_evidence(raw: bytes) -> dict:
    """Accept only complete raw-argument failures from the single -P target."""
    if not raw or len(raw) > 64 * 1024 or b"INJECTED" in raw or b'"' in raw:
        raise ValueError("unsafe_or_missing_syscall_evidence")
    prefix = r"(?:\[pid\s+[0-9]+\]\s+|[0-9]+\s+)?"
    integer = r"(?:0x[0-9a-f]+|0)"
    counts = {name: 0 for name in ("write", "writev", "pwrite64", "fsync", "fdatasync")}
    for line in raw.decode("ascii").splitlines():
        matched = False
        for name, arity in (("write", 3), ("writev", 3), ("pwrite64", 4), ("fsync", 1), ("fdatasync", 1)):
            argument = integer if name in ("write", "writev", "pwrite64") else r"[0-9]+"
            arguments = r",\s*".join([argument] * arity)
            pattern = prefix + name + r"\(" + arguments + r"\)\s+= -1 ENOSPC \(No space left on device\)"
            if re.fullmatch(pattern, line):
                counts[name] += 1
                matched = True
                break
        if not matched:
            raise ValueError("unexpected_syscall_evidence")
    writes = counts["write"] + counts["writev"] + counts["pwrite64"]
    if writes == 0:
        raise ValueError("journal_write_enospc_not_observed")
    return {"errno": 28, "errno_name": "ENOSPC", "write_enospc_count": writes,
            "syscall_counts": counts, "trace_bytes": len(raw),
            "trace_sha256": hashlib.sha256(raw).hexdigest(), "raw_write_arguments": True,
            "single_exact_target_filter": True}


def validate_receipt(receipt: dict, case: str, suite: str = "active") -> None:
    cases = suite_cases(suite)
    if case not in cases:
        raise ValueError("unexpected_test_case")
    if suite == "wallet_prepare":
        wallet_prepare_evidence.validate_receipt(receipt, case)
        return
    if suite == "wallet":
        validate_wallet_receipt(receipt, case)
        return
    if (not isinstance(receipt, dict) or set(receipt) != RECEIPT_FIELDS
            or type(receipt["schema_version"]) is not int or receipt["schema_version"] != 1
            or receipt["case"] != case or receipt["target_rel"] != CASES[case]
            or receipt["profile"] != "active_segments_v1" or receipt["filesystem"] != "tmpfs"):
        raise ValueError("unexpected_test_receipt")
    if any(receipt[field] is not True for field in BOOL_FIELDS):
        raise ValueError("test_invariant_not_confirmed")
    if any(type(receipt[field]) is not int or not 0 <= receipt[field] < 2**64 for field in INTEGER_FIELDS):
        raise ValueError("invalid_receipt_integer")
    if (receipt["target_ino"] == 0 or receipt["target_nlink"] != 1 or receipt["filler_errno"] != 28
            or not 0 < receipt["filler_bytes"] < TMPFS_BYTES
            or not 0 < receipt["frame_len"] <= TMPFS_BYTES
            or not receipt["before_len"] <= receipt["after_len"] <= TMPFS_BYTES
            or receipt["after_len"] - receipt["before_len"] != receipt["changed_suffix_len"]):
        raise ValueError("invalid_target_extent")
    for field in ("after_sha256", "checkpoint_apphash", "checkpoint_pin_sha256"):
        if not isinstance(receipt[field], str) or not HEX.fullmatch(receipt[field]):
            raise ValueError("invalid_receipt_digest")
    if case == next(iter(CASES)):
        if (not 0 < receipt["changed_suffix_len"] < receipt["frame_len"]
                or not isinstance(receipt["before_sha256"], str) or not HEX.fullmatch(receipt["before_sha256"])):
            raise ValueError("partial_tail_not_observed")
    elif (receipt["before_len"] != 0 or receipt["after_len"] != 0 or receipt["before_sha256"] is not None
          or receipt["after_sha256"] != hashlib.sha256(b"").hexdigest()):
        raise ValueError("new_segment_first_write_not_confirmed")


def validate_wallet_receipt(receipt: dict, case: str) -> None:
    if (not isinstance(receipt, dict) or set(receipt) != WALLET_RECEIPT_FIELDS
            or type(receipt["schema_version"]) is not int or receipt["schema_version"] != 1
            or receipt["case"] != case or receipt["target_rel"] != WALLET_CASES[case]
            or receipt["profile"] != "wallet_journal_v1" or receipt["filesystem"] != "tmpfs"):
        raise ValueError("unexpected_wallet_receipt")
    is_sync = case == next(iter(WALLET_CASES))
    if (any(receipt[field] is not True for field in WALLET_BOOL_FIELDS)
            or receipt["store_unavailable"] is not is_sync
            or receipt["source_retired_after_success"] is not (not is_sync)):
        raise ValueError("wallet_invariant_not_confirmed")
    if any(type(receipt[field]) is not int or not 0 <= receipt[field] < 2**64 for field in WALLET_INTEGER_FIELDS):
        raise ValueError("invalid_wallet_receipt_integer")
    if (receipt["target_ino"] == 0 or receipt["target_nlink"] != 1 or receipt["filler_errno"] != 28
            or not 0 < receipt["filler_bytes"] < TMPFS_BYTES
            or receipt["frame_len"] != WALLET_RECORD_BYTES
            or not 0 < receipt["changed_suffix_len"] < WALLET_RECORD_BYTES
            or receipt["receipt_generation"] != 3
            or not 1 <= receipt["recovered_receipt_generation"] <= 256
            or receipt["backup_len"] != WALLET_HEADER_BYTES + receipt["receipt_generation"] * WALLET_RECORD_BYTES
            or receipt["backup_len"] > TMPFS_BYTES
            or not receipt["before_len"] <= receipt["after_len"] <= TMPFS_BYTES):
        raise ValueError("invalid_wallet_target_extent")
    for field in ("after_sha256", "backup_sha256", "receipt_pin_sha256", "recovered_receipt_pin_sha256"):
        if not isinstance(receipt[field], str) or not HEX.fullmatch(receipt[field]):
            raise ValueError("invalid_wallet_receipt_digest")
    if is_sync:
        if (receipt["before_len"] != receipt["backup_len"]
                or receipt["before_sha256"] != receipt["backup_sha256"]
                or receipt["after_len"] != 102400 or receipt["changed_suffix_len"] != 3484
                or receipt["after_len"] - receipt["before_len"] != receipt["changed_suffix_len"]
                or receipt["recovered_receipt_generation"] != receipt["receipt_generation"]
                or receipt["recovered_receipt_pin_sha256"] != receipt["receipt_pin_sha256"]):
            raise ValueError("partial_wallet_sync_not_confirmed")
    elif (receipt["before_len"] != 0 or receipt["before_sha256"] is not None
          or receipt["after_len"] != 4096 or receipt["changed_suffix_len"] != 4024
          or receipt["after_len"] - WALLET_HEADER_BYTES != receipt["changed_suffix_len"]
          or receipt["recovered_receipt_generation"] != 1
          or receipt["recovered_receipt_pin_sha256"] == receipt["receipt_pin_sha256"]):
        raise ValueError("partial_wallet_compact_not_confirmed")


def wallet_public_pin(path: Path, pin: bytes, *, require_tip: bool) -> tuple[os.stat_result, str, bytes]:
    """Bind a retained receipt to encrypted bytes, without treating hashes as authentication."""
    if path.resolve(strict=True) != path:
        raise ValueError("wallet_public_path_changed")
    info, digest, encrypted = file_identity(path, TMPFS_BYTES, capture=True)
    count, remainder = divmod(len(encrypted) - WALLET_HEADER_BYTES, WALLET_RECORD_BYTES)
    generation = int.from_bytes(pin[32:40], "big")
    if (len(pin) != 72 or not 1 <= count <= 256 or remainder or encrypted[:8] != b"ZVWJNL01"
            or not 1 <= generation <= count or (require_tip and generation != count)):
        raise ValueError("wallet_public_framing_mismatch")
    previous = hashlib.sha256(encrypted[:WALLET_HEADER_BYTES]).digest()
    if previous != pin[:32]:
        raise ValueError("wallet_public_pin_mismatch")
    for index in range(1, count + 1):
        offset = WALLET_HEADER_BYTES + (index - 1) * WALLET_RECORD_BYTES
        record = encrypted[offset:offset + WALLET_RECORD_BYTES]
        observed = hashlib.sha256(record[:-32]).digest()
        if (record[:8] != index.to_bytes(8, "big") or record[8:40] != previous
                or record[-32:] != observed or (index == generation and observed != pin[40:])):
            raise ValueError("wallet_public_pin_mismatch")
        previous = observed
    return info, digest, encrypted


def verify_wallet_files(mount: Path, control: Path, receipt: dict, case: str, uid: int) -> None:
    control_device = control.stat().st_dev
    pins = []
    for name, field, generation in (("checkpoint.bin", "receipt_pin_sha256", "receipt_generation"),
                                    ("recovered-checkpoint.bin", "recovered_receipt_pin_sha256", "recovered_receipt_generation")):
        info, digest, pin = file_identity(control / name, 72, capture=True)
        if (info.st_uid != uid or info.st_dev != control_device or info.st_size != 72 or digest != receipt[field]
                or int.from_bytes(pin[32:40], "big") != receipt[generation]):
            raise ValueError("wallet_checkpoint_identity_mismatch")
        pins.append(pin)
    is_sync = case == next(iter(WALLET_CASES))
    if (is_sync and pins[0] != pins[1]) or (not is_sync and pins[0][:32] == pins[1][:32]):
        raise ValueError("wallet_checkpoint_relationship_mismatch")
    info, digest, _ = wallet_public_pin(control / "backup/wallet.journal", pins[0], require_tip=True)
    if (info.st_uid != uid or info.st_dev != control_device
            or info.st_size != receipt["backup_len"] or digest != receipt["backup_sha256"]):
        raise ValueError("wallet_backup_identity_mismatch")
    source_base = mount if is_sync else control
    source_path = source_base / "source/wallet.journal"
    if source_path.resolve(strict=True) != source_path:
        raise ValueError("wallet_source_path_changed")
    info, _, source = file_identity(source_path, TMPFS_BYTES, capture=True)
    if (info.st_uid != uid or info.st_dev != source_base.stat().st_dev
            or (not is_sync and info.st_size != receipt["backup_len"])
            or hashlib.sha256(source[:receipt["backup_len"]]).hexdigest() != receipt["backup_sha256"]):
        raise ValueError("wallet_source_prefix_mismatch")
    info, _, _ = wallet_public_pin(control / "restored/wallet.journal", pins[1], require_tip=False)
    if info.st_uid != uid or info.st_dev != control_device:
        raise ValueError("wallet_recovered_identity_mismatch")


def utility(command: list[str]) -> None:
    subprocess.run(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                   stderr=subprocess.PIPE, check=True, timeout=10)


def verify_mount(path: Path, control: Path, uid: int) -> dict:
    found = []
    for line in Path("/proc/self/mountinfo").read_text().splitlines():
        before, after = line.split(" - ", 1)
        fields = before.split()
        # The generated paths contain no spaces or mountinfo escapes.
        if fields[4] == str(path):
            found.append((fields, after.split()))
    if len(found) != 1:
        raise ValueError("dedicated_mount_not_found")
    fields, after = found[0]
    flags = set(fields[5].split(","))
    usage = os.statvfs(path)
    info = path.stat()
    if (after[0] != "tmpfs" or not {"rw", "nodev", "nosuid", "noexec"} <= flags
            or any(field.startswith("shared:") for field in fields[6:])
            or info.st_uid != uid or info.st_dev == control.stat().st_dev
            or usage.f_frsize != 4096 or usage.f_blocks * usage.f_frsize != TMPFS_BYTES
            or usage.f_files != TMPFS_INODES or any(path.iterdir())):
        raise ValueError("unexpected_filesystem_boundary")
    return {"filesystem": "tmpfs", "bytes": TMPFS_BYTES, "inodes": TMPFS_INODES,
            "block_bytes": usage.f_frsize, "huge_pages": "never", "device": info.st_dev,
            "total_blocks": usage.f_blocks, "free_blocks_before": usage.f_bfree,
            "available_blocks_before": usage.f_bavail, "free_inodes_before": usage.f_ffree,
            "mount_flags": ["nodev", "nosuid", "noexec"], "private_mount_namespace": True}


def verify_exhausted(path: Path) -> dict:
    usage = os.statvfs(path)
    if usage.f_bfree != 0 or usage.f_bavail != 0 or usage.f_ffree <= 0:
        raise ValueError("block_exhaustion_not_confirmed")
    return {"free_blocks_after": usage.f_bfree, "available_blocks_after": usage.f_bavail,
            "free_inodes_after": usage.f_ffree, "block_exhaustion_confirmed": True,
            "inode_exhaustion_observed": False}


def run_case(binary: Path, case: str, base: Path, uid: int, gid: int, deadline: float, *, suite: str = "active") -> dict:
    cases = suite_cases(suite)
    if case not in cases:
        raise ValueError("unexpected_test_case")
    mount = base / ("mount-" + str(list(cases).index(case)))
    control = base / ("control-" + str(list(cases).index(case)))
    mount.mkdir(mode=0o700)
    control.mkdir(mode=0o700)
    os.chown(mount, uid, gid)
    os.chown(control, uid, gid)
    result = {"case": case, "target_rel": cases[case], "started_at": utc(),
              "completed": False, "ordinary_unmount_succeeded": False}
    mounted = False
    stage = "mount"
    try:
        options = f"size={TMPFS_BYTES},nr_inodes={TMPFS_INODES},huge=never,nodev,nosuid,noexec,mode=0700,uid={uid},gid={gid}"
        utility(["/usr/bin/mount", "-n", "-t", "tmpfs", "-o", options, "zevune-enospc", str(mount)])
        mounted = True
        stage = "filesystem_boundary"
        result["mount"] = verify_mount(mount, control, uid)
        target = mount / cases[case]
        trace_read, trace_write = os.pipe()
        # /proc/self/fd/N is reopened by the already-unprivileged tracer. Its
        # inherited pipe inode must therefore belong to that same identity.
        try:
            os.fchown(trace_write, uid, gid)
            if os.fstat(trace_write).st_uid != uid:
                raise ValueError("trace_pipe_identity_mismatch")
        except (OSError, ValueError):
            os.close(trace_read)
            os.close(trace_write)
            raise
        command = ["/usr/bin/setpriv", f"--reuid={uid}", f"--regid={gid}", "--clear-groups",
                   "--inh-caps=-all", "--ambient-caps=-all", "--bounding-set=-all", "--no-new-privs",
                   "/usr/bin/strace", *TRACE_OPTIONS, "-P", str(target), "-o", f"/proc/self/fd/{trace_write}",
                   "--", str(binary), "--exact", case, "--ignored", "--nocapture", "--test-threads=1"]
        environment = {"PATH": "/usr/bin:/bin", "LC_ALL": "C", "RUST_BACKTRACE": "0",
                       "RUST_LIB_BACKTRACE": "0", "RAYON_NUM_THREADS": "2",
                       "ZEVUNE_ENOSPC_DIR": str(mount), "ZEVUNE_ENOSPC_CONTROL_DIR": str(control)}
        remaining = min(CASE_SECONDS, deadline - time.monotonic() - 15)
        if remaining <= 0:
            os.close(trace_read)
            os.close(trace_write)
            raise ValueError("namespace_deadline_exceeded")
        stage = "execute_test"
        execution = run_bounded(command, timeout=remaining, env=environment,
                                cwd=control, trace_pipe=(trace_read, trace_write))
        result["process"] = {key: execution[key] for key in ("returncode", "timed_out", "overflow", "leaked_output")}
        source_file = SUITE_TEST_FILES[suite]
        location = re.search(rb"(?:tests/)?" + re.escape(source_file.encode("ascii")) + rb":([0-9]{1,6}):([0-9]{1,6})",
                             execution["stderr"] + execution["stdout"])
        if location:
            result["rust_test_location"] = {"file": source_file, "line": int(location[1]), "column": int(location[2])}
        require_process(execution)
        if execution["stderr"]:
            raise ValueError("unexpected_tracer_or_test_stderr")
        stage = "syscall_evidence"
        result["syscall_evidence"] = trace_evidence(execution["trace"])
        stage = "test_receipt"
        info, _, raw = file_identity(control / "receipt.json", 16 * 1024, capture=True)
        if info.st_uid != uid:
            raise ValueError("unexpected_receipt_owner")
        receipt = json.loads(raw, object_pairs_hook=unique)
        validate_receipt(receipt, case, suite)
        stage = "target_identity"
        if target.resolve(strict=True) != target:
            raise ValueError("traced_target_path_changed")
        info, digest, _ = file_identity(target, TMPFS_BYTES)
        if (info.st_dev != result["mount"]["device"] or info.st_uid != uid
                or info.st_dev != receipt["target_dev"] or info.st_ino != receipt["target_ino"]
                or info.st_nlink != receipt["target_nlink"] or info.st_size != receipt["after_len"]
                or digest != receipt["after_sha256"]):
            raise ValueError("traced_target_identity_mismatch")
        if suite == "wallet_prepare":
            stage = "wallet_prepare_file_identities"
            wallet_prepare_evidence.verify_files(mount, control, receipt, case, uid,
                                                 read_file=file_identity, read_chain=wallet_public_pin)
        elif suite == "wallet":
            stage = "wallet_file_identities"
            verify_wallet_files(mount, control, receipt, case, uid)
        else:
            stage = "checkpoint_identity"
            checkpoint, checkpoint_digest, _ = file_identity(control / "checkpoint.bin", 128)
            if checkpoint.st_size != 128 or checkpoint_digest != receipt["checkpoint_pin_sha256"]:
                raise ValueError("checkpoint_identity_mismatch")
        stage = "filesystem_exhaustion"
        result["mount"].update(verify_exhausted(mount))
        result["receipt"] = receipt
        result["completed"] = True
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        result["failure"] = failure_code(error)
        result["failure_type"] = type(error).__name__
        result["failure_stage"] = stage
    finally:
        if mounted:
            try:
                utility(["/usr/bin/umount", "--", str(mount)])
                result["ordinary_unmount_succeeded"] = True
                mount.rmdir()
            except (OSError, subprocess.SubprocessError):
                result["completed"] = False
                result["failure"] = "ordinary_unmount_failed"
                result["failure_stage"] = "ordinary_unmount"
        result["finished_at"] = utc()
    return result


def namespace(args: argparse.Namespace) -> int:
    if (sys.platform != "linux" or os.geteuid() != 0 or os.getpid() != 1
            or args.uid <= 0 or args.gid <= 0
            or os.readlink("/proc/self/ns/mnt") == args.parent_mount_ns
            or os.readlink("/proc/self/ns/pid") == args.parent_pid_ns):
        raise ValueError("fresh_privileged_namespaces_required")
    cases = suite_cases(args.suite)
    base = args.directory
    info = base.lstat()
    if (not base.is_absolute() or base.resolve(strict=True) != base or not stat.S_ISDIR(info.st_mode)
            or info.st_uid != args.uid or stat.S_IMODE(info.st_mode) != 0o700 or any(base.iterdir())):
        raise ValueError("fresh_runner_owned_directory_required")
    _, binary_pin, _ = file_identity(args.test_executable, 128 * 1024 * 1024)
    if binary_pin != args.executable_sha256:
        raise ValueError("test_binary_identity_changed")
    utility(["/usr/bin/mount", "--make-rprivate", "/"])
    deadline = time.monotonic() + NAMESPACE_SECONDS
    results = []
    for case in cases:
        result = run_case(args.test_executable, case, base, args.uid, args.gid, deadline, suite=args.suite)
        results.append(result)
        if not result["completed"] or not result["ordinary_unmount_succeeded"]:
            break
    completed = len(results) == len(cases) and all(case["completed"] for case in results)
    print(json.dumps({"suite": args.suite, "completed": completed, "cases": results}, sort_keys=True), flush=True)
    return 0 if completed else 1


def root_namespace_command(payload: list[str], *, seconds: int = WATCHDOG_SECONDS,
                           kill_after: int = 5) -> list[str]:
    # GNU timeout remains root and outside the namespaces. Its default process
    # group must be retained: --foreground would omit descendants. The same
    # construction is used by the actual privileged supervision probe.
    return ["/usr/bin/sudo", "-n", "--", "/usr/bin/timeout", "--signal=TERM",
            f"--kill-after={kill_after}s", f"{seconds}s", "/usr/bin/unshare",
            "--mount", "--pid", "--fork", "--kill-child", "--mount-proc", "--propagation", "private",
            "/usr/bin/python3", str(Path(__file__).resolve()), *payload]


def namespace_members(identity: str) -> int:
    if not re.fullmatch(r"pid:\[[0-9]+\]", identity):
        raise ValueError("invalid_probe_namespace_identity")
    members = scanned = 0
    with os.scandir("/proc") as entries:
        for entry in entries:
            if not entry.name.isdecimal():
                continue
            scanned += 1
            if scanned > 16384:
                raise ValueError("probe_process_scan_exceeded")
            try:
                current = os.readlink(f"/proc/{entry.name}/ns/pid")
            except (FileNotFoundError, ProcessLookupError):
                continue
            if current == identity:
                members += 1
    return members


def probe_payload(directory: Path) -> int:
    if os.geteuid() != 0 or os.getpid() != 1:
        raise ValueError("probe_requires_root_namespace_init")
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    with (directory / "probe-state.json").open("x", encoding="utf-8") as handle:
        json.dump({"root_euid": os.geteuid(), "pid_namespace": os.readlink("/proc/self/ns/pid"),
                   "mount_namespace": os.readlink("/proc/self/ns/mnt"), "ignores_sigterm": True}, handle)
        handle.flush()
        os.fsync(handle.fileno())
    while True:
        signal.pause()


def probe_controller(args: argparse.Namespace) -> int:
    if (sys.platform != "linux" or os.geteuid() != 0 or os.getpid() == 1
            or args.directory.resolve(strict=True) != args.directory
            or args.directory.stat().st_uid != args.uid or any(args.directory.iterdir())):
        raise ValueError("fresh_probe_controller_required")
    report = {"schema_version": 1, "kind": "root_watchdog_probe", "started_at": utc(),
              "completed": False, "root_euid": os.geteuid(), "tmpfs_mounted": False,
              "watchdog_timeout_seconds": 3, "kill_after_seconds": 2}
    start = time.monotonic()
    try:
        command = root_namespace_command(["--probe-payload", "--directory", str(args.directory)], seconds=3, kill_after=2)
        execution = run_bounded(command, timeout=15)
        elapsed = time.monotonic() - start
        report["elapsed_seconds"] = round(elapsed, 3)
        report["watchdog_exit"] = execution["returncode"]
        if (execution["returncode"] not in (124, 137, -signal.SIGKILL) or execution["timed_out"] or execution["overflow"]
                or execution["leaked_output"] or execution["stdout"] or execution["stderr"]
                or not 3 <= elapsed < 15):
            raise ValueError("privileged_watchdog_not_observed")
        _, _, raw = file_identity(args.directory / "probe-state.json", 4096, capture=True)
        state = json.loads(raw, object_pairs_hook=unique)
        if (not isinstance(state, dict) or set(state) != {"root_euid", "pid_namespace", "mount_namespace", "ignores_sigterm"}
                or type(state["root_euid"]) is not int or state["root_euid"] != 0 or state["ignores_sigterm"] is not True
                or not isinstance(state["pid_namespace"], str) or not isinstance(state["mount_namespace"], str)
                or not re.fullmatch(r"mnt:\[[0-9]+\]", state["mount_namespace"])
                or state["pid_namespace"] == os.readlink("/proc/self/ns/pid")
                or state["mount_namespace"] == os.readlink("/proc/self/ns/mnt")):
            raise ValueError("invalid_privileged_probe_state")
        until = time.monotonic() + 2
        while namespace_members(state["pid_namespace"]):
            if time.monotonic() >= until:
                raise ValueError("privileged_namespace_still_alive")
            time.sleep(0.05)
        report.update(pid_namespace=state["pid_namespace"], mount_namespace=state["mount_namespace"],
                      payload_ignored_sigterm=True, namespace_members_after=0,
                      namespace_exit_confirmed=True, completed=True)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        report["failure"] = failure_code(error)
    report["finished_at"] = utc()
    print(json.dumps(report, sort_keys=True), flush=True)
    return 0 if report["completed"] else 1


def supervision_probe(output: Path) -> dict:
    if (sys.platform != "linux" or os.geteuid() == 0 or not output.is_absolute()
            or output.exists() or output.is_symlink()):
        raise ValueError("ordinary_runner_and_new_probe_output_required")
    base = Path(tempfile.mkdtemp(prefix="zevune-enospc-probe-", dir=os.environ.get("RUNNER_TEMP"))).resolve()
    report = {"schema_version": 1, "kind": "root_watchdog_probe", "completed": False,
              "cleanup_unknown": True, "control_directory_retained": True,
              "kernel_release": os.uname().release, **source_identity()}
    try:
        command = ["/usr/bin/sudo", "-n", "--", "/usr/bin/python3", str(Path(__file__).resolve()),
                   "--probe-controller", "--directory", str(base), "--uid", str(os.geteuid())]
        execution = run_bounded(command, timeout=25, privileged_watchdog=True)
        result = json.loads(execution["stdout"], object_pairs_hook=unique)
        if isinstance(result, dict):
            cause = result.get("failure")
            if isinstance(cause, str) and re.fullmatch(r"[A-Za-z_]{1,80}", cause):
                report["controller_failure"] = cause
            for field in ("watchdog_exit", "root_euid", "namespace_members_after"):
                if type(result.get(field)) is int:
                    report[field] = result[field]
        require_process(execution)
        if (not isinstance(result, dict) or result.get("completed") is not True
                or result.get("kind") != "root_watchdog_probe" or result.get("namespace_exit_confirmed") is not True
                or type(result.get("namespace_members_after")) is not int or result["namespace_members_after"] != 0
                or execution["stderr"]):
            raise ValueError("root_watchdog_probe_not_confirmed")
        report.update(result)
        shutil.rmtree(base)
        report.update(cleanup_unknown=False, control_directory_retained=False)
    except (OSError, ValueError, subprocess.SubprocessError, KeyboardInterrupt) as error:
        report["completed"] = False
        report["failure"] = failure_code(error)
    with output.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(report, handle, indent=2, sort_keys=True)
        handle.write("\n")
    return report


def outer(binary: Path, output: Path, suite: str = "active") -> dict:
    cases = suite_cases(suite)
    if sys.platform != "linux" or os.geteuid() == 0 or os.getegid() == 0:
        raise ValueError("ordinary_linux_runner_required")
    if not binary.is_absolute() or binary.resolve(strict=True) != binary or not os.access(binary, os.X_OK):
        raise ValueError("absolute_regular_test_executable_required")
    if not output.is_absolute() or output.exists() or output.is_symlink():
        raise ValueError("new_absolute_evidence_path_required")
    _, binary_pin, _ = file_identity(binary, 128 * 1024 * 1024)
    report = {"schema_version": 1, "kind": "linux_tmpfs_enospc", "suite": suite, **source_identity(),
              "test_executable_sha256": binary_pin, "started_at": utc(), "completed": False,
              "real_funds_allowed": False, "physical_disk_failure_tested": False,
              "power_loss_tested": False, "case_timeout_seconds": CASE_SECONDS,
              "kernel_release": os.uname().release,
              "namespace_timeout_seconds": NAMESPACE_SECONDS, "runtime_uid": os.geteuid(),
              "runtime_gid": os.getegid(), "trace_options": TRACE_OPTIONS, "cases": [],
              "root_watchdog_seconds": WATCHDOG_SECONDS, "root_watchdog_kill_after_seconds": 5,
              "cleanup_unknown": True, "control_directory_retained": False}
    try:
        stage = "strace_setup"
        version = run_bounded(["/usr/bin/strace", "--version"], timeout=10)
        require_process(version)
        first = version["stdout"].decode("ascii").splitlines()[0]
        if not re.fullmatch(r"strace -- version [0-9]+\.[0-9]+(?:\.[0-9]+)?", first):
            raise ValueError("unexpected_strace_version")
        report["strace_version"] = first
        stage = "ignored_case_discovery"
        listing = run_bounded([str(binary), "--list", "--ignored"], timeout=15)
        require_process(listing)
        discovered = [line.removesuffix(": test") for line in listing["stdout"].decode("ascii").splitlines() if line.endswith(": test")]
        if len(discovered) != len(cases) or set(discovered) != set(cases):
            raise ValueError("ignored_case_inventory_mismatch")
        # Only public receipts survive this directory. Raw traces use pipes;
        # filler writes are confined to fresh tmpfs mounts in the child namespace.
        base = Path(tempfile.mkdtemp(prefix="zevune-enospc-", dir=os.environ.get("RUNNER_TEMP"))).resolve()
        report["control_directory_retained"] = True
        command = root_namespace_command(["--namespace", "--suite", suite, "--test-executable", str(binary),
                   "--directory", str(base), "--uid", str(os.geteuid()), "--gid", str(os.getegid()),
                   "--parent-mount-ns", os.readlink("/proc/self/ns/mnt"),
                   "--parent-pid-ns", os.readlink("/proc/self/ns/pid"), "--executable-sha256", binary_pin])
        stage = "namespace_execution"
        execution = run_bounded(command, timeout=OUTER_SECONDS, privileged_watchdog=True)
        report["namespace_process"] = {key: execution[key] for key in ("returncode", "timed_out", "overflow", "leaked_output", "signal_permission_denied")}
        # On interruption, timeout or a missing exit acknowledgement, preserve
        # the bounded directory. An ordinary user's killpg is not root cleanup.
        result = None
        if not execution["overflow"] and execution["stdout"]:
            result = json.loads(execution["stdout"], object_pairs_hook=unique)
            if (not isinstance(result, dict) or set(result) != {"suite", "completed", "cases"}
                    or result["suite"] != suite
                    or type(result["completed"]) is not bool or not isinstance(result["cases"], list)
                    or len(result["cases"]) > len(cases) or any(not isinstance(case, dict) for case in result["cases"])):
                raise ValueError("unexpected_namespace_receipt")
            report["cases"] = result["cases"]
        require_process(execution)
        if (execution["stderr"] or result is None or not result["completed"]
                or len(result["cases"]) != len(cases)
                or [case.get("case") for case in result["cases"]] != list(cases)
                or any(case.get("target_rel") != cases[case["case"]] or case.get("completed") is not True
                       or case.get("ordinary_unmount_succeeded") is not True for case in result["cases"])):
            raise ValueError("namespace_not_completed")
        # unshare --fork has now waited for namespace init, GNU timeout has
        # reaped unshare, and both ordinary umount acknowledgements are present.
        report["namespace_exit_confirmed"] = True
        stage = "control_directory_cleanup"
        shutil.rmtree(base)
        report.update(completed=True, cleanup_unknown=False, control_directory_retained=False)
    except (OSError, ValueError, IndexError, subprocess.SubprocessError, KeyboardInterrupt) as error:
        report["failure"] = failure_code(error)
        report["failure_stage"] = stage
        report["failure_type"] = type(error).__name__
    finally:
        report["finished_at"] = utc()
        with output.open("x", encoding="utf-8", newline="\n") as handle:
            json.dump(report, handle, indent=2, sort_keys=True)
            handle.write("\n")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--test-executable", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--suite", choices=tuple(SUITE_CASES), default="active")
    parser.add_argument("--namespace", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--supervision-probe", action="store_true")
    parser.add_argument("--probe-controller", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--probe-payload", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--directory", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--uid", type=int, default=0, help=argparse.SUPPRESS)
    parser.add_argument("--gid", type=int, default=0, help=argparse.SUPPRESS)
    parser.add_argument("--parent-mount-ns", help=argparse.SUPPRESS)
    parser.add_argument("--parent-pid-ns", help=argparse.SUPPRESS)
    parser.add_argument("--executable-sha256", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    try:
        if args.probe_payload:
            return probe_payload(args.directory)
        if args.probe_controller:
            return probe_controller(args)
        if args.namespace:
            return namespace(args)
        if args.output is None:
            raise ValueError("evidence_output_required")
        if args.supervision_probe:
            result = supervision_probe(args.output)
            print(json.dumps(public_summary(result), sort_keys=True), flush=True)
            return 0 if result["completed"] else 1
        if args.test_executable is None:
            raise ValueError("test_executable_required")
        result = outer(args.test_executable, args.output, args.suite)
        print(json.dumps(public_summary(result), sort_keys=True), flush=True)
        return 0 if result["completed"] else 1
    except (OSError, ValueError, TypeError, subprocess.SubprocessError):
        print("ENOSPC experiment not completed; no raw subprocess output is published.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
