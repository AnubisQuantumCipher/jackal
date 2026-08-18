#!/usr/bin/env python3
"""Build the isolated JACKAL Navier v1.8 macOS-arm64 successor package."""

from __future__ import annotations

import argparse
import errno
import hashlib
import hmac
import json
import os
import platform
import pwd
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import unicodedata
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any


PACKAGE_VERSION = "1.8.0"
CATALOG_PATH = "plugin/hermes/tools.json"
BUNDLE_IDENTITY_SCHEMA = "jackal-hermes-runtime-bundle-v2"
OUTER_MANIFEST_PATH = "release/evidence/navier_stokes_release_manifest.json"
OUTER_VERIFIER_PATH = "tools/navier_stokes_release_verify.py"
PACK_MANIFEST_PATH = "domain_packs/pde/navier_stokes_v1.json"
ANUBIS_LOCATOR_ID = "macos-account-home-relative-v1:anubis-a733565f237d"
ANUBIS_RELATIVE_CANDIDATES = (
    "Library/Application Support/JACKAL/anubis-pins/anubis-a733565f237d",
    "anubis-lang/vm/pins/anubis-a733565f237d",
)
ANUBIS_SHA256 = "a733565f237df171e7cf93b9b37700a42d8713576818fd92f8cd23a8ad7a69e2"
ANUBIS_SIZE_BYTES = 99_415_712
ANUBIS_REQUIRED_MODE = 0o555
PERMANENT_NONCLAIMS = (
    "finite_scopes_do_not_close_future_time_or_continuum_quantifiers",
    "not_global_regular",
    "not_millennium_solved",
    "not_smooth_for_all_time",
    "ratio_alert_not_evidence_of_singularity",
)
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
REQUIRED_OUTER_PATHS = tuple(
    sorted(
        {
            ".github/workflows/navier-stokes-macos-arm64.yml",
            "domain_packs/pde/NAVIER_STOKES_VERIFICATION_SPEC.md",
            "domain_packs/pde/certificates/JACKAL_T3_ZERO_PROOF_OBJECT_V1.txt",
            "domain_packs/pde/identities/JACKAL_T3_ZERO_SOLUTION_IDENTITY_V1.txt",
            "domain_packs/pde/navier_stokes_v1.anb",
            "domain_packs/pde/navier_stokes_v1.json",
            "domain_packs/pde/representations/T3_ZERO_FOURIER_FIELD_V1.txt",
            "domain_packs/pde/sources/CCRT2007_COROLLARY_5_T3_APOSTERIORI.pdf",
            "domain_packs/pde/sources/ESS2003_R3_REGULARITY.pdf",
            "plugin/hermes/bundle_hash.py",
            "plugin/hermes/jackal_hermes",
            "plugin/hermes/server.py",
            CATALOG_PATH,
            "release/build_package_v180_navier.py",
            "release/evidence/navier_stokes_claim_audit.json",
            "release/evidence/navier_stokes_fixture_receipts/build_fixtures.py",
            "release/evidence/navier_stokes_fixture_receipts/index.json",
            "release/evidence/navier_stokes_report_crosswalk.json",
            "release/evidence/navier_stokes_semantic_mutations.json",
            "tests/navier_stokes_gate_test.py",
            "tests/navier_stokes_package_v180_test.py",
            "tests/navier_stokes_release_blockers_test.py",
            "tests/navier_stokes_release_manifest_test.py",
            "tests/navier_stokes_report_crosscheck.py",
            "tests/navier_stokes_semantic_mutations.py",
            "tools/navier_stokes_certificate_producer.py",
            "tools/navier_stokes_receipt_verify.py",
            OUTER_VERIFIER_PATH,
            *{
                "release/evidence/navier_stokes_fixture_receipts/requests/"
                f"{fixture_id}.json"
                for fixture_id in _FIXTURE_IDS
            },
            *{
                "release/evidence/navier_stokes_fixture_receipts/receipts/"
                f"{fixture_id}.json"
                for fixture_id in _FIXTURE_IDS
            },
        }
    )
)
REQUIRED_NAVIER_RUNTIME_FILES = (
    "runtime/domain_packs/pde/certificates/JACKAL_T3_ZERO_PROOF_OBJECT_V1.txt",
    "runtime/domain_packs/pde/identities/JACKAL_T3_ZERO_SOLUTION_IDENTITY_V1.txt",
    "runtime/domain_packs/pde/navier_stokes_v1.anb",
    "runtime/domain_packs/pde/navier_stokes_v1.json",
    "runtime/domain_packs/pde/representations/T3_ZERO_FOURIER_FIELD_V1.txt",
    "runtime/domain_packs/pde/sources/CCRT2007_COROLLARY_5_T3_APOSTERIORI.pdf",
    "runtime/domain_packs/pde/sources/ESS2003_R3_REGULARITY.pdf",
    "runtime/tools/navier_stokes_certificate_producer.py",
    "runtime/tools/navier_stokes_receipt_verify.py",
)
REQUIRED_PLUGIN_RUNTIME_FILES = (
    "plugin/bundle_hash.py",
    "plugin/jackal_hermes",
    "plugin/server.py",
    "plugin/tools.json",
)
MAX_CATALOG_BYTES = 2 * 1024 * 1024
MAX_RUNTIME_FILE_BYTES = 64 * 1024 * 1024
MAX_RUNTIME_TOTAL_BYTES = 256 * 1024 * 1024
_LOGICAL_NAME = re.compile(r"[A-Za-z0-9._/-]+", re.ASCII)


class PackageRefusal(RuntimeError):
    def __init__(self, reason: str, detail: str = "") -> None:
        self.reason = reason
        self.detail = " ".join(str(detail).splitlines()).strip()[:240]
        super().__init__(reason if not self.detail else f"{reason}:{self.detail}")


@dataclass(frozen=True)
class ArtifactAuthority:
    catalog_sha256: str
    bundle_sha256: str
    outer_manifest_sha256: str
    compiler_locator_id: str
    compiler_sha256: str
    compiler_path: Path
    runtime_files: tuple[tuple[str, Path], ...]


