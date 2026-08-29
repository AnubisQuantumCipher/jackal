import json
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "assurance/requirements.json"


class AssuranceTraceabilityTests(unittest.TestCase):
    """JCK-INT-001 through JCK-INT-004 and whole-surface closure regression."""

    def test_traceability_and_surface_closure_gate(self) -> None:
        completed = subprocess.run(
            ["python3", "-B", "tools/check_assurance_traceability.py"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertIn("JACKAL_ASSURANCE_TRACEABILITY_PASS", completed.stdout)

    def test_whole_product_claim_stays_open_with_unproved_surfaces(self) -> None:
        document = json.loads(BASELINE.read_text(encoding="utf-8"))
        self.assertEqual(document["product_claim"]["status"], "in-progress")
        closure = document["surface_closure"]
        statuses = list(closure["sealed_dependency_families"].values())
        statuses.extend(closure["additive_groups"].values())
        self.assertTrue(any(status != closure["closed_status"] for status in statuses))


if __name__ == "__main__":
    unittest.main(verbosity=2)
