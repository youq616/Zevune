"""Frontend/protocol regressions only; Rust native tests prove authorization."""
import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import zevune_wallet as wallet

PIN = '11' * 32 + f'{1:016x}' + '22' * 32
APP = '33' * 32
PASSWORD = b'synthetic-prepare-test-password'


def synthetic_genesis(root):
    raw = (b'ZVTGEN02' + hashlib.sha256(b'zevune-orchard-lab-1').digest()
           + (100000).to_bytes(8, 'big') + b'\x00\x01' + b'\x01' * 32
           + b'\x02' * 43 + (100000).to_bytes(8, 'big') + b'\x03' * 64)
    p = root / 'genesis'
    p.write_bytes(raw)
    digest = hashlib.sha256(raw).hexdigest()
    body = '02' * 43
    check = hashlib.sha256(b'ZEVUNE-LOCAL-ADDRESS\0\x02' + bytes.fromhex(digest + body)).hexdigest()[:16]
    return p, digest, f'zvlab2:{digest}:{body}:{check}'


def response(genesis='44' * 32):
    return {'ok': True, 'scope': 'local_journal_only_no_funds',
            'result': 'checkpoint_payment_saved_not_broadcast', 'checkpoint_matched': True,
            'payment_profile': 'LAB2', 'signing_domain': genesis, 'genesis_sha256': genesis,
            'height': 0, 'app_hash': APP, 'txid': '55' * 32,
            'receipt': PIN[:64] + f'{2:016x}' + '66' * 32, 'broadcast': False}


