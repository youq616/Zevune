"""Capacity arithmetic, actual OS probes and refusal-only wallet fixtures.

These synthetic public frames do not authenticate. Complete success paths are
exercised separately with the real pinned Rust wallet, never an accepting double.
"""
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import wallet_health as health
import wallet_backup as catalog
from test_wallet_backup import frames


def disk(available=1 << 30, unit=4096, inodes=100, readonly=False):
    return dict(available_bytes=available, allocation_unit_bytes=unit,
                available_inodes=inodes, read_only=readonly)


class CapacityPlanTests(unittest.TestCase):
    def test_canonical_policy_and_type_boundaries(self):
        for text, number in (("0", 0), ("16", 16), (str(health.MAX_NUMBER), health.MAX_NUMBER)):
            self.assertEqual(health.decimal(text), number)
        for bad in (True, None, "", "01", "-1", "+1", "1.0", " 1", "1\n", "１", str(1 << 63), [], {}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                health.decimal(bad)
        for bad in (False, -1, 1.5, "1", 1 << 63):
            with self.assertRaises(ValueError):
                health.bounded(bad)

    def test_budget_rounds_each_file_not_only_combined_size(self):
        result = health.estimate([4097, 1], disk(), 123, 3)
        self.assertEqual(result["payload_bytes"], 4098)
        self.assertEqual(result["payload_estimate_bytes"], 12288)
        self.assertEqual(result["required_with_reserve_bytes"], 12411)
        self.assertEqual(result["shortfall_bytes"], 0)
        self.assertFalse(result["space_reserved"])
        self.assertFalse(result["write_success_guaranteed"])
        self.assertEqual(health.estimate([4096], disk(), 0, 1)["payload_estimate_bytes"], 4096)

    def test_unknown_allocation_and_inode_counts_stay_unknown(self):
        result = health.estimate([4097], disk(unit=None, inodes=None, readonly=None), 0, 1)
        self.assertEqual(result["payload_estimate_bytes"], 4097)
        self.assertEqual(result["inode_check"], "unknown")
        self.assertIsNone(result["read_only"])
        self.assertEqual(result["estimate_basis"], "logical_data_bytes_allocation_unknown")

    def test_reserve_inclusive_boundary_and_payload_shortfall(self):
        for free, expected in ((4196, "nominal"), (4195, "warning"), (4096, "warning"), (4095, "critical"), (0, "critical")):
            budget = health.estimate([4000], disk(available=free), 100, 1)
            assessment = health.assessment(255, 1, 16, budget)
            self.assertEqual(assessment["severity"], expected)
            self.assertEqual(budget["shortfall_bytes"], max(0, 4196 - free))

    def test_record_budget_is_saves_not_payment_count(self):
        budget = health.estimate([catalog.RECORD], disk(), 0, 0)
        for remaining, saves, expected in ((255, 1, "nominal"), (17, 1, "warning"), (18, 1, "nominal"),
                                            (1, 1, "warning"), (0, 1, "critical"), (20, 21, "critical")):
            self.assertEqual(health.assessment(remaining, saves, 16, budget)["severity"], expected)
        self.assertEqual(health.assessment(0, 1, 16, budget, source=False)["severity"], "nominal")
        for remaining, saves, warn in ((256, 1, 16), (0, 0, 16), (1, 1, 256), (-1, 1, 16)):
            with self.assertRaises(ValueError):
                health.assessment(remaining, saves, warn, budget)

    def test_readonly_and_inode_exhaustion_are_not_nominal(self):
        budget = health.estimate([1], disk(readonly=True), 0, 1)
        self.assertIn("filesystem_read_only", health.assessment(255, 1, 0, budget)["issues"])
        budget = health.estimate([1], disk(inodes=2), 0, 3)
        self.assertEqual(health.assessment(255, 1, 0, budget, source=False)["severity"], "critical")
        budget = health.estimate([1], disk(inodes=0), 0, 0)
        self.assertEqual(budget["inode_check"], "sufficient")  # existing journal append

    def test_every_operation_counts_retained_source_as_zero_reclaimed(self):
        for generation in (1, 3, 255, 256):
            wallet, pin = frames(generation)
            snapshot = catalog.wallet_bytes_summary(wallet, pin)
            metadata = len(catalog.canonical(health.archive.manifest_for(pin, snapshot)))
            expected = {
                "wallet-copy": ([len(wallet)], 1),
                "catalog-backup": ([len(wallet), metadata], 3),
                "archive-export": ([16 + len(wallet) + metadata], 1),
                "compact-copy": ([catalog.HEADER + catalog.RECORD], 1),
            }
            for op in health.OPERATIONS:
                files, entries, steps = health.operation_payload(op, pin, snapshot)
                self.assertEqual((files, entries), expected[op])
                self.assertGreater(len(steps), 2)
                self.assertGreater(health.estimate(files, disk(), 0, entries)["payload_bytes"], 0)
        with self.assertRaises(ValueError):
            health.operation_payload("delete", pin, snapshot)

    def test_overflow_or_invalid_allocation_does_not_wrap_to_good(self):
        for sizes, sample, reserve, entries in (([health.MAX_NUMBER], disk(), 1, 1), ([1], disk(unit=0), 0, 1),
                                              ([], disk(), 0, 1), ([True], disk(), 0, 1), ([1], disk(), -1, 1),
                                              ([1], disk(available=-1), 0, 1), ([1], disk(), 0, 4)):
            with self.assertRaises(ValueError):
                health.estimate(sizes, sample, reserve, entries)


class OSProbeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()

    def test_actual_platform_probe_is_readonly_and_bounded(self):
        if sys.platform not in ("linux", "win32"):
            self.skipTest("native Linux/Windows capacity scope")
        before = list(self.root.iterdir())
        result = health.probe(self.root)
        self.assertEqual(set(result), {"method", "total_bytes", "available_bytes", "allocation_unit_bytes", "available_inodes", "read_only"})
        self.assertLessEqual(0, result["available_bytes"])
        self.assertLessEqual(result["available_bytes"], result["total_bytes"])
        self.assertEqual(list(self.root.iterdir()), before)

    @unittest.skipUnless(sys.platform == "linux", "real Linux directory descriptor")
    def test_linux_uses_available_not_reserved_blocks_and_reports_readonly(self):
        stats = SimpleNamespace(f_frsize=4096, f_blocks=100, f_bfree=20, f_bavail=5,
                                f_files=100, f_favail=3, f_flag=os.ST_RDONLY)
        with patch.object(health.os, "fstatvfs", return_value=stats):
            result = health.probe(self.root)
        self.assertEqual(result["available_bytes"], 5 * 4096)
        self.assertTrue(result["read_only"])
        stats.f_files = 0
        with patch.object(health.os, "fstatvfs", return_value=stats):
            self.assertIsNone(health.probe(self.root)["available_inodes"])
        stats.f_bavail = 101
        with patch.object(health.os, "fstatvfs", return_value=stats), self.assertRaises(ValueError):
            health.probe(self.root)
        with patch.object(health.os, "fstatvfs", side_effect=OSError("private sentinel")), self.assertRaises(OSError):
            health.probe(self.root)

    def test_windows_caller_free_does_not_assume_used_plus_free_equals_total(self):
        usage = SimpleNamespace(total=10000, used=9000, free=400)
        with patch.object(health.sys, "platform", "win32"), patch.object(health.shutil, "disk_usage", return_value=usage):
            result = health.probe(self.root)
        self.assertEqual(result["available_bytes"], 400)
        self.assertIsNone(result["allocation_unit_bytes"])
        self.assertIsNone(result["read_only"])

    def test_probe_rejects_changed_directory_and_unsupported_platform(self):
        original = health.directory_id(self.root)
        with patch.object(health, "directory_id", side_effect=[original, (original[0], original[1] + 1)]), self.assertRaises(ValueError):
            health.probe(self.root)
        with patch.object(health.sys, "platform", "unsupported"), self.assertRaises(ValueError):
            health.probe(self.root)
        with self.assertRaises((OSError, ValueError)):
            health.probe(self.root / "missing")
        self.assertFalse((self.root / "missing").exists())


class HealthRefusalTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.raw, self.pin = frames(3)
        self.wallet = self.root / "source.wallet"
        self.wallet.write_bytes(self.raw)

    def test_public_frame_cannot_substitute_for_authentication(self):
        with patch.object(catalog, "authenticate", side_effect=RuntimeError("AEAD required")), self.assertRaises(RuntimeError):
            health.inspect(self.wallet, self.pin, b"refusal-only", None, reserve_bytes=0)
        self.assertEqual(self.wallet.read_bytes(), self.raw)
        self.assertEqual(list(self.root.iterdir()), [self.wallet])

    def test_wrong_tip_or_source_change_is_not_a_health_success(self):
        with self.assertRaises(ValueError):
            health.inspect(self.wallet, frames(2)[1], b"unused", None, reserve_bytes=0)
        before = catalog.wallet_snapshot(self.wallet, self.pin)
        self.wallet.write_bytes(self.raw + b"x")
        with self.assertRaises(ValueError):
            catalog.same_wallet(self.wallet, self.pin, before)

    def test_invalid_plan_rejected_without_creating_target_or_authenticating(self):
        with patch.object(catalog, "authenticate", side_effect=AssertionError("must not authenticate")):
            for args in ({"operation": "compact-copy"}, {"target_directory": self.root},
                         {"operation": "delete", "target_directory": self.root}, {"saves": 0},
                         {"operation": "wallet-copy", "target_directory": self.root / "missing"}):
                with self.assertRaises((ValueError, OSError)):
                    health.inspect(self.wallet, self.pin, b"unused", None, reserve_bytes=0, **args)
        self.assertEqual(list(self.root.iterdir()), [self.wallet])

    def test_cli_failures_are_redacted_and_do_not_prompt(self):
        args = ["--no-real-funds", "check", str(self.wallet), "--pin", "PRIVATE_SENTINEL",
                "--backend", str(self.root / "private"), "--backend-sha256", "0" * 64, "--reserve-bytes", "1"]
        out, err = io.StringIO(), io.StringIO()
        with patch.object(health, "hidden_password", side_effect=AssertionError("no prompt")), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            self.assertEqual(health.main(args), 1)
        self.assertEqual(out.getvalue(), "")
        self.assertNotIn("PRIVATE_SENTINEL", err.getvalue())
        self.assertNotIn(str(self.root), err.getvalue())

    def test_normal_cli_help_syntax_errors_and_cache_policy(self):
        bundle = self.root / "bundle"
        bundle.mkdir()
        scripts = Path(health.__file__).parent
        for name in ("wallet_health.py", "wallet_archive.py", "wallet_backup.py", "wallet_backup_backend.py", "zevune_wallet.py"):
            shutil.copyfile(scripts / name, bundle / name)
        before = {p.name: p.read_bytes() for p in bundle.iterdir()}
        env = os.environ.copy()
        for name in ("PYTHONDONTWRITEBYTECODE", "PYTHONPYCACHEPREFIX"):
            env.pop(name, None)
        for args, code in ((["--help"], 0), (["--no-real-funds", "plan", "--help"], 0),
                           (["--password", "PRIVATE_SENTINEL"], 64)):
            run = subprocess.run([sys.executable, str(bundle / "wallet_health.py"), *args],
                                 capture_output=True, timeout=20, env=env)
            self.assertEqual(run.returncode, code)
            self.assertNotIn(b"PRIVATE_SENTINEL", run.stdout + run.stderr)
            self.assertNotIn(b"--password", run.stdout)
            self.assertTrue({p.name: p.read_bytes() for p in bundle.iterdir()} == before)


if __name__ == "__main__":
    unittest.main()
