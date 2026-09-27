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
from test_ledger_transaction_batch_once_desktop import values
import ledger_transaction_batch_once_desktop as desktop


def disabled(widget):
    return str(widget.cget('state')) == 'disabled'


def replace_ids(app, text):
    # Deliberate programmatic bypass of disabled input, only in the test driver.
    state = app.txids.cget('state')
    app.txids.configure(state='normal')
    app.txids.delete('1.0', 'end')
    app.txids.insert('1.0', text)
    app.txids.configure(state=state)


def wait(app, limit=4):
    end = time.monotonic() + limit
    while app.job is not None and time.monotonic() < end:
        app.root.update()
        time.sleep(0.005)
    assert app.job is None, 'owned job did not complete within test budget'


class BatchWidgetTests(unittest.TestCase):
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
        self.app.txids.insert('1.0', 'a' * 64 + '\n' + 'c' * 64)
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
        # Programmatic invoke is not a user click and does not activate a
        # Windows top-level. Activate only this test-owned window first.
        self.root.focus_force()
        self.root.update()
        with patch.object(desktop.once, 'lookup_batch_once', side_effect=AssertionError('must not run')), \
                patch.object(desktop, 'OnceJob', side_effect=AssertionError('must not construct')):
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

    def test_background_review_remembers_cancel_without_stealing_focus(self):
        # A separate Tcl application owns the foreground. The product must use
        # remembered in-window focus, never force itself above another app.
        other = tk.Tk()
        try:
            other.update()
            other.focus_force()
            other.update()
            self.root.update()
            self.assertIsNone(self.root.focus_get())
            self.app.review()
            self.root.update()
            self.assertIsNone(self.root.focus_get())
            self.assertIs(other.focus_get(), other)
            self.assertIs(self.root.focus_lastfor(), self.app.cancel_button)
            self.assertEqual(self.app.phase, 'review')
            self.assertIsNone(self.app.job)
        finally:
            other.destroy()

    def test_return_never_confirms_and_escape_cancels_review(self):
        self.root.focus_force()
        self.root.update()
        with patch.object(desktop, 'OnceJob', side_effect=AssertionError('no implicit job')) as factory:
            self.app.review()
            self.root.update()
            self.assertIs(self.root.focus_get(), self.app.cancel_button)
            self.app.cancel_button.event_generate('<KeyPress-Return>')
            self.root.update()
            self.assertIsNone(self.app.job)
            self.assertIn(self.app.phase, ('idle', 'review'))
            if self.app.phase == 'review':
                self.app.cancel_button.event_generate('<KeyPress-Escape>')
                self.root.update()
            self.assertEqual(self.app.phase, 'idle')
            self.assertEqual(factory.call_count, 0)

    def test_invalid_form_never_enters_review_or_starts_job(self):
        for key, bad in (('backend_sha256', 'x'), ('checkpoint', 'x'), ('journal', 'relative')):
            before = self.app.values[key].get()
            self.app.values[key].set(bad)
            with patch.object(desktop, 'OnceJob', side_effect=AssertionError('no task')):
                self.app.review()
            self.assertEqual(self.app.phase, 'idle')
            self.assertEqual(self.app.status.get(), desktop.previous.FAILURE)
            self.assertIsNone(self.app.intent)
            self.app.values[key].set(before)

    def test_programmatic_change_revokes_review(self):
        self.app.review()
        replace_ids(self.app, '0' * 64)
        self.app.confirm()
        self.assertEqual(self.app.phase, 'idle')
        self.assertIsNone(self.app.intent)
        self.assertIsNone(self.app.job)
        self.assertTrue(self.app.confirm_button.instate(['disabled']))

    def test_close_in_review_never_starts_native(self):
        self.app.review()
        with patch.object(desktop, 'OnceJob', side_effect=AssertionError('no task')):
            self.app.close()
        self.assertEqual(self.app.phase, 'closed')
        self.assertIsNone(self.app.job)

    def test_failure_worker_is_off_tk_thread_and_redacted(self):
        gate, entered, calls, refuse = self.blocked()
        out = io.StringIO()
        with patch.object(desktop.once, 'lookup_batch_once', side_effect=refuse), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            self.start()
            self.assertTrue(entered.wait(timeout=1))
            self.assertNotEqual(calls[0], threading.get_ident())
            gate.set()
            wait(self.app)
        self.assertEqual(self.app.phase, 'idle')
        self.assertEqual(self.app.status.get(), desktop.previous.FAILURE)
        self.assertEqual(out.getvalue(), '')
        self.assertIsNone(self.app.last)

    def test_event_loop_responsive_and_repeated_confirm_never_replays_twice(self):
        gate, entered, calls, refuse = self.blocked()
        with patch.object(desktop.once, 'lookup_batch_once', side_effect=refuse):
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
            self.assertTrue(all(disabled(widget) for widget in self.app.controls))
            gate.set()
            wait(self.app)

    def test_close_and_repeated_close_wait_for_actual_worker_exit(self):
        gate, entered, calls, refuse = self.blocked()
        with patch.object(desktop.once, 'lookup_batch_once', side_effect=refuse):
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
        with patch.object(desktop.once, 'lookup_batch_once', side_effect=refuse):
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
        with patch.object(desktop, 'OnceJob', side_effect=MemoryError('PRIVATE')):
            self.app.confirm()
        self.assertEqual(self.app.phase, 'idle')
        self.assertIsNone(self.app.job)
        self.assertIsNone(self.app.intent)
        self.assertEqual(self.app.status.get(), desktop.previous.FAILURE)

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
        actual = desktop.OnceJob
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
            with patch.object(desktop, 'OnceJob', side_effect=factory), \
                    patch.object(desktop.once, 'lookup_batch_once', side_effect=AssertionError('withdrawn')) as call:
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
        with patch.object(desktop.once, 'lookup_batch_once', side_effect=refuse), patch.object(self.root, 'after', side_effect=after):
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




    def test_all_32_ids_reviewed_in_order_and_modified_notification_is_consumed(self):
        ids = [f'{i:064x}' for i in range(32)]
        replace_ids(self.app, '\r\n'.join(ids) + '\r\n')
        self.app.review()  # No event pumping before the explicit action.
        self.assertEqual(self.app.phase, 'review')
        text = self.app.details.get('1.0', 'end')
        positions = [text.index(f'{i+1:02d}  {txid}') for i, txid in enumerate(ids)]
        self.assertEqual(positions, sorted(positions))
        revision = self.app.revision
        self.root.update()  # Queued reset events must not revoke an unchanged review.
        self.assertEqual(self.app.phase, 'review')
        self.assertEqual(self.app.revision, revision)
        self.assertEqual(self.app.intent.txids, tuple(ids))

    def test_invalid_or_oversized_multiline_input_never_constructs_job(self):
        for text in ('a'*64+'\n\n', 'a'*64+'\n'+'a'*64, 'x'*10000):
            replace_ids(self.app, text)
            with patch.object(desktop, 'OnceJob', side_effect=AssertionError('must not start')):
                self.app.review()
            self.assertEqual(self.app.phase, 'idle')
            self.assertEqual(self.app.status.get(), desktop.previous.FAILURE)
        with patch.object(self.app.txids, 'get', side_effect=AssertionError('oversized materialization')) as get:
            self.app.review()
        self.assertEqual(get.call_count, 0)

    def test_multiline_change_before_queued_event_revokes_review(self):
        self.app.review()
        replace_ids(self.app, 'f'*64)
        with patch.object(desktop, 'OnceJob', side_effect=AssertionError('stale review')) as jobs:
            self.app.confirm()
        self.assertEqual(jobs.call_count, 0)
        self.assertEqual(self.app.phase, 'idle')
        self.assertIsNone(self.app.intent)

    def test_multiline_change_while_running_revokes_result_without_another_job(self):
        gate, entered, calls, refuse = self.blocked()
        with patch.object(desktop.once, 'lookup_batch_once', side_effect=refuse):
            self.start()
            self.assertTrue(entered.wait(timeout=1))
            held = self.app.job
            revision = self.app.active_revision
            replace_ids(self.app, 'e'*64)
            self.root.update()
            self.assertGreater(self.app.revision, revision)
            self.assertIs(self.app.job, held)
            self.assertEqual(self.app.phase, 'running')
            gate.set(); wait(self.app)
        self.assertEqual(len(calls), 1)
        self.assertIsNone(self.app.last)

    def test_clear_also_removes_all_multiline_ids(self):
        self.app.clear()
        self.root.update()
        self.assertEqual(self.app.txids.get('1.0', 'end-1c'), '')
        self.assertEqual(self.app._observed_text, '')
        self.assertEqual(self.app.callback_errors, 0)

    def test_original_single_and_new_batch_windows_do_not_replace_each_others_core(self):
        from test_ledger_transaction_desktop import values as single_values
        root = tk.Tk()
        old = desktop.previous.single_ui.Workbench(root)
        single_calls, batch_calls = [], []
        def single_refuse(intent):
            single_calls.append(type(intent)); raise ValueError('refusal only')
        def batch_refuse(intent):
            batch_calls.append(type(intent)); raise ValueError('refusal only')
        try:
            for key, value in single_values(self.path).items(): old.values[key].set(value)
            with patch.object(desktop.previous.single_ui.lookup, 'lookup', side_effect=single_refuse), \
                    patch.object(desktop.once, 'lookup_batch_once', side_effect=batch_refuse):
                old.review(); old.confirm(); self.start()
                wait(old); wait(self.app)
            self.assertEqual(single_calls, [desktop.once.single.Intent])
            self.assertEqual(batch_calls, [desktop.once.Intent])
            self.assertIsNone(old.last); self.assertIsNone(self.app.last)
        finally:
            if old.job is not None:
                old.job.thread.join(timeout=4)
                self.assertFalse(old.job.thread.is_alive())
            old.cancel_poll(); root.destroy()

    def test_new_review_states_one_pass_and_isolates_old_batch_window(self):
        old_root = tk.Tk()
        old_app = desktop.previous.Workbench(old_root)
        try:
            for key, value in values(self.path).items():
                old_app.values[key].set(value)
            replace_ids(old_app, 'a'*64)
            old_root.update()
            self.app.review()
            old_app.review()
            self.assertIn('一次完整记录定位', self.app.details.get('1.0', 'end'))
            self.assertIn('再逐ID完整扫描', old_app.details.get('1.0', 'end'))
            self.app.cancel_review(); old_app.cancel_review()
            new_calls, old_calls = [], []
            def new_refuse(intent):
                new_calls.append(1); raise RuntimeError('refusal')
            def old_refuse(intent):
                old_calls.append(1); raise RuntimeError('refusal')
            with patch.object(desktop.once, 'lookup_batch_once', side_effect=new_refuse), \
                    patch.object(desktop.previous.batch, 'lookup_batch', side_effect=old_refuse):
                self.start(); wait(self.app)
                old_app.review(); old_app.confirm(); wait(old_app)
            self.assertEqual(new_calls, [1]); self.assertEqual(old_calls, [1])
            self.assertIsNone(self.app.last); self.assertIsNone(old_app.last)
        finally:
            if old_app.job is not None:
                old_app.job.thread.join(timeout=4)
                assert not old_app.job.thread.is_alive()
            old_app.cancel_poll(); old_root.destroy()

    def test_old_display_cannot_gain_copy_permission_in_new_window(self):
        self.root.clipboard_clear(); self.root.clipboard_append('KEEP')
        # Inert display metadata only, to exercise type rejection, not authentication.
        old = desktop.previous.BatchDisplay('inert', None, ('a'*64,))
        self.assertFalse(self.app._valid_display(old))
        self.app.last = old
        self.app.active_revision = self.app.revision
        self.app.copy()
        self.assertEqual(self.root.clipboard_get(), 'KEEP')


if __name__ == '__main__':
    unittest.main()
