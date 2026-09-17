"""Failure evidence and fixed protocol completeness, never payment verification.

All protocol fixtures and process probes here are explicitly synthetic. They
exercise the supervisor's accounting and persistence contract only; no fixture
is an Orchard verifier, a real payment, or a native resource measurement.
"""
from contextlib import contextmanager
import copy
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

import test_payment_resources as fixtures

resource = fixtures.resource


def publish(directory, name, value):
    with (directory / name).open("x", encoding="utf-8") as output:
        json.dump(value, output, sort_keys=True)


def resequence(records):
    result = copy.deepcopy(records)
    for seq, record in enumerate(result, 1):
        record["seq"] = seq
    return result


def result_for(records):
    value = fixtures.result_value()
    value["timings"]["operations"] = [copy.deepcopy(entry) for entry in records
                                         if entry["status"] == "completed"]
    return value


def validate_progress(records):
    pending = None
    for seq, entry in enumerate(records, 1):
        resource.checked_progress(entry, seq, pending)
        pending = entry if entry["status"] == "started" else None
    return pending


class EvidenceCompletenessTests(unittest.TestCase):
    def test_fixture_has_exact_fixed_go_operation_contract(self):
        # The fixture must keep the 32+1 schedule even if implementation
        # constants change. This is a schema count, not payment test evidence.
        records = fixtures.progress_sequence()
        completed = [entry for entry in records if entry["status"] == "completed"]
        self.assertEqual((len(records), len(completed)), (362, 181))
        self.assertIsNone(validate_progress(records))
        core = [(entry["operation"], entry["payment_index"]) for entry in completed
                if entry["payment_index"] and entry["operation"] != "outbox_restore"]
        self.assertEqual(core, [(operation, n) for n in range(1, 34)
                                for operation in ("prepare", "candidate", "worker_commit",
                                                  "scenario_apply", "wallet_sync")])
        tail = [(entry["operation"], entry["payment_index"], entry["committed_blocks"])
                for entry in completed[-3:]]
        self.assertEqual(tail, [("worker_close", 0, 33), ("disk_check", 0, 33), ("finish", 0, 33)])
        encoded = json.dumps(result_for(records), separators=(",", ":")).encode()
        self.assertLessEqual(len(encoded), 65536)

    def test_removing_whole_core_pair_cannot_be_hidden_by_matching_timings(self):
        events = [fixtures.event(n) for n in range(1, 10)]
        for operation in ("prepare", "candidate", "worker_commit", "scenario_apply", "wallet_sync"):
            records = resequence([entry for entry in fixtures.progress_sequence()
                                  if (entry["operation"], entry["payment_index"]) != (operation, 17)])
            self.assertIsNone(validate_progress(records))
            with self.subTest(operation=operation), self.assertRaisesRegex(
                    resource.MeasurementError, "payment_operations"):
                resource.checked_result(result_for(records), events, records)

    def test_reordering_complete_core_pairs_is_not_a_valid_timing_result(self):
        records = fixtures.progress_sequence()
        prepare = next(index for index, entry in enumerate(records)
                       if entry["operation"] == "prepare" and entry["payment_index"] == 16)
        records[prepare:prepare + 4] = records[prepare + 2:prepare + 4] + records[prepare:prepare + 2]
        records = resequence(records)
        self.assertIsNone(validate_progress(records))
        with self.assertRaisesRegex(resource.MeasurementError, "payment_operations"):
            resource.checked_result(result_for(records), [fixtures.event(n) for n in range(1, 10)], records)

    def test_missing_or_repeated_recovery_pair_cannot_claim_complete_recovery(self):
        for operation in ("worker_reopen", "wallet_recover", "outbox_restore", "disk_check"):
            original = fixtures.progress_sequence()
            pair = [entry for entry in original if entry["operation"] == operation
                    and entry["committed_blocks"] == 32]
            self.assertEqual(len(pair), 2)
            for remove in (True, False):
                if remove:
                    records = [entry for entry in original if entry not in pair]
                else:
                    index = original.index(pair[0])
                    records = original[:index] + copy.deepcopy(pair) + original[index:]
                records = resequence(records)
                self.assertIsNone(validate_progress(records))
                with self.subTest(operation=operation, remove=remove), self.assertRaisesRegex(
                        resource.MeasurementError, "recovery_operations"):
                    resource.checked_result(result_for(records), [fixtures.event(n) for n in range(1, 10)], records)

    def test_recovery_cannot_be_recorded_at_a_different_committed_height(self):
        for operation in ("worker_reopen", "wallet_recover", "outbox_restore"):
            start = copy.deepcopy(next(entry for entry in fixtures.progress_sequence()
                                       if entry["operation"] == operation and entry["status"] == "started"))
            for height in (0, 31, 33):
                changed = dict(start, committed_blocks=height)
                with self.subTest(operation=operation, height=height), self.assertRaisesRegex(
                        resource.MeasurementError, "progress_scope"):
                    resource.checked_progress(changed, changed["seq"], None)

    def test_every_one_of_nine_checkpoints_is_required(self):
        events, records = [fixtures.event(n) for n in range(1, 10)], fixtures.progress_sequence()
        for missing in range(9):
            with self.subTest(missing=missing + 1), self.assertRaisesRegex(
                    resource.MeasurementError, "incomplete_checkpoint"):
                resource.checked_result(result_for(records), events[:missing] + events[missing + 1:], records)


