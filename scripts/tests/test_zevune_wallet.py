import getpass
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import warnings

MODULE = Path(__file__).resolve().parents[1] / "zevune_wallet.py"
spec = importlib.util.spec_from_file_location("wallet_console", MODULE)
wallet = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wallet)
PASSWORD = b"synthetic-console-test-password"


class WalletConsoleTests(unittest.TestCase):
    def test_request_bounds_and_receipt(self):
        raw = wallet.encode_request(0, PASSWORD, ["/synthetic-wallet"])
        self.assertTrue(raw.startswith(b"ZVWCLI01\0"))
        self.assertIn(PASSWORD, raw)
        for op, fields in [(9, []), (0, []), (0, ["a", "b"]), (0, ["a\0b"]), (0, ["x" * 4097])]:
            with self.assertRaises(ValueError):
                wallet.encode_request(op, PASSWORD, fields)
        with self.assertRaises(ValueError):
            wallet.encode_request(0, b"short", ["/a"])
        with self.assertRaises(ValueError):
            wallet.encode_request(0, PASSWORD, ["/a"], "0" * 144)
        self.assertIn(bytes.fromhex("01" * 72), wallet.encode_request(1, PASSWORD, ["/a", "0"], "01" * 72))

    def test_address_checksum_and_numeric_canonicality(self):
        raw = bytes(range(43))
        digest = hashlib.sha256(b"ZEVUNE-LOCAL-ADDRESS\0\x01" + raw).hexdigest()[:8]
        address = "zvlab:" + raw.hex() + ":" + digest
        self.assertEqual(wallet.checked_address(address), address)
        for bad in [address + "x", address.upper(), address[:-1] + ("0" if address[-1] != "0" else "1")]:
            with self.assertRaises(ValueError):
                wallet.checked_address(bad)
        for bad in ["01", "-1", "+1", " 1", "1.0", str(1 << 64)]:
            with self.assertRaises(ValueError):
                wallet.integer(bad)
        self.assertEqual(wallet.integer("0"), "0")

    def test_no_echo_fallback_and_confirmation(self):
        def fallback(*args):
            warnings.warn("No echo protection", getpass.GetPassWarning)
            return "not-used"
        with patch.object(getpass, "getpass", side_effect=fallback):
            with self.assertRaises(getpass.GetPassWarning):
                wallet.hidden_password(False)
        with patch.object(getpass, "getpass", side_effect=["synthetic-test-one", "synthetic-test-two"]):
            with self.assertRaises(ValueError):
                wallet.hidden_password(True)

    def test_private_input_never_enters_arguments_or_environment(self):
        with tempfile.TemporaryDirectory() as directory:
            backend = Path(directory) / "only-a-test-double"
            backend.write_bytes(b"not-executed")
            request = wallet.encode_request(0, PASSWORD, ["/private-path"])
            response = {"ok": True, "scope": "local_journal_only_no_funds"}
            completed = subprocess.CompletedProcess([], 0, json.dumps(response).encode(), b"")
            with patch.dict(wallet.os.environ, {"SECRET_TOKEN": "synthetic-env-secret"}):
                with patch.object(subprocess, "run", return_value=completed) as run:
                    self.assertEqual(wallet.invoke(backend, request), response)
                    arguments, options = run.call_args
                    self.assertEqual(arguments[0], [str(backend), "--no-real-funds"])
                    self.assertEqual(options["input"], request)
                    self.assertNotIn("SECRET_TOKEN", options["env"])
                    self.assertFalse(options["shell"])

    def test_wrong_executable_digest_prevents_execution(self):
        with tempfile.TemporaryDirectory() as directory:
            backend = Path(directory) / "only-a-test-double"
            backend.write_bytes(b"not-executed")
            with patch.object(subprocess, "run") as run:
                with self.assertRaises(ValueError):
                    wallet.invoke(backend, b"", "0" * 64)
                run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
