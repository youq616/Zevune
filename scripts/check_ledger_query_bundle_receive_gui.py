#!/usr/bin/env python3
"""Actual Tk, actual pack bytes and actual unpack/check; no success substitutes."""
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

sys.path.insert(0, str(Path(__file__).resolve().parent/'tests'))
from test_ledger_query_bundle_receive import fixture
import ledger_query_bundle_receive_desktop as desktop


def wait(app):
    end = time.monotonic() + 8
    while app.job is not None and time.monotonic() < end:
        app.root.update(); time.sleep(0.005)
    assert app.job is None, 'worker did not end'


class GuiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='receive-gui-'); self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name).resolve(); self.values, self.raw = fixture(self.folder)
        self.root = tk.Tk(); self.app = desktop.Workbench(self.root); self.gates = []
        self.addCleanup(self.cleanup)
        for key, value in self.values.items(): self.app.values[key].set(value)
        self.root.update()

    def cleanup(self):
        for release in self.gates: release.set()
        if self.app.job is not None and self.app.job.thread.ident is not None:
            self.app.job.thread.join(8); assert not self.app.job.thread.is_alive()
        if self.app.phase != 'closed': self.app.cancel_poll(); self.root.destroy()

    def dest(self): return Path(self.values['destination'])

    def start(self):
        self.app.review_button.invoke(); assert self.app.phase == 'review'
        self.app.confirm_button.invoke()

    def blocked_write(self):
        original = desktop.receive.files.write_new
        entered, release = threading.Event(), threading.Event(); self.gates.append(release)
        calls = []
        def write(path, data):
            calls.append((path, threading.get_ident()))
            entered.set(); assert release.wait(8)
            return original(path, data)
        return entered, release, calls, write

    def test_real_unpack_copy_and_explicit_directory_recheck(self):
        self.root.clipboard_clear(); self.root.clipboard_append('KEEP')
        self.start(); wait(self.app)
        self.assertIs(type(self.app.last), desktop.receive.Display)
        self.assertEqual(self.root.clipboard_get(), 'KEEP')
        self.app.copy_button.invoke(); self.assertEqual(self.root.clipboard_get(), self.values['bundle_sha256'])
        self.app.values['operation'].set('verify-directory')
        self.assertIsNone(self.app.last)
        self.start(); wait(self.app)
        self.assertIn('不证明以前还原调用成功', self.app.last.text)
        self.assertEqual(Path(self.values['bundle']).read_bytes(), self.raw)

    def test_review_lists_32_files_and_all_pins_without_writing(self):
        Path(self.values['bundle']).unlink(); values, _ = fixture(self.folder, 32)
        for k,v in values.items(): self.app.values[k].set(v)
        with patch.object(desktop.receive.bundle, 'unpack', side_effect=AssertionError('implicit write')) as write:
            self.app.review()
        self.assertEqual(write.call_count, 0); self.assertFalse(self.dest().exists())
        self.assertIsNone(self.app.job)
        text = self.app.details.get('1.0','end')
        for entry in desktop.receive.bundle.decode(Path(values['bundle']).read_bytes(),values['bundle_sha256']):
            self.assertIn(entry.sha256,text)
        self.assertIn('32-report.json',text); self.assertIn(values['destination'],text)

    def test_default_cancel_enter_escape_never_starts(self):
        self.root.focus_force(); self.root.update(); self.app.review(); self.root.update()
        self.assertIs(self.root.focus_get(),self.app.cancel_button)
        with patch.object(desktop,'ReceiveJob',side_effect=AssertionError('implicit job')) as factory:
            self.app.cancel_button.event_generate('<KeyPress-Return>');self.root.update()
            if self.app.phase == 'review':
                self.app.cancel_button.event_generate('<KeyPress-Escape>');self.root.update()
        self.assertEqual(factory.call_count,0);self.assertIsNone(self.app.job);self.assertFalse(self.dest().exists())

    def test_background_review_does_not_force_focus(self):
        other=tk.Tk()
        try:
            other.update();other.focus_force();other.update();self.root.update()
            self.app.review();self.root.update()
            self.assertIsNone(self.root.focus_get());self.assertIs(self.root.focus_lastfor(),self.app.cancel_button)
        finally:other.destroy()

    def test_cancel_review_and_close_do_not_create_anything(self):
        self.app.review();self.app.cancel_review();self.assertEqual(self.app.phase,'idle')
        self.app.review();self.app.close();self.assertEqual(self.app.phase,'closed');self.assertFalse(self.dest().exists())

    def test_each_field_change_revokes_confirmation(self):
        for key in desktop.receive.FIELDS:
            for k,v in self.values.items():self.app.values[k].set(v)
            self.app.review();self.assertIsNotNone(self.app.intent)
            self.app.values[key].set('changed')
            self.assertIsNone(self.app.intent);self.assertEqual(self.app.phase,'idle')
        self.assertFalse(self.dest().exists())

    def test_bypassed_trace_before_confirm_cannot_write(self):
        self.app.review();value=self.app.values['destination']
        for mode,name in value.trace_info():value.trace_remove(mode,name)
        value.set(str(self.folder/'unreviewed'))
        with patch.object(desktop,'ReceiveJob',side_effect=AssertionError('unreviewed')) as job:self.app.confirm()
        self.assertEqual(job.call_count,0);self.assertFalse(self.dest().exists())

    def test_same_bytes_bundle_replacement_after_review_refuses_worker_write(self):
        self.app.review();path=Path(self.values['bundle']);path.rename(self.folder/'held');path.write_bytes(self.raw)
        with patch.object(desktop.receive.bundle,'unpack',side_effect=AssertionError('wrong identity')) as write:
            self.app.confirm();wait(self.app)
        self.assertEqual(write.call_count,0);self.assertFalse(self.dest().exists());self.assertIsNone(self.app.last)

    def test_target_created_after_review_is_retained_not_overwritten(self):
        self.app.review();self.dest().mkdir();(self.dest()/'keep').write_bytes(b'KEEP')
        self.app.confirm();wait(self.app)
        self.assertIsNone(self.app.last);self.assertEqual(list(p.name for p in self.dest().iterdir()),['keep'])

    def test_partial_write_failure_preserves_directory_and_disables_copy(self):
        real=desktop.receive.files.write_new;calls=[]
        def fail(path,data):
            calls.append(path);real(path,data[:20]);raise OSError('PRIVATE')
        stream=io.StringIO()
        with patch.object(desktop.receive.files,'write_new',fail),contextlib.redirect_stderr(stream):
            self.start();wait(self.app)
        self.assertEqual(stream.getvalue(),'');self.assertTrue(self.dest().exists());self.assertEqual(len(calls),1)
        self.assertEqual(len(calls[0].read_bytes()),20);self.assertIsNone(self.app.last)
        self.assertTrue(self.app.copy_button.instate(['disabled']));self.assertIn('部分',self.app.status.get())

    def test_running_ui_remains_responsive_no_reentry_and_write_off_main(self):
        entered,release,calls,write=self.blocked_write()
        with patch.object(desktop.receive.files,'write_new',write):
            self.start();self.assertTrue(entered.wait(3));self.assertTrue(self.app.busy)
            self.app.confirm();self.app.review();self.app.clear();self.app.cancel_review()
            ticks=[];self.root.after(5,lambda:ticks.append(1))
            end=time.monotonic()+0.08
            while time.monotonic()<end:self.root.update();time.sleep(0.005)
            self.assertEqual(ticks,[1]);self.assertEqual(len(calls),1)
            self.assertNotEqual(calls[0][1],threading.get_ident())
            release.set();wait(self.app)
        self.assertEqual(len(calls),2);self.assertIsNotNone(self.app.last)

    def test_close_waits_for_actual_write_and_no_rollback(self):
        entered,release,calls,write=self.blocked_write()
        with patch.object(desktop.receive.files,'write_new',write):
            self.start();self.assertTrue(entered.wait(3));job=self.app.job
            self.app.close();self.app.close()
            self.assertIs(self.app.job,job);self.assertEqual(self.app.phase,'closing');self.assertTrue(self.root.winfo_exists())
            release.set();wait(self.app)
        self.assertEqual(self.app.phase,'closed');self.assertFalse(job.thread.is_alive())
        self.assertEqual(len(list(self.dest().iterdir())),2)

    def test_input_change_while_writing_discards_late_success_without_rollback(self):
        entered,release,_,write=self.blocked_write()
        with patch.object(desktop.receive.files,'write_new',write):
            self.start();self.assertTrue(entered.wait(3))
            self.app.values['bundle_sha256'].set('0'*64);release.set();wait(self.app)
        self.assertIsNone(self.app.last);self.assertEqual(len(list(self.dest().iterdir())),2)

    def test_status_trace_during_review_cannot_restore_revoked_approval(self):
        def changed(*_):
            if self.app.status.get().startswith('完整包已核验'):self.app.values['destination'].set(str(self.folder/'other'))
        token=self.app.status.trace_add('write',changed)
        try:
            self.app.review();self.assertIsNone(self.app.intent);self.assertEqual(self.app.phase,'idle')
            self.assertTrue(self.app.confirm_button.instate(['disabled']))
        finally:self.app.status.trace_remove('write',token)

    def test_status_trace_at_publish_cannot_restore_revoked_success(self):
        def changed(*_):
            if self.app.status.get().startswith('所选操作完成'):self.app.values['bundle_sha256'].set('0'*64)
        token=self.app.status.trace_add('write',changed)
        try:
            self.start();wait(self.app);self.assertIsNone(self.app.last)
            self.assertTrue(self.app.copy_button.instate(['disabled']))
        finally:self.app.status.trace_remove('write',token)

    def test_bypassed_trace_prevents_copy_after_completion(self):
        self.start();wait(self.app);value=self.app.values['destination']
        for mode,name in value.trace_info():value.trace_remove(mode,name)
        value.set(str(self.folder/'other'));self.root.clipboard_clear();self.root.clipboard_append('KEEP')
        self.app.copy();self.assertIsNone(self.app.last);self.assertEqual(self.root.clipboard_get(),'KEEP')

    def test_unknown_start_stays_owned_no_retry(self):
        self.app.review()
        with patch.object(threading.Thread,'start',side_effect=RuntimeError('PRIVATE')):self.app.confirm()
        self.assertIsNotNone(self.app.job);self.assertIsNone(self.app.job.request[0])
        self.assertEqual(self.app.phase,'running');self.app.close();self.assertEqual(self.app.phase,'closing')
        self.assertFalse(self.dest().exists())

    def test_poll_registration_failure_close_resumes_same_operation(self):
        entered,release,calls,write=self.blocked_write();actual=self.root.after;first=[]
        def interrupted(ms,func=None,*args):
            token=actual(ms,func,*args)
            if ms==50 and not first:first.append(1);raise tk.TclError('PRIVATE')
            return token
        with patch.object(desktop.receive.files,'write_new',write),patch.object(self.root,'after',interrupted):
            self.start();self.assertTrue(entered.wait(3));job=self.app.job
            self.assertIsNone(self.app.poll_ticket);self.app.close();self.assertIs(self.app.job,job)
            release.set();wait(self.app)
        self.assertEqual(self.app.phase,'closed');self.assertEqual(len(calls),2)

    def test_callback_failure_keeps_running_job_and_loses_display(self):
        entered,release,_,write=self.blocked_write()
        with patch.object(desktop.receive.files,'write_new',write):
            self.start();self.assertTrue(entered.wait(3));job=self.app.job
            self.app.callback_error(ValueError,ValueError('PRIVATE'),None);self.assertIs(self.app.job,job)
            release.set();wait(self.app)
        self.assertIsNone(self.app.last)

    def test_select_controls_do_not_export_selection_and_no_implicit_load(self):
        pending=[self.root]
        while pending:
            widget=pending.pop();pending.extend(widget.winfo_children())
            if 'exportselection' in widget.keys():self.assertFalse(int(widget.cget('exportselection')))
        with patch.object(self.app.filedialog,'askopenfilename',return_value=self.values['bundle']), \
             patch.object(desktop.receive,'approve',side_effect=AssertionError('implicit load')) as load:self.app.choose()
        self.assertEqual(load.call_count,0);self.assertIsNone(self.app.job)

    def test_clear_and_failed_destroy_never_delete_output(self):
        self.start();wait(self.app);self.app.clear();self.assertTrue(self.dest().exists())
        self.assertTrue(all(not value.get() for value in self.app.values.values()))
        with patch.object(self.root,'destroy',side_effect=tk.TclError('PRIVATE')):
            with self.assertRaises(tk.TclError):self.app.close()
        self.assertEqual(self.app.phase,'closing');self.app.close();self.assertEqual(self.app.phase,'closed')
        self.assertEqual(len(list(self.dest().iterdir())),2)


if __name__=='__main__':unittest.main()
