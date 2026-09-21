"""Public intent/parser/refusal tests; synthetic frames cannot authorize payment.

Real signing, persistence and exact pending recovery run against the real Rust
backend in check_payment_request_backend.py, never an accepting backend double.
"""
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import payment_request as request
import wallet_backup as storage
import wallet_backup_backend as transport
from test_wallet_backup import frames


def genesis_bytes(marker=b'q', magic=b'ZVTGEN02'):
    return (magic + hashlib.sha256(b'zevune-orchard-lab-1').digest()
            + (100000).to_bytes(8, 'big') + b'\0\1' + marker * 32
            + b'r' * 43 + (100000).to_bytes(8, 'big') + b's' * 64)


def address(domain):
    receiver = '73' * 43
    checksum = hashlib.sha256(b'ZEVUNE-LOCAL-ADDRESS\0\x02' + bytes.fromhex(domain + receiver)).hexdigest()[:16]
    return f'zvlab2:{domain}:{receiver}:{checksum}'


def intent(domain):
    return dict(format=request.FORMAT, genesis_sha256=domain, recipient=address(domain),
                amount=1234, expiry_height=10, nonce='b' * 32, real_funds_allowed=False)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


class RequestFormatTests(unittest.TestCase):
    def setUp(self):
        self.domain = sha(genesis_bytes())
        self.data = intent(self.domain)
        self.raw = storage.canonical(self.data)

    def check(self, raw):
        return request.decode(raw, self.domain, sha(raw))

    def test_canonical_roundtrip_and_strict_fields(self):
        self.assertEqual(self.check(self.raw), self.data)
        for field in self.data:
            data = dict(self.data); del data[field]
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.check(storage.canonical(data))
        for key in ('fee', 'backend', 'wallet', 'output', 'password', 'path', 'broadcast'):
            with self.subTest(field=key), self.assertRaises(ValueError):
                self.check(storage.canonical({**self.data, key: 'SENTINEL'}))

    def test_digest_and_network_must_come_from_outside_request(self):
        for invalid in (None, True, '', 'A' * 64, '0' * 64, sha(self.raw) + '\n'):
            with self.subTest(value=invalid), self.assertRaises(ValueError):
                request.decode(self.raw, self.domain, invalid)
        other = sha(genesis_bytes(b'z'))
        with self.assertRaises(ValueError):
            request.decode(self.raw, other, sha(self.raw))
        for invalid in ('0' * 64, None, True):
            with self.assertRaises(ValueError):
                request.decode(self.raw, invalid, sha(self.raw))

    def test_boundaries_types_and_address_domain(self):
        for amount in (1, (1 << 63) - 2):
            for expiry in (1, (1 << 64) - 1):
                self.check(storage.canonical({**self.data, 'amount': amount, 'expiry_height': expiry}))
        for key, values in (('amount', [0, -1, True, 1.0, '1', (1 << 63) - 1]),
                            ('expiry_height', [0, -1, True, 1.5, '1', 1 << 64]),
                            ('nonce', ['', 'b' * 31, 'B' * 32, 'b' * 32 + '\n', 1]),
                            ('recipient', ['', None, True, address('a' * 64), address(self.domain)[:-1] + 'x']),
                            ('real_funds_allowed', [True, 0, None, 'false'])):
            for value in values:
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    self.check(storage.canonical({**self.data, key: value}))

    def test_malformed_noncanonical_duplicate_and_oversize_refused(self):
        for raw in (b'', b'[]', b'null', b'NaN', b'\xff', b' ' + self.raw, self.raw + b'\n',
                    self.raw[:-1], self.raw + self.raw, b'x' * (request.MAX_REQUEST + 1),
                    json.dumps(self.data, indent=2).encode(),
                    self.raw.replace(b'"amount":', b'"amount":1,"amount":'),
                    b'[' * 1100 + b']' * 1100):
            with self.subTest(size=len(raw)), self.assertRaises(ValueError):
                self.check(raw)
        with self.assertRaises(ValueError):
            request.decode(bytearray(self.raw), self.domain, sha(self.raw))


class RequestFilesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='request-tests-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.genesis = self.root / 'genesis'
        self.genesis.write_bytes(genesis_bytes())
        self.domain = sha(self.genesis.read_bytes())
        self.source = self.root / 'intent.zvrequest'
        self.raw = storage.canonical(intent(self.domain)); self.source.write_bytes(self.raw)
        self.pin = sha(self.raw)

    def inspect(self, path=None):
        return request.inspect_request(path or self.source, self.pin, self.genesis, self.domain)

    def test_inspect_is_read_only_and_not_sender_or_payment_authentication(self):
        before = {p.name: p.read_bytes() for p in self.root.iterdir()}
        with patch.object(request, 'RequestBackend', side_effect=AssertionError('no backend')), \
                patch.object(request, 'hidden_password', side_effect=AssertionError('no password')):
            result = self.inspect()
        self.assertIs(result['authenticated'], False)
        self.assertIs(result['single_use_enforced'], False)
        self.assertIs(result['expiry_checked_against_ledger'], False)
        self.assertEqual({p.name: p.read_bytes() for p in self.root.iterdir()}, before)

    def test_create_is_private_exclusive_nonce_unique_and_reparseable(self):
        first, second = self.root / 'one', self.root / 'two'
        one = request.create_request(first, self.genesis, self.domain, address(self.domain), '1234', '10')
        two = request.create_request(second, self.genesis, self.domain, address(self.domain), '1234', '10')
        self.assertNotEqual(one['request_sha256'], two['request_sha256'])
        self.assertFalse(one['authenticated'])
        request.inspect_request(first, one['request_sha256'], self.genesis, self.domain)
        if os.name == 'posix': self.assertEqual(first.stat().st_mode & 0o777, 0o600)
        before = first.read_bytes()
        with self.assertRaises(ValueError):
            request.create_request(first, self.genesis, self.domain, address(self.domain), '1', '10')
        self.assertEqual(first.read_bytes(), before)

    def test_invalid_creation_never_creates_output(self):
        output = self.root / 'out'
        for recipient, amount, expiry in ((address('1' * 64), '1', '10'), (address(self.domain), '01', '10'),
                                          (address(self.domain), '0', '10'), (address(self.domain), '1', '0')):
            with self.assertRaises(ValueError):
                request.create_request(output, self.genesis, self.domain, recipient, amount, expiry)
            self.assertFalse(output.exists())

    def test_invalid_genesis_and_legacy_refused_before_writes(self):
        for raw in (genesis_bytes(magic=b'ZVTGEN04'), genesis_bytes() + b'tail',
                    genesis_bytes(magic=b'ZVTGEN01'), genesis_bytes(marker=b'\0')):
            self.genesis.write_bytes(raw)
            with self.assertRaises(ValueError):
                request.network(self.genesis, sha(raw))
        self.genesis.write_bytes(genesis_bytes())
        with self.assertRaises(ValueError): request.network(self.genesis, '0' * 64)

    def test_input_links_identity_changes_and_directory_refused(self):
        link = self.root / 'hardlink'; os.link(self.source, link)
        with self.assertRaises(ValueError): self.inspect()
        link.unlink()
        if os.name == 'posix':
            link.symlink_to(self.source)
            with self.assertRaises(ValueError): self.inspect(link)
            link.unlink()
        with self.assertRaises(ValueError): self.inspect(self.root)
        snapshot = storage.read_file(self.source, request.MAX_REQUEST)
        replacement = self.root / 'replacement'; replacement.write_bytes(self.raw)
        os.replace(replacement, self.source)
        with self.assertRaises(ValueError): request.unchanged(self.source, snapshot, request.MAX_REQUEST)

    def test_failure_after_output_write_retains_partial_file(self):
        target = self.root / 'partial'
        def fail(path, raw):
            path.write_bytes(raw[:20]); raise OSError('test write error')
        with patch.object(storage, 'write_new', side_effect=fail), self.assertRaises(OSError):
            request.create_request(target, self.genesis, self.domain, address(self.domain), '1', '10')
        self.assertEqual(target.stat().st_size, 20)

    def backend(self):
        binary = self.root / 'inert'; binary.write_bytes(b'not an executable; refusal only')
        return request.RequestBackend(binary, sha(binary.read_bytes()))

    def test_bad_request_rejected_before_backend_and_wallet_mutation(self):
        wallet = self.root / 'wallet'; raw, pin = frames(2); wallet.write_bytes(raw)
        backend = self.backend()
        with patch('subprocess.Popen', side_effect=AssertionError('no execution')), self.assertRaises(ValueError):
            request.prepare_request(self.source, '0' * 64, self.genesis, self.domain, wallet, pin,
                                    self.root / 'pool', self.root / 'out', '1', b'no-real-password', backend)
        self.assertEqual(wallet.read_bytes(), raw); self.assertFalse((self.root / 'out').exists())

    def test_existing_output_and_stale_tip_refuse_before_launch(self):
        wallet = self.root / 'wallet'; raw, pin = frames(3); wallet.write_bytes(raw)
        output = self.root / 'out'; output.write_bytes(b'existing')
        backend = self.backend()
        for requested_pin in (pin, frames(2)[1]):
            with patch('subprocess.Popen', side_effect=AssertionError('no execution')), self.assertRaises(ValueError):
                request.prepare_request(self.source, self.pin, self.genesis, self.domain, wallet, requested_pin,
                                        self.root / 'pool', output, '1', b'no-real-password', backend)
        output.unlink()
        with patch('subprocess.Popen', side_effect=AssertionError('no execution')), self.assertRaises(ValueError):
            request.prepare_request(self.source, self.pin, self.genesis, self.domain, wallet, frames(2)[1],
                                    self.root / 'pool', output, '1', b'no-real-password', backend)
        self.assertEqual(wallet.read_bytes(), raw)

    def test_declined_signing_does_not_request_password_or_execute(self):
        wallet = self.root / 'wallet'; raw, pin = frames(2); wallet.write_bytes(raw)
        backend = self.backend()
        args = ['--no-real-funds', 'prepare', str(self.source), str(self.root / 'out'),
                '--request-sha256', self.pin, '--genesis', str(self.genesis), '--genesis-sha256', self.domain,
                '--wallet', str(wallet), '--wallet-pin', pin, '--journal', str(self.root / 'pool'),
                '--backend', str(backend.path), '--backend-sha256', backend.digest]
        with patch('builtins.input', side_effect=['1', 'NO']), \
                patch.object(request, 'hidden_password', side_effect=AssertionError('no password')), \
                patch('subprocess.Popen', side_effect=AssertionError('no backend')), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(request.main(args), 1)
        self.assertEqual(wallet.read_bytes(), raw)

    def test_export_inside_active_ledger_refused_before_backend(self):
        wallet = self.root / 'wallet'
        raw, pin = frames(2)
        wallet.write_bytes(raw)
        ledger = self.root / 'active'
        ledger.mkdir()
        backend = self.backend()
        with patch('subprocess.Popen', side_effect=AssertionError('no process')), self.assertRaises(ValueError):
            request.prepare_request(self.source, self.pin, self.genesis, self.domain, wallet, pin,
                                    ledger, ledger / 'payment.tx', '1', b'unused-password-fixture', backend)
        self.assertEqual(list(ledger.iterdir()), [])
        self.assertEqual(wallet.read_bytes(), raw)

    def test_old_catalog_allowlist_does_not_grow(self):
        backend = self.backend()
        for op in (0, 1, 3, 4, 5, 7, 8, 10, 255):
            with patch('subprocess.Popen', side_effect=AssertionError('no process')), self.assertRaises(RuntimeError):
                backend.call(op, b'x' * 16, [], 'a' * 144)

    def test_real_cli_inspect_and_create_without_bytecode_or_secret_arguments(self):
        bundle = self.root / 'bundle'; bundle.mkdir()
        for name in ('payment_request.py', 'wallet_backup.py', 'wallet_backup_backend.py', 'zevune_wallet.py'):
            shutil.copyfile(Path(request.__file__).parent / name, bundle / name)
        before = {p.name: p.read_bytes() for p in bundle.iterdir()}
        env = os.environ.copy()
        for key in ('PYTHONDONTWRITEBYTECODE', 'PYTHONPYCACHEPREFIX'): env.pop(key, None)
        base = [sys.executable, str(bundle / 'payment_request.py'), '--no-real-funds']
        network = ['--genesis', str(self.genesis), '--genesis-sha256', self.domain]
        result = subprocess.run(base + ['inspect', str(self.source), '--request-sha256', self.pin] + network,
                                capture_output=True, env=env, timeout=20)
        self.assertEqual(result.returncode, 0); self.assertEqual(result.stderr, b'')
        self.assertIs(json.loads(result.stdout)['authenticated'], False)
        created = self.root / 'created'
        result = subprocess.run(base + ['create', str(created)] + network,
                                input=f'{address(self.domain)}\n1234\n10\nCREATE\n'.encode(),
                                capture_output=True, env=env, timeout=20)
        self.assertEqual(result.returncode, 0)
        self.assertEqual({str(p.relative_to(bundle)): p.read_bytes() if p.is_file() else None
                          for p in bundle.rglob('*')}, before)
        help_result = subprocess.run(base + ['prepare', '--help'], capture_output=True, timeout=20)
        for name in (b'--password', b'--fee', b'--amount', b'--recipient'):
            self.assertNotIn(name, help_result.stdout)


if __name__ == '__main__':
    unittest.main()
