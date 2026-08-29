import shutil
import subprocess
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SPARK_ROOT = REPO_ROOT / "proofs/spark/hellgate_interval"


class SparkIntervalEnvelopeTests(unittest.TestCase):
    """Proof regression for JCK-INT-001, JCK-INT-002, JCK-INT-003, JCK-INT-004."""

    def test_source_keeps_the_declared_formal_boundary(self):
        sources = [
            SPARK_ROOT / "src/jackal_interval_envelope.ads",
            SPARK_ROOT / "src/jackal_interval_envelope.adb",
            SPARK_ROOT / "tests/hellgate_interval_demo.adb",
        ]
        text = "\n".join(path.read_text(encoding="utf-8") for path in sources)
        self.assertIn("SPARK_Mode", text)
        self.assertIn("function Admits_Untrusted_Envelope", text)
        self.assertIn("function Strictly_Meets_Target", text)
        self.assertIn("function Evaluate_Untrusted_Envelope", text)
        self.assertIn("Required_Verdict", text)
        self.assertIn("Post =>", text)
        self.assertNotIn("pragma Assume", text)
        self.assertNotIn("pragma Annotate", text)

    @unittest.skipUnless(
        shutil.which("gprbuild") and shutil.which("gnatprove") and shutil.which("rg"),
        "GNATprove toolchain is not installed",
    )
    def test_build_runtime_boundary_and_gnatprove_gate(self):
        completed = subprocess.run(
            [str(SPARK_ROOT / "prove.sh")],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
        )
        transcript = completed.stdout + completed.stderr
        self.assertEqual(completed.returncode, 0, transcript)
        self.assertIn("HELLGATE fixed-scale interval envelope: ACCEPT", transcript)
        self.assertIn("Success: all checks proved", transcript)
        self.assertIn("SPARK_PLATINUM_INTERVAL_COMPONENT_PROOF_PASS", transcript)


if __name__ == "__main__":
    unittest.main()
