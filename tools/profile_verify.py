#!/usr/bin/env python3
"""Fail-closed verifier for JACKAL agent profiles.

A profile declares the tool *names* an agent host may expose. It grants no
capability and computes nothing: the engine remains the only authority for
calculation, routing, assurance, and refusal. This verifier therefore only
checks bytes, identities and set relations. It never rewrites a profile and
never repairs one.

Checks, each with a stable refusal name:

  schema-violation           document violates plugin/hermes/schemas/jackal_agent_profile.schema.json
  schema-unsupported-keyword the schema file uses a keyword this validator does not implement
  profile-id-mismatch        profile_id disagrees with the file stem
  immutable-false            a shipped profile declares immutable=false
  digest-mismatch            profile_digest_sha256 is not the canonical digest of the document
  unknown-tool               a listed tool does not exist in plugin/hermes/tools.json
  tool-order                 tools are not in tools.json declaration order
  core-arity                 core does not expose exactly three front doors
  full-incomplete            full is not exactly the tools.json tool set
  not-nested                 core is not a subset of formal, or formal not a subset of full

Usage:
  python3 tools/profile_verify.py [--root PATH] [--json]
Exit status: 0 all profiles verified, 1 refusal, 2 usage error.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

PROFILE_DIR = Path("plugin") / "hermes" / "profiles"
SCHEMA_PATH = Path("plugin") / "hermes" / "schemas" / "jackal_agent_profile.schema.json"
TOOLS_PATH = Path("plugin") / "hermes" / "tools.json"

PROFILE_IDS = ("core", "formal", "full")
DIGEST_KEY = "profile_digest_sha256"
CORE_TOOL_COUNT = 3

MAX_PROFILE_BYTES = 262_144
MAX_SCHEMA_BYTES = 262_144
MAX_TOOLS_BYTES = 4_194_304
MAX_JSON_DEPTH = 32
MAX_JSON_NODES = 262_144

# JSON Schema keywords this validator implements. Anything else in the schema
# file is a refusal, because silently ignoring a constraint would turn the
# schema into decoration.
SUPPORTED_KEYWORDS = frozenset(
    {
        "type",
        "const",
        "enum",
        "pattern",
        "minLength",
        "maxLength",
        "required",
        "properties",
        "additionalProperties",
        "items",
        "minItems",
        "maxItems",
        "uniqueItems",
    }
)
# Annotation-only keywords: carry no constraint, safe to ignore.
ANNOTATION_KEYWORDS = frozenset({"$schema", "$id", "title", "description", "$comment"})

JSON_TYPES: dict[str, tuple[type, ...]] = {
    "object": (dict,),
    "array": (list,),
    "string": (str,),
    "boolean": (bool,),
    "null": (type(None),),
}


class ProfileVerificationError(RuntimeError):
    """Stable fail-closed verification refusal.

    ``reason`` is the machine-stable refusal name; ``str(error)`` is the full
    ``reason=... profile=... path=... detail=...`` line.
    """

    def __init__(self, reason: str, detail: str, profile: str = "-", path: str = "$"):
        self.reason = reason
        self.detail = detail
        self.profile = profile
        self.path = path
        super().__init__(
            f"reason={reason} profile={profile} path={path} detail={detail}"
        )


def refuse(reason: str, detail: str, profile: str = "-", path: str = "$") -> None:
    raise ProfileVerificationError(reason, detail, profile, path)


def canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def profile_digest(document: dict[str, Any]) -> str:
    """SHA-256 over the canonical JSON of ``document`` minus its digest field."""
    payload = {key: value for key, value in document.items() if key != DIGEST_KEY}
    return hashlib.sha256(canonical_bytes(payload)).hexdigest()


def validate_json_structure(value: object, context: str) -> None:
    stack: list[tuple[object, int]] = [(value, 0)]
    nodes = 0
    while stack:
        current, depth = stack.pop()
        nodes += 1
        if depth > MAX_JSON_DEPTH:
            refuse("json-too-deep", f"{context} exceeds depth {MAX_JSON_DEPTH}")
        if nodes > MAX_JSON_NODES:
            refuse("json-too-large", f"{context} exceeds {MAX_JSON_NODES} nodes")
        if isinstance(current, dict):
            for key, item in current.items():
                if not isinstance(key, str):
                    refuse("json-non-string-key", f"{context} has a non-string key")
                stack.append((item, depth + 1))
        elif isinstance(current, list):
            stack.extend((item, depth + 1) for item in current)


def load_json(path: Path, maximum: int, context: str) -> dict[str, Any]:
    if not path.is_file():
        refuse("missing-file", f"{context} is not a regular file: {path}")
    size = path.stat().st_size
    if size > maximum:
        refuse("oversize-file", f"{context} is {size} bytes, limit {maximum}")
    raw = path.read_bytes()
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        refuse("invalid-json", f"{context} is not valid UTF-8 JSON: {error}")
    if not isinstance(value, dict):
        refuse("invalid-json", f"{context} top level is not a JSON object")
    validate_json_structure(value, context)
    return value


# --------------------------------------------------------------------------
# Dependency-free JSON Schema subset validator.
# --------------------------------------------------------------------------


def _assert_schema_supported(schema: dict[str, Any], path: str) -> None:
    for keyword in schema:
        if keyword in ANNOTATION_KEYWORDS or keyword in SUPPORTED_KEYWORDS:
            continue
        refuse(
            "schema-unsupported-keyword",
            f"schema keyword {keyword!r} is not implemented by this validator",
            path=path,
        )


def _same_json_value(left: object, right: object) -> bool:
    """Type-strict equality; refuses Python's True == 1 conflation."""
    if isinstance(left, bool) != isinstance(right, bool):
        return False
    if isinstance(left, dict) and isinstance(right, dict):
        return left.keys() == right.keys() and all(
            _same_json_value(left[key], right[key]) for key in left
        )
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(
            _same_json_value(a, b) for a, b in zip(left, right)
        )
    return type(left) is type(right) and left == right


