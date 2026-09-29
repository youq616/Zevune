#!/usr/bin/env python3
"""Real installed Rust verification and batch queries; no accepting test doubles.

Keep the entire previous install/recovery/single-lookup driver unchanged. All
changes below affect only temporary valueless fixtures, and are restored.
"""
import contextlib
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

import check_ledger_transaction_backend as previous
import ledger_transaction_batch as batch


def run(wallet: Path, worker: Path, recovery: Path):
    saved_recover = previous.original.reconcile.recover
    txid = None
    groups, checks = [], []

    def observe(*args, **kwargs):
        nonlocal txid
        report = saved_recover(*args, **kwargs)  # Real recovery returns before observing any result.
        directory, journal = args[1], kwargs['journal']
        if directory.name == 'pending':
            txid = report['txid']
        assert txid is not None
        backend = kwargs['recovery_backend'].binary.path
        values = dict(journal=str(journal), checkpoint=kwargs['checkpoint'], genesis_sha256=kwargs['genesis_sha256'],
                      backend=str(backend), backend_sha256=hashlib.sha256(backend.read_bytes()).hexdigest(),
                      txids=['0' * 64, txid, '1' * 64])
        intent = batch.prepare(values)
        original_files = previous.original.inventory(journal)
        original_evidence = previous.original.inventory(directory)
        real_native = batch.single.checked.RecoveryBackend._run
        real_scan = batch.single.scan_archive
        calls, scan_deadlines = [], []
        def counted_native(self, *params):
            calls.append((params[0][0], params[-1]))
            return real_native(self, *params)
        def counted_scan(*params):
            scan_deadlines.append(params[-1])
            return real_scan(*params)
        with patch.object(batch.single.checked.RecoveryBackend, '_run', counted_native), \
                patch.object(batch.single, 'scan_archive', counted_scan):
            result = batch.lookup_batch(intent)
        assert len(calls) == 1 and calls[0][0] == 'verify-active'
        assert scan_deadlines == [calls[0][1]] * 3
        assert result['batch_complete'] is True and result['native_replay_count'] == 1
        assert result['history_scan_count'] == result['query_count'] == 3
        assert [row['txid'] for row in result['results']] == values['txids']
        included = directory.name == 'included'
        assert [row['historical_inclusion_verified'] for row in result['results']] == [False, included, False]
        assert result['included_count'] == int(included) and result['absent_count'] == 3 - int(included)
        for flag in ('wallet_authenticated', 'recipient_or_amount_verified', 'finality_verified',
                     'retry_authorized', 'portable_proof_generated', 'real_funds_allowed'):
            assert result[flag] is False
        assert result['current_chain_height'] is None
        assert result['broadcast_status'] == result['settlement_status'] == 'unknown'

        if included:
            common = {key: values[key] for key in batch.COMMON_FIELDS}
            for row in result['results']:
                reference = batch.single.lookup(batch.single.prepare(dict(common, txid=row['txid'])))
                assert row == {key: reference[key] for key in row}
            checks.append('each_result_matches_fresh_single_lookup')
            many_values = dict(values, txids=[txid] + [f'{i:064x}' for i in range(31)])
            calls.clear()
            with patch.object(batch.single.checked.RecoveryBackend, '_run', counted_native):
                many = batch.lookup_batch(batch.prepare(many_values))
            assert len(calls) == 1 and many['query_count'] == many['history_scan_count'] == 32
            assert many['included_count'] == 1 and many['absent_count'] == 31
            checks.append('32_queries_one_real_native_replay')
            reversed_values = dict(values, txids=list(reversed(values['txids'])))
            reversed_result = batch.lookup_batch(batch.prepare(reversed_values))
            assert reversed_result['results'] == list(reversed(result['results']))
            checks.append('caller_order_preserved')
            command_args = ['--no-real-funds']
            for key in batch.COMMON_FIELDS:
                command_args.extend(['--' + key.replace('_', '-'), values[key]])
            for value in values['txids']:
                command_args.extend(['--txid', value])
            command = [sys.executable, '-B', str(Path(batch.__file__)), *command_args]
            process = subprocess.run(command, capture_output=True, check=True, timeout=310)
            assert json.loads(process.stdout) == result and not process.stderr
            text = subprocess.run(command + ['--text'], capture_output=True, check=True, timeout=310)
            assert text.stdout.decode('utf-8') == batch.render(result) + '\n' and not text.stderr
            checks.append('real_cli_json_and_utf8_text')

            # A native failure cannot reuse the preceding successful batch.
            segment = journal / '00000000.journal'
            raw = segment.read_bytes()
            calls.clear()
            try:
                segment.write_bytes(raw[:-1] + bytes([raw[-1] ^ 1]))
                with patch.object(batch.single.checked.RecoveryBackend, '_run', counted_native), \
                        patch.object(batch, 'scan_requests', side_effect=AssertionError('unverified scan')):
                    previous.original.reject(lambda: batch.lookup_batch(intent))
                assert len(calls) == 1
                checks.append('real_native_corruption_refusal_no_cached_success')
            finally:
                segment.write_bytes(raw)

            # First scan genuinely completes; a later failure must produce NO prefix JSON.
            for when in ('after_first_scan', 'after_last_scan'):
                scans = []
                extra = journal / 'batch-test-extra'
                def alter(*params):
                    answer = real_scan(*params)
                    scans.append(params[0].txid)
                    if when == 'after_first_scan' and len(scans) == 1:
                        segment.write_bytes(raw[:-1] + bytes([raw[-1] ^ 1]))
                    if when == 'after_last_scan' and len(scans) == 3:
                        extra.write_bytes(b'inert-test-only')
                    return answer
                out, err = io.StringIO(), io.StringIO()
                try:
                    with patch.object(batch.single, 'scan_archive', alter), \
                            contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                        code = batch.main(command_args)
                    assert code == 1 and not out.getvalue() and 'Batch lookup failed.' in err.getvalue()
                    assert len(scans) == (1 if when == 'after_first_scan' else 3)
                    checks.append(when + '_refused_without_partial_output')
                finally:
                    segment.write_bytes(raw)
                    if extra.exists():
                        extra.unlink()
        assert previous.original.inventory(journal) == original_files
        assert previous.original.inventory(directory) == original_evidence
        groups.append((directory.name, included))
        return report

    with patch.object(previous.original.reconcile, 'recover', side_effect=observe):
        previous.run(wallet, worker, recovery)
    assert groups == [('pending', False), ('empty-result', False), ('included', True), ('expired', False)], groups
    assert len(checks) == 7
    print(json.dumps(dict(operation='ledger_transaction_batch_native_test', genuine_history_groups=4,
                          original_install_and_single_suite_completed=True, input_bytes_preserved=True,
                          checks=checks, real_funds_allowed=False), sort_keys=True))


if __name__ == '__main__':
    if len(sys.argv) != 4:
        raise SystemExit('Original wallet, worker and recovery executables required')
    run(*(Path(value) for value in sys.argv[1:]))
