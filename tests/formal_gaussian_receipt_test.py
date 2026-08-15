#!/usr/bin/env python3
"""End-to-end formal receipt tracer for the Gaussian checker lane."""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PRODUCER = ROOT / "tools" / "gaussian_certificate.py"
RELEASE = ROOT / "tools" / "gaussian_release.py"
ISOLATED = ROOT / "tools" / "isolated_entry.py"
VERIFIER = ROOT / "jackal-receipt-verify"
CHECKER = ROOT / "proofs" / "lean" / ".lake" / "build" / "bin" / "jackal_gaussian_check"
INVENTORY = ROOT / "release" / "coverage" / "formal_coverage_inventory.json"
PROOF_IDENTITY = ROOT / "release" / "evidence" / "gaussian_proof_identity.json"
EXPR = "exp(-10000000000*(x-0.5000123456789)^2)"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class GaussianReceiptTest(unittest.TestCase):
    def test_root_wrapper_uses_pinned_manifest_and_verifies(self) -> None:
        with tempfile.TemporaryDirectory(prefix="jackal-gaussian-wrapper-") as td:
            receipt_path = Path(td) / "receipt.json"
            released = subprocess.run([
                str(ROOT / "jackal-gaussian-release"), EXPR, "0", "1",
                "1/1000000000000", str(receipt_path),
            ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
               check=False, timeout=120)
            self.assertEqual(released.returncode, 0, released.stderr)
            receipt = json.loads(receipt_path.read_text())
            self.assertEqual(receipt["theorem"]["id"],
                             "gaussian_integral_check_sound")
            self.assertEqual(receipt["identities"]["checker_sha256"],
                             sha256(CHECKER))

    def test_receipt_rehydrates_and_reruns_pinned_checker(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            receipt = Path(directory) / "receipt.json"
            released = subprocess.run(
                [
                    sys.executable,
                    "-I", "-S", "-B", str(ISOLATED), "gaussian",
                    "--expression",
                    EXPR,
                    "--lower",
                    "0.0",
                    "--upper",
                    "1.00",
                    "--tolerance",
                    "0.000000000001",
                    "--producer",
                    str(PRODUCER),
                    "--checker",
                    str(CHECKER),
                    "--expected-producer",
                    sha256(PRODUCER),
                    "--expected-checker",
                    sha256(CHECKER),
                    "--receipt",
                    str(receipt),
                    "--inventory",
                    str(INVENTORY),
                    "--expected-inventory",
                    sha256(INVENTORY),
                    "--proof-identity",
                    str(PROOF_IDENTITY),
                    "--expected-proof-identity-file",
                    sha256(PROOF_IDENTITY),
                    "--expected-proof-identity-digest",
                    json.loads(PROOF_IDENTITY.read_text())["identity_digest_sha256"],
                ],
                text=True,
                capture_output=True,
                timeout=60,
            )
            self.assertEqual(released.returncode, 0, released.stderr)
            self.assertIn("status=formal-bounded", released.stdout)
            document = json.loads(receipt.read_text())
            self.assertEqual(document["schema"], "jackal-formal-receipt-v1")
            self.assertEqual(document["theorem"]["id"], "gaussian_integral_check_sound")
            self.assertEqual(document["certificate"]["schema"], "jackal-gaussian-integral-cert v1")
            self.assertEqual(document["request"]["input_lo"], "0.0")
            self.assertEqual(document["request"]["input_hi"], "1.00")
            self.assertEqual(document["request"]["tolerance"], "0.000000000001")
            self.assertEqual(document["request"]["canonical_lo"], "0")
            self.assertEqual(document["request"]["canonical_hi"], "1")
            self.assertEqual(document["request"]["canonical_tolerance"],
                             "1/1000000000000")

            verified = subprocess.run(
                [
                    str(VERIFIER),
                    "--receipt",
                    str(receipt),
                    "--checker",
                    str(CHECKER),
                    "--expected-evaluator",
                    sha256(PRODUCER),
                    "--expected-checker",
                    sha256(CHECKER),
                    "--expected-release-epoch",
                    "v1.3.0",
                    "--expected-command",
                    "integrate",
                    "--expected-expression",
                    EXPR,
                    "--expected-input-lo",
                    "0.0",
                    "--expected-input-hi",
                    "1.00",
                    "--expected-tolerance",
                    "0.000000000001",
                    "--inventory",
                    str(INVENTORY),
                    "--expected-inventory",
                    sha256(INVENTORY),
                    "--proof-identity",
                    str(PROOF_IDENTITY),
                    "--expected-proof-identity-file",
                    sha256(PROOF_IDENTITY),
                    "--expected-proof-identity-digest",
                    json.loads(PROOF_IDENTITY.read_text())["identity_digest_sha256"],
                ],
                text=True,
                capture_output=True,
                timeout=60,
            )
            self.assertEqual(verified.returncode, 0, verified.stderr)
            self.assertIn("receipt_valid=true", verified.stdout)
            self.assertIn("checker_verdict=ACCEPT", verified.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
