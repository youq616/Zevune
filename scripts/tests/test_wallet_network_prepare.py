"""Orchestration/UI isolation only, not accepted cryptography or a fake binary.
The native scenario calls the real verifier and opcode12 without these mocks.
"""
import argparse
import contextlib
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import zevune_wallet as w

PIN = '11' * 32 + '0000000000000001' + '22' * 32
PASSWORD = b'synthetic-prepare-ui-only-password'


def signed_result():
    # Just a parser/UI input, NEVER submitted as a certificate or Orchard proof.
    return dict(scope='fixed_validator_local_test_network', height=3, app_hash='33' * 32,
                root='44' * 32, new_blocks=3, observed_signed_tip=4,
                caught_up_to_observed_tip=True, real_funds_allowed=False,
                base_checkpoint_matched=False)


def decode_frame(raw):
    if raw[:8] != b'ZVWCLI01':
        raise AssertionError('frame magic')
    op = raw[8]; n = int.from_bytes(raw[9:11], 'big')
    password = raw[11:11+n]; pos = 11+n
    if raw[pos] != 1:
        raise AssertionError('required receipt')
    pin = raw[pos+1:pos+73].hex(); pos += 73
    count = raw[pos]; pos += 1; fields = []
    for _ in range(count):
        n = int.from_bytes(raw[pos:pos+2], 'big'); pos += 2
        fields.append(raw[pos:pos+n].decode()); pos += n
    if pos != len(raw):
        raise AssertionError('trailing frame')
    return op, password, pin, fields


class NetworkPreparationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        public = (b'ZVTGEN02' + hashlib.sha256(b'zevune-orchard-lab-1').digest()
                  + (100000).to_bytes(8, 'big') + b'\x00\x01' + b'\x55'*32
                  + b'\x66'*43 + (100000).to_bytes(8, 'big') + b'\x77'*64)
        self.genesis = self.root/'genesis'; self.genesis.write_bytes(public)
        self.gpin = hashlib.sha256(public).hexdigest()
        conf = dict(version=1, chain_id='zevune-orchard-lab-1', asset_genesis_sha256=self.gpin,
                    consensus_genesis_sha256='11'*32, node_ids=['11'*20]*4)
        self.config = self.root/'config'; self.config.write_text(json.dumps(conf))
        self.prog = self.root/'not-executed'; self.prog.write_bytes(b'not a binary')
        bpin = hashlib.sha256(self.prog.read_bytes()).hexdigest()
        self.a = argparse.Namespace(no_real_funds=True, command='prepare-network',
            backend=self.prog, backend_sha256=bpin, network_backend=self.prog,
            network_backend_sha256=bpin, worker=self.prog, worker_sha256=bpin,
            config=self.config, config_sha256=hashlib.sha256(self.config.read_bytes()).hexdigest(),
            genesis=self.genesis, genesis_sha256=self.gpin, wallet=self.root/'wallet',
            journal=self.root/'reference', pin=PIN, endpoint='http://127.0.0.1:26657',
            socks_proxy=None, create_reference=True, limit='128', output=self.root/'payment.tx',
            expiry_blocks='20')
        self.a.wallet.write_bytes(b'original synthetic wallet bytes, not an encrypted wallet')
        body = bytes(range(43))
        self.destination = 'zvlab2:'+self.gpin+':'+body.hex()+':'+hashlib.sha256(
            b'ZEVUNE-LOCAL-ADDRESS\0\x02'+bytes.fromhex(self.gpin)+body).hexdigest()[:16]
        self.result = dict(ok=True, scope='local_journal_only_no_funds',
            result='checkpoint_payment_saved_not_broadcast', checkpoint_matched=True,
            height=3, app_hash='33'*32, txid='55'*32, receipt=PIN[:64]+'0000000000000002'+'66'*32,
            broadcast=False, payment_profile='LAB2', signing_domain=self.gpin, genesis_sha256=self.gpin)

    def invoke(self, *, network=None, answer=None, prompts=None, secret=None, expected=None):
        """UI isolation: successful path is NOT counted as a real wallet test."""
        with contextlib.ExitStack() as s:
            stdout = s.enter_context(contextlib.redirect_stdout(io.StringIO()))
            s.enter_context(contextlib.redirect_stderr(io.StringIO()))
            process = s.enter_context(patch.object(w, '_sync_network_process',
                **({'side_effect': network} if callable(network) or isinstance(network, BaseException)
                   else {'return_value': json.dumps(network or signed_result()).encode()})))
            inputs = s.enter_context(patch('builtins.input', side_effect=prompts or [self.destination, '7', '1', 'PREPARE']))
            password = s.enter_context(patch.object(w, 'hidden_password',
                **({'side_effect': secret} if secret else {'return_value': PASSWORD})))
            backend = s.enter_context(patch.object(w, 'invoke',
                **({'side_effect': answer} if callable(answer) or isinstance(answer, BaseException)
                   else {'return_value': self.result if answer is None else answer})))
            if expected:
                with self.assertRaises(expected):
                    w.prepare_network(self.a)
                value = None
            else:
                value = w.prepare_network(self.a)
            return value, process, inputs, password, backend, stdout.getvalue()

    def test_one_verifier_then_one_opcode12_without_scan_or_broadcast(self):
        value, proc, prompts, secret, backend, _ = self.invoke()
        self.assertEqual(proc.call_count, 1); self.assertEqual(backend.call_count, 1)
        self.assertEqual(secret.call_count, 1); self.assertEqual(prompts.call_count, 4)
        op, pw, pin, f = decode_frame(backend.call_args.args[1])
        self.assertEqual((op, pw, pin), (12, PASSWORD, PIN))
        self.assertEqual(f, [str(self.a.wallet), str(self.a.journal), str(self.genesis), self.gpin,
            self.destination, '7', '1', '23', str(self.a.output), '3', '33'*32])
        command = proc.call_args.args[0]
        self.assertEqual(command[1], 'sync'); self.assertNotIn('submit', command)
        for private in (str(self.a.wallet), str(self.a.output), PIN, self.destination, PASSWORD.decode()):
            self.assertNotIn(private, command)
        self.assertEqual(value['result'], 'network_verified_payment_prepared_not_broadcast')
        self.assertFalse(value['broadcast']); self.assertFalse(value['latest_verified'])
        self.assertFalse(value['retry_authorized']); self.assertFalse(value['real_funds_allowed'])
        self.assertNotIn('confirmed', value)
        self.assertEqual(value['network']['app_hash'], value['wallet']['app_hash'])

    def test_network_failure_stops_before_private_input(self):
        _, p, inputs, secret, backend, _ = self.invoke(network=RuntimeError('refused'), expected=RuntimeError)
        self.assertEqual(p.call_count, 1)
        inputs.assert_not_called(); secret.assert_not_called(); backend.assert_not_called()

    def test_partial_catchup_never_signs_or_loops(self):
        v = signed_result(); v.update(observed_signed_tip=5, caught_up_to_observed_tip=False)
        before = self.a.wallet.read_bytes()
        _, p, inputs, secret, backend, _ = self.invoke(network=v, expected=ValueError)
        self.assertEqual(p.call_count, 1); inputs.assert_not_called(); secret.assert_not_called()
        backend.assert_not_called(); self.assertEqual(before, self.a.wallet.read_bytes())

    def test_invalid_network_shapes_never_reach_secret(self):
        for key, value in [('app_hash', '0'*64), ('height', True), ('caught_up_to_observed_tip', 1),
                           ('real_funds_allowed', True), ('scope', 'finality')]:
            v = signed_result(); v[key] = value
            with self.subTest(key=key):
                _, _, inputs, secret, backend, _ = self.invoke(network=v, expected=ValueError)
                inputs.assert_not_called(); secret.assert_not_called(); backend.assert_not_called()

    def test_expiry_window_boundaries_and_default(self):
        for window in ('1', '20', '100'):
            self.a.expiry_blocks = window
            _, _, _, _, backend, _ = self.invoke()
            self.assertEqual(decode_frame(backend.call_args.args[1])[3][7], str(3+int(window)))
        for bad in ('0', '101', '01', '', '1e1', None, 20, '9'*100):
            self.a.expiry_blocks = bad
            with self.subTest(bad=bad):
                _, proc, inputs, secret, backend, _ = self.invoke(expected=ValueError)
                proc.assert_not_called(); inputs.assert_not_called(); secret.assert_not_called(); backend.assert_not_called()

    def test_expiry_may_not_cross_profile_height_limit(self):
        self.a.create_reference = False
        v = signed_result(); v.update(height=9990, new_blocks=0, observed_signed_tip=9991)
        _, _, inputs, secret, backend, _ = self.invoke(network=v, expected=ValueError)
        inputs.assert_not_called(); secret.assert_not_called(); backend.assert_not_called()

    def test_wrong_domain_fee_bounds_or_cancel_do_not_open_wallet(self):
        wrong = self.destination.replace(self.gpin, '77'*32)
        for prompts in ([wrong, '7', '1', 'PREPARE'], [self.destination, '1', '99999', 'PREPARE'],
                        [self.destination, '100', '2', 'PREPARE'], [self.destination, '0', '1', 'PREPARE'],
                        [self.destination, '7', '1', 'CANCEL']):
            with self.subTest(prompts=prompts[1:]):
                _, p, _, secret, backend, _ = self.invoke(prompts=prompts, expected=ValueError)
                self.assertEqual(p.call_count, 1); secret.assert_not_called(); backend.assert_not_called()

    def test_existing_output_is_not_overwritten_and_network_not_started(self):
        self.a.output.write_bytes(b'existing output')
        _, p, inputs, secret, backend, _ = self.invoke(expected=ValueError)
        p.assert_not_called(); inputs.assert_not_called(); secret.assert_not_called(); backend.assert_not_called()
        self.assertEqual(self.a.output.read_bytes(), b'existing output')

    def test_overlapping_reference_or_input_output_rejected_before_network(self):
        for output in (self.a.journal, self.a.journal/'inside', self.a.wallet, self.genesis,
                       self.prog, Path('relative'), self.root/'..'/'outside'):
            self.a.output = output
            with self.subTest(output=str(output)):
                _, p, _, secret, backend, _ = self.invoke(expected=(ValueError, OSError))
                p.assert_not_called(); secret.assert_not_called(); backend.assert_not_called()

    def test_new_output_during_confirmation_prevents_secret(self):
        def prompts(_):
            prompts.n += 1
            if prompts.n == 4:
                self.a.output.write_bytes(b'raced output')
            return [self.destination, '7', '1', 'PREPARE'][prompts.n-1]
        prompts.n = 0
        _, _, _, secret, backend, _ = self.invoke(prompts=prompts, expected=ValueError)
        secret.assert_not_called(); backend.assert_not_called()
        self.assertEqual(self.a.output.read_bytes(), b'raced output')

    def test_new_output_during_password_is_preserved_without_backend(self):
        def secret(_):
            self.a.output.write_bytes(b'raced later output'); return PASSWORD
        _, _, _, password, backend, _ = self.invoke(secret=secret, expected=ValueError)
        self.assertEqual(password.call_count, 1); backend.assert_not_called()
        self.assertEqual(self.a.output.read_bytes(), b'raced later output')

    def test_config_or_program_change_during_password_prevents_wallet(self):
        for path in (self.config, self.prog):
            before = path.read_bytes()
            def secret(_, path=path):
                path.write_bytes(path.read_bytes()+b' '); return PASSWORD
            with self.subTest(path=path.name):
                _, _, _, password, backend, _ = self.invoke(secret=secret, expected=(ValueError, RuntimeError))
                self.assertEqual(password.call_count, 1); backend.assert_not_called()
            path.write_bytes(before)

    def test_unknown_wallet_failure_does_not_retry_or_clean_saved_output(self):
        def unknown(*_):
            self.a.output.write_bytes(b'partial synthetic test output')
            raise RuntimeError('acknowledgement missing')
        before = self.a.wallet.read_bytes()
        _, p, _, _, backend, _ = self.invoke(answer=unknown, expected=RuntimeError)
        self.assertEqual(p.call_count, 1); self.assertEqual(backend.call_count, 1)
        self.assertEqual(self.a.output.read_bytes(), b'partial synthetic test output')
        self.assertEqual(self.a.wallet.read_bytes(), before)

    def test_response_identity_checkpoint_receipt_and_nonbroadcast_are_exact(self):
        for key, value in [('app_hash', '99'*32), ('height', 4), ('broadcast', True),
                           ('txid', 'gg'*32), ('receipt', PIN), ('receipt', 'aa'*32+'0000000000000002'+'bb'*32),
                           ('signing_domain', 'aa'*32), ('genesis_sha256', 'aa'*32), ('confirmed', True)]:
            v=copy.deepcopy(self.result); v[key]=value
            with self.subTest(key=key):
                _, p, _, _, backend, _ = self.invoke(answer=v, expected=(ValueError, RuntimeError))
                self.assertEqual(p.call_count, 1); self.assertEqual(backend.call_count, 1)

    def test_explicit_private_route_is_passed_without_fallback(self):
        self.a.endpoint='http://'+'a'*56+'.onion:80'; self.a.socks_proxy='127.0.0.1:9050'
        _, p, _, _, backend, _=self.invoke(network=RuntimeError('SOCKS refused'),expected=RuntimeError)
        self.assertEqual(p.call_count,1); backend.assert_not_called()
        self.assertIn(self.a.endpoint,p.call_args.args[0]); self.assertIn(self.a.socks_proxy,p.call_args.args[0])

    def args(self):
        a=self.a
        args=['--no-real-funds','--backend',str(a.backend),'--backend-sha256',a.backend_sha256,
              '--pin',a.pin,'prepare-network',str(a.wallet),str(a.output)]
        for name in ('journal','genesis','config','network_backend','worker','genesis_sha256',
                     'config_sha256','network_backend_sha256','worker_sha256','endpoint'):
            args += ['--'+name.replace('_','-'),str(getattr(a,name))]
        return args+['--create-reference']

    def test_real_cli_dispatch_uses_this_operation(self):
        with patch.object(w,'prepare_network',side_effect=RuntimeError('stop')) as operation, \
             contextlib.redirect_stderr(io.StringIO()),contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(w.main(self.args()),1); self.assertEqual(out.getvalue(),'')
        self.assertEqual(operation.call_count,1)
        self.assertEqual(operation.call_args.args[0].expiry_blocks,'20')

    def test_no_caller_checkpoint_or_private_intent_argument(self):
        for flags in (['--expected-height','3'],['--expected-app-hash','33'*32],
                      ['--recipient',self.destination],['--fee','1']):
            with contextlib.redirect_stderr(io.StringIO()),patch.object(w,'prepare_network') as run:
                with self.assertRaises(SystemExit): w.main(self.args()+flags)
                run.assert_not_called()

    def test_duplicate_or_abbreviated_flags_refused(self):
        for args in (self.args()+['--limit','1','--limit','128'],
                     self.args()+['--expiry-blocks','1','--expiry-blocks','20'],
                     ['--backend-sha='+self.a.backend_sha256]+self.args()):
            with contextlib.redirect_stderr(io.StringIO()),patch.object(w,'prepare_network') as run:
                self.assertEqual(w.main(args),1); run.assert_not_called()

    def test_old_opcodes_and_single_operations_still_present(self):
        self.assertEqual(list(w.OPS.values()), list(range(14)))
        self.assertNotIn('prepare-network',w.OPS); self.assertNotIn('sync-network',w.OPS)
        self.assertEqual(w.COUNTS[11],6); self.assertEqual(w.COUNTS[12],11)
        self.assertEqual(w.OPS['prepare'],4); self.assertEqual(w.OPS['pending'],5)


if __name__=='__main__': unittest.main()
