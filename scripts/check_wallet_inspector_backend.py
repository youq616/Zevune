#!/usr/bin/env python3
"""Real password widgets -> read-only native identity/capacity checks.

Only this isolated fixture creates wallets or signatures. Runtime inspector
calls are recorded then delegated to the unchanged original Rust op9.
"""
import hashlib
from pathlib import Path
import secrets
import sys
import tempfile
import time
import tkinter as tk
from unittest.mock import patch

import wallet_inspector_desktop as desktop
from check_wallet_inspector_gui import enter, press, wait
from zevune_wallet import encode_request, invoke


def snapshot(root):
    return {p.relative_to(root):p.read_bytes() if p.is_file() else None for p in root.rglob('*')}


def run(binary):
    binary = binary.resolve(strict=True)
    digest = hashlib.sha256(binary.read_bytes()).hexdigest()
    secret = secrets.token_hex(16)
    password = secret.encode('utf-8')
    start = time.monotonic()
    groups = []
    print('INSPECTOR_NATIVE_STAGE start', flush=True)
    with tempfile.TemporaryDirectory(prefix='zevune-inspector-native-') as temp:
        root = Path(temp).resolve()
        wallet, peer, pool, genesis = (root/name for name in ('wallet', 'peer', 'pool', 'genesis'))
        def native(op, paths, pin=None):
            return invoke(binary, encode_request(op, password, [str(p) for p in paths], pin), digest)
        initial = native(0, [wallet])['receipt']
        print('INSPECTOR_NATIVE_STAGE wallet_created', flush=True)
        window = tk.Tk()  # Real display required, never skip.
        app = desktop.Workbench(window)
        window.update()
        calls=[]
        original_call=desktop.ReadOnlyBackend.call
        def observed(self, op, *args):
            assert op == 9, 'runtime inspector used a non-read-only operation'
            calls.append(op)
            return original_call(self, op, *args)
        def check(level='nominal', passcode=secret):
            before=snapshot(root)
            print('INSPECTOR_NATIVE_STAGE check_' + str(level), flush=True)
            press(app, password=passcode)
            wait(app, limit=180)
            assert snapshot(root)==before, 'UI changed original test data'
            assert app.callback_errors == 0
            if level is None:
                assert app.last_result is None and not app.receipt.get()
            else:
                assert app.last_result.severity == level
                assert '未扫描历史' in app.details.get('1.0','end')
                assert secret not in app.details.get('1.0','end')+app.status.get()+app.receipt.get()
        try:
            with patch.object(desktop.ReadOnlyBackend, 'call', observed):
                for key, value in dict(wallet=wallet, ancestor=initial, backend=binary, backend_sha256=digest,
                                       reserve='0', saves='1', warn='16').items():
                    enter(app,key,value)
                before=snapshot(root)
                press(app,password=secret,accept=False)
                assert not calls and snapshot(root)==before
                check()
                assert app.last_result.receipt==initial and app.last_result.used==1
                assert app.last_result.remaining==255
                app.copy_button.invoke();window.update()
                assert window.clipboard_get()==initial
                enter(app,'warn','255')
                assert app.last_result is None and not app.receipt.get()
                check('warning')
                enter(app,'warn','16');enter(app,'saves','256')
                check('critical')
                enter(app,'saves','1')
                print('INSPECTOR_NATIVE_STAGE group_completed', flush=True)
                groups.append('authenticated_identity_and_three_capacity_levels')
                check(None, 'wrong-password-not-the-real-one')
                enter(app,'backend_sha256','0'*64)
                check(None)
                enter(app,'backend_sha256',digest)
                enter(app,'ancestor',initial[:80]+'7'*64)
                check(None)
                enter(app,'ancestor',initial)
                print('INSPECTOR_NATIVE_STAGE group_completed', flush=True)
                groups.append('wrong_password_digest_and_ancestor_refused_without_mutation')

                # A genuine signed pending payment is constructed OUTSIDE the
                # GUI to demonstrate inspection does not scan/release it.
                created=native(7,[wallet,pool,genesis])
                domain=created['genesis_sha256']
                native(0,[peer])
                recipient=native(8,[peer,pool,genesis,domain,'0'])['address']
                transaction=root/'original.tx'
                signed=native(4,[wallet,pool,genesis,domain,recipient,'25000','1000','10',transaction],created['receipt'])
                pinned=signed['receipt']; wallet_bytes=wallet.read_bytes()
                check()
                assert app.last_result.receipt==pinned and app.last_result.used==3
                exported=root/'exported.tx'
                recovered=native(5,[wallet,pool,genesis,domain,exported],pinned)
                assert recovered['txid']==signed['txid'] and exported.read_bytes()==transaction.read_bytes()
                state=native(3,[wallet,pool,genesis,domain],pinned)
                assert state['pending'] is True and state['available']==0 and state['receipt']==pinned
                assert wallet.read_bytes()==wallet_bytes
                print('INSPECTOR_NATIVE_STAGE group_completed', flush=True)
                groups.append('old_ancestor_real_pending_signature_and_reservation_preserved')

                before=snapshot(root)
                press(app,password=secret)
                # Programmatic input mutation even while widgets are disabled.
                app.values['reserve'].set('1')
                wait(app,limit=180)
                assert app.last_result is None and not app.receipt.get() and snapshot(root)==before
                print('INSPECTOR_NATIVE_STAGE group_completed', flush=True)
                groups.append('late_completion_cannot_relabel_changed_form')
                enter(app,'reserve','0')

                # Both checks are real, then alter this test-only source before
                # the coordinator's final equality check. No accepting double.
                real_inspect=desktop.health.inspect
                def after_authentication(*args,**kwargs):
                    report=real_inspect(*args,**kwargs)
                    damaged=bytearray(wallet_bytes);damaged[-1]^=1
                    wallet.write_bytes(damaged)
                    return report
                with patch.object(desktop.health,'inspect',side_effect=after_authentication):
                    press(app,password=secret);wait(app,limit=180)
                    assert app.last_result is None and not app.receipt.get()
                wallet.write_bytes(wallet_bytes)  # fixture repair, never runtime behavior
                assert snapshot(root)==before
                print('INSPECTOR_NATIVE_STAGE group_completed', flush=True)
                groups.append('source_change_between_authentication_and_display_refused')
                check()
                app.clear_button.invoke()
                assert app.last_result is None and not app.receipt.get()
                assert window.clipboard_get()==initial  # no automatic clipboard erasure
                for key,value in dict(wallet=wallet,ancestor=initial,backend=binary,backend_sha256=digest,
                                      reserve='0',saves='1',warn='16').items():enter(app,key,value)
                before=snapshot(root)
                press(app,password=secret)
                assert app.job is not None
                app.close()
                assert app.closing and app.busy and app.job is not None
                wait(app,limit=180)
                assert app.job is None and snapshot(root)==before
                print('INSPECTOR_NATIVE_STAGE group_completed', flush=True)
                groups.append('close_waits_for_genuine_worker_cleanup')
            assert calls and set(calls)=={9}
        finally:
            if app.job is not None:
                app.job.thread.join(timeout=600)
                assert not app.job.thread.is_alive(), 'native UI test left a worker'
            try:window.destroy()
            except tk.TclError:pass
    assert not root.exists()
    assert hashlib.sha256(binary.read_bytes()).hexdigest()==digest
    print('Native read-only inspector: '+str(len(groups))+' groups completed; original pending/signature/reservation preserved; fixtures removed; NO-FUNDS.')
    print('Elapsed seconds: '+str(round(time.monotonic()-start,3)))


if __name__=='__main__':
    if len(sys.argv)!=2:raise SystemExit('One trusted original wallet executable required')
    run(Path(sys.argv[1]))
