"""Execute actual portable CLIs without -B; verified bundle files stay unchanged.

The public inspection fixture is synthetic and never claims AEAD validity.
The catalog commands do not need a backend and cannot authorize a payment.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from test_wallet_archive import packed
from test_wallet_backup import frames

SCRIPTS = Path(__file__).resolve().parents[1]
PAYLOADS = ('wallet_archive.py', 'wallet_backup.py', 'wallet_backup_backend.py', 'zevune_wallet.py')


class PortableCLIFileTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='portable-cli-files-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.bundle = self.root / 'bundle'
        self.bundle.mkdir()
        for name in PAYLOADS:
            shutil.copyfile(SCRIPTS / name, self.bundle / name)
        self.before = self.inventory()
        self.environment = os.environ.copy()
        for key in ('PYTHONDONTWRITEBYTECODE', 'PYTHONPYCACHEPREFIX'):
            self.environment.pop(key, None)

    def inventory(self):
        return {str(p.relative_to(self.bundle)): p.read_bytes() if p.is_file() else None
                for p in self.bundle.rglob('*')}

    def command(self, script, args):
        result = subprocess.run([sys.executable, str(self.bundle / script), '--no-real-funds', *args],
                                cwd=self.root, env=self.environment, capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 0, 'native CLI did not succeed')
        self.assertEqual(result.stderr, b'')
        self.assertTrue(self.inventory() == self.before, 'CLI wrote into the verified bundle')
        return json.loads(result.stdout)

    def test_actual_inspect_does_not_create_bytecode_or_other_bundle_files(self):
        wallet, pin = frames(2)
        raw = packed(wallet, pin)
        path = self.root / 'fixture.zvbackup'
        path.write_bytes(raw)
        result = self.command('wallet_archive.py', ['inspect', str(path), '--pin', pin,
                              '--archive-sha256', hashlib.sha256(raw).hexdigest()])
        self.assertIs(result['authenticated'], False)
        self.assertEqual(path.read_bytes(), raw)

    def test_packaged_catalog_entrypoint_preserves_bundle_during_init_and_list(self):
        target = self.root / 'new-catalog'
        result = self.command('wallet_backup.py', ['init', str(target)])
        self.assertEqual(result['result'], 'catalog_created')
        result = self.command('wallet_backup.py', ['list', str(target)])
        self.assertEqual(result['versions'], [])


if __name__ == '__main__':
    unittest.main()
