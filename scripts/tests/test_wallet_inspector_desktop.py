"""Pure input/UI formatting and real refusing jobs, never accepting crypto mocks."""
import contextlib
from dataclasses import FrozenInstanceError
import io
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import wallet_inspector_desktop as desktop
from test_wallet_backup import frames


def values(root):
    return dict(wallet=str(root / 'wallet.journal'), ancestor=frames(2)[1],
                backend=str(root / 'backend'), backend_sha256='a' * 64,
                reserve='0', saves='1', warn='16')


class InspectorTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.form = values(self.root)

    def test_prepare_is_immutable_and_does_not_probe_any_files(self):
        with patch.object(Path, 'stat', side_effect=AssertionError('unexpected disk probe')), \
                patch.object(Path, 'lstat', side_effect=AssertionError('unexpected disk probe')):
            intent = desktop.prepare(self.form)
            self.assertEqual(intent.saves, 1)
            self.assertEqual(intent.ancestor, self.form['ancestor'])
            self.assertEqual(intent.reserve, 0)
            with self.assertRaises(FrozenInstanceError):
                intent.wallet = self.root / 'other'
        self.assertIn(str(self.root), intent.review())
        self.assertNotIn('password', intent.__dict__)

    def test_all_fields_are_bounded_and_malformed_last_field_never_touches_files(self):
        changes = ({'saves': '0'}, {'saves': '257'}, {'warn': '256'}, {'reserve': '01'},
                   {'reserve': str(1 << 63)}, {'reserve': '-1'}, {'saves': True},
                   {'backend_sha256': 'A'*64}, {'ancestor': 'f'*144},
                   {'wallet': 'relative.wallet'}, {'backend': 'relative.exe'})
        with patch.object(Path, 'stat', side_effect=AssertionError('unexpected disk probe')):
            for change in changes:
                with self.subTest(change=change), self.assertRaises(ValueError):
                    desktop.prepare({**self.form, **change})
        for field, limit in desktop.FIELDS.items():
            for value in ('', 'x'*(limit+1), None):
                with self.subTest(field=field), self.assertRaises(ValueError):
                    desktop.prepare({**self.form, field: value})
        with self.assertRaises(ValueError):
            desktop.prepare({**self.form, 'password': 'not allowed'})

    def test_unicode_controls_and_utf8_path_byte_limit(self):
        for character in ('\x00', '\x85', '\u061c', '\u200b', '\u200e', '\u2028', '\u2029', '\ud800'):
            for key in ('wallet', 'backend'):
                with self.subTest(key=key, character=repr(character)), self.assertRaises(ValueError):
                    desktop.prepare({**self.form, key: str(self.root / ('a'+character+'b'))})
        allowed = desktop.prepare({**self.form, 'wallet': str(self.root/'钱包é.journal')})
        self.assertIn('钱包', str(allowed.wallet))
        with self.assertRaises(ValueError):
            desktop.prepare({**self.form, 'wallet': '/'+'中'*2000})

    def test_password_utf8_bounds_no_stripping_or_normalization(self):
        for value in ('x'*15, 'x'*1025, '\ud800'*16, '中'*342, None):
            with self.subTest(type=type(value).__name__), self.assertRaises((ValueError, UnicodeError)):
                desktop.password_bytes(value)
        for value in ('x'*16, '中'*6, ' '+ 'x'*14 + ' ', 'x'*1024):
            self.assertEqual(desktop.password_bytes(value), value.encode('utf-8'))

    def test_readonly_backend_refuses_every_write_scan_and_bool_before_exchange(self):
        backend = desktop.ReadOnlyBackend(self.root/'unused', 'a'*64)
        with patch.object(backend, '_exchange', side_effect=RuntimeError('refusal-only')) as exchange:
            for op in list(range(9)) + [10, True, '9', 9.0]:
                with self.assertRaises(ValueError):
                    backend.call(op, b'x'*16, ['unused'], self.form['ancestor'])
            exchange.assert_not_called()
            with self.assertRaisesRegex(RuntimeError, 'refusal-only'):
                backend.call(9, b'x'*16, ['unused'], self.form['ancestor'])
            self.assertEqual(exchange.call_args.args[0][8], 9)

    def test_public_frames_cannot_be_returned_as_authenticated(self):
        (self.root/'wallet.journal').write_bytes(frames(3)[0])
        with patch.object(desktop.ReadOnlyBackend, 'call', side_effect=RuntimeError('native refusal')), \
                self.assertRaises(RuntimeError):
            desktop.inspect_wallet(desktop.prepare(self.form), b'x'*16)
        self.assertEqual((self.root/'wallet.journal').read_bytes(), frames(3)[0])

    def test_job_catches_private_errors_without_logs_or_exception_objects(self):
        captured = io.StringIO()
        for error in (RuntimeError('PRIVATE_SENTINEL'), SystemExit('PRIVATE_SENTINEL')):
            with patch.object(desktop, 'inspect_wallet', side_effect=error), \
                    contextlib.redirect_stdout(captured), contextlib.redirect_stderr(captured):
                job = desktop.InspectionJob(desktop.prepare(self.form), b'x'*16)
                self.assertFalse(job.thread.daemon)
                job.start()
                job.thread.join(timeout=2)
                self.assertFalse(job.thread.is_alive())
                self.assertIsNone(job.poll().result)
                self.assertIsNone(job.poll())
                self.assertEqual(job.channel.qsize(), 0)
        self.assertEqual(captured.getvalue(), '')

    def test_poll_never_blocks_or_releases_live_job(self):
        gate = threading.Event()
        def delayed_refusal(*args):
            gate.wait(timeout=2)
            raise RuntimeError('refusal only')
        with patch.object(desktop, 'inspect_wallet', side_effect=delayed_refusal):
            job = desktop.InspectionJob(desktop.prepare(self.form), b'x'*16)
            try:
                job.start()
                self.assertIsNone(job.poll())
            finally:
                gate.set()
                job.thread.join(timeout=3)
            self.assertIsNone(job.poll().result)
        self.assertFalse(job.thread.is_alive())

    def test_unknown_start_withdraws_credentials_and_requires_worker_acknowledgement(self):
        job = desktop.InspectionJob(desktop.prepare(self.form), b'x'*16)
        with patch.object(job.thread, 'start', side_effect=RuntimeError('test-only-start-refusal')):
            with self.assertRaises(RuntimeError):
                job.start()
        self.assertTrue(job.start_attempted)
        self.assertIsNone(job.thread.ident)
        self.assertIsNone(job.request[0])
        self.assertIsNone(job.poll())
        self.assertFalse(job.completed.is_set())
        # Emulate a late bootstrap, with a REAL worker and no crypto success.
        # Runtime never retries start: this is exclusively test cleanup.
        with patch.object(desktop, 'inspect_wallet', side_effect=AssertionError('withdrawn job must not authenticate')) as call:
            job.thread.start()
            job.thread.join(timeout=2)
            self.assertFalse(job.thread.is_alive())
            self.assertIsNone(job.poll().result)
            call.assert_not_called()
        self.assertTrue(job.completed.is_set())

    def test_ui_formatting_only_does_not_claim_payment_or_write_success(self):
        # A pure display fixture, not a success backend or authentication test.
        data = desktop.Inspection(self.form['ancestor'], 2, 254, 65968, 123456789, 'warning',
                                  ('disk_reserve_low',), '2000-01-01T00:00:00+00:00')
        self.assertIn('不是付款笔数', data.render())
        self.assertIn('未扫描历史', data.render())
        self.assertNotIn(self.form['ancestor'], data.render())
        self.assertIn('不是写入保证', desktop.LEVELS['nominal'])

    def test_plain_cli_help_and_syntax_do_not_load_tk_or_write_cache(self):
        bundle = self.root/'source'; bundle.mkdir()
        names = ('wallet_inspector_desktop.py', 'wallet_reconcile.py', 'wallet_health.py', 'wallet_backup.py',
                 'wallet_archive.py', 'wallet_backup_backend.py', 'zevune_wallet.py',
                 'ledger_restore.py', 'ledger_recovery_backend.py')
        for name in names:
            shutil.copyfile(Path(desktop.__file__).parent/name, bundle/name)
        before = {p.name:p.read_bytes() for p in bundle.iterdir()}
        env = os.environ.copy()
        for key in ('PYTHONDONTWRITEBYTECODE', 'PYTHONPYCACHEPREFIX', 'DISPLAY'):
            env.pop(key, None)
        for args, code in ((['--help'], 0), (['--password', 'PRIVATE_SENTINEL'], 64)):
            result = subprocess.run([sys.executable, str(bundle/'wallet_inspector_desktop.py'), *args],
                                    env=env, capture_output=True, timeout=15)
            self.assertEqual(result.returncode, code)
            self.assertNotIn(b'PRIVATE_SENTINEL', result.stdout+result.stderr)
        self.assertEqual(before, {p.name:p.read_bytes() for p in bundle.iterdir()})


if __name__ == '__main__':
    unittest.main()
