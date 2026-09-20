"""Synthetic receipt/path tests; not kernel failure or cryptographic evidence."""
import ast
import hashlib
import json
import os
import re
from pathlib import Path
import sys
import tempfile
import time
import textwrap
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import run_active_enospc as runner
import wallet_prepare_evidence as evidence
from test_active_enospc import completed, public_wallet_chain

CASE = next(iter(evidence.CASES))


def fixture():
    return dict(schema_version=1, case=CASE, profile="wallet_prepare_v1", filesystem="tmpfs",
                target_rel=evidence.CASES[CASE], target_dev=1, target_ino=2, target_nlink=1,
                before_len=evidence.BEFORE, after_len=evidence.AFTER, frame_len=evidence.RECORD,
                changed_suffix_len=evidence.AFTER - evidence.BEFORE, receipt_generation=2,
                pending_generation=3, final_generation=4, backup_len=evidence.BEFORE,
                restored_len=evidence.FINAL, filler_errno=28, filler_bytes=4096,
                before_sha256="a" * 64, after_sha256="b" * 64, backup_sha256="a" * 64,
                receipt_pin_sha256="c" * 64, pending_pin_sha256="d" * 64,
                final_pin_sha256="e" * 64, restored_sha256="f" * 64,
                real_funds_allowed=False, **{field: True for field in evidence.TRUE_FIELDS})


def write_fixture(mount, control):
    backup, old_pin = public_wallet_chain(2)
    _, pending_pin = public_wallet_chain(3)
    restored, final_pin = public_wallet_chain(4)
    suffix = (3).to_bytes(8, "big") + old_pin[40:] + b"s" * (evidence.AFTER - evidence.BEFORE - 40)
    target = mount / evidence.CASES[CASE]
    target.parent.mkdir()
    target.write_bytes(backup + suffix)
    data = fixture()
    data.update(target_dev=target.stat().st_dev, target_ino=target.stat().st_ino,
                after_sha256=hashlib.sha256(target.read_bytes()).hexdigest(),
                before_sha256=hashlib.sha256(backup).hexdigest(),
                backup_sha256=hashlib.sha256(backup).hexdigest(),
                restored_sha256=hashlib.sha256(restored).hexdigest())
    for name, raw, field in (("checkpoint.bin", old_pin, "receipt_pin_sha256"),
                              ("pending-checkpoint.bin", pending_pin, "pending_pin_sha256"),
                              ("final-checkpoint.bin", final_pin, "final_pin_sha256"),
                              ("backup/wallet.journal", backup, None),
                              ("restored/wallet.journal", restored, None)):
        path = control / name
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(raw)
        if field:
            data[field] = hashlib.sha256(raw).hexdigest()
    return data


def verify(mount, control, receipt):
    evidence.verify_files(mount, control, receipt, CASE, os.geteuid(),
                          read_file=runner.file_identity, read_chain=runner.wallet_public_pin)


