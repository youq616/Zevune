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
