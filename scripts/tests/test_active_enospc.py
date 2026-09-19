"""Harness safety tests; synthetic receipts are not kernel ENOSPC evidence.

No test mounts a filesystem, uses sudo, starts a compiler, or traces a process.
Linux subprocess tests only exercise bounded public output and child cleanup.
"""
import argparse
import contextlib
import hashlib
import json
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import run_active_enospc as runner

TAIL, NEW = tuple(runner.CASES)
TRACE = b"123 write(0x4, 0x7ff000, 0x1000) = -1 ENOSPC (No space left on device)\n"


def receipt(case=TAIL):
    result = {"schema_version": 1, "case": case, "profile": "active_segments_v1",
              "filesystem": "tmpfs", "target_rel": runner.CASES[case], "target_dev": 1,
              "target_ino": 2, "target_nlink": 1, "before_len": 4090, "after_len": 4096,
              "frame_len": 12, "changed_suffix_len": 6, "before_sha256": "a" * 64,
              "after_sha256": "b" * 64, "checkpoint_height": 1,
              "checkpoint_apphash": "c" * 64, "checkpoint_pin_sha256": "d" * 64,
              "filler_errno": 28, "filler_bytes": 4096,
              **{field: True for field in runner.BOOL_FIELDS}}
    if case == NEW:
        result.update(before_len=0, after_len=0, changed_suffix_len=0, before_sha256=None,
                      after_sha256=hashlib.sha256(b"").hexdigest())
    return result


def completed(trace=TRACE):
    return {"returncode": 0, "timed_out": False, "overflow": False,
            "leaked_output": False, "signal_permission_denied": False,
            "stdout": b"public test harness output", "stderr": b"", "trace": trace}


