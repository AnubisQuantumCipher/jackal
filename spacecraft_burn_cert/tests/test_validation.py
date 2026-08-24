from __future__ import annotations

import importlib.util
import json
import unittest
from fractions import Fraction
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = ROOT / "validate.py"
BASELINE = ROOT / "evidence" / "legacy-v1" / "baseline_receipt.json"


def load_validator(testcase: unittest.TestCase):
    if not VALIDATOR.is_file():
        testcase.fail("validate.py is missing")
    spec = importlib.util.spec_from_file_location("spacecraft_validation", VALIDATOR)
    if spec is None or spec.loader is None:
        testcase.fail("validate.py cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class InstrumentValidationTests(unittest.TestCase):
    def test_analytic_mass_reachable_set_is_inside_certified_hull(self):
        validator = load_validator(self)
        receipt = json.loads(BASELINE.read_text())
        exact_lo, exact_hi = validator.analytic_mass_reachable()
        hull_lo, hull_hi = validator.receipt_interval(
            receipt["cutoff_state_hull"]["mass"]
        )
        self.assertLessEqual(hull_lo, exact_lo)
        self.assertGreaterEqual(hull_hi, exact_hi)

    def test_independent_nominal_rk4_is_contained_and_near_reference(self):
        validator = load_validator(self)
        receipt = json.loads(BASELINE.read_text())
        state, margin = validator.nominal_rk4(step=Fraction(1, 64))
        for name, value in zip(("x", "y", "vx", "vy", "mass"), state):
            lo, hi = validator.receipt_interval(receipt["cutoff_state_hull"][name])
            self.assertLessEqual(float(lo), value)
            self.assertGreaterEqual(float(hi), value)
        self.assertAlmostEqual(margin, 61.3600182105, places=8)


if __name__ == "__main__":
    unittest.main()
