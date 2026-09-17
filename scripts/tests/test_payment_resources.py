"""Resource evidence schema, PID identity and native OS measurement checks."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import check_payment_resources as resource


def event(seq):
    phase, height, generation = resource.PHASES[seq - 1]
    records = [2 + height + (height + 1) // 2, 2 + height + height // 2]
    if seq == 8:
        records[0] += 1
    return {
        "schema_version": 1, "seq": seq, "phase": phase, "height": height,
        "paid_blocks": height, "elapsed_ms": seq * 100,
        "processes": [{"role": "worker", "generation": generation, "pid": 20 + generation},
                      {"role": "scenario", "generation": 1, "pid": 30}],
        "state": {"commitments": 2 + height * 2, "nullifiers": height * 2,
                  "fees": height * 1000, "logical_bytes": 140 + height * 9352,
                  "segments": 1 if height else 0, "tail_bytes": height * 9352},
        "wallets": [{"records_used": n, "file_bytes": 72 + 32948 * n} for n in records],
    }


def stat(pid=20, parent=10, creation=123, state="S", comm="worker (held) )"):
    fields = [state, str(parent)] + ["0"] * 17 + [str(creation)]
    return f"{pid} ({comm}) " + " ".join(fields) + "\n"


def progress_sequence():
    records = []

    def pair(operation, payment, committed):
        start = {"schema_version": 1, "seq": len(records) + 1, "operation": operation,
                 "payment_index": payment, "committed_blocks": committed, "status": "started"}
        records.append(start)
        end = dict(start, seq=len(records) + 1, status="completed", duration_ms=1)
        if operation == "worker_commit":
            end["committed_blocks"] += 1
        records.append(end)

    pair("scenario_start", 0, 0)
    pair("worker_create", 0, 0)
    pair("wallet_sync", 0, 0)
    for payment in range(1, 34):
        pair("prepare", payment, payment - 1)
        if payment == 33:
            pair("outbox_restore", 33, 32)
        for operation in resource.CORE_OPERATIONS[1:]:
            pair(operation, payment, payment if operation in {"scenario_apply", "wallet_sync"} else payment - 1)
        if payment in (8, 16, 24, 32, 33):
            pair("duplicate_rejection", 0, payment)
        if payment == 32:
            pair("worker_close", 0, 32)
            pair("disk_check", 0, 32)
            pair("worker_reopen", 0, 32)
            pair("wallet_recover", 0, 32)
    pair("worker_close", 0, 33)
    pair("disk_check", 0, 33)
    pair("finish", 0, 33)
    return records


def result_value():
    final = event(9)
    return {
        "schema_version": 1, "complete": True, "paid_blocks": 33, "height": 33,
        "actions_per_payment": 2, **final["state"],
        "wallet_records": [item["records_used"] for item in final["wallets"]],
        "wallet_bytes": [item["file_bytes"] for item in final["wallets"]],
        "checks": {key: True for key in resource.CHECKS},
        "timings": {"total_ms": 2000, "operations": [entry for entry in progress_sequence()
                                                    if entry["status"] == "completed"]},
    }


def validated_progress_prefix(records):
    pending = None
    for seq, entry in enumerate(records, 1):
        resource.checked_progress(entry, seq, pending)
        pending = entry if entry["status"] == "started" else None
    return pending


class FakeProbe:
    def __init__(self, pid, parent_pid):
        creation = "1" if pid == 99 else str(100 + pid)
        self.identity = resource.ProcessIdentity(pid, parent_pid, creation, "test_creation")
        self.alive = True
        self.peak = 2 << 20
        self.closed = False

    def verify(self):
        if not self.alive:
            raise resource.MeasurementError("process_not_live")

    def sample(self):
        self.verify()
        return resource.MemorySample(self.identity, 1 << 20, self.peak, "synthetic_test_only")

    def is_alive(self):
        return self.alive

    def terminate(self):
        self.alive = False

    def close(self):
        self.closed = True


class RecordingWriter:
    def __init__(self):
        self.last = None

    def save(self, evidence):
        self.last = copy.deepcopy(evidence)


class ResourceSchemaTests(unittest.TestCase):
    def test_all_nine_exact_checkpoints_and_pending_wallet_record(self):
        for seq in range(1, 10):
            value = event(seq)
            self.assertIs(resource.checked_event(value, seq), value)
            self.assertEqual(resource.decode_json(json.dumps(value).encode()), value)
        self.assertEqual([v["records_used"] for v in event(8)["wallets"]], [51, 50])
        self.assertEqual([v["records_used"] for v in event(9)["wallets"]], [52, 51])

    def test_unsigned_numbers_reject_booleans_floats_and_out_of_bounds(self):
        for value in (True, False, -1, 1.0, "1", None, 1 << 64):
            with self.subTest(value=value), self.assertRaises(resource.MeasurementError):
                resource.checked_uint(value)
        self.assertEqual(resource.checked_uint(0), 0)
        self.assertEqual(resource.checked_uint((1 << 64) - 1), (1 << 64) - 1)

    def test_json_duplicates_nonfinite_scalars_and_oversize_rejected(self):
        for raw in (b'{"seq":1,"seq":2}', b'{"seq":NaN}', b'{"seq":Infinity}',
                    b'[]', b'null', b'"secret"', b'\xff', b'{}' + b' ' * 16384):
            with self.subTest(raw=raw[:30]), self.assertRaises(resource.MeasurementError):
                resource.decode_json(raw)

    def test_unknown_and_missing_fields_cannot_enter_evidence(self):
        for extra in (True, False):
            value = event(1)
            if extra:
                value["private_witness"] = "must never be copied"
            else:
                del value["state"]
            with self.assertRaises(resource.MeasurementError):
                resource.checked_event(value, 1)
        for field in ("processes", "wallets", "state"):
            value = event(1)
            target = value[field][0] if isinstance(value[field], list) else value[field]
            target["extra"] = 0
            with self.assertRaises(resource.MeasurementError):
                resource.checked_event(value, 1)

    def test_wrong_phase_height_generation_or_pid_cannot_claim_checkpoint(self):
        changes = [("phase", "complete_33"), ("height", 33), ("paid_blocks", True),
                   ("seq", 2), ("schema_version", 2), ("elapsed_ms", 1200001)]
        for key, change in changes:
            value = event(1)
            value[key] = change
            with self.subTest(key=key), self.assertRaises(resource.MeasurementError):
                resource.checked_event(value, 1)
        for field, change in (("generation", 1), ("pid", 0), ("pid", True),
                              ("role", "go")):
            value = event(6)
            value["processes"][0][field] = change
            with self.assertRaises(resource.MeasurementError):
                resource.checked_event(value, 6)
        for field in ("pid", "role"):
            value = event(1)
            value["processes"][1][field] = value["processes"][0][field]
            with self.assertRaises(resource.MeasurementError):
                resource.checked_event(value, 1)

    def test_wallet_and_capacity_counts_are_checked_not_just_types(self):
        for field, change in (("commitments", 18), ("nullifiers", 31), ("fees", 15999),
                              ("logical_bytes", 140), ("segments", 0), ("tail_bytes", 1 << 21)):
            value = event(3)
            value["state"][field] = change
            with self.subTest(field=field), self.assertRaises(resource.MeasurementError):
                resource.checked_event(value, 3)
        for field in ("records_used", "file_bytes"):
            value = event(8)
            value["wallets"][0][field] -= 1
            with self.assertRaises(resource.MeasurementError):
                resource.checked_event(value, 8)

    def test_budget_keeps_valid_over_budget_measurement(self):
        identity = resource.ProcessIdentity(20, 10, "123", "test")
        sample = resource.MemorySample(identity, 1024, 1 << 30, "test")
        resource.check_budget(sample)
        over = resource.MemorySample(identity, 1024, (1 << 30) + 1, "test")
        before = over.public()
        with self.assertRaisesRegex(resource.MeasurementError, "budget_exceeded"):
            resource.check_budget(over)
        self.assertEqual(over.public(), before)
        for current, peak in ((0, 0), (100, 99), (True, 100)):
            with self.assertRaises(resource.MeasurementError):
                resource.checked_memory(current, peak)


class LinuxParserTests(unittest.TestCase):
    def test_proc_stat_parentheses_identity_and_creation(self):
        value = resource.linux_identity(stat(), 20)
        self.assertEqual((value.pid, value.parent_pid, value.creation_identity), (20, 10, "123"))
        self.assertNotIn("worker", str(value))
        for raw in (stat(state="Z"), stat(state="X"), stat(creation=0),
                    stat(parent=-1), stat(pid=21), "20 (broken"):
            with self.subTest(raw=raw[:30]), self.assertRaises(resource.MeasurementError):
                resource.linux_identity(raw, 20)

    def test_memory_requires_exact_kib_fields_and_positive_consistent_values(self):
        self.assertEqual(resource.linux_memory("Name:\tignored\nVmHWM:\t2048 kB\nVmRSS:\t1024 kB\n"),
                         (1 << 20, 2 << 20))
        for raw in ("VmRSS: 1 kB", "VmRSS: 1 kB\nVmHWM: 2 MB",
                    "VmRSS: 0 kB\nVmHWM: 2 kB", "VmRSS: 3 kB\nVmHWM: 2 kB",
                    "VmRSS: 1 kB\nVmHWM: 2 kB\nVmRSS: 1 kB"):
            with self.subTest(raw=raw), self.assertRaises(resource.MeasurementError):
                resource.linux_memory(raw)

    @unittest.skipUnless(sys.platform == "linux", "Linux proc descriptor semantics")
    def test_proc_pinned_identity_rechecks_both_sides_of_memory_read(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "20").mkdir()
            (root / "20" / "stat").write_text(stat())
            (root / "20" / "status").write_text("VmRSS: 1 kB\nVmHWM: 2 kB\n")
            probe = resource.LinuxProcessProbe(20, 10, root)
            try:
                self.assertEqual(probe.sample().current_bytes, 1024)
                with mock.patch.object(probe, "_identity", side_effect=[probe.identity,
                        resource.ProcessIdentity(20, 10, "124", "linux_proc_starttime_ticks")]):
                    with self.assertRaisesRegex(resource.MeasurementError, "identity_changed"):
                        probe.sample()
                (root / "20" / "stat").write_text(stat(parent=11))
                with self.assertRaisesRegex(resource.MeasurementError, "identity_changed"):
                    probe.sample()
            finally:
                probe.close()
            with self.assertRaisesRegex(resource.MeasurementError, "probe_closed"):
                probe.sample()


class ProgressAndResultTests(unittest.TestCase):
    def test_full_operation_sequence_is_paired_and_final_result_matches(self):
        records = progress_sequence()
        pending = None
        for seq, record in enumerate(records, 1):
            resource.checked_progress(record, seq, pending)
            pending = record if record["status"] == "started" else None
        self.assertIsNone(pending)
        resource.checked_result(result_value(), [event(n) for n in range(1, 10)], records)

    def test_unfinished_operation_has_no_fabricated_duration(self):
        records = progress_sequence()
        index = next(index for index, entry in enumerate(records)
                     if entry["operation"] == "worker_commit" and entry["payment_index"] == 33
                     and entry["status"] == "started")
        start = records[index]
        self.assertEqual(validated_progress_prefix(records[:index + 1]), start)
        self.assertNotIn("duration_ms", start)
        for change in (dict(start, duration_ms=0), dict(start, status="completed"),
                       dict(start, status=[]), dict(start, payment_index=True),
                       dict(start, committed_blocks=33)):
            with self.assertRaises(resource.MeasurementError):
                resource.checked_progress(change, start["seq"], None)
        with self.assertRaisesRegex(resource.MeasurementError, "overlapping"):
            resource.checked_progress(start, start["seq"], start)

    def test_progress_completion_must_match_operation_payment_and_commit_count(self):
        records = progress_sequence()
        index = next(index for index, entry in enumerate(records)
                     if entry["operation"] == "worker_commit" and entry["payment_index"] == 33
                     and entry["status"] == "started")
        start, complete = records[index:index + 2]
        self.assertEqual(validated_progress_prefix(records[:index + 1]), start)
        resource.checked_progress(complete, complete["seq"], start)
        for key, value in (("seq", complete["seq"] + 1), ("duration_ms", True), ("committed_blocks", 32),
                           ("operation", "scenario_apply"), ("payment_index", 32)):
            with self.subTest(key=key), self.assertRaises(resource.MeasurementError):
                resource.checked_progress(dict(complete, **{key: value}), complete["seq"], start)

    def test_final_result_does_not_accept_empty_tests_missing_checks_or_edited_timings(self):
        events, records = [event(n) for n in range(1, 10)], progress_sequence()
        for change in (dict(result_value(), complete=False), dict(result_value(), paid_blocks=True),
                       dict(result_value(), wallet_records=[52, 50])):
            with self.assertRaises(resource.MeasurementError):
                resource.checked_result(change, events, records)
        for altered_records in ([], records[:-1], records[:-2]):
            with self.assertRaises(resource.MeasurementError):
                resource.checked_result(result_value(), events, altered_records)
        for target in ("checks", "timings"):
            value = result_value()
            if target == "checks":
                value["checks"]["genuine_payments"] = 1
            else:
                value["timings"]["operations"][0]["duration_ms"] = True
            with self.assertRaises(resource.MeasurementError):
                resource.checked_result(value, events, records)
        repeated = copy.deepcopy(records)
        completed = [entry for entry in repeated if entry["status"] == "completed"]
        completed[4]["payment_index"] = 2
        value = result_value()
        value["timings"]["operations"] = completed
        with self.assertRaisesRegex(resource.MeasurementError, "unexpected_progress_step"):
            resource.checked_result(value, events, repeated)


class PersistenceAndCollectorTests(unittest.TestCase):
    def test_evidence_reservation_never_overwrites_user_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "report.json"
            path.write_text("existing user data")
            with self.assertRaisesRegex(resource.MeasurementError, "output_already_exists"):
                resource.EvidenceFile(path, resource.initial_evidence())
            self.assertEqual(path.read_text(), "existing user data")
            path.unlink()
            evidence = resource.initial_evidence()
            writer = resource.EvidenceFile(path, evidence)
            evidence["status"] = "failed"
            evidence["failures"] = [{"error_code": "test_failure"}]
            writer.save(evidence)
            self.assertEqual(json.loads(path.read_text()), evidence)
            path.unlink()
            path.write_text("replacement user data")
            with self.assertRaisesRegex(resource.MeasurementError, "output_identity_changed"):
                writer.save(evidence)
            self.assertEqual(path.read_text(), "replacement user data")

    def test_budget_failure_preserves_valid_sample_and_sends_negative_ack(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            evidence, writer = resource.initial_evidence(), RecordingWriter()

            def probe_factory(pid, parent):
                probe = FakeProbe(pid, parent)
                if pid == 21:
                    probe.peak = (1 << 30) + 1
                return probe

            collector = resource.ProtocolCollector(directory, evidence, writer, 99, probe_factory)
            try:
                (directory / "event-01.json").write_text(json.dumps(event(1)))
                with self.assertRaisesRegex(resource.MeasurementError, "budget_exceeded"):
                    collector.events()
                checkpoint = writer.last["memory_checkpoints"][0]
                self.assertFalse(checkpoint["measurement_complete"])
                self.assertEqual(checkpoint["samples"][0]["os_lifetime_peak_bytes"], (1 << 30) + 1)
                ack = json.loads((directory / "ack-01.json").read_text())
                self.assertFalse(ack["ok"])
                self.assertEqual(ack["error_code"], "resident_memory_budget_exceeded")
            finally:
                collector.close()

    def test_pid_change_parent_failure_and_missing_metric_cannot_be_success(self):
        for failure in ("pid", "parent", "sample"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as temporary:
                directory = Path(temporary)
                evidence, writer = resource.initial_evidence(), RecordingWriter()
                collector = resource.ProtocolCollector(directory, evidence, writer, 99, FakeProbe)
                try:
                    (directory / "event-01.json").write_text(json.dumps(event(1)))
                    collector.events()
                    second = event(2)
                    if failure == "pid":
                        second["processes"][0]["pid"] += 10
                    elif failure == "parent":
                        collector.parent.alive = False
                    else:
                        collector.probes[("worker", 1)].sample = mock.Mock(
                            side_effect=resource.MeasurementError("missing_linux_memory"))
                    (directory / "event-02.json").write_text(json.dumps(second))
                    with self.assertRaises(resource.MeasurementError):
                        collector.events()
                    self.assertFalse(writer.last["memory_checkpoints"][-1]["measurement_complete"])
                    self.assertTrue(writer.last["memory_checkpoints"][0]["measurement_complete"])
                finally:
                    collector.close()

    def test_progress_failure_keeps_confirmed_count_and_uncertain_commit(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            evidence, writer = resource.initial_evidence(), RecordingWriter()
            collector = resource.ProtocolCollector(directory, evidence, writer, 99, FakeProbe)
            try:
                records = progress_sequence()
                index = next(index for index, entry in enumerate(records)
                             if entry["operation"] == "worker_commit" and entry["payment_index"] == 33
                             and entry["status"] == "started")
                prefix, start = records[:index + 1], records[index]
                for entry in prefix:
                    (directory / f"progress-{entry['seq']:04d}.json").write_text(json.dumps(entry))
                collector.progress()
                self.assertEqual(writer.last["last_confirmed_committed_blocks"], 32)
                self.assertTrue(writer.last["commit_outcome_uncertain"])
                self.assertEqual(writer.last["unfinished_operation"], start)
                self.assertNotIn("duration_ms", writer.last["unfinished_operation"])
                (directory / f"progress-{start['seq'] + 2:04d}.json").write_text("{}")
                with self.assertRaisesRegex(resource.MeasurementError, "sequence_gap"):
                    collector.check_names()
                self.assertEqual(len(writer.last["progress"]), len(prefix))
            finally:
                collector.close()

    def test_complete_evidence_requires_all_children_stopped_and_immutable_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            evidence, writer = resource.initial_evidence(), RecordingWriter()
            collector = resource.ProtocolCollector(directory, evidence, writer, 99, FakeProbe)
            try:
                for entry in progress_sequence():
                    (directory / f"progress-{entry['seq']:04d}.json").write_text(json.dumps(entry))
                collector.progress()
                for seq in range(1, 10):
                    (directory / f"event-{seq:02d}.json").write_text(json.dumps(event(seq)))
                    collector.events()
                (directory / "result.json").write_text(json.dumps(result_value()))
                with self.assertRaisesRegex(resource.MeasurementError, "child_still_alive"):
                    collector.finish()
                for probe in collector.probes.values():
                    probe.alive = False
                collector.finish()
                self.assertEqual(writer.last["result"]["paid_blocks"], 33)
                self.assertEqual(len(collector.probes), 3)
                (directory / "event-01.json").write_text(json.dumps(event(1), indent=2))
                with self.assertRaisesRegex(resource.MeasurementError, "immutable_protocol_record_changed"):
                    collector.check_names(final=True)
            finally:
                collector.close()

    def test_metadata_failure_still_saves_start_and_failure_without_exception_text(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            output = directory / "report.json"
            with mock.patch.object(resource, "collect_metadata", side_effect=OSError("SECRET must not be saved")):
                code = resource.run(directory / "test", directory / "worker", directory / "scenario", output)
            self.assertEqual(code, 1)
            raw = output.read_text()
            evidence = json.loads(raw)
            self.assertNotIn("SECRET", raw)
            self.assertEqual(evidence["status"], "failed")
            self.assertEqual(evidence["failures"], [{"error_code": "supervisor_operation_failed"}])
            self.assertIn("started_at_utc", evidence)

    def test_collector_initialization_failure_reaps_started_coordinator(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            executable = directory / "test"
            executable.write_bytes(b"synthetic")
            process = mock.Mock()
            process.returncode = -9
            output = directory / "report.json"
            with mock.patch.object(resource, "collect_metadata", return_value={}), \
                    mock.patch.object(resource.subprocess, "Popen", return_value=process), \
                    mock.patch.object(resource, "ProtocolCollector", side_effect=resource.MeasurementError("process_open_failed")), \
                    mock.patch.object(resource, "stop_test") as stop:
                code = resource.run(executable, executable, executable, output)
            self.assertEqual(code, 1)
            stop.assert_called_once_with(process, None)
            self.assertEqual(json.loads(output.read_text())["go_exit_code"], -9)


class NativeMemoryTests(unittest.TestCase):
    def test_unsupported_platform_is_failure_not_skip_or_zero(self):
        with mock.patch.object(resource.sys, "platform", "unsupported"):
            with self.assertRaisesRegex(resource.MeasurementError, "unsupported_memory_platform"):
                resource.open_process(os.getpid(), os.getppid())

    def test_live_self_sample_uses_real_os_counters(self):
        probe = resource.open_process(os.getpid(), os.getppid())
        try:
            first, second = probe.sample(), probe.sample()
            self.assertEqual(first.identity, second.identity)
            self.assertGreater(first.current_bytes, 0)
            self.assertGreaterEqual(first.os_lifetime_peak_bytes, first.current_bytes)
            self.assertIn("identity", first.public())
        finally:
            probe.close()

    def test_direct_child_parent_identity_exit_and_current_rss(self):
        child = subprocess.Popen([sys.executable, "-c", "import sys; memory=bytearray(4<<20); "
                                  "print('ready', flush=True); sys.stdin.readline()"],
                                 stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                 stderr=subprocess.DEVNULL, text=True)
        probe = None
        try:
            self.assertEqual(child.stdout.readline().strip(), "ready")
            with self.assertRaisesRegex(resource.MeasurementError, "unexpected_parent_process"):
                resource.open_process(child.pid, os.getpid() + 1)
            probe = resource.open_process(child.pid, os.getpid())
            sample = probe.sample()
            self.assertEqual(sample.identity.parent_pid, os.getpid())
            self.assertGreater(sample.current_bytes, 4 << 20)
            child.stdin.close()
            child.wait(timeout=10)
            with self.assertRaises(resource.MeasurementError):
                probe.sample()
        finally:
            if child.poll() is None:
                child.kill()
                child.wait(timeout=10)
            if child.stdin and not child.stdin.closed:
                child.stdin.close()
            if child.stdout:
                child.stdout.close()
            if probe:
                probe.close()


if __name__ == "__main__":
    unittest.main()
