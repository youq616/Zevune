"""Real bounded task/report inputs. No accepting native verifier doubles."""
from dataclasses import replace
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ledger_query_evidence_desktop as desktop
import check_ledger_query_audit as fixtures


def fixture(root):
    a = fixtures.request_fixture()
    b = desktop.task.prepare(a.checkpoint, a.genesis_sha256, 'b' * 64, (*a.txids[1:], 'f' * 64))
    sources = []
    for name, request in (('a', a), ('b', b)):
        path, report = root / (name + '.json'), root / (name + '-report.json')
        pin = desktop.task.create(request, path)['request_sha256']
        report_pin = desktop.comparison.reports.export_audit(path, pin, report)['audit_sha256']
        sources.append({'task': desktop.comparison.Source('task', path, pin),
                        'report': desktop.comparison.Source('report', report, report_pin)})
    return sources, (a, b)


def fields(before, after):
    return {f'{side}_{name}': str(getattr(source, name))
            for side, source in (('before', before), ('after', after)) for name in ('kind', 'path', 'sha256')}


class BoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='evidence-desktop-unit-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.sources, self.requests = fixture(self.root)
        self.values = fields(self.sources[0]['task'], self.sources[1]['report'])
        self.before = {p.name: p.read_bytes() for p in self.root.iterdir()}

    def test_prepare_freezes_both_sources_and_disclosure(self):
        intent = desktop.prepare(self.values)
        self.values['before_kind'] = 'report'
        self.assertEqual(intent.before, self.sources[0]['task'])
        self.assertFalse(intent.details)
        with self.assertRaises(AttributeError): intent.details = True

    def test_all_inputs_checked_before_any_comparison_read(self):
        with patch.object(desktop.comparison, 'compare', side_effect=AssertionError('no IO')):
            for key, value in (('before_kind', ''), ('after_kind', 'auto'), ('before_path', None),
                               ('after_path', 'relative'), ('after_path', '/tmp/../x'),
                               ('before_sha256', 'A'*64), ('after_sha256', None),
                               ('after_path', '/a/'+'中'*1400), ('after_path', '/a/\u202ex')):
                with self.subTest(key=key), self.assertRaises(ValueError):
                    desktop.inspect(desktop.prepare(dict(self.values, **{key:value})))
            for bad in (None, {}, dict(self.values, extra=1)):
                with self.assertRaises(ValueError): desktop.prepare(bad)
            for details in (0, 1, None, 'true'):
                with self.assertRaises(ValueError): desktop.prepare(self.values, details)

    def test_forged_intent_rejected_before_io(self):
        intent = desktop.prepare(self.values)
        with patch.object(desktop.comparison, 'compare', side_effect=AssertionError('no IO')):
            for bad in (None, replace(intent, before=None), replace(intent, details=1),
                        replace(intent, after=replace(intent.after, kind='auto'))):
                with self.assertRaises(ValueError): desktop.inspect(bad)

    def test_real_four_combinations_match_existing_cli_presentation(self):
        for a in ('task', 'report'):
            for b in ('task', 'report'):
                for details in (False, True):
                    intent = desktop.prepare(fields(self.sources[0][a], self.sources[1][b]), details)
                    result = desktop.inspect(intent)
                    reference = desktop.comparison.compare(intent.before, intent.after, details=details)
                    self.assertEqual(result.text, desktop.comparison.render(reference))
                    self.assertEqual(result.intent, intent)
                    self.assertLess(len(result.text.encode('utf-8')), desktop.comparison.MAX_OUTPUT_BYTES)
                    with self.assertRaises(AttributeError): result.text = 'changed'
        self.assertEqual(self.before, {p.name:p.read_bytes() for p in self.root.iterdir()})

    def test_default_has_no_complete_ids_pins_or_paths(self):
        text = desktop.inspect(desktop.prepare(self.values)).text
        for request in self.requests:
            for value in (*request.txids, request.checkpoint, request.genesis_sha256, request.backend_sha256):
                self.assertNotIn(value, text)
        self.assertNotIn(str(self.root), text)
        for side in ('before', 'after'): self.assertIn(self.values[side+'_sha256'], text)
        detailed = desktop.inspect(desktop.prepare(self.values, True)).text
        self.assertIn(self.requests[0].txids[0], detailed)

    def test_reports_work_without_original_tasks_and_do_not_claim_recheck(self):
        for source in self.sources: source['task'].path.unlink()
        intent = desktop.prepare(fields(self.sources[0]['report'], self.sources[1]['report']))
        with patch.object(desktop.task, 'load', side_effect=AssertionError('opened deleted task')):
            shown = desktop.inspect(intent)
        self.assertIn('未读取原任务', shown.text)
        self.assertIn('未检查对应原任务当前是否存在', shown.text)
        with self.assertRaises(OSError): desktop.inspect(desktop.prepare(self.values))

    def test_wrong_kind_or_digest_never_falls_back(self):
        for change in ({'before_kind':'report'}, {'after_sha256':'0'*64},
                       {'after_sha256':self.sources[1]['task'].sha256}):
            with self.assertRaises(ValueError): desktop.inspect(desktop.prepare(dict(self.values, **change)))

    def test_real_inputs_cannot_execute_or_write(self):
        with patch.object(subprocess, 'Popen', side_effect=AssertionError('no process')) as popen, \
                patch.object(desktop.task, 'run_request', side_effect=AssertionError('no query')) as run, \
                patch.object(desktop.task.files, 'write_new', side_effect=AssertionError('no write')) as write, \
                patch.object(desktop.task.once.single.ledger, 'archive_snapshot', side_effect=AssertionError('no ledger')):
            desktop.inspect(desktop.prepare(self.values))
        self.assertEqual((popen.call_count,run.call_count,write.call_count),(0,0,0))

    def test_same_bytes_input_replacement_during_comparison_refused(self):
        real = desktop.comparison.changes.describe
        path = self.sources[0]['task'].path
        def changed(*args, **kwargs):
            raw = path.read_bytes(); path.rename(self.root/'held'); path.write_bytes(raw)
            return real(*args, **kwargs)
        with patch.object(desktop.comparison.changes, 'describe', side_effect=changed), self.assertRaises(ValueError):
            desktop.inspect(desktop.prepare(self.values))

    def test_hardlinked_input_is_not_relaxed_by_gui_adapter(self):
        os.link(self.sources[0]['task'].path, self.root/'alias')
        with self.assertRaises(ValueError): desktop.inspect(desktop.prepare(self.values))

    def test_core_failure_is_not_display_or_absence(self):
        for exc in (ValueError('PRIVATE'), OSError('PRIVATE'), KeyboardInterrupt('PRIVATE')):
            with patch.object(desktop.comparison, 'compare', side_effect=exc) as call:
                with self.assertRaises(type(exc)): desktop.inspect(desktop.prepare(self.values))
            self.assertEqual(call.call_count,1)

    def test_real_help_without_display_and_errors_redacted(self):
        for args, code in ((['--help'],0), ([],64), (['--secret','PRIVATE'],64), (['--no-real-f'],64)):
            p = subprocess.run([sys.executable,'-B',desktop.__file__,*args], capture_output=True, timeout=10,
                               env={**os.environ,'DISPLAY':''})
            self.assertEqual(p.returncode,code,p.stderr)
            self.assertNotIn(b'PRIVATE',p.stderr+p.stdout)


if __name__ == '__main__': unittest.main()
