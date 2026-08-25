#!/usr/bin/python3 -IB
"""Build deterministic JACKAL v1.7.5 spacecraft certificate release assets.

Publication invocation: /usr/bin/python3 -I -B package_spacecraft_v175.py ...
"""

from __future__ import annotations

import argparse
import ctypes
import errno
import gzip
import hashlib
import importlib.util
import io
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import types
from pathlib import Path
from typing import Mapping, Sequence

ROOT = Path(__file__).resolve().parents[2]
PYTHON_LAUNCHER = Path("/usr/bin/python3")

VERSION = "v1.7.5"
CERTIFICATE_EPOCH = "v1.7.5"
MODEL_ID = "jackal-spacecraft-finite-burn-ode-v2"
PUBLICATION_NONCE = "spacecraft-burn-v2-publication-20260825"
ARCHIVE_NAME = "jackal-spacecraft-burn-v1.7.5-verifier-macos-arm64.tar.gz"
WITNESS_NAME = "baseline_witness_v2.cert"
RECEIPT_NAME = "baseline_receipt_v2.json"
PROOF_NAME = "spacecraft_burn_proof_identity_v1.json"
REVIEW_NAME = "spacecraft_burn_independent_review_v175.md"
REVIEW_CLEARANCE_NAME = "spacecraft_burn_review_clearance_v175.json"
RELEASE_METADATA_NAME = "spacecraft_burn_release_metadata_v175.json"
RELEASE_NOTES_NAME = "spacecraft_burn_v175_release_notes.md"
WITNESS_MANIFEST_NAME = "baseline_witness_v2.manifest.json"
CHECKER = ROOT / "proofs/lean/.lake/build/bin/jackal_spacecraft_burn_check"
IDENTITY = ROOT / "release/evidence" / PROOF_NAME
REVIEW = ROOT / "release/evidence" / REVIEW_NAME
REVIEW_CLEARANCE = ROOT / "release/evidence" / REVIEW_CLEARANCE_NAME
EVIDENCE = ROOT / "spacecraft_burn_cert/evidence"
SPACECRAFT_REQUEST_DIGEST = (
    "03bcad618ad60114007c74a384eb8c9432e3755b817e74bd5bdc9bd1ba6df3e7"
)
AUXILIARY_EVIDENCE_NAMES = (
    "independent_verification_v2.json",
    "instrument_validation_v2.json",
    "mutation_aba_v2.json",
)
MODEL_QUALIFIER = (
    "under the stated finite-burn ODE model, supplied input bounds, "
    "and machine-checked interval-certificate assumptions"
)
QUALIFIED_VERDICT = f"CERTIFIED SAFE {MODEL_QUALIFIER}"
REVIEW_REQUIRED_SECTIONS = (
    "## Review scope",
    "## Findings and dispositions",
    "## Full-file Picard/source review",
    "## Lean correspondence",
    "## Final zero-finding pass",
)
REVIEW_ADMIN_PATHS = (
    f"release/evidence/{REVIEW_NAME}",
    f"release/evidence/{REVIEW_CLEARANCE_NAME}",
)

IDENTITY_LOGICAL_PATH = f"release/evidence/{PROOF_NAME}"
REVIEW_LOGICAL_PATH = f"release/evidence/{REVIEW_NAME}"
REVIEW_CLEARANCE_LOGICAL_PATH = f"release/evidence/{REVIEW_CLEARANCE_NAME}"
RELEASE_METADATA_LOGICAL_PATH = f"release/evidence/{RELEASE_METADATA_NAME}"
RELEASE_NOTES_LOGICAL_PATH = f"release/{RELEASE_NOTES_NAME}"
REQUEST_LOGICAL_PATH = "spacecraft_burn_cert/request_v2.json"
PRODUCER_LOGICAL_PATH = "spacecraft_burn_cert/certify.py"
VERIFIER_LOGICAL_PATH = "spacecraft_burn_cert/verify_receipt.py"
WITNESS_CODEC_LOGICAL_PATH = "spacecraft_burn_cert/witness_codec.py"
VALIDATION_LOGICAL_PATH = "spacecraft_burn_cert/validate.py"
MUTATION_LOGICAL_PATH = "spacecraft_burn_cert/mutation_aba.py"
MUTATION_TEST_LOGICAL_PATH = "spacecraft_burn_cert/tests/test_certifier.py"
CLAIM_GATE_LOGICAL_PATH = "tools/spacecraft_burn_release_gate.py"
LEGACY_RECEIPT_LOGICAL_PATH = (
    "spacecraft_burn_cert/evidence/legacy-v1/baseline_receipt.json"
)
EVIDENCE_SUMS_LOGICAL_PATH = "spacecraft_burn_cert/evidence/SHA256SUMS"
BASELINE_RECEIPT_LOGICAL_PATH = (
    f"spacecraft_burn_cert/evidence/{RECEIPT_NAME}"
)
WITNESS_MANIFEST_LOGICAL_PATH = (
    f"spacecraft_burn_cert/evidence/{WITNESS_MANIFEST_NAME}"
)
GENERATOR_LOGICAL_PATH = "release/tools/spacecraft_burn_proof_identity.py"
GENERATOR_ENGINE_LOGICAL_PATH = "release/tools/gaussian_proof_identity.py"
GENERATOR_CLOSURE_DEFINITION = (
    "Complete repository-local Python generator source closure used to construct and "
    "verify this identity. The interpreter and standard library remain in the explicit "
    "build-platform trusted base."
)
GENERATOR_CLOSURE_PATHS = (
    GENERATOR_LOGICAL_PATH,
    GENERATOR_ENGINE_LOGICAL_PATH,
)
SPACECRAFT_ROOT_MODULES = ("JackalIv.Spacecraft.CertMain",)
LEAN_MODULE_PATTERN = re.compile(
    r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*"
)
AUXILIARY_LOGICAL_PATHS = {
    name: f"spacecraft_burn_cert/evidence/{name}"
    for name in AUXILIARY_EVIDENCE_NAMES
}
STATIC_TRACKED_INPUT_PATHS = (
    "release/tools/package_spacecraft_v175.py",
    "release/tools/package_spacecraft_v174.py",
    CLAIM_GATE_LOGICAL_PATH,
    GENERATOR_LOGICAL_PATH,
    GENERATOR_ENGINE_LOGICAL_PATH,
    IDENTITY_LOGICAL_PATH,
    REVIEW_LOGICAL_PATH,
    REVIEW_CLEARANCE_LOGICAL_PATH,
    RELEASE_METADATA_LOGICAL_PATH,
    RELEASE_NOTES_LOGICAL_PATH,
    REQUEST_LOGICAL_PATH,
    PRODUCER_LOGICAL_PATH,
    VERIFIER_LOGICAL_PATH,
    WITNESS_CODEC_LOGICAL_PATH,
    VALIDATION_LOGICAL_PATH,
    MUTATION_LOGICAL_PATH,
    MUTATION_TEST_LOGICAL_PATH,
    LEGACY_RECEIPT_LOGICAL_PATH,
    EVIDENCE_SUMS_LOGICAL_PATH,
    BASELINE_RECEIPT_LOGICAL_PATH,
    WITNESS_MANIFEST_LOGICAL_PATH,
    *AUXILIARY_LOGICAL_PATHS.values(),
)

GIT_EXECUTABLE = Path("/usr/bin/git").resolve(strict=True)
GIT_ENVIRONMENT = {
    "GIT_ATTR_NOSYSTEM": "1",
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_CONFIG_SYSTEM": "/dev/null",
    "GIT_NO_REPLACE_OBJECTS": "1",
    "GIT_OPTIONAL_LOCKS": "0",
    "GIT_PAGER": "cat",
    "GIT_TERMINAL_PROMPT": "0",
    "HOME": "/var/empty",
    "LANG": "C",
    "LC_ALL": "C",
    "PATH": "/usr/bin:/bin",
    "PAGER": "cat",
    "XDG_CONFIG_HOME": "/var/empty",
}
GIT_GLOBAL_OPTIONS = (
    "--no-replace-objects",
    "-c",
    "core.fsmonitor=false",
    "-c",
    "core.hooksPath=/var/empty",
)
FORBIDDEN_LOCAL_GIT_CONFIG_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"alias\..+",
        r"core\.(?:alternateRefsCommand|attributesFile|editor|excludesFile|"
        r"fsmonitor|hooksPath|pager|sshCommand|worktree)",
        r"credential(?:\..+)?\.helper",
        r"diff\.external",
        r"diff\..+\.(?:command|textconv)",
        r"difftool\..+\.cmd",
        r"filter\..+\.(?:clean|process|smudge)",
        r"fsck\..+",
        r"gpg\.(?:program|ssh\.program)",
        r"include(?:If\..+)?\.path",
        r"interactive\.diffFilter",
        r"man\..+\.cmd",
        r"merge\..+\.driver",
        r"mergetool\..+\.cmd",
        r"pager\..+",
        r"sequence\.editor",
    )
)
MAX_TRACKED_INPUT_BYTES = 64 * 1024 * 1024
MAX_STAGED_JSON_BYTES = 64 * 1024 * 1024
MAX_STAGED_WITNESS_BYTES = 512 * 1024 * 1024
MAX_CHECKER_BYTES = 512 * 1024 * 1024
MAX_JSON_NESTING_DEPTH = 128
MAX_JSON_INTEGER_DIGITS = 128


class DuplicateJsonKey(ValueError):
    """Raised when a purported binding uses ambiguous duplicate JSON keys."""


def reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateJsonKey(key)
        result[key] = value
    return result


def reject_nonfinite_json(value: str) -> None:
    raise ValueError(f"non-finite JSON number: {value}")


def reject_fractional_json(_value: str) -> None:
    raise ValueError("fractional JSON numbers are not admitted")


def parse_bounded_json_integer(value: str) -> int:
    digits = value[1:] if value.startswith("-") else value
    if len(digits) > MAX_JSON_INTEGER_DIGITS:
        raise ValueError("JSON integer exceeds the package digit limit")
    return int(value)


def contains_unicode_surrogate(value: str) -> bool:
    return any("\ud800" <= character <= "\udfff" for character in value)


