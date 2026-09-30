"""Frontend/schema isolation only, never a replacement verifier or native proof.

Successful crypto/store/CLI and network-to-recovery paths run in native suites.
"""
import contextlib
import copy
import io
import hashlib
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import zevune_wallet as w
import test_wallet_network_prepare as fixture


class PendingRecoveryTests(unittest.TestCase):
    def setUp(self):
        fixture.NetworkPreparationTests.setUp(self)
        self.a.command = 'recover-pending-network'
        del self.a.expiry_blocks
        self.result.update(result='checkpoint_pending_exported_not_broadcast',
                           wallet_unchanged=True, receipt=fixture.PIN)

    def args(self):
        a = fixture.NetworkPreparationTests.args(self)
        a[a.index('prepare-network')] = 'recover-pending-network'
        return a

    def direct_args(self):
        a = self.a
        return ['--no-real-funds', '--backend', str(a.backend), '--backend-sha256', a.backend_sha256,
                '--pin', a.pin, 'pending-at-checkpoint', str(a.wallet), str(a.output),
                '--journal', str(a.journal), '--genesis', str(a.genesis), '--genesis-sha256', self.gpin,
                '--expected-height', '3', '--expected-app-hash', '33' * 32]

    def run_recovery(self, *, network=None, response=None, approve='RECOVER', secret=None, error=None):
        with contextlib.ExitStack() as stack:
            stack.enter_context(contextlib.redirect_stderr(io.StringIO()))
            stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
            proc = stack.enter_context(patch.object(w, '_sync_network_process',
                **({'side_effect': network} if isinstance(network, BaseException)
                   else {'return_value': json.dumps(network or fixture.signed_result()).encode()})))
            prompt = stack.enter_context(patch('builtins.input', return_value=approve))
            password = stack.enter_context(patch.object(w, 'hidden_password',
                **({'side_effect': secret} if secret else {'return_value': fixture.PASSWORD})))
            child = stack.enter_context(patch.object(w, 'invoke',
                **({'side_effect': response} if isinstance(response, BaseException) or callable(response)
                   else {'return_value': self.result if response is None else response})))
            if error:
                with self.assertRaises(error): w.recover_pending_network(self.a)
                value = None
            else:
                value = w.recover_pending_network(self.a)
            return value, proc, prompt, password, child

    def test_exact_seven_field_frame_and_original_opcodes(self):
        fields = [str(self.a.wallet), str(self.a.journal), str(self.genesis), self.gpin,
                  str(self.a.output), '3', '33' * 32]
        encoded = w.encode_request(13, fixture.PASSWORD, fields, fixture.PIN)
        self.assertEqual(fixture.decode_frame(encoded), (13, fixture.PASSWORD, fixture.PIN, fields))
        self.assertEqual(w.COUNTS[13], 7)
        self.assertEqual(list(w.OPS.values()), list(range(14)))
        self.assertEqual((w.OPS['pending'], w.OPS['prepare-at-checkpoint']), (5, 12))
        for pin in (None, '', '0' * 144, 'AA' * 72):
            with self.assertRaises(ValueError): w.encode_request(13, fixture.PASSWORD, fields, pin)
        for index, value in ((5, '01'), (6, '0' * 64)):
            bad = fields.copy(); bad[index] = value
            with self.assertRaises(ValueError): w.encode_request(13, fixture.PASSWORD, bad, fixture.PIN)

    def test_readonly_receipt_can_equal_or_follow_independent_ancestor(self):
        for generation in (1, 2, 256):
            r = copy.deepcopy(self.result)
            r['receipt'] = fixture.PIN[:64] + f'{generation:016x}' + fixture.PIN[80:]
            self.assertEqual(w.checked_checkpoint_recovery(r, '3', '33' * 32, fixture.PIN), r)
        for pin in ('aa' * 32 + fixture.PIN[64:], fixture.PIN[:80] + '77' * 32,
                    fixture.PIN[:64] + '0000000000000000' + fixture.PIN[80:]):
            r = copy.deepcopy(self.result); r['receipt'] = pin
            with self.assertRaises((ValueError, RuntimeError)):
                w.checked_checkpoint_recovery(r, '3', '33' * 32, fixture.PIN)

    def test_response_exact_fields_types_and_no_confirmation(self):
        for key in self.result:
            r = copy.deepcopy(self.result); del r[key]
            with self.subTest(key=key), self.assertRaises((ValueError, RuntimeError)):
                w.checked_checkpoint_recovery(r, '3', '33' * 32, fixture.PIN)
        for key, value in [('wallet_unchanged', 1), ('broadcast', True), ('height', True),
                           ('app_hash', 'ff' * 32), ('confirmed', True), ('balance', 7),
                           ('result', 'confirmed'), ('txid', 'xx' * 32), ('signing_domain', 'aa' * 32)]:
            r = copy.deepcopy(self.result); r[key] = value
            with self.subTest(key=key), self.assertRaises((ValueError, RuntimeError)):
                w.checked_checkpoint_recovery(r, '3', '33' * 32, fixture.PIN)

    def test_one_real_dispatch_to_verifier_then_only_opcode13(self):
        value, proc, prompt, password, child = self.run_recovery()
        self.assertEqual((proc.call_count, prompt.call_count, password.call_count, child.call_count), (1, 1, 1, 1))
        op, pw, pin, fields = fixture.decode_frame(child.call_args.args[1])
        self.assertEqual((op, pw, pin), (13, fixture.PASSWORD, fixture.PIN))
        self.assertEqual(fields, [str(self.a.wallet), str(self.a.journal), str(self.genesis), self.gpin,
                                 str(self.a.output), '3', '33' * 32])
        command = proc.call_args.args[0]
        self.assertEqual(command[1], 'sync'); self.assertNotIn('submit', command)
        for private in (str(self.a.wallet), str(self.a.output), pin, pw.decode()):
            self.assertNotIn(private, command)
        self.assertEqual(value['result'], 'network_verified_pending_recovered_not_broadcast')
        for flag in ('broadcast', 'retry_authorized', 'latest_verified', 'real_funds_allowed'):
            self.assertIs(value[flag], False)
        self.assertIs(value['wallet']['wallet_unchanged'], True)

    def test_network_failure_and_partial_catchup_precede_secret(self):
        partial = fixture.signed_result()
        partial.update(observed_signed_tip=5, caught_up_to_observed_tip=False)
        before = self.a.wallet.read_bytes()
        for response in (partial, RuntimeError('refused')):
            _, proc, prompt, secret, child = self.run_recovery(network=response, error=(ValueError, RuntimeError))
            self.assertEqual(proc.call_count, 1)
            prompt.assert_not_called(); secret.assert_not_called(); child.assert_not_called()
            self.assertEqual(self.a.wallet.read_bytes(), before)

    def test_public_pin_and_output_refused_before_network(self):
        for field, value in [('pin', ''), ('genesis_sha256', '0' * 64), ('backend_sha256', ''),
                             ('output', self.a.wallet), ('output', self.a.journal / 'inside'),
                             ('output', Path('relative'))]:
            old = getattr(self.a, field); setattr(self.a, field, value)
            try:
                _, proc, prompt, secret, child = self.run_recovery(error=(ValueError, OSError))
                proc.assert_not_called(); prompt.assert_not_called(); secret.assert_not_called(); child.assert_not_called()
            finally: setattr(self.a, field, old)

    def test_explicit_cancel_never_opens_wallet(self):
        _, proc, _, secret, child = self.run_recovery(approve='NO', error=ValueError)
        self.assertEqual(proc.call_count, 1); secret.assert_not_called(); child.assert_not_called()

    def test_late_output_race_and_program_change_stop_wallet(self):
        def output_race(_):
            self.a.output.write_bytes(b'preserve raced output'); return fixture.PASSWORD
        _, _, _, _, child = self.run_recovery(secret=output_race, error=ValueError)
        child.assert_not_called(); self.assertEqual(self.a.output.read_bytes(), b'preserve raced output')
        self.a.output.unlink()  # explicit temporary test fixture only
        def program_change(_):
            self.prog.write_bytes(b'changed'); return fixture.PASSWORD
        _, _, _, _, child = self.run_recovery(secret=program_change, error=(ValueError, RuntimeError))
        child.assert_not_called()

    def test_unknown_export_failure_does_not_retry_or_remove_output(self):
        before = self.a.wallet.read_bytes()
        def fail(*_):
            self.a.output.write_bytes(b'partial synthetic public bytes')
            raise RuntimeError('lost acknowledgement')
        _, proc, _, _, child = self.run_recovery(response=fail, error=RuntimeError)
        self.assertEqual((proc.call_count, child.call_count), (1, 1))
        self.assertEqual(self.a.wallet.read_bytes(), before)
        self.assertEqual(self.a.output.read_bytes(), b'partial synthetic public bytes')

    def test_invalid_reply_is_not_retry_authority(self):
        r = copy.deepcopy(self.result); r['wallet_unchanged'] = False
        _, proc, _, _, child = self.run_recovery(response=r, error=RuntimeError)
        self.assertEqual((proc.call_count, child.call_count), (1, 1))

    def test_private_route_refusal_has_no_direct_fallback(self):
        self.a.endpoint = 'http://' + 'a' * 56 + '.onion:80'
        self.a.socks_proxy = '127.0.0.1:9050'
        _, proc, _, secret, child = self.run_recovery(network=RuntimeError('SOCKS'), error=RuntimeError)
        self.assertEqual(proc.call_count, 1)
        self.assertIn(self.a.endpoint, proc.call_args.args[0]); self.assertIn(self.a.socks_proxy, proc.call_args.args[0])
        secret.assert_not_called(); child.assert_not_called()

    def test_actual_network_cli_routes_recovery_and_rejects_checkpoint_injection(self):
        with patch.object(w, 'recover_pending_network', side_effect=RuntimeError('stop')) as operation, \
                contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(w.main(self.args()), 1)
            self.assertEqual(operation.call_count, 1)
        for flags in (['--expected-height', '3'], ['--expected-app-hash', '33'*32], ['--expiry-blocks', '1']):
            with patch.object(w, 'recover_pending_network') as operation, contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit): w.main(self.args() + flags)
                operation.assert_not_called()
        with patch.object(w, 'recover_pending_network') as operation, contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(w.main(self.args() + ['--limit', '1', '--limit', '2']), 1)
            operation.assert_not_called()

    def test_actual_direct_cli_seven_fields_and_one_recovery(self):
        with patch('builtins.input', return_value='RECOVER') as prompt, \
                patch.object(w, 'hidden_password', return_value=fixture.PASSWORD), \
                patch.object(w, 'invoke', return_value=self.result) as child, \
                contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(w.main(self.direct_args()), 0)
            self.assertEqual(prompt.call_count, 1)
        self.assertEqual(fixture.decode_frame(child.call_args.args[1])[0], 13)
        self.assertEqual(fixture.decode_frame(child.call_args.args[1])[3][-3:], [str(self.a.output), '3', '33'*32])
        self.assertIs(json.loads(output.getvalue())['wallet_unchanged'], True)

    def test_direct_existing_target_or_bad_pin_precedes_private_input(self):
        for flag, value in (('--pin', ''), ('--expected-app-hash', '0'*64)):
            args = self.direct_args(); args[args.index(flag)+1] = value
            with patch('builtins.input') as prompt, patch.object(w, 'hidden_password') as secret, \
                    contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(w.main(args), 1)
                prompt.assert_not_called(); secret.assert_not_called()
        self.a.output.write_bytes(b'existing')
        with patch('builtins.input') as prompt, patch.object(w, 'hidden_password') as secret, \
                contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(w.main(self.direct_args()), 1)
            prompt.assert_not_called(); secret.assert_not_called()
        self.assertEqual(self.a.output.read_bytes(), b'existing')


    def test_actual_refusing_network_process_is_joined_before_secret(self):
        # A real Python executable refuses the Go-style command; it never emits
        # an accepting network response and has no access to wallet secrets.
        executable = Path(sys.executable).resolve(strict=True)
        self.a.network_backend = executable
        self.a.network_backend_sha256 = hashlib.sha256(executable.read_bytes()).hexdigest()
        before = self.a.wallet.read_bytes()
        children = []
        popen = w.subprocess.Popen
        def spawn(*args, **kwargs):
            child = popen(*args, **kwargs)
            children.append(child)
            return child
        with patch.object(w.subprocess, 'Popen', side_effect=spawn), \
                patch('builtins.input') as prompt, patch.object(w, 'hidden_password') as secret, \
                patch.object(w, 'invoke') as wallet_call, \
                contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(RuntimeError):
                w.recover_pending_network(self.a)
        self.assertEqual(len(children), 1)
        self.assertIsNotNone(children[0].poll())
        prompt.assert_not_called(); secret.assert_not_called(); wallet_call.assert_not_called()
        self.assertEqual(self.a.wallet.read_bytes(), before)
        self.assertFalse(self.a.output.exists())

    def test_actual_refusing_wallet_process_cannot_fallback_or_clear_pending(self):
        # The network result here is UI isolation, not a certificate. The REAL
        # child rejects --no-real-funds and cannot sign or write a wallet.
        executable = Path(sys.executable).resolve(strict=True)
        self.a.backend = executable
        self.a.backend_sha256 = hashlib.sha256(executable.read_bytes()).hexdigest()
        before = self.a.wallet.read_bytes()
        children = []
        popen = w.subprocess.Popen
        def spawn(*args, **kwargs):
            child = popen(*args, **kwargs)
            children.append(child)
            return child
        with patch.object(w, '_sync_network_process', return_value=json.dumps(fixture.signed_result()).encode()), \
                patch.object(w.subprocess, 'Popen', side_effect=spawn), \
                patch('builtins.input', return_value='RECOVER'), \
                patch.object(w, 'hidden_password', return_value=fixture.PASSWORD), \
                contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(RuntimeError):
                w.recover_pending_network(self.a)
        self.assertEqual(len(children), 1)
        self.assertIsNotNone(children[0].poll())
        self.assertEqual(self.a.wallet.read_bytes(), before)
        self.assertFalse(self.a.output.exists())

    def test_direct_input_tree_overlap_refuses_before_prompt(self):
        for target in [self.a.wallet, self.a.journal / 'not-allowed.tx', self.a.genesis]:
            original = self.a.output
            self.a.output = target
            try:
                with patch('builtins.input') as prompt, patch.object(w, 'hidden_password') as secret, \
                        patch.object(w, 'invoke') as child, contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(w.main(self.direct_args()), 1)
                prompt.assert_not_called(); secret.assert_not_called(); child.assert_not_called()
            finally:
                self.a.output = original


if __name__ == '__main__': unittest.main()
