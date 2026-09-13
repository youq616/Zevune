"""Synthetic schema tests; real measured samples are checked by the backend runner."""
import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import zevune_wallet as wallet


def response():
    return {"local_timing": {
        "format": "zevune-prepare-timing-1", "scope": "local_prepare_not_finality",
        "unit": "microseconds", "valid": True,
        "stages": {k: 1 for k in wallet.PREPARE_STAGES}, "total": 5,
    }}


class PrepareTimingTests(unittest.TestCase):
    def test_exact_stages_allow_only_submicrosecond_rounding(self):
        result = response()
        for remainder in range(5):
            result["local_timing"]["total"] = 5 + remainder
            self.assertIs(wallet.checked_prepare_timing(result), result["local_timing"])
        for total in (0, 4, 10, 100):
            result["local_timing"]["total"] = total
            with self.assertRaises(RuntimeError):
                wallet.checked_prepare_timing(result)

    def test_wrong_scope_or_unknown_fields_cannot_claim_finality(self):
        for key, value in [("scope", "confirmed_payment"), ("unit", "milliseconds"),
                           ("format", "future-version"), ("valid", 1), ("finality", True)]:
            result = response()
            result["local_timing"][key] = value
            with self.assertRaises(RuntimeError):
                wallet.checked_prepare_timing(result)
        for missing in (None, {}, []):
            with self.assertRaises(RuntimeError):
                wallet.checked_prepare_timing({"local_timing": missing})

    def test_integer_types_bounds_and_missing_stages_fail(self):
        for value in (True, -1, 0.5, "1", None, 1 << 64):
            for location in ("stage", "total"):
                result = response()
                if location == "stage":
                    result["local_timing"]["stages"]["export"] = value
                else:
                    result["local_timing"]["total"] = value
                with self.subTest(value=value, location=location), self.assertRaises(RuntimeError):
                    wallet.checked_prepare_timing(result)
        result = response()
        del result["local_timing"]["stages"]["export"]
        with self.assertRaises(RuntimeError):
            wallet.checked_prepare_timing(result)

    def test_broken_clock_is_unknown_not_zero_duration(self):
        result = response()
        timing = result["local_timing"]
        timing["valid"] = False
        timing["stages"] = {key: None for key in wallet.PREPARE_STAGES}
        timing["total"] = None
        before = copy.deepcopy(result)
        self.assertFalse(wallet.checked_prepare_timing(result)["valid"])
        self.assertEqual(result, before)
        timing["total"] = 0
        with self.assertRaises(RuntimeError):
            wallet.checked_prepare_timing(result)


if __name__ == "__main__":
    unittest.main()
