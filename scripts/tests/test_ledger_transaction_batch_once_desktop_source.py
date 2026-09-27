"""Source and CI boundary checks for the actual batch desktop, not native success."""
import ast
import fnmatch
from pathlib import Path
import re
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ledger_transaction_batch_once_desktop as desktop
import inspector_source_bundle as bundle
import test_inspector_delivery_source as guard

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / '.github/workflows/ledger-transaction-batch-once-desktop.yml'


class OnceDesktopSourceTests(unittest.TestCase):
    def test_actual_workflow_guard_rejects_wrong_head_and_dirty_source(self):
        with patch.object(guard, 'WORKFLOW', WORKFLOW):
            guard.DeliverySourceTests().test_actual_workflow_guard_rejects_wrong_commit_and_dirty_source()

    def test_all_transitive_sources_trigger_both_events(self):
        pending = [ROOT / 'scripts' / name for name in ('ledger_transaction_batch_once_desktop.py',
                   'check_ledger_transaction_batch_once_gui.py', 'check_ledger_transaction_batch_once_desktop_backend.py')]
        pending += [Path(__file__), ROOT / 'scripts/tests/test_ledger_transaction_batch_once_desktop.py']
        expected = {WORKFLOW.relative_to(ROOT).as_posix(), guard.WORKFLOW.relative_to(ROOT).as_posix(),
                    'docs/LEDGER_TRANSACTION_BATCH_ONCE_DESKTOP.zh-CN.md', 'integration/orchard/src/pool.rs',
                    'internal/poolbridge/client.go'}
        visited = set()
        while pending:
            path = pending.pop()
            if path in visited:continue
            visited.add(path); expected.add(path.relative_to(ROOT).as_posix())
            for node in ast.walk(ast.parse(path.read_bytes())):
                imports = ([n.name for n in node.names] if isinstance(node, ast.Import) else
                           [node.module] if isinstance(node, ast.ImportFrom) and node.module and not node.level else [])
                for name in imports:
                    for directory in (ROOT / 'scripts', ROOT / 'scripts/tests'):
                        child = directory / (name.split('.')[0] + '.py')
                        if child.is_file():pending.append(child)
        text = WORKFLOW.read_text(encoding='utf-8')
        events = dict(re.findall(r'^  (push|pull_request):\n((?:    [^\n]*\n)+)', text, re.M))
        self.assertEqual(set(events), {'push', 'pull_request'})
        for block in events.values():
            patterns = ast.literal_eval(re.findall(r'^    paths: (.+)$', block, re.M)[0])
            for path in expected:
                self.assertTrue(any(fnmatch.fnmatchcase(path, pattern) for pattern in patterns), path)

    def test_original_lifecycle_and_query_implementations_are_reused(self):
        for name in ('start', 'poll', 'withdraw_start'):
            self.assertIs(getattr(desktop.OnceJob, name), getattr(desktop.lifecycle.LedgerJob, name))
        for name in ('review', 'confirm', 'poll', 'copy', 'clear', '_sync_text', '_text_changed',
                     'schedule_poll', 'cancel_poll', 'close', 'changed', 'discard'):
            self.assertIs(getattr(desktop.Workbench, name), getattr(desktop.previous.Workbench, name))
        self.assertIs(desktop.prepare, desktop.previous.prepare)
        self.assertEqual(desktop.previous.MAX_TEXT_CHARS, 32 * 66)
        self.assertEqual(len(bundle.SOURCES), 10)
        self.assertNotIn('ledger_transaction_batch_once_desktop.py', bundle.SOURCES)
        data = (ROOT / 'scripts/ledger_transaction_batch_once_desktop.py').read_bytes()
        self.assertNotIn(b'ZVOBLK01', data)
        for node in ast.walk(ast.parse(data)):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name):
                        self.assertNotIn(target.value.id, {'once', 'previous', 'lifecycle'})

    def test_old_window_defaults_remain_old_contract_and_dynamic_factory(self):
        from test_ledger_transaction_batch_once_desktop import values
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            intent = desktop.prepare(values(Path(tmp).resolve()), 'a'*64)
            old = object.__new__(desktop.previous.Workbench)
            new = object.__new__(desktop.Workbench)
            self.assertIn('再逐ID完整扫描', old._review_description(intent))
            self.assertIn('一次完整记录定位', new._review_description(intent))
            with patch.object(desktop.previous, 'BatchJob', side_effect=RuntimeError('old')) as job:
                with self.assertRaisesRegex(RuntimeError, 'old'):
                    old._new_job(intent)
            self.assertEqual(job.call_count, 1)
            with patch.object(desktop, 'OnceJob', side_effect=RuntimeError('new')) as job:
                with self.assertRaisesRegex(RuntimeError, 'new'):
                    new._new_job(intent)
            self.assertEqual(job.call_count, 1)

    def test_native_pipeline_keeps_real_install_replay_and_original_budget(self):
        text = WORKFLOW.read_text(encoding='utf-8')
        for required in ('persist-credentials: false', 'os: [ubuntu-latest, windows-latest]',
                         'ref: ${{ github.event.pull_request.head.sha || github.sha }}',
                         'cargo +1.98.1 build', '--locked --release --features local-funding-lab',
                         '--bin zevune-pool-recovery', 'check=True, timeout=600', 'timeout-minutes: 20',
                         'check_ledger_transaction_batch_once_gui.py', 'check_ledger_transaction_batch_once_desktop_backend.py'):
            self.assertIn(required, text)
        self.assertNotIn('continue-on-error', text)
        self.assertNotIn('upload-artifact', text)
        driver = (ROOT / 'scripts/check_ledger_transaction_batch_once_desktop_backend.py').read_text(encoding='utf-8')
        for required in ('report = saved_recover(*args, **kwargs)', 'result = real_batch(intent)',
                         'previous.run(wallet, worker, recovery)', '32_real_results_one_pass_rendered_and_copied'):
            self.assertIn(required, driver)


if __name__ == '__main__':unittest.main()
