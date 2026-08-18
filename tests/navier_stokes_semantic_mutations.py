#!/usr/bin/env python3
"""A-to-B-to-A semantic mutation battery for Navier--Stokes v1 receipts."""

from __future__ import annotations

import argparse
import copy
import json
import math
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tests"))

from navier_stokes_certificate_producer import (  # noqa: E402
    ESS_SOURCE_SHA256,
    canonical_json_bytes,
    produce_receipt,
    sha256_bytes,
)
from navier_stokes_gate_test import (  # noqa: E402
    base_request,
    gate_a_request,
    gate_b_request,
    gate_s_request,
    interval,
)
from navier_stokes_receipt_verify import ReceiptRefusal, verify_receipt  # noqa: E402


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def request_mutation(
    name: str,
    baseline: dict,
    mutate,
    expected_status: str,
    expected_reason: str,
) -> dict:
    pre = produce_receipt(baseline, root=ROOT)
    poisoned = copy.deepcopy(baseline)
    mutate(poisoned)
    middle = produce_receipt(poisoned, root=ROOT)
    post = produce_receipt(baseline, root=ROOT)
    require(pre == post, f"{name}: A/post drift")
    require(middle["result"]["status"] == expected_status, f"{name}: status")
    require(middle["result"]["reason"] == expected_reason, f"{name}: reason")
    require(middle["receipt_sha256"] != pre["receipt_sha256"], f"{name}: identity did not change")
    return {
        "name": name,
        "pre_sha256": pre["receipt_sha256"],
        "poison_sha256": middle["receipt_sha256"],
        "post_sha256": post["receipt_sha256"],
        "poison_status": middle["result"]["status"],
        "poison_reason": middle["result"]["reason"],
        "aba_restored": pre == post,
    }


def launder_receipt(
    name: str,
    baseline_request: dict,
    mutate,
    *,
    expected_refusal: str = "anubis_reexecution_mismatch",
) -> dict:
    original = produce_receipt(baseline_request, root=ROOT)
    poisoned = copy.deepcopy(original)
    mutate(poisoned)
    body = {key: poisoned[key] for key in poisoned if key != "receipt_sha256"}
    poisoned["receipt_sha256"] = sha256_bytes(canonical_json_bytes(body))
    try:
        verify_receipt(poisoned, expected_request=baseline_request, root=ROOT)
    except ReceiptRefusal as exc:
        require(expected_refusal in str(exc), f"{name}: wrong refusal {exc}")
        verified_refusal = str(exc)
    else:
        raise AssertionError(f"{name}: laundered receipt verified")
    restored = produce_receipt(baseline_request, root=ROOT)
    require(restored == original, f"{name}: A/post drift")
    return {
        "name": name,
        "pre_sha256": original["receipt_sha256"],
        "poison_sha256": poisoned["receipt_sha256"],
        "post_sha256": restored["receipt_sha256"],
        "poison_refusal": verified_refusal,
        "aba_restored": restored == original,
    }


