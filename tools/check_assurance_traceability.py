#!/usr/bin/python3 -B
"""Fail closed on JACKAL requirement, claim, or public-surface drift."""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "assurance/requirements.json"
INVENTORY = ROOT / "release/capability_inventory_v1.json"
CODEX_SERVER = ROOT / "plugins/jackel/mcp/server.py"
ID_PATTERN = re.compile(r"^JCK-[A-Z]+-[0-9]{3}$")
GROUP_CONSTANTS = {
    "measurement": "MEASUREMENT_TOOL_NAMES",
    "advanced": "ADVANCED_TOOL_NAMES",
    "stem": "STEM_TOOL_NAMES",
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"FAIL: {message}")


def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        require(key not in result, f"duplicate JSON key: {key}")
        result[key] = value
    return result


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=reject_duplicate_keys,
    )
    require(isinstance(value, dict), f"top level is not an object: {path}")
    return value


def additive_groups() -> dict[str, set[str]]:
    tree = ast.parse(CODEX_SERVER.read_text(encoding="utf-8"), filename=str(CODEX_SERVER))
    wanted = set(GROUP_CONSTANTS.values())
    found: dict[str, set[str]] = {}
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        for target in targets:
            if not isinstance(target, ast.Name) or target.id not in wanted:
                continue
            call = node.value
            require(
                isinstance(call, ast.Call)
                and isinstance(call.func, ast.Name)
                and call.func.id == "frozenset"
                and len(call.args) == 1
                and isinstance(call.args[0], ast.Set),
                f"{target.id} is not a literal frozenset",
            )
            values = {
                item.value
                for item in call.args[0].elts
                if isinstance(item, ast.Constant) and isinstance(item.value, str)
            }
            require(
                len(values) == len(call.args[0].elts),
                f"{target.id} contains a non-string or duplicate",
            )
            found[target.id] = values
    require(set(found) == wanted, "one or more additive public tool groups are missing")
    return {group: found[constant] for group, constant in GROUP_CONSTANTS.items()}


document = read_json(BASELINE)
require(document.get("schema") == "jackal-assurance-requirements-v1", "schema mismatch")
requirements = document.get("requirements")
require(isinstance(requirements, list) and requirements, "requirements list is empty")
by_id: dict[str, dict[str, Any]] = {}

for requirement in requirements:
    require(isinstance(requirement, dict), "requirement is not an object")
    identifier = requirement.get("id")
    require(
        isinstance(identifier, str) and ID_PATTERN.fullmatch(identifier) is not None,
        f"invalid requirement id: {identifier!r}",
    )
    require(identifier not in by_id, f"duplicate requirement id: {identifier}")
    by_id[identifier] = requirement
    shall = requirement.get("shall")
    require(
        isinstance(shall, str) and " shall " in f" {shall.lower()} ",
        f"requirement is not a shall-statement: {identifier}",
    )
    require(requirement.get("status") in {"proved", "tested", "planned"},
            f"invalid requirement status: {identifier}")
    residuals = requirement.get("residuals")
    require(isinstance(residuals, list), f"invalid residuals: {identifier}")
    for relation in ("allocation", "verification"):
        paths = requirement.get(relation)
        require(isinstance(paths, list) and paths, f"{identifier} lacks {relation}")
        for raw_path in paths:
            require(isinstance(raw_path, str) and raw_path, f"invalid path in {identifier}")
            relative = Path(raw_path)
            require(not relative.is_absolute() and ".." not in relative.parts,
                    f"path escapes repository: {raw_path}")
            path = (ROOT / relative).resolve()
            require(path.is_relative_to(ROOT), f"resolved path escapes repository: {raw_path}")
            require(path.is_file() and not path.is_symlink(), f"not a regular file: {raw_path}")
            require(identifier in path.read_text(encoding="utf-8"),
                    f"{identifier} is not cited by {raw_path}")

for claim in document.get("component_claims", []):
    require(claim.get("target") == "SPARK Platinum", "component target is not SPARK Platinum")
    identifiers = claim.get("requirement_ids")
    require(isinstance(identifiers, list) and identifiers, "component claim has no requirements")
    for identifier in identifiers:
        require(identifier in by_id, f"component claim cites unknown requirement: {identifier}")
        requirement = by_id[identifier]
        require(requirement.get("method") == "spark-platinum",
                f"component includes non-SPARK requirement: {identifier}")
        if claim.get("status") == "proved-local":
            require(requirement.get("status") == "proved",
                    f"proved component includes open requirement: {identifier}")
            require(requirement.get("residuals") == [],
                    f"proved component requirement has functional residual: {identifier}")

inventory = read_json(INVENTORY)
tools = inventory.get("tools")
require(isinstance(tools, list) and tools, "capability inventory has no tools")
tool_names = [tool.get("name") for tool in tools if isinstance(tool, dict)]
require(len(tool_names) == len(tools) and len(tool_names) == len(set(tool_names)),
        "sealed tool names are invalid or duplicated")
discovered_families = {
    tool.get("dependency", {}).get("family")
    for tool in tools
    if isinstance(tool, dict) and isinstance(tool.get("dependency"), dict)
}
require(None not in discovered_families, "a sealed tool lacks a dependency family")

closure = document.get("surface_closure")
require(isinstance(closure, dict), "surface closure is absent")
sealed = closure.get("sealed_dependency_families")
additive = closure.get("additive_groups")
require(isinstance(sealed, dict), "sealed family closure is invalid")
require(isinstance(additive, dict), "additive group closure is invalid")
require(set(sealed) == discovered_families,
        f"sealed assurance coverage drift: expected={sorted(discovered_families)} actual={sorted(sealed)}")
groups = additive_groups()
require(set(additive) == set(groups), "additive assurance group coverage drift")
require(all(groups.values()), "an additive public tool group is empty")
require(not (set(tool_names) & set().union(*groups.values())),
        "sealed and additive public tool names overlap")

closed_status = closure.get("closed_status")
all_closed = all(status == closed_status for status in [*sealed.values(), *additive.values()])
all_requirements_proved = all(item.get("status") == "proved" for item in requirements)
product_status = document.get("product_claim", {}).get("status")
if product_status == "proved-universal":
    require(all_closed and all_requirements_proved,
            "whole-product universal claim has open surface or requirements")
else:
    require(product_status == "in-progress", "invalid whole-product claim status")
    require(not all_closed, "all surfaces are closed but product claim was not reviewed")

print("JACKAL_ASSURANCE_TRACEABILITY_PASS")
