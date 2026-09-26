"""Desktop source/CI guards. Native verification cannot be replaced by these checks."""
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
import reconciliation_ledger_desktop as desktop

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / '.github/workflows/reconciliation-ledger-desktop.yml'


class DesktopSourceTests(unittest.TestCase):
    def test_source_guard_executes_wrong_head_and_dirty_refusals(self):
        with patch.object(guard, 'WORKFLOW', WORKFLOW):
            guard.DeliverySourceTests().test_actual_workflow_guard_rejects_wrong_commit_and_dirty_source()

    def test_static_runtime_and_test_dependencies_trigger_both_events(self):
        pending = [ROOT / 'scripts' / name for name in ('reconciliation_ledger_desktop.py',
                   'check_reconciliation_ledger_desktop_backend.py', 'check_reconciliation_ledger_gui.py')]
        pending += list((ROOT / 'scripts/tests').glob('test_reconciliation_ledger*.py'))
        expected = {WORKFLOW.relative_to(ROOT).as_posix(), guard.WORKFLOW.relative_to(ROOT).as_posix(),
                    'docs/RECONCILIATION_LEDGER_DESKTOP.zh-CN.md',
                    'integration/orchard/src/bin/zevune-pool-recovery.rs'}
        visited = set()
        while pending:
            path = pending.pop()
            if path in visited:continue
            visited.add(path)
            expected.add(path.relative_to(ROOT).as_posix())
            for node in ast.walk(ast.parse(path.read_bytes())):
                imports = ([item.name for item in node.names] if isinstance(node, ast.Import) else
                           [node.module] if isinstance(node, ast.ImportFrom) and node.module and not node.level else [])
                for name in imports:
                    for folder in (ROOT / 'scripts', ROOT / 'scripts/tests'):
                        child = folder / (name.split('.')[0] + '.py')
                        if child.is_file():pending.append(child)
        blocks = dict(re.findall(r'^  (push|pull_request):\n((?:    [^\n]*\n)+)', WORKFLOW.read_text(encoding='utf-8'), re.M))
        self.assertEqual(set(blocks), {'push', 'pull_request'})
        for block in blocks.values():
            patterns = ast.literal_eval(re.findall(r'^    paths: (.+)$', block, re.M)[0])
            for path in expected:
                self.assertTrue(any(fnmatch.fnmatchcase(path, pattern) for pattern in patterns), path)

    def test_both_platforms_real_tk_and_unchanged_native_budget(self):
        text = WORKFLOW.read_text(encoding='utf-8')
        for required in ('persist-credentials: false', 'os: [ubuntu-latest, windows-latest]',
                         'ref: ${{ github.event.pull_request.head.sha || github.sha }}',
                         'cargo +1.98.1 build', '--locked --release --features local-funding-lab',
                         '--bin zevune-pool-recovery', 'check=True, timeout=600', 'timeout-minutes: 20',
                         'check_reconciliation_ledger_desktop_backend.py',
                         'xvfb-run -a python -B scripts/check_reconciliation_ledger_gui.py -v'):
            self.assertIn(required, text)
        self.assertNotIn('continue-on-error', text)
        self.assertNotIn('upload-artifact', text)

    def test_native_driver_retains_original_checks_and_actual_success_before_delay(self):
        text = (ROOT / 'scripts/check_reconciliation_ledger_desktop_backend.py').read_text(encoding='utf-8')
        self.assertIn('original_recover(*args, **kwargs)', text)
        self.assertIn('previous.run(wallet, worker, recovery)', text)
        self.assertIn('result = actual_check(intent)', text)
        self.assertIn("[('pending', True), ('empty-result', False), ('included', False), ('expired', False)]", text)
        self.assertIn("['stale_result', 'close_during_real_check']", text)

    def test_no_new_wallet_operation_or_expansion_of_fixed_delivery(self):
        self.assertEqual(desktop.checker.CHECK_SECONDS, 300)
        self.assertEqual(len(bundle.SOURCES), 10)
        self.assertNotIn('reconciliation_ledger_desktop.py', bundle.SOURCES)
        source = (ROOT / 'scripts/reconciliation_ledger_desktop.py').read_bytes()
        tree = ast.parse(source)
        calls = {node.func.attr for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
        self.assertFalse(calls & {'write_bytes', 'write_text', 'mkdir', 'unlink', 'rename', 'recover',
                                 'authenticate', 'authenticate_descendant', '_exchange', 'active', 'Popen'})
        worker = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == '_execute')
        worker_source = ast.get_source_segment(source.decode(), worker)
        self.assertNotIn('tkinter', worker_source)
        self.assertNotIn('root.', worker_source)
        self.assertIn('checker.check(intent)', worker_source)


if __name__ == '__main__':
    unittest.main()