def require_bounded_json_tree(document: object) -> None:
    pending = [(document, 0)]
    while pending:
        value, depth = pending.pop()
        if type(value) is dict:
            if depth >= MAX_JSON_NESTING_DEPTH:
                raise ValueError("JSON nesting exceeds the package limit")
            if any(contains_unicode_surrogate(key) for key in value):
                raise ValueError("JSON strings must not contain Unicode surrogates")
            pending.extend((child, depth + 1) for child in value.values())
        elif type(value) is list:
            if depth >= MAX_JSON_NESTING_DEPTH:
                raise ValueError("JSON nesting exceeds the package limit")
            pending.extend((child, depth + 1) for child in value)
        elif type(value) is str and contains_unicode_surrogate(value):
            raise ValueError("JSON strings must not contain Unicode surrogates")
        elif type(value) is float:
            raise ValueError("fractional JSON numbers are not admitted")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def deterministic_tar_gz(entries: dict[str, tuple[bytes, int]]) -> bytes:
    buffer = io.BytesIO()
    with gzip.GzipFile(
        filename="", mode="wb", fileobj=buffer, mtime=0
    ) as compressed:
        with tarfile.open(
            fileobj=compressed, mode="w", format=tarfile.PAX_FORMAT
        ) as archive:
            for name in sorted(entries):
                data, mode = entries[name]
                info = tarfile.TarInfo(name)
                info.size = len(data)
                info.mode = mode
                info.mtime = 0
                info.uid = info.gid = 0
                info.uname = info.gname = "root"
                archive.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def validate_witness_digests(witness_bytes: bytes, receipt: dict) -> str:
    digest = sha256(witness_bytes)
    witness = receipt.get("witness") if isinstance(receipt, dict) else None
    binding = receipt.get("formal_checker") if isinstance(receipt, dict) else None
    if not isinstance(witness, dict) or digest != witness.get("sha256"):
        raise RuntimeError("witness digest does not match receipt")
    if not isinstance(binding, dict) or digest != binding.get("witness_sha256"):
        raise RuntimeError(
            "checker-bound witness digest does not match packaged witness"
        )
    return digest


def validate_request_binding(request_bytes: bytes, binding: dict) -> None:
    observed = sha256(request_bytes)
    if observed != SPACECRAFT_REQUEST_DIGEST:
        raise RuntimeError("request bytes do not match fixed Lean checker digest")
    if binding.get("request_digest") != SPACECRAFT_REQUEST_DIGEST:
        raise RuntimeError(
            "receipt request digest does not match fixed Lean checker digest"
        )


def observed_platform_binary(path: Path, role: str) -> dict[str, object]:
    try:
        before = os.lstat(path)
        symlink_target = os.readlink(path) if stat.S_ISLNK(before.st_mode) else None
        resolved = path.resolve(strict=True)
        raw = read_bounded_regular_file(
            resolved,
            f"live {role}",
            MAX_TRACKED_INPUT_BYTES,
        )
        after = os.lstat(path)
        after_target = os.readlink(path) if stat.S_ISLNK(after.st_mode) else None
    except (OSError, RuntimeError) as error:
        raise RuntimeError(
            "publication Python runtime does not match proof identity"
        ) from error
    identity_before = (
        before.st_dev,
        before.st_ino,
        before.st_mode,
        before.st_size,
        before.st_mtime_ns,
        before.st_ctime_ns,
        symlink_target,
    )
    identity_after = (
        after.st_dev,
        after.st_ino,
        after.st_mode,
        after.st_size,
        after.st_mtime_ns,
        after.st_ctime_ns,
        after_target,
    )
    if identity_before != identity_after:
        raise RuntimeError(
            "publication Python runtime does not match proof identity"
        )
    return {
        "bytes": len(raw),
        "invocation_path": path.as_posix(),
        "invocation_symlink_target": symlink_target,
        "resolved_path": resolved.as_posix(),
        "role": role,
        "sha256": sha256(raw),
    }


def validate_publication_runtime(identity: object) -> dict[str, object]:
    attestation = identity.get("build_attestation") if isinstance(identity, dict) else None
    environment = (
        attestation.get("build_environment") if isinstance(attestation, dict) else None
    )
    rows = (
        environment.get("trusted_platform_launchers")
        if isinstance(environment, dict)
        else None
    )
    expected_roles = (
        "python-launcher",
        "python-interpreter",
        "git-client",
        "sandbox-launcher",
    )
    if (
        not isinstance(rows, list)
        or len(rows) != len(expected_roles)
        or tuple(
            row.get("role") if isinstance(row, dict) else None for row in rows
        )
        != expected_roles
    ):
        raise RuntimeError(
            "publication Python runtime does not match proof identity"
        )
    launcher = rows[0]
    interpreter = rows[1]
    git_client = rows[2]
    expected_keys = {
        "bytes",
        "invocation_path",
        "invocation_symlink_target",
        "resolved_path",
        "role",
        "sha256",
    }
    if (
        not isinstance(launcher, dict)
        or not isinstance(interpreter, dict)
        or not isinstance(git_client, dict)
        or set(launcher) != expected_keys
        or set(interpreter) != expected_keys
        or set(git_client) != expected_keys
        or launcher.get("invocation_path") != PYTHON_LAUNCHER.as_posix()
        or git_client.get("invocation_path") != GIT_EXECUTABLE.as_posix()
        or Path(sys.executable).as_posix() != interpreter.get("invocation_path")
    ):
        raise RuntimeError(
            "publication Python runtime does not match proof identity"
        )
    observed_launcher = observed_platform_binary(
        PYTHON_LAUNCHER, "python-launcher"
    )
    observed_interpreter = observed_platform_binary(
        Path(sys.executable), "python-interpreter"
    )
    observed_git = observed_platform_binary(GIT_EXECUTABLE, "git-client")
    if (
        observed_launcher != launcher
        or observed_interpreter != interpreter
        or observed_git != git_client
    ):
        raise RuntimeError(
            "publication Python runtime does not match proof identity"
        )
    return {
        "launcher_path": observed_launcher["invocation_path"],
        "launcher_sha256": observed_launcher["sha256"],
        "interpreter_path": observed_interpreter["invocation_path"],
        "interpreter_resolved_path": observed_interpreter["resolved_path"],
        "interpreter_sha256": observed_interpreter["sha256"],
        "git_path": observed_git["invocation_path"],
        "git_sha256": observed_git["sha256"],
    }


def validate_publication_startup() -> dict[str, object]:
    if (
        sys.flags.isolated != 1
        or sys.flags.dont_write_bytecode != 1
        or sys.flags.ignore_environment != 1
        or sys.flags.no_user_site != 1
    ):
        raise RuntimeError(
            "publication requires /usr/bin/python3 -I -B "
            "release/tools/package_spacecraft_v175.py"
        )
    try:
        identity_bytes = read_bounded_regular_file(
            IDENTITY,
            "live proof identity",
            MAX_TRACKED_INPUT_BYTES,
        )
        identity = strict_json_document(identity_bytes, "live proof identity")
    except RuntimeError as error:
        raise RuntimeError(
            "publication Python runtime does not match proof identity"
        ) from error
    return validate_publication_runtime(identity)


def load_claim_validator(source_bytes: bytes):
    """Load the claim validator only from the already commit-bound snapshot."""
    try:
        source = source_bytes.decode("utf-8")
    except UnicodeDecodeError as error:
        raise RuntimeError("snapshotted claim validator is not valid UTF-8") from error
    module = types.ModuleType("_jackal_snapshotted_release_claim_validator")
    module.__file__ = "tools/spacecraft_burn_release_gate.py"
    try:
        exec(compile(source, module.__file__, "exec"), module.__dict__)
    except BaseException as error:
        raise RuntimeError("snapshotted claim validator could not be loaded") from error
    if (
        getattr(module, "MODEL_QUALIFIER", None) != MODEL_QUALIFIER
        or getattr(module, "QUALIFIED_VERDICT", None) != QUALIFIED_VERDICT
        or not callable(getattr(module, "document_findings", None))
        or not callable(getattr(module, "string_findings", None))
    ):
        raise RuntimeError("snapshotted claim validator contract is invalid")
    return module


def fsync_directory(path: Path) -> None:
    """Durably commit directory entries using macOS directory-fsync support."""
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def read_bounded_regular_file(path: Path, label: str, max_bytes: int) -> bytes:
    """Open one non-followed regular-file identity and read it within a cap."""
    if type(max_bytes) is not int or max_bytes < 0:
        raise RuntimeError(f"{label} has an invalid size limit")
    flags = (
        os.O_RDONLY
        | os.O_NONBLOCK
        | os.O_NOFOLLOW
        | getattr(os, "O_CLOEXEC", 0)
    )
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise RuntimeError(f"{label} is not a bounded regular file") from error
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise RuntimeError(f"{label} is not a regular file")
        if before.st_size > max_bytes:
            raise RuntimeError(f"{label} exceeds its size limit")
        chunks: list[bytes] = []
        observed = 0
        while observed <= max_bytes:
            chunk = os.read(
                descriptor,
                min(1024 * 1024, max_bytes + 1 - observed),
            )
            if not chunk:
                break
            chunks.append(chunk)
            observed += len(chunk)
        if observed > max_bytes:
            raise RuntimeError(f"{label} exceeds its size limit")
        after = os.fstat(descriptor)
        identity_before = (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
        )
        identity_after = (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        )
        if identity_before != identity_after or observed != after.st_size:
            raise RuntimeError(f"{label} changed while it was read")
        return b"".join(chunks)
    except OSError as error:
        raise RuntimeError(f"{label} is unreadable") from error
    finally:
        os.close(descriptor)


def rename_directory_exclusive(source: Path, destination: Path) -> None:
    """Atomically publish a sibling directory without replacing any entry."""
    if sys.platform != "darwin":
        raise RuntimeError(
            "exclusive release publication requires macOS renameatx_np"
        )
    libc = ctypes.CDLL(None, use_errno=True)
    try:
        renameatx_np = libc.renameatx_np
    except AttributeError as error:
        raise RuntimeError(
            "exclusive release publication is unavailable on this macOS"
        ) from error
    renameatx_np.argtypes = (
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    )
    renameatx_np.restype = ctypes.c_int
    at_fdcwd = -2
    rename_excl = 0x00000004
    result = renameatx_np(
        at_fdcwd,
        os.fsencode(source),
        at_fdcwd,
        os.fsencode(destination),
        rename_excl,
    )
    if result != 0:
        error_number = ctypes.get_errno()
        if error_number in {errno.EEXIST, errno.ENOTEMPTY}:
            raise FileExistsError(
                error_number,
                f"release output already exists: {destination}",
                destination,
            )
        raise OSError(
            error_number,
            f"exclusive release publication failed: {destination}",
            destination,
        )


