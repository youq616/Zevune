"""Fixed-command, bounded transport to the original PUBLIC ledger recovery CLI.

Pins are independently supplied policy, not signatures or finality. The trusted
native executable has no children. No wallet operation or shell is exposed.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
import re
import subprocess
import threading
import time

from wallet_backup_backend import Backend, BackendError, unique

MAX_BYTES = 1024 ** 3
SEGMENT_BYTES = 1024 ** 2
MAX_SEGMENTS = 2048
MAX_PACKAGE = MAX_BYTES + 24844
MAX_REPLY = 2048 + 96 * MAX_SEGMENTS
CALL_SECONDS = 300


def require(condition, code):
    if not condition:
        raise ValueError(code)


def remaining(deadline):
    """One absolute budget, never refreshed after slow identity/I/O work."""
    require(type(deadline) in (int, float) and math.isfinite(deadline),
            "invalid_recovery_deadline")
    value = deadline - time.monotonic()
    require(math.isfinite(value) and value > 0, "recovery_deadline_expired")
    return value


@dataclass(frozen=True)
class Checkpoint:
    encoded: str
    genesis: str
    height: int
    app_hash: str
    length: int
    header: int
    segments: int

    @classmethod
    def parse(cls, value):
        require(type(value) is str and re.fullmatch(r"[0-9a-f]{256}", value) is not None,
                "independent_active_checkpoint_required")
        raw = bytes.fromhex(value)
        require(raw[:8] == b"ZVARCP01", "active_checkpoint_version_required")
        num = lambda a, b: int.from_bytes(raw[a:b], "big")
        height, length, header, count = num(40, 48), num(80, 88), num(88, 92), num(92, 96)
        require(all(raw[a:b] != bytes(b - a) for a, b in ((8, 40), (48, 80), (96, 128))),
                "zero_checkpoint_digest")
        require(height <= 1_000_000 and length <= MAX_BYTES and count <= MAX_SEGMENTS
                and 76 <= header <= 76 + 32 * 65536 and (header - 76) % 32 == 0,
                "checkpoint_bounds")
        records = length - header
        require((height == count == records == 0) if height == 0 else
                (1 <= count <= height and 150 * height <= records <= count * SEGMENT_BYTES),
                "checkpoint_layout_bounds")
        return cls(value, raw[8:40].hex(), height, raw[48:80].hex(), length, header, count)


def ordered(checkpoints):
    require(type(checkpoints) is list and 1 <= len(checkpoints) <= 9, "one_to_nine_checkpoints_required")
    pins = [Checkpoint.parse(value) for value in checkpoints]
    for a, b in zip(pins, pins[1:]):
        require(a.genesis == b.genesis and a.header == b.header and a.height < b.height
                and a.length < b.length and a.segments <= b.segments, "checkpoint_chain_not_increasing")
    return pins


def validate_reply(reply, operation, pin, base=None):
    """Strict response schema/arithmetic; it never authenticates disk bytes."""
    require(type(reply) is dict, "invalid_recovery_response")
    fixed = dict(operation=operation, checkpoint=pin.encoded, height=pin.height, bytes=pin.length,
                 replay_verified=True, finality_verified=False, validator_ready=False, real_funds_allowed=False)
    if base is None:
        fixed.update(checkpoint_format="ZVARCP01", storage_profile="ActiveSegmentsV1",
                     app_hash=pin.app_hash, segment_count=pin.segments)
        require(set(reply) == set(fixed), "unexpected_active_response_fields")
    else:
        package = operation in ("pack-active-incremental", "verify-active-incremental", "restore-active-incremental")
        fixed.update(format="zevune-active-incremental-package-1" if package else "zevune-active-incremental-plan-1",
                     base_checkpoint=base.encoded, base_height=base.height, base_bytes=base.length,
                     reused_bytes=base.length, appended_bytes=pin.length-base.length,
                     new_segment_count=pin.segments-base.segments, byte_prefix_verified=True,
                     incremental_backup_written=operation == "pack-active-incremental", snapshot_imported=False)
        variable = {"ranges", "unchanged_segment_count"}
        if package:
            fixed.update(package_format="ZVAIPK01", archive_restored=operation == "restore-active-incremental")
            variable.add("package_bytes")
        require(set(reply) == set(fixed) | variable, "unexpected_incremental_response_fields")
        ranges = reply["ranges"]
        require(type(ranges) is list and 1 <= len(ranges) <= MAX_SEGMENTS, "invalid_range_count")
        total, indices = 0, []
        for item in ranges:
            require(type(item) is dict and set(item) == {"segment_index", "offset", "length"}, "invalid_range")
            i, offset, size = (item[k] for k in ("segment_index", "offset", "length"))
            require(all(type(n) is int for n in (i, offset, size)) and 0 <= i < pin.segments
                    and 0 <= offset < SEGMENT_BYTES and 0 < size <= SEGMENT_BYTES-offset, "invalid_range_bounds")
            require(not indices or i == indices[-1]+1, "noncontiguous_ranges")
            require((i == base.segments-1 and offset > 0) if i < base.segments else offset == 0,
                    "invalid_range_prefix")
            total += size
            indices.append(i)
        require(indices[0] in {max(0, base.segments-1), base.segments}
                and indices[-1] == pin.segments-1 and total == pin.length-base.length, "invalid_range_total")
        unchanged = base.segments - int(indices[0] < base.segments)
        require(type(reply["unchanged_segment_count"]) is int and reply["unchanged_segment_count"] == unchanged,
                "invalid_unchanged_segments")
        if package:
            size = 268 + 12*len(ranges) + total
            require(type(reply["package_bytes"]) is int and reply["package_bytes"] == size <= MAX_PACKAGE,
                    "invalid_package_length")
    require(all(type(reply[k]) is type(v) and reply[k] == v for k, v in fixed.items()), "recovery_response_mismatch")
    return reply


class RecoveryBackend:
    def __init__(self, executable: Path, sha256: str):
        self.binary = Backend(executable, sha256)  # only its existing identity gate is reused

    def _run(self, args, pin, base, deadline):
        # Hashing the approved executable and creating the process consume the
        # same per-call and outer budgets as waiting for its response.
        remaining(deadline)
        call_deadline = min(deadline, time.monotonic() + CALL_SECONDS)
        before = self.binary._check()
        remaining(call_deadline)
        environment = {k: v for k, v in os.environ.items() if k.upper() in {"SYSTEMROOT", "WINDIR", "TEMP", "TMP"}}
        environment["RAYON_NUM_THREADS"] = "2"
        output, errors, bad = bytearray(), bytearray(), threading.Event()
        threads = []
        drain_deadline = stop_deadline = None
        # No child exists during the allocations above. Once Popen returns,
        # even Thread construction failure must go through owned cleanup.
        remaining(call_deadline)
        proc = subprocess.Popen([str(self.binary.path), *args], stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=False,
                                cwd=self.binary.path.parent, env=environment)

        def stop():
            bad.set()
            try:
                proc.kill()
            except OSError:
                pass

        def reap():
            nonlocal stop_deadline
            if proc.poll() is not None:
                return
            if stop_deadline is None:
                stop_deadline = time.monotonic() + 5
                stop()
            # A failed earlier wait cannot obtain another five-second budget.
            proc.wait(timeout=max(0, stop_deadline - time.monotonic()))

        def drain(stream, target, limit):
            try:
                while part := stream.read(4096):
                    left = limit-len(target)
                    target.extend(part[:left])
                    if len(part) > left:
                        stop()
                        return
            except (OSError, ValueError):
                stop()
            finally:
                # The reader owns this pipe while running. Closing it here
                # also cleans up if a delayed reader outlives the join budget.
                stream.close()

        def join_readers():
            nonlocal drain_deadline
            if drain_deadline is None:
                drain_deadline = time.monotonic() + 2
            for thread in threads:
                if thread.ident is not None:
                    thread.join(timeout=max(0, drain_deadline-time.monotonic()))
            require(not any(t.is_alive() for t in threads), "recovery_stream_not_closed")

        try:
            remaining(call_deadline)
            for stream, target, limit in ((proc.stdout, output, MAX_REPLY), (proc.stderr, errors, 4096)):
                thread = threading.Thread(target=drain, args=(stream, target, limit), daemon=True)
                threads.append(thread)
                thread.start()
            try:
                code = proc.wait(timeout=remaining(call_deadline))
            except subprocess.TimeoutExpired as error:
                reap()
                raise BackendError("recovery_timeout_retain_outputs") from error
            join_readers()
            remaining(call_deadline)
            require(code == 0 and not bad.is_set() and not errors, "recovery_failed_retain_outputs")
            require(self.binary._check() == before, "recovery_binary_changed")
            remaining(call_deadline)
            reply = json.loads(output.decode("ascii"), object_pairs_hook=unique,
                               parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite_recovery_response")))
            checked = validate_reply(reply, args[0], pin, base)
            remaining(call_deadline)
            return checked
        finally:
            try:
                reap()
            finally:
                try:
                    join_readers()
                finally:
                    # Never close a running reader's locked BufferedReader in
                    # the main thread. Its own finally closes it on exit.
                    for i, stream in enumerate((proc.stdout, proc.stderr)):
                        if i >= len(threads) or not threads[i].is_alive():
                            stream.close()

    def active(self, source, pin, deadline, output=None):
        mode = "verify-active" if output is None else "restore-active"
        args = [mode, "--no-real-funds", "--source", str(source), "--checkpoint", pin.encoded]
        if output is not None:
            args += ["--output", str(output)]
        return self._run(args, pin, None, deadline)

    def incremental(self, base_path, base, source, pin, deadline, output=None):
        mode = "plan-active-incremental" if output is None else "restore-active-incremental"
        args = [mode, "--no-real-funds", "--base", str(base_path), "--base-checkpoint", base.encoded,
                "--source", str(source), "--checkpoint", pin.encoded]
        if output is not None:
            args += ["--output", str(output)]
        return self._run(args, pin, base, deadline)

    def backup(self, source, pin, deadline, output):
        args = ["backup-active", "--no-real-funds", "--source", str(source),
                "--checkpoint", pin.encoded, "--output", str(output)]
        return self._run(args, pin, None, deadline)

    def package(self, base_path, base, source, pin, deadline, output=None):
        mode = "verify-active-incremental" if output is None else "pack-active-incremental"
        args = [mode, "--no-real-funds", "--base", str(base_path), "--base-checkpoint", base.encoded,
                "--source", str(source), "--checkpoint", pin.encoded]
        if output is not None:
            args += ["--output", str(output)]
        return self._run(args, pin, base, deadline)
