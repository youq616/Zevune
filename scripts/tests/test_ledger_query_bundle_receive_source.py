"""Dependency/real CI guards; reuse original worker ownership, never approval."""
import ast
import fnmatch
from pathlib import Path
import re
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ledger_query_bundle_receive as receive
import ledger_query_bundle_receive_desktop as desktop
import test_inspector_delivery_source as guard
import inspector_source_bundle as delivery

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT/'.github/workflows/ledger-query-bundle-receive.yml'


class SourceTests(unittest.TestCase):
    def test_actual_source_guard_refuses_wrong_head_and_dirty_tree(self):
        with patch.object(guard,'WORKFLOW',WORKFLOW):
            guard.DeliverySourceTests().test_actual_workflow_guard_rejects_wrong_commit_and_dirty_source()

    def test_all_transitive_inputs_trigger_push_and_pull_request(self):
        pending=list((ROOT/'scripts/tests').glob('test_ledger_query*.py'))
        pending += [ROOT/'scripts'/name for name in ('ledger_query_bundle_receive.py',
                    'ledger_query_bundle_receive_desktop.py','check_ledger_query_bundle_receive_gui.py',
                    'check_ledger_query_audit.py','check_ledger_query_evidence_compare.py','check_ledger_query_evidence_bundle.py')]
        expected={WORKFLOW.relative_to(ROOT).as_posix(),'docs/LEDGER_QUERY_BUNDLE_RECEIVE.zh-CN.md',
                  guard.WORKFLOW.relative_to(ROOT).as_posix()}; visited=set()
        while pending:
            path=pending.pop()
            if path in visited:continue
            visited.add(path);expected.add(path.relative_to(ROOT).as_posix())
            for node in ast.walk(ast.parse(path.read_bytes())):
                names=([n.name for n in node.names] if isinstance(node,ast.Import) else
                       [node.module] if isinstance(node,ast.ImportFrom) and node.module and not node.level else [])
                for name in names:
                    for folder in (ROOT/'scripts',ROOT/'scripts/tests'):
                        file=folder/(name.split('.')[0]+'.py')
                        if file.is_file():pending.append(file)
        blocks=dict(re.findall(r'^  (push|pull_request):\n((?:    [^\n]*\n)+)',WORKFLOW.read_text(encoding='utf-8'),re.M))
        self.assertEqual(set(blocks),{'push','pull_request'})
        for block in blocks.values():
            patterns=ast.literal_eval(re.findall(r'^    paths: (.+)$',block,re.M)[0])
            for path in expected:self.assertTrue(any(fnmatch.fnmatchcase(path,p) for p in patterns),path)

    def test_original_job_admission_exit_and_poll_tickets_are_reused(self):
        for name in ('start','withdraw_start','poll'):
            self.assertIs(getattr(desktop.ReceiveJob,name),getattr(desktop.lifecycle.LedgerJob,name))
        for name in ('schedule_poll','cancel_poll'):
            self.assertIs(getattr(desktop.Workbench,name),getattr(desktop.lifecycle.Workbench,name))
        self.assertEqual(receive.bundle.MAX_ITEMS,32)
        self.assertEqual(receive.bundle.MAX_BUNDLE_BYTES,1100000)
        self.assertEqual(len(delivery.SOURCES),10)
        self.assertNotIn('ledger_query_bundle_receive.py',delivery.SOURCES)

    def test_only_original_bundle_operations_write_no_queries_or_global_patches(self):
        paths=[ROOT/'scripts/ledger_query_bundle_receive.py',ROOT/'scripts/ledger_query_bundle_receive_desktop.py']
        calls=set()
        for path in paths:
            calls |= {n.func.attr for n in ast.walk(ast.parse(path.read_bytes()))
                      if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute)}
        self.assertTrue({'unpack','verify_directory','unchanged','metadata_unchanged'}<=calls)
        self.assertFalse(calls & {'write_new','write_bytes','mkdir','unlink','rename','run_request','recover','Popen','patch'})
        tree=ast.parse(paths[1].read_bytes())
        self.assertFalse(any(isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                             and n.func.attr in {'update', 'update_idletasks', 'wait_window'}
                             and ast.unparse(n.func.value) in {'root', 'self.root'} for n in ast.walk(tree)))
        worker=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='_execute')
        self.assertFalse({n.id for n in ast.walk(worker) if isinstance(n,ast.Name)} & {'root','tk','ttk','filedialog'})

    def test_dual_platform_workflow_runs_real_receiving_and_prior_integration(self):
        source=WORKFLOW.read_text(encoding='utf-8')
        for item in ('persist-credentials: false','os: [ubuntu-latest, windows-latest]',
                     'ref: ${{ github.event.pull_request.head.sha || github.sha }}',
                     "-p 'test_ledger_query*.py'",'scripts/check_ledger_query_bundle_receive_gui.py',
                     'check=True, timeout=120','scripts/check_ledger_query_evidence_bundle.py'):
            self.assertIn(item,source)
        for item in ('continue-on-error','cargo ','rustup ','pip install'):
            self.assertNotIn(item,source)


if __name__=='__main__':unittest.main()
