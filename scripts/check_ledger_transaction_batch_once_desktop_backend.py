#!/usr/bin/env python3
"""Actual single-pass GUI over original installed Rust history; no accepting substitutes.

Retain the complete C24 installer/recovery/single/batch/one-pass driver. Delays only hold
results that have actually completed the unchanged native batch query.
"""
import hashlib
import json
from pathlib import Path
import sys
import threading
import time
import tkinter as tk
from unittest.mock import patch

import check_ledger_transaction_batch_once_backend as previous
import check_wallet_reconcile_backend as original
import ledger_transaction_batch_once_desktop as desktop


def pump(app, condition, seconds=320):
    deadline = time.monotonic() + seconds
    while not condition() and time.monotonic() < deadline:
        app.root.update()
        time.sleep(0.005)
    assert condition(), 'batch GUI did not finish within the existing test budget'


def set_ids(app, ids):
    # Fixture-only programmatic bypass, to test a change even while input is disabled.
    state = app.txids.cget('state')
    app.txids.configure(state='normal')
    app.txids.delete('1.0', 'end')
    app.txids.insert('1.0', '\n'.join(ids))
    app.txids.configure(state=state)


def run(wallet: Path, worker: Path, recovery: Path):
    saved_recover = original.reconcile.recover
    txid = None
    observed, delayed_checks = [], []

    def observe(*args, **kwargs):
        nonlocal txid
        report = saved_recover(*args, **kwargs)  # Genuine original recovery only.
        folder, journal = args[1], kwargs['journal']
        if folder.name == 'pending':
            txid = report['txid']
        assert txid is not None
        executable = kwargs['recovery_backend'].binary.path
        assert executable.stat().st_nlink == 1
        values = dict(journal=str(journal), checkpoint=kwargs['checkpoint'],
                      genesis_sha256=kwargs['genesis_sha256'], backend=str(executable),
                      backend_sha256=hashlib.sha256(executable.read_bytes()).hexdigest())
        ids = ('0' * 64, txid, '1' * 64)
        before, evidence = original.inventory(journal), original.inventory(folder)
        root = tk.Tk()
        app = desktop.Workbench(root)
        real_batch = desktop.once.lookup_batch_once
        try:
            for key, value in values.items():app.values[key].set(value)
            set_ids(app, ids)
            captured = []
            def capture(intent):
                result = real_batch(intent)
                captured.append(result)
                return result
            native_calls, segments = [], []
            real_native = desktop.once.single.checked.RecoveryBackend._run
            real_scan = desktop.once.single.scan_segment_many
            def counted_native(self, *params):
                native_calls.append((params[0][0], params[-1]))
                return real_native(self, *params)
            def counted_segment(*params):
                segments.append((params[1], params[-1]))
                return real_scan(*params)
            with patch.object(desktop.once, 'lookup_batch_once', side_effect=capture), \
                    patch.object(desktop.once.single.checked.RecoveryBackend, '_run', counted_native), \
                    patch.object(desktop.once.single, 'scan_segment_many', counted_segment):
                app.review_button.invoke()
                assert app.phase == 'review' and app.job is None
                root.clipboard_clear(); root.clipboard_append('INERT_EXISTING_CLIPBOARD')
                app.confirm_button.invoke(); held = app.job
                assert held is not None and not held.thread.daemon
                pump(app, lambda: app.job is None)
            assert len(captured) == 1
            expected = captured[0]
            pin = desktop.once.single.Checkpoint.parse(values['checkpoint'])
            assert len(native_calls) == 1 and native_calls[0][0] == 'verify-active'
            assert len(segments) == pin.segments and all(t == native_calls[0][1] for _, t in segments)
            assert expected['format'] == 'zevune-ledger-transaction-batch-once-1'
            assert expected['history_scan_count'] == expected['native_replay_count'] == 1
            assert [r['historical_inclusion_verified'] for r in expected['results']] == [False, folder.name=='included', False]
            assert app.last == desktop.present(expected, desktop.prepare(values, '\n'.join(ids)))
            assert app.phase == 'idle' and not held.thread.is_alive()
            assert root.clipboard_get() == 'INERT_EXISTING_CLIPBOARD'
            app.copy_button.invoke()
            assert root.clipboard_get() == '\n'.join(ids)
            if folder.name == 'included':
                many = (txid, *(f'{i:064x}' for i in range(31)))
                native_calls.clear(); segments.clear()
                with patch.object(desktop.once.single.checked.RecoveryBackend, '_run', counted_native), \
                        patch.object(desktop.once.single, 'scan_segment_many', counted_segment):
                    set_ids(app, many); app.review(); app.confirm(); pump(app, lambda: app.job is None)
                assert len(native_calls) == 1 and len(segments) == pin.segments
                assert type(app.last) is desktop.OnceDisplay and app.last.txids == many
                app.copy_button.invoke(); assert root.clipboard_get() == '\n'.join(many)
                delayed_checks.append('32_real_results_one_pass_rendered_and_copied')
                set_ids(app, ids)
            app.values['backend_sha256'].set('a' * 64)
            assert app.last is None and app.copy_button.instate(['disabled'])
            app.review(); app.confirm(); pump(app, lambda: app.job is None)
            assert app.last is None and app.status.get() == desktop.previous.FAILURE
            app.values['backend_sha256'].set(values['backend_sha256'])
            if folder.name == 'pending':
                for mode in ('multiline_stale_result', 'close_during_genuine_batch'):
                    entered, finished, release = threading.Event(), threading.Event(), threading.Event()
                    def delay(intent):
                        entered.set()
                        result = real_batch(intent)
                        finished.set()
                        assert release.wait(timeout=10)
                        return result
                    try:
                        with patch.object(desktop.once, 'lookup_batch_once', side_effect=delay):
                            app.review(); app.confirm(); held = app.job
                            pump(app, entered.is_set, 3)
                            if mode == 'close_during_genuine_batch':
                                app.close()
                                assert app.phase == 'closing' and app.job is held and root.winfo_exists()
                            pump(app, finished.is_set)
                            if mode == 'multiline_stale_result':set_ids(app, ('f'*64,))
                            release.set(); pump(app, lambda: app.job is None)
                            assert app.last is None and not held.thread.is_alive()
                        delayed_checks.append(mode)
                        if mode == 'multiline_stale_result':
                            assert app.phase == 'idle'; set_ids(app, ids)
                        else:assert app.phase == 'closed'
                    finally:
                        release.set()
                        if app.job is not None:
                            app.job.thread.join(timeout=10)
                            assert not app.job.thread.is_alive()
            assert app.callback_errors == 0
        finally:
            if app.job is not None:
                app.job.thread.join(timeout=310)
                assert not app.job.thread.is_alive(), 'fixture left a native worker'
            if app.phase != 'closed':
                app.cancel_poll(); root.destroy()
        assert original.inventory(journal) == before and original.inventory(folder) == evidence
        observed.append((folder.name, folder.name=='included'))
        return report

    with patch.object(original.reconcile, 'recover', side_effect=observe):
        previous.run(wallet, worker, recovery)
    assert observed == [('pending', False), ('empty-result', False), ('included', True), ('expired', False)]
    assert delayed_checks == ['multiline_stale_result', 'close_during_genuine_batch', '32_real_results_one_pass_rendered_and_copied']
    print(json.dumps(dict(operation='ledger_transaction_batch_once_desktop_native_test', genuine_gui_groups=4,
                          previous_install_recovery_and_one_pass_suite_completed=True, input_bytes_preserved=True,
                          checks=delayed_checks, real_funds_allowed=False), sort_keys=True))


if __name__ == '__main__':
    if len(sys.argv) != 4:raise SystemExit('Original wallet, worker and recovery executables required')
    run(*(Path(value) for value in sys.argv[1:]))
