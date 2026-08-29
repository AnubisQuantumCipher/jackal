import json
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPARK_ROOT = ROOT / "proofs/spark/claim_policy"
VECTORS = SPARK_ROOT / "bin/jackal_claim_policy_vectors"
VERIFIER_BRIDGE = ROOT / "tests/claim_policy_verifier_bridge.py"

sys.path.insert(0, str(ROOT))
from tools import claim_kernel as producer  # noqa: E402


def normalized(value: str, prefix: str = "") -> str:
    result = value.strip().lower().replace("_", "-")
    if prefix and result.startswith(prefix):
        return result[len(prefix):]
    return result


def artifact_flags(mask: int) -> dict[str, bool]:
    return {
        flag: bool(mask & (1 << position))
        for position, flag in enumerate(producer.ARTIFACT_FLAGS)
    }


def artifact_mask(flags: dict[str, bool]) -> int:
    return sum(
        1 << position
        for position, flag in enumerate(producer.ARTIFACT_FLAGS)
        if flags[flag]
    )


def assurance_parent(
    *,
    mathematical: str = "checked",
    implementation: str = "directly-trusted",
    input_provenance: str = "unknown",
    model_validity: str = "not-applicable",
    artifact: dict[str, bool] | None = None,
) -> dict:
    return {
        "assurance": {
            "input_provenance": input_provenance,
            "model_validity": model_validity,
            "mathematical": mathematical,
            "implementation": implementation,
            "artifact": artifact or {
                flag: False for flag in producer.ARTIFACT_FLAGS
            },
        }
    }


