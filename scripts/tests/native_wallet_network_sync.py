#!/usr/bin/env python3
"""Native-only valueless P4 scenario. Go supplies public network coordinates.

All network/wallet/worker calls execute actual independently pinned binaries.
Only the interactive password prompt is replaced; secrets never cross the Go
coordinator, arguments, environment or public progress frames. No fake verifier.
"""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import struct
import sys
from unittest.mock import patch

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import zevune_wallet as wallet

STAGE = "setup"


def require(value, stage):
    if not value:
        raise RuntimeError(stage)


def write_frame(value):
    raw = json.dumps(value, sort_keys=True).encode('utf-8')
    require(0 < len(raw) <= 4096, 'public_frame_bounds')
    sys.stdout.buffer.write(struct.pack('>I', len(raw)) + raw)
    sys.stdout.buffer.flush()


def read_frame():
    def exact(n):
        result = bytearray()
        while len(result) < n:
            part = sys.stdin.buffer.read(n - len(result))
            require(bool(part), 'public_frame_eof')
            result.extend(part)
        return bytes(result)
    size = struct.unpack('>I', exact(4))[0]
    require(0 < size <= 4096, 'public_frame_bounds')
    return json.loads(exact(size))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    global STAGE
    require(len(sys.argv) == 6, 'scenario_arguments')
    root, network, worker, backend = (Path(p).resolve(strict=True) for p in sys.argv[1:5])
    mode = sys.argv[5]
    require(mode in ('02', '03') and root.is_dir() and not list(root.iterdir()), 'new_test_root')
    pins = dict(network=digest(network), worker=digest(worker), backend=digest(backend))
    passwords = [os.urandom(32), os.urandom(32)]
    actors = [root / 'alice.wallet', root / 'bob.wallet']
    receipts = [None, None]

    def call(op, actor, fields, pin):
        return wallet.invoke(backend, wallet.encode_request(op, passwords[actor], fields, pin), pins['backend'])

    # Only the public test allocation is reused when selecting a NEW 03 genesis.
    # Donor remains offline. Alice was copied BEFORE any network scan, so neither
    # a 02 journal nor a synchronized wallet is reinterpreted as an active one.
    donor = root / 'donor-offline.wallet'
    created = call(0, 0, [str(donor)], None)
    receipts[0] = created['receipt']
    copied = call(2, 0, [str(donor), str(actors[0])], receipts[0])
    require(copied['receipt'] == receipts[0], 'initial_private_copy')
    receipts[1] = call(0, 1, [str(actors[1])], None)['receipt']
    seed = root / 'unused-seed-genesis.bin'
    call(7, 0, [str(donor), str(root / 'unused-seed.journal'), str(seed)], receipts[0])
    raw = seed.read_bytes()
    require(raw[:8] == b'ZVTGEN02', 'actual_seed_genesis')
    genesis = root / 'genesis.bin'
    # Public-only fresh profile fixture. The real decoder independently checks
    # every allocation/note and supply when initializing the NEW network.
    with genesis.open('xb') as stream:
        stream.write(b'ZVTGEN' + mode.encode('ascii') + raw[8:])
    genesis_pin = digest(genesis)
    reference = root / 'reference.journal'
    write_frame(dict(stage='genesis', genesis_sha256=genesis_pin))
    STAGE = 'network-start'
    route = read_frame()
    require(set(route) == {'config', 'config_sha256', 'endpoint', 'socks_proxy', 'false_endpoint'}, 'route_shape')

    route['config'] = str(Path(route['config']).resolve(strict=True))

    def arguments(actor, create=False, limit='128', *, false_peer=False):
        args = ['--no-real-funds', '--backend', str(backend), '--backend-sha256', pins['backend'],
                '--pin', receipts[actor], 'sync-network', str(actors[actor]),
                '--journal', str(reference), '--genesis', str(genesis), '--genesis-sha256', genesis_pin,
                '--config', route['config'], '--config-sha256', route['config_sha256'],
                '--network-backend', str(network), '--network-backend-sha256', pins['network'],
                '--worker', str(worker), '--worker-sha256', pins['worker'],
                '--endpoint', route['false_endpoint'] if false_peer else route['endpoint'], '--limit', limit]
        if not false_peer:
            args.extend(['--socks-proxy', route['socks_proxy']])
        if create:
            args.append('--create-reference')
        return args

    def run_sync(actor, *, create=False, limit='128', prompt=None, fail=False, false_peer=False):
        output, errors = io.StringIO(), io.StringIO()
        # Replace ONLY the terminal UI. Exact production main, source pins,
        # network subprocess/Go verifier, Rust opcode11 and journal locks execute.
        with patch.object(wallet, 'hidden_password', side_effect=prompt or (lambda _: passwords[actor])), \
                contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            code = wallet.main(arguments(actor, create, limit, false_peer=false_peer))
        if fail:
            require(code == 1 and not output.getvalue(), 'failure_not_success')
            return None
        require(code == 0, 'sync_network_failed')
        value = json.loads(output.getvalue())
        require(value['result'] == 'network_verified_wallet_scanned'
                and value['real_funds_allowed'] is False and value['broadcast'] is False
                and value['latest_verified'] is False and value['retry_authorized'] is False,
                'result_scope')
        state = value['wallet']
        require(state['checkpoint_matched'] is True
                and state['height'] == value['network']['height']
                and state['app_hash'] == value['network']['app_hash'], 'cross_backend_checkpoint')
        receipts[actor] = state['receipt']
        return value

    STAGE = 'initial-catchup'
    initial = run_sync(0, create=True, limit='1')
    require(initial['network']['height'] == 1 and initial['network']['new_blocks'] == 1
            and initial['network']['caught_up_to_observed_tip'] is False
            and initial['wallet']['balance'] == 100000, 'bounded_partial_catchup')
    old_reference = root / 'retained-early-reference'
    if reference.is_dir():
        shutil.copytree(reference, old_reference)
    else:
        shutil.copyfile(reference, old_reference)
    received = run_sync(1)
    require(received['wallet']['balance'] == 0 and received['wallet']['available'] == 0, 'initial_receiver')
    base_fields = lambda actor: [str(actors[actor]), str(reference), str(genesis), genesis_pin]
    STAGE = 'real-payment-and-pending'
    address = call(8, 1, base_fields(1) + ['0'], receipts[1])
    receipts[1] = address['receipt']
    txfile = root / 'payment.tx'
    prepared = call(4, 0, base_fields(0) + [address['address'], '7', '1',
                    str(received['wallet']['height'] + 100), str(txfile)], receipts[0])
    receipts[0] = prepared['receipt']
    raw_tx = txfile.read_bytes()
    require(raw_tx[:8] == b'ZVORLAB2' and raw_tx[8:40].hex() == genesis_pin
            and digest(txfile) == prepared['txid'], 'genuine_payment_bytes')
    pending = run_sync(0)['wallet']
    require(pending['pending'] is True and pending['available'] == 0 and pending['balance'] == 100000,
            'reservation_retained_before_broadcast')
    same_tx = root / 'same-pending.tx'
    reply = call(5, 0, base_fields(0) + [str(same_tx)], receipts[0])
    receipts[0] = reply['receipt']
    require(same_tx.read_bytes() == raw_tx and reply['txid'] == prepared['txid'], 'no_resign')
    # Broadcast is ONLY an explicit fixture operation via the existing command.
    # The production sync-network operation never submits or signs anything.
    submit = [str(network), 'submit', '--no-real-funds', '--worker', str(worker),
              '--worker-sha256', pins['worker'], '--config', route['config'],
              '--config-sha256', route['config_sha256'], '--endpoint', route['endpoint'],
              '--socks-proxy', route['socks_proxy'], '--journal', str(reference), '--tx', str(txfile)]
    STAGE = 'explicit-fixture-broadcast'
    response = wallet._sync_json(wallet._sync_network_process(submit), 4096)
    require(response['status'] == 'accepted_to_mempool_not_confirmed'
            and response['confirmed'] is False and response['txid'] == prepared['txid'], 'one_mempool_not_confirmation')
    write_frame(dict(stage='submitted'))
    require(read_frame() == {'stage': 'included'}, 'inclusion_coordination')
    STAGE = 'payment-rescan'
    sender = run_sync(0)['wallet']
    receiver = run_sync(1)['wallet']
    require(sender['pending'] is False and sender['balance'] == 99992 and sender['available'] == 99992,
            'sender_authenticated_settlement')
    require(receiver['pending'] is False and receiver['balance'] == 7 and receiver['available'] == 7,
            'receiver_genuine_decryption')
    write_frame(dict(stage='restart', height=receiver['height']))
    require(read_frame() == {'stage': 'restarted'}, 'restart_coordination')
    STAGE = 'restart-rescan'
    require(run_sync(0)['wallet']['balance'] == 99992 and run_sync(1)['wallet']['balance'] == 7,
            'restart_rescan')

    STAGE = 'false-peer-refusal'
    before = [path.read_bytes() for path in actors]
    def must_not_prompt(_):
        raise RuntimeError('untrusted_peer_reached_password')
    # Capture the prompt call count separately so an exception converted to a
    # CLI failure cannot masquerade as pre-wallet rejection.
    with patch.object(wallet, 'hidden_password', side_effect=must_not_prompt) as blocked, \
            contextlib.redirect_stdout(io.StringIO()) as output, contextlib.redirect_stderr(io.StringIO()):
        code = wallet.main(arguments(0, false_peer=True))
    require(code == 1 and not output.getvalue() and blocked.call_count == 0, 'unsigned_peer_rejected_before_unlock')
    require([path.read_bytes() for path in actors] == before and txfile.read_bytes() == raw_tx,
            'false_peer_preserved_wallets')

    STAGE = 'stale-handoff-refusal'
    latest_reference = root / 'retained-latest-reference'
    replaced = False
    def replace_gap(_):
        nonlocal replaced
        reference.rename(latest_reference)
        old_reference.rename(reference)
        replaced = True
        return passwords[0]
    try:
        run_sync(0, prompt=replace_gap, fail=True)
        require(replaced and [path.read_bytes() for path in actors] == before,
                'late_reference_change_preserved_wallets')
    finally:
        # Explicit test-only restoration of PUBLIC ephemeral fixtures. No wallet
        # rollback, deletion, recovery operation or retry is added to production.
        if replaced:
            reference.rename(old_reference)
            latest_reference.rename(reference)
    STAGE = 'final-rescan'
    require(run_sync(0)['wallet']['balance'] == 99992, 'healthy_reference_after_fault')
    write_frame(dict(stage='done', real_funds_allowed=False, private_route_exercised=True,
                     false_peer_rejected=True, stale_handoff_rejected=True))
    require(sys.stdin.buffer.read(1) == b'', 'expected_supervisor_eof')


if __name__ == '__main__':
    try:
        main()
    except BaseException:
        # Never expose passwords, local wallet data or arbitrary exception text.
        try:
            write_frame(dict(stage='failed', step=STAGE))
        except BaseException:
            pass
        sys.stderr.write('Native wallet-network scenario failed.\n')
        raise SystemExit(1) from None
