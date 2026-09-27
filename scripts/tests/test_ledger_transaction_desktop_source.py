"""Actual source/CI dependency checks, not a successful verifier substitute."""
import ast
import fnmatch
from pathlib import Path
import re
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import ledger_transaction_desktop as desktop
import inspector_source_bundle as bundle
import test_inspector_delivery_source as guard

ROOT=Path(__file__).resolve().parents[2]
WORKFLOW=ROOT/'.github/workflows/ledger-transaction-desktop.yml'


class DesktopSourceTests(unittest.TestCase):
    def test_actual_workflow_head_and_dirty_source_guards(self):
        with patch.object(guard,'WORKFLOW',WORKFLOW):
            guard.DeliverySourceTests().test_actual_workflow_guard_rejects_wrong_commit_and_dirty_source()

    def test_static_dependency_closure_triggers_both_events(self):
        pending=[ROOT/'scripts'/name for name in ('ledger_transaction_desktop.py',
                 'check_ledger_transaction_gui.py','check_ledger_transaction_desktop_backend.py')]
        pending += [Path(__file__),ROOT/'scripts/tests/test_ledger_transaction_desktop.py',
                    ROOT/'scripts/tests/test_ledger_transaction_lookup.py',
                    ROOT/'scripts/tests/test_ledger_transaction_source.py',
                    ROOT/'scripts/tests/test_native_backend_install.py',
                    ROOT/'scripts/tests/test_native_backend_install_source.py']
        dependencies={WORKFLOW.relative_to(ROOT).as_posix(),guard.WORKFLOW.relative_to(ROOT).as_posix(),
                      'docs/LEDGER_TRANSACTION_DESKTOP.zh-CN.md','internal/poolbridge/client.go',
                      'integration/orchard/src/pool.rs'}
        seen=set()
        while pending:
            path=pending.pop()
            if path in seen:continue
            seen.add(path);dependencies.add(path.relative_to(ROOT).as_posix())
            for node in ast.walk(ast.parse(path.read_bytes())):
                imports=([n.name for n in node.names] if isinstance(node,ast.Import) else
                         [node.module] if isinstance(node,ast.ImportFrom) and node.module and not node.level else [])
                for name in imports:
                    for directory in (ROOT/'scripts',ROOT/'scripts/tests'):
                        candidate=directory/(name.split('.')[0]+'.py')
                        if candidate.is_file():pending.append(candidate)
        self.assertIn('scripts/reconciliation_ledger_desktop.py',dependencies)
        blocks=dict(re.findall(r'^  (push|pull_request):\n((?:    [^\n]*\n)+)',WORKFLOW.read_text(encoding='utf-8'),re.M))
        self.assertEqual(set(blocks),{'push','pull_request'})
        for block in blocks.values():
            patterns=ast.literal_eval(re.findall(r'^    paths: (.+)$',block,re.M)[0])
            for path in dependencies:self.assertTrue(any(fnmatch.fnmatchcase(path,p) for p in patterns),path)

    def test_real_native_driver_and_limits_not_replaced(self):
        text=WORKFLOW.read_text(encoding='utf-8')
        for expected in ('persist-credentials: false','os: [ubuntu-latest, windows-latest]',
                         'ref: ${{ github.event.pull_request.head.sha || github.sha }}',
                         'cargo +1.98.1 build','--locked --release --features local-funding-lab',
                         '--bin zevune-pool-recovery','timeout-minutes: 20','check=True, timeout=600',
                         'scripts/check_ledger_transaction_gui.py -v','scripts/check_ledger_transaction_desktop_backend.py',
                         "-p 'test_ledger_transaction*.py'", "-p 'test_native_backend_install*.py'"):
            self.assertIn(expected,text)
        self.assertNotIn('continue-on-error',text)
        driver=(ROOT/'scripts/check_ledger_transaction_desktop_backend.py').read_text(encoding='utf-8')
        self.assertIn('previous.run(wallet,worker,recovery)',driver)
        self.assertIn('result=real_lookup(intent)',driver)
        self.assertIn("[('pending',False),('empty-result',False),('included',True),('expired',False)]",driver)
        self.assertEqual(desktop.lookup.LOOKUP_SECONDS,300)
        self.assertEqual(len(bundle.SOURCES),10)
        self.assertNotIn('ledger_transaction_desktop.py',bundle.SOURCES)

    def test_worker_is_lookup_not_ledger_check_and_never_touches_tk(self):
        source=(ROOT/'scripts/ledger_transaction_desktop.py').read_bytes()
        tree=ast.parse(source)
        worker=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='_execute')
        calls={ast.unparse(n.func) for n in ast.walk(worker) if isinstance(n,ast.Call)}
        self.assertIn('lookup.lookup',calls)
        self.assertIn('present',calls)
        self.assertFalse(any('root' in name or 'tk.' in name or 'checker.check' in name for name in calls))
        # No monkey-patching shared production modules, copy/write, wallet or launch interface.
        calls={ast.unparse(n.func) for n in ast.walk(tree) if isinstance(n,ast.Call)}
        self.assertFalse(calls & {'setattr','exec','eval','subprocess.run','subprocess.Popen','os.system'})
        self.assertNotIn('focus_force',source.decode())


if __name__=='__main__':unittest.main()
