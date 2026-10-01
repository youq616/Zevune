#!/usr/bin/env python3
"""Actual valueless wallet/network binaries; only terminal input is substituted.

Two explicit submissions of DIFFERENT genuine fixture payments: one accepted,
then one whose real upstream response is lost. Neither operation may re-sign,
change wallet bytes or automatically retry. The Go coordinator checks broadcast
bytes/counts and brings quorum back before shutdown (mempools aren't durable).
"""
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import sys
from unittest.mock import patch

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import zevune_wallet as wallet
import native_wallet_network_prepare as preparation
from native_wallet_network_sync import digest, read_frame, require, write_frame

STAGE = 'setup'
DETAIL = {}
PENDING_FAILURE_STEPS = frozenset(('setup', 'submission-config', 'partial-submission-refusal',
    'prepare-0', 'prepare-1', 'submit-0', 'submit-1', 'reconcile-0', 'reconcile-1'))


def pending_failure_frame(error, step, detail):
    # Reuse the already reviewed fixed-code/boolean/counter encoder; only the
    # bounded stage vocabulary differs for this two-payment native scenario.
    report = preparation.failure_frame(error, 'unknown', detail)
    report['step'] = step if type(step) is str and step in PENDING_FAILURE_STEPS else 'unknown'
    return report


def run_pending_command(argv, answers, password, *, success=True, before_secret=False,
                        partial_reference=None, detail=None):
    out, err = io.StringIO(), io.StringIO()
    observer = (preparation.observe_original_reference(detail) if partial_reference is not None
                else contextlib.nullcontext(None))
    with observer as observed, patch('builtins.input', side_effect=answers) as prompt, \
         patch.object(wallet, 'hidden_password', return_value=password) as secret, \
         contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = wallet.main(argv)
    if partial_reference is not None:
        preparation.checked_initial_partial(observed, detail, code, out.getvalue(),
            prompt.call_count, secret.call_count, partial_reference)
    require(code == (0 if success else 1), 'actual_command_exit')
    if before_secret:
        require(prompt.call_count == 0 and secret.call_count == 0, 'pre_secret_refusal')
    elif answers:
        require(prompt.call_count == len(answers) and secret.call_count == 1, 'actual_ui_boundary')
    if not success:
        require(not out.getvalue(), 'failure_has_no_success')
        return None
    return json.loads(out.getvalue())


