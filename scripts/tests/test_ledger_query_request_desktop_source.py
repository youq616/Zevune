"""Task UI dependency/contract checks, never substitutes for native execution."""
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
import ledger_query_request_desktop as desktop

ROOT=Path(__file__).resolve().parents[2]
WORKFLOW=ROOT/'.github/workflows/ledger-query-request-desktop.yml'


class SourceTests(unittest.TestCase):
    def test_actual_wrong_head_and_dirty_source_guards(self):
        with patch.object(guard,'WORKFLOW',WORKFLOW):
            guard.DeliverySourceTests().test_actual_workflow_guard_rejects_wrong_commit_and_dirty_source()

    def test_all_static_dependencies_trigger_both_events(self):
        pending=[ROOT/'scripts/ledger_query_request_desktop.py',ROOT/'scripts/check_ledger_query_request_gui.py',
                 ROOT/'scripts/check_ledger_query_request_desktop_backend.py',
                 ROOT/'scripts/check_ledger_transaction_batch_once_gui.py',Path(__file__),
                 ROOT/'scripts/tests/test_ledger_query_request_desktop.py']
        # The workflow runs both complete families, not merely this module.
        pending+=list((ROOT/'scripts/tests').glob('test_ledger_query_request*.py'))
        pending+=list((ROOT/'scripts/tests').glob('test_ledger_transaction*.py'))
        pending+=list((ROOT/'scripts/tests').glob('test_native_backend_install*.py'))
        expected={WORKFLOW.relative_to(ROOT).as_posix(),guard.WORKFLOW.relative_to(ROOT).as_posix(),
                  'docs/LEDGER_QUERY_REQUEST_DESKTOP.zh-CN.md'}
        visited=set()
        while pending:
            path=pending.pop()
            if path in visited:continue
            visited.add(path);expected.add(path.relative_to(ROOT).as_posix())
            for node in ast.walk(ast.parse(path.read_bytes())):
                names=([n.name for n in node.names] if isinstance(node,ast.Import) else
                       [node.module] if isinstance(node,ast.ImportFrom) and node.module and not node.level else [])
                for name in names:
                    for folder in (ROOT/'scripts',ROOT/'scripts/tests'):
                        child=folder/(name.split('.')[0]+'.py')
                        if child.is_file():pending.append(child)
        events=dict(re.findall(r'^  (push|pull_request):\n((?:    [^\n]*\n)+)',WORKFLOW.read_text(encoding='utf-8'),re.M))
        self.assertEqual(set(events),{'push','pull_request'})
        for text in events.values():
            patterns=ast.literal_eval(re.findall(r'^    paths: (.+)$',text,re.M)[0])
            for path in expected:self.assertTrue(any(fnmatch.fnmatchcase(path,p) for p in patterns),path)

    def test_confirm_poll_copy_and_ownership_are_original_implementations(self):
        for name in ('confirm','poll','copy','schedule_poll','cancel_poll','close','withdraw_start'):
            if name=='withdraw_start':
                self.assertIs(desktop.RequestJob.withdraw_start,desktop.lifecycle.LedgerJob.withdraw_start)
            else:self.assertIs(getattr(desktop.Workbench,name),getattr(desktop.previous.Workbench,name))
        self.assertIs(desktop.RequestJob.start,desktop.lifecycle.LedgerJob.start)
        self.assertIs(desktop.RequestJob.poll,desktop.lifecycle.LedgerJob.poll)
        self.assertIsNot(desktop.Workbench._sync_text,desktop.previous.Workbench._sync_text)
        self.assertEqual(len(bundle.SOURCES),10)
        self.assertNotIn('ledger_query_request_desktop.py',bundle.SOURCES)

    def test_real_native_pipeline_and_timeouts_preserved(self):
        text=WORKFLOW.read_text(encoding='utf-8')
        for item in ('persist-credentials: false','os: [ubuntu-latest, windows-latest]',
                     'ref: ${{ github.event.pull_request.head.sha || github.sha }}',
                     'cargo +1.98.1 build','--locked --release --features local-funding-lab',
                     'timeout-minutes: 20','check=True, timeout=600',
                     'scripts/check_ledger_query_request_desktop_backend.py','check_ledger_transaction_batch_once_gui.py'):
            self.assertIn(item,text)
        self.assertNotIn('continue-on-error',text)
        native=(ROOT/'scripts/check_ledger_query_request_desktop_backend.py').read_text(encoding='utf-8')
        for item in ('report = saved_recover(*args, **kwargs)', 'previous.run(wallet, worker, recovery)',
                     'response = task_run(*params)', 'return native(self, *params)', 'assert len(checks) == 7'):
            self.assertIn(item,native)

    def test_worker_has_no_tk_and_product_has_no_writes_or_global_patch(self):
        source=(ROOT/'scripts/ledger_query_request_desktop.py').read_bytes();tree=ast.parse(source)
        calls={n.func.attr for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute)}
        self.assertFalse(calls & {'write_bytes','write_text','unlink','rename','recover','create','send','Popen','patch'})
        self.assertTrue({'run_request','unchanged','load'}<=calls)
        execute=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='_execute')
        names={n.id for n in ast.walk(execute) if isinstance(n,ast.Name)}
        self.assertFalse(names & {'tk','ttk','root','filedialog'})


if __name__=='__main__':unittest.main()
