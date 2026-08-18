#!/usr/bin/env python3
"""Behavioral gates for the bounded Navier--Stokes research pack.

These tests deliberately exercise the real Anubis program through the Python
orchestrator.  The Python replay is tested separately; no mock policy engine is
used here.
"""

from __future__ import annotations

import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from navier_stokes_certificate_producer import (  # noqa: E402
    CCRT_SOURCE_SHA256,
    ESS_SOURCE_SHA256,
    SchemaRefusal,
    ZERO_FIELD_SHA256,
    canonical_json_bytes,
    load_json_strict,
    produce_receipt,
    sha256_bytes,
)
from navier_stokes_receipt_verify import ReceiptRefusal, verify_receipt  # noqa: E402


HEX_A = "a" * 64
HEX_B = "b" * 64
HEX_C = "c" * 64
HEX_D = "d" * 64
ZERO_THEOREM_SHA256 = "4a26df4e465412aca24de29aeb882fb5c6c36148d16422ffd09f03fd8f3cdc09"
ZERO_PROOF_OBJECT_SHA256 = "42ac530f66869eafa2e1f82441ef1c47617fb2ee23a8b05e7d13a7aba4eb1e1f"


def interval(lower: str, upper: str) -> dict[str, str]:
    return {"lower": lower, "upper": upper}


def zero_solution_link() -> dict[str, object]:
    return {
        "theorem_id": "JACKAL_T3_ZERO_SOLUTION_IDENTITY_V1",
        "theorem_source_sha256": ZERO_THEOREM_SHA256,
        "theorem_locator": "domain_packs/pde/NAVIER_STOKES_VERIFICATION_SPEC.md#zero-solution-identity",
        "m": 3,
        "norm_id": "T3_Vm_STOKES_HOMOGENEOUS_PHYSICAL_VOLUME",
        "representation_id": "T3_ZERO_FOURIER_FIELD_V1",
        "initial_mismatch_upper": "0",
        "residual_integral_upper": "0",
        "divergence_defect_upper": "0",
        "eta_upper": "0",
        "threshold_lower": "1",
        "continuum_remainders_certified": True,
        "proof_object_id": "JACKAL_T3_ZERO_PROOF_OBJECT_V1",
        "proof_object_digest": ZERO_PROOF_OBJECT_SHA256,
    }


def base_request(operation: str, gate_data: dict[str, object]) -> dict[str, object]:
    requested = {
        "gate_s": "solution_link_on_scope",
        "gate_a": "energy_on_scope",
        "gate_b": "enstrophy_nonincrease_on_scope",
        "gate_c": "continuation_on_prefix",
        "gate_d": "conditional_regular_on_scope",
    }[operation]
    return {
        "schema": "jackal-navier-stokes-request-v1",
        "pack_version": "1.0.0",
        "operation": operation,
        "requested_claim": requested,
        "allow_fallback": False,
        "model": {
            "dimension": 3,
            "equation": "incompressible_navier_stokes",
            "density": "1",
            "forcing": "0",
            "viscosity": "1",
            "domain": "T3_periodic",
            "period": "1",
            "measure_normalization": "physical_volume",
            "pressure_gauge": "zero_spatial_mean",
            "sign_convention": "dt_u_minus_nu_laplacian_plus_advection_plus_grad_p_eq_0",
        },
        "scope": {
            "t0": "0",
            "t1": "1",
            "topology": "closed",
            "terminal_role": "finite_scope_only",
            "initial_field_digest": ZERO_FIELD_SHA256,
            "approximate_field_digest": ZERO_FIELD_SHA256,
            "reconstruction_digest": ZERO_FIELD_SHA256,
        },
        "preconditions": {
            "smooth_initial": True,
            "divergence_free_initial": True,
            "exact_zero_forcing": True,
            "mean_zero": True,
            "solution_class": "smooth_on_scope",
        },
        "solution_link": zero_solution_link(),
        "gate_data": gate_data,
        "nonclaims": [
            "not_global_regular",
            "not_smooth_for_all_time",
            "not_millennium_solved",
        ],
    }