def verify_catalog_authority(
    root: Path | str,
    expected_catalog_sha256: str,
    expected_bundle_sha256: str,
) -> tuple[str, tuple[tuple[str, Path], ...]]:
    expected_catalog = _require_digest(
        expected_catalog_sha256, "expected_catalog_sha256"
    )
    expected_bundle = _require_digest(expected_bundle_sha256, "expected_bundle_sha256")
    root_path = _require_root(root)
    catalog_raw = _read_relative(
        root_path,
        CATALOG_PATH,
        byte_limit=MAX_CATALOG_BYTES,
        unavailable_reason="catalog_unavailable",
        unsafe_reason="catalog_unsafe",
    )
    catalog_digest = hashlib.sha256(catalog_raw).hexdigest()
    if not hmac.compare_digest(catalog_digest, expected_catalog):
        raise PackageRefusal("catalog_identity_mismatch")
    catalog = _parse_json_object(catalog_raw, "catalog")
    if (
        catalog.get("schema") != "jackal-hermes-plugin-v1"
        or catalog.get("bundle_identity_schema") != BUNDLE_IDENTITY_SCHEMA
    ):
        raise PackageRefusal("catalog_schema_invalid")

    declared = catalog.get("runtime_files")
    if not isinstance(declared, dict) or not declared:
        raise PackageRefusal("catalog_runtime_files_invalid")
    resolved: list[tuple[str, Path]] = []
    resolved_bytes: dict[str, bytes] = {}
    selected_relatives: dict[str, str] = {}
    remaining = MAX_RUNTIME_TOTAL_BYTES
    for logical_name in sorted(declared):
        if (
            not isinstance(logical_name, str)
            or _LOGICAL_NAME.fullmatch(logical_name) is None
            or logical_name.startswith("/")
            or ".." in PurePosixPath(logical_name).parts
        ):
            raise PackageRefusal("catalog_logical_name_invalid")
        candidates = declared[logical_name]
        if (
            not isinstance(candidates, list)
            or not candidates
            or any(not isinstance(candidate, str) or not candidate for candidate in candidates)
        ):
            raise PackageRefusal("catalog_runtime_candidates_invalid", logical_name)
        selected: tuple[str, bytes] | None = None
        for candidate in candidates:
            relative = _normalize_candidate("plugin/hermes", candidate)
            try:
                data = _read_relative(
                    root_path,
                    relative,
                    byte_limit=min(MAX_RUNTIME_FILE_BYTES, remaining),
                    unavailable_reason="runtime_file_unavailable",
                    unsafe_reason="runtime_file_unsafe",
                )
            except PackageRefusal as error:
                if error.reason == "runtime_file_unavailable":
                    continue
                raise
            selected = (relative, data)
            break
        if selected is None:
            raise PackageRefusal("runtime_file_missing", logical_name)
        relative, data = selected
        remaining -= len(data)
        if remaining < 0:
            raise PackageRefusal("runtime_total_limit")
        selected_relatives[logical_name] = relative
        resolved_bytes[logical_name] = data
        resolved.append((logical_name, root_path / relative))

    required = set(REQUIRED_PLUGIN_RUNTIME_FILES) | set(REQUIRED_NAVIER_RUNTIME_FILES)
    missing = sorted(required - set(resolved_bytes))
    if missing:
        raise PackageRefusal("required_runtime_file_missing", missing[0])
    _validate_bundle_files(catalog, selected_relatives)
    _validate_navier_tools(catalog)

    digest = hashlib.sha256()
    digest.update(BUNDLE_IDENTITY_SCHEMA.encode("ascii") + b"\0")
    for logical_name in sorted(resolved_bytes):
        digest.update(_framed(logical_name, resolved_bytes[logical_name]))
    observed_bundle = digest.hexdigest()
    if not hmac.compare_digest(observed_bundle, expected_bundle):
        raise PackageRefusal("bundle_identity_mismatch")
    return observed_bundle, tuple(resolved)


def verify_compiler_authority(
    root: Path | str,
    *,
    account_home: Path | str | None = None,
    enforce_host: bool = True,
) -> tuple[str, str, Path]:
    if enforce_host and (
        platform.system() != "Darwin" or platform.machine() != "arm64"
    ):
        raise PackageRefusal("host_platform_invalid", "requires macos arm64")
    root_path = _require_root(root)
    manifest_raw = _read_relative(
        root_path,
        PACK_MANIFEST_PATH,
        byte_limit=2 * 1024 * 1024,
        unavailable_reason="pack_manifest_unavailable",
        unsafe_reason="pack_manifest_unsafe",
    )
    manifest = _parse_json_object(manifest_raw, "pack_manifest")
    platform_record = manifest.get("platform")
    if (
        manifest.get("schema") != "jackal-domain-pack-manifest-v1"
        or manifest.get("pack_id") != "navier_stokes_v1"
        or manifest.get("pack_version") != "1.0.0"
        or not isinstance(platform_record, dict)
        or platform_record.get("os") != "macos"
        or platform_record.get("architecture") != "arm64"
        or platform_record.get("authoritative_language") != "anubis"
        or platform_record.get("anubis_binary_locator_id") != ANUBIS_LOCATOR_ID
        or platform_record.get("anubis_binary_relative_candidates")
        != list(ANUBIS_RELATIVE_CANDIDATES)
        or platform_record.get("anubis_binary_sha256") != ANUBIS_SHA256
        or platform_record.get("anubis_binary_size_bytes") != ANUBIS_SIZE_BYTES
        or platform_record.get("anubis_binary_required_mode") != "0555"
        or platform_record.get("anubis_execution_binding")
        != "descriptor_snapshot_v1"
    ):
        raise PackageRefusal("compiler_manifest_contract_invalid")

    if account_home is None:
        try:
            account_home = Path(pwd.getpwuid(os.getuid()).pw_dir)
        except (KeyError, OSError) as error:
            raise PackageRefusal("account_home_unavailable") from error
    home_path = _require_root(account_home)
    selected_path: Path | None = None
    selected_relative: str | None = None
    for relative in ANUBIS_RELATIVE_CANDIDATES:
        normalized = _normalize_relative(relative)
        candidate = home_path / normalized
        try:
            info = candidate.lstat()
        except FileNotFoundError:
            continue
        except OSError as error:
            raise PackageRefusal("compiler_unavailable", normalized) from error
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
            raise PackageRefusal("compiler_unsafe", normalized)
        selected_path = candidate
        selected_relative = normalized
        break
    if selected_path is None or selected_relative is None:
        raise PackageRefusal("compiler_unavailable", ANUBIS_LOCATOR_ID)

    info = selected_path.lstat()
    if stat.S_IMODE(info.st_mode) != ANUBIS_REQUIRED_MODE:
        raise PackageRefusal("compiler_mode_invalid", selected_relative)
    if info.st_size != ANUBIS_SIZE_BYTES:
        raise PackageRefusal("compiler_size_mismatch", selected_relative)
    compiler_bytes = _read_relative(
        home_path,
        selected_relative,
        byte_limit=ANUBIS_SIZE_BYTES,
        unavailable_reason="compiler_unavailable",
        unsafe_reason="compiler_unsafe",
    )
    observed = hashlib.sha256(compiler_bytes).hexdigest()
    if not hmac.compare_digest(observed, ANUBIS_SHA256):
        raise PackageRefusal("compiler_identity_mismatch")
    return ANUBIS_LOCATOR_ID, observed, selected_path


