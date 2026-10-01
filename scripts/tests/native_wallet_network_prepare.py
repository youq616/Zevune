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
DETAIL = {}
FAILURE_CODES = frozenset(('unknown', 'config_canonicalization_failed', 'preflight_refused',
    'network_call_failed', 'network_result_refused', 'partial_evidence_mismatch',
    'partial_command_mismatch', 'partial_private_boundary', 'missing_reference',
    'reference_copy_failed'))
FAILURE_STEPS = frozenset(('setup', 'network-start', 'initial-config',
    'initial-partial-command', 'initial-partial-check', 'initial-reference-copy',
    'false-peer-refusal', 'stale-handoff-refusal', 'real-payment-and-pending',
    'restart-rescan', 'readonly-pending-recovery'))


class FixtureFailure(RuntimeError):
    def __init__(self, code):
        self.code = code if code in FAILURE_CODES else 'unknown'
        super().__init__(self.code)


def canonical_config(route, detail):
    # Normalize only this test's generated path, exactly as the older sync driver
    # already does. Production pinned-file/path rejection remains unchanged.
    try:
        original = Path(route['config'])
        resolved = original.resolve(strict=True)
        detail['config_was_canonical'] = original == resolved
        detail['config_canonical'] = True
        result = dict(route)
        result['config'] = str(resolved)
        return result
    except (OSError, ValueError, TypeError):
        detail['config_canonical'] = False
        raise FixtureFailure('config_canonicalization_failed') from None


@contextlib.contextmanager
def observe_original_reference(detail):
    # Transparent observation of the actual pinned verifier. Each wrapper calls
    # its original function and returns its original result; it fabricates none.
    original_reference = wallet._verified_network_reference
    original_network = wallet._sync_network_process
    original_wallet = wallet.invoke
    observed = {'network': None, 'network_returned': False, 'wallet_calls': 0}
    detail.update(verifier_calls=0, network_calls=0, verified_partial=False)
    def reference(*args, **kw):
        detail['verifier_calls'] += 1
        result = original_reference(*args, **kw)
        observed['network'] = {key: result[1][key] for key in (
            'height', 'new_blocks', 'observed_signed_tip', 'caught_up_to_observed_tip',
            'base_checkpoint_matched', 'real_funds_allowed')}
        return result
    def network(*args, **kw):
        detail['network_calls'] += 1
        result = original_network(*args, **kw)
        observed['network_returned'] = True
        return result
    def invoke(*args, **kw):
        observed['wallet_calls'] += 1
        return original_wallet(*args, **kw)
    with patch.object(wallet, '_verified_network_reference', side_effect=reference), \
         patch.object(wallet, '_sync_network_process', side_effect=network), \
         patch.object(wallet, 'invoke', side_effect=invoke):
        yield observed


def checked_initial_partial(observed, detail, code, stdout, input_calls, secret_calls, reference):
    detail['reference_exists'] = reference.exists()
    if observed['network'] is None:
        if detail['network_calls'] == 0:
            raise FixtureFailure('preflight_refused')
        if not observed['network_returned']:
            raise FixtureFailure('network_call_failed')
        raise FixtureFailure('network_result_refused')
    n = observed['network']
    if (detail['verifier_calls'] != 1 or detail['network_calls'] != 1
            or observed['network_returned'] is not True
            or type(n['height']) is not int or n['height'] != 1
            or type(n['new_blocks']) is not int or n['new_blocks'] != 1
            or type(n['observed_signed_tip']) is not int or not 3 <= n['observed_signed_tip'] <= 1000000
            or n['caught_up_to_observed_tip'] is not False
            or n['base_checkpoint_matched'] is not False or n['real_funds_allowed'] is not False):
        raise FixtureFailure('partial_evidence_mismatch')
    if type(code) is not int or code != 1 or stdout:
        raise FixtureFailure('partial_command_mismatch')
    if input_calls != 0 or secret_calls != 0 or observed['wallet_calls'] != 0:
        raise FixtureFailure('partial_private_boundary')
    if not detail['reference_exists']:
        raise FixtureFailure('missing_reference')
    detail['verified_partial'] = True


def failure_frame(error, step, detail):
    code = error.code if type(error) is FixtureFailure else 'unknown'
    result = dict(stage='failed', step=step if step in FAILURE_STEPS else 'unknown',
                  code=code if code in FAILURE_CODES else 'unknown')
    for name in ('config_was_canonical', 'config_canonical', 'reference_exists', 'verified_partial'):
        value = detail.get(name)
        result[name] = value if type(value) is bool else None
    for name in ('verifier_calls', 'network_calls'):
        value = detail.get(name)
        result[name] = min(value, 2) if type(value) is int and value >= 0 else None
    return result


def run_preparation(argv, destination, password, *, fail=False, no_input=False, prompt=None,
                    partial_reference=None, detail=None):
    out, err = io.StringIO(), io.StringIO()
    observer = (observe_original_reference(detail) if partial_reference is not None
                else contextlib.nullcontext(None))
    with observer as observed, \
         patch('builtins.input', side_effect=[destination,'7','1','PREPARE']) as inputs, \
         patch.object(wallet,'hidden_password',side_effect=prompt or (lambda _: password)) as secret, \
         contextlib.redirect_stdout(out),contextlib.redirect_stderr(err):
        code=wallet.main(argv)
    if partial_reference is not None:
        checked_initial_partial(observed, detail, code, out.getvalue(), inputs.call_count,
                                secret.call_count, partial_reference)
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


def copy_reference(source, target):
    if source.is_dir():
        shutil.copytree(source, target)
    else:
        shutil.copyfile(source, target)


def copy_initial_reference(source, target, detail):
    detail['reference_exists'] = source.exists()
    if not detail['reference_exists']:
        raise FixtureFailure('missing_reference')
    try:
        copy_reference(source, target)
    except OSError:
        raise FixtureFailure('reference_copy_failed') from None


def main():
    global STAGE, DETAIL
    DETAIL = {}
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
    STAGE = 'initial-config'
    route = canonical_config(route, DETAIL)
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

    def run(output, *, fail=False, no_input=False, prompt=None, partial=False, **kw):
        return run_preparation(args(output, **kw), destination, password, fail=fail,
            no_input=no_input, prompt=prompt,
            partial_reference=reference if partial else None, detail=DETAIL)

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

    STAGE='initial-partial-command'
    run(root/'partial.tx',create=True,limit='1',fail=True,no_input=True,partial=True)
    STAGE='initial-partial-check'
    require(sender.read_bytes()==before and not (root/'partial.tx').exists(),'partial_no_wallet_mutation')
    STAGE='initial-reference-copy'
    early = root/'early-reference'
    copy_initial_reference(reference, early, DETAIL)

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
                     stale_handoff_rejected=True,false_peer_rejected=True,pending_preserved=True,
                     verified_partial=DETAIL['verified_partial'],config_canonical=DETAIL['config_canonical'],
                     config_was_canonical=DETAIL['config_was_canonical']))
    require(sys.stdin.buffer.read(1)==b'','supervisor_eof')


if __name__=='__main__':
    try:
        main()
    except BaseException as error:
        try:
            write_frame(failure_frame(error, STAGE, DETAIL))
        except BaseException:
            pass
        sys.stderr.write('Native network preparation scenario failed.\n')
        raise SystemExit(1) from None
