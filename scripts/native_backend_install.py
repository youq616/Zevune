#!/usr/bin/env python3
"""Create-only, digest-pinned local native backend installation; NO-FUNDS.

Source build artifacts may have hardlinks; installed files must have exactly one.
No payload execution, wallet operation, platform/protocol approval or system setup.
Trusted stopped source/parents are required. Failures preserve partial output.
"""
from __future__ import annotations

import sys
if __name__ == '__main__':
    sys.dont_write_bytecode = True

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import time
import unicodedata

from wallet_backup_backend import Backend, MAX_BINARY, file_object_identity, metadata_identity

INSTALL_SECONDS = 300
CHUNK_BYTES = 1024 * 1024


def require(condition: bool, code: str) -> None:
    if not condition:
        raise ValueError(code)


def remaining(deadline: float) -> None:
    require(time.monotonic() < deadline, 'native_install_deadline_expired')


def validate(path: Path, digest: str) -> None:
    """Pure validation, including the digest, before any filesystem access."""
    require(type(digest) is str and re.fullmatch(r'[0-9a-f]{64}', digest) is not None
            and digest != '0' * 64, 'independent_backend_digest_required')
    require(isinstance(path, Path), 'explicit_native_path_required')
    text = str(path)
    require(path.is_absolute() and '..' not in path.parts and len(text) <= 4096
            and not any(unicodedata.category(c) in {'Cc', 'Cf', 'Cs', 'Zl', 'Zp'} for c in text)
            and len(text.encode('utf-8')) <= 4096, 'bounded_absolute_native_path_required')


def directory_chain(folder: Path) -> tuple:
    result = []
    for path in (*reversed(folder.parents), folder):
        info = path.lstat()
        require(stat.S_ISDIR(info.st_mode) and not getattr(info, 'st_file_attributes', 0) & 0x400,
                'plain_native_parent_required')
        result.append((str(path), info.st_dev, info.st_ino, info.st_mode))
    return tuple(result)


def inspect_file(path: Path, digest: str, *, single_link: bool, deadline: float) -> tuple:
    remaining(deadline)
    chain = directory_chain(path.parent)
    before = path.lstat()
    require(stat.S_ISREG(before.st_mode) and 0 < before.st_size <= MAX_BINARY
            and before.st_nlink >= 1 and (not single_link or before.st_nlink == 1)
            and not getattr(before, 'st_file_attributes', 0) & 0x400, 'invalid_native_install_file')
    # The original checker performs bounded hashing and separates Windows path
    # and handle timestamp baselines. Do not replace it with a size-only check.
    identity = Backend(path, digest)._check()
    require(metadata_identity(before) == identity == metadata_identity(path.lstat())
            and directory_chain(path.parent) == chain, 'native_install_file_changed')
    remaining(deadline)
    return identity, chain


def unchanged(path: Path, captured: tuple) -> None:
    identity, chain = captured
    require(directory_chain(path.parent) == chain and metadata_identity(path.lstat()) == identity,
            'native_install_file_changed')


def _summary(digest: str, size: int, operation: str) -> dict:
    return dict(format='zevune-native-backend-install-1', operation=operation,
                backend_sha256=digest, bytes=size, integrity_verified=True, single_link_verified=True,
                executable_started=False, protocol_verified=False, code_signature_verified=False,
                platform_compatibility_verified=False, system_configuration_modified=False,
                accepted=False, real_funds_allowed=False)


def verify(backend: Path, digest: str) -> dict:
    validate(backend, digest)
    deadline = time.monotonic() + INSTALL_SECONDS
    captured = inspect_file(backend, digest, single_link=True, deadline=deadline)
    unchanged(backend, captured)
    remaining(deadline)
    return _summary(digest, captured[0][2], 'verify_native_backend')