def preflight(
    root: Path | str,
    *,
    expected_catalog_sha256: str,
    expected_bundle_sha256: str,
    expected_outer_manifest_sha256: str,
    account_home: Path | str | None = None,
    enforce_host: bool = True,
) -> ArtifactAuthority | None:
    expected_catalog = _require_digest(
        expected_catalog_sha256, "expected_catalog_sha256"
    )
    expected_bundle = _require_digest(expected_bundle_sha256, "expected_bundle_sha256")
    expected_outer = _require_digest(
        expected_outer_manifest_sha256, "expected_outer_manifest_sha256"
    )
    root_path = _require_root(root)
    outer_digest = _verify_outer_manifest(
        root_path,
        expected_outer,
        expected_catalog,
    )
    bundle_digest, runtime_files = verify_catalog_authority(
        root_path,
        expected_catalog,
        expected_bundle,
    )
    locator_id, compiler_digest, compiler_path = verify_compiler_authority(
        root_path,
        account_home=account_home,
        enforce_host=enforce_host,
    )
    return ArtifactAuthority(
        catalog_sha256=expected_catalog,
        bundle_sha256=bundle_digest,
        outer_manifest_sha256=outer_digest,
        compiler_locator_id=locator_id,
        compiler_sha256=compiler_digest,
        compiler_path=compiler_path,
        runtime_files=runtime_files,
    )


def _verify_outer_manifest(
    root: Path | str,
    expected_outer_manifest_sha256: str,
    expected_catalog_sha256: str,
) -> str:
    expected_outer = _require_digest(
        expected_outer_manifest_sha256, "expected_outer_manifest_sha256"
    )
    expected_catalog = _require_digest(
        expected_catalog_sha256, "expected_catalog_sha256"
    )
    root_path = _require_root(root)
    raw = _read_relative(
        root_path,
        OUTER_MANIFEST_PATH,
        byte_limit=512 * 1024,
        unavailable_reason="outer_manifest_unavailable",
        unsafe_reason="outer_manifest_unsafe",
    )
    observed_outer = hashlib.sha256(raw).hexdigest()
    if not hmac.compare_digest(observed_outer, expected_outer):
        raise PackageRefusal("outer_manifest_identity_mismatch")
    manifest = _parse_json_object(raw, "outer_manifest")
    if raw != canonical_json_bytes(manifest):
        raise PackageRefusal("outer_manifest_noncanonical")
    if set(manifest) != {
        "artifacts",
        "claim_boundary",
        "pack_id",
        "pack_version",
        "platform",
        "schema",
    }:
        raise PackageRefusal("outer_manifest_schema_invalid")
    claim = manifest.get("claim_boundary")
    if (
        manifest.get("schema") != "jackal-navier-stokes-release-manifest-v1"
        or manifest.get("pack_id") != "navier_stokes_v1"
        or manifest.get("pack_version") != "1.0.0"
        or manifest.get("platform") != "macos-arm64"
        or not isinstance(claim, dict)
        or set(claim)
        != {"assurance_ceiling", "global_claims_admitted", "permanent_nonclaims"}
        or claim.get("assurance_ceiling") != "bounded"
        or claim.get("global_claims_admitted") is not False
        or claim.get("permanent_nonclaims") != list(PERMANENT_NONCLAIMS)
    ):
        raise PackageRefusal("outer_manifest_claim_contract_invalid")
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts or len(artifacts) > 256:
        raise PackageRefusal("outer_manifest_artifacts_invalid")
    token = re.compile(r"[a-z0-9][a-z0-9._-]{0,127}", re.ASCII)
    records: dict[str, dict[str, Any]] = {}
    aliases: set[str] = set()
    prior: str | None = None
    for record in artifacts:
        if not isinstance(record, dict) or set(record) != {
            "artifact_id",
            "path",
            "role",
            "sha256",
            "size_bytes",
        }:
            raise PackageRefusal("outer_artifact_record_invalid")
        path = _normalize_relative(record.get("path"))
        if path in (OUTER_MANIFEST_PATH, "out/navier_stokes_v1.mono.json"):
            raise PackageRefusal("outer_artifact_path_forbidden", path)
        alias = "/".join(
            unicodedata.normalize("NFD", part).casefold()
            for part in path.split("/")
        )
        if (
            prior is not None
            and path <= prior
            or path in records
            or alias in aliases
            or not isinstance(record.get("artifact_id"), str)
            or token.fullmatch(record["artifact_id"]) is None
            or not isinstance(record.get("role"), str)
            or token.fullmatch(record["role"]) is None
            or not isinstance(record.get("sha256"), str)
            or _HEX64.fullmatch(record["sha256"]) is None
            or not isinstance(record.get("size_bytes"), int)
            or isinstance(record.get("size_bytes"), bool)
            or record["size_bytes"] <= 0
            or record["size_bytes"] > 64 * 1024 * 1024
        ):
            raise PackageRefusal("outer_artifact_record_invalid", path)
        records[path] = record
        aliases.add(alias)
        prior = path
    missing = sorted(set(REQUIRED_OUTER_PATHS) - set(records))
    if missing:
        raise PackageRefusal("outer_required_artifact_missing", missing[0])
    if not hmac.compare_digest(records[CATALOG_PATH]["sha256"], expected_catalog):
        raise PackageRefusal("outer_catalog_pin_mismatch")

    remaining = 256 * 1024 * 1024
    for path, record in records.items():
        data = _read_relative(
            root_path,
            path,
            byte_limit=min(64 * 1024 * 1024, remaining),
            unavailable_reason="outer_artifact_unavailable",
            unsafe_reason="outer_artifact_unsafe",
        )
        if len(data) != record["size_bytes"]:
            raise PackageRefusal("outer_artifact_size_mismatch", path)
        if not hmac.compare_digest(hashlib.sha256(data).hexdigest(), record["sha256"]):
            raise PackageRefusal("outer_artifact_digest_mismatch", path)
        remaining -= len(data)
        if remaining < 0:
            raise PackageRefusal("outer_artifact_total_limit")

    verifier = root_path / OUTER_VERIFIER_PATH
    command = (
        sys.executable,
        "-I",
        "-S",
        "-B",
        os.fspath(verifier),
        "verify",
        "--root",
        os.fspath(root_path),
        "--manifest",
        os.fspath(root_path / OUTER_MANIFEST_PATH),
        "--expected-manifest-sha256",
        expected_outer,
    )
    try:
        with tempfile.TemporaryFile() as stdout_file, tempfile.TemporaryFile() as stderr_file:
            completed = subprocess.run(
                command,
                cwd=root_path,
                stdin=subprocess.DEVNULL,
                stdout=stdout_file,
                stderr=stderr_file,
                check=False,
                timeout=60,
                env={
                    "LANG": "C",
                    "LC_ALL": "C",
                    "PATH": os.defpath,
                    "PYTHONDONTWRITEBYTECODE": "1",
                },
            )
            stdout_size = stdout_file.tell()
            stderr_size = stderr_file.tell()
            if stdout_size > 64 * 1024 or stderr_size > 64 * 1024:
                raise PackageRefusal("outer_verifier_output_limit")
            stdout_file.seek(0)
            stderr_file.seek(0)
            stdout = stdout_file.read().decode("utf-8", errors="strict")
            stderr = stderr_file.read().decode("utf-8", errors="strict")
    except subprocess.TimeoutExpired as error:
        raise PackageRefusal("outer_verifier_timeout") from error
    except UnicodeDecodeError as error:
        raise PackageRefusal("outer_verifier_output_invalid") from error
    if (
        completed.returncode != 0
        or stderr
        or len(stdout.splitlines()) != 1
        or not stdout.startswith("NAVIER_STOKES_RELEASE_VERIFY=PASS ")
        or not stdout.endswith("\n")
    ):
        raise PackageRefusal("outer_verifier_rejected")
    return observed_outer


