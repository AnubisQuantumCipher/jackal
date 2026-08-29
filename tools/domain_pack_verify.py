#!/usr/bin/env python3
"""Fail-closed verifier for the JACKAL domain-pack protocol."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import stat
import sys
from pathlib import Path
from typing import Any


MAX_BOOTSTRAP_JSON_BYTES = 1_048_576
MAX_BOOTSTRAP_TEXT_BYTES = 8_388_608
MAX_DOMAIN_INVENTORY_ENTRIES = 8192
MAX_DOMAIN_INVENTORY_DEPTH = 64
MAX_DOMAIN_INVENTORY_PATH_BYTES = 4096
MAX_JSON_STRUCTURE_DEPTH = 64
MAX_JSON_STRUCTURE_NODES = 65_536
MAX_JSON_INTEGER_DIGITS = 19
SHA256_RE = re.compile(r"[0-9a-f]{64}")
ID_RE = re.compile(r"[a-z][a-z0-9]*(?:[._-][a-z0-9]+)+")
VERSION_RE = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+")
RELEASE_RE = re.compile(r"v[0-9]+\.[0-9]+\.[0-9]+")

PROTOCOL_V1_LIMITS = {
    "max_json_bytes": 1_048_576,
    "max_artifact_bytes": 8_388_608,
    "max_pack_artifact_bytes": 16_777_216,
    "max_packs": 64,
    "max_operations_per_pack": 256,
    "max_total_operations": 4096,
    "max_request_bytes": 1_048_576,
    "max_response_bytes": 4_194_304,
    "max_arguments": 64,
    "max_argument_bytes": 16_384,
    "max_timeout_ms": 600_000,
    "max_memory_bytes": 1_073_741_824,
    "max_depth": 64,
    "max_nodes": 4096,
    "max_text_bytes": 4096,
}
PROTOCOL_V1_REQUIRED_NONCLAIMS = [
    "no_input_truth",
    "no_universal_soundness",
    "raw_output_requires_independent_verification",
]
PROTOCOL_V1_ASSURANCE_SOURCE = (
    "release/claim/inference_registry_v1.json#axis_orders.mathematical"
)
PROTOCOL_V1_CONSEQUENCE_SOURCE = (
    "release/claim/inference_registry_v1.json#consequence_classes"
)
# The consequence axis is an ordered lattice for the purpose of a *ceiling*
# check. The pinned registry stores each class as a floor row rather than as an
# ordered list, so the order lives here and is cross-checked against the
# registry's key set at verification time: a class the registry knows and this
# table does not is a fail-closed refusal, never a silent pass.
PROTOCOL_V1_CONSEQUENCE_ORDER = [
    "informational",
    "advisory",
    "decision-boundary",
    "safety-critical",
]
# Closed evidence-contract allowlist. Each entry binds an evidence kind to the
# single response schema and single checker identity that may carry it, plus
# the strongest assurance AND the strongest consequence class the kind is ever
# permitted to reach. The consequence bound is not documentation: a structural
# programming fact is byte-exact (`exact`) yet may never be rendered as a
# correctness or safety claim, so its consequence bound is `informational`.
TRUSTED_V1_EVIDENCE_CONTRACTS = {
    "exact-cert": {
        "response_schema": "jackal-exact-cert-v1",
        "checker_path": "tools/exact_verify.py",
        "checker_sha256": (
            "2c07e6257ce1524de3e31374371c6d5859dce710767156de2566ec77fa1883a7"
        ),
        "assurance_ceiling": "exact",
        "consequence_bound": "safety-critical",
    },
    "test-exists-cert": {
        "response_schema": "jackal-test-exists-cert-v1",
        "checker_path": "tools/test_exists_verify.py",
        "checker_sha256": (
            "598cb99e1eb70c9410ca87345efee346f73e43aaf3625427dca17ea04231caea"
        ),
        "assurance_ceiling": "exact",
        "consequence_bound": "informational",
    },
    "decision-cert": {
        "response_schema": "jackal-decision-cert-v1",
        # A second response schema, NOT a second contract. `jackal-decision-cert-v2`
        # is the closed-unit lane of the same evidence kind: same single checker
        # identity below, same assurance ceiling, same consequence bound. What
        # the closure rule requires is that the set of admissible (kind, schema)
        # pairs be enumerated here and that each be carried by exactly one
        # checker; a kind with two schemas and one checker satisfies that, and a
        # schema absent from this tuple is still refused.
        "additional_response_schemas": ("jackal-decision-cert-v2",),
        "checker_path": "tools/decision_verify.py",
        "checker_sha256": (
            "f1ad7c9fbd4c1d899dbb4bebabbbeb97e97a56bd4b279ad7d8ec3722bf12e0f6"
        ),
        "assurance_ceiling": "exact",
        "consequence_bound": "decision-boundary",
    },
}

SCHEMA_KEYS = {
    "schema", "protocol_version", "authority", "manifest_schema",
    "registry_schema", "request_abis", "assurance_ceiling_source",
    "consequence_class_source", "fallback", "resource_keys", "limits",
    "required_nonclaims",
}
LIMIT_KEYS = {
    "max_json_bytes", "max_artifact_bytes", "max_pack_artifact_bytes",
    "max_packs", "max_operations_per_pack", "max_total_operations",
    "max_request_bytes", "max_response_bytes", "max_arguments",
    "max_argument_bytes", "max_timeout_ms", "max_memory_bytes",
    "max_depth", "max_nodes", "max_text_bytes",
}
REGISTRY_KEYS = {
    "schema", "registry_version", "protocol_version", "authority",
    "pack_schema_path", "pack_schema_sha256", "pack_spec_path",
    "pack_spec_sha256", "pack_verifier_path", "pack_verifier_sha256",
    "inference_registry_path",
    "inference_registry_sha256", "packs", "registry_digest_sha256",
}
PACK_ROW_KEYS = {
    "pack_id", "pack_version", "manifest_path", "manifest_sha256",
    "entry_source_path", "entry_source_sha256", "route_source_path",
    "route_source_sha256", "operation_ids",
}
MANIFEST_KEYS = {
    "schema", "protocol_version", "pack_id", "pack_version",
    "description", "compatibility", "request_abi", "engine", "operations",
    "manifest_digest_sha256",
}
COMPATIBILITY_KEYS = {
    "jackal_release_min", "jackal_release_max_exclusive", "protocol_min",
    "protocol_max",
}
ENGINE_KEYS = {
    "authority", "entry_source_path", "entry_source_sha256",
    "route_source_path", "route_source_sha256", "route_command",
}
OPERATION_KEYS = {
    "operation_id", "engine_command", "argument_schema", "response_schema",
    "checker", "evidence_kind", "inference_rule", "assurance_ceiling",
    "consequence_ceiling", "refusal_classes", "fallback", "resources",
    "nonclaims",
}
ARGUMENT_KEYS = {"name", "type", "max_bytes"}
CHECKER_KEYS = {"path", "sha256"}
FALLBACK_KEYS = {"allowed", "reason"}
ARGUMENT_TYPES = {
    "canonical_integer", "canonical_nonnegative_integer",
    "canonical_positive_integer", "canonical_rational", "utf8_text",
    "content_digest", "path_token",
}


class PackVerificationError(RuntimeError):
    """Stable fail-closed verification refusal."""


def refuse(message: str) -> None:
    raise PackVerificationError(message)


def canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            refuse(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def strict_json_integer(token: str) -> int:
    digits = token[1:] if token.startswith("-") else token
    if len(digits) > MAX_JSON_INTEGER_DIGITS:
        refuse("JSON integer exceeds digit budget")
    return int(token)


def refuse_json_float(token: str) -> None:
    refuse(f"non-integer JSON number is not admitted: {token[:64]}")


def validate_json_structure(value: object, context: str) -> None:
    stack: list[tuple[object, int]] = [(value, 0)]
    nodes = 0
    while stack:
        current, depth = stack.pop()
        nodes += 1
        if nodes > MAX_JSON_STRUCTURE_NODES:
            refuse(f"JSON structure node budget exceeded: {context}")
        if depth > MAX_JSON_STRUCTURE_DEPTH:
            refuse(f"JSON structure depth budget exceeded: {context}")
        if isinstance(current, dict):
            nodes += len(current)
            if nodes > MAX_JSON_STRUCTURE_NODES:
                refuse(f"JSON structure node budget exceeded: {context}")
            stack.extend((item, depth + 1) for item in current.values())
        elif isinstance(current, list):
            stack.extend((item, depth + 1) for item in current)


def decode_json_bytes(raw: bytes, context: str) -> object:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        refuse(f"JSON is not UTF-8: {context}")
    try:
        value = json.loads(
            text,
            object_pairs_hook=strict_object,
            parse_int=strict_json_integer,
            parse_float=refuse_json_float,
            parse_constant=lambda token: refuse(f"non-finite JSON number: {token}"),
        )
    except PackVerificationError:
        raise
    except (json.JSONDecodeError, RecursionError) as error:
        refuse(f"invalid or over-nested JSON: {context}: {error}")
    validate_json_structure(value, context)
    return value


def read_regular_bounded(path: Path, maximum: int) -> bytes:
    try:
        before = path.lstat()
    except OSError as error:
        refuse(f"cannot stat {path}: {error}")
    if not stat.S_ISREG(before.st_mode):
        refuse(f"not a regular file: {path}")
    if before.st_size > maximum:
        refuse(f"artifact exceeds byte bound: {path}")
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        refuse(f"cannot open {path}: {error}")
    try:
        opened = os.fstat(descriptor)
        if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
            refuse(f"artifact path identity changed before read: {path}")
        chunks: list[bytes] = []
        total = 0
        while True:
            remaining = maximum + 1 - total
            chunk = os.read(descriptor, min(1_048_576, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > maximum:
                refuse(f"artifact exceeds byte bound while reading: {path}")
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    try:
        current = path.lstat()
    except OSError as error:
        refuse(f"artifact disappeared after read: {path}: {error}")
    def identity(value: os.stat_result) -> tuple[int, int, int, int, int, int]:
        return (
            value.st_dev,
            value.st_ino,
            value.st_mode,
            value.st_size,
            value.st_mtime_ns,
            value.st_ctime_ns,
        )
    if identity(opened) != identity(after) or identity(after) != identity(current):
        refuse(f"artifact changed while reading: {path}")
    return b"".join(chunks)


def load_json(path: Path, maximum: int) -> tuple[dict[str, Any], bytes]:
    raw = read_regular_bounded(path, maximum)
    value = decode_json_bytes(raw, os.fspath(path))
    if not isinstance(value, dict):
        refuse(f"JSON root must be an object: {path}")
    return value, raw


def exact_keys(value: object, expected: set[str], context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        refuse(f"{context} must be an object")
    actual = set(value)
    if actual != expected:
        refuse(f"{context} keys mismatch: {sorted(actual ^ expected)}")
    return value


def bounded_text(value: object, context: str, maximum: int) -> str:
    if not isinstance(value, str) or not value:
        refuse(f"{context} must be non-empty text")
    if len(value.encode("utf-8")) > maximum:
        refuse(f"{context} exceeds text bound")
    return value


def digest_token(value: object, context: str) -> str:
    if not isinstance(value, str) or SHA256_RE.fullmatch(value) is None:
        refuse(f"{context} is not a canonical SHA-256")
    return value


def positive_integer(value: object, context: str, maximum: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        refuse(f"{context} must be a positive integer")
    if value > maximum:
        refuse(f"{context} exceeds protocol limit")
    return value


def safe_path(root: Path, value: object, context: str) -> tuple[str, Path]:
    text = bounded_text(value, context, 512)
    relative = Path(text)
    if (
        relative.is_absolute()
        or ".." in relative.parts
        or relative.as_posix() != text
        or "\\" in text
        or text.startswith("./")
    ):
        refuse(f"unsafe path in {context}: {text}")
    candidate = root / relative
    resolved_root = root.resolve()
    resolved_parent = candidate.parent.resolve(strict=False)
    if resolved_parent != resolved_root and resolved_root not in resolved_parent.parents:
        refuse(f"path escapes repository in {context}: {text}")
    return text, candidate


def check_self_digest(document: dict[str, Any], key: str, context: str) -> str:
    actual = digest_token(document.get(key), f"{context}.{key}")
    expected = sha256(canonical_bytes({k: v for k, v in document.items() if k != key}))
    if actual != expected:
        refuse(f"{context} self-digest mismatch")
    return actual


def read_bound_artifact(
    root: Path, relative: object, expected_digest: object, maximum: int, context: str
) -> tuple[str, bytes]:
    relative_text, path = safe_path(root, relative, f"{context}.path")
    expected = digest_token(expected_digest, f"{context}.sha256")
    raw = read_regular_bounded(path, maximum)
    if sha256(raw) != expected:
        refuse(f"artifact digest mismatch: {relative_text}")
    return relative_text, raw


def _string_list(value: object, context: str, maximum: int) -> list[str]:
    if not isinstance(value, list) or not value or len(value) > maximum:
        refuse(f"{context} must be a non-empty bounded list")
    result: list[str] = []
    for index, item in enumerate(value):
        text = bounded_text(item, f"{context}[{index}]", 256)
        if text in result:
            refuse(f"duplicate value in {context}: {text}")
        result.append(text)
    return result


def _domain_inventory(root: Path, expected_files: set[str]) -> None:
    domain_root = root / "domain_packs"
    expected_dirs = {""}
    for relative in expected_files:
        path = Path(relative)
        for parent in path.parents:
            if parent == Path("."):
                break
            expected_dirs.add(parent.as_posix())
    actual_files: set[str] = set()
    actual_dirs: set[str] = {""}
    stack = [domain_root]
    entry_count = 0
    while stack:
        directory = stack.pop()
        try:
            entries = os.scandir(directory)
        except OSError as error:
            refuse(f"cannot scan domain-pack inventory: {error}")
        with entries:
            for entry in entries:
                entry_count += 1
                if entry_count > MAX_DOMAIN_INVENTORY_ENTRIES:
                    refuse("domain-pack inventory entry budget exceeded")
                relative_path = Path(directory).relative_to(domain_root) / entry.name
                relative = relative_path.as_posix()
                if len(relative_path.parts) > MAX_DOMAIN_INVENTORY_DEPTH:
                    refuse("domain-pack inventory depth budget exceeded")
                if len(relative.encode("utf-8")) > MAX_DOMAIN_INVENTORY_PATH_BYTES:
                    refuse("domain-pack inventory path budget exceeded")
                try:
                    metadata = entry.stat(follow_symlinks=False)
                except OSError as error:
                    refuse(
                        f"cannot stat domain-pack inventory entry: {relative}: {error}"
                    )
                if stat.S_ISDIR(metadata.st_mode):
                    actual_dirs.add(relative)
                    stack.append(Path(entry.path))
                elif stat.S_ISREG(metadata.st_mode):
                    actual_files.add(relative)
                else:
                    refuse(f"non-regular domain-pack inventory entry: {relative}")
    if actual_files != expected_files or actual_dirs != expected_dirs:
        refuse(
            "domain-pack inventory mismatch: "
            f"files={sorted(actual_files ^ expected_files)} "
            f"dirs={sorted(actual_dirs ^ expected_dirs)}"
        )


def _verify_schema(document: dict[str, Any]) -> dict[str, Any]:
    schema = exact_keys(document, SCHEMA_KEYS, "pack schema")
    if schema["schema"] != "jackal-domain-pack-contract-schema-v1":
        refuse("wrong pack schema identity")
    if schema["protocol_version"] != "1":
        refuse("wrong protocol version")
    if schema["authority"] != "anubis-safe-mode":
        refuse("pack schema has non-Anubis authority")
    if schema["manifest_schema"] != "jackal-domain-pack-manifest-v1":
        refuse("wrong manifest schema identity")
    if schema["registry_schema"] != "jackal-domain-pack-registry-v1":
        refuse("wrong registry schema identity")
    if schema["request_abis"] != ["argv-v1"]:
        refuse("unsupported request ABI set")
    if schema["fallback"] != {"allowed": False, "reason": "fallback_forbidden"}:
        refuse("schema fallback must be forbidden")
    resource_keys = _string_list(schema["resource_keys"], "schema.resource_keys", 32)
    limits = exact_keys(schema["limits"], LIMIT_KEYS, "schema.limits")
    for key, value in limits.items():
        positive_integer(value, f"schema.limits.{key}", 2**63 - 1)
    if limits != PROTOCOL_V1_LIMITS:
        refuse("v1 protocol limits mismatch")
    if set(resource_keys) != {
        "max_request_bytes", "max_response_bytes", "max_arguments",
        "max_argument_bytes", "timeout_ms", "memory_bytes", "max_depth",
        "max_nodes",
    }:
        refuse("schema resource key set mismatch")
    required_nonclaims = _string_list(
        schema["required_nonclaims"], "schema.required_nonclaims", 32
    )
    if required_nonclaims != PROTOCOL_V1_REQUIRED_NONCLAIMS:
        refuse("v1 mandatory nonclaims mismatch")
    assurance_source = bounded_text(
        schema["assurance_ceiling_source"], "assurance source", 512
    )
    consequence_source = bounded_text(
        schema["consequence_class_source"], "consequence source", 512
    )
    if assurance_source != PROTOCOL_V1_ASSURANCE_SOURCE:
        refuse("v1 assurance source mismatch")
    if consequence_source != PROTOCOL_V1_CONSEQUENCE_SOURCE:
        refuse("v1 consequence source mismatch")
    return schema


def _release_tuple(value: object, context: str) -> tuple[int, int, int]:
    text = bounded_text(value, context, 64)
    if RELEASE_RE.fullmatch(text) is None:
        refuse(f"invalid release version in {context}: {text}")
    major, minor, patch = text[1:].split(".")
    return int(major), int(minor), int(patch)


SUPPORTED_HOSTS = {("Darwin", "arm64"), ("Linux", "aarch64")}


def validate_host() -> None:
    system = platform.system()
    machine = platform.machine()
    if (system, machine) not in SUPPORTED_HOSTS:
        supported = ", ".join(f"{s}/{m}" for s, m in sorted(SUPPORTED_HOSTS))
        refuse(
            "unsupported host: domain-pack protocol v1 requires "
            f"one of {supported}, got {system}/{machine}"
        )


def _verify_operation(
    operation: object,
    *,
    index: int,
    root: Path,
    schema: dict[str, Any],
    inference: dict[str, Any],
    seen_operations: set[str],
) -> tuple[str, str]:
    context = f"operation[{index}]"
    row = exact_keys(operation, OPERATION_KEYS, context)
    operation_id = bounded_text(row["operation_id"], f"{context}.operation_id", 128)
    if ID_RE.fullmatch(operation_id) is None:
        refuse(f"invalid operation id: {operation_id}")
    if operation_id in seen_operations:
        refuse(f"duplicate operation id: {operation_id}")
    seen_operations.add(operation_id)
    engine_command = bounded_text(row["engine_command"], f"{context}.engine_command", 128)
    if ID_RE.fullmatch(f"x.{engine_command.replace('-', '_')}") is None:
        refuse(f"invalid engine command: {engine_command}")
    response_schema = bounded_text(row["response_schema"], f"{context}.response_schema", 128)

    if not isinstance(row["resources"], dict) or set(row["resources"]) != set(schema["resource_keys"]):
        refuse(f"resource keys mismatch: {operation_id}")
    resources = row["resources"]
    limit_map = {
        "max_request_bytes": "max_request_bytes",
        "max_response_bytes": "max_response_bytes",
        "max_arguments": "max_arguments",
        "max_argument_bytes": "max_argument_bytes",
        "timeout_ms": "max_timeout_ms",
        "memory_bytes": "max_memory_bytes",
        "max_depth": "max_depth",
        "max_nodes": "max_nodes",
    }
    for key, limit_key in limit_map.items():
        positive_integer(resources[key], f"{context}.resources.{key}", schema["limits"][limit_key])

    arguments = row["argument_schema"]
    if not isinstance(arguments, list) or len(arguments) != resources["max_arguments"]:
        refuse(f"{context} argument count does not match max_arguments")
    argument_names: set[str] = set()
    for argument_index, argument in enumerate(arguments):
        argument_context = f"{context}.argument_schema[{argument_index}]"
        argument_row = exact_keys(argument, ARGUMENT_KEYS, argument_context)
        name = bounded_text(argument_row["name"], f"{argument_context}.name", 64)
        if re.fullmatch(r"[a-z][a-z0-9_]*", name) is None or name in argument_names:
            refuse(f"invalid or duplicate argument name: {name}")
        argument_names.add(name)
        if argument_row["type"] not in ARGUMENT_TYPES:
            refuse(f"unknown argument type: {argument_row['type']}")
        maximum = positive_integer(
            argument_row["max_bytes"], f"{argument_context}.max_bytes",
            resources["max_argument_bytes"],
        )
        if maximum > resources["max_argument_bytes"]:
            refuse(f"argument byte bound exceeds operation limit: {name}")

    inference_rule = bounded_text(row["inference_rule"], f"{context}.inference_rule", 128)
    rules = inference.get("rules")
    if not isinstance(rules, dict) or inference_rule not in rules:
        refuse(f"inference rule is not registered: {inference_rule}")
    if inference_rule != "evidence_admit":
        refuse(f"v1 operations require evidence_admit: {operation_id}")
    evidence_kind = bounded_text(row["evidence_kind"], f"{context}.evidence_kind", 128)
    adapters = inference.get("evidence_admit_params_by_kind")
    if inference_rule == "evidence_admit" and (
        not isinstance(adapters, dict) or evidence_kind not in adapters
    ):
        refuse(f"evidence kind is not registered: {evidence_kind}")
    assurance = bounded_text(row["assurance_ceiling"], f"{context}.assurance_ceiling", 64)
    axis_orders = inference.get("axis_orders")
    mathematical = axis_orders.get("mathematical") if isinstance(axis_orders, dict) else None
    if not isinstance(mathematical, list) or assurance not in mathematical:
        refuse(f"assurance ceiling is not registered: {assurance}")

    checker = exact_keys(row["checker"], CHECKER_KEYS, f"{context}.checker")
    checker_path = bounded_text(checker["path"], f"{context}.checker.path", 512)
    checker_digest = digest_token(checker["sha256"], f"{context}.checker.sha256")
    contract = TRUSTED_V1_EVIDENCE_CONTRACTS.get(evidence_kind)
    if contract is None:
        refuse(f"v1 evidence contract mismatch: {operation_id}")
    # The admissible response schemas for a kind are enumerated, closed, and
    # carried by exactly one checker identity. A kind may name more than one
    # schema (a versioned lane over the same evidence), but never more than one
    # checker, and never a schema absent from the tuple below.
    admitted_schemas = (
        contract["response_schema"],
        *contract.get("additional_response_schemas", ()),
    )
    if response_schema not in admitted_schemas or {
        "checker_path": checker_path,
        "checker_sha256": checker_digest,
        "assurance_ceiling": assurance,
    } != {key: contract[key] for key in (
        "checker_path", "checker_sha256", "assurance_ceiling",
    )}:
        refuse(f"v1 evidence contract mismatch: {operation_id}")
    _, checker_raw = read_bound_artifact(
        root, checker_path, checker_digest,
        schema["limits"]["max_artifact_bytes"], f"{context}.checker",
    )
    if not checker_raw.startswith(b"#!/usr/bin/env python3"):
        refuse(f"checker has unexpected executable format: {operation_id}")

    consequence = bounded_text(row["consequence_ceiling"], f"{context}.consequence_ceiling", 64)
    consequence_classes = inference.get("consequence_classes")
    if not isinstance(consequence_classes, dict) or consequence not in consequence_classes:
        refuse(f"consequence ceiling is not registered: {consequence}")
    # Validate the instrument before using it: if the pinned registry knows a
    # consequence class this verifier cannot rank, the ceiling comparison below
    # is not meaningful, so refuse rather than compare against a partial order.
    if not set(consequence_classes).issubset(PROTOCOL_V1_CONSEQUENCE_ORDER):
        refuse(
            "registry declares consequence classes outside the v1 order: "
            + ",".join(sorted(set(consequence_classes) - set(PROTOCOL_V1_CONSEQUENCE_ORDER)))
        )
    bound = contract["consequence_bound"]
    if PROTOCOL_V1_CONSEQUENCE_ORDER.index(consequence) > PROTOCOL_V1_CONSEQUENCE_ORDER.index(bound):
        refuse(
            "v1 consequence ceiling exceeds the evidence-contract bound: "
            f"{operation_id} evidence_kind={evidence_kind} "
            f"declared={consequence} bound={bound}"
        )

    exact_keys(row["fallback"], FALLBACK_KEYS, f"{context}.fallback")
    if row["fallback"] != schema["fallback"]:
        refuse(f"fallback must be forbidden: {operation_id}")
    if not isinstance(row["refusal_classes"], list) or not row["refusal_classes"]:
        refuse(f"refusal classes missing: {operation_id}")
    _string_list(row["refusal_classes"], f"{context}.refusal_classes", 64)
    nonclaims = _string_list(row["nonclaims"], f"{context}.nonclaims", 64)
    required_nonclaims = set(schema["required_nonclaims"])
    if not required_nonclaims.issubset(nonclaims):
        refuse(f"mandatory nonclaims missing: {operation_id}")
    return operation_id, response_schema


def verify_repository(root: Path | str) -> dict[str, Any]:
    validate_host()
    repository = Path(root).resolve()
    schema_path = repository / "domain_packs" / "PACK_SCHEMA.json"
    schema_document, schema_raw = load_json(schema_path, MAX_BOOTSTRAP_JSON_BYTES)
    schema = _verify_schema(schema_document)
    limits = schema["limits"]

    registry_path = repository / "domain_packs" / "registry_v1.json"
    registry_document, registry_raw = load_json(registry_path, limits["max_json_bytes"])
    registry = exact_keys(registry_document, REGISTRY_KEYS, "pack registry")
    if registry["schema"] != schema["registry_schema"]:
        refuse("registry schema mismatch")
    if registry["registry_version"] != "1" or registry["protocol_version"] != "1":
        refuse("registry version mismatch")
    if registry["authority"] != "anubis-safe-mode":
        refuse("registry has non-Anubis authority")
    registry_digest = check_self_digest(registry, "registry_digest_sha256", "registry")

    schema_relative, bound_schema = read_bound_artifact(
        repository, registry["pack_schema_path"], registry["pack_schema_sha256"],
        limits["max_json_bytes"], "registry.pack_schema",
    )
    if bound_schema != schema_raw or schema_relative != "domain_packs/PACK_SCHEMA.json":
        refuse("registry pack schema binding mismatch")
    spec_relative, _ = read_bound_artifact(
        repository, registry["pack_spec_path"], registry["pack_spec_sha256"],
        MAX_BOOTSTRAP_TEXT_BYTES, "registry.pack_spec",
    )
    if spec_relative != "domain_packs/PACK_SPEC.md":
        refuse("registry pack spec binding mismatch")
    verifier_relative, verifier_raw = read_bound_artifact(
        repository, registry["pack_verifier_path"],
        registry["pack_verifier_sha256"], limits["max_artifact_bytes"],
        "registry.pack_verifier",
    )
    if verifier_relative != "tools/domain_pack_verify.py":
        refuse("registry pack verifier binding mismatch")
    inference_relative, inference_raw = read_bound_artifact(
        repository, registry["inference_registry_path"],
        registry["inference_registry_sha256"], limits["max_json_bytes"],
        "registry.inference_registry",
    )
    if inference_relative != "release/claim/inference_registry_v1.json":
        refuse("registry inference binding mismatch")
    inference = decode_json_bytes(inference_raw, "pinned inference registry")
    if not isinstance(inference, dict):
        refuse("pinned inference registry root is not an object")

    packs = registry["packs"]
    if not isinstance(packs, list) or not (1 <= len(packs) <= limits["max_packs"]):
        refuse("pack count outside protocol bounds")
    seen_packs: set[str] = set()
    seen_operations: set[str] = set()
    expected_domain_files = {"PACK_SCHEMA.json", "PACK_SPEC.md", "registry_v1.json"}
    total_operations = 0
    total_pack_artifacts = 0
    manifests: list[dict[str, Any]] = []

    for pack_index, pack_value in enumerate(packs):
        context = f"pack[{pack_index}]"
        pack = exact_keys(pack_value, PACK_ROW_KEYS, context)
        pack_id = bounded_text(pack["pack_id"], f"{context}.pack_id", 128)
        if ID_RE.fullmatch(pack_id) is None or pack_id in seen_packs:
            refuse(f"invalid or duplicate pack id: {pack_id}")
        seen_packs.add(pack_id)
        pack_version = bounded_text(pack["pack_version"], f"{context}.pack_version", 64)
        if VERSION_RE.fullmatch(pack_version) is None:
            refuse(f"invalid pack version: {pack_version}")

        manifest_relative, manifest_raw = read_bound_artifact(
            repository, pack["manifest_path"], pack["manifest_sha256"],
            limits["max_json_bytes"], f"{context}.manifest",
        )
        if not manifest_relative.startswith("domain_packs/"):
            refuse(f"manifest is outside domain_packs: {pack_id}")
        expected_domain_files.add(manifest_relative.removeprefix("domain_packs/"))
        manifest = decode_json_bytes(manifest_raw, f"pack manifest {pack_id}")
        manifest = exact_keys(manifest, MANIFEST_KEYS, f"{context}.manifest")
        check_self_digest(manifest, "manifest_digest_sha256", f"manifest {pack_id}")
        if manifest["schema"] != schema["manifest_schema"]:
            refuse(f"manifest schema mismatch: {pack_id}")
        if manifest["protocol_version"] != "1":
            refuse(f"manifest protocol mismatch: {pack_id}")
        if manifest["pack_id"] != pack_id or manifest["pack_version"] != pack_version:
            refuse(f"manifest/registry identity mismatch: {pack_id}")
        bounded_text(manifest["description"], f"manifest {pack_id}.description", limits["max_text_bytes"])

        compatibility = exact_keys(
            manifest["compatibility"], COMPATIBILITY_KEYS,
            f"manifest {pack_id}.compatibility",
        )
        release_min = _release_tuple(
            compatibility["jackal_release_min"],
            f"manifest {pack_id}.compatibility.jackal_release_min",
        )
        release_max = _release_tuple(
            compatibility["jackal_release_max_exclusive"],
            f"manifest {pack_id}.compatibility.jackal_release_max_exclusive",
        )
        if compatibility["protocol_min"] != "1" or compatibility["protocol_max"] != "1":
            refuse(f"invalid compatibility range: {pack_id}")
        if release_min >= release_max:
            refuse(f"compatibility range is empty or reversed: {pack_id}")
        if manifest["request_abi"] not in schema["request_abis"]:
            refuse(f"unsupported request ABI: {pack_id}")

        engine = exact_keys(manifest["engine"], ENGINE_KEYS, f"manifest {pack_id}.engine")
        if engine["authority"] != "anubis-safe-mode":
            refuse(f"non-Anubis authority: {pack_id}")
        if engine["route_command"] != "pack-route":
            refuse(f"unsupported route command: {pack_id}")
        entry_relative, entry_raw = read_bound_artifact(
            repository, engine["entry_source_path"], engine["entry_source_sha256"],
            limits["max_artifact_bytes"], f"manifest {pack_id}.entry_source",
        )
        route_relative, route_raw = read_bound_artifact(
            repository, engine["route_source_path"], engine["route_source_sha256"],
            limits["max_artifact_bytes"], f"manifest {pack_id}.route_source",
        )
        if not route_relative.startswith("domain_packs/"):
            refuse(f"route source is outside domain_packs: {pack_id}")
        expected_domain_files.add(route_relative.removeprefix("domain_packs/"))
        total_pack_artifacts += len(manifest_raw) + len(route_raw)
        if total_pack_artifacts > limits["max_pack_artifact_bytes"]:
            refuse("aggregate pack artifacts exceed protocol bound")
        if (
            pack["entry_source_path"] != entry_relative
            or pack["entry_source_sha256"] != sha256(entry_raw)
            or pack["route_source_path"] != route_relative
            or pack["route_source_sha256"] != sha256(route_raw)
        ):
            refuse(f"registry/manifest source binding mismatch: {pack_id}")
        if not route_raw.lstrip().startswith(b"// JACKAL") or b"pub fn route_operation" not in route_raw:
            refuse(f"route source lacks closed Anubis entry: {pack_id}")
        import_token = f"import {route_relative[:-4].replace('/', '.')};".encode("utf-8")
        if import_token not in entry_raw or b'if op == "pack-route"' not in entry_raw:
            refuse(f"entry source does not bind the pack route: {pack_id}")

        operations = manifest["operations"]
        if not isinstance(operations, list) or not (
            1 <= len(operations) <= limits["max_operations_per_pack"]
        ):
            refuse(f"operation count outside protocol bounds: {pack_id}")
        operation_ids: list[str] = []
        for operation_index, operation in enumerate(operations):
            operation_id, _ = _verify_operation(
                operation,
                index=operation_index,
                root=repository,
                schema=schema,
                inference=inference,
                seen_operations=seen_operations,
            )
            operation_ids.append(operation_id)
        declared_ids = _string_list(pack["operation_ids"], f"{context}.operation_ids", limits["max_operations_per_pack"])
        if declared_ids != operation_ids:
            refuse(f"registry/manifest operation inventory mismatch: {pack_id}")
        total_operations += len(operation_ids)
        if total_operations > limits["max_total_operations"]:
            refuse("total operation count exceeds protocol bound")
        manifests.append(manifest)

    _domain_inventory(repository, expected_domain_files)
    return {
        "status": "accepted",
        "schema": schema["registry_schema"],
        "protocol_version": "1",
        "authority": "anubis-safe-mode",
        "host": f"{platform.system().lower()}-{platform.machine().lower()}",
        "verification_scope": "metadata-identity-and-policy-only",
        "anubis_execution_status": "NOT_EXECUTED",
        "assurance_status": "NOT_MINTED",
        "pack_count": len(packs),
        "operation_count": total_operations,
        "registry_digest_sha256": registry_digest,
        "registry_file_sha256": sha256(registry_raw),
        "verifier_sha256": sha256(verifier_raw),
        "pack_ids": sorted(seen_packs),
        "operation_ids": sorted(seen_operations),
    }


def main(argv: list[str] | None = None) -> int:
    if not (sys.flags.isolated and sys.flags.no_site):
        print(
            "domain_pack_verification=refused reason=python-not-isolated "
            "detail='requires python3 -I -S -B'",
            file=sys.stderr,
        )
        return 126
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    arguments = parser.parse_args(argv)
    try:
        result = verify_repository(arguments.root)
    except (PackVerificationError, OSError, ValueError) as error:
        print(
            "domain_pack_verification=refused detail="
            + (" ".join(str(error).splitlines()) or "verification failed")[:512],
            file=sys.stderr,
        )
        return 1
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
