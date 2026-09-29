"""Public framing/CLI refusal only. No successful native verifier substitute."""
from dataclasses import replace
import contextlib
import hashlib
import io
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
import ledger_transaction_batch as batch
from test_ledger_transaction_lookup import archive, frame


class BatchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='zevune-batch-tests-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.journal = self.root / 'journal'
        self.a, self.b = (hashlib.sha256(raw).hexdigest() for raw in (b'inert-a', b'inert-b'))
        self.pin, self.header = archive(
            self.journal, [frame(1, [b'inert-a']) + frame(2, [b'inert-b'])], 2)
        backend = Path(sys.executable).resolve()
        self.values = dict(journal=str(self.journal), checkpoint=self.pin.encoded, genesis_sha256='d' * 64,
                           backend=str(backend), backend_sha256=hashlib.sha256(backend.read_bytes()).hexdigest(),
                           txids=[self.b, '0' * 64, self.a])
        self.intent = batch.prepare(self.values)
        self.captured = batch.single.ledger.archive_snapshot(self.journal, self.pin)
        self.before = self.inventory()

    def inventory(self):
        return {p.name: p.read_bytes() for p in self.journal.iterdir()}

    def scans(self, intent=None, deadline=None):
        return batch.scan_requests(intent or self.intent, self.pin, self.captured, self.header,
                                   time.monotonic() + 10 if deadline is None else deadline)

    def args(self, values=None):
        values = self.values if values is None else values
        args = ['--no-real-funds']
        for key in batch.COMMON_FIELDS:
            args.extend(['--' + key.replace('_', '-'), values[key]])
        for txid in values['txids']:
            args.extend(['--txid', txid])
        return args

    def test_order_and_immutable_request_are_preserved(self):
        self.assertEqual(self.intent.txids, (self.b, '0' * 64, self.a))
        self.assertEqual(self.intent.source.txid, self.b)
        self.values['txids'][0] = '1' * 64
        self.assertEqual(self.intent.txids[0], self.b)
        with self.assertRaises(AttributeError):
            self.intent.txids = ()

    def test_one_and_maximum_count_are_validated_before_io(self):
        with patch.object(batch.single.view, '_chain', side_effect=AssertionError('no IO')):
            for count in (1, batch.MAX_TXIDS):
                ids = [f'{i:064x}' for i in range(count)]
                self.assertEqual(batch.prepare(dict(self.values, txids=ids)).txids, tuple(ids))

    def test_invalid_id_collections_and_duplicates_are_rejected(self):
        invalid = ([], ['0' * 64] * 2, [f'{i:064x}' for i in range(33)], '0' * 64,
                   None, True, {'0' * 64}, [self.a, 'A' * 64], [self.a, 'x'], [self.a, {}],
                   [self.a, False], [self.a, '0' * 65])
        with patch.object(batch.single.view, '_chain', side_effect=AssertionError('no IO')):
            for ids in invalid:
                with self.subTest(ids=repr(ids)[:80]), self.assertRaises(ValueError):
                    batch.prepare(dict(self.values, txids=ids))

    def test_all_common_inputs_rejected_before_io(self):
        with patch.object(batch.single.view, '_chain', side_effect=AssertionError('no IO')):
            for key, value in (('journal', 'relative'), ('backend', '/a/../b'), ('backend', None),
                               ('backend_sha256', '0' * 64), ('genesis_sha256', '0' * 64),
                               ('checkpoint', 'latest'), ('journal', str(self.root) + '\u202e'),
                               ('backend', '/a/' + '中' * 1500)):
                with self.subTest(key=key), self.assertRaises(ValueError):
                    batch.lookup_batch(batch.prepare(dict(self.values, **{key: value})))
            for values in ({}, dict(self.values, extra=1), None):
                with self.assertRaises(ValueError):
                    batch.prepare(values)

    def test_forged_nested_intent_rejected_before_io(self):
        bad = (None, replace(self.intent, source=None), replace(self.intent, txids=[]),
               replace(self.intent, txids=()), replace(self.intent, source=replace(self.intent.source, txid=self.a)))
        with patch.object(batch.single.view, '_chain', side_effect=AssertionError('no IO')):
            for intent in bad:
                with self.assertRaises(ValueError):
                    batch.lookup_batch(intent)

    def test_framing_scans_return_ordered_matches_and_absence_without_authority(self):
        results = self.scans()
        self.assertIs(type(results), tuple)
        self.assertEqual([row.match.height if row.match else None for row in results], [2, None, 1])
        self.assertTrue(all((row.records, row.transactions) == (2, 2) for row in results))
        self.assertTrue(all(not hasattr(row, 'ledger_replayed') for row in results))
        self.assertEqual(self.inventory(), self.before)

    def test_32_public_scans_reuse_exact_deadline_and_capture(self):
        intent = batch.prepare(dict(self.values, txids=[f'{i:064x}' for i in range(32)]))
        deadline = time.monotonic() + 10
        with patch.object(batch.single, 'scan_archive', wraps=batch.single.scan_archive) as scan:
            results = self.scans(intent, deadline)
        self.assertEqual(len(results), 32)
        self.assertEqual(scan.call_count, 32)
        for call in scan.call_args_list:
            self.assertIs(call.args[2], self.captured)
            self.assertEqual(call.args[-1], deadline)
        self.assertEqual([call.args[0].txid for call in scan.call_args_list], list(intent.txids))

    def test_found_first_does_not_skip_damaged_tail(self):
        path = self.journal / '00000000.journal'
        raw = path.read_bytes()
        path.write_bytes(raw[:-1] + bytes([raw[-1] ^ 1]))
        self.captured = batch.single.ledger.archive_snapshot(self.journal, self.pin)
        intent = batch.prepare(dict(self.values, txids=[self.a]))
        with self.assertRaises(ValueError):
            self.scans(intent)

    def test_later_scan_failure_never_returns_completed_prefix(self):
        actual = batch.single.scan_archive
        count = []
        def changed(*args):
            result = actual(*args)
            count.append(args[0].txid)
            if len(count) == 1:
                path = self.journal / '00000000.journal'
                path.write_bytes(path.read_bytes() + b'x')
            return result
        with patch.object(batch.single, 'scan_archive', side_effect=changed):
            with self.assertRaises(ValueError):
                self.scans()
        self.assertEqual(count, [self.b])

    def test_independent_layout_is_rechecked_per_id(self):
        bad = replace(self.pin, encoded=self.pin.encoded[:-64] + 'e' * 64)
        with self.assertRaisesRegex(ValueError, 'layout'):
            batch.scan_requests(self.intent, bad, self.captured, self.header, time.monotonic() + 10)

    def test_native_rejection_prevents_any_scan_or_retry(self):
        with patch.object(batch.single.checked.RecoveryBackend, '_run', side_effect=RuntimeError('refused')) as native, \
                patch.object(batch, 'scan_requests', side_effect=AssertionError('no unverified scan')):
            with self.assertRaises(RuntimeError):
                batch.lookup_batch(self.intent)
        self.assertEqual(native.call_count, 1)
        self.assertEqual(native.call_args.args[0][0], 'verify-active')
        self.assertEqual(self.inventory(), self.before)

    def test_malformed_native_success_fields_are_rejected(self):
        for reply in (None, {}, {'replay_verified': True}):
            with patch.object(batch.single.checked.RecoveryBackend, '_run', return_value=reply), \
                    patch.object(batch, 'scan_requests', side_effect=AssertionError('unverified scan')):
                with self.assertRaises(ValueError):
                    batch.lookup_batch(self.intent)

    def test_expired_budget_does_not_launch_or_continue(self):
        with patch.object(batch, 'BATCH_SECONDS', -1), \
                patch.object(batch.single.checked.RecoveryBackend, '_run', side_effect=AssertionError('late launch')):
            with self.assertRaisesRegex(ValueError, 'deadline'):
                batch.lookup_batch(self.intent)
        with self.assertRaisesRegex(ValueError, 'deadline'):
            self.scans(deadline=time.monotonic() - 1)

    def test_wrong_domain_or_backend_digest_never_starts_process(self):
        with patch.object(subprocess, 'Popen', side_effect=AssertionError('invalid process')):
            for key, value in (('genesis_sha256', 'e' * 64), ('backend_sha256', 'a' * 64)):
                with self.assertRaises((ValueError, RuntimeError)):
                    batch.lookup_batch(batch.prepare(dict(self.values, **{key: value})))

    def test_hardlinked_backend_is_not_relaxed_for_batch(self):
        path = self.root / ('backend.exe' if os.name == 'nt' else 'backend')
        shutil.copy2(self.intent.source.backend, path)
        os.link(path, self.root / 'backend-alias')
        with patch.object(subprocess, 'Popen', side_effect=AssertionError('linked process')) as spawn:
            with self.assertRaises((ValueError, RuntimeError)):
                batch.lookup_batch(batch.prepare(dict(self.values, backend=str(path))))
        self.assertEqual(spawn.call_count, 0)

    def test_real_interpreter_is_not_an_accepting_backend(self):
        with self.assertRaises((ValueError, RuntimeError)):
            batch.lookup_batch(self.intent)
        self.assertEqual(self.inventory(), self.before)

    def test_cli_failure_and_interrupt_do_not_emit_partial_batch(self):
        for error in (ValueError('PRIVATE'), RuntimeError('PRIVATE'), OSError('PRIVATE'),
                      subprocess.TimeoutExpired(['PRIVATE'], 1), KeyboardInterrupt('PRIVATE')):
            out, err = io.StringIO(), io.StringIO()
            with patch.object(batch, 'lookup_batch', side_effect=error), \
                    contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                result = batch.main(self.args())
            self.assertEqual(result, 130 if isinstance(error, KeyboardInterrupt) else 1)
            self.assertEqual(out.getvalue(), '')
            self.assertNotIn('PRIVATE', err.getvalue())

    def test_cli_limit_rejects_the_33rd_argument_before_io(self):
        out, err = io.StringIO(), io.StringIO()
        values = dict(self.values, txids=[f'{i:064x}' for i in range(33)])
        with patch.object(batch, 'lookup_batch', side_effect=AssertionError('too many')), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), self.assertRaises(SystemExit) as exit:
            batch.main(self.args(values))
        self.assertEqual(exit.exception.code, 64)
        self.assertEqual(out.getvalue(), '')
        self.assertNotIn(values['journal'], err.getvalue())

    def test_real_cli_help_refusal_duplicate_and_syntax(self):
        examples = ((['--help'], 0), (self.args(), 1), (self.args(dict(self.values, txids=[self.a, self.a])), 1),
                    (['--secret', 'PRIVATE'], 64), (['--no-real-f', '--txid', self.a], 64))
        for args, expected in examples:
            process = subprocess.run([sys.executable, '-B', batch.__file__, *args], capture_output=True, timeout=10)
            self.assertEqual(process.returncode, expected)
            self.assertNotIn(b'PRIVATE', process.stderr)
            if expected:
                self.assertEqual(process.stdout, b'')
        self.assertEqual(self.inventory(), self.before)

    def test_text_render_is_only_pure_presentation(self):
        result = dict(query_count=1, included_count=0, absent_count=1, checkpoint_height=2,
                      results=[dict(txid=self.a, occurrence=None)])
        text = batch.render(result)
        self.assertIn('不能据此重试付款', text)
        self.assertIn('不是付款凭证', text)
        self.assertIn(self.a, text)


if __name__ == '__main__':
    unittest.main()
