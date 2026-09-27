#!/usr/bin/env python3
"""Real Tk with actual pinned task files and refusing workers; no fake native success."""
import contextlib
from dataclasses import replace
import io
from pathlib import Path
import sys
import tempfile
import threading
import time
import tkinter as tk
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parent/'tests'))
from test_ledger_query_request_desktop import fixture, metadata
import ledger_query_request_desktop as desktop


def disabled(widget):
    return str(widget.cget('state')) == 'disabled'


def wait(app, limit=4):
    end=time.monotonic()+limit
    while app.job is not None and time.monotonic()<end:
        app.root.update();time.sleep(0.005)
    assert app.job is None,'owned worker did not finish'


class WidgetTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='task-desktop-ui-')
        self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name).resolve()
        self.input,self.approval=fixture(self.path)
        self.original=self.approval.form.request.read_bytes()
        self.root=tk.Tk();self.app=desktop.Workbench(self.root);self.gates=[]
        self.addCleanup(self.cleanup)
        for key,value in self.input.items():self.app.values[key].set(value)
        self.root.update()

    def cleanup(self):
        for gate in self.gates:gate.set()
        job=self.app.job
        if job is not None and job.thread.ident is not None:
            job.thread.join(timeout=4)
            assert not job.thread.is_alive(),'test leaked worker'
        if self.app.phase!='closed':
            self.app.cancel_poll();self.root.destroy()

    def blocked(self):
        gate,entered,calls=threading.Event(),threading.Event(),[]
        self.gates.append(gate)
        def refuse(approval):
            calls.append(threading.get_ident());entered.set();gate.wait(timeout=4)
            raise RuntimeError('PRIVATE_SENTINEL')
        return gate,entered,calls,refuse

    def start(self):
        self.app.review_button.invoke()
        assert self.app.phase=='review' and self.app.job is None
        self.app.confirm_button.invoke()

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
        with patch.object(desktop, 'RequestJob', side_effect=AssertionError('no implicit job')) as factory:
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


    def test_close_in_review_never_starts_native(self):
        self.app.review()
        with patch.object(desktop, 'RequestJob', side_effect=AssertionError('no task')):
            self.app.close()
        self.assertEqual(self.app.phase, 'closed')
        self.assertIsNone(self.app.job)


    def test_failure_worker_is_off_tk_thread_and_redacted(self):
        gate, entered, calls, refuse = self.blocked()
        out = io.StringIO()
        with patch.object(desktop, 'execute', side_effect=refuse), \
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
        with patch.object(desktop, 'execute', side_effect=refuse):
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
        with patch.object(desktop, 'execute', side_effect=refuse):
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
        with patch.object(desktop, 'execute', side_effect=refuse):
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
        with patch.object(desktop, 'RequestJob', side_effect=MemoryError('PRIVATE')):
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


    def test_real_os_start_interruption_retains_ui_until_acknowledgement(self):
        actual = desktop.RequestJob
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
            with patch.object(desktop, 'RequestJob', side_effect=factory), \
                    patch.object(desktop, 'execute', side_effect=AssertionError('withdrawn')) as call:
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
        with patch.object(desktop, 'execute', side_effect=refuse), patch.object(self.root, 'after', side_effect=after):
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


    def test_review_loads_only_pinned_task_and_lists_all_inputs(self):
        self.root.focus_force();self.root.update()
        with patch.object(desktop.task,'run_request',side_effect=AssertionError('no implicit query')) as query, \
                patch.object(desktop,'RequestJob',side_effect=AssertionError('no worker before consent')):
            self.app.review_button.invoke();self.root.update()
            self.assertEqual(self.app.phase,'review')
            self.assertIs(self.root.focus_get(),self.app.cancel_button)
            text=self.app.details.get('1.0','end')
            for value in (*self.input.values(),*self.approval.snapshot.request.txids):self.assertIn(value,text)
            self.app.cancel_button.invoke()
        self.assertEqual(query.call_count,0)
        self.assertEqual(self.app.phase,'idle');self.assertIsNone(self.app.intent)
        self.assertEqual(self.approval.form.request.read_bytes(),self.original)

    def test_invalid_form_or_bad_pin_never_constructs_job(self):
        for key,bad in (('request_sha256','x'),('request_sha256','0'*64),('journal','relative'),('backend','relative')):
            original=self.app.values[key].get();self.app.values[key].set(bad)
            with patch.object(desktop,'RequestJob',side_effect=AssertionError('invalid job')) as factory:
                self.app.review()
            self.assertEqual(factory.call_count,0);self.assertEqual(self.app.phase,'idle')
            self.assertIsNone(self.app.intent);self.assertIsNone(self.app.last)
            self.app.values[key].set(original)

    def test_choosing_file_does_not_load_task_or_run(self):
        with patch.object(self.app.filedialog,'askopenfilename',return_value=self.input['request']), \
                patch.object(desktop.task,'load',side_effect=AssertionError('choose cannot load')) as load:
            self.app.choose('request')
        self.assertEqual(load.call_count,0);self.assertEqual(self.app.phase,'idle')
        self.assertIsNone(self.app.intent);self.assertIsNone(self.app.job)

    def test_bypassed_variable_trace_cannot_confirm_stale_local_paths(self):
        self.app.review()
        value=self.app.values['backend']
        for mode,name in value.trace_info():value.trace_remove(mode,name)
        value.set(str(self.path/'unreviewed-backend'))
        with patch.object(desktop,'RequestJob',side_effect=AssertionError('stale approval')) as factory:
            self.app.confirm()
        self.assertEqual(factory.call_count,0);self.assertEqual(self.app.phase,'idle')
        self.assertIsNone(self.app.intent)

    def test_task_same_bytes_replaced_after_review_cannot_execute(self):
        self.app.review()
        path=self.approval.form.request
        path.rename(self.path/'held');path.write_bytes(self.original)
        with patch.object(desktop.task,'run_request',side_effect=AssertionError('changed approval')) as query:
            self.app.confirm();wait(self.app)
        self.assertEqual(query.call_count,0);self.assertIsNone(self.app.last)
        self.assertEqual(self.app.phase,'idle')
        self.assertEqual(path.read_bytes(),self.original)

    def test_input_change_during_actual_task_read_discards_approval(self):
        original=desktop.approve
        def changed(form):
            result=original(form)
            self.app.values['backend'].set(str(self.path/'other'))
            return result
        with patch.object(desktop,'approve',side_effect=changed):self.app.review()
        self.assertEqual(self.app.phase,'idle');self.assertIsNone(self.app.intent)
        self.assertTrue(self.app.confirm_button.instate(['disabled']))
        self.assertEqual(self.app.details.get('1.0','end').strip(),'')

    def test_all_32_ids_shown_in_original_order(self):
        folder=self.path/'many';folder.mkdir()
        fields,approval=fixture(folder,32)
        for key,value in fields.items():self.app.values[key].set(value)
        self.app.review()
        self.assertEqual(self.app.phase,'review')
        text=self.app.details.get('1.0','end')
        positions=[text.index(f'{i+1:02d}  {txid}') for i,txid in enumerate(approval.snapshot.request.txids)]
        self.assertEqual(positions,sorted(positions))
        self.assertEqual(self.app.intent,approval)

    def test_pure_display_copy_is_explicit_ordered_and_bound(self):
        # Exercise only the GUI's immutable presentation/clipboard boundary.
        # No worker is fed this synthetic metadata; native success is not simulated.
        self.app.review();approval=self.app.intent;self.app.cancel_review()
        display=desktop.present(metadata(approval),approval)
        self.app.last=display;self.app.active_revision=self.app.revision
        self.root.clipboard_clear();self.root.clipboard_append('KEEP')
        self.assertEqual(self.root.clipboard_get(),'KEEP')
        self.app.copy()
        self.assertEqual(self.root.clipboard_get(),'\n'.join(approval.snapshot.request.txids))
        self.root.clipboard_clear();self.root.clipboard_append('KEEP')
        self.app.last=replace(display,request_sha256='f'*64)
        self.app.copy();self.assertEqual(self.root.clipboard_get(),'KEEP')
        self.app.last=display
        value=self.app.values['request_sha256']
        for mode,name in value.trace_info():value.trace_remove(mode,name)
        value.set('0'*64)
        self.app.copy();self.assertEqual(self.root.clipboard_get(),'KEEP');self.assertIsNone(self.app.last)

    def test_old_display_has_no_copy_permission_and_clear_does_not_delete_task(self):
        self.app.review();self.app.cancel_review()
        self.root.clipboard_clear();self.root.clipboard_append('KEEP')
        self.app.last=desktop.once_ui.OnceDisplay('inert',None,self.approval.snapshot.request.txids)
        self.app.active_revision=self.app.revision
        self.app.copy();self.assertEqual(self.root.clipboard_get(),'KEEP')
        self.app.clear()
        self.assertTrue(all(not v.get() for v in self.app.values.values()))
        self.assertEqual(self.approval.form.request.read_bytes(),self.original)
        self.assertEqual(self.root.clipboard_get(),'KEEP')

    def test_old_manual_and_task_windows_keep_separate_execution(self):
        from test_ledger_transaction_batch_once_desktop import values
        root=tk.Tk();old=desktop.once_ui.Workbench(root);calls=[]
        try:
            for key,value in values(self.path).items():old.values[key].set(value)
            old.txids.insert('1.0','a'*64)
            def refuse_task(approval):calls.append('task');raise ValueError('refusal')
            def refuse_manual(intent):calls.append('manual');raise ValueError('refusal')
            with patch.object(desktop,'execute',side_effect=refuse_task), \
                    patch.object(desktop.once_ui.once,'lookup_batch_once',side_effect=refuse_manual):
                self.start();wait(self.app)
                old.review();old.confirm();wait(old)
            self.assertEqual(calls,['task','manual']);self.assertIsNone(self.app.last);self.assertIsNone(old.last)
        finally:
            if old.job is not None:
                old.job.thread.join(timeout=4);assert not old.job.thread.is_alive()
            old.cancel_poll();root.destroy()


if __name__=='__main__':unittest.main()
