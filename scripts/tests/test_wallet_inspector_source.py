"""Exact-source guard and complete local import dependency coverage for GUI CI."""
import ast
import re
from pathlib import Path
import unittest
from unittest.mock import patch

import test_wallet_backup_source as established

WORKFLOW = Path(__file__).resolve().parents[2]/'.github/workflows/wallet-inspector-desktop.yml'
ROOTS = ('wallet_inspector_desktop.py', 'check_wallet_inspector_gui.py', 'check_wallet_inspector_backend.py')
TESTS = ('test_wallet_inspector_desktop.py', 'test_wallet_inspector_source.py',
         'test_wallet_backup_source.py', 'test_local_bundle.py', 'test_verify_local_lab.py')


class InspectorSourceTests(established.CatalogSourceTests):
    def setUp(self):
        patcher=patch.object(established,'WORKFLOW',WORKFLOW)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_workflow_pins_checkout_and_runs_source_regressions(self):
        super().test_workflow_pins_checkout_and_runs_source_regressions()
        source=WORKFLOW.read_text()
        for name in TESTS[:2]:
            self.assertEqual(source.count("'scripts/tests/"+name+"'"),2)
            self.assertIn('python -m unittest discover -s scripts/tests -p '+name+' -v',source)
        self.assertIn('python scripts/check_wallet_inspector_gui.py -v',source)
        self.assertIn("'scripts/check_wallet_inspector_backend.py', str(backend)",source)
        self.assertNotIn('continue-on-error',source)

    def test_both_events_include_transitive_imports_and_source_guard_workflow(self):
        repo=WORKFLOW.parents[2]
        scripts=repo/'scripts'
        pending=[scripts/name for name in ROOTS]+[scripts/'tests'/name for name in TESTS]
        dependencies={'.github/workflows/wallet-backup-catalog.yml'}
        while pending:
            path=pending.pop()
            relative=path.relative_to(repo).as_posix()
            if relative in dependencies:continue
            dependencies.add(relative)
            for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
                modules=([a.name for a in node.names] if isinstance(node,ast.Import) else
                         [node.module] if isinstance(node,ast.ImportFrom) and node.level==0 and node.module else [])
                for module in modules:
                    for root in (scripts,scripts/'tests'):
                        candidate=root/(module.split('.')[0]+'.py')
                        if candidate.is_file():pending.append(candidate)
        blocks=dict(re.findall(r'^  (push|pull_request):\n((?:    [^\n]*\n)+)',WORKFLOW.read_text(),re.M))
        self.assertEqual(set(blocks),{'push','pull_request'})
        for event,body in blocks.items():
            paths=ast.literal_eval(re.findall(r'^    paths: (.+)$',body,re.M)[0])
            for dependency in dependencies:
                with self.subTest(event=event,dependency=dependency):self.assertIn(dependency,paths)


if __name__=='__main__':unittest.main()
