"""Source/CI boundaries for the read-only result viewer, not wallet acceptance."""
import ast
import fnmatch
from pathlib import Path
import re
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import inspector_source_bundle as bundle
import test_inspector_delivery_source as guard
import reconciliation_view as view

ROOT=Path(__file__).resolve().parents[2]
WORKFLOW=ROOT/'.github/workflows/reconciliation-view.yml'


class ViewSourceTests(unittest.TestCase):
    def test_original_delivery_payload_contract_is_not_expanded(self):
        self.assertEqual(len(bundle.SOURCES),10)
        self.assertNotIn('reconciliation_view.py',bundle.SOURCES)
        self.assertNotIn('reconciliation_view_desktop.py',bundle.SOURCES)
        self.assertEqual(view.reconciliation.MARKER,'RECONCILE.json')
        self.assertEqual(view.files.MAX_MANIFEST,4096)
        self.assertEqual(view.files.MAX_WALLET,72+256*32948)

    def test_source_guard_executes_wrong_head_and_dirty_refusals(self):
        with patch.object(guard,'WORKFLOW',WORKFLOW):
            guard.DeliverySourceTests().test_actual_workflow_guard_rejects_wrong_commit_and_dirty_source()

    def test_all_static_dependencies_trigger_both_events(self):
        pending=[ROOT/'scripts'/name for name in ('reconciliation_view.py','reconciliation_view_desktop.py',
                'check_reconciliation_view_gui.py','check_reconciliation_view_backend.py')]
        pending += [Path(__file__),ROOT/'scripts/tests/test_reconciliation_view.py']
        expected={WORKFLOW.relative_to(ROOT).as_posix(),'docs/RECONCILIATION_VIEW.zh-CN.md',
                  guard.WORKFLOW.relative_to(ROOT).as_posix()}
        visited=set()
        while pending:
            path=pending.pop()
            if path in visited:continue
            visited.add(path);expected.add(path.relative_to(ROOT).as_posix())
            for node in ast.walk(ast.parse(path.read_bytes())):
                imports=([n.name for n in node.names] if isinstance(node,ast.Import) else
                         [node.module] if isinstance(node,ast.ImportFrom) and node.module and not node.level else [])
                for name in imports:
                    for folder in (ROOT/'scripts',ROOT/'scripts/tests'):
                        source=folder/(name.split('.')[0]+'.py')
                        if source.is_file():pending.append(source)
        blocks=dict(re.findall(r'^  (push|pull_request):\n((?:    [^\n]*\n)+)',WORKFLOW.read_text(encoding='utf-8'),re.M))
        self.assertEqual(set(blocks),{'push','pull_request'})
        for block in blocks.values():
            patterns=ast.literal_eval(re.findall(r'^    paths: (.+)$',block,re.M)[0])
            for path in expected:self.assertTrue(any(fnmatch.fnmatchcase(path,p) for p in patterns),path)

    def test_native_workflow_and_driver_keep_original_crypto_and_all_four_cases(self):
        text=WORKFLOW.read_text(encoding='utf-8')
        for value in ('persist-credentials: false','os: [ubuntu-latest, windows-latest]',
                      'ref: ${{ github.event.pull_request.head.sha || github.sha }}','cargo +1.98.1 build',
                      '--locked --release --features local-funding-lab', '--bin zevune-pool-recovery',
                      'check=True, timeout=600','timeout-minutes: 20','check_reconciliation_view_gui.py -v'):
            self.assertIn(value,text)
        self.assertNotIn('continue-on-error',text)
        self.assertNotIn('upload-artifact',text)
        driver=(ROOT/'scripts/check_reconciliation_view_backend.py').read_text(encoding='utf-8')
        self.assertIn('saved_recover(*args, **kwargs)',driver)
        self.assertIn('original.run(wallet, worker, recovery)',driver)
        self.assertIn("[('pending', True), ('empty-result', False), ('included', False), ('expired', False)]",driver)

    def test_source_audit_uses_explicit_utf8_under_legacy_defaults(self):
        original = Path.read_text
        def legacy_default(path, *args, **kwargs):
            if not args and 'encoding' not in kwargs:
                kwargs['encoding'] = 'cp1252'
            return original(path, *args, **kwargs)
        # Real source and AST, only the implicit text-decoding default changes.
        with patch.object(Path, 'read_text', autospec=True, side_effect=legacy_default):
            self.test_cli_has_no_password_native_or_mutating_interface()

    def test_cli_has_no_password_native_or_mutating_interface(self):
        source=(ROOT/'scripts/reconciliation_view.py').read_text(encoding='utf-8')
        tree=ast.parse(source)
        calls={n.func.attr for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute)}
        self.assertFalse(calls & {'write_bytes','write_text','write_new','mkdir','unlink','rename','recover',
                                 'authenticate','authenticate_descendant','Popen','_exchange'})
        self.assertNotIn('hidden_password',source)


if __name__=='__main__':unittest.main()