class ClaimPolicyConformanceTests(unittest.TestCase):
    """Exhaustive refinement for JCK-CLAIM-001, JCK-CLAIM-002, JCK-CLAIM-003."""

    def test_source_keeps_the_declared_formal_boundary(self) -> None:
        sources = [
            SPARK_ROOT / "src/jackal_claim_policy.ads",
            SPARK_ROOT / "src/jackal_claim_policy.adb",
        ]
        text = "\n".join(path.read_text(encoding="utf-8") for path in sources)
        self.assertIn("SPARK_Mode", text)
        self.assertIn("function Meet_Mathematical", text)
        self.assertIn("function Apply_Rule_Caps", text)
        self.assertIn("function Meet_Artifact", text)
        self.assertIn("Post =>", text)
        self.assertNotIn("pragma Assume", text)
        self.assertNotIn("pragma Annotate", text)

    @unittest.skipUnless(
        shutil.which("gprbuild") and shutil.which("gnatprove") and shutil.which("rg"),
        "GNATprove toolchain is not installed",
    )
    def test_proved_kernel_matches_both_python_implementations_exhaustively(self) -> None:
        proof = subprocess.run(
            [str(SPARK_ROOT / "prove.sh")],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
        )
        transcript = proof.stdout + proof.stderr
        self.assertEqual(proof.returncode, 0, transcript)
        self.assertIn("Success: all checks proved", transcript)
        self.assertIn("SPARK_PLATINUM_CLAIM_POLICY_COMPONENT_PROOF_PASS", transcript)

        completed = subprocess.run(
            [str(VECTORS)],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

        seen: set[str] = set()
        rule_vectors: dict[tuple[str, str, str], tuple[str, str]] = {}

        def integrated_axes(rule_id: str, parents: list[dict]) -> dict:
            return producer.computed_axes(rule_id, parents)

        for raw_line in completed.stdout.splitlines():
            fields = [field.strip() for field in raw_line.split("|")]
            kind = fields[0]
            seen.add(kind)

            if kind == "MATH":
                left, right, expected = (normalized(item) for item in fields[1:])
                self.assertEqual(
                    producer._meet([left, right], producer.MATH_ORDER,
                                   producer.MATH_RANKS),
                    expected,
                )
                axes = integrated_axes(
                    "model_condition",
                    [
                        assurance_parent(mathematical=left),
                        assurance_parent(mathematical=right),
                    ],
                )
                self.assertEqual(axes["mathematical"], expected)
            elif kind == "PROVENANCE":
                left, right, expected = (normalized(item) for item in fields[1:])
                self.assertEqual(
                    producer._meet([left, right], producer.PROV_ORDER), expected
                )
                axes = integrated_axes(
                    "model_condition",
                    [
                        assurance_parent(input_provenance=left),
                        assurance_parent(input_provenance=right),
                    ],
                )
                self.assertEqual(axes["input_provenance"], expected)
            elif kind == "MODEL":
                left, right, expected = (
                    normalized(item, "model-") for item in fields[1:]
                )
                self.assertEqual(producer._meet_model([left, right]), expected)
                axes = integrated_axes(
                    "model_condition",
                    [
                        assurance_parent(model_validity=left),
                        assurance_parent(model_validity=right),
                    ],
                )
                self.assertEqual(axes["model_validity"], expected)
            elif kind == "IMPLEMENTATION":
                left, right, expected = (
                    normalized(item, "impl-") for item in fields[1:]
                )
                self.assertEqual(
                    producer._meet([left, right], producer.IMPL_ORDER), expected
                )
                axes = integrated_axes(
                    "model_condition",
                    [
                        assurance_parent(implementation=left),
                        assurance_parent(implementation=right),
                    ],
                )
                self.assertEqual(axes["implementation"], expected)
            elif kind == "RULE":
                behavior = normalized(fields[1])
                mathematical = normalized(fields[2])
                implementation = normalized(fields[3], "impl-")
                rule_vectors[(behavior, mathematical, implementation)] = (
                    normalized(fields[4]), normalized(fields[5], "impl-")
                )
            elif kind == "ARTIFACT":
                left, right, expected = (int(item) for item in fields[1:])
                self.assertEqual(left & right, expected)
                axes = integrated_axes(
                    "model_condition",
                    [
                        assurance_parent(artifact=artifact_flags(left)),
                        assurance_parent(artifact=artifact_flags(right)),
                    ],
                )
                self.assertEqual(artifact_mask(axes["artifact"]), expected)
            else:
                self.fail(f"unknown SPARK vector kind: {kind}")

        self.assertEqual(
            seen,
            {"MATH", "PROVENANCE", "MODEL", "IMPLEMENTATION", "RULE", "ARTIFACT"},
        )

        bridge = subprocess.run(
            [
                sys.executable,
                "-I",
                "-S",
                "-B",
                str(VERIFIER_BRIDGE),
                str(VECTORS),
            ],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(bridge.returncode, 0, bridge.stdout + bridge.stderr)
        bridge_result = json.loads(bridge.stdout)
        self.assertEqual(bridge_result["status"], "pass")
        self.assertEqual(producer.PROV_ORDER, bridge_result["PROV_ORDER"])
        self.assertEqual(producer.MODEL_ORDER, bridge_result["MODEL_ORDER"])
        self.assertEqual(producer.MODEL_IDENTITY, bridge_result["MODEL_IDENTITY"])
        self.assertEqual(producer.MATH_ORDER, bridge_result["MATH_ORDER"])
        self.assertEqual(producer.MATH_RANKS, bridge_result["MATH_RANKS"])
        self.assertEqual(producer.IMPL_ORDER, bridge_result["IMPL_ORDER"])
        self.assertEqual(producer.ARTIFACT_FLAGS, bridge_result["ARTIFACT_FLAGS"])
        self.assertEqual(producer.MATH_CAPS, bridge_result["MATH_CAPS"])
        self.assertEqual(
            sorted(producer.PRESERVE_RULES), bridge_result["PRESERVE_RULES"]
        )
        self.assertEqual(producer.IMPL_CAP_DEFAULT, bridge_result["IMPL_CAP_DEFAULT"])

        for rule_id in bridge_result["RULE_IDS"]:
            if rule_id in producer.PRESERVE_RULES:
                behavior = "preserve-axes"
            elif rule_id in producer.MATH_CAPS:
                behavior = "interval-arithmetic"
            else:
                behavior = "derived-default"
            for mathematical in producer.MATH_ORDER:
                for implementation in producer.IMPL_ORDER:
                    expected_math, expected_impl = rule_vectors[
                        (behavior, mathematical, implementation)
                    ]
                    parent = assurance_parent(
                        mathematical=mathematical, implementation=implementation
                    )
                    produced = integrated_axes(rule_id, [parent])
                    self.assertEqual(produced["mathematical"], expected_math)
                    self.assertEqual(produced["implementation"], expected_impl)


if __name__ == "__main__":
    unittest.main(verbosity=2)
