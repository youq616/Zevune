import hashlib
import importlib.util
import os
from pathlib import Path
import tempfile
import subprocess
import unittest
import sys
from unittest.mock import patch

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
            git("config", "core.autocrlf", "false")
            source = {
                ".gitignore": b"ignored.go\n",
                "integration/cometbft/go.mod": b"synthetic locked Go input\n",
                "integration/orchard/Cargo.lock": b"synthetic locked Rust input\n",
                "scripts/zevune_wallet.py": b"synthetic script fixture; never executed\n",
                "docs/LOCAL_NETWORK_OPERATOR.zh-CN.md": b"synthetic public operator guide\n",
            }
            for name, payload in source.items():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(payload)
            (root / "reports").mkdir()
            (root / "reports/evidence.txt").write_bytes(b"retained source evidence")
            git("add", ".")
            git("commit", "-qm", "Synthetic provenance")
            commit = git("rev-parse", "HEAD")
            tree = git("rev-parse", "HEAD^{tree}")
            (root / "integration/cometbft/untracked.go").write_bytes(b"untracked working copy input")
            (root / "integration/cometbft/ignored.go").write_bytes(b"ignored working copy input")
            actual_output, actual_run = build.checked_output, subprocess.run
            compiler_inputs = []

            def tool_output(args, cwd):
                # These are test declarations, not installed toolchain evidence.
                if args == ["go", "version"]:
                    return "go version go1.27.1 synthetic/test"
                if args == ["rustc", "--version"]:
                    return "rustc 1.98.1 synthetic-test"
                return actual_output(args, cwd)

            def run(args, **kwargs):
                if args[0] not in ("go", "cargo"):
                    return actual_run(args, **kwargs)
                # Observe the real build call's isolated inputs; no compiler or
                # fixture executable is run. Production bundle verification is
                # still performed by build() after these inert files are copied.
                staged = Path(kwargs["cwd"]).parents[1]
                self.assertNotEqual(staged, root)
                self.assertEqual({p.relative_to(staged).as_posix() for p in staged.rglob("*") if p.is_file()}, set(source))
                for name, payload in source.items():
                    self.assertEqual((staged / name).read_bytes(), payload)
                compiler_inputs.append(args[0])
                if args[0] == "go":
                    Path(args[args.index("-o") + 1]).write_bytes(b"inert Go output fixture")
                else:
                    release = Path(kwargs["env"]["CARGO_TARGET_DIR"]) / "release"
                    release.mkdir(parents=True)
                    suffix = ".exe" if os.name == "nt" else ""
                    for name in ("zevune-pool-worker", "zevune-wallet-local"):
                        (release / (name + suffix)).write_bytes(b"inert Rust output fixture")
                return subprocess.CompletedProcess(args, 0)

            bundle = Path(temp) / "bundle"
            with patch.object(build, "__file__", str(root / "scripts/build_local_lab.py")), \
                    patch.object(build, "checked_output", side_effect=tool_output), \
                    patch.object(build.subprocess, "run", side_effect=run):
                output = build.build(bundle)
            self.assertEqual(output["source_commit"], commit)
            self.assertEqual(output["source_tree"], tree)
            self.assertEqual(output["format"], "zevune-local-bundle-2")
            self.assertEqual(output["build_source"], "isolated_exact_git_blobs")
            self.assertTrue((root / "reports/evidence.txt").is_file())
            self.assertEqual(compiler_inputs, ["go", "cargo"])
            self.assertEqual(len(output["files"]), 5)
            self.assertEqual((bundle / "zevune_wallet.py").read_bytes(), source["scripts/zevune_wallet.py"])

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