def build_package(
    root: Path | str,
    destination: Path | str,
    authority: ArtifactAuthority,
) -> Path | None:
    if not isinstance(authority, ArtifactAuthority):
        raise PackageRefusal("authority_invalid")
    root_path = _require_root(root)
    for value, label in (
        (authority.catalog_sha256, "catalog_sha256"),
        (authority.bundle_sha256, "bundle_sha256"),
        (authority.outer_manifest_sha256, "outer_manifest_sha256"),
        (authority.compiler_sha256, "compiler_sha256"),
    ):
        _require_digest(value, label)
    if (
        authority.compiler_locator_id != ANUBIS_LOCATOR_ID
        or authority.compiler_sha256 != ANUBIS_SHA256
    ):
        raise PackageRefusal("authority_compiler_mismatch")

    _verify_outer_manifest(
        root_path,
        authority.outer_manifest_sha256,
        authority.catalog_sha256,
    )
    bundle_digest, runtime_files = verify_catalog_authority(
        root_path,
        authority.catalog_sha256,
        authority.bundle_sha256,
    )
    if bundle_digest != authority.bundle_sha256 or runtime_files != authority.runtime_files:
        raise PackageRefusal("authority_runtime_mapping_mismatch")
    account_home = _account_home_from_compiler_path(authority.compiler_path)
    locator, compiler_digest, compiler_path = verify_compiler_authority(
        root_path,
        account_home=account_home,
        enforce_host=True,
    )
    if (
        locator != authority.compiler_locator_id
        or compiler_digest != authority.compiler_sha256
        or compiler_path != authority.compiler_path
    ):
        raise PackageRefusal("authority_compiler_changed")

    destination_path = Path(destination)
    if not destination_path.is_absolute():
        destination_path = root_path / destination_path
    destination_path = destination_path.absolute()
    try:
        destination_relative = destination_path.relative_to(root_path)
    except ValueError as error:
        raise PackageRefusal("destination_outside_root") from error
    if (
        len(destination_relative.parts) != 3
        or destination_relative.parts[:2] != ("release", "dist")
        or destination_relative.name in ("", ".", "..")
    ):
        raise PackageRefusal("destination_invalid")
    release_directory = root_path / "release"
    try:
        release_info = release_directory.lstat()
    except OSError as error:
        raise PackageRefusal("destination_parent_unavailable") from error
    if stat.S_ISLNK(release_info.st_mode) or not stat.S_ISDIR(release_info.st_mode):
        raise PackageRefusal("destination_parent_unsafe")
    dist_directory = release_directory / "dist"
    try:
        dist_directory.mkdir(mode=0o755)
    except FileExistsError:
        pass
    except OSError as error:
        raise PackageRefusal("destination_parent_unavailable") from error
    dist_info = dist_directory.lstat()
    if stat.S_ISLNK(dist_info.st_mode) or not stat.S_ISDIR(dist_info.st_mode):
        raise PackageRefusal("destination_parent_unsafe")
    if os.path.lexists(destination_path):
        raise PackageRefusal("destination_exists")

    temporary = Path(
        tempfile.mkdtemp(prefix=f".{destination_path.name}.", suffix=".tmp", dir=dist_directory)
    )
    installed = False
    try:
        outer_raw = _read_relative(
            root_path,
            OUTER_MANIFEST_PATH,
            byte_limit=512 * 1024,
            unavailable_reason="outer_manifest_unavailable",
            unsafe_reason="outer_manifest_unsafe",
        )
        outer = _parse_json_object(outer_raw, "outer_manifest")
        for record in outer["artifacts"]:
            relative = _normalize_relative(record["path"])
            data = _read_relative(
                root_path,
                relative,
                byte_limit=record["size_bytes"],
                unavailable_reason="outer_artifact_unavailable",
                unsafe_reason="outer_artifact_unsafe",
            )
            if (
                len(data) != record["size_bytes"]
                or hashlib.sha256(data).hexdigest() != record["sha256"]
            ):
                raise PackageRefusal("source_changed_during_package", relative)
            _write_package_file(
                temporary,
                relative,
                data,
                mode=_packaged_source_mode(root_path / relative),
            )
        _write_package_file(
            temporary,
            OUTER_MANIFEST_PATH,
            outer_raw,
            mode=0o444,
        )

        runtime_metadata: list[dict[str, str]] = []
        for logical_name, source_path in runtime_files:
            try:
                relative = source_path.absolute().relative_to(root_path).as_posix()
            except ValueError as error:
                raise PackageRefusal("runtime_path_outside_root", logical_name) from error
            relative = _normalize_relative(relative)
            data = _read_relative(
                root_path,
                relative,
                byte_limit=MAX_RUNTIME_FILE_BYTES,
                unavailable_reason="runtime_file_unavailable",
                unsafe_reason="runtime_file_unsafe",
            )
            _write_package_file(
                temporary,
                relative,
                data,
                mode=_packaged_source_mode(root_path / relative),
            )
            runtime_metadata.append({"logical_name": logical_name, "path": relative})

        metadata = {
            "authority": {
                "bundle_sha256": authority.bundle_sha256,
                "catalog_sha256": authority.catalog_sha256,
                "compiler_included": False,
                "compiler_locator_id": authority.compiler_locator_id,
                "compiler_required_mode": "0555",
                "compiler_sha256": authority.compiler_sha256,
                "compiler_size_bytes": ANUBIS_SIZE_BYTES,
                "outer_manifest_sha256": authority.outer_manifest_sha256,
            },
            "catalog_path": CATALOG_PATH,
            "claim_boundary": {
                "assurance_ceiling": "bounded",
                "global_claims_admitted": False,
                "permanent_nonclaims": list(PERMANENT_NONCLAIMS),
            },
            "outer_manifest_path": OUTER_MANIFEST_PATH,
            "package_index_path": "SHA256SUMS",
            "package_version": PACKAGE_VERSION,
            "platform": "macos-arm64",
            "runtime_files": runtime_metadata,
            "schema": "jackal-navier-v180-package-v1",
        }
        _write_package_file(
            temporary,
            "NAVIER_V180_PACKAGE.json",
            canonical_json_bytes(metadata),
            mode=0o444,
        )
        _write_package_file(
            temporary,
            "jackal-navier-stokes-v1.8",
            _gate_wrapper_bytes(),
            mode=0o555,
        )
        index_raw = _build_package_index(temporary)
        _write_package_file(temporary, "SHA256SUMS", index_raw, mode=0o444)
        index_digest = hashlib.sha256(index_raw).hexdigest()
        verify_package_authority(
            temporary,
            index_digest,
            account_home=account_home,
            enforce_host=True,
        )
        if os.path.lexists(destination_path):
            raise PackageRefusal("destination_exists")
        try:
            os.rename(temporary, destination_path)
        except OSError as error:
            raise PackageRefusal("destination_install_failed") from error
        installed = True
        return destination_path
    finally:
        if not installed:
            shutil.rmtree(temporary, ignore_errors=True)


