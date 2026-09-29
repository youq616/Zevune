"""Dependency/CI guards; these do not stand in for native batch success."""
import ast
import fnmatch
from pathlib import Path
import re
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ledger_transaction_batch as batch
import inspector_source_bundle as bundle
import test_inspector_delivery_source as guard

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / '.github/workflows/ledger-transaction-batch.yml'


class BatchSourceTests(unittest.TestCase):
    def test_actual_guard_refuses_wrong_commit_and_dirty_source(self):
        with patch.object(guard, 'WORKFLOW', WORKFLOW):
            guard.DeliverySourceTests().test_actual_workflow_guard_rejects_wrong_commit_and_dirty_source()

    def test_all_transitive_inputs_trigger_both_events(self):
        pending = [ROOT / 'scripts/ledger_transaction_batch.py', ROOT / 'scripts/check_ledger_transaction_batch_backend.py',
                   ROOT / 'scripts/tests/test_ledger_transaction_batch.py', Path(__file__)]
        expected = {WORKFLOW.relative_to(ROOT).as_posix(), guard.WORKFLOW.relative_to(ROOT).as_posix(),
                    'docs/LEDGER_TRANSACTION_BATCH.zh-CN.md', 'integration/orchard/src/pool.rs',
                    'internal/poolbridge/client.go'}
        visited = set()
        while pending:
            path = pending.pop()
            if path in visited:
                continue
            visited.add(path)
            expected.add(path.relative_to(ROOT).as_posix())
            for node in ast.walk(ast.parse(path.read_bytes())):
                imports = ([item.name for item in node.names] if isinstance(node, ast.Import) else
                           [node.module] if isinstance(node, ast.ImportFrom) and node.module and not node.level else [])
                for name in imports:
                    for folder in (ROOT / 'scripts', ROOT / 'scripts/tests'):
                        child = folder / (name.split('.')[0] + '.py')
                        if child.is_file():
                            pending.append(child)
        text = WORKFLOW.read_text(encoding='utf-8')
        events = dict(re.findall(r'^  (push|pull_request):\n((?:    [^\n]*\n)+)', text, re.M))
        self.assertEqual(set(events), {'push', 'pull_request'})
        for block in events.values():
            patterns = ast.literal_eval(re.findall(r'^    paths: (.+)$', block, re.M)[0])
            for path in expected:
                self.assertTrue(any(fnmatch.fnmatchcase(path, pattern) for pattern in patterns), path)

    def test_keeps_original_native_build_and_budget(self):
        text = WORKFLOW.read_text(encoding='utf-8')
        for literal in ('persist-credentials: false', 'os: [ubuntu-latest, windows-latest]', 'timeout-minutes: 20',
                        'ref: ${{ github.event.pull_request.head.sha || github.sha }}', 'cargo +1.98.1 build',
                        '--locked --release --features local-funding-lab', '--bin zevune-pool-recovery',
                        'scripts/check_ledger_transaction_batch_backend.py', 'check=True, timeout=600',
                        "-p 'test_ledger_transaction*.py'", "-p 'test_native_backend_install*.py'"):
            self.assertIn(literal, text)
        self.assertNotIn('continue-on-error', text)
        self.assertNotIn('upload-artifact', text)
        driver = (ROOT / 'scripts/check_ledger_transaction_batch_backend.py').read_text(encoding='utf-8')
        self.assertIn('report = saved_recover(*args, **kwargs)', driver)
        self.assertIn('return real_native(self, *params)', driver)
        self.assertIn('previous.run(wallet, worker, recovery)', driver)
        self.assertIn("assert len(checks) == 7", driver)

    def test_no_new_parser_wallet_write_or_global_replacement(self):
        source = (ROOT / 'scripts/ledger_transaction_batch.py').read_bytes()
        tree = ast.parse(source)
        calls = {node.func.attr for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
        self.assertTrue({'scan_archive', 'LookupVerifier', 'validate_reply'} <= calls)
        self.assertFalse(calls & {'write_bytes', 'write_text', 'mkdir', 'unlink', 'rename', 'recover', 'authenticate',
                                 'authenticate_descendant', 'pending', 'send', 'Popen', 'patch'})
        self.assertNotIn(b'ZVOBLK01', source)  # Existing scanner owns the record layout.
        self.assertEqual(len(bundle.SOURCES), 10)
        self.assertNotIn('ledger_transaction_batch.py', bundle.SOURCES)
        self.assertEqual(batch.BATCH_SECONDS, batch.single.LOOKUP_SECONDS)
        self.assertEqual((batch.MAX_TXIDS, batch.MAX_OUTPUT_BYTES), (32, 65536))


if __name__ == '__main__':
    unittest.main()
