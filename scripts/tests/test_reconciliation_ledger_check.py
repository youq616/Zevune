"""Refusal/preflight tests only; native replay success is never substituted.

Public synthetic headers and wallet frames intentionally contain no valid
Orchard authorization. Positive replay/CLI tests use real Rust in the driver.
"""
import contextlib
from dataclasses import replace
import hashlib
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import reconciliation_ledger_check as check
from test_reconciliation_view import fixture


class ReachedNative(RuntimeError):
    pass


class LedgerCheckTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='reconciliation-ledger-unit-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        values, self.report = fixture(self.root)
        self.folder = Path(values['directory'])
        self.journal = self.root / 'ledger'
        self.journal.mkdir()
        # The original fixture uses header length 108: one initial commitment.
        pin = check.view.Checkpoint.parse(values['checkpoint'])
        count = (pin.header - 76) // 32
        raw = (b'ZVOPOL03' + hashlib.sha256(b'zevune-orchard-lab-1').digest()
               + bytes.fromhex(values['genesis_sha256']) + count.to_bytes(4, 'big') + bytes(32 * count))
        (self.journal / 'genesis').write_bytes(raw)
        backend = Path(sys.executable).resolve()
        self.values = dict(values, journal=str(self.journal), backend=str(backend),
                           backend_sha256=hashlib.sha256(backend.read_bytes()).hexdigest())
        self.intent = check.prepare(self.values)
        self.before = self.inventory()

    def inventory(self):
        return {p.relative_to(self.root).as_posix(): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}

    def test_valid_public_preflight_reaches_refusing_native_exactly_once(self):
        with patch.object(check.RecoveryBackend, '_run', side_effect=ReachedNative('refusal')) as call:
            with self.assertRaises(ReachedNative):check.check(self.intent)
        self.assertEqual(call.call_count, 1)
        args, pin, base, deadline = call.call_args.args
        self.assertEqual(args, ['verify-active', '--no-real-funds', '--source', str(self.journal),
                                '--checkpoint', self.intent.evidence.checkpoint])
        self.assertIsNone(base)
        self.assertEqual(pin.encoded, self.intent.evidence.checkpoint)
        self.assertGreater(deadline, time.monotonic())
        self.assertLessEqual(deadline, time.monotonic() + 300)
        self.assertEqual(self.inventory(), self.before)

    def test_all_fields_validated_before_io(self):
        invalid = {'journal': ['relative', str(self.root / '..' / 'bad'), None, 'x\u202ey'],
                   'backend': ['relative', '', True, str(self.root)+'\n'],
                   'backend_sha256': ['0'*64, 'A'*64, 'x', False],
                   'report_sha256': ['A'*64, None], 'checkpoint': ['HEAD'], 'genesis_sha256': ['0'*64]}
        with patch.object(check, 'evidence_snapshot', side_effect=AssertionError('no IO')):
            for key, bad in invalid.items():
                for value in bad:
                    with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                        check.check(check.prepare(dict(self.values, **{key: value})))
            with self.assertRaises(ValueError):check.prepare(dict(self.values, extra=1))
            missing = dict(self.values); missing.pop('backend')
            with self.assertRaises(ValueError):check.prepare(missing)
            with self.assertRaises(ValueError):check.check(None)
            with self.assertRaises(ValueError):check.check(replace(self.intent, backend_sha256='x'))

    def test_nested_or_same_input_directories_rejected(self):
        for journal in (self.folder, self.folder / 'child', self.folder.parent):
            with self.subTest(journal=journal), self.assertRaises(ValueError):
                check.prepare(dict(self.values, journal=str(journal)))

    def test_utf8_path_byte_limit(self):
        with self.assertRaises(ValueError):check.prepare(dict(self.values, backend=str(self.root)+'/'+'中'*1400))

    def test_wrong_report_pin_never_launches(self):
        with patch.object(check.RecoveryBackend, '_run', side_effect=AssertionError('must not launch')):
            with self.assertRaises(ValueError):check.check(check.prepare(dict(self.values, report_sha256='0'*64)))

    def test_wrong_domain_or_header_rejected_before_native(self):
        path = self.journal / 'genesis'; raw = path.read_bytes()
        bad = [b'ZVOPOL02'+raw[8:], raw[:8]+bytes(32)+raw[40:], raw[:40]+bytes(32)+raw[72:],
               raw[:72]+(65537).to_bytes(4,'big')+raw[76:], raw[:-1], raw+b'x']
        with patch.object(check.RecoveryBackend, '_run', side_effect=AssertionError('must not launch')):
            for value in bad:
                path.write_bytes(value)
                with self.subTest(size=len(value)), self.assertRaises(ValueError):check.check(self.intent)
                path.write_bytes(raw)

    def test_checkpoint_pool_commitment_is_not_used_as_signing_domain(self):
        raw = (self.journal/'genesis').read_bytes()
        pin = check.view.Checkpoint.parse(self.intent.evidence.checkpoint)
        self.assertNotEqual(pin.genesis, self.intent.evidence.genesis_sha256)
        check.header_domain(raw, pin, self.intent.evidence.genesis_sha256)
        with self.assertRaises(ValueError):check.header_domain(raw, pin, pin.genesis)

    def test_journal_missing_extra_and_hardlinked_files_rejected(self):
        header = self.journal/'genesis'
        header.rename(self.root/'saved')
        with self.assertRaises(ValueError):check.check(self.intent)
        (self.root/'saved').rename(header)
        extra=self.journal/'extra';extra.write_bytes(b'x')
        with self.assertRaises(ValueError):check.check(self.intent)
        extra.unlink();os.link(header,self.root/'alias')
        with self.assertRaises(ValueError):check.check(self.intent)

    @unittest.skipUnless(os.name=='posix','POSIX links/FIFO only')
    def test_linked_ledger_backend_parent_and_fifo_refused(self):
        alias=self.root/'alias';alias.symlink_to(self.journal,target_is_directory=True)
        with self.assertRaises(ValueError):check.check(check.prepare(dict(self.values,journal=str(alias))))
        binary=Path(self.values['backend']);tools=self.root/'tools';tools.symlink_to(binary.parent,target_is_directory=True)
        with self.assertRaises(ValueError):check.check(check.prepare(dict(self.values,backend=str(tools/binary.name))))
        path=self.journal/'genesis';path.unlink();os.mkfifo(path)
        with self.assertRaises(ValueError):check.check(self.intent)

    def test_real_wrong_backend_hash_rejected_without_process(self):
        with patch.object(subprocess,'Popen',side_effect=AssertionError('bad hash started process')):
            with self.assertRaises((ValueError,RuntimeError)):
                check.check(check.prepare(dict(self.values,backend_sha256='a'*64)))
        self.assertEqual(self.inventory(), self.before)

    def test_real_python_executable_is_not_accepted_as_recovery_backend(self):
        # Real interpreter refuses verify-active. It is not an executable mock verifier.
        with self.assertRaises((ValueError,RuntimeError)):check.check(self.intent)
        self.assertEqual(self.inventory(),self.before)

    def test_no_restore_backup_incremental_or_alternate_source_can_run(self):
        pin=check.view.Checkpoint.parse(self.intent.evidence.checkpoint)
        backend=check.LedgerVerifier(self.intent.backend,self.intent.backend_sha256,self.journal,pin)
        deadline=time.monotonic()+300
        with patch.object(check.RecoveryBackend,'_run',side_effect=AssertionError('mutating native call')):
            for action in (lambda:backend.active(self.journal,pin,deadline,output=self.root/'new'),
                           lambda:backend.backup(self.journal,pin,deadline,self.root/'new'),
                           lambda:backend.active(self.root/'other',pin,deadline),
                           lambda:backend._run(['verify-active'],pin,None,deadline)):
                with self.assertRaises(ValueError):action()
        self.assertEqual(self.inventory(),self.before)

    def test_malformed_success_reply_is_not_replay_proof(self):
        for reply in ({}, {'replay_verified':True}, None, {'operation':'restore-active'}):
            with patch.object(check.RecoveryBackend,'_run',return_value=reply):
                with self.subTest(reply=reply),self.assertRaises(ValueError):check.check(self.intent)
        self.assertEqual(self.inventory(),self.before)

    def test_preflight_time_uses_same_deadline_without_native_launch(self):
        real=check.evidence_snapshot
        def slow(*args):
            answer=real(*args)
            time.sleep(0.035)
            return answer
        with patch.object(check,'CHECK_SECONDS',0.02),patch.object(check,'evidence_snapshot',side_effect=slow),\
                patch.object(check.RecoveryBackend,'_run',side_effect=AssertionError('expired launch')):
            with self.assertRaisesRegex(ValueError,'deadline'):check.check(self.intent)

    def test_backend_timeout_is_not_retried_or_returned_as_success(self):
        with patch.object(check.RecoveryBackend,'_run',side_effect=RuntimeError('private timeout')) as call:
            with self.assertRaises(RuntimeError):check.check(self.intent)
        self.assertEqual(call.call_count,1)
        self.assertEqual(self.inventory(),self.before)

    def test_evidence_mutation_during_view_refuses_before_native(self):
        real=check.view.inspect
        def changed(intent):
            result=real(intent)
            with (self.folder/'wallet.journal').open('ab') as f:f.write(b'x')
            return result
        with patch.object(check.view,'inspect',side_effect=changed),\
                patch.object(check.RecoveryBackend,'_run',side_effect=AssertionError('changed source')):
            with self.assertRaises(ValueError):check.check(self.intent)

    def test_evidence_same_bytes_replacement_detected(self):
        before=check.evidence_snapshot(self.folder,time.monotonic()+3)
        path=self.folder/'wallet.journal';raw=path.read_bytes();path.rename(self.root/'old');path.write_bytes(raw)
        with self.assertRaises(ValueError):check.evidence_unchanged(self.folder,before,time.monotonic()+3)

    def test_report_directory_replacement_detected(self):
        before=check.evidence_snapshot(self.folder,time.monotonic()+3)
        self.folder.rename(self.root/'old');self.folder.mkdir()
        for name,raw in self.before.items():
            if name.startswith('result/'):(self.folder/Path(name).name).write_bytes(raw)
        with self.assertRaises(ValueError):check.evidence_unchanged(self.folder,before,time.monotonic()+3)

    def test_cli_failure_no_sensitive_output_and_no_success(self):
        values=dict(self.values,backend_sha256='b'*64)
        command=[sys.executable,check.__file__,'--no-real-funds']
        for key,value in values.items():command.extend(['--'+key.replace('_','-'),value])
        process=subprocess.run(command,capture_output=True,timeout=10)
        self.assertEqual(process.returncode,1);self.assertEqual(process.stdout,b'')
        self.assertNotIn(str(self.root).encode(),process.stderr)
        for tail in (['--secret','PRIVATE_SENTINEL'],['--no-real-funds','--back','PRIVATE_SENTINEL']):
            bad=subprocess.run([sys.executable,check.__file__,*tail],capture_output=True,timeout=10)
            self.assertEqual(bad.returncode,64);self.assertNotIn(b'PRIVATE',bad.stderr+bad.stdout)

    def test_cli_interrupt_has_no_partial_success(self):
        args=['--no-real-funds']
        for key,value in self.values.items():args.extend(['--'+key.replace('_','-'),value])
        out,err=io.StringIO(),io.StringIO()
        with patch.object(check,'check',side_effect=KeyboardInterrupt('PRIVATE')),\
                contextlib.redirect_stdout(out),contextlib.redirect_stderr(err):code=check.main(args)
        self.assertEqual(code,130);self.assertEqual(out.getvalue(),'');self.assertNotIn('PRIVATE',err.getvalue())


if __name__=='__main__':unittest.main()
