"""Refusal-only pending-fixture regressions; no accepting executable or proof.

The inherited preparation tests cover the shared observer/parser. The genuine
accepted/lost-response two-profile scenario remains the native positive gate.
"""
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parent))
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import native_wallet_pending_submit as native
import native_wallet_network_prepare as preparation
import test_wallet_network_prepare as fixture
import zevune_wallet as wallet


class NativePendingFixtureTests(unittest.TestCase):
    def setUp(self):
        fixture.NetworkPreparationTests.setUp(self)
        self.a.limit='1'

    def argv(self):
        a=self.a
        return ['--no-real-funds','--backend',str(a.backend),'--backend-sha256',a.backend_sha256,
            '--pin',a.pin,'submit-pending-network',str(a.wallet),
            '--journal',str(a.journal),'--genesis',str(a.genesis),'--genesis-sha256',a.genesis_sha256,
            '--config',str(a.config),'--config-sha256',a.config_sha256,
            '--network-backend',str(a.network_backend),'--network-backend-sha256',a.network_backend_sha256,
            '--worker',str(a.worker),'--worker-sha256',a.worker_sha256,
            '--endpoint',a.endpoint,'--limit','1','--create-reference']

    def run_initial(self,detail):
        return native.run_pending_command(self.argv(),[],fixture.PASSWORD,success=False,
            before_secret=True,partial_reference=self.a.journal,detail=detail)

    def test_same_original_console_and_shared_observer(self):
        self.assertIs(native.wallet,wallet)
        self.assertIs(native.preparation,preparation)
        self.assertIs(native.preparation.wallet,wallet)
        self.assertIs(native.preparation.observe_original_reference,preparation.observe_original_reference)
        self.assertIs(native.preparation.checked_initial_partial,preparation.checked_initial_partial)

    def test_missing_input_cannot_be_mistaken_for_partial_success(self):
        self.a.config=self.root/'missing'
        before=self.a.wallet.read_bytes();detail={}
        with patch.object(wallet,'_sync_network_process',side_effect=AssertionError('no network')) as network, \
             patch.object(wallet,'invoke',side_effect=AssertionError('no wallet')) as backend:
            with self.assertRaises(preparation.FixtureFailure) as failure:
                self.run_initial(detail)
            self.assertEqual(failure.exception.code,'preflight_refused')
            network.assert_not_called();backend.assert_not_called()
        self.assertEqual(self.a.wallet.read_bytes(),before)
        self.assertFalse(self.a.journal.exists())
        self.assertFalse(list(self.root.glob('.zevune-submit-*')))
        self.assertIs(detail['verified_partial'],False)

    @unittest.skipIf(os.name=='nt','POSIX alias mechanism; inherited Windows short-name regression is native-only')
    def test_config_alias_is_fixed_only_in_fixture_and_pin_still_required(self):
        directory=self.root/'canonical';directory.mkdir()
        config=directory/'config';config.write_bytes(self.config.read_bytes())
        alias=self.root/'alias';alias.symlink_to(directory,target_is_directory=True)
        self.a.config=alias/'config'
        with patch.object(wallet,'_sync_network_process',side_effect=AssertionError('no network')) as network:
            with self.assertRaises(preparation.FixtureFailure) as failure:
                self.run_initial({})
            self.assertEqual(failure.exception.code,'preflight_refused');network.assert_not_called()
        detail={}
        route=preparation.canonical_config(dict(config=str(self.a.config)),detail)
        self.a.config=Path(route['config'])
        self.assertEqual(self.a.config,config)
        self.assertIs(detail['config_was_canonical'],False)
        raw,_=wallet._sync_pinned_file(self.a.config,self.a.config_sha256,16384,contents=True)
        self.assertEqual(raw,config.read_bytes())
        with self.assertRaises(ValueError):wallet._sync_pinned_file(self.a.config,'00'*32,16384,contents=True)
        with patch.object(wallet,'_sync_network_process',side_effect=RuntimeError('refusal only')) as network, \
             patch.object(wallet,'invoke',side_effect=AssertionError('no wallet')) as backend:
            with self.assertRaises(preparation.FixtureFailure) as failure:self.run_initial(detail)
            self.assertEqual(failure.exception.code,'network_call_failed')
            self.assertEqual(network.call_count,1);backend.assert_not_called()

    def test_network_failure_and_bad_reply_are_not_partial_evidence(self):
        before=self.a.wallet.read_bytes()
        for value,code in ((RuntimeError('PRIVATE_SENTINEL'),'network_call_failed'),(b'{}','network_result_refused')):
            detail={}
            with patch.object(wallet,'_sync_network_process',**({'side_effect':value} if isinstance(value,Exception) else {'return_value':value})) as network, \
                 patch.object(wallet,'invoke',side_effect=AssertionError('no wallet')) as backend:
                with self.assertRaises(preparation.FixtureFailure) as failure:self.run_initial(detail)
                self.assertEqual(failure.exception.code,code)
                self.assertEqual(network.call_count,1);backend.assert_not_called()
                self.assertIs(detail['verified_partial'],False)
            self.assertEqual(self.a.wallet.read_bytes(),before)
            self.assertFalse(self.a.journal.exists())

    def test_failure_frames_are_fixed_and_private_fields_cannot_escape(self):
        for step in native.PENDING_FAILURE_STEPS:
            frame=native.pending_failure_frame(preparation.FixtureFailure('preflight_refused'),step,
                dict(config_canonical=True,reference_exists=False,verified_partial=False,verifier_calls=1,network_calls=0))
            self.assertEqual(frame['step'],step);self.assertEqual(frame['code'],'preflight_refused')
        sentinel='PRIVATE_SENTINEL/path/password/receipt'
        frame=native.pending_failure_frame(RuntimeError(sentinel),sentinel,
            dict(config_canonical=sentinel,reference_exists=1,verifier_calls=999,network_calls=True,stderr=sentinel))
        raw=json.dumps(frame)
        self.assertNotIn(sentinel,raw);self.assertNotIn('stderr',raw)
        self.assertEqual((frame['step'],frame['code']),('unknown','unknown'))
        self.assertIsNone(frame['config_canonical']);self.assertIsNone(frame['reference_exists'])
        self.assertEqual(frame['verifier_calls'],2);self.assertIsNone(frame['network_calls'])


if __name__=='__main__':unittest.main()
