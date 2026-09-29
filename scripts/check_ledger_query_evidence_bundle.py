#!/usr/bin/env python3
"""Real bounded bundle CLI round trip with write destinations restricted by a test hook.

Hooks are trusted-code regression instrumentation, not a security sandbox.
Fixture deletion, corruption and source creation occur only in this parent.
"""
import sys
sys.dont_write_bytecode = True

import hashlib
import json
from pathlib import Path
import subprocess
import tempfile

import ledger_query_evidence_bundle as bundle
import check_ledger_query_audit as fixtures

GUARD = r'''
import os, re, sys
from pathlib import Path
root = Path(sys.argv[1]).resolve()
allowed = None if sys.argv[2] == '-' else Path(sys.argv[2])
mode = sys.argv[3]
attempts = []
def guard(event, args):
    bad = event.startswith('socket.') or event in ('subprocess.Popen', 'os.system', 'os.posix_spawn',
        'os.posix_spawnp', 'os.remove', 'os.rename', 'os.rmdir', 'os.link', 'os.symlink', 'os.chmod', 'os.utime')
    if event == 'open':
        path, _, flags = args
        writing = flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC)
        if isinstance(path, (str, bytes)):
            p = Path(os.fsdecode(path))
            bad = bad or p.name == 'genesis' or p.name.endswith('.journal')
            if writing:
                permitted = allowed is not None and (
                    (mode == 'pack' and p == allowed) or
                    (mode == 'unpack' and p.parent == allowed and re.fullmatch(r'(0[1-9]|[12][0-9]|3[0-2])-(task|report)\.json', p.name)))
                bad = bad or not permitted
        elif writing:
            # fdopen of an already approved, exclusively created file descriptor.
            bad = bad or allowed is None
    if event == 'os.mkdir':
        bad = bad or allowed is None or mode != 'unpack' or Path(args[0]) != allowed
    if bad:
        attempts.append(event)
        raise PermissionError('forbidden bundle regression operation')
sys.addaudithook(guard)
sys.path.insert(0, str(root))
import ledger_query_evidence_bundle as product
assert Path(product.__file__).resolve().parent == root
code = product.main(sys.argv[4:])
assert not attempts, 'a forbidden action was attempted, even if caught'
raise SystemExit(code)
'''


def run():
    commands = []
    with tempfile.TemporaryDirectory(prefix='zevune-bundle-cli-') as temp:
        root = Path(temp).resolve()
        sources = []
        for i in range(16):
            example = fixtures.request_fixture()
            request = bundle.task.prepare(example.checkpoint, example.genesis_sha256, example.backend_sha256,
                                           [hashlib.sha256(f'public-{i}-{j}'.encode()).hexdigest() for j in range(32)])
            path, report = root/f'task-{i}.json', root/f'report-{i}.json'
            pin = bundle.task.create(request, path)['request_sha256']
            rp = bundle.reports.export_audit(path, pin, report)['audit_sha256']
            sources.extend((bundle.evidence.Source('task', path, pin), bundle.evidence.Source('report', report, rp)))
        originals = {s.path.name: s.path.read_bytes() for s in sources}
        packed, restored = root/'bundle.json', root/'new-directory'

        def cli(action, arguments, expected=0, output=None):
            command = [sys.executable, '-I', '-S', '-B', '-c', GUARD,
                       str(Path(bundle.__file__).resolve().parent), str(output) if output else '-', action,
                       '--no-real-funds', action, *arguments]
            process = subprocess.run(command, capture_output=True, timeout=20, cwd=root)
            assert process.returncode == expected, (action, process.returncode, process.stderr)
            commands.append((action, expected))
            if expected:
                assert not process.stdout
                return None
            assert not process.stderr
            assert str(root).encode() not in process.stdout
            result = json.loads(process.stdout)
            assert result['execution_performed'] is result['signature_verified'] is result['real_funds_allowed'] is False
            return result

        inputs = []
        for source in sources:
            inputs += ['--entry', source.kind, str(source.path), source.sha256]
        result = cli('pack', [*inputs, '--destination', str(packed)], output=packed)
        assert result['entry_count'] == 32 and result['selected_input_files_rechecked'] is True
        raw, pin = packed.read_bytes(), result['bundle_sha256']
        params = ['--bundle', str(packed), '--bundle-sha256', pin]
        verified = cli('verify', params)
        assert verified['original_inputs_rechecked'] is False
        out = cli('unpack', [*params, '--destination', str(restored)], output=restored)
        for item, source in zip(out['entries'], sources):
            assert (restored/item['filename']).read_bytes() == originals[source.path.name]
        cli('verify-directory', [*params, '--destination', str(restored)])
        cli('unpack', [*params, '--destination', str(restored)], expected=1, output=restored)
        cli('pack', [*inputs, '--destination', str(packed)], expected=1, output=packed)
        second = root/'second-bundle.json'
        cli('pack', [*inputs, '--destination', str(second)], output=second)
        assert second.read_bytes() == raw and originals == {s.path.name: s.path.read_bytes() for s in sources}
        for s in sources:
            s.path.unlink()
        cli('verify', params)
        cli('verify-directory', [*params, '--destination', str(restored)])
        cli('verify', ['--bundle', str(packed), '--bundle-sha256', '0'*64], expected=1)
        (restored/'EXTRA').write_bytes(b'inert')
        cli('verify-directory', [*params, '--destination', str(restored)], expected=1)
        packed.write_bytes(raw+b'x')
        cli('unpack', [*params, '--destination', str(root/'must-not-exist')], expected=1, output=root/'must-not-exist')
        assert not (root/'must-not-exist').exists()
    assert not root.exists()
    result = dict(operation='evidence_bundle_offline_integration', actual_cli_commands=len(commands),
                  entries=32, exact_roundtrip=True, deterministic_package=True,
                  original_source_presence_not_claimed=True, native_execution_performed=False,
                  unexpected_write_process_network_ledger_attempts=0, fixtures_removed=True, real_funds_allowed=False)
    print(json.dumps(result, sort_keys=True))
    return result


if __name__ == '__main__':
    run()
