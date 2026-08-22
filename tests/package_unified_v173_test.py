#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import importlib.util
import os
import subprocess
import tempfile
import shutil
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILDER = ROOT / "release/build_package_v173.sh"
REPIN = ROOT / "release/tools/repin_v173.py"
COMPAT = ROOT / "release/compat/v173_floor.json"
ALIGNMENT_RECEIPT = ROOT / "release/evidence/package_alignment_v173_candidate.json"
PACKAGE_NAME = "jackal-v1.7.3-macos-arm64"
REQUIRED_PACKAGE_INPUTS = {
    "release/capability_inventory_v1.json",
    "domain_packs/PACK_SCHEMA.json",
    "domain_packs/PACK_SPEC.md",
    "domain_packs/registry_v1.json",
    "domain_packs/core/manifest.json",
    "domain_packs/core/core_pack.anb",
    "domain_packs/programming/manifest.json",
    "domain_packs/programming/programming_pack.anb",
    "domain_packs/decision/manifest.json",
    "domain_packs/decision/decision_pack.anb",
    "tools/domain_pack_verify.py",
    "tools/exact_verify.py",
    "tools/test_exists_verify.py",
    "tools/decision_verify.py",
    "release/program/SPEC.md",
    "release/evidence/lean_admission_audit_v173.json",
    "tools/anubis_program_verify.py",
    "release/program/inventory_safe_v1.json",
    "plugin/hermes/profiles/core.json",
    "plugin/hermes/profiles/formal.json",
    "plugin/hermes/profiles/full.json",
    "plugin/hermes/schemas/jackal_agent_profile.schema.json",
}
REQUIRED_MANIFEST_LABELS = {
    "domain_pack_registry",
    "domain_pack_verifier",
    "domain_pack_test_exists_checker",
    "domain_pack_decision_checker",
    "anubis_program_verifier",
    "anubis_program_policy",
    "plugin_hermes",
    "source",
    "evaluator",
    "claim_inference_registry",
    "lean-admission-audit",
    "lean-admission-audit-digest",
}


def complete_sha256sums(root: Path) -> bool:
    sums = root / "SHA256SUMS"
    if sums.is_symlink() or not sums.is_file():
        return False
    rows: dict[str, str] = {}
    for line in sums.read_text(encoding="utf-8").splitlines():
        digest, separator, raw_path = line.partition("  ")
        if (
            separator != "  "
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
            or not raw_path.startswith("./")
        ):
            return False
        relative = raw_path[2:]
        if not relative or relative in rows:
            return False
        rows[relative] = digest
    actual = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and path.name != "SHA256SUMS"
    }
    if set(rows) != actual:
        return False
    for relative, expected in rows.items():
        path = root / relative
        if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            return False
    return True


