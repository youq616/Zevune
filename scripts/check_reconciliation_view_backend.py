#!/usr/bin/env python3
"""Inspect real original-Rust reconciliation output; never substitute acceptance.

The unchanged original driver creates value-free wallets, signs and recovers.
This test wraps only the successful recovery call to observe its actual files.
All wallet and ledger cryptography still runs in the original native programs.
"""
import hashlib
import json
from pathlib import Path
import sys
import tkinter as tk
from unittest.mock import patch

import check_wallet_reconcile_backend as original
import reconciliation_view as view
import reconciliation_view_desktop as desktop


def run(wallet: Path, worker: Path, recovery: Path):
    saved_recover = original.reconcile.recover
    observed = []

    def observe(*args, **kwargs):
        result = saved_recover(*args, **kwargs)  # Real native recovery; errors stay errors.
        output = args[1]
        before = original.inventory(output)
        values = dict(directory=str(output), report_sha256=result['report_sha256'],
                      checkpoint=kwargs['checkpoint'], genesis_sha256=kwargs['genesis_sha256'])
        checkpoint = view.Checkpoint.parse(values['checkpoint'])
        assert checkpoint.genesis != values['genesis_sha256'], 'fixture must exercise distinct commitments'
        intent = view.prepare(values)
        # Even with real recovery files, viewing must never call a backend.
        with patch.object(view.reconciliation.Backend, '_exchange', side_effect=AssertionError('view executed backend')):
            checked = view.inspect(intent)
            root = tk.Tk()
            try:
                app = desktop.Workbench(root)
                for key, value in values.items():app.values[key].set(value)
                app.inspect_button.invoke()
                assert app.last == checked and not app.busy
            finally:
                root.destroy()
        assert checked.txid == result['txid'] and checked.pending_file_present == result['pending']
        assert checked.summary()['checkpoint_genesis_commitment'] == checkpoint.genesis
        assert checked.summary()['checkpoint_domain_relation_verified'] is False
        assert checked.copy_receipt == result['copy_receipt'] and checked.checkpoint_height == result['height']
        assert checked.summary()['settlement_status'] == 'unknown' and checked.summary()['retry_authorized'] is False
        assert original.inventory(output) == before
        original.reject(lambda: view.inspect(view.prepare(dict(values, report_sha256='0'*64))))
        if checked.pending_file_present:
            path = output / 'pending.tx'
            raw = path.read_bytes()
            try:
                path.write_bytes(raw[:-1] + bytes([raw[-1] ^ 1]))
                original.reject(lambda: view.inspect(intent))
            finally:
                path.write_bytes(raw)
            assert view.inspect(intent).txid == result['txid']
        assert original.inventory(output) == before
        observed.append((output.name, result['pending']))
        return result

    with patch.object(original.reconcile, 'recover', side_effect=observe):
        original.run(wallet, worker, recovery)
    assert observed == [('pending', True), ('empty-result', False), ('included', False), ('expired', False)], observed
    print(json.dumps(dict(operation='reconciliation_view_native_test', genuine_recovery_groups=len(observed),
                          real_gui_completed=True, original_driver_completed=True, input_bytes_preserved=True,
                          wallet_authentication_performed_by_viewer=False, real_funds_allowed=False), sort_keys=True))


if __name__=='__main__':
    if len(sys.argv)!=4:raise SystemExit('Original wallet, worker and recovery executables required')
    run(*(Path(value) for value in sys.argv[1:]))
