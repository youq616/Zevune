"""Headless form/refusal tests; public synthetic inputs are NOT authentication."""
import dataclasses
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import request_desktop as desktop
from test_payment_request import genesis_bytes, address


class DesktopInputTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.genesis = self.root / 'genesis'
        self.genesis.write_bytes(genesis_bytes())
        self.domain = hashlib.sha256(self.genesis.read_bytes()).hexdigest()
        self.fields = dict(genesis=str(self.genesis), genesis_pin=self.domain, target=str(self.root/'new.zvrequest'),
                           recipient=address(self.domain), amount='1234', expiry='10', source='', request_pin='')

    def test_review_never_writes_and_intent_is_immutable(self):
        before = self.genesis.read_bytes()
        intent = desktop.prepare_intent(self.fields)
        self.assertFalse(intent.target.exists())
        self.assertEqual(self.genesis.read_bytes(), before)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            intent.amount = '999'
        self.assertIn('不是签名', intent.review())
        self.assertIn(self.domain, intent.review())

    def test_existing_core_roundtrip_and_no_backend_or_password(self):
        with patch.object(desktop.request, 'RequestBackend', side_effect=AssertionError('no backend')), \
                patch.object(desktop.request, 'hidden_password', side_effect=AssertionError('no password')):
            intent = desktop.prepare_intent(self.fields)
            result = desktop.save_intent(intent)
            self.assertFalse(result['authenticated'])
            values = {**self.fields, 'source': str(intent.target), 'request_pin': result['request_sha256']}
            inspected = desktop.inspect_values(values)
            self.assertEqual(inspected['request']['amount'], 1234)
            for field in ('authenticated', 'expiry_checked_against_ledger', 'single_use_enforced', 'real_funds_allowed'):
                self.assertIs(inspected[field], False)
        with self.assertRaises(ValueError):
            desktop.save_intent(intent)

    def test_each_input_bounded_no_control_text_and_no_relative_paths(self):
        for field in ('genesis', 'genesis_pin', 'target', 'recipient', 'amount', 'expiry'):
            for value in ('', 'a'*(desktop.LIMITS[field]+1), 'bad\ntext', 'bad\u202etext', None):
                with self.subTest(field=field), self.assertRaises((ValueError, TypeError)):
                    desktop.prepare_intent({**self.fields, field: value})
        for field in ('genesis', 'target'):
            with self.assertRaises(ValueError):
                desktop.prepare_intent({**self.fields, field: 'relative'})
        self.assertEqual(set(p.name for p in self.root.iterdir()), {'genesis'})

    def test_wrong_network_and_noncanonical_numbers_rejected_without_output(self):
        for field, value in (('genesis_pin', '0'*64), ('recipient', address('1'*64)),
                             ('amount', '01'), ('amount', '0'), ('expiry', '0'), ('expiry', str(1<<64))):
            with self.subTest(field=field), self.assertRaises(ValueError):
                desktop.prepare_intent({**self.fields, field: value})
        self.assertFalse(Path(self.fields['target']).exists())

    def test_genesis_changed_between_review_and_save_refused(self):
        intent = desktop.prepare_intent(self.fields)
        self.genesis.write_bytes(genesis_bytes(b'z'))
        with self.assertRaises(ValueError):
            desktop.save_intent(intent)
        self.assertFalse(intent.target.exists())

    def test_output_claimed_after_review_not_overwritten(self):
        intent = desktop.prepare_intent(self.fields)
        intent.target.write_bytes(b'retained')
        with self.assertRaises(ValueError):
            desktop.save_intent(intent)
        self.assertEqual(intent.target.read_bytes(), b'retained')

    def test_failed_save_retains_partial_output(self):
        intent = desktop.prepare_intent(self.fields)
        def interrupted(path, data):
            path.write_bytes(data[:17])
            raise OSError('test partial write')
        with patch.object(desktop.request.storage, 'write_new', side_effect=interrupted), self.assertRaises(OSError):
            desktop.save_intent(intent)
        self.assertEqual(intent.target.stat().st_size, 17)

    def test_inspection_requires_external_pin_and_refuses_unknown_fields(self):
        intent = desktop.prepare_intent(self.fields)
        digest = desktop.save_intent(intent)['request_sha256']
        values = {**self.fields, 'source': str(intent.target), 'request_pin': digest}
        original = intent.target.read_bytes()
        with self.assertRaises(ValueError):
            desktop.inspect_values({**values, 'request_pin': '0'*64})
        intent.target.write_bytes(original+b' ')
        with self.assertRaises(ValueError):
            desktop.inspect_values(values)
        self.assertEqual(intent.target.read_bytes(), original+b' ')

    def test_plain_cli_help_does_not_load_tk_or_write_cache_and_redacts_arguments(self):
        bundle = self.root/'bundle'; bundle.mkdir()
        for name in ('request_desktop.py', 'payment_request.py', 'wallet_backup.py', 'wallet_backup_backend.py', 'zevune_wallet.py'):
            shutil.copyfile(Path(desktop.__file__).parent/name, bundle/name)
        before = {p.name:p.read_bytes() for p in bundle.iterdir()}
        env = {k:v for k,v in os.environ.items() if k not in ('PYTHONDONTWRITEBYTECODE', 'PYTHONPYCACHEPREFIX', 'DISPLAY')}
        for args, code in ((['--help'], 0), (['--password', 'PRIVATE_SENTINEL'], 64)):
            result = subprocess.run([sys.executable, str(bundle/'request_desktop.py'), *args],
                                    capture_output=True, timeout=10, env=env)
            self.assertEqual(result.returncode, code)
            self.assertNotIn(b'PRIVATE_SENTINEL', result.stdout+result.stderr)
        self.assertEqual({p.name:p.read_bytes() for p in bundle.iterdir()}, before)


if __name__ == '__main__':
    unittest.main()
