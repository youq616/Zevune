"""Explicit submission of an ALREADY saved pending payment; NO REAL FUNDS.

Internal library for zevune_wallet, not another CLI, signer or verifier. The
caller passes the actual console module so __main__ and imported use share the
same pinned backends. Do not replace these with an accepting verifier in runtime.
"""
import argparse
import json
from pathlib import Path
import sys
import tempfile


class SubmissionUnknown(RuntimeError):
    """The one submission may have reached its peer. Reconcile; never retry here."""


def checked_submission(raw, txid, initial_height, maximum, api):
    """Wire validation ONLY; the original Go verifier performs authorization."""
    api._sync_hash(txid)
    value = api._sync_json(raw, 4096)
    if (set(value) != {'status', 'txid', 'reference_height', 'confirmed', 'base_checkpoint_matched'}
            or value['status'] != 'accepted_to_mempool_not_confirmed'
            or value['txid'] != txid or value['confirmed'] is not False
            or value['base_checkpoint_matched'] is not True
            or type(value['reference_height']) is not int
            or not initial_height <= value['reference_height'] <= maximum):
        raise ValueError('Unexpected non-confirming submission receipt')
    return value


def submit_pending_network(args, api):
    """Authenticate -> recover once -> submit the same bytes once. No wallet write.

    There is intentionally no durable broadcast flag in this stage. A new human
    invocation may submit the same bytes again; this is not global exactly-once.
    """
    options = vars(args).copy()
    if any(k in options for k in ('output', 'expected_height', 'expected_app_hash', 'tx', 'tx_sha256')):
        raise ValueError('Submission takes no caller transaction or checkpoint')
    api.checked_preparation_checkpoint('0', options['genesis_sha256'], options['pin'])
    o, network, identity, unchanged, maximum = api._verified_network_reference(
        argparse.Namespace(**options))
    if not network['caught_up_to_observed_tip']:
        raise ValueError('Reference catchup incomplete; pending was not submitted')
    height, app_hash = str(network['height']), network['app_hash']
    parent = o['wallet'].parent
    if parent.resolve(strict=True) != parent or not parent.is_dir():
        raise ValueError('Submission scratch parent must be a trusted canonical directory')
    print('Pinned submission network: ' + json.dumps(identity, sort_keys=True)
          + '; submitting existing pending only. Mempool acceptance is NOT confirmation.', file=sys.stderr)
    if input('Type SUBMIT to send the SAME saved pending once; reconcile any prior unknown result first: ') != 'SUBMIT':
        raise ValueError('Submission not approved')
    unchanged()
    # Private sibling, never in wallet/reference input trees; no secret file.
    # After abnormal process termination a public signed payload may remain.
    # No claim of secure erasure or physical directory durability is made.
    with tempfile.TemporaryDirectory(prefix='.zevune-submit-', dir=parent,
                                     ignore_cleanup_errors=True) as directory:
        target = Path(directory) / 'pending.tx'
        paths = dict(o, output=target)
        output_parent = api._prepare_network_output(paths)
        fields = [str(o['wallet']), str(o['journal']), str(o['genesis']), o['genesis_sha256'],
                  str(target), height, app_hash]
        api.encode_request(13, bytes(16), fields, o['pin'])
        password = api.hidden_password(False)
        unchanged()
        if api._prepare_network_output(paths) != output_parent:
            raise ValueError('Submission scratch parent changed')
        recovered = api.invoke(o['backend'], api.encode_request(13, password, fields, o['pin']),
                               o['backend_sha256'])
        api.checked_checkpoint_recovery(recovered, height, app_hash, o['pin'])
        if any(recovered[k] != v for k, v in identity.items()):
            raise ValueError('Recovered payment identity differs')
        txid = recovered['txid']
        # This checks the actual recovered file and its identity; it is not proof
        # verification. The Go command independently hashes its own same raw bytes
        # before worker/RPC start and still performs the original Check.
        file_identity = api._sync_pinned_file(target, txid, 28134)
        unchanged()
        if api._sync_pinned_file(target, txid, 28134) != file_identity:
            raise ValueError('Recovered transaction changed before submission')
        command = [str(o['network_backend']), 'submit', '--no-real-funds',
                   '--worker', str(o['worker']), '--worker-sha256', o['worker_sha256'],
                   '--config', str(o['config']), '--config-sha256', o['config_sha256'],
                   '--endpoint', o['endpoint'], '--journal', str(o['journal']), '--limit', o['limit'],
                   '--expected-height', height, '--expected-app-hash', app_hash,
                   '--tx', str(target), '--tx-sha256', txid]
        if o['socks_proxy'] is not None:
            command += ['--socks-proxy', o['socks_proxy']]
        try:
            # NEVER loop/recover/re-sign here. Nonzero exit may follow broadcast.
            # The inherited helper joins the original bounded child; stdout and
            # stderr spools contain only bounded-program PUBLIC diagnostics.
            result = checked_submission(api._sync_network_process(command), txid,
                                        network['height'], maximum, api)
            unchanged()
            if api._sync_pinned_file(target, txid, 28134) != file_identity:
                raise ValueError('Submission source changed')
        except (Exception, KeyboardInterrupt) as error:
            raise SubmissionUnknown('Submission outcome unknown; preserve pending and reconcile') from error
    return {'result': 'pending_accepted_to_mempool_not_confirmed',
            'scope': 'fixed_validator_pending_submission_no_funds',
            'config_sha256': o['config_sha256'], 'txid': txid,
            'receipt': recovered['receipt'], 'network': network, 'submission': result,
            'wallet_unchanged': True, 'confirmed': False, 'retry_authorized': False,
            'real_funds_allowed': False}
