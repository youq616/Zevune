"""Test target scheduling only: no substitute verifier or payment execution."""
import contextlib
import copy
import io
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import run_funded_rust as runner


def metadata():
    targets = [{"kind": ["lib"], "name": "zevune_orchard_lab", "test": True, "doctest": True},
               {"kind": ["bin"], "name": "zevune-wallet-local", "test": True,
                "required-features": [runner.FEATURE]},
               {"kind": ["test"], "name": "recovery_cli", "test": True},
               {"kind": ["test"], "name": "genesis_domain", "test": True}]
    return {"version": 1, "workspace_members": ["owned"], "packages": [
        {"id": "owned", "name": "zevune-orchard-lab", "manifest_path": str(runner.MANIFEST),
         "targets": targets}]}


class FundedRustPlanTests(unittest.TestCase):
    def test_target_union_is_complete_and_disjoint(self):
        m = metadata()
        a = runner.make_plan(m, runner.MANIFEST, "library")
        b = runner.make_plan(m, runner.MANIFEST, "interfaces")
        expected = {(t["kind"][0], t["name"]) for t in m["packages"][0]["targets"]}
        self.assertEqual(set(a["test_targets"]) | set(b["test_targets"]), expected)
        self.assertFalse(set(a["test_targets"]) & set(b["test_targets"]))
        self.assertFalse(a["documentation_tests"])
        self.assertTrue(b["documentation_tests"])

    def test_commands_keep_flags_and_never_filter_test_names(self):
        for cohort in ("library", "interfaces"):
            plan = runner.make_plan(metadata(), runner.MANIFEST, cohort)
            for command in plan["commands"]:
                self.assertEqual(command[:len(runner.COMMON)], list(runner.COMMON))
                self.assertEqual(command[command.index("--") + 1:], ["--test-threads=1"])
                for prohibited in ("--tests", "--skip", "--exclude", "--ignored", "--no-run"):
                    self.assertNotIn(prohibited, command)
        command = runner.make_plan(metadata(), runner.MANIFEST, "interfaces")["commands"][0]
        self.assertEqual(command.count("--test"), 2)
        self.assertEqual(command.count("--bin"), 1)

    def test_future_binary_and_integration_targets_join_automatically(self):
        m = metadata()
        m["packages"][0]["targets"].extend([
            {"kind": ["test"], "name": "new_storage", "test": True},
            {"kind": ["bin"], "name": "new-tool", "test": True}])
        plan = runner.make_plan(m, runner.MANIFEST, "interfaces")
        self.assertIn(("test", "new_storage"), plan["test_targets"])
        self.assertIn(("bin", "new-tool"), plan["test_targets"])

    def test_reordering_metadata_does_not_change_plan(self):
        m = metadata()
        expected = runner.make_plan(m, runner.MANIFEST, "interfaces")
        m["packages"][0]["targets"].reverse()
        self.assertEqual(expected, runner.make_plan(m, runner.MANIFEST, "interfaces"))

    def test_unknown_cohort_or_schema_fails(self):
        for cohort in ("", "everything", "--help"):
            with self.assertRaises(ValueError):
                runner.make_plan(metadata(), runner.MANIFEST, cohort)
        for version in (None, True, 1.0, 2, "1"):
            m = metadata(); m["version"] = version
            with self.assertRaises(ValueError):
                runner.make_plan(m, runner.MANIFEST, "library")

    def test_wrong_workspace_identity_fails(self):
        cases = []
        m = metadata(); m["workspace_members"] = ["other"]; cases.append(m)
        m = metadata(); m["packages"].append(copy.deepcopy(m["packages"][0])); cases.append(m)
        m = metadata(); m["packages"][0]["manifest_path"] = str(runner.MANIFEST.parent / "other.toml"); cases.append(m)
        m = metadata(); m["packages"][0]["name"] = "other"; cases.append(m)
        for m in cases:
            with self.subTest(m=m), self.assertRaises(ValueError):
                runner.make_plan(m, runner.MANIFEST, "library")

    def test_unknown_or_disabled_targets_are_not_silently_omitted(self):
        for kind in ("example", "bench", "proc-macro", "unknown"):
            m = metadata(); m["packages"][0]["targets"][1]["kind"] = [kind]
            with self.assertRaises(ValueError):
                runner.make_plan(m, runner.MANIFEST, "interfaces")
        for flag in (False, 1, None, "true"):
            m = metadata(); m["packages"][0]["targets"][1]["test"] = flag
            with self.assertRaises(ValueError):
                runner.make_plan(m, runner.MANIFEST, "interfaces")
        m = metadata(); m["packages"][0]["targets"][0]["doctest"] = False
        with self.assertRaises(ValueError):
            runner.make_plan(m, runner.MANIFEST, "interfaces")

    def test_unselected_features_fail(self):
        for value in (["new-feature"], runner.FEATURE, None):
            m = metadata(); m["packages"][0]["targets"][1]["required-features"] = value
            with self.assertRaises(ValueError):
                runner.make_plan(m, runner.MANIFEST, "library")

    def test_invalid_names_and_duplicate_targets_fail(self):
        for name in ("--all", "a b", "x;exit", "a\n", "", "a" * 129):
            m = metadata(); m["packages"][0]["targets"][1]["name"] = name
            with self.assertRaises(ValueError):
                runner.make_plan(m, runner.MANIFEST, "interfaces")
        m = metadata(); m["packages"][0]["targets"].append(m["packages"][0]["targets"][1])
        with self.assertRaises(ValueError):
            runner.make_plan(m, runner.MANIFEST, "interfaces")

    def test_empty_or_incomplete_inventory_fails(self):
        for targets in ([], metadata()["packages"][0]["targets"][1:], [None] * 3):
            m = metadata(); m["packages"][0]["targets"] = targets
            with self.assertRaises(ValueError):
                runner.make_plan(m, runner.MANIFEST, "library")

    def test_command_failure_stops_cohort_and_never_reports_completion(self):
        plan = runner.make_plan(metadata(), runner.MANIFEST, "interfaces")
        out = io.StringIO()
        with patch.object(runner.subprocess, "run", side_effect=subprocess.CalledProcessError(101, "cargo")) as run:
            with contextlib.redirect_stdout(out), self.assertRaises(subprocess.CalledProcessError):
                runner.execute(plan, runner.MANIFEST)
            self.assertEqual(run.call_count, 1)
            self.assertTrue(run.call_args.kwargs["check"])
            self.assertNotIn("shell", run.call_args.kwargs)
        self.assertNotIn("FUNDED_COHORT_COMPLETE", out.getvalue())

    def test_plan_only_is_not_a_test_execution(self):
        out = io.StringIO()
        with patch.object(runner, "load_metadata", return_value=metadata()), patch.object(runner, "execute") as execute:
            with contextlib.redirect_stdout(out):
                self.assertEqual(runner.main(["interfaces", "--plan-only"]), 0)
            execute.assert_not_called()
        self.assertNotIn("FUNDED_COHORT_COMPLETE", out.getvalue())

    def test_metadata_failure_is_a_nonzero_exit(self):
        with patch.object(runner, "load_metadata", side_effect=ValueError("invalid metadata")):
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(runner.main(["library"]), 1)


if __name__ == "__main__":
    unittest.main()
