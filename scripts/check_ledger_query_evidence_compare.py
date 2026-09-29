#!/usr/bin/env python3
"""Exercise the real offline CLIs with attempted writes/process/network IO denied.

Audit hooks are regression instrumentation for trusted code, not a sandbox.
All fixture creation/deletion happens in this parent driver's temporary folder.
"""
import sys
sys.dont_write_bytecode = True

import hashlib
import json
from pathlib import Path
import subprocess
import tempfile

import ledger_query_evidence_compare as compare
import check_ledger_query_audit as original

ROOT = Path(__file__).resolve().parent
GUARD = r'''
import os, sys
from pathlib import Path
attempts = []
seen_probe = []
def guard(event, args):
    if event == 'zevune.comparison_guard_probe':
        seen_probe.append(True)
    forbidden = event.startswith('socket.') or event in (
        'subprocess.Popen', 'os.system', 'os.posix_spawn', 'os.posix_spawnp',
        'os.remove', 'os.rename', 'os.rmdir', 'os.mkdir', 'os.link', 'os.symlink',
        'os.chmod', 'os.chown', 'os.utime', 'os.truncate')
    if event == 'open':
        path, mode, flags = args
        if isinstance(path, (str, bytes)):
            name = Path(os.fsdecode(path)).name
            forbidden = forbidden or name.endswith('.journal') or name == 'genesis'
        forbidden = forbidden or bool(flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND))
    if forbidden:
        attempts.append(event)
        raise PermissionError('offline comparison attempted a forbidden operation')
sys.addaudithook(guard)
sys.audit('zevune.comparison_guard_probe')
assert seen_probe == [True]
sys.path.insert(0, sys.argv[1])
import ledger_query_evidence_compare as product
assert Path(product.__file__).resolve().parent == Path(sys.argv[1]).resolve()
code = product.main(sys.argv[2:])
assert not attempts, 'forbidden attempt occurred even if the product caught it'
raise SystemExit(code)
'''


def run():
    with tempfile.TemporaryDirectory(prefix='zevune-evidence-offline-') as temporary:
        root = Path(temporary).resolve()
        original_request = original.request_fixture()
        # Full 32-ID tasks: the after set removes one ID, adds one and reorders.
        after_request = compare.task.prepare(
            original_request.checkpoint, original_request.genesis_sha256, 'b' * 64,
            (*reversed(original_request.txids[1:]), 'f' * 64))
        sources = []
        for label, request in (('before', original_request), ('after', after_request)):
            path, report = root / (label + '.json'), root / (label + '-report.json')
            pin = compare.task.create(request, path)['request_sha256']
            report_pin = compare.reports.export_audit(path, pin, report)['audit_sha256']
            sources.append(dict(task=compare.Source('task', path, pin), report=compare.Source('report', report, report_pin)))
        before_bytes = {path.name: path.read_bytes() for path in root.iterdir()}
        invocations = []

        def cli(left, right, *, flags=(), expected=0):
            args = ['--no-real-funds']
            for side, source in (('before', left), ('after', right)):
                args += ['--' + side, str(source.path), '--' + side + '-sha256', source.sha256,
                         '--' + side + '-kind', source.kind]
            result = subprocess.run([sys.executable, '-I', '-S', '-B', '-c', GUARD, str(ROOT), *args, *flags],
                                    capture_output=True, timeout=20, cwd=root)
            assert result.returncode == expected, (result.returncode, result.stderr)
            invocations.append((left.kind, right.kind, tuple(flags), expected))
            if expected:
                assert not result.stdout
                return None
            assert not result.stderr
            text = result.stdout.decode('utf-8')
            if '--details' not in flags:
                for sensitive in (*original_request.txids, *after_request.txids, original_request.checkpoint,
                                  original_request.backend_sha256, after_request.backend_sha256, str(root)):
                    assert sensitive not in text
            if '--text' in flags:
                assert left.sha256 in text and right.sha256 in text
                return text
            return json.loads(text)

        expected = compare.changes.describe(original_request, after_request)
        for left_kind in compare.KINDS:
            for right_kind in compare.KINDS:
                result = cli(sources[0][left_kind], sources[1][right_kind])
                assert result['difference'] == expected
                assert result['before']['source_file_rechecked'] is (left_kind == 'task')
                assert result['after']['source_file_rechecked'] is (right_kind == 'task')
                assert result['execution_performed'] is result['signature_verified'] is result['retry_authorized'] is False
        detailed = cli(sources[0]['report'], sources[1]['task'], flags=('--details',))
        assert detailed['difference']['details']['before'] == original_request.document()
        assert detailed['difference']['details']['after'] == after_request.document()
        cli(sources[0]['report'], sources[1]['report'], flags=('--text',))
        cli(sources[0]['task'], sources[1]['report'], flags=('--text', '--details'))
        assert before_bytes == {path.name: path.read_bytes() for path in root.iterdir()}

        sources[0]['task'].path.unlink()
        sources[1]['task'].path.unlink()
        result = cli(sources[0]['report'], sources[1]['report'])
        assert not result['before']['source_file_rechecked'] and not result['after']['source_file_rechecked']
        cli(sources[0]['task'], sources[1]['report'], expected=1)
        bad = compare.Source('report', sources[0]['report'].path, sources[0]['task'].sha256)
        cli(bad, sources[1]['report'], expected=1)
        bad = compare.Source('task', sources[0]['report'].path, sources[0]['report'].sha256)
        cli(bad, sources[1]['report'], expected=1)
        sources[0]['report'].path.write_bytes(before_bytes['before-report.json'] + b'x')
        cli(sources[0]['report'], sources[1]['report'], expected=1)
        assert sources[1]['report'].path.read_bytes() == before_bytes['after-report.json']
    assert not root.exists()
    result = dict(operation='offline_query_evidence_comparison_integration', actual_cli_commands=len(invocations),
                  maximum_query_count_per_side=32, all_four_input_modes_verified=True,
                  default_output_omits_details=True, report_source_not_misreported=True,
                  forbidden_process_network_ledger_write_attempts=0, native_query_executed=False,
                  fixtures_removed=True, real_funds_allowed=False)
    print(json.dumps(result, sort_keys=True))
    return result


if __name__ == '__main__':
    run()
