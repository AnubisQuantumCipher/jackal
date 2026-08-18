#!/usr/bin/env python3
"""Build and independently replay the bounded Navier--Stokes v1 fixtures."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from navier_stokes_certificate_producer import (  # noqa: E402
    ANUBIS_EXECUTION_BINDING,
    ESS_SOURCE_SHA256,
    EXPECTED_ANUBIS_BINARY_LOCATOR_ID,
    EXPECTED_ANUBIS_BINARY_RELATIVE_CANDIDATES,
    EXPECTED_ANUBIS_BINARY_SHA256,
    EXPECTED_ANUBIS_BINARY_SIZE,
    ZERO_FIELD_SHA256,
    ZERO_PROOF_OBJECT_SHA256,
    ZERO_THEOREM_SHA256,
    canonical_json_bytes,
    produce_receipt,
    sha256_file,
)
from navier_stokes_receipt_verify import verify_receipt  # noqa: E402


HEX_A = "a" * 64
HEX_B = "b" * 64
HEX_C = "c" * 64
HEX_D = "d" * 64


def interval(lower: str, upper: str) -> dict[str, str]:
    return {"lower": lower, "upper": upper}


def zero_solution_link() -> dict[str, Any]:
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


def base_request(operation: str, gate_data: dict[str, Any]) -> dict[str, Any]:
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


def gate_b_request(w: str, d: str) -> dict[str, Any]:
    request = base_request(
        "gate_b",
        {
            "kind": "vortex_stretching_cutoff_sequence",
            "identity_id": "T3_GLOBAL_ENSTROPHY_IDENTITY_V1",
            "dimension_id": "NU_D_EQUALS_W_L3_PER_T2",
            "cutoff_kind": "fourier_mode_number",
            "cutoffs": [{
                "lambda": "8",
                "w_truncated": interval(w, w),
                "w_tail_upper": interval("0", "0"),
                "d_truncated": interval(d, d),
                "d_tail_upper": interval("0", "0"),
                "tail_theorem_id": "TEST_FIXTURE_EXACT_FINITE_SUPPORT_V1",
                "tail_certificate_digest": HEX_A,
                "method_digest": HEX_B,
            }],
        },
    )
    request["solution_link"] = None
    request["scope"].update(
        initial_field_digest=HEX_C,
        approximate_field_digest=HEX_D,
        reconstruction_digest=HEX_D,
    )
    return request


def fixtures() -> dict[str, dict[str, Any]]:
    gate_d = base_request(
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
    gate_d["model"].update(
        domain="R3_schwartz_decay",
        period="not_applicable",
        pressure_gauge="decay_at_infinity",
    )
    gate_d["preconditions"]["mean_zero"] = False
    gate_d["solution_link"] = None

    return {
        "gate_s_zero_bounded": base_request("gate_s", {"kind": "solution_link"}),
        "gate_a_zero_bounded": base_request("gate_a", {
            "kind": "energy_prefix",
            "energy_t": interval("0", "0"),
            "dissipation_integral": interval("0", "0"),
            "energy_0": interval("0", "0"),
            "norm_id": "L2_SQUARED_PHYSICAL_VOLUME",
        }),
        "gate_b_ratio_lt_one_arithmetic_only": gate_b_request("1", "2"),
        "gate_b_ratio_eq_one_arithmetic_only": gate_b_request("2", "2"),
        "gate_b_ratio_gt_one_alert": gate_b_request("3", "2"),
        "gate_c_bkm_euler_refused": base_request("gate_c", {
            "kind": "vorticity_continuation_prefix",
            "theorem_id": "BKM1984_EULER_ONLY",
            "theorem_source_sha256": HEX_A,
            "theorem_locator": "Theorem 1",
            "prefix_bound": interval("0", "1"),
            "terminal_coverage": True,
            "continuum_norm_certified": True,
        }),
        "gate_c_kato_ponce_disabled": base_request("gate_c", {
            "kind": "vorticity_continuation_prefix",
            "theorem_id": "KATO_PONCE_1988_NS_CONTINUATION_DISABLED",
            "theorem_source_sha256": HEX_A,
            "theorem_locator": "disabled_pending_exact_theorem_audit",
            "prefix_bound": interval("0", "1"),
            "terminal_coverage": True,
            "continuum_norm_certified": True,
        }),
        "gate_d_ess_endpoint_preconditions_unverified": gate_d,
    }


def main() -> int:
    request_dir = HERE / "requests"
    receipt_dir = HERE / "receipts"
    request_dir.mkdir(parents=True, exist_ok=True)
    receipt_dir.mkdir(parents=True, exist_ok=True)
    entries = []
    for fixture_id, request in sorted(fixtures().items()):
        receipt = produce_receipt(request, root=ROOT)
        verify_receipt(receipt, expected_request=request, root=ROOT)
        request_path = request_dir / f"{fixture_id}.json"
        receipt_path = receipt_dir / f"{fixture_id}.json"
        request_path.write_bytes(canonical_json_bytes(request) + b"\n")
        receipt_path.write_bytes(canonical_json_bytes(receipt) + b"\n")
        entries.append({
            "fixture_id": fixture_id,
            "request_path": str(request_path.relative_to(ROOT)),
            "request_file_sha256": sha256_file(request_path),
            "receipt_path": str(receipt_path.relative_to(ROOT)),
            "receipt_file_sha256": sha256_file(receipt_path),
            "receipt_sha256": receipt["receipt_sha256"],
            "status": receipt["result"]["status"],
            "reason": receipt["result"]["reason"],
            "arithmetic_status": receipt["result"]["arithmetic_status"],
            "continuum_status": receipt["result"]["continuum_status"],
            "solution_link_status": receipt["result"]["solution_link_status"],
            "theorem_status": receipt["result"]["theorem_status"],
            "conclusion_status": receipt["result"]["conclusion_status"],
            "halt": receipt["result"]["halt"],
        })
    index = {
        "schema": "jackal-navier-stokes-fixture-index-v1",
        "fixture_count": len(entries),
        "authoritative_source_sha256": sha256_file(
            ROOT / "domain_packs/pde/navier_stokes_v1.anb"
        ),
        "pack_manifest_sha256": sha256_file(
            ROOT / "domain_packs/pde/navier_stokes_v1.json"
        ),
        "anubis_binary_sha256": EXPECTED_ANUBIS_BINARY_SHA256,
        "anubis_binary_locator_id": EXPECTED_ANUBIS_BINARY_LOCATOR_ID,
        "anubis_binary_relative_candidates": list(
            EXPECTED_ANUBIS_BINARY_RELATIVE_CANDIDATES
        ),
        "anubis_binary_size_bytes": EXPECTED_ANUBIS_BINARY_SIZE,
        "anubis_execution_binding": ANUBIS_EXECUTION_BINDING,
        "claim_audit_sha256": sha256_file(
            ROOT / "release/evidence/navier_stokes_claim_audit.json"
        ),
        "report_crosswalk_sha256": sha256_file(
            ROOT / "release/evidence/navier_stokes_report_crosswalk.json"
        ),
        "fixtures": entries,
        "nonclaims": [
            "fixtures_do_not_prove_global_regularity",
            "gate_b_fixture_tails_are_not_continuum_verified",
            "ratio_alert_is_not_evidence_of_singularity",
        ],
    }
    (HERE / "index.json").write_bytes(canonical_json_bytes(index) + b"\n")
    print(f"NAVIER_STOKES_FIXTURE_COUNT={len(entries)}")
    print("NAVIER_STOKES_FIXTURE_REPLAY=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