class PrepareReceiptTests(unittest.TestCase):
    def test_workflow_routes_one_binary_and_preserves_existing_suites(self):
        workflow = Path(__file__).resolve().parents[2] / ".github/workflows/active-storage-faults.yml"
        source = workflow.read_text()
        self.assertIn("suite: [active, wallet, wallet_prepare]", source)
        blocks = re.findall(r"python - <<'PY'\n(.*?)^          PY$", source, re.M | re.S)
        calls = [node for block in blocks for node in ast.walk(ast.parse(textwrap.dedent(block)))
                 if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                 and isinstance(node.func.value, ast.Name)
                 and node.func.value.id == "subprocess" and node.func.attr == "run"]
        self.assertEqual(len(calls), 1)
        args = calls[0].args[0].elts
        self.assertEqual(len(args), 8)
        self.assertEqual([args[i].value for i in (1, 2, 4, 6)],
                         ["scripts/run_active_enospc.py", "--suite", "--test-executable", "--output"])
        self.assertIsInstance(args[3], ast.Name)
        self.assertEqual(args[3].id, "suite")
        self.assertTrue(any(k.arg == "check" and k.value.value is True for k in calls[0].keywords))
        self.assertIn('--test "${ZEVUNE_ENOSPC_SUITE}_enospc" --no-run', source)
        self.assertEqual((runner.CASE_SECONDS, runner.NAMESPACE_SECONDS, runner.WATCHDOG_SECONDS,
                          runner.OUTER_SECONDS), (180, 420, 430, 450))

    def test_schema_is_complete_and_routed_only_to_its_suite(self):
        data = fixture()
        self.assertEqual(set(data), evidence.FIELDS)
        runner.validate_receipt(data, CASE, "wallet_prepare")
        for suite in ("wallet", "active"):
            with self.assertRaises(ValueError):
                runner.validate_receipt(data, CASE, suite)
        self.assertEqual(runner.SUITE_TEST_FILES["wallet_prepare"], "wallet_prepare_enospc.rs")
        self.assertEqual(len(runner.WALLET_CASES), 2)
        self.assertEqual(len(runner.CASES), 2)

    def test_every_field_is_required_and_unknown_fields_fail(self):
        for field in evidence.FIELDS:
            data = fixture()
            del data[field]
            with self.subTest(field=field), self.assertRaises(ValueError):
                evidence.validate_receipt(data, CASE)
        data = fixture()
        data["private_key"] = "SENTINEL"
        with self.assertRaises(ValueError):
            evidence.validate_receipt(data, CASE)

    def test_booleans_integers_hashes_and_false_funds_are_strict(self):
        groups = ((evidence.TRUE_FIELDS, (False, 1, None, "true")),
                  (evidence.INTEGERS | {"schema_version"}, (True, -1, 2**64, 1.5, "2")),
                  (evidence.HASHES, (False, None, "A" * 64, "a" * 63, "a" * 64 + "\n")),
                  ({"real_funds_allowed"}, (True, 0, None, "false")))
        for fields, values in groups:
            for field in fields:
                for value in values:
                    data = fixture()
                    data[field] = value
                    with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                        evidence.validate_receipt(data, CASE)

    def test_extents_and_generations_cannot_describe_sync_or_compaction(self):
        changes = ({"before_len": 98916}, {"after_len": 102400}, {"changed_suffix_len": 3484},
                   {"receipt_generation": 3}, {"pending_generation": 4}, {"final_generation": 5},
                   {"before_sha256": "9" * 64}, {"pending_pin_sha256": "c" * 64},
                   {"filler_bytes": 4097}, {"filler_errno": 5}, {"target_ino": 0},
                   {"target_rel": "compacted/wallet.journal"}, {"profile": "wallet_journal_v1"})
        for change in changes:
            data = fixture()
            data.update(change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                evidence.validate_receipt(data, CASE)

    def test_public_summary_cannot_echo_outbox_or_other_suite(self):
        report = {"kind": "linux_tmpfs_enospc", "suite": "wallet_prepare", "cases": [
            {"case": CASE, "target_rel": evidence.CASES[CASE], "completed": True,
             "receipt": {**fixture(), "signed_outbox": "SENTINEL"}, "stderr": "SENTINEL",
             "rust_test_location": {"file": "wallet_enospc.rs", "line": 12}}]}
        summary = runner.public_summary(report)
        self.assertEqual(len(summary["cases"]), 1)
        self.assertNotIn("SENTINEL", json.dumps(summary))
        self.assertNotIn("rust_test_line", summary["cases"][0])


@unittest.skipUnless(sys.platform == "linux", "Linux ownership and harness semantics")
class PrepareFileTests(unittest.TestCase):
    def test_retained_files_and_each_pin_are_bound(self):
        mutations = (None, "checkpoint.bin", "pending-checkpoint.bin", "final-checkpoint.bin",
                     "backup/wallet.journal", "restored/wallet.journal", "source", "partial_generation",
                     "partial_predecessor", "foreign_pending", "old_final", "link")
        for mutation in mutations:
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary).resolve()
                mount, control = root / "mount", root / "control"
                mount.mkdir(); control.mkdir()
                data = write_fixture(mount, control)
                if mutation in ("checkpoint.bin", "pending-checkpoint.bin", "final-checkpoint.bin",
                                "backup/wallet.journal", "restored/wallet.journal"):
                    path = control / mutation
                    raw = bytearray(path.read_bytes()); raw[-1] ^= 1; path.write_bytes(raw)
                elif mutation in ("source", "partial_generation", "partial_predecessor"):
                    path = mount / evidence.CASES[CASE]
                    raw = bytearray(path.read_bytes())
                    index = {"source": 100, "partial_generation": evidence.BEFORE,
                             "partial_predecessor": evidence.BEFORE + 8}[mutation]
                    raw[index] ^= 1; path.write_bytes(raw)
                    data["after_sha256"] = hashlib.sha256(raw).hexdigest()
                elif mutation == "foreign_pending":
                    _, wrong = public_wallet_chain(3, marker=b"q")
                    (control / "pending-checkpoint.bin").write_bytes(wrong)
                    data["pending_pin_sha256"] = hashlib.sha256(wrong).hexdigest()
                elif mutation == "old_final":
                    raw, _ = public_wallet_chain(3)
                    (control / "restored/wallet.journal").write_bytes(raw)
                    data["restored_sha256"] = hashlib.sha256(raw).hexdigest()
                elif mutation == "link":
                    path = control / "checkpoint.bin"
                    path.rename(control / "retained.bin")
                    path.symlink_to(control / "retained.bin")
                if mutation is None:
                    verify(mount, control, data)
                else:
                    with self.assertRaises((ValueError, OSError)):
                        verify(mount, control, data)

    def test_namespace_path_checks_are_executed_after_trace_validation(self):
        for mutation in (None, "inode", "pending_pin", "no_trace"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as temporary, \
                    patch.object(runner.os, "chown"), patch.object(runner, "utility"):
                base = Path(temporary)
                def execute(command, **kwargs):
                    for descriptor in kwargs["trace_pipe"]:
                        os.close(descriptor)
                    mount, control = base / "mount-0", base / "control-0"
                    self.assertEqual(command.count("-P"), 1)
                    self.assertEqual(command[command.index("-P") + 1], str(mount / evidence.CASES[CASE]))
                    self.assertEqual(command[command.index("--exact") + 1], CASE)
                    data = write_fixture(mount, control)
                    if mutation == "inode":
                        data["target_ino"] += 1
                    elif mutation == "pending_pin":
                        (control / "pending-checkpoint.bin").write_bytes(b"x" * 72)
                    (control / "receipt.json").write_text(json.dumps(data))
                    return completed(trace=b"") if mutation == "no_trace" else completed()
                with patch.object(runner, "verify_mount", return_value={"device": base.stat().st_dev}), \
                        patch.object(runner, "run_bounded", side_effect=execute), \
                        patch.object(runner, "verify_exhausted", return_value={"block_exhaustion_confirmed": True}), \
                        patch.object(Path, "rmdir"):
                    result = runner.run_case(Path("/unused"), CASE, base, os.geteuid(), os.getegid(),
                                             time.monotonic() + 30, suite="wallet_prepare")
                self.assertEqual(result["completed"], mutation is None)
                self.assertTrue(result["ordinary_unmount_succeeded"])
                if mutation == "pending_pin":
                    self.assertEqual(result["failure_stage"], "wallet_prepare_file_identities")


if __name__ == "__main__":
    unittest.main()
