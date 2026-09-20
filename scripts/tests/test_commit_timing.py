"""Evidence-parser fixtures, not synthesized worker or timing measurements."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location("check_commit_timing", Path(__file__).resolve().parents[1] / "check_commit_timing.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def fixture():
    phases = []
    for name in module.PHASES:
        count = 0 if name in ("rotation_prepare", "directory_sync") else 8190
        phases.append(dict(name=name, ordinary_count=count, ordinary_total_ns=count,
                           ordinary_max_ns=int(count > 0), rotating_count=2,
                           rotating_total_ns=2, rotating_max_ns=1))
    return dict(blocks=8192, control_bytes_equal=True, replay_and_continuation=True,
                real_funds_allowed=False, profile=dict(
                    schema_version=1, scope="test_store_internal_not_worker_ipc", valid=True,
                    attempts=8192, accepted=8192, failed=0, last_accepted_height=8192,
                    paid=2, rotated=2, accepted_commit_total_ns=8192 * 20,
                    accepted_commit_max_ns=20, phases=phases, last_failed_attempt=None))


class TestCommitTiming(unittest.TestCase):
    def test_valid_measurement_fixture(self):
        module.validate(fixture())

    def test_each_phase_missing_duplicate_or_miscalculated(self):
        for index in range(len(module.PHASES)):
            for field in ("ordinary_count", "rotating_count", "ordinary_max_ns"):
                data = fixture()
                data["profile"]["phases"][index][field] += 10000
                with self.assertRaises(ValueError):
                    module.validate(data)
            data = fixture()
            del data["profile"]["phases"][index]
            with self.assertRaises(ValueError):
                module.validate(data)
        data = fixture()
        data["profile"]["phases"][0]["name"] = module.PHASES[1]
        with self.assertRaises(ValueError):
            module.validate(data)

    def test_incomplete_or_private_fields_refused(self):
        for field, value in (("valid", False), ("attempts", 8191), ("accepted", True),
                             ("failed", 1), ("paid", 0), ("last_accepted_height", 8191),
                             ("last_failed_attempt", {}), ("accepted_commit_total_ns", 1)):
            data = fixture()
            data["profile"][field] = value
            with self.assertRaises(ValueError):
                module.validate(data)
        data = fixture()
        data["private_path"] = "SENTINEL"
        with self.assertRaises(ValueError):
            module.validate(data)

    def test_strict_json_and_bounds(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "test.json"
            for value in (b'{"x":1,"x":2}', b'{"x":NaN}', b'[]', b' ' * 20):
                path.write_bytes(value)
                with self.assertRaises(ValueError):
                    module.read(path, 16)
            path.write_bytes(b'{"x":1}')
            self.assertEqual(module.read(path, 16), {"x": 1})


if __name__ == "__main__":
    unittest.main()
