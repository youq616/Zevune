"""Synthetic PUBLIC bytes and refusal fixtures, never successful native proofs."""
import copy
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ledger_backup as backup
from ledger_recovery_backend import Checkpoint, RecoveryBackend, validate_reply, ordered
from test_ledger_restore import pin, response


class LedgerBackupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()

    def dummy_set(self, count=3):
        # Public consistency only; pins/dummy frames are NOT authenticated.
        root = self.root / 'set'
        (root / backup.BASE).mkdir(parents=True)
        (root / backup.BASE / 'genesis').write_bytes(bytes(108))
        pins = ordered([pin(i) for i in range(count)])
        for i in range(1, count):
            raw = b'ZVAIPK01' + bytes.fromhex(pins[i-1].encoded+pins[i].encoded)
            raw += (1).to_bytes(4, 'big') + bytes(12+150)
            (root / backup.increment(i)).write_bytes(raw)
        captured = backup.capture(root, pins, time.monotonic()+10, complete=False)
        (root / backup.MARKER).write_bytes(backup.marker(pins, captured[1], captured[2]))
        return root, pins

    def test_inspect_is_bounded_readonly_consistency_never_authentication(self):
        root, pins = self.dummy_set()
        before = {p.relative_to(root): p.read_bytes() for p in root.rglob('*') if p.is_file()}
        with patch('subprocess.Popen', side_effect=AssertionError('no backend allowed')):
            report = backup.inspect(root, [p.encoded for p in pins])
        self.assertTrue(report['completed'])
        for flag in ('inspection_is_authentication', 'replay_verified', 'snapshot_imported',
                     'finality_verified', 'validator_ready', 'real_funds_allowed'):
            self.assertIs(report[flag], False)
        self.assertEqual(before, {p.relative_to(root): p.read_bytes() for p in root.rglob('*') if p.is_file()})

    def test_marker_canonical_and_external_pins_required(self):
        root, pins = self.dummy_set()
        with self.assertRaises(ValueError): backup.inspect(root, [p.encoded for p in pins[:-1]])
        saved = (root / backup.MARKER).read_bytes()
        for raw in (saved+b' ', saved.replace(b'false', b'true', 1), b'{"checkpoints":["untrusted"]}'):
            (root / backup.MARKER).write_bytes(raw)
            with self.assertRaises(ValueError): backup.inspect(root, [p.encoded for p in pins])
        self.assertEqual((root/backup.MARKER).read_bytes(), raw)

    def test_every_artifact_change_or_extra_entry_is_rejected(self):
        root, pins = self.dummy_set()
        for path in (root/backup.BASE/'genesis', root/backup.increment(1), root/backup.increment(2)):
            raw=path.read_bytes(); changed=bytearray(raw); changed[-1] ^= 1; path.write_bytes(changed)
            with self.assertRaises(ValueError): backup.inspect(root, [p.encoded for p in pins])
            self.assertEqual(path.read_bytes(), changed); path.write_bytes(raw)
        (root/'unexpected').mkdir()
        with self.assertRaises(ValueError): backup.inspect(root, [p.encoded for p in pins])

    def test_maximum_chain_marker_fits_original_bound(self):
        root, pins = self.dummy_set(9)
        self.assertLessEqual((root/backup.MARKER).stat().st_size, backup.recovery.files.MAX_MANIFEST)
        self.assertEqual(backup.inspect(root, [p.encoded for p in pins])['package_count'], 8)
        for n in (True, 0, 9, -1, '1'):
            with self.assertRaises(ValueError): backup.increment(n)

    def test_snapshot_compatible_with_existing_restore_inputs(self):
        root, pins = self.dummy_set()
        for i in range(1, len(pins)):
            value=backup.recovery.package_snapshot(root/backup.increment(i), pins[i-1], pins[i])
            self.assertEqual(value[0][2],430)
        self.assertEqual(backup.recovery.archive_snapshot(root/backup.BASE,pins[0])[1]['genesis'][0][2],108)

    def test_output_must_be_new_and_outside_every_source(self):
        root, pins = self.dummy_set(1)
        for out in (root, root/backup.BASE/'new'):
            with self.assertRaises(ValueError):
                backup.create([(root/backup.BASE,pins[0].encoded)],out,None,reserve_bytes=0)
        self.assertFalse((root/backup.BASE/'new').exists())

    def test_public_hashes_do_not_replace_native_authentication(self):
        root,pins = self.dummy_set(1)
        class Refusal:
            def active(self,*args): raise RuntimeError('native_refusal')
        output=self.root/'refused'
        with self.assertRaises(RuntimeError):
            backup.create([(root/backup.BASE,pins[0].encoded)],output,Refusal(),reserve_bytes=0)
        self.assertFalse(output.exists())

    def test_budget_rounds_all_files_and_counts_directories(self):
        root,pins=self.dummy_set(1)
        captured=backup.recovery.archive_snapshot(root/backup.BASE,pins[0])
        sample=dict(allocation_unit_bytes=4096,available_bytes=16384,available_inodes=6,read_only=False)
        with patch.object(backup.recovery.space,'probe',return_value=sample):
            self.assertEqual(backup.budget(self.root,(1,2),captured,[430,430],0,time.monotonic()+2),16384)
        for change in ({'available_bytes':16383},{'available_inodes':5},{'read_only':True}):
            with patch.object(backup.recovery.space,'probe',return_value={**sample,**change}),self.assertRaises(ValueError):
                backup.budget(self.root,(1,2),captured,[430,430],0,time.monotonic()+2)

    def test_budget_overflow_and_deadline_refuse(self):
        root,pins=self.dummy_set(1);captured=backup.recovery.archive_snapshot(root/backup.BASE,pins[0])
        sample=dict(allocation_unit_bytes=None,available_bytes=(1<<63)-1,available_inodes=None,read_only=None)
        with patch.object(backup.recovery.space,'probe',return_value=sample):
            with self.assertRaises(ValueError): backup.budget(self.root,(1,2),captured,[],(1<<63)-1,time.monotonic()+2)
        with patch.object(backup.recovery.space,'probe',side_effect=AssertionError('expired before OS query')), self.assertRaises(ValueError):
            backup.budget(self.root,(1,2),captured,[],0,time.monotonic()-1)
        with patch.object(backup,'SET_SECONDS',-1),self.assertRaises(ValueError): backup.inspect(root,[pins[0].encoded])

    def test_new_native_responses_have_exact_write_and_restore_flags(self):
        base,later=Checkpoint.parse(pin()),Checkpoint.parse(pin(1))
        for mode in ('pack-active-incremental','verify-active-incremental'):
            reply=response(base,later,True)
            reply.update(operation=mode,archive_restored=False,incremental_backup_written=mode.startswith('pack-'))
            validate_reply(reply,mode,later,base)
            for field in ('archive_restored','incremental_backup_written','real_funds_allowed','replay_verified'):
                bad={**reply,field:not reply[field]}
                with self.assertRaises(ValueError): validate_reply(bad,mode,later,base)
            for field in reply:
                bad=copy.deepcopy(reply);del bad[field]
                with self.assertRaises(ValueError): validate_reply(bad,mode,later,base)
        reply=response(None,later);reply['operation']='backup-active'
        validate_reply(reply,'backup-active',later)

    def test_fixed_native_command_routing(self):
        base,later=Checkpoint.parse(pin()),Checkpoint.parse(pin(1))
        backend=RecoveryBackend(self.root/'unused','0'*64)
        # Capture requested arguments only. No result/authentication simulated.
        with patch.object(backend,'_run',side_effect=RuntimeError('observe_only')) as run:
            for action,mode in ((lambda:backend.backup(self.root,base,1,self.root/'new'),'backup-active'),
                                (lambda:backend.package(self.root,base,self.root,later,1,self.root/'new'),'pack-active-incremental'),
                                (lambda:backend.package(self.root,base,self.root,later,1),'verify-active-incremental')):
                with self.assertRaises(RuntimeError):action()
                self.assertEqual(run.call_args[0][0][0],mode)
                self.assertEqual(run.call_args[0][0].count('--no-real-funds'),1)

    def test_v9_packages_keep_all_old_exact_contracts(self):
        import build_local_lab as build
        import verify_local_lab as verify
        for windows in (False, True):
            root=self.root/('windows' if windows else 'linux');root.mkdir()
            for name in verify.required_files(windows,9): (root/name).write_bytes(b'inert payload; never executed')
            data=build.manifest_for(root,'a'*40,{'go':'go version go1.27.1 fixture','rust':'rustc 1.98.1 fixture'},'b'*40,'zevune-local-bundle-9')
            def check(data):
                raw=backup.recovery.files.canonical(data);(root/verify.MANIFEST).write_bytes(raw)
                return verify.verify(root,hashlib.sha256(raw).hexdigest(),'a'*40)
            self.assertEqual(check(data)['files_checked'],22)
            for old in range(2,9):
                with self.assertRaises(ValueError): check({**data,'format':f'zevune-local-bundle-{old}'})
            for name in ('ledger_backup.py','LEDGER_BACKUP.zh-CN.md'):
                raw=(root/name).read_bytes();(root/name).write_bytes(b'tampered')
                with self.assertRaises(ValueError):check(data)
                (root/name).write_bytes(raw)
            self.assertEqual(check(data)['files_checked'],22)

    def test_plain_cli_avoids_cache_and_redacts_unexpected_secret(self):
        bundle=self.root/'bundle';bundle.mkdir()
        for name in ('ledger_backup.py','ledger_restore.py','ledger_recovery_backend.py','wallet_backup.py',
                     'wallet_health.py','wallet_archive.py','wallet_backup_backend.py','zevune_wallet.py'):
            shutil.copyfile(Path(backup.__file__).parent/name,bundle/name)
        before={p.name:p.read_bytes() for p in bundle.iterdir()}
        env=os.environ.copy()
        for k in ('PYTHONDONTWRITEBYTECODE','PYTHONPYCACHEPREFIX'):env.pop(k,None)
        for args,code in ((['--help'],0),(['--no-real-funds','create','--help'],0),(['--private','SECRET_SENTINEL'],64)):
            result=subprocess.run([sys.executable,str(bundle/'ledger_backup.py'),*args],env=env,capture_output=True,timeout=15)
            self.assertEqual(result.returncode,code)
            self.assertNotIn(b'SECRET_SENTINEL',result.stdout+result.stderr)
        self.assertEqual(before,{p.name:p.read_bytes() for p in bundle.iterdir()})


if __name__=='__main__':unittest.main()
