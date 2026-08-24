from __future__ import annotations

import importlib.util
import hashlib
import json
import tempfile
import unittest
from unittest import mock
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
VERIFIER = ROOT / "verify_receipt.py"
CERTIFIER = ROOT / "certify.py"
BASELINE = ROOT / "evidence" / "legacy-v1" / "baseline_receipt.json"
PROOF_IDENTITY = ROOT.parent / "release" / "evidence" / "spacecraft_burn_proof_identity_v1.json"
CHECKER = ROOT.parent / "proofs" / "lean" / ".lake" / "build" / "bin" / "jackal_spacecraft_burn_check"
REQUEST_DIGEST = "03bcad618ad60114007c74a384eb8c9432e3755b817e74bd5bdc9bd1ba6df3e7"
MODEL_ID = "jackal-spacecraft-finite-burn-ode-v2"
EPOCH = "v1.7.4"
NONCE = "verifier-mutation-test"
QUALIFIER = (
    "under the stated finite-burn ODE model, supplied input bounds, "
    "and machine-checked interval-certificate assumptions"
)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_verifier(testcase: unittest.TestCase):
    if not VERIFIER.is_file():
        testcase.fail("verify_receipt.py is missing")
    spec = importlib.util.spec_from_file_location("spacecraft_verifier", VERIFIER)
    if spec is None or spec.loader is None:
        testcase.fail("verify_receipt.py cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class IndependentVerifierTests(unittest.TestCase):
    def test_checker_execution_uses_private_byte_snapshots(self):
        verifier = load_verifier(self)
        checker_bytes = b"#!/bin/sh\nexit 0\n"
        witness_bytes = b"bound witness\n"
        observed: dict[str, object] = {}

        def fake_run(command, **kwargs):
            checker_snapshot, witness_snapshot = map(Path, command[:2])
            observed["checker"] = checker_snapshot.read_bytes()
            observed["witness"] = witness_snapshot.read_bytes()
            observed["private"] = checker_snapshot.parent == witness_snapshot.parent
            return subprocess.CompletedProcess(command, 0, "ACCEPT\n", "")

        with mock.patch.object(verifier.subprocess, "run", side_effect=fake_run):
            completed = verifier.run_checker_snapshot(
                checker_bytes, witness_bytes, "request", "model", "epoch", 10
            )
        self.assertEqual(completed.stdout, "ACCEPT\n")
        self.assertEqual(observed, {
            "checker": checker_bytes,
            "witness": witness_bytes,
            "private": True,
        })

    def test_identity_digest_uses_the_already_parsed_bytes(self):
        verifier = load_verifier(self)
        identity = json.loads(PROOF_IDENTITY.read_text(encoding="utf-8"))
        reasons: list[str] = []
        with mock.patch.object(
            verifier, "sha256_file", side_effect=AssertionError("unexpected reread")
        ):
            verifier.verify_identity_file(
                PROOF_IDENTITY,
                sha(PROOF_IDENTITY),
                identity["identity_digest_sha256"],
                identity["checker"]["sha256"],
                REQUEST_DIGEST,
                MODEL_ID,
                EPOCH,
                reasons,
            )
        self.assertEqual(reasons, [])

    def test_source_literals_parse_caller_supplied_bytes(self):
        verifier = load_verifier(self)
        raw = b'THRUST_KM_SCALE_TEXT = "0.001"\nINTEGRATE_MASS = True\n'
        self.assertEqual(
            verifier.source_literals(raw, Path("producer.py")),
            {"THRUST_KM_SCALE_TEXT": "0.001", "INTEGRATE_MASS": True},
        )

    def test_exact_symbolic_orbital_identities_hold(self):
        verifier = load_verifier(self)
        results = verifier.verify_symbolic_identities()
        self.assertTrue(results)
        self.assertTrue(all(results.values()))
        self.assertIn("vis_viva_cleared_denominator_expansion", results)
        self.assertNotIn("energy_definition_substitution", results)

    def test_legacy_v1_receipt_is_never_promoted(self):
        verifier = load_verifier(self)
        result = verifier.verify_receipt(BASELINE, CERTIFIER)
        self.assertEqual(result["status"], "REFUSED", result)
        self.assertEqual(result["reasons"], ["legacy-unproved-verdict-schema"])

    def test_v2_candidate_without_formal_binding_is_refused(self):
        verifier = load_verifier(self)
        payload = json.loads(BASELINE.read_text())
        payload["schema"] = "spacecraft-finite-burn-formal-receipt-v2"
        payload["verdict"] = "CERTIFIED SAFE"
        payload["verdict_qualifier"] = (
            "under the stated finite-burn ODE model, supplied input bounds, "
            "and machine-checked interval-certificate assumptions"
        )
        payload["producer_assurance"] = "candidate-only"
        payload["formal_checker_status"] = "NOT_EXECUTED"
        with tempfile.TemporaryDirectory() as directory:
            candidate = Path(directory) / "candidate.json"
            candidate.write_text(json.dumps(payload), encoding="utf-8")
            result = verifier.verify_receipt(candidate, CERTIFIER)
        self.assertEqual(result["status"], "REFUSED")
        self.assertEqual(result["reasons"], ["formal-checker-not-bound"])

    def test_malformed_replay_sections_refuse_without_traceback(self):
        verifier = load_verifier(self)
        reasons = {
            "method": "invalid-method-section",
            "cutoff_state_hull": "invalid-cutoff-state-hull",
            "orbital_hulls": "invalid-orbital-hulls",
        }
        with tempfile.TemporaryDirectory() as directory:
            for field, reason in reasons.items():
                with self.subTest(field=field):
                    payload = {
                        "schema": "spacecraft-finite-burn-formal-receipt-v2",
                        "formal_checker_status": "ACCEPT",
                        "method": {}, "cutoff_state_hull": {}, "orbital_hulls": {},
                    }
                    payload[field] = []
                    path = Path(directory) / f"{field}.json"
                    path.write_text(json.dumps(payload))
                    result = verifier.verify_receipt(path, CERTIFIER)
                    self.assertEqual(result, {"status": "REFUSED", "reasons": [reason]})

    def test_caller_supplied_symlink_is_refused_before_resolution(self):
        verifier = load_verifier(self)
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "target.cert"
            target.write_text("witness\n")
            link = Path(directory) / "link.cert"
            link.symlink_to(target)
            result = verifier.verify_receipt(BASELINE, CERTIFIER, witness_path=link)
            self.assertEqual(result, {"status": "REFUSED", "reasons": ["witness-unreadable"]})

    @unittest.skipUnless(CHECKER.is_file(), "Lean checker binary is not built")
    def test_formal_binding_mutations_refuse_with_stable_reasons(self):
        verifier = load_verifier(self)
        self.assertTrue(PROOF_IDENTITY.is_file())
        self.assertTrue(CHECKER.is_file())
        identity = json.loads(PROOF_IDENTITY.read_text(encoding="utf-8"))
        proof_file_digest = sha(PROOF_IDENTITY)
        proof_internal_digest = identity["identity_digest_sha256"]
        mutations = {
            "checker_sha256": ("0" * 64, "checker-hash-mismatch"),
            "proof_identity_file_sha256": ("0" * 64, "proof-identity-file-hash-mismatch"),
            "proof_identity_digest_sha256": ("0" * 64, "proof-identity-internal-digest-mismatch"),
            "witness_sha256": ("0" * 64, "witness-hash-mismatch"),
            "request_digest": ("0" * 64, "request-digest-mismatch"),
            "model_id": ("wrong-model", "model-id-mismatch"),
            "epoch": ("wrong-epoch", "release-epoch-mismatch"),
            "nonce": ("wrong-nonce", "nonce-mismatch"),
            "theorem": ("wrong_theorem", "theorem-name-mismatch"),
            "result_line": ("bad\nline", "checker-result-line-invalid"),
        }
        with tempfile.TemporaryDirectory(prefix="spacecraft-binding-") as directory:
            temp = Path(directory)
            witness = temp / "witness.cert"
            witness.write_text("fixture-witness\n", encoding="ascii")
            base_binding = {
                "checker_sha256": sha(CHECKER),
                "proof_identity_file_sha256": proof_file_digest,
                "proof_identity_digest_sha256": proof_internal_digest,
                "witness_sha256": sha(witness),
                "request_digest": REQUEST_DIGEST,
                "model_id": MODEL_ID,
                "epoch": EPOCH,
                "nonce": NONCE,
                "theorem": "spacecraft_burn_certified_safe",
                "result_line": "not-invoked-because-each-case-refuses-before-execution",
            }
            for field, (mutated, reason) in mutations.items():
                with self.subTest(field=field):
                    candidate = {
                        "verdict_qualifier": QUALIFIER,
                        "formal_checker": {**base_binding, field: mutated},
                    }
                    receipt = temp / f"{field}.json"
                    receipt.write_text(json.dumps(candidate, sort_keys=True), encoding="utf-8")
                    reasons, _digests = verifier.verify_formal_binding(
                        candidate,
                        receipt,
                        witness_path=witness,
                        checker_path=CHECKER,
                        proof_identity_path=PROOF_IDENTITY,
                        expected_receipt_sha256=sha(receipt),
                        expected_proof_file_sha256=proof_file_digest,
                        expected_proof_identity_sha256=proof_internal_digest,
                        expected_request_digest=REQUEST_DIGEST,
                        expected_model_id=MODEL_ID,
                        expected_epoch=EPOCH,
                        nonce=NONCE,
                    )
                    self.assertIn(reason, reasons)

            candidate = {"verdict_qualifier": QUALIFIER, "formal_checker": base_binding}
            receipt = temp / "receipt-digest.json"
            receipt.write_text(json.dumps(candidate, sort_keys=True), encoding="utf-8")
            reasons, _digests = verifier.verify_formal_binding(
                candidate,
                receipt,
                witness_path=witness,
                checker_path=CHECKER,
                proof_identity_path=PROOF_IDENTITY,
                expected_receipt_sha256="0" * 64,
                expected_proof_file_sha256=proof_file_digest,
                expected_proof_identity_sha256=proof_internal_digest,
                expected_request_digest=REQUEST_DIGEST,
                expected_model_id=MODEL_ID,
                expected_epoch=EPOCH,
                nonce=NONCE,
            )
            self.assertIn("receipt-hash-mismatch", reasons)

            mutated_identity = json.loads(PROOF_IDENTITY.read_text(encoding="utf-8"))
            mutated_identity["fragment"]["soundness_theorem"] = "wrong_theorem"
            body = {key: value for key, value in mutated_identity.items()
                    if key != "identity_digest_sha256"}
            mutated_identity["identity_digest_sha256"] = hashlib.sha256(
                verifier.canonical_json_bytes(body)
            ).hexdigest()
            identity_path = temp / "mutated-identity.json"
            identity_path.write_text(
                json.dumps(mutated_identity, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            candidate = {
                "verdict_qualifier": QUALIFIER,
                "formal_checker": {
                    **base_binding,
                    "proof_identity_file_sha256": sha(identity_path),
                    "proof_identity_digest_sha256": mutated_identity["identity_digest_sha256"],
                },
            }
            receipt = temp / "identity-theorem.json"
            receipt.write_text(json.dumps(candidate, sort_keys=True), encoding="utf-8")
            reasons, _digests = verifier.verify_formal_binding(
                candidate,
                receipt,
                witness_path=witness,
                checker_path=CHECKER,
                proof_identity_path=identity_path,
                expected_receipt_sha256=sha(receipt),
                expected_proof_file_sha256=sha(identity_path),
                expected_proof_identity_sha256=mutated_identity["identity_digest_sha256"],
                expected_request_digest=REQUEST_DIGEST,
                expected_model_id=MODEL_ID,
                expected_epoch=EPOCH,
                nonce=NONCE,
            )
            self.assertIn("proof-identity-fragment-mismatch", reasons)


if __name__ == "__main__":
    unittest.main()
