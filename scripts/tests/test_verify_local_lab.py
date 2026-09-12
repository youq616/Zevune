"""Synthetic bundle bytes only; never execute the named fixture files."""
import copy
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import verify_local_lab as verify
import build_local_lab as build


class BundleVerificationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.commit = "a" * 40
        for name in sorted(verify.required_files(False)):
            (self.root / name).write_bytes(b"synthetic non-executable fixture\n")
        self.manifest = build.manifest_for(self.root, self.commit,
            {"go": "go version go1.27.1 linux/amd64", "rust": "rustc 1.98.1 (synthetic)"}, "b" * 40)
        self.save()

    def save(self, manifest=None):
        if manifest is not None:
            self.manifest = manifest
        self.raw = (json.dumps(self.manifest, indent=2) + "\n").encode()
        (self.root / verify.MANIFEST).write_bytes(self.raw)
        self.pin = hashlib.sha256(self.raw).hexdigest()

    def check(self):
        return verify.verify(self.root, self.pin, self.commit)

    def test_matching_bundle_verifies_without_launch_or_mutation(self):
        before = {p.name: p.read_bytes() for p in self.root.iterdir()}
        with patch("subprocess.run", side_effect=AssertionError("must not launch")):
            result = self.check()
        self.assertTrue(result["integrity_verified"])
        self.assertFalse(result["code_signature_verified"])
        self.assertFalse(result["real_funds_allowed"])
        self.assertEqual(result["files_checked"], 5)
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.root.iterdir()})

    def test_wrong_independent_pin_and_commit_rejected(self):
        for pin in ("0" * 64, "", self.pin.upper(), self.pin + "\n"):
            with self.subTest(pin=pin), self.assertRaises(ValueError):
                verify.verify(self.root, pin, self.commit)
        with self.assertRaisesRegex(ValueError, "source_commit_mismatch"):
            verify.verify(self.root, self.pin, "c" * 40)

    def test_each_modified_payload_is_rejected(self):
        for name in verify.required_files(False):
            file = self.root / name
            original = file.read_bytes()
            file.write_bytes(b"changed" + original[7:])
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.check()
            file.write_bytes(original)

    def test_rewritten_manifest_without_trusted_pin_rejected(self):
        original_pin = self.pin
        self.manifest["files"][0]["sha256"] = "0" * 64
        self.save()
        with self.assertRaisesRegex(ValueError, "manifest_digest_mismatch"):
            verify.verify(self.root, original_pin)

    def test_missing_and_unlisted_files_rejected(self):
        p = self.root / "unexpected.txt"
        p.write_bytes(b"not allowed")
        with self.assertRaises(ValueError): self.check()
        p.unlink()
        p = self.root / "zevune-network"
        p.unlink()
        with self.assertRaises(ValueError): self.check()
        self.assertFalse(p.exists())

    def test_directory_cannot_substitute_for_executable(self):
        p = self.root / "zevune-network"
        p.unlink(); p.mkdir()
        with self.assertRaises(ValueError): self.check()

    def test_duplicate_json_fields_rejected_even_with_matching_pin(self):
        raw = self.raw.replace(b'"format":', b'"format":"ignored", "format":', 1)
        (self.root / verify.MANIFEST).write_bytes(raw)
        with self.assertRaisesRegex(ValueError, "duplicate_manifest_field"):
            verify.verify(self.root, hashlib.sha256(raw).hexdigest())

    def test_unsafe_duplicate_and_unknown_filenames_rejected(self):
        original = copy.deepcopy(self.manifest)
        for name in ("../outside", "/outside", "C:\\outside", "zevune_wallet.py", "unknown.exe"):
            altered = copy.deepcopy(original)
            altered["files"][0]["name"] = name
            self.save(altered)
            with self.subTest(name=name), self.assertRaises(ValueError): self.check()

    def test_strict_false_flags_not_numeric_zero(self):
        original = copy.deepcopy(self.manifest)
        for field in ("real_funds_allowed", "public_network_supported", "network_anonymity_implemented"):
            for value in (0, None, "false", True):
                altered = copy.deepcopy(original); altered[field] = value
                self.save(altered)
                with self.subTest(field=field, value=value), self.assertRaises(ValueError): self.check()

    def test_invalid_sizes_and_hashes_are_rejected(self):
        original = copy.deepcopy(self.manifest)
        for value in (True, -1, 0, 1.5, "20", verify.MAX_FILE_BYTES + 1):
            altered = copy.deepcopy(original); altered["files"][0]["size"] = value
            self.save(altered)
            with self.subTest(value=value), self.assertRaises(ValueError): self.check()
        altered = copy.deepcopy(original); altered["files"][0]["sha256"] = "G" * 64
        self.save(altered)
        with self.assertRaises(ValueError): self.check()

    def test_unknown_and_legacy_manifest_fields_rejected(self):
        altered = copy.deepcopy(self.manifest); altered["extra"] = 1
        self.save(altered)
        with self.assertRaises(ValueError): self.check()
        del altered["extra"]; altered["format"] = "zevune-local-bundle-1"
        self.save(altered)
        with self.assertRaises(ValueError): self.check()

    def test_windows_bundle_supported_but_mixed_platform_refused(self):
        for entry in self.manifest["files"]:
            if entry["name"].startswith("zevune-"):
                original = entry["name"]; entry["name"] += ".exe"
                (self.root / original).rename(self.root / entry["name"])
        self.save()
        self.assertTrue(self.check()["integrity_verified"])
        self.manifest["files"][0]["name"] = "zevune-network"
        self.save()
        with self.assertRaises(ValueError): self.check()

    def test_oversized_manifest_rejected_before_parse(self):
        (self.root / verify.MANIFEST).write_bytes(b" " * (verify.MAX_MANIFEST_BYTES + 1))
        with self.assertRaises(ValueError): self.check()

    def test_windows_reparse_point_is_not_regular_input(self):
        info = types.SimpleNamespace(st_mode=stat.S_IFREG, st_file_attributes=0x400)
        self.assertTrue(verify.linked(info))
        with patch.object(Path, "lstat", return_value=info), self.assertRaises(ValueError):
            verify.fingerprint(self.root / "zevune-network", 100)

    def test_file_size_change_is_rejected(self):
        with patch.object(verify.os.path, "samestat", return_value=False), self.assertRaises(ValueError):
            verify.fingerprint(self.root / "zevune-network", 100)

    def test_cli_failure_is_redacted_and_returns_nonzero(self):
        result = subprocess.run([sys.executable, str(Path(verify.__file__)), "--bundle", str(self.root),
            "--manifest-sha256", "0" * 64], capture_output=True, check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, b"")
        self.assertNotIn(str(self.root).encode(), result.stderr)


if __name__ == "__main__":
    unittest.main()
