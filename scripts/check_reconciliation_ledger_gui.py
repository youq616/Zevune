#!/usr/bin/env python3
"""Real Tk and refusing OS-worker tests; no successful replay is substituted."""
import contextlib
import io
from pathlib import Path
import sys
import tempfile
import threading
import time
import tkinter as tk
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent / 'tests'))
from test_reconciliation_ledger_desktop import values
import reconciliation_ledger_desktop as desktop


def wait(app, limit=4):
    end = time.monotonic() + limit
    while app.job is not None and time.monotonic() < end:
        app.root.update()
        time.sleep(0.005)
    assert app.job is None, 'owned job did not complete within test budget'


class LedgerWidgetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='ledger-desktop-ui-')
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name).resolve()
        self.root = tk.Tk()
        self.app = desktop.Workbench(self.root)
        self.gates = []
        self.addCleanup(self.cleanup)
        for key, value in values(self.path).items():
            self.app.values[key].set(value)
        self.root.update()

    def cleanup(self):
        for gate in self.gates:gate.set()
        job = self.app.job
        if job is not None and job.thread.ident is not None:
            job.thread.join(timeout=4)
            assert not job.thread.is_alive(), 'test left an active worker'
        if self.app.phase != 'closed':
            self.app.cancel_poll()
            self.root.destroy()

    def blocked(self):
        gate, entered, calls = threading.Event(), threading.Event(), []
        self.gates.append(gate)
        def refuse(intent):
            calls.append(threading.get_ident())
            entered.set()
            gate.wait(timeout=4)
            raise RuntimeError('PRIVATE_NATIVE_SENTINEL')
        return gate, entered, calls, refuse

    def start(self):
        self.app.review_button.invoke()
        assert self.app.phase == 'review' and self.app.job is None
        self.app.confirm_button.invoke()

    def test_review_is_pure_default_cancel_and_no_implicit_confirmation(self):
        with patch.object(desktop.checker, 'check', side_effect=AssertionError('must not run')), \
                patch.object(desktop, 'LedgerJob', side_effect=AssertionError('must not construct')):
            self.app.review_button.invoke()
            self.root.update()
            self.assertEqual(self.app.phase, 'review')
            self.assertIs(self.root.focus_get(), self.app.cancel_button)
            text = self.app.details.get('1.0', 'end')
            for value in values(self.path).values():self.assertIn(value, text)
            self.app.cancel_button.invoke()
        self.assertEqual(self.app.phase, 'idle')
        self.assertIsNone(self.app.intent)
        self.assertIsNone(self.app.job)
        self.assertEqual(list(self.path.iterdir()), [])

    def test_invalid_form_never_enters_review_or_starts_job(self):
        for key, bad in (('backend_sha256', 'x'), ('checkpoint', 'x'), ('journal', 'relative')):
            before = self.app.values[key].get()
            self.app.values[key].set(bad)
            with patch.object(desktop, 'LedgerJob', side_effect=AssertionError('no task')):
                self.app.review()
            self.assertEqual(self.app.phase, 'idle')
            self.assertEqual(self.app.status.get(), desktop.FAILURE)
            self.assertIsNone(self.app.intent)
            self.app.values[key].set(before)

    def test_programmatic_change_revokes_review(self):
        self.app.review()
        self.app.values['report_sha256'].set('0' * 64)
        self.app.confirm()
        self.assertEqual(self.app.phase, 'idle')
        self.assertIsNone(self.app.intent)
        self.assertIsNone(self.app.job)
        self.assertTrue(self.app.confirm_button.instate(['disabled']))

    def test_close_in_review_never_starts_native(self):
        self.app.review()
        with patch.object(desktop, 'LedgerJob', side_effect=AssertionError('no task')):
            self.app.close()
        self.assertEqual(self.app.phase, 'closed')
        self.assertIsNone(self.app.job)

    def test_failure_worker_is_off_tk_thread_and_redacted(self):
        gate, entered, calls, refuse = self.blocked()
        out = io.StringIO()
        with patch.object(desktop.checker, 'check', side_effect=refuse), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            self.start()
            self.assertTrue(entered.wait(timeout=1))
            self.assertNotEqual(calls[0], threading.get_ident())
            gate.set()
            wait(self.app)
        self.assertEqual(self.app.phase, 'idle')
        self.assertEqual(self.app.status.get(), desktop.FAILURE)
        self.assertEqual(out.getvalue(), '')
        self.assertIsNone(self.app.last)

    def test_event_loop_responsive_and_repeated_confirm_never_replays_twice(self):
        gate, entered, calls, refuse = self.blocked()
        with patch.object(desktop.checker, 'check', side_effect=refuse):
            self.start()
            self.assertTrue(entered.wait(timeout=1))
            self.app.confirm()
            self.app.review()
            self.app.cancel_review()
            self.app.clear()
            beats = []
            self.root.after(10, lambda: beats.append(True))
            until = time.monotonic() + 0.06
            while time.monotonic() < until:
                self.root.update()
                time.sleep(0.005)
            self.assertTrue(beats)
            self.assertEqual(len(calls), 1)
            self.assertTrue(all(widget.instate(['disabled']) for widget in self.app.controls))
            gate.set()
            wait(self.app)

    def test_close_and_repeated_close_wait_for_actual_worker_exit(self):
        gate, entered, calls, refuse = self.blocked()
        with patch.object(desktop.checker, 'check', side_effect=refuse):
            self.start()
            self.assertTrue(entered.wait(timeout=1))
            job = self.app.job
            self.app.close()
            self.app.close()
            self.assertEqual(self.app.phase, 'closing')
            self.assertTrue(self.root.winfo_exists())
            self.assertIs(self.app.job, job)
            gate.set()
            wait(self.app)
        self.assertEqual(len(calls), 1)
        self.assertEqual(self.app.phase, 'closed')
        self.assertFalse(job.thread.is_alive())

    def test_callback_error_during_running_keeps_worker_owned(self):
        gate, entered, _, refuse = self.blocked()
        with patch.object(desktop.checker, 'check', side_effect=refuse):
            self.start()
            self.assertTrue(entered.wait(timeout=1))
            job = self.app.job
            out = io.StringIO()
            with contextlib.redirect_stderr(out):
                self.app.callback_error(ValueError, ValueError('PRIVATE'), None)
            self.assertIs(self.app.job, job)
            self.assertEqual(self.app.phase, 'running')
            self.assertEqual(out.getvalue(), '')
            gate.set()
            wait(self.app)
        self.assertIsNone(self.app.last)

    def test_construction_failure_leaves_no_task_or_review(self):
        self.app.review()
        with patch.object(desktop, 'LedgerJob', side_effect=MemoryError('PRIVATE')):
            self.app.confirm()
        self.assertEqual(self.app.phase, 'idle')
        self.assertIsNone(self.app.job)
        self.assertIsNone(self.app.intent)
        self.assertEqual(self.app.status.get(), desktop.FAILURE)

    def test_unconfirmed_start_stays_busy_without_completion(self):
        self.app.review()
        with patch.object(threading.Thread, 'start', side_effect=RuntimeError('PRIVATE')):
            self.app.confirm()
        self.assertEqual(self.app.phase, 'running')
        self.assertIsNotNone(self.app.job)
        self.assertIsNone(self.app.job.request[0])
        self.assertIsNone(self.app.job.poll())
        self.app.close()
        self.assertEqual(self.app.phase, 'closing')
        self.assertTrue(self.root.winfo_exists())
        self.assertNotIn('PRIVATE', self.app.status.get())
        # No OS thread exists under this injection; only test cleanup destroys root.

    def test_real_os_start_interruption_retains_ui_until_acknowledgement(self):
        actual = desktop.LedgerJob
        reached, release, ended = threading.Event(), threading.Event(), threading.Event()
        held = []
        def factory(intent):
            job = actual(intent)
            original = job.thread._bootstrap_inner
            def delayed():
                reached.set()
                try:
                    release.wait(timeout=3)
                    original()
                finally:ended.set()
            def interrupt(*args, **kwargs):
                assert reached.wait(timeout=2)
                raise KeyboardInterrupt('PRIVATE')
            job.thread._bootstrap_inner = delayed
            job.thread._started.wait = interrupt
            held.append(job)
            return job
        try:
            with patch.object(desktop, 'LedgerJob', side_effect=factory), \
                    patch.object(desktop.checker, 'check', side_effect=AssertionError('withdrawn')) as call:
                self.start()
                self.assertIs(self.app.job, held[0])
                self.assertIsNone(held[0].thread.ident)
                self.app.close()
                self.assertTrue(self.root.winfo_exists())
                release.set()
                wait(self.app)
                self.assertEqual(call.call_count, 0)
                self.assertEqual(self.app.phase, 'closed')
        finally:
            release.set()
            if held:
                self.assertTrue(ended.wait(timeout=3))
                held[0].thread.join(timeout=3)

    def timer_case(self, *, at=1, registered=False, repeated=False, interrupt=False):
        gate, entered, calls, refuse = self.blocked()
        real_after = self.root.after
        scheduled, failed = [], []
        def after(ms, func=None, *args):
            if ms == 50 and func is not None:
                scheduled.append(func)
                if len(scheduled) == at or (repeated and len(scheduled) == at + 1):
                    failed.append(True)
                    if registered:real_after(ms, func, *args)
                    raise (KeyboardInterrupt if interrupt else tk.TclError)('PRIVATE')
            return real_after(ms, func, *args)
        with patch.object(desktop.checker, 'check', side_effect=refuse), patch.object(self.root, 'after', side_effect=after):
            self.start()
            self.assertTrue(entered.wait(timeout=1))
            until = time.monotonic() + 1
            while not failed and time.monotonic() < until:
                self.root.update()
                time.sleep(0.005)
            self.assertEqual(failed, [True])
            job = self.app.job
            self.assertIsNotNone(job)
            self.assertIsNone(self.app.poll_ticket)
            self.app.confirm()
            self.app.close()
            if repeated:
                self.assertEqual(len(failed), 2)
                self.app.close()
            until = time.monotonic() + 0.1
            while time.monotonic() < until:
                self.root.update()
                time.sleep(0.005)
            self.assertIs(self.app.job, job)
            self.assertEqual(len(calls), 1)
            gate.set()
            wait(self.app)
        self.assertEqual(self.app.callback_errors, 0)
        self.assertEqual(self.app.phase, 'closed')

    def test_initial_poll_failure_can_close(self):self.timer_case()
    def test_reschedule_failure_can_close(self):self.timer_case(at=2)
    def test_registered_then_interrupted_callback_is_inert(self):self.timer_case(registered=True)
    def test_keyboard_interrupt_after_registration_is_inert(self):self.timer_case(registered=True, interrupt=True)
    def test_repeated_close_recovers_another_schedule_failure(self):self.timer_case(repeated=True)

    def test_window_destroy_failure_allows_explicit_close_retry(self):
        with patch.object(self.root, 'destroy', side_effect=tk.TclError('PRIVATE')):
            with self.assertRaises(tk.TclError):self.app.close()
        self.assertEqual(self.app.phase, 'closing')
        self.app.close()
        self.assertEqual(self.app.phase, 'closed')

    def test_all_selectable_controls_disable_automatic_export(self):
        pending = [self.root]
        while pending:
            widget = pending.pop()
            pending.extend(widget.winfo_children())
            if 'exportselection' in widget.keys():
                self.assertFalse(int(widget.cget('exportselection')))

    @unittest.skipUnless(sys.platform.startswith('linux'), 'X11 PRIMARY only')
    def test_review_selection_preserves_primary_and_clipboard(self):
        owner = tk.Entry(self.root, exportselection=True)
        owner.place(x=0, y=0, width=1, height=1)
        owner.insert(0, 'KEEP_PRIMARY')
        owner.selection_range(0, 'end')
        self.root.clipboard_clear()
        self.root.clipboard_append('KEEP_CLIPBOARD')
        self.root.update()
        self.app.review()
        self.app.details.tag_add('sel', '1.0', 'end')
        self.root.update()
        self.assertEqual(self.root.selection_get(selection='PRIMARY'), 'KEEP_PRIMARY')
        self.assertEqual(self.root.clipboard_get(), 'KEEP_CLIPBOARD')
        owner.destroy()

    def test_clear_and_unverified_copy_do_not_touch_clipboard(self):
        self.root.clipboard_clear()
        self.root.clipboard_append('KEEP')
        self.app.copy()
        self.app.clear()
        self.assertEqual(self.root.clipboard_get(), 'KEEP')
        self.assertTrue(all(not value.get() for value in self.app.values.values()))
        self.assertIsNone(self.app.last)
        self.assertEqual(list(self.path.iterdir()), [])


if __name__ == '__main__':
    unittest.main()
