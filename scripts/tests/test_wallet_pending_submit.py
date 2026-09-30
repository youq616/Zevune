"""UI/hand-off isolation; NOT a fake proof or an accepting network executable.

Real verifier / signed bytes / RPC receipt cases belong to wallet_network_e2e.
"""
import contextlib
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import zevune_wallet as w
import wallet_submission as s
import test_wallet_network_prepare as fixture

RAW = b'synthetic public bytes for UI-only tests'
TXID = hashlib.sha256(RAW).hexdigest()


def accepted(**extra):
    result = dict(status='accepted_to_mempool_not_confirmed', txid=TXID,
                  reference_height=3, confirmed=False, base_checkpoint_matched=True)
    result.update(extra)
    return json.dumps(result).encode()


class PendingSubmissionTests(unittest.TestCase):
    def setUp(self):
        fixture.NetworkPreparationTests.setUp(self)
        self.a.command = 'submit-pending-network'
        del self.a.output
        del self.a.expiry_blocks
        self.a.socks_proxy='127.0.0.1:19050'
        # UI-only route forwarding fixture; Go alone validates onion checksum.
        self.a.endpoint='http://'+'a'*56+'.onion:80'
        self.result.update(result='checkpoint_pending_exported_not_broadcast',
                           wallet_unchanged=True, receipt=fixture.PIN, txid=TXID)
        self.payload_paths = []

    def args(self):
        a=self.a
        result=['--no-real-funds','--backend',str(a.backend),'--backend-sha256',a.backend_sha256,
                '--pin',a.pin,'submit-pending-network',str(a.wallet)]
        for k in ('journal','genesis','genesis_sha256','config','config_sha256','network_backend',
                  'network_backend_sha256','worker','worker_sha256','endpoint','limit'):
            result += ['--'+k.replace('_','-'),str(getattr(a,k))]
        if a.socks_proxy is not None: result+=['--socks-proxy',a.socks_proxy]
        if a.create_reference: result+=['--create-reference']
        return result

    def run_submit(self, *, network=None, reply=None, recovery=None, approve='SUBMIT',
                   password=None, error=None, use_main=False):
        def net(command):
            if command[1] == 'sync':
                if isinstance(network, BaseException):
                    raise network
                return json.dumps(network or fixture.signed_result()).encode()
            self.assertEqual(command[1], 'submit')
            if isinstance(reply, BaseException):
                raise reply
            if callable(reply):
                return reply(command)
            return accepted() if reply is None else reply
        def recover(_backend, frame, _digest):
            op, pw, pin, fields = fixture.decode_frame(frame)
            self.assertEqual((op, pw, pin), (13, fixture.PASSWORD, fixture.PIN))
            path = Path(fields[4]); self.payload_paths.append(path)
            self.assertEqual(path.name, 'pending.tx')
            self.assertNotEqual(path, self.a.wallet)
            if callable(recovery):
                return recovery(path, fields)
            path.write_bytes(RAW)
            if isinstance(recovery, BaseException):
                raise recovery
            return self.result if recovery is None else recovery
        with contextlib.ExitStack() as stack:
            out, err = io.StringIO(), io.StringIO()
            stack.enter_context(contextlib.redirect_stderr(err))
            stack.enter_context(contextlib.redirect_stdout(out))
            proc = stack.enter_context(patch.object(w, '_sync_network_process', side_effect=net))
            prompt = stack.enter_context(patch('builtins.input', return_value=approve))
            secret = stack.enter_context(patch.object(w, 'hidden_password',
                **({'side_effect': password} if password else {'return_value': fixture.PASSWORD})))
            child = stack.enter_context(patch.object(w, 'invoke', side_effect=recover))
            if use_main:
                value = w.main(self.args())
            elif error:
                with self.assertRaises(error):
                    s.submit_pending_network(self.a, w)
                value = None
            else:
                value = s.submit_pending_network(self.a, w)
        return value, proc, prompt, secret, child, out.getvalue(), err.getvalue()

    def test_schema_only_exact_nonconfirmation_receipt(self):
        self.assertEqual(s.checked_submission(accepted(), TXID, 3, 10000, w)['txid'], TXID)
        good = json.loads(accepted())
        for k in good:
            r = dict(good); del r[k]
            with self.subTest(k=k), self.assertRaises(ValueError):
                s.checked_submission(json.dumps(r).encode(), TXID, 3, 10000, w)
        for k, v in [('status','confirmed'),('txid','44'*32),('reference_height',True),
                     ('reference_height',2),('reference_height',10001),('confirmed',1),
                     ('confirmed',True),('base_checkpoint_matched',False),('balance',3)]:
            with self.subTest(k=k,v=v), self.assertRaises(ValueError):
                s.checked_submission(accepted(**{k:v}), TXID, 3, 10000, w)
        for raw in (b'{} {}', b'[]', accepted().replace(b'"confirmed": false',
                    b'"confirmed": false, "confirmed": false'), b' '*4097,
                    accepted().replace(b'"reference_height": 3', b'"reference_height": 3.0')):
            with self.assertRaises(ValueError): s.checked_submission(raw, TXID, 3, 10000, w)

    def test_one_recovery_then_one_pinned_original_submission(self):
        before = self.a.wallet.read_bytes()
        result, proc, prompt, secret, child, _, _ = self.run_submit()
        self.assertEqual((proc.call_count,prompt.call_count,secret.call_count,child.call_count),(2,1,1,1))
        sync, submit = [c.args[0] for c in proc.call_args_list]
        self.assertEqual((sync[1], submit[1]), ('sync','submit'))
        self.assertIn('--no-real-funds', submit)
        for flag,value in [('--tx-sha256',TXID),('--expected-height','3'),
                           ('--expected-app-hash','33'*32),('--endpoint',self.a.endpoint),
                           ('--socks-proxy',self.a.socks_proxy),('--config-sha256',self.a.config_sha256)]:
            self.assertEqual(submit[submit.index(flag)+1],value)
        for private in (str(self.a.wallet),fixture.PIN,fixture.PASSWORD.decode()):
            self.assertNotIn(private,submit); self.assertNotIn(private,sync)
        self.assertNotIn('--create',submit)
        self.assertEqual(result['result'],'pending_accepted_to_mempool_not_confirmed')
        for flag in ('confirmed','retry_authorized','real_funds_allowed'):
            self.assertIs(result[flag],False)
        self.assertIs(result['wallet_unchanged'],True)
        self.assertEqual(result['receipt'],fixture.PIN)
        self.assertEqual(before,self.a.wallet.read_bytes())
        self.assertTrue(all(not p.exists() for p in self.payload_paths))

    def test_partial_and_false_network_refuse_before_confirmation(self):
        partial = fixture.signed_result(); partial.update(observed_signed_tip=5,caught_up_to_observed_tip=False)
        for net in (partial,RuntimeError('do not echo')):
            _,proc,prompt,secret,child,*_ = self.run_submit(network=net,error=(ValueError,RuntimeError))
            self.assertEqual(proc.call_count,1); prompt.assert_not_called(); secret.assert_not_called(); child.assert_not_called()

    def test_cancel_cannot_recover_or_submit(self):
        _,proc,_,secret,child,*_ = self.run_submit(approve='NO',error=ValueError)
        self.assertEqual(proc.call_count,1); secret.assert_not_called(); child.assert_not_called()

    def test_invalid_pins_and_caller_payload_are_not_backdoors(self):
        for k,v in [('pin',''),('genesis_sha256','0'*64),('output',Path('/tmp/caller')),
                    ('expected_height','3'),('expected_app_hash','33'*32),('tx','caller'),('tx_sha256',TXID)]:
            exists=hasattr(self.a,k); old=getattr(self.a,k,None); setattr(self.a,k,v)
            try:
                _,proc,prompt,secret,child,*_ = self.run_submit(error=(ValueError,RuntimeError))
                proc.assert_not_called(); prompt.assert_not_called(); secret.assert_not_called(); child.assert_not_called()
            finally:
                if exists: setattr(self.a,k,old)
                else: delattr(self.a,k)

    def test_wrong_recovery_reply_or_bytes_never_reaches_submit(self):
        bad=copy.deepcopy(self.result); bad['wallet_unchanged']=False
        def wrong_bytes(path,fields):
            path.write_bytes(b'not the bytes for this txid'); return self.result
        def missing(path,fields): return self.result
        for response in (bad,wrong_bytes,missing,RuntimeError('wallet refused')):
            _,proc,_,_,child,*_ = self.run_submit(recovery=response,error=(ValueError,RuntimeError,OSError))
            self.assertEqual((proc.call_count,child.call_count),(1,1))

    def test_program_change_before_secret_prevents_recovery(self):
        def changed(_):
            self.prog.write_bytes(b'changed'); return fixture.PASSWORD
        _,proc,_,_,child,*_ = self.run_submit(password=changed,error=(ValueError,RuntimeError))
        self.assertEqual(proc.call_count,1); child.assert_not_called()

    def test_all_failures_after_submit_remain_unknown_without_retry(self):
        before=self.a.wallet.read_bytes()
        for response in (RuntimeError('received then disconnected'),subprocess.TimeoutExpired('private',300),
                         accepted(confirmed=True),accepted(txid='99'*32),b'',KeyboardInterrupt()):
            _,proc,_,_,child,*_ = self.run_submit(reply=response,error=s.SubmissionUnknown)
            self.assertEqual((proc.call_count,child.call_count),(2,1))
            self.assertEqual(self.a.wallet.read_bytes(),before)

    def test_changed_identity_after_network_submit_is_unknown(self):
        def changed(command):
            self.prog.write_bytes(b'changed after send'); return accepted()
        _,proc,_,_,child,*_ = self.run_submit(reply=changed,error=s.SubmissionUnknown)
        self.assertEqual((proc.call_count,child.call_count),(2,1))

    def test_main_dispatch_has_no_payload_path_and_unknown_is_explicit(self):
        code,proc,_,_,child,out,_ = self.run_submit(use_main=True)
        self.assertEqual(code,0); self.assertIs(json.loads(out)['confirmed'],False)
        self.assertEqual((proc.call_count,child.call_count),(2,1))
        code,proc,_,_,child,out,err = self.run_submit(reply=RuntimeError('never print secret'),use_main=True)
        self.assertEqual(code,1); self.assertEqual(out,''); self.assertIn('unknown',err.lower())
        self.assertNotIn('never print secret',err)
        self.assertEqual((proc.call_count,child.call_count),(2,1))

    def test_main_rejects_duplicate_and_external_transaction_flags(self):
        for tail in (['--limit','1'],['--tx','/tmp/a'],['--expected-height','3'],['--output','/tmp/a']):
            with patch.object(w,'_sync_network_process') as proc, patch.object(w,'invoke') as child, \
                 contextlib.redirect_stderr(io.StringIO()):
                try: code=w.main(self.args()+tail)
                except SystemExit as e: code=e.code
                self.assertNotEqual(code,0); proc.assert_not_called(); child.assert_not_called()


    def test_loopback_absent_proxy_is_preserved_not_fallback(self):
        self.a.endpoint='http://127.0.0.1:26657'; self.a.socks_proxy=None
        _,proc,*_=self.run_submit()
        for invocation in proc.call_args_list:
            self.assertNotIn('--socks-proxy',invocation.args[0])
            self.assertIn(self.a.endpoint,invocation.args[0])

    def test_real_refusing_and_timed_out_submission_children_are_reaped(self):
        original_runner=w._sync_network_process
        original_popen=subprocess.Popen
        before=self.a.wallet.read_bytes()
        for code in ('raise SystemExit(7)', 'import time; time.sleep(30)'):
            children=[]
            def spawn(*a,**kw):
                child=original_popen(*a,**kw); children.append(child)
                real_wait=child.wait
                def bounded_wait(timeout=None):
                    return real_wait(timeout=0.05 if timeout==300 else timeout)
                child.wait=bounded_wait
                return child
            def fail_submission(_command):
                # Real process only refuses or stalls; never fabricates a valid
                # network or cryptographic result. Production budget unchanged.
                return original_runner([sys.executable,'-I','-c',code])
            with patch.object(subprocess,'Popen',side_effect=spawn):
                _,proc,_,_,child,*_=self.run_submit(reply=fail_submission,error=s.SubmissionUnknown)
            self.assertEqual((proc.call_count,child.call_count,len(children)),(2,1,1))
            self.assertIsNotNone(children[0].returncode)
            self.assertEqual(self.a.wallet.read_bytes(),before)

    def test_stdout_failure_after_send_does_not_retry(self):
        original_print=print
        def fail_stdout(*a,**kw):
            if kw.get('file',sys.stdout) is sys.stdout:
                raise OSError('private output failure')
            return original_print(*a,**kw)
        with patch('builtins.print',side_effect=fail_stdout):
            code,proc,_,_,child,out,err=self.run_submit(use_main=True)
        self.assertEqual(code,1); self.assertEqual(out,'')
        self.assertEqual((proc.call_count,child.call_count),(2,1))
        self.assertIn('unknown',err.lower()); self.assertNotIn('private output failure',err)


if __name__=='__main__': unittest.main()
