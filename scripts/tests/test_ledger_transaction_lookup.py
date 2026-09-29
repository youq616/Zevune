"""Public framing and refusal tests; never a successful substitute for native replay."""
from dataclasses import replace
import contextlib
import hashlib
import io
import os
import shutil
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ledger_transaction_lookup as lookup


def frame(height, transactions=(), base=b'a' * 32, result=b'a' * 32):
    # Synthetic public Record framing, not valid Orchard transactions or a ledger.
    body = b'ZVOBLK01' + height.to_bytes(8, 'big') + b'b' * 32 + base + result
    body += len(transactions).to_bytes(2, 'big')
    for tx in transactions:
        body += len(tx).to_bytes(4, 'big') + tx
    return len(body).to_bytes(4, 'big') + body + hashlib.sha256(body).digest()


def with_body(body):
    return len(body).to_bytes(4, 'big') + body + hashlib.sha256(body).digest()


def archive(root, segments=(), height=0, domain='d' * 64):
    root.mkdir()
    header = b'ZVOPOL03' + hashlib.sha256(b'zevune-orchard-lab-1').digest() + bytes.fromhex(domain) + bytes(4)
    (root / 'genesis').write_bytes(header)
    layout = hashlib.sha256(b'ZVARLY01' + len(header).to_bytes(4, 'big') + header + len(segments).to_bytes(4, 'big'))
    for i, raw in enumerate(segments):
        (root / f'{i:08}.journal').write_bytes(raw)
        layout.update(i.to_bytes(4, 'big') + len(raw).to_bytes(4, 'big') + raw)
    encoded = (b'ZVARCP01' + hashlib.sha256(header).digest() + height.to_bytes(8, 'big') + b'a' * 32
               + (len(header) + sum(map(len, segments))).to_bytes(8, 'big')
               + len(header).to_bytes(4, 'big') + len(segments).to_bytes(4, 'big') + layout.digest()).hex()
    return lookup.Checkpoint.parse(encoded), header


