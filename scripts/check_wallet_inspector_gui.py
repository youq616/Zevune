#!/usr/bin/env python3
"""Real Tk password/modal/async refusal checks; no successful backend substitute.

Missing display/Tk fails rather than skipping. Native positive flows live in the
separate genuine-backend driver. Test passwords are synthetic and never logged.
"""
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

import wallet_inspector_desktop as desktop
sys.path.insert(0, str(Path(__file__).resolve().parent/'tests'))
from test_wallet_inspector_desktop import values


def enter(app, key, value):
    entry = app.entries[key]
    entry.delete(0, 'end')
    entry.insert(0, str(value))


def press(app, password='synthetic-password-only', accept=True, during=None):
    events, errors = [], []
    def decide():
        events.append(True)
        try:
            dialog = app.dialog
            assert dialog is not None and app.busy
            assert dialog.entry.cget('show') and not int(dialog.entry.cget('exportselection'))
            assert all(control.instate(['disabled']) for control in app.controls)
            dialog.entry.insert(0, password)
            if during is not None:
                during()
            if dialog.window.winfo_exists():
                (dialog.confirm if accept else dialog.cancel).invoke()
        except Exception:
            errors.append(True)
            if app.dialog is not None and app.dialog.window.winfo_exists():
                app.dialog.finish(False)
    token = app.root.after(20, decide)
    app.inspect_button.invoke()
    app.root.after_cancel(token)
    assert events and not errors, 'real password dialog did not complete'
    assert app.callback_errors == 0, 'unexpected Tk callback failure'


def wait(app, limit=5):
    until = time.monotonic()+limit
    while app.busy and time.monotonic()<until:
        app.root.update()
        time.sleep(0.005)
    assert not app.busy, 'UI job did not finish within test budget'


class InspectorWidgetTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='zevune-inspector-ui-')
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name).resolve()
        self.root = tk.Tk()
        self.app = desktop.Workbench(self.root)
        self.root.update()
        for key, value in values(self.path).items():
            enter(self.app, key, value)
        self.gates = []
        self.addCleanup(self.cleanup)

    def cleanup(self):
        for gate in self.gates:
            gate.set()
        job = self.app.job
        if job is not None and job.thread.ident is not None:
            job.thread.join(timeout=3)
            assert not job.thread.is_alive(), 'test left a worker'
        try:
            if self.app.poll_token:
                self.root.after_cancel(self.app.poll_token)
            self.root.destroy()
        except tk.TclError:
            pass

    def test_password_cancel_starts_no_worker_and_forgets_field(self):
        with patch.object(desktop, 'InspectionJob', side_effect=AssertionError('no job')):
            press(self.app, accept=False)
        self.assertFalse(self.app.busy)
        self.assertIsNone(self.app.dialog)
        self.assertIsNone(self.app.job)
        self.assertIsNone(self.app.last_result)
        self.assertTrue(all(widget.instate(['!disabled']) for widget in self.app.controls))

    def test_entire_form_refused_before_password_prompt(self):
        with patch.object(desktop, 'PasswordDialog', side_effect=AssertionError('must not prompt')):
            for field, invalid in (('reserve', '01'), ('saves', '0'), ('warn', '999'), ('ancestor', 'x'),
                                   ('wallet', str(self.path/'a\u200bb'))):
                original = self.app.values[field].get()
                enter(self.app, field, invalid)
                self.app.inspect_button.invoke()
                self.assertEqual(self.app.status.get(), desktop.FAILURE)
                self.assertFalse(self.app.busy)
                self.assertIsNone(self.app.dialog)
                enter(self.app, field, original)

    def test_password_invalid_clears_entry_and_does_not_accept(self):
        events=[]
        def check():
            dialog = self.app.dialog
            dialog.entry.insert(0, 'short')
            dialog.confirm.invoke()
            events.append(dialog.entry.get() == '' and dialog.password is None and dialog.window.winfo_exists())
            dialog.cancel.invoke()
        self.root.after(20, check)
        self.app.inspect_button.invoke()
        self.assertEqual(events, [True])
        self.assertIsNone(self.app.job)

    def test_password_copy_event_does_not_change_clipboard(self):
        self.root.clipboard_clear(); self.root.clipboard_append('unchanged')
        def check():
            dialog = self.app.dialog
            dialog.entry.selection_range(0, 'end')
            dialog.entry.event_generate('<<Copy>>')
            self.assertEqual(self.root.clipboard_get(), 'unchanged')
        press(self.app, accept=False, during=check)
        self.assertEqual(self.root.clipboard_get(), 'unchanged')

    def test_all_selectable_inspector_fields_disable_selection_export(self):
        # Includes the password and frozen-review dialog, not just output.
        def verify_options():
            pending = [self.root]
            while pending:
                widget = pending.pop()
                pending.extend(widget.winfo_children())
                if 'exportselection' in widget.keys():
                    self.assertFalse(int(widget.cget('exportselection')),
                                     'inspector widget silently exports selection')
        verify_options()
        press(self.app, accept=False, during=verify_options)

    @unittest.skipUnless(sys.platform.startswith('linux'), 'X11 PRIMARY semantics only')
    def test_selecting_receipt_keeps_unrelated_primary_and_clipboard(self):
        # Inert text only: this exercises Tk selection, not authentication.
        receipt_widget = next(widget for widget in self.app.copy_button.master.winfo_children()
                              if widget.winfo_class() == 'TEntry')
        owner = tk.Entry(self.root, exportselection=True)
        owner.place(x=0, y=0, width=1, height=1)
        self.addCleanup(owner.destroy)
        owner.insert(0, 'INERT_EXISTING_PRIMARY')
        owner.selection_range(0, 'end')
        self.root.clipboard_clear()
        self.root.clipboard_append('INERT_EXISTING_CLIPBOARD')
        self.root.update()
        self.assertEqual(self.root.selection_get(selection='PRIMARY'), 'INERT_EXISTING_PRIMARY')
        self.app.receipt.set('INERT_RECEIPT_NOT_AUTHENTICATED')
        receipt_widget.selection_range(0, 'end')
        self.root.update()
        self.assertEqual(self.root.selection_get(selection='PRIMARY'), 'INERT_EXISTING_PRIMARY',
                         'selecting a display-only receipt exported it without explicit copy')
        self.assertEqual(self.root.clipboard_get(), 'INERT_EXISTING_CLIPBOARD')
        self.assertIsNone(self.app.last_result)

    def test_changed_intent_during_password_is_not_dispatched(self):
        with patch.object(desktop, 'InspectionJob', side_effect=AssertionError('do not dispatch')):
            press(self.app, during=lambda: self.app.values['reserve'].set('10'))
        self.assertFalse(self.app.busy)
        self.assertIsNone(self.app.job)
        self.assertIsNone(self.app.last_result)

    def test_worker_runs_off_main_thread_and_failure_is_redacted(self):
        main_thread = threading.get_ident()
        seen=[]
        def refuse(intent, password):
            seen.append((threading.get_ident()!=main_thread, type(intent) is desktop.Intent,
                         password == b'synthetic-password-only'))
            raise RuntimeError('PRIVATE_SENTINEL')
        output=io.StringIO()
        with patch.object(desktop, 'inspect_wallet', side_effect=refuse), \
                contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            press(self.app)
            wait(self.app)
        self.assertEqual(seen, [(True, True, True)])
        self.assertIsNone(self.app.last_result)
        self.assertEqual(output.getvalue(), '')
        self.assertEqual(self.app.status.get(), desktop.FAILURE)
        self.assertIsNone(self.app.dialog)

    def test_close_waits_for_owned_job_and_never_launches_second(self):
        gate=threading.Event(); self.gates.append(gate)
        calls=[]
        def refuse(*args):
            calls.append(1); gate.wait(timeout=3); raise RuntimeError('refusal')
        with patch.object(desktop, 'inspect_wallet', side_effect=refuse):
            press(self.app)
            heartbeat=[]
            self.root.after(10, lambda: heartbeat.append(1))
            for _ in range(5):
                self.root.update(); time.sleep(0.01)
            self.app.begin()
            self.app.close()
            self.assertTrue(self.app.closing and self.app.busy)
            self.assertTrue(self.root.winfo_exists())
            self.assertEqual(heartbeat, [1])
            gate.set()
            wait(self.app)
        self.assertEqual(calls, [1])
        self.assertIsNone(self.app.job)
        with self.assertRaises(tk.TclError):
            self.root.winfo_exists()

    def test_close_during_password_cancels_without_job(self):
        self.root.after(20, self.app.close)
        self.app.inspect_button.invoke()
        self.assertTrue(self.app.closing)
        self.assertIsNone(self.app.job)
        self.assertFalse(self.app.busy)

    def test_thread_construction_failure_has_no_start_attempt_or_credentials(self):
        with patch.object(desktop, 'InspectionJob', side_effect=MemoryError('PRIVATE_SENTINEL')):
            press(self.app)
        self.assertFalse(self.app.busy)
        self.assertIsNone(self.app.job)
        self.assertIsNone(self.app.dialog)
        self.assertEqual(self.app.status.get(), desktop.FAILURE)

    def test_unconfirmed_start_failure_is_not_reported_as_idle_or_closed(self):
        with patch.object(threading.Thread, 'start', side_effect=RuntimeError('PRIVATE_SENTINEL')):
            press(self.app)
        job = self.app.job
        self.assertIsNotNone(job)
        self.assertTrue(self.app.busy and job.start_attempted)
        self.assertIsNone(job.request[0])
        self.assertIsNone(self.app.dialog)
        self.assertIsNone(job.poll())
        self.assertNotIn('PRIVATE_SENTINEL', self.app.status.get())
        self.app.close()
        self.assertTrue(self.root.winfo_exists())
        self.assertIs(self.app.job, job)
        # No actual OS thread was created by this test injection. Leave the
        # guarded UI in place until test cleanup destroys the test-only root.

    def test_os_thread_before_ident_interruption_retains_job_until_completion(self):
        # Exercise the exact CPython start window with a REAL OS thread: hold
        # bootstrap before ident, then interrupt the parent's _started.wait.
        # No successful backend is substituted. The late target must not run
        # authentication after startup was withdrawn.
        reached, release, booted = threading.Event(), threading.Event(), threading.Event()
        real_job = desktop.InspectionJob
        held, calls = [], []
        def factory(*args):
            job = real_job(*args)
            bootstrap = job.thread._bootstrap_inner
            def delayed_bootstrap():
                reached.set()
                try:
                    release.wait(timeout=3)
                    bootstrap()
                finally:
                    booted.set()
            def interrupted_wait(*args, **kwargs):
                assert reached.wait(timeout=2), 'real OS thread was not created'
                raise KeyboardInterrupt('test_only_interrupted_start')
            job.thread._bootstrap_inner = delayed_bootstrap
            job.thread._started.wait = interrupted_wait
            held.append(job)
            return job
        def refuse(*args):
            calls.append(1)
            raise RuntimeError('unexpected late authentication')
        try:
            with patch.object(desktop, 'InspectionJob', side_effect=factory), \
                    patch.object(desktop, 'inspect_wallet', side_effect=refuse):
                press(self.app)
                self.assertEqual(len(held), 1)
                job = held[0]
                self.assertIsNone(job.thread.ident)
                self.assertIs(self.app.job, job, 'uncertain OS thread ownership was dropped')
                self.assertTrue(self.app.busy)
                self.root.update()
                self.assertIs(self.app.job, job, 'poll treated ident=None as completed')
                self.app.begin()
                self.assertEqual(len(held), 1, 'a second job was allowed')
                self.app.close()
                self.assertTrue(self.root.winfo_exists(), 'window closed before worker acknowledgement')
                release.set()
                wait(self.app)
                self.assertTrue(booted.wait(timeout=2))
                self.assertFalse(job.thread.is_alive())
                self.assertEqual(calls, [], 'withdrawn startup still authenticated')
        finally:
            release.set()
            if held:
                self.assertTrue(booted.wait(timeout=3), 'test OS thread did not finish')
                held[0].thread.join(timeout=2)
                self.assertFalse(held[0].thread.is_alive())

    def test_callback_failure_never_logs_and_invalidates_result(self):
        output=io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            self.root.report_callback_exception(ValueError, ValueError('PRIVATE_SENTINEL'), None)
        self.assertEqual(self.app.callback_errors, 1)
        self.assertEqual(output.getvalue(), '')
        self.assertEqual(self.app.status.get(), desktop.FAILURE)
        self.assertIsNone(self.app.last_result)


if __name__ == '__main__':
    unittest.main()
