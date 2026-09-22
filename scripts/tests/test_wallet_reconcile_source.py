"""Apply established real Git source-guard tests to reconciliation CI."""
import ast
import re
from pathlib import Path
import unittest
from unittest.mock import patch

import test_wallet_backup_source as established

WORKFLOW = Path(__file__).resolve().parents[2] / '.github/workflows/wallet-reconcile.yml'


class ReconcileSourceTests(established.CatalogSourceTests):
    def setUp(self):
        guard = patch.object(established, 'WORKFLOW', WORKFLOW)
        guard.start()
        self.addCleanup(guard.stop)

    def test_workflow_pins_checkout_and_runs_source_regressions(self):
        super().test_workflow_pins_checkout_and_runs_source_regressions()
        source = WORKFLOW.read_text()
        for name in ('test_wallet_reconcile.py', 'test_wallet_reconcile_transport.py', 'test_wallet_reconcile_source.py'):
            self.assertEqual(source.count("'scripts/tests/" + name + "'"), 2)
            self.assertIn('python -m unittest discover -s scripts/tests -p ' + name + ' -v', source)
        self.assertIn("'scripts/check_wallet_reconcile_backend.py', *backends", source)
        self.assertIn('--bin zevune-wallet-local --bin zevune-pool-worker --bin zevune-pool-recovery', source)
        self.assertNotIn('continue-on-error', source)


    def test_both_events_cover_transitive_local_test_dependencies(self):
        # Inspect source, without importing fixtures or accepting a backend.
        # A fixture-only edit must run the same reconciliation native matrix.
        repository = WORKFLOW.parents[2]
        scripts = repository / 'scripts'
        roots = (scripts, scripts / 'tests')
        pending = [scripts / name for name in
                   ('wallet_reconcile.py', 'check_wallet_reconcile_backend.py')]
        pending += [scripts / 'tests' / name for name in
                    ('test_wallet_reconcile.py', 'test_wallet_reconcile_transport.py', 'test_wallet_reconcile_source.py',
                     'test_wallet_backup_source.py', 'test_local_bundle.py',
                     'test_verify_local_lab.py')]
        dependencies = set()
        while pending:
            path = pending.pop()
            relative = path.relative_to(repository).as_posix()
            if relative in dependencies:
                continue
            dependencies.add(relative)
            for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
                modules = ([item.name for item in node.names] if isinstance(node, ast.Import)
                           else [node.module] if isinstance(node, ast.ImportFrom)
                           and node.level == 0 and node.module else [])
                for module in modules:
                    for root in roots:
                        candidate = root / (module.split('.')[0] + '.py')
                        if candidate.is_file():
                            pending.append(candidate)
        # The separately executed original source test reads this fixed file;
        # patching its WORKFLOW for the inherited tests does not remove that run.
        dependencies.add('.github/workflows/wallet-backup-catalog.yml')
        blocks = dict(re.findall(r'^  (push|pull_request):\n((?:    [^\n]*\n)+)',
                                 WORKFLOW.read_text(encoding='utf-8'), re.M))
        self.assertEqual(set(blocks), {'push', 'pull_request'})
        for event, body in blocks.items():
            lines = re.findall(r'^    paths: (.+)$', body, re.M)
            self.assertEqual(len(lines), 1)
            paths = ast.literal_eval(lines[0])
            self.assertIsInstance(paths, list)
            for dependency in sorted(dependencies):
                with self.subTest(event=event, dependency=dependency):
                    self.assertIn(dependency, paths)


if __name__ == '__main__':
    unittest.main()
