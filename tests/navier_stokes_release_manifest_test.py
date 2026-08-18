#!/usr/bin/env python3
"""Tests for the standalone Navier--Stokes outer release manifest."""

from __future__ import annotations

import ast
import hashlib
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
VERIFY_TOOL = ROOT / "tools/navier_stokes_release_verify.py"
sys.path.insert(0, str(ROOT / "tools"))

import navier_stokes_release_verify as release_verify  # noqa: E402


class NavierStokesReleaseManifestTests(unittest.TestCase):
    def _write_two_artifact_manifest(
        self, root: Path
    ) -> tuple[tuple[release_verify.ArtifactSpec, ...], Path, dict, bytes]:
        (root / "nested").mkdir(parents=True, exist_ok=True)
        (root / "alpha.txt").write_bytes(b"alpha\n")
        (root / "nested/beta.json").write_bytes(b'{"beta":1}\n')
        specs = (
            release_verify.ArtifactSpec("core.alpha", "source", "alpha.txt"),
            release_verify.ArtifactSpec(
                "evidence.beta", "evidence", "nested/beta.json"
            ),
        )
        manifest = release_verify.build_manifest(root, specs)
        raw = release_verify.canonical_json_bytes(manifest)
        manifest_path = root / "release/evidence/navier_stokes_release_manifest.json"
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_bytes(raw)
        return specs, manifest_path, manifest, raw

    def test_standalone_release_manifest_tool_exists(self) -> None:
        self.assertTrue(VERIFY_TOOL.is_file())

    def test_builder_and_verifier_api_exists(self) -> None:
        self.assertTrue(hasattr(release_verify, "ArtifactSpec"))
        self.assertTrue(hasattr(release_verify, "ManifestRefusal"))
        self.assertTrue(callable(getattr(release_verify, "canonical_json_bytes", None)))
        self.assertTrue(callable(getattr(release_verify, "build_manifest", None)))
        self.assertTrue(callable(getattr(release_verify, "verify_manifest", None)))
        self.assertTrue(callable(getattr(release_verify, "main", None)))

    def test_build_is_deterministic_canonical_and_round_trips_with_caller_pin(self) -> None:
        with tempfile.TemporaryDirectory(prefix="navier-release-manifest-") as temporary:
            root = Path(temporary)
            (root / "nested").mkdir()
            (root / "alpha.txt").write_bytes(b"alpha\n")
            (root / "nested/beta.json").write_bytes(b'{"beta":1}\n')
            specs = (
                release_verify.ArtifactSpec("evidence.beta", "evidence", "nested/beta.json"),
                release_verify.ArtifactSpec("core.alpha", "source", "alpha.txt"),
            )

            first = release_verify.build_manifest(root, specs)
            second = release_verify.build_manifest(root, reversed(specs))
            self.assertNotEqual(first, {})
            self.assertEqual(first, second)
            self.assertEqual(
                [item["path"] for item in first["artifacts"]],
                ["alpha.txt", "nested/beta.json"],
            )
            raw = release_verify.canonical_json_bytes(first)
            self.assertEqual(raw[-1:], b"\n")
            self.assertEqual(
                raw,
                (
                    json.dumps(first, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
                    + "\n"
                ).encode("utf-8"),
            )
            manifest_path = root / "release/evidence/navier_stokes_release_manifest.json"
            manifest_path.parent.mkdir(parents=True)
            manifest_path.write_bytes(raw)
            expected = hashlib.sha256(raw).hexdigest()

            summary = release_verify.verify_manifest(root, manifest_path, expected, specs)
            self.assertEqual(
                summary,
                {
                    "artifact_count": 2,
                    "manifest_sha256": expected,
                    "total_artifact_bytes": len(b"alpha\n") + len(b'{"beta":1}\n'),
                },
            )

    def test_required_inventory_binds_core_tests_evidence_and_theorem_bytes(self) -> None:
        self.assertTrue(hasattr(release_verify, "REQUIRED_ARTIFACTS"))
        required_paths = {item.path for item in release_verify.REQUIRED_ARTIFACTS}
        fixtures = {
            "gate_a_zero_bounded",
            "gate_b_ratio_eq_one_arithmetic_only",
            "gate_b_ratio_gt_one_alert",
            "gate_b_ratio_lt_one_arithmetic_only",
            "gate_c_bkm_euler_refused",
            "gate_c_kato_ponce_disabled",
            "gate_d_ess_endpoint_preconditions_unverified",
            "gate_s_zero_bounded",
        }
        expected = {
            ".github/workflows/navier-stokes-macos-arm64.yml",
            "docs/superpowers/plans/2026-08-17-jackal-navier-stokes-verification-report.md",
            "domain_packs/pde/NAVIER_STOKES_VERIFICATION_SPEC.md",
            "domain_packs/pde/navier_stokes_v1.anb",
            "domain_packs/pde/navier_stokes_v1.json",
            "domain_packs/pde/certificates/JACKAL_T3_ZERO_PROOF_OBJECT_V1.txt",
            "domain_packs/pde/identities/JACKAL_T3_ZERO_SOLUTION_IDENTITY_V1.txt",
            "domain_packs/pde/representations/T3_ZERO_FOURIER_FIELD_V1.txt",
            "domain_packs/pde/sources/CCRT2007_COROLLARY_5_T3_APOSTERIORI.pdf",
            "domain_packs/pde/sources/ESS2003_R3_REGULARITY.pdf",
            "tools/navier_stokes_certificate_producer.py",
            "tools/navier_stokes_receipt_verify.py",
            "tools/navier_stokes_release_verify.py",
            "plugin/hermes/README.md",
            "plugin/hermes/bundle_hash.py",
            "plugin/hermes/jackal_hermes",
            "plugin/hermes/server.py",
            "plugin/hermes/tools.json",
            "release/build_package_v180_navier.py",
            "tests/navier_stokes_package_v180_test.py",
            "tests/plugin_bundle_identity_test.py",
            "tests/plugin_smoke.py",
            "tests/navier_stokes_gate_test.py",
            "tests/navier_stokes_release_blockers_test.py",
            "tests/navier_stokes_release_manifest_test.py",
            "tests/navier_stokes_report_crosscheck.py",
            "tests/navier_stokes_semantic_mutations.py",
            "release/evidence/navier_stokes_claim_audit.json",
            "release/evidence/navier_stokes_report_crosswalk.json",
            "release/evidence/navier_stokes_semantic_mutations.json",
            "release/evidence/navier_stokes_fixture_receipts/build_fixtures.py",
            "release/evidence/navier_stokes_fixture_receipts/index.json",
        }
        for fixture in fixtures:
            expected.add(
                f"release/evidence/navier_stokes_fixture_receipts/requests/{fixture}.json"
            )
            expected.add(
                f"release/evidence/navier_stokes_fixture_receipts/receipts/{fixture}.json"
            )
        self.assertTrue(expected.issubset(required_paths))
        self.assertNotIn(
            "release/evidence/navier_stokes_release_manifest.json", required_paths
        )
        self.assertNotIn("out/navier_stokes_v1.mono.json", required_paths)

    def test_caller_pin_is_mandatory_lowercase_sha256_and_must_match(self) -> None:
        with tempfile.TemporaryDirectory(prefix="navier-release-pin-") as temporary:
            root = Path(temporary)
            specs, manifest_path, unused_manifest, raw = self._write_two_artifact_manifest(root)
            cases = (
                ("", "expected_manifest_digest_invalid"),
                ("A" * 64, "expected_manifest_digest_invalid"),
                ("0" * 64, "manifest_identity_mismatch"),
            )
            self.assertNotEqual(hashlib.sha256(raw).hexdigest(), "0" * 64)
            for candidate, reason in cases:
                with self.subTest(candidate=candidate[:8], reason=reason):
                    with self.assertRaises(release_verify.ManifestRefusal) as raised:
                        release_verify.verify_manifest(
                            root, manifest_path, candidate, specs
                        )
                    self.assertEqual(raised.exception.reason, reason)

    def test_repinning_an_omitted_required_artifact_still_refuses(self) -> None:
        with tempfile.TemporaryDirectory(prefix="navier-release-omission-") as temporary:
            root = Path(temporary)
            specs, manifest_path, manifest, unused_raw = self._write_two_artifact_manifest(root)
            manifest["artifacts"] = manifest["artifacts"][:1]
            raw = release_verify.canonical_json_bytes(manifest)
            manifest_path.write_bytes(raw)
            with self.assertRaises(release_verify.ManifestRefusal) as raised:
                release_verify.verify_manifest(
                    root,
                    manifest_path,
                    hashlib.sha256(raw).hexdigest(),
                    specs,
                )
            self.assertEqual(raised.exception.reason, "required_artifact_missing")

    def test_builder_refuses_self_reference_unsafe_paths_and_macos_aliases(self) -> None:
        with tempfile.TemporaryDirectory(prefix="navier-release-paths-") as temporary:
            root = Path(temporary)
            final_manifest = root / "release/evidence/navier_stokes_release_manifest.json"
            final_manifest.parent.mkdir(parents=True)
            final_manifest.write_bytes(b"not-authority\n")
            (root / "Alpha.txt").write_bytes(b"one\n")
            cases = (
                (
                    (
                        release_verify.ArtifactSpec(
                            "self.manifest",
                            "manifest",
                            "release/evidence/navier_stokes_release_manifest.json",
                        ),
                    ),
                    "manifest_self_reference",
                ),
                ((release_verify.ArtifactSpec("bad.parent", "source", "../escape"),), "artifact_path_invalid"),
                ((release_verify.ArtifactSpec("bad.absolute", "source", "/absolute"),), "artifact_path_invalid"),
                ((release_verify.ArtifactSpec("bad.backslash", "source", "bad\\path"),), "artifact_path_invalid"),
                ((release_verify.ArtifactSpec("bad.dot", "source", "a/./b"),), "artifact_path_invalid"),
                (
                    (
                        release_verify.ArtifactSpec("alias.upper", "source", "Alpha.txt"),
                        release_verify.ArtifactSpec("alias.lower", "source", "alpha.txt"),
                    ),
                    "artifact_path_alias_collision",
                ),
            )
            for specs, reason in cases:
                with self.subTest(reason=reason):
                    with self.assertRaises(release_verify.ManifestRefusal) as raised:
                        release_verify.build_manifest(root, specs)
                    self.assertEqual(raised.exception.reason, reason)

    def test_verifier_refuses_noncanonical_duplicate_unsorted_and_unknown_manifest(self) -> None:
        with tempfile.TemporaryDirectory(prefix="navier-release-format-") as temporary:
            root = Path(temporary)
            specs, manifest_path, manifest, raw = self._write_two_artifact_manifest(root)
            malformed: list[tuple[bytes, str]] = []
            malformed.append((json.dumps(manifest, indent=2).encode("utf-8") + b"\n", "manifest_noncanonical"))
            duplicate = raw[:-2] + b',"schema":"duplicate"}\n'
            malformed.append((duplicate, "manifest_duplicate_field"))
            reversed_manifest = json.loads(raw)
            reversed_manifest["artifacts"].reverse()
            malformed.append(
                (
                    release_verify.canonical_json_bytes(reversed_manifest),
                    "artifact_order_invalid",
                )
            )
            unknown = json.loads(raw)
            unknown["unexpected"] = True
            malformed.append(
                (release_verify.canonical_json_bytes(unknown), "manifest_schema_invalid")
            )
            for candidate, reason in malformed:
                with self.subTest(reason=reason):
                    manifest_path.write_bytes(candidate)
                    with self.assertRaises(release_verify.ManifestRefusal) as raised:
                        release_verify.verify_manifest(
                            root,
                            manifest_path,
                            hashlib.sha256(candidate).hexdigest(),
                            specs,
                        )
                    self.assertEqual(raised.exception.reason, reason)

    def test_named_artifacts_are_nofollow_regular_and_digest_stable(self) -> None:
        with tempfile.TemporaryDirectory(prefix="navier-release-files-") as temporary:
            root = Path(temporary)
            target = root / "target.txt"
            target.write_bytes(b"target\n")
            os.symlink("target.txt", root / "linked.txt")
            with self.assertRaises(release_verify.ManifestRefusal) as raised:
                release_verify.build_manifest(
                    root,
                    (
                        release_verify.ArtifactSpec(
                            "bad.link", "source", "linked.txt"
                        ),
                    ),
                )
            self.assertEqual(raised.exception.reason, "artifact_symlink")

            specs, manifest_path, unused_manifest, raw = self._write_two_artifact_manifest(root)
            (root / "alpha.txt").write_bytes(b"ALPHA\n")
            with self.assertRaises(release_verify.ManifestRefusal) as raised:
                release_verify.verify_manifest(
                    root,
                    manifest_path,
                    hashlib.sha256(raw).hexdigest(),
                    specs,
                )
            self.assertEqual(raised.exception.reason, "artifact_digest_mismatch")

    def test_builder_refuses_empty_and_forbidden_generated_artifacts(self) -> None:
        with tempfile.TemporaryDirectory(prefix="navier-release-forbidden-") as temporary:
            root = Path(temporary)
            (root / "empty.txt").write_bytes(b"")
            with self.assertRaises(release_verify.ManifestRefusal) as raised:
                release_verify.build_manifest(
                    root,
                    (
                        release_verify.ArtifactSpec(
                            "bad.empty", "source", "empty.txt"
                        ),
                    ),
                )
            self.assertEqual(raised.exception.reason, "artifact_empty")

            generated = root / "out/navier_stokes_v1.mono.json"
            generated.parent.mkdir()
            generated.write_bytes(b"[]")
            (root / "good.txt").write_bytes(b"good\n")
            with self.assertRaises(release_verify.ManifestRefusal) as raised:
                release_verify.build_manifest(
                    root,
                    (
                        release_verify.ArtifactSpec(
                            "core.good", "source", "good.txt"
                        ),
                    ),
                )
            self.assertEqual(
                raised.exception.reason, "forbidden_generated_artifact_present"
            )
            with self.assertRaises(release_verify.ManifestRefusal) as raised:
                release_verify.build_manifest(
                    root,
                    (
                        release_verify.ArtifactSpec(
                            "bad.generated",
                            "generated_output",
                            "out/navier_stokes_v1.mono.json",
                        ),
                    ),
                )
            self.assertEqual(raised.exception.reason, "forbidden_generated_artifact")

    def test_verifier_refuses_unbound_generated_output_even_when_manifest_is_repinned(self) -> None:
        with tempfile.TemporaryDirectory(prefix="navier-release-unbound-") as temporary:
            root = Path(temporary)
            specs, manifest_path, unused_manifest, raw = self._write_two_artifact_manifest(root)
            generated = root / "out/navier_stokes_v1.mono.json"
            generated.parent.mkdir()
            generated.write_bytes(b"[]")
            with self.assertRaises(release_verify.ManifestRefusal) as raised:
                release_verify.verify_manifest(
                    root,
                    manifest_path,
                    hashlib.sha256(raw).hexdigest(),
                    specs,
                )
            self.assertEqual(
                raised.exception.reason, "forbidden_generated_artifact_present"
            )

    def test_tool_has_no_import_dependency_on_runtime_producer_or_receipt_verifier(self) -> None:
        tree = ast.parse(VERIFY_TOOL.read_text(encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
        self.assertNotIn("navier_stokes_certificate_producer", imported)
        self.assertNotIn("navier_stokes_receipt_verify", imported)

    def test_cli_builds_deterministically_and_verify_requires_the_caller_pin(self) -> None:
        with tempfile.TemporaryDirectory(prefix="navier-release-cli-") as temporary:
            root = Path(temporary)
            expected_total = 0
            for index, spec in enumerate(release_verify.REQUIRED_ARTIFACTS):
                path = root / spec.path
                path.parent.mkdir(parents=True, exist_ok=True)
                payload = f"required-{index}-{spec.artifact_id}\n".encode("utf-8")
                path.write_bytes(payload)
                expected_total += len(payload)
            extra = root / "integration/catalog.json"
            extra.parent.mkdir(parents=True)
            extra.write_bytes(b'{"tool":"navier"}\n')
            expected_total += extra.stat().st_size
            manifest_path = root / "release/evidence/navier_stokes_release_manifest.json"

            build_command = [
                sys.executable,
                "-B",
                str(VERIFY_TOOL),
                "build",
                "--root",
                str(root),
                "--out",
                str(manifest_path),
                "--artifact",
                "integration.catalog",
                "hermes_catalog",
                "integration/catalog.json",
            ]
            first = subprocess.run(
                build_command, capture_output=True, text=True, check=False, timeout=10
            )
            self.assertEqual(first.returncode, 0, first.stderr)
            first_raw = manifest_path.read_bytes()
            first_digest = hashlib.sha256(first_raw).hexdigest()
            second = subprocess.run(
                build_command, capture_output=True, text=True, check=False, timeout=10
            )
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertEqual(manifest_path.read_bytes(), first_raw)
            self.assertRegex(
                first.stdout,
                rf"^NAVIER_STOKES_RELEASE_MANIFEST_BUILD=PASS manifest_sha256={first_digest} artifacts={len(release_verify.REQUIRED_ARTIFACTS) + 1} total_artifact_bytes={expected_total}\n$",
            )
            self.assertEqual(first.stderr, "")

            missing_pin = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(VERIFY_TOOL),
                    "verify",
                    "--root",
                    str(root),
                    "--manifest",
                    str(manifest_path),
                ],
                capture_output=True,
                text=True,
                check=False,
                timeout=10,
            )
            self.assertEqual(missing_pin.returncode, 2)
            self.assertNotIn("Traceback", missing_pin.stderr)

            verified = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(VERIFY_TOOL),
                    "verify",
                    "--root",
                    str(root),
                    "--manifest",
                    str(manifest_path),
                    "--expected-manifest-sha256",
                    first_digest,
                ],
                capture_output=True,
                text=True,
                check=False,
                timeout=10,
            )
            self.assertEqual(verified.returncode, 0, verified.stderr)
            self.assertEqual(
                verified.stdout,
                f"NAVIER_STOKES_RELEASE_VERIFY=PASS manifest_sha256={first_digest} "
                f"artifacts={len(release_verify.REQUIRED_ARTIFACTS) + 1} "
                f"total_artifact_bytes={expected_total}\n",
            )
            self.assertEqual(verified.stderr, "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
