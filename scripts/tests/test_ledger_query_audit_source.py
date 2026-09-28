"""Audit dependency closure and prohibition checks; not a funds/security approval."""
import ast
import fnmatch
from pathlib import Path
import re
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import ledger_query_audit as audit
import inspector_source_bundle as bundle
import test_inspector_delivery_source as guard

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT/'.github/workflows/ledger-query-audit.yml'


class SourceTests(unittest.TestCase):
    def test_real_head_and_dirty_source_guard(self):
        with patch.object(guard,'WORKFLOW',WORKFLOW):
            guard.DeliverySourceTests().test_actual_workflow_guard_rejects_wrong_commit_and_dirty_source()

    def test_all_transitive_files_trigger_both_events(self):
        pending=[ROOT/'scripts/ledger_query_audit.py',ROOT/'scripts/check_ledger_query_audit.py',
                 ROOT/'scripts/tests/test_ledger_query_audit.py',ROOT/'scripts/tests/test_ledger_query_request.py',
                 Path(__file__)]
        expected={WORKFLOW.relative_to(ROOT).as_posix(),guard.WORKFLOW.relative_to(ROOT).as_posix(),
                  'docs/LEDGER_QUERY_AUDIT.zh-CN.md'}
        visited=set()
        while pending:
            path=pending.pop()
            if path in visited: continue
            visited.add(path); expected.add(path.relative_to(ROOT).as_posix())
            for node in ast.walk(ast.parse(path.read_bytes())):
                names=([item.name for item in node.names] if isinstance(node,ast.Import) else
                       [node.module] if isinstance(node,ast.ImportFrom) and node.module and not node.level else [])
                for name in names:
                    for directory in (ROOT/'scripts',ROOT/'scripts/tests'):
                        item=directory/(name.split('.')[0]+'.py')
                        if item.is_file(): pending.append(item)
        text=WORKFLOW.read_text(encoding='utf-8')
        events=dict(re.findall(r'^  (push|pull_request):\n((?:    [^\n]*\n)+)',text,re.M))
        self.assertEqual(set(events),{'push','pull_request'})
        for body in events.values():
            patterns=ast.literal_eval(re.findall(r'^    paths: (.+)$',body,re.M)[0])
            for name in expected: self.assertTrue(any(fnmatch.fnmatchcase(name,p) for p in patterns),name)

    def test_product_has_no_query_backend_ledger_or_mutating_source_action(self):
        tree=ast.parse((ROOT/'scripts/ledger_query_audit.py').read_bytes())
        calls={n.func.attr for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute)}
        self.assertFalse(calls & {'run_request','lookup_batch_once','archive_snapshot','Popen','system',
                                 'exec','eval','unlink','rename','recover','authenticate','send'})
        self.assertTrue({'write_new','decode','load','unchanged'} <= calls)
        self.assertEqual(len(bundle.SOURCES),10)
        self.assertNotIn('ledger_query_audit.py',bundle.SOURCES)
        self.assertEqual(audit.task.MAX_REQUEST_BYTES,8192)
        self.assertEqual(audit.MAX_REPORT_BYTES,16384)
        self.assertEqual(audit.task.once.ONCE_SECONDS,300)

    def test_offline_both_platforms_deny_execution_in_real_child_process(self):
        text=WORKFLOW.read_text(encoding='utf-8')
        for item in ('persist-credentials: false','os: [ubuntu-latest, windows-latest]',
                     'ref: ${{ github.event.pull_request.head.sha || github.sha }}',
                     'python -B scripts/check_ledger_query_audit.py',"-p 'test_ledger_query_request.py'"):
            self.assertIn(item,text)
        self.assertNotIn('continue-on-error',text)
        self.assertNotIn('cargo ',text)  # This read-only audit must not need a backend build.
        driver=(ROOT/'scripts/check_ledger_query_audit.py').read_text(encoding='utf-8')
        for item in ('sys.addaudithook(guard)',"assert not attempts", "'subprocess.Popen'",
                     "event.startswith('socket.')", "name.endswith('.journal')", "name == 'genesis'"):
            self.assertIn(item,driver)


if __name__=='__main__':
    unittest.main()
