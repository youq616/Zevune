#!/usr/bin/env python3
"""Historical inclusion against genuine original-Rust recovery fixtures, NO-FUNDS.

No accepting verifier substitutes. The original ten recovery scenarios remain
unchanged. Mutations below affect only this driver's temporary public fixtures.
"""
import hashlib
import os
import json
from pathlib import Path
import subprocess
import shutil
import sys
import tempfile
from unittest.mock import patch

import check_wallet_reconcile_backend as original
import ledger_transaction_lookup as lookup
import native_backend_install as installer


def _run(wallet: Path, worker: Path, recovery: Path):
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


            # A real original executable with a second path must be rejected,
            # even though every executable byte and its approved digest match.
            copied = directory.parent / ('lookup-recovery' + recovery.suffix)
            alias = directory.parent / 'lookup-recovery-alias'
            shutil.copy2(recovery, copied)
            try:
                os.link(copied, alias)
                assert copied.stat().st_nlink == 2
                with patch.object(subprocess, 'Popen', side_effect=AssertionError('linked backend executed')) as spawn:
                    original.reject(lambda: lookup.lookup(lookup.prepare(dict(values, backend=str(copied)))))
                assert spawn.call_count == 0
                checks.append('hardlinked_original_backend_refused_before_process')
            finally:
                if alias.exists():
                    alias.unlink()
                copied.unlink()

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
    assert len(checks) == 6
    print(json.dumps(dict(operation='ledger_transaction_lookup_native_test', genuine_history_groups=4,
                          original_recovery_driver_completed=True, input_bytes_preserved=True,
                          checks=checks, real_funds_allowed=False), sort_keys=True))


def run(wallet: Path, worker: Path, recovery: Path):
    # Build artifacts may share an inode with the build cache. Exercise the real
    # installer CLI; never weaken the lookup's independent single-link gate.
    recovery = recovery.resolve(strict=True)
    digest = hashlib.sha256(recovery.read_bytes()).hexdigest()
    source_identity = lookup.metadata_identity(recovery.lstat())
    with tempfile.TemporaryDirectory(prefix='zevune-native-install-integration-') as temp:
        workspace = Path(temp).resolve()
        approved = workspace / ('zevune-pool-recovery' + recovery.suffix)
        command = [sys.executable, '-B', str(Path(installer.__file__)), '--no-real-funds', 'install',
                   '--source', str(recovery), '--destination', str(approved), '--backend-sha256', digest]
        installed = subprocess.run(command, capture_output=True, check=True, timeout=310)
        reply = json.loads(installed.stdout)
        assert reply['installed'] is True and reply['source_unchanged'] is True and not installed.stderr
        assert reply['backend_sha256'] == digest and reply['source_link_count'] == recovery.stat().st_nlink
        assert reply['executable_started'] is False and reply['protocol_verified'] is False
        assert approved.stat().st_nlink == 1 and not os.path.samefile(approved, recovery)
        assert installer.verify(approved, digest)['single_link_verified'] is True
        lookup.SingleLinkBackend(approved, digest)._check()
        _run(wallet, worker, approved)  # Entire original native scenario set, now with independent bytes.
        assert installer.verify(approved, digest)['integrity_verified'] is True
        assert lookup.metadata_identity(recovery.lstat()) == source_identity
        assert hashlib.sha256(recovery.read_bytes()).hexdigest() == digest
    assert not workspace.exists()
    print(json.dumps(dict(operation='native_backend_install_integration', real_cli_installed=True,
                          installed_backend_executed_by_test_driver=True, installer_executed_backend=False,
                          source_link_count=source_identity[4], source_unchanged=True,
                          fixtures_removed=True, real_funds_allowed=False), sort_keys=True))


if __name__ == '__main__':
    if len(sys.argv) != 4:
        raise SystemExit('Original wallet, worker and recovery executables required')
    run(*(Path(value) for value in sys.argv[1:]))
