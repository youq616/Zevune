"""No accepting verifier double: schemas are pure; processes only refuse/fail.
The successful crypto/network/wallet composition is in the native E2E.
"""
import argparse
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import zevune_wallet as w


def raw(value):
    return json.dumps(value).encode()


def receipt():
    return '11' * 32 + (1).to_bytes(8, 'big').hex() + '22' * 32


def status():
    return dict(scope='fixed_validator_local_test_network', height=3, app_hash='33' * 32,
                root='44' * 32, new_blocks=3, observed_signed_tip=4,
                caught_up_to_observed_tip=True, real_funds_allowed=False,
                base_checkpoint_matched=False)


class SchemaTests(unittest.TestCase):
    def check(self, v):
        return w.checked_network_sync(raw(v), limit=128, maximum=10000, create=True)

    def test_full_result_and_partial_progress_are_distinct(self):
        v = status()
        self.assertEqual(self.check(v), v)
        v.update(height=128, new_blocks=128, observed_signed_tip=200,
                 caught_up_to_observed_tip=False)
        self.assertFalse(self.check(v)['caught_up_to_observed_tip'])

    def test_every_field_required_unknown_fields_not_ignored(self):
        for key in status():
            with self.subTest(key=key):
                v = status(); del v[key]
                with self.assertRaises(ValueError): self.check(v)
        v = status(); v['confirmed'] = True
        with self.assertRaises(ValueError): self.check(v)

    def test_counters_do_not_accept_boolean_float_string_negative(self):
        for key in ('height', 'new_blocks', 'observed_signed_tip'):
            for bad in (True, False, 3.0, '3', -1, 2 ** 65, None):
                with self.subTest(key=key, bad=bad):
                    v = status(); v[key] = bad
                    with self.assertRaises(ValueError): self.check(v)

    def test_scope_false_flags_and_caught_up_are_exact(self):
        for key, bads in {'scope': ['local_journal_only_no_funds', None],
                          'real_funds_allowed': [True, 0, None],
                          'base_checkpoint_matched': [True, 0, None],
                          'caught_up_to_observed_tip': [False, 1, 'true']}.items():
            for bad in bads:
                v = status(); v[key] = bad
                with self.subTest(key=key, bad=bad), self.assertRaises(ValueError): self.check(v)

    def test_tip_height_limit_and_create_relations(self):
        for change in ({'height': 0}, {'height': 4}, {'observed_signed_tip': 10001},
                       {'new_blocks': 129}, {'new_blocks': 2}):
            v = status(); v.update(change)
            with self.assertRaises(ValueError): self.check(v)
        v = status(); v['new_blocks'] = 0
        self.assertEqual(w.checked_network_sync(raw(v), limit=1, maximum=10000, create=False), v)

    def test_zero_noncanonical_wrong_type_hashes_fail(self):
        for key in ('app_hash', 'root'):
            for bad in ('0' * 64, 'A' * 64, 'aa', 1, None, ' ab' * 22):
                v = status(); v[key] = bad
                with self.subTest(key=key, bad=bad), self.assertRaises(ValueError): self.check(v)

    def test_duplicate_trailing_nonfinite_and_deep_json_fail(self):
        encoded = raw(status())
        for bad in (b'', b'[]', encoded + b'{}', b'\xff', b'\xef\xbb\xbf' + encoded,
                    encoded[:-1] + b',"height":3}', b'{"x":NaN}', b'{"x":3.1}',
                    b'{"x":' + b'[' * 1100 + b'0' + b']' * 1100 + b'}', b' ' * 4097):
            with self.subTest(size=len(bad)), self.assertRaises(ValueError):
                w.checked_network_sync(bad, limit=128, maximum=10000, create=True)

    def test_shorthand_caught_up_is_not_the_original_wire_field(self):
        value = status()
        value['caught_up'] = value.pop('caught_up_to_observed_tip')
        with self.assertRaises(ValueError):
            self.check(value)

    def test_old_opcodes_are_unchanged(self):
        self.assertEqual(list(w.OPS.values()), list(range(12)))
        self.assertNotIn('sync-network', w.OPS)  # composition, not a new Rust opcode


class BoundaryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        # Public parser fixture, never submitted as an Orchard authorization.
        genesis = (b'ZVTGEN02' + hashlib.sha256(b'zevune-orchard-lab-1').digest()
                   + (100000).to_bytes(8, 'big') + (1).to_bytes(2, 'big') + b'\x55' * 32
                   + b'\x66' * 43 + (100000).to_bytes(8, 'big') + b'\x77' * 64)
        self.g = self.root / 'genesis'; self.g.write_bytes(genesis)
        self.sha = hashlib.sha256(genesis).hexdigest()
        self.c = self.root / 'config'
        self.conf = dict(version=1, chain_id='zevune-orchard-lab-1', asset_genesis_sha256=self.sha,
                         consensus_genesis_sha256='11' * 32, node_ids=['11' * 20] * 4)
        self.c.write_bytes(raw(self.conf))
        self.binary = self.root / 'not-an-executable'; self.binary.write_bytes(b'not code')
        self.bsha = hashlib.sha256(self.binary.read_bytes()).hexdigest()
        self.args = argparse.Namespace(no_real_funds=True, backend=self.binary, backend_sha256=self.bsha,
              network_backend=self.binary, network_backend_sha256=self.bsha, worker=self.binary,
              worker_sha256=self.bsha, config=self.c, config_sha256=hashlib.sha256(self.c.read_bytes()).hexdigest(),
              genesis=self.g, genesis_sha256=self.sha, wallet=self.root/'wallet', journal=self.root/'reference',
              pin=receipt(), endpoint='http://127.0.0.1:26657', socks_proxy=None, create_reference=True, limit='128')

    def reject_before_network(self, a):
        with patch.object(w, '_sync_network_process', side_effect=AssertionError('must not execute')) as process, \
             patch.object(w, 'hidden_password', side_effect=AssertionError('must not prompt')) as password, \
             patch.object(w, 'invoke', side_effect=AssertionError('must not open wallet')) as wallet:
            with self.assertRaises((ValueError, OSError, RuntimeError)):
                w.sync_network(a)
            process.assert_not_called(); password.assert_not_called(); wallet.assert_not_called()

    def test_all_digest_inputs_checked_before_io_or_secrets(self):
        for field in ('backend_sha256', 'network_backend_sha256', 'worker_sha256', 'config_sha256', 'genesis_sha256'):
            for value in (None, '', '0' * 64, 'A' * 64):
                a = copy.copy(self.args); setattr(a, field, value)
                with self.subTest(field=field, value=value): self.reject_before_network(a)

    def test_mismatched_config_asset_cannot_use_wallet_genesis(self):
        self.conf['asset_genesis_sha256'] = '11' * 32; self.c.write_bytes(raw(self.conf))
        self.args.config_sha256 = hashlib.sha256(self.c.read_bytes()).hexdigest()
        self.reject_before_network(self.args)

    def test_forged_config_or_genesis_pin_fails_before_process(self):
        self.c.write_bytes(self.c.read_bytes() + b' ')
        self.reject_before_network(self.args)
        self.c.write_bytes(raw(self.conf)); self.g.write_bytes(b'bad')
        self.reject_before_network(self.args)

    def test_unsupported_profile_and_boolean_config_version(self):
        for value in (True, 2, 0, '1'):
            self.conf['version'] = value; self.c.write_bytes(raw(self.conf))
            self.args.config_sha256 = hashlib.sha256(self.c.read_bytes()).hexdigest()
            self.reject_before_network(self.args)

    def test_limits_route_receipt_paths_and_funds_before_process(self):
        fields = {'limit': ('0', '129', '01', 1, ''), 'socks_proxy': ('', 'localhost:9050\n'),
                  'pin': (None, '', '0' * 144), 'no_real_funds': (False, 1),
                  'create_reference': (1,), 'endpoint': ('', 'x\n'),
                  'journal': (Path('relative'), self.root/'..'/'escape', self.root),
                  'wallet': (self.root/'reference'/'inside', self.root/'reference')}
        for key, values in fields.items():
            for value in values:
                a = copy.copy(self.args); setattr(a, key, value)
                with self.subTest(key=key, value=value): self.reject_before_network(a)

    def test_network_failure_never_asks_for_password_or_calls_wallet(self):
        with patch.object(w, '_sync_network_process', side_effect=RuntimeError('failed')) as process, \
             patch.object(w, 'hidden_password', side_effect=AssertionError('secret')) as password, \
             patch.object(w, 'invoke', side_effect=AssertionError('wallet')) as wallet:
            with self.assertRaises(RuntimeError): w.sync_network(self.args)
            self.assertEqual(process.call_count, 1)
            command = process.call_args.args[0]
            self.assertNotIn(str(self.args.wallet), command); self.assertNotIn(self.args.pin, command)
            self.assertEqual(command[1], 'sync'); self.assertNotIn('submit', command)
            password.assert_not_called(); wallet.assert_not_called()

    def test_explicit_private_route_is_preserved_and_not_retried(self):
        self.args.socks_proxy='127.0.0.1:9050'; self.args.endpoint='http://' + 'a'*56 + '.onion:80'
        with patch.object(w, '_sync_network_process', side_effect=RuntimeError('refused')) as process:
            with self.assertRaises(RuntimeError): w.sync_network(self.args)
            self.assertEqual(process.call_count, 1)
            self.assertIn(self.args.socks_proxy, process.call_args.args[0])
            self.assertIn(self.args.endpoint, process.call_args.args[0])

    def test_pin_reader_regular_size_digest_identity_and_links(self):
        self.assertEqual(w._sync_pinned_file(self.c, self.args.config_sha256, 16384, contents=True)[0], self.c.read_bytes())
        for p, pin, limit in ((self.c, '11'*32, 16384), (self.c, self.args.config_sha256, 1),
                               (self.root, '11'*32, 16384)):
            with self.assertRaises((ValueError, OSError)): w._sync_pinned_file(p, pin, limit)
        if os.name != 'nt':
            link=self.root/'link'; link.symlink_to(self.c)
            with self.assertRaises(ValueError): w._sync_pinned_file(link, self.args.config_sha256, 16384)

    def cli_args(self):
        a = self.args
        return ['--no-real-funds', '--backend', str(a.backend), '--backend-sha256', a.backend_sha256,
                '--pin', a.pin, 'sync-network', str(a.wallet), '--journal', str(a.journal),
                '--genesis', str(a.genesis), '--genesis-sha256', a.genesis_sha256,
                '--config', str(a.config), '--config-sha256', a.config_sha256,
                '--network-backend', str(a.network_backend), '--network-backend-sha256', a.network_backend_sha256,
                '--worker', str(a.worker), '--worker-sha256', a.worker_sha256,
                '--endpoint', a.endpoint, '--create-reference']

    def test_real_cli_dispatch_reaches_original_verifier_only_once(self):
        with patch.object(w, '_sync_network_process', side_effect=RuntimeError('refused')) as process, \
             patch.object(w, 'hidden_password', side_effect=AssertionError('secret')) as password, \
             patch('sys.stdout', new=io.StringIO()) as output, patch('sys.stderr', new=io.StringIO()):
            self.assertEqual(w.main(self.cli_args()), 1)
            self.assertEqual(process.call_count, 1)
            self.assertEqual(process.call_args.args[0][1], 'sync')
            self.assertEqual(output.getvalue(), '')
            password.assert_not_called()

    def test_duplicate_flags_rejected_by_actual_cli_before_io(self):
        with patch.object(w, '_sync_network_process', side_effect=AssertionError('must not run')) as process, \
             patch('sys.stderr', new=io.StringIO()):
            self.assertEqual(w.main(self.cli_args() + ['--limit', '1', '--limit', '128']), 1)
            process.assert_not_called()

    def test_cli_never_accepts_supplied_expected_tip(self):
        args=['--no-real-funds', 'sync-network', str(self.args.wallet), '--expected-height', '1']
        with patch('sys.stderr', new=io.StringIO()), self.assertRaises(SystemExit): w.main(args)


