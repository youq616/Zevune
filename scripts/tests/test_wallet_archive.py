"""Public-framing and refusal tests only; fake encrypted frames cannot authenticate.

Successful export/import paths execute the genuine backend separately in
check_wallet_archive_backend.py. No accepting backend double is used here.
"""
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import wallet_archive as archive
import wallet_backup as backup
from test_wallet_backup import frames, manifest


def packed(wallet, pin, metadata=None):
    metadata = backup.canonical(manifest(pin, wallet)) if metadata is None else metadata
    return archive.FRAME.pack(archive.MAGIC, len(metadata), len(wallet)) + metadata + wallet


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


class ArchiveFramingTests(unittest.TestCase):
    def setUp(self):
        self.wallet, self.pin = frames(3)
        self.raw = packed(self.wallet, self.pin)

    def check(self, raw=None, pin=None):
        raw = self.raw if raw is None else raw
        return archive.decode(raw, pin or self.pin, digest(raw))

    def test_exact_fixed_endian_header_and_public_wallet_roundtrip(self):
        expected_manifest = backup.canonical(manifest(self.pin, self.wallet))
        header = b"ZVWBPK01" + len(expected_manifest).to_bytes(4, "big") + len(self.wallet).to_bytes(4, "big")
        self.assertEqual(self.raw[:16], header)
        wallet, summary, parsed = self.check()
        self.assertEqual(wallet, self.wallet)
        self.assertEqual(summary, backup.wallet_bytes_summary(self.wallet, self.pin))
        self.assertEqual(parsed, manifest(self.pin, self.wallet))

    def test_each_supported_generation_has_identical_byte_contract(self):
        for count in (1, 2, 255, 256):
            wallet, pin = frames(count)
            raw = packed(wallet, pin)
            self.assertLessEqual(len(raw), archive.MAX_ARCHIVE)
            self.assertEqual(archive.decode(raw, pin, digest(raw))[0], wallet)
        wallet, pin = frames(257)
        with self.assertRaises(ValueError):
            archive.decode(packed(wallet, pin), pin, digest(packed(wallet, pin)))

    def test_independent_digest_is_required_and_not_read_from_manifest(self):
        for value in (None, True, "", "A" * 64, "0" * 64, digest(self.raw) + "\n", [], {}):
            with self.subTest(value=type(value).__name__), self.assertRaises(ValueError):
                archive.decode(self.raw, self.pin, value)
        for pin in (frames(2)[1], frames(3, b"q")[1], self.pin.upper(), self.pin + "\n"):
            with self.assertRaises(ValueError):
                self.check(pin=pin)

    def test_truncated_extended_or_concatenated_archive_refused(self):
        for cut in (0, 7, 8, 15, 16, 17, 30, len(self.raw) - 1):
            with self.subTest(cut=cut), self.assertRaises(ValueError):
                self.check(self.raw[:cut])
        for raw in (self.raw + b"x", self.raw + self.raw):
            with self.assertRaises(ValueError):
                self.check(raw)

    def test_header_fields_cannot_request_unbounded_or_wrong_layout(self):
        magic, m, w = archive.FRAME.unpack_from(self.raw)
        values = ((b"ZVWBPK02", m, w), (magic, 0, w), (magic, m + 1, w),
                  (magic, m, w - 1), (magic, 2**32 - 1, w),
                  (magic, m, 2**32 - 1), (magic, 4097, w))
        for args in values:
            raw = archive.FRAME.pack(*args) + self.raw[16:]
            with self.subTest(args=args), self.assertRaises(ValueError):
                self.check(raw)
        raw = struct.pack("<8sII", magic, m, w) + self.raw[16:]
        with self.assertRaises(ValueError):
            self.check(raw)

    def test_canonical_manifest_is_exact_and_never_contains_paths(self):
        normal = manifest(self.pin, self.wallet)
        for changed in ({**normal, "path": "../../outside"}, {**normal, "requires_rescan": False},
                        {**normal, "real_funds_allowed": 0}, {**normal, "wallet_bytes": True},
                        {**normal, "receipt": frames(2)[1]}, {**normal, "format": "unknown"}):
            with self.assertRaises(ValueError):
                self.check(packed(self.wallet, self.pin, backup.canonical(changed)))
        encoded = backup.canonical(normal)
        for raw in (encoded[:-1], b" " + encoded, encoded + b"\n", b"[]\n", b"\xff",
                    encoded.replace(b'"format":', b'"format":"duplicate","format":', 1),
                    json.dumps(normal, indent=2).encode()):
            with self.assertRaises(ValueError):
                self.check(packed(self.wallet, self.pin, raw))

    def test_each_public_chain_component_rejected_after_archive_rehash(self):
        for index in (0, 8, backup.HEADER, backup.HEADER + 8,
                      backup.HEADER + 80, len(self.wallet) - 1):
            modified = bytearray(self.wallet)
            modified[index] ^= 1
            with self.subTest(index=index), self.assertRaises(ValueError):
                self.check(packed(bytes(modified), self.pin))
        for raw in (bytearray(self.raw), None, b"x" * (archive.MAX_ARCHIVE + 1)):
            with self.assertRaises(ValueError):
                archive.decode(raw, self.pin, digest(self.raw))


class ArchiveFileTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="archive-refusals-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.home = self.root / "catalog"
        backup.init(self.home)
        self.wallet, self.pin = frames(3)
        self.raw = packed(self.wallet, self.pin)
        self.source = self.root / "backup.zvbackup"
        self.source.write_bytes(self.raw)
        self.sha = digest(self.raw)

    def test_inspect_never_authenticates_executes_or_changes_files(self):
        before = self.source.read_bytes()
        with patch.object(archive, "Backend", side_effect=AssertionError("must not run backend")), \
                patch.object(archive, "hidden_password", side_effect=AssertionError("must not request password")):
            result = archive.inspect_archive(self.source, self.pin, self.sha)
        self.assertFalse(result["authenticated"])
        self.assertFalse(result["real_funds_allowed"])
        self.assertTrue(result["latest_not_inferred"])
        self.assertEqual(result["receipt"], self.pin)
        self.assertEqual(self.source.read_bytes(), before)
        self.assertEqual(backup.list_versions(self.home)["versions"], [])

    def test_export_authentication_failure_creates_nothing(self):
        folder = self.home / backup.version_id(self.pin)
        folder.mkdir(mode=0o700)
        (folder / "wallet.journal").write_bytes(self.wallet)
        (folder / "MANIFEST.json").write_bytes(backup.canonical(manifest(self.pin, self.wallet)))
        target = self.root / "export.zvbackup"
        with patch.object(backup, "authenticate", side_effect=RuntimeError("authentication required")):
            with self.assertRaises(RuntimeError):
                archive.export_archive(self.home, target, self.pin, b"unused-parser-fixture", None)
        self.assertFalse(target.exists())
        self.assertEqual((folder / "wallet.journal").read_bytes(), self.wallet)

    def test_unapproved_backend_rejected_before_import_creates_output(self):
        binary = self.root / "not-executable"
        binary.write_bytes(b"synthetic bytes never executed")
        backend = archive.Backend(binary, "0" * 64)
        with self.assertRaises(RuntimeError):
            archive.import_archive(self.home, self.source, self.pin, self.sha, b"unused-parser-fixture", backend)
        self.assertEqual(backup.list_versions(self.home)["versions"], [])
        self.assertEqual(self.source.read_bytes(), self.raw)

    def test_changed_file_identity_rejected_even_with_equal_content(self):
        _, marker = backup.read_file(self.source, archive.MAX_ARCHIVE)
        replacement = self.root / "other"
        replacement.write_bytes(self.raw)
        os.replace(replacement, self.source)
        with self.assertRaises(ValueError):
            archive.unchanged_archive(self.source, marker, self.sha)

    def test_symlink_hardlink_directory_and_extra_bytes_fail(self):
        link = self.root / "link"
        if os.name == "posix":
            link.symlink_to(self.source)
            with self.assertRaises((ValueError, OSError)):
                archive.inspect_archive(link, self.pin, self.sha)
            link.unlink()
        os.link(self.source, link)
        with self.assertRaises((ValueError, OSError)):
            archive.inspect_archive(self.source, self.pin, self.sha)
        link.unlink()
        with self.assertRaises((ValueError, OSError)):
            archive.inspect_archive(self.home, self.pin, self.sha)
        self.source.write_bytes(self.raw + b"extra")
        with self.assertRaises(ValueError):
            archive.inspect_archive(self.source, self.pin, digest(self.source.read_bytes()))

    def test_cli_inspect_is_machine_readable_and_errors_do_not_echo_input(self):
        out, err = io.StringIO(), io.StringIO()
        args = ["--no-real-funds", "inspect", str(self.source), "--pin", self.pin,
                "--archive-sha256", self.sha]
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            self.assertEqual(archive.main(args), 0)
        self.assertFalse(json.loads(out.getvalue())["authenticated"])
        self.assertEqual(err.getvalue(), "")
        self.source.write_bytes(b"PRIVATE_SENTINEL")
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            self.assertEqual(archive.main(args), 1)
        self.assertNotIn("PRIVATE_SENTINEL", out.getvalue() + err.getvalue())
        self.assertNotIn(str(self.source), err.getvalue())

    def inert_backend(self):
        # Hash verification alone is not executable/AEAD success. Every test
        # below is required to refuse before this inert file is ever launched.
        path = self.root / "inert"
        path.write_bytes(b"inert transport refusal fixture")
        return archive.Backend(path, digest(path.read_bytes()))

    def test_import_write_failure_retains_partial_entry_and_releases_lock(self):
        backend = self.inert_backend()
        def fail_write(path, data):
            with path.open("xb") as stream:
                stream.write(data[:100])
            raise OSError("write failure fixture")
        with patch.object(backup, "write_new", side_effect=fail_write), \
                patch("subprocess.Popen", side_effect=AssertionError("must fail before authentication")):
            with self.assertRaises(OSError):
                archive.import_archive(self.home, self.source, self.pin, self.sha,
                                       b"unused-synthetic-password", backend)
        entry = self.home / backup.version_id(self.pin)
        self.assertEqual({p.name for p in entry.iterdir()}, {"wallet.journal"})
        self.assertEqual((entry / "wallet.journal").read_bytes(), self.wallet[:100])
        self.assertFalse(backup.list_versions(self.home)["versions"][0]["metadata_complete"])
        self.assertEqual(self.source.read_bytes(), self.raw)

    def test_duplicate_capacity_and_lock_refuse_before_writing_or_authenticating(self):
        backend = self.inert_backend()
        with backup.Catalog(self.home), patch("subprocess.Popen", side_effect=AssertionError("no backend")):
            with self.assertRaises((ValueError, OSError)):
                archive.import_archive(self.home, self.source, self.pin, self.sha, b"unused-synthetic-password", backend)
        duplicate = self.home / backup.version_id(self.pin)
        duplicate.mkdir()
        with self.assertRaisesRegex(ValueError, "destination_already_exists"):
            archive.import_archive(self.home, self.source, self.pin, self.sha, b"unused-synthetic-password", backend)
        duplicate.rmdir()
        for index in range(backup.MAX_ENTRIES):
            (self.home / f"{index:064x}").mkdir()
        with self.assertRaisesRegex(ValueError, "catalog_full"):
            archive.import_archive(self.home, self.source, self.pin, self.sha, b"unused-synthetic-password", backend)
        self.assertFalse(duplicate.exists())
        self.assertEqual(self.source.read_bytes(), self.raw)

    def test_cli_declined_import_never_requests_password_or_creates_entry(self):
        backend = self.inert_backend()
        args = ["--no-real-funds", "import", str(self.home), str(self.source),
                "--pin", self.pin, "--archive-sha256", self.sha,
                "--backend", str(backend.path), "--backend-sha256", backend.digest]
        with patch("builtins.input", return_value="NO"), \
                patch.object(archive, "hidden_password", side_effect=AssertionError("no password after refusal")), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(archive.main(args), 1)
        self.assertEqual(backup.list_versions(self.home)["versions"], [])

    def test_cli_requires_no_funds_and_no_password_in_argument_interface(self):
        script = Path(archive.__file__).resolve()
        process = subprocess.run([sys.executable, str(script), "inspect", str(self.source),
                                  "--pin", self.pin, "--archive-sha256", self.sha],
                                 capture_output=True, timeout=10)
        self.assertNotEqual(process.returncode, 0)
        help_run = subprocess.run([sys.executable, str(script), "--no-real-funds", "import", "--help"],
                                  capture_output=True, timeout=10)
        self.assertEqual(help_run.returncode, 0)
        self.assertNotIn(b"--password", help_run.stdout)


if __name__ == "__main__":
    unittest.main()
