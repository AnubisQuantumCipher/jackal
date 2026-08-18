#!/usr/bin/env python3
"""Untrusted fixture/orchestration layer for the Anubis Navier--Stokes pack.

The closed JSON codec lives here because Anubis v0.1 has no general JSON
parser.  All well-formed semantic decisions are made by
``domain_packs/pde/navier_stokes_v1.anb``.  The resulting receipt must be
independently replayed; this module is never a trust anchor by itself.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pwd
import resource
import selectors
import signal
import stat
import subprocess
import tempfile
import time
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
ZERO_FIELD_CANONICAL = (
    b"jackal-navier-stokes-zero-field-v1\nu0=0\nua=0\nforcing=0\n"
)
ZERO_FIELD_SHA256 = hashlib.sha256(ZERO_FIELD_CANONICAL).hexdigest()
ZERO_THEOREM_CANONICAL = (
    b"jackal-navier-stokes-zero-theorem-v1\n"
    b"claim=the-zero-field-solves-unforced-incompressible-navier-stokes\n"
    b"domain=T3_periodic\n"
)
ZERO_THEOREM_SHA256 = hashlib.sha256(ZERO_THEOREM_CANONICAL).hexdigest()
ZERO_PROOF_OBJECT_CANONICAL = (
    b"jackal-navier-stokes-zero-proof-object-v1\n"
    b"theorem=JACKAL_T3_ZERO_SOLUTION_IDENTITY_V1\n"
    b"representation=T3_ZERO_FOURIER_FIELD_V1\n"
    b"u0=0\nua=0\nforcing=0\ninitial_mismatch=0\npde_residual=0\n"
    b"divergence=0\ncontinuum_remainders=0\ndependency_graph=exact_identity\n"
)
ZERO_PROOF_OBJECT_SHA256 = hashlib.sha256(ZERO_PROOF_OBJECT_CANONICAL).hexdigest()
CCRT_SOURCE_SHA256 = "e815cbcdba8303dc03fb763bb0d10ce33660502ebd075b817359b9d05c89d76b"
ESS_SOURCE_SHA256 = "2712fad880a7c626c5b7cdb678052585f502f0bd53594b03e51ea16b149fcc19"

ROOT_KEYS = {
    "schema",
    "pack_version",
    "operation",
    "requested_claim",
    "allow_fallback",
    "model",
    "scope",
    "preconditions",
    "solution_link",
    "gate_data",
    "nonclaims",
}
MODEL_KEYS = {
    "dimension",
    "equation",
    "density",
    "forcing",
    "viscosity",
    "domain",
    "period",
    "measure_normalization",
    "pressure_gauge",
    "sign_convention",
}
SCOPE_KEYS = {
    "t0",
    "t1",
    "topology",
    "terminal_role",
    "initial_field_digest",
    "approximate_field_digest",
    "reconstruction_digest",
}
PRECONDITION_KEYS = {
    "smooth_initial",
    "divergence_free_initial",
    "exact_zero_forcing",
    "mean_zero",
    "solution_class",
}
SOLUTION_KEYS = {
    "theorem_id",
    "theorem_source_sha256",
    "theorem_locator",
    "m",
    "norm_id",
    "representation_id",
    "initial_mismatch_upper",
    "residual_integral_upper",
    "divergence_defect_upper",
    "eta_upper",
    "threshold_lower",
    "continuum_remainders_certified",
    "proof_object_id",
    "proof_object_digest",
}
INTERVAL_KEYS = {"lower", "upper"}
GATE_KEYS = {
    "gate_s": {"kind"},
    "gate_a": {"kind", "energy_t", "dissipation_integral", "energy_0", "norm_id"},
    "gate_b": {"kind", "identity_id", "dimension_id", "cutoff_kind", "cutoffs"},
    "gate_c": {
        "kind",
        "theorem_id",
        "theorem_source_sha256",
        "theorem_locator",
        "prefix_bound",
        "terminal_coverage",
        "continuum_norm_certified",
    },
    "gate_d": {
        "kind",
        "theorem_id",
        "theorem_source_sha256",
        "theorem_locator",
        "p",
        "q",
        "mixed_norm",
        "continuum_norm_certified",
        "time_embedding_factor",
    },
}
CUTOFF_KEYS = {
    "lambda",
    "w_truncated",
    "w_tail_upper",
    "d_truncated",
    "d_tail_upper",
    "tail_theorem_id",
    "tail_certificate_digest",
    "method_digest",
}


class SchemaRefusal(ValueError):
    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason
        self.detail = detail


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
    """Drain both pipes incrementally and kill before output can grow unbounded."""
    if process.stdout is None or process.stderr is None:
        _terminate_process_group(process)
        raise RuntimeError("Anubis output pipes are unavailable")
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
                raise RuntimeError("Anubis policy kernel timed out")
            events = selector.select(remaining)
            if not events:
                _terminate_process_group(process)
                raise RuntimeError("Anubis policy kernel timed out")
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
                    raise RuntimeError("Anubis output exceeded the manifest limit")
    finally:
        selector.close()
        for stream in buffers:
            stream.close()
    remaining = deadline - time.monotonic()
    try:
        return_code = process.wait(timeout=max(remaining, 0))
    except subprocess.TimeoutExpired as exc:
        _terminate_process_group(process)
        raise RuntimeError("Anubis policy kernel timed out") from exc
    return return_code, bytes(buffers[process.stdout]), bytes(buffers[process.stderr])


def _reject_json_float(token: str) -> Any:
    raise SchemaRefusal("noncanonical_numeric_type", token)


def _strict_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise SchemaRefusal("schema_duplicate_field", key)
        result[key] = value
    return result


def load_json_strict(path: Path, *, maximum_bytes: int = 4 * 1024 * 1024) -> Any:
    data = _read_regular_bounded(
        path,
        maximum_bytes,
        "json_input_unavailable",
        allow_empty=True,
    )
    try:
        text = data.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise SchemaRefusal("schema_invalid_utf8") from exc
    try:
        return json.loads(
            text,
            object_pairs_hook=_strict_pairs,
            parse_float=_reject_json_float,
            parse_constant=_reject_json_float,
        )
    except SchemaRefusal:
        raise
    except json.JSONDecodeError as exc:
        raise SchemaRefusal("schema_invalid_json", f"line={exc.lineno} column={exc.colno}") from exc


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


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
    reason: str,
    *,
    allow_empty: bool = False,
) -> bytes:
    try:
        descriptor = os.open(
            path,
            os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK,
        )
    except FileNotFoundError as exc:
        raise SchemaRefusal(reason) from exc
    except OSError as exc:
        raise SchemaRefusal(reason, "nonregular") from exc
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise SchemaRefusal(reason, "nonregular")
        if (metadata.st_size < 1 and not allow_empty) or metadata.st_size > maximum_bytes:
            raise SchemaRefusal(reason, "resource_limit")
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
        raise SchemaRefusal(reason, "changed_during_read")
    if len(data) > maximum_bytes:
        raise SchemaRefusal(reason, "resource_limit")
    return data


def _regular_path_identity(path: Path, reason: str) -> tuple[int, int, int, int, int]:
    if not path.is_absolute():
        raise SchemaRefusal(reason, "path_not_absolute")
    try:
        resolved = path.resolve(strict=True)
        metadata = os.stat(path, follow_symlinks=False)
    except (FileNotFoundError, OSError) as exc:
        raise SchemaRefusal(reason, "path_unavailable") from exc
    if resolved != path or not stat.S_ISREG(metadata.st_mode):
        raise SchemaRefusal(reason, "path_identity_mismatch")
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
        raise SchemaRefusal("anubis_binary_unavailable", "account_home") from exc
    saw_regular_candidate = False
    for relative in EXPECTED_ANUBIS_BINARY_RELATIVE_CANDIDATES:
        compiler = account_home / relative
        try:
            before = _regular_path_identity(compiler, "anubis_binary_unavailable")
        except SchemaRefusal:
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
            raise SchemaRefusal("anubis_binary_unavailable", "changed_during_read")
        if (
            len(compiler_data) == platform["anubis_binary_size_bytes"]
            and sha256_bytes(compiler_data) == platform["anubis_binary_sha256"]
        ):
            return compiler, compiler_data
    reason = "anubis_binary_identity_mismatch" if saw_regular_candidate else "anubis_binary_unavailable"
    raise SchemaRefusal(reason)


def _sanitized_execution_environment(temporary: str) -> dict[str, str]:
    try:
        account_home = Path(pwd.getpwuid(os.getuid()).pw_dir).resolve(strict=True)
    except (KeyError, OSError) as exc:
        raise SchemaRefusal("anubis_binary_unavailable", "account_home") from exc
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
        raise RuntimeError(f"{reason}:create_failed") from exc
    try:
        offset = 0
        while offset < len(data):
            written = os.write(descriptor, data[offset : offset + 1024 * 1024])
            if written < 1:
                raise RuntimeError(f"{reason}:short_write")
            offset += written
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    os.chmod(path, mode, follow_symlinks=False)
    identity = _regular_path_identity(path, reason)
    snapshot = _read_regular_bounded(path, len(data), reason)
    if identity[2] != len(data) or identity[4] != mode or snapshot != data:
        raise RuntimeError(f"{reason}:identity_mismatch")
    return identity


def _assert_authority_snapshot_unchanged(
    path: Path,
    data: bytes,
    identity: tuple[int, int, int, int, int],
    *,
    reason: str,
) -> None:
    if _regular_path_identity(path, reason) != identity:
        raise RuntimeError(f"{reason}:changed_during_execution")
    if _read_regular_bounded(path, len(data), reason) != data:
        raise RuntimeError(f"{reason}:changed_during_execution")


def _manifest_authority(root: Path) -> dict[str, Any]:
    manifest_path = root / "domain_packs/pde/navier_stokes_v1.json"
    data = _read_regular_bounded(manifest_path, MAXIMUM_MANIFEST_BYTES, "pack_manifest_unavailable")
    manifest_sha256 = sha256_bytes(data)
    if manifest_sha256 != EXPECTED_MANIFEST_SHA256:
        raise SchemaRefusal("pack_manifest_identity_mismatch")
    try:
        manifest = json.loads(
            data.decode("utf-8", errors="strict"),
            object_pairs_hook=_strict_pairs,
            parse_float=_reject_json_float,
            parse_constant=_reject_json_float,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SchemaRefusal("pack_manifest_invalid") from exc
    platform = manifest.get("platform") if isinstance(manifest, dict) else None
    limits = manifest.get("resource_limits") if isinstance(manifest, dict) else None
    registry = manifest.get("theorem_registry") if isinstance(manifest, dict) else None
    if not isinstance(platform, dict) or not isinstance(limits, dict) or not isinstance(registry, dict):
        raise SchemaRefusal("pack_manifest_schema_mismatch")
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
        raise SchemaRefusal("pack_manifest_authority_mismatch")
    zero = registry.get("JACKAL_T3_ZERO_SOLUTION_IDENTITY_V1")
    if not isinstance(zero, dict):
        raise SchemaRefusal("pack_manifest_schema_mismatch")
    for kind, path_key, digest_key in (
        ("representation", "representation_path", "representation_sha256"),
        ("theorem_source", "theorem_source_path", "theorem_source_sha256"),
        ("proof_object", "proof_object_path", "proof_object_sha256"),
    ):
        artifact = root / zero.get(path_key, "")
        artifact_data = _read_regular_bounded(
            artifact,
            limits.get("maximum_identity_artifact_bytes", 0),
            f"{kind}_unavailable",
        )
        if sha256_bytes(artifact_data) != zero.get(digest_key):
            raise SchemaRefusal(f"{kind}_identity_mismatch")
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
        theorem = registry.get(theorem_id)
        expected_path, expected_digest = expected_identity
        if not isinstance(theorem, dict) or (
            theorem.get("source_path"), theorem.get("source_sha256")
        ) != expected_identity:
            raise SchemaRefusal("pack_manifest_theorem_source_mismatch")
        if expected_identity in verified_sources:
            continue
        theorem_data = _read_regular_bounded(
            root / expected_path,
            limits.get("maximum_theorem_source_bytes", 0),
            "theorem_source_unavailable",
        )
        if sha256_bytes(theorem_data) != expected_digest:
            raise SchemaRefusal("theorem_source_identity_mismatch")
        verified_sources.add(expected_identity)
    source = root / platform.get("authoritative_source", "")
    source_data = _read_regular_bounded(
        source,
        limits.get("maximum_authoritative_source_bytes", 0),
        "anubis_source_unavailable",
    )
    source_sha256 = sha256_bytes(source_data)
    if source_sha256 != platform.get("authoritative_source_sha256"):
        raise SchemaRefusal("anubis_source_identity_mismatch")
    compiler, compiler_data = _read_exact_compiler(platform, limits)
    return {
        "manifest_sha256": manifest_sha256,
        "source": source,
        "source_sha256": source_sha256,
        "compiler": compiler,
        "compiler_bytes": compiler_data,
        "compiler_locator_id": platform["anubis_binary_locator_id"],
        "compiler_sha256": platform["anubis_binary_sha256"],
        "compiler_size": platform["anubis_binary_size_bytes"],
        "execution_binding": platform["anubis_execution_binding"],
        "source_bytes": source_data,
        "limits": limits,
    }


def _rejection_fingerprint_tree(
    value: Any,
    *,
    depth: int = 0,
    seen: set[int] | None = None,
) -> Any:
    """Build a bounded JSON-safe identity for input the JSON codec rejects."""
    if depth > 64:
        return {"type": "depth_limit"}
    seen = seen if seen is not None else set()
    if isinstance(value, float):
        return {"type": "noncanonical_float", "hex": value.hex()}
    if value is None or isinstance(value, (str, int, bool)):
        return {"type": type(value).__name__, "value": value}
    identity = id(value)
    if identity in seen:
        return {"type": "cycle"}
    seen.add(identity)
    if isinstance(value, dict):
        items = []
        for key, item in sorted(value.items(), key=lambda pair: repr(pair[0]))[:4096]:
            items.append([
                _rejection_fingerprint_tree(key, depth=depth + 1, seen=seen),
                _rejection_fingerprint_tree(item, depth=depth + 1, seen=seen),
            ])
        result: Any = {"type": "dict", "items": items, "truncated": len(value) > 4096}
    elif isinstance(value, (list, tuple)):
        result = {
            "type": type(value).__name__,
            "items": [
                _rejection_fingerprint_tree(item, depth=depth + 1, seen=seen)
                for item in value[:4096]
            ],
            "truncated": len(value) > 4096,
        }
    else:
        result = {"type": type(value).__name__, "repr": repr(value)[:4096]}
    seen.remove(identity)
    return result


def _enforce_json_tree_limits(value: Any, *, maximum_depth: int, maximum_nodes: int) -> None:
    stack: list[tuple[Any, int]] = [(value, 1)]
    nodes = 0
    while stack:
        item, depth = stack.pop()
        nodes += 1
        if nodes > maximum_nodes:
            raise SchemaRefusal("schema_resource_limit", "json_nodes")
        if depth > maximum_depth:
            raise SchemaRefusal("schema_resource_limit", "json_depth")
        if isinstance(item, dict):
            stack.extend((child, depth + 1) for child in item.values())
        elif isinstance(item, list):
            stack.extend((child, depth + 1) for child in item)


def _decode_request_bytes(raw: bytes, limits: dict[str, Any]) -> Any:
    if len(raw) > limits["maximum_request_json_bytes"]:
        raise SchemaRefusal("schema_resource_limit", "request_bytes")
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise SchemaRefusal("schema_invalid_utf8") from exc
    try:
        request = json.loads(
            text,
            object_pairs_hook=_strict_pairs,
            parse_float=_reject_json_float,
            parse_constant=_reject_json_float,
        )
    except SchemaRefusal:
        raise
    except (json.JSONDecodeError, RecursionError) as exc:
        reason = "schema_resource_limit" if isinstance(exc, RecursionError) else "schema_invalid_json"
        raise SchemaRefusal(reason) from exc
    _enforce_json_tree_limits(
        request,
        maximum_depth=limits["maximum_json_depth"],
        maximum_nodes=limits["maximum_json_nodes"],
    )
    return request


def _codec_request_marker(raw: bytes) -> dict[str, Any]:
    return {
        "codec_input_kind": "raw_json_bytes",
        "raw_request_bytes": len(raw),
        "raw_request_sha256": sha256_bytes(raw),
    }


def _codec_refusal_receipt(
    raw: bytes,
    *,
    reason: str,
    pinned: dict[str, Any],
) -> dict[str, Any]:
    marker = _codec_request_marker(raw)
    body = {
        "schema": RECEIPT_SCHEMA,
        "pack_version": PACK_VERSION,
        "request": marker,
        "request_sha256": sha256_bytes(raw),
        "authority": {
            "decision_layer": "closed_json_codec",
            "anubis_invoked": False,
            "anubis_source_sha256": pinned["source_sha256"],
            "anubis_binary_locator_id": pinned["compiler_locator_id"],
            "anubis_binary_sha256": pinned["compiler_sha256"],
            "anubis_binary_size_bytes": pinned["compiler_size"],
            "anubis_execution_binding": pinned["execution_binding"],
            "pack_manifest_sha256": pinned["manifest_sha256"],
            "protocol_sha256": "not_emitted",
        },
        "result": _default_result("refused", reason),
    }
    return _receipt_with_digest(body)


def _closed_object(value: Any, expected: set[str], where: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise SchemaRefusal("schema_type_mismatch", where)
    actual = set(value)
    unknown = sorted(actual - expected)
    missing = sorted(expected - actual)
    if unknown:
        raise SchemaRefusal("schema_unknown_field", f"{where}.{unknown[0]}")
    if missing:
        raise SchemaRefusal("schema_missing_field", f"{where}.{missing[0]}")
    if len(value) != len(expected):
        raise SchemaRefusal("schema_duplicate_field", where)
    return value


def _reject_non_json_numbers(value: Any, where: str = "request") -> None:
    if isinstance(value, float):
        raise SchemaRefusal("noncanonical_numeric_type", where)
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise SchemaRefusal("schema_nonstring_key", where)
            _reject_non_json_numbers(item, f"{where}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _reject_non_json_numbers(item, f"{where}[{index}]")
    elif value is not None and not isinstance(value, (str, int, bool)):
        raise SchemaRefusal("schema_type_mismatch", where)


def _atom(value: Any, where: str) -> str:
    if not isinstance(value, str):
        raise SchemaRefusal("schema_type_mismatch", where)
    if any(token in value for token in ("\n", "\r", "=", "|", "~")):
        raise SchemaRefusal("protocol_delimiter_injection", where)
    if len(value.encode("utf-8")) > 4096:
        raise SchemaRefusal("schema_resource_limit", where)
    return value


def _digest_atom(value: Any, where: str) -> str:
    atom = _atom(value, where)
    if len(atom) != 64 or any(char not in "0123456789abcdef" for char in atom):
        raise SchemaRefusal("schema_invalid_digest", where)
    return atom


def _bool(value: Any, where: str) -> bool:
    if type(value) is not bool:
        raise SchemaRefusal("schema_type_mismatch", where)
    return value


def _integer(value: Any, where: str) -> int:
    if type(value) is not int:
        raise SchemaRefusal("schema_type_mismatch", where)
    if value < 0 or value > 1_000_000:
        raise SchemaRefusal("schema_resource_limit", where)
    return value


def _interval(value: Any, where: str) -> dict[str, str]:
    obj = _closed_object(value, INTERVAL_KEYS, where)
    _atom(obj["lower"], f"{where}.lower")
    _atom(obj["upper"], f"{where}.upper")
    return obj


def validate_request_shape(request: Any) -> dict[str, Any]:
    _reject_non_json_numbers(request)
    root = _closed_object(request, ROOT_KEYS, "request")
    _atom(root["schema"], "request.schema")
    _atom(root["pack_version"], "request.pack_version")
    operation = _atom(root["operation"], "request.operation")
    _atom(root["requested_claim"], "request.requested_claim")
    _bool(root["allow_fallback"], "request.allow_fallback")

    model = _closed_object(root["model"], MODEL_KEYS, "request.model")
    _integer(model["dimension"], "request.model.dimension")
    for key in MODEL_KEYS - {"dimension"}:
        _atom(model[key], f"request.model.{key}")

    scope = _closed_object(root["scope"], SCOPE_KEYS, "request.scope")
    for key in SCOPE_KEYS:
        if key.endswith("_digest"):
            _digest_atom(scope[key], f"request.scope.{key}")
        else:
            _atom(scope[key], f"request.scope.{key}")

    pre = _closed_object(root["preconditions"], PRECONDITION_KEYS, "request.preconditions")
    for key in PRECONDITION_KEYS - {"solution_class"}:
        _bool(pre[key], f"request.preconditions.{key}")
    _atom(pre["solution_class"], "request.preconditions.solution_class")

    solution = root["solution_link"]
    if solution is not None:
        solution = _closed_object(solution, SOLUTION_KEYS, "request.solution_link")
        _integer(solution["m"], "request.solution_link.m")
        _bool(
            solution["continuum_remainders_certified"],
            "request.solution_link.continuum_remainders_certified",
        )
        for key in SOLUTION_KEYS - {"m", "continuum_remainders_certified"}:
            validator = _digest_atom if key in {"theorem_source_sha256", "proof_object_digest"} else _atom
            validator(solution[key], f"request.solution_link.{key}")

    if operation not in GATE_KEYS:
        raise SchemaRefusal("operation_not_admitted", "request.operation")
    expected_gate_keys = GATE_KEYS[operation]
    gate = _closed_object(root["gate_data"], expected_gate_keys, "request.gate_data")
    if operation == "gate_s":
        _atom(gate["kind"], "request.gate_data.kind")
    elif operation == "gate_a":
        _atom(gate["kind"], "request.gate_data.kind")
        _interval(gate["energy_t"], "request.gate_data.energy_t")
        _interval(gate["dissipation_integral"], "request.gate_data.dissipation_integral")
        _interval(gate["energy_0"], "request.gate_data.energy_0")
        _atom(gate["norm_id"], "request.gate_data.norm_id")
    elif operation == "gate_b":
        for key in ("kind", "identity_id", "dimension_id", "cutoff_kind"):
            _atom(gate[key], f"request.gate_data.{key}")
        if not isinstance(gate["cutoffs"], list) or not gate["cutoffs"] or len(gate["cutoffs"]) > 128:
            raise SchemaRefusal("cutoff_sequence_invalid", "request.gate_data.cutoffs")
        for index, item in enumerate(gate["cutoffs"]):
            item = _closed_object(item, CUTOFF_KEYS, f"request.gate_data.cutoffs[{index}]")
            for key in ("lambda", "tail_theorem_id"):
                _atom(item[key], f"request.gate_data.cutoffs[{index}].{key}")
            for key in ("tail_certificate_digest", "method_digest"):
                _digest_atom(item[key], f"request.gate_data.cutoffs[{index}].{key}")
            for key in ("w_truncated", "w_tail_upper", "d_truncated", "d_tail_upper"):
                _interval(item[key], f"request.gate_data.cutoffs[{index}].{key}")
    elif operation == "gate_c":
        for key in ("kind", "theorem_id", "theorem_locator"):
            _atom(gate[key], f"request.gate_data.{key}")
        _digest_atom(gate["theorem_source_sha256"], "request.gate_data.theorem_source_sha256")
        _interval(gate["prefix_bound"], "request.gate_data.prefix_bound")
        _bool(gate["terminal_coverage"], "request.gate_data.terminal_coverage")
        _bool(gate["continuum_norm_certified"], "request.gate_data.continuum_norm_certified")
    elif operation == "gate_d":
        for key in (
            "kind",
            "theorem_id",
            "theorem_locator",
            "p",
            "q",
            "time_embedding_factor",
        ):
            _atom(gate[key], f"request.gate_data.{key}")
        _digest_atom(gate["theorem_source_sha256"], "request.gate_data.theorem_source_sha256")
        _interval(gate["mixed_norm"], "request.gate_data.mixed_norm")
        _bool(gate["continuum_norm_certified"], "request.gate_data.continuum_norm_certified")

    if not isinstance(root["nonclaims"], list) or not root["nonclaims"]:
        raise SchemaRefusal("schema_type_mismatch", "request.nonclaims")
    for index, item in enumerate(root["nonclaims"]):
        _atom(item, f"request.nonclaims[{index}]")
    required_nonclaims = {
        "not_global_regular",
        "not_smooth_for_all_time",
        "not_millennium_solved",
    }
    if set(root["nonclaims"]) != required_nonclaims or len(root["nonclaims"]) != 3:
        raise SchemaRefusal("required_nonclaim_missing", "request.nonclaims")
    return root


def _bool_text(value: bool) -> str:
    return "true" if value else "false"


def protocol_lines(request: dict[str, Any]) -> list[str]:
    model = request["model"]
    scope = request["scope"]
    pre = request["preconditions"]
    solution = request["solution_link"]
    if solution is None:
        solution = {
            "theorem_id": "",
            "theorem_source_sha256": "",
            "theorem_locator": "",
            "m": 0,
            "norm_id": "",
            "representation_id": "",
            "initial_mismatch_upper": "",
            "residual_integral_upper": "",
            "divergence_defect_upper": "",
            "eta_upper": "",
            "threshold_lower": "",
            "continuum_remainders_certified": False,
            "proof_object_id": "",
            "proof_object_digest": "",
        }
    lines = [
        f"schema={request['schema']}",
        f"pack_version={request['pack_version']}",
        f"operation={request['operation']}",
        f"requested_claim={request['requested_claim']}",
        f"allow_fallback={_bool_text(request['allow_fallback'])}",
        f"dimension={model['dimension']}",
        f"equation={model['equation']}",
        f"density={model['density']}",
        f"forcing={model['forcing']}",
        f"viscosity={model['viscosity']}",
        f"domain={model['domain']}",
        "domain_geometry=periodic_cube_or_whole_space_v1",
        f"period={model['period']}",
        f"measure_normalization={model['measure_normalization']}",
        f"pressure_gauge={model['pressure_gauge']}",
        f"sign_convention={model['sign_convention']}",
        f"t0={scope['t0']}",
        f"t1={scope['t1']}",
        f"topology={scope['topology']}",
        f"initial_field_digest={scope['initial_field_digest']}",
        f"approximate_field_digest={scope['approximate_field_digest']}",
        f"reconstruction_digest={scope['reconstruction_digest']}",
        f"terminal_role={scope['terminal_role']}",
        f"solution_class={pre['solution_class']}",
        f"smooth_initial={_bool_text(pre['smooth_initial'])}",
        f"divergence_free_initial={_bool_text(pre['divergence_free_initial'])}",
        f"exact_zero_forcing={_bool_text(pre['exact_zero_forcing'])}",
        f"mean_zero={_bool_text(pre['mean_zero'])}",
        "scope_semantics=bounded_time_scope_only",
        f"solution_present={_bool_text(request['solution_link'] is not None)}",
        f"solution_theorem_id={solution['theorem_id']}",
        f"solution_theorem_sha256={solution['theorem_source_sha256']}",
        f"solution_theorem_locator={solution['theorem_locator']}",
        f"solution_m={solution['m']}",
        f"solution_norm_id={solution['norm_id']}",
        f"solution_representation_id={solution['representation_id']}",
        f"solution_initial_mismatch_upper={solution['initial_mismatch_upper']}",
        f"solution_residual_integral_upper={solution['residual_integral_upper']}",
        f"solution_divergence_defect_upper={solution['divergence_defect_upper']}",
        f"solution_eta_upper={solution['eta_upper']}",
        f"solution_threshold_lower={solution['threshold_lower']}",
        f"solution_continuum_remainders_certified={_bool_text(solution['continuum_remainders_certified'])}",
        f"solution_proof_object_id={solution['proof_object_id']}",
        f"solution_proof_object_digest={solution['proof_object_digest']}",
        f"gate_payload={_gate_payload(request)}",
    ]
    if len(lines) != 45:
        raise AssertionError(f"protocol line count drift: {len(lines)}")
    return lines


def _gate_payload(request: dict[str, Any]) -> str:
    gate = request["gate_data"]
    operation = request["operation"]
    reconstruction = request["scope"]["reconstruction_digest"]
    if operation == "gate_s":
        return gate["kind"]
    if operation == "gate_a":
        return "|".join(
            [
                gate["kind"],
                gate["energy_t"]["lower"],
                gate["energy_t"]["upper"],
                gate["dissipation_integral"]["lower"],
                gate["dissipation_integral"]["upper"],
                gate["energy_0"]["lower"],
                gate["energy_0"]["upper"],
                gate["norm_id"],
            ]
        )
    if operation == "gate_b":
        records = []
        for item in gate["cutoffs"]:
            records.append(
                "~".join(
                    [
                        item["lambda"],
                        item["w_truncated"]["lower"],
                        item["w_truncated"]["upper"],
                        item["w_tail_upper"]["lower"],
                        item["w_tail_upper"]["upper"],
                        item["d_truncated"]["lower"],
                        item["d_truncated"]["upper"],
                        item["d_tail_upper"]["lower"],
                        item["d_tail_upper"]["upper"],
                        item["tail_theorem_id"],
                        item["tail_certificate_digest"],
                        item["method_digest"],
                        reconstruction,
                    ]
                )
            )
        return "|".join(
            [
                gate["kind"],
                gate["identity_id"],
                gate["dimension_id"],
                gate["cutoff_kind"],
                str(len(records)),
                ";".join(records),
            ]
        )
    if operation == "gate_c":
        return "|".join(
            [
                gate["kind"],
                gate["theorem_id"],
                gate["theorem_source_sha256"],
                gate["theorem_locator"],
                gate["prefix_bound"]["lower"],
                gate["prefix_bound"]["upper"],
                _bool_text(gate["terminal_coverage"]),
                _bool_text(gate["continuum_norm_certified"]),
                reconstruction,
            ]
        )
    if operation == "gate_d":
        return "|".join(
            [
                gate["kind"],
                gate["theorem_id"],
                gate["theorem_source_sha256"],
                gate["theorem_locator"],
                gate["p"],
                gate["q"],
                gate["mixed_norm"]["lower"],
                gate["mixed_norm"]["upper"],
                _bool_text(gate["continuum_norm_certified"]),
                reconstruction,
                gate["time_embedding_factor"],
            ]
        )
    return "unknown_operation"


def _protocol_node_count(request: dict[str, Any]) -> int:
    if request["operation"] == "gate_b":
        return 45 + 13 * len(request["gate_data"]["cutoffs"])
    return 45


def _default_result(status: str, reason: str) -> dict[str, Any]:
    return {
        "status": status,
        "reason": reason,
        "arithmetic_status": "NOT_CHECKED",
        "continuum_status": "NOT_VERIFIED",
        "solution_link_status": "NOT_VERIFIED",
        "theorem_status": "NOT_APPLICABLE",
        "conclusion_status": "NONE",
        "halt": True,
        "ratio_upper": "not_computed",
        "comparison_margin": "not_computed",
        "failed_cutoff": "none",
        "evaluated_cutoff_count": 0,
        "mathematical_implication": "none",
        "nonclaim": "not_a_global_regularity_result",
        "transcript": f"refused:{reason}",
    }


def _parse_anubis_output(stdout: str, expected_protocol_sha256: str) -> dict[str, Any]:
    wanted = {
        "status",
        "reason",
        "arithmetic_status",
        "continuum_status",
        "solution_link_status",
        "theorem_status",
        "conclusion_status",
        "halt",
        "ratio_upper",
        "comparison_margin",
        "failed_cutoff",
        "evaluated_cutoff_count",
        "mathematical_implication",
        "nonclaim",
        "transcript",
        "protocol_sha256",
    }
    parsed: dict[str, str] = {}
    for raw in stdout.splitlines():
        if "=" not in raw:
            continue
        key, value = raw.split("=", 1)
        if key in wanted:
            if key in parsed:
                raise RuntimeError(f"duplicate Anubis output field: {key}")
            parsed[key] = value
    if set(parsed) != wanted:
        raise RuntimeError(f"Anubis output fields mismatch: missing={sorted(wanted-set(parsed))}")
    if parsed.pop("protocol_sha256") != expected_protocol_sha256:
        raise RuntimeError("Anubis protocol digest mismatch")
    halt = parsed.pop("halt")
    if halt not in {"true", "false"}:
        raise RuntimeError("Anubis halt field is not canonical bool")
    evaluated = parsed.pop("evaluated_cutoff_count")
    if not evaluated.isascii() or not evaluated.isdigit():
        raise RuntimeError("Anubis cutoff count is not canonical int")
    if evaluated != str(int(evaluated)) or int(evaluated) > 128:
        raise RuntimeError("Anubis cutoff count exceeds the manifest limit")
    result: dict[str, Any] = dict(parsed)
    result["halt"] = halt == "true"
    result["evaluated_cutoff_count"] = int(evaluated)
    return result


def _receipt_with_digest(body: dict[str, Any]) -> dict[str, Any]:
    receipt = dict(body)
    receipt["receipt_sha256"] = sha256_bytes(canonical_json_bytes(body))
    return receipt


def receipt_exit_code(result: dict[str, Any]) -> int:
    """Map a mathematical result to a fail-closed command-line status."""
    if result.get("status") == "bounded" and result.get("halt") is False:
        return 0
    if result.get("status") == "refused":
        return 2
    return 3


def produce_receipt(
    request: Any,
    *,
    root: Path | None = None,
) -> dict[str, Any]:
    root = (root or Path(__file__).resolve().parents[1]).resolve()
    pinned = _manifest_authority(root)

    try:
        _enforce_json_tree_limits(
            request,
            maximum_depth=pinned["limits"]["maximum_json_depth"],
            maximum_nodes=pinned["limits"]["maximum_json_nodes"],
        )
        request_bytes = canonical_json_bytes(request)
    except SchemaRefusal as exc:
        request_bytes = canonical_json_bytes(_rejection_fingerprint_tree(request))
        return _codec_refusal_receipt(request_bytes, reason=exc.reason, pinned=pinned)
    except (TypeError, ValueError, OverflowError, RecursionError):
        try:
            request_bytes = json.dumps(
                request,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=True,
            ).encode("utf-8")
        except (TypeError, ValueError, OverflowError, RecursionError):
            request_bytes = canonical_json_bytes(_rejection_fingerprint_tree(request))
    request_sha = sha256_bytes(request_bytes)
    if len(request_bytes) > pinned["limits"]["maximum_request_json_bytes"]:
        return _codec_refusal_receipt(
            request_bytes,
            reason="schema_resource_limit",
            pinned=pinned,
        )
    try:
        validate_request_shape(request)
    except SchemaRefusal as exc:
        return _codec_refusal_receipt(request_bytes, reason=exc.reason, pinned=pinned)

    lines = protocol_lines(request)
    if len(lines) > pinned["limits"]["maximum_protocol_lines"]:
        return _codec_refusal_receipt(
            request_bytes,
            reason="protocol_resource_limit_exceeded",
            pinned=pinned,
        )
    if _protocol_node_count(request) > pinned["limits"]["maximum_protocol_nodes"]:
        return _codec_refusal_receipt(
            request_bytes,
            reason="protocol_node_resource_limit_exceeded",
            pinned=pinned,
        )
    protocol = ("\n".join(lines) + "\n").encode("utf-8")
    if len(protocol) > pinned["limits"]["maximum_protocol_bytes"]:
        return _codec_refusal_receipt(
            request_bytes,
            reason="protocol_resource_limit_exceeded",
            pinned=pinned,
        )
    protocol_sha = sha256_bytes(protocol)
    source_sha = pinned["source_sha256"]
    with tempfile.TemporaryDirectory(prefix="jackal-navier-request-") as temporary:
        temporary_path = Path(temporary).resolve(strict=True)
        native_out = temporary_path / "native"
        protocol_path = temporary_path / "request.protocol"
        compiler_snapshot = temporary_path / "anubis-authority.snapshot"
        source_snapshot = temporary_path / "navier-stokes-authority.snapshot.anb"
        protocol_path.write_bytes(protocol)
        compiler_identity = _write_authority_snapshot(
            compiler_snapshot,
            pinned["compiler_bytes"],
            mode=0o500,
            reason="anubis_binary_snapshot",
        )
        source_identity = _write_authority_snapshot(
            source_snapshot,
            pinned["source_bytes"],
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
            preexec_fn=lambda: _bound_child_process(pinned["limits"]),
        )
        return_code, stdout_bytes, stderr_bytes = _communicate_bounded(
            process,
            maximum_output_bytes=pinned["limits"]["maximum_anubis_output_bytes"],
            timeout_seconds=pinned["limits"]["anubis_subprocess_timeout_seconds"],
        )
        try:
            stdout = stdout_bytes.decode("utf-8", errors="strict")
            stderr = stderr_bytes.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise RuntimeError("Anubis output is not canonical UTF-8") from exc
        _assert_authority_snapshot_unchanged(
            compiler_snapshot,
            pinned["compiler_bytes"],
            compiler_identity,
            reason="anubis_binary_snapshot",
        )
        _assert_authority_snapshot_unchanged(
            source_snapshot,
            pinned["source_bytes"],
            source_identity,
            reason="anubis_source_snapshot",
        )
    if return_code != 0:
        raise RuntimeError(
            "Anubis policy kernel failed closed outside its result protocol: "
            f"rc={return_code} stderr={stderr[-2000:]} stdout={stdout[-2000:]}"
        )
    result = _parse_anubis_output(stdout, protocol_sha)
    body = {
        "schema": RECEIPT_SCHEMA,
        "pack_version": PACK_VERSION,
        "request": request,
        "request_sha256": request_sha,
        "authority": {
            "decision_layer": "anubis_policy_kernel",
            "anubis_invoked": True,
            "anubis_source_sha256": source_sha,
            "anubis_binary_locator_id": pinned["compiler_locator_id"],
            "anubis_binary_sha256": pinned["compiler_sha256"],
            "anubis_binary_size_bytes": pinned["compiler_size"],
            "anubis_execution_binding": pinned["execution_binding"],
            "pack_manifest_sha256": pinned["manifest_sha256"],
            "protocol_sha256": protocol_sha,
        },
        "result": result,
    }
    receipt = _receipt_with_digest(body)
    _enforce_json_tree_limits(
        receipt,
        maximum_depth=pinned["limits"]["maximum_receipt_json_depth"],
        maximum_nodes=pinned["limits"]["maximum_receipt_json_nodes"],
    )
    if len(canonical_json_bytes(receipt)) > pinned["limits"]["maximum_receipt_json_bytes"]:
        raise RuntimeError("receipt exceeded the manifest limit")
    return receipt


def produce_receipt_from_json_bytes(
    raw: bytes,
    *,
    root: Path | None = None,
) -> dict[str, Any]:
    root = (root or Path(__file__).resolve().parents[1]).resolve()
    pinned = _manifest_authority(root)
    try:
        request = _decode_request_bytes(raw, pinned["limits"])
        validate_request_shape(request)
    except SchemaRefusal as exc:
        return _codec_refusal_receipt(raw, reason=exc.reason, pinned=pinned)
    return produce_receipt(request, root=root)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    try:
        pinned = _manifest_authority(root)
        raw = _read_regular_bounded(
            args.request,
            pinned["limits"]["maximum_request_json_bytes"],
            "request_input_unavailable",
            allow_empty=True,
        )
        receipt = produce_receipt_from_json_bytes(raw, root=root)
    except (SchemaRefusal, RuntimeError, OSError, subprocess.SubprocessError) as exc:
        print(f"NAVIER_STOKES_RECEIPT_STATUS=REFUSED reason={exc}")
        return 2
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes(canonical_json_bytes(receipt) + b"\n")
    print(f"NAVIER_STOKES_RECEIPT_STATUS={receipt['result']['status']}")
    print(f"NAVIER_STOKES_RECEIPT_SHA256={receipt['receipt_sha256']}")
    return receipt_exit_code(receipt["result"])


if __name__ == "__main__":
    raise SystemExit(main())
