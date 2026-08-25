from __future__ import annotations

import importlib.util
import hashlib
import copy
import json
import os
import subprocess
import tempfile
import unittest
from unittest import mock
from decimal import Decimal, localcontext
from fractions import Fraction
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CERTIFIER = Path(os.environ.get("SPACECRAFT_CERTIFIER_PATH", ROOT / "certify.py"))
PICARD_PRODUCER_NONCLAIM = (
    "The Python Picard witness generator and its source are not formally verified. "
    "They are outside the mathematical soundness base because the pinned Lean "
    "checker independently checks every accepted tube, but remain trusted for "
    "termination, witness search/completeness, and reproducible generation. A "
    "producer defect may cause refusal, nontermination, or failure to find a "
    "witness, but cannot yield formal ACCEPT absent a defect in the pinned Lean "
    "checker or outer verification gate."
)


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
    def test_formal_binding_records_exact_picard_producer_trust_boundary(self):
        c = load_certifier(self)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            witness = root / "witness.cert"
            checker = root / "checker"
            identity = root / "identity.json"
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
            accepted = subprocess.CompletedProcess(
                [],
                0,
                (
                    "ACCEPT theorem=spacecraft_burn_certified_safe "
                    "status=formal-bounded margin_lo=5 margin_hi=9 "
                    "model=model-v2 epoch=v1.7.5\n"
                ),
                "",
            )
            with (
                mock.patch.object(
                    c,
                    "validate_proof_identity_for_binding",
                    return_value="a" * 64,
                ),
                mock.patch.object(c.subprocess, "run", return_value=accepted),
            ):
                c.bind_formal_checker(
                    receipt,
                    witness,
                    checker,
                    identity,
                    "b" * 64,
                    "model-v2",
                    "v1.7.5",
                    "nonce-v1",
                )
        self.assertIn(PICARD_PRODUCER_NONCLAIM, receipt["non_claims"])

    def test_formal_input_snapshot_refuses_symlink_fifo_and_oversize_before_read(self):
        c = load_certifier(self)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            regular = root / "regular"
            regular.write_bytes(b"exact")
            self.assertEqual(c.read_regular_snapshot(regular, 5, "fixture"), b"exact")

            link = root / "link"
            link.symlink_to(regular)
            fifo = root / "fifo"
            os.mkfifo(fifo)
            oversized = root / "oversized"
            with oversized.open("wb") as stream:
                stream.truncate(9)
            for path in (link, fifo, oversized):
                with self.subTest(path=path.name), self.assertRaises(c.CertificationError):
                    c.read_regular_snapshot(path, 8, "fixture")

    def test_formal_binding_distinguishes_changed_from_unreadable_inputs(self):
        c = load_certifier(self)
        identity_bytes = json.dumps({"identity_digest_sha256": "a" * 64}).encode()
        checker_bytes = b"checker"
        witness_bytes = b"witness"
        receipt = {
            "orbital_hulls": {
                "margin_intersection": {
                    "lo_scaled_integer": "5",
                    "hi_scaled_integer": "9",
                }
            }
        }
        accepted = subprocess.CompletedProcess(
            [],
            0,
            (
                "ACCEPT theorem=spacecraft_burn_certified_safe "
                "status=formal-bounded margin_lo=5 margin_hi=9 "
                "model=model-v2 epoch=v1.7.5\n"
            ),
            "",
        )
        with (
            mock.patch.object(
                c,
                "read_regular_snapshot",
                side_effect=(
                    identity_bytes,
                    checker_bytes,
                    witness_bytes,
                    b"changed-checker",
                    witness_bytes,
                ),
            ),
            mock.patch.object(
                c,
                "validate_proof_identity_for_binding",
                return_value="a" * 64,
            ),
            mock.patch.object(c, "run_formal_checker_snapshot", return_value=accepted),
            self.assertRaisesRegex(
                c.CertificationError,
                "formal binding input changed during checker execution",
            ),
        ):
            c.bind_formal_checker(
                receipt,
                Path("witness"),
                Path("checker"),
                Path("identity"),
                "b" * 64,
                "model-v2",
                "v1.7.5",
                "nonce-v1",
            )

    def test_cli_refuses_aliasing_output_and_formal_input_paths(self):
        c = load_certifier(self)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shared = str(root / "shared")
            with mock.patch.object(
                c,
                "run_from_private_source_snapshot",
                side_effect=AssertionError("must refuse before execution"),
            ):
                with self.assertRaises(SystemExit):
                    c.main(["--output", shared, "--witness", shared])

                checker = root / "checker"
                checker.write_bytes(b"checker")
                witness = root / "witness"
                identity = root / "identity"
                output_link = root / "output-link"
                output_link.symlink_to(checker)
                formal = [
                    "--output", str(output_link),
                    "--witness", str(witness),
                    "--checker", str(checker),
                    "--proof-identity", str(identity),
                    "--request-digest", "a" * 64,
                    "--model-id", "model",
                    "--epoch", "epoch",
                    "--nonce", "nonce",
                ]
                with self.assertRaises(SystemExit):
                    c.main(formal)
                self.assertEqual(checker.read_bytes(), b"checker")

                output_hardlink = root / "output-hardlink"
                os.link(checker, output_hardlink)
                formal[1] = str(output_hardlink)
                with self.assertRaises(SystemExit):
                    c.main(formal)
                self.assertEqual(checker.read_bytes(), b"checker")

    def test_atomic_output_completes_short_writes_and_cleans_failed_temp(self):
        c = load_certifier(self)
        payload = b"bounded output" * 64
        real_write = os.write

        def short_write(descriptor, data):
            return real_write(descriptor, data[:max(1, len(data) // 3)])

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            destination = root / "receipt.bin"
            with mock.patch.object(c.os, "write", side_effect=short_write):
                c.write_bytes_atomic(destination, payload)
            self.assertEqual(destination.read_bytes(), payload)

            failed = root / "failed.bin"
            with (
                mock.patch.object(c.os, "write", side_effect=OSError("write failed")),
                self.assertRaisesRegex(OSError, "write failed"),
            ):
                c.write_bytes_atomic(failed, payload)
            self.assertFalse(failed.exists())
            self.assertEqual(list(root.glob(".failed.bin.tmp-*")), [])

            existing = root / "existing.bin"
            existing.write_bytes(b"trusted implicit input")
            with self.assertRaisesRegex(c.CertificationError, "must not already exist"):
                c.write_bytes_atomic(existing, b"replacement")
            self.assertEqual(existing.read_bytes(), b"trusted implicit input")

    def test_inner_formal_checker_executes_private_hashed_byte_snapshots(self):
        c = load_certifier(self)
        observed = {}
        checker_bytes = b"checker bytes"
        witness_bytes = b"witness bytes"

        def fake_run(command, **kwargs):
            checker, witness = map(Path, command[:2])
            observed.update({
                "checker": checker.read_bytes(),
                "witness": witness.read_bytes(),
                "private": checker.parent == witness.parent == kwargs["cwd"],
            })
            return subprocess.CompletedProcess(command, 0, "ACCEPT\n", "")

        with mock.patch.object(c.subprocess, "run", side_effect=fake_run):
            completed = c.run_formal_checker_snapshot(
                checker_bytes, witness_bytes, "request", "model", "epoch"
            )
        self.assertEqual(completed.stdout, "ACCEPT\n")
        self.assertEqual(observed, {
            "checker": checker_bytes,
            "witness": witness_bytes,
            "private": True,
        })

    def test_publication_cli_executes_an_exact_private_source_snapshot(self):
        c = load_certifier(self)
        observed = {}

        def fake_run(command, **kwargs):
            snapshot = Path(next(item for item in command if item.endswith("certify.py")))
            codec = snapshot.with_name("witness_codec.py")
            descriptor = kwargs["pass_fds"][0]
            observed.update({
                "source": snapshot.read_bytes(),
                "codec": codec.read_bytes(),
                "digest": os.read(descriptor, 64).decode("ascii"),
                "check": kwargs.get("check"),
                "public_bypass": "--source-snapshot-sha256" in command,
                "descriptor_env": kwargs["env"][c.PRIVATE_SOURCE_FD_ENV],
                "isolated_flags": all(flag in command for flag in ("-E", "-s", "-S", "-B")),
                "environment": kwargs["env"],
            })
            return subprocess.CompletedProcess(command, 0)

        with mock.patch.object(c.subprocess, "run", side_effect=fake_run):
            self.assertEqual(c.run_from_private_source_snapshot(["--output", "x"]), 0)
        source = CERTIFIER.read_bytes()
        self.assertEqual(observed["source"], source)
        self.assertEqual(
            observed["codec"], (ROOT / "witness_codec.py").read_bytes()
        )
        self.assertEqual(observed["digest"], hashlib.sha256(source).hexdigest())
        self.assertFalse(observed["check"])
        self.assertFalse(observed["public_bypass"])
        self.assertRegex(observed["descriptor_env"], r"^[0-9]+$")
        self.assertTrue(observed["isolated_flags"])
        self.assertNotIn("PYTHONPATH", observed["environment"])

    def test_inner_checker_binding_validates_identity_self_digest_and_fragment(self):
        c = load_certifier(self)
        identity_path = ROOT.parent / "release/evidence/spacecraft_burn_proof_identity_v1.json"
        identity_bytes = identity_path.read_bytes()
        identity = json.loads(identity_bytes)
        expected = identity["identity_digest_sha256"]
        self.assertEqual(
            c.validate_proof_identity_for_binding(
                identity,
                identity_bytes,
                identity["checker"]["sha256"],
                identity["fragment"]["request_digest"],
                identity["fragment"]["model_id"],
                identity["fragment"]["release_epoch"],
            ),
            expected,
        )
        for field, value in (
            ("checker", "0" * 64),
            ("request_digest", "1" * 64),
        ):
            mutated = copy.deepcopy(identity)
            if field == "checker":
                mutated["checker"]["sha256"] = value
            else:
                mutated["fragment"][field] = value
            body = {
                key: item for key, item in mutated.items()
                if key != "identity_digest_sha256"
            }
            mutated["identity_digest_sha256"] = hashlib.sha256(
                json.dumps(
                    body, ensure_ascii=False, separators=(",", ":"), sort_keys=True
                ).encode()
            ).hexdigest()
            with self.subTest(field=field), self.assertRaises(c.CertificationError):
                c.validate_proof_identity_for_binding(
                    mutated,
                    (json.dumps(mutated, sort_keys=True) + "\n").encode(),
                    identity["checker"]["sha256"],
                    identity["fragment"]["request_digest"],
                    identity["fragment"]["model_id"],
                    identity["fragment"]["release_epoch"],
                )

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

    def test_decimal_endpoint_text_is_directed_outward(self):
        c = load_certifier(self)
        self.assertEqual(c.decimal_lower_text(Fraction(1, 3), 4), "0.3333")
        self.assertEqual(c.decimal_upper_text(Fraction(1, 3), 4), "0.3334")
        self.assertEqual(c.decimal_lower_text(Fraction(-1, 3), 4), "-0.3334")
        self.assertEqual(c.decimal_upper_text(Fraction(-1, 3), 4), "-0.3333")

        enclosure = c.DInterval.from_fractions(
            Fraction(1, 3), Fraction(2, 3)
        ).to_json()
        self.assertLessEqual(Fraction(enclosure["lo_decimal"]), Fraction(1, 3))
        self.assertGreaterEqual(Fraction(enclosure["hi_decimal"]), Fraction(2, 3))

    def test_baseline_contract_integrates_mass_and_converts_thrust_to_km(self):
        c = load_certifier(self)
        self.assertTrue(c.PROPAGATE_FULL_BOX, "full-box-coverage-mismatch")
        self.assertTrue(c.INTEGRATE_MASS, "mass-integration-mismatch")
        self.assertEqual(c.THRUST_KM_SCALE_TEXT, "0.001", "unit-scale-mismatch")
        self.assertEqual(c.ENERGY_HALF_DENOMINATOR, 2, "energy-half-mismatch")
        self.assertEqual(c.APOAPSIS_ECCENTRICITY_SIGN, 1, "apoapsis-plus-mismatch")
        self.assertEqual(c.DECISION_MODE, "exact_lower_bound", "decision-rounding-mismatch")

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

    def test_vector_field_refuses_nonpositive_mass_domain(self):
        c = load_certifier(self)
        state = tuple(
            c.DInterval.point(Fraction(value))
            for value in (6679, 0, 0, Fraction(7726, 1000), -1200)
        )
        with self.assertRaisesRegex(c.CertificationError, "mass must stay strictly positive"):
            c.derivative(state, c.DInterval.point(2000), state[4])

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

    def test_candidate_summary_is_explicitly_not_formal(self):
        c = load_certifier(self)
        receipt = {
            "verdict": c.VERDICT_CERTIFIED_SAFE,
            "verdict_qualifier": c.MODEL_QUALIFIER,
            "producer_assurance": "candidate-only",
            "formal_checker_status": "NOT_EXECUTED",
            "decisive_margin": {"reported_lower_decimal": "1.0000"},
        }
        self.assertEqual(
            c.format_summary(receipt, Path("candidate.json")),
            (
                "CANDIDATE ONLY producer_assurance=candidate-only "
                "formal_checker_status=NOT_EXECUTED candidate_verdict=CERTIFIED SAFE "
                "under the stated finite-burn ODE model, supplied "
                "input bounds, and machine-checked interval-certificate assumptions "
                "candidate_margin_lo=1.0000 receipt=candidate.json"
            ),
        )

    def test_formal_summary_uses_checker_status_and_formal_margin(self):
        c = load_certifier(self)
        receipt = {
            "verdict": c.VERDICT_CERTIFIED_SAFE,
            "verdict_qualifier": c.MODEL_QUALIFIER,
            "producer_assurance": "candidate-only",
            "formal_checker_status": "ACCEPT",
            "decisive_margin": {"reported_lower_decimal": "1.0000"},
            "formal_decisive_margin": {"lo_decimal": "0.7500"},
        }
        self.assertEqual(
            c.format_summary(receipt, Path("formal.json")),
            (
                "CHECKER-ACCEPTED CANDIDATE outer_verification=REQUIRED "
                "candidate_verdict=CERTIFIED SAFE under the stated finite-burn ODE model, supplied "
                "input bounds, and machine-checked interval-certificate assumptions "
                "checker_claimed_status=formal-bounded formal_checker_status=ACCEPT "
                "formal_margin_lo=0.7500 receipt=formal.json"
            ),
        )


if __name__ == "__main__":
    unittest.main()
