#!/usr/bin/env python3
"""Semantic documentation, package-pin, adapter, and skill drift controls."""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DRIFT_PATH = ROOT / "tools/capability_drift_gate.py"
ARTIFACT_PATH = Path("release/capability_inventory_v1.json")
CURRENT_SURFACES = (
    Path("README.md"),
    Path("GETTING-STARTED.md"),
    Path("PROVENANCE.md"),
    Path("docs/superpowers/specs/2026-08-17-jackel-codex-plugin-design.md"),
    Path("plugins/jackel/skills/jackel/SKILL.md"),
)


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


DRIFT = load_module("capability_drift_gate", DRIFT_PATH)
INVENTORY = load_module("capability_inventory_for_drift_test", ROOT / "tools/capability_inventory.py")


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


class DriftFixture:
    def __init__(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="jackal-capability-drift-"))
        paths = {
            *INVENTORY.INPUT_PATHS,
            INVENTORY.PROGRAM_FLOOR_PATH,
            INVENTORY.PROGRAM_POLICY_PATH,
            ARTIFACT_PATH,
            *CURRENT_SURFACES,
            Path("plugins/jackel/scripts/provision_runtime.py"),
            Path("plugins/jackel/PLUGIN_IDENTITY.sha256"),
            *(
                Path("plugins/jackel") / relative
                for relative in DRIFT.CODEX_PLUGIN_IDENTITY_FILES
            ),
            DRIFT.PACKAGE_EVIDENCE_PATH,
        }
        for relative in sorted(paths):
            destination = self.root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / relative, destination)

    def cleanup(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)