class EvidenceCollectorBoundaryTests(unittest.TestCase):
    @contextmanager
    def collector(self, persistent=False, factory=fixtures.FakeProbe):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            directory = root / "protocol"
            directory.mkdir()
            evidence = resource.initial_evidence()
            report = root / "report.json"
            writer = resource.EvidenceFile(report, evidence) if persistent else fixtures.RecordingWriter()
            collector = resource.ProtocolCollector(directory, evidence, writer, 99, factory)
            try:
                yield collector, evidence, directory, report
            finally:
                collector.close()

    def populate(self, collector, directory):
        for entry in fixtures.progress_sequence():
            publish(directory, f"progress-{entry['seq']:04d}.json", entry)
        collector.progress()
        for seq in range(1, 10):
            publish(directory, f"event-{seq:02d}.json", fixtures.event(seq))
            collector.events()
        for probe in collector.probes.values():
            probe.alive = False

    def test_complete_checkpoints_without_result_file_are_still_failure(self):
        with self.collector() as (collector, evidence, directory, _report):
            self.populate(collector, directory)
            with self.assertRaisesRegex(resource.MeasurementError, "protocol_file_read_failed"):
                collector.finish()
            self.assertFalse(collector.result_seen)
            self.assertIsNone(evidence["result"])
            self.assertEqual(len(evidence["events"]), 9)

    def test_numeric_measurement_complete_cannot_stand_in_for_true(self):
        with self.collector() as (collector, evidence, directory, _report):
            self.populate(collector, directory)
            publish(directory, "result.json", fixtures.result_value())
            evidence["memory_checkpoints"][-1]["measurement_complete"] = 1
            with self.assertRaisesRegex(resource.MeasurementError, "incomplete_memory_measurement"):
                collector.finish()
            self.assertFalse(collector.result_seen)

    def test_same_height_recovery_cannot_change_capacity(self):
        with self.collector() as (collector, evidence, directory, _report):
            for seq in range(1, 6):
                publish(directory, f"event-{seq:02d}.json", fixtures.event(seq))
                collector.events()
            changed = fixtures.event(6)
            changed["state"]["logical_bytes"] += 150
            changed["state"]["tail_bytes"] += 150
            resource.checked_event(changed, 6)  # Individually well-formed, but not the same ledger.
            publish(directory, "event-06.json", changed)
            with self.assertRaisesRegex(resource.MeasurementError, "recovery_changed_state"):
                collector.events()
            self.assertEqual(len(evidence["events"]), 5)
            ack = json.loads((directory / "ack-06.json").read_text())
            self.assertIs(ack["ok"], False)

    def test_second_role_over_budget_retains_both_samples_in_real_report(self):
        def factory(pid, parent):
            probe = fixtures.FakeProbe(pid, parent)
            if pid == 30:
                probe.peak = resource.MEMORY_BUDGET_BYTES + 1
            return probe

        with self.collector(persistent=True, factory=factory) as (collector, _evidence, directory, report):
            publish(directory, "event-01.json", fixtures.event(1))
            with self.assertRaisesRegex(resource.MeasurementError, "budget_exceeded"):
                collector.events()
            saved = json.loads(report.read_text())
            checkpoint = saved["memory_checkpoints"][0]
            self.assertIs(checkpoint["measurement_complete"], False)
            self.assertEqual([sample["role"] for sample in checkpoint["samples"]], ["worker", "scenario"])
            self.assertEqual(checkpoint["samples"][1]["os_lifetime_peak_bytes"], resource.MEMORY_BUDGET_BYTES + 1)
            self.assertIs(json.loads((directory / "ack-01.json").read_text())["ok"], False)

    def test_report_save_failure_does_not_acknowledge_success(self):
        with self.collector(persistent=True) as (collector, _evidence, directory, report):
            before = report.read_bytes()
            publish(directory, "event-01.json", fixtures.event(1))
            with mock.patch.object(resource.os, "replace", side_effect=OSError("not public diagnostic")):
                with self.assertRaisesRegex(resource.MeasurementError, "evidence_save_failed"):
                    collector.events()
            self.assertEqual(report.read_bytes(), before)
            ack = json.loads((directory / "ack-01.json").read_text())
            self.assertEqual(ack, {"schema_version": 1, "seq": 1, "ok": False,
                                   "error_code": "evidence_save_failed"})
            self.assertEqual(list(report.parent.glob("report.json.*.tmp")), [])

    def test_unvalidated_fields_never_enter_failure_report_or_ack(self):
        with self.collector(persistent=True) as (collector, evidence, directory, report):
            event = fixtures.event(1)
            event["private_witness"] = "UNTRUSTED_PRIVATE_CONTENT"
            publish(directory, "event-01.json", event)
            with self.assertRaisesRegex(resource.MeasurementError, "invalid_object_fields"):
                collector.events()
            self.assertEqual(evidence["events"], [])
            self.assertNotIn("UNTRUSTED_PRIVATE_CONTENT", report.read_text())
            self.assertNotIn("UNTRUSTED_PRIVATE_CONTENT", (directory / "ack-01.json").read_text())

    def test_commit_completion_changes_confirmed_count_without_inventing_apply_success(self):
        records = fixtures.progress_sequence()
        index = next(index for index, entry in enumerate(records)
                     if entry["operation"] == "worker_commit" and entry["payment_index"] == 33
                     and entry["status"] == "started")
        with self.collector() as (collector, evidence, directory, _report):
            for entry in records[:index + 1]:
                publish(directory, f"progress-{entry['seq']:04d}.json", entry)
            collector.progress()
            self.assertEqual(evidence["last_confirmed_committed_blocks"], 32)
            self.assertIs(evidence["commit_outcome_uncertain"], True)
            self.assertNotIn("duration_ms", evidence["unfinished_operation"])
            for entry in records[index + 1:index + 3]:
                publish(directory, f"progress-{entry['seq']:04d}.json", entry)
            collector.progress()
            self.assertEqual(evidence["last_confirmed_committed_blocks"], 33)
            self.assertIs(evidence["commit_outcome_uncertain"], False)
            self.assertEqual(evidence["unfinished_operation"]["operation"], "scenario_apply")
            self.assertNotIn("duration_ms", evidence["unfinished_operation"])
            self.assertIsNone(evidence["result"])

    def test_zero_exit_without_checkpoints_is_not_successful_acceptance(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            executable = root / "fixture-binary"
            executable.write_bytes(b"protocol fixture only")
            process = mock.Mock(pid=99, returncode=0)
            process.poll.return_value = 0
            process.wait.return_value = 0
            real_collector = resource.ProtocolCollector

            def collector_factory(directory, evidence, writer, pid):
                return real_collector(directory, evidence, writer, pid, fixtures.FakeProbe)

            output = root / "report.json"
            with mock.patch.object(resource, "collect_metadata", return_value={}), \
                    mock.patch.object(resource.subprocess, "Popen", return_value=process), \
                    mock.patch.object(resource, "ProtocolCollector", side_effect=collector_factory):
                code = resource.run(executable, executable, executable, output)
            evidence = json.loads(output.read_text())
            self.assertEqual(code, 1)
            self.assertEqual(evidence["go_exit_code"], 0)
            self.assertEqual(evidence["status"], "failed")
            self.assertEqual(evidence["events"], [])
            self.assertIsNone(evidence["result"])
            self.assertIn({"error_code": "incomplete_memory_measurement"}, evidence["failures"])
            self.assertEqual(evidence["cleanup"]["registered_processes"], 0)
            self.assertIs(evidence["cleanup"]["initial_roles_registered"], False)
            self.assertIs(evidence["cleanup"]["registered_children_exit_confirmed"], False)
            self.assertIs(evidence["cleanup"]["precheckpoint_child_tree_cleanup_confirmed"], False)
            process.kill.assert_not_called()

    def test_cleanup_does_not_restart_its_existing_deadline(self):
        # All operations are test doubles. No native process is signaled here.
        process = mock.Mock(pid=99, returncode=None)
        process.poll.return_value = None
        process._zevune_cleanup_deadline = 101.0
        process.wait.side_effect = [subprocess.TimeoutExpired("fixture", 1), 0]
        with mock.patch.object(resource.time, "monotonic", return_value=100.0), \
                mock.patch.object(resource.sys, "platform", "linux"), \
                mock.patch.object(resource.os, "killpg") as kill_group:
            resource.stop_test(process, None)
        self.assertEqual(process._zevune_cleanup_deadline, 101.0)
        self.assertEqual(process.wait.call_args_list, [mock.call(timeout=1.0), mock.call(timeout=1.0)])
        kill_group.assert_called_once_with(99, resource.signal.SIGKILL)
        process.kill.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
