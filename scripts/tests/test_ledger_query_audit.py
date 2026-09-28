"""Real public task/report files and failures, never a successful native double."""
import contextlib
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ledger_query_audit as audit
from test_ledger_restore import pin


def fixture(folder, count=3):
    request = audit.task.prepare(pin(7), 'd' * 64, 'e' * 64,
                                 tuple(f'{i:064x}' for i in reversed(range(count))))
    path = folder / 'task.json'
    raw = audit.task.encode(request)
    audit.files.write_new(path, raw)
    return path, hashlib.sha256(raw).hexdigest(), request


class AuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='zevune-audit-tests-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.source, self.source_pin, self.request = fixture(self.root)
        self.target = self.root / 'audit.json'
        self.original = self.source.read_bytes()
        self.raw = audit.encode(self.request, self.source_pin)
        self.audit_pin = hashlib.sha256(self.raw).hexdigest()

    def export(self):
        return audit.export_audit(self.source, self.source_pin, self.target)

    def recheck(self):
        return audit.recheck(self.target, self.audit_pin, self.source, self.source_pin)

    def reject_document(self, document):
        raw = audit.files.canonical(document)
        with self.assertRaises(ValueError):
            audit.decode(raw, hashlib.sha256(raw).hexdigest())

    def test_report_is_deterministic_and_preserves_original_order(self):
        report = audit.report_for(self.request, self.source_pin)
        self.assertEqual(audit.decode(self.raw, self.audit_pin), (self.request, self.source_pin))
        self.assertEqual(report['query_count'], 3)
        self.assertEqual(report['checkpoint_height'], 7)
        self.assertEqual(report['request_bytes'], len(self.original))
        self.assertEqual(report['request']['txids'], list(self.request.txids))
        self.assertNotIn(str(self.root).encode(), self.raw)
        for name in ('timestamp', 'created_at', 'hostname', 'path', 'file_identity'):
            self.assertNotIn(name, report)
        other = self.root / 'other'; other.mkdir()
        path, pin_, request = fixture(other)
        self.assertEqual(self.source_pin, pin_)
        self.assertEqual(audit.inspect_task(path, pin_), audit.inspect_task(self.source, self.source_pin))

    def test_result_objects_do_not_alias_request(self):
        first = audit.report_for(self.request, self.source_pin)
        first['request']['txids'].reverse()
        self.assertEqual(audit.report_for(self.request, self.source_pin)['request']['txids'], list(self.request.txids))
        self.assertEqual(audit.encode(self.request, self.source_pin), self.raw)

    def test_each_report_field_is_required_and_extra_metadata_refused(self):
        expected = json.loads(self.raw)
        for key in expected:
            bad = dict(expected); del bad[key]
            with self.subTest(missing=key): self.reject_document(bad)
        for name in ('created_at', 'signature', 'auto_run', 'backend', 'journal', 'permission'):
            self.reject_document(dict(expected, **{name: 'UNTRUSTED'}))

    def test_every_false_flag_rejects_true_integer_and_string(self):
        expected = json.loads(self.raw)
        for key in ('query_executed', 'signature_verified', 'backend_verified', 'ledger_replayed',
                    'retry_authorized', 'real_funds_allowed'):
            for value in (True, 0, 1, None, 'false'):
                with self.subTest(key=key, value=value):
                    self.reject_document(dict(expected, **{key: value}))

    def test_derived_fields_and_scope_cannot_be_forged(self):
        expected = json.loads(self.raw)
        for key, value in (('format', 'zevune-ledger-query-audit-2'), ('scope', 'executed'),
                           ('query_count', 2), ('query_count', True), ('checkpoint_height', 8),
                           ('request_bytes', len(self.original)+1), ('request_bytes', float(len(self.original))),
                           ('request_sha256', '0'*64)):
            with self.subTest(key=key): self.reject_document(dict(expected, **{key: value}))

    def test_nested_task_uses_original_decoder_not_new_acceptance(self):
        for change in ({'query_profile': 'other'}, {'real_funds_allowed': True},
                       {'txids': ['0'*64]*2}, {'backend': '/not/allowed'}):
            bad = json.loads(self.raw)
            bad['request'].update(change)
            # Even a matching changed nested digest cannot bless an invalid original task.
            bad['request_sha256'] = hashlib.sha256(audit.files.canonical(bad['request'])).hexdigest()
            self.reject_document(bad)

    def test_report_pin_is_verified_before_json_parsing(self):
        with patch.object(audit.json, 'loads', side_effect=AssertionError('untrusted parse')):
            with self.assertRaises(ValueError): audit.decode(self.raw, '0'*64)
        with patch.object(audit.task.view, '_chain', side_effect=AssertionError('no IO')):
            for value in (None, 'A'*64, '', False):
                with self.assertRaises(ValueError): audit.load(self.target, value)

    def test_canonical_json_duplicate_keys_bom_nonfinite_and_depth(self):
        variants = (self.raw+b' ', b'\xef\xbb\xbf'+self.raw,
                    json.dumps(json.loads(self.raw), indent=2).encode(),
                    self.raw[:-2]+b',"scope":"task_content_only"}\n',
                    self.raw.replace(b'"query_count":3', b'"query_count":NaN'),
                    self.raw.replace(b'"query_count":3', b'"query_count":Infinity'),
                    b'[]\n', b'null\n', b'\xff', b'['*3000+b']'*3000)
        for raw in variants:
            with self.subTest(size=len(raw)), self.assertRaises((ValueError, RecursionError)):
                audit.decode(raw, hashlib.sha256(raw).hexdigest())

    def test_all_truncations_fail_and_maximum_input_bounded(self):
        for length in range(len(self.raw)):
            raw = self.raw[:length]
            with self.assertRaises(ValueError): audit.decode(raw, hashlib.sha256(raw).hexdigest())
        raw = b' ' * (audit.MAX_REPORT_BYTES+1)
        with self.assertRaises(ValueError): audit.decode(raw, hashlib.sha256(raw).hexdigest())
        self.target.write_bytes(raw)
        with self.assertRaises(ValueError): audit.load(self.target, hashlib.sha256(raw).hexdigest())

    def test_minimum_and_32_ids_round_trip(self):
        for count in (1, 32):
            folder = self.root / str(count); folder.mkdir()
            source, pin_, request = fixture(folder, count)
            target = folder / 'audit.json'
            result = audit.export_audit(source, pin_, target)
            self.assertEqual(result['query_count'], count)
            self.assertLess(result['audit_bytes'], audit.MAX_REPORT_BYTES)
            checked = audit.recheck(target, result['audit_sha256'], source, pin_)
            self.assertTrue(checked['source_file_rechecked'])

    def test_all_operations_never_run_query_process_or_read_ledger(self):
        allowed = {self.source, self.target}
        actual = audit.files.read_file
        def guarded(path, bound):
            self.assertIn(path, allowed)
            return actual(path, bound)
        with patch.object(subprocess, 'Popen', side_effect=AssertionError('no execution')), \
                patch.object(audit.task, 'run_request', side_effect=AssertionError('no query')), \
                patch.object(audit.task.once, 'lookup_batch_once', side_effect=AssertionError('no lookup')), \
                patch.object(audit.task.once.single.ledger, 'archive_snapshot', side_effect=AssertionError('no ledger')), \
                patch.object(audit.files, 'read_file', side_effect=guarded):
            inspected = audit.inspect_task(self.source, self.source_pin)
            self.export()
            alone = audit.verify_audit(self.target, self.audit_pin)
            together = self.recheck()
        self.assertTrue(inspected['source_file_rechecked'])
        self.assertFalse(alone['source_file_rechecked'])
        self.assertTrue(together['source_file_rechecked'])
        self.assertFalse(together['query_executed'])
        self.assertEqual(self.source.read_bytes(), self.original)

    def test_standalone_verification_never_asserts_source_still_exists(self):
        self.export(); self.source.unlink()
        result = audit.verify_audit(self.target, self.audit_pin)
        self.assertTrue(result['audit_integrity_verified'])
        self.assertFalse(result['source_file_rechecked'])
        self.assertFalse(result['report']['query_executed'])
        with self.assertRaises(OSError): self.recheck()

    def test_recheck_requires_independent_source_pin_before_source_access(self):
        self.export()
        with patch.object(audit.task, 'load', side_effect=AssertionError('pin mismatch before source IO')):
            with self.assertRaises(ValueError):
                audit.recheck(self.target, self.audit_pin, self.source, '0'*64)

    def test_matching_copy_can_be_rechecked_but_no_export_time_identity_claim(self):
        self.export()
        moved = self.root / 'copied-task.json'; moved.write_bytes(self.original)
        result = audit.recheck(self.target, self.audit_pin, moved, self.source_pin)
        self.assertTrue(result['source_file_rechecked'])
        self.assertNotIn('unchanged_since_export', result)

    def test_existing_empty_populated_directory_and_same_source_refused(self):
        for raw in (b'', b'KEEP'):
            self.target.write_bytes(raw)
            with self.assertRaises(ValueError): self.export()
            self.assertEqual(self.target.read_bytes(), raw); self.target.unlink()
        self.target.mkdir()
        with self.assertRaises(ValueError): self.export()
        self.assertEqual(list(self.target.iterdir()), [])
        with self.assertRaises(ValueError): audit.export_audit(self.source, self.source_pin, self.source)
        self.assertEqual(self.source.read_bytes(), self.original)

    def test_invalid_input_paths_fail_before_reads_or_creation(self):
        with patch.object(audit.task, 'load', side_effect=AssertionError('no source IO')):
            for target in (Path('relative'), self.root/'..'/'escape', str(self.target),
                           self.root/'new\nline', self.root/('中'*1400)):
                with self.assertRaises(ValueError): audit.export_audit(self.source, self.source_pin, target)
            with self.assertRaises(ValueError):
                audit.recheck(self.target, self.audit_pin, Path('relative'), self.source_pin)
        with self.assertRaises(OSError): audit.export_audit(self.source, self.source_pin, self.root/'missing'/'new')
        self.assertFalse((self.root/'missing').exists())

    def test_wrong_source_pin_cannot_create_report(self):
        with self.assertRaises(ValueError): audit.export_audit(self.source, '0'*64, self.target)
        self.assertFalse(self.target.exists())

    def test_partial_write_fsync_failure_and_existing_partial_remain(self):
        real = audit.files.write_new
        def failed(path, raw):
            real(path, raw[:30]); raise OSError('PRIVATE_WRITE')
        with patch.object(audit.files, 'write_new', side_effect=failed), self.assertRaises(OSError): self.export()
        self.assertEqual(self.target.read_bytes(), self.raw[:30])
        with self.assertRaises(ValueError): self.export()
        self.target.unlink()
        with patch.object(audit.files.os, 'fsync', side_effect=OSError('PRIVATE_SYNC')), self.assertRaises(OSError):
            self.export()
        self.assertTrue(self.target.exists())
        self.assertEqual(self.source.read_bytes(), self.original)

    def test_silent_short_copy_is_refused_by_output_reread(self):
        real = audit.files.write_new
        with patch.object(audit.files, 'write_new', side_effect=lambda p,b: real(p,b[:30])), self.assertRaises(ValueError):
            self.export()
        self.assertEqual(self.target.read_bytes(), self.raw[:30])

    def test_lost_write_acknowledgement_is_not_a_successful_export(self):
        real = audit.files.write_new
        def lost(path, raw):
            real(path, raw); raise OSError('PRIVATE_ACK')
        with patch.object(audit.files, 'write_new', side_effect=lost), self.assertRaises(OSError): self.export()
        result = audit.verify_audit(self.target, self.audit_pin)
        self.assertTrue(result['audit_integrity_verified'])
        self.assertNotIn('created', result)

    def test_source_change_during_report_write_refuses_success(self):
        real = audit.files.write_new
        def changed(path, raw):
            real(path, raw); self.source.write_bytes(self.original+b'x')
        with patch.object(audit.files, 'write_new', side_effect=changed), self.assertRaises(ValueError): self.export()
        self.assertTrue(self.target.exists())

    def test_report_changed_during_final_source_read_is_rejected(self):
        real = audit.task.unchanged
        def changed(snapshot):
            real(snapshot)
            if self.target.exists(): self.target.write_bytes(self.raw+b'x')
        with patch.object(audit.task, 'unchanged', side_effect=changed), self.assertRaises(ValueError): self.export()

    def test_source_changes_during_last_report_read_cannot_report_success(self):
        real = audit.unchanged
        calls = []
        def changed(snapshot):
            real(snapshot); calls.append(1)
            if len(calls)==2: self.source.write_bytes(self.original+b'x')
        with patch.object(audit, 'unchanged', side_effect=changed), self.assertRaises(ValueError): self.export()
        self.assertEqual(len(calls), 2)

    def test_file_and_parent_replacement_are_detected(self):
        self.export(); snapshot = audit.load(self.target, self.audit_pin)
        self.target.rename(self.root/'old'); self.target.write_bytes(self.raw)
        with self.assertRaises(ValueError): audit.unchanged(snapshot)
        parent = self.root/'reports'; parent.mkdir()
        target = parent/'audit.json'; target.write_bytes(self.raw)
        snapshot = audit.load(target, self.audit_pin)
        parent.rename(self.root/'old-parent'); parent.mkdir(); target.write_bytes(self.raw)
        with self.assertRaises(ValueError): audit.unchanged(snapshot)

    def test_hardlinks_on_source_or_report_refused(self):
        self.export()
        os.link(self.target, self.root/'alias')
        with self.assertRaises(ValueError): audit.verify_audit(self.target, self.audit_pin)
        (self.root/'alias').unlink(); os.link(self.source, self.root/'alias')
        with self.assertRaises(ValueError): self.recheck()

    @unittest.skipUnless(os.name=='posix', 'POSIX link/FIFO fixture')
    def test_links_fifo_and_dangling_destination_refused(self):
        self.export()
        alias = self.root/'alias'; alias.symlink_to(self.target)
        with self.assertRaises(ValueError): audit.load(alias, self.audit_pin)
        alias.unlink(); alias.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(ValueError): audit.load(alias/self.target.name, self.audit_pin)
        self.target.unlink(); os.mkfifo(self.target)
        with self.assertRaises(ValueError): audit.load(self.target, self.audit_pin)
        self.target.unlink(); self.target.symlink_to(self.root/'missing')
        with self.assertRaises(ValueError): self.export()
        self.assertTrue(self.target.is_symlink())

    def test_windows_reparse_parent_refused(self):
        from types import SimpleNamespace
        info = self.root.lstat()
        before = SimpleNamespace(st_mode=info.st_mode, st_file_attributes=0x400)
        with patch.object(Path, 'lstat', return_value=before), self.assertRaises(ValueError):
            audit.load(self.target, self.audit_pin)

    def test_real_cli_export_verify_recheck_and_fixed_failures(self):
        common = ['--request', str(self.source), '--request-sha256', self.source_pin]
        report = ['--audit', str(self.target), '--audit-sha256', self.audit_pin]
        for args in (['inspect', *common], ['export', *common, '--destination', str(self.target)],
                     ['verify', *report], ['recheck', *report, *common]):
            p = subprocess.run([sys.executable, audit.__file__, '--no-real-funds', *args], capture_output=True, timeout=10)
            self.assertEqual(p.returncode, 0, p.stderr); self.assertIsInstance(json.loads(p.stdout), dict)
        for args, code in ((['--private', 'PRIVATE_SENTINEL'],64),
                           (['--no-real-funds','export',*common,'--destination',str(self.target)],1),
                           (['--no-real-funds','verify','--audit',str(self.target),'--audit-sha256','PRIVATE_SENTINEL'],1)):
            p = subprocess.run([sys.executable, audit.__file__, *args], capture_output=True, timeout=10)
            self.assertEqual(p.returncode, code); self.assertEqual(p.stdout, b'')
            self.assertNotIn(b'PRIVATE', p.stderr); self.assertNotIn(str(self.root).encode(), p.stderr)
        self.assertEqual(self.source.read_bytes(), self.original)

    def test_errors_interrupt_and_write_failure_never_become_valid_results(self):
        args = ['--no-real-funds','inspect','--request',str(self.source),'--request-sha256',self.source_pin]
        for error in (OSError('PRIVATE'), ValueError('PRIVATE'), KeyboardInterrupt('PRIVATE')):
            out, err = io.StringIO(), io.StringIO()
            with patch.object(audit, 'inspect_task', side_effect=error), \
                    contextlib.redirect_stdout(out), contextlib.redirect_stderr(err): code = audit.main(args)
            self.assertEqual(code, 130 if isinstance(error,KeyboardInterrupt) else 1)
            self.assertEqual(out.getvalue(), ''); self.assertNotIn('PRIVATE',err.getvalue())
        with patch.object(audit.task.view, 'write_output', side_effect=OSError('PRIVATE')):
            with contextlib.redirect_stderr(io.StringIO()): self.assertEqual(audit.main(args), 1)

    def test_unicode_paths_and_legacy_stdout_do_not_change_report_bytes(self):
        target = self.root/'审计 报告.json'
        result = audit.export_audit(self.source, self.source_pin, target)
        p = subprocess.run([sys.executable,audit.__file__,'--no-real-funds','verify','--audit',str(target),
                            '--audit-sha256',result['audit_sha256']],capture_output=True,timeout=10,
                           env={**os.environ,'PYTHONIOENCODING':'cp1252','PYTHONUTF8':'0'})
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertTrue(json.loads(p.stdout.decode('utf-8'))['audit_integrity_verified'])
        self.assertEqual(target.read_bytes(),self.raw)


if __name__=='__main__':
    unittest.main()
