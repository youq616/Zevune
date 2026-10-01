import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import check_cometbft_origin as origin

class CometBFTOwnerOriginTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="zevune-origin-test-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        source = Path(__file__).resolve().parents[2]
        for relative in (origin.VENDOR, origin.PROVENANCE):
            target = self.root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(source / relative, target)
        self.vendor = self.root / origin.VENDOR
        self.provenance = self.root / origin.PROVENANCE

    def test_exact_origin_and_reversible_patch(self):
        got = origin.verify_files(self.root)
        self.assertEqual(got["runtime_patch_files"], 1)
        self.assertEqual(got["retained_origin_files"], 1019)

    def test_untouched_runtime_mutation_rejected(self):
        p = self.vendor / "store/store.go"
        p.write_bytes(p.read_bytes() + b"\n")
        with self.assertRaisesRegex(origin.OriginError, "digest_mismatch"):
            origin.verify_files(self.root)

    def test_host_crlf_settings_preserve_exact_origin_and_reject_mutation(self):
        # Command-scoped settings simulate a Windows host without modifying
        # shared Git configuration. Verification still compares original bytes.
        with patch.dict(os.environ, {
                "GIT_CONFIG_COUNT": "2", "GIT_CONFIG_KEY_0": "core.autocrlf",
                "GIT_CONFIG_VALUE_0": "true", "GIT_CONFIG_KEY_1": "core.eol",
                "GIT_CONFIG_VALUE_1": "crlf"}):
            got = origin.verify_files(self.root)
            self.assertEqual(got["retained_origin_files"], 1019)
            runtime = self.vendor / origin.RUNTIME_PATCH
            runtime.write_bytes(runtime.read_bytes().replace(b"\n", b"\r\n"))
            with self.assertRaisesRegex(origin.OriginError, "digest_mismatch"):
                origin.verify_files(self.root)

    def test_license_and_module_metadata_are_immutable(self):
        for name in ("LICENSE", "NOTICE", "go.mod", "go.sum"):
            with self.subTest(name=name):
                p = self.vendor / name
                saved = p.read_bytes()
                p.write_bytes(saved + b"\n")
                with self.assertRaises(origin.OriginError):
                    origin.verify_files(self.root)
                p.write_bytes(saved)

    def test_missing_and_extra_source_rejected(self):
        p = self.vendor / "LICENSE"
        saved = p.read_bytes()
        p.unlink()
        with self.assertRaisesRegex(origin.OriginError, "missing_dependency_source"):
            origin.verify_files(self.root)
        p.write_bytes(saved)
        (self.vendor / "extra.go").write_text("package extra\n")
        with self.assertRaisesRegex(origin.OriginError, "extra_dependency_source"):
            origin.verify_files(self.root)

    def test_origin_manifest_cannot_refresh_its_own_pin(self):
        p = self.provenance / "complete-upstream-manifest.json"
        data = json.loads(p.read_text())
        data[0]["size"] += 1
        p.write_text(json.dumps(data))
        with self.assertRaisesRegex(origin.OriginError, "origin_manifest_digest_mismatch"):
            origin.verify_files(self.root)

    def test_stale_patch_rejected(self):
        p = self.provenance / "lifetime.patch"
        p.write_bytes(p.read_bytes() + b"\n")
        with self.assertRaisesRegex(origin.OriginError, "patch_digest_mismatch"):
            origin.verify_files(self.root)

    def test_unlisted_patch_file_rejected_even_with_recomputed_patch_digest(self):
        p = self.provenance / "lifetime.patch"
        data = p.read_bytes() + b"--- a/extra.txt\n+++ /dev/null\n@@ -1 +0,0 @@\n+x\n"
        p.write_bytes(data)
        m = self.provenance / "patch.json"
        meta = json.loads(m.read_text())
        meta["patch_sha256"] = hashlib.sha256(data).hexdigest()
        m.write_text(json.dumps(meta))
        with self.assertRaises(origin.OriginError):
            origin.verify_files(self.root)

    def test_symlink_source_rejected(self):
        p = self.vendor / "NOTICE"
        p.unlink()
        try:
            p.symlink_to("LICENSE")
        except OSError:
            self.skipTest("native symlink creation unavailable")
        with self.assertRaises(origin.OriginError):
            origin.verify_files(self.root)

    def test_symlink_ancestor_rejected(self):
        p = self.root / "integration/cometbft/third_party"
        saved = self.root / "outside"
        p.rename(saved)
        try:
            p.symlink_to(saved, target_is_directory=True)
        except OSError:
            self.skipTest("native directory symlink creation unavailable")
        with self.assertRaises(origin.OriginError):
            origin.verify_files(self.root)

    def test_additional_runtime_patch_not_authorized(self):
        p = self.provenance / "patch.json"
        data = json.loads(p.read_text())
        data["runtime"]["store/store.go"] = "0" * 64
        p.write_text(json.dumps(data))
        with self.assertRaisesRegex(origin.OriginError, "unapproved_patch_scope"):
            origin.verify_files(self.root)

if __name__ == "__main__":
    unittest.main()
