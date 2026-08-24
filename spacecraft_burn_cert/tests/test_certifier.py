from __future__ import annotations

import importlib.util
import hashlib
import json
import math
import os
import unittest
from decimal import Decimal, localcontext
from fractions import Fraction
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CERTIFIER = Path(os.environ.get("SPACECRAFT_CERTIFIER_PATH", ROOT / "certify.py"))


def load_certifier(testcase: unittest.TestCase):
    if not CERTIFIER.is_file():
        testcase.fail("certify.py is missing")
    spec = importlib.util.spec_from_file_location("spacecraft_certify", CERTIFIER)
    if spec is None or spec.loader is None:
        testcase.fail("certify.py cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class CertifierContractTests(unittest.TestCase):
    def test_receipt_records_positive_ode_denominator_domains(self):
        receipt = json.loads(
            (ROOT / "evidence" / "legacy-v1" / "baseline_receipt.json").read_text()
        )
        self.assertIn("domain_lower_bounds", receipt["method"])
        domains = receipt["method"]["domain_lower_bounds"]
        self.assertGreater(Fraction(domains["radius_squared_exact"]), 0)
        self.assertGreater(Fraction(domains["speed_squared_exact"]), 0)
        self.assertGreater(Fraction(domains["mass_exact"]), 0)

    def test_dyadic_arithmetic_and_sqrt_enclose_exact_values(self):
        c = load_certifier(self)
        a = c.DInterval.point(Fraction(1, 3))
        b = c.DInterval.point(Fraction(7, 11))
        for observed, exact in (
            (a + b, Fraction(1, 3) + Fraction(7, 11)),
            (a * b, Fraction(1, 3) * Fraction(7, 11)),
            (a / b, Fraction(1, 3) / Fraction(7, 11)),
        ):
            self.assertLessEqual(observed.lo_fraction(), exact)
            self.assertGreaterEqual(observed.hi_fraction(), exact)

        root = c.DInterval.point(Fraction(2)).sqrt()
        self.assertLessEqual(root.lo * root.lo, 2 * c.SCALE * c.SCALE)
        self.assertGreaterEqual(root.hi * root.hi, 2 * c.SCALE * c.SCALE)

    def test_baseline_contract_integrates_mass_and_converts_thrust_to_km(self):
        c = load_certifier(self)
        self.assertTrue(c.PROPAGATE_FULL_BOX)
        self.assertTrue(c.INTEGRATE_MASS)
        self.assertEqual(c.THRUST_KM_SCALE_TEXT, "0.001")
        self.assertEqual(c.ENERGY_HALF_DENOMINATOR, 2)
        self.assertEqual(c.APOAPSIS_ECCENTRICITY_SIGN, 1)
        self.assertEqual(c.DECISION_MODE, "exact_lower_bound")

        state = tuple(
            c.DInterval.point(Fraction(value))
            for value in (6679, 0, 0, Fraction(7726, 1000), 1200)
        )
        thrust = c.DInterval.point(Fraction(2000))
        deriv = c.derivative(state, thrust, state[4])
        expected_thrust_y = Fraction(2000, 1200) * Fraction(1, 1000)
        self.assertLessEqual(deriv[3].lo_fraction(), expected_thrust_y)
        self.assertGreaterEqual(deriv[3].hi_fraction(), expected_thrust_y)
        expected_dm = -Fraction(2000, 1) / (Fraction(450) * Fraction(196133, 20000))
        self.assertLessEqual(deriv[4].lo_fraction(), expected_dm)
        self.assertGreaterEqual(deriv[4].hi_fraction(), expected_dm)

    def test_picard_tube_contains_its_interval_mapping(self):
        c = load_certifier(self)
        state, thrust = c.center_state_and_thrust()
        h = Fraction(1, 32)
        tube, _iterations = c.picard_tube(state, thrust, h, state[4])
        mapped = c.picard_mapping(state, tube, thrust, h, state[4])
        self.assertTrue(c.box_strictly_inside(mapped, tube))

    def test_postprocessing_contains_independent_nominal_reference(self):
        c = load_certifier(self)
        texts = (
            "6614.20820810541",
            "936.2929755636",
            "-1.08281707417387",
            "7.85508901556144",
            "1145.61513530784",
        )
        cutoff = tuple(c.DInterval.point(Fraction(text)) for text in texts)
        post = c.postprocess(cutoff)
        margin = post["margin_intersection"]
        with localcontext() as context:
            context.prec = 80
            x, y, vx, vy, _mass = map(Decimal, texts)
            mu = Decimal("398600.4418")
            radius = (x * x + y * y).sqrt()
            speed_squared = vx * vx + vy * vy
            energy = speed_squared / 2 - mu / radius
            semimajor = -mu / (2 * energy)
            angular_momentum = x * vy - y * vx
            eccentricity = (
                1 + 2 * energy * angular_momentum * angular_momentum / (mu * mu)
            ).sqrt()
            nominal_decimal = (
                semimajor * (1 + eccentricity)
                - Decimal("6378.1363")
                - Decimal("1000")
            )
        nominal = Fraction(str(nominal_decimal))
        self.assertLessEqual(margin.lo_fraction(), nominal)
        self.assertGreaterEqual(margin.hi_fraction(), nominal)
        self.assertFalse(post["eccentricity"].intersection(post["eccentricity_vector"]).is_empty())

    def test_decision_is_strict_and_never_uses_display_rounding(self):
        c = load_certifier(self)
        tiny = Fraction(1, 1 << 50)
        self.assertEqual(
            c.classify_margin(c.DInterval.point(tiny)),
            {
                "verdict": "CERTIFIED SAFE",
                "qualifier": (
                    "under the stated finite-burn ODE model, supplied input bounds, "
                    "and machine-checked interval-certificate assumptions"
                ),
            },
        )
        self.assertEqual(
            c.classify_margin(c.DInterval.point(-tiny))["verdict"],
            "INDETERMINATE",
        )
        self.assertEqual(
            c.classify_margin(c.DInterval.from_fractions(-tiny, tiny))["verdict"],
            "INDETERMINATE",
        )
        self.assertEqual(c.reported_lower_bound(c.DInterval.point(tiny)), tiny)

    def test_producer_status_cannot_mint_formal_assurance(self):
        c = load_certifier(self)
        self.assertEqual(
            c.producer_status(),
            {
                "producer_assurance": "candidate-only",
                "formal_checker_status": "NOT_EXECUTED",
            },
        )

    def test_full_candidate_emits_complete_canonical_witness(self):
        c = load_certifier(self)
        receipt, witness = c.certify()
        encoded = c.witness_codec.encode_witness(witness)
        self.assertEqual(len(witness.branches), 32)
        self.assertEqual(witness.steps_per_branch, 3888)
        self.assertEqual(sum(len(branch.steps) for branch in witness.branches), 124416)
        self.assertEqual(receipt["witness"]["branch_count"], 32)
        self.assertEqual(receipt["witness"]["tube_count"], 124416)
        self.assertEqual(receipt["witness"]["cutoff_cell_count"], 3072)
        self.assertEqual(receipt["witness"]["byte_size"], len(encoded))
        self.assertEqual(receipt["witness"]["sha256"], hashlib.sha256(encoded).hexdigest())
        self.assertEqual(c.witness_codec.encode_witness(c.witness_codec.decode_witness(encoded)), encoded)

    def test_summary_keeps_model_qualifier_adjacent_to_positive_verdict(self):
        c = load_certifier(self)
        receipt = {
            "verdict": c.VERDICT_CERTIFIED_SAFE,
            "verdict_qualifier": c.MODEL_QUALIFIER,
            "decisive_margin": {"reported_lower_decimal": "1.0000"},
        }
        self.assertEqual(
            c.format_summary(receipt, Path("candidate.json")),
            (
                "CERTIFIED SAFE under the stated finite-burn ODE model, supplied "
                "input bounds, and machine-checked interval-certificate assumptions "
                "margin_lo=1.0000 receipt=candidate.json"
            ),
        )


if __name__ == "__main__":
    unittest.main()
