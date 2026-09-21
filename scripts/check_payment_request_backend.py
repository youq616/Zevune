#!/usr/bin/env python3
"""Real offline request signing and durable pending recovery; NO-FUNDS only.

No accepting doubles. Private fixtures never enter argv, env or reports.
"""
from __future__ import annotations
import hashlib
from pathlib import Path
import secrets
import sys
import tempfile
import payment_request as request
from zevune_wallet import encode_request, invoke
from wallet_backup_backend import BackendError


def refused(operation):
    try:
        operation()
    except (OSError, ValueError, RuntimeError):
        return
    raise AssertionError('unsafe request accepted')



def native_refused(operation):
    """Require the real process failure, not a Python precheck or launch error."""
    try:
        operation()
    except BackendError as error:
        assert str(error) == 'backend_operation_failed_reconcile_files'
        return
    raise AssertionError('native network mismatch was not rejected')


class ObservedPrepare(request.RequestBackend):
    """Test-only observation: every call delegates to the unchanged real backend."""
    def __init__(self, binary, digest):
        super().__init__(binary, digest)
        self.attempts = 0

    def prepare(self, password, paths, pin):
        self.attempts += 1
        return super().prepare(password, paths, pin)


def network_refusals(root, binary, backend_sha, password, call, wallet, pool, genesis,
                     domain, pin, recipient):
    # Generate and authenticate a second REAL LAB2 network, not a synthetic
    # manifest or checksum-relabelled receiver. Both networks remain unmodified.
    other_wallet, other_pool, other_genesis = (root / name for name in
                                             ('other.wallet', 'other-pool', 'other-genesis'))
    call(0, [other_wallet])
    other = call(7, [other_wallet, other_pool, other_genesis])
    other_domain = other['genesis_sha256']
    assert other['payment_profile'] == 'LAB2' and other_domain != domain
    assert hashlib.sha256(other_genesis.read_bytes()).hexdigest() == other_domain
    other_request = root / 'other-network.zvrequest'
    other_sha = request.create_request(other_request, other_genesis, other_domain,
                                       other['address'], '25000', '10')['request_sha256']
    request.inspect_request(other_request, other_sha, other_genesis, other_domain)
    baseline = {p.name: p.read_bytes() for p in root.iterdir() if p.is_file()}
    members = {p.name for p in root.iterdir()}

    def unchanged():
        assert {p.name for p in root.iterdir()} == members, 'network refusal created output'
        assert {p.name: p.read_bytes() for p in root.iterdir() if p.is_file()} == baseline, 'network refusal changed bytes'
        assert call(9, [wallet], pin)['receipt'] == pin
        assert call(9, [other_wallet], other['receipt'])['receipt'] == other['receipt']
        assert {p.name: p.read_bytes() for p in root.iterdir() if p.is_file()} == baseline

    observed = ObservedPrepare(binary, backend_sha)
    # These two calls deliberately bypass the Python network precheck, so only
    # the native genesis/recipient checks can reject them. All other fields are
    # those used by the positive signing control immediately after these cases.
    for label, selected_domain, selected_recipient in (
            ('wrong-genesis-pin', other_domain, recipient),
            ('wrong-recipient-domain', domain, other['address'])):
        output = root / (label + '.tx')
        native_refused(lambda: observed.prepare(password,
            [str(wallet), str(pool), str(genesis), selected_domain, selected_recipient,
             '25000', '1000', '10', str(output)], pin))
        unchanged()
    assert observed.attempts == 2
    # A coherent foreign request and genesis pass the Python checks; using the
    # original ledger MUST actually reach op4 and be refused by the real Rust
    # backend. An early Python error cannot satisfy native_refused().
    native_refused(lambda: request.prepare_request(other_request, other_sha,
        other_genesis, other_domain, wallet, pin, pool, root / 'wrong-ledger.tx',
        '1000', password, observed))
    assert observed.attempts == 3
    unchanged()


