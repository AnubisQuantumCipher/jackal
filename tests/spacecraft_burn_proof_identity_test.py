from __future__ import annotations

import json
import platform
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "release" / "tools" / "spacecraft_burn_proof_identity.py"
IDENTITY = ROOT / "release" / "evidence" / "spacecraft_burn_proof_identity_v1.json"


class SpacecraftProofIdentityTests(unittest.TestCase):
    def run_gate(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-B", str(SCRIPT), *args],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

    def test_committed_source_and_proof_identity_reproduce_cross_platform(self) -> None:
        result = self.run_gate("check", "--proof-only")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("PASS spacecraft-burn proof identity", result.stdout)

    @unittest.skipUnless(
        sys.platform == "darwin" and platform.machine() == "arm64",
        "committed executable identity is macOS/arm64-specific",
    )
    def test_committed_checker_binary_identity_reproduces_on_owning_platform(self) -> None:
        result = self.run_gate("check")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("checker build binding", result.stdout)

    def test_mutated_checker_identity_refuses(self) -> None:
        document = json.loads(IDENTITY.read_text(encoding="utf-8"))
        document["checker"]["sha256"] = "0" * 64
        with tempfile.TemporaryDirectory(prefix="spacecraft-proof-id-") as directory:
            candidate = Path(directory) / "identity.json"
            candidate.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")
            result = self.run_gate("check", "--identity", str(candidate))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("identity self-digest mismatch", result.stderr)

    def test_wrapper_rejects_lane_override(self) -> None:
        result = self.run_gate("check", "--lane=gaussian")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("fixed to spacecraft-burn", result.stderr)


if __name__ == "__main__":
    unittest.main()
