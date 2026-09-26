"""Real-file installer tests. No accepting wallet verification substitutes."""
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import inspector_source_bundle as delivery
import inspector_source_install as installer

ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / 'scripts/inspector_source_install.py'


class SourceInstallTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base = tempfile.TemporaryDirectory(prefix='source-install-tests-')
        cls.addClassCleanup(cls.base.cleanup)
        cls.workspace = Path(cls.base.name).resolve()
        cls.repo = cls.workspace / 'repo'
        cls.repo.mkdir()

        def git(*args):
            return subprocess.check_output(['git', '-c', 'core.autocrlf=false', *args],
                                           cwd=cls.repo, stderr=subprocess.DEVNULL, timeout=15).decode().strip()

        git('init', '-q')
        git('config', 'user.name', 'Source installation tests')
        git('config', 'user.email', 'tests@example.invalid')
        for source in delivery.SOURCES.values():
            path = cls.repo / source
            path.parent.mkdir(exist_ok=True)
            path.write_bytes((ROOT / source).read_bytes())
        git('add', '.')
        git('commit', '-qm', 'Actual source fixture; not an upstream commit')
        cls.commit = git('rev-parse', 'HEAD')
        cls.original = cls.workspace / 'original'
        cls.pin = delivery.build(cls.repo, cls.commit, cls.original)['manifest_sha256']

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=self.workspace)
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.source = self.folder / 'received'
        self.target = self.folder / 'installed'
        shutil.copytree(self.original, self.source)
        self.original_bytes = self.contents(self.source)

    @staticmethod
    def contents(folder):
        return {path.name: path.read_bytes() for path in folder.iterdir()}

    def install(self, source=None, target=None, pin=None, commit=None):
        return installer.install(self.source if source is None else source,
                                 self.target if target is None else target,
                                 self.pin if pin is None else pin,
                                 self.commit if commit is None else commit)

    def command(self, operation='install'):
        command = [sys.executable, str(TOOL), '--no-real-funds', operation,
                   '--bundle', str(self.source if operation == 'install' else self.target),
                   '--manifest-sha256', self.pin, '--source-commit', self.commit]
        if operation == 'install':
            command += ['--destination', str(self.target)]
        return command

    def test_copy_preserves_exact_bytes_and_original_manifest(self):
        result = self.install()
        self.assertEqual(self.contents(self.target), self.original_bytes)
        self.assertEqual(self.contents(self.source), self.original_bytes)
        self.assertEqual(set(self.contents(self.target)), set(delivery.SOURCES) | {delivery.MANIFEST})
        self.assertEqual(result['manifest_sha256'], self.pin)
        self.assertEqual(result['source_commit'], self.commit)
        self.assertTrue(result['installed'] and result['integrity_verified'] and result['source_unchanged'])
        for field in ('accepted', 'real_funds_allowed', 'payload_executed', 'code_signature_verified',
                      'automatic_launch', 'existing_installation_modified'):
            self.assertIs(result[field], False)
        for name in self.original_bytes:
            self.assertEqual((self.target / name).stat().st_nlink, 1)
            self.assertFalse(os.path.samefile(self.source / name, self.target / name))

    def test_install_needs_no_git_and_imports_no_payload(self):
        before = set(sys.modules)
        with patch.object(delivery, 'git_bytes', side_effect=AssertionError('no Git allowed')), \
                patch.object(subprocess, 'run', side_effect=AssertionError('no subprocess allowed')):
            self.install()
        new = set(sys.modules) - before
        self.assertFalse(new & ({name[:-3] for name in delivery.SOURCES if name.endswith('.py')} | {'tkinter'}))

    def test_malformed_pins_refused_before_filesystem_access(self):
        for pin, commit in ((False, self.commit), ('A' * 64, self.commit),
                            (self.pin, 'HEAD'), (self.pin, self.commit[:8]), (self.pin, None)):
            with self.subTest(pin=pin, commit=commit), \
                    patch.object(delivery, 'directory_chain', side_effect=AssertionError('no path access')):
                with self.assertRaises(ValueError):
                    installer.install(self.source, self.target, pin, commit)
        self.assertFalse(self.target.exists())

    def test_wrong_digest_or_commit_never_creates_destination(self):
        for pin, commit in (('0' * 64, self.commit), (self.pin, '0' * 40)):
            with self.assertRaises(ValueError):
                self.install(pin=pin, commit=commit)
            self.assertFalse(self.target.exists())

    def test_each_modified_payload_refused_before_mkdir(self):
        for name in delivery.SOURCES:
            path = self.source / name
            raw = path.read_bytes()
            path.write_bytes(bytes([raw[0] ^ 1]) + raw[1:])
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.install()
            self.assertFalse(self.target.exists())
            path.write_bytes(raw)

    def test_rehashed_manifest_does_not_replace_external_pin(self):
        path = self.source / 'wallet_health.py'
        data = path.read_bytes() + b'\n# inert change\n'
        path.write_bytes(data)
        manifest_path = self.source / delivery.MANIFEST
        manifest = json.loads(manifest_path.read_bytes())
        for entry in manifest['files']:
            if entry['name'] == path.name:
                entry.update(size=len(data), sha256=hashlib.sha256(data).hexdigest(), git_blob=delivery.blob_id(data))
        manifest_path.write_text(json.dumps(manifest))
        with self.assertRaises(ValueError):
            self.install()
        self.assertFalse(self.target.exists())

    def test_existing_populated_directory_is_untouched(self):
        self.target.mkdir()
        sentinel = self.target / 'existing.txt'
        sentinel.write_bytes(b'EXISTING_INSTALLATION')
        with self.assertRaises(ValueError):
            self.install()
        self.assertEqual(self.contents(self.target), {'existing.txt': b'EXISTING_INSTALLATION'})
        self.assertEqual(self.contents(self.source), self.original_bytes)

    def test_existing_empty_directory_and_file_are_refused(self):
        self.target.mkdir()
        with self.assertRaises(ValueError):
            self.install()
        self.assertEqual(list(self.target.iterdir()), [])
        self.target.rmdir()
        self.target.write_bytes(b'EXISTING_FILE')
        with self.assertRaises(ValueError):
            self.install()
        self.assertEqual(self.target.read_bytes(), b'EXISTING_FILE')

    def test_nested_same_relative_and_traversal_targets_refused(self):
        for target in (self.source, self.source / 'child', Path('relative'),
                       self.folder / '..' / 'escape'):
            with self.subTest(target=str(target)), self.assertRaises(ValueError):
                self.install(target=target)
        self.assertEqual(self.contents(self.source), self.original_bytes)
        with self.assertRaises(ValueError):
            self.install(source=Path('relative'))
        with self.assertRaises(ValueError):
            self.install(target=str(self.target))

    def test_missing_parent_is_not_created(self):
        destination = self.folder / 'not-created' / 'installed'
        with self.assertRaises(OSError):
            self.install(target=destination)
        self.assertFalse(destination.parent.exists())

    def test_missing_extra_and_hardlinked_source_payloads_refused(self):
        missing = self.source / 'wallet_health.py'
        raw = missing.read_bytes()
        missing.unlink()
        with self.assertRaises(ValueError):
            self.install()
        missing.write_bytes(raw)
        extra = self.source / 'extra'
        extra.write_bytes(b'INERT')
        with self.assertRaises(ValueError):
            self.install()
        extra.unlink()
        os.link(missing, self.folder / 'hardlink')
        with self.assertRaises(ValueError):
            self.install()
        self.assertFalse(self.target.exists())

    @unittest.skipUnless(os.name == 'posix', 'native POSIX symlink fixture only')
    def test_symlink_source_parent_payload_and_destination_refused(self):
        alias = self.folder / 'alias'
        alias.symlink_to(self.source, target_is_directory=True)
        with self.assertRaises(ValueError):
            self.install(source=alias)
        with self.assertRaises(ValueError):
            self.install(target=alias / 'child')
        self.target.symlink_to(self.folder / 'missing', target_is_directory=True)
        with self.assertRaises(ValueError):
            self.install()
        self.assertTrue(self.target.is_symlink())
        self.target.unlink()
        payload = self.source / 'wallet_health.py'
        payload.unlink()
        payload.symlink_to(self.original / payload.name)
        with self.assertRaises(ValueError):
            self.install()
        self.assertFalse(self.target.exists())

    def test_partial_write_failure_is_retained_without_manifest(self):
        real = delivery.write_new
        calls = []

        def failed(path, data):
            calls.append(path.name)
            if len(calls) == 2:
                real(path, data[:13])
                raise OSError('PRIVATE_WRITE_SENTINEL')
            real(path, data)

        with patch.object(delivery, 'write_new', side_effect=failed), self.assertRaises(OSError):
            self.install()
        self.assertEqual(len(list(self.target.iterdir())), 2)
        self.assertFalse((self.target / delivery.MANIFEST).exists())
        leftover = self.contents(self.target)
        with self.assertRaises(ValueError):
            self.install()
        self.assertEqual(self.contents(self.target), leftover)
        self.assertEqual(self.contents(self.source), self.original_bytes)

    def test_fsync_failure_does_not_report_installation_success(self):
        with patch.object(delivery.os, 'fsync', side_effect=OSError('PRIVATE_SYNC_SENTINEL')), \
                self.assertRaises(OSError):
            self.install()
        self.assertEqual(len(list(self.target.iterdir())), 1)
        self.assertFalse((self.target / delivery.MANIFEST).exists())
        self.assertEqual(self.contents(self.source), self.original_bytes)

    def test_lost_reply_after_manifest_keeps_valid_copy_but_call_fails(self):
        real = delivery.write_new

        def lost_reply(path, data):
            real(path, data)
            if path.name == delivery.MANIFEST:
                raise OSError('PRIVATE_LOST_REPLY_SENTINEL')

        with patch.object(delivery, 'write_new', side_effect=lost_reply), self.assertRaises(OSError):
            self.install()
        self.assertEqual(self.contents(self.target), self.original_bytes)
        self.assertTrue(delivery.verify(self.target, self.pin, self.commit)['integrity_verified'])
        self.assertEqual(self.contents(self.source), self.original_bytes)

    def test_real_short_writes_complete_exactly(self):
        real = os.write
        calls = []

        def short(fd, data):
            calls.append(len(data))
            return real(fd, data[:4096])

        with patch.object(delivery.os, 'write', side_effect=short):
            self.install()
        self.assertTrue(any(size > 4096 for size in calls))
        self.assertEqual(self.contents(self.target), self.original_bytes)

    def test_zero_write_fails_without_loop_or_manifest(self):
        with patch.object(delivery.os, 'write', return_value=0) as write, self.assertRaises(ValueError):
            self.install()
        self.assertEqual(write.call_count, 1)
        self.assertFalse((self.target / delivery.MANIFEST).exists())

    def test_source_changes_during_copy_prevent_manifest(self):
        real = delivery.write_new
        calls = []

        def change(path, data):
            real(path, data)
            calls.append(path.name)
            if len(calls) == 1:
                (self.source / 'wallet_health.py').write_bytes(b'INERT_CONCURRENT_CHANGE')

        with patch.object(delivery, 'write_new', side_effect=change), self.assertRaises(ValueError):
            self.install()
        self.assertFalse((self.target / delivery.MANIFEST).exists())
        self.assertEqual((self.source / 'wallet_health.py').read_bytes(), b'INERT_CONCURRENT_CHANGE')

    def test_same_bytes_source_replacement_is_not_unchanged_identity(self):
        real = delivery.write_new
        changed = []

        def replace(path, data):
            real(path, data)
            if not changed:
                changed.append(True)
                old = self.source / 'wallet_health.py'
                old.rename(self.folder / 'old-source')
                old.write_bytes(self.original_bytes[old.name])

        with patch.object(delivery, 'write_new', side_effect=replace), self.assertRaises(ValueError):
            self.install()
        self.assertFalse((self.target / delivery.MANIFEST).exists())
        self.assertEqual(self.contents(self.source), self.original_bytes)

    def test_replaced_target_never_receives_more_writes_or_cleanup(self):
        real = delivery.write_new
        moved = self.folder / 'owned-partial'
        calls = []

        def replace(path, data):
            real(path, data)
            calls.append(path.name)
            if len(calls) == 1:
                self.target.rename(moved)
                self.target.mkdir()
                (self.target / 'unrelated').write_bytes(b'DO_NOT_TOUCH')

        with patch.object(delivery, 'write_new', side_effect=replace), self.assertRaises(ValueError):
            self.install()
        self.assertEqual(self.contents(self.target), {'unrelated': b'DO_NOT_TOUCH'})
        self.assertEqual(len(list(moved.iterdir())), 1)
        self.assertEqual(len(calls), 1)

    def test_destination_created_between_check_and_mkdir_is_preserved(self):
        real = Path.mkdir

        def race(path, *args, **kwargs):
            if path == self.target:
                real(path)
                (path / 'unrelated').write_bytes(b'DO_NOT_TOUCH')
            return real(path, *args, **kwargs)

        with patch.object(Path, 'mkdir', autospec=True, side_effect=race), self.assertRaises(FileExistsError):
            self.install()
        self.assertEqual(self.contents(self.target), {'unrelated': b'DO_NOT_TOUCH'})

    def test_extra_destination_entry_after_write_is_rejected(self):
        real = delivery.write_new

        def extra(path, data):
            real(path, data)
            if path.name == delivery.MANIFEST:
                (self.target / 'extra').write_bytes(b'INERT')

        with patch.object(delivery, 'write_new', side_effect=extra), self.assertRaises(ValueError):
            self.install()
        self.assertEqual((self.target / 'extra').read_bytes(), b'INERT')

    def test_target_change_during_final_source_check_is_refused(self):
        real = installer._confirm
        changed = []

        def modify_after_source_check(snapshot):
            real(snapshot)
            if (self.target / delivery.MANIFEST).exists() and not changed:
                changed.append(True)
                (self.target / 'wallet_health.py').write_bytes(b'INERT_LATE_TARGET_CHANGE')

        with patch.object(installer, '_confirm', side_effect=modify_after_source_check):
            with self.assertRaises(ValueError):
                self.install()
        self.assertEqual(changed, [True])
        self.assertEqual(self.contents(self.source), self.original_bytes)

    def test_source_change_during_target_verification_is_refused(self):
        real = delivery.verify
        changed = []

        def modify_after_target_check(folder, *args):
            result = real(folder, *args)
            if folder == self.target and not changed:
                changed.append(True)
                (self.source / 'wallet_health.py').write_bytes(b'INERT_LATE_SOURCE_CHANGE')
            return result

        with patch.object(delivery, 'verify', side_effect=modify_after_target_check):
            with self.assertRaises(ValueError):
                self.install()
        self.assertEqual(changed, [True])
        self.assertEqual(self.contents(self.target), self.original_bytes)

    def test_manifest_is_the_final_created_file(self):
        real = delivery.write_new
        order = []

        def record(path, data):
            order.append(path.name)
            return real(path, data)

        with patch.object(delivery, 'write_new', side_effect=record):
            self.install()
        self.assertEqual(order, sorted(delivery.SOURCES) + [delivery.MANIFEST])

    def test_cli_install_and_verify_without_git_or_display(self):
        env = {**os.environ, 'PATH': '', 'DISPLAY': ''}
        for command in (self.command(), self.command('verify')):
            result = subprocess.run(command, capture_output=True, env=env, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(json.loads(result.stdout)['integrity_verified'])
            self.assertFalse(json.loads(result.stdout)['payload_executed'])
        self.assertEqual(self.contents(self.target), self.original_bytes)
        self.assertEqual(self.contents(self.source), self.original_bytes)

    def test_cli_failure_syntax_and_abbreviations_are_redacted(self):
        command = self.command()
        command[command.index('--manifest-sha256') + 1] = 'PRIVATE_INPUT_SENTINEL'
        for args, expected in ((command, 1),
                               ([sys.executable, str(TOOL), '--PRIVATE_INPUT_SENTINEL'], 64),
                               ([sys.executable, str(TOOL), '--no-real-f', 'verify'], 64)):
            result = subprocess.run(args, capture_output=True, timeout=15)
            self.assertEqual(result.returncode, expected)
            self.assertNotIn(b'PRIVATE_INPUT', result.stdout + result.stderr)
            self.assertNotIn(str(self.source).encode(), result.stdout + result.stderr)
        self.assertFalse(self.target.exists())

    def test_interruption_returns_130_and_preserves_partial_output(self):
        output, errors = io.StringIO(), io.StringIO()
        real = delivery.write_new

        def interrupt(path, data):
            real(path, data)
            raise KeyboardInterrupt('PRIVATE_INTERRUPT_SENTINEL')

        with patch.object(delivery, 'write_new', side_effect=interrupt), \
                contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            code = installer.main(self.command()[2:])
        self.assertEqual(code, 130)
        self.assertEqual(output.getvalue(), '')
        self.assertNotIn('PRIVATE', errors.getvalue())
        self.assertEqual(len(list(self.target.iterdir())), 1)
        self.assertFalse((self.target / delivery.MANIFEST).exists())

    def test_unicode_and_spaces_in_plain_paths(self):
        folder = self.folder / '源码 空间'
        folder.mkdir()
        source = folder / '收到的版本'
        shutil.copytree(self.original, source)
        target = folder / '新版本'
        self.install(source=source, target=target)
        self.assertEqual(self.contents(target), self.original_bytes)

    def test_tool_help_does_not_create_import_cache(self):
        tools = self.folder / 'trusted-tools'
        tools.mkdir()
        for path in (TOOL, ROOT / 'scripts/inspector_source_bundle.py'):
            shutil.copyfile(path, tools / path.name)
        before = self.contents(tools)
        result = subprocess.run([sys.executable, str(tools / TOOL.name), '--help'],
                                capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(self.contents(tools), before)


if __name__ == '__main__':
    unittest.main()
