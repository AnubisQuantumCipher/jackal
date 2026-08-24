from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "spacecraft-burn-proof-gate.yml"
GAUSSIAN = ROOT / ".github" / "workflows" / "gaussian-proof-gate.yml"


class SpacecraftBurnWorkflowTests(unittest.TestCase):
    def test_full_hosted_campaign_is_bounded_and_complete(self):
        source = WORKFLOW.read_text(encoding="utf-8")
        for required in (
            "timeout-minutes:", "jackal_spacecraft_burn_check",
            "spacecraft_burn_proof_identity.py", "lean_admission_audit.py",
            "spacecraft_burn_cert/certify.py", "spacecraft_burn_cert/verify_receipt.py",
            "spacecraft_burn_cert/validate.py", "spacecraft_burn_cert/mutation_aba.py",
            "spacecraft_burn_cert/release_evidence.py",
            "run-a", "run-b", "cmp -s",
            "spacecraft_burn_release_gate.py", "upload-artifact@",
            "macos-14",
        ):
            self.assertIn(required, source)
        actions = re.findall(r"uses:\s*([^\s#]+)", source)
        self.assertTrue(actions, "action SHA checks must not be vacuous")
        for action in actions:
            self.assertRegex(action, r"@[0-9a-f]{40}$")
        self.assertIn("if: always()", source)

    def test_primary_formal_workflow_builds_and_audits_spacecraft_lane(self):
        source = GAUSSIAN.read_text(encoding="utf-8")
        self.assertIn("jackal_spacecraft_burn_check", source)
        self.assertIn("spacecraft_burn_proof_identity.py check --proof-only", source)


if __name__ == "__main__":
    unittest.main()
