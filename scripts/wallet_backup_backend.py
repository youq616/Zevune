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


def _identity(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


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
            if _identity(os.fstat(stream.fileno())) != _identity(before):
                raise BackendError("backend_changed")
            remaining = MAX_BINARY + 1
            while remaining:
                part = stream.read(min(1024 * 1024, remaining))
                if not part:
                    break
                digest.update(part)
                remaining -= len(part)
            if remaining == 0 or _identity(os.fstat(stream.fileno())) != _identity(before):
                raise BackendError("backend_changed")
        if _identity(self.path.lstat()) != _identity(before) or digest.hexdigest() != self.digest:
            raise BackendError("backend_digest_mismatch")
        return _identity(before)

    def call(self, op: int, password: bytes, paths: list[str], receipt: str):
        if op not in (2, 6, 9):
            raise BackendError("unsupported_catalog_backend_operation")
        request = encode_request(op, password, paths, receipt)
        before = self._check()
        environment = {key: value for key, value in os.environ.items()
                       if key.upper() in {"SYSTEMROOT", "WINDIR", "TEMP", "TMP"}}
        environment["RAYON_NUM_THREADS"] = "2"
        # Three bounded streams avoid both unlimited communicate() buffering and
        # a stalled stdin writer blocking the parent's deadline.
        proc = subprocess.Popen([str(self.path), "--no-real-funds"], stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                cwd=self.path.parent, env=environment, shell=False)
        output, errors = bytearray(), bytearray()
        bad = threading.Event()

        def stop():
            bad.set()
            try:
                proc.kill()
            except OSError:
                pass

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

        def feed():
            try:
                proc.stdin.write(request)
                proc.stdin.close()
            except (OSError, ValueError):
                stop()

        threads = [threading.Thread(target=drain, args=(proc.stdout, output, 4096), daemon=True),
                   threading.Thread(target=drain, args=(proc.stderr, errors, 1024), daemon=True),
                   threading.Thread(target=feed, daemon=True)]
        try:
            for thread in threads:
                thread.start()
            try:
                code = proc.wait(timeout=TIMEOUT)
            except subprocess.TimeoutExpired as error:
                stop()
                proc.wait(timeout=5)
                raise BackendError("backend_timeout_reconcile_files") from error
            for thread in threads:
                thread.join(timeout=2)
            if any(thread.is_alive() for thread in threads):
                raise BackendError("backend_stream_not_closed")
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
            if proc.poll() is None:
                stop()
                proc.wait(timeout=5)
            # A malicious descendant inheriting a pipe is outside the pinned
            # backend contract; do not block closing a pipe owned by its reader.
            if not any(thread.is_alive() for thread in threads):
                for stream in (proc.stdin, proc.stdout, proc.stderr):
                    stream.close()
