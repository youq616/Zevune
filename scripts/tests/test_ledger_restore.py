"""Pure wire, schema and refusal tests. Synthetic pins are not trust evidence."""
import copy
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ledger_restore as ledger
from ledger_recovery_backend import Checkpoint, RecoveryBackend, ordered, validate_reply
import ledger_recovery_backend as transport


def pin(height=0, *, genesis=b'g'*32, length=None, segments=None):
    length = 108+150*height if length is None else length
    segments = int(height > 0) if segments is None else segments
    raw = b'ZVARCP01'+genesis+height.to_bytes(8,'big')+b'a'*32+length.to_bytes(8,'big')
    return (raw+(108).to_bytes(4,'big')+segments.to_bytes(4,'big')+b'l'*32).hex()


def response(base=None, later=None, package=False):
    later = later or Checkpoint.parse(pin(1))
    mode = 'restore-active-incremental' if package else ('plan-active-incremental' if base else 'verify-active')
    result = dict(operation=mode, checkpoint=later.encoded, height=later.height, bytes=later.length,
                  replay_verified=True, finality_verified=False, validator_ready=False, real_funds_allowed=False)
    if base is None:
        result.update(checkpoint_format='ZVARCP01', storage_profile='ActiveSegmentsV1', app_hash=later.app_hash,
                      segment_count=later.segments)
    else:
        result.update(format='zevune-active-incremental-package-1' if package else 'zevune-active-incremental-plan-1',
                      base_checkpoint=base.encoded, base_height=base.height, base_bytes=base.length,
                      reused_bytes=base.length, appended_bytes=later.length-base.length,
                      unchanged_segment_count=0, new_segment_count=later.segments-base.segments,
                      ranges=[dict(segment_index=0, offset=base.length-base.header, length=later.length-base.length)],
                      byte_prefix_verified=True, incremental_backup_written=False, snapshot_imported=False)
        if package:
            result.update(package_format='ZVAIPK01', package_bytes=280+later.length-base.length, archive_restored=True)
    return result


class LedgerRestoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()

    def test_checkpoint_wire_inclusive_limits_and_strict_types(self):
        self.assertEqual(Checkpoint.parse(pin()).length,108)
        self.assertEqual(Checkpoint.parse(pin(1)).height,1)
        for raw in (None, 12, pin().upper(), pin()+'\n', pin()[:-2], '00'*128):
            with self.subTest(value=str(raw)[:8]), self.assertRaises(ValueError): Checkpoint.parse(raw)
        for raw in (pin(1, segments=0), pin(0, segments=1), pin(1, length=257),
                    pin(1, genesis=bytes(32)), pin(1_000_001, segments=150), pin(1, length=2**30+1)):
            with self.assertRaises(ValueError): Checkpoint.parse(raw)

    def test_chain_order_network_and_wrapper_count_limits(self):
        self.assertEqual(len(ordered([pin(i) for i in range(9)])),9)
        for values in ([], [pin(i) for i in range(10)], [pin(1),pin()], [pin(),pin()],
                       [pin(),pin(1,genesis=b'x'*32)]):
            with self.assertRaises(ValueError): ordered(values)

    def test_all_backend_response_fields_strict_and_no_extra_flags(self):
        for base in (None, Checkpoint.parse(pin()), Checkpoint.parse(pin(1))):
            later = Checkpoint.parse(pin(1 if base is None else base.height+1))
            for package in ((False,) if base is None else (False,True)):
                good = response(base,later,package)
                validate_reply(good,good['operation'],later,base)
                for key in good:
                    bad = copy.deepcopy(good); del bad[key]
                    with self.subTest(key=key),self.assertRaises(ValueError):
                        validate_reply(bad,good['operation'],later,base)
                for key,value in (('height',True),('bytes',False),('replay_verified',1),
                                  ('finality_verified',0),('validator_ready',True),('real_funds_allowed',True)):
                    bad = {**good,key:value}
                    with self.assertRaises(ValueError): validate_reply(bad,good['operation'],later,base)
                with self.assertRaises(ValueError): validate_reply({**good,'extra':1},good['operation'],later,base)

    def test_incremental_range_counts_and_lengths(self):
        base,later=Checkpoint.parse(pin()),Checkpoint.parse(pin(1))
        good=response(base,later,True)
        for key,value in (('package_bytes',True),('package_bytes',431),('unchanged_segment_count',False),
                          ('new_segment_count',0),('ranges',[]),('ranges',[dict(segment_index=0,offset=0,length=151)])):
            with self.assertRaises(ValueError): validate_reply({**good,key:value},good['operation'],later,base)
        for value in (True,-1,2**32):
            bad=copy.deepcopy(good);bad['ranges'][0]['segment_index']=value
            with self.assertRaises(ValueError): validate_reply(bad,good['operation'],later,base)

    def test_multi_segment_response_shape(self):
        base=Checkpoint.parse(pin(6990,length=108+1_048_500,segments=1))
        later=Checkpoint.parse(pin(6991,length=108+1_048_500+150,segments=2))
        good=response(base,later,True)
        good.update(unchanged_segment_count=1, ranges=[dict(segment_index=1,offset=0,length=150)])
        validate_reply(good,good['operation'],later,base)
        good['ranges'][0]['offset']=1
        with self.assertRaises(ValueError): validate_reply(good,good['operation'],later,base)

    def test_package_prefix_is_bound_to_both_independent_pins(self):
        base,later=Checkpoint.parse(pin()),Checkpoint.parse(pin(1))
        raw=b'ZVAIPK01'+bytes.fromhex(base.encoded+later.encoded)+(1).to_bytes(4,'big')+bytes(12+150)
        path=self.root/'package';path.write_bytes(raw)
        self.assertEqual(ledger.package_snapshot(path,base,later)[0][2],len(raw))
        for data in (raw[:-1],raw+b'x',b'x'+raw[1:],raw[:8]+bytes(128)+raw[136:]):
            path.write_bytes(data)
            with self.assertRaises(ValueError): ledger.package_snapshot(path,base,later)

    def test_marker_only_accepts_independent_pin_sequence_without_parsing(self):
        raw=ledger.marker(ordered([pin(),pin(1)]))
        self.assertLess(len(ledger.marker(ordered([pin(i) for i in range(9)]))),4096)
        (self.root/ledger.MARKER).write_bytes(raw)
        with self.assertRaises(ValueError): ledger.verify(self.root,[pin()],None)
        (self.root/ledger.MARKER).write_bytes(b'{"checkpoints": ["untrusted"]}')
        with self.assertRaises(ValueError): ledger.verify(self.root,[pin()],None)

    def test_workspace_inventory_is_exact_and_bounded(self):
        expected={ledger.stage(0),ledger.MARKER}
        with self.assertRaises(ValueError):ledger.names(self.root,expected)
        (self.root/ledger.stage(0)).mkdir();(self.root/ledger.MARKER).touch()
        ledger.names(self.root,expected)
        (self.root/'extra').touch()
        with self.assertRaises(ValueError):ledger.names(self.root,expected)
        for value in (True,-1,9):
            with self.assertRaises(ValueError):ledger.stage(value)

    def test_budget_retains_all_stages_and_reserve(self):
        pins=ordered([pin(),pin(1)])
        sample=dict(available_bytes=1_000_000,available_inodes=6,allocation_unit_bytes=4096,read_only=False)
        # Three ledger files + two stage dirs + workspace + marker need 7 entries.
        with patch.object(ledger.space,'probe',return_value=sample),self.assertRaises(ValueError):
            ledger.budget(self.root,(1,2),pins,0)
        sample['available_inodes']=7
        expected=108+258+3*4095+4096+123
        with patch.object(ledger.space,'probe',return_value=sample):
            self.assertEqual(ledger.budget(self.root,(1,2),pins,123),expected)
        for change in ({'available_bytes':expected-1},{'read_only':True}):
            with patch.object(ledger.space,'probe',return_value={**sample,**change}),self.assertRaises(ValueError):
                ledger.budget(self.root,(1,2),pins,123)

    def test_preexisting_workspace_refused_without_backend(self):
        base=self.root/'base';base.mkdir();(base/'genesis').write_bytes(b'x'*108)
        output=self.root/'output';output.mkdir()
        with self.assertRaises(ValueError):ledger.restore(base,pin(),[],output,None,reserve_bytes=0)
        with self.assertRaises(ValueError):ledger.restore(base,pin(),[],base/'inside',None,reserve_bytes=0)
        self.assertEqual(list(output.iterdir()),[])

    def test_archive_damage_fingerprint_never_accepts_links_or_unknown_files(self):
        (self.root/'genesis').write_bytes(b'x'*108)
        before=ledger.archive_snapshot(self.root,Checkpoint.parse(pin()))
        self.assertEqual(len(before[1]),1)
        (self.root/'bad').write_bytes(b'x')
        with self.assertRaises(ValueError):ledger.archive_snapshot(self.root,Checkpoint.parse(pin()))

    @unittest.skipUnless(os.name == 'posix', 'POSIX hardlink/symlink identity checks')
    def test_archive_fingerprint_rejects_actual_links(self):
        genesis=self.root/'genesis'
        raw=b'x'*108
        outside=self.root.parent/(self.root.name+'-outside')
        outside.write_bytes(raw)
        self.addCleanup(lambda: outside.unlink(missing_ok=True))
        genesis.symlink_to(outside)
        with self.assertRaises(ValueError): ledger.archive_snapshot(self.root,Checkpoint.parse(pin()))
        genesis.unlink()
        os.link(outside,genesis)
        with self.assertRaises(ValueError): ledger.archive_snapshot(self.root,Checkpoint.parse(pin()))
        self.assertEqual(outside.read_bytes(),raw)

    def test_transport_refuses_real_failing_children_and_reaps_them(self):
        # An actual Python executable emits ONLY rejecting output or blocks.
        # It never simulates successful native replay or accepted authorization.
        executable=Path(sys.executable).resolve(strict=True)
        digest=hashlib.sha256(executable.read_bytes()).hexdigest()
        backend=RecoveryBackend(executable,digest)
        scripts=("import sys; sys.exit(1)",
                 "import sys; sys.stdout.write('x'*220000)",
                 "import sys; sys.stderr.write('refusal'); sys.stdout.write('{}')",
                 "import time; time.sleep(30)")
        actual=subprocess.Popen
        for script in scripts:
            children=[]
            def launch(*args,**kwargs):
                child=actual(*args,**kwargs); children.append(child); return child
            with self.subTest(script=script), patch.object(transport,'CALL_SECONDS',1), \
                    patch.object(transport.subprocess,'Popen',side_effect=launch):
                with self.assertRaises((ValueError,RuntimeError)):
                    backend._run(['-c',script],Checkpoint.parse(pin()),None,time.monotonic()+10)
            self.assertEqual(len(children),1)
            self.assertIsNotNone(children[0].poll())
            self.assertTrue(children[0].stdout.closed and children[0].stderr.closed)

    def _assert_timeout_after_readers_started(self, slow_preflight=False):
        # Exercise the real wait timeout, not a pre-launch deadline refusal.
        # Only this transport's test clock pauses during hashing/OS startup;
        # subprocess/threading retain their real clocks and bounded waits.
        executable = Path(sys.executable).resolve(strict=True)
        backend = RecoveryBackend(executable, hashlib.sha256(executable.read_bytes()).hexdigest())
        actual_thread, actual_popen = threading.Thread, subprocess.Popen
        actual_check, monotonic = backend.binary._check, time.monotonic
        readers, children, waits, timeouts, joins, checks = [], [], [], [], [], []
        original_waits = []
        armed_at = [None]

        def clock():
            return 100.0 if armed_at[0] is None else 100.0 + monotonic() - armed_at[0]

        def checked():
            value = actual_check()  # Actual executable identity and SHA256.
            checks.append(True)
            if slow_preflight:
                time.sleep(0.03)  # Deliberately longer than the injected 20ms.
            return value

        def delayed_thread(*args, **kwargs):
            target, call_args = kwargs["target"], kwargs["args"]
            started, drained, release = threading.Event(), threading.Event(), threading.Event()
            def run():
                started.set()
                try:
                    target(*call_args)  # Actual pipe read and close on EOF.
                finally:
                    drained.set()
                    release.wait(3)  # Test fail-safe, not a production budget.
            reader = actual_thread(target=run, daemon=kwargs.get("daemon", False))
            original_join = reader.join
            index = len(readers)
            readers.append((reader, started, drained, release, original_join))
            def joined(timeout=None):
                began = monotonic()
                self.assertIsNotNone(timeout)
                self.assertGreater(timeout, 0)
                self.assertLessEqual(timeout, 2)
                self.assertTrue(drained.wait(min(timeout, 1)), "real pipe was not drained")
                self.assertTrue(reader.is_alive(), "delayed reader was not retained until join")
                joins.append(index)
                release.set()  # Only production cleanup's join releases it.
                original_join(timeout=max(0, timeout - (monotonic() - began)))
            reader.join = joined
            return reader

        def launch(*args, **kwargs):
            child = actual_popen(*args, **kwargs)
            children.append(child)
            original_wait = child.wait
            original_waits.append(original_wait)
            def wait(timeout=None):
                waits.append(timeout)
                if len(waits) == 1:
                    self.assertEqual(len(readers), 2, "both real readers must exist")
                    for reader, started, _, _, _ in readers:
                        self.assertTrue(started.wait(1), "reader did not enter its target")
                        self.assertTrue(reader.is_alive())
                    self.assertIsNone(child.poll(), "blocking child exited before timeout")
                    self.assertGreater(timeout, 0)
                    self.assertLessEqual(timeout, 0.020001)
                    armed_at[0] = monotonic()
                    try:
                        return original_wait(timeout=timeout)
                    except subprocess.TimeoutExpired:
                        timeouts.append(True)
                        raise  # Preserve the actual OS-process wait exception.
                return original_wait(timeout=timeout)
            child.wait = wait
            return child

        try:
            with patch.object(transport, "time", SimpleNamespace(monotonic=clock)), \
                    patch.object(transport, "CALL_SECONDS", 0.02), \
                    patch.object(backend.binary, "_check", side_effect=checked), \
                    patch.object(transport.threading, "Thread", side_effect=delayed_thread), \
                    patch.object(transport.subprocess, "Popen", side_effect=launch):
                with self.assertRaisesRegex(transport.BackendError, "^recovery_timeout_retain_outputs$") as raised:
                    backend._run(["-c", "import time; time.sleep(30)"],
                                 Checkpoint.parse(pin()), None, 110.0)
            self.assertIsInstance(raised.exception.__cause__, subprocess.TimeoutExpired)
            self.assertEqual(checks, [True])
            self.assertEqual(timeouts, [True])
            self.assertEqual(len(children), 1)
            self.assertEqual(joins, [0, 1], "both delayed readers require a real join")
            self.assertIsNotNone(children[0].returncode)
            self.assertTrue(all(not item[0].is_alive() for item in readers))
            self.assertTrue(children[0].stdout.closed and children[0].stderr.closed)
        finally:
            # Also collect resources when a regression assertion fails.
            for _, _, _, release, _ in readers:
                release.set()
            for child, wait in zip(children, original_waits):
                if child.poll() is None:
                    child.kill()
                wait(timeout=5)
            for reader, _, _, _, join in readers:
                if reader.ident is not None:
                    join(timeout=2)
                    self.assertFalse(reader.is_alive(), "test left a reader")
            for child in children:
                child.stdout.close()
                child.stderr.close()

    def test_timeout_joins_delayed_drainers_and_closes_both_pipes(self):
        self._assert_timeout_after_readers_started()

    def test_timeout_cleanup_still_reached_after_slow_real_executable_check(self):
        self._assert_timeout_after_readers_started(slow_preflight=True)

    def test_reader_start_failure_reaps_child_and_closes_owned_pipes(self):
        executable = Path(sys.executable).resolve(strict=True)
        backend = RecoveryBackend(executable, hashlib.sha256(executable.read_bytes()).hexdigest())
        real_start, real_popen = threading.Thread.start, subprocess.Popen
        started, children = [], []

        def start(reader):
            if started:
                raise RuntimeError("test_only_reader_start_failure")
            real_start(reader)
            started.append(reader)

        def launch(*args, **kwargs):
            child = real_popen(*args, **kwargs)
            children.append(child)
            return child

        with patch.object(transport.threading.Thread, "start", new=start), \
                patch.object(transport.subprocess, "Popen", side_effect=launch):
            with self.assertRaisesRegex(RuntimeError, "test_only_reader_start_failure"):
                backend._run(["-c", "import time; time.sleep(30)"],
                             Checkpoint.parse(pin()), None, time.monotonic()+10)
        self.assertEqual(len(children), 1)
        self.assertIsNotNone(children[0].returncode)
        self.assertTrue(all(not reader.is_alive() for reader in started))
        self.assertTrue(children[0].stdout.closed and children[0].stderr.closed)

    def test_expired_binary_check_does_not_start_a_new_child(self):
        # Hash the actual Python executable. Advance only the test clock after
        # that check, never supply an accepting recovery or verifier response.
        executable = Path(sys.executable).resolve(strict=True)
        backend = RecoveryBackend(executable, hashlib.sha256(executable.read_bytes()).hexdigest())
        real_check, real_popen = backend.binary._check, subprocess.Popen
        for call_limit, outer_deadline in ((300, 110), (10, 1000), (0.02, 1000)):
            clock, children = [100.0], []
            def delayed_check():
                result = real_check()
                clock[0] = 111.0
                return result
            def launch(*args, **kwargs):
                child = real_popen(*args, **kwargs)
                children.append(child)
                return child
            with self.subTest(call_limit=call_limit), \
                    patch.object(transport, "time", SimpleNamespace(monotonic=lambda: clock[0])), \
                    patch.object(transport, "CALL_SECONDS", call_limit), \
                    patch.object(backend.binary, "_check", side_effect=delayed_check), \
                    patch.object(transport.subprocess, "Popen", side_effect=launch):
                with self.assertRaisesRegex(ValueError, "recovery_deadline_expired"):
                    backend._run(["-c", "import sys; sys.exit(1)"],
                                 Checkpoint.parse(pin()), None, outer_deadline)
                self.assertEqual(children, [], "a command started after its budget expired")

    def test_expired_input_fingerprint_never_reaches_native_recovery(self):
        # A valid public shape is NOT authentication. No accepted native call
        # is mocked: a spent budget must refuse before contacting the backend.
        base = self.root / "base"
        base.mkdir()
        (base / "genesis").write_bytes(b"x" * 108)
        output = self.root / "out"
        snapshot = ledger.archive_snapshot
        clock = [100.0]
        def slow_snapshot(*args, **kwargs):
            result = snapshot(*args, **kwargs)
            clock[0] = 111.0
            return result
        class NoBackend:
            def active(self, *args):
                raise AssertionError("authentication must not start after expiry")
        with patch.object(ledger.time, "monotonic", side_effect=lambda: clock[0]), \
                patch.object(ledger, "CHAIN_SECONDS", 10), \
                patch.object(ledger, "archive_snapshot", side_effect=slow_snapshot):
            with self.assertRaisesRegex(ValueError, "recovery_deadline_expired"):
                ledger.restore(base, pin(), [], output, NoBackend(), reserve_bytes=0)
        self.assertFalse(output.exists())
        self.assertEqual((base / "genesis").read_bytes(), b"x" * 108)

    def test_expired_verify_marker_read_does_not_get_a_fresh_budget(self):
        pins = ordered([pin()])
        folder = self.root / "stage-00"
        folder.mkdir()
        (folder / "genesis").write_bytes(b"x" * 108)
        raw = ledger.marker(pins)
        (self.root / ledger.MARKER).write_bytes(raw)
        read_file, clock = ledger.files.read_file, [100.0]
        def slow_read(*args, **kwargs):
            result = read_file(*args, **kwargs)
            clock[0] = 111.0
            return result
        class NoBackend:
            def active(self, *args):
                raise AssertionError("authentication must not start after expiry")
        with patch.object(ledger.time, "monotonic", side_effect=lambda: clock[0]), \
                patch.object(ledger, "CHAIN_SECONDS", 10), \
                patch.object(ledger.files, "read_file", side_effect=slow_read):
            with self.assertRaisesRegex(ValueError, "recovery_deadline_expired"):
                ledger.verify(self.root, [pin()], NoBackend())
        self.assertEqual((self.root / ledger.MARKER).read_bytes(), raw)

    def test_reader_construction_failure_reaps_child_and_closes_pipes(self):
        executable = Path(sys.executable).resolve(strict=True)
        backend = RecoveryBackend(executable, hashlib.sha256(executable.read_bytes()).hexdigest())
        real_popen, children = subprocess.Popen, []
        def launch(*args, **kwargs):
            child = real_popen(*args, **kwargs)
            children.append(child)
            return child
        try:
            with patch.object(transport.threading, "Thread", side_effect=RuntimeError("test_reader_allocation")), \
                    patch.object(transport.subprocess, "Popen", side_effect=launch):
                with self.assertRaisesRegex(RuntimeError, "test_reader_allocation"):
                    backend._run(["-c", "import time; time.sleep(30)"],
                                 Checkpoint.parse(pin()), None, time.monotonic() + 10)
            self.assertEqual(len(children), 1)
            self.assertIsNotNone(children[0].returncode, "reader construction orphaned a child")
            self.assertTrue(children[0].stdout.closed and children[0].stderr.closed)
        finally:
            # The red test exercises an actual old leak; do not leak its child.
            for child in children:
                if child.poll() is None:
                    child.kill()
                    child.wait(timeout=5)
                child.stdout.close()
                child.stderr.close()

    def test_ordinary_cli_no_cache_and_redacted_syntax_error(self):
        bundle=self.root/'bundle';bundle.mkdir()
        names=('ledger_restore.py','ledger_recovery_backend.py','wallet_backup.py','wallet_backup_backend.py',
               'wallet_health.py','wallet_archive.py','zevune_wallet.py')
        for name in names:shutil.copyfile(Path(ledger.__file__).parent/name,bundle/name)
        before={p.name:p.read_bytes() for p in bundle.iterdir()}
        env=os.environ.copy()
        for name in ('PYTHONDONTWRITEBYTECODE','PYTHONPYCACHEPREFIX'):env.pop(name,None)
        for args,code in ((['--help'],0),(['--no-real-funds','restore','--help'],0),(['--secret','SENTINEL'],64)):
            result=subprocess.run([sys.executable,str(bundle/'ledger_restore.py'),*args],env=env,capture_output=True,timeout=20)
            self.assertEqual(result.returncode,code)
            self.assertNotIn(b'SENTINEL',result.stdout+result.stderr)
        self.assertEqual({p.name:p.read_bytes() for p in bundle.iterdir()},before)


if __name__ == '__main__':unittest.main()
