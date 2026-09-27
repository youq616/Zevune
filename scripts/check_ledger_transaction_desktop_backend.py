#!/usr/bin/env python3
"""Actual GUI queries on original native history; keep the full C20 integration.

Every successful result below comes from the original installed Rust backend.
Delays preserve a real result, never manufacture accepting verification data.
"""
import hashlib
import json
from pathlib import Path
import sys
import threading
import time
import tkinter as tk
from unittest.mock import patch

import check_ledger_transaction_backend as previous
import ledger_transaction_desktop as desktop


def pump(app, condition, seconds=320):
    deadline = time.monotonic() + seconds
    while not condition() and time.monotonic() < deadline:
        app.root.update()
        time.sleep(0.005)
    assert condition(), 'native lookup UI did not finish within test budget'


def run(wallet: Path, worker: Path, recovery: Path):
    saved_recover = previous.original.reconcile.recover
    txid = None
    observed, delayed_checks = [], []

    def observe(*args, **kwargs):
        nonlocal txid
        report = saved_recover(*args, **kwargs)
        folder, journal = args[1], kwargs['journal']
        if folder.name == 'pending':
            txid = report['txid']
        assert txid is not None
        # C20's outer run has already installed the approved single-link copy.
        executable = kwargs['recovery_backend'].binary.path
        assert executable.stat().st_nlink == 1
        values = dict(journal=str(journal), checkpoint=kwargs['checkpoint'],
                      genesis_sha256=kwargs['genesis_sha256'], txid=txid, backend=str(executable),
                      backend_sha256=hashlib.sha256(executable.read_bytes()).hexdigest())
        before, evidence = previous.original.inventory(journal), previous.original.inventory(folder)
        root = tk.Tk()
        app = desktop.Workbench(root)
        real_lookup = desktop.lookup.lookup
        try:
            for name,value in values.items():app.values[name].set(value)
            actual_results = []
            def capture(intent):
                result = real_lookup(intent)
                actual_results.append(result)
                return result
            with patch.object(desktop.lookup,'lookup',side_effect=capture):
                app.review_button.invoke()
                assert app.phase == 'review' and app.job is None
                root.clipboard_clear();root.clipboard_append('INERT_PREVIOUS_CLIPBOARD')
                app.confirm_button.invoke()
                job = app.job
                assert job is not None and not job.thread.daemon
                pump(app,lambda: app.job is None)
            assert len(actual_results)==1
            expected=actual_results[0]
            assert expected['historical_inclusion_verified'] is (folder.name=='included')
            assert app.last == desktop.present(expected,desktop.lookup.prepare(values))
            assert app.phase=='idle' and not job.thread.is_alive()
            assert root.clipboard_get()=='INERT_PREVIOUS_CLIPBOARD'
            app.copy_button.invoke()
            assert root.clipboard_get()==txid
            app.values['backend_sha256'].set('a'*64)
            assert app.last is None and app.copy_button.instate(['disabled'])
            app.review();app.confirm();pump(app,lambda: app.job is None)
            assert app.last is None and app.status.get()==desktop.FAILURE
            app.values['backend_sha256'].set(values['backend_sha256'])

            if folder.name=='pending':
                for mode in ('stale_result','close_during_real_lookup'):
                    entered, completed, release = threading.Event(),threading.Event(),threading.Event()
                    def delayed(intent):
                        entered.set()
                        result=real_lookup(intent)
                        completed.set()
                        assert release.wait(timeout=10), 'test did not release genuine result'
                        return result
                    try:
                        with patch.object(desktop.lookup,'lookup',side_effect=delayed):
                            app.review();app.confirm();held=app.job
                            pump(app,entered.is_set,3)
                            if mode=='close_during_real_lookup':
                                app.close()
                                assert app.phase=='closing' and app.job is held and root.winfo_exists()
                            pump(app,completed.is_set)
                            if mode=='stale_result':app.values['txid'].set('0'*64)
                            release.set();pump(app,lambda: app.job is None)
                            assert app.last is None and not held.thread.is_alive()
                        delayed_checks.append(mode)
                        if mode=='stale_result':
                            assert app.phase=='idle';app.values['txid'].set(txid)
                        else:assert app.phase=='closed'
                    finally:
                        release.set()
                        if app.job is not None:
                            app.job.thread.join(timeout=10)
                            assert not app.job.thread.is_alive()
            assert app.callback_errors==0
        finally:
            if app.job is not None:
                app.job.thread.join(timeout=310)
                assert not app.job.thread.is_alive(), 'test left a native lookup worker'
            if app.phase!='closed':
                app.cancel_poll();root.destroy()
        assert previous.original.inventory(journal)==before and previous.original.inventory(folder)==evidence
        observed.append((folder.name, folder.name=='included'))
        return report

    with patch.object(previous.original.reconcile,'recover',side_effect=observe):
        previous.run(wallet,worker,recovery)
    assert observed==[('pending',False),('empty-result',False),('included',True),('expired',False)]
    assert delayed_checks==['stale_result','close_during_real_lookup']
    print(json.dumps(dict(operation='ledger_transaction_desktop_native_test', genuine_gui_groups=4,
                          actual_installer_and_previous_driver_completed=True, input_bytes_preserved=True,
                          delayed_genuine_results_checked=delayed_checks, real_funds_allowed=False),sort_keys=True))


if __name__=='__main__':
    if len(sys.argv)!=4:raise SystemExit('Original wallet, worker and recovery paths required')
    run(*(Path(value) for value in sys.argv[1:]))
