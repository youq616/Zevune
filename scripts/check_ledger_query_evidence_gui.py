#!/usr/bin/env python3
"""Actual Tk and genuine task/report files. Positive results use the real C29 API."""
import contextlib
from dataclasses import replace
import io
from pathlib import Path
import subprocess
import sys
import tempfile
import tkinter as tk
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parent/'tests'))
from test_ledger_query_evidence_desktop import fixture, fields
import ledger_query_evidence_desktop as desktop


class GuiTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='evidence-gui-')
        self.addCleanup(self.temp.cleanup)
        self.folder=Path(self.temp.name).resolve()
        self.sources,self.requests=fixture(self.folder)
        self.original={p.name:p.read_bytes() for p in self.folder.iterdir()}
        self.root=tk.Tk(); self.app=desktop.Workbench(self.root)
        self.addCleanup(self.cleanup)
        self.fill('task','report'); self.root.update()

    def cleanup(self):
        if not self.app.closed: self.root.destroy()

    def fill(self,a,b):
        values=fields(self.sources[0][a],self.sources[1][b])
        for k,v in values.items(): self.app.values[k].set(v)

    def text(self): return self.app.output.get('1.0','end').rstrip('\n')

    def test_real_four_modes_and_explicit_clipboard_copy(self):
        for a in ('task','report'):
            for b in ('task','report'):
                self.fill(a,b)
                self.root.clipboard_clear(); self.root.clipboard_append('KEEP')
                self.app.compare_button.invoke()
                self.assertIs(type(self.app.last),desktop.Display)
                self.assertEqual(self.text(),self.app.last.text)
                self.assertEqual(self.root.clipboard_get(),'KEEP')
                self.app.copy_button.invoke()
                self.assertEqual(self.root.clipboard_get(),self.app.last.text)
        self.assertEqual(self.original,{p.name:p.read_bytes() for p in self.folder.iterdir()})

    def test_details_choice_clears_old_result_and_requires_new_comparison(self):
        self.app.begin(); summary=self.text()
        self.assertNotIn(self.requests[0].txids[0],summary)
        self.app.disclosure.set(True)
        self.assertIsNone(self.app.last); self.assertEqual(self.text(),'')
        self.app.begin(); self.assertIn(self.requests[0].txids[0],self.text())
        self.app.disclosure.set(False)
        self.assertIsNone(self.app.last); self.assertEqual(self.text(),'')
        self.app.begin(); self.assertEqual(self.text(),summary)

    def test_all_six_inputs_invalidate_existing_result(self):
        for key in desktop.FIELDS:
            self.fill('task','report'); self.app.begin()
            self.assertIsNotNone(self.app.last)
            self.app.values[key].set('changed')
            self.assertIsNone(self.app.last); self.assertEqual(self.text(),'')
            self.assertTrue(self.app.copy_button.instate(['disabled']))

    def test_bypassed_traces_cannot_copy_stale_details_or_paths(self):
        self.app.disclosure.set(True); self.app.begin()
        for value in (self.app.disclosure,self.app.values['before_path']):
            for mode,name in value.trace_info(): value.trace_remove(mode,name)
        self.root.clipboard_clear(); self.root.clipboard_append('KEEP')
        self.app.disclosure.set(False); self.app.copy()
        self.assertIsNone(self.app.last); self.assertEqual(self.root.clipboard_get(),'KEEP')
        self.app.begin(); self.app.values['before_path'].set(str(self.folder/'missing'));self.app.copy()
        self.assertIsNone(self.app.last); self.assertEqual(self.root.clipboard_get(),'KEEP')

    def test_stale_changed_input_during_read_never_shown(self):
        real=desktop.inspect
        def changed(intent):
            result=real(intent)
            value=self.app.values['after_sha256']
            for mode,name in value.trace_info(): value.trace_remove(mode,name)
            value.set('0'*64)
            return result
        with patch.object(desktop,'inspect',side_effect=changed): self.app.begin()
        self.assertIsNone(self.app.last); self.assertEqual(self.text(),'')
        self.assertFalse(self.app.busy)

    def test_invalid_type_or_pin_clears_previous_success(self):
        for key,value in (('before_kind',''),('before_kind','auto'),('after_sha256','0'*64)):
            self.fill('task','report');self.app.begin();self.assertIsNotNone(self.app.last)
            self.app.values[key].set(value);self.app.begin()
            self.assertIsNone(self.app.last);self.assertEqual(self.text(),'')
            self.assertEqual(self.app.status.get(),desktop.FAILURE)

    def test_swap_moves_all_three_fields_without_reading_or_writing(self):
        before=self.app._raw();self.app.begin()
        with patch.object(desktop,'inspect',side_effect=AssertionError('swap read inputs')) as read:
            self.app.swap_button.invoke()
        after=self.app._raw()
        self.assertEqual(after,(*before[3:6],*before[:3],False))
        self.assertEqual(read.call_count,0);self.assertIsNone(self.app.last)
        self.app.begin();self.assertIsNotNone(self.app.last)
        self.app.swap();self.assertEqual(self.app._raw(),before)

    def test_file_selection_does_not_infer_kind_or_digest(self):
        old=self.app._raw()
        with patch.object(self.app.filedialog,'askopenfilename',return_value=str(self.folder/'other.json')), \
                patch.object(desktop.comparison,'compare',side_effect=AssertionError('automatic compare')) as call:
            self.app.choose('before')
        self.assertEqual(call.call_count,0)
        self.assertEqual(self.app.values['before_kind'].get(),old[0])
        self.assertEqual(self.app.values['before_sha256'].get(),old[2])
        self.assertIsNone(self.app.last)

    def test_clear_resets_disclosure_but_preserves_files_and_clipboard(self):
        self.app.disclosure.set(True);self.app.begin()
        self.root.clipboard_clear();self.root.clipboard_append('KEEP')
        self.app.clear()
        self.assertTrue(all(not v.get() for v in self.app.values.values()))
        self.assertFalse(self.app.disclosure.get());self.assertEqual(self.text(),'')
        self.assertEqual(self.root.clipboard_get(),'KEEP')
        self.assertEqual(self.original,{p.name:p.read_bytes() for p in self.folder.iterdir()})

    def test_reentry_swap_clear_close_refused_during_synchronous_io(self):
        real=desktop.inspect;calls=[]
        def reenter(intent):
            calls.append(intent)
            self.assertTrue(self.app.busy)
            self.assertTrue(all(w.instate(['disabled']) for w,_ in self.app.controls))
            self.app.begin();self.app.swap();self.app.clear();self.app.close();self.app.copy()
            self.assertFalse(self.app.closed)
            return real(intent)
        with patch.object(desktop,'inspect',side_effect=reenter):self.app.begin()
        self.assertEqual(len(calls),1);self.assertIsNotNone(self.app.last)
        self.assertTrue(self.app.entries['before_kind'].instate(['readonly']))

    def test_copy_binding_mismatch_is_rejected(self):
        self.app.begin()
        shown=self.app.last
        self.app.last=replace(shown,intent=replace(shown.intent,details=True))
        self.root.clipboard_clear();self.root.clipboard_append('KEEP')
        self.app.copy()
        self.assertEqual(self.root.clipboard_get(),'KEEP');self.assertIsNone(self.app.last)

    def test_output_widget_failure_removes_result_and_recovers_controls(self):
        with patch.object(self.app.output,'insert',side_effect=tk.TclError('PRIVATE')):self.app.begin()
        self.assertIsNone(self.app.last);self.assertFalse(self.app.busy)
        self.assertTrue(self.app.copy_button.instate(['disabled']))
        self.app.begin();self.assertIsNotNone(self.app.last)

    def test_input_edit_from_status_notification_cannot_restore_revoked_result(self):
        def edit(*_):
            if self.app.status.get().startswith('本次文件比较完成'):
                self.app.values['after_sha256'].set('0'*64)
        token=self.app.status.trace_add('write',edit)
        try:
            self.app.begin()
            self.assertIsNone(self.app.last)
            self.assertTrue(self.app.copy_button.instate(['disabled']))
            self.assertEqual(self.text(),'')
        finally:
            self.app.status.trace_remove('write',token)

    def test_exceptions_and_interrupts_emit_no_sensitive_console_output(self):
        for exc in (OSError('PRIVATE'),KeyboardInterrupt('PRIVATE'),ValueError('PRIVATE')):
            self.app.begin();self.assertIsNotNone(self.app.last)
            stream=io.StringIO()
            with patch.object(desktop,'inspect',side_effect=exc),contextlib.redirect_stdout(stream),contextlib.redirect_stderr(stream):
                self.app.begin()
            self.assertEqual(stream.getvalue(),'');self.assertIsNone(self.app.last)
            self.assertEqual(self.app.status.get(),desktop.FAILURE)

    def test_callback_and_clipboard_failure_drop_copy_permission(self):
        self.app.begin();self.app.callback_error(ValueError,ValueError('PRIVATE'),None)
        self.assertIsNone(self.app.last);self.assertEqual(self.text(),'')
        self.app.begin()
        with patch.object(self.root,'clipboard_append',side_effect=tk.TclError('PRIVATE')):self.app.copy()
        self.assertIsNone(self.app.last)

    def test_report_inputs_after_source_deletion_are_not_current_task_checks(self):
        self.fill('report','report')
        for s in self.sources:s['task'].path.unlink()
        self.app.begin()
        self.assertIsNotNone(self.app.last);self.assertIn('未读取原任务',self.text())
        self.assertIn('未检查对应原任务当前是否存在',self.text())

    def test_task_tamper_or_same_byte_replacement_during_compare_is_failure(self):
        real=desktop.comparison.changes.describe
        path=self.sources[0]['task'].path
        def changed(*args,**kwargs):
            raw=path.read_bytes();path.rename(self.folder/'held');path.write_bytes(raw)
            return real(*args,**kwargs)
        with patch.object(desktop.comparison.changes,'describe',side_effect=changed):self.app.begin()
        self.assertIsNone(self.app.last);self.assertEqual(self.app.status.get(),desktop.FAILURE)

    def test_positive_ui_does_not_execute_native_write_or_read_ledger(self):
        with patch.object(subprocess,'Popen',side_effect=AssertionError('process')) as popen, \
                patch.object(desktop.task,'run_request',side_effect=AssertionError('task')) as query, \
                patch.object(desktop.task.files,'write_new',side_effect=AssertionError('write')) as write, \
                patch.object(desktop.task.once.single.ledger,'archive_snapshot',side_effect=AssertionError('ledger')):
            self.app.begin()
        self.assertIsNotNone(self.app.last)
        self.assertEqual((popen.call_count,query.call_count,write.call_count),(0,0,0))

    def test_every_selectable_control_disables_automatic_export(self):
        pending=[self.root]
        while pending:
            widget=pending.pop();pending.extend(widget.winfo_children())
            if 'exportselection' in widget.keys():self.assertFalse(int(widget.cget('exportselection')))

    @unittest.skipUnless(sys.platform.startswith('linux'),'X11 PRIMARY only')
    def test_selection_preserves_primary_until_explicit_copy(self):
        owner=tk.Entry(self.root,exportselection=True);owner.place(x=0,y=0,width=1,height=1)
        owner.insert(0,'KEEP_PRIMARY');owner.selection_range(0,'end');self.root.update()
        self.app.begin();self.app.output.tag_add('sel','1.0','end');self.root.update()
        self.assertEqual(self.root.selection_get(selection='PRIMARY'),'KEEP_PRIMARY')
        owner.destroy()

    def test_return_has_no_implicit_read(self):
        self.root.focus_force();entry=self.app.entries['before_path'];entry.focus_set();self.root.update()
        with patch.object(desktop,'inspect',side_effect=AssertionError('implicit read')) as read:
            entry.event_generate('<KeyPress-Return>');self.root.update()
        self.assertEqual(read.call_count,0);self.assertIsNone(self.app.last)

    def test_failed_close_is_retryable_without_file_changes(self):
        self.app.begin()
        with patch.object(self.root,'destroy',side_effect=tk.TclError('PRIVATE')):
            with self.assertRaises(tk.TclError):self.app.close()
        self.assertFalse(self.app.closed);self.assertIsNone(self.app.last)
        self.app.close();self.assertTrue(self.app.closed)
        self.assertEqual(self.original,{p.name:p.read_bytes() for p in self.folder.iterdir()})


if __name__=='__main__':unittest.main()
