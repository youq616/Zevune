"""Actual C31 pack/unpack and file checks, never accepting native doubles."""
import contextlib
from dataclasses import replace
import hashlib
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ledger_query_bundle_receive as receive
import ledger_query_bundle_receive_desktop as desktop
from test_ledger_query_request_audit import request


def fixture(root, count=2):
    entries = []
    for i in range(count):
        req = request(range(i * 32, (i + 1) * 32))
        raw = receive.task.encode(req)
        sha = hashlib.sha256(raw).hexdigest()
        kind = 'task' if i % 2 == 0 else 'report'
        if kind == 'report': raw = receive.bundle.reports.encode(req, sha)
        entries.append(receive.bundle.entry(kind, hashlib.sha256(raw).hexdigest(), raw))
    raw = receive.bundle.encode(tuple(entries))
    path = root / 'received.json'; path.write_bytes(raw)
    values = dict(operation='unpack', bundle=str(path), bundle_sha256=hashlib.sha256(raw).hexdigest(),
                  destination=str(root / 'new-output'))
    return values, raw


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='receive-core-'); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve(); self.values, self.raw = fixture(self.root)
        self.form = receive.prepare(self.values)

    def test_all_fields_validate_before_io(self):
        with patch.object(receive.bundle, 'load', side_effect=AssertionError('no IO')):
            for k, v in (('operation', ''), ('operation', 'pack'), ('bundle', 'relative'), ('bundle', True),
                         ('bundle_sha256', 'A'*64), ('destination', '/a/../b'), ('destination', '/a/'+'中'*1500)):
                with self.subTest(k=k), self.assertRaises(ValueError):
                    receive.approve(receive.prepare(dict(self.values, **{k:v})))
            for obj in (None, {}, dict(self.values, extra=1)):
                with self.assertRaises(ValueError): receive.prepare(obj)
            with self.assertRaises(ValueError): receive.approve(None)
            with self.assertRaises(ValueError): receive.prepare(dict(self.values, destination=str(self.root)))

    def test_review_32_entries_is_read_only_complete_and_deterministic(self):
        self.form.bundle.unlink(); values, raw = fixture(self.root, 32)
        with patch.object(receive.files, 'write_new', side_effect=AssertionError('write')), \
             patch.object(subprocess, 'Popen', side_effect=AssertionError('process')):
            approval = receive.approve(receive.prepare(values)); text = receive.review_text(approval)
        self.assertFalse(approval.form.destination.exists())
        for i, entry in enumerate(approval.snapshot.entries):
            self.assertIn(receive.bundle.filename(i, entry.kind), text); self.assertIn(entry.sha256, text)
        self.assertIn(str(approval.form.destination), text); self.assertIn(values['bundle_sha256'], text)
        self.assertIn('默认取消', text); self.assertLess(len(text.encode()), receive.MAX_TEXT_BYTES)
        self.assertEqual(approval.form.bundle.read_bytes(), raw)

    def test_actual_unpack_then_existing_directory_verification(self):
        approved = receive.approve(self.form)
        with patch.object(subprocess, 'Popen', side_effect=AssertionError('no backend')), \
             patch.object(receive.task, 'run_request', side_effect=AssertionError('no execution')):
            displayed = receive.execute(approved)
            check_form = replace(self.form, operation='verify-directory')
            checked = receive.execute(receive.approve(check_form))
        self.assertIn('本次新目录还原调用已完成', displayed.text)
        self.assertIn('不证明以前还原调用成功', checked.text)
        self.assertEqual(checked.form, check_form)
        for i, entry in enumerate(approved.snapshot.entries):
            self.assertEqual((self.form.destination / receive.bundle.filename(i, entry.kind)).read_bytes(), entry.raw)
        self.assertEqual(self.form.bundle.read_bytes(), self.raw)

    def test_malformed_approvals_are_rejected_without_io(self):
        approval = receive.approve(self.form)
        bad = (None, replace(approval, form=None), replace(approval, snapshot=None),
               replace(approval, snapshot=replace(approval.snapshot, raw=b'{}')),
               replace(approval, destination_parent=[]), replace(approval, destination_chain=()),
               replace(approval, form=replace(self.form, bundle_sha256='0'*64)))
        with patch.object(receive.bundle, 'unchanged', side_effect=AssertionError('no IO')):
            for value in bad:
                with self.assertRaises(ValueError): receive.execute(value)

    def test_reviewed_same_bytes_replacement_refused_before_any_write(self):
        approval = receive.approve(self.form)
        self.form.bundle.rename(self.root/'held'); self.form.bundle.write_bytes(self.raw)
        with patch.object(receive.bundle, 'unpack', side_effect=AssertionError('must not start')) as operation:
            with self.assertRaises(ValueError): receive.execute(approval)
        self.assertEqual(operation.call_count, 0); self.assertFalse(self.form.destination.exists())

    def test_wrong_pin_existing_empty_target_and_dangling_target_fail_review(self):
        with self.assertRaises(ValueError): receive.approve(replace(self.form, bundle_sha256='0'*64))
        self.form.destination.mkdir()
        with self.assertRaises(ValueError): receive.approve(self.form)
        self.assertEqual(list(self.form.destination.iterdir()), [])

    def test_destination_created_after_review_is_never_overwritten(self):
        approval = receive.approve(self.form); self.form.destination.mkdir()
        keeper = self.form.destination/'keep'; keeper.write_bytes(b'KEEP')
        with self.assertRaises(ValueError): receive.execute(approval)
        self.assertEqual(keeper.read_bytes(), b'KEEP')

    def test_destination_parent_replaced_after_review_refused(self):
        parent = self.root/'parent'; parent.mkdir(); form = replace(self.form, destination=parent/'new')
        approval = receive.approve(form); parent.rename(self.root/'old'); parent.mkdir()
        with self.assertRaises(ValueError): receive.execute(approval)
        self.assertFalse(form.destination.exists())

    def test_existing_directory_identity_is_bound_to_review(self):
        receive.execute(receive.approve(self.form))
        form = replace(self.form, operation='verify-directory'); approval = receive.approve(form)
        form.destination.rename(self.root/'held'); form.destination.mkdir()
        with patch.object(receive.bundle, 'verify_directory', side_effect=AssertionError('old consent')):
            with self.assertRaises(ValueError): receive.execute(approval)

    def test_verified_directory_replaced_after_original_call_is_refused(self):
        receive.execute(receive.approve(self.form))
        form = replace(self.form, operation='verify-directory'); approved = receive.approve(form)
        actual = receive.bundle.verify_directory
        def moved(*args):
            result = actual(*args)
            form.destination.rename(self.root/'verified-old'); form.destination.mkdir()
            return result
        with patch.object(receive.bundle, 'verify_directory', side_effect=moved):
            with self.assertRaises(ValueError): receive.execute(approved)
        self.assertTrue((self.root/'verified-old'/'01-task.json').exists())

    def test_partial_write_failure_retained_and_explicit_verify_rejects_it(self):
        approval = receive.approve(self.form); real = receive.files.write_new; written = []
        def failure(path, data):
            written.append(path); real(path, data if len(written) == 1 else data[:20])
            if len(written) == 2: raise OSError('PRIVATE')
        with patch.object(receive.files, 'write_new', side_effect=failure):
            with self.assertRaises(OSError): receive.execute(approval)
        self.assertEqual(len(list(self.form.destination.iterdir())), 2)
        self.assertEqual(written[1].read_bytes(), approval.snapshot.entries[1].raw[:20])
        with self.assertRaises(ValueError): receive.execute(receive.approve(replace(self.form, operation='verify-directory')))
        with self.assertRaises(ValueError): receive.approve(self.form)

    def test_original_success_then_bundle_replacement_cannot_yield_display(self):
        approval = receive.approve(self.form); real = receive.bundle.unpack
        def changed(*args):
            answer = real(*args)
            self.form.bundle.rename(self.root/'held'); self.form.bundle.write_bytes(self.raw)
            return answer
        with patch.object(receive.bundle, 'unpack', side_effect=changed):
            with self.assertRaises(ValueError): receive.execute(approval)
        self.assertTrue(self.form.destination.is_dir())
        self.assertTrue(receive.bundle.verify_directory(self.form.bundle, self.form.bundle_sha256,
                                                       self.form.destination)['directory_bytes_verified'])

    def test_loss_of_real_success_receipt_is_failure_not_rollback(self):
        approval = receive.approve(self.form); real = receive.bundle.unpack
        def lost(*args): real(*args); raise OSError('PRIVATE')
        with patch.object(receive.bundle, 'unpack', side_effect=lost):
            with self.assertRaises(OSError): receive.execute(approval)
        checked = receive.execute(receive.approve(replace(self.form, operation='verify-directory')))
        self.assertIn('不证明以前还原调用成功', checked.text)

    def test_exact_receipt_types_operation_pin_and_inventory(self):
        approval = receive.approve(self.form)
        result = receive.bundle.unpack(self.form.bundle, self.form.bundle_sha256, self.form.destination)
        for key, val in (('created', 1), ('directory_bytes_verified', 1), ('operation', 'evidence_bundle_pack'),
                         ('bundle_sha256', '0'*64), ('entry_count', 1), ('execution_performed', 0),
                         ('entries', []), ('signature_verified', True)):
            with self.subTest(key=key), self.assertRaises(ValueError):
                receive.present(dict(result, **{key:val}), approval)
        with self.assertRaises(ValueError): receive.present(dict(result, extra=1), approval)
        displayed = receive.present(result, approval)
        with self.assertRaises(AttributeError): displayed.text = 'x'

    def test_missing_or_extra_restored_files_do_not_become_success(self):
        receive.execute(receive.approve(self.form)); extra = self.form.destination/'extra'; extra.write_bytes(b'x')
        form = replace(self.form, operation='verify-directory')
        with self.assertRaises(ValueError): receive.execute(receive.approve(form))
        extra.unlink(); (form.destination/'01-task.json').unlink()
        with self.assertRaises(ValueError): receive.execute(receive.approve(form))

    @unittest.skipUnless(os.name=='posix','POSIX link fixture')
    def test_linked_parent_and_hardlinked_bundle_rejected(self):
        parent = self.root/'alias'; parent.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(ValueError): receive.approve(replace(self.form, destination=parent/'new'))
        os.link(self.form.bundle, self.root/'link')
        with self.assertRaises(ValueError): receive.approve(self.form)


class JobTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='receive-job-'); self.addCleanup(self.temp.cleanup)
        self.values, _ = fixture(Path(self.temp.name).resolve())
        self.approval = receive.approve(receive.prepare(self.values))

    def finish(self, job):
        job.thread.join(5); self.assertFalse(job.thread.is_alive())
        out = job.poll(); self.assertIsNotNone(out); self.assertIsNone(job.poll())
        self.assertIsNone(job.request[0]); return out.result

    def test_actual_worker_success_has_no_tk_and_releases_request(self):
        job = desktop.ReceiveJob(self.approval); self.assertFalse(job.thread.daemon)
        job.start(); shown = self.finish(job)
        self.assertIs(type(shown), receive.Display); self.assertTrue(self.approval.form.destination.exists())
        with self.assertRaises(ValueError): job.start()

    def test_withdrawn_admission_cannot_write(self):
        job = desktop.ReceiveJob(self.approval); job.thread.start()
        self.assertIsNone(job.poll()); job.withdraw_start()
        self.assertIsNone(self.finish(job)); self.assertFalse(self.approval.form.destination.exists())

    def test_finished_signal_is_not_actual_thread_exit(self):
        real = desktop._execute; entered, release = threading.Event(), threading.Event(); job = None
        def delayed(*args): real(*args); entered.set(); release.wait(5)
        try:
            with patch.object(desktop, '_execute', delayed):
                job = desktop.ReceiveJob(self.approval); job.start(); self.assertTrue(entered.wait(3))
                self.assertTrue(job.completed.is_set()); self.assertIsNone(job.poll())
                release.set(); self.assertIs(type(self.finish(job)), receive.Display)
        finally:
            release.set()
            if job: job.thread.join(5)

    def test_unknown_start_keeps_ownership_and_cannot_retry(self):
        job = desktop.ReceiveJob(self.approval)
        with patch.object(job.thread, 'start', side_effect=RuntimeError('PRIVATE')):
            with self.assertRaises(RuntimeError): job.start()
        self.assertIsNone(job.request[0]); self.assertIsNone(job.poll())
        with self.assertRaises(ValueError): job.start()

    def test_failure_keyboardinterrupt_and_lost_queue_are_redacted(self):
        for error in (OSError('PRIVATE'), KeyboardInterrupt('PRIVATE')):
            out = io.StringIO()
            with patch.object(receive, 'execute', side_effect=error), contextlib.redirect_stderr(out):
                job = desktop.ReceiveJob(self.approval); job.start(); self.assertIsNone(self.finish(job))
            self.assertEqual(out.getvalue(), '')
        job = desktop.ReceiveJob(self.approval)
        with patch.object(job.channel, 'put_nowait', side_effect=MemoryError('PRIVATE')):
            job.start(); self.assertIsNone(self.finish(job))
        self.assertTrue(self.approval.form.destination.exists())

    def test_actual_bootstrap_interruption_withdraws_write_before_admission(self):
        job = desktop.ReceiveJob(self.approval); original = job.thread._bootstrap_inner
        reached, release, ended = threading.Event(), threading.Event(), threading.Event()
        def delayed():
            reached.set()
            try: release.wait(5); original()
            finally: ended.set()
        def interrupt(*a, **k):
            assert reached.wait(3); raise KeyboardInterrupt('PRIVATE')
        job.thread._bootstrap_inner = delayed; job.thread._started.wait = interrupt
        try:
            with self.assertRaises(KeyboardInterrupt): job.start()
            self.assertIsNone(job.thread.ident); self.assertIsNone(job.poll())
            release.set(); self.assertTrue(ended.wait(4)); self.assertIsNone(self.finish(job))
            self.assertFalse(self.approval.form.destination.exists())
        finally:
            release.set(); ended.wait(5); job.thread.join(5)

    def test_help_requires_no_display_and_syntax_is_fixed(self):
        for args, code in ((['--help'],0), ([],64), (['--secret','PRIVATE'],64), (['--no-real-f'],64)):
            result = subprocess.run([sys.executable,'-B',desktop.__file__,*args], capture_output=True, timeout=10,
                                    env={**os.environ,'DISPLAY':''})
            self.assertEqual(result.returncode,code); self.assertNotIn(b'PRIVATE',result.stdout+result.stderr)


if __name__=='__main__': unittest.main()