def verify_package_authority(
    package_root: Path | str,
    expected_package_index_sha256: str,
    *,
    account_home: Path | str | None = None,
    enforce_host: bool = True,
) -> ArtifactAuthority:
    expected_index = _require_digest(
        expected_package_index_sha256, "expected_package_index_sha256"
    )
    package = _require_root(package_root)
    index_raw = _read_relative(
        package,
        "SHA256SUMS",
        byte_limit=2 * 1024 * 1024,
        unavailable_reason="package_index_unavailable",
        unsafe_reason="package_index_unsafe",
    )
    if not hmac.compare_digest(hashlib.sha256(index_raw).hexdigest(), expected_index):
        raise PackageRefusal("package_index_identity_mismatch")
    records = _parse_package_index(index_raw)
    observed_files = _inventory_package_files(package)
    if observed_files != set(records) | {"SHA256SUMS"}:
        raise PackageRefusal("package_inventory_mismatch")
    remaining = 512 * 1024 * 1024
    for relative, expected_digest in records.items():
        data = _read_relative(
            package,
            relative,
            byte_limit=min(64 * 1024 * 1024, remaining),
            unavailable_reason="package_file_unavailable",
            unsafe_reason="package_file_unsafe",
        )
        if not hmac.compare_digest(hashlib.sha256(data).hexdigest(), expected_digest):
            raise PackageRefusal("package_file_digest_mismatch", relative)
        remaining -= len(data)
        if remaining < 0:
            raise PackageRefusal("package_total_limit")

    metadata_raw = _read_relative(
        package,
        "NAVIER_V180_PACKAGE.json",
        byte_limit=2 * 1024 * 1024,
        unavailable_reason="package_metadata_unavailable",
        unsafe_reason="package_metadata_unsafe",
    )
    metadata = _parse_json_object(metadata_raw, "package_metadata")
    if metadata_raw != canonical_json_bytes(metadata):
        raise PackageRefusal("package_metadata_noncanonical")
    if set(metadata) != {
        "authority",
        "catalog_path",
        "claim_boundary",
        "outer_manifest_path",
        "package_index_path",
        "package_version",
        "platform",
        "runtime_files",
        "schema",
    }:
        raise PackageRefusal("package_metadata_schema_invalid")
    authority_record = metadata.get("authority")
    claim = metadata.get("claim_boundary")
    runtime_metadata = metadata.get("runtime_files")
    if (
        metadata.get("schema") != "jackal-navier-v180-package-v1"
        or metadata.get("package_version") != PACKAGE_VERSION
        or metadata.get("platform") != "macos-arm64"
        or metadata.get("catalog_path") != CATALOG_PATH
        or metadata.get("outer_manifest_path") != OUTER_MANIFEST_PATH
        or metadata.get("package_index_path") != "SHA256SUMS"
        or not isinstance(authority_record, dict)
        or set(authority_record)
        != {
            "bundle_sha256",
            "catalog_sha256",
            "compiler_included",
            "compiler_locator_id",
            "compiler_required_mode",
            "compiler_sha256",
            "compiler_size_bytes",
            "outer_manifest_sha256",
        }
        or authority_record.get("compiler_included") is not False
        or authority_record.get("compiler_locator_id") != ANUBIS_LOCATOR_ID
        or authority_record.get("compiler_sha256") != ANUBIS_SHA256
        or authority_record.get("compiler_size_bytes") != ANUBIS_SIZE_BYTES
        or authority_record.get("compiler_required_mode") != "0555"
        or not isinstance(claim, dict)
        or claim.get("assurance_ceiling") != "bounded"
        or claim.get("global_claims_admitted") is not False
        or claim.get("permanent_nonclaims") != list(PERMANENT_NONCLAIMS)
        or not isinstance(runtime_metadata, list)
        or not runtime_metadata
    ):
        raise PackageRefusal("package_metadata_contract_invalid")
    catalog_digest = _require_digest(
        authority_record.get("catalog_sha256"), "catalog_sha256"
    )
    bundle_digest = _require_digest(
        authority_record.get("bundle_sha256"), "bundle_sha256"
    )
    outer_digest = _require_digest(
        authority_record.get("outer_manifest_sha256"), "outer_manifest_sha256"
    )
    _verify_outer_manifest(package, outer_digest, catalog_digest)
    observed_bundle, runtime_files = verify_catalog_authority(
        package,
        catalog_digest,
        bundle_digest,
    )
    locator, compiler_digest, compiler_path = verify_compiler_authority(
        package,
        account_home=account_home,
        enforce_host=enforce_host,
    )
    expected_runtime_metadata = []
    for logical_name, path in runtime_files:
        try:
            relative = path.absolute().relative_to(package).as_posix()
        except ValueError as error:
            raise PackageRefusal("package_runtime_path_outside_root") from error
        expected_runtime_metadata.append(
            {"logical_name": logical_name, "path": _normalize_relative(relative)}
        )
    if runtime_metadata != expected_runtime_metadata:
        raise PackageRefusal("package_runtime_mapping_mismatch")
    return ArtifactAuthority(
        catalog_sha256=catalog_digest,
        bundle_sha256=observed_bundle,
        outer_manifest_sha256=outer_digest,
        compiler_locator_id=locator,
        compiler_sha256=compiler_digest,
        compiler_path=compiler_path,
        runtime_files=runtime_files,
    )


