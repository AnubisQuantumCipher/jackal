#!/usr/bin/env python3
"""Tracer test for the independent Gaussian proof checker."""
from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PRODUCER = ROOT / "tools" / "gaussian_certificate.py"
CHECKER = ROOT / "proofs" / "lean" / ".lake" / "build" / "bin" / "jackal_gaussian_check"
EXPR = "exp(-10000000000*(x-0.5000123456789)^2)"


class GaussianCheckerTest(unittest.TestCase):
    def test_extreme_certificate_is_checker_accepted(self) -> None:
        produced = subprocess.run(
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
            check=True,
        )
        with tempfile.NamedTemporaryFile("w", suffix=".gcert", delete=False) as handle:
            handle.write(produced.stdout)
            cert_path = Path(handle.name)
        try:
            checked = subprocess.run(
                [str(CHECKER), str(cert_path)],
                text=True,
                capture_output=True,
                timeout=120,
            )
        finally:
            cert_path.unlink(missing_ok=True)
        self.assertEqual(checked.returncode, 0, checked.stderr)
        self.assertIn("ACCEPT theorem=gaussian_integral_check_sound", checked.stdout)
        self.assertIn("family=gaussian-exp-square-v1", checked.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