def run(binary: Path):
    binary = binary.absolute()
    backend_sha = hashlib.sha256(binary.read_bytes()).hexdigest()
    backend = request.RequestBackend(binary, backend_sha)
    password = secrets.token_bytes(32)
    with tempfile.TemporaryDirectory(prefix='zevune-request-interop-') as temporary:
        root = Path(temporary).resolve()
        wallet, peer, pool, genesis = (root / name for name in ('source.wallet', 'peer.wallet', 'pool', 'genesis'))
        def call(op, paths, pin=None):
            return invoke(binary, encode_request(op, password, [str(p) for p in paths], pin), backend_sha)
        first = call(0, [wallet])['receipt']
        initialized = call(7, [wallet, pool, genesis])
        domain, pin = initialized['genesis_sha256'], initialized['receipt']
        assert initialized['payment_profile'] == 'LAB2' and int(pin[64:80], 16) == 2
        call(0, [peer])
        recipient = call(8, [peer, pool, genesis, domain, '0'])['address']
        source_before, pool_before, genesis_before = wallet.read_bytes(), pool.read_bytes(), genesis.read_bytes()
        filename = root / 'request.zvrequest'
        request_sha = request.create_request(filename, genesis, domain, recipient, '25000', '10')['request_sha256']
        request_bytes = filename.read_bytes()
        inspected = request.inspect_request(filename, request_sha, genesis, domain)
        assert not inspected['authenticated'] and not inspected['single_use_enforced']
        assert wallet.read_bytes() == source_before and pool.read_bytes() == pool_before
        output = root / 'payment.tx'
        def prepare(*, req_sha=request_sha, wallet_pin=pin, fee='1000', pw=password, target=output):
            return request.prepare_request(filename, req_sha, genesis, domain, wallet, wallet_pin,
                                           pool, target, fee, pw, backend)
        for operation in (lambda: prepare(req_sha='0' * 64), lambda: prepare(wallet_pin=first),
                          lambda: prepare(fee=str(1 << 63)), lambda: prepare(pw=secrets.token_bytes(32))):
            refused(operation)
            assert wallet.read_bytes() == source_before and pool.read_bytes() == pool_before
            assert filename.read_bytes() == request_bytes and not output.exists()
        network_refusals(root, binary, backend_sha, password, call, wallet, pool,
                         genesis, domain, pin, recipient)
        # A test-only clone created before signing is never broadcast or funded
        # independently; it exercises a discarded genuine successful response.
        copy = root / 'lost-response.wallet'
        call(2, [wallet, copy], pin)
        result = prepare()
        final_pin = result['receipt']
        assert result['result'] == 'request_prepared_not_broadcast' and result['broadcast'] is False
        assert int(final_pin[64:80], 16) == 3
        signed, saved = output.read_bytes(), wallet.read_bytes()
        assert hashlib.sha256(signed).hexdigest() == result['txid']
        pending_file = root / 'pending.tx'
        pending = call(5, [wallet, pool, genesis, domain, pending_file], final_pin)
        assert pending_file.read_bytes() == signed and pending['txid'] == result['txid']
        status = call(3, [wallet, pool, genesis, domain], final_pin)
        assert status['pending'] is True and status['available'] == 0 and status['balance'] == 100000
        assert wallet.read_bytes() == saved
        refused(lambda: prepare(wallet_pin=final_pin, target=root / 'no-second-payment'))
        assert not (root / 'no-second-payment').exists() and wallet.read_bytes() == saved
        assert pool.read_bytes() == pool_before and genesis.read_bytes() == genesis_before
        assert filename.read_bytes() == request_bytes

        class LostReply(request.RequestBackend):
            def prepare(self, password, paths, pin):
                super().prepare(password, paths, pin)  # actual native persisted signature
                raise RuntimeError('test-only discarded successful application response')
        lost_output = root / 'lost-output.tx'
        refused(lambda: request.prepare_request(filename, request_sha, genesis, domain, copy, pin,
                                                pool, lost_output, '1000', password, LostReply(binary, backend_sha)))
        assert lost_output.is_file() and copy.read_bytes() != source_before
        # Original pending recovery accepts the old independent receipt as a
        # lower bound; never prepare again after the uncertain result.
        recovered_file = root / 'lost-pending.tx'
        recovered = call(5, [copy, pool, genesis, domain, recovered_file], pin)
        assert recovered_file.read_bytes() == lost_output.read_bytes()
        assert recovered['txid'] == hashlib.sha256(lost_output.read_bytes()).hexdigest()
        status = call(3, [copy, pool, genesis, domain], recovered['receipt'])
        assert status['pending'] is True and status['available'] == 0
        assert pool.read_bytes() == pool_before and filename.read_bytes() == request_bytes
    print('Payment request real-backend lifecycle passed: explicit signing, three real native network refusals, safe refusals, exact durable pending recovery and discarded-response reconciliation. No broadcast or retained private fixtures.')


if __name__ == '__main__':
    if len(sys.argv) != 2:
        raise SystemExit('Exactly one trusted native wallet executable is required')
    run(Path(sys.argv[1]))
