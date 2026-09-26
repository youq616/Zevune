#!/usr/bin/env python3
"""Actual Tk file-view tests; public synthetic frames never authenticate a wallet."""
import contextlib
import io
from pathlib import Path
import sys
import tempfile
import tkinter as tk
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent / 'tests'))
from test_reconciliation_view import fixture
import reconciliation_view as view
import reconciliation_view_desktop as desktop


class ViewWidgetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='reconcile-view-gui-')
        self.addCleanup(self.temp.cleanup)
        self.values, self.report = fixture(Path(self.temp.name).resolve())
        self.root = tk.Tk()
        self.app = desktop.Workbench(self.root)
        self.addCleanup(self.cleanup)
        for key, value in self.values.items():self.app.values[key].set(value)
        self.root.update()

    def cleanup(self):
        if not self.app.closed:self.root.destroy()

    def test_real_view_shows_unknown_status_and_explicit_copy_only(self):
        self.root.clipboard_clear();self.root.clipboard_append('EXISTING_CLIPBOARD')
        self.app.inspect_button.invoke()
        self.assertIsNotNone(self.app.last)
        self.assertIn('结算状态未知',self.app.details.get('1.0','end'))
        self.assertEqual(self.root.clipboard_get(),'EXISTING_CLIPBOARD')
        self.app.copy_button.invoke()
        self.assertEqual(self.root.clipboard_get(),self.report['txid'])
        self.assertFalse(self.app.busy)

    def test_inputs_change_immediately_discards_result_and_copy_permission(self):
        self.app.begin()
        self.app.values['report_sha256'].set('0'*64)
        self.assertIsNone(self.app.last)
        self.assertEqual(self.app.details.get('1.0','end').strip(),'')
        self.assertTrue(self.app.copy_button.instate(['disabled']))
        self.root.clipboard_clear();self.root.clipboard_append('KEEP')
        self.app.copy()
        self.assertEqual(self.root.clipboard_get(),'KEEP')

    def test_failure_clears_previous_result_without_echoing_exception(self):
        self.app.begin()
        out=io.StringIO()
        with patch.object(view,'inspect',side_effect=OSError('PRIVATE_SENTINEL')), \
                contextlib.redirect_stderr(out),contextlib.redirect_stdout(out):
            self.app.begin()
        self.assertIsNone(self.app.last)
        self.assertEqual(self.app.status.get(),view.FAILURE)
        self.assertEqual(out.getvalue(),'')
        self.assertTrue(all(widget.instate(['!disabled']) for widget in self.app.controls))

    def test_reentrant_begin_and_programmatic_changes_never_show_stale_result(self):
        original=view.inspect
        calls=[]
        def inspect(intent):
            calls.append(True)
            self.assertTrue(self.app.busy)
            self.assertTrue(all(widget.instate(['disabled']) for widget in self.app.controls))
            self.app.begin()
            self.app.close()  # Refused during synchronous IO, no nested event loop.
            self.app.values['report_sha256'].set('0'*64)
            return original(intent)
        with patch.object(view,'inspect',side_effect=inspect):self.app.begin()
        self.assertEqual(calls,[True]);self.assertIsNone(self.app.last)
        self.assertFalse(self.app.closed)

    def test_all_selectable_fields_disable_automatic_export(self):
        pending=[self.root]
        while pending:
            widget=pending.pop();pending.extend(widget.winfo_children())
            if 'exportselection' in widget.keys():self.assertFalse(int(widget.cget('exportselection')))

    @unittest.skipUnless(sys.platform.startswith('linux'),'X11 PRIMARY only')
    def test_real_x11_selection_does_not_export_report_text(self):
        owner=tk.Entry(self.root,exportselection=True)
        owner.place(x=0,y=0,width=1,height=1)
        owner.insert(0,'UNCHANGED_PRIMARY');owner.selection_range(0,'end')
        self.root.update()
        self.app.begin()
        self.app.details.tag_add('sel','1.0','end')
        self.root.update()
        self.assertEqual(self.root.selection_get(selection='PRIMARY'),'UNCHANGED_PRIMARY')
        owner.destroy()

    def test_no_pending_view_does_not_enable_transaction_copy(self):
        folder=Path(self.values['directory'])
        (folder/'pending.tx').unlink()
        report=dict(self.report,pending=False,txid=None,result='no_pending_not_settlement_proof')
        raw=view.files.canonical(report)
        (folder/view.reconciliation.MARKER).write_bytes(raw)
        import hashlib
        self.app.values['report_sha256'].set(hashlib.sha256(raw).hexdigest())
        self.app.begin()
        self.assertIsNotNone(self.app.last)
        self.assertIn('不能据此区分',self.app.details.get('1.0','end'))
        self.assertTrue(self.app.copy_button.instate(['disabled']))

    def test_clear_and_close_do_not_change_files_or_global_clipboard(self):
        folder=Path(self.values['directory'])
        before={p.name:p.read_bytes() for p in folder.iterdir()}
        self.app.begin();self.root.clipboard_clear();self.root.clipboard_append('KEEP')
        self.app.clear()
        self.assertIsNone(self.app.last)
        self.assertTrue(all(not value.get() for value in self.app.values.values()))
        self.assertEqual(self.root.clipboard_get(),'KEEP')
        self.app.close()
        self.assertTrue(self.app.closed)
        self.assertEqual({p.name:p.read_bytes() for p in folder.iterdir()},before)

    def test_callback_exception_is_redacted_and_revokes_result(self):
        self.app.begin();output=io.StringIO()
        with contextlib.redirect_stderr(output):self.root.report_callback_exception(ValueError,ValueError('PRIVATE'),None)
        self.assertEqual(output.getvalue(),'');self.assertIsNone(self.app.last)


if __name__=='__main__':unittest.main()
