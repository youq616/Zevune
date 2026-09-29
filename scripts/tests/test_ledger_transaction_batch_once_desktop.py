"""Real worker refusals and pure presentation metadata, never fake native success."""
from dataclasses import replace
import contextlib
import copy
import io
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ledger_transaction_batch_once_desktop as desktop
from test_ledger_restore import pin


def values(root):
    return dict(journal=str(root / 'journal'), checkpoint=pin(2), genesis_sha256='d' * 64,
                backend=str(Path(sys.executable).resolve()), backend_sha256='b' * 64)


def display_fixture(intent):
    """Public display contract only: never inject this into a job/verifier."""
    p = desktop.once.single.Checkpoint.parse(intent.source.checkpoint)
    rows = [dict(txid=txid, historical_inclusion_verified=False, state='absent_from_verified_history',
                 occurrence=None, subsequent_record_count=None) for txid in intent.txids]
    rows[0].update(historical_inclusion_verified=True, state='included_in_verified_history',
                   occurrence=dict(height=1, record_block_id='e' * 64, transaction_index=0,
                                   segment='00000000.journal', record_offset=0, transaction_bytes=100),
                   subsequent_record_count=p.height - 1)
    return dict(format='zevune-ledger-transaction-batch-once-1', checkpoint=p.encoded,
                checkpoint_height=p.height, checkpoint_app_hash=p.app_hash,
                genesis_sha256=intent.source.genesis_sha256, native_backend_sha256=intent.source.backend_sha256,
                query_count=len(rows), included_count=1, absent_count=len(rows)-1, results=rows,
                batch_complete=True, ledger_replayed=True, native_replay_count=1, history_scan_count=1,
                historical_search_complete=True, scanned_records=p.height,
                scanned_transactions=1, ledger_bytes=p.length, source_files_unchanged=True,
                current_chain_height=None, broadcast_status='unknown', settlement_status='unknown',
                wallet_authenticated=False, recipient_or_amount_verified=False, finality_verified=False,
                retry_authorized=False, portable_proof_generated=False, real_funds_allowed=False)


class InputDisplayTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.ids = ('a' * 64, 'c' * 64)
        self.intent = desktop.prepare(values(self.root), '\n'.join(self.ids))
        self.result = display_fixture(self.intent)

    def test_multiline_limits_order_and_optional_terminal_newline(self):
        for count in (1, 32):
            ids = tuple(f'{i:064x}' for i in range(count))
            for sep in ('\n', '\r\n'):
                for ending in ('', sep):
                    self.assertEqual(desktop.parse_ids(sep.join(ids)+ending), ids)
        self.assertEqual(desktop.parse_ids('\n'.join(reversed(self.ids))), tuple(reversed(self.ids)))

    def test_no_whitespace_repair_dedup_or_unicode_separators(self):
        for text in ('', '\n', 'a'*64+'\n\n', 'a'*64+'\n'+'a'*64, ' '+'a'*64,
                     'a'*64+' ', 'a'*64+'\r', 'a'*64+'\u2028'+'c'*64, 'A'*64, None,
                     '\n'.join(f'{i:064x}' for i in range(33)), 'x'*10000):
            with self.subTest(text=repr(text)[:75]), self.assertRaises(ValueError):
                desktop.parse_ids(text)

    def test_review_lists_all_pins_and_ids_without_io(self):
        with patch.object(desktop.once.single.view, '_chain', side_effect=AssertionError('no IO')):
            intent = desktop.prepare(values(self.root), '\r\n'.join(self.ids))
            text = desktop.review_text(intent)
        for item in (*values(self.root).values(), *self.ids):
            self.assertIn(item, text)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_pure_display_is_immutable_and_bound_to_all_ids(self):
        shown = desktop.present(self.result, self.intent)
        self.assertIs(type(shown), desktop.OnceDisplay)
        self.assertIsNone(shown.txid)
        self.assertEqual(shown.txids, self.ids)
        self.result['results'][0]['txid'] = '0'*64
        self.assertEqual(shown.txids, self.ids)
        with self.assertRaises(AttributeError):
            shown.txids = ()

    def test_fixed_fields_are_required_and_strictly_typed(self):
        variable = {'results', 'included_count', 'absent_count', 'scanned_transactions'}
        for key, value in self.result.items():
            bad = copy.deepcopy(self.result); bad.pop(key)
            with self.subTest(missing=key), self.assertRaises(ValueError):desktop.present(bad, self.intent)
            if key not in variable:
                bad = copy.deepcopy(self.result)
                bad[key] = int(value) if type(value) is bool else (True if type(value) is int else 'wrong')
                with self.subTest(changed=key), self.assertRaises(ValueError):desktop.present(bad, self.intent)
        with self.assertRaises(ValueError):desktop.present(dict(self.result, extra=True), self.intent)

    def test_order_duplicates_missing_rows_and_wrong_counts_are_refused(self):
        cases = [dict(self.result, results=list(reversed(self.result['results']))),
                 dict(self.result, results=self.result['results'][:1]),
                 dict(self.result, results=[self.result['results'][0]]*2),
                 dict(self.result, results=tuple(self.result['results'])),
                 dict(self.result, included_count=True), dict(self.result, absent_count=0),
                 dict(self.result, included_count=0, absent_count=2),
                 dict(self.result, scanned_transactions=True)]
        for bad in cases:
            with self.assertRaises(ValueError):desktop.present(bad, self.intent)

    def test_every_row_and_occurrence_uses_original_strict_contract(self):
        for key, value in (('txid','0'*64), ('historical_inclusion_verified',1), ('state','paid'),
                           ('occurrence',None), ('subsequent_record_count',True)):
            bad = copy.deepcopy(self.result); bad['results'][0][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):desktop.present(bad, self.intent)
        for key, value in (('height',3),('transaction_index',16),('segment','../../x'),
                           ('record_offset',-1),('record_block_id','bad'),('transaction_bytes',0)):
            bad = copy.deepcopy(self.result); bad['results'][0]['occurrence'][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):desktop.present(bad, self.intent)
        bad = copy.deepcopy(self.result); bad['results'][0]['extra'] = 'untrusted'
        with self.assertRaises(ValueError):desktop.present(bad, self.intent)

    def test_forged_intents_and_incomplete_results_are_refused(self):
        for invalid in (None, {}, replace(self.intent, source=None), replace(self.intent, txids=())):
            with self.assertRaises(ValueError):desktop.present(self.result, invalid)
        for invalid in (None, {}, {'batch_complete':True}):
            with self.assertRaises(ValueError):desktop.present(invalid, self.intent)

    def test_maximum_batch_display_is_bounded(self):
        intent = desktop.prepare(values(self.root), '\n'.join(f'{i:064x}' for i in range(32)))
        shown = desktop.present(display_fixture(intent), intent)
        self.assertLessEqual(len(shown.text.encode()), desktop.once.MAX_OUTPUT_BYTES)
        self.assertEqual(len(shown.txids), 32)

    def test_old_and_new_profiles_refuse_each_other_even_for_one_id(self):
        from test_ledger_transaction_batch_desktop import display_fixture as old_fixture
        for count in (1, 2):
            intent = desktop.prepare(values(self.root), '\n'.join(f'{i:064x}' for i in range(count)))
            with self.assertRaises(ValueError):
                desktop.present(old_fixture(intent), intent)
            with self.assertRaises(ValueError):
                desktop.previous.present(display_fixture(intent), intent)

    def test_projection_never_changes_result_and_preserves_one_scan_type(self):
        original = copy.deepcopy(self.result)
        shown = desktop.present(self.result, self.intent)
        self.assertEqual(original, self.result)
        self.assertIn('一次记录扫描', shown.text)
        self.assertNotIn('每个交易ID分别完整扫描', shown.text)
        for bad in (True, False, 0, 2, 32, None):
            with self.assertRaises(ValueError):
                desktop.present(dict(self.result, history_scan_count=bad), self.intent)

    def test_old_counter_names_cannot_coexist_with_new_contract(self):
        for key in ('scanned_records_per_query', 'scanned_transactions_per_query'):
            with self.assertRaises(ValueError):
                desktop.present(dict(self.result, **{key: 2}), self.intent)

    def test_absence_is_not_replay_failure_or_payment_permission(self):
        result = copy.deepcopy(self.result)
        result['results'][0].update(historical_inclusion_verified=False, state='absent_from_verified_history',
                                    occurrence=None, subsequent_record_count=None)
        result.update(included_count=0, absent_count=len(self.intent.txids))
        shown = desktop.present(result, self.intent)
        self.assertEqual(shown.txids, self.intent.txids)
        self.assertIn('不能据此重试付款', shown.text)
        self.assertIn('结算状态仍未知', shown.text)


class JobTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.intent = desktop.prepare(values(Path(self.temp.name).resolve()), 'a'*64)

    def finished(self, job):
        job.thread.join(timeout=3)
        self.assertFalse(job.thread.is_alive())
        completion = job.poll()
        self.assertIsNotNone(completion)
        self.assertIsNone(completion.result)
        self.assertIsNone(job.poll())

    def test_missing_files_use_real_batch_refusal_and_release_request(self):
        with patch.object(subprocess, 'Popen', side_effect=AssertionError('no native process')):
            job = desktop.OnceJob(self.intent); job.start(); self.finished(job)
        self.assertFalse(job.thread.daemon)
        self.assertIsNone(job.request[0])

    def test_withdrawal_before_admission_never_executes(self):
        with patch.object(desktop.once,'lookup_batch_once',side_effect=AssertionError('withdrawn')) as run:
            job=desktop.OnceJob(self.intent); job.thread.start()
            self.assertIsNone(job.poll()); job.withdraw_start(); self.finished(job)
            self.assertEqual(run.call_count,0)

    def test_completion_event_alone_does_not_allow_idle(self):
        original=desktop._execute
        reached,release=threading.Event(),threading.Event()
        def delayed(*args):
            original(*args); reached.set(); release.wait(timeout=3)
        job=None
        try:
            with patch.object(desktop,'_execute',side_effect=delayed):
                job=desktop.OnceJob(self.intent); job.start()
                self.assertTrue(reached.wait(timeout=2)); self.assertTrue(job.completed.is_set())
                self.assertIsNone(job.poll()); release.set(); self.finished(job)
        finally:
            release.set()
            if job is not None:job.thread.join(timeout=3)

    def test_failure_and_queue_loss_are_redacted_not_partial_success(self):
        for error in (ValueError('PRIVATE'), KeyboardInterrupt('PRIVATE')):
            output=io.StringIO()
            with patch.object(desktop.once,'lookup_batch_once',side_effect=error), \
                    contextlib.redirect_stdout(output),contextlib.redirect_stderr(output):
                job=desktop.OnceJob(self.intent); job.start(); self.finished(job)
            self.assertEqual(output.getvalue(),'')
        job=desktop.OnceJob(self.intent)
        with patch.object(job.channel,'put_nowait',side_effect=MemoryError('PRIVATE')):
            job.start(); self.finished(job)

    def test_start_failure_remains_owned_and_does_not_retry(self):
        job=desktop.OnceJob(self.intent)
        with patch.object(job.thread,'start',side_effect=RuntimeError('PRIVATE')):
            with self.assertRaises(RuntimeError):job.start()
        self.assertIsNone(job.request[0]); self.assertTrue(job.start_attempted)
        self.assertIsNone(job.poll())
        with self.assertRaises(ValueError):job.start()

    def test_real_os_bootstrap_interruption_withdraws_unadmitted_batch(self):
        job=desktop.OnceJob(self.intent)
        reached,release,ended=threading.Event(),threading.Event(),threading.Event()
        original=job.thread._bootstrap_inner
        def late():
            reached.set()
            try:release.wait(timeout=3); original()
            finally:ended.set()
        def interrupt(*args,**kwargs):
            assert reached.wait(timeout=2)
            raise KeyboardInterrupt('PRIVATE')
        job.thread._bootstrap_inner=late; job.thread._started.wait=interrupt
        try:
            with patch.object(desktop.once,'lookup_batch_once',side_effect=AssertionError('withdrawn')) as run:
                with self.assertRaises(KeyboardInterrupt):job.start()
                self.assertIsNone(job.thread.ident); self.assertIsNone(job.poll())
                release.set(); self.assertTrue(ended.wait(timeout=2)); self.finished(job)
                self.assertEqual(run.call_count,0)
        finally:
            release.set(); self.assertTrue(ended.wait(timeout=3)); job.thread.join(timeout=3)

    def test_job_rejects_invalid_type_before_thread_construction(self):
        with patch.object(threading,'Thread',side_effect=AssertionError('no thread')):
            with self.assertRaises(ValueError):desktop.OnceJob(None)

    def test_help_and_unknown_arguments_are_redacted(self):
        for tail,status in ((['--help'],0),(['--secret','PRIVATE'],64),(['--no-real-f'],64)):
            result=subprocess.run([sys.executable,'-B',desktop.__file__,*tail],capture_output=True,timeout=10)
            self.assertEqual(result.returncode,status)
            self.assertNotIn(b'PRIVATE',result.stdout+result.stderr)


if __name__=='__main__':unittest.main()
