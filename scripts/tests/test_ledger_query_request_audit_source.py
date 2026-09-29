"""Audit source boundaries and actual CI identity guard, not execution approval."""
import ast
import fnmatch
from pathlib import Path
import re
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import inspector_source_bundle as bundle
import test_inspector_delivery_source as guard
import ledger_query_request_audit as audit

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / '.github/workflows/ledger-query-request-audit.yml'


class SourceTests(unittest.TestCase):
    def test_actual_workflow_refuses_wrong_commit_and_dirty_source(self):
        with patch.object(guard, 'WORKFLOW', WORKFLOW):
            guard.DeliverySourceTests().test_actual_workflow_guard_rejects_wrong_commit_and_dirty_source()

    def test_transitive_runtime_and_test_sources_trigger_both_events(self):
        pending = [ROOT / 'scripts/ledger_query_request_audit.py', Path(__file__),
                   ROOT / 'scripts/tests/test_ledger_query_request_audit.py',
                   ROOT / 'scripts/tests/test_ledger_query_request.py',
                   ROOT / 'scripts/ledger_query_evidence_compare.py',
                   ROOT / 'scripts/check_ledger_query_evidence_compare.py',
                   ROOT / 'scripts/check_ledger_query_audit.py',
                   ROOT / 'scripts/tests/test_ledger_query_evidence_compare.py']
        pending += list((ROOT / 'scripts/tests').glob('test_ledger_query_audit*.py'))
        expected = {WORKFLOW.relative_to(ROOT).as_posix(), guard.WORKFLOW.relative_to(ROOT).as_posix(),
                    'docs/LEDGER_QUERY_REQUEST_AUDIT.zh-CN.md'}
        visited = set()
        while pending:
            path = pending.pop()
            if path in visited:
                continue
            visited.add(path)
            expected.add(path.relative_to(ROOT).as_posix())
            for node in ast.walk(ast.parse(path.read_bytes())):
                names = ([n.name for n in node.names] if isinstance(node, ast.Import) else
                         [node.module] if isinstance(node, ast.ImportFrom) and node.module and not node.level else [])
                for name in names:
                    for folder in (ROOT / 'scripts', ROOT / 'scripts/tests'):
                        child = folder / (name.split('.')[0] + '.py')
                        if child.is_file():
                            pending.append(child)
        events = dict(re.findall(r'^  (push|pull_request):\n((?:    [^\n]*\n)+)', WORKFLOW.read_text(encoding='utf-8'), re.M))
        self.assertEqual(set(events), {'push', 'pull_request'})
        for body in events.values():
            patterns = ast.literal_eval(re.findall(r'^    paths: (.+)$', body, re.M)[0])
            for path in expected:
                self.assertTrue(any(fnmatch.fnmatchcase(path, p) for p in patterns), path)

    def test_product_calls_no_execution_write_or_new_decoder(self):
        tree = ast.parse((ROOT / 'scripts/ledger_query_request_audit.py').read_bytes())
        calls = {n.func.attr for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
        self.assertTrue({'load', 'unchanged', 'encode'} <= calls)
        self.assertFalse(calls & {'loads', 'run_request', 'create', 'write_new', 'write_bytes', 'unlink', 'rename',
                                 'mkdir', 'Popen', 'active', 'recover', 'lookup_batch_once', 'patch'})
        self.assertEqual(audit.MAX_OUTPUT_BYTES, 32768)
        self.assertEqual(audit.task.MAX_REQUEST_BYTES, 8192)
        self.assertEqual(len(bundle.SOURCES), 10)
        self.assertNotIn('ledger_query_request_audit.py', bundle.SOURCES)

    def test_ci_requires_both_platforms_without_native_execution(self):
        text = WORKFLOW.read_text(encoding='utf-8')
        for item in ('persist-credentials: false', 'os: [ubuntu-latest, windows-latest]', 'timeout-minutes: 5',
                     'ref: ${{ github.event.pull_request.head.sha || github.sha }}',
                     "-p 'test_ledger_query_request_audit*.py'", '-p test_ledger_query_request.py'):
            self.assertIn(item, text)
        for item in ('continue-on-error', 'cargo ', 'rustup ', 'upload-artifact', 'pip install'):
            self.assertNotIn(item, text)

    def test_mixed_adapter_reuses_original_decoders_and_pure_difference(self):
        tree = ast.parse((ROOT / 'scripts/ledger_query_evidence_compare.py').read_bytes())
        calls = {n.func.attr for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
        self.assertTrue({'describe', 'unchanged', 'metadata_unchanged'} <= calls)
        self.assertFalse(calls & {'loads', 'run_request', 'write_new', 'create', 'unlink', 'rename', 'Popen'})
        text = WORKFLOW.read_text(encoding='utf-8')
        for name in ('check_ledger_query_audit.py', 'check_ledger_query_evidence_compare.py',
                     'test_ledger_query_evidence_compare.py', 'test_ledger_query_audit*.py'):
            self.assertIn(name, text)



if __name__ == '__main__':
    unittest.main()
