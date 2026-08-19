#!/usr/bin/env python3
"""Contract for v1.7.2 proof identities and archival compatibility policy."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import unittest
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
RANGE_V1 = ROOT / "release" / "evidence" / "range_proof_identity.json"
INT_V1 = ROOT / "release" / "evidence" / "int_cert_proof_identity.json"
RANGE_V2 = ROOT / "release" / "evidence" / "range_proof_identity_v172.json"
INT_V2 = ROOT / "release" / "evidence" / "int_cert_proof_identity_v172.json"
COMPAT = ROOT / "release" / "compat" / "v172_floor.json"
GENERATOR = ROOT / "release" / "tools" / "range_proof_identity.py"

ARCHIVAL_HASHES = {
    RANGE_V1: "1b2d623904930d748bfbf489637e0e8aa720188e7d68f5250e5bd8f257b89a67",
    INT_V1: "f0323e312d8b0e05a7200546fd819fc191d5f146d359bb14efec5b1575f16844",
}


def strict_load(path: Path) -> dict[str, Any]:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate key: {key}")
            result[key] = value
        return result

    document = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=reject_duplicates)
    if not isinstance(document, dict):
        raise ValueError("document root must be an object")
    return document


class ProofIdentityV172ContractTests(unittest.TestCase):
    def test_archival_v1_identity_bytes_are_unchanged(self) -> None:
        for path, expected in ARCHIVAL_HASHES.items():
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), expected)

    def test_range_v2_closes_every_runtime_premise(self) -> None:
        record = strict_load(RANGE_V2)
        self.assertEqual(record["schema"], "jackal-range-proof-identity-v2")
        fragment = record["fragment"]
        self.assertEqual(
            fragment["theorem_premises"],
            [
                "requestMatches command rawExpr rawLo rawHi hdr nodes = true (runtime checked)",
                "checkCert hdr nodes = true (runtime checked)",
            ],
        )
        self.assertEqual(fragment["premises_not_discharged_by_checker"], [])
        audited = {item["theorem"] for item in record["proof"]["theorems"]}
        self.assertIn("JackalIv.Cert.requestMatches_interval_order", audited)
        self.assertIn("JackalIv.Cert.releaseNodesOk_modelTCB", audited)

    def test_int_cert_v2_closes_tree_tcb_and_binds_raw_request(self) -> None:
        record = strict_load(INT_V2)
        self.assertEqual(record["schema"], "jackal-int-cert-proof-identity-v2")
        fragment = record["fragment"]
        self.assertEqual(
            fragment["theorem_premises"],
            [
                "checkIntCertRequest rawExpr rawLo rawHi rawTol hdr tree = .ok () (runtime checked)",
            ],
        )
        self.assertEqual(fragment["premises_not_discharged_by_checker"], [])
        audited = {item["theorem"] for item in record["proof"]["theorems"]}
        self.assertIn("JackalIv.IntCert.intRequestMatches_true", audited)
        self.assertIn("JackalIv.IntCert.rootRawExpr_rootQExpr_embed", audited)

    def test_compatibility_floor_is_explicit_and_fail_closed(self) -> None:
        policy = strict_load(COMPAT)
        self.assertEqual(policy["schema"], "jackal-proof-compatibility-floor-v1")
        self.assertEqual(policy["current_release_epoch"], "v1.7.2")
        self.assertEqual(policy["unsupported_policy"], "refuse")
        self.assertEqual(policy["reversed_interval_policy"], "revoked-refuse")
        for lane in ("range", "int_cert"):
            self.assertEqual(policy["lanes"][lane]["current"]["minimum_schema_version"], 2)
        self.assertEqual(policy["lanes"]["range"]["archival_v1"]["mode"],
                         "replay-only")
        revoked = policy["lanes"]["int_cert"]["archival_v1"]
        self.assertEqual(revoked["mode"], "revoked-refuse")
        self.assertEqual(revoked["allowed_release_epochs"], [])
        self.assertIn("does not bind the raw request", revoked["reason"])

    def test_lane_specific_generator_exists(self) -> None:
        self.assertTrue(GENERATOR.is_file())

    def test_lane_specific_generator_defaults_to_range_without_overriding_lane(self) -> None:
        spec = importlib.util.spec_from_file_location("range_proof_identity_v172", GENERATOR)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        try:
            spec.loader.exec_module(module)
            self.assertEqual(
                module._normalized_argv(["check", "--identity", "identity.json"]),
                ["check", "--lane", "range", "--identity", "identity.json"],
            )
            self.assertEqual(
                module._normalized_argv(["check", "--lane", "int-cert"]),
                ["check", "--lane", "int-cert"],
            )
        finally:
            sys.modules.pop(spec.name, None)


if __name__ == "__main__":
    unittest.main(verbosity=2)