class EnospcEvidenceTests(unittest.TestCase):
    def test_only_complete_raw_target_write_failures_count(self):
        raw = TRACE + b"[pid 124] pwrite64(0x4, 0x7ff100, 0x1000, 0) = -1 ENOSPC (No space left on device)\n"
        result = runner.trace_evidence(raw)
        self.assertEqual(result["write_enospc_count"], 2)
        self.assertEqual(result["syscall_counts"]["pwrite64"], 1)
        self.assertEqual(result["trace_sha256"], hashlib.sha256(raw).hexdigest())
        self.assertTrue(result["raw_write_arguments"])

    def test_decoded_buffers_injection_unfinished_and_other_errors_are_not_evidence(self):
        samples = [b"", TRACE + b"INJECTED\n", TRACE.replace(b"0x7ff000", b'"secret fixture"'),
                   TRACE.replace(b"ENOSPC", b"EIO"), TRACE.replace(b"-1 ENOSPC (No space left on device)", b"4096"),
                   b"write(0x4, 0x7ff000, 0x1000 <unfinished ...>\n",
                   b"fsync(4) = -1 ENOSPC (No space left on device)\n", b"x" * (65536 + 1)]
        for raw in samples:
            with self.subTest(raw=raw[:40]), self.assertRaises(ValueError):
                runner.trace_evidence(raw)

    def test_receipts_distinguish_partial_tail_from_empty_new_segment(self):
        runner.validate_receipt(receipt(), TAIL)
        runner.validate_receipt(receipt(NEW), NEW)
        for case, changes in ((TAIL, {"changed_suffix_len": 0}), (TAIL, {"frame_len": 6}),
                              (NEW, {"after_len": 1, "changed_suffix_len": 1}),
                              (NEW, {"before_sha256": "0" * 64})):
            wrong = receipt(case)
            wrong.update(changes)
            with self.subTest(case=case, changes=changes), self.assertRaises(ValueError):
                runner.validate_receipt(wrong, case)

    def test_receipt_missing_false_ambiguous_or_unbounded_fields_fail(self):
        mutations = [{"store_unavailable": False}, {"no_new_summary_published": 1},
                     {"filler_errno": 5}, {"filler_bytes": 0}, {"filler_bytes": runner.TMPFS_BYTES},
                     {"target_dev": True}, {"target_nlink": 2}, {"target_rel": "../elsewhere"},
                     {"after_sha256": "not-a-digest"}, {"physical_disk_failure_tested": True}]
        for changes in mutations:
            wrong = receipt()
            wrong.update(changes)
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                runner.validate_receipt(wrong, TAIL)
        wrong = receipt()
        del wrong["reopen_rejected"]
        with self.assertRaises(ValueError):
            runner.validate_receipt(wrong, TAIL)
        with self.assertRaises(ValueError):
            json.loads('{"case":1,"case":2}', object_pairs_hook=runner.unique)

    def test_bounded_regular_file_identity_refuses_links_and_oversize(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "source"
            source.write_bytes(b"public fixture")
            _, digest, raw = runner.file_identity(source, 32, capture=True)
            self.assertEqual(raw, b"public fixture")
            self.assertEqual(digest, hashlib.sha256(raw).hexdigest())
            with self.assertRaises(ValueError):
                runner.file_identity(source, 1)
            linked = Path(temporary) / "hardlink"
            os.link(source, linked)
            with self.assertRaises(ValueError):
                runner.file_identity(source, 32)

    def test_diagnostics_never_echo_exception_paths_or_payloads(self):
        self.assertEqual(runner.failure_code(ValueError("unexpected_test_receipt")), "unexpected_test_receipt")
        self.assertEqual(runner.failure_code(OSError("private-path fixture")), "OSError")
        self.assertEqual(runner.failure_code(ValueError("private-path fixture")), "ValueError")

    def test_public_summary_cannot_publish_raw_output_or_absolute_paths(self):
        data = {"kind": "linux_tmpfs_enospc", "completed": False, "source_head": "a" * 40,
                "checkout_commit": "b" * 40, "checkout_tree": "c" * 40,
                "stdout": "private-fixture", "stderr": "private-fixture", "trace": "private-fixture",
                "cases": [{"case": TAIL, "target_rel": runner.CASES[TAIL], "completed": False,
                           "receipt": receipt(), "syscall_evidence": runner.trace_evidence(TRACE),
                           "failure": "/private-fixture", "raw_trace": "private-fixture"}]}
        result = runner.public_summary(data)
        self.assertNotIn("private-fixture", json.dumps(result))
        self.assertEqual(result["cases"][0]["write_enospc_count"], 1)
        self.assertEqual(result["cases"][0]["filler_errno"], 28)
        self.assertEqual(result["checkout_tree"], "c" * 40)

    def test_root_watchdog_precedes_the_same_namespaces_in_main_and_probe(self):
        main = runner.root_namespace_command(["--namespace"])
        probe = runner.root_namespace_command(["--probe-payload"], seconds=3, kill_after=2)
        for command in (main, probe):
            self.assertLess(command.index("/usr/bin/sudo"), command.index("/usr/bin/timeout"))
            self.assertLess(command.index("/usr/bin/timeout"), command.index("/usr/bin/unshare"))
            for flag in ("--kill-child", "--fork", "--mount", "--pid", "--mount-proc"):
                self.assertIn(flag, command)
            self.assertNotIn("--foreground", command)
            self.assertNotIn("--preserve-status", command)
        self.assertEqual(main[main.index("/usr/bin/unshare"):-1], probe[probe.index("/usr/bin/unshare"):-1])


@unittest.skipUnless(sys.platform == "linux", "Linux process groups and namespace harness semantics")
class EnospcProcessSafetyTests(unittest.TestCase):
    def test_probe_accepts_actual_negative_sigkill_status_only_with_namespace_confirmation(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            args = argparse.Namespace(directory=base, uid=base.stat().st_uid)
            def run(command, **kwargs):
                state = {"root_euid": 0, "pid_namespace": "pid:[123456789]",
                         "mount_namespace": "mnt:[123456789]", "ignores_sigterm": True}
                (base / "probe-state.json").write_text(json.dumps(state))
                result = completed()
                result.update(returncode=-9, stdout=b"")
                return result
            with patch.object(runner.os, "geteuid", return_value=0), patch.object(runner, "run_bounded", side_effect=run), \
                    patch.object(runner, "namespace_members", return_value=0) as observed, \
                    patch.object(runner.time, "monotonic", side_effect=[0, 5, 5]), contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(runner.probe_controller(args), 0)
            observed.assert_called_once_with("pid:[123456789]")
            result = json.loads(output.getvalue())
            self.assertEqual(result["watchdog_exit"], -9)
            self.assertTrue(result["namespace_exit_confirmed"])

    def test_output_flood_is_bounded_and_cannot_report_success(self):
        result = runner.run_bounded([sys.executable, "-c", "import os; os.write(1, b'x' * 1000000)"], timeout=3)
        self.assertTrue(result["overflow"])
        self.assertLessEqual(len(result["stdout"]), 65536)
        with self.assertRaises(ValueError):
            runner.require_process(result)

    def test_stalled_child_is_terminated_with_a_bounded_wait(self):
        start = time.monotonic()
        result = runner.run_bounded([sys.executable, "-c", "import time; time.sleep(20)"], timeout=0.1)
        self.assertTrue(result["timed_out"])
        self.assertLess(time.monotonic() - start, 8)
        self.assertIsNotNone(result["returncode"])

    def test_descendant_holding_stdout_cannot_block_cleanup(self):
        program = "import subprocess,sys; subprocess.Popen([sys.executable,'-c','import time; time.sleep(20)'])"
        start = time.monotonic()
        result = runner.run_bounded([sys.executable, "-c", program], timeout=10)
        self.assertTrue(result["leaked_output"])
        self.assertLess(time.monotonic() - start, 9)

    def test_descendant_without_inherited_pipes_is_killed_before_leader_reap(self):
        program = "import os,time; pid=os.fork(); "
        program += "\nif pid: print(pid,flush=True); os._exit(0)"
        program += "\nfor fd in (0,1,2): os.close(fd)"
        program += "\ntime.sleep(10)"
        result = runner.run_bounded([sys.executable, "-c", program], timeout=3)
        runner.require_process(result)
        child = int(result["stdout"])
        until = time.monotonic() + 1
        while True:
            try:
                status = Path(f"/proc/{child}/stat").read_text().split(")", 1)[1].split()[0]
            except FileNotFoundError:
                break
            if status == "Z":
                break
            self.assertLess(time.monotonic(), until, "descendant kept running after successful leader cleanup")
            time.sleep(0.01)

    def test_namespace_entry_refuses_host_process_before_mount(self):
        args = argparse.Namespace(uid=1001, gid=1001)
        with patch.object(runner.os, "geteuid", return_value=0), patch.object(runner.os, "getpid", return_value=42), \
                patch.object(runner, "utility") as command, self.assertRaises(ValueError):
            runner.namespace(args)
        command.assert_not_called()

    def test_mount_validation_failure_still_uses_ordinary_unmount(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(runner.os, "chown"), \
                patch.object(runner, "verify_mount", side_effect=ValueError("unexpected_filesystem_boundary")), \
                patch.object(runner, "utility") as command:
            result = runner.run_case(Path("/unused"), TAIL, Path(temporary), 1001, 1001, time.monotonic() + 30)
        self.assertFalse(result["completed"])
        self.assertTrue(result["ordinary_unmount_succeeded"])
        self.assertEqual(command.call_args_list[-1].args[0][:2], ["/usr/bin/umount", "--"])
        self.assertNotIn("-l", command.call_args_list[-1].args[0])

    def test_full_bytes_with_remaining_inodes_are_required(self):
        for free, available, inodes, accepted in ((0, 0, 10, True), (1, 0, 10, False),
                                                (0, 1, 10, False), (0, 0, 0, False)):
            usage = argparse.Namespace(f_bfree=free, f_bavail=available, f_ffree=inodes)
            with patch.object(runner.os, "statvfs", return_value=usage):
                if accepted:
                    self.assertTrue(runner.verify_exhausted(Path("/unused"))["block_exhaustion_confirmed"])
                else:
                    with self.assertRaises(ValueError):
                        runner.verify_exhausted(Path("/unused"))

    def test_failed_privileged_run_never_deletes_the_unconfirmed_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            binary = root / "public-test-binary"
            binary.write_bytes(b"inert fixture; never executed")
            binary.chmod(0o700)
            retained = root / "retained"
            retained.mkdir()
            version = completed()
            version["stdout"] = b"strace -- version 6.8\n"
            listing = completed()
            listing["stdout"] = "\n".join(name + ": test" for name in runner.CASES).encode()
            failed = completed()
            failed.update(returncode=124, stdout=b'{"completed":false,"cases":[]}')
            with patch.object(runner.os, "geteuid", return_value=1001), patch.object(runner.os, "getegid", return_value=1001), \
                    patch.object(runner, "source_identity", return_value={"source_head": "a" * 40}), \
                    patch.object(runner.tempfile, "mkdtemp", return_value=str(retained)), \
                    patch.object(runner, "run_bounded", side_effect=[version, listing, failed]), \
                    patch.object(runner.shutil, "rmtree") as remove:
                result = runner.outer(binary, root / "result.json")
            remove.assert_not_called()
            self.assertFalse(result["completed"])
            self.assertTrue(result["cleanup_unknown"])
            self.assertTrue(retained.exists())

    def test_missing_kernel_evidence_and_unmount_failure_are_failures(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(runner.os, "chown"), \
                patch.object(runner, "verify_mount", return_value={"device": 1}):
            def execute(command, **kwargs):
                for descriptor in kwargs["trace_pipe"]:
                    os.close(descriptor)
                return completed(trace=b"")
            def utility(command):
                if command[0].endswith("umount"):
                    raise subprocess.CalledProcessError(1, "umount")
            with patch.object(runner, "run_bounded", side_effect=execute), patch.object(runner, "utility", side_effect=utility):
                result = runner.run_case(Path("/unused"), TAIL, Path(temporary), os.geteuid(), os.getegid(), time.monotonic() + 30)
        self.assertFalse(result["completed"])
        self.assertFalse(result["ordinary_unmount_succeeded"])
        self.assertEqual(result["failure"], "ordinary_unmount_failed")

    def test_final_file_identity_is_checked_independently_of_the_receipt(self):
        for forged in (False, True):
            with self.subTest(forged=forged), tempfile.TemporaryDirectory() as temporary, \
                    patch.object(runner.os, "chown"), patch.object(runner, "utility"):
                base = Path(temporary)
                def execute(command, **kwargs):
                    for descriptor in kwargs["trace_pipe"]:
                        os.close(descriptor)
                    mount = base / "mount-0"
                    target = mount / runner.CASES[TAIL]
                    target.parent.mkdir()
                    target.write_bytes(b"x" * 4096)
                    control = base / "control-0"
                    checkpoint = b"p" * 128
                    (control / "checkpoint.bin").write_bytes(checkpoint)
                    data = receipt()
                    data.update(target_dev=target.stat().st_dev, target_ino=target.stat().st_ino,
                                after_sha256=hashlib.sha256(target.read_bytes()).hexdigest(),
                                checkpoint_pin_sha256=hashlib.sha256(checkpoint).hexdigest())
                    if forged:
                        data["target_ino"] += 1
                    (control / "receipt.json").write_text(json.dumps(data))
                    return completed()
                with patch.object(runner, "verify_mount", return_value={"device": base.stat().st_dev}), \
                        patch.object(runner, "run_bounded", side_effect=execute), \
                        patch.object(runner, "verify_exhausted", return_value={"block_exhaustion_confirmed": True}), \
                        patch.object(Path, "rmdir"):
                    result = runner.run_case(Path("/unused"), TAIL, base, os.geteuid(), os.getegid(), time.monotonic() + 30)
                self.assertEqual(result["completed"], not forged)
                self.assertTrue(result["ordinary_unmount_succeeded"])
                if forged:
                    self.assertEqual(result["failure"], "traced_target_identity_mismatch")


if __name__ == "__main__":
    unittest.main()
