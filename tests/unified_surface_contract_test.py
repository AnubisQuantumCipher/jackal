#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugin/hermes"
PROGRAM_TOOLS = [
    "jackal_anubis_check_program",
    "jackal_anubis_verify_program",
    "jackal_anubis_verify_program_receipt",
]
BASELINE_TOOLS = [
    "jackal_range_bound",
    "jackal_gaussian_integral",
    "jackal_integrate_bound_cert",
    "jackal_verify_receipt",
    "jackal_sqrt_rat_bound",
    "jackal_exp_rat_bound",
    "jackal_ln_rat_bound",
    "jackal_sin_rat_bound",
    "jackal_cos_rat_bound",
    "jackal_atan_rat_bound",
    "jackal_tanh_rat_bound",
    "jackal_exact",
    "jackal_evaluate",
    "jackal_diff",
    "jackal_integrate",
    "jackal_integrate_adaptive",
    "jackal_integrate_bound",
    "jackal_solve",
    "jackal_canon",
    "jackal_poly_canon",
    "jackal_poly_eq",
    "jackal_poly_gcd",
    "jackal_ratfunc_canon",
    "jackal_roots_isolate",
    "jackal_alg_sign",
    "jackal_alg_cmp",
    "jackal_xgcd",
    "jackal_mod_pow",
    "jackal_mod_inv",
    "jackal_crt",
    "jackal_divides",
    "jackal_prime_cert",
    "jackal_claim",
    "jackal_verify_bundle",
    "jackal_test_exists",
    "jackal_claim_cites_test",
    "jackal_decision_rank",
    "jackal_decision_rank_v2",
]
EXPECTED_FULL = [*BASELINE_TOOLS, *PROGRAM_TOOLS]
EXPECTED_CORE = [
    "jackal_verify_receipt",
    "jackal_claim",
    "jackal_verify_bundle",
]
EXPECTED_FORMAL = [
    "jackal_range_bound",
    "jackal_gaussian_integral",
    "jackal_integrate_bound_cert",
    "jackal_verify_receipt",
    "jackal_sqrt_rat_bound",
    "jackal_exp_rat_bound",
    "jackal_ln_rat_bound",
    "jackal_sin_rat_bound",
    "jackal_cos_rat_bound",
    "jackal_atan_rat_bound",
    "jackal_tanh_rat_bound",
    "jackal_claim",
    "jackal_verify_bundle",
]
PROGRAM_RUNTIME_FILES = {
    "runtime/anubis_program_verify.py",
    "runtime/anubis_program_policy.json",
}
DOMAIN_MANIFEST_LABELS = {
    "domain_pack_registry",
    "domain_pack_verifier",
    "domain_pack_test_exists_checker",
    "domain_pack_decision_checker",
}


def digest_profile(document: dict) -> str:
    payload = {
        key: value
        for key, value in document.items()
        if key != "profile_digest_sha256"
    }
    return hashlib.sha256(
        json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
    ).hexdigest()


class UnifiedSurfaceContractTest(unittest.TestCase):
    def test_catalog_is_exact_combined_41_tool_surface(self) -> None:
        catalog = json.loads((PLUGIN / "tools.json").read_text(encoding="utf-8"))
        names = [row["name"] for row in catalog["tools"]]
        self.assertEqual(catalog["version"], "v1.7.3")
        self.assertEqual(names, EXPECTED_FULL)
        self.assertEqual(len(names), 41)
        self.assertEqual(len(set(names)), 41)

    def test_core_and_formal_are_unchanged_program_tools_are_full_only(self) -> None:
        profiles = {
            name: json.loads(
                (PLUGIN / f"profiles/{name}.json").read_text(encoding="utf-8")
            )
            for name in ("core", "formal", "full")
        }
        self.assertEqual(profiles["core"]["tools"], EXPECTED_CORE)
        self.assertEqual(profiles["formal"]["tools"], EXPECTED_FORMAL)
        self.assertEqual(profiles["full"]["tools"], EXPECTED_FULL)
        for name, document in profiles.items():
            self.assertEqual(document["profile_digest_sha256"], digest_profile(document), name)
        for tool in PROGRAM_TOOLS:
            self.assertNotIn(tool, profiles["core"]["tools"])
            self.assertNotIn(tool, profiles["formal"]["tools"])
            self.assertIn(tool, profiles["full"]["tools"])

    def test_program_is_bundle_bound_and_domain_surface_is_call_local_pinned(self) -> None:
        catalog = json.loads((PLUGIN / "tools.json").read_text(encoding="utf-8"))
        runtime_files = set(catalog["runtime_files"])
        self.assertTrue(PROGRAM_RUNTIME_FILES <= runtime_files)
        self.assertFalse(any(name.startswith("runtime/domain_pack") for name in runtime_files))
        manifest_labels = {
            line.split()[0]
            for line in (ROOT / "release/MANIFEST.sha256").read_text().splitlines()
            if line and not line.startswith("#")
        }
        self.assertTrue(DOMAIN_MANIFEST_LABELS <= manifest_labels)

    def test_server_dispatch_declares_all_catalog_tools_once(self) -> None:
        source = (PLUGIN / "server.py").read_text(encoding="utf-8")
        for tool in PROGRAM_TOOLS:
            self.assertEqual(source.count(f'"{tool}"'), 1, tool)
        for tool in BASELINE_TOOLS:
            self.assertIn(tool, source, tool)


if __name__ == "__main__":
    unittest.main()
