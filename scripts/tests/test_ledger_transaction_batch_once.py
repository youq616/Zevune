"""Public-frame equivalence/counting and refusals only; not successful native replay."""
from dataclasses import replace
import contextlib
import hashlib
import io
import os
from pathlib import Path
import random
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ledger_transaction_batch_once as once
from test_ledger_transaction_lookup import archive, frame


class OnceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='zevune-once-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.journal = self.root / 'journal'
        self.raw = frame(1, [b'inert-a', b'inert-b']) + frame(2, [b'inert-c'])
        self.pin, self.header = archive(self.journal, [self.raw], 2)
        self.ids = [hashlib.sha256(x).hexdigest() for x in (b'inert-c', b'absent', b'inert-a', b'inert-b')]
        backend = Path(sys.executable).resolve()
        self.values = dict(journal=str(self.journal), checkpoint=self.pin.encoded, genesis_sha256='d' * 64,
                           backend=str(backend), backend_sha256=hashlib.sha256(backend.read_bytes()).hexdigest(),
                           txids=self.ids)
        self.intent = once.prepare(self.values)
        self.captured = once.single.ledger.archive_snapshot(self.journal, self.pin)
        self.before = {p.name: p.read_bytes() for p in self.journal.iterdir()}

    def scan(self, intent=None):
        return once.scan_once(intent or self.intent, self.pin, self.captured, self.header, time.monotonic() + 10)

    def args(self, values=None):
        values = self.values if values is None else values
        args = ['--no-real-funds']
        for key in once.batch.COMMON_FIELDS:
            args.extend(['--' + key.replace('_', '-'), values[key]])
        for txid in values['txids']:
            args.extend(['--txid', txid])
        return args

    def test_order_occurrences_and_absence_match_original_batch(self):
        actual = self.scan()
        expected = once.batch.scan_requests(self.intent, self.pin, self.captured, self.header, time.monotonic() + 10)
        self.assertEqual(actual, expected)
        self.assertEqual([r.match.height if r.match else None for r in actual], [2, None, 1, 1])
        self.assertEqual(actual[3].match.transaction_index, 1)
        self.assertEqual(actual[0].match.record_offset, len(frame(1, [b'inert-a', b'inert-b'])))
        self.assertTrue(all((r.records, r.transactions) == (2, 3) for r in actual))
        self.assertFalse(any(hasattr(r, 'ledger_replayed') for r in actual))
        self.assertEqual({p.name: p.read_bytes() for p in self.journal.iterdir()}, self.before)

    def test_one_to_32_ids_read_each_record_segment_only_once(self):
        for count in (1, 2, 16, 32):
            intent = once.prepare(dict(self.values, txids=[f'{i:064x}' for i in range(count)]))
            with patch.object(once.single.files, 'read_file', wraps=once.single.files.read_file) as read:
                actual = self.scan(intent)
            self.assertEqual(read.call_count, self.pin.segments)
            with patch.object(once.single.files, 'read_file', wraps=once.single.files.read_file) as old_read:
                expected = once.batch.scan_requests(intent, self.pin, self.captured, self.header, time.monotonic() + 10)
            self.assertEqual(old_read.call_count, count * self.pin.segments)
            self.assertEqual(actual, expected)

    def test_each_transaction_hashed_once_regardless_of_query_count(self):
        real = hashlib.sha256
        payloads = (b'inert-a', b'inert-b', b'inert-c')
        calls = []
        def counted(data=b'', *args, **kwargs):
            if bytes(data) in payloads:
                calls.append(bytes(data))
            return real(data, *args, **kwargs)
        with patch.object(once.single.hashlib, 'sha256', side_effect=counted):
            self.scan()
        self.assertEqual(calls, list(payloads))

    def test_reversing_caller_order_reverses_only_results(self):
        actual = self.scan(once.prepare(dict(self.values, txids=list(reversed(self.ids)))))
        self.assertEqual(actual, tuple(reversed(self.scan())))

    def test_deterministic_public_records_match_single_scans(self):
        rng = random.Random(937)
        data = [rng.randbytes(rng.randint(1, 100)) for _ in range(32)]
        raw = b''.join(frame(i + 1, data[i * 4:(i + 1) * 4]) for i in range(8))
        (self.journal / '00000000.journal').write_bytes(raw)
        # Framing comparison is deliberately independent of native authorization.
        ids = frozenset(hashlib.sha256(p).hexdigest() for p in data)
        height, count, matches, tip, size = once.single.scan_segment_many(raw, '00000000.journal', 0, None,
                                                                         ids, time.monotonic() + 10)
        self.assertEqual((height, count, len(matches)), (8, 32, 32))
        for txid in ids:
            single = once.single.scan_segment(raw, '00000000.journal', 0, None, txid, time.monotonic() + 10)
            self.assertEqual((height, count, matches[txid], tip, size), single)

    def test_every_truncated_frame_and_checksum_byte_damage_rejected(self):
        raw = frame(1, [b'inert-a', b'inert-b'])
        ids = frozenset(self.ids)
        for n in range(len(raw)):
            with self.subTest(length=n), self.assertRaises(ValueError):
                once.single.scan_segment_many(raw[:n], 's', 0, None, ids, time.monotonic() + 10)
        for n in range(4, len(raw)):
            broken = raw[:n] + bytes((raw[n] ^ 1,)) + raw[n + 1:]
            with self.subTest(byte=n), self.assertRaises(ValueError):
                once.single.scan_segment_many(broken, 's', 0, None, ids, time.monotonic() + 10)

    def test_all_requested_found_never_skips_damaged_tail(self):
        ids = frozenset((self.ids[2], self.ids[3]))
        first = frame(1, [b'inert-a', b'inert-b'])
        for tail in (b'x', frame(2)[:-1], frame(3), frame(2, base=b'z' * 32)):
            with self.subTest(size=len(tail)), self.assertRaises(ValueError):
                once.single.scan_segment_many(first + tail, 's', 0, None, ids, time.monotonic() + 10)

    def test_duplicate_requested_match_rejected_even_after_all_found(self):
        raw = frame(1, [b'inert-a', b'inert-b']) + frame(2, [b'inert-a'])
        with self.assertRaisesRegex(ValueError, 'ambiguous'):
            once.single.scan_segment_many(raw, 's', 0, None, frozenset(self.ids), time.monotonic() + 10)

    def test_shared_scanner_requires_strict_bounded_id_set(self):
        for ids in ((), set(self.ids), frozenset(), frozenset(['x']), frozenset([True]),
                    frozenset(f'{i:064x}' for i in range(33))):
            with self.subTest(ids=type(ids)), self.assertRaises(ValueError):
                once.single.scan_segment_many(self.raw, 's', 0, None, ids, time.monotonic() + 10)

    def test_layout_tip_count_and_identity_still_bound(self):
        for pin in (replace(self.pin, encoded=self.pin.encoded[:-64] + 'e' * 64),
                    replace(self.pin, height=3), replace(self.pin, app_hash='f' * 64)):
            with self.assertRaises(ValueError):
                once.scan_once(self.intent, pin, self.captured, self.header, time.monotonic() + 10)
        path = self.journal / '00000000.journal'
        path.rename(self.root / 'old'); path.write_bytes(self.raw)
        with self.assertRaises(ValueError):
            self.scan()

    def test_zero_record_archive_completes_with_no_matches(self):
        folder = self.root / 'zero'
        pin, header = archive(folder)
        intent = once.prepare(dict(self.values, journal=str(folder), checkpoint=pin.encoded))
        captured = once.single.ledger.archive_snapshot(folder, pin)
        result = once.scan_once(intent, pin, captured, header, time.monotonic() + 10)
        self.assertEqual(result, tuple(once.single.Scan(0, 0, None) for _ in self.ids))

    def test_real_segment_rotation_and_duplicate_across_segments(self):
        count = once.single.ledger.SEGMENT_BYTES // 150
        first = b''.join(frame(i) for i in range(1, count + 1))
        second = frame(count + 1, [b'inert-a', b'inert-b'])
        folder = self.root / 'rotated'
        pin, header = archive(folder, [first, second], count + 1)
        intent = once.prepare(dict(self.values, journal=str(folder), checkpoint=pin.encoded))
        capture = once.single.ledger.archive_snapshot(folder, pin)
        result = once.scan_once(intent, pin, capture, header, time.monotonic() + 10)
        self.assertEqual(result[2].match.segment, '00000001.journal')
        self.assertEqual(result[2].match.record_offset, 0)
        # Add target to first segment without changing canonical physical rotation.
        first = frame(1, [b'inert-a']) + b''.join(frame(i) for i in range(2, count + 1))
        duplicate = self.root / 'duplicate'
        pin, header = archive(duplicate, [first, second], count + 1)
        intent = once.prepare(dict(self.values, journal=str(duplicate), checkpoint=pin.encoded))
        capture = once.single.ledger.archive_snapshot(duplicate, pin)
        with self.assertRaisesRegex(ValueError, 'ambiguous'):
            once.scan_once(intent, pin, capture, header, time.monotonic() + 10)

    def test_early_rotation_remains_invalid(self):
        folder = self.root / 'early'
        pin, header = archive(folder, [frame(1), frame(2)], 2)
        intent = once.prepare(dict(self.values, journal=str(folder), checkpoint=pin.encoded))
        with self.assertRaisesRegex(ValueError, 'rotation'):
            once.scan_once(intent, pin, once.single.ledger.archive_snapshot(folder, pin), header,
                           time.monotonic() + 10)

    def test_one_absolute_deadline_for_all_segments(self):
        deadline = time.monotonic() + 10
        with patch.object(once.single, 'scan_segment_many', wraps=once.single.scan_segment_many) as scan:
            once.scan_once(self.intent, self.pin, self.captured, self.header, deadline)
        self.assertEqual([call.args[-1] for call in scan.call_args_list], [deadline] * self.pin.segments)
        with self.assertRaisesRegex(ValueError, 'deadline'):
            once.scan_once(self.intent, self.pin, self.captured, self.header, time.monotonic() - 1)

    def test_preflight_refusals_and_invalid_nested_intents_precede_io(self):
        with patch.object(once.single.view, '_chain', side_effect=AssertionError('no IO')):
            for ids in ([], [self.ids[0]] * 2, ['x'], [f'{i:064x}' for i in range(33)]):
                with self.assertRaises(ValueError): once.prepare(dict(self.values, txids=ids))
            for bad in (None, replace(self.intent, source=None), replace(self.intent, txids=[]),
                        replace(self.intent, source=replace(self.intent.source, txid='a' * 64))):
                with self.assertRaises(ValueError): once.lookup_batch_once(bad)

    def test_native_error_never_scans_or_retries(self):
        with patch.object(once.single.checked.RecoveryBackend, '_run', side_effect=RuntimeError('refused')) as call, \
                patch.object(once, 'scan_once', side_effect=AssertionError('unverified scan')):
            with self.assertRaises(RuntimeError): once.lookup_batch_once(self.intent)
        self.assertEqual(call.call_count, 1)
        self.assertEqual(call.call_args.args[0][0], 'verify-active')

    def test_malformed_native_success_is_not_authority(self):
        for reply in (None, {}, {'replay_verified': True}):
            with patch.object(once.single.checked.RecoveryBackend, '_run', return_value=reply), \
                    patch.object(once, 'scan_once', side_effect=AssertionError('unverified scan')):
                with self.assertRaises(ValueError): once.lookup_batch_once(self.intent)

    def test_expired_preflight_does_not_start_process(self):
        with patch.object(once, 'ONCE_SECONDS', -1), \
                patch.object(once.single.checked.RecoveryBackend, '_run', side_effect=AssertionError('expired')):
            with self.assertRaisesRegex(ValueError, 'deadline'): once.lookup_batch_once(self.intent)

    def test_wrong_domain_and_backend_digest_never_start_process(self):
        with patch.object(subprocess, 'Popen', side_effect=AssertionError('must not start')):
            for key in ('backend_sha256', 'genesis_sha256'):
                with self.assertRaises((ValueError, RuntimeError)):
                    once.lookup_batch_once(once.prepare(dict(self.values, **{key: 'e' * 64})))

    def test_hardlinked_backend_is_still_refused(self):
        path = self.root / ('native.exe' if os.name == 'nt' else 'native')
        shutil.copy2(self.intent.source.backend, path); os.link(path, self.root / 'alias')
        with patch.object(subprocess, 'Popen', side_effect=AssertionError('linked process')) as spawn:
            with self.assertRaises((ValueError, RuntimeError)):
                once.lookup_batch_once(once.prepare(dict(self.values, backend=str(path))))
        self.assertEqual(spawn.call_count, 0)

    def test_cli_failure_families_and_interrupt_never_emit_success(self):
        for error in (ValueError('PRIVATE'), OSError('PRIVATE'), subprocess.TimeoutExpired(['PRIVATE'], 1),
                      subprocess.CalledProcessError(1, ['PRIVATE']), KeyboardInterrupt('PRIVATE')):
            out, err = io.StringIO(), io.StringIO()
            with patch.object(once, 'lookup_batch_once', side_effect=error), \
                    contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = once.main(self.args())
            self.assertEqual(code, 130 if isinstance(error, KeyboardInterrupt) else 1)
            self.assertEqual(out.getvalue(), ''); self.assertNotIn('PRIVATE', err.getvalue())

    def test_real_cli_help_syntax_duplicates_limit_and_backend_refusal(self):
        examples = [(['--help'], 0), (['--secret', 'PRIVATE'], 64), (self.args(), 1),
                    (self.args(dict(self.values, txids=[self.ids[0]] * 2)), 1),
                    (self.args(dict(self.values, txids=[f'{i:064x}' for i in range(33)])), 64)]
        for args, code in examples:
            result = subprocess.run([sys.executable, '-B', once.__file__, *args], capture_output=True, timeout=10)
            self.assertEqual(result.returncode, code)
            self.assertNotIn(b'PRIVATE', result.stderr)
            if code: self.assertEqual(result.stdout, b'')
        self.assertEqual({p.name: p.read_bytes() for p in self.journal.iterdir()}, self.before)


if __name__ == '__main__':
    unittest.main()