def gate_s_request() -> dict[str, object]:
    return base_request("gate_s", {"kind": "solution_link"})


def gate_a_request() -> dict[str, object]:
    return base_request(
        "gate_a",
        {
            "kind": "energy_prefix",
            "energy_t": interval("0", "0"),
            "dissipation_integral": interval("0", "0"),
            "energy_0": interval("0", "0"),
            "norm_id": "L2_SQUARED_PHYSICAL_VOLUME",
        },
    )


def gate_b_request(*, w: str = "1", d: str = "2") -> dict[str, object]:
    req = base_request(
        "gate_b",
        {
            "kind": "vortex_stretching_cutoff_sequence",
            "identity_id": "T3_GLOBAL_ENSTROPHY_IDENTITY_V1",
            "dimension_id": "NU_D_EQUALS_W_L3_PER_T2",
            "cutoff_kind": "fourier_mode_number",
            "cutoffs": [
                {
                    "lambda": "8",
                    "w_truncated": interval(w, w),
                    "w_tail_upper": interval("0", "0"),
                    "d_truncated": interval(d, d),
                    "d_tail_upper": interval("0", "0"),
                    "tail_theorem_id": "TEST_FIXTURE_EXACT_FINITE_SUPPORT_V1",
                    "tail_certificate_digest": HEX_A,
                    "method_digest": HEX_B,
                }
            ],
        },
    )
    # Nonzero fixture observables are not the exact-zero solution.  They are
    # intentionally arithmetic-only so the engine cannot launder them into a
    # PDE conclusion.
    req["solution_link"] = None
    req["scope"]["initial_field_digest"] = HEX_C
    req["scope"]["approximate_field_digest"] = HEX_D
    req["scope"]["reconstruction_digest"] = HEX_D
    return req


