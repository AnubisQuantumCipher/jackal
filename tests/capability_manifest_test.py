#!/usr/bin/env python3
"""W2 capability manifest — parity, schema, revoked-lane, and A->B->A tests.

Run: python3 tests/capability_manifest_test.py
"""
from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import capability_manifest as cm  # noqa: E402

MANIFEST = cm.MANIFEST_PATH
SCHEMA = ROOT / "release/capabilities/jackal_capabilities_v1.schema.json"
GEN = ROOT / "tools/capability_manifest.py"


def run_check() -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(GEN), "--check"],
        capture_output=True, text=True, cwd=ROOT)


class CapabilityManifestTests(unittest.TestCase):
    def setUp(self) -> None:
        # Pristine committed bytes, captured before any mutation.
        self._orig = MANIFEST.read_text(encoding="utf-8")

    def tearDown(self) -> None:
        # Always restore, even if an assertion failed mid-mutation.
        MANIFEST.write_text(self._orig, encoding="utf-8")

    def test_parity_holds(self) -> None:
        p = run_check()
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn("CAPABILITY_MANIFEST_PARITY=PASS", p.stdout)

    def test_manifest_matches_committed_bytes(self) -> None:
        self.assertEqual(cm.canonical(cm.build_manifest()), self._orig)

    def test_build_is_deterministic(self) -> None:
        self.assertEqual(
            cm.canonical(cm.build_manifest()),
            cm.canonical(cm.build_manifest()))

    def test_schema_required_keys_present(self) -> None:
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        man = json.loads(self._orig)
        for key in schema["required"]:
            self.assertIn(key, man, f"schema-required key missing: {key}")
        try:
            import jsonschema  # noqa: WPS433 - optional stricter validation
            jsonschema.validate(man, schema)
        except ImportError:
            pass

    def test_revoked_lane_not_promoted(self) -> None:
        man = json.loads(self._orig)
        self.assertFalse(
            man["bundle_admissibility"]["revoked_checker_present_in_repo"],
            "revoked lane must never be present")
        sha = man["bundle_admissibility"]["revoked_checker_sha256"]
        mani = ROOT / "release/MANIFEST.sha256"
        if mani.exists():
            self.assertNotIn(
                sha, mani.read_text(encoding="utf-8"),
                "revoked checker sha appears in MANIFEST.sha256")

    def _aba(self, mutate) -> None:
        """A (parity) -> B (mutate one axis -> gate FAILs) -> A (restore -> PASS)."""
        self.assertEqual(run_check().returncode, 0, "A: baseline parity")
        man = json.loads(self._orig)
        mutate(man)
        MANIFEST.write_text(cm.canonical(man), encoding="utf-8")
        drift = run_check()
        self.assertNotEqual(drift.returncode, 0, "B: gate must detect drift")
        self.assertIn("FAIL", drift.stdout)
        MANIFEST.write_text(self._orig, encoding="utf-8")
        self.assertEqual(run_check().returncode, 0, "A: parity restored")

    def test_aba_admissibility(self) -> None:
        self._aba(lambda x: x["bundle_admissibility"].__setitem__(
            "revoked_checker_present_in_repo", True))

    def test_aba_checker_identity(self) -> None:
        self._aba(lambda x: x["coverage_inventory"].__setitem__(
            "sha256", "0" * 64))

    def test_aba_assurance_ceiling(self) -> None:
        self._aba(lambda x: x["assurance_ceilings"][
            "producer_emittable_provenance"].append("measured"))

    def test_aba_platform(self) -> None:
        self._aba(lambda x: x["platform"].__setitem__("arch", "x86_64"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
