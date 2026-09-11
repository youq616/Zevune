"""Synthetic archives only; no real wallets or external network access."""
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("crate_notices", Path(__file__).resolve().parents[1] / "audit_crate_notices.py")
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


def archive(entries=None):
    default = [("demo-1.0.0/Cargo.toml", b'[package]\nname="demo"\nversion="1.0.0"\nlicense="MIT"\n'), ("demo-1.0.0/LICENSE-MIT", b"Synthetic notice for tests only.\n"), ("demo-1.0.0/src/lib.rs", b"not a notice")]
    result = io.BytesIO()
    with tarfile.open(fileobj=result, mode="w:gz") as stream:
        for name, value in (default if entries is None else entries):
            member = tarfile.TarInfo(name)
            if value is None:
                member.type = tarfile.SYMTYPE
                member.linkname = "../../outside"
                stream.addfile(member)
            else:
                member.size = len(value)
                stream.addfile(member, io.BytesIO(value))
    raw = result.getvalue()
    return raw, {"name": "demo", "version": "1.0.0", "source": "registry+https://example.invalid/index", "checksum": hashlib.sha256(raw).hexdigest()}


class CrateNoticeTests(unittest.TestCase):
    def test_pinned_archive_collects_notices_not_source(self):
        raw, package = archive()
        declared, documents = audit.archive_notices(raw, package)
        self.assertEqual(declared, "MIT")
        self.assertEqual(set(documents), {"LICENSE-MIT"})

    def test_wrong_archive_checksum_fails_before_parsing(self):
        raw, package = archive()
        package["checksum"] = "0" * 64
        with self.assertRaisesRegex(audit.AuditError, "archive_checksum_mismatch"):
            audit.archive_notices(raw, package)

    def test_traversal_foreign_root_and_symlink_rejected(self):
        for entries in [[("demo-1.0.0/../LICENSE", b"x")], [("other-1.0.0/LICENSE", b"x")], [("demo-1.0.0/LICENSE", None)]]:
            with self.subTest(entries=entries):
                raw, package = archive(entries)
                with self.assertRaises(audit.AuditError):
                    audit.archive_notices(raw, package)

    def test_duplicate_archive_path_rejected(self):
        raw, package = archive([("demo-1.0.0/LICENSE", b"a"), ("demo-1.0.0/LICENSE", b"b")])
        with self.assertRaisesRegex(audit.AuditError, "duplicate_archive_member"):
            audit.archive_notices(raw, package)

    def test_member_and_expanded_byte_limits(self):
        raw, package = archive()
        with patch.object(audit, "MAX_MEMBERS", 1), self.assertRaises(audit.AuditError):
            audit.archive_notices(raw, package)
        with patch.object(audit, "MAX_TAR_BYTES", 128), self.assertRaises(audit.AuditError):
            audit.archive_notices(raw, package)

    def test_missing_notices_is_not_distribution_approval(self):
        raw, package = archive([("demo-1.0.0/Cargo.toml", b'[package]\nname="demo"\nversion="1.0.0"\nlicense="MIT"\n')])
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            (root / "demo-1.0.0.crate").write_bytes(raw)
            lock = root / "Cargo.lock"
            lock.write_text('version=4\n[[package]]\n' + '\n'.join(f'{key}={json.dumps(value)}' for key, value in package.items()), encoding="utf-8")
            report, documents = audit.inventory(lock, [root])
            self.assertFalse(report["complete"])
            self.assertFalse(report["distribution_approved"])
            self.assertEqual(documents, {})
            self.assertEqual(report["packages"][0]["status"], "missing_license_notice_documents")

    def test_inventory_is_create_only(self):
        raw, package = archive()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            (root / "demo-1.0.0.crate").write_bytes(raw)
            lock = root / "Cargo.lock"
            lock.write_text('version=4\n[[package]]\n' + '\n'.join(f'{key}={json.dumps(value)}' for key, value in package.items()), encoding="utf-8")
            report, documents = audit.inventory(lock, [root])
            self.assertTrue(report["complete"])
            self.assertFalse(report["license_compatibility_reviewed"])
            output = root / "inventory"
            audit.write_inventory(output, report, documents)
            saved = (output / "NOTICE-INVENTORY.json").read_bytes()
            with self.assertRaises(FileExistsError):
                audit.write_inventory(output, report, documents)
            self.assertEqual((output / "NOTICE-INVENTORY.json").read_bytes(), saved)

    def test_lock_rejects_path_identities_and_duplicates(self):
        for name in ("../demo", "a/b", "a\\b", "/demo"):
            lock = f'[[package]]\nname={json.dumps(name)}\nversion="1"\nsource="registry+test"\nchecksum="' + '0'*64 + '"\n'
            with self.assertRaises(audit.AuditError):
                audit.locked_packages(lock.encode())
        _, package = archive()
        entry = '[[package]]\n' + '\n'.join(f'{key}={json.dumps(value)}' for key, value in package.items()) + '\n'
        with self.assertRaisesRegex(audit.AuditError, "duplicate_package_identity"):
            audit.locked_packages((entry + entry).encode())

    def test_registry_checksum_required_and_workspace_separate(self):
        with self.assertRaisesRegex(audit.AuditError, "missing_registry_checksum"):
            audit.locked_packages(b'[[package]]\nname="demo"\nversion="1"\nsource="registry+test"\n')
        self.assertEqual(audit.locked_packages(b'[[package]]\nname="local"\nversion="1"\n'), [])


if __name__ == "__main__":
    unittest.main()
