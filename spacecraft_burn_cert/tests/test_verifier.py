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

    def test_independent_replay_accepts_the_baseline(self):
        verifier = load_verifier(self)
        result = verifier.verify_receipt(BASELINE, CERTIFIER)
        self.assertEqual(result["status"], "ACCEPT", result)
        self.assertEqual(result["reasons"], [])
        self.assertIn("domain_lower_bounds", result["replay"])

    def test_tampered_reported_lower_bound_is_rejected(self):
        verifier = load_verifier(self)
        payload = json.loads(BASELINE.read_text())
        payload["decisive_margin"]["reported_lower_exact"] = "1000"
        with tempfile.TemporaryDirectory() as directory:
            candidate = Path(directory) / "tampered.json"
            candidate.write_text(json.dumps(payload), encoding="utf-8")
            result = verifier.verify_receipt(candidate, CERTIFIER)
        self.assertEqual(result["status"], "REFUSED")
        self.assertIn("reported-lower-bound-mismatch", result["reasons"])


if __name__ == "__main__":
    unittest.main()
