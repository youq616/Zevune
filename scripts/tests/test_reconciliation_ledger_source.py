"""Contract checks for replay-backed reconciliation evidence, not native success."""
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
import reconciliation_ledger_check as checker

ROOT=Path(__file__).resolve().parents[2]
WORKFLOW=ROOT/'.github/workflows/reconciliation-ledger-check.yml'


class LedgerSourceTests(unittest.TestCase):
    def test_source_guard_executes_real_wrong_head_and_dirty_refusals(self):
        with patch.object(guard,'WORKFLOW',WORKFLOW):
            guard.DeliverySourceTests().test_actual_workflow_guard_rejects_wrong_commit_and_dirty_source()

    def test_original_bundle_and_replay_budgets_are_not_changed(self):
        self.assertEqual(len(bundle.SOURCES),10)
        self.assertNotIn('reconciliation_ledger_check.py',bundle.SOURCES)
        self.assertEqual(checker.CHECK_SECONDS,300)
        self.assertEqual(checker.view.reconciliation.MAX_PAYMENT,32768)
        self.assertEqual(checker.files.MAX_WALLET,72+256*32948)

    def test_all_static_dependencies_trigger_both_events(self):
        pending=[ROOT/'scripts/reconciliation_ledger_check.py',ROOT/'scripts/check_reconciliation_ledger_backend.py',
                 Path(__file__),ROOT/'scripts/tests/test_reconciliation_ledger_check.py']
        expected={WORKFLOW.relative_to(ROOT).as_posix(),'docs/RECONCILIATION_LEDGER_CHECK.zh-CN.md',
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
                        child=folder/(name.split('.')[0]+'.py')
                        if child.is_file():pending.append(child)
        blocks=dict(re.findall(r'^  (push|pull_request):\n((?:    [^\n]*\n)+)',WORKFLOW.read_text(encoding='utf-8'),re.M))
        self.assertEqual(set(blocks),{'push','pull_request'})
        for block in blocks.values():
            patterns=ast.literal_eval(re.findall(r'^    paths: (.+)$',block,re.M)[0])
            for path in expected:self.assertTrue(any(fnmatch.fnmatchcase(path,p) for p in patterns),path)

    def test_native_workflow_runs_original_crypto_and_all_four_results(self):
        text=WORKFLOW.read_text(encoding='utf-8')
        for required in ('persist-credentials: false','os: [ubuntu-latest, windows-latest]',
                         'ref: ${{ github.event.pull_request.head.sha || github.sha }}',
                         'cargo +1.98.1 build','--locked --release --features local-funding-lab',
                         '--bin zevune-pool-recovery','check=True, timeout=600','timeout-minutes: 20',
                         'scripts/check_reconciliation_ledger_backend.py'):
            self.assertIn(required,text)
        self.assertNotIn('continue-on-error',text)
        self.assertNotIn('upload-artifact',text)
        driver=(ROOT/'scripts/check_reconciliation_ledger_backend.py').read_text(encoding='utf-8')
        self.assertIn('original_recover(*args, **kwargs)',driver)
        self.assertIn('original.run(wallet,worker,recovery)',driver)
        self.assertIn("[('pending',True),('empty-result',False),('included',False),('expired',False)]",driver)
        self.assertIn('native_run(self,*params)',driver)
        self.assertIn('json.loads(response.stdout) == result',driver)

    def test_original_header_layout_stays_in_sync_with_native_source(self):
        source=(ROOT/'integration/orchard/src/pool.rs').read_text(encoding='utf-8')
        replay=(ROOT/'integration/orchard/src/pool/replay.rs').read_text(encoding='utf-8')
        self.assertIn('const ACTIVE_FILE_MAGIC: &[u8; 8] = b"ZVOPOL03";',source)
        self.assertIn('let mut fixed = [0; 40]',replay)
        self.assertIn('let mut domain = [0; 32]',replay)
        self.assertIn('let mut encoded = [0; 4]',replay)

    def test_product_has_no_wallet_or_file_mutation_entrypoint(self):
        source=(ROOT/'scripts/reconciliation_ledger_check.py').read_text(encoding='utf-8')
        calls={node.func.attr for node in ast.walk(ast.parse(source))
               if isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute)}
        self.assertFalse(calls & {'write_bytes','write_text','mkdir','unlink','rename','recover','backup',
                                 'authenticate','authenticate_descendant','pending','status'})
        self.assertNotIn('hidden_password',source)


if __name__=='__main__':unittest.main()