class ProcessTests(unittest.TestCase):
    def test_real_failing_child_is_reaped_without_echoing_stderr(self):
        with self.assertRaises(RuntimeError) as failure:
            w._sync_network_process([sys.executable, '-c', 'import sys;print("secret",file=sys.stderr);sys.exit(7)'])
        self.assertNotIn('secret', str(failure.exception))

    def test_oversize_public_stdout_rejected_before_decode(self):
        with self.assertRaises(RuntimeError):
            w._sync_network_process([sys.executable, '-c', 'print("x"*5000)'])

    def test_zero_exit_with_stderr_is_not_success(self):
        with self.assertRaises(RuntimeError):
            w._sync_network_process([sys.executable, '-c', 'import sys;print("bad",file=sys.stderr)'])

    def test_wait_exception_kills_and_joins_real_child(self):
        real_wait = subprocess.Popen.wait
        calls=[]
        def timed(proc, timeout=None):
            calls.append((proc, timeout))
            if len(calls)==1:
                return real_wait(proc, timeout=0.05)
            return real_wait(proc, timeout=timeout)
        with patch.object(subprocess.Popen, 'wait', timed):
            with self.assertRaises(subprocess.TimeoutExpired):
                w._sync_network_process([sys.executable, '-c', 'import time;time.sleep(30)'])
        self.assertEqual(calls[0][1], 300)
        self.assertEqual(calls[-1][1], 5)
        self.assertIsNotNone(calls[0][0].poll())


if __name__ == '__main__':
    unittest.main()
