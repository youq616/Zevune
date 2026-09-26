#!/usr/bin/env python3
"""Real original-Rust recovery and fresh replay; no successful verifier doubles.

All mutation is limited to this driver's own temporary, valueless test inputs.
The original recovery driver and its ten native scenarios run without edits.
"""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
from unittest.mock import patch

import check_wallet_reconcile_backend as original
import reconciliation_ledger_check as checker


def run(wallet: Path, worker: Path, recovery: Path):
    recovery = recovery.resolve(strict=True)
    digest = hashlib.sha256(recovery.read_bytes()).hexdigest()
    original_recover = original.reconcile.recover
    observed = []
    mutation_checks = []

    def observe(*args, **kwargs):
        report = original_recover(*args, **kwargs)  # Real auth/recovery; a failure stays a failure.
        output, journal = args[1], kwargs['journal']
        values = dict(directory=str(output), report_sha256=report['report_sha256'],
                      checkpoint=kwargs['checkpoint'], genesis_sha256=kwargs['genesis_sha256'],
                      journal=str(journal), backend=str(recovery), backend_sha256=digest)
        intent = checker.prepare(values)
        before, ledger_before = original.inventory(output), original.inventory(journal)
        result = checker.check(intent)  # Always invokes the original native verifier.
        assert result['ledger_replayed'] is True and result['checkpoint_domain_relation_verified'] is True
        assert result['checkpoint'] == report['checkpoint'] and result['genesis_sha256'] == report['genesis_sha256']
        assert result['txid'] == report['txid'] and result['settlement_status'] == 'unknown'
        for name in ('wallet_authenticated','transaction_authorization_verified','finality_verified',
                     'retry_authorized','genesis_manifest_validated','pending_transaction_inclusion_verified',
                     'original_recovery_success_verified','real_funds_allowed'):
            assert result[name] is False, name
        assert checker.view.inspect(intent.evidence).summary()['ledger_replayed'] is False
        assert original.inventory(output) == before and original.inventory(journal) == ledger_before
        if output.name == 'pending':
            command = [sys.executable, '-B', str(Path(checker.__file__)), '--no-real-funds']
            for name,value in values.items():command.extend(['--'+name.replace('_','-'),value])
            response = subprocess.run(command, capture_output=True, check=True, timeout=310)
            assert json.loads(response.stdout) == result and not response.stderr
            original.reject(lambda: checker.check(checker.prepare(dict(values, backend_sha256='0'*64))))

        if output.name == 'included':
            # The original backend MUST actually replay this damaged real ledger
            # and reject it. Do not alter a trusted checkpoint to bless damage.
            segment = journal / '00000000.journal'
            raw = segment.read_bytes()
            try:
                segment.write_bytes(raw[:-1]+bytes([raw[-1]^1]))
                calls=[]
                native_run=checker.RecoveryBackend._run
                def actual(self,*params):
                    calls.append(1)
                    return native_run(self,*params)
                with patch.object(checker.RecoveryBackend,'_run',actual):
                    original.reject(lambda: checker.check(intent))
                assert calls == [1], 'damage refusal did not reach the real native verifier'
                mutation_checks.append('real_corrupt_ledger_rejected_by_native')
            finally:
                segment.write_bytes(raw)

            # Refuse input mutations AFTER a real successful native call. There
            # is no accepting stub: original_run must complete first each time.
            for target, label in ((output/'pending.tx','post_native_extra_evidence'),
                                  (journal/'genesis','post_native_changed_header')):
                existed=target.exists(); old=target.read_bytes() if existed else None
                native_run=checker.RecoveryBackend._run
                calls=[]
                def change_after_native(self,*params):
                    response=native_run(self,*params)
                    calls.append(1)
                    if existed:
                        target.write_bytes(old[:-1]+bytes([old[-1]^1]))
                    else:
                        target.write_bytes(b'inert-test-only')
                    return response
                try:
                    with patch.object(checker.RecoveryBackend,'_run',change_after_native):
                        original.reject(lambda: checker.check(intent))
                    assert calls == [1]
                    mutation_checks.append(label)
                finally:
                    if existed:target.write_bytes(old)
                    else:target.unlink()
        assert original.inventory(output) == before and original.inventory(journal) == ledger_before
        observed.append((output.name, report['pending']))
        return report

    began=time.monotonic()
    with patch.object(original.reconcile,'recover',side_effect=observe):
        original.run(wallet,worker,recovery)
    assert observed == [('pending',True),('empty-result',False),('included',False),('expired',False)], observed
    assert len(mutation_checks)==3
    print(json.dumps(dict(operation='reconciliation_ledger_native_test', genuine_recovery_groups=4,
                          genuine_ledger_replay=True, real_cli_completed=True, input_bytes_preserved=True,
                          mutation_checks=mutation_checks, original_driver_completed=True,
                          elapsed_seconds=round(time.monotonic()-began,3), real_funds_allowed=False),sort_keys=True))


if __name__=='__main__':
    if len(sys.argv)!=4:raise SystemExit('Original wallet, worker and recovery paths required')
    run(*(Path(value) for value in sys.argv[1:]))