def _violate(profile: str, path: str, rule: str, detail: str) -> None:
    refuse("schema-violation", f"rule={rule} {detail}", profile=profile, path=path)


def validate_against_schema(
    value: object, schema: dict[str, Any], profile: str, path: str = "$"
) -> None:
    """Validate ``value`` against the supported JSON Schema subset."""
    if not isinstance(schema, dict):
        refuse("schema-unsupported-keyword", "schema node is not an object", path=path)
    _assert_schema_supported(schema, path)

    if "type" in schema:
        declared = schema["type"]
        if not isinstance(declared, str) or declared not in JSON_TYPES:
            refuse(
                "schema-unsupported-keyword",
                f"unsupported type declaration {declared!r}",
                path=path,
            )
        allowed = JSON_TYPES[declared]
        matched = isinstance(value, allowed) and (
            declared == "boolean" or not isinstance(value, bool)
        )
        if not matched:
            _violate(profile, path, "type", f"expected {declared}")

    if "const" in schema and not _same_json_value(value, schema["const"]):
        _violate(profile, path, "const", f"expected {schema['const']!r}")

    if "enum" in schema:
        options = schema["enum"]
        if not isinstance(options, list) or not options:
            refuse("schema-unsupported-keyword", "enum must be a non-empty array", path=path)
        if not any(_same_json_value(value, option) for option in options):
            _violate(profile, path, "enum", f"value not in {options!r}")

    if isinstance(value, str) and not isinstance(value, bool):
        if "pattern" in schema:
            pattern = schema["pattern"]
            if not isinstance(pattern, str):
                refuse("schema-unsupported-keyword", "pattern must be a string", path=path)
            if re.compile(pattern).search(value) is None:
                _violate(profile, path, "pattern", f"value does not match {pattern}")
        if "minLength" in schema and len(value) < schema["minLength"]:
            _violate(
                profile, path, "minLength", f"length {len(value)} < {schema['minLength']}"
            )
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            _violate(
                profile, path, "maxLength", f"length {len(value)} > {schema['maxLength']}"
            )

    if isinstance(value, dict):
        required = schema.get("required", [])
        if not isinstance(required, list):
            refuse("schema-unsupported-keyword", "required must be an array", path=path)
        for key in required:
            if key not in value:
                _violate(profile, path, "required", f"missing property {key!r}")
        properties = schema.get("properties", {})
        if not isinstance(properties, dict):
            refuse("schema-unsupported-keyword", "properties must be an object", path=path)
        if schema.get("additionalProperties") is False:
            for key in value:
                if key not in properties:
                    _violate(
                        profile,
                        path,
                        "additionalProperties",
                        f"unknown property {key!r}",
                    )
        elif "additionalProperties" in schema:
            refuse(
                "schema-unsupported-keyword",
                "only additionalProperties=false is implemented",
                path=path,
            )
        for key, subschema in properties.items():
            if key in value:
                validate_against_schema(value[key], subschema, profile, f"{path}.{key}")

    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            _violate(profile, path, "minItems", f"{len(value)} < {schema['minItems']}")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            _violate(profile, path, "maxItems", f"{len(value)} > {schema['maxItems']}")
        if schema.get("uniqueItems") is True:
            for index, item in enumerate(value):
                if any(_same_json_value(item, other) for other in value[:index]):
                    _violate(
                        profile, f"{path}[{index}]", "uniqueItems", f"duplicate {item!r}"
                    )
        if "items" in schema:
            for index, item in enumerate(value):
                validate_against_schema(
                    item, schema["items"], profile, f"{path}[{index}]"
                )


# --------------------------------------------------------------------------
# Cross-file profile checks.
# --------------------------------------------------------------------------