class CheckedPreparation(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.genesis, self.domain, self.address = synthetic_genesis(self.root)
        # Regular non-executable fixture: invoke is never actually executed by
        # frontend success tests. It is not a mock signer or accepting verifier.
        self.backend = self.root / 'backend'
        self.backend.write_bytes(b'frontend-only-nonexecuting-fixture')
        self.digest = hashlib.sha256(self.backend.read_bytes()).hexdigest()
        self.fields = [str(self.root / 'wallet'), str(self.root / 'pool'), str(self.genesis),
                       self.domain, self.address, '1000', '1', '10', str(self.root / 'tx'), '0', APP]
        self.argv = ['--no-real-funds', '--backend', str(self.backend), '--backend-sha256', self.digest,
                     '--pin', PIN, 'prepare-at-checkpoint', self.fields[0], self.fields[8],
                     '--journal', self.fields[1], '--genesis', self.fields[2], '--genesis-sha256', self.domain,
                     '--expected-height', '0', '--expected-app-hash', APP]

    def run_main(self, args=None):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return wallet.main(self.argv if args is None else args)

    def test_exact_frame_and_old_op_numbers(self):
        self.assertEqual(wallet.OPS['prepare-at-checkpoint'], 12)
        raw = wallet.encode_request(12, PASSWORD, self.fields, PIN)
        prefix = b'ZVWCLI01\x0c' + struct.pack('>H', len(PASSWORD)) + PASSWORD + b'\x01' + bytes.fromhex(PIN) + b'\x0b'
        want = prefix + b''.join(struct.pack('>H', len(f.encode())) + f.encode() for f in self.fields)
        self.assertEqual(raw, want)
        self.assertEqual(wallet.OPS['prepare'], 4)
        self.assertEqual(wallet.OPS['pending'], 5)
        self.assertEqual(wallet.OPS['status-at-checkpoint'], 11)
        old = wallet.encode_request(4, PASSWORD, self.fields[:9], None)
        self.assertEqual(old[8], 4)

    def test_frame_rejects_missing_pin_bad_checkpoint_and_fee(self):
        for pin in [None, '', '0' * 144, PIN[:64] + '0' * 16 + PIN[80:], '0' * 64 + PIN[64:]]:
            with self.subTest(pin=pin), self.assertRaises(ValueError):
                wallet.encode_request(12, PASSWORD, self.fields, pin)
        for index, value in [(9, '01'), (10, '0' * 64), (6, '11'), (7, '0')]:
            fields = self.fields.copy()
            fields[index] = value
            with self.subTest(index=index), self.assertRaises(ValueError):
                wallet.encode_request(12, PASSWORD, fields, PIN)
        for fields in [self.fields[:-1], self.fields + ['extra']]:
            with self.assertRaises(ValueError):
                wallet.encode_request(12, PASSWORD, fields, PIN)

    def test_fee_boundaries_and_legacy_compatibility(self):
        for amount in [1, 99, 100, 199, 200, 9999, 10000, 10100]:
            cap = min(100, max(1, amount // 100))
            self.assertEqual(wallet.checked_preparation_numbers(str(amount), str(cap), '10'),
                             (str(amount), str(cap), '10'))
            with self.assertRaises(ValueError):
                wallet.checked_preparation_numbers(str(amount), str(cap + 1), '10')
        # Old API intentionally does not inherit the new guard.
        self.assertEqual(wallet.checked_payment_numbers('1', '99999', '10'), ('1', '99999', '10'))

    def test_response_is_local_saved_not_confirmed(self):
        self.assertIsNotNone(wallet.checked_checkpoint_preparation(response(), '0', APP, PIN))
        for key, value in [('ok', 1), ('checkpoint_matched', 1), ('broadcast', 0),
                           ('height', False), ('height', 1), ('app_hash', '00' * 32),
                           ('receipt', PIN), ('signing_domain', 'ff' * 32), ('txid', 'GG' * 32)]:
            bad = response()
            bad[key] = value
            with self.subTest(key=key, value=value), self.assertRaises((ValueError, RuntimeError)):
                wallet.checked_checkpoint_preparation(bad, '0', APP, PIN)
        for key in ['confirmed', 'balance', 'local_timing']:
            bad = response()
            bad[key] = True
            with self.assertRaises(RuntimeError):
                wallet.checked_checkpoint_preparation(bad, '0', APP, PIN)
        for key in response():
            bad = response()
            bad.pop(key)
            with self.assertRaises(RuntimeError):
                wallet.checked_checkpoint_preparation(bad, '0', APP, PIN)

    def test_ancestor_pin_does_not_require_last_generation(self):
        r = response()
        r['receipt'] = PIN[:64] + f'{7:016x}' + '66' * 32
        wallet.checked_checkpoint_preparation(r, '0', APP, PIN)

    def test_bad_public_inputs_precede_password_and_backend(self):
        for option, value in [('--pin', ''), ('--expected-height', '01'), ('--expected-app-hash', '0' * 64),
                              ('--backend-sha256', 'ff' * 32), ('--genesis-sha256', 'ff' * 32)]:
            args = self.argv.copy()
            args[args.index(option) + 1] = value
            with self.subTest(option=option), mock.patch.object(wallet, 'hidden_password') as password, mock.patch.object(wallet, 'invoke') as invoke:
                self.assertEqual(self.run_main(args), 1)
                password.assert_not_called()
                invoke.assert_not_called()

    def test_existing_output_is_rejected_before_private_inputs(self):
        Path(self.fields[8]).write_bytes(b'retain')
        with mock.patch('builtins.input') as prompt, mock.patch.object(wallet, 'hidden_password') as password, mock.patch.object(wallet, 'invoke') as invoke:
            self.assertEqual(self.run_main(), 1)
            prompt.assert_not_called()
            password.assert_not_called()
            invoke.assert_not_called()
        self.assertEqual(Path(self.fields[8]).read_bytes(), b'retain')

    def test_high_fee_or_missing_confirmation_never_enters_password(self):
        for answers in [[self.address, '1', '99999', '10'], [self.address, '1000', '1', '10', 'NO']]:
            with mock.patch('builtins.input', side_effect=answers), mock.patch.object(wallet, 'hidden_password') as password, mock.patch.object(wallet, 'invoke') as invoke:
                self.assertEqual(self.run_main(), 1)
                password.assert_not_called()
                invoke.assert_not_called()

    def test_main_dispatch_has_exact_new_frame_and_no_fallback(self):
        for result in [response(self.domain), RuntimeError('reconcile')]:
            with mock.patch('builtins.input', side_effect=[self.address, '1000', '1', '10', 'PREPARE']), mock.patch.object(wallet, 'hidden_password', return_value=PASSWORD), mock.patch.object(wallet, 'invoke') as invoke:
                if isinstance(result, Exception):
                    invoke.side_effect = result
                else:
                    invoke.return_value = result
                self.assertEqual(self.run_main(), int(isinstance(result, Exception)))
                invoke.assert_called_once()
                self.assertEqual(invoke.call_args.args[1], wallet.encode_request(12, PASSWORD, self.fields, PIN))

    def test_response_failure_does_not_retry_or_print_success(self):
        r = response(self.domain)
        r['broadcast'] = True
        with mock.patch('builtins.input', side_effect=[self.address, '1000', '1', '10', 'PREPARE']), mock.patch.object(wallet, 'hidden_password', return_value=PASSWORD), mock.patch.object(wallet, 'invoke', return_value=r) as invoke:
            self.assertEqual(self.run_main(), 1)
            invoke.assert_called_once()


if __name__ == '__main__':
    unittest.main()
