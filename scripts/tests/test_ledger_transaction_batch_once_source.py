"""Source and CI guards, not substitutes for native authorization."""
import ast
import fnmatch
from pathlib import Path
import re
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ledger_transaction_batch_once as once
import inspector_source_bundle as bundle
import test_inspector_delivery_source as guard

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / '.github/workflows/ledger-transaction-batch-once.yml'


class SourceTests(unittest.TestCase):
    def test_exact_head_and_clean_worktree_guard_really_refuses(self):
        with patch.object(guard, 'WORKFLOW', WORKFLOW):
            guard.DeliverySourceTests().test_actual_workflow_guard_rejects_wrong_commit_and_dirty_source()

    def test_shared_decoder_and_old_api_contracts_remain_explicit(self):
        source = (ROOT / 'scripts/ledger_transaction_lookup.py').read_text(encoding='utf-8')
        self.assertEqual(source.count("body[:8] == b'ZVOBLK01'"), 1)
        self.assertIn('def scan_segment_many(', source)
        self.assertIn('def scan_segment(', source)
        self.assertIn('matches.get(txid)', source)
        self.assertEqual(once.ONCE_SECONDS, once.batch.BATCH_SECONDS)
        self.assertEqual(once.batch.MAX_TXIDS, 32)
        self.assertEqual(once.MAX_OUTPUT_BYTES, 65536)
        self.assertEqual(len(bundle.SOURCES), 10)
        self.assertNotIn('ledger_transaction_batch_once.py', bundle.SOURCES)
        old = (ROOT / 'scripts/ledger_transaction_batch.py').read_text(encoding='utf-8')
        self.assertIn('history_scan_count=len(scans)', old)
        self.assertNotIn('scan_once', old)

    def test_no_new_record_parser_or_mutating_entrypoint(self):
        raw = (ROOT / 'scripts/ledger_transaction_batch_once.py').read_bytes()
        calls = {n.func.attr for n in ast.walk(ast.parse(raw)) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
        self.assertTrue({'scan_segment_many', 'LookupVerifier', 'validate_reply'} <= calls)
        self.assertNotIn(b'ZVOBLK01', raw)
        self.assertFalse(calls & {'Popen', 'write_bytes', 'write_text', 'unlink', 'mkdir', 'recover', 'patch', 'authenticate'})

    def test_workflow_covers_transitive_sources(self):
        pending = [ROOT / 'scripts/ledger_transaction_batch_once.py',
                   ROOT / 'scripts/check_ledger_transaction_batch_once_backend.py',
                   ROOT / 'scripts/tests/test_ledger_transaction_batch_once.py', Path(__file__)]
        dependencies = {WORKFLOW.relative_to(ROOT).as_posix(), guard.WORKFLOW.relative_to(ROOT).as_posix(),
                        'docs/LEDGER_TRANSACTION_BATCH_ONCE.zh-CN.md',
                        'integration/orchard/src/pool.rs', 'internal/poolbridge/client.go'}
        seen = set()
        while pending:
            path = pending.pop()
            if path in seen: continue
            seen.add(path); dependencies.add(path.relative_to(ROOT).as_posix())
            for n in ast.walk(ast.parse(path.read_bytes())):
                names = [x.name for x in n.names] if isinstance(n, ast.Import) else (
                    [n.module] if isinstance(n, ast.ImportFrom) and n.module and not n.level else [])
                for name in names:
                    for folder in (ROOT / 'scripts', ROOT / 'scripts/tests'):
                        p = folder / (name.split('.')[0] + '.py')
                        if p.is_file(): pending.append(p)
        blocks = dict(re.findall(r'^  (push|pull_request):\n((?:    [^\n]*\n)+)', WORKFLOW.read_text(), re.M))
        self.assertEqual(set(blocks), {'push', 'pull_request'})
        for block in blocks.values():
            patterns = ast.literal_eval(re.findall(r'^    paths: (.+)$', block, re.M)[0])
            for path in dependencies:
                self.assertTrue(any(fnmatch.fnmatchcase(path, pattern) for pattern in patterns), path)

    def test_genuine_native_pipeline_and_budgets_not_weakened(self):
        text = WORKFLOW.read_text(encoding='utf-8')
        for value in ('persist-credentials: false', 'os: [ubuntu-latest, windows-latest]', 'timeout-minutes: 20',
                      'ref: ${{ github.event.pull_request.head.sha || github.sha }}', 'cargo +1.98.1 build',
                      '--locked --release --features local-funding-lab', 'check=True, timeout=600',
                      "-p 'test_ledger_transaction*.py'", "-p 'test_native_backend_install*.py'"):
            self.assertIn(value, text)
        self.assertNotIn('continue-on-error', text)
        native = (ROOT / 'scripts/check_ledger_transaction_batch_once_backend.py').read_text(encoding='utf-8')
        for value in ('saved_recover(*args, **kwargs)', 'return real_native(self, *params)',
                      'previous.run(wallet, worker, recovery)', "assert len(checks) == 6"):
            self.assertIn(value, native)


if __name__ == '__main__':
    unittest.main()