def atomic_write(path: Path, data: bytes, mode: int = 0o644) -> None:
    """Persist all asset bytes, or leave neither the target nor a temp file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    descriptor: int | None = None
    try:
        descriptor = os.open(
            temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode
        )
        view = memoryview(data)
        offset = 0
        while offset < len(view):
            written = os.write(descriptor, view[offset:])
            if written <= 0:
                raise RuntimeError("zero-length release-asset write")
            offset += written
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = None
        os.replace(temporary, path)
        fsync_directory(path.parent)
    except BaseException:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def validate_review_clearance(
    clearance: dict, reviewed_commit: str, review_bytes: bytes
) -> None:
    expected_keys = {
        "schema",
        "status",
        "reviewed_commit",
        "completed_pass",
        "resolved_findings",
        "invalid_findings",
        "unresolved_release_blocking",
        "review_sha256",
    }
    if (
        not isinstance(clearance, dict)
        or set(clearance) != expected_keys
        or clearance.get("schema")
        != "jackal-spacecraft-independent-review-clearance-v175"
        or clearance.get("status") != "complete"
        or not re.fullmatch(
            r"[0-9a-f]{40}",
            clearance.get("reviewed_commit")
            if isinstance(clearance.get("reviewed_commit"), str)
            else "",
        )
        or type(clearance.get("completed_pass")) is not int
        or clearance["completed_pass"] < 1
        or type(clearance.get("resolved_findings")) is not int
        or clearance["resolved_findings"] < 0
        or type(clearance.get("invalid_findings")) is not int
        or clearance["invalid_findings"] < 0
        or type(clearance.get("unresolved_release_blocking")) is not int
        or clearance["unresolved_release_blocking"] != 0
        or not isinstance(clearance.get("review_sha256"), str)
        or re.fullmatch(r"[0-9a-f]{64}", clearance["review_sha256"]) is None
    ):
        raise RuntimeError("v1.7.5 independent review clearance incomplete")
    if not re.fullmatch(r"[0-9a-f]{40}", reviewed_commit):
        raise RuntimeError("reviewed commit is invalid")
    if clearance["reviewed_commit"] != reviewed_commit:
        raise RuntimeError("reviewed commit does not match independent review clearance")
    if clearance["review_sha256"] != sha256(review_bytes):
        raise RuntimeError("review report digest does not match independent review clearance")


def validate_review_report(
    review_bytes: bytes,
    reviewed_commit: str,
    producer_source_sha256: str,
    clearance: dict,
) -> None:
    try:
        review_text = review_bytes.decode("utf-8")
    except UnicodeDecodeError as error:
        raise RuntimeError("independent review report is not valid UTF-8") from error
    canonical_header = (
        "# JACKAL v1.7.5 spacecraft-burn internal independent review\n"
        "\n"
        "Review schema: jackal-spacecraft-independent-review-v175\n"
        "Status: complete\n"
        f"Reviewed commit: `{reviewed_commit}`\n"
        f"Producer source SHA-256: `{producer_source_sha256}`\n"
        f"Completed review passes: {clearance['completed_pass']}\n"
        f"Resolved findings: {clearance['resolved_findings']}\n"
        f"Invalid findings: {clearance['invalid_findings']}\n"
        "Unresolved release-blocking findings: 0\n"
        "Review class: internal independent code review, not external peer review\n"
        "\n"
    )
    if not review_text.startswith(canonical_header):
        raise RuntimeError("independent review report is incomplete or unbound")
    body = review_text[len(canonical_header):]
    metadata_labels = (
        "Review schema",
        "Status",
        "Reviewed commit",
        "Producer source SHA-256",
        "Completed review passes",
        "Resolved findings",
        "Invalid findings",
        "Unresolved release-blocking findings",
        "Review class",
    )
    duplicate_metadata = re.compile(
        r"(?im)^(?:"
        + "|".join(re.escape(label) for label in metadata_labels)
        + r")\s*:"
    )
    if duplicate_metadata.search(body):
        raise RuntimeError("independent review report contains duplicate metadata")
    section_bodies: dict[str, str] = {}
    previous = -1
    for marker in REVIEW_REQUIRED_SECTIONS:
        if body.count(marker + "\n") != 1:
            raise RuntimeError(
                "independent review report lacks canonical substantive sections"
            )
        position = body.index(marker + "\n")
        if position <= previous:
            raise RuntimeError(
                "independent review report sections are not in canonical order"
            )
        previous = position
    for index, marker in enumerate(REVIEW_REQUIRED_SECTIONS):
        start = body.index(marker + "\n") + len(marker) + 1
        end = (
            body.index(REVIEW_REQUIRED_SECTIONS[index + 1] + "\n")
            if index + 1 < len(REVIEW_REQUIRED_SECTIONS)
            else len(body)
        )
        section = body[start:end].strip()
        if (
            len(re.sub(r"\s+", " ", section)) < 20
            or re.search(r"(?i)\b(?:TODO|TBD|pending)\b", section)
        ):
            raise RuntimeError(
                f"independent review report section is incomplete: {marker}"
            )
        section_bodies[marker] = section
    findings = section_bodies["## Findings and dispositions"]
    expected_status_counts = {
        "resolved": clearance["resolved_findings"],
        "invalid": clearance["invalid_findings"],
    }
    expected_dispositions = sum(expected_status_counts.values())
    disposition_lines = [
        line for line in findings.splitlines() if line.startswith("Disposition:")
    ]
    disposition_pattern = re.compile(
        r"^Disposition: ([A-Z][A-Z0-9-]{2,31}) \| "
        r"status: (resolved|invalid) \| (\S.*)$"
    )
    dispositions = [disposition_pattern.fullmatch(line) for line in disposition_lines]
    if (
        len(disposition_lines) != expected_dispositions
        or any(match is None for match in dispositions)
    ):
        raise RuntimeError(
            "independent review report disposition count or schema is invalid"
        )
    disposition_rows = [match.groups() for match in dispositions if match is not None]
    identifiers = [identifier for identifier, _status, _detail in disposition_rows]
    observed_status_counts = {
        status: sum(row_status == status for _identifier, row_status, _detail in disposition_rows)
        for status in expected_status_counts
    }
    if (
        len(identifiers) != len(set(identifiers))
        or observed_status_counts != expected_status_counts
        or any(len(re.sub(r"\s+", " ", detail)) < 20 for _, _, detail in disposition_rows)
    ):
        raise RuntimeError("independent review report dispositions are invalid")
    zero_finding_statement = "No findings requiring disposition."
    if expected_dispositions == 0:
        if findings.count(zero_finding_statement) != 1:
            raise RuntimeError(
                "independent review report lacks zero-finding disposition statement"
            )
    elif zero_finding_statement in findings:
        raise RuntimeError("independent review report contradicts finding dispositions")
    source_review = section_bodies["## Full-file Picard/source review"]
    if "certify.py" not in source_review or "Picard" not in source_review:
        raise RuntimeError("independent review report lacks full-file Picard review")
    lean_review = section_bodies["## Lean correspondence"]
    if "Lean" not in lean_review:
        raise RuntimeError("independent review report lacks Lean correspondence")
    final_pass = section_bodies["## Final zero-finding pass"]
    if re.search(r"(?i)\bzero (?:new )?findings\b", final_pass) is None:
        raise RuntimeError("independent review report lacks final zero-finding pass")
    expected_final_result = (
        "Final pass result: pass "
        f"{clearance['completed_pass']} completed with zero new findings."
    )
    final_result_markers = [
        line
        for line in final_pass.splitlines()
        if all(token in line.lower() for token in ("final", "pass", "result"))
    ]
    if (
        final_result_markers != [expected_final_result]
        or final_pass.splitlines()[-1] != expected_final_result
    ):
        raise RuntimeError(
            "independent review report final pass result is invalid or unbound"
        )


def validate_release_binding(binding: dict) -> None:
    expected = {
        "request_digest": SPACECRAFT_REQUEST_DIGEST,
        "model_id": MODEL_ID,
        "epoch": CERTIFICATE_EPOCH,
        "nonce": PUBLICATION_NONCE,
    }
    if not isinstance(binding, dict) or any(
        binding.get(key) != value for key, value in expected.items()
    ):
        raise RuntimeError("v1.7.5 receipt release binding is invalid")


def validate_producer_source(receipt: dict, source_bytes: bytes) -> None:
    expected = receipt.get("source_sha256") if isinstance(receipt, dict) else None
    if (
        not isinstance(expected, str)
        or re.fullmatch(r"[0-9a-f]{64}", expected) is None
        or sha256(source_bytes) != expected
    ):
        raise RuntimeError("producer source digest does not match receipt")


def validate_formal_receipt(receipt: dict, claim_validator) -> None:
    if (
        not isinstance(receipt, dict)
        or receipt.get("schema") != "spacecraft-finite-burn-formal-receipt-v2"
        or receipt.get("formal_checker_status") != "ACCEPT"
    ):
        raise RuntimeError("release package requires a formally accepted baseline receipt")
    findings = claim_validator.document_findings(
        receipt, Path("spacecraft_burn_cert/evidence/baseline_receipt_v2.json")
    )
    binding = receipt.get("formal_checker")
    result_line = binding.get("result_line") if isinstance(binding, dict) else None
    match = re.fullmatch(
        r"ACCEPT theorem=spacecraft_burn_certified_safe status=formal-bounded "
        rf"margin_lo=([1-9][0-9]{{0,{MAX_JSON_INTEGER_DIGITS - 1}}}) "
        rf"margin_hi=([1-9][0-9]{{0,{MAX_JSON_INTEGER_DIGITS - 1}}}) "
        rf"model={re.escape(MODEL_ID)} epoch={re.escape(CERTIFICATE_EPOCH)}",
        result_line if isinstance(result_line, str) else "",
    )
    if (
        findings
        or not isinstance(binding, dict)
        or binding.get("theorem") != "spacecraft_burn_certified_safe"
        or match is None
        or int(match.group(1)) > int(match.group(2))
    ):
        raise RuntimeError("release package requires a formally accepted baseline receipt")


def validate_committed_baseline(
    receipt_bytes: bytes,
    witness_bytes: bytes,
    receipt: dict,
    expected_digests: dict[str, str],
    manifest_bytes: bytes,
) -> None:
    receipt_digest = sha256(receipt_bytes)
    if expected_digests.get(RECEIPT_NAME) != receipt_digest:
        raise RuntimeError("committed baseline receipt digest mismatch")
    if expected_digests.get(WITNESS_MANIFEST_NAME) != sha256(manifest_bytes):
        raise RuntimeError("committed witness manifest digest mismatch")
    manifest = strict_json_document(
        manifest_bytes, "committed witness manifest"
    )
    witness_digest = sha256(witness_bytes)
    if (
        not isinstance(manifest, dict)
        or manifest.get("schema") != "spacecraft-finite-burn-witness-manifest-v2"
        or manifest.get("release_asset") != WITNESS_NAME
        or manifest.get("sha256") != witness_digest
        or manifest.get("byte_size") != len(witness_bytes)
        or manifest.get("receipt_sha256") != receipt_digest
        or manifest.get("formal_checker") != receipt.get("formal_checker")
    ):
        raise RuntimeError("committed witness manifest does not bind staged baseline")


def validate_reviewed_tree_changes(paths: Sequence[str]) -> None:
    unexpected = sorted(set(paths) - set(REVIEW_ADMIN_PATHS))
    if unexpected:
        raise RuntimeError(
            "release tree differs from reviewed source tree: " + ", ".join(unexpected)
        )


def _git(args: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(GIT_EXECUTABLE), *GIT_GLOBAL_OPTIONS, *args],
        cwd=ROOT,
        env=GIT_ENVIRONMENT,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )


def _git_bytes(args: Sequence[str]) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [str(GIT_EXECUTABLE), *GIT_GLOBAL_OPTIONS, *args],
        cwd=ROOT,
        env=GIT_ENVIRONMENT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=30,
        check=False,
    )


def _git_object_digest(kind: str, body: bytes) -> str:
    header = f"{kind} {len(body)}\0".encode("ascii")
    return hashlib.sha1(header + body).hexdigest()


def _git_metadata_path(logical_path: str) -> Path:
    completed = _git(["rev-parse", "--git-path", logical_path])
    if completed.returncode != 0 or not completed.stdout.strip():
        raise RuntimeError("cannot resolve Git repository metadata")
    path = Path(completed.stdout.strip())
    if not path.is_absolute():
        path = ROOT / path
    return path


def validate_git_repository_provenance() -> None:
    local_config = _git(
        ["config", "--local", "--null", "--name-only", "--list", "--no-includes"]
    )
    if local_config.returncode != 0:
        raise RuntimeError("cannot inspect repository-local Git config")
    local_keys = [key for key in local_config.stdout.split("\0") if key]
    for key in local_keys:
        if any(
            pattern.fullmatch(key)
            for pattern in FORBIDDEN_LOCAL_GIT_CONFIG_PATTERNS
        ):
            raise RuntimeError(
                f"command-bearing local Git config is forbidden: {key}"
            )
    replacements = _git(["for-each-ref", "--format=%(refname)", "refs/replace"])
    if replacements.returncode != 0:
        raise RuntimeError("cannot inspect Git replacement object refs")
    if replacements.stdout.strip():
        raise RuntimeError("Git replacement object refs are forbidden")
    for logical_path, label in (
        ("info/grafts", "Git graft metadata"),
        ("objects/info/alternates", "Git alternate object metadata"),
    ):
        path = _git_metadata_path(logical_path)
        if path.is_symlink() or path.exists():
            raise RuntimeError(f"{label} is forbidden")


def validate_git_object_integrity(*commits: str) -> None:
    unique_commits = tuple(dict.fromkeys(commits))
    if not unique_commits or any(
        re.fullmatch(r"[0-9a-f]{40}", commit) is None
        for commit in unique_commits
    ):
        raise RuntimeError("Git object integrity roots are invalid")
    checked = _git(
        [
            "fsck",
            "--full",
            "--strict",
            "--no-reflogs",
            "--no-dangling",
            *unique_commits,
        ]
    )
    if checked.returncode != 0:
        raise RuntimeError("reachable Git object integrity check failed")


def _resolve_git_commit(commit: str, label: str) -> str:
    if re.fullmatch(r"[0-9a-f]{40}", commit) is None:
        raise RuntimeError(f"{label} commit must be 40 lowercase hex characters")
    object_type = _git(["cat-file", "-t", commit])
    commit_object = _git_bytes(["cat-file", "commit", commit])
    if (
        object_type.returncode != 0
        or object_type.stdout != "commit\n"
        or commit_object.returncode != 0
        or _git_object_digest("commit", commit_object.stdout) != commit
    ):
        raise RuntimeError(f"{label} commit is not an exact local Git commit object")
    first_line = commit_object.stdout.split(b"\n", 1)[0]
    match = re.fullmatch(rb"tree ([0-9a-f]{40})", first_line)
    if match is None:
        raise RuntimeError(f"{label} commit does not bind a canonical root tree")
    tree = match.group(1).decode("ascii")
    tree_type = _git(["cat-file", "-t", tree])
    tree_object = _git_bytes(["cat-file", "tree", tree])
    if (
        tree_type.returncode != 0
        or tree_type.stdout != "tree\n"
        or tree_object.returncode != 0
        or _git_object_digest("tree", tree_object.stdout) != tree
    ):
        raise RuntimeError(f"{label} commit root tree identity is invalid")
    return tree


def validate_git_release_binding(commit: str, reviewed_commit: str) -> None:
    validate_git_repository_provenance()
    _resolve_git_commit(commit, "release")
    _resolve_git_commit(reviewed_commit, "reviewed")
    validate_git_object_integrity(commit, reviewed_commit)
    head = _git(["rev-parse", "HEAD"])
    if head.returncode != 0 or head.stdout.strip() != commit:
        raise RuntimeError("release commit does not match the checked-out HEAD")
    ancestor = _git(["merge-base", "--is-ancestor", reviewed_commit, commit])
    if ancestor.returncode != 0:
        raise RuntimeError("reviewed commit is not an ancestor of the release commit")
    changed = _git(
        [
            "diff",
            "--no-ext-diff",
            "--no-textconv",
            "--name-only",
            reviewed_commit,
            commit,
            "--",
        ]
    )
    if changed.returncode != 0:
        raise RuntimeError("cannot compare reviewed source tree with release tree")
    validate_reviewed_tree_changes(
        [line for line in changed.stdout.splitlines() if line]
    )
    status = _git(["status", "--porcelain=v1", "--untracked-files=all"])
    if status.returncode != 0 or status.stdout:
        raise RuntimeError("release package requires a clean exact-commit worktree")


def strict_json_document(raw: bytes, label: str) -> dict:
    try:
        document = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=reject_duplicate_keys,
            parse_constant=reject_nonfinite_json,
            parse_float=reject_fractional_json,
            parse_int=parse_bounded_json_integer,
        )
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
        DuplicateJsonKey,
        OverflowError,
        RecursionError,
        ValueError,
    ) as error:
        raise RuntimeError(f"{label} is invalid JSON") from error
    try:
        require_bounded_json_tree(document)
    except ValueError as error:
        raise RuntimeError(f"{label} is invalid JSON") from error
    if not isinstance(document, dict):
        raise RuntimeError(f"{label} is invalid JSON")
    return document


def validate_release_metadata(
    metadata_bytes: bytes,
    notes_bytes: bytes,
    claim_validator,
) -> dict:
    metadata = strict_json_document(metadata_bytes, "release metadata")
    if set(metadata) != {"notes_path", "notes_sha256", "schema", "tag", "title"}:
        raise RuntimeError("release metadata has an invalid field set")
    canonical = (
        json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    if metadata_bytes != canonical:
        raise RuntimeError("release metadata is not canonical JSON")
    title = metadata.get("title")
    if (
        metadata.get("schema") != "jackal-spacecraft-burn-release-metadata-v1"
        or metadata.get("tag") != VERSION
        or metadata.get("notes_path") != RELEASE_NOTES_LOGICAL_PATH
        or metadata.get("notes_sha256") != sha256(notes_bytes)
        or not isinstance(title, str)
        or not title
        or len(title.encode("utf-8")) > 200
        or "\n" in title
        or "\r" in title
    ):
        raise RuntimeError("release metadata binding is invalid")
    metadata_findings = claim_validator.document_findings(
        metadata,
        Path(RELEASE_METADATA_LOGICAL_PATH),
    )
    if metadata_findings:
        raise RuntimeError(
            f"release metadata claim surface failed: {metadata_findings}"
        )
    try:
        notes = notes_bytes.decode("utf-8")
    except UnicodeDecodeError as error:
        raise RuntimeError("release notes are not UTF-8") from error
    notes_findings = claim_validator.string_findings(
        notes,
        Path(RELEASE_NOTES_LOGICAL_PATH),
        "$",
    )
    if notes_findings:
        raise RuntimeError(f"release notes claim surface failed: {notes_findings}")
    return metadata


def git_show_bytes(commit: str, logical_path: str) -> bytes:
    parts = Path(logical_path).parts
    if (
        not logical_path
        or logical_path.startswith("/")
        or ".." in parts
        or Path(logical_path).as_posix() != logical_path
    ):
        raise RuntimeError(f"invalid tracked release input path: {logical_path}")
    completed = _git_bytes(["cat-file", "blob", f"{commit}:{logical_path}"])
    if completed.returncode != 0:
        raise RuntimeError(
            f"tracked release input is absent from release commit: {logical_path}"
        )
    return completed.stdout


def committed_lean_paths(commit: str) -> set[str]:
    completed = _git_bytes(
        [
            "ls-tree",
            "-r",
            "-z",
            "--name-only",
            commit,
            "--",
            "proofs/lean",
        ]
    )
    if completed.returncode != 0:
        raise RuntimeError("cannot enumerate committed Lean source paths")
    try:
        paths = {
            raw.decode("utf-8")
            for raw in completed.stdout.split(b"\0")
            if raw
        }
    except UnicodeDecodeError as error:
        raise RuntimeError("committed Lean source path is not UTF-8") from error
    return {
        path
        for path in paths
        if path.startswith("proofs/lean/") and path.endswith(".lean")
    }


def lean_code_without_comments_or_strings(source: str) -> str:
    output: list[str] = []
    index = 0
    block_depth = 0
    in_string = False
    while index < len(source):
        char = source[index]
        pair = source[index : index + 2]
        if block_depth:
            if pair == "/-":
                output.extend("  ")
                block_depth += 1
                index += 2
            elif pair == "-/":
                output.extend("  ")
                block_depth -= 1
                index += 2
            else:
                output.append("\n" if char == "\n" else " ")
                index += 1
            continue
        if in_string:
            if char == "\\" and index + 1 < len(source):
                output.extend("  ")
                index += 2
            elif char == '"':
                output.append(" ")
                in_string = False
                index += 1
            else:
                output.append("\n" if char == "\n" else " ")
                index += 1
            continue
        if pair == "/-":
            output.extend("  ")
            block_depth = 1
            index += 2
        elif pair == "--":
            while index < len(source) and source[index] != "\n":
                output.append(" ")
                index += 1
        elif char == '"':
            output.append(" ")
            in_string = True
            index += 1
        else:
            output.append(char)
            index += 1
    if block_depth or in_string:
        raise RuntimeError("unterminated comment or string in committed Lean source")
    return "".join(output)


def parse_committed_lean_imports(logical_path: str, raw: bytes) -> list[str]:
    try:
        source = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise RuntimeError(
            f"committed Lean source is not UTF-8: {logical_path}"
        ) from error
    code = lean_code_without_comments_or_strings(source)
    imports: list[str] = []
    for line_number, line in enumerate(code.splitlines(), start=1):
        contains_import = re.search(r"\bimport\b", line) is not None
        match = re.fullmatch(r"\s*import\s+(.+?)\s*", line)
        if not contains_import:
            continue
        tokens = match.group(1).split() if match is not None else []
        if (
            match is None
            or not tokens
            or any(LEAN_MODULE_PATTERN.fullmatch(token) is None for token in tokens)
        ):
            raise RuntimeError(
                "unsupported import syntax in committed Lean source: "
                f"{logical_path}:{line_number}"
            )
        imports.extend(tokens)
    return imports


def validate_source_closure_classification(
    closure: object,
    committed_paths: set[str],
    source_bytes: Mapping[str, bytes] | None = None,
) -> None:
    casefold_paths: dict[str, str] = {}
    for logical_path in committed_paths:
        folded = logical_path.casefold()
        previous = casefold_paths.get(folded)
        if previous is not None and previous != logical_path:
            raise RuntimeError("committed local Lean paths have ambiguous casing")
        casefold_paths[folded] = logical_path
    rows = closure.get("files") if isinstance(closure, dict) else None
    root_modules = closure.get("root_modules") if isinstance(closure, dict) else None
    external_imports = (
        closure.get("external_imports") if isinstance(closure, dict) else None
    )
    if (
        not isinstance(rows, list)
        or not rows
        or root_modules != list(SPACECRAFT_ROOT_MODULES)
        or not isinstance(external_imports, list)
        or external_imports != sorted(set(external_imports))
        or any(
            not isinstance(module, str)
            or LEAN_MODULE_PATTERN.fullmatch(module) is None
            for module in external_imports
        )
    ):
        raise RuntimeError("proof identity Lean source closure classification is invalid")
    records: dict[str, dict] = {}
    record_paths: list[str] = []
    for row in rows:
        module = row.get("module") if isinstance(row, dict) else None
        logical_path = row.get("path") if isinstance(row, dict) else None
        imports = row.get("imports") if isinstance(row, dict) else None
        expected_path = (
            f"proofs/lean/{module.replace('.', '/')}.lean"
            if isinstance(module, str)
            else None
        )
        if (
            not isinstance(row, dict)
            or set(row) != {"bytes", "imports", "module", "path", "sha256"}
            or not isinstance(module, str)
            or LEAN_MODULE_PATTERN.fullmatch(module) is None
            or logical_path != expected_path
            or logical_path not in committed_paths
            or module in records
            or not isinstance(imports, list)
            or any(
                not isinstance(imported, str)
                or LEAN_MODULE_PATTERN.fullmatch(imported) is None
                for imported in imports
            )
        ):
            raise RuntimeError("proof identity Lean source closure row is invalid")
        if source_bytes is not None:
            raw = source_bytes.get(logical_path)
            if raw is None or parse_committed_lean_imports(logical_path, raw) != imports:
                raise RuntimeError(
                    f"proof identity Lean imports differ from committed source: {logical_path}"
                )
        records[module] = row
        record_paths.append(logical_path)
    if record_paths != sorted(record_paths):
        raise RuntimeError("proof identity Lean source closure rows are not canonical")
    pending = list(SPACECRAFT_ROOT_MODULES)
    reachable: set[str] = set()
    observed_external: set[str] = set()
    while pending:
        module = pending.pop()
        if module in reachable:
            continue
        row = records.get(module)
        if row is None:
            raise RuntimeError(
                f"proof identity omits reachable local Lean import: {module}"
            )
        reachable.add(module)
        for imported in row["imports"]:
            imported_path = f"proofs/lean/{imported.replace('.', '/')}.lean"
            local_path = casefold_paths.get(imported_path.casefold())
            if local_path is not None:
                if local_path != imported_path:
                    raise RuntimeError(
                        f"noncanonical committed local Lean import path: {local_path}"
                    )
                if imported not in records:
                    raise RuntimeError(
                        f"proof identity misclassifies local Lean import: {imported}"
                    )
                pending.append(imported)
            else:
                observed_external.add(imported)
    if reachable != set(records):
        raise RuntimeError("proof identity includes unreachable local Lean source")
    if observed_external != set(external_imports):
        raise RuntimeError("proof identity external Lean imports are misclassified")


def validate_generator_closure(
    generator: object, file_bytes: Mapping[str, bytes]
) -> None:
    files = generator.get("files") if isinstance(generator, dict) else None
    if (
        not isinstance(generator, dict)
        or set(generator) != {"definition", "files"}
        or generator.get("definition") != GENERATOR_CLOSURE_DEFINITION
        or not isinstance(files, list)
        or len(files) != len(GENERATOR_CLOSURE_PATHS)
    ):
        raise RuntimeError("proof identity generator closure is invalid")
    for row, expected_path in zip(files, GENERATOR_CLOSURE_PATHS):
        if (
            not isinstance(row, dict)
            or set(row) != {"path", "sha256"}
            or row.get("path") != expected_path
            or row.get("sha256") != sha256(file_bytes.get(expected_path, b""))
            or not file_bytes.get(expected_path)
        ):
            raise RuntimeError("proof identity generator closure is invalid")


def tracked_input_paths(commit: str) -> tuple[str, ...]:
    identity = strict_json_document(
        git_show_bytes(commit, IDENTITY_LOGICAL_PATH), "committed proof identity"
    )
    closure = identity.get("source_closure")
    rows = closure.get("files") if isinstance(closure, dict) else None
    toolchain = identity.get("toolchain")
    configurations = (
        toolchain.get("configuration_files") if isinstance(toolchain, dict) else None
    )
    generator = identity.get("generator")
    if (
        not isinstance(rows, list)
        or not rows
        or not isinstance(configurations, list)
        or not configurations
    ):
        raise RuntimeError("proof identity does not enumerate tracked release inputs")
    generator_bytes = {
        path: git_show_bytes(commit, path) for path in GENERATOR_CLOSURE_PATHS
    }
    validate_generator_closure(generator, generator_bytes)
    paths = set(STATIC_TRACKED_INPUT_PATHS)
    paths.update(GENERATOR_CLOSURE_PATHS)
    for row in (*rows, *configurations):
        logical_path = row.get("path") if isinstance(row, dict) else None
        parts = Path(logical_path).parts if isinstance(logical_path, str) else ()
        if (
            not isinstance(logical_path, str)
            or logical_path.startswith("/")
            or ".." in parts
            or parts[:2] != ("proofs", "lean")
            or Path(logical_path).as_posix() != logical_path
        ):
            raise RuntimeError("proof identity contains an invalid tracked input path")
        paths.add(logical_path)
    closure_sources = {
        row["path"]: git_show_bytes(commit, row["path"])
        for row in rows
        if isinstance(row, dict) and isinstance(row.get("path"), str)
    }
    validate_source_closure_classification(
        closure,
        committed_lean_paths(commit),
        closure_sources,
    )
    return tuple(sorted(paths))


def snapshot_tracked_inputs(commit: str) -> dict[str, bytes]:
    snapshot: dict[str, bytes] = {}
    for logical_path in tracked_input_paths(commit):
        committed = git_show_bytes(commit, logical_path)
        if len(committed) > MAX_TRACKED_INPUT_BYTES:
            raise RuntimeError(
                f"tracked release input exceeds its size limit: {logical_path}"
            )
        working_path = ROOT / logical_path
        working = read_bounded_regular_file(
            working_path,
            f"tracked release input {logical_path}",
            MAX_TRACKED_INPUT_BYTES,
        )
        if working != committed:
            raise RuntimeError(
                f"tracked release input differs from release commit: {logical_path}"
            )
        snapshot[logical_path] = committed
    return snapshot


def _after_tracked_input_snapshot(_snapshot: Mapping[str, bytes]) -> None:
    """No-op seam used to exercise post-binding mutation refusal."""


def validated_release_snapshot(
    commit: str, reviewed_commit: str
) -> dict[str, bytes]:
    validate_git_release_binding(commit, reviewed_commit)
    snapshot = snapshot_tracked_inputs(commit)
    _after_tracked_input_snapshot(snapshot)
    return snapshot


def validate_tracked_inputs_unchanged(
    commit: str, snapshot: Mapping[str, bytes]
) -> None:
    validate_git_object_integrity(commit)
    expected_paths = tracked_input_paths(commit)
    if tuple(sorted(snapshot)) != expected_paths:
        raise RuntimeError("tracked release input set changed after snapshot")
    for logical_path in expected_paths:
        expected = snapshot[logical_path]
        if git_show_bytes(commit, logical_path) != expected:
            raise RuntimeError(
                f"release commit bytes changed after snapshot: {logical_path}"
            )
        path = ROOT / logical_path
        try:
            observed = read_bounded_regular_file(
                path,
                f"tracked release input {logical_path}",
                MAX_TRACKED_INPUT_BYTES,
            )
        except RuntimeError as error:
            raise RuntimeError(
                f"tracked release input changed after snapshot: {logical_path}"
            ) from error
        if observed != expected:
            raise RuntimeError(
                f"tracked release input changed after snapshot: {logical_path}"
            )


def write_release_assets(
    output: Path,
    assets: Mapping[str, bytes],
    sums: bytes,
    commit: str,
    snapshot: Mapping[str, bytes],
) -> None:
    validate_tracked_inputs_unchanged(commit, snapshot)
    if os.path.lexists(output):
        raise FileExistsError(f"release output already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(
        tempfile.mkdtemp(prefix=f".{output.name}.tmp-", dir=output.parent)
    )
    try:
        for name, data in assets.items():
            atomic_write(temporary / name, data)
        atomic_write(temporary / "SHA256SUMS", sums)
        temporary.chmod(0o755)
        fsync_directory(temporary)
        fsync_directory(output.parent)
        if os.path.lexists(output):
            raise FileExistsError(f"release output already exists: {output}")
        rename_directory_exclusive(temporary, output)
        fsync_directory(output.parent)
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def archive_entries(
    checker_bytes: bytes,
    identity_bytes: bytes,
    identity: dict,
    request_bytes: bytes,
    producer_source_bytes: bytes,
    tracked_inputs: Mapping[str, bytes],
) -> dict[str, tuple[bytes, int]]:
    validate_generator_closure(identity.get("generator"), tracked_inputs)
    prefix = "jackal-spacecraft-burn-v1.7.5-verifier-macos-arm64"
    entries: dict[str, tuple[bytes, int]] = {
        f"{prefix}/bin/jackal_spacecraft_burn_check": (checker_bytes, 0o755),
        f"{prefix}/verifier/verify_receipt.py": (
            tracked_inputs[VERIFIER_LOGICAL_PATH],
            0o644,
        ),
        f"{prefix}/verifier/witness_codec.py": (
            tracked_inputs[WITNESS_CODEC_LOGICAL_PATH],
            0o644,
        ),
        f"{prefix}/producer/certify.py": (
            producer_source_bytes,
            0o644,
        ),
        f"{prefix}/producer/witness_codec.py": (
            tracked_inputs[WITNESS_CODEC_LOGICAL_PATH],
            0o644,
        ),
        f"{prefix}/evidence/{PROOF_NAME}": (identity_bytes, 0o644),
        f"{prefix}/request_v2.json": (request_bytes, 0o644),
        f"{prefix}/proofs/lean-toolchain": (
            tracked_inputs["proofs/lean/lean-toolchain"],
            0o644,
        ),
        f"{prefix}/proofs/lakefile.toml": (
            tracked_inputs["proofs/lean/lakefile.toml"],
            0o644,
        ),
        f"{prefix}/proofs/lake-manifest.json": (
            tracked_inputs["proofs/lean/lake-manifest.json"],
            0o644,
        ),
        f"{prefix}/{GENERATOR_LOGICAL_PATH}": (
            tracked_inputs[GENERATOR_LOGICAL_PATH],
            0o644,
        ),
        f"{prefix}/{GENERATOR_ENGINE_LOGICAL_PATH}": (
            tracked_inputs[GENERATOR_ENGINE_LOGICAL_PATH],
            0o644,
        ),
    }
    rows = identity.get("source_closure", {}).get("files")
    if not isinstance(rows, list) or not rows:
        raise RuntimeError("proof identity lacks source closure")
    for row in rows:
        logical_path = row.get("path") if isinstance(row, dict) else None
        if not isinstance(logical_path, str) or logical_path not in tracked_inputs:
            raise RuntimeError("proof identity source binding is absent from snapshot")
        source_bytes = tracked_inputs[logical_path]
        if (
            row.get("bytes") != len(source_bytes)
            or row.get("sha256") != sha256(source_bytes)
        ):
            raise RuntimeError("proof identity source binding mismatch")
        relative = Path(logical_path).relative_to("proofs/lean")
        entries[f"{prefix}/proofs/{relative.as_posix()}"] = (source_bytes, 0o644)
    return entries


def verification_text(
    commit: str,
    reviewed_commit: str,
    receipt_sha: str,
    witness_sha: str,
    proof_file_sha: str,
    proof_internal_sha: str,
    review_sha: str,
    review_clearance_sha: str,
    binding: dict[str, str],
) -> bytes:
    archive_root = "jackal-spacecraft-burn-v1.7.5-verifier-macos-arm64"
    text = f"""# JACKAL v1.7.5 spacecraft certificate verification

