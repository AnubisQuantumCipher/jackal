#!/usr/bin/env python3
"""Strict live acceptance for the installed JACKAL Codex plugin.

The default mode is a non-mutating dry run.  ``--live`` performs only a local
marketplace install inside a newly created temporary ``CODEX_HOME`` and then
exercises the already provisioned, caller-selected runtime.  It never downloads
or provisions runtime bytes.
"""

from __future__ import annotations

import argparse
import base64
import copy
import hashlib
import json
import os
import pwd
import re
import select
import selectors
import secrets
import signal
import stat
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from plugins.jackel.scripts import provision_runtime as provisioner  # noqa: E402
from plugins.jackel.scripts import verify_plugin as identity  # noqa: E402


PLUGIN_ROOT = REPOSITORY_ROOT / "plugins" / "jackel"
MARKETPLACE = "anubis-quantum-cipher"
PLUGIN = "jackel"
MCP_PROTOCOL_VERSION = "2025-11-25"
# Anti-shrink floor, not an exact count.  This module is driven with two
# different catalogs: the REPO `plugin/hermes/tools.json` (repo test) and the
# SEALED RELEASE catalog the provisioner downloads (installed-config run).  The
# substantive inventory invariant is `discovered == expected` plus uniqueness,
# which is exact and catalog-agnostic; an absolute count here would go stale
# against whichever of the two surfaces moved, and pinning it to one silently
# stops checking the other.  34 is the smallest surface either has ever
# shipped, so a catalog that SHRANK below it still refuses.
MIN_TOOL_COUNT = 34
HOST_TRANSCRIPT_LIMIT = 4 * 1024 * 1024
HOST_REGISTRY_LIMIT = 1024 * 1024
HOST_REGISTRY_ENTRY_LIMIT = 256
HOST_STDERR_LIMIT = 256 * 1024
HOST_EVENT_LIMIT = 1024
HOST_EVENT_DEPTH_LIMIT = 64
HOST_TASK_TIMEOUT = 900.0
HOST_REGISTRY_TIMEOUT = 30.0
HOST_BINARY_VERSION_TIMEOUT = 10.0
HOST_BINARY_VERSION_LIMIT = 1024
HOST_BINARY_BYTE_LIMIT = 512 * 1024 * 1024
HOST_BINARY_PATH_LIMIT = 4096

HERMES_BUNDLE_SHA256 = "d141c909e8f5f03e268a2112f291e6bd79fafff906522eb7ca9accc247a3274b"
INT_CERT_PRODUCER_SHA256 = "b4240fdac3c77b2abd751595303b2b3a0e4bebd492b2ae57fa5ccf052cd50af4"
INT_CERT_CHECKER_SHA256 = "c858e3bfc0ff2809a808170caabbf090077cb54996e76f065dbcd26ffb067d49"

CLAIM_TIME = "1786752000"
CLAIM_NONCE = "jackal-codex-task5-v1"
CLAIM_RELEASE_EPOCH = "v1.6.0"
FORMAL_RELEASE_EPOCH = "v1.7.0"

DEFAULT_POLICY = {
    "schema": "jackal-claim-policy-v1",
    "policy_id": "jackal-default-v1",
    "accept": {
        "input_provenance": ["supplied", "integrity-bound"],
        "model_validity": ["not-applicable", "assumed"],
        "mathematical": ["checked", "bounded", "formal-bounded", "exact"],
        "implementation": [
            "directly-trusted", "campaign-tested", "independently-recomputed",
            "checker-derived",
        ],
        "artifact_required_flags": {},
    },
    "require": {
        "max_nodes": 128,
        "max_depth": 32,
        "require_nonce": False,
        "max_age_seconds": None,
        "decision_margin_min": None,
        "max_enclosure_width": None,
        "forbid_rules": [],
    },
    "allow_fallback": False,
}

EXPECTED_ROOT_PROPOSITION = {
    "t": "in",
    "arg": {
        "t": "app",
        "fn": "mod_pow",
        "args": [
            {"t": "rat", "v": "3"},
            {"t": "rat", "v": "100"},
            {"t": "rat", "v": "7"},
        ],
    },
    "set": {"t": "interval", "lo": "4", "hi": "4"},
}

CLAIM_REQUEST = {
    "schema": "jackal-claim-request-v1",
    "emitted_at_unix": CLAIM_TIME,
    "nonce": CLAIM_NONCE,
    "steps": [
        {
            "id": "p", "op": "exact", "command": "mod-pow",
            "args": ["3", "100", "7"],
        }
    ],
    "root": "p",
}

EXACT_ARGUMENTS = {"expression": "0.1+0.2"}
FORMAL_ARGUMENTS = {
    "expression": "sin(x)", "input_lo": "0", "input_hi": "1",
    "tolerance": "1/100",
}
UNSUPPORTED_FORMAL_ARGUMENTS = {
    "expression": "exp(x)", "input_lo": "0", "input_hi": "1",
    "tolerance": "1/10",
}


class AcceptanceError(RuntimeError):
    """A named acceptance invariant did not hold."""


class _DuplicateJSONKey(ValueError):
    pass


