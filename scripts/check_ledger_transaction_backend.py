#!/usr/bin/env python3
"""Historical inclusion against genuine original-Rust recovery fixtures, NO-FUNDS.

No accepting verifier substitutes. The original ten recovery scenarios remain
unchanged. Mutations below affect only this driver's temporary public fixtures.
"""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

import check_wallet_reconcile_backend as original
import ledger_transaction_lookup as lookup


def run(wallet: Path, worker: Path, recovery: Path):
    recovery = recovery.resolve(strict=True)
    backend_digest = hashlib.sha256(recovery.read_bytes()).hexdigest()
    saved_recover = original.reconcile.recover
    txid = None
    groups, checks = [], []

    def observe(*args, **kwargs):
        nonlocal txid
        report = saved_recover(*args, **kwargs)  # Real recovery: never return a forged successful response.
        directory, journal = args[1], kwargs['journal']
        if directory.name == 'pending':
            txid = report['txid']
        assert txid is not None
        values = dict(journal=str(journal), checkpoint=kwargs['checkpoint'], genesis_sha256=kwargs['genesis_sha256'],
                      txid=txid, backend=str(recovery), backend_sha256=backend_digest)
        intent = lookup.prepare(values)
        before = original.inventory(journal)
        evidence = original.inventory(directory)
        result = lookup.lookup(intent)
        included = directory.name == 'included'
        assert result['historical_inclusion_verified'] is included
        assert result['ledger_replayed'] is True and result['historical_search_complete'] is True
        assert result['txid'] == txid and result['checkpoint'] == values['checkpoint']
        assert result['settlement_status'] == result['broadcast_status'] == 'unknown'
        assert result['current_chain_height'] is None
        for field in ('wallet_authenticated', 'recipient_or_amount_verified', 'finality_verified',
                      'retry_authorized', 'portable_proof_generated', 'real_funds_allowed'):
            assert result[field] is False
        if included:
            assert result['occurrence']['height'] == 1 and result['occurrence']['transaction_index'] == 0
            assert result['occurrence']['segment'] == '00000000.journal' and result['occurrence']['record_offset'] == 0
            assert result['subsequent_record_count'] == 0 and result['scanned_transactions'] == 1
            command = [sys.executable, '-B', str(Path(lookup.__file__)), '--no-real-funds']
            for key, value in values.items():
                command += ['--' + key.replace('_', '-'), value]
            process = subprocess.run(command, capture_output=True, check=True, timeout=310)
            assert json.loads(process.stdout) == result and not process.stderr
            text = subprocess.run(command + ['--text'], capture_output=True, check=True, timeout=310)
            assert text.stdout.decode('utf-8') == lookup.render(result) + '\n'
            checks.append('real_cli_json_and_text')
            absent = lookup.lookup(lookup.prepare(dict(values, txid='0' * 64)))
            assert absent['state'] == 'absent_from_verified_history' and absent['occurrence'] is None
            checks.append('other_txid_absent_after_real_replay')

            # Damaged segment reaches the real native verifier and must fail.
            path = journal / '00000000.journal'
            raw = path.read_bytes()
            real_run = lookup.checked.RecoveryBackend._run
            calls = []
            def reached(self, *params):
                calls.append(1)
                return real_run(self, *params)
            try:
                path.write_bytes(raw[:-1] + bytes([raw[-1] ^ 1]))
                with patch.object(lookup.checked.RecoveryBackend, '_run', reached):
                    original.reject(lambda: lookup.lookup(intent))
                assert calls == [1]
                checks.append('damaged_ledger_rejected_by_real_native')
            finally:
                path.write_bytes(raw)

            # A valid replay response is not reusable permission to scan changed bytes.
            calls.clear()
            def altered_after_real_replay(self, *params):
                reply = real_run(self, *params)
                calls.append(1)
                path.write_bytes(raw[:-1] + bytes([raw[-1] ^ 1]))
                return reply
            try:
                with patch.object(lookup.checked.RecoveryBackend, '_run', altered_after_real_replay):
                    original.reject(lambda: lookup.lookup(intent))
                assert calls == [1]
                checks.append('post_replay_mutation_rejected')
            finally:
                path.write_bytes(raw)

            # Mutate after the entire real scan to test the final freshness checks.
            saved_scan = lookup.scan_archive
            extra = journal / 'unexpected'
            def changed_after_scan(*params):
                answer = saved_scan(*params)
                extra.write_bytes(b'inert-test-only')
                return answer
            try:
                with patch.object(lookup, 'scan_archive', changed_after_scan):
                    original.reject(lambda: lookup.lookup(intent))
                checks.append('post_scan_inventory_change_rejected')
            finally:
                if extra.exists():
                    extra.unlink()
        else:
            assert result['occurrence'] is None and result['subsequent_record_count'] is None
        assert original.inventory(journal) == before and original.inventory(directory) == evidence
        groups.append((directory.name, included))
        return report

    with patch.object(original.reconcile, 'recover', side_effect=observe):
        original.run(wallet, worker, recovery)
    assert groups == [('pending', False), ('empty-result', False), ('included', True), ('expired', False)], groups
    assert len(checks) == 5
    print(json.dumps(dict(operation='ledger_transaction_lookup_native_test', genuine_history_groups=4,
                          original_recovery_driver_completed=True, input_bytes_preserved=True,
                          checks=checks, real_funds_allowed=False), sort_keys=True))


if __name__ == '__main__':
    if len(sys.argv) != 4:
        raise SystemExit('Original wallet, worker and recovery executables required')
    run(*(Path(value) for value in sys.argv[1:]))
