from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VERIFIER = ROOT / "verify_receipt.py"
CERTIFIER = ROOT / "certify.py"
BASELINE = ROOT / "evidence" / "legacy-v1" / "baseline_receipt.json"


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
    def test_exact_symbolic_orbital_identities_hold(self):
        verifier = load_verifier(self)
        results = verifier.verify_symbolic_identities()
        self.assertTrue(results)
        self.assertTrue(all(results.values()))

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


if __name__ == "__main__":
    unittest.main()
