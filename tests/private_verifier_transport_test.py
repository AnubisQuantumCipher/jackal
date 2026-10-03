#!/usr/bin/env python3
"""Compatibility controls for private argument-file transport.

These tests exercise the newly built checker drivers, not sealed release pins.
"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / "proofs/lean/.lake/build/bin"


class PrivateTransportTests(unittest.TestCase):
    def call(self, executable, arguments, private):
        with tempfile.TemporaryDirectory() as directory:
            if private:
                path = Path(directory) / "request.json"
                path.write_text(json.dumps(arguments), encoding="utf-8")
                path.chmod(0o600)
                arguments = ["--private-argv-json", str(path)]
            return subprocess.run([*executable, *arguments], capture_output=True, timeout=300)

    def test_python_verifier_interfaces_preserve_help_and_argument_errors(self):
        for script in ("receipt_verify.py", "claim_bundle_verify.py"):
            executable = [sys.executable, "-I", "-S", "-B", str(ROOT / "tools" / script)]
            for arguments in (["--help"], ["--unknown-option"]):
                direct = self.call(executable, arguments, False)
                private = self.call(executable, arguments, True)
                self.assertEqual((private.returncode, private.stdout, private.stderr),
                                 (direct.returncode, direct.stdout, direct.stderr))

    def test_integral_request_binding_preserved(self):
        produced = subprocess.run([sys.executable, "-I", "-S", "-B",
            str(ROOT / "tools/int_cert_producer.py"), "emit", "--expression", "0",
            "--lower", "0", "--upper", "1", "--tolerance", "2"],
            capture_output=True, check=True, timeout=300)
        with tempfile.TemporaryDirectory() as directory:
            artifact = Path(directory) / "cert.jic"
            artifact.write_bytes(produced.stdout)
            executable = [str(BIN / "jackal_int_cert_check")]
            for expression in ("0", "x"):
                arguments = [str(artifact), expression, "0", "1", "2"]
                direct = self.call(executable, arguments, False)
                private = self.call(executable, arguments, True)
                self.assertEqual((private.returncode, private.stdout, private.stderr),
                                 (direct.returncode, direct.stdout, direct.stderr))
                if expression == "0": self.assertEqual(private.returncode, 0)
                else: self.assertNotEqual(private.returncode, 0)

    def test_checker_private_schema_refuses_non_string_arguments(self):
        for name in ("jackal_cert_check", "jackal_int_cert_check"):
            for arguments in ({"expression": "x"}, [None], [True]):
                result = self.call([str(BIN / name)], arguments, True)
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn(b"ACCEPT", result.stdout)
                self.assertIn(b"private-argv-schema", result.stderr)


if __name__ == "__main__": unittest.main(verbosity=2)
