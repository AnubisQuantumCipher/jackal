#!/usr/bin/env python3
"""Fail-closed receipt compatibility contract for the v1.7.2 proof floor."""

from __future__ import annotations

import copy
import hashlib
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import formal_receipt as fr  # noqa: E402
import receipt_verify as rv  # noqa: E402


RANGE_V1 = ROOT / "release/evidence/range_proof_identity.json"
RANGE_V2 = ROOT / "release/evidence/range_proof_identity_v172.json"
INT_V1 = ROOT / "release/evidence/int_cert_proof_identity.json"
INT_V2 = ROOT / "release/evidence/int_cert_proof_identity_v172.json"
COMPAT = ROOT / "release/compat/v172_floor.json"
RANGE_WRAPPER = ROOT / "jackal-cert-release"
INT_WRAPPER = ROOT / "jackal-int-cert-release"
RATIONAL_WRAPPERS = [
    ROOT / name
    for name in (
        "jackal-sqrt-rat-release",
        "jackal-exp-rat-release",
        "jackal-ln-rat-release",
        "jackal-sin-rat-release",
        "jackal-cos-rat-release",
        "jackal-atan-rat-release",
        "jackal-tanh-rat-release",
    )
]


def binding(path: Path) -> dict:
    return fr.load_proof_identity_binding(path)


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class ProofCompatibilityV172Tests(unittest.TestCase):
    def test_code_authority_matches_committed_compatibility_record(self) -> None:
        self.assertEqual(
            fr.proof_compatibility_policy_document(),
            json.loads(COMPAT.read_text(encoding="utf-8")),
        )

    def test_release_wrappers_select_only_current_identity_and_epoch(self) -> None:
        range_wrapper = RANGE_WRAPPER.read_text(encoding="utf-8")
        int_wrapper = INT_WRAPPER.read_text(encoding="utf-8")
        self.assertIn("range_proof_identity_v172.json", range_wrapper)
        self.assertIn("int_cert_proof_identity_v172.json", int_wrapper)
        self.assertIn("--release-epoch v1.7.2", range_wrapper)
        self.assertIn("--release-epoch v1.7.2", int_wrapper)

    def test_rational_wrappers_select_current_v2_identity_and_epoch(self) -> None:
        for wrapper in RATIONAL_WRAPPERS:
            with self.subTest(wrapper=wrapper.name):
                source = wrapper.read_text(encoding="utf-8")
                self.assertIn("range_proof_identity_v172.json", source)
                self.assertIn('--release-epoch v1.7.2', source)
                self.assertNotIn('release_epoch="v1.5.0"', source)

    def test_range_v2_has_no_external_model_or_ordering_premise(self) -> None:
        assumptions = fr.proof_identity_receipt_assumptions(
            variant=fr.RANGE_VARIANT,
            release_epoch="v1.7.2",
            proof_identity=binding(RANGE_V2),
        )
        joined = "\n".join(assumptions)
        self.assertNotIn("ModelTCB hdr nodes =", joined)
        self.assertNotIn("lo <= hi", joined)
        self.assertIn("derived inside the proved checker", joined)

    def test_int_v2_has_no_external_tree_tcb_premise(self) -> None:
        assumptions = fr.proof_identity_receipt_assumptions(
            variant=fr.INT_CERT_VARIANT,
            release_epoch="v1.7.2",
            proof_identity=binding(INT_V2),
        )
        self.assertNotIn("TreeTCB tree =", "\n".join(assumptions))

    def test_range_v1_replays_but_int_v1_is_revoked(self) -> None:
        self.assertEqual(
            fr.proof_identity_receipt_assumptions(
                variant=fr.RANGE_VARIANT,
                release_epoch="v1.5.0",
                proof_identity=binding(RANGE_V1),
            ),
            fr.MODEL_ASSUMPTIONS,
        )
        with self.assertRaisesRegex(ValueError, "proof compatibility"):
            fr.proof_identity_receipt_assumptions(
                variant=fr.INT_CERT_VARIANT,
                release_epoch="v1.7.0",
                proof_identity=binding(INT_V1),
            )

    def test_cross_epoch_schema_and_file_substitution_refuse(self) -> None:
        cases = [
            (fr.RANGE_VARIANT, "v1.7.2", binding(RANGE_V1)),
            (fr.RANGE_VARIANT, "v1.5.0", binding(RANGE_V2)),
            (fr.INT_CERT_VARIANT, "v1.7.2", binding(INT_V1)),
            (fr.INT_CERT_VARIANT, "v1.7.0", binding(INT_V1)),
            (fr.INT_CERT_VARIANT, "v1.7.0", binding(INT_V2)),
        ]
        for variant, epoch, proof in cases:
            with self.subTest(variant=variant, epoch=epoch, schema=proof["schema"]):
                with self.assertRaisesRegex(ValueError, "proof compatibility"):
                    fr.proof_identity_receipt_assumptions(
                        variant=variant,
                        release_epoch=epoch,
                        proof_identity=proof,
                    )
        forged = binding(RANGE_V2)
        forged["file_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "proof compatibility"):
            fr.proof_identity_receipt_assumptions(
                variant=fr.RANGE_VARIANT,
                release_epoch="v1.7.2",
                proof_identity=forged,
            )

    def test_rational_archival_epoch_is_explicit_and_file_pinned(self) -> None:
        archival = binding(RANGE_V1)
        self.assertEqual(
            fr.proof_identity_receipt_assumptions(
                variant=fr.LN_RAT_VARIANT,
                release_epoch="v1.5.0",
                proof_identity=archival,
            ),
            fr.LN_RAT_ASSUMPTIONS,
        )

        forged = dict(archival)
        forged["file_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "proof compatibility"):
            fr.proof_identity_receipt_assumptions(
                variant=fr.LN_RAT_VARIANT,
                release_epoch="v1.5.0",
                proof_identity=forged,
            )

        with self.assertRaisesRegex(ValueError, "proof compatibility"):
            fr.proof_identity_receipt_assumptions(
                variant=fr.LN_RAT_VARIANT,
                release_epoch="v999.0.0",
                proof_identity=archival,
            )

        policy = fr.proof_compatibility_policy_document()
        self.assertEqual(
            policy["lanes"]["rational_variants"]["archival_v1"][
                "allowed_release_epochs"
            ],
            ["v1.5.0"],
        )

    def test_archival_replay_pins_the_required_v170_checker_bytes(self) -> None:
        policy = fr.proof_compatibility_policy_document()
        range_archive = policy["lanes"]["range"]["archival_v1"]
        rational_archive = policy["lanes"]["rational_variants"]["archival_v1"]
        int_archive = policy["lanes"]["int_cert"]["archival_v1"]
        self.assertEqual(range_archive["allowed_release_epochs"], ["v1.5.0"])
        self.assertEqual(
            range_archive["checker_sha256"],
            "05c3518b836f239712f897c483a2ddadad9f544e0887b1b7bb1424a27289de8a",
        )
        self.assertEqual(rational_archive["checker_sha256"], range_archive["checker_sha256"])
        self.assertEqual(int_archive["allowed_release_epochs"], [])
        self.assertEqual(int_archive["mode"], "revoked-refuse")
        self.assertIn("does not bind the raw request", int_archive["reason"])
        self.assertEqual(
            int_archive["checker_sha256"],
            "c858e3bfc0ff2809a808170caabbf090077cb54996e76f065dbcd26ffb067d49",
        )

    def test_receipt_emitter_rejects_checker_proof_identity_mismatch(self) -> None:
        with self.assertRaisesRegex(ValueError, "checker/proof identity"):
            fr.build_variant_formal_receipt(
                variant=fr.SQRT_RAT_VARIANT,
                release_epoch="v1.7.2",
                request={
                    "command": "range-bound-cert",
                    "expression": "sqrt(x)",
                    "input_lo": "0",
                    "input_hi": "1",
                },
                enclosure=("0", "1"),
                cert_bytes=b"",
                producer_sha256="1" * 64,
                checker_sha256="0" * 64,
                canonical_lo="0",
                canonical_hi="1",
                request_commitment_b64="YQ==",
                coverage_inventory_sha256="2" * 64,
                proof_identity=binding(RANGE_V2),
            )

    def test_range_emitter_rejects_reversed_interval(self) -> None:
        proof = binding(RANGE_V2)
        kwargs = {
            "release_epoch": "v1.7.2",
            "request": {
                "command": "range-bound-cert",
                "expression": "x",
                "input_lo": "2",
                "input_hi": "1",
            },
            "enclosure": ("1", "2"),
            "cert_bytes": (
                b"jackal-eval-cert v2\nmodel jackal-iv-model-v1\n"
                b"expr x\ninput 2 1\noutput 1 2\n"
            ),
            "evaluator_sha256": "1" * 64,
            "checker_sha256": proof["checker_sha256"],
            "source_anb_sha256": "2" * 64,
            "plugin_sha256": None,
            "admitted_operators": ["var"],
            "coverage_row_ids": ["var"],
            "unsupported_refused": [],
            "canonical_lo": "2",
            "canonical_hi": "1",
            "request_commitment_b64": "YQ==",
            "coverage_inventory_sha256": "3" * 64,
            "proof_identity": proof,
        }
        with self.assertRaisesRegex(ValueError, "interval order"):
            fr.build_formal_receipt(**kwargs)

    def test_verifier_rejects_coherent_v2_to_v1_epoch_relabel_before_execution(self) -> None:
        proof = binding(RANGE_V2)
        receipt = fr.build_formal_receipt(
            release_epoch="v1.7.2",
            request={
                "command": "range-bound-cert",
                "expression": "x",
                "input_lo": "0",
                "input_hi": "1",
            },
            enclosure=("0", "1"),
            cert_bytes=(
                b"jackal-eval-cert v2\nmodel jackal-iv-model-v1\n"
                b"expr x\ninput 0 1\noutput 0 1\n"
            ),
            evaluator_sha256="1" * 64,
            checker_sha256=proof["checker_sha256"],
            source_anb_sha256="2" * 64,
            plugin_sha256=None,
            admitted_operators=["var"],
            coverage_row_ids=["var"],
            unsupported_refused=[],
            canonical_lo="0",
            canonical_hi="1",
            request_commitment_b64=fr.request_commitment_b64(
                "range-bound-cert", "x", "0", "1"
            ),
            coverage_inventory_sha256="3" * 64,
            proof_identity=proof,
            emitted_at_unix=0,
        )
        relabelled = copy.deepcopy(receipt)
        relabelled["release_epoch"] = "v1.5.0"
        relabelled["receipt_digest_sha256"] = fr.recompute_receipt_digest(relabelled)
        with self.assertRaises(rv.ReceiptRefusal) as caught:
            rv.verify_receipt(
                receipt=relabelled,
                checker="/bin/false",
                expected_evaluator="1" * 64,
                expected_checker=proof["checker_sha256"],
                expected_source="2" * 64,
                inventory_path=ROOT / "release/coverage/formal_coverage_inventory.json",
                expected_inventory_sha256="3" * 64,
                proof_identity_path=RANGE_V2,
                expected_proof_identity_file=file_sha(RANGE_V2),
                expected_proof_identity_digest=proof["identity_digest_sha256"],
                expected_release_epoch="v1.5.0",
                expected_request={
                    "command": "range-bound-cert",
                    "expression": "x",
                    "input_lo": "0",
                    "input_hi": "1",
                },
            )
        self.assertEqual(caught.exception.cls, "proof-compatibility")


if __name__ == "__main__":
    unittest.main(verbosity=2)