def _object_pairs(pairs: Sequence[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateJSONKey(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError(f"non-standard JSON value: {value}")


def strict_json_loads(raw: str | bytes) -> Any:
    return json.loads(
        raw, object_pairs_hook=_object_pairs, parse_constant=_reject_constant,
    )


def canonical_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value, ensure_ascii=False, allow_nan=False,
            sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise AcceptanceError("value is not canonical strict JSON") from error


def canonical_sha256(value: object) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


DEFAULT_POLICY_SHA256 = canonical_sha256(DEFAULT_POLICY)
EXPECTED_ROOT_PROPOSITION_SHA256 = canonical_sha256(EXPECTED_ROOT_PROPOSITION)

if DEFAULT_POLICY_SHA256 != "3ef0655ad2a3f9b553f7c4b9f7af2d4cfdd71c150f4a0337b0da0cea32fd8410":
    raise RuntimeError("independent default policy constant drifted")
if EXPECTED_ROOT_PROPOSITION_SHA256 != \
        "e6740fdaa34c63f07b037dd131191b92a8420ea902515cbfab94e9073f1ca269":
    raise RuntimeError("independent root proposition constant drifted")


def receipt_digest(receipt: Mapping[str, Any]) -> str:
    body = {key: value for key, value in receipt.items()
            if key != "receipt_digest_sha256"}
    return canonical_sha256(body)


def verify_wrapper(
    plugin_root: Path | str,
    *,
    trusted_manifest: Path | str | None = None,
    expected_aggregate: str | None = None,
) -> str:
    root = Path(plugin_root)
    manifest = root / "PLUGIN_IDENTITY.sha256" \
        if trusted_manifest is None else Path(trusted_manifest)
    try:
        records = identity.verify_manifest(root, manifest)
        aggregate = identity.aggregate_digest(records)
        if expected_aggregate is not None:
            identity.require_expected_aggregate(records, expected_aggregate)
    except identity.ManifestError as error:
        raise AcceptanceError("wrapper identity verification refused") from error
    return aggregate


def _manifest_name_version(path: Path) -> tuple[str, str] | None:
    try:
        raw = identity._read_regular_file_nofollow(path, "plugin manifest")
        document = strict_json_loads(raw)
    except (identity.ManifestError, OSError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(document, dict):
        return None
    name, version = document.get("name"), document.get("version")
    if not isinstance(name, str) or not isinstance(version, str):
        return None
    return name, version


def locate_cache_copy(
    codex_home: Path | str,
    source_plugin: Path | str,
    *,
    marketplace: str = MARKETPLACE,
    plugin: str = PLUGIN,
    expected_aggregate: str,
) -> Path:
    """Locate one opaque-version cache copy and bind it to source manifest bytes."""
    source = Path(source_plugin)
    source_name_version = _manifest_name_version(
        source / ".codex-plugin" / "plugin.json"
    )
    if source_name_version is None or source_name_version[0] != plugin:
        raise AcceptanceError("source plugin manifest identity is invalid")
    trusted_manifest = source / "PLUGIN_IDENTITY.sha256"
    try:
        trusted_bytes = identity._read_regular_file_nofollow(
            trusted_manifest, "trusted source identity manifest"
        )
    except identity.ManifestError as error:
        raise AcceptanceError("trusted source identity manifest is unreadable") from error
    base = Path(codex_home) / "plugins" / "cache" / marketplace / plugin
    try:
        children = sorted(base.iterdir(), key=lambda path: path.name)
    except OSError as error:
        raise AcceptanceError("cache root is unavailable") from error

    verified: list[Path] = []
    for candidate in children:
        try:
            info = candidate.lstat()
        except OSError as error:
            raise AcceptanceError("cache contains an unreadable plugin copy") from error
        if not stat.S_ISDIR(info.st_mode) or candidate.is_symlink():
            raise AcceptanceError("cache contains an unsafe plugin copy")
        candidate_name_version = _manifest_name_version(
            candidate / ".codex-plugin" / "plugin.json"
        )
        if candidate_name_version is None:
            raise AcceptanceError("cache contains an unreadable plugin manifest")
        if candidate_name_version != source_name_version:
            continue
        try:
            cache_manifest = identity._read_regular_file_nofollow(
                candidate / "PLUGIN_IDENTITY.sha256", "cache identity manifest"
            )
            if cache_manifest != trusted_bytes:
                raise AcceptanceError("same-version unverified cache copy exists")
            verify_wrapper(
                candidate, trusted_manifest=trusted_manifest,
                expected_aggregate=expected_aggregate,
            )
        except (identity.ManifestError, AcceptanceError) as error:
            raise AcceptanceError("same-version unverified cache copy exists") from error
        verified.append(candidate)
    if len(verified) != 1:
        raise AcceptanceError(
            f"expected exactly one verified cache copy, found {len(verified)}"
        )
    return verified[0]


@dataclass(frozen=True)
class CodexInstallPlan:
    commands: tuple[tuple[str, ...], ...]
    environment: dict[str, str]
    forbidden_codex_homes: tuple[str, ...] = ()


@dataclass(frozen=True)
class HostDiscoveryPlan:
    command: tuple[str, ...]
    prompt: str
    nonce: str
    emitted_at_unix: str
    codex_home: Path
    runtime_root: Path


@dataclass(frozen=True)
class HostBinaryIdentity:
    invocation_path: str
    resolved_path: str
    sha256: str
    size: int
    version: str
    file_signature: tuple[int, int, int, int, int, int]
    target_parent_signature: tuple[int, int, int, int, int, int]
    invocation_parent_signature: tuple[int, int, int, int, int, int]


def _host_stat_signature(
    info: os.stat_result,
) -> tuple[int, int, int, int, int, int]:
    return (
        info.st_dev,
        info.st_ino,
        info.st_mode,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )


def _read_host_binary_file(binary: Path | str) -> HostBinaryIdentity:
    invocation = Path(binary)
    if not invocation.is_absolute() or len(os.fsencode(invocation)) > HOST_BINARY_PATH_LIMIT:
        raise AcceptanceError("host binary path is not a bounded absolute path")
    parent_fd = -1
    binary_fd = -1
    current_fd = -1
    try:
        invocation_parent = invocation.parent.resolve(strict=True)
        invocation_parent_before = os.stat(
            invocation_parent, follow_symlinks=False
        )
        resolved = invocation.resolve(strict=True)
        if (
            not resolved.is_absolute()
            or len(os.fsencode(resolved)) > HOST_BINARY_PATH_LIMIT
        ):
            raise AcceptanceError("host binary canonical path exceeds limit")
        parent_fd = os.open(
            resolved.parent,
            os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW | os.O_DIRECTORY,
        )
        target_parent_before = os.fstat(parent_fd)
        binary_fd = os.open(
            resolved.name,
            os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW,
            dir_fd=parent_fd,
        )
        before = os.fstat(binary_fd)
        if (
            not stat.S_ISREG(before.st_mode)
            or not before.st_mode & 0o111
            or before.st_size > HOST_BINARY_BYTE_LIMIT
        ):
            raise AcceptanceError("host binary is not a bounded executable file")
        digest = hashlib.sha256()
        count = 0
        while True:
            chunk = os.read(
                binary_fd,
                min(64 * 1024, HOST_BINARY_BYTE_LIMIT - count + 1),
            )
            if not chunk:
                break
            count += len(chunk)
            if count > HOST_BINARY_BYTE_LIMIT:
                raise AcceptanceError("host binary exceeds byte limit")
            digest.update(chunk)
        after = os.fstat(binary_fd)
        current_fd = os.open(
            resolved.name,
            os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW,
            dir_fd=parent_fd,
        )
        current = os.fstat(current_fd)
        target_parent_after = os.fstat(parent_fd)
        target_parent_path = os.stat(resolved.parent, follow_symlinks=False)
        invocation_parent_after = os.stat(
            invocation_parent, follow_symlinks=False
        )
        if (
            count != after.st_size
            or _host_stat_signature(before) != _host_stat_signature(after)
            or _host_stat_signature(after) != _host_stat_signature(current)
            or _host_stat_signature(target_parent_before)
            != _host_stat_signature(target_parent_after)
            or _host_stat_signature(target_parent_after)
            != _host_stat_signature(target_parent_path)
            or _host_stat_signature(invocation_parent_before)
            != _host_stat_signature(invocation_parent_after)
            or invocation.resolve(strict=True) != resolved
        ):
            raise AcceptanceError("host binary identity changed during inspection")
        return HostBinaryIdentity(
            invocation_path=os.fspath(invocation),
            resolved_path=os.fspath(resolved),
            sha256=digest.hexdigest(),
            size=count,
            version="",
            file_signature=_host_stat_signature(after),
            target_parent_signature=_host_stat_signature(target_parent_after),
            invocation_parent_signature=_host_stat_signature(invocation_parent_after),
        )
    except AcceptanceError:
        raise
    except OSError as error:
        raise AcceptanceError("host binary cannot be inspected safely") from error
    finally:
        for fd in (current_fd, binary_fd, parent_fd):
            if fd >= 0:
                try:
                    os.close(fd)
                except OSError:
                    pass


def inspect_host_binary(
    binary: Path | str,
    *,
    runner: Callable[..., subprocess.CompletedProcess[bytes]],
    environment: Mapping[str, str],
) -> HostBinaryIdentity:
    before = _read_host_binary_file(binary)
    command = (before.resolved_path, "--version")
    completed = runner(
        command,
        cwd=REPOSITORY_ROOT,
        environment=dict(environment),
        timeout=HOST_BINARY_VERSION_TIMEOUT,
        output_limit=HOST_BINARY_VERSION_LIMIT,
        stderr_limit=HOST_BINARY_VERSION_LIMIT,
    )
    if (
        completed.returncode != 0
        or not isinstance(completed.stdout, bytes)
        or not isinstance(completed.stderr, bytes)
        or completed.stderr
        or len(completed.stdout) > HOST_BINARY_VERSION_LIMIT
    ):
        raise AcceptanceError("host binary version query refused")
    try:
        version = completed.stdout.decode("utf-8")
    except UnicodeDecodeError as error:
        raise AcceptanceError("host binary version is not UTF-8") from error
    if (
        not version.endswith("\n")
        or version.count("\n") != 1
        or re.fullmatch(
            r"codex-cli [0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?\n",
            version,
            re.ASCII,
        )
        is None
    ):
        raise AcceptanceError("host binary version has an unsupported shape")
    after = _read_host_binary_file(binary)
    if before != after:
        raise AcceptanceError("host binary identity changed during version query")
    return HostBinaryIdentity(
        invocation_path=before.invocation_path,
        resolved_path=before.resolved_path,
        sha256=before.sha256,
        size=before.size,
        version=version[:-1],
        file_signature=before.file_signature,
        target_parent_signature=before.target_parent_signature,
        invocation_parent_signature=before.invocation_parent_signature,
    )


def build_codex_install_plan(
    *, codex_home: Path | str, repository_root: Path | str,
    codex_binary: Path | str,
) -> CodexInstallPlan:
    try:
        isolated = Path(codex_home).resolve(strict=False)
        forbidden = _forbidden_codex_homes()
    except OSError as error:
        raise AcceptanceError("CODEX_HOME cannot be canonicalized safely") from error
    if any(
        isolated == actual
        or isolated.is_relative_to(actual)
        or actual.is_relative_to(isolated)
        for actual in forbidden
    ):
        raise AcceptanceError("refusing to target the actual CODEX_HOME")
    try:
        repository = Path(repository_root).resolve(strict=True)
    except OSError as error:
        raise AcceptanceError("repository root is not a directory") from error
    if not repository.is_dir() or repository.is_symlink():
        raise AcceptanceError("repository root is not a directory")
    binary = str(codex_binary)
    commands = (
        (binary, "plugin", "marketplace", "add", str(repository), "--json"),
        (binary, "plugin", "add", f"{PLUGIN}@{MARKETPLACE}", "--json"),
        (binary, "plugin", "list", "--available", "--json"),
    )
    environment = dict(os.environ)
    environment["CODEX_HOME"] = str(isolated)
    return CodexInstallPlan(
        commands=commands,
        environment=environment,
        forbidden_codex_homes=tuple(os.fspath(path) for path in forbidden),
    )


def _forbidden_codex_homes() -> tuple[Path, ...]:
    try:
        account_home_value = pwd.getpwuid(os.getuid()).pw_dir
        process_home = Path.home()
    except (KeyError, OSError, RuntimeError) as error:
        raise AcceptanceError("Codex home authority cannot be observed safely") from error
    if (
        not isinstance(account_home_value, str)
        or not account_home_value
        or "\x00" in account_home_value
    ):
        raise AcceptanceError("Codex account home authority is invalid")
    candidates = (Path(account_home_value) / ".codex", process_home / ".codex")
    result: list[Path] = []
    try:
        for candidate in candidates:
            if not candidate.is_absolute():
                raise AcceptanceError("Codex home authority is not absolute")
            canonical = candidate.resolve(strict=False)
            if canonical not in result:
                result.append(canonical)
    except OSError as error:
        raise AcceptanceError("Codex home authority cannot be canonicalized") from error
    return tuple(result)


def _validate_isolated_codex_home(
    selected_value: object,
    forbidden: Sequence[Path],
) -> tuple[Path, tuple[int, int, int]]:
    if (
        not isinstance(selected_value, str)
        or not selected_value
        or "\x00" in selected_value
    ):
        raise AcceptanceError("isolated CODEX_HOME is not a canonical directory")
    selected = Path(selected_value)
    try:
        selected_info = selected.lstat()
        selected_resolved = selected.resolve(strict=True)
    except OSError as error:
        raise AcceptanceError("isolated CODEX_HOME is not a canonical directory") from error
    if (
        not selected.is_absolute()
        or stat.S_ISLNK(selected_info.st_mode)
        or not stat.S_ISDIR(selected_info.st_mode)
        or selected_resolved != selected
    ):
        raise AcceptanceError("isolated CODEX_HOME is not a canonical directory")
    for actual in forbidden:
        if (
            selected_resolved == actual
            or selected_resolved.is_relative_to(actual)
            or actual.is_relative_to(selected_resolved)
        ):
            raise AcceptanceError("refusing to target the actual CODEX_HOME")
        if actual.exists():
            try:
                if os.path.samefile(selected_resolved, actual):
                    raise AcceptanceError("refusing to target the actual CODEX_HOME")
            except OSError as error:
                raise AcceptanceError(
                    "CODEX_HOME identity cannot be checked safely"
                ) from error
    return selected_resolved, (
        selected_info.st_dev,
        selected_info.st_ino,
        stat.S_IFMT(selected_info.st_mode),
    )


def execute_codex_install(
    plan: CodexInstallPlan,
    *, runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> tuple[dict[str, Any], ...]:
    selected_value = plan.environment.get("CODEX_HOME")
    try:
        carried = tuple(Path(value) for value in plan.forbidden_codex_homes)
        observed = _forbidden_codex_homes()
    except (OSError, TypeError, ValueError) as error:
        raise AcceptanceError("Codex home authority cannot be checked safely") from error
    forbidden = tuple(dict.fromkeys((*carried, *observed)))
    selected_resolved, selected_identity = _validate_isolated_codex_home(
        selected_value, forbidden
    )
    if not carried or carried != observed:
        raise AcceptanceError("Codex home authority changed after install planning")

    def revalidate() -> None:
        current_observed = _forbidden_codex_homes()
        current_path, current_identity = _validate_isolated_codex_home(
            plan.environment.get("CODEX_HOME"),
            tuple(dict.fromkeys((*carried, *current_observed))),
        )
        if (
            current_observed != carried
            or current_path != selected_resolved
            or current_identity != selected_identity
        ):
            raise AcceptanceError("isolated CODEX_HOME identity changed during install")

    results: list[dict[str, Any]] = []
    for command in plan.commands:
        revalidate()
        completed = runner(
            list(command), capture_output=True, text=True, check=False,
            timeout=120, env=plan.environment,
        )
        if completed.returncode != 0:
            raise AcceptanceError("isolated Codex plugin command refused")
        try:
            parsed = strict_json_loads(completed.stdout)
        except (ValueError, json.JSONDecodeError) as error:
            raise AcceptanceError("Codex plugin command returned invalid JSON") from error
        if not isinstance(parsed, dict):
            raise AcceptanceError("Codex plugin command returned a non-object")
        results.append(parsed)
    revalidate()
    installed = results[-1].get("installed") if results else None
    matches = [
        record for record in installed
        if isinstance(record, dict)
        and record.get("pluginId") == f"{PLUGIN}@{MARKETPLACE}"
        and record.get("installed") is True
        and record.get("enabled") is True
    ] if isinstance(installed, list) else []
    if len(matches) != 1:
        raise AcceptanceError("Codex list did not confirm one enabled installed plugin")
    return tuple(results)


def host_claim_request(plan: HostDiscoveryPlan) -> dict[str, Any]:
    return {
        "schema": "jackal-claim-request-v1",
        "emitted_at_unix": plan.emitted_at_unix,
        "nonce": plan.nonce,
        "steps": [
            {
                "id": "p",
                "op": "exact",
                "command": "mod-pow",
                "args": ["3", "100", "7"],
            }
        ],
        "root": "p",
    }


def host_verification_arguments(
    bundle: dict[str, Any], plan: HostDiscoveryPlan,
) -> dict[str, Any]:
    return {
        "bundle": bundle,
        "expected_release_epoch": CLAIM_RELEASE_EPOCH,
        "expected_policy_sha256": DEFAULT_POLICY_SHA256,
        "expected_root_proposition": copy.deepcopy(EXPECTED_ROOT_PROPOSITION),
        "verification_time_unix": plan.emitted_at_unix,
        "expected_nonce": plan.nonce,
    }


def build_host_discovery_plan(
    *,
    codex_binary: Path | str,
    codex_home: Path | str,
    runtime_root: Path | str,
    nonce: str,
    emitted_at_unix: str,
) -> HostDiscoveryPlan:
    binary = Path(codex_binary)
    home = Path(codex_home)
    runtime = Path(runtime_root)
    if not binary.is_absolute() or not home.is_absolute() or not runtime.is_absolute():
        raise AcceptanceError("host discovery paths must be absolute")
    if (
        not isinstance(nonce, str)
        or len(nonce.encode("utf-8")) < 16
        or len(nonce.encode("utf-8")) > 128
        or not isinstance(emitted_at_unix, str)
        or not emitted_at_unix.isdigit()
    ):
        raise AcceptanceError("host discovery freshness inputs are invalid")
    root_json = canonical_bytes(EXPECTED_ROOT_PROPOSITION).decode("utf-8")
    prompt = (
        "Use only an installed claim-aware mathematical capability available to this "
        "fresh task. Obtain a structured claim evidence bundle for 3^100 mod 7, "
        f"binding nonce {nonce} and emitted_at_unix {emitted_at_unix}. Then "
        "independently replay that returned bundle against release epoch "
        f"{CLAIM_RELEASE_EPOCH}, policy SHA-256 {DEFAULT_POLICY_SHA256}, expected "
        f"root proposition {root_json}, verification time {emitted_at_unix}, and "
        f"expected nonce {nonce}. Do not execute shell commands, read or write files, "
        "browse the web, or use any unrelated capability. Return a concise summary "
        "only after both structured operations complete."
    )
    command = (
        os.fspath(binary),
        "--ask-for-approval",
        "never",
        "exec",
        "--ephemeral",
        "--json",
        "--color",
        "never",
        "--sandbox",
        "read-only",
        "-C",
        os.fspath(REPOSITORY_ROOT),
        prompt,
    )
    return HostDiscoveryPlan(
        command=command,
        prompt=prompt,
        nonce=nonce,
        emitted_at_unix=emitted_at_unix,
        codex_home=home,
        runtime_root=runtime,
    )


def _event_depth(value: Any) -> int:
    maximum = 0
    stack = [(value, 1)]
    while stack:
        current, depth = stack.pop()
        maximum = max(maximum, depth)
        if maximum > HOST_EVENT_DEPTH_LIMIT:
            raise AcceptanceError("host event exceeds nesting limit")
        if isinstance(current, dict):
            stack.extend((item, depth + 1) for item in current.values())
        elif isinstance(current, list):
            stack.extend((item, depth + 1) for item in current)
    return maximum


def _host_events(raw: bytes) -> tuple[dict[str, Any], ...]:
    if not isinstance(raw, bytes) or not raw or len(raw) > HOST_TRANSCRIPT_LIMIT:
        raise AcceptanceError("host transcript is empty or exceeds byte limit")
    if not raw.endswith(b"\n"):
        raise AcceptanceError("host transcript is not newline terminated")
    lines = raw[:-1].split(b"\n")
    if len(lines) > HOST_EVENT_LIMIT or any(not line for line in lines):
        raise AcceptanceError("host transcript exceeds event limit or has empty events")
    events: list[dict[str, Any]] = []
    for line in lines:
        try:
            event = strict_json_loads(line)
        except (ValueError, json.JSONDecodeError, RecursionError) as error:
            raise AcceptanceError("host transcript contains invalid JSON") from error
        if not isinstance(event, dict):
            raise AcceptanceError("host transcript event is not an object")
        _event_depth(event)
        events.append(event)
    return tuple(events)


def _structured_host_result(item: dict[str, Any]) -> dict[str, Any]:
    result = item.get("result")
    if (
        not isinstance(result, dict)
        or not {"content", "structured_content"}.issubset(result)
        or not set(result).issubset({"content", "structured_content", "_meta"})
        or ("_meta" in result and result["_meta"] is not None
            and not isinstance(result["_meta"], dict))
    ):
        raise AcceptanceError("host MCP completion result shape is invalid")
    structured = result["structured_content"]
    content = result["content"]
    if not isinstance(structured, dict):
        raise AcceptanceError("host MCP completion omitted structured content")
    if (
        not isinstance(content, list)
        or len(content) != 1
        or not isinstance(content[0], dict)
        or set(content[0]) != {"type", "text"}
        or content[0].get("type") != "text"
        or not isinstance(content[0].get("text"), str)
    ):
        raise AcceptanceError("host MCP completion content shape is invalid")
    try:
        text_value = strict_json_loads(content[0]["text"])
    except (ValueError, json.JSONDecodeError, RecursionError) as error:
        raise AcceptanceError("host MCP completion content is not strict JSON") from error
    _event_depth(text_value)
    if text_value != structured:
        raise AcceptanceError("host MCP completion content diverges from structured content")
    return structured


def validate_host_discovery_events(
    raw: bytes, plan: HostDiscoveryPlan,
) -> dict[str, Any]:
    events = _host_events(raw)
    allowed_event_types = {
        "thread.started",
        "turn.started",
        "turn.completed",
        "turn.failed",
        "item.started",
        "item.updated",
        "item.completed",
        "error",
    }
    if any(event.get("type") not in allowed_event_types for event in events):
        raise AcceptanceError("host transcript contains an unsupported event type")
    canonical_event_keys = {
        "thread.started": {"type", "thread_id"},
        "turn.started": {"type"},
        "turn.completed": {"type", "usage"},
        "item.started": {"type", "item"},
        "item.updated": {"type", "item"},
        "item.completed": {"type", "item"},
    }
    if any(
        event.get("type") in canonical_event_keys
        and set(event) != canonical_event_keys[event["type"]]
        for event in events
    ):
        raise AcceptanceError("host transcript event schema is invalid")
    if any(
        event.get("type") == "error"
        or str(event.get("type", "")).endswith(".failed")
        or ("error" in event and event.get("error") is not None)
        for event in events
    ):
        raise AcceptanceError("host transcript contains a failed lifecycle event")
    thread_ids = [event.get("thread_id") for event in events if event.get("type") == "thread.started"]
    if len(thread_ids) != 1 or not isinstance(thread_ids[0], str) or not thread_ids[0]:
        raise AcceptanceError("host transcript lacks one fresh thread lifecycle")
    thread_positions = [
        index for index, event in enumerate(events)
        if event.get("type") == "thread.started"
    ]
    turn_start_positions = [
        index for index, event in enumerate(events)
        if event.get("type") == "turn.started"
    ]
    turn_complete_positions = [
        index for index, event in enumerate(events)
        if event.get("type") == "turn.completed"
    ]
    if (
        thread_positions[0] != 0
        or len(turn_start_positions) != 1
        or len(turn_complete_positions) != 1
    ):
        raise AcceptanceError("host transcript lacks the exact outer lifecycle")
    usage = events[turn_complete_positions[0]].get("usage")
    required_usage_keys = {
        "input_tokens", "cached_input_tokens", "output_tokens"
    }
    allowed_usage_keys = required_usage_keys | {
        "cache_write_input_tokens", "reasoning_output_tokens"
    }
    if (
        not isinstance(usage, dict)
        or not required_usage_keys.issubset(usage)
        or not set(usage).issubset(allowed_usage_keys)
        or any(
            isinstance(value, bool) or not isinstance(value, int) or value < 0
            for value in usage.values()
        )
    ):
        raise AcceptanceError("host transcript turn usage is invalid")

    passive_item_types = {"agent_message", "reasoning"}
    lifecycle: list[tuple[str, str]] = []
    lifecycle_positions: list[int] = []
    started: list[dict[str, Any]] = []
    started_positions: list[int] = []
    completed: list[dict[str, Any]] = []
    completed_positions: list[int] = []
    updated: list[tuple[int, dict[str, Any]]] = []
    passive_events: list[tuple[int, str, dict[str, Any]]] = []
    for event_index, event in enumerate(events):
        if event.get("type") not in {
            "item.started", "item.updated", "item.completed"
        }:
            continue
        item = event.get("item")
        if not isinstance(item, dict):
            raise AcceptanceError("host item lifecycle is malformed")
        if not (
            turn_start_positions[0] < event_index < turn_complete_positions[0]
        ):
            raise AcceptanceError("host item lifecycle is outside the turn")
        item_type = item.get("type")
        if item_type in passive_item_types:
            if (
                set(item) != {"id", "type", "text"}
                or not isinstance(item.get("id"), str)
                or not item["id"]
                or not isinstance(item.get("text"), str)
            ):
                raise AcceptanceError("host passive item schema is invalid")
            passive_events.append((event_index, event["type"], item))
            continue
        if item_type != "mcp_tool_call":
            raise AcceptanceError("host task used a forbidden external capability")
        if (
            set(item) != {
                "id", "type", "server", "tool", "arguments", "result",
                "error", "status",
            }
        ):
            raise AcceptanceError("host MCP item schema is invalid")
        if item.get("server") != PLUGIN or item.get("tool") not in {
            "jackal_claim", "jackal_verify_bundle",
        }:
            raise AcceptanceError("host task routed through an unexpected MCP capability")
        if event["type"] in {"item.started", "item.updated"} and (
            not {"status", "result", "error"}.issubset(item)
            or item.get("status") != "in_progress"
            or item.get("result") is not None
            or item.get("error") is not None
        ):
            raise AcceptanceError("host MCP item state is invalid")
        if event["type"] == "item.completed" and (
            not {"status", "result", "error"}.issubset(item)
            or item.get("status") != "completed"
            or item.get("result") is None
            or item.get("error") is not None
        ):
            raise AcceptanceError("host MCP item state is invalid")
        if event["type"] == "item.updated":
            updated.append((event_index, item))
            continue
        lifecycle.append((event["type"], item["tool"]))
        lifecycle_positions.append(event_index)
        if event["type"] == "item.started":
            started.append(item)
            started_positions.append(event_index)
        else:
            completed.append(item)
            completed_positions.append(event_index)
    expected_lifecycle = [
        ("item.started", "jackal_claim"),
        ("item.completed", "jackal_claim"),
        ("item.started", "jackal_verify_bundle"),
        ("item.completed", "jackal_verify_bundle"),
    ]
    if lifecycle != expected_lifecycle:
        raise AcceptanceError("host transcript has invalid MCP lifecycle order")
    passive_by_id: dict[str, list[tuple[int, str, dict[str, Any]]]] = {}
    for passive_event in passive_events:
        passive_by_id.setdefault(passive_event[2]["id"], []).append(passive_event)
    for item_id, item_events in passive_by_id.items():
        event_types = [event_type for unused_index, event_type, unused_item in item_events]
        item_types = {item.get("type") for unused_index, unused_type, item in item_events}
        terminal_only = event_types == ["item.completed"]
        correlated = (
            len(event_types) >= 2
            and event_types[0] == "item.started"
            and event_types[-1] == "item.completed"
            and all(event_type == "item.updated" for event_type in event_types[1:-1])
        )
        if len(item_types) != 1 or not (terminal_only or correlated):
            raise AcceptanceError(
                f"host passive item lifecycle is incomplete: {item_id}"
            )
    globally_ordered = [
        thread_positions[0],
        turn_start_positions[0],
        *lifecycle_positions,
        turn_complete_positions[0],
    ]
    if globally_ordered != sorted(globally_ordered) or len(set(globally_ordered)) != len(
        globally_ordered
    ):
        raise AcceptanceError("host transcript has invalid outer lifecycle order")
    expected_tools = ["jackal_claim", "jackal_verify_bundle"]
    if [item.get("tool") for item in started] != expected_tools or [
        item.get("tool") for item in completed
    ] != expected_tools:
        raise AcceptanceError("host transcript lacks the exact MCP lifecycle")
    if [item.get("id") for item in started] != [item.get("id") for item in completed]:
        raise AcceptanceError("host MCP lifecycle identifiers do not correlate")
    tool_call_ids = [item.get("id") for item in completed]
    if (
        any(not isinstance(item_id, str) or not item_id for item_id in tool_call_ids)
        or len(set(tool_call_ids)) != len(tool_call_ids)
    ):
        raise AcceptanceError("host MCP lifecycle identifiers are invalid")
    if set(tool_call_ids) & set(passive_by_id):
        raise AcceptanceError("host item lifecycle identifiers are ambiguous")
    started_by_id = {item["id"]: item for item in started}
    positions_by_id = {
        started[index]["id"]: (started_positions[index], completed_positions[index])
        for index in range(len(started))
    }
    if any(
        not isinstance(item.get("id"), str)
        or item.get("id") not in started_by_id
        or item.get("tool") != started_by_id[item["id"]].get("tool")
        or item.get("arguments") != started_by_id[item["id"]].get("arguments")
        or not (
            positions_by_id[item["id"]][0]
            < event_index
            < positions_by_id[item["id"]][1]
        )
        for event_index, item in updated
    ):
        raise AcceptanceError("host transcript contains an unexpected MCP update order")

    claim_arguments = completed[0].get("arguments")
    expected_claim = {"request": host_claim_request(plan)}
    if claim_arguments != expected_claim or started[0].get("arguments") != expected_claim:
        raise AcceptanceError("host claim request is not freshness-bound")
    claim_result = _structured_host_result(completed[0])
    bundle = claim_result.get("bundle")
    expected_claim_keys = {
        "status", "root", "bundle_digest_sha256", "rendering",
        "route_trace", "bundle",
    }
    expected_bundle_keys = {
        "schema", "release_epoch", "engine_identity", "registries", "policy",
        "nodes", "root", "rendering", "bundle_digest_sha256",
    }
    bundle_digest = bundle.get("bundle_digest_sha256") if isinstance(bundle, dict) else None
    bundle_body = {
        key: value for key, value in bundle.items()
        if key != "bundle_digest_sha256"
    } if isinstance(bundle, dict) else None
    rendering = claim_result.get("rendering")
    if (
        set(claim_result) != expected_claim_keys
        or claim_result.get("status") != "ok"
        or not isinstance(bundle, dict)
        or set(bundle) != expected_bundle_keys
        or bundle.get("schema") != "jackal-claim-bundle-v1"
        or bundle.get("release_epoch") != CLAIM_RELEASE_EPOCH
        or claim_result.get("root") != bundle.get("root")
        or not isinstance(rendering, dict)
        or set(rendering) != {"token", "permitted_text"}
        or not all(isinstance(value, str) for value in rendering.values())
        or rendering != bundle.get("rendering")
        or not isinstance(bundle_digest, str)
        or claim_result.get("bundle_digest_sha256") != bundle_digest
        or bundle_digest != canonical_sha256(bundle_body)
    ):
        raise AcceptanceError("host claim did not return a bound bundle")
    _validate_claim(claim_result)
    expected_verification = host_verification_arguments(bundle, plan)
    if completed[1].get("arguments") != expected_verification or started[1].get("arguments") != expected_verification:
        raise AcceptanceError("host verifier did not receive independent caller pins")
    verification = _structured_host_result(completed[1])
    report_lines = verification.get("report")
    if (
        set(verification) != {"status", "verdict", "report"}
        or verification.get("status") != "verified"
        or verification.get("verdict") != "verified"
        or not isinstance(report_lines, list)
        or not all(isinstance(line, str) for line in report_lines)
        or "claim-verify=verified" not in report_lines
        or f"bundle.digest={bundle_digest}" not in report_lines
        or f"root.proposition_sha256={EXPECTED_ROOT_PROPOSITION_SHA256}" not in report_lines
        or not any(
            line.startswith(f"freshness: epoch={CLAIM_RELEASE_EPOCH} ")
            and " nonce=bound" in line
            for line in report_lines
        )
    ):
        raise AcceptanceError("host verifier did not confirm the fixed claim")
    return {
        "thread_id": thread_ids[0],
        "nonce": plan.nonce,
        "transcript_sha256": hashlib.sha256(raw).hexdigest(),
        "claim_bundle_digest_sha256": claim_result["bundle_digest_sha256"],
        "tool_call_ids": tool_call_ids,
    }


def _host_environment(plan: HostDiscoveryPlan) -> dict[str, str]:
    source = os.environ
    binary_directory = str(Path(plan.command[0]).parent)
    result = {
        "CODEX_HOME": os.fspath(plan.codex_home),
        "JACKAL_HOME": os.fspath(plan.runtime_root),
        "PATH": f"{binary_directory}:/usr/bin:/bin:/usr/sbin:/sbin",
    }
    for name in ("HOME", "USER", "LOGNAME", "TMPDIR", "LANG", "LC_ALL", "SSL_CERT_FILE"):
        value = source.get(name)
        if isinstance(value, str) and "\x00" not in value:
            result[name] = value
    return result


def validate_host_mcp_registry(
    raw: bytes, installed_root: Path | str,
) -> Path:
    if not isinstance(raw, bytes) or not raw or len(raw) > HOST_REGISTRY_LIMIT:
        raise AcceptanceError("host MCP registry is empty or exceeds byte limit")
    try:
        document = strict_json_loads(raw)
    except (ValueError, json.JSONDecodeError, RecursionError) as error:
        raise AcceptanceError("host MCP registry is invalid JSON") from error
    _event_depth(document)
    if (
        not isinstance(document, list)
        or len(document) > HOST_REGISTRY_ENTRY_LIMIT
        or any(not isinstance(entry, dict) for entry in document)
    ):
        raise AcceptanceError("host MCP registry has an unsupported shape")
    matches = [entry for entry in document if entry.get("name") == PLUGIN]
    if len(matches) != 1:
        raise AcceptanceError("host MCP registry must contain exactly one jackel server")
    installed, declaration = load_installed_mcp_declaration(installed_root)
    entry = matches[0]
    transport = entry.get("transport")
    if (
        entry.get("enabled") is not True
        or entry.get("disabled_reason") is not None
        or not isinstance(transport, dict)
        or transport.get("type") != "stdio"
        or transport.get("command") != declaration["command"]
        or transport.get("args") != declaration["args"]
        or transport.get("env") is not None
        or transport.get("env_vars") != declaration["env_vars"]
        or entry.get("tool_timeout_sec") != declaration["tool_timeout_sec"]
    ):
        raise AcceptanceError("host MCP registry declaration differs from installed config")
    cwd = transport.get("cwd")
    if not isinstance(cwd, str) or not Path(cwd).is_absolute():
        raise AcceptanceError("host MCP registry cwd is not absolute")
    try:
        active_root = Path(cwd).resolve(strict=True)
    except OSError as error:
        raise AcceptanceError("host MCP registry cwd is unavailable") from error
    if active_root != installed:
        raise AcceptanceError("host MCP registry is not bound to the verified cache")
    return active_root


def _read_host_mcp_registry(
    plan: HostDiscoveryPlan,
    installed_root: Path,
    runner: Callable[..., subprocess.CompletedProcess[bytes]],
) -> Path:
    command = (plan.command[0], "mcp", "list", "--json")
    completed = runner(
        command,
        cwd=REPOSITORY_ROOT,
        environment=_host_environment(plan),
        timeout=HOST_REGISTRY_TIMEOUT,
        output_limit=HOST_REGISTRY_LIMIT,
        stderr_limit=HOST_STDERR_LIMIT,
    )
    if completed.returncode != 0 or not isinstance(completed.stdout, bytes):
        raise AcceptanceError("host MCP registry query refused")
    return validate_host_mcp_registry(completed.stdout, installed_root)


def _terminate_host_process(process: subprocess.Popen[bytes]) -> int:
    try:
        provisioner._cleanup_completed_process_group(
            process.pid,
            provisioner._cleanup_process_group,
            os.killpg,
        )
    except provisioner.ProvisionError as error:
        raise AcceptanceError("host task process-group cleanup failed") from error
    try:
        return process.wait(timeout=0.5)
    except subprocess.TimeoutExpired as error:
        raise AcceptanceError("host task did not exit after bounded cleanup") from error


def _run_bounded_host_command(
    command: Sequence[str],
    *,
    cwd: Path,
    environment: Mapping[str, str],
    timeout: float = HOST_TASK_TIMEOUT,
    output_limit: int = HOST_TRANSCRIPT_LIMIT,
    stderr_limit: int = HOST_STDERR_LIMIT,
) -> subprocess.CompletedProcess[bytes]:
    try:
        process = subprocess.Popen(
            list(command), cwd=cwd, env=dict(environment),
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            start_new_session=True, close_fds=True,
        )
    except OSError as error:
        raise AcceptanceError("fresh Codex host task failed to start") from error
    if process.stdout is None or process.stderr is None:
        _terminate_host_process(process)
        raise AcceptanceError("fresh Codex host task pipes are unavailable")
    selector: selectors.BaseSelector | None = None
    stdout = bytearray()
    stderr = bytearray()
    deadline = time.monotonic() + timeout
    cleanup_started = False
    cleanup_allowed = True
    try:
        try:
            selector = selectors.DefaultSelector()
        except OSError as error:
            raise AcceptanceError("fresh Codex host task failed within bounds") from error
        selector.register(process.stdout, selectors.EVENT_READ, (stdout, output_limit))
        selector.register(process.stderr, selectors.EVENT_READ, (stderr, stderr_limit))
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise AcceptanceError("fresh Codex host task timed out")
            for key, unused in selector.select(min(remaining, 0.1)):
                sink, limit = key.data
                chunk = os.read(key.fd, min(64 * 1024, limit - len(sink) + 1))
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                sink.extend(chunk)
                if len(sink) > limit:
                    raise AcceptanceError("fresh Codex host task output exceeded limit")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise AcceptanceError("fresh Codex host task timed out")
        try:
            while not provisioner._leader_exited_without_reaping(
                process.pid, os.waitid
            ):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise AcceptanceError("fresh Codex host task timed out")
                time.sleep(min(0.01, remaining))
        except provisioner._LeaderAnchorLost as error:
            cleanup_allowed = False
            raise AcceptanceError("fresh Codex host leader anchor was lost") from error
        cleanup_started = True
        return_code = _terminate_host_process(process)
    except AcceptanceError:
        if not cleanup_started and cleanup_allowed:
            _terminate_host_process(process)
        raise
    except Exception as error:
        if not cleanup_started and cleanup_allowed:
            _terminate_host_process(process)
        raise AcceptanceError("fresh Codex host task failed within bounds") from error
    finally:
        if selector is not None:
            selector.close()
        process.stdout.close()
        process.stderr.close()
    return subprocess.CompletedProcess(tuple(command), return_code, bytes(stdout), bytes(stderr))


def run_host_discovery_acceptance(
    *,
    codex_binary: Path | str,
    codex_home: Path | str,
    runtime_root: Path | str,
    evidence_path: Path | str,
    runner: Callable[..., subprocess.CompletedProcess[bytes]] = _run_bounded_host_command,
    nonce_factory: Callable[[], str] = lambda: secrets.token_hex(24),
    clock: Callable[[], float] = time.time,
) -> dict[str, Any]:
    evidence = Path(evidence_path)
    if not evidence.is_absolute():
        raise AcceptanceError("host evidence path must be absolute")
    try:
        evidence_fd = os.open(
            evidence,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
        )
    except OSError as error:
        raise AcceptanceError("host evidence path is not new and writable") from error
    try:
        source_aggregate = verify_wrapper(PLUGIN_ROOT)
        verify_runtime(runtime_root)
        installed_before = locate_cache_copy(
            codex_home, PLUGIN_ROOT, expected_aggregate=source_aggregate,
        ).resolve(strict=True)
        preliminary_plan = build_host_discovery_plan(
            codex_binary=codex_binary,
            codex_home=codex_home,
            runtime_root=runtime_root,
            nonce=nonce_factory(),
            emitted_at_unix=str(int(clock())),
        )
        binary_before = inspect_host_binary(
            codex_binary,
            runner=runner,
            environment=_host_environment(preliminary_plan),
        )
        plan = build_host_discovery_plan(
            codex_binary=Path(binary_before.resolved_path),
            codex_home=codex_home,
            runtime_root=runtime_root,
            nonce=preliminary_plan.nonce,
            emitted_at_unix=preliminary_plan.emitted_at_unix,
        )
        active_before = _read_host_mcp_registry(plan, installed_before, runner)
        completed = runner(
            plan.command,
            cwd=REPOSITORY_ROOT,
            environment=_host_environment(plan),
            timeout=HOST_TASK_TIMEOUT,
            output_limit=HOST_TRANSCRIPT_LIMIT,
            stderr_limit=HOST_STDERR_LIMIT,
        )
        raw = completed.stdout
        if not isinstance(raw, bytes) or len(raw) > HOST_TRANSCRIPT_LIMIT:
            raise AcceptanceError("fresh Codex host task returned invalid output")
        view = memoryview(raw)
        while view:
            written = os.write(evidence_fd, view)
            if written <= 0:
                raise AcceptanceError("host evidence write made no progress")
            view = view[written:]
        os.fsync(evidence_fd)
        if completed.returncode != 0:
            raise AcceptanceError("fresh Codex host task refused")
        report = validate_host_discovery_events(raw, plan)
        source_after = verify_wrapper(PLUGIN_ROOT)
        installed_after = locate_cache_copy(
            codex_home, PLUGIN_ROOT, expected_aggregate=source_aggregate,
        ).resolve(strict=True)
        verify_runtime(runtime_root)
        active_after = _read_host_mcp_registry(plan, installed_after, runner)
        binary_after = inspect_host_binary(
            codex_binary,
            runner=runner,
            environment=_host_environment(plan),
        )
        if (
            source_after != source_aggregate
            or installed_after != installed_before
            or active_after != active_before
        ):
            raise AcceptanceError("host acceptance identities changed during the task")
        if binary_after != binary_before:
            raise AcceptanceError("host binary identity changed during the task")
        return {
            "status": "accepted",
            "acceptance_kind": "fresh-codex-host-discovery",
            "wrapper_aggregate_sha256": source_aggregate,
            "runtime_package_sha256": provisioner.PACKAGE_SHA256,
            "runtime_tree_sha256": provisioner.SHA256SUMS_SHA256,
            "evidence_path": os.fspath(evidence),
            "active_mcp_cwd": os.fspath(active_before),
            "codex_binary_invocation_path": binary_before.invocation_path,
            "codex_binary_resolved_path": binary_before.resolved_path,
            "codex_binary_sha256": binary_before.sha256,
            "codex_binary_size": binary_before.size,
            "codex_binary_version": binary_before.version,
            "codex_binary_trust": "caller-supplied-external-anchor",
            **report,
        }
    finally:
        os.close(evidence_fd)


def tool_payload(response: object) -> dict[str, Any]:
    if not isinstance(response, dict) or response.get("jsonrpc") != "2.0" \
            or "error" in response:
        raise AcceptanceError("MCP call did not return a successful JSON-RPC response")
    result = response.get("result")
    if not isinstance(result, dict) or set(result) != {"content", "structuredContent"}:
        raise AcceptanceError("MCP tool result has an unsupported wrapper shape")
    if "isError" in result:
        raise AcceptanceError("JACKAL epistemic result was promoted to a transport error")
    structured = result["structuredContent"]
    content = result["content"]
    if not isinstance(structured, dict) or not isinstance(content, list) \
            or len(content) != 1 or content[0].get("type") != "text" \
            or not isinstance(content[0].get("text"), str):
        raise AcceptanceError("MCP tool result content shape is invalid")
    try:
        text_value = strict_json_loads(content[0]["text"])
    except (ValueError, json.JSONDecodeError) as error:
        raise AcceptanceError("MCP text fallback is not strict JSON") from error
    if text_value != structured:
        raise AcceptanceError("MCP text and structured outputs diverge")
    return structured


def validate_exact(mcp_response: object, direct: object) -> dict[str, Any]:
    value = tool_payload(mcp_response)
    if value != direct:
        raise AcceptanceError("exact result failed direct backend parity")
    if value.get("status") != "exact" or value.get("lane") != "rat" \
            or value.get("formal") is not False \
            or not isinstance(value.get("fields"), dict) \
            or value["fields"].get("exact") != "3/10":
        raise AcceptanceError("exact result did not satisfy its fixed oracle")
    return value


def _verify_formal_receipt(receipt: object) -> dict[str, Any]:
    if not isinstance(receipt, dict):
        raise AcceptanceError("formal result omitted its receipt")
    expected_request = {
        "command": "integrate-bound-cert", "expression": "sin(x)",
        "input_lo": "0", "input_hi": "1", "tolerance": "1/100",
    }
    if receipt.get("schema") != "jackal-formal-receipt-v1" \
            or receipt.get("variant") != "int_cert" \
            or receipt.get("release_epoch") != FORMAL_RELEASE_EPOCH \
            or receipt.get("theorem", {}).get("id") != "int_cert_sound" \
            or receipt.get("checker", {}).get("verdict") != "ACCEPT" \
            or receipt.get("result", {}).get("status") != "formal-bounded":
        raise AcceptanceError("formal receipt shape or theorem binding is invalid")
    request = receipt.get("request")
    if not isinstance(request, dict) or any(
        request.get(key) != value for key, value in expected_request.items()
    ):
        raise AcceptanceError("formal receipt request binding is invalid")
    identities = receipt.get("identities")
    if not isinstance(identities, dict) or {
        "evaluator_sha256": identities.get("evaluator_sha256"),
        "producer_sha256": identities.get("producer_sha256"),
        "checker_sha256": identities.get("checker_sha256"),
        "plugin_sha256": identities.get("plugin_sha256"),
    } != {
        "evaluator_sha256": INT_CERT_PRODUCER_SHA256,
        "producer_sha256": INT_CERT_PRODUCER_SHA256,
        "checker_sha256": INT_CERT_CHECKER_SHA256,
        "plugin_sha256": HERMES_BUNDLE_SHA256,
    }:
        raise AcceptanceError("formal receipt identity binding is invalid")
    certificate = receipt.get("certificate")
    if not isinstance(certificate, dict) \
            or certificate.get("schema") != "jackal-int-cert v1":
        raise AcceptanceError("formal receipt certificate shape is invalid")
    try:
        decoded = base64.b64decode(certificate["bytes_b64"], validate=True)
    except (KeyError, TypeError, ValueError) as error:
        raise AcceptanceError("formal certificate bytes are invalid base64") from error
    if hashlib.sha256(decoded).hexdigest() != certificate.get("sha256"):
        raise AcceptanceError("formal certificate digest mismatch")
    if receipt_digest(receipt) != receipt.get("receipt_digest_sha256"):
        raise AcceptanceError("formal outer receipt digest mismatch")
    return receipt


def _normalized_formal(value: dict[str, Any]) -> dict[str, Any]:
    normalized = copy.deepcopy(value)
    receipt = normalized["receipt"]
    receipt.pop("emitted_at_unix", None)
    receipt.pop("receipt_digest_sha256", None)
    return normalized


def validate_formal_int_cert(
    mcp_response: object, direct: object,
) -> dict[str, Any]:
    value = tool_payload(mcp_response)
    if not isinstance(direct, dict):
        raise AcceptanceError("direct formal backend result is not an object")
    for result in (value, direct):
        if result.get("status") != "formal-bounded" \
                or result.get("checker_rerun") != "ACCEPT":
            raise AcceptanceError("formal result was not checker-attested")
        _verify_formal_receipt(result.get("receipt"))
    if _normalized_formal(value) != _normalized_formal(direct):
        raise AcceptanceError("formal result failed normalized direct backend parity")
    return value


def validate_unsupported_formal(
    mcp_response: object, direct: object,
) -> dict[str, Any]:
    value = tool_payload(mcp_response)
    if value != direct:
        raise AcceptanceError("formal refusal failed direct backend parity")
    if set(value) != {"status", "reason", "detail"}:
        raise AcceptanceError("unsupported-formal refusal shape leaked a fallback")
    if value.get("status") != "refused" or value.get("reason") != "producer-refused" \
            or not isinstance(value.get("detail"), str):
        raise AcceptanceError("unsupported formal request lacked its named refusal")
    return value


def claim_verification_arguments(bundle: dict[str, Any]) -> dict[str, Any]:
    return {
        "bundle": bundle,
        "expected_release_epoch": CLAIM_RELEASE_EPOCH,
        "expected_policy_sha256": DEFAULT_POLICY_SHA256,
        "expected_root_proposition": copy.deepcopy(EXPECTED_ROOT_PROPOSITION),
        "verification_time_unix": CLAIM_TIME,
        "expected_nonce": CLAIM_NONCE,
    }


def receipt_verification_arguments(receipt: dict[str, Any]) -> dict[str, Any]:
    return {
        "receipt": receipt,
        "expected_release_epoch": FORMAL_RELEASE_EPOCH,
        "expected_command": "integrate-bound-cert",
        "expected_expression": "sin(x)",
        "expected_input_lo": "0",
        "expected_input_hi": "1",
        "expected_tolerance": "1/100",
    }


def _validate_claim(value: dict[str, Any]) -> dict[str, Any]:
    bundle = value.get("bundle")
    if value.get("status") != "ok" or not isinstance(bundle, dict) \
            or bundle.get("release_epoch") != CLAIM_RELEASE_EPOCH \
            or canonical_sha256(bundle.get("policy")) != DEFAULT_POLICY_SHA256:
        raise AcceptanceError("claim bundle did not bind the fixed epoch and policy")
    root_id = bundle.get("root")
    nodes = bundle.get("nodes")
    if not isinstance(root_id, str) or not isinstance(nodes, list):
        raise AcceptanceError("claim bundle graph is malformed")
    roots = [node for node in nodes if isinstance(node, dict) and node.get("id") == root_id]
    if len(roots) != 1 or roots[0].get("proposition") != EXPECTED_ROOT_PROPOSITION:
        raise AcceptanceError("claim root proposition differs from the caller-fixed oracle")
    digest = value.get("bundle_digest_sha256")
    if not isinstance(digest, str) or len(digest) != 64 \
            or any(character not in "0123456789abcdef" for character in digest):
        raise AcceptanceError("claim bundle digest is malformed")
    trace = value.get("route_trace")
    if not isinstance(trace, list) or not any(
        isinstance(row, dict) and row.get("selected") == "engine-exact-cert"
        for row in trace
    ):
        raise AcceptanceError("claim route did not select the exact-cert lane")
    return bundle


def _validate_bundle_verification(response: object) -> dict[str, Any]:
    value = tool_payload(response)
    report = value.get("report")
    if value.get("status") != "verified" or value.get("verdict") != "verified" \
            or not isinstance(report, list) \
            or "claim-verify=verified" not in report \
            or f"root.proposition_sha256={EXPECTED_ROOT_PROPOSITION_SHA256}" not in report \
            or not any(
                isinstance(line, str) and "freshness: epoch=v1.6.0" in line
                and "nonce=bound" in line for line in report
            ):
        raise AcceptanceError("claim bundle verifier did not attest fixed expectations")
    return value


def _validate_receipt_verification(
    response: object, receipt: dict[str, Any],
) -> dict[str, Any]:
    value = tool_payload(response)
    result = receipt["result"]
    expected = {
        "receipt_digest_sha256": receipt["receipt_digest_sha256"],
        "certificate_sha256": receipt["certificate"]["sha256"],
        "checker_sha256": INT_CERT_CHECKER_SHA256,
        "evaluator_sha256": INT_CERT_PRODUCER_SHA256,
        "plugin_sha256": HERMES_BUNDLE_SHA256,
        "enclosure": [result["enclosure_lo"], result["enclosure_hi"]],
    }
    if value.get("status") != "verified" or value.get("verdict") != "ACCEPT" \
            or any(value.get(key) != expected_value
                   for key, expected_value in expected.items()):
        raise AcceptanceError("formal receipt replay did not bind fixed expectations")
    return value


def _validate_initialize(response: object) -> None:
    if not isinstance(response, dict) or "error" in response:
        raise AcceptanceError("MCP initialize failed")
    result = response.get("result")
    if not isinstance(result, dict) \
            or result.get("protocolVersion") != MCP_PROTOCOL_VERSION \
            or result.get("serverInfo", {}).get("name") != "jackel-codex" \
            or not isinstance(result.get("capabilities", {}).get("tools"), dict):
        raise AcceptanceError("MCP initialize returned an unsupported capability shape")


def _validate_inventory(response: object, runtime_document: object) -> list[str]:
    if not isinstance(runtime_document, dict) \
            or not isinstance(runtime_document.get("tools"), list):
        raise AcceptanceError("runtime tools document is malformed")
    expected = [record.get("name") for record in runtime_document["tools"]
                if isinstance(record, dict)]
    result = response.get("result") if isinstance(response, dict) else None
    tools = result.get("tools") if isinstance(result, dict) else None
    if not isinstance(tools, list):
        raise AcceptanceError("MCP tools/list returned no tool inventory")
    discovered = [record.get("name") for record in tools if isinstance(record, dict)]
    if len(expected) < MIN_TOOL_COUNT:
        raise AcceptanceError("runtime catalog shrank below the frozen floor")
    if len(discovered) != len(expected) \
            or len(set(discovered)) != len(discovered) \
            or discovered != expected:
        raise AcceptanceError("MCP inventory differs from the exact runtime catalog")
    return discovered


def run_acceptance(
    *, client: Any, runtime_document: dict[str, Any],
    direct_call: Callable[[str, dict[str, Any]], dict[str, Any]],
) -> dict[str, Any]:
    initialize = client.request(
        "initialize-1", "initialize",
        {
            "protocolVersion": MCP_PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "jackel-live-acceptance", "version": "1"},
        },
    )
    _validate_initialize(initialize)
    client.notification("notifications/initialized", {})
    discovered = _validate_inventory(
        client.request("tools-list-1", "tools/list", {}), runtime_document,
    )

    exact_response = client.request(
        "exact-1", "tools/call",
        {"name": "jackal_exact", "arguments": copy.deepcopy(EXACT_ARGUMENTS)},
    )
    exact = validate_exact(
        exact_response, direct_call("jackal_exact", copy.deepcopy(EXACT_ARGUMENTS)),
    )

    formal_response = client.request(
        "formal-1", "tools/call",
        {"name": "jackal_integrate_bound_cert",
         "arguments": copy.deepcopy(FORMAL_ARGUMENTS)},
    )
    formal = validate_formal_int_cert(
        formal_response,
        direct_call("jackal_integrate_bound_cert", copy.deepcopy(FORMAL_ARGUMENTS)),
    )

    refused_response = client.request(
        "refuse-1", "tools/call",
        {"name": "jackal_integrate_bound_cert",
         "arguments": copy.deepcopy(UNSUPPORTED_FORMAL_ARGUMENTS)},
    )
    refused = validate_unsupported_formal(
        refused_response,
        direct_call(
            "jackal_integrate_bound_cert",
            copy.deepcopy(UNSUPPORTED_FORMAL_ARGUMENTS),
        ),
    )

    claim_response = client.request(
        "claim-1", "tools/call",
        {"name": "jackal_claim", "arguments": {"request": copy.deepcopy(CLAIM_REQUEST)}},
    )
    bundle = _validate_claim(tool_payload(claim_response))
    bundle_verified = _validate_bundle_verification(client.request(
        "bundle-verify-1", "tools/call",
        {"name": "jackal_verify_bundle",
         "arguments": claim_verification_arguments(bundle)},
    ))

    receipt = formal["receipt"]
    receipt_verified = _validate_receipt_verification(client.request(
        "receipt-verify-1", "tools/call",
        {"name": "jackal_verify_receipt",
         "arguments": receipt_verification_arguments(receipt)},
    ), receipt)

    return {
        "discovered_tool_count": len(discovered),
        "gates": {
            "exact": exact["status"],
            "formal": formal["status"],
            "unsupported_formal": refused["reason"],
            "claim_bundle": bundle_verified["status"],
            "formal_receipt": receipt_verified["status"],
        },
    }


class MCPClient:
    """Small bounded line-delimited MCP client for the installed adapter."""

    def __init__(
        self, command: Sequence[str], *, cwd: Path | str,
        environment: Mapping[str, str], timeout: float = 3700,
        line_limit: int = 32 * 1024 * 1024,
    ) -> None:
        self.timeout = float(timeout)
        self.line_limit = int(line_limit)
        self._buffer = bytearray()
        self._stderr = tempfile.TemporaryFile()
        self._process = subprocess.Popen(
            list(command), cwd=str(cwd), env=dict(environment),
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self._stderr,
            start_new_session=True,
        )

    def __enter__(self) -> "MCPClient":
        return self

    def __exit__(self, unused_type, existing_error, unused_traceback) -> None:
        try:
            self.close()
        except AcceptanceError:
            if existing_error is None:
                raise

    def _send(self, message: dict[str, Any]) -> None:
        if self._process.stdin is None:
            raise AcceptanceError("MCP stdin is unavailable")
        try:
            encoded = canonical_bytes(message) + b"\n"
            self._process.stdin.write(encoded)
            self._process.stdin.flush()
        except (BrokenPipeError, OSError) as error:
            raise AcceptanceError("MCP adapter closed stdin") from error

    def _read(self) -> dict[str, Any]:
        if self._process.stdout is None:
            raise AcceptanceError("MCP stdout is unavailable")
        descriptor = self._process.stdout.fileno()
        deadline = time.monotonic() + self.timeout
        while True:
            newline = self._buffer.find(b"\n")
            if newline >= 0:
                raw = bytes(self._buffer[:newline])
                del self._buffer[:newline + 1]
                try:
                    value = strict_json_loads(raw)
                except (ValueError, json.JSONDecodeError) as error:
                    raise AcceptanceError("MCP adapter emitted invalid JSON") from error
                if not isinstance(value, dict):
                    raise AcceptanceError("MCP adapter emitted a non-object response")
                return value
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise AcceptanceError("MCP response timed out")
            readable, _, _ = select.select([descriptor], [], [], remaining)
            if not readable:
                raise AcceptanceError("MCP response timed out")
            chunk = os.read(descriptor, 64 * 1024)
            if not chunk:
                raise AcceptanceError("MCP adapter closed stdout")
            self._buffer.extend(chunk)
            if len(self._buffer) > self.line_limit:
                raise AcceptanceError("MCP response exceeded its byte limit")

    def request(
        self, request_id: str | int, method: str, params: dict[str, Any],
    ) -> dict[str, Any]:
        self._send({
            "jsonrpc": "2.0", "id": request_id, "method": method,
            "params": params,
        })
        response = self._read()
        if response.get("jsonrpc") != "2.0" or response.get("id") != request_id:
            raise AcceptanceError("MCP response correlation failed")
        if "error" in response:
            raise AcceptanceError("MCP request returned a protocol error")
        return response

    def notification(self, method: str, params: dict[str, Any]) -> None:
        self._send({"jsonrpc": "2.0", "method": method, "params": params})

    def close(self) -> None:
        process = self._process
        cleanup_error: Exception | None = None
        try:
            if process.stdin is not None:
                try:
                    process.stdin.close()
                except OSError:
                    pass
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    process.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    try:
                        process.wait(timeout=2)
                    except subprocess.TimeoutExpired as error:
                        cleanup_error = error
        except OSError as error:
            cleanup_error = error
        finally:
            if process.stdout is not None:
                try:
                    process.stdout.close()
                except OSError:
                    pass
            try:
                self._stderr.close()
            except OSError:
                pass
        if cleanup_error is not None:
            raise AcceptanceError("MCP adapter did not terminate within cleanup bounds") from cleanup_error


def load_installed_mcp_declaration(
    installed_root: Path | str,
) -> tuple[Path, dict[str, Any]]:
    """Load and validate exactly one installed MCP launch declaration."""
    try:
        installed = Path(installed_root).resolve(strict=True)
        raw = identity._read_regular_file_nofollow(
            installed / ".mcp.json", "installed MCP configuration"
        )
        document = strict_json_loads(raw)
    except (OSError, ValueError, json.JSONDecodeError, identity.ManifestError) as error:
        raise AcceptanceError("installed MCP configuration is invalid") from error
    if not isinstance(document, dict) or set(document) != {"mcpServers"}:
        raise AcceptanceError("installed MCP configuration has an unsupported shape")
    servers = document["mcpServers"]
    if not isinstance(servers, dict) or set(servers) != {PLUGIN}:
        raise AcceptanceError("installed MCP configuration has an unsupported server set")
    record = servers[PLUGIN]
    expected_fields = {"command", "args", "cwd", "env_vars", "tool_timeout_sec"}
    if not isinstance(record, dict) or set(record) != expected_fields:
        raise AcceptanceError("installed MCP server configuration has an unsupported shape")
    command = record["command"]
    arguments = record["args"]
    if (
        not isinstance(command, str)
        or not Path(command).is_absolute()
        or not isinstance(arguments, list)
        or not arguments
        or any(not isinstance(argument, str) or not argument for argument in arguments)
        or record["cwd"] != "."
        or record["env_vars"] != ["JACKAL_HOME"]
        or record["tool_timeout_sec"] != 3700
    ):
        raise AcceptanceError("installed MCP launch declaration is invalid")
    return installed, record


def installed_mcp_client(
    installed_root: Path | str, environment: Mapping[str, str],
) -> MCPClient:
    """Start exactly the installed plugin's declared MCP command."""
    installed, record = load_installed_mcp_declaration(installed_root)
    command = record["command"]
    arguments = record["args"]
    return MCPClient(
        [command, *arguments], cwd=installed, environment=environment,
    )


def load_runtime_document(runtime_root: Path | str) -> dict[str, Any]:
    path = Path(runtime_root) / "plugin" / "hermes" / "tools.json"
    try:
        raw = identity._read_regular_file_nofollow(path, "runtime tools catalog")
        document = strict_json_loads(raw)
    except (identity.ManifestError, OSError, ValueError, json.JSONDecodeError) as error:
        raise AcceptanceError("runtime tools catalog is unreadable") from error
    if not isinstance(document, dict):
        raise AcceptanceError("runtime tools catalog is not an object")
    return document


def runtime_acceptance_environment(
    runtime_root: Path | str,
    caller_environment: Mapping[str, str] | None = None,
) -> dict[str, str]:
    runtime = Path(runtime_root)
    if not runtime.is_absolute():
        raise AcceptanceError("runtime environment requires an absolute runtime root")
    source = dict(os.environ if caller_environment is None else caller_environment)
    source["JACKAL_HOME"] = os.fspath(runtime)
    try:
        return provisioner.runtime_subprocess_environment(source)
    except provisioner.ProvisionError as error:
        raise AcceptanceError("runtime subprocess environment refused") from error


def direct_backend_call(
    runtime_root: Path | str, tool: str, arguments: dict[str, Any],
    *, environment: Mapping[str, str], timeout: float = 3600,
) -> dict[str, Any]:
    runtime = Path(runtime_root)
    launcher = runtime / "plugin" / "hermes" / "jackal_hermes"
    completed = subprocess.run(
        [str(launcher), "call", tool, canonical_bytes(arguments).decode("utf-8")],
        cwd=runtime, capture_output=True, text=True, check=False, timeout=timeout,
        env=dict(environment),
    )
    try:
        value = strict_json_loads(completed.stdout)
    except (ValueError, json.JSONDecodeError) as error:
        raise AcceptanceError("direct backend emitted invalid JSON") from error
    if not isinstance(value, dict):
        raise AcceptanceError("direct backend emitted a non-object")
    expected_code = 1 if value.get("status") == "refused" else 0
    if completed.returncode != expected_code:
        raise AcceptanceError("direct backend exit status disagrees with result")
    return value


def verify_runtime(runtime_root: Path | str) -> None:
    try:
        provisioner.validate_runtime(
            Path(runtime_root), timeout=provisioner.SELFTEST_TIMEOUT,
            output_limit=provisioner.SELFTEST_OUTPUT_LIMIT,
            expected_tree_sha256=provisioner.SHA256SUMS_SHA256,
        )
    except provisioner.ProvisionError as error:
        raise AcceptanceError("pinned runtime validation refused") from error


def dry_run_document(
    *, codex_binary: Path | str, repository_root: Path | str,
) -> dict[str, Any]:
    placeholder = Path("/private/tmp/jackel-codex-isolated-CODEX_HOME")
    plan = build_codex_install_plan(
        codex_home=placeholder, repository_root=repository_root,
        codex_binary=codex_binary,
    )
    return {
        "mode": "dry-run",
        "network": False,
        "runtime_provisioning": False,
        "commands": [list(command) for command in plan.commands],
        "mcp_tools": [
            "jackal_exact", "jackal_integrate_bound_cert",
            "jackal_claim", "jackal_verify_bundle", "jackal_verify_receipt",
        ],
        "caller_pins": {
            "claim_release_epoch": CLAIM_RELEASE_EPOCH,
            "formal_release_epoch": FORMAL_RELEASE_EPOCH,
            "policy_sha256": DEFAULT_POLICY_SHA256,
            "root_proposition_sha256": EXPECTED_ROOT_PROPOSITION_SHA256,
            "verification_time_unix": CLAIM_TIME,
            "nonce": CLAIM_NONCE,
        },
    }


def _isolated_codex_temp_parent() -> Path:
    parent = Path("/private/tmp")
    try:
        info = parent.lstat()
        resolved = parent.resolve(strict=True)
    except OSError as error:
        raise AcceptanceError("fixed isolated temporary root is unavailable") from error
    if (
        stat.S_ISLNK(info.st_mode)
        or not stat.S_ISDIR(info.st_mode)
        or resolved != parent
    ):
        raise AcceptanceError("fixed isolated temporary root is not canonical")
    if any(
        parent == actual
        or parent.is_relative_to(actual)
        or actual.is_relative_to(parent)
        for actual in _forbidden_codex_homes()
    ):
        raise AcceptanceError("fixed isolated temporary root overlaps Codex state")
    return parent


def _live(runtime_root: Path, codex_binary: Path) -> dict[str, Any]:
    source_aggregate = verify_wrapper(PLUGIN_ROOT)
    verify_runtime(runtime_root)
    runtime_document = load_runtime_document(runtime_root)
    with tempfile.TemporaryDirectory(
        prefix="jackel-codex-live-", dir=_isolated_codex_temp_parent()
    ) as directory:
        codex_home = Path(directory)
        plan = build_codex_install_plan(
            codex_home=codex_home, repository_root=REPOSITORY_ROOT,
            codex_binary=codex_binary,
        )
        execute_codex_install(plan)
        installed = locate_cache_copy(
            codex_home, PLUGIN_ROOT, expected_aggregate=source_aggregate,
        )
        environment = runtime_acceptance_environment(runtime_root)
        with installed_mcp_client(installed, environment) as client:
            report = run_acceptance(
                client=client, runtime_document=runtime_document,
                direct_call=lambda tool, arguments: direct_backend_call(
                    runtime_root, tool, arguments, environment=environment
                ),
            )
    return {
        "status": "accepted",
        "wrapper_aggregate_sha256": source_aggregate,
        "runtime_package_sha256": provisioner.PACKAGE_SHA256,
        "runtime_tree_sha256": provisioner.SHA256SUMS_SHA256,
        **report,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--live", action="store_true")
    modes.add_argument("--host-live", action="store_true")
    parser.add_argument("--runtime-root", type=Path)
    parser.add_argument("--codex-binary", type=Path, default=Path("codex"))
    parser.add_argument("--codex-home", type=Path)
    parser.add_argument("--host-evidence", type=Path)
    arguments = parser.parse_args(argv)
    try:
        if arguments.host_live:
            required = (
                arguments.runtime_root,
                arguments.codex_binary,
                arguments.codex_home,
                arguments.host_evidence,
            )
            if any(path is None or not path.is_absolute() for path in required):
                raise AcceptanceError(
                    "--host-live requires absolute --runtime-root, --codex-binary, "
                    "--codex-home, and --host-evidence"
                )
            document = run_host_discovery_acceptance(
                codex_binary=arguments.codex_binary,
                codex_home=arguments.codex_home,
                runtime_root=arguments.runtime_root,
                evidence_path=arguments.host_evidence,
            )
        elif arguments.live:
            if arguments.runtime_root is None or not arguments.runtime_root.is_absolute():
                raise AcceptanceError("--live requires an absolute --runtime-root")
            document = _live(arguments.runtime_root, arguments.codex_binary)
        else:
            document = dry_run_document(
                codex_binary=arguments.codex_binary,
                repository_root=REPOSITORY_ROOT,
            )
    except AcceptanceError as error:
        print(
            "live_acceptance=refused detail="
            + (" ".join(str(error).splitlines()) or "acceptance failed")[:240],
            file=sys.stderr,
        )
        return 1
    print(json.dumps(document, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
