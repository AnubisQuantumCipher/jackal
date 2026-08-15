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
VERIFIER = ROOT / "tools" / "receipt_verify.py"
CHECKER = ROOT / "proofs" / "lean" / ".lake" / "build" / "bin" / "jackal_gaussian_check"
INVENTORY = ROOT / "release" / "coverage" / "formal_coverage_inventory.json"
EXPR = "exp(-10000000000*(x-0.5000123456789)^2)"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class GaussianReceiptTest(unittest.TestCase):
    def test_receipt_rehydrates_and_reruns_pinned_checker(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            receipt = Path(directory) / "receipt.json"
            released = subprocess.run(
                [
                    sys.executable,
                    str(RELEASE),
                    "--expression",
                    EXPR,
                    "--lower",
                    "0",
                    "--upper",
                    "1",
                    "--tolerance",
                    "1/1000000000000",
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

            verified = subprocess.run(
                [
                    sys.executable,
                    str(VERIFIER),
                    "--receipt",
                    str(receipt),
                    "--checker",
                    str(CHECKER),
                    "--expected-evaluator",
                    sha256(PRODUCER),
                    "--expected-checker",
                    sha256(CHECKER),
                    "--inventory",
                    str(INVENTORY),
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
