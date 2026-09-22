#!/usr/bin/env python3
"""Real Tk-produced request consumed by the unchanged authentic Rust wallet.

No accepting backend double. The GUI does not see passwords, wallet paths or
signing APIs; only this test driver invokes the original wallet after UI output.
"""
from pathlib import Path
import hashlib
import secrets
import sys
import tempfile
import tkinter as tk

from check_request_desktop_gui import enter, press_create
import request_desktop as desktop
import payment_request as requests
from zevune_wallet import encode_request, invoke


def files(root):
    return {p.relative_to(root): p.read_bytes() if p.is_file() else None for p in root.rglob('*')}


def run(binary):
    binary = binary.resolve(strict=True)
    digest = hashlib.sha256(binary.read_bytes()).hexdigest()
    password = secrets.token_bytes(32)
    with tempfile.TemporaryDirectory(prefix='zevune-desktop-native-') as temp:
        root = Path(temp).resolve()
        wallet, peer, pool, genesis = (root / name for name in ('wallet', 'peer', 'pool', 'genesis'))
        def native(op, paths, pin=None):
            return invoke(binary, encode_request(op, password, [str(p) for p in paths], pin), digest)
        native(0, [wallet])
        created = native(7, [wallet, pool, genesis])
        domain, pin = created['genesis_sha256'], created['receipt']
        native(0, [peer])
        recipient = native(8, [peer, pool, genesis, domain, '0'])['address']
        before = files(root)
        window = tk.Tk()  # missing Tk/display must fail, never skip
        app = desktop.Workbench(window)
        try:
            window.update()
            path = root/'request.zvrequest'
            for key, value in dict(genesis=genesis, genesis_pin=domain, target=path,
                                   recipient=recipient, amount='25000', expiry='10').items():
                enter(app, key, value)
            press_create(app, False)
            assert files(root) == before and app.last_result is None
            press_create(app)
            result = app.last_result
            assert result['result'] == 'request_created_not_signed' and result['authenticated'] is False
            request_pin = result['request_sha256']
            after = files(root)
            assert {k:v for k,v in after.items() if k != path.relative_to(root)} == before
            raw_request = path.read_bytes()
            assert hashlib.sha256(raw_request).hexdigest() == request_pin
            # An altered selected genesis must not be silently trusted.
            other = root/'other-genesis'
            raw = bytearray(genesis.read_bytes()); raw[-1] ^= 1
            other.write_bytes(raw)
            # Keep the trusted ORIGINAL pin: no implicit hashing of selections.
            enter(app, 'genesis', other)
            enter(app, 'target', root/'wrong-network.zvrequest')
            app.actions['create'].invoke()
            assert app.last_result is None and not (root/'wrong-network.zvrequest').exists()
            assert app.confirmation is None and app.status.get() == desktop.FAILURE
            enter(app, 'genesis', genesis)
            app.tabs.select(1); window.update()
            enter(app, 'source', path); enter(app, 'request_pin', request_pin)
            app.actions['inspect'].invoke()
            inspected = app.last_result
            assert inspected['request']['recipient'] == recipient and inspected['request']['amount'] == 25000
            assert inspected['authenticated'] is False and inspected['single_use_enforced'] is False
            assert inspected['expiry_checked_against_ledger'] is False
            stable = files(root)
            enter(app, 'request_pin', '0'*64)
            assert app.last_result is None and not app.digest.get()
            app.actions['inspect'].invoke()
            assert app.last_result is None and files(root) == stable
            assert app.callback_errors == 0
            # GUI-produced bytes feed the already accepted signing module. The
            # desktop itself has no backend/path/password/fee/signing control.
            transaction = root/'payment.tx'
            signed = requests.prepare_request(path, request_pin, genesis, domain, wallet, pin, pool,
                                               transaction, '1000', password, requests.RequestBackend(binary, digest))
            assert signed['result'] == 'request_prepared_not_broadcast' and signed['broadcast'] is False
            final_pin = signed['receipt']
            persisted = wallet.read_bytes()
            restored = root/'pending.tx'
            pending = native(5, [wallet, pool, genesis, domain, restored], final_pin)
            assert pending['txid'] == signed['txid'] and restored.read_bytes() == transaction.read_bytes()
            state = native(3, [wallet, pool, genesis, domain], final_pin)
            assert state['pending'] is True and state['available'] == 0 and state['receipt'] == final_pin
            assert wallet.read_bytes() == persisted and path.read_bytes() == raw_request
            assert pool.read_bytes() == before[pool.relative_to(root)]
            stable = files(root)
            enter(app, 'request_pin', request_pin)
            app.actions['inspect'].invoke()
            assert app.last_result['authenticated'] is False and files(root) == stable
            app.actions['clear'].invoke()
            assert app.last_result is None and files(root) == stable
            assert app.callback_errors == 0
        finally:
            window.destroy()
    print('Actual desktop widgets created and inspected a request consumed by the original Rust wallet; exact signed pending/reservation preserved, refusals unchanged. No broadcast or retained private fixtures.')


if __name__ == '__main__':
    if len(sys.argv) != 2:
        raise SystemExit('One trusted native wallet executable is required')
    run(Path(sys.argv[1]))
