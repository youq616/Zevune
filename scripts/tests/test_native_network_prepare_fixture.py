"""Fixture/path/diagnostic regressions, not a substitute for native verification.

No valid binary/proof result is fabricated. Positive scalar examples below test
only observation validation; genuine partial catchup runs in wallet_network_e2e.
"""
import copy
import ctypes
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import native_wallet_network_prepare as native
import zevune_wallet as wallet
import test_wallet_network_prepare as fixture


class NativePreparationFixtureTests(unittest.TestCase):
    def setUp(self):
        fixture.NetworkPreparationTests.setUp(self)
        self.a.limit = '1'

    def argv(self):
        a = self.a
        return ['--no-real-funds', '--backend', str(a.backend), '--backend-sha256', a.backend_sha256,
            '--pin', a.pin, 'prepare-network', str(a.wallet), str(a.output),
            '--journal', str(a.journal), '--genesis', str(a.genesis), '--genesis-sha256', a.genesis_sha256,
            '--config', str(a.config), '--config-sha256', a.config_sha256,
            '--network-backend', str(a.network_backend), '--network-backend-sha256', a.network_backend_sha256,
            '--worker', str(a.worker), '--worker-sha256', a.worker_sha256,
            '--endpoint', a.endpoint, '--limit', '1', '--expiry-blocks', '100', '--create-reference']

    def run_initial(self, detail):
        return native.run_preparation(self.argv(), self.destination, fixture.PASSWORD, fail=True,
            no_input=True, partial_reference=self.a.journal, detail=detail)

    def test_canonical_config_preserves_original_bytes_and_pin(self):
        route = dict(config=str(self.config), config_sha256=self.a.config_sha256)
        detail = {}
        normalized = native.canonical_config(route, detail)
        self.assertEqual(normalized, route)
        self.assertIsNot(normalized, route)
        self.assertEqual(detail, dict(config_was_canonical=True, config_canonical=True))
        raw, _ = wallet._sync_pinned_file(Path(normalized['config']), self.a.config_sha256, 16384, contents=True)
        self.assertEqual(raw, self.config.read_bytes())
        with self.assertRaises(ValueError):
            wallet._sync_pinned_file(Path(normalized['config']), '00'*32, 16384, contents=True)
        with self.assertRaises(native.FixtureFailure) as failure:
            native.canonical_config({'config': str(self.root/'missing')}, {})
        self.assertEqual(failure.exception.code, 'config_canonicalization_failed')

    @unittest.skipIf(os.name == 'nt', 'POSIX alias mechanism; native Windows short-name case is separate')
    def test_path_alias_refusal_can_no_longer_pass_as_partial_catchup(self):
        canonical = self.root/'long-canonical-directory'; canonical.mkdir()
        real = canonical/'config'; real.write_bytes(self.config.read_bytes())
        alias = self.root/'alias'; alias.symlink_to(canonical, target_is_directory=True)
        self.a.config = alias/'config'
        before = self.a.wallet.read_bytes()
        with patch.object(wallet, '_sync_network_process', side_effect=AssertionError('no network')) as network, \
             patch.object(wallet, 'invoke', side_effect=AssertionError('no wallet')) as backend:
            with self.assertRaises(native.FixtureFailure) as failure:
                self.run_initial({})
            self.assertEqual(failure.exception.code, 'preflight_refused')
            network.assert_not_called(); backend.assert_not_called()
        self.assertEqual(self.a.wallet.read_bytes(), before)
        self.assertFalse(self.a.output.exists()); self.assertFalse(self.a.journal.exists())
        detail = {}
        route = native.canonical_config(dict(config=str(self.a.config)), detail)
        self.assertIs(detail['config_was_canonical'], False)
        self.assertIs(detail['config_canonical'], True)
        self.assertEqual(Path(route['config']), real)
        raw, _ = wallet._sync_pinned_file(Path(route['config']), self.a.config_sha256, 16384, contents=True)
        self.assertEqual(raw, real.read_bytes())

    def test_preflight_network_and_invalid_result_are_distinct_failures(self):
        for answer, expected in ((RuntimeError('PRIVATE_SENTINEL'), 'network_call_failed'),
                                 (b'{}', 'network_result_refused')):
            detail = {}
            with patch.object(wallet, '_sync_network_process',
                              **({'side_effect':answer} if isinstance(answer, Exception) else {'return_value':answer})) as network, \
                 patch.object(wallet, 'invoke', side_effect=AssertionError('no wallet')) as backend:
                with self.assertRaises(native.FixtureFailure) as failure:
                    self.run_initial(detail)
                self.assertEqual(failure.exception.code, expected)
                self.assertEqual(network.call_count, 1); backend.assert_not_called()
                self.assertEqual(detail['network_calls'], 1)
                self.assertFalse(detail['verified_partial'])
        self.a.config = self.root/'missing'
        with patch.object(wallet, '_sync_network_process') as network:
            with self.assertRaises(native.FixtureFailure) as failure:
                self.run_initial({})
            self.assertEqual(failure.exception.code, 'preflight_refused')
            network.assert_not_called()

    def test_partial_metadata_requires_every_exact_field_and_private_boundary(self):
        # Inert metadata validation only. This does not produce a verifier result.
        observation = dict(network=dict(height=1, new_blocks=1, observed_signed_tip=3,
            caught_up_to_observed_tip=False, base_checkpoint_matched=False, real_funds_allowed=False),
            network_returned=True, wallet_calls=0)
        detail = dict(verifier_calls=1, network_calls=1, verified_partial=False)
        self.a.journal.write_bytes(b'inert existence fixture, not a journal')
        native.checked_initial_partial(observation, detail, 1, '', 0, 0, self.a.journal)
        self.assertIs(detail['verified_partial'], True)
        for key, value in [('height',True),('height',2),('new_blocks',0),('new_blocks',True),
                           ('observed_signed_tip',2),('observed_signed_tip',True),
                           ('caught_up_to_observed_tip',True),('caught_up_to_observed_tip',0),
                           ('base_checkpoint_matched',True),('real_funds_allowed',0)]:
            wrong=copy.deepcopy(observation); wrong['network'][key]=value
            with self.subTest(key=key,value=value), self.assertRaises(native.FixtureFailure):
                native.checked_initial_partial(wrong, dict(detail), 1, '', 0, 0, self.a.journal)
        for returned in (False, 1):
            with self.assertRaises(native.FixtureFailure):
                native.checked_initial_partial(dict(observation,network_returned=returned),dict(detail),1,'',0,0,self.a.journal)
        for d in (dict(detail, verifier_calls=0),dict(detail, verifier_calls=2),dict(detail, network_calls=2)):
            with self.assertRaises(native.FixtureFailure):
                native.checked_initial_partial(observation,d,1,'',0,0,self.a.journal)
        for code,out,prompts,secrets in ((0,'',0,0),(True,'',0,0),(1,'private output',0,0),(1,'',1,0),(1,'',0,1)):
            with self.assertRaises(native.FixtureFailure):
                native.checked_initial_partial(observation,dict(detail),code,out,prompts,secrets,self.a.journal)
        with self.assertRaises(native.FixtureFailure):
            native.checked_initial_partial(dict(observation,wallet_calls=1),dict(detail),1,'',0,0,self.a.journal)
        self.a.journal.unlink()
        with self.assertRaises(native.FixtureFailure) as failure:
            native.checked_initial_partial(observation,dict(detail),1,'',0,0,self.a.journal)
        self.assertEqual(failure.exception.code,'missing_reference')

    def test_reference_copy_failures_are_bounded_and_distinct(self):
        detail = {}
        with self.assertRaises(native.FixtureFailure) as failure:
            native.copy_initial_reference(self.root/'missing', self.root/'target', detail)
        self.assertEqual(failure.exception.code, 'missing_reference')
        self.assertIs(detail['reference_exists'], False)
        source = self.root/'public-reference'
        source.write_bytes(b'inert public fixture')
        target = self.root/'public-copy'
        native.copy_initial_reference(source, target, detail)
        self.assertEqual(source.read_bytes(), target.read_bytes())
        existing_directory = self.root/'existing-directory'; existing_directory.mkdir()
        with self.assertRaises(native.FixtureFailure) as failure:
            native.copy_initial_reference(source, existing_directory, detail)
        self.assertEqual(failure.exception.code, 'reference_copy_failed')
        self.assertIs(detail['reference_exists'], True)

    def test_observer_returns_exact_original_object_without_second_call(self):
        # Observer plumbing only; no cryptographic success or executable mock.
        result = (None,dict(height=1,new_blocks=1,observed_signed_tip=3,
            caught_up_to_observed_tip=False,base_checkpoint_matched=False,real_funds_allowed=False),None,None,None)
        token = object()
        def original(argument):
            self.assertIs(argument, token)
            self.assertEqual(wallet._sync_network_process(['inert-observer-argument']), b'inert')
            return result
        with patch.object(wallet,'_verified_network_reference',side_effect=original) as original_call, \
             patch.object(wallet,'_sync_network_process',return_value=b'inert') as network, \
             patch.object(wallet,'invoke',side_effect=AssertionError('never a wallet')) as backend:
            detail={}
            with native.observe_original_reference(detail) as observed:
                self.assertIs(wallet._verified_network_reference(token),result)
            self.assertEqual(original_call.call_count,1); self.assertEqual(network.call_count,1)
            backend.assert_not_called();self.assertEqual(detail['verifier_calls'],1)
            self.assertEqual(observed['network'],result[1])
            self.assertIs(wallet._verified_network_reference,original_call)

    def test_failure_frame_never_leaks_arbitrary_fields(self):
        sentinel='PRIVATE_SENTINEL/path/password/receipt'
        detail=dict(config_was_canonical=sentinel,config_canonical=True,reference_exists=False,
            verified_partial=False,verifier_calls=999,network_calls=True,stderr=sentinel)
        raw=json.dumps(native.failure_frame(RuntimeError(sentinel),sentinel,detail))
        self.assertNotIn(sentinel,raw);self.assertNotIn('stderr',raw)
        value=json.loads(raw)
        self.assertEqual((value['step'],value['code']),('unknown','unknown'))
        self.assertIsNone(value['config_was_canonical']);self.assertEqual(value['verifier_calls'],2)
        self.assertIsNone(value['network_calls'])
        good=native.failure_frame(native.FixtureFailure('missing_reference'),'initial-reference-copy',{})
        self.assertEqual(good['code'],'missing_reference')
        recovery=native.failure_frame(RuntimeError('private'),'readonly-pending-recovery',{})
        self.assertEqual(recovery['step'],'readonly-pending-recovery')

    @unittest.skipUnless(os.name == 'nt', 'requires actual native Windows short-name API')
    def test_native_windows_short_config_normalizes_without_weakening_pin(self):
        folder=self.root/'configuration-directory-with-long-name';folder.mkdir()
        target=folder/'public-configuration-with-long-name.json';target.write_bytes(self.config.read_bytes())
        get=ctypes.WinDLL('kernel32',use_last_error=True).GetShortPathNameW
        get.argtypes=(ctypes.c_wchar_p,ctypes.c_wchar_p,ctypes.c_uint32);get.restype=ctypes.c_uint32
        size=get(str(target),None,0)
        if not size:self.skipTest('native filesystem did not provide an8.3 alias')
        buffer=ctypes.create_unicode_buffer(size)
        if not get(str(target),buffer,size):self.fail('native short-name lookup failed')
        short=Path(buffer.value)
        if short == short.resolve(strict=True):self.skipTest('native filesystem8.3 alias unavailable')
        with self.assertRaises(ValueError):
            wallet._sync_pinned_file(short,self.a.config_sha256,16384,contents=True)
        detail={};route=native.canonical_config(dict(config=str(short)),detail)
        self.assertIs(detail['config_was_canonical'],False)
        raw,_=wallet._sync_pinned_file(Path(route['config']),self.a.config_sha256,16384,contents=True)
        self.assertEqual(raw,target.read_bytes())


if __name__=='__main__':unittest.main()
