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
import select
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
EXPECTED_TOOL_COUNT = 34

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
        except OSError:
            continue
        if not stat.S_ISDIR(info.st_mode) or candidate.is_symlink():
            continue
        if _manifest_name_version(candidate / ".codex-plugin" / "plugin.json") \
                != source_name_version:
            continue
        try:
            cache_manifest = identity._read_regular_file_nofollow(
                candidate / "PLUGIN_IDENTITY.sha256", "cache identity manifest"
            )
            if cache_manifest != trusted_bytes:
                continue
            verify_wrapper(
                candidate, trusted_manifest=trusted_manifest,
                expected_aggregate=expected_aggregate,
            )
        except (identity.ManifestError, AcceptanceError):
            continue
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


def build_codex_install_plan(
    *, codex_home: Path | str, repository_root: Path | str,
    codex_binary: Path | str,
) -> CodexInstallPlan:
    isolated = Path(codex_home).absolute()
    actual = (Path.home() / ".codex").absolute()
    if isolated == actual:
        raise AcceptanceError("refusing to target the actual CODEX_HOME")
    repository = Path(repository_root).absolute()
    if not repository.is_dir():
        raise AcceptanceError("repository root is not a directory")
    binary = str(codex_binary)
    commands = (
        (binary, "plugin", "marketplace", "add", str(repository), "--json"),
        (binary, "plugin", "add", f"{PLUGIN}@{MARKETPLACE}", "--json"),
        (binary, "plugin", "list", "--available", "--json"),
    )
    environment = dict(os.environ)
    environment["CODEX_HOME"] = str(isolated)
    return CodexInstallPlan(commands=commands, environment=environment)


def execute_codex_install(
    plan: CodexInstallPlan,
    *, runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> tuple[dict[str, Any], ...]:
    results: list[dict[str, Any]] = []
    for command in plan.commands:
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
    if len(expected) != EXPECTED_TOOL_COUNT or len(discovered) != EXPECTED_TOOL_COUNT \
            or len(set(discovered)) != EXPECTED_TOOL_COUNT or discovered != expected:
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


def installed_mcp_client(
    installed_root: Path | str, environment: Mapping[str, str],
) -> MCPClient:
    """Start exactly the installed plugin's declared MCP command."""
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


def direct_backend_call(
    runtime_root: Path | str, tool: str, arguments: dict[str, Any],
    *, timeout: float = 3600,
) -> dict[str, Any]:
    runtime = Path(runtime_root)
    launcher = runtime / "plugin" / "hermes" / "jackal_hermes"
    completed = subprocess.run(
        [str(launcher), "call", tool, canonical_bytes(arguments).decode("utf-8")],
        cwd=runtime, capture_output=True, text=True, check=False, timeout=timeout,
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
            "jackal_integrate_bound_cert", "jackal_claim",
            "jackal_verify_bundle", "jackal_verify_receipt",
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


def _live(runtime_root: Path, codex_binary: Path) -> dict[str, Any]:
    source_aggregate = verify_wrapper(PLUGIN_ROOT)
    verify_runtime(runtime_root)
    runtime_document = load_runtime_document(runtime_root)
    with tempfile.TemporaryDirectory(prefix="jackel-codex-live-") as directory:
        codex_home = Path(directory)
        plan = build_codex_install_plan(
            codex_home=codex_home, repository_root=REPOSITORY_ROOT,
            codex_binary=codex_binary,
        )
        execute_codex_install(plan)
        installed = locate_cache_copy(
            codex_home, PLUGIN_ROOT, expected_aggregate=source_aggregate,
        )
        environment = dict(os.environ)
        environment["CODEX_HOME"] = str(codex_home)
        environment["JACKAL_HOME"] = str(runtime_root)
        with installed_mcp_client(installed, environment) as client:
            report = run_acceptance(
                client=client, runtime_document=runtime_document,
                direct_call=lambda tool, arguments: direct_backend_call(
                    runtime_root, tool, arguments
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
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--runtime-root", type=Path)
    parser.add_argument("--codex-binary", type=Path, default=Path("codex"))
    arguments = parser.parse_args(argv)
    try:
        if arguments.live:
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
