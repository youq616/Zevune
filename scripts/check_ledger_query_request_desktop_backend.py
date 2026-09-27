#!/usr/bin/env python3
"""Real task UI through the entire unchanged installed-Rust recovery/query chain.

No accepting replay substitutes. Only test-owned temporary valueless task files
are created/replaced, and every successful query still uses the original core.
"""
import hashlib
import json
from pathlib import Path
import sys
import threading
import time
import tkinter as tk
from unittest.mock import patch

import check_ledger_query_request_backend as previous
import check_wallet_reconcile_backend as original
import ledger_query_request_desktop as desktop


def pump(app, condition, seconds=310):
    end = time.monotonic() + seconds
    while not condition() and time.monotonic() < end:
        app.root.update()
        time.sleep(0.005)
    assert condition(), 'test UI did not complete within its existing native budget'


def run(wallet: Path, worker: Path, recovery: Path):
    saved_recover = original.reconcile.recover
    transaction_id = None
    groups, checks = [], []

    def observe(*args, **kwargs):
        nonlocal transaction_id
        report = saved_recover(*args, **kwargs)  # Real original recovery, no substituted success.
        output, journal = args[1], kwargs['journal']
        if output.name == 'pending':
            transaction_id = report['txid']
        assert transaction_id is not None
        backend = kwargs['recovery_backend'].binary.path
        request = desktop.task.prepare(kwargs['checkpoint'], kwargs['genesis_sha256'],
                                       hashlib.sha256(backend.read_bytes()).hexdigest(),
                                       ['0' * 64, transaction_id, '1' * 64])
        path = output.parent / (output.name + '-desktop-task.json')
        created = desktop.task.create(request, path)
        raw = path.read_bytes()
        fields = dict(request=str(path), request_sha256=created['request_sha256'],
                      journal=str(journal), backend=str(backend))
        before, evidence = original.inventory(journal), original.inventory(output)
        root = tk.Tk()
        app = desktop.Workbench(root)
        gates, owned = [], [path]
        native = desktop.task.once.single.checked.RecoveryBackend._run
        task_run = desktop.task.run_request
        replies, calls = [], []

        def recorded_task(*params):
            response = task_run(*params)
            replies.append(response)
            return response

        def counted_native(self, *params):
            calls.append(params[0][0])
            return native(self, *params)

        def set_fields(values):
            for key, value in values.items():
                app.values[key].set(value)

        def query():
            app.review()
            assert app.phase == 'review' and app.job is None
            app.confirm()
            pump(app, lambda: app.job is None)

        try:
            set_fields(fields)
            with patch.object(desktop.task, 'run_request', side_effect=AssertionError('review executed task')) as probe:
                app.review()
                assert app.phase == 'review' and app.job is None
                text = app.details.get('1.0', 'end')
                for value in (*fields.values(), *request.txids, request.checkpoint,
                              request.genesis_sha256, request.backend_sha256):
                    assert value in text
                assert probe.call_count == 0
            root.clipboard_clear()
            root.clipboard_append('KEEP_BEFORE_EXPLICIT_COPY')
            with patch.object(desktop.task, 'run_request', recorded_task), \
                    patch.object(desktop.task.once.single.checked.RecoveryBackend, '_run', counted_native):
                app.confirm()
                pump(app, lambda: app.job is None)
            assert calls == ['verify-active'] and len(replies) == 1
            assert type(app.last) is desktop.RequestDisplay
            assert app.last.txids == request.txids and app.last.request_sha256 == fields['request_sha256']
            assert replies[0]['result']['included_count'] == int(output.name == 'included')
            assert replies[0]['result']['settlement_status'] == 'unknown'
            assert replies[0]['result']['retry_authorized'] is False
            assert root.clipboard_get() == 'KEEP_BEFORE_EXPLICIT_COPY'
            app.copy()
            assert root.clipboard_get() == '\n'.join(request.txids)

            if output.name == 'included':
                checks.append('real_task_ui_one_replay_and_explicit_ordered_copy')
                folder_pin = dict(fields)
                folder_pin['request_sha256'] = '0' * 64
                set_fields(folder_pin)
                with patch.object(desktop, 'RequestJob', side_effect=AssertionError('bad task started')) as jobs:
                    app.review()
                    assert app.phase == 'idle' and app.last is None and jobs.call_count == 0
                checks.append('wrong_task_digest_refused_before_job')
                set_fields(fields)
                app.review()
                held = path.with_suffix('.review-held')
                path.rename(held)
                path.write_bytes(raw)
                try:
                    with patch.object(desktop.task, 'run_request', side_effect=AssertionError('unreviewed identity')) as query_call:
                        app.confirm()
                        pump(app, lambda: app.job is None)
                    assert query_call.call_count == 0 and app.last is None
                    checks.append('reviewed_same_bytes_replacement_refused_before_native')
                finally:
                    path.unlink()
                    held.rename(path)

                # Maximum count uses a real task and the real native/one-pass path.
                many_path = output.parent / 'desktop-32-task.json'
                many_ids = (transaction_id, *(f'{i:064x}' for i in range(31)))
                many = desktop.task.prepare(request.checkpoint, request.genesis_sha256,
                                            request.backend_sha256, many_ids)
                many_created = desktop.task.create(many, many_path)
                owned.append(many_path)
                set_fields(dict(fields, request=str(many_path), request_sha256=many_created['request_sha256']))
                calls.clear()
                with patch.object(desktop.task.once.single.checked.RecoveryBackend, '_run', counted_native):
                    query()
                assert calls == ['verify-active'] and app.last.txids == many_ids
                app.copy()
                assert root.clipboard_get() == '\n'.join(many_ids)
                checks.append('32_item_task_gui_executes_and_copies_in_order')
                set_fields(fields)

                # The core succeeds first. The GUI's original review snapshot must
                # still reject a subsequent equal-byte replacement before display.
                held = path.with_suffix('.finished-held')
                def replaced_after_real_task(*params):
                    response = task_run(*params)
                    path.rename(held)
                    path.write_bytes(raw)
                    return response
                try:
                    with patch.object(desktop.task, 'run_request', replaced_after_real_task):
                        query()
                    assert held.exists() and app.last is None
                    checks.append('same_bytes_replacement_after_real_query_refused')
                finally:
                    if held.exists():
                        path.unlink()
                        held.rename(path)

                # Delay only delivery after the real task finishes, never its verification.
                for action in ('edit', 'close'):
                    entered, release = threading.Event(), threading.Event()
                    gates.append(release)
                    def delayed_real_task(*params):
                        response = task_run(*params)
                        entered.set()
                        assert release.wait(timeout=30), 'test result-release gate timed out'
                        return response
                    with patch.object(desktop.task, 'run_request', delayed_real_task):
                        app.review()
                        assert app.phase == 'review'
                        app.confirm()
                        pump(app, entered.is_set)
                        job = app.job
                        assert job is not None and app.phase == 'running'
                        if action == 'edit':
                            app.values['request_sha256'].set('f' * 64)
                        else:
                            app.close()
                            app.close()
                            assert app.phase == 'closing' and app.job is job and root.winfo_exists()
                        release.set()
                        pump(app, lambda: app.job is None)
                        assert not job.thread.is_alive() and app.last is None
                    if action == 'edit':
                        assert app.phase == 'idle'
                        set_fields(fields)
                        checks.append('genuine_late_result_invalidated_after_input_edit')
                    else:
                        assert app.phase == 'closed'
                        checks.append('running_close_waits_for_real_task_exit')
            assert original.inventory(journal) == before and original.inventory(output) == evidence
            assert path.read_bytes() == raw
            groups.append((output.name, int(output.name == 'included')))
        finally:
            for gate in gates:
                gate.set()
            if app.job is not None and app.job.thread.ident is not None:
                app.job.thread.join(timeout=310)
                assert not app.job.thread.is_alive(), 'test left a worker alive'
            if app.phase != 'closed':
                app.cancel_poll()
                root.destroy()
            for item in owned:
                item.unlink()  # Only this driver's own temporary files, never product cleanup.
        return report

    with patch.object(original.reconcile, 'recover', side_effect=observe):
        previous.run(wallet, worker, recovery)
    assert groups == [('pending', 0), ('empty-result', 0), ('included', 1), ('expired', 0)], groups
    assert len(checks) == 7
    print(json.dumps(dict(operation='ledger_query_request_desktop_native_test', genuine_history_groups=4,
                          previous_task_install_recovery_and_query_chain_completed=True,
                          real_gui_completed=True, input_bytes_preserved=True,
                          checks=checks, real_funds_allowed=False), sort_keys=True))


if __name__ == '__main__':
    if len(sys.argv) != 4:
        raise SystemExit('Original wallet, worker and recovery executable paths required')
    run(*(Path(value) for value in sys.argv[1:]))