def main():
    global STAGE, DETAIL
    DETAIL = {}
    require(len(sys.argv) == 6, 'arguments')
    root, network, worker, backend = (Path(p).resolve(strict=True) for p in sys.argv[1:5])
    mode = sys.argv[5]
    require(mode in ('02', '03') and root.is_dir() and not list(root.iterdir()), 'private_new_fixture')
    pins = dict(network=digest(network), worker=digest(worker), backend=digest(backend))
    password = os.urandom(32)
    sender, donor = root/'sender.wallet', root/'offline-donor.wallet'
    def call(op, fields, pin):
        return wallet.invoke(backend, wallet.encode_request(op, password, fields, pin), pins['backend'])
    pin = call(0, [str(donor)], None)['receipt']
    require(call(2, [str(donor), str(sender)], pin)['receipt'] == pin, 'pre_scan_copy')
    seed = root/'seed-genesis.bin'
    seeded = call(7, [str(donor), str(root/'unused-pool'), str(seed)], pin)
    raw = seed.read_bytes()
    require(raw[:8] == b'ZVTGEN02', 'real_genesis')
    genesis = root/'genesis.bin'
    with genesis.open('xb') as f:
        f.write(b'ZVTGEN'+mode.encode('ascii')+raw[8:])
    genesis_pin = digest(genesis)
    reference = root/'reference'
    body = bytes.fromhex(seeded['address'].split(':')[2])
    destination = 'zvlab2:'+genesis_pin+':'+body.hex()+':'+hashlib.sha256(
        b'ZEVUNE-LOCAL-ADDRESS\0\x02'+bytes.fromhex(genesis_pin)+body).hexdigest()[:16]
    wallet.checked_recipient(destination, genesis_pin)
    write_frame(dict(stage='genesis', genesis_sha256=genesis_pin))
    route = read_frame()
    require(set(route) == {'config','config_sha256','endpoint','socks_proxy'}, 'route')
    STAGE = 'submission-config'
    route = preparation.canonical_config(route, DETAIL)

    def args(kind, *, output=None, create=False, limit='128'):
        a = ['--no-real-funds','--backend',str(backend),'--backend-sha256',pins['backend'],
             '--pin',pin,kind,str(sender)]
        if output is not None:
            a.append(str(output))
        a += ['--journal',str(reference),'--genesis',str(genesis),'--genesis-sha256',genesis_pin,
              '--config',route['config'],'--config-sha256',route['config_sha256'],
              '--network-backend',str(network),'--network-backend-sha256',pins['network'],
              '--worker',str(worker),'--worker-sha256',pins['worker'],
              '--endpoint',route['endpoint'],'--socks-proxy',route['socks_proxy'],'--limit',limit]
        if kind == 'prepare-network': a += ['--expiry-blocks','100']
        if create: a += ['--create-reference']
        return a

    def run(a, answers, *, success=True, before_secret=False):
        return run_pending_command(a, answers, password, success=success, before_secret=before_secret,
            partial_reference=reference if before_secret else None, detail=DETAIL)

    STAGE = 'partial-submission-refusal'
    initial_wallet = sender.read_bytes()
    run(args('submit-pending-network',create=True,limit='1'), [], success=False, before_secret=True)
    require(sender.read_bytes() == initial_wallet, 'partial_unchanged')
    ids = []
    for index in (0, 1):
        STAGE = 'prepare-'+str(index)
        payment = root/('payment-'+str(index)+'.tx')
        prepared = run(args('prepare-network',output=payment), [destination,'7','1','PREPARE'])
        state = prepared['wallet']
        signed = payment.read_bytes()
        require(signed[:8] == b'ZVORLAB2' and signed[8:40].hex() == genesis_pin
                and digest(payment) == state['txid'] and state['broadcast'] is False, 'genuine_bytes')
        ids.append(state['txid'])
        pin = state['receipt']
        saved = sender.read_bytes()
        # The wire body is expected by Go before it allows this one RPC send.
        write_frame(dict(stage='ready-to-submit',round=index,txid=state['txid']))
        require(read_frame() == {'stage':'submit-now'}, 'submission_coordination')
        STAGE = 'submit-'+str(index)
        result = run(args('submit-pending-network'), ['SUBMIT'], success=index == 0)
        require(sender.read_bytes() == saved and payment.read_bytes() == signed,
                'submission_never_mutates_or_resigns_wallet')
        if index == 0:
            require(result['result'] == 'pending_accepted_to_mempool_not_confirmed'
                    and result['txid'] == state['txid'] and result['receipt'] == pin
                    and result['confirmed'] is False and result['wallet_unchanged'] is True
                    and result['retry_authorized'] is False and result['real_funds_allowed'] is False
                    and result['submission']['base_checkpoint_matched'] is True, 'nonconfirmation_only')
        require(not list(root.glob('.zevune-submit-*')), 'normal_scratch_cleanup')
        # Same original locked reference and valid ancestor pin: inspect exact
        # stored outbox through opcode13 BEFORE separate, explicit reconciliation.
        recovered = root/('still-same-'+str(index)+'.tx')
        recovered_result = call(13, [str(sender),str(reference),str(genesis),genesis_pin,
                                str(recovered),str(state['height']),state['app_hash']], pin)
        require(recovered.read_bytes() == signed and recovered_result['receipt'] == pin
                and recovered_result['wallet_unchanged'] is True
                and sender.read_bytes() == saved, 'pending_preserved_after_receipt_or_unknown')
        write_frame(dict(stage='submitted',round=index,height=state['height']))
        require(read_frame() == {'stage':'included-and-restarted'}, 'actual_inclusion_and_restart')
        # A NEW explicit authenticated reconciliation, not part of submission.
        STAGE = 'reconcile-'+str(index)
        scanned = run(args('sync-network'), [])['wallet']
        require(scanned['pending'] is False and scanned['balance'] == 100000-(index+1)
                and scanned['available'] == scanned['balance'], 'authenticated_post_restart_state')
        pin = scanned['receipt']
    require(ids[0] != ids[1], 'distinct_fixture_payments')
    write_frame(dict(stage='done',real_funds_allowed=False,accepted_not_confirmed=True,
                     lost_response_unknown=True,pending_preserved=True,restarted=True,
                     verified_partial=DETAIL['verified_partial'],config_canonical=DETAIL['config_canonical'],
                     config_was_canonical=DETAIL['config_was_canonical']))


if __name__ == '__main__':
    try:
        main()
    except BaseException as error:
        try:
            write_frame(pending_failure_frame(error, STAGE, DETAIL))
        except BaseException:
            pass
        print('Native saved-pending submission failed; private data suppressed.', file=sys.stderr)
        raise SystemExit(1) from None
