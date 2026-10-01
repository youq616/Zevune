"""Frontend boundary tests only; native tests use the real Orchard wallet.

Mocks below intercept the UI invocation, never implement a cryptographic backend.
"""
import contextlib
import copy
import importlib.util
import io
import json
from pathlib import Path
import struct
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location("checkpoint_console", Path(__file__).resolve().parents[1] / "zevune_wallet.py")
wallet = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(wallet)
PIN = "11" * 32 + "0000000000000001" + "22" * 32
HASH = "33" * 32
GENESIS = "44" * 32
PASSWORD = b"synthetic-test-only-password"


def reply():
    return {"ok": True, "scope": "local_journal_only_no_funds",
            "result": "checkpoint_matched_wallet_scanned", "checkpoint_matched": True,
            "payment_profile": "LAB2", "signing_domain": GENESIS,
            "genesis_sha256": GENESIS, "height": 0, "app_hash": HASH,
            "balance": 100000, "available": 100000, "pending": False, "receipt": PIN}


class CheckpointWalletTests(unittest.TestCase):
    def fields(self):
        return [str(Path(name).absolute()) for name in ("wallet", "journal", "genesis")] + [GENESIS, "0", HASH]

    def args(self):
        f = self.fields()
        return ["--no-real-funds", "--backend-sha256", "55" * 32, "--pin", PIN,
                "status-at-checkpoint", f[0], "--journal", f[1], "--genesis", f[2],
                "--genesis-sha256", GENESIS, "--expected-height", "0", "--expected-app-hash", HASH]

    def test_exact_frame_and_original_operation_numbers(self):
        fields = self.fields()
        expected = (b"ZVWCLI01\x0b" + struct.pack(">H", len(PASSWORD)) + PASSWORD
                    + b"\x01" + bytes.fromhex(PIN) + b"\x06")
        for f in fields:
            raw = f.encode()
            expected += struct.pack(">H", len(raw)) + raw
        self.assertEqual(wallet.encode_request(11, PASSWORD, fields, PIN), expected)
        original = {"create": 0, "address": 1, "backup": 2, "status": 3,
                    "prepare": 4, "pending": 5, "restore": 6, "init-test-ledger": 7,
                    "network-address": 8, "storage": 9, "compact": 10}
        self.assertEqual({k: wallet.OPS[k] for k in original}, original)
        for op, count in {0: 1, 1: 2, 2: 2, 3: 4, 4: 9, 5: 5, 6: 2, 7: 3, 8: 5, 9: 1, 10: 2}.items():
            p = None if op == 0 else PIN
            frame = b"ZVWCLI01" + bytes([op]) + struct.pack(">H", len(PASSWORD)) + PASSWORD
            frame += b"\x00" if p is None else b"\x01" + bytes.fromhex(p)
            frame += bytes([count]) + b"\x00\x01x" * count
            self.assertEqual(wallet.encode_request(op, PASSWORD, ["x"] * count, p), frame)

    def test_missing_pin_fields_and_invalid_public_values(self):
        for pin in (None, "", "0" * 144, "A" * 144, PIN[:-1], PIN[:64] + "0000000000000101" + PIN[80:]):
            with self.subTest(pin_shape=len(pin or "")), self.assertRaises(ValueError):
                wallet.encode_request(11, PASSWORD, self.fields(), pin)
        for height in ("", "01", "-1", "+1", " 1", "1e0", "18446744073709551616", "9" * 100):
            f = self.fields(); f[4] = height
            with self.subTest(height=height), self.assertRaises(ValueError):
                wallet.encode_request(11, PASSWORD, f, PIN)
        for value in ("", "0" * 64, HASH.upper().replace("3", "A"), HASH[:-1], HASH + "\n"):
            f = self.fields(); f[5] = value
            with self.assertRaises(ValueError):
                wallet.encode_request(11, PASSWORD, f, PIN)
        for fields in (self.fields()[:-1], self.fields() + ["extra"]):
            with self.assertRaises(ValueError):
                wallet.encode_request(11, PASSWORD, fields, PIN)

    def test_reply_requires_exact_checkpoint_and_never_claims_finality(self):
        r = reply()
        self.assertEqual(wallet.checked_checkpoint_status(r, "0", HASH), r)
        mutations = {"ok": False, "scope": "network_finality", "result": "confirmed",
                     "checkpoint_matched": 1, "height": True, "app_hash": "66" * 32,
                     "balance": True, "available": 100001, "pending": 0, "receipt": "bad",
                     "payment_profile": [], "signing_domain": "77" * 32,
                     "genesis_sha256": "0" * 64}
        for k, v in mutations.items():
            altered = copy.deepcopy(r); altered[k] = v
            with self.subTest(field=k), self.assertRaises((ValueError, RuntimeError)):
                wallet.checked_checkpoint_status(altered, "0", HASH)
        for k in r:
            altered = copy.deepcopy(r); del altered[k]
            with self.assertRaises(RuntimeError):
                wallet.checked_checkpoint_status(altered, "0", HASH)
        r["confirmed"] = True
        with self.assertRaises(RuntimeError):
            wallet.checked_checkpoint_status(r, "0", HASH)

    def test_main_checks_pins_before_password_files_and_child(self):
        for flag, value in (("--pin", "bad"), ("--expected-height", "01"),
                            ("--expected-app-hash", ""), ("--backend-sha256", "")):
            args = self.args(); args[args.index(flag) + 1] = value
            with patch.object(wallet, "hidden_password") as secret, patch.object(wallet, "genesis_identity") as identity, patch.object(wallet, "invoke") as child, contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(wallet.main(args), 1)
                secret.assert_not_called(); identity.assert_not_called(); child.assert_not_called()

    def test_main_routes_new_operation_and_validates_response(self):
        r = reply()
        for bad in (False, True):
            response = copy.deepcopy(r)
            if bad:
                response["app_hash"] = "99" * 32
            output = io.StringIO()
            identity = {k: r[k] for k in ("payment_profile", "signing_domain", "genesis_sha256")}
            with patch.object(wallet, "hidden_password", return_value=PASSWORD), patch.object(wallet, "genesis_identity", return_value=identity), patch.object(wallet, "invoke", return_value=response) as child, contextlib.redirect_stdout(output), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(wallet.main(self.args()), int(bad))
            self.assertEqual(child.call_args.args[1], wallet.encode_request(11, PASSWORD, self.fields(), PIN))
            if bad:
                self.assertEqual(output.getvalue(), "")
            else:
                self.assertEqual(json.loads(output.getvalue()), r)
                self.assertNotIn(PASSWORD.decode(), output.getvalue())

    def test_failures_do_not_retry_or_fallback_to_unchecked_status(self):
        identity = {k: reply()[k] for k in ("payment_profile", "signing_domain", "genesis_sha256")}
        with patch.object(wallet, "hidden_password", return_value=PASSWORD), patch.object(wallet, "genesis_identity", return_value=identity), patch.object(wallet, "invoke", side_effect=RuntimeError("test only")) as child, contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(wallet.main(self.args()), 1)
        self.assertEqual(child.call_count, 1)
        self.assertEqual(child.call_args.args[1][8], 11)


if __name__ == "__main__":
    unittest.main()
