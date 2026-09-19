import hashlib
import importlib.util
from pathlib import Path
import tempfile
import subprocess
import unittest
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

spec = importlib.util.spec_from_file_location("build_local_lab", Path(__file__).resolve().parents[1] / "build_local_lab.py")
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)


class BundleManifestTests(unittest.TestCase):
    def test_manifest_hashes_only_explicit_regular_files(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "public.txt").write_bytes(b"public test data")
            output = build.manifest_for(root, "a" * 40, {"go": "test", "rust": "test"})
            self.assertFalse(output["real_funds_allowed"])
            self.assertFalse(output["network_anonymity_implemented"])
            self.assertEqual(output["files"], [{"name": "public.txt", "size": 16,
                "sha256": hashlib.sha256(b"public test data").hexdigest()}])

    def test_directory_is_not_packaged(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "private-state").mkdir()
            with self.assertRaises(ValueError):
                build.manifest_for(root, "a" * 40, {})

    def test_build_source_manifest_keeps_full_origin_tree_identity(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "repository"
            root.mkdir()
            def git(*args):
                return subprocess.check_output(["git", *args], cwd=root).decode().strip()
            git("init", "-q")
            git("config", "user.name", "Synthetic test")
            git("config", "user.email", "test@example.invalid")
            (root / "reports").mkdir()
            (root / "reports/evidence.txt").write_bytes(b"retained source evidence")
            (root / "public.txt").write_bytes(b"synthetic bundle fixture; never executed")
            git("add", ".")
            git("commit", "-qm", "Synthetic provenance")
            commit = git("rev-parse", "HEAD")
            tree = git("rev-parse", "HEAD^{tree}")
            staged = Path(temp) / "source"
            captured_tree = build.export_build_source(root, commit, staged)
            output = build.manifest_for(staged, commit, {"go": "test", "rust": "test"}, captured_tree)
            self.assertEqual(output["source_commit"], commit)
            self.assertEqual(output["source_tree"], tree)
            self.assertEqual(output["format"], "zevune-local-bundle-2")
            self.assertEqual(output["build_source"], "isolated_exact_git_blobs")
            self.assertFalse((staged / "reports").exists())
            self.assertTrue((root / "reports/evidence.txt").is_file())
            self.assertEqual([item["name"] for item in output["files"]], ["public.txt"])

    def test_signer_material_is_ignored_without_creating_secret_files(self):
        root = Path(__file__).resolve().parents[2]
        paths = ["local-data/config/priv_validator_key.json",
                 "local-data/data/priv_validator_state.json",
                 "local-data/config/node_key.json", "local-data/payment.tx"]
        # Binary NUL framing avoids Windows text-mode CRLF changing filenames.
        payload = ("\0".join(paths) + "\0").encode("utf-8")
        result = subprocess.run(["git", "check-ignore", "--no-index", "--stdin", "-z"],
                                input=payload, cwd=root, capture_output=True, check=False)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, payload)
