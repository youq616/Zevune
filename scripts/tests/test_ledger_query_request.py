"""Public task-file round trips and refusals, never a successful native double."""
from dataclasses import replace
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
import ledger_query_request as task
from test_ledger_transaction_lookup import archive


class RequestTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='zevune-query-request-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.journal = self.root / 'ledger'
        self.pin, _ = archive(self.journal)
        self.backend = Path(sys.executable).resolve()  # Real executable that refuses recovery commands.
        self.request = task.prepare(self.pin.encoded, 'd' * 64, hashlib.sha256(self.backend.read_bytes()).hexdigest(),
                                    ['b' * 64, '0' * 64, 'a' * 64])
        self.path = self.root / 'request.json'
        self.raw = task.encode(self.request)
        self.sha = hashlib.sha256(self.raw).hexdigest()

    def create(self):
        return task.create(self.request, self.path)

    def execute(self):
        return task.run_request(self.path, self.sha, self.journal, self.backend)

    def test_canonical_roundtrip_preserves_pins_and_caller_order(self):
        self.assertEqual(task.decode(self.raw, self.sha), self.request)
        self.assertEqual(self.raw, task.files.canonical(self.request.document()))
        self.assertEqual(task.decode(self.raw, self.sha).txids, ('b' * 64, '0' * 64, 'a' * 64))
        self.assertEqual(set(json.loads(self.raw)), task.FIELDS)
        self.assertNotIn(str(self.root).encode(), self.raw)
        self.assertNotIn(str(self.backend).encode(), self.raw)
        with self.assertRaises(AttributeError):
            self.request.checkpoint = 'x'

    def test_mutating_original_ids_does_not_change_frozen_request(self):
        ids = ['b' * 64, 'a' * 64]
        request = task.prepare(self.pin.encoded, 'd' * 64, 'b' * 64, ids)
        ids.reverse()
        self.assertEqual(request.txids, ('b' * 64, 'a' * 64))

    def test_one_and_32_ids_are_bounded(self):
        for count in (1, 32):
            request = task.prepare(self.pin.encoded, 'd' * 64, 'b' * 64, [f'{i:064x}' for i in range(count)])
            raw = task.encode(request)
            self.assertLess(len(raw), task.MAX_REQUEST_BYTES)
            self.assertEqual(task.decode(raw, hashlib.sha256(raw).hexdigest()), request)

    def test_invalid_ids_pins_and_object_types_refused_without_io(self):
        with patch.object(task.view, '_chain', side_effect=AssertionError('no IO')):
            for ids in ([], ['0' * 64] * 2, [f'{i:064x}' for i in range(33)], None, {}, '0' * 64,
                        ['A' * 64], [False], ['0' * 63], ['0' * 64 + '\n']):
                with self.subTest(ids=repr(ids)[:40]), self.assertRaises(ValueError):
                    task.prepare(self.pin.encoded, 'd' * 64, 'b' * 64, ids)
            for pos, value in ((0, 'latest'), (0, None), (1, '0' * 64), (2, '0' * 64), (2, 'B' * 64), (1, [])):
                args = [self.pin.encoded, 'd' * 64, 'b' * 64, ['a' * 64]]
                args[pos] = value
                with self.assertRaises(ValueError):
                    task.prepare(*args)
            for request in (None, {}, replace(self.request, txids=[]), replace(self.request, backend_sha256='x')):
                with self.assertRaises(ValueError):
                    task.create(request, self.path)
        self.assertFalse(self.path.exists())

    def test_digest_is_checked_before_json_decode(self):
        with patch.object(task.json, 'loads', side_effect=AssertionError('untrusted JSON decode')):
            with self.assertRaises(ValueError):
                task.decode(self.raw, '0' * 64)
        for digest in (None, 'A' * 64, '', False):
            with patch.object(task.view, '_chain', side_effect=AssertionError('no IO')), self.assertRaises(ValueError):
                task.load(self.path, digest)

    def test_every_field_required_and_embedded_paths_are_rejected(self):
        data = self.request.document()
        for name in data:
            wrong = dict(data); del wrong[name]
            self.reject_document(wrong)
        for key in ('journal', 'backend', 'shell', 'password', 'destination', 'auto_run', 'deadline'):
            self.reject_document(dict(data, **{key: 'UNTRUSTED'}))

    def reject_document(self, document):
        raw = task.files.canonical(document)
        with self.assertRaises(ValueError):
            task.decode(raw, hashlib.sha256(raw).hexdigest())

    def test_unknown_profiles_true_flags_and_wrong_types_are_refused(self):
        for key, value in (('format', 'zevune-ledger-query-request-2'), ('query_profile', 'batch'),
                           ('query_profile', 'zevune-ledger-transaction-batch-1'), ('real_funds_allowed', 0),
                           ('real_funds_allowed', True), ('real_funds_allowed', 'false'),
                           ('txids', {}), ('backend_sha256', False)):
            self.reject_document(dict(self.request.document(), **{key: value}))

    def test_rehashed_noncanonical_duplicate_bom_and_nonfinite_rejected(self):
        cases = [self.raw + b' ', b'\xef\xbb\xbf' + self.raw, json.dumps(self.request.document(), indent=2).encode(),
                 self.raw[:-2] + b',"real_funds_allowed":false}\n', b'null\n', b'[]\n', b'\xff',
                 self.raw.replace(b'false', b'NaN'), b'[' * 3000 + b']' * 3000]
        for raw in cases:
            with self.subTest(size=len(raw)), self.assertRaises((ValueError, RecursionError)):
                task.decode(raw, hashlib.sha256(raw).hexdigest())

    def test_create_inspect_do_not_execute_backend_or_touch_ledger(self):
        before = {p.name: p.read_bytes() for p in self.journal.iterdir()}
        with patch.object(subprocess, 'Popen', side_effect=AssertionError('no process')), \
                patch.object(task.once, 'lookup_batch_once', side_effect=AssertionError('no query')):
            created = self.create()
            result = task.inspect_request(self.path, self.sha)
        self.assertEqual(created['request_sha256'], self.sha)
        self.assertTrue(created['created'])
        self.assertFalse(created['execution_performed'])
        self.assertFalse(result['execution_performed'])
        self.assertFalse(result['signature_verified'])
        self.assertEqual(result['request'], self.request.document())
        self.assertEqual(self.path.read_bytes(), self.raw)
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.journal.iterdir()})

    def test_existing_targets_empty_or_populated_never_overwritten(self):
        for raw in (b'', b'EXISTING_FILE'):
            self.path.write_bytes(raw)
            with self.assertRaises(ValueError):
                self.create()
            self.assertEqual(self.path.read_bytes(), raw)
            self.path.unlink()
        self.path.mkdir()
        with self.assertRaises(ValueError):
            self.create()
        self.assertEqual(list(self.path.iterdir()), [])

    def test_invalid_paths_and_missing_parent_do_not_create(self):
        for value in (Path('relative'), self.root / '..' / 'escape', str(self.path), self.root / ('中' * 1400),
                      self.root / 'line\nfeed', self.root / 'a\u202eb'):
            with self.subTest(path=str(value)[:80]), self.assertRaises(ValueError):
                task.create(self.request, value)
        with self.assertRaises(OSError):
            task.create(self.request, self.root / 'missing' / 'request.json')
        self.assertFalse((self.root / 'missing').exists())

    def test_partial_write_and_fsync_failure_retained_without_success(self):
        real = task.files.write_new
        def broken(path, raw):
            real(path, raw[:20])
            raise OSError('PRIVATE_WRITE')
        with patch.object(task.files, 'write_new', side_effect=broken), self.assertRaises(OSError):
            self.create()
        self.assertEqual(self.path.read_bytes(), self.raw[:20])
        self.path.unlink()
        with patch.object(task.files.os, 'fsync', side_effect=OSError('PRIVATE_SYNC')), self.assertRaises(OSError):
            self.create()
        self.assertTrue(self.path.exists())
        with self.assertRaises(ValueError):
            self.create()

    def test_silent_short_write_is_detected_by_exact_reread(self):
        real = task.files.write_new
        with patch.object(task.files, 'write_new', side_effect=lambda p, b: real(p, b[:20])):
            with self.assertRaises(ValueError):
                self.create()
        self.assertEqual(self.path.read_bytes(), self.raw[:20])

    def test_full_copy_lost_reply_is_failure_but_independent_inspect_possible(self):
        real = task.files.write_new
        def lost(path, raw):
            real(path, raw)
            raise OSError('PRIVATE_LOST_REPLY')
        with patch.object(task.files, 'write_new', side_effect=lost), self.assertRaises(OSError):
            self.create()
        self.assertTrue(task.inspect_request(self.path, self.sha)['request_integrity_verified'])
        self.assertNotIn('created', task.inspect_request(self.path, self.sha))

    def test_hardlinks_oversize_and_non_regular_requests_refused(self):
        self.create()
        os.link(self.path, self.root / 'alias')
        with self.assertRaises(ValueError):
            task.load(self.path, self.sha)
        (self.root / 'alias').unlink()
        self.path.write_bytes(b' ' * (task.MAX_REQUEST_BYTES + 1))
        with self.assertRaises(ValueError):
            task.load(self.path, self.sha)
        self.path.unlink(); self.path.mkdir()
        with self.assertRaises(ValueError):
            task.load(self.path, self.sha)

    @unittest.skipUnless(os.name == 'posix', 'POSIX symlink/FIFO fixture')
    def test_linked_parent_file_and_fifo_are_refused(self):
        self.create()
        link = self.root / 'linked'; link.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(ValueError):
            task.load(link / self.path.name, self.sha)
        alias = self.root / 'alias'; alias.symlink_to(self.path)
        with self.assertRaises(ValueError):
            task.load(alias, self.sha)
        self.path.unlink(); os.mkfifo(self.path)
        with self.assertRaises(ValueError):
            task.load(self.path, self.sha)

    def test_request_replacement_with_same_bytes_is_rejected(self):
        self.create()
        captured = task.load(self.path, self.sha)
        self.path.rename(self.root / 'old'); self.path.write_bytes(self.raw)
        with self.assertRaises(ValueError):
            task.unchanged(captured)

    def test_parent_replacement_is_detected(self):
        parent = self.root / 'tasks'; parent.mkdir(); path = parent / 'q.json'
        task.create(self.request, path)
        captured = task.load(path, self.sha)
        parent.rename(self.root / 'old-tasks'); parent.mkdir(); path.write_bytes(self.raw)
        with self.assertRaises(ValueError):
            task.unchanged(captured)

    def test_wrong_digest_and_changed_task_do_not_start_query(self):
        self.create()
        with patch.object(task.once, 'lookup_batch_once', side_effect=AssertionError('no execution')):
            with self.assertRaises(ValueError):
                task.run_request(self.path, '0' * 64, self.journal, self.backend)
            real = task.load
            def changed(*args):
                result = real(*args)
                self.path.write_bytes(self.raw + b'x')
                return result
            with patch.object(task, 'load', side_effect=changed), self.assertRaises(ValueError):
                self.execute()

    def test_explicit_run_passes_exact_request_and_only_local_paths_once(self):
        self.create()
        with patch.object(task.once, 'lookup_batch_once', side_effect=RuntimeError('refusal only')) as query:
            with self.assertRaises(RuntimeError):
                self.execute()
        self.assertEqual(query.call_count, 1)
        intent = query.call_args.args[0]
        self.assertEqual(intent.txids, self.request.txids)
        self.assertEqual(intent.source.checkpoint, self.request.checkpoint)
        self.assertEqual(intent.source.backend_sha256, self.request.backend_sha256)
        self.assertEqual(intent.source.backend, self.backend)
        self.assertEqual(intent.source.journal, self.journal)
        self.assertEqual(self.path.read_bytes(), self.raw)

    def test_real_interpreter_refuses_and_never_yields_query_success(self):
        self.create()
        with self.assertRaises((ValueError, RuntimeError)):
            self.execute()
        self.assertEqual(self.path.read_bytes(), self.raw)

    def test_local_path_syntax_rejected_before_request_read(self):
        with patch.object(task, 'load', side_effect=AssertionError('no reads')):
            for path, journal, backend in ((Path('relative'), self.journal, self.backend),
                                           (self.path, Path('relative'), self.backend),
                                           (self.path, self.journal, 'not-a-path')):
                with self.assertRaises(ValueError):
                    task.run_request(path, self.sha, journal, backend)

    def cli(self, tail):
        return subprocess.run([sys.executable, '-B', task.__file__, '--no-real-funds', *tail],
                              capture_output=True, timeout=15)

    def test_real_cli_create_inspect_run_refusal_and_no_cache(self):
        made = self.cli(['create', '--destination', str(self.path), '--checkpoint', self.request.checkpoint,
                         '--genesis-sha256', self.request.genesis_sha256, '--backend-sha256', self.request.backend_sha256,
                         '--txid', 'b' * 64, '--txid', '0' * 64, '--txid', 'a' * 64])
        self.assertEqual(made.returncode, 0, made.stderr)
        self.assertEqual(json.loads(made.stdout)['request_sha256'], self.sha)
        args = ['--request', str(self.path), '--request-sha256', self.sha]
        read = self.cli(['inspect', *args])
        self.assertEqual(read.returncode, 0)
        self.assertFalse(json.loads(read.stdout)['execution_performed'])
        run = self.cli(['run', *args, '--journal', str(self.journal), '--backend', str(self.backend)])
        self.assertEqual(run.returncode, 1)
        self.assertEqual(run.stdout, b'')
        self.assertNotIn(str(self.root).encode(), run.stderr)
        self.assertEqual(self.path.read_bytes(), self.raw)

    def test_cli_errors_and_interruption_are_fixed_no_success(self):
        self.create()
        args = ['--no-real-funds', 'run', '--request', str(self.path), '--request-sha256', self.sha,
                '--journal', str(self.journal), '--backend', str(self.backend)]
        for failure in (OSError('PRIVATE'), subprocess.TimeoutExpired(['PRIVATE'], 1), KeyboardInterrupt('PRIVATE')):
            out, err = io.StringIO(), io.StringIO()
            with patch.object(task, 'run_request', side_effect=failure), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = task.main(args)
            self.assertEqual(code, 130 if isinstance(failure, KeyboardInterrupt) else 1)
            self.assertEqual(out.getvalue(), '')
            self.assertNotIn('PRIVATE', err.getvalue())
        for args in (['--secret', 'PRIVATE'], ['inspect', '--request-sha', 'PRIVATE'], ['run']):
            process = self.cli(args)
            self.assertEqual(process.returncode, 64)
            self.assertNotIn(b'PRIVATE', process.stderr)

    def test_unicode_paths_and_task_does_not_include_machine_paths(self):
        self.path = self.root / '核查 任务.json'
        self.create()
        self.assertEqual(task.load(self.path, self.sha).request, self.request)
        self.assertEqual(self.path.read_bytes(), self.raw)


if __name__ == '__main__':
    unittest.main()
