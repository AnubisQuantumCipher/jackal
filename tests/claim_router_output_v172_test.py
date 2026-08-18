#!/usr/bin/env python3
"""Fail-closed JSON and write-once output contract for jackal-claim."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ROUTER = ROOT / "tools/claim_router.py"
REQUEST = {
    "schema": "jackal-claim-request-v1",
    "emitted_at_unix": "1786752000",
    "steps": [
        {"id": "x", "op": "input", "name": "x", "lo": "1", "hi": "2"}
    ],
    "root": "x",
}


class ClaimRouterOutputV172Tests(unittest.TestCase):
    def invoke(self, request: Path, output: Path) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-I", "-S", "-B", str(ROUTER), "claim",
             "--request", str(request), "--emit-bundle", str(output)],
            cwd=ROOT, text=True, capture_output=True, timeout=120,
        )

    def test_existing_output_is_not_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            request = Path(td) / "request.json"
            request.write_text(json.dumps(REQUEST))
            output = Path(td) / "bundle.json"
            output.write_bytes(b"SENTINEL\n")
            proc = self.invoke(request, output)
            self.assertNotEqual(proc.returncode, 0)
            self.assertIn("reason=output-path", proc.stdout)
            self.assertNotIn("status=ok", proc.stdout)
            self.assertEqual(output.read_bytes(), b"SENTINEL\n")

    def test_symlink_output_is_not_followed(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            request = Path(td) / "request.json"
            request.write_text(json.dumps(REQUEST))
            target = Path(td) / "authority.json"
            target.write_bytes(b"AUTHORITY\n")
            output = Path(td) / "bundle.json"
            output.symlink_to(target)
            proc = self.invoke(request, output)
            self.assertNotEqual(proc.returncode, 0)
            self.assertIn("reason=output-path", proc.stdout)
            self.assertEqual(target.read_bytes(), b"AUTHORITY\n")
            self.assertTrue(output.is_symlink())

    def test_fresh_output_is_atomic_and_duplicate_request_keys_refuse(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            request = Path(td) / "request.json"
            request.write_text(json.dumps(REQUEST))
            output = Path(td) / "bundle.json"
            proc = self.invoke(request, output)
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertIn("status=ok", proc.stdout)
            self.assertEqual(json.loads(output.read_text())["schema"],
                             "jackal-claim-bundle-v1")

            duplicate = Path(td) / "duplicate.json"
            duplicate.write_text(
                '{"schema":"jackal-claim-request-v1",'
                '"schema":"jackal-claim-request-v1","steps":[],"root":"x"}')
            second = Path(td) / "must-not-exist.json"
            refused = self.invoke(duplicate, second)
            self.assertNotEqual(refused.returncode, 0)
            self.assertIn("duplicate request key", refused.stdout)
            self.assertFalse(second.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
