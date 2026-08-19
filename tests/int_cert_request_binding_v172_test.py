#!/usr/bin/env python3
"""Current int-cert checker must bind the caller's raw request in Lean."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CHECKER = ROOT / "proofs/lean/.lake/build/bin/jackal_int_cert_check"
PRODUCER = ROOT / "tools/int_cert_producer.py"

sys.path.insert(0, str(ROOT / "tools"))
from formal_receipt import int_cert_request_commitment_b64  # noqa: E402


def produce(expression: str) -> bytes:
    process = subprocess.run(
        [
            sys.executable,
            "-I",
            "-S",
            "-B",
            str(PRODUCER),
            "emit",
            "--expression",
            expression,
            "--lower",
            "0",
            "--upper",
            "1",
            "--tolerance",
            "2",
        ],
        check=False,
        capture_output=True,
        timeout=300,
    )
    if process.returncode != 0:
        raise RuntimeError(process.stderr.decode("utf-8", errors="replace"))
    return process.stdout


def run_checker(artifact: bytes, *request: str) -> subprocess.CompletedProcess[bytes]:
    with tempfile.NamedTemporaryFile(suffix=".jic") as handle:
        handle.write(artifact)
        handle.flush()
        return subprocess.run(
            [str(CHECKER), handle.name, *request],
            check=False,
            capture_output=True,
            timeout=300,
        )


class IntCertRequestBindingV172Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not CHECKER.is_file():
            raise unittest.SkipTest("current int-cert checker is not built")
        cls.zero_artifact = produce("0")
        source_zero = int_cert_request_commitment_b64(
            "integrate-bound-cert", "0", "0", "1", "2"
        ).encode("ascii")
        source_x = int_cert_request_commitment_b64(
            "integrate-bound-cert", "x", "0", "1", "2"
        ).encode("ascii")
        needle = b"source " + source_zero
        replacement = b"source " + source_x
        if cls.zero_artifact.count(needle) != 1:
            raise RuntimeError("zero artifact source commitment is not unique")
        cls.relabelled_artifact = cls.zero_artifact.replace(needle, replacement, 1)

    def test_current_checker_accepts_exact_raw_request(self) -> None:
        checked = run_checker(self.zero_artifact, "0", "0", "1", "2")
        self.assertEqual(checked.returncode, 0, checked.stderr)
        self.assertTrue(
            checked.stdout.startswith(
                b"ACCEPT status=bounded theorem=int_cert_sound "
            ),
            checked.stdout,
        )

    def test_proof_of_zero_relabelled_as_x_refuses(self) -> None:
        checked = run_checker(self.relabelled_artifact, "x", "0", "1", "2")
        self.assertNotEqual(checked.returncode, 0, checked.stdout)
        self.assertIn(b"REFUSE reason=request-mismatch:raw-expression", checked.stderr)

    def test_artifact_only_legacy_invocation_cannot_accept(self) -> None:
        checked = run_checker(self.relabelled_artifact)
        self.assertNotEqual(checked.returncode, 0, checked.stdout)
        self.assertNotIn(b"ACCEPT", checked.stdout)


if __name__ == "__main__":
    unittest.main()
