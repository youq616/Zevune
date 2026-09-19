"""Temporary, synthetic repositories only; no compilation or network access."""
from pathlib import Path
import os
import stat
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

    def blob(self, payload):
        return self.git("hash-object", "-w", "--stdin", data=payload).decode().strip()

    def commit_entries(self, entries):
        """Make actual Git trees without platform filename checkout rules."""
        root = {}
        for path, mode, oid in entries:
            node = root
            parts = path.split("/")
            for part in parts[:-1]:
                node = node.setdefault(part, {})
            node[parts[-1]] = (mode, oid)

        def write_tree(node):
            records = []
            for name, value in node.items():
                if isinstance(value, dict):
                    mode, kind, oid = "040000", "tree", write_tree(value)
                else:
                    mode, oid = value
                    kind = "commit" if mode == "160000" else "blob"
                records.append(f"{mode} {kind} {oid}\t{name}\0".encode("utf-8"))
            return self.git("mktree", "-z", data=b"".join(records)).decode().strip()

        return self.git("commit-tree", write_tree(root), "-m", "Synthetic objects").decode().strip()

    def assert_rejected_before_blobs(self, exporter, commit, error):
        with patch.object(snapshot, "git_bytes", wraps=snapshot.git_bytes) as observed:
            with self.assertRaisesRegex(ValueError, error):
                exporter(self.root, commit, self.output)
        self.assertFalse(any(call.args[1:3] == ("cat-file", "--batch")
                             for call in observed.call_args_list))
        self.assertFalse(self.output.exists())

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

    def test_build_excludes_reports_above_real_full_tree_byte_limit(self):
        source = self.blob(b"exact build input\n")
        report = self.blob(b"e" * (7 * 1024 * 1024))
        commit = self.commit_entries([("source.dat", "100644", source)] + [
            (f"reports/evidence-{index}.bin", "100644", report) for index in range(5)])
        # Each evidence blob is below 8 MiB; the full tree really exceeds the
        # unchanged 32 MiB aggregate limit. No budget is patched in this test.
        self.assert_rejected_before_blobs(snapshot.export_source, commit, "source_size_exceeded")
        with patch.object(snapshot, "git_bytes", wraps=snapshot.git_bytes) as observed:
            tree = snapshot.export_build_source(self.root, commit, self.output)
        self.assertEqual(tree, self.git("rev-parse", commit + "^{tree}").decode().strip())
        self.assertEqual((self.output / "source.dat").read_bytes(), b"exact build input\n")
        self.assertFalse((self.output / "reports").exists())
        batches = [call.kwargs["data"] for call in observed.call_args_list
                   if call.args[1:3] == ("cat-file", "--batch")]
        self.assertEqual(batches, [source.encode() + b"\n"])
        self.assertEqual(self.git("cat-file", "-s", report).strip(), str(7 * 1024 * 1024).encode())

    def test_build_excludes_reports_above_real_full_tree_file_limit(self):
        blob = self.blob(b"synthetic evidence\n")
        commit = self.commit_entries([("input.dat", "100644", blob)] + [
            (f"reports/entry-{index}.txt", "100644", blob)
            for index in range(snapshot.MAX_FILES + 1)])
        self.assert_rejected_before_blobs(snapshot.export_source, commit, "source_file_count_exceeded")
        snapshot.export_build_source(self.root, commit, self.output)
        self.assertEqual({p.name for p in self.output.iterdir()}, {"input.dat"})

    def test_build_included_real_size_limits_remain_enforced(self):
        exact = self.blob(b"x" * snapshot.MAX_FILE_BYTES)
        too_large = self.blob(b"x" * (snapshot.MAX_FILE_BYTES + 1))
        small = self.blob(b"x")
        commit = self.commit_entries([("input.dat", "100644", too_large)])
        self.assert_rejected_before_blobs(snapshot.export_build_source, commit, "source_size_exceeded")
        entries = [(f"inputs/part-{index}.bin", "100644", exact) for index in range(4)]
        commit = self.commit_entries(entries + [("inputs/one-more-byte", "100644", small)])
        self.assert_rejected_before_blobs(snapshot.export_build_source, commit, "source_size_exceeded")
        commit = self.commit_entries(entries)
        snapshot.export_build_source(self.root, commit, self.output)
        self.assertEqual(sum(p.stat().st_size for p in self.output.rglob("*") if p.is_file()),
                         snapshot.MAX_SOURCE_BYTES)

    def test_build_included_real_file_limit_remains_enforced(self):
        blob = self.blob(b"x")
        entries = [(f"inputs/part-{index}", "100644", blob)
                   for index in range(snapshot.MAX_FILES + 1)]
        self.assert_rejected_before_blobs(snapshot.export_build_source,
                                         self.commit_entries(entries), "source_file_count_exceeded")
        snapshot.export_build_source(self.root, self.commit_entries(entries[:-1]), self.output)
        self.assertEqual(sum(p.is_file() for p in self.output.rglob("*")), snapshot.MAX_FILES)

    def test_build_preserves_literal_binary_executable_and_nested_report_inputs(self):
        payload = b"\x00binary\r\nexact\xff"
        blob = self.blob(payload)
        entries = [("input[1].dat", "100644", blob), ("reports[1]/data", "100644", blob),
                   ("assets/reports/input", "100644", blob), ("run.sh", "100755", blob),
                   ("reports/excluded", "100644", blob)]
        commit = self.commit_entries(entries)
        # Neither HEAD nor matching working-copy files supply build bytes.
        (self.root / "input[1].dat").write_bytes(b"working copy contamination")
        snapshot.export_build_source(self.root, commit, self.output)
        for path, _, _ in entries[:-1]:
            self.assertEqual((self.output / path).read_bytes(), payload)
        self.assertFalse((self.output / "reports").exists())
        self.assertEqual((self.root / "input[1].dat").read_bytes(), b"working copy contamination")
        if os.name != "nt":
            self.assertEqual(stat.S_IMODE((self.output / "run.sh").stat().st_mode), 0o700)

    def test_build_root_selection_uses_bounded_literal_argument_batches(self):
        blob = self.blob(b"x")
        entries = [(f"input-{index:03d}-" + "x" * 90, "100644", blob) for index in range(100)]
        commit = self.commit_entries(entries)
        with patch.object(snapshot, "git_bytes", wraps=snapshot.git_bytes) as observed:
            snapshot.export_build_source(self.root, commit, self.output)
        selections = [call.args[7:] for call in observed.call_args_list
                      if call.args[1:3] == ("--literal-pathspecs", "ls-tree")]
        self.assertGreater(len(selections), 1)
        for batch in selections:
            self.assertLessEqual(sum(len(path.encode("utf-8")) + 1 for path in batch), 8192)
        self.assertEqual({p.name for p in self.output.iterdir()}, {entry[0] for entry in entries})

    def test_build_reports_exclusion_requires_exact_root_tree(self):
        blob = self.blob(b"regular tracked report filename")
        for mode, oid in (("120000", blob), ("160000", self.commit)):
            with self.subTest(mode=mode):
                commit = self.commit_entries([("reports", mode, oid), ("input", "100644", blob)])
                self.assert_rejected_before_blobs(snapshot.export_build_source, commit, "unsupported_source_entry")
        commit = self.commit_entries([("reports", "100644", blob), ("input", "100644", blob)])
        snapshot.export_build_source(self.root, commit, self.output)
        self.assertEqual((self.output / "reports").read_bytes(), b"regular tracked report filename")

    def test_build_unsafe_paths_links_and_case_collisions_remain_rejected(self):
        blob = self.blob(b"synthetic public input")
        cases = [[(name, "100644", blob)] for name in
                 ("bad:name", "bad\\name", "trailing.", "dir /input", ".GiT/input",
                  "CON", "nul.txt", "src/AUX.dat", "COM1", "LPT9.log", "COM¹", "src/LPT³.dat", "CON .txt")]
        cases += [
            [("src/link", "120000", blob)],
            [("src/submodule", "160000", self.commit)],
            [("Dir/a", "100644", blob), ("dir/b", "100644", blob)],
            [("src/Dir/a", "100644", blob), ("src/dir/b", "100644", blob)],
            [("src/Dir", "100644", blob), ("src/dir/b", "100644", blob)],
            [("input", "100644", blob), ("Input", "100644", blob)],
            [("reports/a", "100644", blob), ("Reports/b", "100644", blob)],
        ]
        for entries in cases:
            with self.subTest(entries=[e[0] for e in entries]):
                commit = self.commit_entries(entries)
                self.assert_rejected_before_blobs(snapshot.export_build_source, commit, "unsupported_source_entry")

    def test_build_create_only_and_non_oid_still_fail(self):
        for value in ("HEAD", "--all", "a" * 39, "a" * 40 + "\n", "F" * 40):
            with self.subTest(value=value), self.assertRaises(ValueError):
                snapshot.export_build_source(self.root, value, self.output)
        self.output.mkdir()
        (self.output / "existing").write_bytes(b"keep")
        with self.assertRaises(FileExistsError):
            snapshot.export_build_source(self.root, self.commit, self.output)
        self.assertEqual((self.output / "existing").read_bytes(), b"keep")

    def test_build_batch_payload_still_requires_exact_blob_identity(self):
        actual = snapshot.git_bytes
        def altered(root, *args, data=None):
            result = actual(root, *args, data=data)
            if args == ("cat-file", "--batch"):
                result = result.replace(b"synthetic tracked", b"synthetic changed")
            return result
        with patch.object(snapshot, "git_bytes", side_effect=altered), self.assertRaises(ValueError):
            snapshot.export_build_source(self.root, self.commit, self.output)


if __name__ == "__main__":
    unittest.main()