def _account_home_from_compiler_path(compiler_path: Path) -> Path:
    path = compiler_path.absolute()
    for relative in ANUBIS_RELATIVE_CANDIDATES:
        relative_parts = PurePosixPath(relative).parts
        if tuple(path.parts[-len(relative_parts) :]) == relative_parts:
            prefix = path.parts[: -len(relative_parts)]
            if prefix:
                return Path(*prefix)
    raise PackageRefusal("compiler_path_not_logical_locator")


def _packaged_source_mode(path: Path) -> int:
    try:
        info = path.lstat()
    except OSError as error:
        raise PackageRefusal("source_mode_unavailable") from error
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise PackageRefusal("source_mode_unsafe")
    return 0o555 if stat.S_IMODE(info.st_mode) & 0o111 else 0o444


def _write_package_file(root: Path, relative: str, data: bytes, *, mode: int) -> None:
    relative = _normalize_relative(relative)
    target = root / relative
    target.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
    if os.path.lexists(target):
        try:
            existing = target.read_bytes()
        except OSError as error:
            raise PackageRefusal("package_overlap_unreadable", relative) from error
        if existing != data:
            raise PackageRefusal("package_overlap_mismatch", relative)
        if stat.S_IMODE(target.lstat().st_mode) != mode:
            target.chmod(mode)
        return
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(target, flags, mode)
        try:
            view = memoryview(data)
            while view:
                written = os.write(descriptor, view)
                if written <= 0:
                    raise OSError("short package write")
                view = view[written:]
            os.fsync(descriptor)
            os.fchmod(descriptor, mode)
        finally:
            os.close(descriptor)
    except OSError as error:
        raise PackageRefusal("package_write_failed", relative) from error


def _gate_wrapper_bytes() -> bytes:
    return b"""#!/bin/sh
set -eu
PACKAGE_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
PYTHON=/opt/homebrew/bin/python3
if [ ! -x "$PYTHON" ]; then
  echo 'NAVIER_V180_PACKAGE_GATE=REFUSED reason=python_unavailable detail=/opt/homebrew/bin/python3' >&2
  exit 1
fi
exec "$PYTHON" -I -S -B "$PACKAGE_ROOT/release/build_package_v180_navier.py" package-gate --package-root "$PACKAGE_ROOT" "$@"
"""


def _build_package_index(package: Path) -> bytes:
    files = sorted(_inventory_package_files(package))
    if "SHA256SUMS" in files:
        raise PackageRefusal("package_index_self_reference")
    lines: list[str] = []
    for relative in files:
        data = _read_relative(
            package,
            relative,
            byte_limit=64 * 1024 * 1024,
            unavailable_reason="package_file_unavailable",
            unsafe_reason="package_file_unsafe",
        )
        lines.append(f"{hashlib.sha256(data).hexdigest()}  {relative}\n")
    return "".join(lines).encode("utf-8")


def _parse_package_index(raw: bytes) -> dict[str, str]:
    if not raw or not raw.endswith(b"\n") or len(raw) > 2 * 1024 * 1024:
        raise PackageRefusal("package_index_format_invalid")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise PackageRefusal("package_index_format_invalid") from error
    records: dict[str, str] = {}
    aliases: set[str] = set()
    prior: str | None = None
    for line in text.splitlines():
        if len(line) < 67 or line[64:66] != "  ":
            raise PackageRefusal("package_index_format_invalid")
        digest = line[:64]
        relative = _normalize_relative(line[66:])
        alias = "/".join(
            unicodedata.normalize("NFD", part).casefold()
            for part in relative.split("/")
        )
        if (
            _HEX64.fullmatch(digest) is None
            or relative == "SHA256SUMS"
            or relative in records
            or alias in aliases
            or (prior is not None and relative <= prior)
        ):
            raise PackageRefusal("package_index_format_invalid")
        records[relative] = digest
        aliases.add(alias)
        prior = relative
    required = {
        "NAVIER_V180_PACKAGE.json",
        "jackal-navier-stokes-v1.8",
        "release/build_package_v180_navier.py",
        CATALOG_PATH,
        OUTER_MANIFEST_PATH,
    }
    if not required <= set(records):
        raise PackageRefusal("package_index_required_file_missing")
    return records


