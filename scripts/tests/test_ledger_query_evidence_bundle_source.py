"""Source closure and CI guards; not signatures or independent review."""
import ast
import fnmatch
from pathlib import Path
import re
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ledger_query_evidence_bundle as bundle
import inspector_source_bundle as delivery
import test_inspector_delivery_source as guard

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / '.github/workflows/ledger-query-evidence-bundle.yml'


class SourceTests(unittest.TestCase):
    def test_actual_wrong_head_and_dirty_source_guard(self):
        with patch.object(guard, 'WORKFLOW', WORKFLOW):
            guard.DeliverySourceTests().test_actual_workflow_guard_rejects_wrong_commit_and_dirty_source()

    def test_transitive_files_trigger_both_events(self):
        pending = list((ROOT/'scripts/tests').glob('test_ledger_query*.py'))
        pending += [ROOT/'scripts'/name for name in ('ledger_query_evidence_bundle.py',
                    'check_ledger_query_evidence_bundle.py', 'check_ledger_query_audit.py', 'check_ledger_query_evidence_compare.py')]
        expected = {WORKFLOW.relative_to(ROOT).as_posix(), 'docs/LEDGER_QUERY_EVIDENCE_BUNDLE.zh-CN.md',
                    guard.WORKFLOW.relative_to(ROOT).as_posix()}
        visited = set()
        while pending:
            path = pending.pop()
            if path in visited: continue
            visited.add(path); expected.add(path.relative_to(ROOT).as_posix())
            for n in ast.walk(ast.parse(path.read_bytes())):
                names = ([x.name for x in n.names] if isinstance(n, ast.Import) else
                         [n.module] if isinstance(n, ast.ImportFrom) and n.module and not n.level else [])
                for name in names:
                    for parent in (ROOT/'scripts', ROOT/'scripts/tests'):
                        child = parent/(name.split('.')[0]+'.py')
                        if child.is_file(): pending.append(child)
        events = dict(re.findall(r'^  (push|pull_request):\n((?:    [^\n]*\n)+)', WORKFLOW.read_text(encoding='utf-8'), re.M))
        self.assertEqual(set(events), {'push', 'pull_request'})
        for body in events.values():
            patterns = ast.literal_eval(re.findall(r'^    paths: (.+)$', body, re.M)[0])
            for path in expected: self.assertTrue(any(fnmatch.fnmatchcase(path, p) for p in patterns), path)

    def test_original_formats_limits_and_delivery_are_unchanged(self):
        self.assertEqual((bundle.MAX_ITEMS, bundle.MAX_BUNDLE_BYTES), (32, 1100000))
        self.assertEqual(bundle.task.MAX_REQUEST_BYTES, 8192)
        self.assertEqual(bundle.reports.MAX_REPORT_BYTES, 16384)
        self.assertEqual(len(delivery.SOURCES), 10)
        self.assertNotIn('ledger_query_evidence_bundle.py', delivery.SOURCES)
        tree = ast.parse((ROOT/'scripts/ledger_query_evidence_bundle.py').read_bytes())
        calls = {n.func.attr for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
        self.assertTrue({'decode','write_new','mkdir'} <= calls)
        self.assertFalse(calls & {'unlink','rename','rmdir','run_request','Popen','recover','active','extractall'})

    def test_both_platforms_require_real_lifecycle_without_native(self):
        text = WORKFLOW.read_text(encoding='utf-8')
        for value in ('os: [ubuntu-latest, windows-latest]', 'persist-credentials: false', 'timeout-minutes: 5',
                      "-p 'test_ledger_query*.py'", 'scripts/check_ledger_query_evidence_bundle.py',
                      'scripts/check_ledger_query_audit.py', 'scripts/check_ledger_query_evidence_compare.py'):
            self.assertIn(value, text)
        for value in ('continue-on-error','cargo ','rustup ','pip install'):
            self.assertNotIn(value, text)


if __name__ == '__main__': unittest.main()
