"""Pure format/budget checks and refusal-only fixtures; no accepting backend."""
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
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import wallet_maintenance as maintenance
from test_wallet_backup import frames


def manifest():
    source, pin = frames(3)
    target, target_pin = frames(1, marker=b"q")
    return dict(format=maintenance.FORMAT, source_receipt=pin, target_receipt=target_pin,
                source_sha256=hashlib.sha256(source).hexdigest(), target_sha256=hashlib.sha256(target).hexdigest(),
                source_bytes=len(source), target_bytes=len(target), requires_rescan=True,
                source_not_revoked=True, real_funds_allowed=False)


class MaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()

    def test_complete_manifest_shape_and_exact_source_pin(self):
        data = manifest()
        self.assertEqual(maintenance.validate_manifest(data, data["source_receipt"]), data["target_receipt"])
        for field in data:
            changed = dict(data); del changed[field]
            with self.subTest(field=field), self.assertRaises(ValueError):
                maintenance.validate_manifest(changed, data["source_receipt"])
        changed = {**data, "filename": "../wallet"}
        with self.assertRaises(ValueError):
            maintenance.validate_manifest(changed, data["source_receipt"])

    def test_manifest_boolean_integer_digest_and_ancestry_rejection(self):
        data = manifest()
        changes = ({"source_bytes": True}, {"target_bytes": 1}, {"source_bytes": data["source_bytes"] + 1},
                   {"requires_rescan": 1}, {"source_not_revoked": False}, {"real_funds_allowed": 0},
                   {"source_sha256": "A" * 64}, {"target_sha256": []}, {"format": []},
                   {"target_receipt": data["source_receipt"]}, {"source_receipt": frames(2)[1]},
                   {"target_receipt": frames(2, marker=b"q")[1]})
        for change in changes:
            with self.subTest(change=list(change)), self.assertRaises(ValueError):
                maintenance.validate_manifest({**data, **change}, data["source_receipt"])

    def test_budget_accounts_three_files_and_four_entries(self):
        sample = dict(allocation_unit_bytes=4096, available_bytes=200000, available_inodes=4, read_only=False)
        # 98916 rounds to102400;33020 to36864;4096 marker+123 reserve.
        required = 102400 + 36864 + 4096 + 123
        with patch.object(maintenance.health, "probe", return_value=sample) as probe:
            self.assertEqual(maintenance.budget(self.root, (1, 2), 98916, 123), required)
            probe.assert_called_once_with(self.root, expected_identity=(1, 2))
        for changes in ({"available_bytes": required - 1}, {"available_inodes": 3}, {"read_only": True}):
            with patch.object(maintenance.health, "probe", return_value={**sample, **changes}), self.assertRaises(ValueError):
                maintenance.budget(self.root, (1, 2), 98916, 123)
        with patch.object(maintenance.health, "probe", return_value={**sample, "available_bytes": required}):
            self.assertEqual(maintenance.budget(self.root, (1, 2), 98916, 123), required)

    def test_unknown_allocation_uses_logical_bytes_without_claiming_inode_check(self):
        sample = dict(allocation_unit_bytes=None, available_bytes=200000, available_inodes=None, read_only=None)
        with patch.object(maintenance.health, "probe", return_value=sample):
            self.assertEqual(maintenance.budget(self.root, (1, 2), 98916, 0), 98916 + 33020 + 4096)
            for bad in (True, -1, 1 << 63):
                with self.assertRaises(ValueError):
                    maintenance.budget(self.root, (1, 2), 98916, bad)
            with self.assertRaises(ValueError):
                maintenance.budget(self.root, (1, 2), 98916, (1 << 63) - 1)

    def test_incomplete_and_unknown_entries_are_not_complete_handover(self):
        for name in ("backup.journal", "compacted.journal", maintenance.MANIFEST):
            with self.assertRaises(ValueError):
                maintenance.inventory(self.root)
            (self.root / name).write_bytes(b"inert")
        maintenance.inventory(self.root)
        (self.root / "extra").mkdir()
        with self.assertRaises(ValueError):
            maintenance.inventory(self.root)

    def test_existing_target_and_wrong_source_pin_refused_before_authentication(self):
        raw, pin = frames(3)
        source = self.root / "source.wallet"; source.write_bytes(raw)
        destination = self.root / "new"
        with patch.object(maintenance.catalog, "authenticate", side_effect=AssertionError("must not authenticate")):
            with self.assertRaises(ValueError):
                maintenance.compact(source, destination, frames(2)[1], b"unused", None, reserve_bytes=0)
            destination.mkdir()
            with self.assertRaises(ValueError):
                maintenance.compact(source, destination, pin, b"unused", None, reserve_bytes=0)
        self.assertEqual(source.read_bytes(), raw)
        self.assertEqual(list(destination.iterdir()), [])

    def test_public_framing_cannot_replace_real_authentication(self):
        raw, pin = frames(3)
        source = self.root / "source.wallet"; source.write_bytes(raw)
        destination = self.root / "new"
        with patch.object(maintenance.catalog, "authenticate", side_effect=RuntimeError("refusal only")), self.assertRaises(RuntimeError):
            maintenance.compact(source, destination, pin, b"unused", None, reserve_bytes=0)
        self.assertFalse(destination.exists())
        self.assertEqual(source.read_bytes(), raw)

    def test_wrong_independent_manifest_digest_refuses_before_authentication(self):
        for name in maintenance.FILES:
            (self.root / name).write_bytes(b"not authenticated")
        with patch.object(maintenance.catalog, "authenticate", side_effect=AssertionError("must not authenticate")):
            for digest in ("0" * 64, "A" * 64, None):
                with self.assertRaises(ValueError):
                    maintenance.verify(self.root, frames(3)[1], digest, b"unused", None)

    def test_cli_cache_and_secret_argument_redaction(self):
        bundle = self.root / "bundle"; bundle.mkdir()
        names = ("wallet_maintenance.py", "wallet_health.py", "wallet_archive.py", "wallet_backup.py",
                 "wallet_backup_backend.py", "zevune_wallet.py")
        for name in names:
            shutil.copyfile(Path(maintenance.__file__).parent / name, bundle / name)
        before = {p.name: p.read_bytes() for p in bundle.iterdir()}
        env = os.environ.copy()
        for key in ("PYTHONDONTWRITEBYTECODE", "PYTHONPYCACHEPREFIX"):
            env.pop(key, None)
        for args, code in ((["--help"], 0), (["--no-real-funds", "compact", "--help"], 0),
                           (["--password", "PRIVATE_SENTINEL"], 64)):
            run = subprocess.run([sys.executable, str(bundle / "wallet_maintenance.py"), *args],
                                 capture_output=True, timeout=20, env=env)
            self.assertEqual(run.returncode, code)
            self.assertNotIn(b"PRIVATE_SENTINEL", run.stdout + run.stderr)
        self.assertEqual({p.name: p.read_bytes() for p in bundle.iterdir()}, before)


if __name__ == "__main__":
    unittest.main()
