#!/usr/bin/env python3
"""Tracer test for the untrusted Gaussian certificate producer.

The producer is deliberately not a root of trust.  This test only fixes the
canonical certificate framing that the independent Lean checker will consume.
"""
from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PRODUCER = ROOT / "tools" / "gaussian_certificate.py"
EXPR = "exp(-10000000000*(x-0.5000123456789)^2)"


class GaussianCertificateEmitterTest(unittest.TestCase):
    def test_extreme_request_emits_canonical_v1_certificate(self) -> None:
        proc = subprocess.run(
            [
                sys.executable,
                str(PRODUCER),
                "emit",
                "--expression",
                EXPR,
                "--lower",
                "0",
                "--upper",
                "1",
                "--tolerance",
                "1/1000000000000",
            ],
            text=True,
            capture_output=True,
            timeout=30,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        lines = proc.stdout.splitlines()
        self.assertEqual(lines[0], "jackal-gaussian-integral-cert v1")
        self.assertEqual(lines[1], "operation integrate")
        self.assertEqual(lines[2], "assurance formal-bounded")
        self.assertEqual(lines[3], "family gaussian-exp-square-v1")
        self.assertIn(f"expression {EXPR}", lines)
        self.assertIn("scale 100000", lines)
        self.assertIn("method gaussian-total-minus-tails-v1", lines)
        self.assertIn("core 6", lines)
        self.assertIn("degree 96", lines)
        self.assertIn("sqrt-pi-lower 177245385090551/100000000000000", lines)
        self.assertIn("sqrt-pi-upper 22155673136319/12500000000000", lines)
        self.assertNotIn("cells 256", lines)
        output = next(line for line in lines if line.startswith("output ")).split()
        self.assertEqual(len(output), 3)
        self.assertEqual(lines[-1], "end")
        self.assertTrue(proc.stdout.endswith("\n"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
