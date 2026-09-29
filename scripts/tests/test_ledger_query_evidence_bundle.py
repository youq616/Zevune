"""Real canonical task/report files and create-only round trips; no native doubles."""
from dataclasses import replace
import contextlib
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
import ledger_query_evidence_bundle as bundle
from test_ledger_query_request_audit import request


class BundleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='zevune-evidence-bundle-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.task_path, self.report_path = self.root / 'a.json', self.root / 'a-report.json'
        self.request = request()
        self.task_pin = bundle.task.create(self.request, self.task_path)['request_sha256']
        self.report_pin = bundle.reports.export_audit(self.task_path, self.task_pin, self.report_path)['audit_sha256']
        self.sources = (bundle.evidence.Source('task', self.task_path, self.task_pin),
                        bundle.evidence.Source('report', self.report_path, self.report_pin))
        self.entries = tuple(bundle.entry(s.kind, s.sha256, s.path.read_bytes()) for s in self.sources)
        self.raw = bundle.encode(self.entries)
        self.pin = hashlib.sha256(self.raw).hexdigest()
        self.path, self.dest = self.root / 'handoff.json', self.root / 'restored'

    def pack(self):
        return bundle.pack(self.sources, self.path)

    def unpack(self):
        return bundle.unpack(self.path, self.pin, self.dest)

    def redigest(self, data):
        raw = bundle.files.canonical(data)
        return raw, hashlib.sha256(raw).hexdigest()

    def test_real_round_trip_exact_bytes_order_and_derived_names(self):
        result = self.pack()
        self.assertEqual(self.path.read_bytes(), self.raw)
        self.assertEqual(result['bundle_sha256'], self.pin)
        self.assertTrue(result['selected_input_files_rechecked'])
        restored = self.unpack()
        self.assertTrue(restored['directory_bytes_verified'])
        self.assertEqual(sorted(p.name for p in self.dest.iterdir()), ['01-task.json', '02-report.json'])
        for meta, item in zip(restored['entries'], self.entries):
            self.assertEqual((self.dest / meta['filename']).read_bytes(), item.raw)
            self.assertEqual(meta['request_sha256'], self.task_pin)
        checked = bundle.verify_directory(self.path, self.pin, self.dest)
        self.assertTrue(checked['directory_bytes_verified'])
        self.assertFalse(checked['unpack_call_success_verified'])

    def test_canonical_encoding_deterministic_and_has_no_source_paths(self):
        self.assertEqual(bundle.decode(self.raw, self.pin), self.entries)
        self.assertEqual(bundle.encode(bundle.decode(self.raw, self.pin)), self.raw)
        self.assertNotIn(str(self.root).encode(), self.raw)
        self.assertEqual(bundle.encode(tuple(reversed(self.entries))), bundle.encode(tuple(reversed(self.entries))))
        self.assertNotEqual(bundle.encode(tuple(reversed(self.entries))), self.raw)
        with self.assertRaises(AttributeError): self.entries[0].kind = 'report'

    def test_external_pin_precedes_json_parse(self):
        with patch.object(bundle.json, 'loads', side_effect=AssertionError('untrusted parse')):
            with self.assertRaises(ValueError): bundle.decode(self.raw, '0'*64)
        with patch.object(bundle.task.view, '_chain', side_effect=AssertionError('early IO')):
            with self.assertRaises(ValueError): bundle.load(self.path, 'A'*64)

    def test_all_sources_and_output_syntax_checked_before_first_read(self):
        with patch.object(bundle.evidence, '_load', side_effect=AssertionError('early IO')):
            for bad in (None, replace(self.sources[1], kind='auto'), replace(self.sources[1], sha256=False),
                        replace(self.sources[1], path=Path('relative'))):
                with self.assertRaises(ValueError): bundle.pack((self.sources[0], bad), self.path)
            for bad in ((), list(self.sources), (self.sources[0],)*33):
                with self.assertRaises(ValueError): bundle.pack(bad, self.path)
            for path in (Path('relative'), str(self.path), self.root/'..'/'other', self.root/'a\u202eb'):
                with self.assertRaises(ValueError): bundle.pack(self.sources, path)
            with self.assertRaises(ValueError): bundle.pack(self.sources, self.task_path)
            with self.assertRaises(ValueError): bundle.pack((self.sources[0],)*2, self.path)

    def test_encode_invalid_types_and_duplicate_items_refused(self):
        for bad in (None, [], (), self.entries * 17, (self.entries[0],)*2, (None,)):
            with self.assertRaises(ValueError): bundle.encode(bad)
        for item in (replace(self.entries[0], kind='auto'), replace(self.entries[0], sha256='0'*64),
                     replace(self.entries[0], raw=bytearray(self.entries[0].raw))):
            with self.assertRaises(ValueError): bundle.encode((item,))

    def test_every_outer_and_item_field_required_extra_names_refused(self):
        data = json.loads(self.raw)
        for key in data:
            wrong = dict(data); wrong.pop(key)
            with self.assertRaises(ValueError): bundle.decode(*self.redigest(wrong))
        for key in data['entries'][0]:
            wrong = json.loads(self.raw); wrong['entries'][0].pop(key)
            with self.assertRaises(ValueError): bundle.decode(*self.redigest(wrong))
        for key in ('filename', 'path', 'command', 'auto_run', 'destination'):
            wrong = json.loads(self.raw); wrong['entries'][0][key] = '../../PRIVATE'
            with self.assertRaises(ValueError): bundle.decode(*self.redigest(wrong))

    def test_unknown_version_and_exact_bool_types(self):
        for key in ('execution_performed', 'signature_verified', 'real_funds_allowed'):
            for value in (0, None, True, 'false'):
                data = json.loads(self.raw); data[key] = value
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    bundle.decode(*self.redigest(data))
        data = json.loads(self.raw); data['format'] = 'zevune-query-evidence-bundle-2'
        with self.assertRaises(ValueError): bundle.decode(*self.redigest(data))

    def test_rehashed_noncanonical_duplicates_bom_and_nonfinite_refused(self):
        cases = [self.raw+b' ', b'\xef\xbb\xbf'+self.raw, b'[]', b'null', b'\xff',
                 self.raw[:-2]+b',"real_funds_allowed":false}\n',
                 self.raw.replace(b'false', b'NaN', 1), json.dumps(json.loads(self.raw), indent=2).encode()]
        for raw in cases:
            with self.subTest(size=len(raw)), self.assertRaises(ValueError):
                bundle.decode(raw, hashlib.sha256(raw).hexdigest())

    def test_hex_must_be_lowercase_exact_no_space_and_bounded(self):
        for value in (self.entries[0].raw.hex().upper(), ' '+self.entries[0].raw.hex(), 'a', 'gg', '', None,
                      '0'*(bundle.reports.MAX_REPORT_BYTES*2+2)):
            data = json.loads(self.raw); data['entries'][0]['data_hex'] = value
            with self.subTest(value=str(value)[:30]), self.assertRaises(ValueError):
                bundle.decode(*self.redigest(data))

    def test_nested_formats_and_hashes_still_use_original_decoders(self):
        for kind in ('task', 'report'):
            i = 0 if kind == 'task' else 1
            data = json.loads(self.raw); record = data['entries'][i]
            record['kind'] = 'report' if kind == 'task' else 'task'
            with self.assertRaises(ValueError): bundle.decode(*self.redigest(data))
            data = json.loads(self.raw); record = data['entries'][i]
            payload = json.loads(bytes.fromhex(record['data_hex']))
            payload['real_funds_allowed'] = 0
            raw = bundle.files.canonical(payload)
            record.update(data_hex=raw.hex(), sha256=hashlib.sha256(raw).hexdigest())
            with self.assertRaises(ValueError): bundle.decode(*self.redigest(data))

    def test_count_limits_and_32_real_distinct_entries(self):
        items = []
        for i in range(32):
            raw = bundle.task.encode(request(range(i*32, (i+1)*32)))
            sha = hashlib.sha256(raw).hexdigest()
            report = bundle.reports.encode(bundle.task.decode(raw, sha), sha)
            items.append(bundle.entry('report', hashlib.sha256(report).hexdigest(), report))
        raw = bundle.encode(tuple(items)); pin = hashlib.sha256(raw).hexdigest()
        self.assertLess(len(raw), bundle.MAX_BUNDLE_BYTES)
        self.assertEqual(bundle.decode(raw, pin), tuple(items))
        for entries in ([], json.loads(self.raw)['entries']*17):
            data = json.loads(self.raw); data['entries'] = entries
            with self.assertRaises(ValueError): bundle.decode(*self.redigest(data))
        with self.assertRaises(ValueError): bundle.decode(b'x'*(bundle.MAX_BUNDLE_BYTES+1), '0'*64)

    def test_verify_and_unpack_after_original_inputs_deleted_do_not_claim_recheck(self):
        self.pack()
        self.task_path.unlink(); self.report_path.unlink()
        for result in (bundle.verify(self.path, self.pin), self.unpack()):
            for key in ('original_inputs_rechecked', 'execution_performed', 'signature_verified',
                        'ledger_replayed', 'approval_reusable', 'retry_authorized', 'real_funds_allowed'):
                self.assertIs(result[key], False)
        with patch.object(bundle.task, 'load', side_effect=AssertionError('original reopened')):
            self.assertTrue(bundle.verify(self.path, self.pin)['bundle_integrity_verified'])

    def test_existing_pack_file_and_unpack_directory_never_overwritten(self):
        self.path.write_bytes(b'')
        with self.assertRaises(ValueError): self.pack()
        self.assertEqual(self.path.read_bytes(), b'')
        self.path.unlink(); self.pack(); self.dest.mkdir()
        for populate in (False, True):
            if populate: (self.dest/'keep').write_bytes(b'KEEP')
            with self.assertRaises(FileExistsError): self.unpack()
            self.assertEqual(sorted(p.name for p in self.dest.iterdir()), ['keep'] if populate else [])
        self.assertEqual(self.path.read_bytes(), self.raw)

    def test_every_entry_is_verified_before_creating_directory(self):
        data = json.loads(self.raw); data['entries'][-1]['sha256'] = '0'*64
        raw, sha = self.redigest(data); self.path.write_bytes(raw)
        with self.assertRaises(ValueError): bundle.unpack(self.path, sha, self.dest)
        self.assertFalse(self.dest.exists())
        with self.assertRaises(ValueError): bundle.unpack(self.path, '0'*64, self.dest)
        self.assertFalse(self.dest.exists())

    def test_failed_partial_pack_and_lost_ack_preserve_output(self):
        actual = bundle.files.write_new
        def partial(path, raw):
            actual(path, raw[:40]); raise OSError('PRIVATE')
        with patch.object(bundle.files, 'write_new', side_effect=partial), self.assertRaises(OSError): self.pack()
        self.assertEqual(self.path.read_bytes(), self.raw[:40])
        self.path.unlink()
        def lost(path, raw):
            actual(path, raw); raise OSError('PRIVATE')
        with patch.object(bundle.files, 'write_new', side_effect=lost), self.assertRaises(OSError): self.pack()
        self.assertTrue(bundle.verify(self.path, self.pin)['bundle_integrity_verified'])
        self.assertNotIn('created', bundle.verify(self.path, self.pin))

    def test_unpack_second_write_failure_leaves_first_and_partial_second(self):
        self.pack(); actual = bundle.files.write_new; calls = []
        def fail(path, raw):
            calls.append(path)
            actual(path, raw if len(calls) == 1 else raw[:20])
            if len(calls) == 2: raise OSError('PRIVATE')
        with patch.object(bundle.files, 'write_new', side_effect=fail), self.assertRaises(OSError): self.unpack()
        self.assertEqual((self.dest/'01-task.json').read_bytes(), self.entries[0].raw)
        self.assertEqual((self.dest/'02-report.json').read_bytes(), self.entries[1].raw[:20])
        with self.assertRaises(ValueError): bundle.verify_directory(self.path, self.pin, self.dest)
        with self.assertRaises(FileExistsError): self.unpack()

    def test_silent_short_write_and_fsync_failure_are_detected(self):
        actual = bundle.files.write_new
        with patch.object(bundle.files, 'write_new', side_effect=lambda p,r: actual(p,r[:20])), self.assertRaises(ValueError):
            self.pack()
        self.assertEqual(self.path.read_bytes(), self.raw[:20]); self.path.unlink()
        with patch.object(bundle.files.os, 'fsync', side_effect=OSError('PRIVATE')), self.assertRaises(OSError): self.pack()
        self.assertTrue(self.path.exists())

    def test_pack_refuses_source_change_during_write(self):
        actual = bundle.files.write_new
        def change(path, raw):
            actual(path, raw); self.task_path.write_bytes(self.entries[0].raw+b'x')
        with patch.object(bundle.files, 'write_new', side_effect=change), self.assertRaises(ValueError): self.pack()
        self.assertTrue(self.path.exists())

    def test_unpack_refuses_bundle_change_after_writes(self):
        self.pack(); actual = bundle.files.write_new
        def change(path, raw):
            actual(path, raw); self.path.write_bytes(self.raw+b'x')
        with patch.object(bundle.files, 'write_new', side_effect=change), self.assertRaises(ValueError): self.unpack()
        self.assertEqual(len(list(self.dest.iterdir())), 2)

    def test_output_same_byte_replacement_between_writes_is_rejected(self):
        self.pack(); actual = bundle.files.write_new
        def change(path, raw):
            actual(path, raw)
            if path.name == '02-report.json':
                first = self.dest/'01-task.json'; original = first.read_bytes()
                first.rename(self.root/'held'); first.write_bytes(original)
        with patch.object(bundle.files, 'write_new', side_effect=change), self.assertRaises(ValueError): self.unpack()

    def test_late_output_change_during_final_bundle_read_is_refused(self):
        self.pack(); actual = bundle.unchanged; armed = []
        def change(snapshot):
            actual(snapshot)
            target = self.dest/'01-task.json'
            if target.exists():
                armed.append(True); raw = target.read_bytes(); target.rename(self.root/'held'); target.write_bytes(raw)
        with patch.object(bundle, 'unchanged', side_effect=change), self.assertRaises(ValueError): self.unpack()
        self.assertEqual(armed, [True])

    def test_directory_verification_rejects_extra_missing_and_wrong_case_names(self):
        self.pack(); self.unpack()
        extra = self.dest/'EXTRA'; extra.write_bytes(b'x')
        with self.assertRaises(ValueError): bundle.verify_directory(self.path,self.pin,self.dest)
        extra.unlink(); path=self.dest/'01-task.json'; path.rename(self.root/'held')
        with self.assertRaises(ValueError): bundle.verify_directory(self.path,self.pin,self.dest)
        (self.root/'held').rename(self.dest/'01-TASK.json')
        with self.assertRaises(ValueError): bundle.verify_directory(self.path,self.pin,self.dest)

    def test_bundle_replacement_during_last_directory_check_is_refused(self):
        self.pack(); self.unpack()
        actual = bundle.directory_unchanged
        calls = []
        def change(directory, captured):
            actual(directory, captured); calls.append(True)
            if len(calls) == 2:
                self.path.rename(self.root/'held'); self.path.write_bytes(self.raw)
        with patch.object(bundle, 'directory_unchanged', side_effect=change):
            with self.assertRaises(ValueError):
                bundle.verify_directory(self.path, self.pin, self.dest)
        self.assertEqual(len(calls), 2)

    def test_same_byte_bundle_replacement_detected(self):
        self.pack(); snapshot=bundle.load(self.path,self.pin)
        self.path.rename(self.root/'held');self.path.write_bytes(self.raw)
        with self.assertRaises(ValueError):bundle.unchanged(snapshot)

    def test_hardlinks_rejected_for_source_bundle_and_restored_file(self):
        alias=self.root/'alias';os.link(self.task_path,alias)
        with self.assertRaises(ValueError):self.pack()
        alias.unlink();self.pack();os.link(self.path,alias)
        with self.assertRaises(ValueError):bundle.verify(self.path,self.pin)
        alias.unlink();self.unpack();os.link(self.dest/'01-task.json',alias)
        with self.assertRaises(ValueError):bundle.verify_directory(self.path,self.pin,self.dest)

    @unittest.skipUnless(os.name=='posix','POSIX symlink/FIFO fixtures')
    def test_symlink_ancestor_dangling_destination_and_fifo_rejected(self):
        self.pack(); parent=self.root/'alias';parent.symlink_to(self.root,target_is_directory=True)
        with self.assertRaises(ValueError):bundle.unpack(self.path,self.pin,parent/'new')
        self.dest.symlink_to(self.root/'missing',target_is_directory=True)
        with self.assertRaises(FileExistsError):self.unpack()
        self.path.unlink();os.mkfifo(self.path)
        with self.assertRaises(ValueError):bundle.verify(self.path,self.pin)

    def test_generated_names_are_not_user_paths(self):
        for i, kind in ((True,'task'),(-1,'task'),(32,'report'),(0,'../escape'),(0,None)):
            with self.assertRaises(ValueError):bundle.filename(i,kind)
        self.assertEqual(bundle.filename(31,'report'),'32-report.json')

    def test_no_query_or_backend_or_ledger_access(self):
        with patch.object(subprocess,'Popen',side_effect=AssertionError('native')), \
                patch.object(bundle.task,'run_request',side_effect=AssertionError('query')), \
                patch.object(bundle.task.once.single.ledger,'archive_snapshot',side_effect=AssertionError('ledger')):
            self.pack();bundle.verify(self.path,self.pin);self.unpack();bundle.verify_directory(self.path,self.pin,self.dest)

    def command(self, op):
        args=['--no-real-funds',op]
        if op=='pack':
            for s in self.sources:args += ['--entry',s.kind,str(s.path),s.sha256]
            args += ['--destination',str(self.path)]
        else:
            args += ['--bundle',str(self.path),'--bundle-sha256',self.pin]
            if op != 'verify':args += ['--destination',str(self.dest)]
        return args

    def test_real_cli_lifecycle_unicode_and_legacy_stdout(self):
        self.path=self.root/'证据 包.json';self.dest=self.root/'还原 目录'
        for op in ('pack','verify','unpack','verify-directory'):
            p=subprocess.run([sys.executable,'-B',bundle.__file__,*self.command(op)],capture_output=True,timeout=15,
                             env={**os.environ,'PYTHONIOENCODING':'cp1252','PYTHONUTF8':'0'})
            self.assertEqual(p.returncode,0,p.stderr);self.assertFalse(json.loads(p.stdout)['execution_performed'])
            self.assertNotIn(str(self.root).encode(),p.stdout+p.stderr)

    def test_cli_limits_syntax_and_failure_output(self):
        args=self.command('pack');more=[]
        for i in range(33):more += ['--entry','task',str(self.task_path),f'{i:064x}']
        for cmd in (['--secret','PRIVATE'],['--no-real-f'],['--no-real-funds','pack',*more,'--destination',str(self.path)]):
            p=subprocess.run([sys.executable,'-B',bundle.__file__,*cmd],capture_output=True,timeout=10)
            self.assertEqual(p.returncode,64);self.assertNotIn(b'PRIVATE',p.stdout+p.stderr)
        for failure in (OSError('PRIVATE'),KeyboardInterrupt('PRIVATE')):
            out,err=io.StringIO(),io.StringIO()
            with patch.object(bundle,'pack',side_effect=failure),contextlib.redirect_stdout(out),contextlib.redirect_stderr(err):
                code=bundle.main(args)
            self.assertEqual(code,130 if isinstance(failure,KeyboardInterrupt) else 1)
            self.assertEqual(out.getvalue(),'');self.assertNotIn('PRIVATE',err.getvalue())


if __name__=='__main__':unittest.main()
