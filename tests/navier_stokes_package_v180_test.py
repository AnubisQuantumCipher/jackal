#!/usr/bin/env python3
"""Contract tests for the isolated JACKAL Navier v1.8 package lane."""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import tempfile
import unittest
from unittest import mock
from pathlib import Path
import sys
import subprocess


ROOT = Path(__file__).resolve().parents[1]
BUILDER = ROOT / "release/build_package_v180_navier.py"
WORKFLOW = ROOT / ".github/workflows/navier-stokes-macos-arm64.yml"
sys.path.insert(0, str(ROOT / "release"))

import build_package_v180_navier as package_v180  # noqa: E402


class NavierStokesPackageV180Tests(unittest.TestCase):
    def _write_synthetic_catalog(self, root: Path) -> tuple[str, str]:
        plugin = root / "plugin/hermes"
        plugin.mkdir(parents=True)
        runtime_files: dict[str, list[str]] = {}
        logical_to_path = {
            "plugin/bundle_hash.py": "bundle_hash.py",
            "plugin/jackal_hermes": "jackal_hermes",
            "plugin/server.py": "server.py",
            "plugin/tools.json": "tools.json",
            **{
                logical: f"../../{logical.removeprefix('runtime/')}"
                for logical in package_v180.REQUIRED_NAVIER_RUNTIME_FILES
            },
        }
        for logical, candidate in logical_to_path.items():
            runtime_files[logical] = [candidate]
            if logical != "plugin/tools.json":
                physical = plugin / candidate
                physical.parent.mkdir(parents=True, exist_ok=True)
                physical.write_bytes((logical + "\n").encode("utf-8"))
        catalog = {
            "schema": "jackal-hermes-plugin-v1",
            "plugin_id": "jackal_range_bound",
            "version": "v1.8.0",
            "description": "synthetic caller-pinned Navier catalog",
            "bundle_files": ["server.py", "bundle_hash.py", "jackal_hermes", "tools.json"],
            "bundle_identity_schema": "jackal-hermes-runtime-bundle-v2",
            "runtime_files": runtime_files,
            "tools": [
                {
                    "name": "jackal_navier_stokes_check",
                    "description": "direct finite-scope checker; not_global_regular and not_millennium_solved",
                    "arguments": {
                        "request": {"type": "object", "required": True},
                    },
                    "returns": {
                        "status": "bounded | indeterminate | refused",
                        "verification_scope": "receipt_replay_only",
                        "nonclaims": "exact request nonclaims",
                    },
                },
                {
                    "name": "jackal_verify_navier_stokes_receipt",
                    "description": "independent receipt replay; never upgraded",
                    "arguments": {
                        "receipt": {"type": "object", "required": True},
                        "expected_request": {"type": "object", "required": True},
                    },
                    "returns": {
                        "status": "verified | refused",
                        "verification_scope": "receipt_replay_only",
                        "mathematical_status": "unchanged",
                    },
                },
            ],
        }
        raw = package_v180.canonical_json_bytes(catalog)
        (plugin / "tools.json").write_bytes(raw)
        catalog_digest = hashlib.sha256(raw).hexdigest()

        digest = hashlib.sha256()
        digest.update(b"jackal-hermes-runtime-bundle-v2\0")
        for logical in sorted(runtime_files):
            selected = plugin / runtime_files[logical][0]
            name = logical.encode("utf-8")
            data = selected.read_bytes()
            digest.update(
                str(len(name)).encode("ascii")
                + b":"
                + name
                + b"\0"
                + str(len(data)).encode("ascii")
                + b":"
                + data
                + b"\0"
            )
        return catalog_digest, digest.hexdigest()

    def _write_synthetic_outer_manifest(
        self, root: Path, catalog_digest: str
    ) -> str:
        for index, relative in enumerate(package_v180.REQUIRED_OUTER_PATHS):
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            if relative == package_v180.CATALOG_PATH:
                if not path.exists():
                    path.write_bytes(b"synthetic catalog bytes\n")
            elif relative == package_v180.OUTER_VERIFIER_PATH:
                path.write_text(
                    "#!/usr/bin/env python3\n"
                    "print('NAVIER_STOKES_RELEASE_VERIFY=PASS manifest_sha256=test artifacts=1 total_artifact_bytes=1')\n",
                    encoding="utf-8",
                )
            elif not path.exists():
                path.write_bytes(f"outer artifact {index}: {relative}\n".encode("utf-8"))

        artifacts = []
        for index, relative in enumerate(sorted(package_v180.REQUIRED_OUTER_PATHS)):
            data = (root / relative).read_bytes()
            artifacts.append(
                {
                    "artifact_id": f"artifact.{index}",
                    "path": relative,
                    "role": "release_artifact",
                    "sha256": hashlib.sha256(data).hexdigest(),
                    "size_bytes": len(data),
                }
            )
        manifest = {
            "artifacts": artifacts,
            "claim_boundary": {
                "assurance_ceiling": "bounded",
                "global_claims_admitted": False,
                "permanent_nonclaims": list(package_v180.PERMANENT_NONCLAIMS),
            },
            "pack_id": "navier_stokes_v1",
            "pack_version": "1.0.0",
            "platform": "macos-arm64",
            "schema": "jackal-navier-stokes-release-manifest-v1",
        }
        raw = package_v180.canonical_json_bytes(manifest)
        outer = root / package_v180.OUTER_MANIFEST_PATH
        outer.parent.mkdir(parents=True, exist_ok=True)
        outer.write_bytes(raw)
        return hashlib.sha256(raw).hexdigest()

    def test_successor_builder_and_dedicated_workflow_exist(self) -> None:
        self.assertTrue(BUILDER.is_file())
        self.assertTrue(WORKFLOW.is_file())

    def test_builder_exposes_fail_closed_preflight_and_package_api(self) -> None:
        self.assertTrue(hasattr(package_v180, "PackageRefusal"))
        self.assertTrue(hasattr(package_v180, "ArtifactAuthority"))
        self.assertTrue(callable(getattr(package_v180, "verify_catalog_authority", None)))
        self.assertTrue(callable(getattr(package_v180, "verify_compiler_authority", None)))
        self.assertTrue(callable(getattr(package_v180, "preflight", None)))
        self.assertTrue(callable(getattr(package_v180, "build_package", None)))
        self.assertTrue(callable(getattr(package_v180, "main", None)))

    def test_workflow_separates_hosted_static_checks_from_self_hosted_authority(self) -> None:
        workflow = WORKFLOW.read_text(encoding="utf-8")
        required_fragments = (
            "pull_request:",
            "workflow_dispatch:",
            "expected_catalog_sha256:",
            "expected_bundle_sha256:",
            "expected_outer_manifest_sha256:",
            "hosted-static-contract:",
            "runs-on: macos-14",
            "self-hosted-authoritative:",
            "runs-on: [self-hosted, macOS, ARM64, jackal-anubis-a733565f237d]",
            "if: github.event_name == 'workflow_dispatch'",
            "release/build_package_v180_navier.py preflight",
            "release/build_package_v180_navier.py build",
            "--expected-catalog-sha256",
            "--expected-bundle-sha256",
            "--expected-outer-manifest-sha256",
            "Verify the packaged caller-pinned runtime gate",
            "jackal-navier-stokes-v1.8",
            "--expected-package-index-sha256",
            "preflight",
        )
        for fragment in required_fragments:
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, workflow)
        hosted = workflow.split("hosted-static-contract:", 1)[1].split(
            "self-hosted-authoritative:", 1
        )[0]
        self.assertIn("tests/navier_stokes_package_v180_test.py", hosted)
        self.assertNotIn("build_package_v180_navier.py build", hosted)
        self.assertNotIn("anubis-a733565f237d", hosted)
        self.assertNotIn("release/build_package_v170.sh", workflow)
        self.assertIn("JACKAL_NAVIER_EXPECTED_CATALOG_SHA256", workflow)
        self.assertIn("JACKAL_NAVIER_EXPECTED_BUNDLE_SHA256", workflow)
        self.assertIn("JACKAL_NAVIER_EXPECTED_OUTER_MANIFEST_SHA256", workflow)
        self.assertNotIn("--expected-catalog-sha256 '${{", workflow)
        self.assertNotIn("--expected-bundle-sha256 '${{", workflow)
        self.assertNotIn("--expected-outer-manifest-sha256 '${{", workflow)

    def test_cli_requires_all_three_external_pins_and_refuses_malformed_digest(self) -> None:
        missing = subprocess.run(
            [sys.executable, "-B", str(BUILDER), "preflight", "--root", str(ROOT)],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
        self.assertEqual(missing.returncode, 2)
        self.assertNotIn("Traceback", missing.stderr)

        malformed = subprocess.run(
            [
                sys.executable,
                "-B",
                str(BUILDER),
                "preflight",
                "--root",
                str(ROOT),
                "--expected-catalog-sha256",
                "A" * 64,
                "--expected-bundle-sha256",
                "b" * 64,
                "--expected-outer-manifest-sha256",
                "c" * 64,
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
        self.assertEqual(malformed.returncode, 1)
        self.assertEqual(malformed.stdout, "")
        self.assertRegex(
            malformed.stderr,
            r"^NAVIER_V180_PACKAGE_PREFLIGHT=REFUSED reason=expected_digest_invalid detail=[^\n]+\n$",
        )
        self.assertNotIn("Traceback", malformed.stderr)

    def test_catalog_authority_binds_catalog_and_all_resolved_runtime_bytes(self) -> None:
        with tempfile.TemporaryDirectory(prefix="navier-v180-catalog-") as temporary:
            root = Path(temporary)
            catalog_digest, bundle_digest = self._write_synthetic_catalog(root)

            observed, runtime_files = package_v180.verify_catalog_authority(
                root,
                catalog_digest,
                bundle_digest,
            )
            self.assertEqual(observed, bundle_digest)
            self.assertEqual(
                {logical for logical, unused_path in runtime_files},
                {
                    "plugin/bundle_hash.py",
                    "plugin/jackal_hermes",
                    "plugin/server.py",
                    "plugin/tools.json",
                    *package_v180.REQUIRED_NAVIER_RUNTIME_FILES,
                },
            )

            changed = root / "tools/navier_stokes_certificate_producer.py"
            changed.write_bytes(b"changed after caller pin\n")
            with self.assertRaises(package_v180.PackageRefusal) as raised:
                package_v180.verify_catalog_authority(
                    root,
                    catalog_digest,
                    bundle_digest,
                )
            self.assertEqual(raised.exception.reason, "bundle_identity_mismatch")

    def test_compiler_authority_uses_exact_manifest_locator_digest_size_and_mode(self) -> None:
        with tempfile.TemporaryDirectory(prefix="navier-v180-compiler-") as temporary:
            root = Path(temporary) / "repo"
            account_home = Path(temporary) / "account"
            compiler_relative = "Library/Application Support/JACKAL/anubis-pins/anubis-test"
            compiler = account_home / compiler_relative
            compiler.parent.mkdir(parents=True)
            compiler_bytes = b"synthetic exact Anubis authority\n"
            compiler.write_bytes(compiler_bytes)
            compiler.chmod(0o555)
            compiler_sha256 = hashlib.sha256(compiler_bytes).hexdigest()
            manifest = {
                "schema": "jackal-domain-pack-manifest-v1",
                "pack_id": "navier_stokes_v1",
                "pack_version": "1.0.0",
                "platform": {
                    "os": "macos",
                    "architecture": "arm64",
                    "authoritative_language": "anubis",
                    "anubis_binary_locator_id": "test-locator",
                    "anubis_binary_relative_candidates": [compiler_relative],
                    "anubis_binary_sha256": compiler_sha256,
                    "anubis_binary_size_bytes": len(compiler_bytes),
                    "anubis_binary_required_mode": "0555",
                    "anubis_execution_binding": "descriptor_snapshot_v1",
                },
            }
            pack = root / package_v180.PACK_MANIFEST_PATH
            pack.parent.mkdir(parents=True)
            pack.write_bytes(package_v180.canonical_json_bytes(manifest))

            patch_values = {
                "ANUBIS_LOCATOR_ID": "test-locator",
                "ANUBIS_RELATIVE_CANDIDATES": (compiler_relative,),
                "ANUBIS_SHA256": compiler_sha256,
                "ANUBIS_SIZE_BYTES": len(compiler_bytes),
            }
            with mock.patch.multiple(package_v180, **patch_values):
                locator, digest, selected = package_v180.verify_compiler_authority(
                    root,
                    account_home=account_home,
                    enforce_host=False,
                )
                self.assertEqual(locator, "test-locator")
                self.assertEqual(digest, compiler_sha256)
                self.assertEqual(selected, compiler)

                compiler.chmod(0o755)
                with self.assertRaises(package_v180.PackageRefusal) as raised:
                    package_v180.verify_compiler_authority(
                        root,
                        account_home=account_home,
                        enforce_host=False,
                    )
                self.assertEqual(raised.exception.reason, "compiler_mode_invalid")

                compiler.chmod(0o755)
                compiler.write_bytes(b"different compiler authority bytes\n")
                compiler.chmod(0o555)
                with self.assertRaises(package_v180.PackageRefusal) as raised:
                    package_v180.verify_compiler_authority(
                        root,
                        account_home=account_home,
                        enforce_host=False,
                    )
                self.assertIn(
                    raised.exception.reason,
                    {"compiler_size_mismatch", "compiler_identity_mismatch"},
                )

    def test_outer_manifest_is_caller_pinned_and_independently_replayed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="navier-v180-outer-") as temporary:
            root = Path(temporary)
            catalog = root / package_v180.CATALOG_PATH
            catalog.parent.mkdir(parents=True)
            catalog.write_bytes(b"synthetic catalog bytes\n")
            catalog_digest = hashlib.sha256(catalog.read_bytes()).hexdigest()
            outer_digest = self._write_synthetic_outer_manifest(root, catalog_digest)

            observed = package_v180._verify_outer_manifest(
                root,
                outer_digest,
                catalog_digest,
            )
            self.assertEqual(observed, outer_digest)

            server = root / "plugin/hermes/server.py"
            original = server.read_bytes()
            server.write_bytes(bytes([original[0] ^ 1]) + original[1:])
            with self.assertRaises(package_v180.PackageRefusal) as raised:
                package_v180._verify_outer_manifest(
                    root,
                    outer_digest,
                    catalog_digest,
                )
            self.assertEqual(raised.exception.reason, "outer_artifact_digest_mismatch")

    def test_preflight_composes_outer_catalog_and_exact_compiler_authorities(self) -> None:
        with tempfile.TemporaryDirectory(prefix="navier-v180-preflight-") as temporary:
            root = Path(temporary) / "repo"
            account_home = Path(temporary) / "account"
            catalog_digest, bundle_digest = self._write_synthetic_catalog(root)
            compiler_relative = "anubis-lang/vm/pins/anubis-test"
            compiler = account_home / compiler_relative
            compiler.parent.mkdir(parents=True)
            compiler_bytes = b"preflight exact Anubis authority\n"
            compiler.write_bytes(compiler_bytes)
            compiler.chmod(0o555)
            compiler_digest = hashlib.sha256(compiler_bytes).hexdigest()
            pack_manifest = {
                "schema": "jackal-domain-pack-manifest-v1",
                "pack_id": "navier_stokes_v1",
                "pack_version": "1.0.0",
                "platform": {
                    "os": "macos",
                    "architecture": "arm64",
                    "authoritative_language": "anubis",
                    "anubis_binary_locator_id": "preflight-test-locator",
                    "anubis_binary_relative_candidates": [compiler_relative],
                    "anubis_binary_sha256": compiler_digest,
                    "anubis_binary_size_bytes": len(compiler_bytes),
                    "anubis_binary_required_mode": "0555",
                    "anubis_execution_binding": "descriptor_snapshot_v1",
                },
            }
            pack_path = root / package_v180.PACK_MANIFEST_PATH
            pack_path.parent.mkdir(parents=True, exist_ok=True)
            pack_path.write_bytes(package_v180.canonical_json_bytes(pack_manifest))
            catalog_value = json.loads((root / package_v180.CATALOG_PATH).read_bytes())
            bundle = hashlib.sha256()
            bundle.update(b"jackal-hermes-runtime-bundle-v2\0")
            for logical in sorted(catalog_value["runtime_files"]):
                candidate = catalog_value["runtime_files"][logical][0]
                selected = root / package_v180._normalize_candidate(
                    "plugin/hermes", candidate
                )
                name = logical.encode("utf-8")
                data = selected.read_bytes()
                bundle.update(
                    str(len(name)).encode("ascii")
                    + b":"
                    + name
                    + b"\0"
                    + str(len(data)).encode("ascii")
                    + b":"
                    + data
                    + b"\0"
                )
            bundle_digest = bundle.hexdigest()
            outer_digest = self._write_synthetic_outer_manifest(root, catalog_digest)

            with mock.patch.multiple(
                package_v180,
                ANUBIS_LOCATOR_ID="preflight-test-locator",
                ANUBIS_RELATIVE_CANDIDATES=(compiler_relative,),
                ANUBIS_SHA256=compiler_digest,
                ANUBIS_SIZE_BYTES=len(compiler_bytes),
            ):
                authority = package_v180.preflight(
                    root,
                    expected_catalog_sha256=catalog_digest,
                    expected_bundle_sha256=bundle_digest,
                    expected_outer_manifest_sha256=outer_digest,
                    account_home=account_home,
                    enforce_host=False,
                )
                package = package_v180.build_package(
                    root,
                    root / "release/dist/jackal-v1.8.0-navier-macos-arm64-test",
                    authority,
                )
                index_raw = (package / "SHA256SUMS").read_bytes()
                index_digest = hashlib.sha256(index_raw).hexdigest()
                second_package = package_v180.build_package(
                    root,
                    root / "release/dist/jackal-v1.8.0-navier-macos-arm64-test-2",
                    authority,
                )
                self.assertEqual(
                    (second_package / "SHA256SUMS").read_bytes(),
                    index_raw,
                )
                verified = package_v180.verify_package_authority(
                    package,
                    index_digest,
                    account_home=account_home,
                    enforce_host=False,
                )
                self.assertEqual(verified.outer_manifest_sha256, outer_digest)
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    gate_rc = package_v180.main(
                        [
                            "package-gate",
                            "--package-root",
                            str(package),
                            "--expected-package-index-sha256",
                            index_digest,
                            "preflight",
                        ],
                        account_home=account_home,
                        enforce_host=False,
                    )
                self.assertEqual(gate_rc, 0)
                self.assertRegex(
                    output.getvalue(),
                    r"^NAVIER_V180_PACKAGE_GATE=PASS action=preflight .+\n$",
                )
            self.assertIsInstance(authority, package_v180.ArtifactAuthority)
            self.assertEqual(authority.catalog_sha256, catalog_digest)
            self.assertEqual(authority.bundle_sha256, bundle_digest)
            self.assertEqual(authority.outer_manifest_sha256, outer_digest)
            self.assertEqual(authority.compiler_sha256, compiler_digest)
            self.assertEqual(authority.compiler_path, compiler)
            self.assertTrue((package / "NAVIER_V180_PACKAGE.json").is_file())
            self.assertTrue((package / "SHA256SUMS").is_file())
            wrapper = package / "jackal-navier-stokes-v1.8"
            self.assertTrue(wrapper.is_file())
            self.assertEqual(wrapper.stat().st_mode & 0o777, 0o555)
            self.assertIn("package-gate", wrapper.read_text(encoding="utf-8"))
            metadata = json.loads((package / "NAVIER_V180_PACKAGE.json").read_bytes())
            self.assertNotIn(str(account_home), json.dumps(metadata))
            self.assertEqual(
                metadata["authority"]["compiler_locator_id"],
                "preflight-test-locator",
            )

            server = package / "plugin/hermes/server.py"
            original = server.read_bytes()
            server.chmod(0o644)
            server.write_bytes(bytes([original[0] ^ 1]) + original[1:])
            with self.assertRaises(package_v180.PackageRefusal) as raised:
                with mock.patch.multiple(
                    package_v180,
                    ANUBIS_LOCATOR_ID="preflight-test-locator",
                    ANUBIS_RELATIVE_CANDIDATES=(compiler_relative,),
                    ANUBIS_SHA256=compiler_digest,
                    ANUBIS_SIZE_BYTES=len(compiler_bytes),
                ):
                    package_v180.verify_package_authority(
                        package,
                        index_digest,
                        account_home=account_home,
                        enforce_host=False,
                    )
            self.assertEqual(raised.exception.reason, "package_file_digest_mismatch")


if __name__ == "__main__":
    unittest.main(verbosity=2)
