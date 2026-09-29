"""Version and workflow guardrails, not native authorization substitutes."""
import ast
import fnmatch
from pathlib import Path
import re
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ledger_transaction_lookup as lookup
import inspector_source_bundle as bundle
import test_inspector_delivery_source as guard

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / '.github/workflows/ledger-transaction-lookup.yml'


class SourceTests(unittest.TestCase):
    def test_original_limits_match_existing_go_and_rust_contracts(self):
        go = (ROOT / 'internal/poolbridge/client.go').read_text(encoding='utf-8')
        pool = (ROOT / 'integration/orchard/src/pool.rs').read_text(encoding='utf-8')
        self.assertEqual(lookup.MAX_TRANSACTION_BYTES, int(re.search(r'const MaxTransactionBytes = (\d+)', go)[1]))
        self.assertEqual(lookup.MAX_TRANSACTIONS, int(re.search(r'MAX_BLOCK_TRANSACTIONS: usize = (\d+)', pool)[1]))
        for exact in ('b"ZVOBLK01"', 'raw[8..16]', 'raw[16..48]', 'raw[48..80]', 'raw[80..112]',
                      'raw[112..114]', 'let mut p = 114usize'):
            self.assertIn(exact, pool)
        self.assertEqual(lookup.LOOKUP_SECONDS, 300)
        self.assertEqual(len(bundle.SOURCES), 10)
        self.assertNotIn('ledger_transaction_lookup.py', bundle.SOURCES)

    def test_guard_rejects_wrong_commit_and_dirty_source(self):
        with patch.object(guard, 'WORKFLOW', WORKFLOW):
            guard.DeliverySourceTests().test_actual_workflow_guard_rejects_wrong_commit_and_dirty_source()

    def test_all_static_dependencies_trigger_both_events(self):
        pending = [ROOT / 'scripts/ledger_transaction_lookup.py', ROOT / 'scripts/check_ledger_transaction_backend.py',
                   Path(__file__), ROOT / 'scripts/tests/test_ledger_transaction_lookup.py']
        expected = {WORKFLOW.relative_to(ROOT).as_posix(), guard.WORKFLOW.relative_to(ROOT).as_posix(),
                    'docs/LEDGER_TRANSACTION_LOOKUP.zh-CN.md', 'internal/poolbridge/client.go',
                    'integration/orchard/src/pool.rs'}
        visited = set()
        while pending:
            path = pending.pop()
            if path in visited:
                continue
            visited.add(path)
            expected.add(path.relative_to(ROOT).as_posix())
            for node in ast.walk(ast.parse(path.read_bytes())):
                imports = ([n.name for n in node.names] if isinstance(node, ast.Import) else
                           [node.module] if isinstance(node, ast.ImportFrom) and node.module and not node.level else [])
                for name in imports:
                    for directory in (ROOT / 'scripts', ROOT / 'scripts/tests'):
                        child = directory / (name.split('.')[0] + '.py')
                        if child.is_file():
                            pending.append(child)
        blocks = dict(re.findall(r'^  (push|pull_request):\n((?:    [^\n]*\n)+)', WORKFLOW.read_text(encoding='utf-8'), re.M))
        self.assertEqual(set(blocks), {'push', 'pull_request'})
        for block in blocks.values():
            patterns = ast.literal_eval(re.findall(r'^    paths: (.+)$', block, re.M)[0])
            for path in expected:
                self.assertTrue(any(fnmatch.fnmatchcase(path, pattern) for pattern in patterns), path)

    def test_workflow_requires_genuine_native_and_keeps_budget(self):
        text = WORKFLOW.read_text(encoding='utf-8')
        for literal in ('persist-credentials: false', 'os: [ubuntu-latest, windows-latest]', 'timeout-minutes: 20',
                        'ref: ${{ github.event.pull_request.head.sha || github.sha }}', 'cargo +1.98.1 build',
                        '--locked --release --features local-funding-lab', '--bin zevune-pool-recovery',
                        'scripts/check_ledger_transaction_backend.py', 'check=True, timeout=600'):
            self.assertIn(literal, text)
        self.assertNotIn('continue-on-error', text)
        self.assertNotIn('upload-artifact', text)
        native = (ROOT / 'scripts/check_ledger_transaction_backend.py').read_text(encoding='utf-8')
        self.assertIn('report = saved_recover(*args, **kwargs)', native)
        self.assertIn('original.run(wallet, worker, recovery)', native)
        self.assertIn('reply = real_run(self, *params)', native)
        self.assertIn("[('pending', False), ('empty-result', False), ('included', True), ('expired', False)]", native)

    def test_product_has_no_wallet_mutation_network_or_persistent_index(self):
        source = (ROOT / 'scripts/ledger_transaction_lookup.py').read_bytes()
        calls = {node.func.attr for node in ast.walk(ast.parse(source))
                 if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
        self.assertFalse(calls & {'write_bytes', 'write_text', 'mkdir', 'unlink', 'rename', 'recover', 'backup',
                                 'authenticate', 'authenticate_descendant', 'pending', 'send', 'Popen'})
        self.assertIn('active', calls)
        self.assertIn('validate_reply', calls)


if __name__ == '__main__':
    unittest.main()