def declared_tool_names(root: Path) -> list[str]:
    document = load_json(root / TOOLS_PATH, MAX_TOOLS_BYTES, "tools.json")
    tools = document.get("tools")
    if not isinstance(tools, list) or not tools:
        refuse("tools-malformed", "tools.json has no tools array")
    names: list[str] = []
    for index, tool in enumerate(tools):
        if not isinstance(tool, dict):
            refuse("tools-malformed", f"tools.json tools[{index}] is not an object")
        name = tool.get("name")
        if not isinstance(name, str) or not name:
            refuse("tools-malformed", f"tools.json tools[{index}] has no name")
        if name in names:
            refuse("tools-malformed", f"tools.json declares {name!r} twice")
        names.append(name)
    return names


def verify_profile(
    root: Path,
    profile_id: str,
    schema: dict[str, Any],
    declared: list[str],
) -> dict[str, Any]:
    path = root / PROFILE_DIR / f"{profile_id}.json"
    document = load_json(path, MAX_PROFILE_BYTES, f"profile {profile_id}")

    validate_against_schema(document, schema, profile_id)

    if document["profile_id"] != profile_id:
        refuse(
            "profile-id-mismatch",
            f"file stem {profile_id!r} declares profile_id {document['profile_id']!r}",
            profile=profile_id,
            path="$.profile_id",
        )

    if document["immutable"] is not True:
        refuse(
            "immutable-false",
            "shipped profiles must declare immutable=true",
            profile=profile_id,
            path="$.immutable",
        )

    expected = profile_digest(document)
    if document[DIGEST_KEY] != expected:
        refuse(
            "digest-mismatch",
            f"declared {document[DIGEST_KEY]} recomputed {expected}",
            profile=profile_id,
            path=f"$.{DIGEST_KEY}",
        )

    tools: list[str] = document["tools"]
    rank = {name: index for index, name in enumerate(declared)}
    for index, name in enumerate(tools):
        if name not in rank:
            refuse(
                "unknown-tool",
                f"{name!r} is not declared in plugin/hermes/tools.json",
                profile=profile_id,
                path=f"$.tools[{index}]",
            )
    ordered = sorted(tools, key=lambda name: rank[name])
    if tools != ordered:
        refuse(
            "tool-order",
            "tools are not in tools.json declaration order",
            profile=profile_id,
            path="$.tools",
        )

    return {
        "profile_id": profile_id,
        "tool_count": len(tools),
        "tools": tools,
        "profile_digest_sha256": expected,
        "description_bytes": len(document["description"].encode("utf-8")),
    }


def verify_repository(root: Path | str) -> dict[str, Any]:
    root = Path(root)
    schema = load_json(root / SCHEMA_PATH, MAX_SCHEMA_BYTES, "profile schema")
    declared = declared_tool_names(root)

    results: dict[str, dict[str, Any]] = {}
    for profile_id in PROFILE_IDS:
        results[profile_id] = verify_profile(root, profile_id, schema, declared)

    core = results["core"]["tools"]
    formal = results["formal"]["tools"]
    full = results["full"]["tools"]

    if len(core) != CORE_TOOL_COUNT:
        refuse(
            "core-arity",
            f"core exposes {len(core)} tools, contract requires exactly {CORE_TOOL_COUNT}",
            profile="core",
            path="$.tools",
        )

    if set(full) != set(declared):
        missing = sorted(set(declared) - set(full))
        extra = sorted(set(full) - set(declared))
        refuse(
            "full-incomplete",
            f"full must equal the tools.json set; missing={missing} extra={extra}",
            profile="full",
            path="$.tools",
        )

    if not set(core) <= set(formal):
        refuse(
            "not-nested",
            f"core is not a subset of formal; outside={sorted(set(core) - set(formal))}",
            profile="core",
            path="$.tools",
        )
    if not set(formal) <= set(full):
        refuse(
            "not-nested",
            f"formal is not a subset of full; outside={sorted(set(formal) - set(full))}",
            profile="formal",
            path="$.tools",
        )

    return {
        "profile_verification": "verified",
        "schema": schema.get("$id", str(SCHEMA_PATH)),
        "tools_declared": len(declared),
        "profiles": {
            profile_id: {
                "tool_count": result["tool_count"],
                "profile_digest_sha256": result["profile_digest_sha256"],
            }
            for profile_id, result in results.items()
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify JACKAL agent profiles.")
    parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    parser.add_argument("--json", action="store_true", help="emit the machine summary")
    arguments = parser.parse_args(argv)

    try:
        result = verify_repository(arguments.root)
    except ProfileVerificationError as error:
        print(f"profile_verification=refused {error}", file=sys.stderr)
        return 1
    except (OSError, ValueError, re.error) as error:
        print(
            f"profile_verification=refused reason=verifier-error detail={error}",
            file=sys.stderr,
        )
        return 1

    if arguments.json:
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    else:
        for profile_id in PROFILE_IDS:
            row = result["profiles"][profile_id]
            print(
                f"profile={profile_id} tools={row['tool_count']} "
                f"digest={row['profile_digest_sha256']} OK"
            )
        print(
            f"profile_verification=verified tools_declared={result['tools_declared']} "
            "nesting=core<=formal<=full OK"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
