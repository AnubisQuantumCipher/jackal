import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SPARK_ROOT = REPO_ROOT / "proofs/spark/hellgate_interval"
ASSUMPTION_GUARD = REPO_ROOT / "proofs/spark/reject_assumptions.sh"


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
        lowered = text.lower()
        self.assertNotIn("pragma assume", lowered)
        self.assertNotIn("pragma annotate", lowered)

    @unittest.skipUnless(shutil.which("rg"), "rg is not installed")
    def test_assumption_guard_rejects_case_and_line_break_bypasses(self):
        with tempfile.TemporaryDirectory() as raw_directory:
            directory = Path(raw_directory)
            source = directory / "guard_probe.adb"
            report = directory / "gnatprove.out"
            report.write_text(
                "Guard_Probe (0 pragma Assume statements)\n",
                encoding="utf-8",
            )
            source.write_text(
                "procedure Guard_Probe is begin null; end Guard_Probe;\n",
                encoding="utf-8",
            )
            accepted = subprocess.run(
                [str(ASSUMPTION_GUARD), str(report), str(directory)],
                cwd=REPO_ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(
                accepted.returncode, 0, accepted.stdout + accepted.stderr
            )

            forbidden_pragmas = (
                "pragma aSsUmE (True);",
                "pragma\nAnNoTaTe (GNATprove, False_Positive, \"probe\");",
            )
            for forbidden in forbidden_pragmas:
                with self.subTest(forbidden=forbidden):
                    source.write_text(forbidden + "\n", encoding="utf-8")
                    refused = subprocess.run(
                        [str(ASSUMPTION_GUARD), str(report), str(directory)],
                        cwd=REPO_ROOT,
                        check=False,
                        capture_output=True,
                        text=True,
                    )
                    transcript = refused.stdout + refused.stderr
                    self.assertNotEqual(refused.returncode, 0, transcript)
                    self.assertIn(
                        "proof assumptions or justifications are forbidden",
                        transcript,
                    )

            source.write_text(
                "procedure Guard_Probe is begin null; end Guard_Probe;\n",
                encoding="utf-8",
            )
            report.write_text(
                "Guard_Probe (1 pragma Assume statement)\n",
                encoding="utf-8",
            )
            refused_report = subprocess.run(
                [str(ASSUMPTION_GUARD), str(report), str(directory)],
                cwd=REPO_ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
            report_transcript = refused_report.stdout + refused_report.stderr
            self.assertNotEqual(refused_report.returncode, 0, report_transcript)
            self.assertIn(
                "GNATprove reports one or more proof assumptions",
                report_transcript,
            )

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
