#!/usr/bin/env python3
"""Actual Tk + unchanged native replay; retain the complete C15 driver.

Only temporary valueless fixtures are used. A delayed result below comes from a
real successful checker call; it is not an accepting verification substitute.
"""
import hashlib
import json
from pathlib import Path
import sys
import threading
import time
import tkinter as tk
from unittest.mock import patch

import check_reconciliation_ledger_backend as previous
import reconciliation_ledger_desktop as desktop


def pump(app, condition, seconds=320):
    deadline = time.monotonic() + seconds
    while not condition() and time.monotonic() < deadline:
        app.root.update()
        time.sleep(0.01)
    assert condition(), 'native desktop condition did not complete'


def run(wallet: Path, worker: Path, recovery: Path):
    recovery = recovery.resolve(strict=True)
    digest = hashlib.sha256(recovery.read_bytes()).hexdigest()
    original_recover = previous.original.reconcile.recover
    observed, delayed_checks = [], []

    def observe(*args, **kwargs):
        report = original_recover(*args, **kwargs)
        folder, journal = args[1], kwargs['journal']
        before = previous.original.inventory(folder)
        ledger_before = previous.original.inventory(journal)
        values = dict(directory=str(folder), report_sha256=report['report_sha256'],
                      checkpoint=kwargs['checkpoint'], genesis_sha256=kwargs['genesis_sha256'],
                      journal=str(journal), backend=str(recovery), backend_sha256=digest)
        root = tk.Tk()
        app = desktop.Workbench(root)
        try:
            for name, value in values.items():app.values[name].set(value)
            app.review_button.invoke()
            assert app.phase == 'review' and app.job is None
            app.confirm_button.invoke()
            job = app.job
            assert job is not None and not job.thread.daemon
            pump(app, lambda: app.job is None)
            assert app.phase == 'idle' and app.last is not None and not job.thread.is_alive()
            assert app.last.txid == report['txid']
            assert '不证明该交易已入账' in app.last.text
            assert '广播和结算仍未知' in app.last.text
            root.clipboard_clear()
            root.clipboard_append('INERT_PREVIOUS_CLIPBOARD')
            app.copy_button.invoke()
            if report['pending']:
                assert root.clipboard_get() == report['txid']
            else:
                assert root.clipboard_get() == 'INERT_PREVIOUS_CLIPBOARD'
                assert app.copy_button.instate(['disabled'])
            # Changing a field revokes a genuine displayed success immediately.
            app.values['report_sha256'].set('0' * 64)
            assert app.last is None and app.copy_button.instate(['disabled'])
            app.review()
            app.confirm()
            pump(app, lambda: app.job is None)
            assert app.last is None and app.status.get() == desktop.FAILURE
            app.values['report_sha256'].set(values['report_sha256'])

            if folder.name == 'pending':
                for mode in ('stale_result', 'close_during_real_check'):
                    actual_check = desktop.checker.check
                    entered, completed, release = threading.Event(), threading.Event(), threading.Event()
                    def delayed(intent):
                        entered.set()
                        result = actual_check(intent)
                        completed.set()
                        assert release.wait(timeout=10), 'test did not release actual result'
                        return result
                    try:
                        with patch.object(desktop.checker, 'check', side_effect=delayed):
                            app.review()
                            app.confirm()
                            held = app.job
                            pump(app, entered.is_set, seconds=3)
                            if mode == 'close_during_real_check':
                                app.close()
                                assert app.phase == 'closing' and app.job is held and root.winfo_exists()
                            pump(app, completed.is_set)
                            if mode == 'stale_result':
                                app.values['report_sha256'].set('0' * 64)
                            release.set()
                            pump(app, lambda: app.job is None)
                            assert app.last is None and not held.thread.is_alive()
                        delayed_checks.append(mode)
                        if mode == 'stale_result':
                            assert app.phase == 'idle'
                            app.values['report_sha256'].set(values['report_sha256'])
                        else:
                            assert app.phase == 'closed'
                    finally:
                        release.set()
                        if app.job is not None:
                            app.job.thread.join(timeout=10)
                            assert not app.job.thread.is_alive()
            assert app.callback_errors == 0
        finally:
            if app.job is not None:
                app.job.thread.join(timeout=310)
                assert not app.job.thread.is_alive(), 'native test left a worker'
            if app.phase != 'closed':
                app.cancel_poll()
                root.destroy()
        assert previous.original.inventory(folder) == before
        assert previous.original.inventory(journal) == ledger_before
        observed.append((folder.name, report['pending']))
        return report

    started = time.monotonic()
    # C15 keeps its own checker, corruption, actual CLI and post-native mutation
    # cases; the underlying original recovery driver keeps its ten scenarios.
    with patch.object(previous.original.reconcile, 'recover', side_effect=observe):
        previous.run(wallet, worker, recovery)
    assert observed == [('pending', True), ('empty-result', False), ('included', False), ('expired', False)]
    assert delayed_checks == ['stale_result', 'close_during_real_check']
    print(json.dumps(dict(operation='reconciliation_ledger_desktop_native_test', genuine_gui_groups=4,
                          delayed_genuine_results_checked=delayed_checks, previous_driver_completed=True,
                          input_bytes_preserved=True, elapsed_seconds=round(time.monotonic() - started, 3),
                          real_funds_allowed=False), sort_keys=True))


if __name__ == '__main__':
    if len(sys.argv) != 4:
        raise SystemExit('Original wallet, worker and recovery programs required')
    run(*(Path(value) for value in sys.argv[1:]))
