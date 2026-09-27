"""Pure task/result metadata and refusing workers; no successful native doubles."""
import contextlib
import copy
from dataclasses import replace
import hashlib
import io
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ledger_query_request_desktop as desktop
import test_ledger_transaction_batch_once_desktop as old_tests


def fixture(root: Path, count=3):
    common = old_tests.values(root)
    ids = tuple(f'{i:064x}' for i in range(count))
    request = desktop.task.prepare(common['checkpoint'], common['genesis_sha256'], common['backend_sha256'], ids)
    path = root / 'request.json'
    created = desktop.task.create(request, path)
    values = dict(request=str(path), request_sha256=created['request_sha256'],
                  journal=common['journal'], backend=common['backend'])
    return values, desktop.approve(desktop.prepare(values))


def metadata(approval):
    # Pure presentation input only. NEVER feed this into a worker or native verifier.
    inner = old_tests.display_fixture(desktop.native_intent(approval))
    return dict(operation='query_request_run', request_sha256=approval.form.request_sha256,
                request_file_unchanged=True, signature_verified=False, real_funds_allowed=False, result=inner)


class BoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='request-ui-unit-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.values, self.approval = fixture(self.root)

    def test_all_form_validation_precedes_request_io(self):
        with patch.object(desktop.task, 'load', side_effect=AssertionError('no IO')):
            for name, value in (('request', 'relative'), ('request', True), ('request_sha256', 'A'*64),
                                ('request_sha256', None), ('journal', '/a/../b'), ('backend', '/a/\u202eb'),
                                ('backend', '/a/'+'中'*1400), ('backend', None)):
                with self.subTest(name=name), self.assertRaises(ValueError):
                    desktop.approve(desktop.prepare(dict(self.values, **{name: value})))
            for value in (None, {}, dict(self.values, extra=1)):
                with self.assertRaises(ValueError): desktop.prepare(value)
            with self.assertRaises(ValueError): desktop.approve(None)

    def test_review_is_complete_bound_and_has_no_process_or_ledger_access(self):
        with patch.object(subprocess, 'Popen', side_effect=AssertionError('no process')), \
                patch.object(desktop.task, 'run_request', side_effect=AssertionError('no query')), \
                patch.object(desktop.task.once.single.ledger, 'archive_snapshot', side_effect=AssertionError('no ledger')):
            approval = desktop.approve(desktop.prepare(self.values))
            text = desktop.review_text(approval)
        for value in (*self.values.values(), approval.snapshot.request.checkpoint,
                      approval.snapshot.request.genesis_sha256, approval.snapshot.request.backend_sha256):
            self.assertIn(value, text)
        positions = [text.index(f'{i+1:02d}  {txid}') for i, txid in enumerate(approval.snapshot.request.txids)]
        self.assertEqual(positions, sorted(positions))
        self.assertIn('默认取消', text)
        self.assertEqual(self.approval, approval)

    def test_approval_validation_is_pure_and_rejects_forgery(self):
        bad = (None, replace(self.approval, form=None), replace(self.approval, snapshot=None),
               replace(self.approval, form=replace(self.approval.form, request_sha256='0'*64)),
               replace(self.approval, snapshot=replace(self.approval.snapshot, raw=b'{}')),
               replace(self.approval, snapshot=replace(self.approval.snapshot, path=self.root/'other')),
               replace(self.approval, snapshot=replace(self.approval.snapshot, request=None)))
        with patch.object(desktop.task, 'load', side_effect=AssertionError('pure only')):
            desktop.validate_approval(self.approval)
            for item in bad:
                with self.assertRaises(ValueError): desktop.validate_approval(item)
        with self.assertRaises(AttributeError): self.approval.form = None

    def test_outer_result_exact_fields_types_and_task_pin(self):
        result = metadata(self.approval)
        shown = desktop.present(result, self.approval)
        self.assertIs(type(shown), desktop.RequestDisplay)
        self.assertEqual(shown.txids, self.approval.snapshot.request.txids)
        self.assertEqual(shown.request_sha256, self.values['request_sha256'])
        for key in result:
            wrong = copy.deepcopy(result); wrong.pop(key)
            with self.subTest(missing=key), self.assertRaises(ValueError): desktop.present(wrong, self.approval)
        for key, value in (('operation','inspect'), ('request_sha256','0'*64), ('request_file_unchanged',1),
                           ('signature_verified',0), ('signature_verified',True), ('real_funds_allowed',0)):
            wrong = dict(result, **{key:value})
            with self.assertRaises(ValueError): desktop.present(wrong,self.approval)
        with self.assertRaises(ValueError): desktop.present(dict(result, extra=1),self.approval)
        with self.assertRaises(ValueError): desktop.present(None,self.approval)

    def test_inner_result_pins_format_order_counts_and_safety_are_not_relaxed(self):
        result = metadata(self.approval)
        for key,value in (('format','zevune-ledger-transaction-batch-1'), ('history_scan_count',True),
                          ('checkpoint','x'),('query_count',1),('batch_complete',False),
                          ('real_funds_allowed',True),('settlement_status','confirmed')):
            bad=copy.deepcopy(result);bad['result'][key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):desktop.present(bad,self.approval)
        for edit in ('order','remove','duplicate','bad_occurrence'):
            bad=copy.deepcopy(result); rows=bad['result']['results']
            if edit=='order':rows.reverse()
            elif edit=='remove':rows.pop()
            elif edit=='duplicate':rows[1]=copy.deepcopy(rows[0])
            else:rows[0]['occurrence']['record_offset']=-1
            with self.assertRaises(ValueError):desktop.present(bad,self.approval)

    def test_display_is_immutable_independent_and_bounded_at_32_ids(self):
        other=self.root/'many';other.mkdir()
        _,approval=fixture(other,32)
        result=metadata(approval); before=copy.deepcopy(result)
        shown=desktop.present(result,approval)
        self.assertEqual(result,before)
        result['result']['results'][0]['txid']='f'*64
        self.assertEqual(shown.txids,approval.snapshot.request.txids)
        self.assertLess(len(shown.text.encode()),desktop.task.MAX_OUTPUT_BYTES)
        with self.assertRaises(AttributeError):shown.txids=()

    def test_changed_or_replaced_reviewed_task_never_starts_query(self):
        path=self.approval.form.request;raw=path.read_bytes()
        with patch.object(desktop.task,'run_request',side_effect=AssertionError('unreviewed file')) as query:
            path.write_bytes(raw+b'x')
            with self.assertRaises(ValueError):desktop.execute(self.approval)
            path.write_bytes(raw)
            # A fresh review is required even when the bytes become equal again.
            current=desktop.approve(self.approval.form)
            path.rename(self.root/'held');path.write_bytes(raw)
            with self.assertRaises(ValueError):desktop.execute(current)
        self.assertEqual(query.call_count,0)

    def test_actual_task_core_is_used_once_and_failures_propagate(self):
        with patch.object(desktop.task,'run_request',side_effect=RuntimeError('refusal only')) as query:
            with self.assertRaises(RuntimeError):desktop.execute(self.approval)
        query.assert_called_once_with(self.approval.form.request, self.approval.form.request_sha256,
                                      self.approval.form.journal,self.approval.form.backend)
        self.assertEqual(self.approval.form.request.read_bytes(),self.approval.snapshot.raw)


class JobTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='request-job-');self.addCleanup(self.temp.cleanup)
        self.values,self.approval=fixture(Path(self.temp.name).resolve())

    def finish(self,job):
        job.thread.join(timeout=4)
        self.assertFalse(job.thread.is_alive())
        result=job.poll();self.assertIsNotNone(result);self.assertIsNone(result.result)
        self.assertIsNone(job.poll());self.assertIsNone(job.request[0])

    def test_real_missing_ledger_refusal_releases_request(self):
        with patch.object(subprocess,'Popen',side_effect=AssertionError('missing ledger must refuse')):
            job=desktop.RequestJob(self.approval);job.start();self.finish(job)
        self.assertFalse(job.thread.daemon)

    def test_no_execution_before_admission_or_after_withdrawal(self):
        with patch.object(desktop,'execute',side_effect=AssertionError('not admitted')) as run:
            job=desktop.RequestJob(self.approval);job.thread.start()
            self.assertIsNone(job.poll());job.withdraw_start();self.finish(job)
        self.assertEqual(run.call_count,0)

    def test_event_is_not_actual_thread_exit(self):
        target=desktop._execute;entered,release=threading.Event(),threading.Event();job=None
        def delayed(*args):target(*args);entered.set();release.wait(timeout=4)
        try:
            with patch.object(desktop,'_execute',delayed):
                job=desktop.RequestJob(self.approval);job.start()
                self.assertTrue(entered.wait(timeout=2));self.assertTrue(job.completed.is_set())
                self.assertIsNone(job.poll());release.set();self.finish(job)
        finally:
            release.set()
            if job is not None:job.thread.join(timeout=4)

    def test_exception_keyboardinterrupt_and_lost_queue_are_redacted(self):
        for error in (ValueError('PRIVATE'),KeyboardInterrupt('PRIVATE')):
            output=io.StringIO()
            with patch.object(desktop,'execute',side_effect=error),contextlib.redirect_stdout(output),contextlib.redirect_stderr(output):
                job=desktop.RequestJob(self.approval);job.start();self.finish(job)
            self.assertEqual(output.getvalue(),'')
        job=desktop.RequestJob(self.approval)
        with patch.object(job.channel,'put_nowait',side_effect=MemoryError('PRIVATE')):
            job.start();self.finish(job)

    def test_unknown_start_keeps_ownership_and_never_retries(self):
        job=desktop.RequestJob(self.approval)
        with patch.object(job.thread,'start',side_effect=RuntimeError('PRIVATE')):
            with self.assertRaises(RuntimeError):job.start()
        self.assertTrue(job.start_attempted);self.assertIsNone(job.request[0]);self.assertIsNone(job.poll())
        with self.assertRaises(ValueError):job.start()

    def test_actual_os_bootstrap_interruption_withdraws_before_execution(self):
        job=desktop.RequestJob(self.approval)
        entered,release,ended=threading.Event(),threading.Event(),threading.Event()
        original=job.thread._bootstrap_inner
        def delayed():
            entered.set()
            try:release.wait(timeout=4);original()
            finally:ended.set()
        def interrupt(*args,**kwargs):
            assert entered.wait(timeout=2)
            raise KeyboardInterrupt('PRIVATE')
        job.thread._bootstrap_inner=delayed;job.thread._started.wait=interrupt
        try:
            with patch.object(desktop,'execute',side_effect=AssertionError('withdrawn')) as run:
                with self.assertRaises(KeyboardInterrupt):job.start()
                self.assertIsNone(job.thread.ident);self.assertIsNone(job.poll())
                release.set();self.assertTrue(ended.wait(timeout=3));self.finish(job)
                self.assertEqual(run.call_count,0)
        finally:
            release.set();self.assertTrue(ended.wait(timeout=4));job.thread.join(timeout=4)

    def test_invalid_approval_refused_before_thread_creation(self):
        with patch.object(threading,'Thread',side_effect=AssertionError('invalid thread')):
            for invalid in (None,replace(self.approval,snapshot=None)):
                with self.assertRaises(ValueError):desktop.RequestJob(invalid)

    def test_help_and_syntax_require_no_tk_display_and_redact_values(self):
        for args,status in ((['--help'],0),(['--secret','PRIVATE'],64),(['--no-real-f'],64)):
            result=subprocess.run([sys.executable,'-B',desktop.__file__,*args],capture_output=True,timeout=15)
            self.assertEqual(result.returncode,status);self.assertNotIn(b'PRIVATE',result.stdout+result.stderr)


if __name__=='__main__':unittest.main()