Independently confirm that annotated tag `v1.7.5` resolves to release merge
commit `{commit}`. The internal independent code review (not external peer
review) binds reviewed source commit `{reviewed_commit}`. The certificate and
checker epoch are also `v1.7.5`.

Public verdict: {QUALIFIED_VERDICT}.

Pinned identities:

- receipt SHA-256: `{receipt_sha}`
- witness SHA-256: `{witness_sha}`
- proof identity file SHA-256: `{proof_file_sha}`
- proof identity internal digest: `{proof_internal_sha}`
- independent review report SHA-256: `{review_sha}`
- machine-readable review clearance SHA-256: `{review_clearance_sha}`
- request digest: `{binding["request_digest"]}`
- model: `{binding["model_id"]}`
- epoch: `{binding["epoch"]}`
- nonce: `{binding["nonce"]}`

From the directory containing all downloaded release assets, run exactly:

```sh
set -eu
# SHA256SUMS checks consistency/integrity only; it is not a signature and does
# not authenticate the release. Verify the annotated tag-to-commit relation
# independently before relying on these files.
shasum -a 256 -c SHA256SUMS
ARCHIVE_ROOT={archive_root}
test ! -e "$ARCHIVE_ROOT"
tar -xzf {ARCHIVE_NAME}
"$ARCHIVE_ROOT/bin/jackal_spacecraft_burn_check" \\
  baseline_witness_v2.cert \\
  {binding["request_digest"]} \\
  {binding["model_id"]} \\
  {binding["epoch"]}
/usr/bin/python3 -I -B "$ARCHIVE_ROOT/verifier/verify_receipt.py" \\
  baseline_receipt_v2.json \\
  --source "$ARCHIVE_ROOT/producer/certify.py" \\
  --request "$ARCHIVE_ROOT/request_v2.json" \\
  --witness baseline_witness_v2.cert \\
  --checker "$ARCHIVE_ROOT/bin/jackal_spacecraft_burn_check" \\
  --proof-identity "$ARCHIVE_ROOT/evidence/{PROOF_NAME}" \\
  --expected-receipt-sha256 {receipt_sha} \\
  --expected-proof-file-sha256 {proof_file_sha} \\
  --expected-proof-identity-sha256 {proof_internal_sha} \\
  --expected-request-digest {binding["request_digest"]} \\
  --expected-model-id {binding["model_id"]} \\
  --expected-epoch {binding["epoch"]} \\
  --nonce {binding["nonce"]} \\
  --output independent_verification_readback_v175.json
```

