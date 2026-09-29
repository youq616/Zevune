"""Real worker refusal/lifecycle tests. No successful ledger verifier substitute."""
import contextlib
import io
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ledger_transaction_desktop as desktop
from test_ledger_restore import pin


def values(root):
    return dict(journal=str(root / 'ledger'), checkpoint=pin(), genesis_sha256=(b'd' * 32).hex(),
                txid='a' * 64, backend=str(Path(sys.executable).resolve()), backend_sha256='b' * 64)


class LookupJobTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.intent = desktop.lookup.prepare(values(self.root))

    def finish(self, job):
        job.thread.join(timeout=3)
        self.assertFalse(job.thread.is_alive())
        outcome = job.poll()
        self.assertIsNotNone(outcome)
        self.assertIsNone(outcome.result)
        self.assertIsNone(job.poll())

    def test_real_missing_files_refuse_without_native_launch(self):
        with patch.object(subprocess, 'Popen', side_effect=AssertionError('no native process')):
            job = desktop.LookupJob(self.intent)
            self.assertFalse(job.thread.daemon)
            job.start()
            self.finish(job)
        self.assertIsNone(job.request[0])
        self.assertEqual(list(self.root.iterdir()), [])

    def test_job_validation_precedes_thread_construction(self):
        with patch.object(threading, 'Thread', side_effect=AssertionError('no thread')):
            for invalid in (None, {}, 'invalid'):
                with self.assertRaises(ValueError):desktop.LookupJob(invalid)

    def test_no_execution_before_admission_and_withdrawn_request_never_runs(self):
        with patch.object(desktop.lookup, 'lookup', side_effect=AssertionError('no admitted job')) as call:
            job = desktop.LookupJob(self.intent)
            job.thread.start()  # Real thread blocked on the actual admission gate.
            self.assertIsNone(job.poll())
            self.assertFalse(job.completed.wait(timeout=0.03))
            job.withdraw_start()
            self.finish(job)
            self.assertEqual(call.call_count, 0)

    def test_duplicate_start_refused(self):
        job = desktop.LookupJob(self.intent)
        job.start()
        with self.assertRaises(ValueError):job.start()
        self.finish(job)

    def test_exceptions_and_keyboard_interrupt_never_reach_thread_excepthook(self):
        for failure in (RuntimeError('PRIVATE'), KeyboardInterrupt('PRIVATE'), SystemExit('PRIVATE')):
            out = io.StringIO()
            with patch.object(desktop.lookup, 'lookup', side_effect=failure), \
                    patch.object(threading, 'excepthook') as hook, \
                    contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
                job = desktop.LookupJob(self.intent)
                job.start()
                self.finish(job)
            self.assertEqual(out.getvalue(), '')
            self.assertEqual(hook.call_count, 0)
            self.assertIsNone(job.request[0])

    def test_completion_event_does_not_replace_actual_thread_exit(self):
        original = desktop._execute
        release, reached = threading.Event(), threading.Event()
        def delayed(*args):
            original(*args)
            reached.set()
            release.wait(timeout=3)
        try:
            with patch.object(desktop, '_execute', side_effect=delayed):
                job = desktop.LookupJob(self.intent)
                job.start()
                self.assertTrue(reached.wait(timeout=2))
                self.assertTrue(job.completed.is_set())
                self.assertIsNone(job.poll())
                release.set()
                self.finish(job)
        finally:
            release.set()
            job.thread.join(timeout=3)

    def test_queue_delivery_failure_still_acknowledges_failed_completion(self):
        job = desktop.LookupJob(self.intent)
        with patch.object(job.channel, 'put_nowait', side_effect=MemoryError('PRIVATE')):
            job.start()
            self.finish(job)
        self.assertTrue(job.completed.is_set())

    def test_no_os_thread_start_is_not_reported_as_completed(self):
        job = desktop.LookupJob(self.intent)
        with patch.object(job.thread, 'start', side_effect=RuntimeError('PRIVATE')):
            with self.assertRaises(RuntimeError):job.start()
        self.assertTrue(job.start_attempted)
        self.assertIsNone(job.request[0])
        self.assertIsNone(job.poll())

    def test_interrupted_real_os_bootstrap_keeps_ownership_and_withdraws_admission(self):
        job = desktop.LookupJob(self.intent)
        reached, release, ended = threading.Event(), threading.Event(), threading.Event()
        bootstrap = job.thread._bootstrap_inner
        def delayed():
            reached.set()
            try:
                release.wait(timeout=3)
                bootstrap()
            finally:
                ended.set()
        def interrupted(*args, **kwargs):
            assert reached.wait(timeout=2)
            raise KeyboardInterrupt('PRIVATE')
        job.thread._bootstrap_inner = delayed
        job.thread._started.wait = interrupted
        try:
            with patch.object(desktop.lookup, 'lookup', side_effect=AssertionError('withdrawn job')) as call:
                with self.assertRaises(KeyboardInterrupt):job.start()
                self.assertIsNone(job.thread.ident)
                self.assertIsNone(job.poll())
                self.assertIsNone(job.request[0])
                release.set()
                self.assertTrue(ended.wait(timeout=2))
                self.finish(job)
                self.assertEqual(call.call_count, 0)
        finally:
            release.set()
            self.assertTrue(ended.wait(timeout=3))
            job.thread.join(timeout=3)

    def test_incomplete_result_is_refused_not_presented_as_replay_success(self):
        for invalid in (None, {}, {'ledger_replayed': True}, {'retry_authorized': True}):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                desktop.present(invalid, self.intent)

    def test_review_lists_exact_frozen_inputs_without_accessing_files(self):
        text = desktop.review_text(self.intent)
        for value in values(self.root).values():self.assertIn(value, text)
        self.assertIn('verify-active', text)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_help_and_arguments_require_no_display_and_are_redacted(self):
        for tail, status in ((['--help'], 0), (['--secret', 'PRIVATE'], 64), (['--no-real-f'], 64)):
            result = subprocess.run([sys.executable, desktop.__file__, *tail], capture_output=True, timeout=10)
            self.assertEqual(result.returncode, status, result.stderr)
            self.assertNotIn(b'PRIVATE', result.stdout + result.stderr)




