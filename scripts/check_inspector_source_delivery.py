#!/usr/bin/env python3
"""Real source-package integration; optional genuine native backend, NO-FUNDS.

The delivery tool never executes payloads. This separate test driver explicitly
executes the known test source, in a child bound to the new delivery directory.
"""
import sys
sys.dont_write_bytecode = True
import argparse
import json
from pathlib import Path
import subprocess
import tempfile

import inspector_source_bundle as delivery

ROOT = Path(__file__).resolve().parent.parent

CHILD = r'''
import importlib, pathlib, runpy, sys
bundle, scripts = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
kind, backend = sys.argv[3], sys.argv[4]
# Python -I ignores environment/site injection; only this explicit directory
# supplies runtime modules. The repository supplies the unchanged test harness.
sys.path.insert(0, str(bundle))
names = ('wallet_inspector_desktop', 'wallet_reconcile', 'wallet_health',
         'wallet_backup_backend', 'wallet_backup', 'wallet_archive',
         'ledger_restore', 'ledger_recovery_backend', 'zevune_wallet')
for name in names:
    module = importlib.import_module(name)
    assert pathlib.Path(module.__file__).resolve().parent == bundle, 'runtime import escaped delivery'
sys.path.append(str(scripts))
if kind == 'native':
    import check_wallet_inspector_backend
    check_wallet_inspector_backend.run(pathlib.Path(backend))
else:
    sys.argv = [str(scripts / 'check_wallet_inspector_gui.py'), '-v']
    runpy.run_path(sys.argv[0], run_name='__main__')
'''


def run(source_commit: str, backend: Path | None = None) -> dict:
    actual = delivery.git_bytes(ROOT, 'rev-parse', 'HEAD', maximum=64).decode().strip()
    delivery.require(actual == source_commit, 'test_source_head_mismatch')
    with tempfile.TemporaryDirectory(prefix='zevune-inspector-delivery-') as temp:
        folder = Path(temp).resolve() / 'runtime'
        result = delivery.build(ROOT, source_commit, folder)
        before = {p.name: p.read_bytes() for p in folder.iterdir()}
        # Public CLI, in another process, independently supplied pins, no Tk.
        subprocess.run([sys.executable, str(ROOT/'scripts/inspector_source_bundle.py'),
                        '--no-real-funds', 'verify', '--bundle', str(folder),
                        '--source-commit', source_commit,
                        '--manifest-sha256', result['manifest_sha256']], check=True, timeout=30)
        # Ordinary launch, not requiring users to supply -B for the app's help.
        subprocess.run([sys.executable, str(folder/'wallet_inspector_desktop.py'), '--help'],
                       cwd=temp, check=True, timeout=30)
        subprocess.run([sys.executable, '-I', '-B', '-c', CHILD, str(folder), str(ROOT/'scripts'),
                        'gui', ''], cwd=temp, check=True, timeout=120)
        if backend is not None:
            subprocess.run([sys.executable, '-I', '-B', '-c', CHILD, str(folder), str(ROOT/'scripts'),
                            'native', str(backend.resolve(strict=True))], cwd=temp, check=True, timeout=600)
        delivery.verify(folder, result['manifest_sha256'], source_commit)
        assert before == {p.name: p.read_bytes() for p in folder.iterdir()}, 'delivery bytes changed'
    assert not folder.exists(), 'test delivery not removed'
    result.update(operation="explicit_test_driver", payload_executed=True, real_gui_completed=True, genuine_backend_completed=backend is not None,
                  fixtures_removed=True)
    print(json.dumps(result, sort_keys=True))
    return result


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-commit',required=True)
    parser.add_argument('--backend',type=Path)
    args=parser.parse_args()
    run(args.source_commit,args.backend)