class NavierStokesGateTests(unittest.TestCase):
    def test_scope_identity_fields_require_lowercase_sha256(self) -> None:
        for field, bad in (
            ("initial_field_digest", ""),
            ("approximate_field_digest", "not-a-digest"),
            ("reconstruction_digest", "A" * 64),
        ):
            with self.subTest(field=field):
                request = gate_b_request(w="1", d="2")
                request["scope"][field] = bad
                receipt = produce_receipt(request, root=ROOT)
                self.assertEqual(receipt["authority"]["decision_layer"], "closed_json_codec")
                self.assertEqual(receipt["result"]["status"], "refused")
                self.assertEqual(receipt["result"]["reason"], "schema_invalid_digest")

    def test_every_request_digest_field_requires_lowercase_sha256(self) -> None:
        cases = []
        solution_theorem = gate_s_request()
        solution_theorem["solution_link"]["theorem_source_sha256"] = "A" * 64
        cases.append(("solution_theorem", solution_theorem))
        solution_proof = gate_s_request()
        solution_proof["solution_link"]["proof_object_digest"] = "short"
        cases.append(("solution_proof", solution_proof))
        cutoff_tail = gate_b_request(w="1", d="2")
        cutoff_tail["gate_data"]["cutoffs"][0]["tail_certificate_digest"] = "G" * 64
        cases.append(("cutoff_tail", cutoff_tail))
        cutoff_method = gate_b_request(w="1", d="2")
        cutoff_method["gate_data"]["cutoffs"][0]["method_digest"] = ""
        cases.append(("cutoff_method", cutoff_method))
        continuation = base_request(
            "gate_c",
            {
                "kind": "vorticity_continuation_prefix",
                "theorem_id": "BKM1984_EULER_ONLY",
                "theorem_source_sha256": "NOT-A-DIGEST",
                "theorem_locator": "Theorem 1",
                "prefix_bound": interval("0", "1"),
                "terminal_coverage": True,
                "continuum_norm_certified": True,
            },
        )
        cases.append(("continuation_theorem", continuation))
        serrin = base_request(
            "gate_d",
            {
                "kind": "serrin_ess_conditional",
                "theorem_id": "ESS2003_THEOREM_1_2_R3_SERRIN",
                "theorem_source_sha256": ESS_SOURCE_SHA256,
                "theorem_locator": "Theorem 1.2; conditions (1.9)-(1.10)",
                "p": "2",
                "q": "inf",
                "mixed_norm": interval("0", "1"),
                "continuum_norm_certified": True,
                "time_embedding_factor": "1",
            },
        )
        serrin["gate_data"]["theorem_source_sha256"] = "B" * 64
        cases.append(("serrin_theorem", serrin))
        for label, request in cases:
            with self.subTest(label=label):
                receipt = produce_receipt(request, root=ROOT)
                self.assertEqual(receipt["authority"]["decision_layer"], "closed_json_codec")
                self.assertEqual(receipt["result"]["status"], "refused")
                self.assertEqual(receipt["result"]["reason"], "schema_invalid_digest")

    def evaluate(self, request: dict[str, object]) -> dict[str, object]:
        return produce_receipt(request, root=ROOT)

    def test_gate_s_accepts_only_the_exact_zero_identity_fixture(self) -> None:
        result = self.evaluate(gate_s_request())["result"]
        self.assertEqual(result["status"], "bounded")
        self.assertEqual(result["solution_link_status"], "SOLUTION_LINK_VERIFIED")
        self.assertEqual(result["conclusion_status"], "BOUNDED_ON_SCOPE")
        self.assertEqual(result["nonclaim"], "not_a_global_regularity_result")

    def test_gate_s_missing_residual_refuses(self) -> None:
        request = gate_s_request()
        request["solution_link"]["residual_integral_upper"] = ""
        result = self.evaluate(request)["result"]
        self.assertEqual(result["status"], "refused")
        self.assertEqual(result["reason"], "pde_residual_not_certified")

    def test_gate_s_wrong_theorem_domain_refuses(self) -> None:
        request = gate_s_request()
        request["solution_link"]["theorem_id"] = "ESS2003_THEOREM_1_3_R3_ENDPOINT"
        result = self.evaluate(request)["result"]
        self.assertEqual(result["status"], "refused")
        self.assertEqual(result["reason"], "solution_link_theorem_not_admitted_for_domain")

    def test_gate_s_wrong_theorem_locator_refuses(self) -> None:
        request = gate_s_request()
        request["solution_link"]["theorem_locator"] = "caller_asserted_identity"
        result = self.evaluate(request)["result"]
        self.assertEqual(result["status"], "refused")
        self.assertEqual(result["reason"], "solution_link_evidence_not_verified")

    def test_gate_s_wrong_payload_kind_refuses(self) -> None:
        request = gate_s_request()
        request["gate_data"]["kind"] = "caller_asserted_solution"
        result = self.evaluate(request)["result"]
        self.assertEqual(result["status"], "refused")
        self.assertEqual(result["reason"], "gate_payload_schema_invalid")

    def test_gate_a_exact_zero_energy_boundary_is_bounded(self) -> None:
        result = self.evaluate(gate_a_request())["result"]
        self.assertEqual(result["status"], "bounded")
        self.assertEqual(result["arithmetic_status"], "ARITHMETIC_CHECKED")
        self.assertEqual(result["comparison_margin"], "0")

    def test_gate_a_overlap_is_indeterminate_not_violation(self) -> None:
        request = gate_a_request()
        request["gate_data"]["energy_t"] = interval("0", "1")
        result = self.evaluate(request)["result"]
        self.assertEqual(result["status"], "indeterminate")
        self.assertEqual(result["reason"], "energy_interval_condition_not_closed")
        self.assertNotIn("violation", json.dumps(result).lower())

    def test_gate_b_ratio_below_one_is_arithmetic_only_without_gate_s(self) -> None:
        result = self.evaluate(gate_b_request(w="1", d="2"))["result"]
        self.assertEqual(result["status"], "refused")
        self.assertEqual(result["reason"], "solution_link_not_verified")
        self.assertEqual(result["arithmetic_status"], "ARITHMETIC_CHECKED")
        self.assertEqual(result["continuum_status"], "NOT_VERIFIED")
        self.assertEqual(result["ratio_upper"], "1/2")

    def test_gate_b_ratio_equal_one_retains_exact_boundary(self) -> None:
        result = self.evaluate(gate_b_request(w="2", d="2"))["result"]
        self.assertEqual(result["status"], "refused")
        self.assertEqual(result["reason"], "solution_link_not_verified")
        self.assertEqual(result["ratio_upper"], "1")
        self.assertFalse(result["halt"])

    def test_gate_b_ratio_above_one_halts_with_nonimplicative_alert(self) -> None:
        request = gate_b_request(w="3", d="2")
        request["gate_data"]["cutoffs"].append(
            {
                **copy.deepcopy(request["gate_data"]["cutoffs"][0]),
                "lambda": "16",
                "w_truncated": interval("0", "0"),
            }
        )
        result = self.evaluate(request)["result"]
        self.assertEqual(result["status"], "indeterminate")
        self.assertEqual(result["reason"], "uncertified_potential_blowup_vortex_stretching")
        self.assertTrue(result["halt"])
        self.assertEqual(result["failed_cutoff"], "8")
        self.assertEqual(result["evaluated_cutoff_count"], 1)
        self.assertEqual(result["continuum_status"], "NOT_VERIFIED")
        self.assertEqual(result["mathematical_implication"], "none")
        self.assertEqual(result["nonclaim"], "not_evidence_of_singularity")

    def test_gate_b_missing_tail_digest_refuses_at_codec_boundary(self) -> None:
        request = gate_b_request()
        request["gate_data"]["cutoffs"][0]["tail_certificate_digest"] = ""
        result = self.evaluate(request)["result"]
        self.assertEqual(result["status"], "refused")
        self.assertEqual(result["reason"], "schema_invalid_digest")

    def test_gate_b_unknown_tail_theorem_refuses(self) -> None:
        request = gate_b_request()
        request["gate_data"]["cutoffs"][0]["tail_theorem_id"] = "PRODUCER_ASSERTED_TAIL"
        result = self.evaluate(request)["result"]
        self.assertEqual(result["status"], "refused")
        self.assertEqual(result["reason"], "tail_theorem_not_admitted")

    def test_gate_b_fixture_tail_theorem_is_explicitly_registered(self) -> None:
        manifest = json.loads(
            (ROOT / "domain_packs/pde/navier_stokes_v1.json").read_text(encoding="utf-8")
        )
        registry = manifest["theorem_registry"]
        fixture = registry["TEST_FIXTURE_EXACT_FINITE_SUPPORT_V1"]
        self.assertEqual(fixture["enabled_for"], "arithmetic_test_fixtures_only")
        self.assertEqual(fixture["domain"], "T3_periodic")
        self.assertEqual(fixture["continuum_claim"], "none")
        self.assertFalse(fixture["production_admitted"])

    def test_enabled_theorem_prechecks_bind_archived_source_bytes(self) -> None:
        manifest = json.loads(
            (ROOT / "domain_packs/pde/navier_stokes_v1.json").read_text(encoding="utf-8")
        )
        registry = manifest["theorem_registry"]
        expected = {
            "CCRT2007_COROLLARY_5_T3_APOSTERIORI": (
                "domain_packs/pde/sources/CCRT2007_COROLLARY_5_T3_APOSTERIORI.pdf",
                CCRT_SOURCE_SHA256,
            ),
            "ESS2003_THEOREM_1_2_R3_SERRIN": (
                "domain_packs/pde/sources/ESS2003_R3_REGULARITY.pdf",
                ESS_SOURCE_SHA256,
            ),
            "ESS2003_THEOREM_1_3_R3_ENDPOINT": (
                "domain_packs/pde/sources/ESS2003_R3_REGULARITY.pdf",
                ESS_SOURCE_SHA256,
            ),
        }
        for theorem_id, (relative, digest) in expected.items():
            with self.subTest(theorem_id=theorem_id):
                theorem = registry[theorem_id]
                self.assertEqual(theorem["source_path"], relative)
                source = ROOT / relative
                self.assertTrue(source.is_file())
                self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), digest)

    def test_gate_b_t3_identity_refuses_whole_space_transfer(self) -> None:
        request = gate_b_request()
        request["model"]["domain"] = "R3_schwartz_decay"
        request["model"]["period"] = "not_applicable"
        request["model"]["pressure_gauge"] = "decay_at_infinity"
        request["preconditions"]["mean_zero"] = False
        result = self.evaluate(request)["result"]
        self.assertEqual(result["status"], "refused")
        self.assertEqual(result["reason"], "theorem_domain_mismatch")

    def test_gate_b_negative_dissipation_refuses(self) -> None:
        request = gate_b_request()
        request["gate_data"]["cutoffs"][0]["d_truncated"] = interval("-1", "-1")
        result = self.evaluate(request)["result"]
        self.assertEqual(result["status"], "refused")
        self.assertEqual(result["reason"], "negative_energy_or_dissipation")

    def test_gate_b_nonpositive_dissipation_lower_is_indeterminate(self) -> None:
        result = self.evaluate(gate_b_request(w="0", d="0"))["result"]
        self.assertEqual(result["status"], "indeterminate")
        self.assertEqual(result["reason"], "dissipation_lower_bound_not_positive")

    def test_gate_c_euler_bkm_is_never_a_navier_stokes_receipt(self) -> None:
        request = base_request(
            "gate_c",
            {
                "kind": "vorticity_continuation_prefix",
                "theorem_id": "BKM1984_EULER_ONLY",
                "theorem_source_sha256": HEX_A,
                "theorem_locator": "Theorem 1",
                "prefix_bound": interval("0", "1"),
                "terminal_coverage": True,
                "continuum_norm_certified": True,
            },
        )
        result = self.evaluate(request)["result"]
        self.assertEqual(result["status"], "refused")
        self.assertEqual(result["reason"], "euler_theorem_not_applicable_to_navier_stokes")

    def test_gate_c_unaudited_kato_ponce_lane_is_disabled(self) -> None:
        request = base_request(
            "gate_c",
            {
                "kind": "vorticity_continuation_prefix",
                "theorem_id": "KATO_PONCE_1988_NS_CONTINUATION_DISABLED",
                "theorem_source_sha256": HEX_A,
                "theorem_locator": "disabled_pending_exact_theorem_audit",
                "prefix_bound": interval("0", "1"),
                "terminal_coverage": True,
                "continuum_norm_certified": True,
            },
        )
        result = self.evaluate(request)["result"]
        self.assertEqual(result["status"], "refused")
        self.assertEqual(result["reason"], "viscous_continuation_theorem_disabled_pending_audit")

    def test_gate_d_ess_endpoint_is_r3_only_and_separate_from_q_gt_3(self) -> None:
        request = base_request(
            "gate_d",
            {
                "kind": "serrin_ess_conditional",
                "theorem_id": "ESS2003_THEOREM_1_3_R3_ENDPOINT",
                "theorem_source_sha256": ESS_SOURCE_SHA256,
                "theorem_locator": "Theorem 1.3; condition (1.13)",
                "p": "inf",
                "q": "3",
                "mixed_norm": interval("0", "1"),
                "continuum_norm_certified": True,
                "time_embedding_factor": "1",
            },
        )
        request["model"]["domain"] = "R3_schwartz_decay"
        request["model"]["period"] = "not_applicable"
        request["model"]["pressure_gauge"] = "decay_at_infinity"
        request["preconditions"]["mean_zero"] = False
        request["solution_link"] = None
        result = self.evaluate(request)["result"]
        self.assertEqual(
            result["theorem_status"],
            "THEOREM_IDENTITY_MATCHED_PRECONDITIONS_UNVERIFIED",
        )
        self.assertEqual(result["continuum_status"], "NOT_VERIFIED")
        self.assertEqual(result["status"], "refused")
        self.assertEqual(result["reason"], "theorem_preconditions_not_verified")

    def test_gate_d_serrin_supports_q_infinity_exactly(self) -> None:
        request = base_request(
            "gate_d",
            {
                "kind": "serrin_ess_conditional",
                "theorem_id": "ESS2003_THEOREM_1_2_R3_SERRIN",
                "theorem_source_sha256": ESS_SOURCE_SHA256,
                "theorem_locator": "Theorem 1.2; conditions (1.9)-(1.10)",
                "p": "2",
                "q": "inf",
                "mixed_norm": interval("0", "1"),
                "continuum_norm_certified": True,
                "time_embedding_factor": "1",
            },
        )
        request["model"].update(
            domain="R3_schwartz_decay",
            period="not_applicable",
            pressure_gauge="decay_at_infinity",
        )
        request["preconditions"]["mean_zero"] = False
        request["solution_link"] = None
        result = self.evaluate(request)["result"]
        self.assertEqual(result["status"], "refused")
        self.assertEqual(result["reason"], "theorem_preconditions_not_verified")
        self.assertEqual(
            result["theorem_status"],
            "THEOREM_IDENTITY_MATCHED_PRECONDITIONS_UNVERIFIED",
        )

    def test_gate_d_endpoint_refuses_periodic_theorem_transfer(self) -> None:
        request = base_request(
            "gate_d",
            {
                "kind": "serrin_ess_conditional",
                "theorem_id": "ESS2003_THEOREM_1_3_R3_ENDPOINT",
                "theorem_source_sha256": ESS_SOURCE_SHA256,
                "theorem_locator": "Theorem 1.3; condition (1.13)",
                "p": "inf",
                "q": "3",
                "mixed_norm": interval("0", "1"),
                "continuum_norm_certified": True,
                "time_embedding_factor": "1",
            },
        )
        result = self.evaluate(request)["result"]
        self.assertEqual(result["status"], "refused")
        self.assertEqual(result["reason"], "theorem_domain_mismatch")

    def test_gate_d_negative_mixed_norm_refuses(self) -> None:
        request = base_request(
            "gate_d",
            {
                "kind": "serrin_ess_conditional",
                "theorem_id": "ESS2003_THEOREM_1_3_R3_ENDPOINT",
                "theorem_source_sha256": ESS_SOURCE_SHA256,
                "theorem_locator": "Theorem 1.3; condition (1.13)",
                "p": "inf",
                "q": "3",
                "mixed_norm": interval("-1", "0"),
                "continuum_norm_certified": True,
                "time_embedding_factor": "1",
            },
        )
        request["model"]["domain"] = "R3_schwartz_decay"
        request["model"]["period"] = "not_applicable"
        request["model"]["pressure_gauge"] = "decay_at_infinity"
        request["preconditions"]["mean_zero"] = False
        request["solution_link"] = None
        result = self.evaluate(request)["result"]
        self.assertEqual(result["status"], "refused")
        self.assertEqual(result["reason"], "negative_norm_enclosure")

    def test_global_claim_target_is_permanently_refused(self) -> None:
        request = gate_a_request()
        request["requested_claim"] = "global_regular"
        result = self.evaluate(request)["result"]
        self.assertEqual(result["status"], "refused")
        self.assertEqual(result["reason"], "global_regular_claim_not_admitted")

    def test_operation_claim_mismatch_refuses(self) -> None:
        request = gate_a_request()
        request["requested_claim"] = "solution_link_on_scope"
        result = self.evaluate(request)["result"]
        self.assertEqual(result["status"], "refused")
        self.assertEqual(result["reason"], "requested_claim_operation_mismatch")

    def test_noncanonical_rational_refuses_before_policy_evaluation(self) -> None:
        request = gate_a_request()
        request["model"]["viscosity"] = "2/2"
        result = self.evaluate(request)["result"]
        self.assertEqual(result["status"], "refused")
        self.assertEqual(result["reason"], "noncanonical_rational")

    def test_unknown_field_refuses_closed_schema(self) -> None:
        request = gate_a_request()
        request["surprise"] = True
        result = self.evaluate(request)["result"]
        self.assertEqual(result["status"], "refused")
        self.assertEqual(result["reason"], "schema_unknown_field")

    def test_unknown_operation_refuses_in_closed_codec(self) -> None:
        request = gate_a_request()
        request["operation"] = "gate_z"
        receipt = self.evaluate(request)
        self.assertEqual(receipt["result"]["status"], "refused")
        self.assertEqual(receipt["result"]["reason"], "operation_not_admitted")
        self.assertEqual(receipt["authority"]["decision_layer"], "closed_json_codec")
        self.assertFalse(receipt["authority"]["anubis_invoked"])

    def test_strict_json_loader_refuses_duplicate_fields(self) -> None:
        with tempfile.TemporaryDirectory(prefix="navier-json-duplicate-") as temporary:
            path = Path(temporary) / "duplicate.json"
            path.write_text('{"schema":"a","schema":"b"}\n', encoding="utf-8")
            with self.assertRaisesRegex(SchemaRefusal, "schema_duplicate_field"):
                load_json_strict(path)

    def test_receipt_replay_is_deterministic_and_caller_pinned(self) -> None:
        request = gate_a_request()
        first = self.evaluate(request)
        second = self.evaluate(request)
        self.assertEqual(first, second)
        verified = verify_receipt(first, expected_request=request, root=ROOT)
        self.assertEqual(verified["receipt_sha256"], first["receipt_sha256"])

        wrong_request = copy.deepcopy(request)
        wrong_request["scope"]["t1"] = "2"
        with self.assertRaisesRegex(ReceiptRefusal, "request_commitment_mismatch"):
            verify_receipt(first, expected_request=wrong_request, root=ROOT)

    def test_receipt_replay_accepts_canonical_denominator_starting_with_one(self) -> None:
        request = gate_a_request()
        request["model"]["viscosity"] = "1/10"
        receipt = self.evaluate(request)
        self.assertEqual(receipt["result"]["status"], "bounded")
        verified = verify_receipt(receipt, expected_request=request, root=ROOT)
        self.assertEqual(verified["receipt_sha256"], receipt["receipt_sha256"])

    def test_receipt_replay_matches_anubis_scope_refusal(self) -> None:
        request = gate_s_request()
        request["scope"]["terminal_role"] = "candidate_blowup_time"
        receipt = self.evaluate(request)
        self.assertEqual(receipt["result"]["reason"], "model_or_precondition_not_admitted")
        verified = verify_receipt(receipt, expected_request=request, root=ROOT)
        self.assertEqual(verified["receipt_sha256"], receipt["receipt_sha256"])

    def test_receipt_replay_matches_gate_d_payload_refusal(self) -> None:
        request = base_request(
            "gate_d",
            {
                "kind": "caller_asserted_serrin",
                "theorem_id": "ESS2003_THEOREM_1_3_R3_ENDPOINT",
                "theorem_source_sha256": ESS_SOURCE_SHA256,
                "theorem_locator": "Theorem 1.3; condition (1.13)",
                "p": "inf",
                "q": "3",
                "mixed_norm": interval("0", "1"),
                "continuum_norm_certified": True,
                "time_embedding_factor": "1",
            },
        )
        request["model"]["domain"] = "R3_schwartz_decay"
        request["model"]["period"] = "not_applicable"
        request["model"]["pressure_gauge"] = "decay_at_infinity"
        request["preconditions"]["mean_zero"] = False
        request["solution_link"] = None
        receipt = self.evaluate(request)
        self.assertEqual(receipt["result"]["reason"], "gate_payload_schema_invalid")
        verified = verify_receipt(receipt, expected_request=request, root=ROOT)
        self.assertEqual(verified["receipt_sha256"], receipt["receipt_sha256"])

    def test_receipt_replay_pins_anubis_binary_identity(self) -> None:
        request = gate_a_request()
        receipt = self.evaluate(request)
        receipt["authority"]["anubis_binary_sha256"] = "0" * 64
        body = {key: receipt[key] for key in receipt if key != "receipt_sha256"}
        receipt["receipt_sha256"] = sha256_bytes(canonical_json_bytes(body))
        with self.assertRaisesRegex(ReceiptRefusal, "anubis_binary_identity_mismatch"):
            verify_receipt(receipt, expected_request=request, root=ROOT)


if __name__ == "__main__":
    unittest.main(verbosity=2)
