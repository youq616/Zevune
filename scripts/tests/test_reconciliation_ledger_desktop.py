"""Real worker refusal/lifecycle tests. No successful ledger verifier substitute."""
import contextlib
import io
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import reconciliation_ledger_desktop as desktop
from test_ledger_restore import pin


def values(root):
    return dict(directory=str(root / 'result'), report_sha256='a' * 64, checkpoint=pin(),
                genesis_sha256=(b'd' * 32).hex(), journal=str(root / 'ledger'),
                backend=str(Path(sys.executable).resolve()), backend_sha256='b' * 64)


class LedgerJobTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.intent = desktop.checker.prepare(values(self.root))

    def finish(self, job):
        job.thread.join(timeout=3)
        self.assertFalse(job.thread.is_alive())
        outcome = job.poll()
        self.assertIsNotNone(outcome)
        self.assertIsNone(outcome.result)
        self.assertIsNone(job.poll())

    def test_real_missing_files_refuse_without_native_launch(self):
        with patch.object(subprocess, 'Popen', side_effect=AssertionError('no native process')):
            job = desktop.LedgerJob(self.intent)
            self.assertFalse(job.thread.daemon)
            job.start()
            self.finish(job)
        self.assertIsNone(job.request[0])
        self.assertEqual(list(self.root.iterdir()), [])

    def test_job_validation_precedes_thread_construction(self):
        with patch.object(threading, 'Thread', side_effect=AssertionError('no thread')):
            for invalid in (None, {}, 'invalid'):
                with self.assertRaises(ValueError):desktop.LedgerJob(invalid)

    def test_no_execution_before_admission_and_withdrawn_request_never_runs(self):
        with patch.object(desktop.checker, 'check', side_effect=AssertionError('no admitted job')) as call:
            job = desktop.LedgerJob(self.intent)
            job.thread.start()  # Real thread blocked on the actual admission gate.
            self.assertIsNone(job.poll())
            self.assertFalse(job.completed.wait(timeout=0.03))
            job.withdraw_start()
            self.finish(job)
            self.assertEqual(call.call_count, 0)

    def test_duplicate_start_refused(self):
        job = desktop.LedgerJob(self.intent)
        job.start()
        with self.assertRaises(ValueError):job.start()
        self.finish(job)

    def test_exceptions_and_keyboard_interrupt_never_reach_thread_excepthook(self):
        for failure in (RuntimeError('PRIVATE'), KeyboardInterrupt('PRIVATE'), SystemExit('PRIVATE')):
            out = io.StringIO()
            with patch.object(desktop.checker, 'check', side_effect=failure), \
                    patch.object(threading, 'excepthook') as hook, \
                    contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
                job = desktop.LedgerJob(self.intent)
                job.start()
                self.finish(job)
            self.assertEqual(out.getvalue(), '')
            self.assertEqual(hook.call_count, 0)
            self.assertIsNone(job.request[0])

    def test_completion_event_does_not_replace_actual_thread_exit(self):
        original = desktop._execute
        release, reached = threading.Event(), threading.Event()
        def delayed(*args):
            original(*args)
            reached.set()
            release.wait(timeout=3)
        try:
            with patch.object(desktop, '_execute', side_effect=delayed):
                job = desktop.LedgerJob(self.intent)
                job.start()
                self.assertTrue(reached.wait(timeout=2))
                self.assertTrue(job.completed.is_set())
                self.assertIsNone(job.poll())
                release.set()
                self.finish(job)
        finally:
            release.set()
            job.thread.join(timeout=3)

    def test_queue_delivery_failure_still_acknowledges_failed_completion(self):
        job = desktop.LedgerJob(self.intent)
        with patch.object(job.channel, 'put_nowait', side_effect=MemoryError('PRIVATE')):
            job.start()
            self.finish(job)
        self.assertTrue(job.completed.is_set())

    def test_no_os_thread_start_is_not_reported_as_completed(self):
        job = desktop.LedgerJob(self.intent)
        with patch.object(job.thread, 'start', side_effect=RuntimeError('PRIVATE')):
            with self.assertRaises(RuntimeError):job.start()
        self.assertTrue(job.start_attempted)
        self.assertIsNone(job.request[0])
        self.assertIsNone(job.poll())

    def test_interrupted_real_os_bootstrap_keeps_ownership_and_withdraws_admission(self):
        job = desktop.LedgerJob(self.intent)
        reached, release, ended = threading.Event(), threading.Event(), threading.Event()
        bootstrap = job.thread._bootstrap_inner
        def delayed():
            reached.set()
            try:
                release.wait(timeout=3)
                bootstrap()
            finally:
                ended.set()
        def interrupted(*args, **kwargs):
            assert reached.wait(timeout=2)
            raise KeyboardInterrupt('PRIVATE')
        job.thread._bootstrap_inner = delayed
        job.thread._started.wait = interrupted
        try:
            with patch.object(desktop.checker, 'check', side_effect=AssertionError('withdrawn job')) as call:
                with self.assertRaises(KeyboardInterrupt):job.start()
                self.assertIsNone(job.thread.ident)
                self.assertIsNone(job.poll())
                self.assertIsNone(job.request[0])
                release.set()
                self.assertTrue(ended.wait(timeout=2))
                self.finish(job)
                self.assertEqual(call.call_count, 0)
        finally:
            release.set()
            self.assertTrue(ended.wait(timeout=3))
            job.thread.join(timeout=3)

    def test_incomplete_result_is_refused_not_presented_as_replay_success(self):
        for invalid in (None, {}, {'ledger_replayed': True}, {'retry_authorized': True}):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                desktop.present(invalid, self.intent)

    def test_review_lists_exact_frozen_inputs_without_accessing_files(self):
        text = desktop.review_text(self.intent)
        for value in values(self.root).values():self.assertIn(value, text)
        self.assertIn('verify-active', text)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_help_and_arguments_require_no_display_and_are_redacted(self):
        for tail, status in ((['--help'], 0), (['--secret', 'PRIVATE'], 64), (['--no-real-f'], 64)):
            result = subprocess.run([sys.executable, desktop.__file__, *tail], capture_output=True, timeout=10)
            self.assertEqual(result.returncode, status, result.stderr)
            self.assertNotIn(b'PRIVATE', result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
