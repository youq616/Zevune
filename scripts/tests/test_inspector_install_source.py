"""Installer workflow and cross-platform repository path regression checks."""
import ast
import fnmatch
import json
import os
import subprocess
import tempfile
from pathlib import Path, PureWindowsPath
import re
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_inspector_delivery_source as source_tests
import check_inspector_source_install as driver


class InstallSourceTests(unittest.TestCase):
    def test_delivery_dependency_guard_uses_git_paths_on_windows(self):
        original = source_tests.WORKFLOW

        class WindowsSpelling:
            def relative_to(self, root):
                return PureWindowsPath(original.relative_to(root).as_posix())

            def read_text(self):
                return original.read_text()

        # Run the REAL dependency closure and assertion, only representing the
        # workflow path with Windows spelling. Not native Windows execution.
        case = source_tests.DeliverySourceTests()
        with patch.object(source_tests, "WORKFLOW", WindowsSpelling()):
            case.test_events_cover_all_static_transitive_test_and_runtime_inputs()


    def test_new_workflow_covers_transitive_sources_and_tests(self):
        root = source_tests.ROOT
        workflow = root / '.github/workflows/inspector-source-install.yml'
        paths = ['scripts/inspector_source_install.py', 'scripts/check_inspector_source_install.py',
                 'scripts/check_wallet_inspector_gui.py', 'scripts/check_wallet_inspector_backend.py',
                 'scripts/tests/test_inspector_source_install.py', 'scripts/tests/test_inspector_install_source.py',
                 'scripts/tests/test_inspector_source_bundle.py', 'scripts/tests/test_inspector_delivery_source.py',
                 'scripts/tests/test_verify_local_lab.py', 'scripts/tests/test_wallet_inspector_desktop.py']
        pending = [root / path for path in paths]
        dependencies = set(source_tests.delivery.SOURCES.values()) | {
            workflow.relative_to(root).as_posix(), source_tests.WORKFLOW.relative_to(root).as_posix(),
            'docs/INSPECTOR_SOURCE_INSTALL.zh-CN.md', 'docs/INSPECTOR_SOURCE_DELIVERY.zh-CN.md'}
        visited = set()
        while pending:
            path = pending.pop()
            if path in visited:
                continue
            visited.add(path)
            dependencies.add(path.relative_to(root).as_posix())
            for node in ast.walk(ast.parse(path.read_bytes())):
                names = ([item.name for item in node.names] if isinstance(node, ast.Import) else
                         [node.module] if isinstance(node, ast.ImportFrom) and node.module and not node.level else [])
                for name in names:
                    for directory in (root / 'scripts', root / 'scripts/tests'):
                        candidate = directory / (name.split('.')[0] + '.py')
                        if candidate.is_file():
                            pending.append(candidate)
        blocks = dict(re.findall(r'^  (push|pull_request):\n((?:    [^\n]*\n)+)', workflow.read_text(), re.M))
        self.assertEqual(set(blocks), {'push', 'pull_request'})
        for body in blocks.values():
            patterns = ast.literal_eval(re.findall(r'^    paths: (.+)$', body, re.M)[0])
            for path in dependencies:
                self.assertTrue(any(fnmatch.fnmatchcase(path, pattern) for pattern in patterns), path)

    def test_new_workflow_guard_rejects_wrong_commit_and_dirty_source(self):
        workflow = source_tests.ROOT / '.github/workflows/inspector-source-install.yml'
        with patch.object(source_tests, 'WORKFLOW', workflow):
            source_tests.DeliverySourceTests().test_actual_workflow_guard_rejects_wrong_commit_and_dirty_source()

    def test_new_workflow_keeps_genuine_native_execution_and_budgets(self):
        text = (source_tests.ROOT / '.github/workflows/inspector-source-install.yml').read_text()
        self.assertIn('ref: ${{ github.event.pull_request.head.sha || github.sha }}', text)
        self.assertIn('persist-credentials: false', text)
        self.assertIn('os: [ubuntu-latest, windows-latest]', text)
        self.assertIn('cargo +1.98.1 build', text)
        self.assertIn('--locked --release --features local-funding-lab --bin zevune-wallet-local', text)
        self.assertIn("'--backend', str(backend)", text)
        self.assertIn('check=True, timeout=750', text)
        self.assertIn('timeout-minutes: 20', text)
        self.assertNotIn('continue-on-error', text)
        self.assertNotIn('upload-artifact', text)
        for name in ('test_inspector_source_install.py', 'test_inspector_install_source.py',
                     'test_inspector_source_bundle.py', 'test_inspector_delivery_source.py', 'test_verify_local_lab.py'):
            self.assertIn('python -B -m unittest discover -s scripts/tests -p ' + name + ' -v', text)

    @staticmethod
    def reply_fixture():
        # Public installer metadata only, never a successful wallet verifier.
        return dict(integrity_verified=True, manifest_sha256="a" * 64,
                    source_commit="b" * 40, source_tree="c" * 40, payload_files=10,
                    payload_executed=False, code_signature_verified=False,
                    accepted=False, real_funds_allowed=False)

    def test_driver_reply_matches_every_pin_field_and_strict_type(self):
        built = self.reply_fixture()
        expected = dict(built, operation="install_source", installed=True, source_unchanged=True,
                        automatic_launch=False, existing_installation_modified=False)
        self.assertEqual(driver.check_install_result(json.dumps(expected).encode(), built), expected)
        for key, value in expected.items():
            wrong = dict(expected)
            wrong[key] = int(value) if type(value) is bool else (True if type(value) is int else "wrong")
            with self.subTest(field=key), self.assertRaises(ValueError):
                driver.check_install_result(json.dumps(wrong).encode(), built)
            missing = dict(expected)
            del missing[key]
            with self.assertRaises(ValueError):
                driver.check_install_result(json.dumps(missing).encode(), built)

    def test_driver_reply_rejects_duplicates_extra_data_and_oversize(self):
        built = self.reply_fixture()
        good = dict(built, operation="install_source", installed=True, source_unchanged=True,
                    automatic_launch=False, existing_installation_modified=False)
        raw = json.dumps(good).encode()
        for bad in (b"", b"[]", b"null", raw + raw, b" " * 8193,
                    raw[:-1] + b',"installed":true}',
                    json.dumps(dict(good, extra="untrusted")).encode()):
            with self.subTest(size=len(bad)), self.assertRaises(ValueError):
                driver.check_install_result(bad, built)

    def test_driver_runtime_command_disables_site_and_ignores_pythonpath(self):
        # Execute actual Python with the exact flags used for both GUI/native.
        with tempfile.TemporaryDirectory() as temp:
            command = driver.runtime_command(Path(temp), Path(temp), "gui")
            self.assertEqual(command[1:5], ['-I', '-S', '-B', '-c'])
            probe = ("import sys, json; print(json.dumps([sys.flags.isolated, "
                     "sys.flags.no_site, sys.dont_write_bytecode, 'site' in sys.modules]))")
            result = subprocess.run(command[:5] + [probe], cwd=temp,
                                    env={**os.environ, 'PYTHONPATH': temp}, capture_output=True,
                                    check=True, timeout=15)
            self.assertEqual(json.loads(result.stdout), [1, 1, True, False])
            native = driver.runtime_command(Path(temp), Path(temp), "native", "original-backend")
            self.assertEqual(native[:5], command[:5])
            self.assertEqual(native[-2:], ["native", "original-backend"])

    def test_installer_does_not_import_runtime_or_expand_payload_contract(self):
        root = source_tests.ROOT
        source = (root / 'scripts/inspector_source_install.py').read_bytes()
        names = set()
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Import):
                names.update(item.name.split('.')[0] for item in node.names)
            elif isinstance(node, ast.ImportFrom):
                names.add(node.module.split('.')[0])
        self.assertTrue(names <= set(sys.stdlib_module_names) | {'inspector_source_bundle'})
        self.assertEqual(len(source_tests.delivery.SOURCES), 10)
        self.assertNotIn('inspector_source_install.py', source_tests.delivery.SOURCES)


if __name__ == "__main__":
    unittest.main()