class CapabilityDriftPositiveTest(unittest.TestCase):
    def test_package_pin_uses_dedicated_alignment_receipt(self) -> None:
        self.assertEqual(
            DRIFT.PACKAGE_EVIDENCE_PATH,
            Path("release/evidence/package_alignment_v173_candidate.json"),
        )

    def test_current_repository_surface_verifies(self) -> None:
        result = DRIFT.verify_surface(ROOT)
        self.assertEqual(result["tool_count"], 41)
        self.assertEqual(result["unique_tool_count"], 41)
        self.assertEqual(result["codex_tool_count"], 41)
        self.assertEqual(result["package_epoch"], "v1.7.3")

    def test_historical_34_tool_fact_outside_current_contract_is_allowed(self) -> None:
        fixture = DriftFixture()
        try:
            provenance = fixture.root / "PROVENANCE.md"
            provenance.write_text(
                provenance.read_text(encoding="utf-8")
                + "\n## Historical migration record\n\n"
                + "The v1.7.0 release exposed a 34-tool surface.\n",
                encoding="utf-8",
            )
            result = DRIFT.verify_surface(fixture.root)
            self.assertEqual(result["tool_count"], 41)
        finally:
            fixture.cleanup()

    def test_skill_tool_parser_returns_only_real_current_names(self) -> None:
        inventory = read_json(ROOT / ARTIFACT_PATH)
        known = {row["name"] for row in inventory["tools"]}
        skill = (ROOT / "plugins/jackel/skills/jackel/SKILL.md").read_text(
            encoding="utf-8"
        )
        names = DRIFT.skill_tool_names(skill)
        self.assertTrue(names)
        self.assertTrue(names <= known)

    def test_codex_plugin_identity_is_generated_from_exact_wrapper_bytes(self) -> None:
        self.assertEqual(
            (ROOT / "plugins/jackel/PLUGIN_IDENTITY.sha256").read_bytes(),
            DRIFT.render_codex_plugin_identity(ROOT),
        )

    def test_cli_reports_bound_counts_and_package_epoch(self) -> None:
        completed = subprocess.run(
            [sys.executable, "-B", str(DRIFT_PATH), "--root", str(ROOT)],
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(
            completed.stdout.strip(),
            "CAPABILITY_DRIFT_PASS tools=41 unique=41 codex=41 package=v1.7.3",
        )


class CapabilityDriftRefusalTest(unittest.TestCase):
    def replace_once(self, source: str, needle: str, replacement: str) -> str:
        self.assertIn(needle, source, f"mutation needle absent: {needle!r}")
        mutated = source.replace(needle, replacement, 1)
        self.assertNotEqual(mutated, source, "mutation did not change source")
        return mutated

    def test_refuses_current_tool_count_drift(self) -> None:
        fixture = DriftFixture()
        try:
            path = fixture.root / "plugins/jackel/.codex-plugin/plugin.json"
            document = read_json(path)
            document["interface"]["longDescription"] = self.replace_once(
                document["interface"]["longDescription"], "41-tool", "34-tool"
            )
            write_json(path, document)
            with self.assertRaisesRegex(DRIFT.DriftError, "current-tool-count"):
                DRIFT.verify_surface(fixture.root)
        finally:
            fixture.cleanup()

    def test_refuses_unknown_skill_tool(self) -> None:
        fixture = DriftFixture()
        try:
            skill = fixture.root / "plugins/jackel/skills/jackel/SKILL.md"
            skill.write_text(
                skill.read_text(encoding="utf-8")
                + "\nRoute this through `jackal_nonexistent_probe`.\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(DRIFT.DriftError, "unknown-skill-tool"):
                DRIFT.verify_surface(fixture.root)
        finally:
            fixture.cleanup()

    def test_refuses_package_pin_mismatch(self) -> None:
        fixture = DriftFixture()
        try:
            provisioner = fixture.root / "plugins/jackel/scripts/provision_runtime.py"
            source = provisioner.read_text(encoding="utf-8")
            expected = read_json(ROOT / DRIFT.PACKAGE_EVIDENCE_PATH)["package"][
                "sha256"
            ]
            source = self.replace_once(
                source,
                f'PACKAGE_SHA256 = "{expected}"',
                f'PACKAGE_SHA256 = "{"0" * 64}"',
            )
            provisioner.write_text(source, encoding="utf-8")
            with self.assertRaisesRegex(DRIFT.DriftError, "package-pin-mismatch"):
                DRIFT.verify_surface(fixture.root)
        finally:
            fixture.cleanup()

    def test_refuses_unknown_status_vocabulary(self) -> None:
        fixture = DriftFixture()
        try:
            skill = fixture.root / "plugins/jackel/skills/jackel/SKILL.md"
            skill.write_text(
                skill.read_text(encoding="utf-8")
                + "\nAdapter probe result: status=cosmic.\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(DRIFT.DriftError, "status-vocabulary"):
                DRIFT.verify_surface(fixture.root)
        finally:
            fixture.cleanup()

    def test_refuses_codex_wrapper_count_mismatch(self) -> None:
        fixture = DriftFixture()
        try:
            server = fixture.root / "plugins/jackel/mcp/server.py"
            source = self.replace_once(
                server.read_text(encoding="utf-8"),
                "EXPECTED_TOOL_COUNT = 41",
                "EXPECTED_TOOL_COUNT = 40",
            )
            server.write_text(source, encoding="utf-8")
            with self.assertRaisesRegex(DRIFT.DriftError, "codex-tool-count"):
                DRIFT.verify_surface(fixture.root)
        finally:
            fixture.cleanup()

    def test_refuses_missing_current_surface_marker(self) -> None:
        fixture = DriftFixture()
        try:
            readme = fixture.root / "README.md"
            text = self.replace_once(
                readme.read_text(encoding="utf-8"),
                DRIFT.CURRENT_SURFACE_BEGIN,
                "<!-- removed-current-surface -->",
            )
            readme.write_text(text, encoding="utf-8")
            with self.assertRaisesRegex(DRIFT.DriftError, "current-surface-marker"):
                DRIFT.verify_surface(fixture.root)
        finally:
            fixture.cleanup()

    def test_refuses_codex_plugin_identity_drift(self) -> None:
        fixture = DriftFixture()
        try:
            identity = fixture.root / "plugins/jackel/PLUGIN_IDENTITY.sha256"
            source = identity.read_text(encoding="utf-8")
            identity.write_text(
                self.replace_once(source, "a", "b"), encoding="utf-8"
            )
            with self.assertRaisesRegex(DRIFT.DriftError, "plugin-identity-drift"):
                DRIFT.check_codex_plugin_identity(fixture.root)
        finally:
            fixture.cleanup()


if __name__ == "__main__":
    unittest.main()
