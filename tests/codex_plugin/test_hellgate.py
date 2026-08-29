import ast
import copy
import hashlib
import json
import unittest
import zlib
from fractions import Fraction
from pathlib import Path

from plugins.jackel.mcp import hellgate_verify
from plugins.jackel.mcp import server as adapter
from tools import hellgate_trial_oracle


REPO_ROOT = Path(__file__).resolve().parents[2]
CERTIFICATE_PATH = (
    REPO_ROOT / "plugins/jackel/mcp/certificates/hellgate_v1.json.zlib"
)
CHECKER_PATH = REPO_ROOT / "plugins/jackel/mcp/hellgate_verify.py"
PLUGIN_WORKFLOW_PATH = REPO_ROOT / ".github/workflows/jackal-codex-plugin.yml"


def canonical_bytes(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def repin(document):
    result = copy.deepcopy(document)
    result.pop("certificate_sha256", None)
    result["certificate_sha256"] = hashlib.sha256(canonical_bytes(result)).hexdigest()
    return canonical_bytes(result) + b"\n"


class HellgateCertificateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.compressed = CERTIFICATE_PATH.read_bytes()
        cls.raw = adapter._decompress_certificate(cls.compressed)
        cls.document = json.loads(cls.raw)
        cls.result = hellgate_verify.verify_bytes(cls.raw)
        cls.oracle = hellgate_trial_oracle.compute_oracle(cls.document)

    def test_static_certificate_is_accepted_at_the_declared_assurance_boundary(self):
        self.assertEqual(self.result["status"], "bounded")
        self.assertEqual(self.result["checker_verdict"], "ACCEPT")
        self.assertIs(self.result["formal"], False)
        self.assertEqual(
            self.result["fields"]["eigenvalue_decimal_interval"],
            ["-4.615978698574496508", "-4.615978698574496507"],
        )
        width = Fraction(self.result["fields"]["interval_width"])
        self.assertLess(width, hellgate_verify.MAX_EIGENVALUE_WIDTH)
        self.assertTrue(any("not formal-bounded" in item for item in self.result["non_claims"]))

    def test_trial_diagnostics_are_bounded_and_subject_scoped(self):
        trial = self.result["fields"]["trial_diagnostics"]
        self.assertEqual(trial["schema"], "jackal-hellgate-trial-diagnostics-v1")
        self.assertEqual(trial["status"], "bounded")
        self.assertEqual(trial["subject"], "normalized-certificate-trial-phi")
        for interval in (
            trial["quartic_norm_interval"],
            trial["kinetic_energy_interval"],
            trial["energy_functional_interval"],
            *trial["moment_intervals"].values(),
        ):
            self.assertLessEqual(Fraction(interval[0]), Fraction(interval[1]))
        for key in (
            "energy_eigenvalue_identity_residual_interval",
            "virial_residual_interval",
        ):
            lower, upper = map(Fraction, trial[key])
            self.assertLessEqual(lower, 0)
            self.assertGreaterEqual(upper, 0)
        self.assertTrue(
            any("not the exact ground state u0" in item for item in trial["non_claims"])
        )

    def test_untrusted_high_precision_oracle_lands_inside_bounded_replay(self):
        self.assertEqual(self.oracle["status"], "unverified-numerical-oracle")
        oracle = self.oracle["fields"]
        fields = self.result["fields"]
        trial = fields["trial_diagnostics"]

        def assert_inside(interval, point):
            lower, upper = map(Fraction, interval)
            value = Fraction(point)
            self.assertLessEqual(lower, value)
            self.assertGreaterEqual(upper, value)

        assert_inside(fields["normalization_interval"], oracle["normalization"])
        assert_inside(trial["quartic_norm_interval"], oracle["quartic_norm"])
        for key in ("x2", "x4", "x6"):
            assert_inside(trial["moment_intervals"][key], oracle["moments"][key])
        assert_inside(trial["kinetic_energy_interval"], oracle["kinetic_energy"])
        assert_inside(
            trial["energy_functional_interval"], oracle["energy_functional"]
        )
        assert_inside(
            fields["eigenvalue_interval"], oracle["eigenvalue_from_energy"]
        )
        assert_inside(
            trial["virial_residual_interval"], oracle["virial_residual"]
        )
        self.assertTrue(
            any(
                "not certificate evidence" in item
                for item in self.oracle["non_claims"]
            )
        )

    def test_hosted_oracle_dependency_is_content_pinned(self):
        workflow = PLUGIN_WORKFLOW_PATH.read_text(encoding="utf-8")
        for token in (
            "mpmath-1.3.0-py3-none-any.whl",
            "a0b2b9fe80bbcd81a6647ff13108738cfb482d481d826cc0e02f5b35e5c88d2c",
            'MPMATH_WHEEL_SIZE: "536198"',
            '--max-filesize "$MPMATH_WHEEL_SIZE"',
            "mpmath wheel digest mismatch",
        ):
            self.assertIn(token, workflow)

    def test_ground_transfer_is_narrow_bounded_and_does_not_launder_moments(self):
        fields = self.result["fields"]
        trial = fields["trial_diagnostics"]
        ground = fields["ground_state_transfer"]
        self.assertEqual(ground["schema"], "jackal-hellgate-ground-transfer-v1")
        self.assertEqual(ground["status"], "bounded")
        self.assertEqual(ground["subject"], "positive-normalized-ground-state-u0")
        self.assertEqual(ground["method"], "lambda-strong-convexity-density-transfer-v1")
        self.assertLess(
            Fraction(ground["density_l2_distance_upper"]),
            hellgate_verify.MAX_DENSITY_L2_DISTANCE,
        )
        trial_lower, trial_upper = map(Fraction, trial["quartic_norm_interval"])
        ground_lower, ground_upper = map(Fraction, ground["quartic_norm_interval"])
        self.assertLessEqual(ground_lower, trial_lower)
        self.assertGreaterEqual(ground_upper, trial_upper)
        self.assertNotIn("moment_intervals", ground)
        self.assertTrue(
            any("does not enclose polynomial moments" in item for item in ground["non_claims"])
        )

    def test_startup_gate_requires_the_scoped_additive_envelopes(self):
        self.assertTrue(adapter._hellgate_result_satisfies_startup_gate(self.result))
        weakened = copy.deepcopy(self.result)
        del weakened["fields"]["trial_diagnostics"]
        self.assertFalse(adapter._hellgate_result_satisfies_startup_gate(weakened))
        laundered = copy.deepcopy(self.result)
        laundered["fields"]["trial_diagnostics"]["subject"] = (
            "positive-normalized-ground-state-u0"
        )
        self.assertFalse(adapter._hellgate_result_satisfies_startup_gate(laundered))

    def test_certificate_asset_remains_byte_pinned(self):
        self.assertEqual(
            hashlib.sha256(self.compressed).hexdigest(),
            "e41ef05cb7ea6aae121a8a60330f52faf58e5827ee39adea3ef298ec4a873a88",
        )

    def test_checker_has_no_numerical_producer_dependency(self):
        tree = ast.parse(CHECKER_PATH.read_text(encoding="utf-8"))
        imported = {
            alias.name.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in node.names
        }
        self.assertTrue({"numpy", "scipy", "mpmath"}.isdisjoint(imported))

    def test_common_denominator_polynomial_arithmetic_matches_exact_vectors(self):
        left = [Fraction(1, 2), Fraction(-2, 3), Fraction(5, 7)]
        right = [Fraction(-3, 5), Fraction(4, 9)]
        # JACKAL exact vectors, outside the formal certificate chain:
        # parsed terms yield -3/10, 28/45, -137/189, 20/63 and
        # parsed=-3/10+28/45/2+-137/189/3+20/63/4 yields -857/5670.
        self.assertEqual(
            hellgate_verify.poly_mul(left, right),
            [
                Fraction(-3, 10),
                Fraction(28, 45),
                Fraction(-137, 189),
                Fraction(20, 63),
            ],
        )
        self.assertEqual(
            hellgate_verify.poly_product_integral_unit(left, right),
            Fraction(-857, 5670),
        )

    def test_internal_digest_tampering_refuses(self):
        document = copy.deepcopy(self.document)
        document["center_eigenvalue"] = "0"
        raw = canonical_bytes(document) + b"\n"
        with self.assertRaises(hellgate_verify.VerificationRefusal) as raised:
            hellgate_verify.verify_bytes(raw)
        self.assertEqual(raised.exception.reason, "certificate-digest")

    def test_coherently_repinned_problem_tampering_refuses(self):
        document = copy.deepcopy(self.document)
        document["problem"]["lambda"] = "3/4"
        with self.assertRaises(hellgate_verify.VerificationRefusal):
            hellgate_verify.verify_bytes(repin(document))

    def test_coherently_repinned_piece_tampering_refuses(self):
        document = copy.deepcopy(self.document)
        piece = document["forward_pieces"][1]
        piece["coefficients"][0] = str(Fraction(piece["coefficients"][0]) + 1)
        with self.assertRaises(hellgate_verify.VerificationRefusal):
            hellgate_verify.verify_bytes(repin(document))

    def test_coherently_repinned_tail_tampering_refuses(self):
        document = copy.deepcopy(self.document)
        document["tail_coefficients"][-1] = str(
            Fraction(document["tail_coefficients"][-1]) + 1
        )
        with self.assertRaises(hellgate_verify.VerificationRefusal):
            hellgate_verify.verify_bytes(repin(document))

    def test_coherently_repinned_nonclaim_weakening_refuses(self):
        document = copy.deepcopy(self.document)
        document["nonclaims"].pop()
        with self.assertRaises(hellgate_verify.VerificationRefusal) as raised:
            hellgate_verify.verify_bytes(repin(document))
        self.assertEqual(raised.exception.reason, "certificate-nonclaims")

    def test_coherently_repinned_density_tampering_refuses(self):
        document = copy.deepcopy(self.document)
        document["forward_pieces"][0]["density_coefficients"][0] = "-1"
        with self.assertRaises(hellgate_verify.VerificationRefusal):
            hellgate_verify.verify_bytes(repin(document))

    def test_duplicate_json_key_refuses(self):
        raw = b'{"schema":"first","schema":"second"}\n'
        with self.assertRaises(hellgate_verify.VerificationRefusal) as raised:
            hellgate_verify.verify_bytes(raw)
        self.assertEqual(raised.exception.reason, "duplicate-json-key")

    def test_compression_trailing_bytes_refuse(self):
        with self.assertRaises(adapter.StartupError):
            adapter._decompress_certificate(self.compressed + b"trailing")

    def test_compression_round_trip_is_byte_exact(self):
        self.assertEqual(zlib.decompress(self.compressed), self.raw)


if __name__ == "__main__":
    unittest.main()
