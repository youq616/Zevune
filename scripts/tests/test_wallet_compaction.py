"""Compaction handover diagnostics and private input framing; synthetic pins."""
import contextlib
import copy
import importlib.util
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("compact_console", Path(__file__).resolve().parents[1] / "zevune_wallet.py")
wallet = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wallet)
SOURCE = "01" * 32 + (256).to_bytes(8, "big").hex() + "02" * 32
TARGET = "ab" * 32 + (1).to_bytes(8, "big").hex() + "cd" * 32
PASSWORD = b"synthetic-never-used-password"


def response():
    return {"ok": True, "scope": "local_journal_only_no_funds",
            "result": "compacted_copy_not_synced", "source_retained": True,
            "requires_rescan": True, "source_receipt": SOURCE, "receipt": TARGET,
            "wallet_storage": {"format": "zevune-wallet-capacity-1", "records_used": 1,
                "records_remaining": 255, "max_records": 256, "file_bytes": 33020,
                "max_file_bytes": 8434760, "can_append": True}}


class CompactionTests(unittest.TestCase):
    def test_receipt_handover_is_not_balance_or_finality(self):
        r = response()
        before = copy.deepcopy(r)
        self.assertEqual(wallet.checked_compaction(r, SOURCE), before)
        self.assertEqual(r, before)

    def test_mismatched_source_target_and_claimed_payment_status_rejected(self):
        for key, value in [("source_receipt", TARGET), ("receipt", SOURCE),
                ("receipt", "03" * 32 + "0000000000000002" + "04" * 32),
                ("receipt", TARGET.upper()), ("receipt", None),
                ("receipt", "01" * 32 + "0000000000000001" + "04" * 32),
                ("source_retained", 1), ("requires_rescan", 1),
                ("result", "confirmed"), ("balance", 0), ("available", 0),
                ("confirmed", False), ("txid", None)]:
            r = response(); r[key] = value
            with self.subTest(key=key, value=value), self.assertRaises(RuntimeError):
                wallet.checked_compaction(r, SOURCE)
        for pin in (None, "", "0" * 144, SOURCE + "\n"):
            with self.assertRaises(RuntimeError): wallet.checked_compaction(response(), pin)

    def test_capacity_report_must_be_one_record(self):
        r = response()
        r["wallet_storage"].update(records_used=2, records_remaining=254, file_bytes=65968)
        with self.assertRaises(RuntimeError): wallet.checked_compaction(r, SOURCE)

    def test_compact_frame_requires_pin_and_exactly_two_paths(self):
        raw = wallet.encode_request(10, PASSWORD, ["/source", "/target"], SOURCE)
        self.assertEqual(raw[:9], b"ZVWCLI01\x0a")
        self.assertIn(bytes.fromhex(SOURCE), raw)
        for fields, pin in [(["/source", "/target"], None), (["/source"], SOURCE),
                            (["/source", "/target", "/extra"], SOURCE)]:
            with self.assertRaises(ValueError): wallet.encode_request(10, PASSWORD, fields, pin)

    def test_missing_pin_or_existing_target_never_asks_password_or_starts_backend(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "existing"; p.write_bytes(b"must stay")
            for argv in [["--no-real-funds", "compact", "/source", str(p)],
                         ["--no-real-funds", "--pin", SOURCE, "compact", "/source", str(p)]]:
                with patch.object(wallet, "hidden_password", side_effect=AssertionError("password prompted")), \
                     patch.object(wallet, "invoke", side_effect=AssertionError("backend started")), \
                     contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(wallet.main(argv), 1)
            self.assertEqual(p.read_bytes(), b"must stay")

    def test_confirmation_and_response_checks_without_scanning_or_spending(self):
        with tempfile.TemporaryDirectory() as d:
            args = ["--no-real-funds", "--pin", SOURCE, "compact", str(Path(d)/"source"), str(Path(d)/"target")]
            with patch("builtins.input", return_value="COMPACT"), \
                 patch.object(wallet, "hidden_password", return_value=PASSWORD), \
                 patch.object(wallet, "genesis_identity", side_effect=AssertionError("history selected")), \
                 patch.object(wallet, "invoke", return_value=response()) as call, \
                 contextlib.redirect_stdout(io.StringIO()) as stdout, contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(wallet.main(args), 0)
                self.assertEqual(call.call_args.args[1][8], 10)
                self.assertNotIn('"balance"', stdout.getvalue())
            with patch("builtins.input", return_value="NO"), \
                 patch.object(wallet, "hidden_password", side_effect=AssertionError("password prompted")), \
                 patch.object(wallet, "invoke", side_effect=AssertionError("backend started")), \
                 contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(wallet.main(args), 1)


if __name__ == "__main__":
    unittest.main()
