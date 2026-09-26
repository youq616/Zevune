"""Public framing fixtures are NOT encrypted wallets or successful authorization.

The viewer's only positive claim is public file consistency with independent
pins. Genuine recovery output compatibility is tested by the separate driver.
"""
import copy
import contextlib
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
import reconciliation_view as view
from test_wallet_backup import frames
from test_ledger_restore import pin


def fixture(root, pending=True, *, height=0, expiry=10, source_generation=2, copy_generation=3):
    folder = root / 'result'
    folder.mkdir()
    genesis = (b'g' * 32).hex()
    checkpoint = pin(height)
    wallet, tip = frames(copy_generation)
    (folder / 'wallet.journal').write_bytes(wallet)
    # Inert public header, no Orchard proof and deliberately NOT authentic.
    transaction = b'ZVORLAB2' + bytes.fromhex(genesis) + expiry.to_bytes(8, 'big') + bytes(50)
    if pending:
        (folder / 'pending.tx').write_bytes(transaction)
    report = dict(format=view.reconciliation.FORMAT,
                  result='pending_recovered_not_broadcast' if pending else 'no_pending_not_settlement_proof',
                  independent_ancestor=frames(1)[1], source_receipt=frames(source_generation)[1], copy_receipt=tip,
                  checkpoint=checkpoint, genesis_sha256=genesis, height=height,
                  txid=hashlib.sha256(transaction).hexdigest() if pending else None,
                  pending=pending, broadcast_status='unknown', source_retained=True, active_wallet_replaced=False,
                  retry_authorized=False, latest_inferred=False, finality_verified=False, real_funds_allowed=False)
    raw = view.files.canonical(report)
    (folder / view.reconciliation.MARKER).write_bytes(raw)
    return dict(directory=str(folder), report_sha256=hashlib.sha256(raw).hexdigest(),
                checkpoint=checkpoint, genesis_sha256=genesis), report


class ViewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='reconcile-view-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.values, self.report = fixture(self.root)
        self.folder = Path(self.values['directory'])
        self.marker = self.folder / view.reconciliation.MARKER
        self.before = self.inventory()

    def inventory(self):
        return {p.name: p.read_bytes() for p in self.folder.iterdir() if p.is_file()}

    def inspect(self):
        return view.inspect(view.prepare(self.values))

    def rewrite(self, report):
        raw = view.files.canonical(report)
        self.marker.write_bytes(raw)
        self.values['report_sha256'] = hashlib.sha256(raw).hexdigest()

    def test_public_pending_view_never_authenticates_or_claims_settlement(self):
        result = self.inspect()
        summary = result.summary()
        self.assertTrue(summary['file_integrity_verified'])
        self.assertEqual(summary['state'], 'pending_file_broadcast_unknown')
        for key in ('wallet_authenticated', 'transaction_authorization_verified', 'ledger_replayed',
                    'original_source_presence_verified', 'retry_authorized', 'finality_verified', 'real_funds_allowed'):
            self.assertIs(summary[key], False, key)
        self.assertIsNone(summary['current_chain_height'])
        self.assertEqual(summary['settlement_status'], 'unknown')
        self.assertEqual(result.txid, self.report['txid'])
        self.assertEqual(result.expiry_height, 10)
        self.assertEqual(result.wallet_records, 3)
        self.assertEqual(self.inventory(), self.before)
        with self.assertRaises(AttributeError):
            result.txid = 'x'

    def test_no_pending_stays_unknown_and_requires_no_transaction_file(self):
        (self.folder / 'pending.tx').unlink()
        self.rewrite(dict(self.report, pending=False, txid=None, result='no_pending_not_settlement_proof'))
        summary = self.inspect().summary()
        self.assertEqual(summary['state'], 'no_pending_outcome_unknown')
        self.assertIsNone(summary['expiry_height'])
        self.assertEqual(summary['expiry_relation'], 'unknown')
        self.assertEqual(summary['settlement_status'], 'unknown')
        self.assertIn('不能据此区分', self.inspect().render())
        (self.folder / 'pending.tx').write_bytes(self.before['pending.tx'])
        with self.assertRaises(ValueError):self.inspect()

    def test_expiry_comparison_is_only_against_recorded_checkpoint(self):
        for height, expected in ((9, 'not_expired_at_checkpoint'), (10, 'not_expired_at_checkpoint'),
                                 (11, 'expired_at_checkpoint')):
            self.values['checkpoint'] = pin(height)
            self.rewrite(dict(self.report, checkpoint=pin(height), height=height))
            summary = self.inspect().summary()
            self.assertEqual(summary['expiry_relation'], expected)
            self.assertIsNone(summary['current_chain_height'])
            self.assertIs(summary['retry_authorized'], False)

    def test_all_input_validation_precedes_file_access(self):
        invalid = {'directory': ('relative', '/tmp/../x', 'x\u200by'),
                   'report_sha256': ('F' * 64, None, 'a' * 65),
                   'checkpoint': ('00' * 128, None, 'x'), 'genesis_sha256': ('0' * 64, 'x', True)}
        with patch.object(view, '_chain', side_effect=AssertionError('must not access files')):
            for key, values in invalid.items():
                for value in values:
                    data = dict(self.values, **{key: value})
                    with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                        view.inspect(view.prepare(data))
            with self.assertRaises(ValueError):view.prepare(dict(self.values, extra='x'))
            with self.assertRaises(ValueError):view.inspect(None)

    def test_unicode_control_and_utf8_path_bounds(self):
        for character in ('\n', '\x00', '\u202e', '\ud800', '\u2028', '\u2029'):
            with self.assertRaises(ValueError):view.prepare(dict(self.values, directory=str(self.root)+character))
        with self.assertRaises(ValueError):view.prepare(dict(self.values, directory=str(self.root)+'/'+'中'*1500))

    def test_wrong_pin_stops_before_reading_wallet(self):
        self.values['report_sha256'] = '0' * 64
        with patch.object(view.files, 'read_file', wraps=view.files.read_file) as read:
            with self.assertRaises(ValueError):self.inspect()
            self.assertEqual(read.call_count, 1)
            self.assertEqual(read.call_args.args[0], self.marker)

    def test_network_and_checkpoint_substitution_refused(self):
        for change in ({'genesis_sha256': 'a'*64}, {'height': 1}, {'height': False}, {'checkpoint': pin(1)}):
            self.rewrite(dict(self.report, **change))
            with self.subTest(change=change), self.assertRaises(ValueError):self.inspect()

    def test_every_report_field_is_required_and_extras_refused(self):
        for name in self.report:
            report = dict(self.report); report.pop(name); self.rewrite(report)
            with self.subTest(missing=name), self.assertRaises(ValueError):self.inspect()
        self.rewrite(dict(self.report, balance=100000))
        with self.assertRaises(ValueError):self.inspect()

    def test_flags_require_exact_types_and_unknown_outcome(self):
        for name in ('source_retained', 'pending', 'active_wallet_replaced', 'retry_authorized',
                     'latest_inferred', 'finality_verified', 'real_funds_allowed'):
            for bad in (int(self.report[name]), None, 'false'):
                self.rewrite(dict(self.report, **{name: bad}))
                with self.subTest(name=name, bad=bad), self.assertRaises(ValueError):self.inspect()
        for name, value in (('source_retained', False), ('retry_authorized', True), ('finality_verified', True),
                            ('real_funds_allowed', True), ('broadcast_status', 'confirmed'), ('result', 'paid')):
            self.rewrite(dict(self.report, **{name: value}))
            with self.assertRaises(ValueError):self.inspect()

    def test_duplicates_nonfinite_noncanonical_and_bad_json_rejected_with_matching_digest(self):
        raw = self.before[view.reconciliation.MARKER]
        candidates = [raw[:-2] + b',"pending":true}\n', raw+b' ', b'[]\n', b'null\n',
                      raw.replace(b'"height":0', b'"height":NaN'),
                      json.dumps(self.report, indent=2).encode(), b'\xff', b'{'*4000]
        for candidate in candidates:
            self.marker.write_bytes(candidate)
            self.values['report_sha256'] = hashlib.sha256(candidate).hexdigest()
            with self.subTest(size=len(candidate)), self.assertRaises((ValueError, RecursionError)):self.inspect()

    def test_receipt_relations_and_exact_public_ancestry(self):
        for key, value in (('independent_ancestor', frames(4)[1]), ('source_receipt', frames(1)[1]),
                           ('copy_receipt', frames(4)[1]), ('source_receipt', frames(2, b'x')[1]),
                           ('source_receipt', frames(2)[1][:-1]+'0'),
                           ('independent_ancestor', frames(1)[1][:-1]+'0')):
            self.rewrite(dict(self.report, **{key: value}))
            with self.subTest(key=key), self.assertRaises(ValueError):self.inspect()
        same = frames(3)[1]
        self.rewrite(dict(self.report, independent_ancestor=same, source_receipt=same))
        self.assertEqual(self.inspect().copy_receipt, same)

    def test_wallet_corruption_and_same_length_rehash_cannot_bypass_original_pin(self):
        path = self.folder / 'wallet.journal'
        raw = path.read_bytes()
        for bad in (raw[:-1], raw+b'x', raw[:100]+bytes([raw[100]^1])+raw[101:]):
            path.write_bytes(bad)
            with self.assertRaises(ValueError):self.inspect()
        path.write_bytes(frames(3, b'q')[0])
        with self.assertRaises(ValueError):self.inspect()

    def test_pending_tamper_or_wrong_txid_rejected(self):
        tx = self.folder / 'pending.tx'; raw = tx.read_bytes()
        tx.write_bytes(raw[:-1] + b'x')
        with self.assertRaises(ValueError):self.inspect()
        tx.write_bytes(raw)
        for value in (None, False, '0'*64, 'F'*64):
            self.rewrite(dict(self.report, txid=value))
            with self.assertRaises(ValueError):self.inspect()

    def test_pending_wrong_domain_header_and_zero_expiry_rejected_even_with_rehashed_report(self):
        raw = self.before['pending.tx']; path = self.folder / 'pending.tx'
        for bad in (raw[:8]+bytes(32)+raw[40:], b'ZVORLAB1'+raw[8:], raw[:40]+bytes(8)+raw[48:], raw[:97]):
            path.write_bytes(bad)
            self.rewrite(dict(self.report, txid=hashlib.sha256(bad).hexdigest()))
            with self.assertRaises(ValueError):self.inspect()

    def test_exact_inventory_missing_extra_case_and_directory_substitution(self):
        extra = self.folder / 'extra'; extra.write_bytes(b'inert')
        with self.assertRaises(ValueError):self.inspect()
        extra.unlink()
        tx = self.folder / 'pending.tx'; tx.unlink()
        with self.assertRaises(ValueError):self.inspect()
        tx.mkdir()
        with self.assertRaises(ValueError):self.inspect()
        tx.rmdir(); tx.write_bytes(self.before['pending.tx'])
        moved = self.folder / 'holding'; wrong = self.folder / 'PENDING.TX'
        tx.rename(moved); moved.rename(wrong)
        try:
            with self.assertRaises(ValueError):self.inspect()
        finally:
            wrong.rename(moved); moved.rename(tx)

    def test_hardlinks_and_size_limits_rejected(self):
        target = self.folder / 'wallet.journal'
        os.link(target, self.root / 'alias')
        with self.assertRaises(ValueError):self.inspect()
        (self.root / 'alias').unlink()
        for path, maximum in ((self.marker, view.files.MAX_MANIFEST),
                              (target, view.files.MAX_WALLET), (self.folder/'pending.tx', view.reconciliation.MAX_PAYMENT)):
            original = path.read_bytes()
            path.write_bytes(b'x'*(maximum+1))
            with self.subTest(path=path.name), self.assertRaises(ValueError):self.inspect()
            path.write_bytes(original)

    @unittest.skipUnless(os.name=='posix', 'POSIX links/FIFO; Windows reparse checked separately')
    def test_symlink_ancestor_and_fifo_refused(self):
        alias = self.root / 'alias'; alias.symlink_to(self.folder, target_is_directory=True)
        with self.assertRaises(ValueError):view.inspect(view.prepare(dict(self.values, directory=str(alias))))
        tx = self.folder/'pending.tx'; tx.unlink(); os.mkfifo(tx)
        with self.assertRaises(ValueError):self.inspect()

    def test_windows_reparse_directory_rejected(self):
        from types import SimpleNamespace
        before = self.folder.lstat()
        info = SimpleNamespace(st_mode=before.st_mode, st_file_attributes=0x400)
        with patch.object(Path,'lstat',return_value=info), self.assertRaises(ValueError):self.inspect()

    def test_mutation_after_wallet_read_is_detected(self):
        real = view.files.read_file
        changed = []
        def read(path, maximum):
            answer = real(path, maximum)
            if path.name == 'pending.tx' and not changed:
                changed.append(True)
                target = self.folder/'wallet.journal'
                target.write_bytes(target.read_bytes()+b'x')
            return answer
        with patch.object(view.files,'read_file',side_effect=read), self.assertRaises(ValueError):self.inspect()
        self.assertEqual(changed,[True])

    def test_same_bytes_file_replacement_is_detected(self):
        real = view.files.read_file; changed=[]
        def read(path, maximum):
            answer=real(path,maximum)
            if path.name=='pending.tx' and not changed:
                changed.append(True); original=self.folder/'wallet.journal'
                original.rename(self.root/'old'); original.write_bytes(self.before['wallet.journal'])
            return answer
        with patch.object(view.files,'read_file',side_effect=read), self.assertRaises(ValueError):self.inspect()

    def test_extra_entry_during_recheck_is_detected(self):
        real = view.files.read_file; count=[]
        def read(path,maximum):
            answer=real(path,maximum);count.append(path.name)
            if len(count)==4:(self.folder/'added').write_bytes(b'x')
            return answer
        with patch.object(view.files,'read_file',side_effect=read), self.assertRaises(ValueError):self.inspect()

    def test_no_native_call_or_subprocess_and_no_inputs_written(self):
        with patch.object(subprocess,'Popen',side_effect=AssertionError('never execute')), \
                patch.object(view.reconciliation.Backend,'_exchange',side_effect=AssertionError('no backend')):
            self.inspect()
        self.assertEqual(self.inventory(),self.before)

    def command(self):
        tool=Path(view.__file__)
        return [sys.executable,str(tool),'--no-real-funds',*sum((["--"+k.replace('_','-'),v] for k,v in self.values.items()),[])]

    def test_real_cli_json_text_and_fixed_errors(self):
        for more in ([],['--text']):
            process=subprocess.run(self.command()+more,capture_output=True,timeout=10)
            self.assertEqual(process.returncode,0,process.stderr)
            if not more:self.assertIs(json.loads(process.stdout)['wallet_authenticated'],False)
        command=self.command();command[command.index('--report-sha256')+1]='PRIVATE_SENTINEL'
        failed=subprocess.run(command,capture_output=True,timeout=10)
        self.assertEqual(failed.returncode,1)
        self.assertNotIn(b'PRIVATE',failed.stderr+failed.stdout)
        syntax=subprocess.run([sys.executable,view.__file__,'--secret','PRIVATE_SENTINEL'],capture_output=True,timeout=10)
        self.assertEqual(syntax.returncode,64)
        self.assertNotIn(b'PRIVATE',syntax.stderr+syntax.stdout)
        self.assertEqual(self.inventory(),self.before)

    def test_cli_help_does_not_import_tk_or_create_cache(self):
        scripts=Path(view.__file__).parent
        tools=self.root/'tools'; tools.mkdir()
        for path in scripts.glob('*.py'):shutil.copyfile(path,tools/path.name)
        before=set(p.name for p in tools.iterdir())
        for name in ('reconciliation_view.py','reconciliation_view_desktop.py'):
            process=subprocess.run([sys.executable,str(tools/name),'--help'],capture_output=True,timeout=10)
            self.assertEqual(process.returncode,0)
        self.assertEqual(set(p.name for p in tools.iterdir()),before)

    def test_real_cli_text_is_utf8_under_legacy_stdout_encoding(self):
        expected = self.inspect().render() + "\n"
        process = subprocess.run(self.command() + ['--text'], capture_output=True, timeout=10,
                                 env={**os.environ, 'PYTHONIOENCODING': 'cp1252', 'PYTHONUTF8': '0'})
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(process.stdout.decode('utf-8'), expected)
        self.assertEqual(self.inventory(), self.before)

    def test_text_only_embedding_and_short_binary_output_are_explicit(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):view.write_output("中文")
        self.assertEqual(out.getvalue(), "中文\n")
        class ShortOutput:
            buffer = None
            def __init__(self):self.buffer = self
            def write(self, raw):return len(raw) - 1
            def flush(self):raise AssertionError('short output must not claim completion')
        with patch.object(view.sys, 'stdout', ShortOutput()), self.assertRaises(OSError):
            view.write_output("中文")
        self.assertEqual(self.inventory(), self.before)

    def test_cli_interruption_does_not_print_partial_success(self):
        out,err=io.StringIO(),io.StringIO()
        with patch.object(view,'inspect',side_effect=KeyboardInterrupt('PRIVATE')), \
                contextlib.redirect_stdout(out),contextlib.redirect_stderr(err):
            code=view.main(self.command()[2:])
        self.assertEqual(code,130);self.assertEqual(out.getvalue(),'');self.assertNotIn('PRIVATE',err.getvalue())


if __name__=='__main__':unittest.main()
