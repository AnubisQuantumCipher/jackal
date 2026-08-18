#!/usr/bin/env python3
"""Cross-check the frozen external report against repository receipt semantics."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    require(isinstance(value, dict), f"not an object: {path}")
    return value


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--external-bundle", required=True, type=Path)
    args = parser.parse_args()
    external = args.external_bundle.resolve()
    crosswalk = load_json(ROOT / "release/evidence/navier_stokes_report_crosswalk.json")
    index = load_json(ROOT / "release/evidence/navier_stokes_fixture_receipts/index.json")
    manifest = load_json(ROOT / "domain_packs/pde/navier_stokes_v1.json")
    runtime = crosswalk["repository_runtime_authority"]
    require(runtime["anubis_binary_locator_id"] == manifest["platform"]["anubis_binary_locator_id"],
            "repository runtime locator crosswalk drift")
    require(runtime["anubis_binary_relative_candidates"] == manifest["platform"]["anubis_binary_relative_candidates"],
            "repository runtime candidates crosswalk drift")
    require(runtime["anubis_binary_sha256"] == manifest["platform"]["anubis_binary_sha256"],
            "repository runtime digest crosswalk drift")
    require(runtime["anubis_execution_binding"] == "descriptor_snapshot_v1",
            "repository runtime execution binding drift")
    require(runtime["mutable_target_release_is_authoritative"] is False,
            "mutable Anubis path was promoted")

    require(
        sha256_file(external / "SOURCE_MANIFEST.json")
        == crosswalk["external_report_source_manifest_sha256"],
        "external source manifest identity mismatch",
    )
    require(
        sha256_file(external / "VERIFICATION_RECEIPT.txt")
        == crosswalk["external_report_verification_receipt_sha256"],
        "external verification receipt identity mismatch",
    )
    external_receipts = {
        fixture: load_json(external / "receipts" / f"{fixture}.json")
        for fixture in crosswalk["external_fixture_sha256"]
    }
    for fixture, digest in crosswalk["external_fixture_sha256"].items():
        require(
            sha256_file(external / "receipts" / f"{fixture}.json") == digest,
            f"external fixture identity mismatch: {fixture}",
        )

    repository = {item["fixture_id"]: item for item in index["fixtures"]}
    arithmetic = external_receipts["gate_s_missing_refusal"]
    require(arithmetic["outcome"] == {
        "status": "ARITHMETIC_CHECKED",
        "reason": "solution_link_missing",
        "reject_global_claim": True,
    }, "external arithmetic transition drift")
    require(
        repository["gate_b_ratio_lt_one_arithmetic_only"]["status"] == "refused"
        and repository["gate_b_ratio_lt_one_arithmetic_only"]["arithmetic_status"]
        == "ARITHMETIC_CHECKED"
        and repository["gate_b_ratio_lt_one_arithmetic_only"]["continuum_status"]
        == "NOT_VERIFIED",
        "repository arithmetic crosswalk drift",
    )

    alert = external_receipts["gate_b_ratio_alert"]
    require(
        alert["outcome"]["status"] == "refused"
        and alert["outcome"]["reason"]
        == "uncertified_potential_blowup_vortex_stretching",
        "external alert transition drift",
    )
    require(
        repository["gate_b_ratio_gt_one_alert"]["status"] == "indeterminate"
        and repository["gate_b_ratio_gt_one_alert"]["halt"] is True
        and repository["gate_b_ratio_gt_one_alert"]["continuum_status"]
        == "NOT_VERIFIED",
        "repository alert crosswalk drift",
    )

    zero = external_receipts["exact_zero_solution_scope"]
    require(
        zero["outcome"]["status"] == "BOUNDED_ON_SCOPE"
        and zero["gate_s"]["verified"] is True
        and zero["gate_s"]["theorem_id"]
        == "JACKAL_T3_ZERO_SOLUTION_IDENTITY_V1",
        "external exact-zero transition drift",
    )
    require(
        repository["gate_s_zero_bounded"]["status"] == "bounded"
        and repository["gate_s_zero_bounded"]["conclusion_status"]
        == "BOUNDED_ON_SCOPE",
        "repository exact-zero crosswalk drift",
    )

    for receipt in external_receipts.values():
        require(receipt["scope"]["tail_bound_included"] is True, "external tail declaration drift")
        require("not_evidence_of_singularity" in receipt["nonclaims"], "external nonclaim missing")
    require(
        crosswalk["dissipation_semantics"]["external_report_dissipation_lower"]
        == "already_viscosity_weighted_lower_bound"
        and crosswalk["dissipation_semantics"]["repository_d_truncated"]
        == "unweighted_dissipation_enclosure"
        and crosswalk["dissipation_semantics"]["forbid_double_viscosity_weighting"]
        is True,
        "dissipation weighting crosswalk drift",
    )
    print("NAVIER_STOKES_REPORT_CROSSCHECK=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
