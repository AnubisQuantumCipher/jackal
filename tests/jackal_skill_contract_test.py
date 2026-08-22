#!/usr/bin/env python3
"""Check JACKAL routing skills against the canonical capability inventory."""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INVENTORY = ROOT / "release/capability_inventory_v1.json"
REPO_ROUTER = ROOT / "plugins/jackel/skills/jackel/SKILL.md"
HOME = Path.home()
PERSONAL_CODEX_ORACLE = HOME / ".codex/skills/jackal-assurance-oracle/SKILL.md"
PERSONAL_HERMES_ROUTER = (
    HOME
    / ".hermes/skills/software-development/jackal-verified-computation/SKILL.md"
)
PERSONAL_HERMES_RESEAL = (
    HOME
    / ".hermes/skills/software-development/jackal-trust-boundary-reseal/SKILL.md"
)
PROFILE_HERMES_ROUTERS = tuple(
    HOME
    / f".hermes/profiles/{profile}/skills/software-development/"
    "jackal-verified-computation/SKILL.md"
    for profile in ("alecto", "athena", "hephaestus", "themis")
)

TOOL_REFERENCE = re.compile(r"`(jackal_[a-z0-9_]+)`")
CURRENT_BEGIN = "<!-- JACKAL_CURRENT_SURFACE_V1_BEGIN -->"
CURRENT_END = "<!-- JACKAL_CURRENT_SURFACE_V1_END -->"
REQUIRED_ROUTING = {
    "jackal_claim",
    "jackal_verify_bundle",
    "jackal_verify_receipt",
    "jackal_anubis_verify_program",
    "jackal_anubis_verify_program_receipt",
}
STALE_CURRENT = (
    "34-tool surface",
    "34 tools",
    "v1.7.0 kernel",
    "plugin v5.0.0 is enabled",
)


def inventory_names() -> set[str]:
    document = json.loads(INVENTORY.read_text(encoding="utf-8"))
    return {row["name"] for row in document["tools"]}


def current_block(text: str) -> str:
    if text.count(CURRENT_BEGIN) != 1 or text.count(CURRENT_END) != 1:
        raise AssertionError("skill must contain one canonical current-surface block")
    start = text.index(CURRENT_BEGIN) + len(CURRENT_BEGIN)
    end = text.index(CURRENT_END)
    if end <= start:
        raise AssertionError("skill current-surface markers are reversed")
    return text[start:end]


def assert_router_contract(
    case: unittest.TestCase, path: Path, *, require_marker: bool = True
) -> None:
    text = path.read_text(encoding="utf-8")
    lower = text.lower()
    names = inventory_names()
    references = set(TOOL_REFERENCE.findall(text))
    case.assertTrue(REQUIRED_ROUTING <= references, (path, references))
    case.assertEqual(references - names, set(), (path, references - names))
    for phrase in ("caller-pinned", "refused", "indeterminate"):
        case.assertIn(phrase, lower, (path, phrase))
    case.assertRegex(lower, r"(?:no|never) silent(?:ly)? downgrade")
    if require_marker:
        block = current_block(text)
        case.assertIn("41-tool", block)
        case.assertIn("release/capability_inventory_v1.json", block)
    for stale in STALE_CURRENT:
        case.assertNotIn(stale, lower, (path, stale))


class JackalSkillContractTest(unittest.TestCase):
    def test_repository_codex_router_uses_only_inventory_tools(self) -> None:
        assert_router_contract(self, REPO_ROUTER)

    def test_personal_codex_oracle_names_current_replay_front_doors(self) -> None:
        if not PERSONAL_CODEX_ORACLE.is_file():
            self.skipTest("personal Codex oracle is not installed on this host")
        text = PERSONAL_CODEX_ORACLE.read_text(encoding="utf-8")
        references = set(TOOL_REFERENCE.findall(text))
        self.assertTrue(REQUIRED_ROUTING <= references, references)
        self.assertEqual(references - inventory_names(), set())
        self.assertIn("Current v1.7.3 profiles: `core=3`, `formal=13`, `full=41`", text)

    def test_personal_hermes_router_uses_only_inventory_tools(self) -> None:
        if not PERSONAL_HERMES_ROUTER.is_file():
            self.skipTest("personal Hermes router is not installed on this host")
        assert_router_contract(self, PERSONAL_HERMES_ROUTER)

    def test_profile_hermes_routers_equal_the_reviewed_personal_router(self) -> None:
        if not PERSONAL_HERMES_ROUTER.is_file():
            self.skipTest("personal Hermes router is not installed on this host")
        expected = PERSONAL_HERMES_ROUTER.read_bytes()
        checked = 0
        for path in PROFILE_HERMES_ROUTERS:
            if not path.is_file():
                continue
            checked += 1
            self.assertEqual(path.read_bytes(), expected, path)
        if checked == 0:
            self.skipTest("no Hermes profile router copies are installed")

    def test_personal_reseal_covers_current_trust_artifacts(self) -> None:
        if not PERSONAL_HERMES_RESEAL.is_file():
            self.skipTest("personal Hermes reseal skill is not installed on this host")
        text = PERSONAL_HERMES_RESEAL.read_text(encoding="utf-8")
        for required in (
            "jackal_cert_check",
            "jackal_gaussian_check",
            "jackal_int_cert_check",
            "release/capability_inventory_v1.json",
            "release/build_package_v173.sh",
            "inventory-safe-v1",
            "policy-construct-totality-not-established",
        ):
            self.assertIn(required, text, (PERSONAL_HERMES_RESEAL, required))


if __name__ == "__main__":
    unittest.main()
