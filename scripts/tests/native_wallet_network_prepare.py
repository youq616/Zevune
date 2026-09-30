#!/usr/bin/env python3
"""Native valueless preparation only. Never submit/broadcast these test bytes.

Uses original binaries and production CLI. Only interactive input is replaced;
no network result, wallet result, signature, proof, or store is mocked.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import sys
from unittest.mock import patch

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import zevune_wallet as wallet
from native_wallet_network_sync import digest, read_frame, require, write_frame

STAGE = 'setup'


def copy_reference(source, target):
    if source.is_dir():
        shutil.copytree(source, target)
    else:
        shutil.copyfile(source, target)


def main():
    global STAGE
    require(len(sys.argv) == 6, 'scenario_arguments')
    root, network, worker, backend = (Path(p).resolve(strict=True) for p in sys.argv[1:5])
    mode = sys.argv[5]
    require(mode in ('02', '03') and root.is_dir() and not list(root.iterdir()), 'new_test_root')
    pins = dict(network=digest(network), worker=digest(worker), backend=digest(backend))
    password = os.urandom(32)
    sender = root/'sender.wallet'
    donor = root/'donor-offline.wallet'

    def call(op, fields, pin):
        return wallet.invoke(backend, wallet.encode_request(op, password, fields, pin), pins['backend'])

    pin = call(0, [str(donor)], None)['receipt']
    require(call(2, [str(donor), str(sender)], pin)['receipt'] == pin, 'offline_prescan_copy')
    seed = root/'seed-genesis.bin'
    seeded = call(7, [str(donor), str(root/'unused-pool'), str(seed)], pin)
    raw = seed.read_bytes()
    require(raw[:8] == b'ZVTGEN02', 'real_public_genesis')
    genesis = root/'genesis.bin'
    with genesis.open('xb') as f:
        f.write(b'ZVTGEN'+mode.encode('ascii')+raw[8:])
    genesis_pin = digest(genesis)
    reference = root/'reference'
    before = sender.read_bytes()
    write_frame(dict(stage='genesis', genesis_sha256=genesis_pin))
    STAGE = 'network-start'
    route = read_frame()
    require(set(route) == {'config', 'config_sha256', 'endpoint', 'socks_proxy', 'false_endpoint'}, 'route')
    # A real unspent Orchard receiver from the real donor; only its public
    # identity/checksum is encoded for the NEW explicit test network profile.
    body = bytes.fromhex(seeded['address'].split(':')[2])
    import hashlib
    destination = 'zvlab2:'+genesis_pin+':'+body.hex()+':'+hashlib.sha256(
        b'ZEVUNE-LOCAL-ADDRESS\0\x02'+bytes.fromhex(genesis_pin)+body).hexdigest()[:16]
    wallet.checked_recipient(destination, genesis_pin)

    def args(output, *, create=False, limit='128', false_peer=False):
        a = ['--no-real-funds','--backend',str(backend),'--backend-sha256',pins['backend'],
             '--pin',pin,'prepare-network',str(sender),str(output),
             '--journal',str(reference),'--genesis',str(genesis),'--genesis-sha256',genesis_pin,
             '--config',route['config'],'--config-sha256',route['config_sha256'],
             '--network-backend',str(network),'--network-backend-sha256',pins['network'],
             '--worker',str(worker),'--worker-sha256',pins['worker'],
             '--endpoint',route['false_endpoint'] if false_peer else route['endpoint'],
             '--limit',limit,'--expiry-blocks','100']
        if not false_peer:
            a += ['--socks-proxy',route['socks_proxy']]
        if create:
            a += ['--create-reference']
        return a

    def run(output, *, fail=False, no_input=False, prompt=None, **kw):
        out, err = io.StringIO(), io.StringIO()
        with patch('builtins.input', side_effect=[destination,'7','1','PREPARE']) as inputs, \
             patch.object(wallet,'hidden_password',side_effect=prompt or (lambda _: password)) as secret, \
             contextlib.redirect_stdout(out),contextlib.redirect_stderr(err):
            code=wallet.main(args(output,**kw))
        if no_input:
            require(inputs.call_count==0 and secret.call_count==0, 'refusal_before_secret')
        if fail:
            require(code==1 and not out.getvalue(), 'not_false_success')
            if not no_input:
                require(inputs.call_count==4 and secret.call_count==1, 'must_reach_real_wallet_refusal')
            return None
        require(code==0 and inputs.call_count==4 and secret.call_count==1, 'real_prepare_network')
        r=json.loads(out.getvalue())
        require(r['result']=='network_verified_payment_prepared_not_broadcast'
                and r['broadcast'] is False and r['real_funds_allowed'] is False
                and r['latest_verified'] is False and r['retry_authorized'] is False
                and r['network']['caught_up_to_observed_tip'] is True, 'result_scope')
        require(r['wallet']['height']==r['network']['height']
                and r['wallet']['app_hash']==r['network']['app_hash'], 'same_verified_checkpoint')
        return r

    def recover(output, expected, *, false_peer=False, fail=False):
        a = args(output, false_peer=false_peer)
        a[a.index('prepare-network')] = 'recover-pending-network'
        i = a.index('--expiry-blocks'); del a[i:i+2]
        out, err = io.StringIO(), io.StringIO()
        frozen = sender.read_bytes()
        with patch('builtins.input', return_value='RECOVER') as inputs, \
             patch.object(wallet, 'hidden_password', return_value=password) as secret, \
             contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = wallet.main(a)
        require(sender.read_bytes() == frozen, 'readonly_recovery_keeps_complete_wallet')
        if fail:
            require(code == 1 and not out.getvalue() and not output.exists(), 'recovery_refusal')
            require(inputs.call_count == 0 and secret.call_count == 0, 'recovery_before_secret')
            return
        require(code == 0 and inputs.call_count == 1 and secret.call_count == 1, 'real_recovery_network')
        r = json.loads(out.getvalue())
        require(r['result'] == 'network_verified_pending_recovered_not_broadcast'
                and r['broadcast'] is False and r['real_funds_allowed'] is False
                and r['retry_authorized'] is False and r['latest_verified'] is False
                and r['network']['caught_up_to_observed_tip'] is True, 'recovery_scope')
        require(r['wallet']['result'] == 'checkpoint_pending_exported_not_broadcast'
                and r['wallet']['wallet_unchanged'] is True and r['wallet']['broadcast'] is False
                and r['wallet']['receipt'] == expected['receipt']
                and r['wallet']['txid'] == expected['txid']
                and r['wallet']['height'] == r['network']['height']
                and r['wallet']['app_hash'] == r['network']['app_hash'], 'recovery_checkpoint_and_receipt')
        require(output.read_bytes() == signed and txfile.read_bytes() == signed,
                'recovery_exact_saved_signed_bytes_no_resign')

    STAGE='initial-catchup'
    run(root/'partial.tx',create=True,limit='1',fail=True,no_input=True)
    require(sender.read_bytes()==before and not (root/'partial.tx').exists(),'partial_no_wallet_mutation')
    early = root/'early-reference'; copy_reference(reference,early)

    STAGE='false-peer-refusal'
    run(root/'false.tx',false_peer=True,fail=True,no_input=True)
    require(sender.read_bytes()==before and not (root/'false.tx').exists(),'false_peer_unchanged')

    STAGE='stale-handoff-refusal'
    latest=root/'saved-live-reference'; changed=False
    def swap(_):
        nonlocal changed
        reference.rename(latest); early.rename(reference); changed=True
        return password
    try:
        run(root/'stale.tx',fail=True,prompt=swap)
        require(changed and sender.read_bytes()==before and not (root/'stale.tx').exists(),'stale_handoff')
    finally:
        # Explicit restoration of only PUBLIC temporary test fixtures. Not a
        # production rollback/retry and never a rollback of encrypted wallets.
        if changed:
            reference.rename(early); latest.rename(reference)

    STAGE='real-payment-and-pending'
    txfile=root/'payment.tx'
    result=run(txfile)
    state=result['wallet']; signed=txfile.read_bytes()
    require(signed[:8]==b'ZVORLAB2' and signed[8:40].hex()==genesis_pin
            and digest(txfile)==state['txid'] and state['broadcast'] is False,'real_signed_bytes')
    require(state['receipt'][:64]==pin[:64]
            and int(state['receipt'][64:80],16)==int(pin[64:80],16)+1,'one_original_record')
    require(int.from_bytes(signed[40:48],'big')==state['height']+100,'expiry_from_verified_height')
    saved=sender.read_bytes()
    # Same verified history and same store checkpoint: export the saved outbox,
    # not another proof. Save public history before later independent sync calls.
    signing_reference=root/'signing-reference'; copy_reference(reference,signing_reference)
    fields=[str(sender),str(signing_reference),str(genesis),genesis_pin]
    same=root/'same-pending.tx'
    exported=call(5,fields+[str(same)],state['receipt'])
    require(same.read_bytes()==signed and exported['txid']==state['txid']
            and exported['receipt']==state['receipt'] and sender.read_bytes()==saved,'exact_pending_no_resign')
    run(root/'second.tx',fail=True)
    require(sender.read_bytes()==saved and not (root/'second.tx').exists(),'pending_cannot_be_replaced')

    STAGE='readonly-pending-recovery'
    recover(root/'recovered-pending.tx', state)
    recover(root/'recovered-same-again.tx', state)
    recover(root/'false-recovery.tx', state, false_peer=True, fail=True)
    require(sender.read_bytes()==saved, 'recovery_keeps_original_receipt_and_outbox')

    write_frame(dict(stage='restart',height=state['height']))
    require(read_frame()=={'stage':'restarted'},'restart_coordination')
    STAGE='restart-rescan'
    run(root/'after-restart.tx',fail=True)
    require(sender.read_bytes()==saved and not (root/'after-restart.tx').exists(),'restart_keeps_pending')
    again=root/'exact-after-restart.tx'
    recovered=call(5,fields+[str(again)],state['receipt'])
    require(again.read_bytes()==signed and recovered['receipt']==state['receipt']
            and sender.read_bytes()==saved,'persistent_exact_pending')
    recover(root/'recovered-after-restart.tx', state)
    require(sender.read_bytes()==saved, 'restart_recovery_does_not_publish_scan')
    write_frame(dict(stage='done',real_funds_allowed=False,partial_refused=True,
                     stale_handoff_rejected=True,false_peer_rejected=True,pending_preserved=True))
    require(sys.stdin.buffer.read(1)==b'','supervisor_eof')


if __name__=='__main__':
    try:
        main()
    except BaseException:
        try:
            write_frame(dict(stage='failed',step=STAGE))
        except BaseException:
            pass
        sys.stderr.write('Native network preparation scenario failed.\n')
        raise SystemExit(1) from None
