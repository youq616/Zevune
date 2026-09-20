"""The catalog workflow must execute the exact external commit, not a merge ref."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import textwrap
import unittest

WORKFLOW = Path(__file__).resolve().parents[2] / '.github/workflows/wallet-backup-catalog.yml'


class CatalogSourceTests(unittest.TestCase):
    def test_workflow_pins_checkout_and_runs_source_regressions(self):
        source = WORKFLOW.read_text()
        self.assertIn('ref: ${{ github.event.pull_request.head.sha || github.sha }}', source)
        self.assertIn('python -m unittest discover -s scripts/tests -p test_wallet_backup_source.py -v', source)
        self.assertEqual(source.count("'scripts/tests/test_wallet_backup_source.py'"), 2)
        blocks = re.findall(r"python - <<'PY_SOURCE'\n(.*?)^          PY_SOURCE$", source, re.M | re.S)
        self.assertEqual(len(blocks), 1)
        compile(textwrap.dedent(blocks[0]), '<catalog source check>', 'exec')

    def test_actual_git_commit_and_dirty_worktree_rejection(self):
        # Real Git objects and a separate Python process. No wallet, crypto,
        # remote access, user repository changes, or replacement Git commands.
        source = WORKFLOW.read_text()
        blocks = re.findall(r"python - <<'PY_SOURCE'\n(.*?)^          PY_SOURCE$", source, re.M | re.S)
        self.assertEqual(len(blocks), 1)
        guard = textwrap.dedent(blocks[0])
        with tempfile.TemporaryDirectory(prefix='catalog-source-fixture-') as home:
            root = Path(home).resolve()
            def git(*args):
                return subprocess.check_output(['git', '--no-replace-objects', *args], cwd=root,
                                               text=True, stderr=subprocess.PIPE).strip()
            git('init', '-q')
            path = root / 'public-fixture.txt'
            path.write_bytes(b'original\n')
            git('add', '.')
            def commit():
                git('-c', 'user.name=Source Test', '-c', 'user.email=source@localhost',
                    '-c', 'commit.gpgsign=false', 'commit', '-q', '-m', 'local source fixture')
                return git('rev-parse', 'HEAD')
            original = commit()
            tree = git('rev-parse', 'HEAD^{tree}')
            def check(expected):
                return subprocess.run([sys.executable, '-c', guard], cwd=root,
                                      env={**os.environ, 'ZEVUNE_CATALOG_SOURCE_HEAD': expected},
                                      capture_output=True, text=True, timeout=15)
            good = check(original)
            self.assertEqual(good.returncode, 0, good.stderr)
            self.assertEqual(json.loads(good.stdout), dict(source_head=original,
                             checkout_commit=original, source_tree=tree))
            path.write_bytes(b'dirty\n')
            self.assertNotEqual(check(original).returncode, 0)
            git('add', '.')
            self.assertNotEqual(check(original).returncode, 0)
            second = commit()
            self.assertNotEqual(original, second)
            self.assertNotEqual(check(original).returncode, 0)
            self.assertEqual(check(second).returncode, 0)
            for invalid in ('0' * 40, original + '\n', '--all'):
                self.assertNotEqual(check(invalid).returncode, 0)


if __name__ == '__main__':
    unittest.main()