def _inventory_package_files(package: Path) -> set[str]:
    files: set[str] = set()
    for directory, directory_names, file_names in os.walk(package, followlinks=False):
        directory_path = Path(directory)
        for name in list(directory_names):
            child = directory_path / name
            info = child.lstat()
            if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
                raise PackageRefusal("package_inventory_unsafe")
        for name in file_names:
            child = directory_path / name
            info = child.lstat()
            if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
                raise PackageRefusal("package_inventory_unsafe")
            relative = child.relative_to(package).as_posix()
            files.add(_normalize_relative(relative))
    if len(files) > 512:
        raise PackageRefusal("package_inventory_limit")
    return files


_HEX64 = re.compile(r"[0-9a-f]{64}", re.ASCII)


def _require_digest(value: str, label: str) -> str:
    if not isinstance(value, str) or _HEX64.fullmatch(value) is None:
        raise PackageRefusal("expected_digest_invalid", label)
    return value


def canonical_json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _require_root(root: Path | str) -> Path:
    candidate = Path(root)
    try:
        info = candidate.lstat()
    except OSError as error:
        raise PackageRefusal("root_unavailable") from error
    if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
        raise PackageRefusal("root_unsafe")
    return candidate.absolute()


def _normalize_relative(path: str) -> str:
    if (
        not isinstance(path, str)
        or not path
        or path.startswith("/")
        or "\\" in path
        or any(ord(character) < 32 or ord(character) == 127 for character in path)
    ):
        raise PackageRefusal("path_invalid")
    parts = PurePosixPath(path).parts
    if any(part in ("", ".", "..") for part in parts):
        raise PackageRefusal("path_invalid")
    return "/".join(parts)


def _normalize_candidate(base: str, candidate: str) -> str:
    if (
        not isinstance(candidate, str)
        or not candidate
        or candidate.startswith("/")
        or "\\" in candidate
        or any(ord(character) < 32 or ord(character) == 127 for character in candidate)
    ):
        raise PackageRefusal("catalog_runtime_candidate_invalid")
    parts = list(PurePosixPath(base).parts)
    for part in PurePosixPath(candidate).parts:
        if part in ("", "."):
            continue
        if part == "..":
            if not parts:
                raise PackageRefusal("catalog_runtime_candidate_escape")
            parts.pop()
        else:
            parts.append(part)
    if not parts:
        raise PackageRefusal("catalog_runtime_candidate_invalid")
    return _normalize_relative("/".join(parts))


def _open_flags(*, directory: bool = False) -> int:
    flags = os.O_RDONLY | os.O_NONBLOCK
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    if directory and hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    return flags


