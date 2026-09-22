#!/usr/bin/env python3
"""Actual Tk widgets/events on Windows or Xvfb; synthetic public inputs only.

No display/Tk means failure, never a platform skip. These UI checks do not prove
Orchard authentication; the separate real-backend test covers interoperability.
"""
from pathlib import Path
import contextlib
import hashlib
import io
import sys
import tempfile
import tkinter as tk
import unittest
from unittest.mock import patch

import request_desktop as desktop


def public_genesis():
    return (b'ZVTGEN02' + hashlib.sha256(b'zevune-orchard-lab-1').digest()
            + (100000).to_bytes(8, 'big') + b'\0\1' + b'q'*32
            + b'r'*43 + (100000).to_bytes(8, 'big') + b's'*64)


def public_address(domain):
    receiver = '73'*43
    checksum = hashlib.sha256(b'ZEVUNE-LOCAL-ADDRESS\0\x02' + bytes.fromhex(domain+receiver)).hexdigest()[:16]
    return f'zvlab2:{domain}:{receiver}:{checksum}'


def enter(app, key, value):
    widget = app.entries[key]
    widget.delete(0, 'end')
    widget.insert(0, str(value))


def press_create(app, accept=True, during=None):
    """Operate the REAL modal dialog's buttons, not a mocked confirmation."""
    events, errors = [], []
    def decide():
        events.append('dialog')
        try:
            assert app.confirmation is not None and app.busy
            assert all(widget.instate(['disabled']) for widget in app.controls)
            if during is not None:
                during()
            (app.confirmation.confirm if accept else app.confirmation.cancel).invoke()
        except Exception as error:
            errors.append(type(error).__name__)
            if app.confirmation is not None and app.confirmation.window.winfo_exists():
                app.confirmation.finish(False)
    token = app.root.after(20, decide)
    app.actions['create'].invoke()
    try:
        app.root.after_cancel(token)
        app.root.update()
    except tk.TclError:
        pass
    assert events == ['dialog'] and not errors, 'real dialog action did not finish'
    assert app.callback_errors == 0, 'Tk callback unexpectedly failed'


class DesktopWidgetTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='zevune-ui-public-')
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name).resolve()
        self.genesis = self.path/'genesis'
        self.genesis.write_bytes(public_genesis())
        self.domain = hashlib.sha256(self.genesis.read_bytes()).hexdigest()
        self.output = self.path/'new.zvrequest'
        self.root = tk.Tk()  # intentionally fail if no GUI capability
        self.addCleanup(self.destroy)
        self.app = desktop.Workbench(self.root)
        self.root.update()
        for key, value in dict(genesis=self.genesis, genesis_pin=self.domain, target=self.output,
                               recipient=public_address(self.domain), amount='1234', expiry='10').items():
            enter(self.app, key, value)

    def destroy(self):
        try:
            self.root.destroy()
        except tk.TclError:
            pass

    def inspect_created(self, digest):
        self.app.tabs.select(1)
        self.root.update()
        enter(self.app, 'source', self.output)
        enter(self.app, 'request_pin', digest)
        self.app.actions['inspect'].invoke()
        self.root.update()

    def test_actual_create_and_inspect_are_existing_format_no_authentication(self):
        press_create(self.app)
        created = self.app.last_result
        self.assertEqual(created['result'], 'request_created_not_signed')
        original = self.output.read_bytes()
        self.inspect_created(created['request_sha256'])
        inspected = self.app.last_result
        self.assertIs(inspected['authenticated'], False)
        self.assertIs(inspected['single_use_enforced'], False)
        self.assertIs(inspected['expiry_checked_against_ledger'], False)
        self.assertEqual(inspected['request']['amount'], 1234)
        self.assertEqual(self.output.read_bytes(), original)
        self.assertIn('不是认证', self.app.status.get())
        self.assertEqual(self.app.callback_errors, 0)

    def test_cancel_preserves_files(self):
        press_create(self.app, False)
        self.assertFalse(self.output.exists())
        self.assertIsNone(self.app.last_result)
        self.assertIn('已取消', self.app.status.get())
        self.assertFalse(self.app.busy)

    def test_edit_or_tab_change_clears_stale_success_and_digest(self):
        press_create(self.app)
        saved = self.output.read_bytes()
        enter(self.app, 'amount', '999')
        self.assertIsNone(self.app.last_result)
        self.assertEqual(self.app.digest.get(), '')
        self.assertEqual(self.app.details.get('1.0', 'end').strip(), '')
        self.assertTrue(self.app.copy_button.instate(['disabled']))
        self.assertEqual(self.output.read_bytes(), saved)

    def test_programmatic_field_change_during_modal_cannot_change_confirmed_intent(self):
        press_create(self.app, during=lambda: self.app.values['amount'].set('999'))
        self.assertFalse(self.output.exists())
        self.assertIsNone(self.app.last_result)
        self.assertEqual(self.app.status.get(), desktop.FAILURE)

    def test_reentry_during_confirmation_creates_only_one_file(self):
        press_create(self.app, during=self.app.create)
        self.assertIsNotNone(self.app.last_result)
        self.assertEqual(set(p.name for p in self.path.iterdir()), {'genesis', 'new.zvrequest'})
        self.assertFalse(self.app.busy)

    def test_external_genesis_change_before_confirmation_refused(self):
        def damage():
            raw = bytearray(self.genesis.read_bytes()); raw[-1] ^= 1
            self.genesis.write_bytes(raw)
        press_create(self.app, during=damage)
        self.assertFalse(self.output.exists())
        self.assertEqual(self.app.status.get(), desktop.FAILURE)

    def test_output_created_while_modal_is_open_is_not_overwritten(self):
        press_create(self.app, during=lambda: self.output.write_bytes(b'preserved'))
        self.assertEqual(self.output.read_bytes(), b'preserved')
        self.assertIsNone(self.app.last_result)
        self.assertEqual(self.app.status.get(), desktop.FAILURE)

    def test_failed_inspection_discards_previous_plaintext_without_logging(self):
        press_create(self.app)
        digest = self.app.last_result['request_sha256']
        self.inspect_created(digest)
        self.output.write_bytes(self.output.read_bytes()+b' ')
        stderr, stdout = io.StringIO(), io.StringIO()
        with contextlib.redirect_stderr(stderr), contextlib.redirect_stdout(stdout):
            self.app.actions['inspect'].invoke()
        self.assertEqual(stderr.getvalue()+stdout.getvalue(), '')
        self.assertIsNone(self.app.last_result)
        self.assertEqual(self.app.details.get('1.0', 'end').strip(), '')
        self.assertEqual(self.app.status.get(), desktop.FAILURE)

    def test_partial_write_failure_does_not_retry_or_delete(self):
        def partial(path, data):
            path.write_bytes(data[:17])
            raise OSError('PRIVATE_SENTINEL')
        with patch.object(desktop.request.storage, 'write_new', side_effect=partial) as write:
            press_create(self.app)
            self.assertEqual(write.call_count, 1)
        self.assertEqual(self.output.stat().st_size, 17)
        self.assertEqual(self.app.status.get(), desktop.FAILURE)
        self.assertNotIn('PRIVATE_SENTINEL', self.app.status.get())
        self.assertIsNone(self.app.last_result)

    def test_window_close_during_review_cancels_without_creating(self):
        self.root.after(20, self.app.close)
        self.app.actions['create'].invoke()
        self.assertTrue(self.app.closing)
        self.assertFalse(self.output.exists())
        self.assertEqual(self.app.callback_errors, 0)

    def test_clear_and_explicit_copy_only_copy_current_digest(self):
        press_create(self.app)
        digest = self.app.digest.get()
        self.app.copy_button.invoke()
        self.root.update()
        self.assertEqual(self.root.clipboard_get(), digest)
        saved = self.output.read_bytes()
        self.app.actions['clear'].invoke()
        self.assertTrue(all(value.get() == '' for value in self.app.values.values()))
        self.assertIsNone(self.app.last_result)
        self.assertEqual(self.root.clipboard_get(), digest)  # clearing UI never silently wipes system clipboard
        self.assertEqual(self.output.read_bytes(), saved)

    def test_unexpected_callback_does_not_print_private_exception(self):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            self.root.report_callback_exception(ValueError, ValueError('PRIVATE_SENTINEL'), None)
        self.assertEqual(stdout.getvalue()+stderr.getvalue(), '')
        self.assertEqual(self.app.callback_errors, 1)
        self.assertEqual(self.app.status.get(), desktop.FAILURE)
        self.assertIsNone(self.app.last_result)


if __name__ == '__main__':
    unittest.main()
