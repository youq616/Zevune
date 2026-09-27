"""Task source/CI closure, not a replacement for successful original replay."""
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
import ledger_query_request as task

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / '.github/workflows/ledger-query-request.yml'


class SourceTests(unittest.TestCase):
    def test_actual_source_guard_rejects_wrong_head_and_dirty_source(self):
        with patch.object(guard, 'WORKFLOW', WORKFLOW):
            guard.DeliverySourceTests().test_actual_workflow_guard_rejects_wrong_commit_and_dirty_source()

    def test_transitive_dependencies_trigger_both_events(self):
        pending = [ROOT / 'scripts/ledger_query_request.py', ROOT / 'scripts/check_ledger_query_request_backend.py',
                   ROOT / 'scripts/tests/test_ledger_query_request.py', Path(__file__)]
        expected = {WORKFLOW.relative_to(ROOT).as_posix(), guard.WORKFLOW.relative_to(ROOT).as_posix(),
                    'docs/LEDGER_QUERY_REQUEST.zh-CN.md', 'integration/orchard/src/pool.rs'}
        visited = set()
        while pending:
            path = pending.pop()
            if path in visited:
                continue
            visited.add(path); expected.add(path.relative_to(ROOT).as_posix())
            for node in ast.walk(ast.parse(path.read_bytes())):
                names = ([x.name for x in node.names] if isinstance(node, ast.Import) else
                         [node.module] if isinstance(node, ast.ImportFrom) and node.module and not node.level else [])
                for name in names:
                    for folder in (ROOT / 'scripts', ROOT / 'scripts/tests'):
                        candidate = folder / (name.split('.')[0] + '.py')
                        if candidate.is_file():
                            pending.append(candidate)
        text = WORKFLOW.read_text(encoding='utf-8')
        events = dict(re.findall(r'^  (push|pull_request):\n((?:    [^\n]*\n)+)', text, re.M))
        self.assertEqual(set(events), {'push', 'pull_request'})
        for body in events.values():
            patterns = ast.literal_eval(re.findall(r'^    paths: (.+)$', body, re.M)[0])
            for path in expected:
                self.assertTrue(any(fnmatch.fnmatchcase(path, p) for p in patterns), path)

    def test_genuine_native_chain_and_original_budgets_preserved(self):
        text = WORKFLOW.read_text(encoding='utf-8')
        for item in ('persist-credentials: false', 'os: [ubuntu-latest, windows-latest]', 'cargo +1.98.1 build',
                     '--locked --release --features local-funding-lab', 'timeout-minutes: 20',
                     'check=True, timeout=600', 'scripts/check_ledger_query_request_backend.py'):
            self.assertIn(item, text)
        self.assertNotIn('continue-on-error', text)
        native = (ROOT / 'scripts/check_ledger_query_request_backend.py').read_text(encoding='utf-8')
        for item in ('report = saved_recover(*args, **kwargs)', 'previous.run(wallet, worker, recovery)',
                     'answer = core(intent)', "assert calls == ['verify-active']", 'assert len(checks) == 5'):
            self.assertIn(item, native)

    def test_request_contract_does_not_add_paths_or_change_old_bundle(self):
        self.assertEqual(task.FIELDS, {'format', 'query_profile', 'checkpoint', 'genesis_sha256',
                                      'backend_sha256', 'txids', 'real_funds_allowed'})
        self.assertEqual(task.MAX_REQUEST_BYTES, 8192)
        self.assertEqual(task.once.ONCE_SECONDS, 300)
        self.assertEqual(len(bundle.SOURCES), 10)
        self.assertNotIn('ledger_query_request.py', bundle.SOURCES)
        source = (ROOT / 'scripts/ledger_query_request.py').read_bytes()
        calls = {n.func.attr for n in ast.walk(ast.parse(source))
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
        self.assertTrue({'lookup_batch_once', 'write_new'} <= calls)
        self.assertFalse(calls & {'Popen', 'unlink', 'rename', 'recover', 'authenticate', 'send', 'pending'})


if __name__ == '__main__':
    unittest.main()
