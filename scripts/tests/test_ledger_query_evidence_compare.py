"""Real task/report comparisons; no query execution or successful native doubles."""
import contextlib
from dataclasses import replace
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
import ledger_query_evidence_compare as compare
from test_ledger_query_request_audit import request


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='zevune-evidence-diff-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.a, self.b = request((1, 2)), request((3, 1, 2))
        self.sources = []
        for label, value in (('a', self.a), ('b', self.b)):
            task_path, report_path = self.root / (label + '.json'), self.root / (label + '-report.json')
            pin = compare.task.create(value, task_path)['request_sha256']
            report_pin = compare.reports.export_audit(task_path, pin, report_path)['audit_sha256']
            self.sources.append(dict(task=compare.Source('task', task_path, pin),
                                     report=compare.Source('report', report_path, report_pin)))
        self.original = {p.name: p.read_bytes() for p in self.root.iterdir()}

    def run_compare(self, before='task', after='report', **kwargs):
        return compare.compare(self.sources[0][before], self.sources[1][after], **kwargs)

    def test_all_four_modes_share_exact_difference_and_truthful_provenance(self):
        expected = compare.changes.describe(self.a, self.b, details=True)
        for left in compare.KINDS:
            for right in compare.KINDS:
                with self.subTest(before=left, after=right):
                    result = self.run_compare(left, right, details=True)
                    self.assertEqual(result['difference'], expected)
                    for i, side in enumerate(('before', 'after')):
                        kind = (left, right)[i]
                        self.assertEqual(result[side]['input_sha256'], self.sources[i][kind].sha256)
                        self.assertEqual(result[side]['request_sha256'], self.sources[i]['task'].sha256)
                        self.assertIs(result[side]['source_file_rechecked'], kind == 'task')
                        self.assertEqual(result[side]['request_digest_basis'],
                                         'external_task_pin' if kind == 'task' else 'verified_report_content')
        self.assertEqual({p.name: p.read_bytes() for p in self.root.iterdir()}, self.original)

    def test_report_comparison_does_not_depend_on_original_tasks(self):
        for sources in self.sources:
            sources['task'].path.unlink()
        with patch.object(compare.task, 'load', side_effect=AssertionError('report opened original task')):
            result = self.run_compare('report', 'report')
        self.assertFalse(result['before']['source_file_rechecked'])
        self.assertFalse(result['after']['source_file_rechecked'])
        self.assertEqual(result['difference']['added_count'], 1)
        with self.assertRaises(OSError):
            self.run_compare('task', 'report')

    def test_equal_task_content_is_not_equal_input_bytes_or_reusable_approval(self):
        result = compare.compare(self.sources[0]['task'], self.sources[0]['report'])
        self.assertTrue(result['difference']['content_identical'])
        self.assertFalse(result['input_bytes_identical'])
        self.assertFalse(result['approval_reusable'])
        self.assertTrue(result['requires_explicit_execution_confirmation'])
        result = compare.compare(self.sources[0]['report'], self.sources[0]['report'])
        self.assertTrue(result['input_bytes_identical'])
        with self.assertRaises(ValueError):
            compare.compare(self.sources[0]['report'], replace(self.sources[0]['report'], sha256='0' * 64))

    def test_all_arguments_checked_before_first_read(self):
        source = self.sources[0]['task']
        with patch.object(compare, '_load', side_effect=AssertionError('early IO')):
            for bad in (None, replace(source, kind='auto'), replace(source, kind=True),
                        replace(source, path=Path('relative')), replace(source, path=str(source.path)),
                        replace(source, sha256=False), replace(source, sha256='A' * 64)):
                for first in (True, False):
                    with self.subTest(input=repr(bad), first=first), self.assertRaises(ValueError):
                        compare.compare(bad if first else source, source if first else bad)
            for details in (0, 1, None, 'yes'):
                with self.assertRaises(ValueError):
                    compare.compare(source, source, details=details)

    def test_wrong_kind_has_no_silent_decoder_fallback(self):
        for source, wrong in ((self.sources[0]['task'], 'report'), (self.sources[0]['report'], 'task')):
            with self.assertRaises(ValueError):
                compare.compare(replace(source, kind=wrong), self.sources[1]['task'])

    def test_report_pin_cannot_be_replaced_by_embedded_task_pin(self):
        wrong = replace(self.sources[0]['report'], sha256=self.sources[0]['task'].sha256)
        with self.assertRaises(ValueError):
            compare.compare(wrong, self.sources[1]['task'])

    def test_rehashed_forged_report_is_refused_by_original_reconstruction(self):
        source = self.sources[0]['report']
        raw = source.path.read_bytes()
        for key, value in (('query_count', 31), ('query_executed', 0), ('signature_verified', True),
                           ('checkpoint_height', 200), ('extra', 'PRIVATE')):
            data = json.loads(raw)
            data[key] = value
            bad = compare.task.files.canonical(data)
            source.path.write_bytes(bad)
            wrong = replace(source, sha256=hashlib.sha256(bad).hexdigest())
            with self.subTest(key=key), self.assertRaises(ValueError):
                compare.compare(wrong, self.sources[1]['task'])

    def test_default_output_omits_ids_pins_paths_in_json_and_text(self):
        result = self.run_compare('report', 'task')
        for text in (json.dumps(result), compare.render(result)):
            for value in (*self.a.txids, *self.b.txids, self.a.checkpoint,
                          self.a.genesis_sha256, self.a.backend_sha256, str(self.root)):
                self.assertNotIn(value, text)
            for side in ('before', 'after'):
                self.assertIn(result[side]['input_sha256'], text)
        detailed = self.run_compare(details=True)
        self.assertEqual(detailed['difference']['details']['before'], self.a.document())
        self.assertIn(self.b.txids[0], compare.render(detailed))

    def test_no_execution_or_write_paths_called(self):
        with patch.object(subprocess, 'Popen', side_effect=AssertionError('process')), \
                patch.object(compare.task, 'run_request', side_effect=AssertionError('query')), \
                patch.object(compare.task.files, 'write_new', side_effect=AssertionError('write')), \
                patch.object(compare.task.once.single.ledger, 'archive_snapshot', side_effect=AssertionError('ledger')):
            result = self.run_compare('report', 'report')
        for key in ('execution_performed', 'signature_verified', 'backend_verified', 'ledger_replayed',
                    'checkpoint_chain_relation_verified', 'approval_reusable', 'finality_verified',
                    'retry_authorized', 'real_funds_allowed'):
            self.assertIs(result[key], False, key)

    def test_second_load_cannot_hide_first_input_change(self):
        loader = compare.reports.load
        def change(path, pin):
            answer = loader(path, pin)
            self.sources[0]['task'].path.write_bytes(self.original['a.json'] + b'x')
            return answer
        with patch.object(compare.reports, 'load', side_effect=change), self.assertRaises(ValueError):
            self.run_compare()

    def test_same_bytes_replacement_during_comparison_is_refused(self):
        original = compare.changes.describe
        path = self.sources[0]['report'].path
        def change(*args, **kwargs):
            path.rename(self.root / 'held')
            path.write_bytes(self.original[path.name])
            return original(*args, **kwargs)
        with patch.object(compare.changes, 'describe', side_effect=change), self.assertRaises(ValueError):
            self.run_compare('report', 'task')

    def test_late_first_change_during_second_final_read_is_refused(self):
        describe = compare.changes.describe
        unchanged = compare.reports.unchanged
        path = self.sources[0]['task'].path
        def late_check(snapshot):
            unchanged(snapshot)
            path.rename(self.root / 'held')
            path.write_bytes(self.original[path.name])
        def install(*args, **kwargs):
            hook = patch.object(compare.reports, 'unchanged', side_effect=late_check)
            hook.start()
            self.addCleanup(hook.stop)
            return describe(*args, **kwargs)
        with patch.object(compare.changes, 'describe', side_effect=install), self.assertRaises(ValueError):
            self.run_compare()

    def test_hardlinks_and_oversized_reports_refused(self):
        source = self.sources[0]['report']
        os.link(source.path, self.root / 'alias')
        with self.assertRaises(ValueError):
            self.run_compare('report', 'task')
        (self.root / 'alias').unlink()
        source.path.write_bytes(b'x' * (compare.reports.MAX_REPORT_BYTES + 1))
        with self.assertRaises(ValueError):
            self.run_compare('report', 'task')

    def test_maximum_disjoint_details_stay_bounded(self):
        for i in range(2):
            sources = self.sources[i]
            content = request(range(i * 32, (i + 1) * 32))
            raw = compare.task.encode(content)
            task_pin = hashlib.sha256(raw).hexdigest()
            report = compare.reports.encode(content, task_pin)
            sources['report'].path.write_bytes(report)
            sources['report'] = replace(sources['report'], sha256=hashlib.sha256(report).hexdigest())
        result = self.run_compare('report', 'report', details=True)
        self.assertEqual(result['difference']['added_count'], 32)
        self.assertLess(len(json.dumps(result).encode()), compare.MAX_OUTPUT_BYTES)
        self.assertLess(len(compare.render(result).encode()), compare.MAX_OUTPUT_BYTES)

    def args(self):
        result = ['--no-real-funds']
        for side, source in (('before', self.sources[0]['report']), ('after', self.sources[1]['task'])):
            result += ['--' + side, str(source.path), '--' + side + '-sha256', source.sha256,
                       '--' + side + '-kind', source.kind]
        return result

    def test_real_cli_all_output_modes_and_fixed_errors(self):
        for tail in ([], ['--text'], ['--details'], ['--details', '--text']):
            process = subprocess.run([sys.executable, '-B', compare.__file__, *self.args(), *tail],
                                     capture_output=True, timeout=15,
                                     env={**os.environ, 'PYTHONIOENCODING': 'cp1252', 'PYTHONUTF8': '0'})
            self.assertEqual(process.returncode, 0, process.stderr)
            text = process.stdout.decode('utf-8')
            if '--text' not in tail:
                self.assertEqual(json.loads(text), self.run_compare('report', 'task', details='--details' in tail))
            self.assertIn(self.sources[0]['report'].sha256, text)
        args = self.args()
        args[args.index('--before-kind') + 1] = 'PRIVATE_KIND'
        process = subprocess.run([sys.executable, '-B', compare.__file__, *args], capture_output=True, timeout=15)
        self.assertEqual(process.returncode, 64)
        self.assertNotIn(b'PRIVATE', process.stdout + process.stderr)
        self.assertEqual({p.name: p.read_bytes() for p in self.root.iterdir()}, self.original)

    def test_failure_and_interruption_never_emit_partial_success(self):
        for error in (OSError('PRIVATE'), ValueError('PRIVATE'), KeyboardInterrupt('PRIVATE')):
            out, err = io.StringIO(), io.StringIO()
            with patch.object(compare, 'compare', side_effect=error), \
                    contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = compare.main(self.args())
            self.assertEqual(code, 130 if isinstance(error, KeyboardInterrupt) else 1)
            self.assertEqual(out.getvalue(), '')
            self.assertNotIn('PRIVATE', err.getvalue())


if __name__ == '__main__':
    unittest.main()
