#!/usr/bin/env python3
"""Independent deterministic replay for JACKAL Navier--Stokes v1 receipts.

This verifier does not import the producer.  It independently canonicalizes
the caller-pinned request, reconstructs the Anubis line protocol, replays all
exact-rational policy decisions, and checks source/manifest/receipt identity.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pwd
import re
import resource
import selectors
import signal
import stat
import subprocess
import tempfile
import time
from fractions import Fraction
from pathlib import Path
from typing import Any


REQUEST_SCHEMA = "jackal-navier-stokes-request-v1"
RECEIPT_SCHEMA = "jackal-navier-stokes-receipt-v1"
PACK_VERSION = "1.0.0"
EXPECTED_MANIFEST_SHA256 = "4fdb23cd057e112b4fa89a503fed1262323857c2ae9eebeb983b22d13861198d"
MAXIMUM_MANIFEST_BYTES = 65536
EXPECTED_SOURCE_SHA256 = "a5598ceeabeca26f9551e9a388bfaeec4c2ccf6e8bc1577ab8a638f624b3dac6"
EXPECTED_ANUBIS_BINARY_LOCATOR_ID = (
    "macos-account-home-relative-v1:anubis-a733565f237d"
)
EXPECTED_ANUBIS_BINARY_RELATIVE_CANDIDATES = (
    "Library/Application Support/JACKAL/anubis-pins/anubis-a733565f237d",
    "anubis-lang/vm/pins/anubis-a733565f237d",
)
EXPECTED_ANUBIS_BINARY_SHA256 = (
    "a733565f237df171e7cf93b9b37700a42d8713576818fd92f8cd23a8ad7a69e2"
)
EXPECTED_ANUBIS_BINARY_SIZE = 99_415_712
EXPECTED_ANUBIS_BINARY_MODE = 0o555
ANUBIS_EXECUTION_BINDING = "descriptor_snapshot_v1"
ZERO_FIELD_SHA256 = "c9ca77221d998a4dadc654091bb27776c2a5e461debe3e88e98f7c1bbba06bcf"
ZERO_THEOREM_SHA256 = "4a26df4e465412aca24de29aeb882fb5c6c36148d16422ffd09f03fd8f3cdc09"
ZERO_PROOF_OBJECT_SHA256 = "42ac530f66869eafa2e1f82441ef1c47617fb2ee23a8b05e7d13a7aba4eb1e1f"
ESS_SOURCE_SHA256 = "2712fad880a7c626c5b7cdb678052585f502f0bd53594b03e51ea16b149fcc19"
CCRT_SOURCE_SHA256 = "e815cbcdba8303dc03fb763bb0d10ce33660502ebd075b817359b9d05c89d76b"
HEX64 = re.compile(r"^[0-9a-f]{64}$")
RATIONAL = re.compile(r"^-?(?:0|[1-9][0-9]*)(?:/[1-9][0-9]*)?$")

ROOT_KEYS = {
    "schema", "pack_version", "operation", "requested_claim", "allow_fallback",
    "model", "scope", "preconditions", "solution_link", "gate_data", "nonclaims",
}
MODEL_KEYS = {
    "dimension", "equation", "density", "forcing", "viscosity", "domain",
    "period", "measure_normalization", "pressure_gauge", "sign_convention",
}
SCOPE_KEYS = {
    "t0", "t1", "topology", "terminal_role", "initial_field_digest",
    "approximate_field_digest", "reconstruction_digest",
}
PRE_KEYS = {
    "smooth_initial", "divergence_free_initial", "exact_zero_forcing", "mean_zero",
    "solution_class",
}
SOLUTION_KEYS = {
    "theorem_id", "theorem_source_sha256", "theorem_locator", "m", "norm_id",
    "representation_id", "initial_mismatch_upper", "residual_integral_upper",
    "divergence_defect_upper", "eta_upper", "threshold_lower",
    "continuum_remainders_certified", "proof_object_id", "proof_object_digest",
}
INTERVAL_KEYS = {"lower", "upper"}
CUTOFF_KEYS = {
    "lambda", "w_truncated", "w_tail_upper", "d_truncated", "d_tail_upper",
    "tail_theorem_id", "tail_certificate_digest", "method_digest",
}
GATE_KEYS = {
    "gate_s": {"kind"},
    "gate_a": {"kind", "energy_t", "dissipation_integral", "energy_0", "norm_id"},
    "gate_b": {"kind", "identity_id", "dimension_id", "cutoff_kind", "cutoffs"},
    "gate_c": {"kind", "theorem_id", "theorem_source_sha256", "theorem_locator", "prefix_bound", "terminal_coverage", "continuum_norm_certified"},
    "gate_d": {"kind", "theorem_id", "theorem_source_sha256", "theorem_locator", "p", "q", "mixed_norm", "continuum_norm_certified", "time_embedding_factor"},
}


class ReceiptRefusal(ValueError):
    pass


def _bound_child_process(limits: dict[str, Any]) -> None:
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    file_cap = limits["maximum_anubis_binary_bytes"]
    _, file_hard = resource.getrlimit(resource.RLIMIT_FSIZE)
    file_soft = file_cap if file_hard == resource.RLIM_INFINITY else min(file_cap, file_hard)
    resource.setrlimit(resource.RLIMIT_FSIZE, (file_soft, file_hard))
    _, nofile_hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    nofile_soft = 256 if nofile_hard == resource.RLIM_INFINITY else min(256, nofile_hard)
    resource.setrlimit(resource.RLIMIT_NOFILE, (nofile_soft, nofile_hard))
    cpu_cap = limits["anubis_subprocess_timeout_seconds"] + 5
    _, cpu_hard = resource.getrlimit(resource.RLIMIT_CPU)
    cpu_soft = cpu_cap if cpu_hard == resource.RLIM_INFINITY else min(cpu_cap, cpu_hard)
    resource.setrlimit(resource.RLIMIT_CPU, (cpu_soft, cpu_hard))


def _terminate_process_group(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is None:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            try:
                process.kill()
            except ProcessLookupError:
                pass
    try:
        process.wait(timeout=1)
    except subprocess.TimeoutExpired:
        try:
            process.kill()
        except ProcessLookupError:
            pass
        process.wait()


def _communicate_bounded(
    process: subprocess.Popen[bytes],
    *,
    maximum_output_bytes: int,
    timeout_seconds: int,
) -> tuple[int, bytes, bytes]:
    if process.stdout is None or process.stderr is None:
        _terminate_process_group(process)
        raise ReceiptRefusal("anubis_output_pipes_unavailable")
    buffers = {process.stdout: bytearray(), process.stderr: bytearray()}
    deadline = time.monotonic() + timeout_seconds
    selector = selectors.DefaultSelector()
    try:
        for stream in buffers:
            os.set_blocking(stream.fileno(), False)
            selector.register(stream, selectors.EVENT_READ)
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                _terminate_process_group(process)
                raise ReceiptRefusal("anubis_subprocess_timeout")
            events = selector.select(remaining)
            if not events:
                _terminate_process_group(process)
                raise ReceiptRefusal("anubis_subprocess_timeout")
            for key, _ in events:
                stream = key.fileobj
                buffer = buffers[stream]
                try:
                    chunk = os.read(
                        stream.fileno(),
                        min(65_536, maximum_output_bytes + 1 - len(buffer)),
                    )
                except BlockingIOError:
                    continue
                if not chunk:
                    selector.unregister(stream)
                    continue
                buffer.extend(chunk)
                if len(buffer) > maximum_output_bytes:
                    _terminate_process_group(process)
                    raise ReceiptRefusal("anubis_output_resource_limit")
    finally:
        selector.close()
        for stream in buffers:
            stream.close()
    remaining = deadline - time.monotonic()
    try:
        return_code = process.wait(timeout=max(remaining, 0))
    except subprocess.TimeoutExpired as exc:
        _terminate_process_group(process)
        raise ReceiptRefusal("anubis_subprocess_timeout") from exc
    return return_code, bytes(buffers[process.stdout]), bytes(buffers[process.stderr])


def _reject_json_number(token: str) -> Any:
    raise ReceiptRefusal(f"noncanonical_numeric_type:{token}")


def _strict_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ReceiptRefusal(f"schema_duplicate_field:{key}")
        result[key] = value
    return result


def load_json_strict(path: Path, *, maximum_bytes: int = 16 * 1024 * 1024) -> Any:
    data = _read_regular_bounded(
        path,
        maximum_bytes,
        "json_input_unavailable",
        allow_empty=True,
    )
    try:
        text = data.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise ReceiptRefusal("schema_invalid_utf8") from exc
    try:
        return json.loads(
            text,
            object_pairs_hook=_strict_pairs,
            parse_float=_reject_json_number,
            parse_constant=_reject_json_number,
        )
    except ReceiptRefusal:
        raise
    except json.JSONDecodeError as exc:
        raise ReceiptRefusal(f"schema_invalid_json:line={exc.lineno}:column={exc.colno}") from exc


def canonical_json_bytes(value: Any) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, OverflowError) as exc:
        raise ReceiptRefusal("noncanonical_json") from exc


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_regular_bounded(
    path: Path,
    maximum_bytes: int,
    unavailable: str,
    *,
    allow_empty: bool = False,
) -> bytes:
    try:
        descriptor = os.open(
            path,
            os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK,
        )
    except FileNotFoundError as exc:
        raise ReceiptRefusal(unavailable) from exc
    except OSError as exc:
        raise ReceiptRefusal(f"{unavailable}:nonregular") from exc
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise ReceiptRefusal(f"{unavailable}:nonregular")
        if (metadata.st_size < 1 and not allow_empty) or metadata.st_size > maximum_bytes:
            raise ReceiptRefusal(f"{unavailable}:resource_limit")
        chunks: list[bytes] = []
        remaining = maximum_bytes + 1
        while remaining > 0:
            block = os.read(descriptor, min(1024 * 1024, remaining))
            if not block:
                break
            chunks.append(block)
            remaining -= len(block)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    data = b"".join(chunks)
    identity = (metadata.st_dev, metadata.st_ino, metadata.st_size, metadata.st_mtime_ns)
    after_identity = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
    if identity != after_identity or len(data) != metadata.st_size:
        raise ReceiptRefusal(f"{unavailable}:changed_during_read")
    if len(data) > maximum_bytes:
        raise ReceiptRefusal(f"{unavailable}:resource_limit")
    return data


def _regular_path_identity(path: Path, reason: str) -> tuple[int, int, int, int, int]:
    if not path.is_absolute():
        raise ReceiptRefusal(f"{reason}:path_not_absolute")
    try:
        resolved = path.resolve(strict=True)
        metadata = os.stat(path, follow_symlinks=False)
    except (FileNotFoundError, OSError) as exc:
        raise ReceiptRefusal(f"{reason}:path_unavailable") from exc
    if resolved != path or not stat.S_ISREG(metadata.st_mode):
        raise ReceiptRefusal(f"{reason}:path_identity_mismatch")
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_size,
        metadata.st_mtime_ns,
        stat.S_IMODE(metadata.st_mode),
    )


def _read_exact_compiler(
    platform: dict[str, Any],
    limits: dict[str, Any],
) -> tuple[Path, bytes]:
    try:
        account_home = Path(pwd.getpwuid(os.getuid()).pw_dir).resolve(strict=True)
    except (KeyError, OSError) as exc:
        raise ReceiptRefusal("anubis_binary_unavailable:account_home") from exc
    saw_regular_candidate = False
    for relative in EXPECTED_ANUBIS_BINARY_RELATIVE_CANDIDATES:
        compiler = account_home / relative
        try:
            before = _regular_path_identity(compiler, "anubis_binary_unavailable")
        except ReceiptRefusal:
            continue
        saw_regular_candidate = True
        if before[2] != EXPECTED_ANUBIS_BINARY_SIZE or before[4] != EXPECTED_ANUBIS_BINARY_MODE:
            continue
        compiler_data = _read_regular_bounded(
            compiler,
            limits["maximum_anubis_binary_bytes"],
            "anubis_binary_unavailable",
        )
        after = _regular_path_identity(compiler, "anubis_binary_unavailable")
        if after != before:
            raise ReceiptRefusal("anubis_binary_unavailable:changed_during_read")
        if (
            len(compiler_data) == platform["anubis_binary_size_bytes"]
            and sha256_bytes(compiler_data) == platform["anubis_binary_sha256"]
        ):
            return compiler, compiler_data
    reason = "anubis_binary_identity_mismatch" if saw_regular_candidate else "anubis_binary_unavailable"
    raise ReceiptRefusal(reason)


def _sanitized_execution_environment(temporary: str) -> dict[str, str]:
    try:
        account_home = Path(pwd.getpwuid(os.getuid()).pw_dir).resolve(strict=True)
    except (KeyError, OSError) as exc:
        raise ReceiptRefusal("anubis_binary_unavailable:account_home") from exc
    cargo_home = account_home / ".cargo"
    rustup_home = account_home / ".rustup"
    return {
        "PATH": os.pathsep.join(
            (str(cargo_home / "bin"), "/usr/bin", "/bin", "/usr/sbin", "/sbin", "/opt/homebrew/bin")
        ),
        "CARGO_HOME": str(cargo_home),
        "RUSTUP_HOME": str(rustup_home),
        "TMPDIR": temporary,
        "LANG": "C",
        "LC_ALL": "C",
    }


def _write_authority_snapshot(
    path: Path,
    data: bytes,
    *,
    mode: int,
    reason: str,
) -> tuple[int, int, int, int, int]:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags, mode)
    except OSError as exc:
        raise ReceiptRefusal(f"{reason}:create_failed") from exc
    try:
        offset = 0
        while offset < len(data):
            written = os.write(descriptor, data[offset : offset + 1024 * 1024])
            if written < 1:
                raise ReceiptRefusal(f"{reason}:short_write")
            offset += written
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    os.chmod(path, mode, follow_symlinks=False)
    identity = _regular_path_identity(path, reason)
    snapshot = _read_regular_bounded(path, len(data), reason)
    if identity[2] != len(data) or identity[4] != mode or snapshot != data:
        raise ReceiptRefusal(f"{reason}:identity_mismatch")
    return identity


def _assert_authority_snapshot_unchanged(
    path: Path,
    data: bytes,
    identity: tuple[int, int, int, int, int],
    *,
    reason: str,
) -> None:
    if _regular_path_identity(path, reason) != identity:
        raise ReceiptRefusal(f"{reason}:changed_during_execution")
    if _read_regular_bounded(path, len(data), reason) != data:
        raise ReceiptRefusal(f"{reason}:changed_during_execution")


def _manifest_authority(root: Path) -> dict[str, Any]:
    manifest_path = root / "domain_packs/pde/navier_stokes_v1.json"
    data = _read_regular_bounded(manifest_path, MAXIMUM_MANIFEST_BYTES, "pack_manifest_unavailable")
    digest = sha256_bytes(data)
    if digest != EXPECTED_MANIFEST_SHA256:
        raise ReceiptRefusal("pack_manifest_identity_mismatch")
    try:
        manifest = json.loads(
            data.decode("utf-8", errors="strict"),
            object_pairs_hook=_strict_pairs,
            parse_float=_reject_json_number,
            parse_constant=_reject_json_number,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReceiptRefusal("pack_manifest_invalid") from exc
    if not isinstance(manifest, dict) or manifest.get("schema") != "jackal-domain-pack-manifest-v1":
        raise ReceiptRefusal("pack_manifest_schema_mismatch")
    platform = manifest.get("platform")
    limits = manifest.get("resource_limits")
    if not isinstance(platform, dict) or not isinstance(limits, dict):
        raise ReceiptRefusal("pack_manifest_schema_mismatch")
    expected_platform = {
        "os": "macos",
        "architecture": "arm64",
        "authoritative_language": "anubis",
        "authoritative_source": "domain_packs/pde/navier_stokes_v1.anb",
        "authoritative_source_sha256": EXPECTED_SOURCE_SHA256,
        "anubis_binary_locator_id": EXPECTED_ANUBIS_BINARY_LOCATOR_ID,
        "anubis_binary_relative_candidates": list(EXPECTED_ANUBIS_BINARY_RELATIVE_CANDIDATES),
        "anubis_binary_sha256": EXPECTED_ANUBIS_BINARY_SHA256,
        "anubis_binary_size_bytes": EXPECTED_ANUBIS_BINARY_SIZE,
        "anubis_binary_required_mode": "0555",
        "anubis_execution_binding": ANUBIS_EXECUTION_BINDING,
        "independent_replay": "tools/navier_stokes_receipt_verify.py",
    }
    if platform != expected_platform:
        raise ReceiptRefusal("pack_manifest_authority_mismatch")
    required_limits = {
        "maximum_rational_numerator_absolute": 1_000_000_000,
        "maximum_rational_denominator": 1_000_000_000,
        "maximum_cutoffs": 128,
        "maximum_atom_utf8_bytes": 4096,
        "maximum_json_depth": 32,
        "maximum_json_nodes": 4096,
        "maximum_request_json_bytes": 4_194_304,
        "maximum_receipt_json_depth": 36,
        "maximum_receipt_json_nodes": 4352,
        "maximum_receipt_json_bytes": 16_777_216,
        "maximum_protocol_bytes": 1_048_576,
        "maximum_protocol_lines": 45,
        "maximum_protocol_nodes": 2048,
        "maximum_anubis_output_bytes": 65_536,
        "maximum_identity_artifact_bytes": 65_536,
        "maximum_theorem_source_bytes": 1_048_576,
        "maximum_authoritative_source_bytes": 1_048_576,
        "maximum_anubis_binary_bytes": 268_435_456,
        "anubis_subprocess_timeout_seconds": 30,
        "allow_nan": False,
        "allow_infinity_in_computed_enclosures": False,
    }
    if limits != required_limits:
        raise ReceiptRefusal("pack_manifest_resource_limits_mismatch")
    registry = manifest.get("theorem_registry")
    zero = registry.get("JACKAL_T3_ZERO_SOLUTION_IDENTITY_V1") if isinstance(registry, dict) else None
    if not isinstance(zero, dict):
        raise ReceiptRefusal("pack_manifest_schema_mismatch")
    for kind, path_key, digest_key in (
        ("representation", "representation_path", "representation_sha256"),
        ("theorem_source", "theorem_source_path", "theorem_source_sha256"),
        ("proof_object", "proof_object_path", "proof_object_sha256"),
    ):
        artifact = root / zero.get(path_key, "")
        artifact_data = _read_regular_bounded(
            artifact,
            limits["maximum_identity_artifact_bytes"],
            f"{kind}_unavailable",
        )
        if sha256_bytes(artifact_data) != zero.get(digest_key):
            raise ReceiptRefusal(f"{kind}_identity_mismatch")
    theorem_sources = {
        "CCRT2007_COROLLARY_5_T3_APOSTERIORI": (
            "domain_packs/pde/sources/CCRT2007_COROLLARY_5_T3_APOSTERIORI.pdf",
            CCRT_SOURCE_SHA256,
        ),
        "ESS2003_THEOREM_1_2_R3_SERRIN": (
            "domain_packs/pde/sources/ESS2003_R3_REGULARITY.pdf",
            ESS_SOURCE_SHA256,
        ),
        "ESS2003_THEOREM_1_3_R3_ENDPOINT": (
            "domain_packs/pde/sources/ESS2003_R3_REGULARITY.pdf",
            ESS_SOURCE_SHA256,
        ),
    }
    verified_sources: set[tuple[str, str]] = set()
    for theorem_id, expected_identity in theorem_sources.items():
        theorem = registry.get(theorem_id) if isinstance(registry, dict) else None
        expected_path, expected_digest = expected_identity
        if not isinstance(theorem, dict) or (
            theorem.get("source_path"), theorem.get("source_sha256")
        ) != expected_identity:
            raise ReceiptRefusal("pack_manifest_theorem_source_mismatch")
        if expected_identity in verified_sources:
            continue
        theorem_data = _read_regular_bounded(
            root / expected_path,
            limits["maximum_theorem_source_bytes"],
            "theorem_source_unavailable",
        )
        if sha256_bytes(theorem_data) != expected_digest:
            raise ReceiptRefusal("theorem_source_identity_mismatch")
        verified_sources.add(expected_identity)
    source = root / platform["authoritative_source"]
    source_data = _read_regular_bounded(
        source,
        limits["maximum_authoritative_source_bytes"],
        "anubis_source_unavailable",
    )
    if sha256_bytes(source_data) != platform["authoritative_source_sha256"]:
        raise ReceiptRefusal("anubis_source_identity_mismatch")
    compiler, compiler_data = _read_exact_compiler(platform, limits)
    return {
        "manifest": manifest,
        "manifest_sha256": digest,
        "source": source,
        "source_bytes": source_data,
        "source_sha256": platform["authoritative_source_sha256"],
        "compiler": compiler,
        "compiler_bytes": compiler_data,
        "compiler_locator_id": platform["anubis_binary_locator_id"],
        "compiler_sha256": platform["anubis_binary_sha256"],
        "compiler_size": platform["anubis_binary_size_bytes"],
        "execution_binding": platform["anubis_execution_binding"],
        "limits": limits,
    }


def _closed(value: Any, keys: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ReceiptRefusal(f"schema_type_mismatch:{label}")
    unknown = sorted(set(value) - keys)
    missing = sorted(keys - set(value))
    if unknown:
        raise ReceiptRefusal(f"schema_unknown_field:{label}.{unknown[0]}")
    if missing:
        raise ReceiptRefusal(f"schema_missing_field:{label}.{missing[0]}")
    if len(value) != len(keys):
        raise ReceiptRefusal(f"schema_duplicate_field:{label}")
    return value


def _walk_no_float(value: Any) -> None:
    if isinstance(value, float):
        raise ReceiptRefusal("noncanonical_numeric_type")
    if isinstance(value, dict):
        if not all(isinstance(key, str) for key in value):
            raise ReceiptRefusal("schema_nonstring_key")
        for item in value.values():
            _walk_no_float(item)
    elif isinstance(value, list):
        for item in value:
            _walk_no_float(item)
    elif value is not None and not isinstance(value, (str, int, bool)):
        raise ReceiptRefusal("schema_type_mismatch")


def _enforce_json_tree_limits(value: Any, *, maximum_depth: int, maximum_nodes: int) -> None:
    stack: list[tuple[Any, int]] = [(value, 1)]
    nodes = 0
    while stack:
        item, depth = stack.pop()
        nodes += 1
        if nodes > maximum_nodes or depth > maximum_depth:
            raise ReceiptRefusal("schema_resource_limit")
        if isinstance(item, dict):
            stack.extend((child, depth + 1) for child in item.values())
        elif isinstance(item, list):
            stack.extend((child, depth + 1) for child in item)


def _decode_expected_request_bytes(raw: bytes, limits: dict[str, Any]) -> Any:
    if len(raw) > limits["maximum_request_json_bytes"]:
        raise ReceiptRefusal("schema_resource_limit")
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise ReceiptRefusal("schema_invalid_utf8") from exc
    try:
        request = json.loads(
            text,
            object_pairs_hook=_strict_pairs,
            parse_float=_reject_json_number,
            parse_constant=_reject_json_number,
        )
    except ReceiptRefusal:
        raise
    except (json.JSONDecodeError, RecursionError) as exc:
        reason = "schema_resource_limit" if isinstance(exc, RecursionError) else "schema_invalid_json"
        raise ReceiptRefusal(reason) from exc
    _enforce_json_tree_limits(
        request,
        maximum_depth=limits["maximum_json_depth"],
        maximum_nodes=limits["maximum_json_nodes"],
    )
    return request


def _decode_receipt_bytes(raw: bytes, limits: dict[str, Any]) -> dict[str, Any]:
    if len(raw) > limits["maximum_receipt_json_bytes"]:
        raise ReceiptRefusal("receipt_resource_limit_exceeded")
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise ReceiptRefusal("receipt_invalid_utf8") from exc
    try:
        receipt = json.loads(
            text,
            object_pairs_hook=_strict_pairs,
            parse_float=_reject_json_number,
            parse_constant=_reject_json_number,
        )
    except ReceiptRefusal:
        raise
    except (json.JSONDecodeError, RecursionError) as exc:
        reason = "receipt_resource_limit_exceeded" if isinstance(exc, RecursionError) else "receipt_invalid_json"
        raise ReceiptRefusal(reason) from exc
    _enforce_json_tree_limits(
        receipt,
        maximum_depth=limits["maximum_receipt_json_depth"],
        maximum_nodes=limits["maximum_receipt_json_nodes"],
    )
    if not isinstance(receipt, dict):
        raise ReceiptRefusal("receipt_schema_type_mismatch")
    return receipt


def _codec_request_marker(raw: bytes) -> dict[str, Any]:
    return {
        "codec_input_kind": "raw_json_bytes",
        "raw_request_bytes": len(raw),
        "raw_request_sha256": sha256_bytes(raw),
    }


def _atom(value: Any) -> str:
    if not isinstance(value, str):
        raise ReceiptRefusal("schema_type_mismatch")
    if any(token in value for token in ("\n", "\r", "=", "|", "~")):
        raise ReceiptRefusal("protocol_delimiter_injection")
    if len(value.encode("utf-8")) > 4096:
        raise ReceiptRefusal("schema_resource_limit")
    return value


def _digest_atom(value: Any) -> str:
    atom = _atom(value)
    if HEX64.fullmatch(atom) is None:
        raise ReceiptRefusal("schema_invalid_digest")
    return atom


def _integer(value: Any) -> int:
    if type(value) is not int:
        raise ReceiptRefusal("schema_type_mismatch")
    if value < 0 or value > 1_000_000:
        raise ReceiptRefusal("schema_resource_limit")
    return value


def _interval_shape(value: Any) -> None:
    obj = _closed(value, INTERVAL_KEYS, "interval")
    _atom(obj["lower"])
    _atom(obj["upper"])


def validate_shape(request: Any) -> None:
    _walk_no_float(request)
    root = _closed(request, ROOT_KEYS, "request")
    model = _closed(root["model"], MODEL_KEYS, "model")
    scope = _closed(root["scope"], SCOPE_KEYS, "scope")
    pre = _closed(root["preconditions"], PRE_KEYS, "preconditions")
    _integer(model["dimension"])
    for key in MODEL_KEYS - {"dimension"}:
        _atom(model[key])
    for key in SCOPE_KEYS:
        if key.endswith("_digest"):
            _digest_atom(scope[key])
        else:
            _atom(scope[key])
    for key in PRE_KEYS - {"solution_class"}:
        if type(pre[key]) is not bool:
            raise ReceiptRefusal("schema_type_mismatch:precondition")
    _atom(pre["solution_class"])
    if type(root["allow_fallback"]) is not bool:
        raise ReceiptRefusal("schema_type_mismatch:allow_fallback")
    for key in ("schema", "pack_version", "operation", "requested_claim"):
        _atom(root[key])
    solution = root["solution_link"]
    if solution is not None:
        solution = _closed(solution, SOLUTION_KEYS, "solution_link")
        _integer(solution["m"])
        if type(solution["continuum_remainders_certified"]) is not bool:
            raise ReceiptRefusal("schema_type_mismatch:solution_link")
        for key in SOLUTION_KEYS - {"m", "continuum_remainders_certified"}:
            validator = _digest_atom if key in {"theorem_source_sha256", "proof_object_digest"} else _atom
            validator(solution[key])
    operation = root["operation"]
    if operation not in GATE_KEYS:
        raise ReceiptRefusal("operation_not_admitted")
    gate = _closed(root["gate_data"], GATE_KEYS[operation], "gate_data")
    if operation == "gate_s":
        _atom(gate["kind"])
    elif operation == "gate_a":
        _atom(gate["kind"])
        for key in ("energy_t", "dissipation_integral", "energy_0"):
            _interval_shape(gate[key])
        _atom(gate["norm_id"])
    elif operation == "gate_b":
        for key in ("kind", "identity_id", "dimension_id", "cutoff_kind"):
            _atom(gate[key])
        if not isinstance(gate["cutoffs"], list) or not gate["cutoffs"] or len(gate["cutoffs"]) > 128:
            raise ReceiptRefusal("cutoff_sequence_invalid")
        for cutoff in gate["cutoffs"]:
            _closed(cutoff, CUTOFF_KEYS, "cutoff")
            for key in ("lambda", "tail_theorem_id"):
                _atom(cutoff[key])
            for key in ("tail_certificate_digest", "method_digest"):
                _digest_atom(cutoff[key])
            for key in ("w_truncated", "w_tail_upper", "d_truncated", "d_tail_upper"):
                _interval_shape(cutoff[key])
    elif operation == "gate_c":
        for key in ("kind", "theorem_id", "theorem_locator"):
            _atom(gate[key])
        _digest_atom(gate["theorem_source_sha256"])
        _interval_shape(gate["prefix_bound"])
        if type(gate["terminal_coverage"]) is not bool or type(gate["continuum_norm_certified"]) is not bool:
            raise ReceiptRefusal("schema_type_mismatch")
    elif operation == "gate_d":
        for key in (
            "kind", "theorem_id", "theorem_locator",
            "p", "q", "time_embedding_factor",
        ):
            _atom(gate[key])
        _digest_atom(gate["theorem_source_sha256"])
        _interval_shape(gate["mixed_norm"])
        if type(gate["continuum_norm_certified"]) is not bool:
            raise ReceiptRefusal("schema_type_mismatch")
    if not isinstance(root["nonclaims"], list) or not root["nonclaims"]:
        raise ReceiptRefusal("schema_type_mismatch")
    for item in root["nonclaims"]:
        _atom(item)
    if set(root["nonclaims"]) != {"not_global_regular", "not_smooth_for_all_time", "not_millennium_solved"} or len(root["nonclaims"]) != 3:
        raise ReceiptRefusal("required_nonclaim_missing")


def rat(token: str) -> Fraction:
    if not isinstance(token, str) or not RATIONAL.fullmatch(token):
        raise ReceiptRefusal("noncanonical_rational")
    if token == "-0":
        raise ReceiptRefusal("noncanonical_rational")
    value = Fraction(token)
    if abs(value.numerator) > 1_000_000_000 or value.denominator > 1_000_000_000:
        raise ReceiptRefusal("rational_resource_bound_exceeded")
    canonical = str(value.numerator) if value.denominator == 1 else f"{value.numerator}/{value.denominator}"
    if token != canonical:
        raise ReceiptRefusal("noncanonical_rational")
    return value


def rat_text(value: Fraction) -> str:
    return str(value.numerator) if value.denominator == 1 else f"{value.numerator}/{value.denominator}"


def bounded_rat(value: Fraction) -> Fraction:
    if abs(value.numerator) > 1_000_000_000 or value.denominator > 1_000_000_000:
        raise ReceiptRefusal("rational_resource_bound_exceeded")
    return value


def interval(value: dict[str, str]) -> tuple[Fraction, Fraction]:
    lower, upper = rat(value["lower"]), rat(value["upper"])
    if lower > upper:
        raise ReceiptRefusal("noncanonical_rational")
    return lower, upper


def refused(reason: str) -> dict[str, Any]:
    return {
        "status": "refused", "reason": reason, "arithmetic_status": "NOT_CHECKED",
        "continuum_status": "NOT_VERIFIED", "solution_link_status": "NOT_VERIFIED",
        "theorem_status": "NOT_APPLICABLE", "conclusion_status": "NONE", "halt": True,
        "ratio_upper": "not_computed", "comparison_margin": "not_computed",
        "failed_cutoff": "none", "evaluated_cutoff_count": 0,
        "mathematical_implication": "none", "nonclaim": "not_a_global_regularity_result",
        "transcript": f"refused:{reason}",
    }


def indeterminate(reason: str) -> dict[str, Any]:
    out = refused(reason)
    out.update(status="indeterminate", halt=False, transcript=f"indeterminate:{reason}")
    return out


def solution_verified(request: dict[str, Any]) -> bool:
    solution = request["solution_link"]
    if not isinstance(solution, dict):
        return False
    model, scope = request["model"], request["scope"]
    if model["domain"] != "T3_periodic":
        return False
    if solution["theorem_id"] != "JACKAL_T3_ZERO_SOLUTION_IDENTITY_V1" or solution["theorem_source_sha256"] != ZERO_THEOREM_SHA256:
        return False
    if solution["theorem_locator"] != "domain_packs/pde/NAVIER_STOKES_VERIFICATION_SPEC.md#zero-solution-identity":
        return False
    if solution["norm_id"] != "T3_Vm_STOKES_HOMOGENEOUS_PHYSICAL_VOLUME" or solution["representation_id"] != "T3_ZERO_FOURIER_FIELD_V1" or solution["m"] < 3:
        return False
    if any(scope[key] != ZERO_FIELD_SHA256 for key in ("initial_field_digest", "approximate_field_digest", "reconstruction_digest")):
        return False
    try:
        if any(rat(solution[key]) != 0 for key in ("initial_mismatch_upper", "residual_integral_upper", "divergence_defect_upper", "eta_upper")):
            return False
        if rat(solution["threshold_lower"]) <= 0:
            return False
    except ReceiptRefusal:
        return False
    if solution["continuum_remainders_certified"] is not True:
        return False
    return (
        solution["proof_object_id"] == "JACKAL_T3_ZERO_PROOF_OBJECT_V1"
        and solution["proof_object_digest"] == ZERO_PROOF_OBJECT_SHA256
    )


def _model_error(request: dict[str, Any]) -> str | None:
    model, scope, pre = request["model"], request["scope"], request["preconditions"]
    if request["schema"] != REQUEST_SCHEMA or request["pack_version"] != PACK_VERSION or request["allow_fallback"] is not False:
        return "model_or_precondition_not_admitted"
    if model["dimension"] != 3 or model["equation"] != "incompressible_navier_stokes" or model["density"] != "1" or model["forcing"] != "0":
        return "model_or_precondition_not_admitted"
    if model["measure_normalization"] != "physical_volume" or model["sign_convention"] != "dt_u_minus_nu_laplacian_plus_advection_plus_grad_p_eq_0":
        return "model_or_precondition_not_admitted"
    if not pre["smooth_initial"] or not pre["divergence_free_initial"] or not pre["exact_zero_forcing"]:
        return "model_or_precondition_not_admitted"
    if scope["topology"] not in {"closed", "half_open_terminal"}:
        return "model_or_precondition_not_admitted"
    if scope["terminal_role"] != "finite_scope_only" or pre["solution_class"] != "smooth_on_scope":
        return "model_or_precondition_not_admitted"
    if model["domain"] == "T3_periodic":
        if model["period"] == "not_applicable" or model["pressure_gauge"] != "zero_spatial_mean" or not pre["mean_zero"]:
            return "model_or_precondition_not_admitted"
    elif model["domain"] == "R3_schwartz_decay":
        if model["period"] != "not_applicable" or model["pressure_gauge"] != "decay_at_infinity":
            return "model_or_precondition_not_admitted"
    else:
        return "model_or_precondition_not_admitted"
    try:
        if rat(model["viscosity"]) <= 0 or rat(scope["t0"]) >= rat(scope["t1"]):
            return "noncanonical_rational"
        if model["domain"] == "T3_periodic" and rat(model["period"]) <= 0:
            return "noncanonical_rational"
    except ReceiptRefusal:
        return "noncanonical_rational"
    return None


def replay_result(request: dict[str, Any]) -> dict[str, Any]:
    global_claims = {"global_regular", "smooth_for_all_time", "millennium_solved", "clay_problem_solved"}
    if request["requested_claim"] in global_claims:
        return refused("global_regular_claim_not_admitted")
    admitted_claim = {
        "gate_s": "solution_link_on_scope",
        "gate_a": "energy_on_scope",
        "gate_b": "enstrophy_nonincrease_on_scope",
        "gate_c": "continuation_on_prefix",
        "gate_d": "conditional_regular_on_scope",
    }[request["operation"]]
    if request["requested_claim"] != admitted_claim:
        return refused("requested_claim_operation_mismatch")
    model_error = _model_error(request)
    if model_error:
        return refused(model_error)
    operation, gate = request["operation"], request["gate_data"]
    if operation == "gate_s":
        if gate["kind"] != "solution_link":
            return refused("gate_payload_schema_invalid")
        solution = request["solution_link"]
        if solution is None:
            return refused("solution_link_not_verified")
        if solution["residual_integral_upper"] == "":
            return refused("pde_residual_not_certified")
        if request["model"]["domain"] != "T3_periodic" or solution["theorem_id"] != "JACKAL_T3_ZERO_SOLUTION_IDENTITY_V1":
            return refused("solution_link_theorem_not_admitted_for_domain")
        if not solution_verified(request):
            return refused("solution_link_evidence_not_verified")
        return {
            "status": "bounded", "reason": "zero_solution_identity_verified_on_finite_scope",
            "arithmetic_status": "ARITHMETIC_CHECKED", "continuum_status": "CONTINUUM_ENCLOSURE_VERIFIED",
            "solution_link_status": "SOLUTION_LINK_VERIFIED", "theorem_status": "THEOREM_APPLICABLE",
            "conclusion_status": "BOUNDED_ON_SCOPE", "halt": False, "ratio_upper": "not_applicable",
            "comparison_margin": "1", "failed_cutoff": "none", "evaluated_cutoff_count": 0,
            "mathematical_implication": "exact_zero_solution_exists_on_named_scope",
            "nonclaim": "not_a_global_regularity_result",
            "transcript": "zero_field;residual=0;divergence=0;initial_mismatch=0",
        }
    if operation == "gate_a":
        if request["scope"]["t0"] != "0":
            return refused("energy_prefix_requires_t0_zero")
        if gate["kind"] != "energy_prefix":
            return refused("gate_payload_schema_invalid")
        if gate["norm_id"] != "L2_SQUARED_PHYSICAL_VOLUME":
            return refused("norm_normalization_mismatch")
        try:
            energy_t, diss, energy_0 = interval(gate["energy_t"]), interval(gate["dissipation_integral"]), interval(gate["energy_0"])
        except ReceiptRefusal:
            return refused("noncanonical_rational")
        if min(energy_t[0], diss[0], energy_0[0]) < 0:
            return refused("negative_energy_or_dissipation")
        try:
            viscous = bounded_rat(bounded_rat(Fraction(2) * rat(request["model"]["viscosity"])) * diss[1])
            lhs = bounded_rat(energy_t[1] + viscous)
            margin = bounded_rat(energy_0[0] - lhs)
        except ReceiptRefusal:
            return refused("rational_resource_bound_exceeded")
        if margin < 0:
            out = indeterminate("energy_interval_condition_not_closed")
            out.update(arithmetic_status="ARITHMETIC_CHECKED", comparison_margin=rat_text(margin), transcript=f"upper(E_t)+2*nu*upper(D)<=lower(E_0);margin={rat_text(margin)}")
            return out
        if not solution_verified(request):
            out = refused("solution_link_not_verified")
            out.update(arithmetic_status="ARITHMETIC_CHECKED", comparison_margin=rat_text(margin))
            return out
        if any(value != 0 for value in (*energy_t, *diss, *energy_0)):
            return refused("observable_dependency_mismatch")
        return {
            "status": "bounded", "reason": "energy_interval_condition_closed_on_linked_scope",
            "arithmetic_status": "ARITHMETIC_CHECKED", "continuum_status": "CONTINUUM_ENCLOSURE_VERIFIED",
            "solution_link_status": "SOLUTION_LINK_VERIFIED", "theorem_status": "THEOREM_APPLICABLE",
            "conclusion_status": "BOUNDED_ON_SCOPE", "halt": False, "ratio_upper": "not_applicable",
            "comparison_margin": rat_text(margin), "failed_cutoff": "none", "evaluated_cutoff_count": 0,
            "mathematical_implication": "energy_inequality_consistent_on_named_prefix",
            "nonclaim": "not_existence_uniqueness_smoothness_or_global_regularity",
            "transcript": f"upper(E_t)+2*nu*upper(D)<=lower(E_0);margin={rat_text(margin)}",
        }
    if operation == "gate_b":
        if gate["kind"] != "vortex_stretching_cutoff_sequence":
            return refused("gate_payload_schema_invalid")
        if gate["identity_id"] != "T3_GLOBAL_ENSTROPHY_IDENTITY_V1":
            return refused("enstrophy_identity_not_admitted")
        if request["model"]["domain"] != "T3_periodic":
            return refused("theorem_domain_mismatch")
        if gate["dimension_id"] != "NU_D_EQUALS_W_L3_PER_T2":
            return refused("dimension_mismatch")
        if gate["cutoff_kind"] != "fourier_mode_number":
            return refused("cutoff_kind_not_admitted")
        previous = Fraction(-1)
        last_ratio, last_margin, evaluated = "not_computed", "not_computed", 0
        for item in gate["cutoffs"]:
            try:
                cutoff = rat(item["lambda"])
                if cutoff < 0 or cutoff <= previous:
                    return refused("cutoff_sequence_invalid")
                previous = cutoff
                w, rw, d, rd = interval(item["w_truncated"]), interval(item["w_tail_upper"]), interval(item["d_truncated"]), interval(item["d_tail_upper"])
            except ReceiptRefusal:
                return refused("noncanonical_rational")
            if rw[0] < 0 or rd[0] < 0:
                return refused("negative_continuum_remainder")
            if item["tail_theorem_id"] != "TEST_FIXTURE_EXACT_FINITE_SUPPORT_V1":
                return refused("tail_theorem_not_admitted")
            if not HEX64.fullmatch(item["tail_certificate_digest"]) or not HEX64.fullmatch(item["method_digest"]):
                return refused("continuum_remainder_not_certified")
            if d[0] < 0:
                return refused("negative_energy_or_dissipation")
            try:
                u_plus = max(Fraction(0), bounded_rat(w[1] + rw[1]))
                d_minus = bounded_rat(d[0] - rd[1])
            except ReceiptRefusal:
                return refused("rational_resource_bound_exceeded")
            evaluated += 1
            if d_minus <= 0:
                out = indeterminate("dissipation_lower_bound_not_positive")
                out.update(arithmetic_status="ARITHMETIC_CHECKED", evaluated_cutoff_count=evaluated, failed_cutoff=rat_text(cutoff), transcript=f"d_minus={rat_text(d_minus)}")
                return out
            try:
                denominator = bounded_rat(rat(request["model"]["viscosity"]) * d_minus)
                ratio = bounded_rat(u_plus / denominator)
                margin = bounded_rat(denominator - u_plus)
            except ReceiptRefusal:
                return refused("rational_resource_bound_exceeded")
            last_ratio, last_margin = rat_text(ratio), rat_text(margin)
            if margin < 0:
                return {
                    "status": "indeterminate", "reason": "uncertified_potential_blowup_vortex_stretching",
                    "arithmetic_status": "ARITHMETIC_CHECKED", "continuum_status": "NOT_VERIFIED",
                    "solution_link_status": "NOT_VERIFIED", "theorem_status": "NOT_APPLICABLE",
                    "conclusion_status": "NONE", "halt": True, "ratio_upper": last_ratio,
                    "comparison_margin": last_margin, "failed_cutoff": rat_text(cutoff),
                    "evaluated_cutoff_count": evaluated, "mathematical_implication": "none",
                    "nonclaim": "not_evidence_of_singularity",
                    "transcript": f"u_plus<=nu*d_minus:false;ratio_upper={last_ratio}",
                }
        if not solution_verified(request):
            out = refused("solution_link_not_verified")
            out.update(halt=False, arithmetic_status="ARITHMETIC_CHECKED", continuum_status="NOT_VERIFIED", ratio_upper=last_ratio, comparison_margin=last_margin, evaluated_cutoff_count=evaluated, transcript=f"u_plus<=nu*d_minus:true;ratio_upper={last_ratio}")
            return out
        return refused("vortex_observable_not_bound_to_admitted_solution_link")
    if operation == "gate_c":
        if gate["kind"] != "vorticity_continuation_prefix":
            return refused("gate_payload_schema_invalid")
        if gate["theorem_id"] == "BKM1984_EULER_ONLY":
            return refused("euler_theorem_not_applicable_to_navier_stokes")
        if gate["theorem_id"] == "KATO_PONCE_1988_NS_CONTINUATION_DISABLED":
            return refused("viscous_continuation_theorem_disabled_pending_audit")
        return refused("viscous_continuation_theorem_not_admitted")
    if operation == "gate_d":
        if gate["kind"] != "serrin_ess_conditional":
            return refused("gate_payload_schema_invalid")
        theorem, domain = gate["theorem_id"], request["model"]["domain"]
        if theorem == "ESS2003_THEOREM_1_3_R3_ENDPOINT":
            if domain != "R3_schwartz_decay":
                return refused("theorem_domain_mismatch")
            if gate["theorem_source_sha256"] != ESS_SOURCE_SHA256 or gate["theorem_locator"] != "Theorem 1.3; condition (1.13)":
                return refused("theorem_identity_mismatch")
            if gate["p"] != "inf" or gate["q"] != "3":
                return refused("ess_endpoint_exponent_mismatch")
        elif theorem == "ESS2003_THEOREM_1_2_R3_SERRIN":
            if domain != "R3_schwartz_decay":
                return refused("theorem_domain_mismatch")
            if gate["theorem_source_sha256"] != ESS_SOURCE_SHA256 or gate["theorem_locator"] != "Theorem 1.2; conditions (1.9)-(1.10)":
                return refused("theorem_identity_mismatch")
            try:
                if gate["q"] == "inf":
                    three_over_q = Fraction(0, 1)
                else:
                    q = rat(gate["q"])
                    if q <= 3:
                        return refused("serrin_exponent_condition_not_met")
                    three_over_q = bounded_rat(Fraction(3, 1) / q)
                lhs = three_over_q if gate["p"] == "inf" else bounded_rat(
                    bounded_rat(Fraction(2, 1) / rat(gate["p"])) + three_over_q
                )
                if lhs > 1:
                    return refused("serrin_exponent_condition_not_met")
            except ReceiptRefusal:
                return refused("serrin_exponent_condition_not_met")
        else:
            return refused("regularity_theorem_not_admitted")
        try:
            mixed_norm = interval(gate["mixed_norm"])
            embedding = rat(gate["time_embedding_factor"])
        except ReceiptRefusal:
            return refused("noncanonical_rational")
        if mixed_norm[0] < 0:
            return refused("negative_norm_enclosure")
        if not gate["continuum_norm_certified"]:
            return refused("continuum_norm_not_certified")
        if embedding <= 0:
            return refused("time_embedding_factor_invalid")
        out = refused("theorem_preconditions_not_verified")
        out.update(
            halt=False,
            arithmetic_status="ARITHMETIC_CHECKED",
            continuum_status="NOT_VERIFIED",
            theorem_status="THEOREM_IDENTITY_MATCHED_PRECONDITIONS_UNVERIFIED",
            transcript="conditional_theorem_identity_matched;continuum_norm_and_solution_link_unverified",
        )
        return out
    return refused("operation_not_admitted")


def _bool_text(value: bool) -> str:
    return "true" if value else "false"


def gate_payload(request: dict[str, Any]) -> str:
    gate, op = request["gate_data"], request["operation"]
    reconstruction = request["scope"]["reconstruction_digest"]
    if op == "gate_s":
        return gate["kind"]
    if op == "gate_a":
        return "|".join([gate["kind"], gate["energy_t"]["lower"], gate["energy_t"]["upper"], gate["dissipation_integral"]["lower"], gate["dissipation_integral"]["upper"], gate["energy_0"]["lower"], gate["energy_0"]["upper"], gate["norm_id"]])
    if op == "gate_b":
        records = []
        for item in gate["cutoffs"]:
            records.append("~".join([item["lambda"], item["w_truncated"]["lower"], item["w_truncated"]["upper"], item["w_tail_upper"]["lower"], item["w_tail_upper"]["upper"], item["d_truncated"]["lower"], item["d_truncated"]["upper"], item["d_tail_upper"]["lower"], item["d_tail_upper"]["upper"], item["tail_theorem_id"], item["tail_certificate_digest"], item["method_digest"], reconstruction]))
        return "|".join([gate["kind"], gate["identity_id"], gate["dimension_id"], gate["cutoff_kind"], str(len(records)), ";".join(records)])
    if op == "gate_c":
        return "|".join([gate["kind"], gate["theorem_id"], gate["theorem_source_sha256"], gate["theorem_locator"], gate["prefix_bound"]["lower"], gate["prefix_bound"]["upper"], _bool_text(gate["terminal_coverage"]), _bool_text(gate["continuum_norm_certified"]), reconstruction])
    return "|".join([gate["kind"], gate["theorem_id"], gate["theorem_source_sha256"], gate["theorem_locator"], gate["p"], gate["q"], gate["mixed_norm"]["lower"], gate["mixed_norm"]["upper"], _bool_text(gate["continuum_norm_certified"]), reconstruction, gate["time_embedding_factor"]])


def _protocol_node_count(request: dict[str, Any]) -> int:
    if request["operation"] == "gate_b":
        return 45 + 13 * len(request["gate_data"]["cutoffs"])
    return 45


def protocol_bytes(request: dict[str, Any]) -> bytes:
    model, scope, pre = request["model"], request["scope"], request["preconditions"]
    present = request["solution_link"] is not None
    solution = request["solution_link"] or {
        "theorem_id": "", "theorem_source_sha256": "", "theorem_locator": "", "m": 0,
        "norm_id": "", "representation_id": "", "initial_mismatch_upper": "",
        "residual_integral_upper": "", "divergence_defect_upper": "", "eta_upper": "",
        "threshold_lower": "", "continuum_remainders_certified": False,
        "proof_object_id": "", "proof_object_digest": "",
    }
    lines = [
        f"schema={request['schema']}", f"pack_version={request['pack_version']}", f"operation={request['operation']}", f"requested_claim={request['requested_claim']}", f"allow_fallback={_bool_text(request['allow_fallback'])}",
        f"dimension={model['dimension']}", f"equation={model['equation']}", f"density={model['density']}", f"forcing={model['forcing']}", f"viscosity={model['viscosity']}", f"domain={model['domain']}", "domain_geometry=periodic_cube_or_whole_space_v1", f"period={model['period']}", f"measure_normalization={model['measure_normalization']}", f"pressure_gauge={model['pressure_gauge']}", f"sign_convention={model['sign_convention']}",
        f"t0={scope['t0']}", f"t1={scope['t1']}", f"topology={scope['topology']}", f"initial_field_digest={scope['initial_field_digest']}", f"approximate_field_digest={scope['approximate_field_digest']}", f"reconstruction_digest={scope['reconstruction_digest']}", f"terminal_role={scope['terminal_role']}", f"solution_class={pre['solution_class']}", f"smooth_initial={_bool_text(pre['smooth_initial'])}", f"divergence_free_initial={_bool_text(pre['divergence_free_initial'])}", f"exact_zero_forcing={_bool_text(pre['exact_zero_forcing'])}", f"mean_zero={_bool_text(pre['mean_zero'])}", "scope_semantics=bounded_time_scope_only", f"solution_present={_bool_text(present)}",
        f"solution_theorem_id={solution['theorem_id']}", f"solution_theorem_sha256={solution['theorem_source_sha256']}", f"solution_theorem_locator={solution['theorem_locator']}", f"solution_m={solution['m']}", f"solution_norm_id={solution['norm_id']}", f"solution_representation_id={solution['representation_id']}", f"solution_initial_mismatch_upper={solution['initial_mismatch_upper']}", f"solution_residual_integral_upper={solution['residual_integral_upper']}", f"solution_divergence_defect_upper={solution['divergence_defect_upper']}", f"solution_eta_upper={solution['eta_upper']}", f"solution_threshold_lower={solution['threshold_lower']}", f"solution_continuum_remainders_certified={_bool_text(solution['continuum_remainders_certified'])}", f"solution_proof_object_id={solution['proof_object_id']}", f"solution_proof_object_digest={solution['proof_object_digest']}", f"gate_payload={gate_payload(request)}",
    ]
    if len(lines) != 45:
        raise ReceiptRefusal("protocol_line_count_drift")
    return ("\n".join(lines) + "\n").encode("utf-8")


def _parse_anubis_result(stdout: str, expected_protocol_sha256: str) -> dict[str, Any]:
    wanted = {
        "status", "reason", "arithmetic_status", "continuum_status",
        "solution_link_status", "theorem_status", "conclusion_status", "halt",
        "ratio_upper", "comparison_margin", "failed_cutoff",
        "evaluated_cutoff_count", "mathematical_implication", "nonclaim",
        "transcript", "protocol_sha256",
    }
    parsed: dict[str, str] = {}
    for raw in stdout.splitlines():
        if "=" not in raw:
            continue
        key, value = raw.split("=", 1)
        if key not in wanted:
            continue
        if key in parsed:
            raise ReceiptRefusal("anubis_output_duplicate_field")
        parsed[key] = value
    if set(parsed) != wanted:
        raise ReceiptRefusal("anubis_output_fields_mismatch")
    if parsed.pop("protocol_sha256") != expected_protocol_sha256:
        raise ReceiptRefusal("anubis_protocol_digest_mismatch")
    halt = parsed.pop("halt")
    if halt not in {"true", "false"}:
        raise ReceiptRefusal("anubis_output_boolean_invalid")
    count_text = parsed.pop("evaluated_cutoff_count")
    if re.fullmatch(r"0|[1-9][0-9]*", count_text) is None:
        raise ReceiptRefusal("anubis_output_count_invalid")
    count = int(count_text)
    if count > 128:
        raise ReceiptRefusal("anubis_output_count_invalid")
    parsed["halt"] = halt == "true"
    parsed["evaluated_cutoff_count"] = count
    return parsed


def _execute_anubis(
    request: dict[str, Any],
    *,
    root: Path,
    authority: dict[str, Any],
) -> dict[str, Any]:
    protocol = protocol_bytes(request)
    limits = authority["limits"]
    if protocol.count(b"\n") > limits["maximum_protocol_lines"]:
        raise ReceiptRefusal("protocol_resource_limit_exceeded")
    if _protocol_node_count(request) > limits["maximum_protocol_nodes"]:
        raise ReceiptRefusal("protocol_node_resource_limit_exceeded")
    if len(protocol) > limits["maximum_protocol_bytes"]:
        raise ReceiptRefusal("protocol_resource_limit_exceeded")
    protocol_sha256 = sha256_bytes(protocol)
    with tempfile.TemporaryDirectory(prefix="jackal-navier-replay-") as temporary:
        temporary_path = Path(temporary).resolve(strict=True)
        protocol_path = temporary_path / "request.protocol"
        native_out = temporary_path / "native"
        compiler_snapshot = temporary_path / "anubis-authority.snapshot"
        source_snapshot = temporary_path / "navier-stokes-authority.snapshot.anb"
        protocol_path.write_bytes(protocol)
        compiler_identity = _write_authority_snapshot(
            compiler_snapshot,
            authority["compiler_bytes"],
            mode=0o500,
            reason="anubis_binary_snapshot",
        )
        source_identity = _write_authority_snapshot(
            source_snapshot,
            authority["source_bytes"],
            mode=0o400,
            reason="anubis_source_snapshot",
        )
        process = subprocess.Popen(
            [
                str(compiler_snapshot),
                "run",
                "--out",
                str(native_out),
                str(source_snapshot),
                "--",
                str(protocol_path),
            ],
            cwd=root,
            env=_sanitized_execution_environment(temporary),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
            preexec_fn=lambda: _bound_child_process(limits),
        )
        return_code, stdout_bytes, stderr_bytes = _communicate_bounded(
            process,
            maximum_output_bytes=limits["maximum_anubis_output_bytes"],
            timeout_seconds=limits["anubis_subprocess_timeout_seconds"],
        )
        try:
            stdout = stdout_bytes.decode("utf-8", errors="strict")
            stderr = stderr_bytes.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise ReceiptRefusal("anubis_output_invalid_utf8") from exc
        _assert_authority_snapshot_unchanged(
            compiler_snapshot,
            authority["compiler_bytes"],
            compiler_identity,
            reason="anubis_binary_snapshot",
        )
        _assert_authority_snapshot_unchanged(
            source_snapshot,
            authority["source_bytes"],
            source_identity,
            reason="anubis_source_snapshot",
        )
    if return_code != 0:
        raise ReceiptRefusal(f"anubis_subprocess_failed:rc={return_code}:stderr={stderr[-512:]}")
    return _parse_anubis_result(stdout, protocol_sha256)


def verify_receipt(
    receipt: dict[str, Any],
    *,
    expected_request: dict[str, Any],
    root: Path | None = None,
) -> dict[str, Any]:
    root = (root or Path(__file__).resolve().parents[1]).resolve()
    pinned = _manifest_authority(root)
    if not isinstance(receipt, dict):
        raise ReceiptRefusal("receipt_schema_type_mismatch")
    _enforce_json_tree_limits(
        receipt,
        maximum_depth=pinned["limits"]["maximum_receipt_json_depth"],
        maximum_nodes=pinned["limits"]["maximum_receipt_json_nodes"],
    )
    _enforce_json_tree_limits(
        expected_request,
        maximum_depth=pinned["limits"]["maximum_json_depth"],
        maximum_nodes=pinned["limits"]["maximum_json_nodes"],
    )
    if (
        isinstance(receipt, dict)
        and isinstance(receipt.get("authority"), dict)
        and receipt["authority"].get("decision_layer") == "closed_json_codec"
    ):
        try:
            raw = canonical_json_bytes(expected_request)
        except ReceiptRefusal:
            raw = json.dumps(
                expected_request,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=True,
            ).encode("utf-8")
        return verify_receipt_bytes(receipt, expected_request_bytes=raw, root=root)
    return _verify_admitted_receipt(
        receipt,
        expected_request=expected_request,
        root=root,
        pinned=pinned,
    )


def _verify_admitted_receipt(
    receipt: dict[str, Any],
    *,
    expected_request: dict[str, Any],
    root: Path,
    pinned: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(receipt, dict):
        raise ReceiptRefusal("receipt_schema_type_mismatch")
    _enforce_json_tree_limits(
        receipt,
        maximum_depth=pinned["limits"]["maximum_receipt_json_depth"],
        maximum_nodes=pinned["limits"]["maximum_receipt_json_nodes"],
    )
    receipt_bytes = canonical_json_bytes(receipt)
    if len(receipt_bytes) > pinned["limits"]["maximum_receipt_json_bytes"]:
        raise ReceiptRefusal("receipt_resource_limit_exceeded")
    if set(receipt) != {"schema", "pack_version", "request", "request_sha256", "authority", "result", "receipt_sha256"}:
        raise ReceiptRefusal("receipt_schema_fields_mismatch")
    if receipt["schema"] != RECEIPT_SCHEMA or receipt["pack_version"] != PACK_VERSION:
        raise ReceiptRefusal("receipt_schema_identity_mismatch")
    body = {key: receipt[key] for key in receipt if key != "receipt_sha256"}
    if sha256_bytes(canonical_json_bytes(body)) != receipt["receipt_sha256"]:
        raise ReceiptRefusal("receipt_digest_mismatch")
    expected_sha = sha256_bytes(canonical_json_bytes(expected_request))
    if receipt["request_sha256"] != expected_sha or receipt["request"] != expected_request:
        raise ReceiptRefusal("request_commitment_mismatch")
    authority = receipt["authority"]
    authority_keys = {
        "decision_layer",
        "anubis_invoked",
        "anubis_source_sha256",
        "anubis_binary_locator_id",
        "anubis_binary_sha256",
        "anubis_binary_size_bytes",
        "anubis_execution_binding",
        "pack_manifest_sha256",
        "protocol_sha256",
    }
    if not isinstance(authority, dict) or set(authority) != authority_keys:
        raise ReceiptRefusal("authority_schema_fields_mismatch")
    if authority.get("anubis_source_sha256") != pinned["source_sha256"]:
        raise ReceiptRefusal("anubis_source_identity_mismatch")
    if authority.get("anubis_binary_locator_id") != pinned["compiler_locator_id"]:
        raise ReceiptRefusal("anubis_binary_locator_identity_mismatch")
    if authority.get("anubis_binary_sha256") != pinned["compiler_sha256"]:
        raise ReceiptRefusal("anubis_binary_identity_mismatch")
    if authority.get("anubis_binary_size_bytes") != pinned["compiler_size"]:
        raise ReceiptRefusal("anubis_binary_size_identity_mismatch")
    if authority.get("anubis_execution_binding") != pinned["execution_binding"]:
        raise ReceiptRefusal("anubis_execution_binding_mismatch")
    if authority.get("pack_manifest_sha256") != pinned["manifest_sha256"]:
        raise ReceiptRefusal("pack_manifest_identity_mismatch")
    if authority.get("decision_layer") != "anubis_policy_kernel" or authority.get("anubis_invoked") is not True:
        raise ReceiptRefusal("anubis_authority_not_invoked")
    validate_shape(expected_request)
    if authority.get("protocol_sha256") != sha256_bytes(protocol_bytes(expected_request)):
        raise ReceiptRefusal("protocol_commitment_mismatch")
    try:
        runtime_result = _execute_anubis(expected_request, root=root, authority=pinned)
    except ReceiptRefusal:
        raise
    except (OSError, subprocess.SubprocessError) as exc:
        raise ReceiptRefusal("anubis_subprocess_spawn_failed") from exc
    if receipt["result"] != runtime_result:
        raise ReceiptRefusal("anubis_reexecution_mismatch")
    expected_result = replay_result(expected_request)
    if receipt["result"] != expected_result:
        raise ReceiptRefusal("independent_replay_mismatch")
    return receipt


def verify_receipt_bytes(
    receipt: dict[str, Any],
    *,
    expected_request_bytes: bytes,
    root: Path | None = None,
) -> dict[str, Any]:
    root = (root or Path(__file__).resolve().parents[1]).resolve()
    pinned = _manifest_authority(root)
    if not isinstance(receipt, dict):
        raise ReceiptRefusal("receipt_schema_type_mismatch")
    _enforce_json_tree_limits(
        receipt,
        maximum_depth=pinned["limits"]["maximum_receipt_json_depth"],
        maximum_nodes=pinned["limits"]["maximum_receipt_json_nodes"],
    )
    try:
        request = _decode_expected_request_bytes(expected_request_bytes, pinned["limits"])
        validate_shape(request)
        request_protocol = protocol_bytes(request)
        if len(request_protocol) > pinned["limits"]["maximum_protocol_bytes"]:
            raise ReceiptRefusal("protocol_resource_limit_exceeded")
        if request_protocol.count(b"\n") > pinned["limits"]["maximum_protocol_lines"]:
            raise ReceiptRefusal("protocol_resource_limit_exceeded")
        if _protocol_node_count(request) > pinned["limits"]["maximum_protocol_nodes"]:
            raise ReceiptRefusal("protocol_node_resource_limit_exceeded")
    except ReceiptRefusal as exc:
        codec_reason = str(exc).split(":", 1)[0]
        if set(receipt) != {"schema", "pack_version", "request", "request_sha256", "authority", "result", "receipt_sha256"}:
            raise ReceiptRefusal("receipt_schema_fields_mismatch")
        if receipt["schema"] != RECEIPT_SCHEMA or receipt["pack_version"] != PACK_VERSION:
            raise ReceiptRefusal("receipt_schema_identity_mismatch")
        receipt_bytes = canonical_json_bytes(receipt)
        if len(receipt_bytes) > pinned["limits"]["maximum_receipt_json_bytes"]:
            raise ReceiptRefusal("receipt_resource_limit_exceeded")
        body = {key: receipt[key] for key in receipt if key != "receipt_sha256"}
        if sha256_bytes(canonical_json_bytes(body)) != receipt["receipt_sha256"]:
            raise ReceiptRefusal("receipt_digest_mismatch")
        if receipt["request"] != _codec_request_marker(expected_request_bytes):
            raise ReceiptRefusal("request_commitment_mismatch")
        if receipt["request_sha256"] != sha256_bytes(expected_request_bytes):
            raise ReceiptRefusal("request_commitment_mismatch")
        authority = receipt["authority"]
        authority_keys = {
            "decision_layer", "anubis_invoked", "anubis_source_sha256",
            "anubis_binary_locator_id", "anubis_binary_sha256",
            "anubis_binary_size_bytes", "anubis_execution_binding",
            "pack_manifest_sha256", "protocol_sha256",
        }
        if not isinstance(authority, dict) or set(authority) != authority_keys:
            raise ReceiptRefusal("authority_schema_fields_mismatch")
        expected_authority = {
            "decision_layer": "closed_json_codec",
            "anubis_invoked": False,
            "anubis_source_sha256": pinned["source_sha256"],
            "anubis_binary_locator_id": pinned["compiler_locator_id"],
            "anubis_binary_sha256": pinned["compiler_sha256"],
            "anubis_binary_size_bytes": pinned["compiler_size"],
            "anubis_execution_binding": pinned["execution_binding"],
            "pack_manifest_sha256": pinned["manifest_sha256"],
            "protocol_sha256": "not_emitted",
        }
        if authority != expected_authority:
            raise ReceiptRefusal("codec_authority_mismatch")
        if receipt["result"] != refused(codec_reason):
            raise ReceiptRefusal("codec_refusal_replay_mismatch")
        return receipt
    if not isinstance(request, dict):
        raise ReceiptRefusal("schema_type_mismatch:request")
    authority = receipt.get("authority")
    if isinstance(authority, dict) and authority.get("decision_layer") == "closed_json_codec":
        raise ReceiptRefusal("codec_refusal_not_reproduced")
    return _verify_admitted_receipt(
        receipt,
        expected_request=request,
        root=root,
        pinned=pinned,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", required=True, type=Path)
    parser.add_argument("--expected-request", required=True, type=Path)
    args = parser.parse_args()
    try:
        root = Path(__file__).resolve().parents[1]
        pinned = _manifest_authority(root)
        receipt_raw = _read_regular_bounded(
            args.receipt,
            pinned["limits"]["maximum_receipt_json_bytes"],
            "receipt_input_unavailable",
        )
        request_raw = _read_regular_bounded(
            args.expected_request,
            pinned["limits"]["maximum_request_json_bytes"],
            "request_input_unavailable",
            allow_empty=True,
        )
        receipt = _decode_receipt_bytes(receipt_raw, pinned["limits"])
        verified = verify_receipt_bytes(
            receipt,
            expected_request_bytes=request_raw,
            root=root,
        )
    except ReceiptRefusal as exc:
        print(f"NAVIER_STOKES_RECEIPT_VERIFY=REFUSED reason={exc}")
        return 2
    print("NAVIER_STOKES_RECEIPT_VERIFY=PASS")
    print(f"NAVIER_STOKES_RECEIPT_SHA256={verified['receipt_sha256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
