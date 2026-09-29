#!/usr/bin/env python3
"""Task-file execution using the unchanged genuine installed-Rust integration.

Only temporary valueless fixtures are changed. Successful replay is never mocked.
"""
import contextlib
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

import check_ledger_transaction_batch_once_backend as previous
import ledger_query_request as task


def run(wallet: Path, worker: Path, recovery: Path):
    original = previous.previous.previous.original
    saved_recover = original.reconcile.recover
    groups, checks = [], []
    transaction_id = None

    def observe(*args, **kwargs):
        nonlocal transaction_id
        report = saved_recover(*args, **kwargs)
        output, journal = args[1], kwargs['journal']
        if output.name == 'pending':
            transaction_id = report['txid']
        assert transaction_id is not None
        backend = kwargs['recovery_backend'].binary.path
        request = task.prepare(kwargs['checkpoint'], kwargs['genesis_sha256'],
                               hashlib.sha256(backend.read_bytes()).hexdigest(),
                               ['0' * 64, transaction_id, '1' * 64])
        path = output.parent / (output.name + '-query.json')
        before, evidence = original.inventory(journal), original.inventory(output)
        # Creation/inspection must not execute even when genuine evidence exists.
        with patch.object(subprocess, 'Popen', side_effect=AssertionError('implicit execution')):
            created = task.create(request, path)
            inspected = task.inspect_request(path, created['request_sha256'])
        assert inspected['execution_performed'] is False and inspected['signature_verified'] is False
        raw, pin = path.read_bytes(), created['request_sha256']
        native = task.once.single.checked.RecoveryBackend._run
        calls = []
        def real_native(self, *params):
            calls.append(params[0][0])
            return native(self, *params)
        with patch.object(task.once.single.checked.RecoveryBackend, '_run', real_native):
            result = task.run_request(path, pin, journal, backend)
        assert calls == ['verify-active']
        query = result['result']
        assert result['request_sha256'] == pin and result['request_file_unchanged'] is True
        assert result['real_funds_allowed'] is result['signature_verified'] is False
        assert [row['txid'] for row in query['results']] == list(request.txids)
        assert query['included_count'] == int(output.name == 'included')
        assert query['native_replay_count'] == query['history_scan_count'] == 1
        assert query['settlement_status'] == 'unknown' and query['retry_authorized'] is False
        assert path.read_bytes() == raw
        if output.name == 'included':
            common = dict(journal=str(journal), backend=str(backend), checkpoint=request.checkpoint,
                          genesis_sha256=request.genesis_sha256, backend_sha256=request.backend_sha256,
                          txids=request.txids)
            assert query == task.once.lookup_batch_once(task.once.prepare(common))
            checks.append('fresh_query_matches_direct_original_core')
            arguments = ['--no-real-funds', 'run', '--request', str(path), '--request-sha256', pin,
                         '--journal', str(journal), '--backend', str(backend)]
            process = subprocess.run([sys.executable, '-B', task.__file__, *arguments],
                                     check=True, capture_output=True, timeout=310)
            assert json.loads(process.stdout) == result and not process.stderr
            checks.append('real_task_cli_executes_original_native')
            original.reject(lambda: task.run_request(path, '0' * 64, journal, backend))
            checks.append('incorrect_external_task_digest_refused')
            # The core actually succeeds before the test mutates the request.
            core = task.once.lookup_batch_once
            def mutate_after_real_query(intent):
                answer = core(intent)
                path.write_bytes(raw + b'x')
                return answer
            out, err = io.StringIO(), io.StringIO()
            try:
                with patch.object(task.once, 'lookup_batch_once', mutate_after_real_query), \
                        contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                    code = task.main(arguments)
                assert code == 1 and out.getvalue() == '' and 'Query request failed.' in err.getvalue()
                checks.append('post_native_request_change_refused_without_success_output')
            finally:
                path.write_bytes(raw)
            # Exact original bytes at a new file identity are still a change.
            held = path.with_suffix('.held')
            def replace_after_real_query(intent):
                answer = core(intent)
                path.rename(held)
                path.write_bytes(raw)
                return answer
            try:
                with patch.object(task.once, 'lookup_batch_once', replace_after_real_query):
                    original.reject(lambda: task.run_request(path, pin, journal, backend))
                checks.append('post_native_same_bytes_replacement_refused')
            finally:
                path.unlink()
                held.rename(path)
        assert original.inventory(journal) == before and original.inventory(output) == evidence
        assert path.read_bytes() == raw
        path.unlink()  # Only the driver's own temporary file; no product deletion.
        groups.append((output.name, query['included_count']))
        return report

    with patch.object(original.reconcile, 'recover', side_effect=observe):
        previous.run(wallet, worker, recovery)
    assert groups == [('pending', 0), ('empty-result', 0), ('included', 1), ('expired', 0)], groups
    assert len(checks) == 5
    print(json.dumps(dict(operation='ledger_query_request_native_test', genuine_history_groups=4,
                          original_installer_recovery_single_batch_once_completed=True,
                          input_bytes_preserved=True, checks=checks, real_funds_allowed=False), sort_keys=True))


if __name__ == '__main__':
    if len(sys.argv) != 4:
        raise SystemExit('Original wallet, worker and recovery paths required')
    run(*(Path(value) for value in sys.argv[1:]))
