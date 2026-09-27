#!/usr/bin/env python3
"""Genuine installed-Rust replay, old/new equivalence and one record pass.

No successful native substitutes. Preserve the entire original C22 integration;
all deliberate mutation is limited to owned, valueless temporary fixtures.
"""
import contextlib
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

import check_ledger_transaction_batch_backend as previous
import ledger_transaction_batch_once as once


def run(wallet: Path, worker: Path, recovery: Path):
    original = previous.previous.original
    saved_recover = original.reconcile.recover
    txid = None
    groups, checks = [], []

    def observe(*args, **kwargs):
        nonlocal txid
        report = saved_recover(*args, **kwargs)
        directory, journal = args[1], kwargs['journal']
        if directory.name == 'pending':
            txid = report['txid']
        assert txid is not None
        backend = kwargs['recovery_backend'].binary.path
        values = dict(journal=str(journal), checkpoint=kwargs['checkpoint'], genesis_sha256=kwargs['genesis_sha256'],
                      backend=str(backend), backend_sha256=hashlib.sha256(backend.read_bytes()).hexdigest(),
                      txids=['0' * 64, txid, '1' * 64])
        intent = once.prepare(values)
        before, evidence = original.inventory(journal), original.inventory(directory)
        real_native = once.single.checked.RecoveryBackend._run
        real_decode = once.single.scan_segment_many
        calls, segments = [], []
        def native(self, *params):
            calls.append((params[0][0], params[-1]))
            return real_native(self, *params)
        def decoded(*params):
            segments.append((params[1], params[-1]))
            return real_decode(*params)
        with patch.object(once.single.checked.RecoveryBackend, '_run', native), \
                patch.object(once.single, 'scan_segment_many', decoded):
            result = once.lookup_batch_once(intent)
        pin = once.single.Checkpoint.parse(values['checkpoint'])
        assert len(calls) == 1 and calls[0][0] == 'verify-active'
        assert len(segments) == pin.segments and all(deadline == calls[0][1] for _, deadline in segments)
        assert result['history_scan_count'] == result['native_replay_count'] == 1
        assert result['batch_complete'] is True and result['historical_search_complete'] is True
        reference = once.batch.lookup_batch(intent)  # Another actual replay, not a cached authority.
        assert result['results'] == reference['results']
        included = directory.name == 'included'
        assert [row['historical_inclusion_verified'] for row in result['results']] == [False, included, False]
        assert result['included_count'] == int(included) and result['absent_count'] == 3 - int(included)
        for name in ('wallet_authenticated', 'recipient_or_amount_verified', 'finality_verified',
                     'retry_authorized', 'portable_proof_generated', 'real_funds_allowed'):
            assert result[name] is False
        assert result['current_chain_height'] is None
        assert result['broadcast_status'] == result['settlement_status'] == 'unknown'
        if included:
            many = once.prepare(dict(values, txids=[txid] + [f'{i:064x}' for i in range(31)]))
            calls.clear(); segments.clear()
            with patch.object(once.single.checked.RecoveryBackend, '_run', native), \
                    patch.object(once.single, 'scan_segment_many', decoded):
                large = once.lookup_batch_once(many)
            assert len(calls) == 1 and len(segments) == pin.segments
            assert large['included_count'] == 1 and large['query_count'] == 32
            assert large['results'] == once.batch.lookup_batch(many)['results']
            checks.append('32_ids_one_native_and_one_record_pass_equal_old_batch')
            reverse = once.lookup_batch_once(once.prepare(dict(values, txids=list(reversed(values['txids'])))))
            assert reverse['results'] == list(reversed(result['results']))
            checks.append('ordered_results')
            args = ['--no-real-funds']
            for key in once.batch.COMMON_FIELDS:
                args.extend(['--' + key.replace('_', '-'), values[key]])
            for item in values['txids']:
                args.extend(['--txid', item])
            command = [sys.executable, '-B', str(Path(once.__file__)), *args]
            output = subprocess.run(command, check=True, capture_output=True, timeout=310)
            assert json.loads(output.stdout) == result and not output.stderr
            output = subprocess.run(command + ['--text'], check=True, capture_output=True, timeout=310)
            assert output.stdout.decode('utf-8') == once.render(result) + '\n' and not output.stderr
            checks.append('real_cli_json_and_utf8')
            path = journal / '00000000.journal'; raw = path.read_bytes()
            calls.clear()
            try:
                path.write_bytes(raw[:-1] + bytes([raw[-1] ^ 1]))
                with patch.object(once.single.checked.RecoveryBackend, '_run', native), \
                        patch.object(once, 'scan_once', side_effect=AssertionError('unverified scan')):
                    original.reject(lambda: once.lookup_batch_once(intent))
                assert len(calls) == 1
                checks.append('real_corrupt_native_refused_without_scan')
            finally:
                path.write_bytes(raw)
            def changed_after_native(self, *params):
                reply = real_native(self, *params)
                path.write_bytes(raw[:-1] + bytes([raw[-1] ^ 1]))
                return reply
            try:
                with patch.object(once.single.checked.RecoveryBackend, '_run', changed_after_native):
                    original.reject(lambda: once.lookup_batch_once(intent))
                checks.append('post_native_mutation_refused')
            finally:
                path.write_bytes(raw)
            real_scan = once.scan_once
            extra = journal / 'one-pass-test-extra'
            def changed_after_scan(*params):
                result = real_scan(*params)
                extra.write_bytes(b'inert-owned-test-only')
                return result
            out, err = io.StringIO(), io.StringIO()
            try:
                with patch.object(once, 'scan_once', changed_after_scan), \
                        contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                    code = once.main(args)
                assert code == 1 and not out.getvalue() and 'One-pass lookup failed.' in err.getvalue()
                checks.append('post_scan_change_no_partial_success')
            finally:
                if extra.exists(): extra.unlink()
        assert original.inventory(journal) == before and original.inventory(directory) == evidence
        groups.append((directory.name, included))
        return report

    with patch.object(original.reconcile, 'recover', side_effect=observe):
        previous.run(wallet, worker, recovery)
    assert groups == [('pending', False), ('empty-result', False), ('included', True), ('expired', False)]
    assert len(checks) == 6
    print(json.dumps(dict(operation='ledger_batch_once_native_test', genuine_history_groups=4,
                          previous_install_recovery_and_batch_suite_completed=True,
                          one_native_one_record_pass=True, checks=checks,
                          input_bytes_preserved=True, real_funds_allowed=False), sort_keys=True))


if __name__ == '__main__':
    if len(sys.argv) != 4:
        raise SystemExit('Original wallet, worker and recovery executables required')
    run(*(Path(value) for value in sys.argv[1:]))