The direct checker command is diagnostic and must emit one
`ACCEPT theorem=spacecraft_burn_certified_safe status=formal-bounded` line.
The outer verifier is authoritative and exits zero only for `status: ACCEPT`;
any mismatch refuses.

This theorem is conditional on the encoded ODE model and supplied bounds. It
does not establish physical-model adequacy, input truth, omitted perturbations,
actuator behavior, or source-to-native compiler correctness.
"""
    return text.encode("utf-8")


JSON_LOGICAL_PATHS = {
    RECEIPT_NAME: Path("spacecraft_burn_cert/evidence/baseline_receipt_v2.json"),
    "independent_verification_v2.json": Path(
        "spacecraft_burn_cert/evidence/independent_verification_v2.json"
    ),
    "instrument_validation_v2.json": Path(
        "spacecraft_burn_cert/evidence/instrument_validation_v2.json"
    ),
    "mutation_aba_v2.json": Path("spacecraft_burn_cert/evidence/mutation_aba_v2.json"),
    PROOF_NAME: Path("release/evidence/spacecraft_burn_proof_identity_v1.json"),
    REVIEW_CLEARANCE_NAME: Path(
        "release/evidence/spacecraft_burn_review_clearance_v175.json"
    ),
    "request_v2.json": Path("spacecraft_burn_cert/request_v2.json"),
}


def assert_release_claims(name: str, data: bytes, claim_validator) -> None:
    if name in JSON_LOGICAL_PATHS:
        payload = strict_json_document(
            data, f"release claim surface is invalid JSON: {name}"
        )
        findings = claim_validator.document_findings(
            payload, JSON_LOGICAL_PATHS[name]
        )
    elif name.endswith(".md"):
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as error:
            raise RuntimeError(f"release claim surface is not UTF-8: {name}") from error
        findings = claim_validator.string_findings(text, Path(name), "$")
    else:
        return
    if findings:
        raise RuntimeError(f"release claim surface failed: {name}: {findings}")


def validate_auxiliary_documents(
    documents: Mapping[str, dict],
    receipt: dict,
    bindings: Mapping[str, str],
    *,
    expected_independent: dict,
    expected_instrument: dict,
    expected_source_mutants: Mapping[str, Mapping[str, object]],
    expected_witness_records: Mapping[str, Mapping[str, object]],
) -> None:
    if set(documents) != set(AUXILIARY_EVIDENCE_NAMES):
        raise RuntimeError("auxiliary evidence set is incomplete")

    independent = documents["independent_verification_v2.json"]
    independent_binding = independent.get("binding")
    required_independent_binding = {
        key: bindings[key]
        for key in (
            "receipt_sha256",
            "witness_sha256",
            "checker_sha256",
            "proof_identity_file_sha256",
            "proof_identity_digest_sha256",
            "request_digest",
            "model_id",
            "epoch",
            "nonce",
        )
    }
    if (
        independent != expected_independent
        or independent.get("status") != "ACCEPT"
        or independent.get("reasons") != []
        or not isinstance(independent_binding, dict)
        or any(
            independent_binding.get(key) != value
            for key, value in required_independent_binding.items()
        )
    ):
        raise RuntimeError(
            "auxiliary evidence independent verification is not reproducible or bound"
        )

    instrument = documents["instrument_validation_v2.json"]
    if (
        instrument != expected_instrument
        or instrument.get("schema")
        != "spacecraft-finite-burn-instrument-validation-v2"
        or instrument.get("status") != "PASS"
        or instrument.get("baseline_receipt_sha256")
        != bindings["receipt_sha256"]
        or instrument.get("formal_checker_status") != "ACCEPT"
        or instrument.get("formal_checker_binding") != receipt.get("formal_checker")
        or instrument.get("formal_decisive_margin")
        != receipt.get("formal_decisive_margin")
        or not all(
            isinstance(instrument.get(section), dict)
            and instrument[section].get("status") == "PASS"
            for section in (
                "reconciliation",
                "arithmetic_corpus",
                "answer_controls",
                "analytic_mass",
                "corner_diagnostics",
                "step_refinement",
            )
        )
    ):
        raise RuntimeError(
            "auxiliary evidence instrument validation is not reproducible or bound"
        )

    mutation = documents["mutation_aba_v2.json"]
    mutation_keys = {
        "schema",
        "status",
        "baseline_source_sha256",
        "final_source_sha256",
        "baseline_verifier_before",
        "baseline_verifier_before_process",
        "mutations",
        "witness_mutations",
        "baseline_verifier_after",
        "baseline_verifier_after_process",
    }
    source_records = mutation.get("mutations")
    witness_records = mutation.get("witness_mutations")
    if (
        set(mutation) != mutation_keys
        or mutation.get("schema") != "spacecraft-finite-burn-mutation-aba-v2"
        or mutation.get("status") != "PASS"
        or mutation.get("baseline_source_sha256") != bindings["source_sha256"]
        or mutation.get("final_source_sha256") != bindings["source_sha256"]
        or mutation.get("baseline_verifier_before") != expected_independent
        or mutation.get("baseline_verifier_after") != expected_independent
        or not isinstance(source_records, list)
        or not isinstance(witness_records, list)
    ):
        raise RuntimeError("auxiliary evidence mutation ABA result is invalid or unbound")

    process_keys = {
        "returncode",
        "timed_out",
        "output_sha256",
        "output_limited",
        "contract_valid",
    }
    expected_baseline_output_sha256 = sha256(
        (json.dumps(expected_independent, sort_keys=True, indent=2) + "\n").encode(
            "utf-8"
        )
    )
    for field in (
        "baseline_verifier_before_process",
        "baseline_verifier_after_process",
    ):
        process = mutation.get(field)
        if (
            not isinstance(process, dict)
            or set(process) != process_keys
            or type(process.get("returncode")) is not int
            or process.get("returncode") != 0
            or process.get("timed_out") is not False
            or process.get("output_limited") is not False
            or process.get("contract_valid") is not True
            or type(process.get("output_sha256")) is not str
            or process["output_sha256"] != expected_baseline_output_sha256
        ):
            raise RuntimeError("auxiliary evidence baseline verifier process is invalid")

    source_record_keys = {
        "mutation",
        "bug",
        "expected_reason",
        "a_before_sha256",
        "b_sha256",
        "a_after_sha256",
        "restored",
        "restored_contract_test_passed",
        "restored_contract_test_output_limited",
        "mutant_tests_failed",
        "mutant_tests_timed_out",
        "mutant_tests_output_limited",
        "reason_observed",
        "mutant_test_output_sha256",
        "detection_boundary",
        "caught",
    }
    if [record.get("mutation") for record in source_records if isinstance(record, dict)] != list(
        expected_source_mutants
    ) or len(source_records) != len(expected_source_mutants):
        raise RuntimeError("auxiliary evidence source mutation inventory is invalid")
    for record in source_records:
        name = record.get("mutation") if isinstance(record, dict) else None
        expected_mutant = expected_source_mutants.get(name, {})
        if (
            not isinstance(record, dict)
            or set(record) != source_record_keys
            or name not in expected_source_mutants
            or record != expected_mutant
            or record.get("a_before_sha256") != bindings["source_sha256"]
            or record.get("a_after_sha256") != bindings["source_sha256"]
            or record.get("b_sha256") != expected_mutant.get("b_sha256")
            or record.get("b_sha256") == bindings["source_sha256"]
            or record.get("bug") != expected_mutant.get("bug")
            or record.get("expected_reason")
            != expected_mutant.get("expected_reason")
            or record.get("restored") is not True
            or record.get("restored_contract_test_passed") is not True
            or record.get("restored_contract_test_output_limited") is not False
            or record.get("mutant_tests_failed") is not True
            or record.get("mutant_tests_timed_out") is not False
            or record.get("mutant_tests_output_limited") is not False
            or record.get("reason_observed") is not True
            or record.get("caught") is not True
            or record.get("detection_boundary")
            != "source contract tests; formal publication requires separately pinned immutable bytes"
        ):
            raise RuntimeError("auxiliary evidence source mutation record is invalid")

    witness_record_keys = {
        "mutation",
        "original_sha256",
        "mutant_sha256",
        "checker_refused",
        "checker_returncode",
        "checker_timed_out",
        "checker_output_sha256",
        "checker_output_limited",
        "checker_output_excerpt",
        "outer_verifier",
        "outer_verifier_returncode",
        "outer_verifier_timed_out",
        "outer_verifier_output_sha256",
        "outer_verifier_output_limited",
        "caught",
    }
    if [record.get("mutation") for record in witness_records if isinstance(record, dict)] != list(
        expected_witness_records
    ) or len(witness_records) != len(expected_witness_records):
        raise RuntimeError("auxiliary evidence witness mutation inventory is invalid")
    for record in witness_records:
        name = record.get("mutation") if isinstance(record, dict) else None
        expected_record = expected_witness_records.get(name, {})
        if (
            not isinstance(record, dict)
            or set(record) != witness_record_keys
            or name not in expected_witness_records
            or record != expected_record
            or record.get("original_sha256") != bindings["witness_sha256"]
            or record.get("mutant_sha256") == bindings["witness_sha256"]
            or record.get("checker_refused") is not True
            or type(record.get("checker_returncode")) is not int
            or record.get("checker_returncode") != 1
            or record.get("checker_timed_out") is not False
            or record.get("checker_output_limited") is not False
            or type(record.get("checker_output_sha256")) is not str
            or re.fullmatch(r"[0-9a-f]{64}", record["checker_output_sha256"])
            is None
            or record.get("outer_verifier")
            != {"status": "REFUSED", "reasons": ["witness-hash-mismatch"]}
            or type(record.get("outer_verifier_returncode")) is not int
            or record.get("outer_verifier_returncode") != 2
            or record.get("outer_verifier_timed_out") is not False
            or record.get("outer_verifier_output_limited") is not False
            or type(record.get("outer_verifier_output_sha256")) is not str
            or re.fullmatch(
                r"[0-9a-f]{64}", record["outer_verifier_output_sha256"]
            ) is None
            or record.get("caught") is not True
        ):
            raise RuntimeError("auxiliary evidence witness mutation record is invalid")


def _materialize_bytes(path: Path, data: bytes, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    path.chmod(mode)


def reproduce_auxiliary_validators(
    tracked_inputs: Mapping[str, bytes],
    receipt_bytes: bytes,
    witness_bytes: bytes,
    checker_bytes: bytes,
    binding: Mapping[str, str],
) -> tuple[dict, dict]:
    validate_publication_runtime(
        strict_json_document(
            tracked_inputs[IDENTITY_LOGICAL_PATH],
            "snapshotted proof identity",
        )
    )
    with tempfile.TemporaryDirectory(prefix="jackal-release-validation-") as directory:
        private = Path(directory)
        for logical_path, data in tracked_inputs.items():
            _materialize_bytes(private / logical_path, data)
        receipt_path = private / "staged" / RECEIPT_NAME
        witness_path = private / "staged" / WITNESS_NAME
        checker_path = private / "checker" / "jackal_spacecraft_burn_check"
        independent_path = private / "independent.json"
        instrument_path = private / "instrument.json"
        _materialize_bytes(receipt_path, receipt_bytes)
        _materialize_bytes(witness_path, witness_bytes)
        _materialize_bytes(checker_path, checker_bytes, 0o700)
        environment = {
            "LANG": "C",
            "LC_ALL": "C",
            "PATH": "/usr/bin:/bin",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONHASHSEED": "0",
            "TZ": "UTC",
        }
        verifier_command = (
            sys.executable,
            "-I",
            "-B",
            str(private / VERIFIER_LOGICAL_PATH),
            str(receipt_path),
            "--source",
            str(private / PRODUCER_LOGICAL_PATH),
            "--request",
            str(private / REQUEST_LOGICAL_PATH),
            "--witness",
            str(witness_path),
            "--checker",
            str(checker_path),
            "--proof-identity",
            str(private / IDENTITY_LOGICAL_PATH),
            "--expected-receipt-sha256",
            sha256(receipt_bytes),
            "--expected-proof-file-sha256",
            binding["proof_identity_file_sha256"],
            "--expected-proof-identity-sha256",
            binding["proof_identity_digest_sha256"],
            "--expected-request-digest",
            binding["request_digest"],
            "--expected-model-id",
            binding["model_id"],
            "--expected-epoch",
            binding["epoch"],
            "--nonce",
            binding["nonce"],
            "--output",
            str(independent_path),
        )
        verifier = subprocess.run(
            verifier_command,
            cwd=private,
            env=environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=300,
            check=False,
        )
        if verifier.returncode != 0 or not independent_path.is_file():
            raise RuntimeError(
                "authoritative independent verification refused staged release inputs"
            )
        validator = subprocess.run(
            (
                sys.executable,
                "-I",
                "-B",
                str(private / VALIDATION_LOGICAL_PATH),
                "--baseline",
                str(receipt_path),
                "--output",
                str(instrument_path),
            ),
            cwd=private,
            env=environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=300,
            check=False,
        )
        if validator.returncode != 0 or not instrument_path.is_file():
            raise RuntimeError(
                "authoritative instrument validation refused staged release inputs"
            )
        return (
            strict_json_document(
                independent_path.read_bytes(), "independent verification replay"
            ),
            strict_json_document(
                instrument_path.read_bytes(), "instrument validation replay"
            ),
        )


def _load_snapshot_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load authoritative snapshot module: {path.name}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(name, None)
        raise
    return module


def reproduce_mutation_inputs(
    tracked_inputs: Mapping[str, bytes],
    producer_source_bytes: bytes,
    witness_bytes: bytes,
    checker_bytes: bytes,
    binding: Mapping[str, str],
) -> tuple[
    dict[str, dict[str, object]],
    dict[str, dict[str, object]],
]:
    with tempfile.TemporaryDirectory(prefix="jackal-release-mutations-") as directory:
        private = Path(directory)
        for logical_path, data in tracked_inputs.items():
            _materialize_bytes(private / logical_path, data)
        witness_path = private / "staged" / WITNESS_NAME
        checker_path = private / "checker" / "jackal_spacecraft_burn_check"
        _materialize_bytes(witness_path, witness_bytes)
        _materialize_bytes(checker_path, checker_bytes, 0o700)
        mutation_path = private / MUTATION_LOGICAL_PATH
        codec_path = private / WITNESS_CODEC_LOGICAL_PATH
        codec_name = f"_jackal_snapshot_codec_{os.getpid()}_{id(private)}"
        mutation_name = f"_jackal_snapshot_mutation_{os.getpid()}_{id(private)}"
        codec = _load_snapshot_module(codec_name, codec_path)
        mutation = _load_snapshot_module(mutation_name, mutation_path)
        if tracked_inputs[PRODUCER_LOGICAL_PATH] != producer_source_bytes:
            raise RuntimeError("mutation source snapshot does not match producer")
        source_mutants = {
            name: mutation.exercise_mutation(name) for name in mutation.MUTATIONS
        }
        previous_package = sys.modules.get("spacecraft_burn_cert")
        previous_codec = sys.modules.get("spacecraft_burn_cert.witness_codec")
        fake_package = types.ModuleType("spacecraft_burn_cert")
        fake_package.witness_codec = codec
        sys.modules["spacecraft_burn_cert"] = fake_package
        sys.modules["spacecraft_burn_cert.witness_codec"] = codec
        try:
            formal_inputs = mutation.FormalInputs(
                private / BASELINE_RECEIPT_LOGICAL_PATH,
                private / REQUEST_LOGICAL_PATH,
                witness_path,
                checker_path,
                private / IDENTITY_LOGICAL_PATH,
                sha256(tracked_inputs[BASELINE_RECEIPT_LOGICAL_PATH]),
                binding["proof_identity_file_sha256"],
                binding["proof_identity_digest_sha256"],
                binding["request_digest"],
                binding["model_id"],
                binding["epoch"],
                binding["nonce"],
            )
            witness_records = {
                name: mutation.exercise_witness_mutation(name, formal_inputs)
                for name in ("corruption", "chain", "coverage")
            }
        finally:
            if previous_package is None:
                sys.modules.pop("spacecraft_burn_cert", None)
            else:
                sys.modules["spacecraft_burn_cert"] = previous_package
            if previous_codec is None:
                sys.modules.pop("spacecraft_burn_cert.witness_codec", None)
            else:
                sys.modules["spacecraft_burn_cert.witness_codec"] = previous_codec
            sys.modules.pop(codec_name, None)
            sys.modules.pop(mutation_name, None)
    return source_mutants, witness_records


def validate_auxiliary_evidence(
    auxiliary_bytes: Mapping[str, bytes],
    receipt_bytes: bytes,
    receipt: dict,
    witness_bytes: bytes,
    checker_bytes: bytes,
    producer_source_bytes: bytes,
    tracked_inputs: Mapping[str, bytes],
) -> dict[str, bytes]:
    documents = {
        name: strict_json_document(data, f"staged {name}")
        for name, data in auxiliary_bytes.items()
    }
    binding = receipt["formal_checker"]
    expected_independent, expected_instrument = reproduce_auxiliary_validators(
        tracked_inputs, receipt_bytes, witness_bytes, checker_bytes, binding
    )
    source_mutants, witness_records = reproduce_mutation_inputs(
        tracked_inputs,
        producer_source_bytes,
        witness_bytes,
        checker_bytes,
        binding,
    )
    bindings = {
        "receipt_sha256": sha256(receipt_bytes),
        "witness_sha256": sha256(witness_bytes),
        "checker_sha256": sha256(checker_bytes),
        "proof_identity_file_sha256": sha256(
            tracked_inputs[IDENTITY_LOGICAL_PATH]
        ),
        "proof_identity_digest_sha256": binding[
            "proof_identity_digest_sha256"
        ],
        "request_digest": sha256(tracked_inputs[REQUEST_LOGICAL_PATH]),
        "model_id": binding["model_id"],
        "epoch": binding["epoch"],
        "nonce": binding["nonce"],
        "source_sha256": sha256(producer_source_bytes),
    }
    validate_auxiliary_documents(
        documents,
        receipt,
        bindings,
        expected_independent=expected_independent,
        expected_instrument=expected_instrument,
        expected_source_mutants=source_mutants,
        expected_witness_records=witness_records,
    )
    return dict(auxiliary_bytes)


def committed_evidence_digests_from_snapshot(raw: bytes) -> dict[str, str]:
    try:
        lines = raw.decode("ascii").splitlines()
    except UnicodeDecodeError as error:
        raise RuntimeError("committed evidence checksum manifest is invalid") from error
    result: dict[str, str] = {}
    for line in lines:
        fields = line.split(maxsplit=1)
        if len(fields) != 2:
            raise RuntimeError("committed evidence checksum manifest is invalid")
        digest, name = fields
        name = name.strip()
        if (
            re.fullmatch(r"[0-9a-f]{64}", digest) is None
            or Path(name).name != name
            or name in result
        ):
            raise RuntimeError("committed evidence checksum manifest is invalid")
        result[name] = digest
    expected_names = {
        RECEIPT_NAME,
        WITNESS_MANIFEST_NAME,
        *AUXILIARY_EVIDENCE_NAMES,
    }
    if set(result) != expected_names:
        raise RuntimeError("committed evidence checksum manifest is incomplete")
    return result


def snapshot_staged_inputs(staging: Path) -> dict[str, bytes]:
    result: dict[str, bytes] = {}
    for name in (RECEIPT_NAME, WITNESS_NAME, *AUXILIARY_EVIDENCE_NAMES):
        path = staging / name
        limit = (
            MAX_STAGED_WITNESS_BYTES
            if name == WITNESS_NAME
            else MAX_STAGED_JSON_BYTES
        )
        result[name] = read_bounded_regular_file(
            path, f"staged release input {name}", limit
        )
    return result


def build(
    staging: Path, output: Path, commit: str, reviewed_commit: str
) -> dict[str, str]:
    if os.path.lexists(output):
        raise FileExistsError(f"release output already exists: {output}")
    tracked_inputs = validated_release_snapshot(commit, reviewed_commit)
    claim_validator = load_claim_validator(
        tracked_inputs[CLAIM_GATE_LOGICAL_PATH]
    )
    validate_release_metadata(
        tracked_inputs[RELEASE_METADATA_LOGICAL_PATH],
        tracked_inputs[RELEASE_NOTES_LOGICAL_PATH],
        claim_validator,
    )
    staged_inputs = snapshot_staged_inputs(staging)
    try:
        review_bytes = tracked_inputs[REVIEW_LOGICAL_PATH]
        clearance_bytes = tracked_inputs[REVIEW_CLEARANCE_LOGICAL_PATH]
        clearance = strict_json_document(clearance_bytes, "review clearance")
    except (KeyError, RuntimeError) as error:
        raise RuntimeError("v1.7.5 independent review clearance incomplete") from error
    validate_review_clearance(clearance, reviewed_commit, review_bytes)

    receipt_bytes = staged_inputs[RECEIPT_NAME]
    witness_bytes = staged_inputs[WITNESS_NAME]
    receipt = strict_json_document(receipt_bytes, "staged baseline receipt")
    identity_bytes = tracked_inputs[IDENTITY_LOGICAL_PATH]
    identity = strict_json_document(identity_bytes, "proof identity")
    validate_publication_runtime(identity)
    checker_bytes = read_bounded_regular_file(
        CHECKER, "live formal checker", MAX_CHECKER_BYTES
    )
    request_bytes = tracked_inputs[REQUEST_LOGICAL_PATH]
    producer_source_bytes = tracked_inputs[PRODUCER_LOGICAL_PATH]
    manifest_bytes = tracked_inputs[WITNESS_MANIFEST_LOGICAL_PATH]
    expected_evidence = committed_evidence_digests_from_snapshot(
        tracked_inputs[EVIDENCE_SUMS_LOGICAL_PATH]
    )

    if receipt_bytes != tracked_inputs[BASELINE_RECEIPT_LOGICAL_PATH]:
        raise RuntimeError("staged baseline receipt differs from release commit")
    for name in AUXILIARY_EVIDENCE_NAMES:
        if staged_inputs[name] != tracked_inputs[AUXILIARY_LOGICAL_PATHS[name]]:
            raise RuntimeError(f"staged evidence differs from release commit: {name}")
        if sha256(staged_inputs[name]) != expected_evidence[name]:
            raise RuntimeError(f"staged evidence digest mismatch: {name}")

    validate_formal_receipt(receipt, claim_validator)
    binding = receipt["formal_checker"]
    validate_committed_baseline(
        receipt_bytes,
        witness_bytes,
        receipt,
        expected_evidence,
        manifest_bytes,
    )
    validate_request_binding(request_bytes, binding)
    validate_release_binding(binding)
    validate_witness_digests(witness_bytes, receipt)
    validate_producer_source(receipt, producer_source_bytes)
    validate_review_report(
        review_bytes, reviewed_commit, sha256(producer_source_bytes), clearance
    )
    if sha256(checker_bytes) != binding["checker_sha256"]:
        raise RuntimeError("checker digest does not match receipt")
    if sha256(identity_bytes) != binding["proof_identity_file_sha256"]:
        raise RuntimeError("proof identity file digest does not match receipt")
    if identity["identity_digest_sha256"] != binding["proof_identity_digest_sha256"]:
        raise RuntimeError("proof identity internal digest does not match receipt")

    entries = archive_entries(
        checker_bytes,
        identity_bytes,
        identity,
        request_bytes,
        producer_source_bytes,
        tracked_inputs,
    )
    archive_bytes = deterministic_tar_gz(entries)
    auxiliary_evidence = validate_auxiliary_evidence(
        {name: staged_inputs[name] for name in AUXILIARY_EVIDENCE_NAMES},
        receipt_bytes,
        receipt,
        witness_bytes,
        checker_bytes,
        producer_source_bytes,
        tracked_inputs,
    )
    assets = {
        WITNESS_NAME: witness_bytes,
        RECEIPT_NAME: receipt_bytes,
        PROOF_NAME: identity_bytes,
        **auxiliary_evidence,
        REVIEW_NAME: review_bytes,
        REVIEW_CLEARANCE_NAME: clearance_bytes,
        "request_v2.json": request_bytes,
        ARCHIVE_NAME: archive_bytes,
    }
    assets["VERIFICATION.md"] = verification_text(
        commit,
        reviewed_commit,
        sha256(receipt_bytes),
        sha256(witness_bytes),
        sha256(identity_bytes),
        identity["identity_digest_sha256"],
        sha256(review_bytes),
        sha256(clearance_bytes),
        binding,
    )
    for name, data in assets.items():
        assert_release_claims(name, data, claim_validator)
    sums = "".join(
        f"{sha256(assets[name])}  {name}\n" for name in sorted(assets)
    ).encode("ascii")
    validate_publication_runtime(identity)
    write_release_assets(output, assets, sums, commit, tracked_inputs)
    return {name: sha256(data) for name, data in assets.items()} | {
        "SHA256SUMS": sha256(sums)
    }


def main(argv: Sequence[str] | None = None) -> int:
    runtime = validate_publication_startup()
    parser = argparse.ArgumentParser(
        epilog=(
            "Publication invocation: /usr/bin/python3 -I -B "
            "release/tools/package_spacecraft_v175.py ..."
        )
    )
    parser.add_argument("--staging-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--merge-commit", required=True)
    parser.add_argument("--reviewed-commit", required=True)
    args = parser.parse_args(argv)
    output = Path(os.path.abspath(os.fspath(args.output_dir)))
    result = build(
        args.staging_dir.resolve(),
        output,
        args.merge_commit,
        args.reviewed_commit,
    )
    print(
        f"SPACECRAFT_V175_ASSETS_BUILT files={len(result)} "
        f"output={output} launcher={runtime['launcher_path']} "
        f"launcher_sha256={runtime['launcher_sha256']} "
        f"python_interpreter={runtime['interpreter_path']} "
        f"python_resolved={runtime['interpreter_resolved_path']} "
        f"python_sha256={runtime['interpreter_sha256']} "
        f"git={runtime['git_path']} git_sha256={runtime['git_sha256']} "
        "isolated=1 bytecode=off"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
