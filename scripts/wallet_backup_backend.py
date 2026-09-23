"""Pinned, bounded subprocess transport for the NO-FUNDS backup catalog.

Uses the existing wallet request format, never a new wallet/crypto backend.
Secrets travel only over stdin. Neither Python nor forced process termination
provides a secure-memory-erasure guarantee. The trusted backend has no children.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import threading
import time

from zevune_wallet import encode_request

MAX_BINARY = 512 * 1024 * 1024
TIMEOUT = 300


class BackendError(RuntimeError):
    pass


def unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise BackendError("duplicate_backend_field")
        result[key] = value
    return result


def file_object_identity(info):
    """Comparable across path/handle queries; timestamps are not file IDs.

    Preserve the full timestamp baseline separately within each query route.
    Windows metadata APIs need not expose an identical timestamp tuple.
    """
    return (info.st_dev, info.st_ino, info.st_size, stat.S_IFMT(info.st_mode),
            info.st_nlink, getattr(info, "st_file_attributes", 0) & 0x400)


def metadata_identity(info):
    return file_object_identity(info) + (info.st_mtime_ns, info.st_ctime_ns)


_identity = metadata_identity


class Backend:
    def __init__(self, executable: Path, expected_sha256: str):
        if not isinstance(expected_sha256, str) or re.fullmatch(r"[0-9a-f]{64}", expected_sha256) is None:
            raise BackendError("independent_backend_digest_required")
        self.path = executable.absolute()
        self.digest = expected_sha256

    def _check(self):
        before = self.path.lstat()
        if (not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= MAX_BINARY
                or getattr(before, "st_file_attributes", 0) & 0x400
                or self.path.resolve(strict=True) != self.path):
            raise BackendError("invalid_backend_file")
        digest = hashlib.sha256()
        with self.path.open("rb") as stream:
            opened = os.fstat(stream.fileno())
            if file_object_identity(opened) != file_object_identity(before):
                raise BackendError("backend_changed")
            remaining = MAX_BINARY + 1
            while remaining:
                part = stream.read(min(1024 * 1024, remaining))
                if not part:
                    break
                digest.update(part)
                remaining -= len(part)
            if remaining == 0 or _identity(os.fstat(stream.fileno())) != _identity(opened):
                raise BackendError("backend_changed")
        if _identity(self.path.lstat()) != _identity(before) or digest.hexdigest() != self.digest:
            raise BackendError("backend_digest_mismatch")
        return _identity(before)

    def call(self, op: int, password: bytes, paths: list[str], receipt: str):
        if op not in (2, 6, 9):
            raise BackendError("unsupported_catalog_backend_operation")
        return self._exchange(encode_request(op, password, paths, receipt))

    def _exchange(self, request: bytes):
        # Shared bounded transport, not an operation-selection or trust API.
        # Each public caller constructs its own fixed-op request before entry.
        before = self._check()
        environment = {key: value for key, value in os.environ.items()
                       if key.upper() in {"SYSTEMROOT", "WINDIR", "TEMP", "TMP"}}
        environment["RAYON_NUM_THREADS"] = "2"
        # Allocate before acquiring the child; Thread construction/start also
        # belongs inside cleanup. Limits, operation whitelist and stdin-only
        # secret transport are unchanged.
        output, errors = bytearray(), bytearray()
        bad = threading.Event()
        threads = []
        stop_deadline = stream_deadline = None
        proc = subprocess.Popen([str(self.path), "--no-real-funds"], stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                cwd=self.path.parent, env=environment, shell=False)

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
            proc.wait(timeout=max(0, stop_deadline - time.monotonic()))

        def close_owned(stream):
            try:
                stream.close()
            except (OSError, ValueError):
                stop()

        def drain(stream, target, limit):
            try:
                while part := stream.read(1024):
                    remaining = limit - len(target)
                    target.extend(part[:remaining])
                    if len(part) > remaining:
                        stop()
                        return
            except (OSError, ValueError):
                stop()
            finally:
                close_owned(stream)

        def feed():
            try:
                proc.stdin.write(request)
            except (OSError, ValueError):
                stop()
            finally:
                close_owned(proc.stdin)

        def join_streams():
            nonlocal stream_deadline
            if stream_deadline is None:
                # Preserve the old aggregate three-times-two-second budget.
                # Finally cannot renew it, including partial Thread startup.
                stream_deadline = time.monotonic() + 6
            for thread in threads:
                if thread.ident is not None:
                    thread.join(timeout=max(0, stream_deadline - time.monotonic()))
            if any(thread.is_alive() for thread in threads):
                raise BackendError("backend_stream_not_closed")

        try:
            for target, args in ((drain, (proc.stdout, output, 4096)),
                                 (drain, (proc.stderr, errors, 1024)), (feed, ())):
                thread = threading.Thread(target=target, args=args, daemon=True)
                threads.append(thread)
                thread.start()
            try:
                code = proc.wait(timeout=TIMEOUT)
            except subprocess.TimeoutExpired as error:
                reap()
                raise BackendError("backend_timeout_reconcile_files") from error
            join_streams()
            if bad.is_set() or code != 0 or errors:
                raise BackendError("backend_operation_failed_reconcile_files")
            if self._check() != before:
                raise BackendError("backend_changed")
            response = json.loads(output, object_pairs_hook=unique,
                                  parse_constant=lambda _: (_ for _ in ()).throw(BackendError("nonfinite_backend_field")))
            if (type(response) is not dict or response.get("ok") is not True
                    or response.get("scope") != "local_journal_only_no_funds"):
                raise BackendError("unexpected_backend_response")
            return response
        finally:
            try:
                reap()
            finally:
                try:
                    join_streams()
                finally:
                    # A running stream thread owns its close, including a
                    # delayed thread outside the join window. Never block the
                    # main thread acquiring its BufferedReader/Writer lock.
                    for i, stream in enumerate((proc.stdout, proc.stderr, proc.stdin)):
                        if i >= len(threads) or not threads[i].is_alive():
                            close_owned(stream)
