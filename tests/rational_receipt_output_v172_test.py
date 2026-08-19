#!/usr/bin/env python3
"""Write-once output contract for every v1.7.2 rational wrapper."""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CASES = {
    "jackal-sqrt-rat-release": ("sqrt(x)", "1", "4"),
    "jackal-exp-rat-release": ("exp(x)", "0", "1"),
    "jackal-ln-rat-release": ("ln(x)", "1", "2"),
    "jackal-sin-rat-release": ("sin(x)", "0", "1"),
    "jackal-cos-rat-release": ("cos(x)", "0", "1"),
    "jackal-atan-rat-release": ("atan(x)", "0", "1"),
    "jackal-tanh-rat-release": ("1-2/(exp(2*x)+1)", "0", "1"),
}


class RationalReceiptOutputV172Tests(unittest.TestCase):
    def invoke(self, wrapper: str, output: Path) -> subprocess.CompletedProcess:
        return subprocess.run(
            [str(ROOT / wrapper), *CASES[wrapper], str(output)],
            cwd=ROOT, text=True, capture_output=True, timeout=600,
        )

    def test_existing_receipt_is_never_overwritten_or_reported_successful(self) -> None:
        for wrapper in CASES:
            with self.subTest(wrapper=wrapper), tempfile.TemporaryDirectory() as td:
                receipt = Path(td) / "receipt.json"
                receipt.write_bytes(b"SENTINEL\n")
                proc = self.invoke(wrapper, receipt)
                self.assertNotEqual(proc.returncode, 0, proc.stdout + proc.stderr)
                self.assertEqual(receipt.read_bytes(), b"SENTINEL\n")
                self.assertNotIn("status=formal-bounded", proc.stdout)

    def test_symlink_receipt_is_never_followed_or_reported_successful(self) -> None:
        for wrapper in CASES:
            with self.subTest(wrapper=wrapper), tempfile.TemporaryDirectory() as td:
                target = Path(td) / "authority.json"
                target.write_bytes(b"AUTHORITY-SENTINEL\n")
                receipt = Path(td) / "receipt.json"
                receipt.symlink_to(target)
                proc = self.invoke(wrapper, receipt)
                self.assertNotEqual(proc.returncode, 0, proc.stdout + proc.stderr)
                self.assertEqual(target.read_bytes(), b"AUTHORITY-SENTINEL\n")
                self.assertTrue(receipt.is_symlink())
                self.assertNotIn("status=formal-bounded", proc.stdout)

    def test_fresh_receipt_is_published_before_success_token(self) -> None:
        for wrapper in CASES:
            with self.subTest(wrapper=wrapper), tempfile.TemporaryDirectory() as td:
                receipt = Path(td) / "receipt.json"
                proc = self.invoke(wrapper, receipt)
                self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
                self.assertTrue(receipt.is_file())
                self.assertGreater(receipt.stat().st_size, 0)
                lines = proc.stdout.splitlines()
                self.assertIn(f"receipt={receipt}", lines)
                self.assertIn("status=formal-bounded", lines)
                self.assertLess(lines.index(f"receipt={receipt}"),
                                lines.index("status=formal-bounded"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