class UnifiedPackageV173Test(unittest.TestCase):
    def test_alignment_receipt_binds_reproducible_candidate_and_live_codex(self) -> None:
        document = json.loads(ALIGNMENT_RECEIPT.read_text(encoding="utf-8"))
        self.assertEqual(document["schema"], "jackal-package-alignment-v1")
        self.assertEqual(document["release_state"], "v1.7.3-candidate")
        self.assertEqual(
            document["package"],
            {
                "basename": "jackal-v1.7.3-macos-arm64.tar.gz",
                "bytes": 158362119,
                "extracted_file_bytes": 555504965,
                "file_count": 106,
                "sha256": "cafab1555d3ea7cf207fd5564464fbe35dfa9288cdd650fe226d9f7633254196",
                "sha256sums_root": "df2d71627cbd02a2dfd45beec4c87efc35753de17b98a8e0d76baf7cf13c9cd6",
            },
        )
        source = document["source"]
        for key, relative in (
            ("builder_sha256", "release/build_package_v173.sh"),
            ("manifest_sha256", "release/MANIFEST.sha256"),
            ("capability_inventory_sha256", "release/capability_inventory_v1.json"),
        ):
            self.assertEqual(
                source[key], hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
            )
        self.assertEqual(
            document["comparisons"],
            {"directory_diff_exit": 0, "tarball_cmp_exit": 0},
        )
        self.assertEqual(
            document["gates"]["package_unified_tests"],
            {"exit": 0, "passed": 11, "skipped": 0},
        )
        self.assertEqual(
            document["gates"]["claim_package_parity"],
            {"exit": 0, "failures": 0, "rows": 60},
        )
        self.assertEqual(
            document["gates"]["codex_repository_tests"],
            {"exit": 0, "passed": 216},
        )
        self.assertEqual(
            document["gates"]["codex_live_acceptance"]["discovered_tool_count"],
            41,
        )
        self.assertIn("no-public-v1.7.3-release-assertion", document["non_claims"])
        self.assertIn("architect-trust-surface-signoff-required", document["non_claims"])

    def test_builder_and_repin_declare_every_unified_trust_input(self) -> None:
        self.assertTrue(BUILDER.is_file(), BUILDER)
        self.assertTrue(REPIN.is_file(), REPIN)
        self.assertTrue(COMPAT.is_file(), COMPAT)
        builder = BUILDER.read_text(encoding="utf-8")
        repin = REPIN.read_text(encoding="utf-8")
        self.assertIn('VER="v1.7.3"', builder)
        self.assertIn('JACKAL_DIST', builder)
        for relative in sorted(REQUIRED_PACKAGE_INPUTS):
            self.assertIn(relative, builder, relative)
        for label in sorted(REQUIRED_MANIFEST_LABELS):
            self.assertIn(label, repin, label)
        self.assertIn("jackal-anubis-program", builder)
        self.assertIn("PACKAGE_V173_BUILD_PASS", builder)

    def test_catalog_profiles_and_compatibility_floor_agree(self) -> None:
        catalog = json.loads((ROOT / "plugin/hermes/tools.json").read_text())
        compatibility = json.loads(COMPAT.read_text())
        full = json.loads((ROOT / "plugin/hermes/profiles/full.json").read_text())
        names = [row["name"] for row in catalog["tools"]]
        self.assertEqual(catalog["version"], "v1.7.3")
        self.assertEqual(compatibility["release_epoch"], "v1.7.3")
        self.assertEqual(compatibility["tool_count"], 41)
        self.assertEqual(compatibility["program_profile"], "inventory-safe-v1")
        self.assertIs(
            compatibility["independent_policy_construct_totality"], False
        )
        self.assertEqual(full["tools"], names)

        inventory = json.loads(
            (ROOT / "release/capability_inventory_v1.json").read_text()
        )
        self.assertEqual(inventory["schema"], "jackal-capability-inventory-v1")
        self.assertEqual(inventory["tool_count"], 41)
        self.assertEqual(inventory["unique_tool_count"], 41)
        self.assertEqual(
            [row["name"] for row in inventory["tools"]],
            names,
        )
        self.assertEqual(
            inventory["catalog"]["sha256"],
            hashlib.sha256(
                (ROOT / "plugin/hermes/tools.json").read_bytes()
            ).hexdigest(),
        )

    def test_dry_run_and_repin_check_are_current_source_instruments(self) -> None:
        dry = subprocess.run(
            [str(BUILDER), "--dry-run"],
            capture_output=True,
            text=True,
            cwd=ROOT,
            timeout=120,
        )
        self.assertEqual(dry.returncode, 0, dry.stdout + dry.stderr)
        self.assertIn("PACKAGE_V173_DRY_RUN_PASS", dry.stdout)
        repin = subprocess.run(
            [os.fspath(REPIN), "--check"],
            capture_output=True,
            text=True,
            cwd=ROOT,
            timeout=120,
        )
        self.assertEqual(repin.returncode, 0, repin.stdout + repin.stderr)
        self.assertIn("REPIN_V173_CHECK_PASS", repin.stdout)

    def test_built_package_has_reachable_complete_surface(self) -> None:
        package_root_raw = os.environ.get("JACKAL_TEST_PACKAGE_ROOT")
        if not package_root_raw:
            self.skipTest("set JACKAL_TEST_PACKAGE_ROOT to a freshly built package")
        package = Path(package_root_raw)
        self.assertEqual(package.name, PACKAGE_NAME)
        self.assertTrue((package / "jackal-anubis-program").is_file())
        for relative in REQUIRED_PACKAGE_INPUTS:
            destination = relative
            if relative.startswith("release/"):
                destination = relative.removeprefix("release/")
            self.assertTrue((package / destination).is_file(), destination)
        listed = subprocess.run(
            [str(package / "plugin/hermes/jackal_hermes"), "stdio"],
            input=json.dumps(
                {"jsonrpc": "2.0", "id": "catalog", "method": "list_tools"}
            )
            + "\n",
            capture_output=True,
            text=True,
            cwd=package,
            timeout=120,
        )
        self.assertEqual(listed.returncode, 0, listed.stdout + listed.stderr)
        reply = json.loads(listed.stdout.strip())
        self.assertEqual(len(reply["result"]["tools"]), 41)


    def test_missing_pack_refuses_pack_only(self) -> None:
        package_root_raw = os.environ.get("JACKAL_TEST_PACKAGE_ROOT")
        if not package_root_raw:
            self.skipTest("set JACKAL_TEST_PACKAGE_ROOT to a freshly built package")
        source_package = Path(package_root_raw)
        with tempfile.TemporaryDirectory(prefix="jackal-package-no-pack-") as td:
            package = Path(td) / PACKAGE_NAME
            shutil.copytree(source_package, package)
            shutil.rmtree(package / "domain_packs")
            nonpack = subprocess.run(
                [
                    str(package / "plugin/hermes/jackal_hermes"),
                    "call",
                    "jackal_exact",
                    json.dumps({"expression": "1+1"}),
                ],
                capture_output=True,
                text=True,
                cwd=package,
                timeout=120,
            )
            self.assertEqual(nonpack.returncode, 0, nonpack.stdout + nonpack.stderr)
            self.assertEqual(json.loads(nonpack.stdout)["status"], "exact")
            pack = subprocess.run(
                [
                    str(package / "plugin/hermes/jackal_hermes"),
                    "call",
                    "jackal_test_exists",
                    json.dumps(
                        {
                            "file_path": "README.txt",
                            "file_sha256": "0" * 64,
                            "symbol": "missing",
                            "declaration_line": "1",
                            "declaration_count": "1",
                        }
                    ),
                ],
                capture_output=True,
                text=True,
                cwd=package,
                timeout=120,
            )
            self.assertNotEqual(pack.returncode, 0)
            self.assertEqual(
                json.loads(pack.stdout)["reason"], "pack-surface-absent"
            )

    def test_declared_program_tool_with_missing_runtime_refuses_startup(self) -> None:
        package_root_raw = os.environ.get("JACKAL_TEST_PACKAGE_ROOT")
        if not package_root_raw:
            self.skipTest("set JACKAL_TEST_PACKAGE_ROOT to a freshly built package")
        source_package = Path(package_root_raw)
        with tempfile.TemporaryDirectory(prefix="jackal-package-unreachable-") as td:
            package = Path(td) / PACKAGE_NAME
            shutil.copytree(source_package, package)
            (package / "tools/anubis_program_verify.py").unlink()
            result = subprocess.run(
                [str(package / "plugin/hermes/jackal_hermes"), "selftest"],
                capture_output=True,
                text=True,
                cwd=package,
                timeout=120,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(
                "plugin-layout-missing: anubis_program_verifier",
                result.stdout + result.stderr,
            )


    def test_sha256sums_is_complete_and_mutation_sensitive(self) -> None:
        package_root_raw = os.environ.get("JACKAL_TEST_PACKAGE_ROOT")
        if not package_root_raw:
            self.skipTest("set JACKAL_TEST_PACKAGE_ROOT to a freshly built package")
        source_package = Path(package_root_raw)
        self.assertTrue(complete_sha256sums(source_package))
        with tempfile.TemporaryDirectory(prefix="jackal-package-sums-") as td:
            package = Path(td) / PACKAGE_NAME
            shutil.copytree(source_package, package)
            (package / "unlisted-extra.txt").write_text("extra\n")
            self.assertFalse(complete_sha256sums(package))
            (package / "unlisted-extra.txt").unlink()

            readme = package / "README.txt"
            readme.write_bytes(readme.read_bytes() + b"tamper\n")
            self.assertFalse(complete_sha256sums(package))
            shutil.copy2(source_package / "README.txt", readme)

            sums = package / "SHA256SUMS"
            lines = sums.read_text().splitlines()
            sums.write_text("\n".join(lines[1:]) + "\n")
            self.assertFalse(complete_sha256sums(package))


    def test_stale_binary_source_pair_refuses_formal_tool(self) -> None:
        package_root_raw = os.environ.get("JACKAL_TEST_PACKAGE_ROOT")
        if not package_root_raw:
            self.skipTest("set JACKAL_TEST_PACKAGE_ROOT to a freshly built package")
        source_package = Path(package_root_raw)
        with tempfile.TemporaryDirectory(prefix="jackal-package-stale-source-") as td:
            package = Path(td) / PACKAGE_NAME
            shutil.copytree(source_package, package)
            source = package / "jackal_calc.anb"
            source.write_bytes(source.read_bytes() + b"\n")
            result = subprocess.run(
                [
                    str(package / "plugin/hermes/jackal_hermes"),
                    "call",
                    "jackal_range_bound",
                    json.dumps(
                        {
                            "expression": "x",
                            "input_lo": "0",
                            "input_hi": "1",
                        }
                    ),
                ],
                capture_output=True,
                text=True,
                cwd=package,
                timeout=120,
            )
            self.assertNotEqual(result.returncode, 0)
            document = json.loads(result.stdout)
            self.assertEqual(document["status"], "refused")
            self.assertEqual(document["reason"], "source-identity")


    def test_every_domain_pack_admits_the_selected_release(self) -> None:
        for pack in ("core", "programming", "decision"):
            document = json.loads(
                (ROOT / f"domain_packs/{pack}/manifest.json").read_text()
            )
            compatibility = document["compatibility"]
            self.assertEqual(
                compatibility["jackal_release_min"],
                "v1.7.3",
                f"{pack} excludes the selected release",
            )
            self.assertEqual(
                compatibility["jackal_release_max_exclusive"], "v2.0.0"
            )

    def test_superseded_builder_mutation_turns_instrument_red(self) -> None:
        path = ROOT / "tests/claim_package_parity_test.py"
        spec = importlib.util.spec_from_file_location("claim_package_parity", path)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        current, current_reason = module.instrument_current()
        self.assertTrue(current, current_reason)
        module.BUILDER = ROOT / "release/build_package_v170.sh"
        accepted, reason = module.instrument_current()
        self.assertFalse(accepted)
        self.assertEqual(reason, "superseded-builder")

if __name__ == "__main__":
    unittest.main()
