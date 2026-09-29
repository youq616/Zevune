"""Source and integration contracts for native byte installation; not code approval."""
import ast
import fnmatch
from pathlib import Path
import re
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import native_backend_install as installer
import inspector_source_bundle as bundle
import test_inspector_delivery_source as guard

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / '.github/workflows/ledger-transaction-lookup.yml'


class InstallerSourceTests(unittest.TestCase):
    def test_actual_ci_source_guard_rejects_wrong_head_and_dirty_source(self):
        with patch.object(guard, 'WORKFLOW', WORKFLOW):
            guard.DeliverySourceTests().test_actual_workflow_guard_rejects_wrong_commit_and_dirty_source()

    def test_transitive_sources_trigger_both_events(self):
        pending = [ROOT / 'scripts/native_backend_install.py', ROOT / 'scripts/check_ledger_transaction_backend.py',
                   ROOT / 'scripts/tests/test_native_backend_install.py', Path(__file__)]
        expected = {WORKFLOW.relative_to(ROOT).as_posix(), guard.WORKFLOW.relative_to(ROOT).as_posix(),
                    'docs/NATIVE_BACKEND_INSTALL.zh-CN.md'}
        visited = set()
        while pending:
            path = pending.pop()
            if path in visited:continue
            visited.add(path); expected.add(path.relative_to(ROOT).as_posix())
            for node in ast.walk(ast.parse(path.read_bytes())):
                imports = ([n.name for n in node.names] if isinstance(node, ast.Import) else
                           [node.module] if isinstance(node, ast.ImportFrom) and node.module and not node.level else [])
                for name in imports:
                    for directory in (ROOT / 'scripts', ROOT / 'scripts/tests'):
                        child = directory / (name.split('.')[0] + '.py')
                        if child.is_file():pending.append(child)
        blocks = dict(re.findall(r'^  (push|pull_request):\n((?:    [^\n]*\n)+)', WORKFLOW.read_text(encoding='utf-8'), re.M))
        self.assertEqual(set(blocks), {'push', 'pull_request'})
        for block in blocks.values():
            patterns = ast.literal_eval(re.findall(r'^    paths: (.+)$', block, re.M)[0])
            for path in expected:
                self.assertTrue(any(fnmatch.fnmatchcase(path, pattern) for pattern in patterns), path)

    def test_original_native_suite_and_budgets_not_replaced(self):
        workflow = WORKFLOW.read_text(encoding='utf-8')
        for text in ("test_native_backend_install*.py", "test_ledger_transaction*.py", 'timeout-minutes: 20',
                     'check=True, timeout=600', 'cargo +1.98.1 build', '--locked --release',
                     'os: [ubuntu-latest, windows-latest]'):
            self.assertIn(text, workflow)
        self.assertNotIn('continue-on-error', workflow)
        source = (ROOT / 'scripts/check_ledger_transaction_backend.py').read_text(encoding='utf-8')
        self.assertIn('original.run(wallet, worker, recovery)', source)
        self.assertIn('_run(wallet, worker, approved)', source)
        self.assertIn("str(Path(installer.__file__))", source)
        self.assertIn("'--backend-sha256', digest", source)
        self.assertIn('lookup.SingleLinkBackend(approved, digest)._check()', source)
        self.assertIn('assert spawn.call_count == 0', source)

    def test_no_execution_deletion_or_protocol_claim_in_product(self):
        source = Path(installer.__file__).read_bytes()
        tree = ast.parse(source)
        calls = {n.func.attr for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
        self.assertFalse(calls & {'unlink', 'rename', 'replace', 'link', 'mkdir', 'Popen', 'run', 'system', 'call', '_exchange'})
        imports = {alias.name for n in ast.walk(tree) if isinstance(n, ast.Import) for alias in n.names}
        self.assertFalse(imports & {'socket', 'subprocess', 'tkinter', 'requests'})
        self.assertIn(b'os.O_EXCL', source)
        self.assertEqual(installer.MAX_BINARY, 512 * 1024 * 1024)
        self.assertEqual(installer.INSTALL_SECONDS, 300)
        self.assertEqual(len(bundle.SOURCES), 10)
        self.assertNotIn('native_backend_install.py', bundle.SOURCES)


if __name__ == '__main__':
    unittest.main()
