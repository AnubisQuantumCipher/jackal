#!/usr/bin/env python3
"""Build and verify caller-pinned Navier--Stokes outer release manifests."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import errno
import os
import re
import stat
import sys
import tempfile
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


MANIFEST_SCHEMA = "jackal-navier-stokes-release-manifest-v1"
PACK_ID = "navier_stokes_v1"
PACK_VERSION = "1.0.0"
PLATFORM = "macos-arm64"
PERMANENT_NONCLAIMS = (
    "finite_scopes_do_not_close_future_time_or_continuum_quantifiers",
    "not_global_regular",
    "not_millennium_solved",
    "not_smooth_for_all_time",
    "ratio_alert_not_evidence_of_singularity",
)
FINAL_MANIFEST_PATH = "release/evidence/navier_stokes_release_manifest.json"
FORBIDDEN_GENERATED_PATH = "out/navier_stokes_v1.mono.json"
MAX_MANIFEST_BYTES = 512 * 1024
MAX_ARTIFACTS = 256
MAX_ARTIFACT_FILE_BYTES = 64 * 1024 * 1024
MAX_ARTIFACT_TOTAL_BYTES = 256 * 1024 * 1024
MAX_ARTIFACT_PATH_BYTES = 4096
MAX_ARTIFACT_PATH_DEPTH = 32
_HEX64 = re.compile(r"[0-9a-f]{64}", re.ASCII)
_TOKEN = re.compile(r"[a-z0-9][a-z0-9._-]{0,127}", re.ASCII)
_TOP_LEVEL_KEYS = {
    "artifacts",
    "claim_boundary",
    "pack_id",
    "pack_version",
    "platform",
    "schema",
}
_CLAIM_KEYS = {
    "assurance_ceiling",
    "global_claims_admitted",
    "permanent_nonclaims",
}
_ARTIFACT_KEYS = {"artifact_id", "path", "role", "sha256", "size_bytes"}


class ManifestRefusal(ValueError):
    """A stable fail-closed outer-manifest refusal."""

    def __init__(self, reason: str, detail: str = "") -> None:
        self.reason = reason
        self.detail = " ".join(str(detail).splitlines()).strip()[:240]
        message = reason if not self.detail else f"{reason}:{self.detail}"
        super().__init__(message)


@dataclass(frozen=True)
class ArtifactSpec:
    artifact_id: str
    role: str
    path: str


_FIXTURE_IDS = (
    "gate_a_zero_bounded",
    "gate_b_ratio_eq_one_arithmetic_only",
    "gate_b_ratio_gt_one_alert",
    "gate_b_ratio_lt_one_arithmetic_only",
    "gate_c_bkm_euler_refused",
    "gate_c_kato_ponce_disabled",
    "gate_d_ess_endpoint_preconditions_unverified",
    "gate_s_zero_bounded",
)

REQUIRED_ARTIFACTS = tuple(
    sorted(
        (
            ArtifactSpec(
                "ci.macos_arm64",
                "ci_workflow",
                ".github/workflows/navier-stokes-macos-arm64.yml",
            ),
            ArtifactSpec(
                "plan.navier_verification",
                "implementation_plan",
                "docs/superpowers/plans/2026-08-17-jackal-navier-stokes-verification-report.md",
            ),
            ArtifactSpec(
                "core.spec",
                "verification_spec",
                "domain_packs/pde/NAVIER_STOKES_VERIFICATION_SPEC.md",
            ),
            ArtifactSpec(
                "core.proof_object.zero",
                "proof_object",
                "domain_packs/pde/certificates/JACKAL_T3_ZERO_PROOF_OBJECT_V1.txt",
            ),
            ArtifactSpec(
                "core.identity.zero",
                "theorem_identity",
                "domain_packs/pde/identities/JACKAL_T3_ZERO_SOLUTION_IDENTITY_V1.txt",
            ),
            ArtifactSpec(
                "core.anubis_source",
                "authoritative_anubis_source",
                "domain_packs/pde/navier_stokes_v1.anb",
            ),
            ArtifactSpec(
                "core.pack_manifest",
                "pack_manifest",
                "domain_packs/pde/navier_stokes_v1.json",
            ),
            ArtifactSpec(
                "core.representation.zero",
                "field_representation",
                "domain_packs/pde/representations/T3_ZERO_FOURIER_FIELD_V1.txt",
            ),
            ArtifactSpec(
                "theorem.ccrt2007.source",
                "archived_primary_source",
                "domain_packs/pde/sources/CCRT2007_COROLLARY_5_T3_APOSTERIORI.pdf",
            ),
            ArtifactSpec(
                "theorem.ess2003.source",
                "archived_primary_source",
                "domain_packs/pde/sources/ESS2003_R3_REGULARITY.pdf",
            ),
            ArtifactSpec(
                "evidence.claim_audit",
                "claim_audit",
                "release/evidence/navier_stokes_claim_audit.json",
            ),
            ArtifactSpec(
                "fixture.builder",
                "fixture_builder",
                "release/evidence/navier_stokes_fixture_receipts/build_fixtures.py",
            ),
            ArtifactSpec(
                "fixture.index",
                "fixture_index",
                "release/evidence/navier_stokes_fixture_receipts/index.json",
            ),
            ArtifactSpec(
                "evidence.report_crosswalk",
                "report_crosswalk",
                "release/evidence/navier_stokes_report_crosswalk.json",
            ),
            ArtifactSpec(
                "evidence.semantic_mutations",
                "semantic_mutation_evidence",
                "release/evidence/navier_stokes_semantic_mutations.json",
            ),
            ArtifactSpec(
                "plugin.readme",
                "plugin_documentation",
                "plugin/hermes/README.md",
            ),
            ArtifactSpec(
                "plugin.bundle_hash",
                "plugin_identity_tool",
                "plugin/hermes/bundle_hash.py",
            ),
            ArtifactSpec(
                "plugin.entrypoint",
                "plugin_entrypoint",
                "plugin/hermes/jackal_hermes",
            ),
            ArtifactSpec(
                "plugin.server",
                "plugin_server",
                "plugin/hermes/server.py",
            ),
            ArtifactSpec(
                "plugin.catalog",
                "plugin_catalog",
                "plugin/hermes/tools.json",
            ),
            ArtifactSpec(
                "package.builder_v180",
                "package_builder",
                "release/build_package_v180_navier.py",
            ),
            ArtifactSpec(
                "test.package_v180",
                "test",
                "tests/navier_stokes_package_v180_test.py",
            ),
            ArtifactSpec(
                "test.plugin_bundle_identity",
                "test",
                "tests/plugin_bundle_identity_test.py",
            ),
            ArtifactSpec(
                "test.plugin_smoke",
                "test",
                "tests/plugin_smoke.py",
            ),
            ArtifactSpec(
                "test.gates",
                "test",
                "tests/navier_stokes_gate_test.py",
            ),
            ArtifactSpec(
                "test.release_blockers",
                "test",
                "tests/navier_stokes_release_blockers_test.py",
            ),
            ArtifactSpec(
                "test.release_manifest",
                "test",
                "tests/navier_stokes_release_manifest_test.py",
            ),
            ArtifactSpec(
                "test.report_crosscheck",
                "test",
                "tests/navier_stokes_report_crosscheck.py",
            ),
            ArtifactSpec(
                "test.semantic_mutations",
                "mutation_harness",
                "tests/navier_stokes_semantic_mutations.py",
            ),
            ArtifactSpec(
                "tool.producer",
                "untrusted_producer",
                "tools/navier_stokes_certificate_producer.py",
            ),
            ArtifactSpec(
                "tool.receipt_verifier",
                "independent_receipt_verifier",
                "tools/navier_stokes_receipt_verify.py",
            ),
            ArtifactSpec(
                "tool.release_verifier",
                "outer_release_verifier",
                "tools/navier_stokes_release_verify.py",
            ),
            *(
                ArtifactSpec(
                    f"fixture.{fixture_id}.request",
                    "fixture_request",
                    "release/evidence/navier_stokes_fixture_receipts/requests/"
                    f"{fixture_id}.json",
                )
                for fixture_id in _FIXTURE_IDS
            ),
            *(
                ArtifactSpec(
                    f"fixture.{fixture_id}.receipt",
                    "fixture_receipt",
                    "release/evidence/navier_stokes_fixture_receipts/receipts/"
                    f"{fixture_id}.json",
                )
                for fixture_id in _FIXTURE_IDS
            ),
        ),
        key=lambda item: item.path,
    )
)


def canonical_json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _validate_artifact_path(path: Any) -> str:
    if not isinstance(path, str) or not path or path.startswith("/") or "\\" in path:
        raise ManifestRefusal("artifact_path_invalid")
    parts = path.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise ManifestRefusal("artifact_path_invalid")
    if any(ord(character) < 32 or ord(character) == 127 for character in path):
        raise ManifestRefusal("artifact_path_invalid")
    try:
        encoded = path.encode("utf-8")
    except UnicodeEncodeError as error:
        raise ManifestRefusal("artifact_path_invalid") from error
    if len(encoded) > MAX_ARTIFACT_PATH_BYTES or len(parts) > MAX_ARTIFACT_PATH_DEPTH:
        raise ManifestRefusal("artifact_path_invalid")
    if path == FINAL_MANIFEST_PATH:
        raise ManifestRefusal("manifest_self_reference")
    if path == FORBIDDEN_GENERATED_PATH:
        raise ManifestRefusal("forbidden_generated_artifact")
    return path


def _validate_token(value: Any, reason: str) -> str:
    if not isinstance(value, str) or _TOKEN.fullmatch(value) is None:
        raise ManifestRefusal(reason)
    return value


def _register_path_aliases(
    path: str, aliases: dict[str, str]
) -> None:
    canonical: list[str] = []
    original: list[str] = []
    for part in path.split("/"):
        canonical.append(unicodedata.normalize("NFD", part).casefold())
        original.append(part)
        key = "/".join(canonical)
        presented = "/".join(original)
        prior = aliases.get(key)
        if prior is not None and prior != presented:
            raise ManifestRefusal("artifact_path_alias_collision")
        aliases[key] = presented


def _validate_specs(
    artifact_specs: Iterable[ArtifactSpec], *, require_sorted: bool
) -> tuple[ArtifactSpec, ...]:
    try:
        specs = tuple(artifact_specs)
    except TypeError as error:
        raise ManifestRefusal("artifact_inventory_invalid") from error
    if not specs or len(specs) > MAX_ARTIFACTS:
        raise ManifestRefusal("artifact_inventory_invalid")
    paths: set[str] = set()
    artifact_ids: set[str] = set()
    aliases: dict[str, str] = {}
    prior_path: str | None = None
    for spec in specs:
        if not isinstance(spec, ArtifactSpec):
            raise ManifestRefusal("artifact_inventory_invalid")
        _validate_token(spec.artifact_id, "artifact_id_invalid")
        _validate_token(spec.role, "artifact_role_invalid")
        path = _validate_artifact_path(spec.path)
        if path in paths:
            raise ManifestRefusal("artifact_path_duplicate")
        if spec.artifact_id in artifact_ids:
            raise ManifestRefusal("artifact_id_duplicate")
        _register_path_aliases(path, aliases)
        if require_sorted and prior_path is not None and path <= prior_path:
            raise ManifestRefusal("artifact_order_invalid")
        prior_path = path
        paths.add(path)
        artifact_ids.add(spec.artifact_id)
    return specs


def _open_flags(*, directory: bool = False) -> int:
    flags = os.O_RDONLY | os.O_NONBLOCK
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    if directory and hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    return flags


def _stable_signature(info: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (
        info.st_dev,
        info.st_ino,
        info.st_mode,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )


def _open_root(root: Path | str) -> int:
    try:
        descriptor = os.open(os.fspath(root), _open_flags(directory=True))
    except OSError as error:
        raise ManifestRefusal("artifact_root_unavailable") from error
    if not stat.S_ISDIR(os.fstat(descriptor).st_mode):
        os.close(descriptor)
        raise ManifestRefusal("artifact_root_unavailable")
    return descriptor


def _open_artifact_at(root_fd: int, path: str) -> int:
    descriptor = os.dup(root_fd)
    try:
        parts = path.split("/")
        for index, part in enumerate(parts):
            try:
                next_descriptor = os.open(
                    part,
                    _open_flags(directory=index < len(parts) - 1),
                    dir_fd=descriptor,
                )
            except OSError as error:
                if error.errno == errno.ELOOP:
                    raise ManifestRefusal("artifact_symlink", path) from error
                raise ManifestRefusal("artifact_unavailable", path) from error
            os.close(descriptor)
            descriptor = next_descriptor
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ManifestRefusal("artifact_nonregular", path)
        return descriptor
    except Exception:
        try:
            os.close(descriptor)
        except OSError:
            pass
        raise


def _entry_exists_at(root_fd: int, path: str) -> bool:
    descriptor = os.dup(root_fd)
    try:
        parts = path.split("/")
        for part in parts[:-1]:
            try:
                next_descriptor = os.open(
                    part, _open_flags(directory=True), dir_fd=descriptor
                )
            except FileNotFoundError:
                return False
            except OSError as error:
                raise ManifestRefusal(
                    "forbidden_generated_artifact_present", path
                ) from error
            os.close(descriptor)
            descriptor = next_descriptor
        try:
            os.stat(parts[-1], dir_fd=descriptor, follow_symlinks=False)
        except FileNotFoundError:
            return False
        except OSError as error:
            raise ManifestRefusal(
                "forbidden_generated_artifact_present", path
            ) from error
        return True
    finally:
        os.close(descriptor)


def _require_artifact_path_identity(
    root_fd: int, path: str, expected: os.stat_result
) -> None:
    descriptor = _open_artifact_at(root_fd, path)
    try:
        current = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    if _stable_signature(current) != _stable_signature(expected):
        raise ManifestRefusal("artifact_changed_during_read", path)


def _hash_artifact_at(
    root_fd: int, path: str, *, byte_limit: int
) -> tuple[str, int]:
    descriptor = _open_artifact_at(root_fd, path)
    try:
        before = os.fstat(descriptor)
        if before.st_size > byte_limit:
            raise ManifestRefusal("artifact_resource_limit", path)
        digest = hashlib.sha256()
        count = 0
        while True:
            chunk = os.read(descriptor, min(64 * 1024, byte_limit - count + 1))
            if not chunk:
                break
            count += len(chunk)
            if count > byte_limit:
                raise ManifestRefusal("artifact_resource_limit", path)
            digest.update(chunk)
        after = os.fstat(descriptor)
        if _stable_signature(before) != _stable_signature(after) or count != after.st_size:
            raise ManifestRefusal("artifact_changed_during_read", path)
    finally:
        os.close(descriptor)
    _require_artifact_path_identity(root_fd, path, after)
    return digest.hexdigest(), count


def _read_manifest_file(path: Path | str) -> bytes:
    try:
        descriptor = os.open(os.fspath(path), _open_flags())
    except OSError as error:
        if error.errno == errno.ELOOP:
            raise ManifestRefusal("manifest_symlink") from error
        raise ManifestRefusal("manifest_unavailable") from error
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise ManifestRefusal("manifest_nonregular")
        if before.st_size > MAX_MANIFEST_BYTES:
            raise ManifestRefusal("manifest_resource_limit")
        chunks: list[bytes] = []
        count = 0
        while True:
            chunk = os.read(descriptor, min(64 * 1024, MAX_MANIFEST_BYTES - count + 1))
            if not chunk:
                break
            count += len(chunk)
            if count > MAX_MANIFEST_BYTES:
                raise ManifestRefusal("manifest_resource_limit")
            chunks.append(chunk)
        after = os.fstat(descriptor)
        if _stable_signature(before) != _stable_signature(after) or count != after.st_size:
            raise ManifestRefusal("manifest_changed_during_read")
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _strict_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ManifestRefusal("manifest_duplicate_field", key)
        result[key] = value
    return result


def _parse_manifest(raw: bytes) -> dict[str, Any]:
    if not raw or not raw.endswith(b"\n"):
        raise ManifestRefusal("manifest_noncanonical")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ManifestRefusal("manifest_invalid_utf8") from error
    try:
        value = json.loads(
            text,
            object_pairs_hook=_strict_json_object,
            parse_constant=lambda unused: (_ for _ in ()).throw(
                ManifestRefusal("manifest_nonfinite_number")
            ),
        )
    except ManifestRefusal:
        raise
    except (json.JSONDecodeError, RecursionError) as error:
        raise ManifestRefusal("manifest_invalid_json") from error
    if not isinstance(value, dict):
        raise ManifestRefusal("manifest_schema_invalid")
    if raw != canonical_json_bytes(value):
        raise ManifestRefusal("manifest_noncanonical")
    return value


def _validated_manifest_specs(manifest: dict[str, Any]) -> tuple[ArtifactSpec, ...]:
    if set(manifest) != _TOP_LEVEL_KEYS:
        raise ManifestRefusal("manifest_schema_invalid")
    if (
        manifest.get("schema") != MANIFEST_SCHEMA
        or manifest.get("pack_id") != PACK_ID
        or manifest.get("pack_version") != PACK_VERSION
        or manifest.get("platform") != PLATFORM
    ):
        raise ManifestRefusal("manifest_schema_invalid")
    claim = manifest.get("claim_boundary")
    if not isinstance(claim, dict) or set(claim) != _CLAIM_KEYS:
        raise ManifestRefusal("manifest_schema_invalid")
    if (
        claim.get("assurance_ceiling") != "bounded"
        or claim.get("global_claims_admitted") is not False
        or claim.get("permanent_nonclaims") != list(PERMANENT_NONCLAIMS)
    ):
        raise ManifestRefusal("manifest_claim_boundary_invalid")
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts or len(artifacts) > MAX_ARTIFACTS:
        raise ManifestRefusal("artifact_inventory_invalid")
    specs: list[ArtifactSpec] = []
    for item in artifacts:
        if not isinstance(item, dict) or set(item) != _ARTIFACT_KEYS:
            raise ManifestRefusal("artifact_record_invalid")
        digest = item.get("sha256")
        size = item.get("size_bytes")
        if not isinstance(digest, str) or _HEX64.fullmatch(digest) is None:
            raise ManifestRefusal("artifact_digest_invalid")
        if (
            not isinstance(size, int)
            or isinstance(size, bool)
            or size <= 0
            or size > MAX_ARTIFACT_FILE_BYTES
        ):
            raise ManifestRefusal("artifact_size_invalid")
        specs.append(
            ArtifactSpec(
                artifact_id=item.get("artifact_id"),
                role=item.get("role"),
                path=item.get("path"),
            )
        )
    return _validate_specs(specs, require_sorted=True)


def build_manifest(
    root: Path | str,
    artifact_specs: Iterable[ArtifactSpec],
) -> dict[str, Any]:
    specs = _validate_specs(artifact_specs, require_sorted=False)
    artifacts = []
    root_fd = _open_root(root)
    try:
        if _entry_exists_at(root_fd, FORBIDDEN_GENERATED_PATH):
            raise ManifestRefusal(
                "forbidden_generated_artifact_present", FORBIDDEN_GENERATED_PATH
            )
        remaining = MAX_ARTIFACT_TOTAL_BYTES
        for spec in sorted(specs, key=lambda item: item.path):
            digest, size = _hash_artifact_at(
                root_fd,
                spec.path,
                byte_limit=min(MAX_ARTIFACT_FILE_BYTES, remaining),
            )
            if size == 0:
                raise ManifestRefusal("artifact_empty", spec.path)
            remaining -= size
            artifacts.append(
                {
                    "artifact_id": spec.artifact_id,
                    "path": spec.path,
                    "role": spec.role,
                    "sha256": digest,
                    "size_bytes": size,
                }
            )
    finally:
        os.close(root_fd)
    return {
        "artifacts": artifacts,
        "claim_boundary": {
            "assurance_ceiling": "bounded",
            "global_claims_admitted": False,
            "permanent_nonclaims": list(PERMANENT_NONCLAIMS),
        },
        "pack_id": PACK_ID,
        "pack_version": PACK_VERSION,
        "platform": PLATFORM,
        "schema": MANIFEST_SCHEMA,
    }


def verify_manifest(
    root: Path | str,
    manifest_path: Path | str,
    expected_manifest_sha256: str,
    required_artifact_specs: Iterable[ArtifactSpec],
) -> dict[str, Any]:
    if (
        not isinstance(expected_manifest_sha256, str)
        or _HEX64.fullmatch(expected_manifest_sha256) is None
    ):
        raise ManifestRefusal("expected_manifest_digest_invalid")
    raw = _read_manifest_file(manifest_path)
    actual_manifest_sha256 = hashlib.sha256(raw).hexdigest()
    if not hmac.compare_digest(actual_manifest_sha256, expected_manifest_sha256):
        raise ManifestRefusal("manifest_identity_mismatch")
    manifest = _parse_manifest(raw)
    observed_specs = _validated_manifest_specs(manifest)
    required_specs = _validate_specs(required_artifact_specs, require_sorted=False)
    required = {
        spec.path: (spec.artifact_id, spec.role) for spec in required_specs
    }
    observed = {
        spec.path: (spec.artifact_id, spec.role) for spec in observed_specs
    }
    if not required.items() <= observed.items():
        raise ManifestRefusal("required_artifact_missing")
    total = 0
    root_fd = _open_root(root)
    try:
        if _entry_exists_at(root_fd, FORBIDDEN_GENERATED_PATH):
            raise ManifestRefusal(
                "forbidden_generated_artifact_present", FORBIDDEN_GENERATED_PATH
            )
        remaining = MAX_ARTIFACT_TOTAL_BYTES
        for item in manifest["artifacts"]:
            digest, size = _hash_artifact_at(
                root_fd,
                item["path"],
                byte_limit=min(MAX_ARTIFACT_FILE_BYTES, remaining),
            )
            if size != item["size_bytes"]:
                raise ManifestRefusal("artifact_size_mismatch", item["path"])
            if not hmac.compare_digest(digest, item["sha256"]):
                raise ManifestRefusal("artifact_digest_mismatch", item["path"])
            remaining -= size
            total += size
    finally:
        os.close(root_fd)
    return {
        "artifact_count": len(manifest["artifacts"]),
        "manifest_sha256": actual_manifest_sha256,
        "total_artifact_bytes": total,
    }


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=path.parent,
            delete=False,
        ) as handle:
            temporary_name = handle.name
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary_name, 0o644)
        os.replace(temporary_name, path)
        temporary_name = None
    finally:
        if temporary_name is not None:
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass


def _argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build or verify the caller-pinned Navier-Stokes outer manifest."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build", help="build a deterministic manifest")
    build.add_argument("--root", required=True)
    build.add_argument("--out", required=True)
    build.add_argument(
        "--artifact",
        action="append",
        nargs=3,
        metavar=("ID", "ROLE", "PATH"),
        default=[],
        help="add one artifact to the constant required inventory",
    )
    verify = commands.add_parser("verify", help="verify a caller-pinned manifest")
    verify.add_argument("--root", required=True)
    verify.add_argument("--manifest", required=True)
    verify.add_argument("--expected-manifest-sha256", required=True)
    return parser


def _refusal_line(operation: str, error: ManifestRefusal) -> str:
    detail = error.detail or "verification refused"
    return (
        f"NAVIER_STOKES_RELEASE_{operation}=REFUSED "
        f"reason={error.reason} detail={detail}\n"
    )


def main(argv: list[str] | None = None) -> int:
    arguments = _argument_parser().parse_args(argv)
    try:
        if arguments.command == "build":
            extras = tuple(
                ArtifactSpec(artifact_id, role, path)
                for artifact_id, role, path in arguments.artifact
            )
            manifest = build_manifest(
                arguments.root,
                (*REQUIRED_ARTIFACTS, *extras),
            )
            raw = canonical_json_bytes(manifest)
            _atomic_write(Path(arguments.out), raw)
            digest = hashlib.sha256(raw).hexdigest()
            total = sum(item["size_bytes"] for item in manifest["artifacts"])
            print(
                "NAVIER_STOKES_RELEASE_MANIFEST_BUILD=PASS "
                f"manifest_sha256={digest} artifacts={len(manifest['artifacts'])} "
                f"total_artifact_bytes={total}"
            )
            return 0
        summary = verify_manifest(
            arguments.root,
            arguments.manifest,
            arguments.expected_manifest_sha256,
            REQUIRED_ARTIFACTS,
        )
        print(
            "NAVIER_STOKES_RELEASE_VERIFY=PASS "
            f"manifest_sha256={summary['manifest_sha256']} "
            f"artifacts={summary['artifact_count']} "
            f"total_artifact_bytes={summary['total_artifact_bytes']}"
        )
        return 0
    except ManifestRefusal as error:
        operation = "MANIFEST_BUILD" if arguments.command == "build" else "VERIFY"
        print(_refusal_line(operation, error), end="", file=sys.stderr)
        return 1
    except Exception:
        operation = "MANIFEST_BUILD" if arguments.command == "build" else "VERIFY"
        print(
            f"NAVIER_STOKES_RELEASE_{operation}=REFUSED "
            "reason=internal_error detail=unexpected_failure",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
