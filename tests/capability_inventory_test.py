#!/usr/bin/env python3
"""Contract and mutation tests for the canonical JACKAL capability inventory."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GENERATOR_PATH = ROOT / "tools/capability_inventory.py"
ARTIFACT_PATH = Path("release/capability_inventory_v1.json")
CATALOG_PATH = Path("plugin/hermes/tools.json")
PROFILE_DIR = Path("plugin/hermes/profiles")
MANIFEST_PATH = Path("release/MANIFEST.sha256")
IDENTITY_PATHS = (
    Path("release/evidence/range_proof_identity_v172.json"),
    Path("release/evidence/gaussian_proof_identity.json"),
    Path("release/evidence/int_cert_proof_identity_v172.json"),
)
CODEX_DEVELOPMENT_OVERLAY_INPUTS = {
    "plugins/jackel/.codex-plugin/plugin.json",
    "plugins/jackel/mcp/server.py",
}


def load_generator():
    spec = importlib.util.spec_from_file_location("capability_inventory", GENERATOR_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load capability inventory generator")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


INVENTORY = load_generator()


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def reseal_profile(document: dict) -> None:
    payload = {
        key: value
        for key, value in document.items()
        if key != "profile_digest_sha256"
    }
    document["profile_digest_sha256"] = hashlib.sha256(
        INVENTORY.canonical_bytes(payload)
    ).hexdigest()


class InventoryFixture:
    """Minimal throwaway inventory input tree with no live-source mutation."""

    def __init__(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="jackal-capability-inventory-"))
        paths = [
            Path("tools/capability_inventory.py"),
            CATALOG_PATH,
            MANIFEST_PATH,
            ARTIFACT_PATH,
            Path("plugin/hermes/server.py"),
            Path("plugins/jackel/.codex-plugin/plugin.json"),
            Path("plugins/jackel/mcp/server.py"),
            Path("plugins/jackel/scripts/provision_runtime.py"),
            Path("release/evidence/anubis_program_dogfood_v1.json"),
            INVENTORY.PROGRAM_FLOOR_PATH,
            INVENTORY.PROGRAM_POLICY_PATH,
            *IDENTITY_PATHS,
            *(PROFILE_DIR / f"{profile}.json" for profile in ("core", "formal", "full")),
        ]
        for relative in paths:
            destination = self.root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / relative, destination)

    def cleanup(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

def normalize_development_overlay_inputs(
    generated: dict, committed: dict
) -> dict:
    generated_rows = {row["path"]: row for row in generated["inputs"]}
    committed_rows = {row["path"]: row for row in committed["inputs"]}
    for path in CODEX_DEVELOPMENT_OVERLAY_INPUTS:
        generated_rows[path]["sha256"] = committed_rows[path]["sha256"]
    return generated


class CapabilityInventoryPositiveTest(unittest.TestCase):
    def test_inventory_graph_excludes_self_referential_package_delivery_pins(self) -> None:
        """The package contains this inventory, so it cannot hash its own pins."""
        delivery_pins = {
            Path("plugins/jackel/scripts/provision_runtime.py"),
            Path("release/evidence/anubis_program_dogfood_v1.json"),
        }
        self.assertTrue(delivery_pins.isdisjoint(INVENTORY.INPUT_PATHS))
        document = INVENTORY.build_inventory(ROOT)
        self.assertTrue(
            {path.as_posix() for path in delivery_pins}.isdisjoint(
                {row["path"] for row in document["inputs"]}
            )
        )

    def test_build_is_exact_ordered_41_tool_surface(self) -> None:
        document = INVENTORY.build_inventory(ROOT)
        records = document["tools"]
        catalog = read_json(ROOT / CATALOG_PATH)["tools"]
        names = [row["name"] for row in records]
        self.assertEqual(names, [row["name"] for row in catalog])
        self.assertEqual(document["tool_count"], 41)
        self.assertEqual(document["unique_tool_count"], 41)
        self.assertEqual(len(names), 41)
        self.assertEqual(len(set(names)), 41)

    def test_every_schema_identity_is_from_exact_catalog_record_bytes(self) -> None:
        document = INVENTORY.build_inventory(ROOT)
        catalog = read_json(ROOT / CATALOG_PATH)["tools"]
        expected = {
            row["name"]: hashlib.sha256(INVENTORY.canonical_bytes(row)).hexdigest()
            for row in catalog
        }
        observed = {row["name"]: row["schema_sha256"] for row in document["tools"]}
        self.assertEqual(observed, expected)

    def test_every_tool_has_explicit_exposure_status_boundary_and_dependency(self) -> None:
        document = INVENTORY.build_inventory(ROOT)
        for row in document["tools"]:
            self.assertEqual(
                row["exposure"],
                {"kernel": True, "hermes": True, "codex": True},
                row["name"],
            )
            self.assertTrue(row["status_classes"], row["name"])
            self.assertIn("refused", row["status_classes"], row["name"])
            self.assertTrue(row["assurance_classes"], row["name"])
            self.assertTrue(row["supported_fragment"], row["name"])
            self.assertTrue(row["refusal_boundary"], row["name"])
            self.assertIn("family", row["dependency"])
            self.assertIn("identities", row["dependency"])
            self.assertTrue(row["dependency"]["identities"], row["name"])
            self.assertEqual(row["release_state"], "v1.7.3")
            self.assertEqual(
                row["containing_ref"],
                {
                    "kind": "surface-origin-commit",
                    "value": "d25bcd9818e0d106f337798f80527ae611cc3acc",
                },
            )

        self.assertEqual(document["release"]["state"], "v1.7.3")
        self.assertEqual(
            document["release"]["statement"],
            "Published release identity; the annotated v1.7.3 tag and GitHub release must bind these exact bytes.",
        )

    def test_surface_origin_is_an_ancestor_with_the_same_catalog(self) -> None:
        document = INVENTORY.build_inventory(ROOT)
        INVENTORY.verify_surface_origin(
            ROOT,
            [row["name"] for row in document["tools"]],
        )

    def test_statuses_are_exact_catalog_tokens_and_allowed(self) -> None:
        document = INVENTORY.build_inventory(ROOT)
        catalog = read_json(ROOT / CATALOG_PATH)["tools"]
        expected = {
            row["name"]: row["returns"]["status"].split(" | ") for row in catalog
        }
        observed = {row["name"]: row["status_classes"] for row in document["tools"]}
        self.assertEqual(observed, expected)
        for statuses in observed.values():
            self.assertTrue(set(statuses) <= INVENTORY.ALLOWED_STATUSES)

    def test_profile_membership_is_derived_from_profile_bytes(self) -> None:
        document = INVENTORY.build_inventory(ROOT)
        memberships = {
            profile: set(read_json(ROOT / PROFILE_DIR / f"{profile}.json")["tools"])
            for profile in ("core", "formal", "full")
        }
        for row in document["tools"]:
            expected = [
                profile for profile in ("core", "formal", "full")
                if row["name"] in memberships[profile]
            ]
            self.assertEqual(row["profiles"], expected, row["name"])

    def test_dependency_families_cover_all_required_checker_classes(self) -> None:
        document = INVENTORY.build_inventory(ROOT)
        families = {row["dependency"]["family"] for row in document["tools"]}
        self.assertTrue(
            {
                "lean-range",
                "lean-gaussian",
                "lean-int-cert",
                "lean-receipt-registry",
                "exact-cert-verifier",
                "structural-checker",
                "decision-checker",
                "claim-router",
                "claim-verifier",
                "program-verifier",
                "runtime-only",
            }
            <= families
        )

    def test_program_tools_bind_the_approved_program_compiler(self) -> None:
        document = INVENTORY.build_inventory(ROOT)
        approved = read_json(
            ROOT / "release/compat/v173_floor.json"
        )["approved_check_compiler_sha256"]
        program_tools = [
            row for row in document["tools"]
            if row["dependency"]["family"] == "program-verifier"
        ]
        self.assertEqual(len(program_tools), 3)
        for row in program_tools:
            identities = {
                identity["label"]: identity
                for identity in row["dependency"]["identities"]
            }
            self.assertNotIn("compiler_pin", identities)
            self.assertEqual(
                identities["approved_program_compiler"],
                {
                    "label": "approved_program_compiler",
                    "locator": (
                        "release/compat/v173_floor.json"
                        "#approved_check_compiler_sha256"
                    ),
                    "sha256": approved,
                },
            )

    def test_committed_artifact_is_generated_byte_for_byte(self) -> None:
        fixture = InventoryFixture()
        try:
            committed = read_json(fixture.root / ARTIFACT_PATH)
            generated = normalize_development_overlay_inputs(
                INVENTORY.build_inventory(fixture.root), committed
            )
            self.assertEqual(
                (fixture.root / ARTIFACT_PATH).read_bytes(),
                INVENTORY.canonical_bytes(generated) + b"\n",
            )
        finally:
            fixture.cleanup()

    def test_adapter_aware_cli_reports_exact_count(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                "-B",
                str(ROOT / "tools/capability_drift_gate.py"),
                "--root",
                str(ROOT),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(
            completed.stdout.strip(),
            "CAPABILITY_DRIFT_PASS tools=41 unique=41 codex=58 package=v1.7.3",
        )

    def test_ci_inventory_jobs_use_adapter_aware_drift_gate(self) -> None:
        for relative in (
            ".github/workflows/gaussian-proof-gate.yml",
            ".github/workflows/jackal-codex-plugin.yml",
        ):
            source = (ROOT / relative).read_text(encoding="utf-8")
            self.assertNotIn("tools/capability_inventory.py --check", source, relative)
            inventory_step = source.find("tools/capability_drift_gate.py")
            self.assertGreaterEqual(inventory_step, 0, relative)
            checkout = source.rfind("uses: actions/checkout@", 0, inventory_step)
            self.assertGreaterEqual(checkout, 0, relative)
            next_step = source.find("\n      - name:", checkout)
            self.assertGreater(next_step, checkout, relative)
            self.assertIn("fetch-depth: 0", source[checkout:next_step], relative)


class CapabilityInventoryRefusalTest(unittest.TestCase):
    def test_refuses_duplicate_catalog_name(self) -> None:
        fixture = InventoryFixture()
        try:
            catalog = read_json(fixture.root / CATALOG_PATH)
            catalog["tools"].append(copy.deepcopy(catalog["tools"][0]))
            write_json(fixture.root / CATALOG_PATH, catalog)
            with self.assertRaisesRegex(INVENTORY.InventoryError, "duplicate-tool"):
                INVENTORY.build_inventory(fixture.root)
        finally:
            fixture.cleanup()

    def test_refuses_unmapped_tool_even_when_profiles_are_consistent(self) -> None:
        fixture = InventoryFixture()
        try:
            catalog = read_json(fixture.root / CATALOG_PATH)
            tool = next(row for row in catalog["tools"] if row["name"] == "jackal_exact")
            tool["name"] = "jackal_unmapped_probe"
            write_json(fixture.root / CATALOG_PATH, catalog)
            full = read_json(fixture.root / PROFILE_DIR / "full.json")
            full["tools"] = [
                "jackal_unmapped_probe" if name == "jackal_exact" else name
                for name in full["tools"]
            ]
            reseal_profile(full)
            write_json(fixture.root / PROFILE_DIR / "full.json", full)
            with self.assertRaisesRegex(INVENTORY.InventoryError, "unmapped-tool"):
                INVENTORY.build_inventory(fixture.root)
        finally:
            fixture.cleanup()

    def test_refuses_unknown_status_vocabulary(self) -> None:
        fixture = InventoryFixture()
        try:
            catalog = read_json(fixture.root / CATALOG_PATH)
            catalog["tools"][0]["returns"]["status"] = "cosmic | refused"
            write_json(fixture.root / CATALOG_PATH, catalog)
            with self.assertRaisesRegex(INVENTORY.InventoryError, "status-vocabulary"):
                INVENTORY.build_inventory(fixture.root)
        finally:
            fixture.cleanup()

    def test_refuses_malformed_optional_consequence_ceiling(self) -> None:
        fixture = InventoryFixture()
        try:
            catalog = read_json(fixture.root / CATALOG_PATH)
            catalog["tools"][0]["returns"]["consequence_ceiling"] = 7
            write_json(fixture.root / CATALOG_PATH, catalog)
            with self.assertRaisesRegex(INVENTORY.InventoryError, "catalog-shape"):
                INVENTORY.build_inventory(fixture.root)
        finally:
            fixture.cleanup()

    def test_refuses_missing_checker_identity(self) -> None:
        fixture = InventoryFixture()
        try:
            manifest = (fixture.root / MANIFEST_PATH).read_text(encoding="utf-8")
            manifest = "\n".join(
                line for line in manifest.splitlines()
                if not line.startswith("gaussian-checker ")
            ) + "\n"
            (fixture.root / MANIFEST_PATH).write_text(manifest, encoding="utf-8")
            with self.assertRaisesRegex(INVENTORY.InventoryError, "missing-checker-identity"):
                INVENTORY.build_inventory(fixture.root)
        finally:
            fixture.cleanup()

    def test_refuses_committed_artifact_drift(self) -> None:
        fixture = InventoryFixture()
        try:
            artifact = read_json(fixture.root / ARTIFACT_PATH)
            generated = INVENTORY.build_inventory(fixture.root)
            generated_rows = {row["path"]: row for row in generated["inputs"]}
            artifact_rows = {row["path"]: row for row in artifact["inputs"]}
            for path in CODEX_DEVELOPMENT_OVERLAY_INPUTS:
                artifact_rows[path]["sha256"] = generated_rows[path]["sha256"]
            artifact["tool_count"] = 40
            (fixture.root / ARTIFACT_PATH).write_bytes(
                INVENTORY.canonical_bytes(artifact) + b"\n"
            )
            with self.assertRaisesRegex(INVENTORY.InventoryError, "artifact-drift"):
                INVENTORY.check_committed(fixture.root)
        finally:
            fixture.cleanup()


if __name__ == "__main__":
    unittest.main()
