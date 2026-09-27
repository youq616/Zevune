"""Real files/CLI for copying public bytes; no wallet or native acceptance doubles."""
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import native_backend_install as install
from ledger_transaction_lookup import SingleLinkBackend


class InstallTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='native-install-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.source = self.root / 'source.bin'
        self.target = self.root / 'approved.bin'
        # Inert public bytes. A successful copy is NOT successful code execution.
        self.raw = b'NOT-A-VERIFIER\n' + bytes(range(256)) * 9000
        self.source.write_bytes(self.raw)
        self.pin = hashlib.sha256(self.raw).hexdigest()
        self.before = install.metadata_identity(self.source.lstat())

    def call(self):
        return install.install(self.source, self.target, self.pin)

    def unchanged_source(self):
        self.assertEqual(self.source.read_bytes(), self.raw)
        self.assertEqual(install.metadata_identity(self.source.lstat()), self.before)

    def test_complete_copy_verify_and_exact_public_scope(self):
        result = self.call()
        self.assertEqual(self.target.read_bytes(), self.raw)
        self.assertFalse(os.path.samefile(self.target, self.source))
        self.assertEqual(self.target.stat().st_nlink, 1)
        self.assertEqual(result['bytes'], len(self.raw))
        self.assertEqual(result['backend_sha256'], self.pin)
        self.assertIs(result['installed'], True)
        for field in ('executable_started', 'protocol_verified', 'code_signature_verified',
                      'platform_compatibility_verified', 'accepted', 'real_funds_allowed',
                      'system_configuration_modified', 'existing_destination_modified', 'automatic_launch'):
            self.assertIs(result[field], False)
        self.assertIs(install.verify(self.target, self.pin)['single_link_verified'], True)
        SingleLinkBackend(self.target, self.pin)._check()  # Real integrity gate, never a verifier response.
        self.unchanged_source()

    def test_hardlinked_build_input_becomes_independent_single_link_copy(self):
        alias = self.root / 'build-cache-alias'
        os.link(self.source, alias)
        self.before = install.metadata_identity(self.source.lstat())
        with self.assertRaises(ValueError):
            SingleLinkBackend(self.source, self.pin)._check()
        result = self.call()
        self.assertEqual(result['source_link_count'], 2)
        self.assertEqual(self.source.stat().st_nlink, 2)
        self.assertEqual(self.target.stat().st_nlink, 1)
        self.assertEqual(alias.read_bytes(), self.target.read_bytes())
        SingleLinkBackend(self.target, self.pin)._check()
        self.unchanged_source()

    def test_verification_does_not_accept_linked_target(self):
        self.call()
        os.link(self.target, self.root / 'alias')
        with self.assertRaises(ValueError):
            install.verify(self.target, self.pin)

    def test_pins_types_and_paths_rejected_before_io(self):
        with patch.object(install, 'directory_chain', side_effect=AssertionError('unexpected IO')):
            for source, target, digest in ((self.source, self.target, '0' * 64), (self.source, self.target, 'A' * 64),
                                          (self.source, self.target, True), (None, self.target, self.pin),
                                          (self.source, str(self.target), self.pin), (Path('relative'), self.target, self.pin),
                                          (self.source, self.root / '..' / 'bad', self.pin)):
                with self.subTest(digest=digest), self.assertRaises(ValueError):
                    install.install(source, target, digest)
        self.assertFalse(self.target.exists())

    def test_controls_and_oversize_paths(self):
        for text in (str(self.root) + '/x\n', str(self.root) + '/x\u202e', str(self.root) + '/\ud800',
                     str(self.root) + '/' + '中' * 1400):
            with self.assertRaises(ValueError):
                install.install(self.source, Path(text), self.pin)
        self.assertFalse(self.target.exists())

    def test_unicode_and_space_paths(self):
        target = self.root / '批准 程序.bin'
        install.install(self.source, target, self.pin)
        self.assertEqual(target.read_bytes(), self.raw)

    def test_wrong_digest_has_no_output_file(self):
        with self.assertRaises((ValueError, RuntimeError)):
            install.install(self.source, self.target, 'a' * 64)
        self.assertFalse(self.target.exists())
        self.unchanged_source()

    def test_empty_and_oversize_source_rejected(self):
        self.source.write_bytes(b'')
        with self.assertRaises(ValueError):self.call()
        self.source.write_bytes(self.raw)
        with patch.object(install, 'MAX_BINARY', 16), self.assertRaises(ValueError):self.call()
        self.assertFalse(self.target.exists())

    def test_existing_file_directory_and_same_source_never_overwritten(self):
        self.target.write_bytes(b'KEEP')
        with self.assertRaises(ValueError):self.call()
        self.assertEqual(self.target.read_bytes(), b'KEEP')
        self.target.unlink(); self.target.mkdir()
        with self.assertRaises(ValueError):self.call()
        self.assertEqual(list(self.target.iterdir()), [])
        with self.assertRaises(ValueError):install.install(self.source, self.source, self.pin)
        self.unchanged_source()

    def test_missing_parent_is_not_created(self):
        target = self.root / 'missing' / 'program'
        with self.assertRaises(OSError):install.install(self.source, target, self.pin)
        self.assertFalse(target.parent.exists())

    @unittest.skipUnless(os.name == 'posix', 'POSIX link and FIFO fixture')
    def test_links_parents_dangling_targets_and_fifo_refused(self):
        alias = self.root / 'source-alias'; alias.symlink_to(self.source)
        with self.assertRaises(ValueError):install.install(alias, self.target, self.pin)
        parent = self.root / 'linked-parent'; parent.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(ValueError):install.install(self.source, parent / 'new', self.pin)
        self.target.symlink_to(self.root / 'missing')
        with self.assertRaises(ValueError):self.call()
        self.assertTrue(self.target.is_symlink()); self.target.unlink()
        self.source.unlink(); os.mkfifo(self.source)
        with self.assertRaises(ValueError):self.call()
        self.assertFalse(self.target.exists())

    def test_reparse_parent_is_rejected(self):
        from types import SimpleNamespace
        with patch.object(Path, 'lstat', return_value=SimpleNamespace(st_mode=stat.S_IFDIR, st_file_attributes=0x400)), \
                self.assertRaises(ValueError):self.call()

    def test_no_subprocess_network_git_or_payload_import(self):
        before = set(sys.modules)
        with patch.object(subprocess, 'Popen', side_effect=AssertionError('no execution')):
            self.call()
        self.assertFalse({'tkinter', 'socket'} & (set(sys.modules) - before))
        self.unchanged_source()

    def test_requested_posix_mode_private_and_executable(self):
        self.call()
        if os.name == 'posix':
            self.assertEqual(stat.S_IMODE(self.target.stat().st_mode), 0o700)
        self.unchanged_source()

    def test_real_short_writes_are_completed(self):
        original = os.write
        counts = []
        def short(fd, raw):
            counts.append(len(raw))
            return original(fd, raw[:65536])
        with patch.object(install.os, 'write', side_effect=short):self.call()
        self.assertGreater(len(counts), 3)
        self.assertLessEqual(max(counts), install.CHUNK_BYTES)
        self.assertEqual(self.target.read_bytes(), self.raw)

    def test_zero_write_fails_once_and_preserves_file(self):
        with patch.object(install.os, 'write', return_value=0) as write, self.assertRaises(ValueError):self.call()
        self.assertEqual(write.call_count, 1)
        self.assertTrue(self.target.exists())
        self.assertEqual(self.target.stat().st_size, 0)
        self.unchanged_source()

    def test_partial_write_failure_no_cleanup_or_resume(self):
        real = os.write
        def partial(fd, raw):
            real(fd, raw[:13]); raise OSError('PRIVATE_WRITE')
        with patch.object(install.os, 'write', side_effect=partial), self.assertRaises(OSError):self.call()
        self.assertEqual(self.target.read_bytes(), self.raw[:13])
        with self.assertRaises(ValueError):self.call()
        self.assertEqual(self.target.read_bytes(), self.raw[:13])
        self.unchanged_source()

    def test_fsync_error_full_file_not_success(self):
        with patch.object(install.os, 'fsync', side_effect=OSError('PRIVATE_SYNC')), self.assertRaises(OSError):self.call()
        self.assertEqual(self.target.read_bytes(), self.raw)
        self.assertIs(install.verify(self.target, self.pin)['integrity_verified'], True)
        self.unchanged_source()

    def test_close_error_not_success_and_descriptor_released(self):
        real = os.close
        def close_then_error(fd):
            real(fd); raise OSError('PRIVATE_CLOSE')
        with patch.object(install.os, 'close', side_effect=close_then_error), self.assertRaises(OSError):self.call()
        self.assertEqual(self.target.read_bytes(), self.raw)
        self.unchanged_source()

    def test_source_grows_during_copy_refused(self):
        real = os.write; events = []
        def change(fd, raw):
            n = real(fd, raw)
            if not events:
                events.append(1)
                with self.source.open('ab') as f:f.write(b'x')
            return n
        with patch.object(install.os, 'write', side_effect=change), self.assertRaises(ValueError):self.call()
        self.assertEqual(events, [1])
        self.assertTrue(self.target.exists())

    def test_new_source_link_during_copy_not_blessed(self):
        real = os.write; events = []
        def change(fd, raw):
            n = real(fd, raw)
            if not events:
                events.append(1); os.link(self.source, self.root / 'late-alias')
            return n
        with patch.object(install.os, 'write', side_effect=change), self.assertRaises(ValueError):self.call()
        self.assertEqual(self.source.stat().st_nlink, 2)

    def test_same_bytes_source_replacement_after_preflight_refused(self):
        real = os.open
        def create_then_replace(path, *args, **kwargs):
            fd = real(path, *args, **kwargs)
            self.source.rename(self.root / 'old'); self.source.write_bytes(self.raw)
            return fd
        with patch.object(install.os, 'open', side_effect=create_then_replace), self.assertRaises(ValueError):self.call()
        self.assertEqual(self.source.read_bytes(), self.raw)

    def test_target_replacement_preserved_not_deleted(self):
        real = install.inspect_file; events = []
        def replace(path, *args, **kwargs):
            result = real(path, *args, **kwargs)
            if path == self.source and self.target.exists() and not events:
                events.append(1)
                self.target.rename(self.root / 'owned-copy'); self.target.write_bytes(b'OTHER_OWNER')
            return result
        with patch.object(install, 'inspect_file', side_effect=replace), self.assertRaises((ValueError, RuntimeError)):
            self.call()
        self.assertEqual(events, [1])
        self.assertEqual(self.target.read_bytes(), b'OTHER_OWNER')
        self.unchanged_source()

    def test_target_extra_link_after_copy_refused(self):
        real = install.inspect_file; events = []
        def link(path, *args, **kwargs):
            result = real(path, *args, **kwargs)
            if path == self.source and self.target.exists() and not events:
                events.append(1); os.link(self.target, self.root / 'target-alias')
            return result
        with patch.object(install, 'inspect_file', side_effect=link), self.assertRaises(ValueError):self.call()
        self.assertEqual(events, [1])
        self.assertEqual(self.target.stat().st_nlink, 2)

    def test_existing_destination_creation_race_preserved(self):
        real = os.open
        def race(path, *args, **kwargs):
            self.target.write_bytes(b'OTHER_OWNER')
            return real(path, *args, **kwargs)
        with patch.object(install.os, 'open', side_effect=race), self.assertRaises(FileExistsError):self.call()
        self.assertEqual(self.target.read_bytes(), b'OTHER_OWNER')

    def test_target_modified_during_final_source_hash_refused(self):
        real = install.inspect_file; count = []
        def inspect(path, *args, **kwargs):
            result = real(path, *args, **kwargs)
            if path == self.source:
                count.append(1)
                if len(count) == 2:self.target.write_bytes(b'TAMPERED')
            return result
        with patch.object(install, 'inspect_file', side_effect=inspect), self.assertRaises((ValueError, RuntimeError)):self.call()
        self.assertEqual(count, [1, 1])

    def test_source_modified_during_final_target_hash_refused(self):
        real = install.inspect_file
        def inspect(path, *args, **kwargs):
            result = real(path, *args, **kwargs)
            if path == self.target:self.source.write_bytes(b'TAMPERED')
            return result
        with patch.object(install, 'inspect_file', side_effect=inspect), self.assertRaises(ValueError):self.call()

    def test_one_deadline_no_copy_after_expired_preflight(self):
        real = install.inspect_file
        def inspect(*args, **kwargs):
            answer = real(*args, **kwargs)
            # Move only the product clock past the same absolute deadline.
            self.clock.return_value = kwargs['deadline'] + 1
            return answer
        with patch.object(install.time, 'monotonic', return_value=1.0) as self.clock, \
                patch.object(install, 'inspect_file', side_effect=inspect), self.assertRaises(ValueError):self.call()
        self.assertFalse(self.target.exists())

    def command(self, operation='install'):
        command = [sys.executable, str(Path(install.__file__)), '--no-real-funds', operation, '--backend-sha256', self.pin]
        return command + (['--source', str(self.source), '--destination', str(self.target)] if operation == 'install'
                          else ['--backend', str(self.target)])

    def test_real_cli_install_verify_and_repeat_no_git_or_display(self):
        env = {**os.environ, 'PATH': '', 'DISPLAY': ''}
        for command in (self.command(), self.command('verify')):
            result = subprocess.run(command, capture_output=True, timeout=20, env=env)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIs(json.loads(result.stdout)['executable_started'], False)
        result = subprocess.run(self.command(), capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, b'')
        self.assertEqual(self.target.read_bytes(), self.raw)

    def test_cli_fixed_failures_abbreviation_and_interrupt(self):
        for args in (['--secret', 'PRIVATE'], ['--no-real-f', 'verify']):
            result = subprocess.run([sys.executable, install.__file__, *args], capture_output=True, timeout=20)
            self.assertEqual(result.returncode, 64)
            self.assertNotIn(b'PRIVATE', result.stderr)
        for error in (OSError('PRIVATE'), RuntimeError('PRIVATE'), ValueError('PRIVATE'), KeyboardInterrupt('PRIVATE')):
            out, err = io.StringIO(), io.StringIO()
            with patch.object(install, 'install', side_effect=error), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = install.main(self.command()[2:])
            self.assertEqual(code, 130 if isinstance(error, KeyboardInterrupt) else 1)
            self.assertEqual(out.getvalue(), '')
            self.assertNotIn('PRIVATE', err.getvalue())


if __name__ == '__main__':
    unittest.main()