def gate_d_request() -> dict:
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
    request["model"].update(
        domain="R3_schwartz_decay",
        period="not_applicable",
        pressure_gauge="decay_at_infinity",
    )
    request["preconditions"]["mean_zero"] = False
    request["solution_link"] = None
    return request


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-out", type=Path)
    args = parser.parse_args()
    results = []
    results.append(request_mutation(
        "missing-pde-residual",
        gate_s_request(),
        lambda req: req["solution_link"].__setitem__("residual_integral_upper", ""),
        "refused",
        "pde_residual_not_certified",
    ))
    results.append(request_mutation(
        "wrong-solution-theorem-domain",
        gate_s_request(),
        lambda req: req["solution_link"].__setitem__("theorem_id", "ESS2003_THEOREM_1_3_R3_ENDPOINT"),
        "refused",
        "solution_link_theorem_not_admitted_for_domain",
    ))
    results.append(request_mutation(
        "wrong-zero-proof-object",
        gate_s_request(),
        lambda req: req["solution_link"].__setitem__("proof_object_digest", "0" * 64),
        "refused",
        "solution_link_evidence_not_verified",
    ))
    results.append(request_mutation(
        "missing-cutoff-tail-digest",
        gate_b_request(),
        lambda req: req["gate_data"]["cutoffs"][0].__setitem__("tail_certificate_digest", ""),
        "refused",
        "schema_invalid_digest",
    ))
    results.append(request_mutation(
        "reversed-energy-interval",
        gate_a_request(),
        lambda req: req["gate_data"].__setitem__("energy_t", {"lower": "1", "upper": "0"}),
        "refused",
        "noncanonical_rational",
    ))
    results.append(request_mutation(
        "nonreduced-viscosity",
        gate_a_request(),
        lambda req: req["model"].__setitem__("viscosity", "2/2"),
        "refused",
        "noncanonical_rational",
    ))
    results.append(request_mutation(
        "infinite-computed-enclosure",
        gate_a_request(),
        lambda req: req["gate_data"]["energy_t"].__setitem__("upper", "inf"),
        "refused",
        "noncanonical_rational",
    ))
    results.append(request_mutation(
        "global-status-target",
        gate_a_request(),
        lambda req: req.__setitem__("requested_claim", "millennium_solved"),
        "refused",
        "global_regular_claim_not_admitted",
    ))
    results.append(request_mutation(
        "nondegenerate-viscosity-interval-not-admitted",
        gate_a_request(),
        lambda req: req["model"].__setitem__("viscosity", {"lower": "1", "upper": "2"}),
        "refused",
        "schema_type_mismatch",
    ))
    ratio_resource = gate_b_request(w="1000000000", d="1")
    ratio_resource["model"]["viscosity"] = "1/1000000000"
    results.append(request_mutation(
        "computed-ratio-resource-bound",
        gate_b_request(w="1", d="2"),
        lambda req: req.update(ratio_resource),
        "refused",
        "rational_resource_bound_exceeded",
    ))

    # Non-JSON NaN is rejected at the codec boundary and still receives a
    # deterministic refusal commitment rather than throwing or reaching Anubis.
    nan_request = gate_a_request()
    nan_request["gate_data"]["energy_t"]["upper"] = math.nan
    nan_receipt = produce_receipt(nan_request, root=ROOT)
    require(nan_receipt["result"]["status"] == "refused", "nan: status")
    require(nan_receipt["result"]["reason"] == "noncanonical_numeric_type", "nan: reason")
    results.append({
        "name": "nan-numeric-payload",
        "poison_sha256": nan_receipt["receipt_sha256"],
        "poison_status": nan_receipt["result"]["status"],
        "poison_reason": nan_receipt["result"]["reason"],
        "aba_restored": True,
    })

    results.append(launder_receipt(
        "status-laundering",
        gate_b_request(w="1", d="2"),
        lambda receipt: receipt["result"].update(
            status="bounded",
            reason="localized_ratio_bound_verified",
            solution_link_status="SOLUTION_LINK_VERIFIED",
            conclusion_status="BOUNDED_ON_SCOPE",
        ),
    ))
    results.append(launder_receipt(
        "historical-failed-mutable-anubis-locator-laundering",
        gate_a_request(),
        lambda receipt: receipt["authority"].update(
            anubis_binary_locator_id="macos-account-home-relative-v1:mutable-anubis",
            anubis_binary_sha256=(
                "666b021815c3591437433bcdf881d063a8da0c5b055a5f4f23bd7bee865befd9"
            ),
            anubis_binary_size_bytes=99_415_712,
        ),
        expected_refusal="anubis_binary_locator_identity_mismatch",
    ))
    results.append(launder_receipt(
        "alert-nonclaim-removal",
        gate_b_request(w="3", d="2"),
        lambda receipt: receipt["result"].update(
            mathematical_implication="singularity",
            nonclaim="none",
        ),
    ))
    results.append(launder_receipt(
        "cutoff-identity-laundering",
        gate_b_request(w="1", d="2"),
        lambda receipt: receipt["result"].update(failed_cutoff="16"),
    ))
    results.append(launder_receipt(
        "threshold-ge-for-gt-laundering",
        gate_b_request(w="2", d="2"),
        lambda receipt: receipt["result"].update(
            status="indeterminate",
            reason="uncertified_potential_blowup_vortex_stretching",
            halt=True,
            failed_cutoff="8",
            mathematical_implication="none",
            nonclaim="not_evidence_of_singularity",
        ),
    ))
    results.append(launder_receipt(
        "gate-d-theorem-applicable-laundering",
        gate_d_request(),
        lambda receipt: receipt["result"].update(
            status="bounded",
            reason="caller_promoted_theorem",
            theorem_status="THEOREM_APPLICABLE",
            conclusion_status="BOUNDED_ON_SCOPE",
        ),
    ))

    dissipation_endpoint = gate_b_request(w="1", d="2")
    dissipation_endpoint["gate_data"]["cutoffs"][0]["d_truncated"] = {"lower": "2", "upper": "4"}
    results.append(launder_receipt(
        "dissipation-upper-for-lower-laundering",
        dissipation_endpoint,
        lambda receipt: receipt["result"].update(
            ratio_upper="1/4",
            comparison_margin="3",
        ),
    ))

    evidence = {
        "schema": "jackal-navier-stokes-semantic-mutations-v1",
        "mutation_count": len(results),
        "all_refused_or_changed": True,
        "all_aba_restored": all(item["aba_restored"] for item in results),
        "results": results,
        "nonclaims": [
            "mutation_rejection_does_not_prove_checker_soundness",
            "no_global_regularity_claim",
            "no_singularity_claim",
        ],
    }
    if args.evidence_out is not None:
        args.evidence_out.parent.mkdir(parents=True, exist_ok=True)
        args.evidence_out.write_bytes(canonical_json_bytes(evidence) + b"\n")
    print(json.dumps(evidence, sort_keys=True, indent=2))
    print("NAVIER_STOKES_SEMANTIC_MUTATIONS=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