def _signature(info: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (
        info.st_dev,
        info.st_ino,
        info.st_mode,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )


def _read_relative(
    root: Path,
    relative: str,
    *,
    byte_limit: int,
    unavailable_reason: str,
    unsafe_reason: str,
) -> bytes:
    relative = _normalize_relative(relative)
    try:
        descriptor = os.open(os.fspath(root), _open_flags(directory=True))
    except OSError as error:
        raise PackageRefusal("root_unavailable") from error
    try:
        for index, part in enumerate(relative.split("/")):
            try:
                next_descriptor = os.open(
                    part,
                    _open_flags(directory=index < len(relative.split("/")) - 1),
                    dir_fd=descriptor,
                )
            except OSError as error:
                if error.errno in (errno.ENOENT, errno.ENOTDIR):
                    raise PackageRefusal(unavailable_reason, relative) from error
                raise PackageRefusal(unsafe_reason, relative) from error
            os.close(descriptor)
            descriptor = next_descriptor
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_size > byte_limit:
            raise PackageRefusal(unsafe_reason, relative)
        chunks: list[bytes] = []
        count = 0
        while True:
            chunk = os.read(descriptor, min(64 * 1024, byte_limit - count + 1))
            if not chunk:
                break
            count += len(chunk)
            if count > byte_limit:
                raise PackageRefusal(unsafe_reason, relative)
            chunks.append(chunk)
        after = os.fstat(descriptor)
        if _signature(before) != _signature(after) or count != after.st_size:
            raise PackageRefusal(unsafe_reason, relative)
        try:
            current = (root / relative).lstat()
        except OSError as error:
            raise PackageRefusal(unsafe_reason, relative) from error
        if _signature(current) != _signature(after):
            raise PackageRefusal(unsafe_reason, relative)
        return b"".join(chunks)
    finally:
        try:
            os.close(descriptor)
        except OSError:
            pass


def _strict_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise PackageRefusal("json_duplicate_field", key)
        result[key] = value
    return result


def _parse_json_object(raw: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_strict_pairs,
            parse_constant=lambda unused: (_ for _ in ()).throw(
                PackageRefusal("json_nonfinite_number", label)
            ),
        )
    except PackageRefusal:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as error:
        raise PackageRefusal("json_invalid", label) from error
    if not isinstance(value, dict):
        raise PackageRefusal("json_schema_invalid", label)
    return value


def _framed(name: str, data: bytes) -> bytes:
    name_bytes = name.encode("utf-8")
    return (
        str(len(name_bytes)).encode("ascii")
        + b":"
        + name_bytes
        + b"\0"
        + str(len(data)).encode("ascii")
        + b":"
        + data
        + b"\0"
    )


def _validate_bundle_files(
    catalog: dict[str, Any], selected_relatives: dict[str, str]
) -> None:
    bundle_files = catalog.get("bundle_files")
    if (
        not isinstance(bundle_files, list)
        or not bundle_files
        or any(not isinstance(item, str) or not item for item in bundle_files)
    ):
        raise PackageRefusal("catalog_bundle_files_invalid")
    selected_local = {
        Path(relative).name
        for logical, relative in selected_relatives.items()
        if logical.startswith("plugin/")
        and PurePosixPath(relative).parent == PurePosixPath("plugin/hermes")
    }
    missing = sorted(set(bundle_files) - selected_local)
    if missing:
        raise PackageRefusal("catalog_plugin_coverage_missing", missing[0])


def _validate_navier_tools(catalog: dict[str, Any]) -> None:
    tools = catalog.get("tools")
    if not isinstance(tools, list):
        raise PackageRefusal("catalog_tools_invalid")
    by_name: dict[str, dict[str, Any]] = {}
    for tool in tools:
        if not isinstance(tool, dict) or not isinstance(tool.get("name"), str):
            raise PackageRefusal("catalog_tool_invalid")
        if tool["name"] in by_name:
            raise PackageRefusal("catalog_tool_duplicate", tool["name"])
        by_name[tool["name"]] = tool
    checker = by_name.get("jackal_navier_stokes_check")
    verifier = by_name.get("jackal_verify_navier_stokes_receipt")
    if checker is None or verifier is None:
        raise PackageRefusal("navier_tool_missing")
    checker_arguments = checker.get("arguments")
    checker_returns = checker.get("returns")
    if (
        not isinstance(checker_arguments, dict)
        or not isinstance(checker_arguments.get("request"), dict)
        or checker_arguments["request"].get("type") != "object"
        or checker_arguments["request"].get("required") is not True
        or not isinstance(checker_returns, dict)
        or checker_returns.get("status") != "bounded | indeterminate | refused"
        or checker_returns.get("verification_scope") != "receipt_replay_only"
        or "nonclaims" not in checker_returns
    ):
        raise PackageRefusal("navier_check_tool_contract_invalid")
    verifier_arguments = verifier.get("arguments")
    verifier_returns = verifier.get("returns")
    if (
        not isinstance(verifier_arguments, dict)
        or set(("receipt", "expected_request")) - set(verifier_arguments)
        or any(
            not isinstance(verifier_arguments[name], dict)
            or verifier_arguments[name].get("type") != "object"
            or verifier_arguments[name].get("required") is not True
            for name in ("receipt", "expected_request")
        )
        or not isinstance(verifier_returns, dict)
        or verifier_returns.get("status") != "verified | refused"
        or verifier_returns.get("verification_scope") != "receipt_replay_only"
        or "mathematical_status" not in verifier_returns
    ):
        raise PackageRefusal("navier_verify_tool_contract_invalid")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build the isolated caller-pinned JACKAL Navier v1.8 package."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("preflight", "build"):
        command = commands.add_parser(name)
        command.add_argument("--root", required=True)
        command.add_argument("--expected-catalog-sha256", required=True)
        command.add_argument("--expected-bundle-sha256", required=True)
        command.add_argument("--expected-outer-manifest-sha256", required=True)
        if name == "build":
            command.add_argument("--destination", required=True)
    gate = commands.add_parser("package-gate")
    gate.add_argument("--package-root", required=True)
    gate.add_argument("--expected-package-index-sha256", required=True)
    gate.add_argument("action", choices=("preflight", "check", "verify"))
    gate.add_argument("tool_arguments", nargs=argparse.REMAINDER)
    return parser


def main(
    argv: list[str] | None = None,
    *,
    account_home: Path | str | None = None,
    enforce_host: bool = True,
) -> int:
    arguments = _parser().parse_args(argv)
    try:
        if arguments.command == "package-gate":
            expected_index = _require_digest(
                arguments.expected_package_index_sha256,
                "expected_package_index_sha256",
            )
            authority = verify_package_authority(
                arguments.package_root,
                expected_index,
                account_home=account_home,
                enforce_host=enforce_host,
            )
            tool_arguments = list(arguments.tool_arguments)
            if tool_arguments[:1] == ["--"]:
                tool_arguments = tool_arguments[1:]
            if arguments.action == "preflight":
                if tool_arguments:
                    raise PackageRefusal("package_gate_arguments_invalid")
                print(
                    "NAVIER_V180_PACKAGE_GATE=PASS action=preflight "
                    f"package_index_sha256={expected_index} "
                    f"bundle_sha256={authority.bundle_sha256} "
                    f"outer_manifest_sha256={authority.outer_manifest_sha256} "
                    f"compiler_sha256={authority.compiler_sha256}"
                )
                return 0
            target = (
                "tools/navier_stokes_certificate_producer.py"
                if arguments.action == "check"
                else "tools/navier_stokes_receipt_verify.py"
            )
            package = _require_root(arguments.package_root)
            executable_arguments = [
                sys.executable,
                "-I",
                "-S",
                "-B",
                os.fspath(package / target),
                *tool_arguments,
            ]
            os.execve(
                sys.executable,
                executable_arguments,
                {
                    "LANG": "C",
                    "LC_ALL": "C",
                    "PATH": os.defpath,
                    "PYTHONDONTWRITEBYTECODE": "1",
                },
            )
            raise PackageRefusal("package_gate_exec_failed")
        expected_catalog = _require_digest(
            arguments.expected_catalog_sha256, "expected_catalog_sha256"
        )
        expected_bundle = _require_digest(
            arguments.expected_bundle_sha256, "expected_bundle_sha256"
        )
        expected_outer = _require_digest(
            arguments.expected_outer_manifest_sha256,
            "expected_outer_manifest_sha256",
        )
        authority = preflight(
            arguments.root,
            expected_catalog_sha256=expected_catalog,
            expected_bundle_sha256=expected_bundle,
            expected_outer_manifest_sha256=expected_outer,
        )
        if authority is None:
            raise PackageRefusal("preflight_not_implemented")
        if arguments.command == "preflight":
            print(
                "NAVIER_V180_PACKAGE_PREFLIGHT=PASS "
                f"catalog_sha256={authority.catalog_sha256} "
                f"bundle_sha256={authority.bundle_sha256} "
                f"outer_manifest_sha256={authority.outer_manifest_sha256} "
                f"compiler_sha256={authority.compiler_sha256}"
            )
            return 0
        package = build_package(arguments.root, arguments.destination, authority)
        if package is None:
            raise PackageRefusal("package_build_not_implemented")
        index_digest = hashlib.sha256((package / "SHA256SUMS").read_bytes()).hexdigest()
        print(
            f"NAVIER_V180_PACKAGE_BUILD=PASS package={package} "
            f"package_index_sha256={index_digest}"
        )
        return 0
    except PackageRefusal as error:
        operation = {
            "preflight": "PREFLIGHT",
            "build": "BUILD",
            "package-gate": "GATE",
        }[arguments.command]
        detail = error.detail or "fail_closed"
        print(
            f"NAVIER_V180_PACKAGE_{operation}=REFUSED "
            f"reason={error.reason} detail={detail}",
            file=sys.stderr,
        )
        return 1
    except Exception:
        operation = {
            "preflight": "PREFLIGHT",
            "build": "BUILD",
            "package-gate": "GATE",
        }[arguments.command]
        print(
            f"NAVIER_V180_PACKAGE_{operation}=REFUSED "
            "reason=internal_error detail=unexpected_failure",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