class PresentationTests(unittest.TestCase):
    """Synthetic public display metadata only: never injected as a replay result."""
    def setUp(self):
        import copy
        self.clone = copy.deepcopy
        self.intent = desktop.lookup.prepare(dict(values(Path('/').resolve()), checkpoint=pin(1)))
        p = desktop.lookup.Checkpoint.parse(self.intent.checkpoint)
        self.result = dict(format='zevune-ledger-transaction-lookup-1', txid=self.intent.txid,
                           checkpoint=p.encoded, checkpoint_height=p.height, checkpoint_app_hash=p.app_hash,
                           genesis_sha256=self.intent.genesis_sha256, native_backend_sha256=self.intent.backend_sha256,
                           ledger_replayed=True, historical_search_complete=True, historical_inclusion_verified=True,
                           state='included_in_verified_history', occurrence=dict(height=1, record_block_id='e'*64,
                           transaction_index=0, segment='00000000.journal', record_offset=0, transaction_bytes=100),
                           subsequent_record_count=0, scanned_records=1, scanned_transactions=1, ledger_bytes=p.length,
                           current_chain_height=None, broadcast_status='unknown', settlement_status='unknown',
                           wallet_authenticated=False, recipient_or_amount_verified=False, finality_verified=False,
                           retry_authorized=False, portable_proof_generated=False, source_files_unchanged=True,
                           real_funds_allowed=False)

    def test_pure_presentation_and_exact_immutable_text(self):
        result = desktop.present(self.result, self.intent)
        self.assertIn('已纳入指定历史账本', result.text)
        self.assertIn('不是共识确认数', result.text)
        self.assertIn('不是', result.text)
        self.assertEqual(result.txid, self.intent.txid)
        with self.assertRaises(AttributeError):result.txid = 'changed'
        self.result['txid'] = 'changed'
        self.assertEqual(result.txid, self.intent.txid)

    def test_absence_is_distinct_from_error_and_never_retry_permission(self):
        changed = dict(self.result, historical_inclusion_verified=False, state='absent_from_verified_history',
                       occurrence=None, subsequent_record_count=None)
        displayed = desktop.present(changed, self.intent)
        self.assertIn('没有该交易', displayed.text)
        self.assertIn('不能据此重试付款', displayed.text)
        self.assertEqual(displayed.txid, self.intent.txid)  # Copy identifies the query, not a payment receipt.
        for key, value in (('occurrence', self.result['occurrence']), ('subsequent_record_count', 0),
                           ('state','included_in_verified_history'), ('historical_inclusion_verified',0)):
            with self.assertRaises(ValueError):desktop.present(dict(changed, **{key:value}), self.intent)

    def test_exact_keys_and_request_binding(self):
        for key in self.result:
            wrong = dict(self.result);wrong.pop(key)
            with self.subTest(key=key), self.assertRaises(ValueError):desktop.present(wrong, self.intent)
        with self.assertRaises(ValueError):desktop.present(dict(self.result, unexpected=True), self.intent)
        for key in ('txid','checkpoint','checkpoint_app_hash','genesis_sha256','native_backend_sha256'):
            wrong = dict(self.result);wrong[key] = '0' * len(wrong[key])
            with self.subTest(key=key), self.assertRaises(ValueError):desktop.present(wrong, self.intent)

    def test_every_boolean_and_fixed_counter_has_exact_type(self):
        for key, value in self.result.items():
            if type(value) is bool:
                for bad in (int(value), not value, 'true'):
                    with self.subTest(key=key, bad=bad), self.assertRaises(ValueError):
                        desktop.present(dict(self.result, **{key:bad}), self.intent)
        for key in ('checkpoint_height','scanned_records','ledger_bytes'):
            for bad in (False, 1.0, -1):
                with self.subTest(key=key), self.assertRaises(ValueError):
                    desktop.present(dict(self.result, **{key:bad}), self.intent)

    def test_unverified_scope_cannot_be_promoted(self):
        for key,value in (('settlement_status','confirmed'), ('broadcast_status','broadcast'),
                          ('current_chain_height',1), ('format','other'), ('scanned_transactions',True),
                          ('scanned_transactions',17), ('scanned_transactions',0), ('subsequent_record_count',True)):
            with self.subTest(key=key), self.assertRaises(ValueError):
                desktop.present(dict(self.result, **{key:value}), self.intent)

    def test_occurrence_bounds_and_unknown_fields(self):
        for key,value in (('height',0), ('height',2), ('height',True), ('transaction_index',1),
                          ('transaction_index',False), ('transaction_bytes',0), ('transaction_bytes',28135),
                          ('record_offset',-1), ('record_offset',2**20), ('record_block_id','PRIVATE'),
                          ('segment','00000001.journal'), ('segment','00000000.JOURNAL'),
                          ('segment','../secret'), ('segment','００００００００.journal')):
            wrong = self.clone(self.result);wrong['occurrence'][key]=value
            with self.subTest(key=key,value=value), self.assertRaises(ValueError):desktop.present(wrong,self.intent)
        wrong=self.clone(self.result);wrong['occurrence']['extra']='PRIVATE'
        with self.assertRaises(ValueError):desktop.present(wrong,self.intent)

    def test_bad_native_metadata_stays_refusal_in_real_worker(self):
        # Intentionally malformed output only; no accepted native verification double.
        with patch.object(desktop.lookup,'lookup',return_value={'ledger_replayed':True}):
            job=desktop.LookupJob(self.intent);job.start();job.thread.join(timeout=3)
        self.assertFalse(job.thread.is_alive());self.assertIsNone(job.poll().result)

    def test_all_inherited_execution_paths_keep_original_lifecycle(self):
        for name in ('start','withdraw_start','poll'):
            self.assertIs(getattr(desktop.LookupJob,name),getattr(desktop.lifecycle.LedgerJob,name))
        for name in ('changed','schedule_poll','cancel_poll','close','copy','clear','enable','discard'):
            self.assertIs(getattr(desktop.Workbench,name),getattr(desktop.lifecycle.Workbench,name))


if __name__ == '__main__':
    unittest.main()
