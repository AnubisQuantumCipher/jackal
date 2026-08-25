from __future__ import annotations

import importlib.util
import json
import os
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
    def test_cli_refuses_symlink_hardlink_and_resolved_parent_output_aliases(self):
        validator = load_validator(self)
        for case in ("symlink", "dangling-symlink", "hardlink", "resolved-parent"):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                real = root / "real"
                real.mkdir()
                baseline = real / "baseline.json"
                original = b"authoritative baseline\n"
                baseline.write_bytes(original)
                if case == "symlink":
                    output = root / "output.json"
                    output.symlink_to(baseline)
                elif case == "dangling-symlink":
                    output = root / "output.json"
                    output.symlink_to(root / "missing.json")
                elif case == "hardlink":
                    output = root / "output.json"
                    os.link(baseline, output)
                else:
                    alias = root / "alias"
                    alias.symlink_to(real, target_is_directory=True)
                    output = alias / baseline.name
                with mock.patch.object(
                    validator, "validate", return_value={"status": "PASS"}
                ) as validate:
                    with self.assertRaises(SystemExit):
                        validator.main([
                            "--baseline", str(baseline), "--output", str(output),
                            "--skip-refinement",
                        ])
                validate.assert_not_called()
                self.assertEqual(baseline.read_bytes(), original)

    def test_atomic_validation_output_completes_short_writes_and_cleans_failure(self):
        validator = load_validator(self)
        payload = {"status": "PASS", "detail": "x" * 4096}
        real_write = os.write

        def short_write(descriptor, data):
            return real_write(descriptor, data[:max(1, len(data) // 4)])

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            destination = root / "validation.json"
            with mock.patch.object(validator.os, "write", side_effect=short_write) as write:
                validator.write_atomic(destination, payload)
            self.assertGreater(write.call_count, 1)
            self.assertEqual(json.loads(destination.read_bytes()), payload)

            failed = root / "failed.json"
            with (
                mock.patch.object(validator.os, "write", side_effect=OSError("blocked")),
                self.assertRaisesRegex(OSError, "blocked"),
            ):
                validator.write_atomic(failed, payload)
            self.assertFalse(failed.exists())
            self.assertEqual(list(root.glob(".failed.json.tmp-*")), [])

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

    def test_baseline_parser_and_exact_numbers_are_bounded_and_strict(self):
        validator = load_validator(self)
        malformed = (
            b"[" * 5000 + b"0" + b"]" * 5000,
            b'{"formal_checker_status":"ACCEPT","formal_checker_status":"ACCEPT"}',
            b'{"formal_checker_status":"ACCEPT","x":NaN}',
            b'{"formal_checker_status":"ACCEPT","x":1.5}',
            b'{"formal_checker_status":"ACCEPT","x":"\\ud800"}',
            b'{"formal_checker_status":"ACCEPT","x":'
            + b"9" * (validator.MAX_JSON_INTEGER_DIGITS + 1)
            + b"}",
        )
        for index, raw in enumerate(malformed):
            with self.subTest(index=index), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "baseline.json"
                path.write_bytes(raw)
                with self.assertRaisesRegex(RuntimeError, "baseline receipt is invalid"):
                    validator.validate(path, include_refinement=False)

        receipt = json.loads(
            (ROOT / "evidence" / "baseline_receipt_v2.json").read_text()
        )
        receipt["method"]["step_exact"] = (
            "1/" + "9" * (validator.MAX_EXACT_NUMBER_DIGITS + 1)
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "baseline.json"
            path.write_text(json.dumps(receipt), encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "baseline receipt is invalid"):
                validator.validate(path, include_refinement=False)

    def test_baseline_input_must_be_a_bounded_regular_snapshot(self):
        validator = load_validator(self)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "target.json"
            target.write_text("{}", encoding="utf-8")
            link = root / "baseline.json"
            link.symlink_to(target)
            with self.assertRaisesRegex(RuntimeError, "baseline receipt is invalid"):
                validator.validate(link, include_refinement=False)

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
            receipt = {
                "evidence_classification": {},
                "non_claims": [],
                "orbital_hulls": {
                    "margin_intersection": {
                        "lo_scaled_integer": "5",
                        "hi_scaled_integer": "9",
                    }
                },
            }
            line = (
                "ACCEPT theorem=spacecraft_burn_certified_safe status=formal-bounded "
                "margin_lo=5 margin_hi=9 model=model-v2 epoch=v1.7.5\n"
            )
            completed = mock.Mock(
                returncode=0, stdout=line.encode("ascii"), stderr=b""
            )
            with (
                mock.patch.object(
                    certifier,
                    "validate_proof_identity_for_binding",
                    return_value="a" * 64,
                ) as validate_identity,
                mock.patch.object(
                    certifier, "run_bounded_process", return_value=completed
                ) as run_checker,
            ):
                certifier.bind_formal_checker(
                    receipt, witness, checker, identity, "b" * 64,
                    "model-v2", "v1.7.5", "nonce-v1",
                )
            self.assertEqual(receipt["formal_checker_status"], "ACCEPT")
            self.assertEqual(receipt["formal_decisive_margin"]["lo_scaled_integer"], "5")
            self.assertEqual(receipt["evidence_classification"]["overall"], "formal-bounded")
            validate_identity.assert_called_once()
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

    def test_reconciliation_counts_require_positive_bounded_exact_integers(self):
        validator = load_validator(self)
        baseline = json.loads(
            (ROOT / "evidence" / "baseline_receipt_v2.json").read_text()
        )
        mutations = (
            ("branch_count", ""),
            ("branch_count", False),
            ("branch_count", []),
            ("branch_count", -1),
            ("tube_count", 0),
            ("postprocess_count", -1),
        )
        for field, value in mutations:
            with self.subTest(field=field, value=value), tempfile.TemporaryDirectory() as directory:
                receipt = json.loads(json.dumps(baseline))
                receipt["method"][field] = value
                path = Path(directory) / "baseline.json"
                path.write_text(json.dumps(receipt), encoding="utf-8")
                with self.assertRaisesRegex(RuntimeError, "counts are invalid"):
                    validator.validate(path, include_refinement=False)

        receipt = json.loads(json.dumps(baseline))
        receipt["method"]["step_exact"] = "1/1" + "0" * 119
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "baseline.json"
            path.write_text(json.dumps(receipt), encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "model limits"):
                validator.validate(path, include_refinement=False)

    def test_step_refinement_rows_preserve_qualifier_and_assurance(self):
        validator = load_validator(self)

        def candidate(step: Fraction) -> dict:
            return {
                "decisive_margin": {
                    "reported_lower_exact": "1",
                    "reported_lower_decimal": "1.0",
                    "formula_only_global_lower_exact": "1/2",
                },
                "method": {
                    "tube_count": 1,
                    "trace_sha256": str(step.denominator) * 64,
                },
                "verdict": "CERTIFIED SAFE",
                "verdict_qualifier": validator.load_certifier().MODEL_QUALIFIER,
                "producer_assurance": "candidate-only",
                "formal_checker_status": "NOT_EXECUTED",
                "evidence_classification": {
                    "overall": "rigorously interval-bounded, not formal-bounded",
                },
            }

        class FakeCertifier:
            STEP = Fraction(1, 32)
            MODEL_QUALIFIER = validator.load_certifier().MODEL_QUALIFIER

            @classmethod
            def certify(cls):
                return candidate(cls.STEP), b"witness"

        baseline = candidate(Fraction(1, 32))
        baseline["method"]["step_exact"] = "1/32"
        baseline["formal_checker_status"] = "ACCEPT"
        baseline["evidence_classification"]["overall"] = "formal-bounded"

        with mock.patch.object(validator, "load_certifier", return_value=FakeCertifier):
            result = validator.step_refinement(baseline)

        self.assertEqual([row["step_exact"] for row in result["runs"]], ["1/16", "1/32", "1/48"])
        for row in result["runs"]:
            self.assertEqual(row["verdict"], "CERTIFIED SAFE")
            self.assertEqual(row["verdict_qualifier"], FakeCertifier.MODEL_QUALIFIER)
            self.assertEqual(row["producer_assurance"], "candidate-only")
            self.assertIn(row["formal_checker_status"], {"ACCEPT", "NOT_EXECUTED"})
            self.assertIn("evidence_classification", row)
        self.assertEqual(
            [row["formal_checker_status"] for row in result["runs"]],
            ["NOT_EXECUTED", "ACCEPT", "NOT_EXECUTED"],
        )
        self.assertEqual(
            [row["evidence_classification"] for row in result["runs"]],
            [
                "rigorously interval-bounded, not formal-bounded",
                "formal-bounded",
                "rigorously interval-bounded, not formal-bounded",
            ],
        )

    def test_refinement_assurance_rejects_laundered_candidate_rows(self):
        validator = load_validator(self)
        qualifier = load_validator(self).load_certifier().MODEL_QUALIFIER
        candidate = {
            "step_exact": "1/16",
            "verdict": "CERTIFIED SAFE",
            "verdict_qualifier": qualifier,
            "producer_assurance": "candidate-only",
            "formal_checker_status": "NOT_EXECUTED",
            "evidence_classification": "rigorously interval-bounded, not formal-bounded",
        }
        baseline = {
            **candidate,
            "step_exact": "1/32",
            "formal_checker_status": "ACCEPT",
            "evidence_classification": "formal-bounded",
        }
        refined = {**candidate, "step_exact": "1/48"}
        validator.validate_refinement_assurance([candidate, baseline, refined], "1/32")
        for mutation in (
            {**candidate, "verdict_qualifier": "for the physical spacecraft"},
            {**candidate, "formal_checker_status": "ACCEPT"},
            {**candidate, "evidence_classification": "formal-bounded"},
        ):
            with self.subTest(mutation=mutation), self.assertRaisesRegex(
                RuntimeError, "assurance mismatch"
            ):
                validator.validate_refinement_assurance([mutation, baseline, refined], "1/32")

    def test_refinement_assurance_requires_exactly_one_accepted_baseline(self):
        validator = load_validator(self)
        qualifier = validator.load_certifier().MODEL_QUALIFIER
        candidate = {
            "step_exact": "1/16",
            "verdict": "CERTIFIED SAFE",
            "verdict_qualifier": qualifier,
            "producer_assurance": "candidate-only",
            "formal_checker_status": "NOT_EXECUTED",
            "evidence_classification": "rigorously interval-bounded, not formal-bounded",
        }
        with self.assertRaisesRegex(RuntimeError, "exactly one accepted baseline"):
            validator.validate_refinement_assurance(
                [candidate, {**candidate, "step_exact": "1/48"}], "1/32"
            )


if __name__ == "__main__":
    unittest.main()
