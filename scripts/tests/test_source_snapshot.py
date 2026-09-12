"""Temporary, synthetic repositories only; no compilation or network access."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import source_snapshot as snapshot


class SourceSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve() / "repository"
        self.root.mkdir()
        self.git("init", "-q")
        self.git("config", "user.name", "Synthetic test")
        self.git("config", "user.email", "test@example.invalid")
        self.git("config", "core.autocrlf", "false")
        (self.root / ".gitignore").write_bytes(b"ignored.rs\n")
        (self.root / "tracked.rs").write_bytes(b"// synthetic tracked source\n")
        self.git("add", ".")
        self.git("commit", "-qm", "Synthetic source")
        self.commit = self.git("rev-parse", "HEAD").decode().strip()
        self.output = self.root.parent / "snapshot"

    def git(self, *args, data=None):
        return subprocess.run(["git", *args], cwd=self.root, input=data,
                              capture_output=True, check=True).stdout

    def test_excludes_untracked_ignored_and_modified_working_copy(self):
        (self.root / "untracked.go").write_bytes(b"not a build input")
        (self.root / "ignored.rs").write_bytes(b"not a build input")
        (self.root / "tracked.rs").write_bytes(b"modified working source")
        tree = snapshot.export_source(self.root, self.commit, self.output)
        self.assertEqual(tree, self.git("rev-parse", self.commit + "^{tree}").decode().strip())
        self.assertEqual({p.name for p in self.output.iterdir()}, {".gitignore", "tracked.rs"})
        self.assertEqual((self.output / "tracked.rs").read_bytes(), b"// synthetic tracked source\n")
        self.assertEqual((self.root / "tracked.rs").read_bytes(), b"modified working source")

    def test_uses_captured_commit_not_moving_head(self):
        (self.root / "later.rs").write_bytes(b"later source")
        self.git("add", "."); self.git("commit", "-qm", "Later source")
        snapshot.export_source(self.root, self.commit, self.output)
        self.assertFalse((self.output / "later.rs").exists())

    def test_no_checkout_eol_filter_changes(self):
        (self.root / ".gitattributes").write_bytes(b"*.ps1 text eol=crlf\n")
        (self.root / "test.ps1").write_bytes(b"# synthetic\n# canonical LF\n")
        self.git("add", "."); self.git("commit", "-qm", "EOL attributes")
        commit = self.git("rev-parse", "HEAD").decode().strip()
        snapshot.export_source(self.root, commit, self.output)
        self.assertEqual((self.output / "test.ps1").read_bytes(), b"# synthetic\n# canonical LF\n")

    def test_create_only(self):
        self.output.mkdir()
        (self.output / "existing").write_bytes(b"keep")
        with self.assertRaises(FileExistsError):
            snapshot.export_source(self.root, self.commit, self.output)
        self.assertEqual((self.output / "existing").read_bytes(), b"keep")

    def test_non_oid_and_option_inputs_rejected(self):
        for value in ("HEAD", "--all", "a" * 39, "a" * 40 + "\n", "F" * 40):
            with self.subTest(value=value), self.assertRaises(ValueError):
                snapshot.export_source(self.root, value, self.output)
        self.assertFalse(self.output.exists())

    def test_tracked_link_refused_without_following_it(self):
        oid = self.git("hash-object", "-w", "--stdin", data=b"../../outside").decode().strip()
        self.git("update-index", "--add", "--cacheinfo", "120000," + oid + ",link")
        tree = self.git("write-tree").decode().strip()
        commit = self.git("commit-tree", tree, "-m", "Synthetic symlink").decode().strip()
        with self.assertRaisesRegex(ValueError, "unsupported_source_entry"):
            snapshot.export_source(self.root, commit, self.output)
        self.assertFalse(self.output.exists())

    def test_file_count_and_size_are_checked_before_blob_fetch(self):
        for setting, limit in (("MAX_FILES", 1), ("MAX_FILE_BYTES", 1), ("MAX_SOURCE_BYTES", 1)):
            with self.subTest(setting=setting), patch.object(snapshot, setting, limit), self.assertRaises(ValueError):
                snapshot.export_source(self.root, self.commit, self.output)
        self.assertFalse(self.output.exists())

    def test_modified_batch_payload_fails_identity_check(self):
        actual = snapshot.git_bytes
        def altered(root, *args, data=None):
            result = actual(root, *args, data=data)
            if args == ("cat-file", "--batch"):
                result = result.replace(b"synthetic tracked", b"synthetic changed")
            return result
        with patch.object(snapshot, "git_bytes", side_effect=altered), self.assertRaises(ValueError):
            snapshot.export_source(self.root, self.commit, self.output)


if __name__ == "__main__":
    unittest.main()
