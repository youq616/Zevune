"""Dependency closure and executed CI source guard; not independent approval."""
import ast
import fnmatch
from pathlib import Path
import re
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import ledger_query_evidence_desktop as desktop
import inspector_source_bundle as bundle
import test_inspector_delivery_source as guard

ROOT=Path(__file__).resolve().parents[2]
WORKFLOW=ROOT/'.github/workflows/ledger-query-evidence-desktop.yml'


class SourceTests(unittest.TestCase):
    def test_actual_guard_rejects_wrong_commit_and_dirty_source(self):
        with patch.object(guard,'WORKFLOW',WORKFLOW):
            guard.DeliverySourceTests().test_actual_workflow_guard_rejects_wrong_commit_and_dirty_source()

    def test_transitive_dependencies_trigger_both_events(self):
        pending=[ROOT/'scripts/ledger_query_evidence_desktop.py',ROOT/'scripts/check_ledger_query_evidence_gui.py',
                 ROOT/'scripts/check_ledger_query_audit.py',ROOT/'scripts/check_ledger_query_evidence_compare.py']
        pending+=list((ROOT/'scripts/tests').glob('test_ledger_query*.py'))
        expected={WORKFLOW.relative_to(ROOT).as_posix(),'docs/LEDGER_QUERY_EVIDENCE_DESKTOP.zh-CN.md',
                  guard.WORKFLOW.relative_to(ROOT).as_posix()}
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
                        candidate=folder/(name.split('.')[0]+'.py')
                        if candidate.is_file():pending.append(candidate)
        events=dict(re.findall(r'^  (push|pull_request):\n((?:    [^\n]*\n)+)',WORKFLOW.read_text(encoding='utf-8'),re.M))
        self.assertEqual(set(events),{'push','pull_request'})
        for block in events.values():
            patterns=ast.literal_eval(re.findall(r'^    paths: (.+)$',block,re.M)[0])
            for path in expected:self.assertTrue(any(fnmatch.fnmatchcase(path,p) for p in patterns),path)

    def test_product_uses_original_comparison_without_execution_or_new_parser(self):
        source=(ROOT/'scripts/ledger_query_evidence_desktop.py').read_bytes()
        tree=ast.parse(source)
        calls={n.func.attr for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute)}
        self.assertTrue({'compare','render','validate_source'}<=calls)
        self.assertFalse(calls & {'loads','load','write_new','write_bytes','unlink','rename','run_request',
                                 'Popen','Thread','after','update','wait_window','main','patch'})
        self.assertEqual(len(bundle.SOURCES),10)
        self.assertNotIn('ledger_query_evidence_desktop.py',bundle.SOURCES)

    def test_both_platforms_require_actual_gui_and_source_check(self):
        text=WORKFLOW.read_text(encoding='utf-8')
        for value in ('os: [ubuntu-latest, windows-latest]','persist-credentials: false',
                      'ref: ${{ github.event.pull_request.head.sha || github.sha }}',
                      "-p 'test_ledger_query*.py'",'scripts/check_ledger_query_evidence_gui.py',
                      'check=True, timeout=120','scripts/check_ledger_query_audit.py',
                      'scripts/check_ledger_query_evidence_compare.py','git diff --exit-code HEAD --'):
            self.assertIn(value,text)
        for value in ('continue-on-error','cargo ','rustup ','pip install','upload-artifact'):
            self.assertNotIn(value,text)

    def test_headless_help_does_not_import_tk_at_module_load(self):
        tree=ast.parse((ROOT/'scripts/ledger_query_evidence_desktop.py').read_bytes())
        top_imports=[n for n in tree.body if isinstance(n,(ast.Import,ast.ImportFrom))]
        self.assertFalse(any('tkinter' in ast.unparse(n) for n in top_imports))
        self.assertEqual(desktop.comparison.MAX_OUTPUT_BYTES,32768)


if __name__=='__main__':unittest.main()
