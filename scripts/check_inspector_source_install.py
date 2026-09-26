#!/usr/bin/env python3
"""Explicit installer integration test; optional genuine wallet backend, NO-FUNDS.

Only temporary test directories are removed. The product installer never deletes
source, runs the installed application or performs wallet operations.
"""
import sys
sys.dont_write_bytecode = True

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

import inspector_source_bundle as delivery
from check_inspector_source_delivery import CHILD

ROOT = Path(__file__).resolve().parents[1]


def check_install_result(raw: bytes, built: dict) -> dict:
    """Bind the actual installer CLI reply to every expected public field."""
    delivery.require(type(raw) is bytes and 0 < len(raw) <= 8192, "invalid_install_reply_size")
    result = json.loads(raw.decode("utf-8"), object_pairs_hook=delivery.unique)
    expected = dict(built, operation="install_source", installed=True, source_unchanged=True,
                    automatic_launch=False, existing_installation_modified=False)
    delivery.require(type(result) is dict and set(result) == set(expected), "invalid_install_reply_fields")
    delivery.require(all(type(result[key]) is type(value) and result[key] == value
                         for key, value in expected.items()), "install_reply_mismatch")
    return result


def runtime_command(installed: Path, scripts: Path, kind: str, backend: str = "") -> list[str]:
    # -I omits user site/environment; -S additionally disables all site startup.
    # This is a test-process boundary, not a sandbox for an untrusted interpreter.
    prelude = ("import sys\nassert sys.flags.isolated and sys.flags.no_site\n"
               "assert sys.dont_write_bytecode and 'site' not in sys.modules\n")
    return [sys.executable, '-I', '-S', '-B', '-c', prelude + CHILD,
            str(installed), str(scripts), kind, backend]


def run(source_commit: str, backend: Path | None = None) -> dict:
    actual = delivery.git_bytes(ROOT, 'rev-parse', 'HEAD', maximum=64).decode().strip()
    delivery.require(actual == source_commit, 'install_driver_source_head_mismatch')
    with tempfile.TemporaryDirectory(prefix='zevune-install-integration-') as temp:
        workspace = Path(temp).resolve()
        received, installed = workspace / 'received', workspace / 'installed'
        built = delivery.build(ROOT, source_commit, received)
        before = {path.name: path.read_bytes() for path in received.iterdir()}
        common = [sys.executable, str(ROOT / 'scripts/inspector_source_install.py'), '--no-real-funds']
        pins = ['--source-commit', source_commit, '--manifest-sha256', built['manifest_sha256']]
        process = subprocess.run(common + ['install', '--bundle', str(received),
                                          '--destination', str(installed), *pins],
                                 capture_output=True, check=True, timeout=30)
        check_install_result(process.stdout, built)
        assert before == {path.name: path.read_bytes() for path in received.iterdir()}
        assert before == {path.name: path.read_bytes() for path in installed.iterdir()}
        # Remove only our owned temporary source fixture. Prove that the installed
        # application has no dependency on a remaining received/source directory.
        shutil.rmtree(received)
        subprocess.run(common + ['verify', '--bundle', str(installed), *pins], check=True, timeout=30)
        subprocess.run([sys.executable, str(installed / 'wallet_inspector_desktop.py'), '--help'],
                       cwd=workspace, check=True, timeout=30)
        subprocess.run(runtime_command(installed, ROOT / 'scripts', 'gui'), cwd=workspace, check=True, timeout=120)
        if backend is not None:
            subprocess.run(runtime_command(installed, ROOT / 'scripts', 'native',
                                           str(backend.resolve(strict=True))),
                           cwd=workspace, check=True, timeout=600)
        delivery.verify(installed, built['manifest_sha256'], source_commit)
        assert before == {path.name: path.read_bytes() for path in installed.iterdir()}
    assert not workspace.exists()
    summary = dict(operation='explicit_install_test_driver', source_commit=source_commit,
                   source_tree=built['source_tree'], cli_install_completed=True, cli_verify_completed=True,
                   real_gui_completed=True, genuine_backend_completed=backend is not None,
                   payload_executed_by_installer=False, payload_executed_by_test_driver=True,
                   source_fixture_removed_before_launch=True, fixtures_removed=True,
                   exact_cli_reply_verified=True, isolated_runtime_without_site=True,
                   accepted=False, real_funds_allowed=False)
    print(json.dumps(summary, sort_keys=True))
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-commit', required=True)
    parser.add_argument('--backend', type=Path)
    args = parser.parse_args()
    run(args.source_commit, args.backend)
