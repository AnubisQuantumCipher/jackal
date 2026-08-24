from __future__ import annotations

import importlib.util
import json
import unittest
from unittest import mock
import tempfile
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
    def test_true_answer_controls_pass_and_wrong_answers_never_pass(self):
        result = load_validator(self).answer_controls()
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["true_answer_pass_rate"], f"{result['case_count']}/{result['case_count']}")
        self.assertEqual(result["wrong_answer_pass_rate"], f"0/{result['case_count']}")

    def test_validation_refuses_unbound_candidate_receipt(self):
        validator = load_validator(self)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "candidate.json"
            path.write_text(json.dumps({"formal_checker_status": "NOT_EXECUTED"}))
            with self.assertRaisesRegex(RuntimeError, "not bound"):
                validator.validate(path, include_refinement=False)

    def test_publication_binding_uses_checker_margin_as_decisive(self):
        certifier_path = ROOT / "certify.py"
        spec = importlib.util.spec_from_file_location("binding_certifier", certifier_path)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        certifier = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(certifier)
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            witness = base / "witness.cert"
            checker = base / "checker"
            identity = base / "identity.json"
            witness.write_bytes(b"witness")
            checker.write_bytes(b"checker")
            identity.write_text(json.dumps({"identity_digest_sha256": "a" * 64}))
            receipt = {"evidence_classification": {}, "non_claims": []}
            line = (
                "ACCEPT theorem=spacecraft_burn_certified_safe status=formal-bounded "
                "margin_lo=5 margin_hi=9 model=model-v2 epoch=v1.7.4\n"
            )
            completed = mock.Mock(returncode=0, stdout=line, stderr="")
            with mock.patch.object(certifier.subprocess, "run", return_value=completed) as run_checker:
                certifier.bind_formal_checker(
                    receipt, witness, checker, identity, "b" * 64,
                    "model-v2", "v1.7.4", "nonce-v1",
                )
            self.assertEqual(receipt["formal_checker_status"], "ACCEPT")
            self.assertEqual(receipt["formal_decisive_margin"]["lo_scaled_integer"], "5")
            self.assertEqual(receipt["evidence_classification"]["overall"], "formal-bounded")
            run_checker.assert_called_once()

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
        self.assertAlmostEqual(margin, 61.3600182105, delta=1e-4)

    def test_reconciliation_refuses_a_step_that_does_not_exactly_partition_bounds(self):
        validator = load_validator(self)
        receipt = json.loads((ROOT / "evidence" / "baseline_receipt_v2.json").read_text())
        receipt["method"]["step_exact"] = "1/31"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad-step.json"
            path.write_text(json.dumps(receipt))
            with self.assertRaisesRegex(RuntimeError, "exactly partition"):
                validator.validate(path, include_refinement=False)


if __name__ == "__main__":
    unittest.main()
