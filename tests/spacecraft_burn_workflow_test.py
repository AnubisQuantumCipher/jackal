from __future__ import annotations

import re
import hashlib
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "spacecraft-burn-proof-gate.yml"
GAUSSIAN = ROOT / ".github" / "workflows" / "gaussian-proof-gate.yml"


def executable_workflow_surface(source: str) -> str:
    """Return YAML execution/configuration values with comments removed."""
    surface = []
    for line in source.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        surface.append(line.split(" #", 1)[0])
    return "\n".join(surface)


class SpacecraftBurnWorkflowTests(unittest.TestCase):
    def test_comment_only_workflow_literals_are_not_executable_surface(self):
        source = """name: decoy\njobs:\n  check:\n    # run: jackal_spacecraft_burn_check\n    steps:\n      # - uses: actions/upload-artifact@0123456789012345678901234567890123456789\n      - run: echo harmless\n"""
        surface = executable_workflow_surface(source)
        self.assertNotIn("jackal_spacecraft_burn_check", surface)
        self.assertNotIn("upload-artifact@", surface)

    def test_full_hosted_campaign_is_bounded_and_complete(self):
        source = WORKFLOW.read_text(encoding="utf-8")
        source = executable_workflow_surface(source)
        self.assertIn("timeout-minutes: 360", source)
        self.assertNotIn("timeout-minutes: 60", source)
        self.assertNotIn("timeout-minutes: 240", source)
        self.assertIn("fetch-depth: 0", source)
        request_digest = hashlib.sha256(
            (ROOT / "spacecraft_burn_cert/request_v2.json").read_bytes()
        ).hexdigest()
        self.assertIn(f"REQUEST_DIGEST: {request_digest}", source)
        self.assertIn(
            '--evidence-dir "$RUNNER_TEMP/spacecraft-v2/reproduced-evidence"',
            source.replace("\\\n", " "),
        )
        for required in (
            "timeout-minutes:", "jackal_spacecraft_burn_check",
            "spacecraft_burn_proof_identity.py", "lean_admission_audit.py",
            "spacecraft_burn_cert/certify.py", "spacecraft_burn_cert/verify_receipt.py",
            "spacecraft_burn_cert/validate.py", "spacecraft_burn_cert/mutation_aba.py",
            "spacecraft_burn_cert/release_evidence.py",
            "tests.spacecraft_burn_release_package_v175_test",
            "tests.spacecraft_burn_v175_epoch_test",
            "tests.spacecraft_burn_publication_state_test",
            '--instrument-validation "$RUN_A/instrument_validation_v2.json"',
            "run-a", "run-b", "cmp -s",
            "spacecraft_burn_release_gate.py", "upload-artifact@",
            "macos-14",
        ):
            self.assertIn(required, source)
        for publication_only in (
            "package_spacecraft_v175.py",
            "--reviewed-commit",
            "tar -xzf",
            'python3 -I -B "$ARCHIVE_ROOT/verifier/verify_receipt.py"',
            'spacecraft_burn_cert/release_evidence.py --staging-dir "$RUN_A" --check',
            'cmp -s "$RUNNER_TEMP/spacecraft-v2/proof_identity.json"',
        ):
            self.assertNotIn(publication_only, source.replace("\\\n", " "))
        actions = re.findall(r"uses:\s*([^\s#]+)", source)
        self.assertTrue(actions, "action SHA checks must not be vacuous")
        for action in actions:
            self.assertRegex(action, r"@[0-9a-f]{40}$")
        self.assertIn("if: always()", source)
        self.assertIn(
            "NON-PUBLICATION-platform-local-spacecraft-burn-macos-14-${{ github.sha }}",
            source,
        )
        self.assertNotIn("matrix.os", source)

    def test_full_campaign_uses_maximum_hosted_timeout_without_scope_reduction(self):
        source = executable_workflow_surface(
            WORKFLOW.read_text(encoding="utf-8")
        )
        self.assertEqual(source.count("timeout-minutes:"), 1)
        self.assertIn("timeout-minutes: 360", source)
        self.assertNotIn("timeout-minutes: 240", source)
        for required in (
            "jackal_spacecraft_burn_check",
            "spacecraft_burn_proof_identity.py check --proof-only",
            "spacecraft_burn_cert/certify.py",
            "spacecraft_burn_cert/verify_receipt.py",
            "spacecraft_burn_cert/validate.py",
            "spacecraft_burn_cert/mutation_aba.py",
            "spacecraft_burn_cert/release_evidence.py",
            "tests.spacecraft_burn_release_package_v175_test",
            "run-a",
            "run-b",
            "cmp -s",
            "spacecraft_burn_release_gate.py",
        ):
            self.assertIn(required, source)

    def test_full_campaign_push_scope_is_master_and_version_tags_only(self):
        source = executable_workflow_surface(
            WORKFLOW.read_text(encoding="utf-8")
        )
        trigger = source[:source.index("permissions:")]
        self.assertRegex(
            trigger,
            (
                r"(?m)^on:\n"
                r"  push:\n"
                r"    branches:\n"
                r"      - master\n"
                r"    tags:\n"
                r"      - ['\"]v\*['\"]\n"
                r"  pull_request:\n"
                r"  workflow_dispatch:$"
            ),
        )
        self.assertNotIn("branches-ignore:", trigger)
        self.assertNotIn("tags-ignore:", trigger)

    def test_early_failure_artifact_upload_warns_when_no_files_exist(self):
        source = executable_workflow_surface(
            WORKFLOW.read_text(encoding="utf-8")
        )
        self.assertIn("if: always()", source)
        self.assertIn("if-no-files-found: warn", source)
        self.assertNotIn("if-no-files-found: error", source)
        self.assertIn("actions/upload-artifact@", source)

    def test_primary_formal_workflow_builds_and_audits_spacecraft_lane(self):
        source = GAUSSIAN.read_text(encoding="utf-8")
        source = executable_workflow_surface(source)
        self.assertIn("jackal_spacecraft_burn_check", source)
        self.assertIn("spacecraft_burn_proof_identity.py check --proof-only", source)
        self.assertIn("release/compat/v173_lakefile.toml", source)
        self.assertLess(
            source.index("range_proof_identity.py check --lane int-cert"),
            source.index('cp "$RUNNER_TEMP/v174-lakefile.toml" proofs/lean/lakefile.toml'),
        )
        self.assertLess(
            source.index('cp "$RUNNER_TEMP/v174-lakefile.toml" proofs/lean/lakefile.toml'),
            source.index("spacecraft_burn_proof_identity.py check --proof-only"),
        )


if __name__ == "__main__":
    unittest.main()
