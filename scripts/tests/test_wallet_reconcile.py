"""Pure framing/schema tests and refusing backends; no accepting crypto double."""
import copy
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import wallet_reconcile as r
from test_wallet_backup import frames
from test_ledger_restore import pin
from ledger_recovery_backend import Checkpoint


def status(pending=True):
    return dict(ok=True, scope=r.SCOPE, payment_profile="LAB2", signing_domain="c" * 64,
                genesis_sha256="c" * 64, height=0, balance=100000, available=0 if pending else 100000,
                pending=pending, receipt=frames(3)[1])


class WalletReconcileTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="reconcile-unit-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.identity = dict(payment_profile="LAB2", signing_domain="c" * 64, genesis_sha256="c" * 64)
        self.checkpoint = Checkpoint.parse(pin())

    def test_public_ancestor_and_exact_tip_are_not_authentication(self):
        raw, tip = frames(3)
        for generation in (1, 2, 3):
            self.assertEqual(r.public_tip(raw, frames(generation)[1]), tip)
        for bad in (frames(4)[1], frames(2, marker=b"x")[1], frames(2)[1][:80] + "0" * 64):
            with self.assertRaises(ValueError):
                r.public_tip(raw, bad)

    def test_partial_extra_or_rehashed_history_mismatch_rejected(self):
        raw, tip = frames(3)
        for bad in (None, b"", raw[:-1], raw + b"x", raw[:100] + bytes([raw[100] ^ 1]) + raw[101:]):
            with self.assertRaises(ValueError):
                r.public_tip(bad, tip)
        with self.assertRaises(ValueError):
            r.public_tip(raw, True)

    def test_ancestor_is_passed_to_native_and_refusal_preserves_source(self):
        raw, tip = frames(3)
        old = frames(2)[1]
        source = self.root / "source.wallet"
        source.write_bytes(raw)
        class Refusing:
            def call(self, op, password, paths, receipt):
                assert op == 9 and receipt == old and paths == [str(source)]
                raise RuntimeError("genuine_auth_required")
        with self.assertRaises(RuntimeError):
            r.discover(source, old, b"test-only", Refusing())
        self.assertEqual(source.read_bytes(), raw)
        self.assertEqual(list(self.root.iterdir()), [source])

    def test_incomplete_native_response_cannot_authenticate(self):
        raw, tip = frames(3)
        source = self.root / "source.wallet"
        source.write_bytes(raw)
        for invalid in ({}, {"ok": True}, {"ok": 1, "receipt": tip}):
            class InvalidOnly:
                def call(self, *args):
                    return invalid
            with self.assertRaises(ValueError):
                r.discover(source, frames(2)[1], b"unused", InvalidOnly())
        self.assertEqual(source.read_bytes(), raw)

    def test_status_strict_fields_types_height_and_single_append(self):
        good = status()
        self.assertEqual(r.checked_status(good, self.identity, self.checkpoint, frames(2)[1]), good["receipt"])
        for field in good:
            bad = dict(good)
            del bad[field]
            with self.subTest(missing=field), self.assertRaises(ValueError):
                r.checked_status(bad, self.identity, self.checkpoint, frames(2)[1])
        changes = ({"height": True}, {"height": 1}, {"pending": 1}, {"balance": True}, {"available": -1},
                   {"balance": 100001}, {"available": 100001}, {"receipt": frames(4)[1]},
                   {"receipt": frames(1)[1]}, {"receipt": frames(3, marker=b"q")[1]},
                   {"genesis_sha256": "0" * 64}, {"signing_domain": None}, {"ok": 1},
                   {"scope": "finality"}, {"local_timing": {}})
        for change in changes:
            with self.subTest(change=change), self.assertRaises(ValueError):
                r.checked_status({**good, **change}, self.identity, self.checkpoint, frames(2)[1])

    def test_no_pending_schema_does_not_add_settlement_or_retry_permission(self):
        empty = status(False)
        before = copy.deepcopy(empty)
        self.assertEqual(r.checked_status(empty, self.identity, self.checkpoint, frames(2)[1]), empty["receipt"])
        self.assertEqual(empty, before)
        for misleading in ("confirmed", "settled", "expired", "retry_authorized"):
            with self.assertRaises(ValueError):
                r.checked_status({**empty, misleading: True}, self.identity, self.checkpoint, frames(2)[1])

    def test_budget_counts_copy_plus_one_append_transaction_and_report(self):
        size = len(frames(2)[0])
        required = 102400 + 32768 + 4096 + 100
        sample = dict(allocation_unit_bytes=4096, available_bytes=required, available_inodes=4, read_only=False)
        with patch.object(r.space, "probe", return_value=sample) as probe:
            self.assertEqual(r.budget(self.root, (1, 2), size, 100), required)
            probe.assert_called_once_with(self.root, expected_identity=(1, 2))
        for change in ({"available_bytes": required - 1}, {"available_inodes": 3}, {"read_only": True}):
            with patch.object(r.space, "probe", return_value={**sample, **change}), self.assertRaises(ValueError):
                r.budget(self.root, (1, 2), size, 100)

    def test_unknown_allocation_and_bounds_preserve_original_wallet_limit(self):
        sample = dict(allocation_unit_bytes=None, available_bytes=(1 << 63) - 1, available_inodes=None, read_only=None)
        with patch.object(r.space, "probe", return_value=sample):
            self.assertEqual(r.budget(self.root, (1, 2), len(frames(2)[0]), 0), 98916 + 32768 + 4096)
            self.assertEqual(r.budget(self.root, (1, 2), r.files.MAX_WALLET, 0), r.files.MAX_WALLET + 32768 + 4096)
            for bad in (True, -1, 1 << 63, (1 << 63) - 1):
                with self.assertRaises(ValueError):
                    r.budget(self.root, (1, 2), len(frames(2)[0]), bad)
            for bad in (True, -1, 72, r.files.MAX_WALLET + 1):
                with self.assertRaises(ValueError):
                    r.budget(self.root, (1, 2), bad, 0)

    def test_fixed_scan_and_export_never_expose_sign_operation(self):
        backend = r.ReconcileBackend(self.root / "unused", "0" * 64)
        # Observe wire operations, then refuse; this does not fake auth success.
        with patch.object(backend, "_exchange", side_effect=RuntimeError("wire_observation_only")) as exchange:
            for action, op in ((lambda: backend.status(b"x" * 16, ["a", "b", "c", "d"], frames()[1]), 3),
                               (lambda: backend.pending(b"x" * 16, ["a", "b", "c", "d", "e"], frames()[1]), 5)):
                with self.assertRaises(RuntimeError):
                    action()
                self.assertEqual(exchange.call_args.args[0][8], op)
            with self.assertRaises(RuntimeError):
                backend.call(4, b"x" * 16, [], frames()[1])

    def test_existing_output_refuses_without_backend_or_source_access(self):
        output = self.root / "existing"
        output.mkdir()
        with self.assertRaises(ValueError):
            r.recover(self.root / "missing", output, frames()[1], b"unused", None,
                      journal=self.root, checkpoint=pin(), genesis=self.root / "missing-genesis",
                      genesis_sha256="1" * 64, recovery_backend=None, reserve_bytes=0)
        self.assertEqual(list(output.iterdir()), [])

    def test_plain_python_cli_no_cache_or_secret_syntax_echo(self):
        folder = self.root / "bundle"
        folder.mkdir()
        for name in ("wallet_reconcile.py", "wallet_backup.py", "wallet_backup_backend.py", "wallet_health.py",
                     "wallet_archive.py", "zevune_wallet.py", "ledger_restore.py", "ledger_recovery_backend.py"):
            shutil.copyfile(Path(r.__file__).parent / name, folder / name)
        before = {p.name: p.read_bytes() for p in folder.iterdir()}
        env = os.environ.copy()
        for key in ("PYTHONDONTWRITEBYTECODE", "PYTHONPYCACHEPREFIX"):
            env.pop(key, None)
        for args, code in ((["--help"], 0), (["--no-real-funds", "recover", "--help"], 0),
                           (["--password", "PRIVATE_SENTINEL"], 64)):
            result = subprocess.run([sys.executable, str(folder / "wallet_reconcile.py"), *args],
                                    capture_output=True, timeout=20, env=env)
            self.assertEqual(result.returncode, code)
            self.assertNotIn(b"PRIVATE_SENTINEL", result.stdout + result.stderr)
        self.assertEqual({p.name: p.read_bytes() for p in folder.iterdir()}, before)

    def test_no_pending_cannot_report_reserved_balance(self):
        response = status(False)
        response["available"] -= 1
        with self.assertRaises(ValueError):
            r.checked_status(response, self.identity, self.checkpoint, frames(2)[1])

    def test_unchanged_generation_must_return_identical_receipt(self):
        response = status()
        response["receipt"] = response["receipt"][:80] + "0" * 64
        with self.assertRaises(ValueError):
            r.checked_status(response, self.identity, self.checkpoint, frames(3)[1])

    def test_source_module_does_not_silently_extend_native_bundle(self):
        import verify_local_lab as verify
        for windows in (False, True):
            self.assertNotIn("wallet_reconcile.py", verify.required_files(windows, 9))
            with self.assertRaises(ValueError):
                verify.required_files(windows, 10)


if __name__ == "__main__":
    unittest.main()
