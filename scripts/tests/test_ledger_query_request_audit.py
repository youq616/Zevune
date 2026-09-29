"""Real pinned task files and CLI, without a native verification success double."""
import contextlib
from dataclasses import replace
import hashlib
import io
import json
import os
from pathlib import Path
import random
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ledger_query_request_audit as audit
from test_ledger_restore import pin


def identifier(number):
    return hashlib.sha256(f'public-test-id-{number}'.encode()).hexdigest()


def request(ids=(1, 2, 3), **overrides):
    values = dict(checkpoint=pin(1), genesis_sha256='d' * 64, backend_sha256='b' * 64,
                  txids=tuple(identifier(i) for i in ids))
    values.update(overrides)
    return audit.task.prepare(**values)


class DifferenceTests(unittest.TestCase):
    def test_equal_content_is_not_file_integrity_or_permission(self):
        result = audit.describe(request(), request())
        self.assertTrue(result['content_identical'])
        self.assertEqual(result['changed_fields'], [])
        self.assertNotIn('request_integrity_verified', result)
        self.assertNotIn('details', result)
        self.assertEqual(result['retained_count'], 3)

    def test_each_pin_change_is_visible_without_query_changes(self):
        for field, value in (('checkpoint', pin(2)), ('genesis_sha256', 'e' * 64),
                             ('backend_sha256', 'c' * 64)):
            with self.subTest(field=field):
                result = audit.describe(request(), request(**{field: value}))
                self.assertEqual(result['changed_trust_fields'], [field])
                self.assertEqual(result['changed_fields'], [field])
                self.assertFalse(result['query_sequence_changed'])
                self.assertFalse(result['content_identical'])

    def test_same_height_different_commitment_is_not_unchanged_checkpoint(self):
        result = audit.describe(request(), request(checkpoint=pin(1, genesis=b'x' * 32)))
        self.assertEqual(result['after_height_comparison'], 'equal')
        self.assertEqual(result['changed_fields'], ['checkpoint'])
        for value, expected in ((pin(0), 'lower'), (pin(2), 'higher')):
            self.assertEqual(audit.describe(request(), request(checkpoint=value))['after_height_comparison'], expected)

    def test_add_delete_reorder_and_positions_preserve_caller_order(self):
        result = audit.describe(request((1, 2, 3)), request((4, 3, 1, 5)), details=True)
        self.assertEqual((result['added_count'], result['removed_count'], result['retained_count']), (2, 1, 2))
        self.assertTrue(result['query_set_changed'])
        self.assertTrue(result['retained_order_changed'])
        details = result['details']
        self.assertEqual(details['added'], [dict(txid=identifier(4), after_index=0), dict(txid=identifier(5), after_index=3)])
        self.assertEqual(details['removed'], [dict(txid=identifier(2), before_index=1)])
        self.assertEqual([row['txid'] for row in details['retained']], [identifier(1), identifier(3)])

    def test_insertion_shifts_positions_without_reordering_retained_ids(self):
        result = audit.describe(request((1, 2)), request((3, 1, 2)))
        self.assertFalse(result['retained_order_changed'])
        self.assertEqual(result['retained_position_changed_count'], 2)
        self.assertTrue(result['query_sequence_changed'])

    def test_reorder_without_membership_change(self):
        result = audit.describe(request((1, 2, 3)), request((3, 2, 1)))
        self.assertFalse(result['query_set_changed'])
        self.assertTrue(result['query_sequence_changed'])
        self.assertTrue(result['retained_order_changed'])
        self.assertEqual(result['retained_position_changed_count'], 2)

    def test_disjoint_and_singleton_lists(self):
        result = audit.describe(request((1,)), request((2,)))
        self.assertEqual((result['added_count'], result['removed_count'], result['retained_count']), (1, 1, 0))
        self.assertFalse(result['retained_order_changed'])

    def test_default_omits_ids_and_full_pins_but_details_are_exact(self):
        before, after = request(), request((3, 4))
        public = json.dumps(audit.describe(before, after))
        for value in (*before.txids, *after.txids, before.checkpoint, before.genesis_sha256, before.backend_sha256):
            self.assertNotIn(value, public)
        details = audit.describe(before, after, details=True)['details']
        self.assertEqual(details['before'], before.document())
        self.assertEqual(details['after'], after.document())
        details['before']['txids'].clear()
        self.assertEqual(len(before.txids), 3)
        self.assertEqual(len(audit.describe(before, after, details=True)['details']['before']['txids']), 3)

    def test_invalid_object_or_details_type_is_refused_without_io(self):
        with patch.object(audit.task, 'load', side_effect=AssertionError('pure comparison read a file')):
            for value in (None, {}, replace(request(), txids=[]), replace(request(), txids=(identifier(1),) * 2)):
                with self.assertRaises(ValueError):
                    audit.describe(value, request())
            for details in (0, 1, 'true', None):
                with self.assertRaises(ValueError):
                    audit.describe(request(), request(), details=details)

    def test_fixed_seed_properties_and_reverse_direction(self):
        rng = random.Random(2801)
        for _ in range(200):
            left = rng.sample(range(40), rng.randint(1, 32))
            right = rng.sample(range(40), rng.randint(1, 32))
            a = audit.describe(request(left), request(right), details=True)
            b = audit.describe(request(right), request(left), details=True)
            self.assertEqual(a['before_query_count'], a['retained_count'] + a['removed_count'])
            self.assertEqual(a['after_query_count'], a['retained_count'] + a['added_count'])
            self.assertEqual(a['added_count'], b['removed_count'])
            self.assertEqual(a['retained_count'], b['retained_count'])
            self.assertEqual(a['retained_position_changed_count'], b['retained_position_changed_count'])
            self.assertEqual(a['retained_order_changed'], b['retained_order_changed'])
            self.assertEqual(a['retained_order_changed'],
                             [i for i in left if i in right] != [i for i in right if i in left])
            self.assertEqual([item['txid'] for item in a['details']['added']],
                             [identifier(i) for i in right if i not in left])


class FileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='zevune-task-audit-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.left, self.right = self.root / 'before.json', self.root / 'after.json'
        self.a, self.b = request(), request((3, 2, 4))
        self.pins = []
        for path, req in ((self.left, self.a), (self.right, self.b)):
            self.pins.append(audit.task.create(req, path)['request_sha256'])
        self.before = {p.name: p.read_bytes() for p in self.root.iterdir()}

    def check(self, **kwargs):
        return audit.audit(self.left, self.pins[0], self.right, self.pins[1], **kwargs)

    def test_actual_audit_safety_flags_and_bytes_preserved(self):
        result = self.check()
        self.assertTrue(result['audit_complete'] and result['request_integrity_verified'])
        self.assertTrue(result['requires_explicit_execution_confirmation'])
        for name in ('execution_performed', 'signature_verified', 'ledger_replayed',
                     'checkpoint_chain_relation_verified', 'approval_reusable', 'finality_verified',
                     'retry_authorized', 'real_funds_allowed'):
            self.assertIs(result[name], False, name)
        self.assertEqual({p.name: p.read_bytes() for p in self.root.iterdir()}, self.before)
        self.assertNotIn(str(self.root), json.dumps(result))

    def test_equal_files_and_same_path_still_require_two_pins(self):
        self.right.write_bytes(self.left.read_bytes())
        self.pins[1] = self.pins[0]
        result = self.check()
        self.assertTrue(result['content_identical'])
        self.assertFalse(result['approval_reusable'])
        self.assertTrue(audit.audit(self.left, self.pins[0], self.left, self.pins[0])['content_identical'])
        with self.assertRaises(ValueError):
            audit.audit(self.left, self.pins[0], self.left, '0' * 64)

    def test_all_arguments_validated_before_first_file_access(self):
        args = [self.left, self.pins[0], self.right, self.pins[1]]
        with patch.object(audit.task, 'load', side_effect=AssertionError('premature IO')):
            for index, value in ((0, Path('relative')), (2, self.root / '..' / 'escape'),
                                 (2, str(self.right)), (1, None), (3, 'A' * 64),
                                 (0, self.root / 'b\u202ed'), (2, self.root / ('中' * 1400))):
                wrong = list(args); wrong[index] = value
                with self.subTest(index=index), self.assertRaises(ValueError):
                    audit.audit(*wrong)
            with self.assertRaises(ValueError):
                self.check(details=1)

    def test_wrong_pins_and_corrupt_second_file_never_return_partial_result(self):
        with self.assertRaises(ValueError):
            audit.audit(self.left, '0' * 64, self.right, self.pins[1])
        self.right.write_bytes(self.before[self.right.name] + b'x')
        with self.assertRaises(ValueError):
            self.check()
        self.assertEqual(self.left.read_bytes(), self.before[self.left.name])

    def test_original_decoder_rejects_new_pin_for_noncanonical_or_unknown_fields(self):
        raw = self.right.read_bytes()
        for bad in (raw + b' ', raw[:-2] + b',"real_funds_allowed":false}\n',
                    audit.task.files.canonical(dict(self.b.document(), auto_run=True)),
                    audit.task.files.canonical(dict(self.b.document(), real_funds_allowed=0)), b'\xff'):
            self.right.write_bytes(bad)
            digest = hashlib.sha256(bad).hexdigest()
            with self.assertRaises(ValueError):
                audit.audit(self.left, self.pins[0], self.right, digest)

    def test_reading_second_task_cannot_hide_first_task_change(self):
        original = audit.task.load
        def changed(path, pin_value):
            answer = original(path, pin_value)
            if path == self.right:
                self.left.write_bytes(self.before[self.left.name] + b'x')
            return answer
        with patch.object(audit.task, 'load', side_effect=changed), self.assertRaises(ValueError):
            self.check()

    def test_same_bytes_replacement_is_not_unchanged_identity(self):
        original = audit.describe
        def replace_left(*args, **kwargs):
            self.left.rename(self.root / 'held')
            self.left.write_bytes(self.before[self.left.name])
            return original(*args, **kwargs)
        with patch.object(audit, 'describe', side_effect=replace_left), self.assertRaises(ValueError):
            self.check()

    def test_change_to_first_during_final_second_read_is_detected(self):
        original = audit.task.unchanged
        calls = []
        # Inject only after describe, so task.load's internal checks stay real.
        def install_hook(*args, **kwargs):
            def changed(snapshot):
                original(snapshot)
                calls.append(snapshot.path)
                if snapshot.path == self.right:
                    self.left.rename(self.root / 'held')
                    self.left.write_bytes(self.before[self.left.name])
            hook = patch.object(audit.task, 'unchanged', side_effect=changed)
            hook.start(); self.addCleanup(hook.stop)
            return real_describe(*args, **kwargs)
        real_describe = audit.describe
        with patch.object(audit, 'describe', side_effect=install_hook), self.assertRaises(ValueError):
            self.check()
        self.assertEqual(calls, [self.left, self.right])

    def test_task_parent_replacement_refused(self):
        child = self.root / 'tasks'; child.mkdir()
        self.left = child / 'before.json'
        self.left.write_bytes(self.before['before.json'])
        original = audit.describe
        def move_parent(*args, **kwargs):
            child.rename(self.root / 'old-tasks'); child.mkdir()
            self.left.write_bytes(self.before['before.json'])
            return original(*args, **kwargs)
        with patch.object(audit, 'describe', side_effect=move_parent), self.assertRaises(ValueError):
            self.check()

    def test_hardlink_directory_and_oversize_request_refused(self):
        os.link(self.right, self.root / 'alias')
        with self.assertRaises(ValueError): self.check()
        (self.root / 'alias').unlink()
        self.right.write_bytes(b'x' * (audit.task.MAX_REQUEST_BYTES + 1))
        with self.assertRaises(ValueError): self.check()
        self.right.unlink(); self.right.mkdir()
        with self.assertRaises(ValueError): self.check()

    @unittest.skipUnless(os.name == 'posix', 'POSIX symlink/FIFO fixtures')
    def test_symlink_parent_and_fifo_refused(self):
        parent = self.root / 'alias'; parent.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(ValueError):
            audit.audit(self.left, self.pins[0], parent / self.right.name, self.pins[1])
        self.right.unlink(); os.mkfifo(self.right)
        with self.assertRaises(ValueError): self.check()

    def test_no_process_ledger_or_write_path_is_called(self):
        with patch.object(subprocess, 'Popen', side_effect=AssertionError('process executed')), \
                patch.object(audit.task, 'run_request', side_effect=AssertionError('query executed')), \
                patch.object(audit.task.files, 'write_new', side_effect=AssertionError('file written')), \
                patch.object(audit.task.once.single.ledger, 'archive_snapshot', side_effect=AssertionError('ledger read')):
            result = self.check(details=True)
        self.assertFalse(result['execution_performed'])

    def test_32_to_32_disjoint_details_and_text_remain_bounded(self):
        for path, values, index in ((self.left, range(32), 0), (self.right, range(32, 64), 1)):
            raw = audit.task.encode(request(values)); path.write_bytes(raw)
            self.pins[index] = hashlib.sha256(raw).hexdigest()
        result = self.check(details=True)
        self.assertEqual((result['added_count'], result['removed_count']), (32, 32))
        self.assertLess(len(json.dumps(result).encode()), audit.MAX_OUTPUT_BYTES)
        self.assertLess(len(audit.render(result).encode()), audit.MAX_OUTPUT_BYTES)

    def arguments(self):
        return ['--no-real-funds', '--before', str(self.left), '--before-sha256', self.pins[0],
                '--after', str(self.right), '--after-sha256', self.pins[1]]

    def test_real_cli_summary_details_and_utf8_without_path_or_display(self):
        env = {**os.environ, 'PATH': '', 'DISPLAY': '', 'PYTHONIOENCODING': 'cp1252', 'PYTHONUTF8': '0'}
        for extra in ([], ['--details'], ['--text'], ['--text', '--details']):
            result = subprocess.run([sys.executable, audit.__file__, *self.arguments(), *extra],
                                    env=env, capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            text = result.stdout.decode('utf-8')
            if '--details' not in extra:
                for value in (*self.a.txids, *self.b.txids, self.a.checkpoint):
                    self.assertNotIn(value, text)
            else:
                self.assertIn(self.a.txids[0], text)
            if '--text' not in extra:
                self.assertEqual(json.loads(text), self.check(details='--details' in extra))
        self.assertEqual({p.name: p.read_bytes() for p in self.root.iterdir()}, self.before)

    def test_cli_invalid_parameters_are_redacted(self):
        for args, status in ((['--secret', 'PRIVATE'], 64), (['--no-real-f'], 64),
                             (self.arguments()[:-1] + ['PRIVATE'], 1)):
            result = subprocess.run([sys.executable, '-B', audit.__file__, *args], capture_output=True, timeout=10)
            self.assertEqual(result.returncode, status)
            self.assertEqual(result.stdout, b'')
            self.assertNotIn(b'PRIVATE', result.stderr)
            self.assertNotIn(str(self.root).encode(), result.stderr)

    def test_cli_failure_or_interruption_never_emits_success(self):
        for failure in (ValueError('PRIVATE'), OSError('PRIVATE'), KeyboardInterrupt('PRIVATE')):
            out, err = io.StringIO(), io.StringIO()
            with patch.object(audit, 'audit', side_effect=failure), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = audit.main(self.arguments())
            self.assertEqual(code, 130 if isinstance(failure, KeyboardInterrupt) else 1)
            self.assertEqual(out.getvalue(), '')
            self.assertNotIn('PRIVATE', err.getvalue())

    def test_text_report_identifies_both_independent_task_pins(self):
        text = audit.render(self.check())
        self.assertIn(self.pins[0], text)
        self.assertIn(self.pins[1], text)

    def test_output_failure_is_not_zero_exit(self):
        with patch.object(audit.task.view, 'write_output', side_effect=OSError('PRIVATE')), \
                contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(audit.main(self.arguments()), 1)
        self.assertEqual(out.getvalue(), '')

    def test_unicode_paths_work_without_appearing_in_output(self):
        self.left.rename(self.root / '原任务 文件.json'); self.left = self.root / '原任务 文件.json'
        result = self.check()
        self.assertNotIn('原任务', json.dumps(result))


if __name__ == '__main__':
    unittest.main()
