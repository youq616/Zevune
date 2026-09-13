"""Public capacity diagnostics; synthetic bytes never represent spendable funds."""
import copy
import contextlib
import importlib.util
import io
from pathlib import Path
import struct
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("wallet_storage_console", Path(__file__).resolve().parents[1] / "zevune_wallet.py")
wallet = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wallet)


def response(used):
    return {"ok": True, "scope": "local_journal_only_no_funds",
            "result": "storage_inspected_not_synced", "receipt": "01" * 72,
            "wallet_storage": {"format": "zevune-wallet-capacity-1", "records_used": used,
            "records_remaining": 256 - used, "max_records": 256,
            "file_bytes": 72 + used * 32948, "max_file_bytes": 8434760,
            "can_append": used < 256}}


class StorageStatusTests(unittest.TestCase):
    def test_new_and_full_reports_are_not_balance_or_confirmation(self):
        for used in (1, 255, 256):
            r = response(used)
            before = copy.deepcopy(r)
            self.assertEqual(wallet.checked_storage_status(r), r["wallet_storage"])
            self.assertEqual(r, before)
            for key in ("balance", "signing_domain", "confirmed"):
                self.assertNotIn(key, r)

    def test_rejects_false_capacity_and_noncanonical_types(self):
        for field, value in [("records_used", 0), ("records_used", 257),
                             ("records_used", True), ("records_remaining", -1),
                             ("max_records", 257), ("file_bytes", 10),
                             ("max_file_bytes", 0), ("can_append", 1),
                             ("can_append", False), ("records_used", 1.0)]:
            r = response(1)
            r["wallet_storage"][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(RuntimeError):
                wallet.checked_storage_status(r)
        r = response(256)
        r["wallet_storage"]["can_append"] = True
        with self.assertRaises(RuntimeError): wallet.checked_storage_status(r)

    def test_extra_missing_and_unsupported_fields_fail(self):
        for edit in ("extra", "missing", "version"):
            r = response(1)
            if edit == "extra": r["wallet_storage"]["balance"] = 1
            if edit == "missing": del r["wallet_storage"]["records_remaining"]
            if edit == "version": r["wallet_storage"]["format"] = "next"
            with self.subTest(edit=edit), self.assertRaises(RuntimeError):
                wallet.checked_storage_status(r)
        with self.assertRaises(RuntimeError): wallet.checked_storage_status({})

    def test_storage_request_has_one_field_and_existing_private_pin(self):
        raw = wallet.encode_request(9, b"synthetic-unused-password", ["/wallet"], "01" * 72)
        self.assertEqual(raw[:9], b"ZVWCLI01\x09")
        password_size = struct.unpack(">H", raw[9:11])[0]
        self.assertEqual(raw[11 + password_size], 1)
        self.assertEqual(raw[12 + password_size + 72], 1)
        with self.assertRaises(ValueError):
            wallet.encode_request(9, b"synthetic-unused-password", ["/wallet", "/extra"])

    def test_console_storage_never_selects_history_or_constructs_payment(self):
        with patch.object(wallet, "hidden_password", return_value=b"synthetic-unused-password"), \
             patch.object(wallet, "genesis_identity", side_effect=AssertionError("must not load history")), \
             patch.object(wallet, "invoke", return_value=response(256)) as call, \
             patch("builtins.input", side_effect=AssertionError("must not ask payment intent")), \
             contextlib.redirect_stdout(io.StringIO()) as stdout, \
             contextlib.redirect_stderr(io.StringIO()):
            code = wallet.main(["--no-real-funds", "storage", "/unused-wallet"])
            self.assertEqual(code, 0)
            self.assertEqual(call.call_args.args[1][8], 9)
            self.assertNotIn('"balance"', stdout.getvalue())
            self.assertIn('"can_append": false', stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