def install(source: Path, destination: Path, digest: str) -> dict:
    """Copy approved bytes to a NEW single-linked file; no activation or rollback.

    A multiply-linked source is allowed ONLY as stopped installation input.
    It never becomes an acceptable execution path by passing this function.
    """
    validate(source, digest)
    validate(destination, digest)
    deadline = time.monotonic() + INSTALL_SECONDS
    parent = directory_chain(destination.parent)
    require(not os.path.lexists(destination), 'native_destination_exists')
    before = inspect_file(source, digest, single_link=False, deadline=deadline)
    size = before[0][2]
    require(directory_chain(destination.parent) == parent, 'native_destination_parent_changed')
    # No parents=True, overwrite, unlink, rename, link, shell or program launch.
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NOFOLLOW', 0)
    remaining(deadline)
    fd = os.open(destination, flags, 0o700)
    target_id = None
    try:
        opened_target = os.fstat(fd)
        require(stat.S_ISREG(opened_target.st_mode) and opened_target.st_nlink == 1,
                'invalid_new_native_file')
        require(file_object_identity(destination.lstat()) == file_object_identity(opened_target)
                and directory_chain(destination.parent) == parent, 'native_destination_changed')
        unchanged(source, before)
        hasher = hashlib.sha256()
        total = 0
        with source.open('rb') as stream:
            opened_source = os.fstat(stream.fileno())
            require(file_object_identity(opened_source) == file_object_identity(source.lstat())
                    and metadata_identity(source.lstat()) == before[0], 'native_source_changed')
            while True:
                remaining(deadline)
                chunk = stream.read(min(CHUNK_BYTES, size - total + 1))
                if not chunk:
                    break
                total += len(chunk)
                require(total <= size, 'native_source_size_changed')
                hasher.update(chunk)
                pending = memoryview(chunk)
                while pending:
                    remaining(deadline)
                    written = os.write(fd, pending)
                    require(type(written) is int and 0 < written <= len(pending), 'native_copy_short_write')
                    pending = pending[written:]
            require(metadata_identity(os.fstat(stream.fileno())) == metadata_identity(opened_source),
                    'native_source_handle_changed')
        require(total == size and hasher.hexdigest() == digest, 'native_copy_digest_mismatch')
        unchanged(source, before)
        os.fsync(fd)
        current_target = os.fstat(fd)
        require((current_target.st_dev, current_target.st_ino) ==
                (opened_target.st_dev, opened_target.st_ino) and current_target.st_nlink == 1
                and current_target.st_size == size
                and file_object_identity(destination.lstat()) == file_object_identity(current_target)
                and directory_chain(destination.parent) == parent, 'native_destination_changed')
        target_id = file_object_identity(destination.lstat())
    finally:
        os.close(fd)  # A close/fsync failure is not success and never triggers cleanup deletion.
    # Fully re-read the source before the final target verification. Keep the
    # original hardlink baseline; do not update it to bless concurrent changes.
    require(inspect_file(source, digest, single_link=False, deadline=deadline) == before,
            'native_source_changed')
    target = inspect_file(destination, digest, single_link=True, deadline=deadline)
    # Closing a write handle can finalize timestamps on Windows. Compare object
    # identity across close; the final complete hash and path metadata checks remain.
    require(target[0][:6] == target_id and target[1] == parent, 'native_destination_changed')
    unchanged(source, before)
    unchanged(destination, target)
    remaining(deadline)
    result = _summary(digest, size, 'install_native_backend')
    result.update(installed=True, source_unchanged=True, source_link_count=before[0][4],
                  existing_destination_modified=False, automatic_launch=False)
    return result


class Parser(argparse.ArgumentParser):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **dict(kwargs, allow_abbrev=False))

    def error(self, message):
        self.exit(64, 'Invalid native installer arguments. Use --help; never supply wallet secrets.\n')


def main(argv=None) -> int:
    parser = Parser(description=__doc__)
    parser.add_argument('--no-real-funds', required=True, action='store_true')
    commands = parser.add_subparsers(dest='command', required=True, parser_class=Parser)
    make = commands.add_parser('install', help='copy approved bytes to a NEW file; never execute')
    make.add_argument('--source', required=True, type=Path)
    make.add_argument('--destination', required=True, type=Path)
    check = commands.add_parser('verify', help='verify a single-linked file without executing it')
    check.add_argument('--backend', required=True, type=Path)
    for command in (make, check):
        command.add_argument('--backend-sha256', required=True)
    args = parser.parse_args(argv)
    try:
        result = (install(args.source, args.destination, args.backend_sha256) if args.command == 'install'
                  else verify(args.backend, args.backend_sha256))
        print(json.dumps(result, sort_keys=True))
        sys.stdout.flush()
        return 0
    except KeyboardInterrupt:
        print('Native installation interrupted. Preserve original and partial files; nothing was executed.', file=sys.stderr)
        return 130
    except (ValueError, OSError, RuntimeError, TypeError):
        print('Native installation/check failed. Preserve original and partial files; nothing was executed.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
