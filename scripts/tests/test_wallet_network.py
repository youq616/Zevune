"""Synthetic public frames only; genuine Orchard checks run in backend tests."""
import hashlib
import importlib.util
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

MODULE = Path(__file__).resolve().parents[1] / "zevune_wallet.py"
spec = importlib.util.spec_from_file_location("wallet_network_console", MODULE)
wallet = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wallet)


def address(domain=None):
    raw = bytes(range(43))  # shape fixture, NOT a valid spendable note
    if domain is None:
        digest = hashlib.sha256(b"ZEVUNE-LOCAL-ADDRESS\0\x01" + raw).hexdigest()[:8]
        return "zvlab:" + raw.hex() + ":" + digest
    digest = hashlib.sha256(b"ZEVUNE-LOCAL-ADDRESS\0\x02" + bytes.fromhex(domain) + raw).hexdigest()[:16]
    return "zvlab2:" + domain + ":" + raw.hex() + ":" + digest


def manifest(bound=True):
    magic = b"ZVTGEN02" if bound else b"ZVTGEN01"
    header = magic + hashlib.sha256(b"zevune-orchard-lab-1").digest()
    header += (100_000).to_bytes(8, "big") + (1).to_bytes(2, "big")
    if bound:
        header += bytes([1]) * 32
    return header + bytes(43) + (100_000).to_bytes(8, "big") + bytes(64)


class NetworkIdentityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.file = self.root / "genesis.bin"
        self.raw = manifest()
        self.file.write_bytes(self.raw)
        self.pin = hashlib.sha256(self.raw).hexdigest()

    def test_bound_checksum_and_expected_identity(self):
        text = address(self.pin)
        self.assertEqual(len(text), 175)
        self.assertEqual(wallet.checked_address(text), text)
        self.assertEqual(wallet.checked_recipient(text, self.pin), text)
        for expected in (None, "02" * 32):
            with self.assertRaises(ValueError):
                wallet.checked_recipient(text, expected)
        with self.assertRaises(ValueError):
            wallet.checked_recipient(address(), self.pin)
        self.assertEqual(wallet.checked_recipient(address(), None), address())

    def test_addresses_reject_mutation_and_noncanonical_text(self):
        text = address(self.pin)
        for index in range(len(text)):
            altered = text[:index] + ("0" if text[index] != "0" else "1") + text[index + 1:]
            with self.subTest(index=index), self.assertRaises(ValueError):
                wallet.checked_address(altered)
        for value in [None, 1, {}, text.upper(), text + ":x", text + "\n", " " + text, address("00" * 32)]:
            with self.subTest(value_type=type(value)), self.assertRaises(ValueError):
                wallet.checked_address(value)

    def test_pinned_genesis_is_read_only_and_profile_is_explicit(self):
        self.assertEqual(wallet.genesis_identity(self.file, self.pin), {
            "payment_profile": "LAB2", "signing_domain": self.pin, "genesis_sha256": self.pin})
        self.assertEqual(self.file.read_bytes(), self.raw)
        raw = manifest(False)
        self.file.write_bytes(raw)
        pin = hashlib.sha256(raw).hexdigest()
        self.assertEqual(wallet.genesis_identity(self.file, pin), {
            "payment_profile": "LAB1", "signing_domain": None, "genesis_sha256": pin})

    def test_untrusted_pin_missing_and_nonregular_files_fail(self):
        for pin in ["00" * 32, "01" * 32, self.pin.upper(), self.pin + "\n"]:
            with self.assertRaises(ValueError):
                wallet.genesis_identity(self.file, pin)
        with self.assertRaises(OSError):
            wallet.genesis_identity(self.root / "missing", self.pin)
        with self.assertRaises(ValueError):
            wallet.genesis_identity(self.root, self.pin)

    def test_truncated_unknown_overlarge_and_wrong_network_frames_fail(self):
        samples = [self.raw[:end] for end in range(len(self.raw))]
        samples += [self.raw + b"x", bytes(1923), b"ZVTGEN03" + self.raw[8:],
                    self.raw[:8] + bytes(32) + self.raw[40:],
                    self.raw[:50] + bytes(32) + self.raw[82:]]
        for raw in samples:
            self.file.write_bytes(raw)
            with self.assertRaises(ValueError):
                wallet.genesis_identity(self.file, hashlib.sha256(raw).hexdigest())

    def test_public_supply_precheck_rejects_bad_allocation_not_just_pin(self):
        for value in [0, 99_999, 100_001, (1 << 64) - 1]:
            raw = bytearray(self.raw)
            raw[125:133] = value.to_bytes(8, "big")
            self.file.write_bytes(raw)
            with self.assertRaises(ValueError):
                wallet.genesis_identity(self.file, hashlib.sha256(raw).hexdigest())

    def test_network_address_wire_operation_has_exact_field_count(self):
        password = b"synthetic-console-password"
        fields = ["/wallet", "/journal", "/genesis", self.pin, "0"]
        raw = wallet.encode_request(8, password, fields)
        self.assertEqual(raw[:9], b"ZVWCLI01\x08")
        for broken in [fields[:-1], fields + ["extra"]]:
            with self.assertRaises(ValueError):
                wallet.encode_request(8, password, broken)

    def args(self, command):
        args = ["--no-real-funds", command, str(self.root / "wallet")]
        if command == "prepare":
            args.append(str(self.root / "payment"))
        return args + ["--journal", str(self.root / "journal"), "--genesis", str(self.file),
                       "--genesis-sha256", self.pin]

    def test_wrong_network_frontend_stops_before_password_and_backend(self):
        for recipient in [address(), address("02" * 32)]:
            with patch("builtins.input", return_value=recipient), \
                 patch.object(wallet, "hidden_password") as password, \
                 patch.object(wallet, "invoke") as backend, \
                 patch.object(sys, "stderr", io.StringIO()):
                self.assertEqual(wallet.main(self.args("prepare")), 1)
                password.assert_not_called()
                backend.assert_not_called()
        self.assertEqual({p.name for p in self.root.iterdir()}, {"genesis.bin"})

    def test_network_address_frontend_checks_backend_identity(self):
        response = {"ok": True, "scope": "local_journal_only_no_funds", "address": address(self.pin),
                    "payment_profile": "LAB2", "signing_domain": self.pin, "genesis_sha256": self.pin}
        with patch.object(wallet, "hidden_password", return_value=b"synthetic-test-password"), \
             patch.object(wallet, "invoke", return_value=response) as backend, \
             patch.object(sys, "stderr", io.StringIO()), patch.object(sys, "stdout", io.StringIO()):
            self.assertEqual(wallet.main(self.args("network-address")), 0)
            self.assertEqual(backend.call_args[0][1][:9], b"ZVWCLI01\x08")
            response["signing_domain"] = "02" * 32
            self.assertEqual(wallet.main(self.args("network-address")), 1)
            del response["signing_domain"]
            self.assertEqual(wallet.main(self.args("network-address")), 1)


if __name__ == "__main__":
    unittest.main()