class SegmentTests(unittest.TestCase):
    def scan(self, raw, tx=b'inert target', height=0, previous=None):
        return lookup.scan_segment(raw, '00000000.journal', height, previous,
                                   hashlib.sha256(tx).hexdigest(), time.monotonic() + 10)

    def test_framing_only_exact_record_height_index_offset(self):
        first = frame(1, [b'not target'])
        answer = self.scan(first + frame(2, [b'another', b'inert target']))
        self.assertEqual(answer[0:2], (2, 3))
        self.assertEqual(answer[2], lookup.Occurrence(2, (b'b' * 32).hex(), 1, '00000000.journal', len(first), 12))
        self.assertFalse(hasattr(answer[2], 'ledger_replayed'))

    def test_absence_and_empty_block_are_not_inclusion(self):
        self.assertIsNone(self.scan(frame(1))[2])
        self.assertIsNone(self.scan(frame(1, [b'other']))[2])

    def test_byte_substring_is_not_a_transaction_match(self):
        self.assertIsNone(self.scan(frame(1, [b'prefix inert target suffix']))[2])

    def test_every_truncation_refused(self):
        raw = frame(1, [b'inert target'])
        for length in range(len(raw)):
            with self.subTest(length=length), self.assertRaises(ValueError):
                self.scan(raw[:length])

    def test_bad_tail_after_match_never_returns_early_success(self):
        first = frame(1, [b'inert target'])
        for tail in (b'x', frame(2)[:-1], bytes(150), frame(3)):
            with self.subTest(tail=len(tail)), self.assertRaises(ValueError):
                self.scan(first + tail)

    def test_bad_magic_checksum_record_extent_count_and_tx_extent(self):
        raw = frame(1, [b'test'])
        body = raw[4:-32]
        cases = [raw[:-1] + bytes([raw[-1] ^ 1]), b'\xff' * 4 + raw[4:],
                 with_body(b'XXXXXXXX' + body[8:]), with_body(body[:112] + (17).to_bytes(2, 'big') + body[114:]),
                 with_body(body[:114] + (lookup.MAX_TRANSACTION_BYTES + 1).to_bytes(4, 'big') + body[118:]),
                 with_body(body + b'x'), with_body(body[:114]), with_body(body[:116])]
        for value in cases:
            with self.subTest(length=len(value)), self.assertRaises(ValueError):
                self.scan(value)

    def test_maximum_record_and_transaction_count_boundaries(self):
        tx = b'x' * lookup.MAX_TRANSACTION_BYTES
        raw = frame(1, [tx[:-1] + bytes([i]) for i in range(16)])
        self.assertEqual(len(raw), lookup.MAX_RECORD_BYTES + 36)
        self.assertEqual(self.scan(raw)[1], 16)
        with self.assertRaises(ValueError):
            self.scan(frame(1, [b'x'] * 17))
        with self.assertRaises(ValueError):
            self.scan(frame(1, [tx + b'x']))

    def test_same_tx_twice_is_not_silently_one_occurrence(self):
        for raw in (frame(1, [b'inert target'] * 2), frame(1, [b'inert target']) + frame(2, [b'inert target'])):
            with self.assertRaisesRegex(ValueError, 'ambiguous'):
                self.scan(raw)

    def test_hash_chain_and_record_height_must_connect(self):
        with self.assertRaises(ValueError):
            self.scan(frame(1) + frame(2, base=b'z' * 32))
        with self.assertRaises(ValueError):
            self.scan(frame(2))
        with self.assertRaises(ValueError):
            self.scan(frame(2), height=1, previous=b'z' * 32)

    def test_bounded_segment_and_expired_budget(self):
        with self.assertRaises(ValueError):
            self.scan(b'x' * (lookup.ledger.SEGMENT_BYTES + 1))
        with self.assertRaises(ValueError):
            lookup.scan_segment(frame(1), 'test', 0, None, '0' * 64, time.monotonic() - 1)


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='lookup-archive-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.journal = self.root / 'journal'

    def setup_archive(self, segments=(), height=0):
        self.pin, self.header = archive(self.journal, segments, height)
        self.intent = lookup.Intent(self.journal, self.pin.encoded, 'd' * 64, hashlib.sha256(b'target').hexdigest(),
                                    Path(sys.executable).resolve(), 'b' * 64)
        self.captured = lookup.ledger.archive_snapshot(self.journal, self.pin)

    def scan(self):
        return lookup.scan_archive(self.intent, self.pin, self.captured, self.header, time.monotonic() + 10)

    def test_zero_record_archive_is_complete_public_scan_only(self):
        self.setup_archive()
        self.assertEqual(self.scan(), lookup.Scan(0, 0, None))

    def test_independent_layout_digest_is_required(self):
        self.setup_archive([frame(1, [b'target'])], 1)
        self.assertEqual(self.scan().match.height, 1)
        self.pin = replace(self.pin, encoded=self.pin.encoded[:-64] + 'e' * 64)
        with self.assertRaisesRegex(ValueError, 'layout'):
            self.scan()

    def test_record_count_and_final_hash_must_match_pin(self):
        self.setup_archive([frame(1, [b'target'])], 1)
        for pin in (replace(self.pin, height=2), replace(self.pin, app_hash='f' * 64)):
            with self.assertRaises(ValueError):
                lookup.scan_archive(self.intent, pin, self.captured, self.header, time.monotonic() + 10)

    def test_same_bytes_replacement_after_capture_is_refused(self):
        self.setup_archive([frame(1)], 1)
        p = self.journal / '00000000.journal'
        raw = p.read_bytes()
        p.rename(self.root / 'old')
        p.write_bytes(raw)
        with self.assertRaises(ValueError):
            self.scan()

    def test_noncanonical_early_rotation_refused(self):
        self.setup_archive([frame(1), frame(2)], 2)
        with self.assertRaisesRegex(ValueError, 'rotation'):
            self.scan()

    def test_real_segment_boundary_scan_and_match_in_second_segment(self):
        count = lookup.ledger.SEGMENT_BYTES // 150
        first = b''.join(frame(i) for i in range(1, count + 1))
        self.setup_archive([first, frame(count + 1, [b'target'])], count + 1)
        scan = self.scan()
        self.assertEqual(scan.records, count + 1)
        self.assertEqual(scan.match.segment, '00000001.journal')
        self.assertEqual(scan.match.record_offset, 0)


class BoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='lookup-boundary-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.pin, self.header = archive(self.root / 'journal')
        backend = Path(sys.executable).resolve()
        self.values = dict(journal=str(self.root / 'journal'), checkpoint=self.pin.encoded, genesis_sha256='d' * 64,
                           txid='0' * 64, backend=str(backend), backend_sha256=hashlib.sha256(backend.read_bytes()).hexdigest())
        self.intent = lookup.prepare(self.values)

    def args(self):
        return ['--no-real-funds', *sum((['--' + k.replace('_', '-'), v] for k, v in self.values.items()), [])]

    def test_all_input_refusals_precede_io(self):
        with patch.object(lookup.view, '_chain', side_effect=AssertionError('IO')):
            for name, value in (('journal', 'relative'), ('backend', '/a/../b'), ('backend', None),
                                ('txid', 'A' * 64), ('txid', True), ('checkpoint', 'latest'),
                                ('genesis_sha256', '0' * 64), ('backend_sha256', '0' * 64),
                                ('journal', str(self.root) + '\u202e'), ('backend', '/a/' + '中' * 1400)):
                with self.subTest(name=name), self.assertRaises(ValueError):
                    lookup.lookup(lookup.prepare(dict(self.values, **{name: value})))
            with self.assertRaises(ValueError):
                lookup.prepare(dict(self.values, extra=True))
            with self.assertRaises(ValueError):
                lookup.lookup(None)
            with self.assertRaises(ValueError):
                lookup.lookup(replace(self.intent, txid=None))

    def test_public_precheck_is_not_native_success_and_must_not_scan(self):
        with patch.object(lookup.checked.RecoveryBackend, '_run', side_effect=RuntimeError('refused')) as call, \
                patch.object(lookup, 'scan_archive', side_effect=AssertionError('unverified scan')):
            with self.assertRaises(RuntimeError):
                lookup.lookup(self.intent)
        self.assertEqual(call.call_count, 1)
        self.assertEqual(call.call_args.args[0], ['verify-active', '--no-real-funds', '--source',
                                                str(self.intent.journal), '--checkpoint', self.pin.encoded])

    def test_malformed_native_reply_is_not_authority(self):
        for reply in (None, {}, {'replay_verified': True}):
            with patch.object(lookup.checked.RecoveryBackend, '_run', return_value=reply), \
                    patch.object(lookup, 'scan_archive', side_effect=AssertionError('unverified scan')):
                with self.assertRaises(ValueError):
                    lookup.lookup(self.intent)

    def test_genesis_and_domain_substitution_refused_before_native(self):
        with patch.object(lookup.checked.RecoveryBackend, '_run', side_effect=AssertionError('must not launch')):
            with self.assertRaises(ValueError):
                lookup.lookup(replace(self.intent, genesis_sha256='c' * 64))
            (self.intent.journal / 'genesis').write_bytes(self.header[:-1] + b'x')
            with self.assertRaises(ValueError):
                lookup.lookup(self.intent)

    def test_timeout_cannot_restart_native_or_scan(self):
        with patch.object(lookup.checked.RecoveryBackend, '_run', side_effect=subprocess.TimeoutExpired('PRIVATE', 1)) as call:
            with self.assertRaises(subprocess.TimeoutExpired):
                lookup.lookup(self.intent)
        self.assertEqual(call.call_count, 1)
        with patch.object(lookup, 'LOOKUP_SECONDS', -1), \
                patch.object(lookup.checked.RecoveryBackend, '_run', side_effect=AssertionError('expired launch')):
            with self.assertRaises(ValueError):
                lookup.lookup(self.intent)

    def test_reject_extra_inventory_links_and_wrong_backend_digest(self):
        extra = self.intent.journal / 'extra'
        extra.write_bytes(b'x')
        with self.assertRaises(ValueError):
            lookup.lookup(self.intent)
        extra.unlink()
        os.link(self.intent.journal / 'genesis', self.root / 'hardlink')
        with self.assertRaises(ValueError):
            lookup.lookup(self.intent)
        (self.root / 'hardlink').unlink()
        with patch.object(subprocess, 'Popen', side_effect=AssertionError('wrong binary executed')):
            with self.assertRaises((ValueError, RuntimeError)):
                lookup.lookup(replace(self.intent, backend_sha256='a' * 64))

    @unittest.skipUnless(os.name == 'posix', 'POSIX symlink fixture')
    def test_linked_parent_refused(self):
        link = self.root / 'linked'
        link.symlink_to(self.intent.journal, target_is_directory=True)
        with self.assertRaises(ValueError):
            lookup.lookup(replace(self.intent, journal=link))

    def test_real_python_is_not_an_accepting_replay_backend(self):
        with self.assertRaises((ValueError, RuntimeError)):
            lookup.lookup(self.intent)
        self.assertEqual((self.intent.journal / 'genesis').read_bytes(), self.header)

    def copied_backend(self):
        target = self.root / ('approved' + ('.exe' if os.name == 'nt' else ''))
        shutil.copy2(self.intent.backend, target)
        self.assertEqual(target.stat().st_nlink, 1)
        return replace(self.intent, backend=target)

    def test_hardlinked_native_backend_refused_before_any_process(self):
        intent = self.copied_backend()
        alias = self.root / 'alternate-backend-path'
        os.link(intent.backend, alias)
        self.assertEqual(intent.backend.stat().st_nlink, 2)
        with patch.object(subprocess, 'Popen', side_effect=AssertionError('hardlinked process started')) as spawn:
            with self.assertRaises((ValueError, RuntimeError)):
                lookup.lookup(intent)
        self.assertEqual(spawn.call_count, 0)
        self.assertEqual(alias.read_bytes(), intent.backend.read_bytes())

    def test_single_link_backend_still_reaches_original_process_gate(self):
        intent = self.copied_backend()
        class ReachedProcess(RuntimeError):
            pass
        with patch.object(subprocess, 'Popen', side_effect=ReachedProcess('refusal only')) as spawn:
            with self.assertRaises(ReachedProcess):
                lookup.lookup(intent)
        self.assertEqual(spawn.call_count, 1)
        self.assertEqual(spawn.call_args.args[0][0], str(intent.backend))

    def test_link_created_during_digest_check_is_not_an_approved_binary(self):
        intent = self.copied_backend()
        alias = self.root / 'late-backend-alias'
        from wallet_backup_backend import Backend
        original = Backend._check
        def checked_then_linked(binary):
            result = original(binary)  # Actual hash and handle/path checks run first.
            os.link(binary.path, alias)
            return result
        with patch.object(Backend, '_check', checked_then_linked), \
                patch.object(subprocess, 'Popen', side_effect=AssertionError('changed backend launched')) as spawn:
            with self.assertRaises((ValueError, RuntimeError)):
                lookup.lookup(intent)
        self.assertEqual(spawn.call_count, 0)
        self.assertTrue(alias.exists())

    def test_cli_error_families_are_fixed_and_do_not_emit_success(self):
        for error in (ValueError('PRIVATE'), OSError('PRIVATE'), subprocess.TimeoutExpired(['PRIVATE'], 1),
                      subprocess.CalledProcessError(1, ['PRIVATE']), KeyboardInterrupt('PRIVATE')):
            out, err = io.StringIO(), io.StringIO()
            with patch.object(lookup, 'lookup', side_effect=error), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = lookup.main(self.args())
            self.assertEqual(code, 130 if isinstance(error, KeyboardInterrupt) else 1)
            self.assertEqual(out.getvalue(), '')
            self.assertNotIn('PRIVATE', err.getvalue())

    def test_real_cli_help_syntax_and_native_refusal(self):
        for args, status in ((['--help'], 0), (['--secret', 'PRIVATE'], 64), (self.args(), 1)):
            result = subprocess.run([sys.executable, '-B', lookup.__file__, *args], capture_output=True, timeout=10)
            self.assertEqual(result.returncode, status)
            self.assertNotIn(b'PRIVATE', result.stderr)
            if status != 0:
                self.assertEqual(result.stdout, b'')


if __name__ == '__main__':
    unittest.main()
