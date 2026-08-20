#!/usr/bin/env python3
"""Contract, mutation, and parity gates for JACKAL domain packs."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
VERIFIER_PATH = ROOT / "tools" / "domain_pack_verify.py"
ANUBIS = Path(
    os.environ.get(
        "ANUBIS_BIN",
        "/Users/sicarii/anubis-lang/vm/pins/anubis-a733565f237d",
    )
)
FIXED_PATH = (
    "/Users/sicarii/.cargo/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"
)


def load_verifier():
    spec = importlib.util.spec_from_file_location("domain_pack_verify", VERIFIER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load domain-pack verifier")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def write_self_bound(path: Path, value: dict, digest_key: str) -> None:
    document = copy.deepcopy(value)
    document[digest_key] = sha256(
        canonical_bytes({key: item for key, item in document.items() if key != digest_key})
    )
    path.write_bytes(canonical_bytes(document) + b"\n")


class DomainPackContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.verifier = load_verifier()

    def _referenced_checkers(self) -> set[str]:
        """Every checker path any registered manifest names.

        Derived from the manifests rather than hardcoded, so adding a pack with
        a new checker cannot silently leave the temp root incomplete. A missing
        checker used to surface as an unrelated digest refusal; now it fails
        here, loudly, naming the file.
        """
        registry = json.loads(
            (ROOT / "domain_packs" / "registry_v1.json").read_text(encoding="utf-8")
        )
        paths: set[str] = set()
        for pack in registry["packs"]:
            manifest = json.loads((ROOT / pack["manifest_path"]).read_text(encoding="utf-8"))
            for operation in manifest["operations"]:
                paths.add(operation["checker"]["path"])
        if not paths:
            raise AssertionError("no manifest names a checker; the contract is vacuous")
        return paths

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="jackal-domain-pack-test-")
        self.root = Path(self.temp.name)
        shutil.copytree(ROOT / "domain_packs", self.root / "domain_packs")
        (self.root / "release" / "claim").mkdir(parents=True)
        (self.root / "tools").mkdir()
        shutil.copy2(ROOT / "jackal_calc.anb", self.root / "jackal_calc.anb")
        for relative in sorted(self._referenced_checkers()):
            source = ROOT / relative
            if not source.is_file():
                raise AssertionError(
                    f"manifest names checker {relative} but it does not exist at {source}"
                )
            destination = self.root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
        shutil.copy2(
            VERIFIER_PATH,
            self.root / "tools" / "domain_pack_verify.py",
        )
        shutil.copy2(
            ROOT / "release" / "claim" / "inference_registry_v1.json",
            self.root / "release" / "claim" / "inference_registry_v1.json",
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _documents(self) -> tuple[Path, dict, Path, dict]:
        manifest_path = self.root / "domain_packs" / "core" / "manifest.json"
        registry_path = self.root / "domain_packs" / "registry_v1.json"
        return (
            manifest_path,
            json.loads(manifest_path.read_text(encoding="utf-8")),
            registry_path,
            json.loads(registry_path.read_text(encoding="utf-8")),
        )

    def _repin_pack(self, pack_id: str, mutate) -> None:
        """Mutate one registered pack's manifest and re-derive every digest.

        Coherent repinning matters: if the tree were left digest-inconsistent
        the verifier would refuse for a digest reason and the test would prove
        nothing about the policy it claims to exercise.
        """
        registry_path = self.root / "domain_packs" / "registry_v1.json"
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
        row = next(pack for pack in registry["packs"] if pack["pack_id"] == pack_id)
        manifest_path = self.root / row["manifest_path"]
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        mutate(manifest)
        write_self_bound(manifest_path, manifest, "manifest_digest_sha256")
        row["manifest_sha256"] = sha256(manifest_path.read_bytes())
        write_self_bound(registry_path, registry, "registry_digest_sha256")

    def _repin_manifest_and_registry(self, mutate) -> None:
        manifest_path, manifest, registry_path, registry = self._documents()
        mutate(manifest)
        write_self_bound(manifest_path, manifest, "manifest_digest_sha256")
        pack_row = registry["packs"][0]
        pack_row["manifest_sha256"] = sha256(manifest_path.read_bytes())
        write_self_bound(registry_path, registry, "registry_digest_sha256")

    def _repin_schema_and_registry(self, mutate) -> None:
        schema_path = self.root / "domain_packs" / "PACK_SCHEMA.json"
        registry_path = self.root / "domain_packs" / "registry_v1.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
        mutate(schema)
        schema_path.write_bytes(canonical_bytes(schema) + b"\n")
        registry["pack_schema_sha256"] = sha256(schema_path.read_bytes())
        write_self_bound(registry_path, registry, "registry_digest_sha256")

    def assertRefused(self, expected: str) -> None:
        with self.assertRaises(self.verifier.PackVerificationError) as caught:
            self.verifier.verify_repository(self.root)
        self.assertIn(expected, str(caught.exception))

    def test_canonical_repository_contract_passes(self) -> None:
        registry = json.loads(
            (ROOT / "domain_packs" / "registry_v1.json").read_text(encoding="utf-8")
        )
        expected_packs = [pack["pack_id"] for pack in registry["packs"]]
        expected_operations = [
            operation for pack in registry["packs"] for operation in pack["operation_ids"]
        ]
        result = self.verifier.verify_repository(self.root)
        self.assertEqual(result["status"], "accepted")
        # Derived from the registry, not hardcoded: registering a pack must not
        # require editing this assertion. The identity lists keep it honest --
        # a count alone would pass for a tree with the wrong packs in it.
        self.assertEqual(result["pack_count"], len(expected_packs))
        self.assertEqual(result["operation_count"], len(expected_operations))
        self.assertEqual(result["pack_ids"], sorted(expected_packs))
        self.assertEqual(result["operation_ids"], sorted(expected_operations))
        self.assertEqual(result["authority"], "anubis-safe-mode")
        self.assertEqual(
            result["verification_scope"], "metadata-identity-and-policy-only"
        )
        self.assertEqual(result["anubis_execution_status"], "NOT_EXECUTED")
        self.assertEqual(result["assurance_status"], "NOT_MINTED")

    def _set_consequence(self, pack_id: str, ceiling: str) -> None:
        def mutate(manifest):
            for operation in manifest["operations"]:
                operation["consequence_ceiling"] = ceiling
        self._repin_pack(pack_id, mutate)

    def test_structural_programming_fact_cannot_be_laundered_upward(self) -> None:
        # The anti-laundering boundary. "This test exists" is byte-exact, so its
        # assurance ceiling is genuinely `exact` -- but a test existing is never
        # evidence the code under test is correct, so its consequence ceiling is
        # capped at `informational`. Every stronger class must refuse, including
        # the one immediately above the bound.
        pristine = {
            path: path.read_bytes()
            for path in (self.root / "domain_packs").rglob("*.json")
        }
        for ceiling in ("advisory", "decision-boundary", "safety-critical"):
            with self.subTest(consequence_ceiling=ceiling):
                for path, raw in pristine.items():
                    path.write_bytes(raw)
                self._set_consequence("jackal.programming.source", ceiling)
                self.assertRefused(
                    "v1 consequence ceiling exceeds the evidence-contract bound"
                )

    def test_decision_pack_cannot_reach_safety_critical(self) -> None:
        self._set_consequence("jackal.decision.matrix", "safety-critical")
        self.assertRefused("v1 consequence ceiling exceeds the evidence-contract bound")

    def test_consequence_ceiling_is_an_upper_bound_not_an_equality(self) -> None:
        # Declaring a weaker class than the bound is always allowed; otherwise
        # the refusal above would be an identity check wearing a ceiling's name,
        # and this suite could not tell the two apart.
        self._set_consequence("jackal.decision.matrix", "informational")
        result = self.verifier.verify_repository(self.root)
        self.assertEqual(result["status"], "accepted")

    def test_unrankable_consequence_class_refuses(self) -> None:
        # Instrument check on the ceiling comparison itself: if the pinned
        # registry ever declares a class this verifier cannot rank, comparing
        # against a partial order would silently admit anything unranked.
        registry_path = self.root / "release" / "claim" / "inference_registry_v1.json"
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
        registry["consequence_classes"]["mission-critical"] = copy.deepcopy(
            registry["consequence_classes"]["safety-critical"]
        )
        registry_path.write_text(json.dumps(registry, indent=2), encoding="utf-8")
        pack_registry_path = self.root / "domain_packs" / "registry_v1.json"
        pack_registry = json.loads(pack_registry_path.read_text(encoding="utf-8"))
        pack_registry["inference_registry_sha256"] = sha256(registry_path.read_bytes())
        write_self_bound(pack_registry_path, pack_registry, "registry_digest_sha256")
        self.assertRefused("registry declares consequence classes outside the v1 order")

    def test_duplicate_operation_id_refuses_after_coherent_repin(self) -> None:
        self._repin_manifest_and_registry(
            lambda manifest: manifest["operations"].append(
                copy.deepcopy(manifest["operations"][0])
            )
        )
        self.assertRefused("duplicate operation id")

    def test_fallback_must_be_explicitly_forbidden(self) -> None:
        def mutate(manifest: dict) -> None:
            manifest["operations"][0]["fallback"]["allowed"] = True

        self._repin_manifest_and_registry(mutate)
        self.assertRefused("fallback must be forbidden")

    def test_refusal_classes_are_mandatory(self) -> None:
        def mutate(manifest: dict) -> None:
            manifest["operations"][0]["refusal_classes"] = []

        self._repin_manifest_and_registry(mutate)
        self.assertRefused("refusal classes missing")

    def test_every_resource_bound_is_mandatory(self) -> None:
        def mutate(manifest: dict) -> None:
            del manifest["operations"][0]["resources"]["timeout_ms"]

        self._repin_manifest_and_registry(mutate)
        self.assertRefused("resource keys mismatch")

    def test_non_anubis_authority_refuses(self) -> None:
        def mutate(manifest: dict) -> None:
            manifest["engine"]["authority"] = "python"

        self._repin_manifest_and_registry(mutate)
        self.assertRefused("non-Anubis authority")

    def test_non_apple_silicon_macos_host_refuses_before_inventory_access(self) -> None:
        with (
            mock.patch.object(self.verifier.platform, "system", return_value="Linux"),
            mock.patch.object(self.verifier.platform, "machine", return_value="x86_64"),
            mock.patch.object(self.verifier, "load_json") as load_json,
        ):
            self.assertRefused("unsupported host")
        load_json.assert_not_called()

    def test_v1_schema_resource_ceilings_cannot_be_coherently_raised(self) -> None:
        self._repin_schema_and_registry(
            lambda schema: schema["limits"].__setitem__(
                "max_artifact_bytes", schema["limits"]["max_artifact_bytes"] + 1
            )
        )
        self.assertRefused("v1 protocol limits mismatch")

    def test_v1_schema_mandatory_nonclaims_cannot_be_weakened(self) -> None:
        self._repin_schema_and_registry(
            lambda schema: schema.__setitem__(
                "required_nonclaims", ["raw_output_requires_independent_verification"]
            )
        )
        self.assertRefused("v1 mandatory nonclaims mismatch")

    def test_metadata_json_structure_depth_is_bounded(self) -> None:
        def mutate(schema: dict) -> None:
            nested: object = "anubis-safe-mode"
            for _ in range(80):
                nested = [nested]
            schema["authority"] = nested

        self._repin_schema_and_registry(mutate)
        self.assertRefused("JSON structure depth budget exceeded")

    def test_metadata_json_integer_digit_count_is_bounded_before_conversion(self) -> None:
        self._repin_schema_and_registry(
            lambda schema: schema["limits"].__setitem__(
                "max_artifact_bytes", 10**200
            )
        )
        self.assertRefused("JSON integer exceeds digit budget")

    def test_release_compatibility_range_must_be_ordered(self) -> None:
        def mutate(manifest: dict) -> None:
            manifest["compatibility"]["jackal_release_min"] = "v2.0.0"
            manifest["compatibility"]["jackal_release_max_exclusive"] = "v1.8.0"

        self._repin_manifest_and_registry(mutate)
        self.assertRefused("compatibility range is empty or reversed")

    def test_assurance_ceiling_requires_registered_inference_rule(self) -> None:
        def mutate(manifest: dict) -> None:
            manifest["operations"][0]["inference_rule"] = "unregistered_rule"

        self._repin_manifest_and_registry(mutate)
        self.assertRefused("inference rule is not registered")

    def test_v1_operation_cannot_substitute_a_weaker_registered_rule(self) -> None:
        def mutate(manifest: dict) -> None:
            manifest["operations"][0]["inference_rule"] = "input_declare"

        self._repin_manifest_and_registry(mutate)
        self.assertRefused("v1 operations require evidence_admit")

    def test_v1_evidence_contract_cannot_be_replaced_by_pack_bytes(self) -> None:
        alternate = self.root / "tools" / "alternate_checker.py"
        alternate.write_text(
            "#!/usr/bin/env python3\nprint('ACCEPT')\n", encoding="utf-8"
        )

        def mutate(manifest: dict) -> None:
            operation = manifest["operations"][0]
            operation["checker"]["path"] = "tools/alternate_checker.py"
            operation["checker"]["sha256"] = sha256(alternate.read_bytes())

        self._repin_manifest_and_registry(mutate)
        self.assertRefused("v1 evidence contract mismatch")

    def test_v1_response_schema_is_bound_to_the_trusted_checker(self) -> None:
        def mutate(manifest: dict) -> None:
            manifest["operations"][0]["response_schema"] = "attacker-schema-v1"

        self._repin_manifest_and_registry(mutate)
        self.assertRefused("v1 evidence contract mismatch")

    def test_source_tamper_refuses_and_a_b_a_restoration_passes(self) -> None:
        source = self.root / "domain_packs" / "core" / "core_pack.anb"
        original = source.read_bytes()
        source.write_bytes(original + b"\n// mutation\n")
        self.assertRefused("artifact digest mismatch")
        source.write_bytes(original)
        result = self.verifier.verify_repository(self.root)
        self.assertEqual(result["status"], "accepted")

    def test_pack_verifier_identity_is_bound_by_the_registry(self) -> None:
        verifier = self.root / "tools" / "domain_pack_verify.py"
        verifier.write_bytes(verifier.read_bytes() + b"\n# mutation\n")
        self.assertRefused("artifact digest mismatch: tools/domain_pack_verify.py")

    def test_unknown_extra_artifact_refuses(self) -> None:
        extra = self.root / "domain_packs" / "core" / "undeclared.txt"
        extra.write_text("undeclared\n", encoding="utf-8")
        self.assertRefused("domain-pack inventory mismatch")

    def test_domain_inventory_has_an_early_entry_budget(self) -> None:
        extra = self.root / "domain_packs" / "core" / "undeclared.txt"
        extra.write_text("undeclared\n", encoding="utf-8")
        with mock.patch.object(self.verifier, "MAX_DOMAIN_INVENTORY_ENTRIES", 6):
            self.assertRefused("domain-pack inventory entry budget exceeded")

    def test_direct_and_pack_route_outputs_are_byte_identical(self) -> None:
        if not ANUBIS.is_file():
            self.skipTest("pinned Anubis compiler unavailable")
        cases = [
            ("3", "100", "7"),
            ("-12", "5", "97"),
            ("12345678901234567890", "0", "101"),
            ("42", "17", "1"),
        ]
        for index, arguments in enumerate(cases):
            with self.subTest(case=index):
                with tempfile.TemporaryDirectory(
                    prefix="jackal-domain-pack-run-"
                ) as out_root:
                    environment = {
                        "ANUBIS_BIN": os.fspath(ANUBIS),
                        "JACKAL_FORCE_SOURCE": "1",
                        "JACKAL_OUT": os.fspath(Path(out_root) / "direct"),
                        "PATH": FIXED_PATH,
                    }
                    direct = subprocess.run(
                        [os.fspath(ROOT / "jackal"), "mod-pow", *arguments],
                        cwd=ROOT,
                        env=environment,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        timeout=120,
                        check=False,
                    )
                    environment["JACKAL_OUT"] = os.fspath(Path(out_root) / "routed")
                    routed = subprocess.run(
                        [
                            os.fspath(ROOT / "jackal"),
                            "pack-route",
                            "jackal.core.exact",
                            "core.exact.mod_pow.v1",
                            *arguments,
                        ],
                        cwd=ROOT,
                        env=environment,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        timeout=120,
                        check=False,
                    )
                self.assertEqual(direct.returncode, 0, direct.stderr.decode())
                self.assertEqual(routed.returncode, 0, routed.stderr.decode())
                self.assertEqual(routed.stdout, direct.stdout)
                certificate_lines = [
                    line.removeprefix(b"exact-cert=")
                    for line in routed.stdout.splitlines()
                    if line.startswith(b"exact-cert=")
                ]
                self.assertEqual(len(certificate_lines), 1)
                checked = subprocess.run(
                    [
                        "/usr/bin/python3",
                        "-I",
                        "-S",
                        "-B",
                        os.fspath(ROOT / "tools" / "exact_verify.py"),
                        "-",
                    ],
                    cwd=ROOT,
                    env={"PATH": "/usr/bin:/bin:/usr/sbin:/sbin"},
                    input=certificate_lines[0],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=30,
                    check=False,
                )
                self.assertEqual(checked.returncode, 0, checked.stderr.decode())
                self.assertIn(b"ACCEPT", checked.stdout)

    def test_unknown_operation_does_not_fallback(self) -> None:
        if not ANUBIS.is_file():
            self.skipTest("pinned Anubis compiler unavailable")
        with tempfile.TemporaryDirectory(prefix="jackal-domain-pack-refuse-") as out_root:
            completed = subprocess.run(
                [
                    os.fspath(ROOT / "jackal"),
                    "pack-route",
                    "jackal.core.exact",
                    "core.exact.unknown.v1",
                    "3",
                    "100",
                    "7",
                ],
                cwd=ROOT,
                env={
                    "ANUBIS_BIN": os.fspath(ANUBIS),
                    "JACKAL_FORCE_SOURCE": "1",
                    "JACKAL_OUT": out_root,
                    "PATH": FIXED_PATH,
                },
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=120,
                check=False,
            )
        self.assertNotEqual(completed.returncode, 0)
        combined = (completed.stdout + completed.stderr).decode(errors="replace")
        self.assertIn("pack-operation-unknown", combined)
        self.assertNotIn("exact-cert=", combined)


if __name__ == "__main__":
    unittest.main(verbosity=2)
