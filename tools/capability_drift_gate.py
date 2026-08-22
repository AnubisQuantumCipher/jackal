#!/usr/bin/env python3
"""Fail closed on JACKAL capability, package-pin, documentation, or skill drift."""

from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.util
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any

INVENTORY_PATH = Path("release/capability_inventory_v1.json")
PLUGIN_MANIFEST_PATH = Path("plugins/jackel/.codex-plugin/plugin.json")
CODEX_SERVER_PATH = Path("plugins/jackel/mcp/server.py")
PROVISIONER_PATH = Path("plugins/jackel/scripts/provision_runtime.py")
PACKAGE_EVIDENCE_PATH = Path("release/evidence/anubis_program_dogfood_v1.json")
SKILL_PATH = Path("plugins/jackel/skills/jackel/SKILL.md")
DESIGN_PATH = Path("docs/superpowers/specs/2026-08-17-jackel-codex-plugin-design.md")
CURRENT_SURFACES = (
    Path("README.md"),
    Path("GETTING-STARTED.md"),
    Path("PROVENANCE.md"),
    DESIGN_PATH,
    SKILL_PATH,
)
CODEX_PLUGIN_IDENTITY_FILES = (
    ".codex-plugin/plugin.json",
    ".mcp.json",
    "README.md",
    "mcp/server.py",
    "scripts/launch_mcp.zsh",
    "scripts/provision_runtime.py",
    "scripts/verify_plugin.py",
    "skills/jackel/SKILL.md",
)
CODEX_PLUGIN_ROOT = Path("plugins/jackel")
CODEX_PLUGIN_IDENTITY_PATH = CODEX_PLUGIN_ROOT / "PLUGIN_IDENTITY.sha256"

CURRENT_SURFACE_BEGIN = "<!-- JACKAL_CURRENT_SURFACE_V1_BEGIN -->"
CURRENT_SURFACE_END = "<!-- JACKAL_CURRENT_SURFACE_V1_END -->"
TOOL_REFERENCE = re.compile(r"`(jackal_[a-z0-9_]+)`")
STATUS_ASSIGNMENT = re.compile(r"\bstatus\s*(?:=|:)\s*`?([a-z][a-z0-9-]*)")
HEX64 = re.compile(r"[0-9a-f]{64}\Z")

NEUTRAL_METADATA_CLAUSES = (
    "copies the parsed runtime result object into structuredContent unchanged",
    "only adapter-local tool result is status=refused reason=plugin-busy",
)
FORBIDDEN_PROMOTIONAL_CLAIMS = (
    "statuses pass through verbatim",
    "statuses pass through unchanged and never inflate",
    "status inflation is impossible",
)
STALE_CURRENT_DESIGN_CLAIMS = (
    "revision declares 34 tools",
    "runtime's 34-tool `plugin/hermes/tools.json` inventory",
    "runtime is the separately sealed JACKAL v1.7.0 macOS release package",
    "release epoch: `v1.7.0`",
    "asset: `jackal-v1.7.0-macos-arm64.tar.gz`",
    "releases/download/v1.7.0/jackal-v1.7.0-macos-arm64.tar.gz",
    "Application Support/JACKAL/runtimes/v1.7.0/",
    "identify epoch v1.7.0",
    "Verify the fixed v1.7.0 URL, epoch, filename",
    "Using the pinned v1.7.0 runtime",
    "pinned v1.7.0 runtime bytes",
)


class DriftError(RuntimeError):
    def __init__(self, reason: str, detail: str):
        self.reason = reason
        self.detail = detail
        super().__init__(f"reason={reason} detail={detail}")


def refuse(reason: str, detail: str) -> None:
    raise DriftError(reason, detail)


def _read_text(path: Path) -> str:
    if not path.is_file():
        refuse("missing-surface", f"required regular file is absent: {path}")
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError as error:
        refuse("surface-encoding", f"{path} is not UTF-8: {error}")


def render_codex_plugin_identity(root: Path | str) -> bytes:
    root_path = Path(root).resolve()
    plugin_root = root_path / CODEX_PLUGIN_ROOT
    lines: list[str] = []
    for relative in CODEX_PLUGIN_IDENTITY_FILES:
        path = plugin_root / relative
        if not path.is_file() or path.is_symlink():
            refuse("plugin-identity-input", f"not a regular non-symlink file: {path}")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        lines.append(f"{digest}  {relative}\n")
    return "".join(lines).encode("utf-8")


def check_codex_plugin_identity(root: Path | str) -> None:
    root_path = Path(root).resolve()
    path = root_path / CODEX_PLUGIN_IDENTITY_PATH
    if not path.is_file():
        refuse("plugin-identity-drift", f"identity manifest is absent: {path}")
    expected = render_codex_plugin_identity(root_path)
    actual = path.read_bytes()
    if actual != expected:
        refuse(
            "plugin-identity-drift",
            f"{CODEX_PLUGIN_IDENTITY_PATH} actual={hashlib.sha256(actual).hexdigest()} "
            f"generated={hashlib.sha256(expected).hexdigest()}",
        )


def _write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o644)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _load_json(path: Path) -> dict[str, Any]:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                refuse("duplicate-json-key", f"{path} repeats key {key!r}")
            result[key] = value
        return result

    try:
        value = json.loads(_read_text(path), object_pairs_hook=reject_duplicates)
    except json.JSONDecodeError as error:
        refuse("invalid-json", f"{path}: {error}")
    if not isinstance(value, dict):
        refuse("invalid-json", f"{path} top level is not an object")
    return value


def _load_inventory_module(root: Path):
    path = root / "tools/capability_inventory.py"
    spec = importlib.util.spec_from_file_location("jackal_capability_inventory", path)
    if spec is None or spec.loader is None:
        refuse("inventory-generator", f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as error:
        refuse("inventory-generator", f"cannot execute {path}: {error}")
    return module


def skill_tool_names(markdown: str) -> set[str]:
    return set(TOOL_REFERENCE.findall(markdown))


def _python_constants(path: Path, required: set[str]) -> dict[str, object]:
    try:
        tree = ast.parse(_read_text(path), filename=str(path))
    except SyntaxError as error:
        refuse("python-parse", f"{path}: {error}")
    values: dict[str, object] = {}
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        value_node = node.value
        for target in targets:
            if not isinstance(target, ast.Name) or target.id not in required:
                continue
            if target.id in values:
                refuse("python-constant", f"{path} repeats {target.id}")
            try:
                values[target.id] = ast.literal_eval(value_node)
            except (ValueError, TypeError) as error:
                refuse("python-constant", f"{path} {target.id} is not literal: {error}")
    missing = sorted(required - set(values))
    if missing:
        refuse("python-constant", f"{path} lacks constants {missing}")
    return values


def _current_surface_block(path: Path) -> str:
    text = _read_text(path)
    if text.count(CURRENT_SURFACE_BEGIN) != 1 or text.count(CURRENT_SURFACE_END) != 1:
        refuse("current-surface-marker", f"{path} must contain one current-surface block")
    start = text.index(CURRENT_SURFACE_BEGIN) + len(CURRENT_SURFACE_BEGIN)
    end = text.index(CURRENT_SURFACE_END)
    if end <= start:
        refuse("current-surface-marker", f"{path} current-surface markers are reversed")
    block = text[start:end].strip()
    if not block:
        refuse("current-surface-marker", f"{path} current-surface block is empty")
    return block


def _verify_package_pin(root: Path, version: str) -> dict[str, object]:
    names = {
        "EPOCH",
        "ASSET",
        "URL",
        "PACKAGE_SIZE",
        "PACKAGE_SHA256",
        "SHA256SUMS_SHA256",
    }
    constants = _python_constants(root / PROVISIONER_PATH, names)
    evidence = _load_json(root / PACKAGE_EVIDENCE_PATH)
    package = evidence.get("package")
    if not isinstance(package, dict):
        refuse("package-pin-mismatch", "dogfood evidence lacks package object")
    expected = {
        "EPOCH": version,
        "ASSET": package.get("basename"),
        "URL": (
            "https://github.com/AnubisQuantumCipher/jackal/releases/download/"
            f"{version}/{package.get('basename')}"
        ),
        "PACKAGE_SIZE": package.get("bytes"),
        "PACKAGE_SHA256": package.get("sha256"),
        "SHA256SUMS_SHA256": package.get("sha256sums_root"),
    }
    if evidence.get("release_candidate") != version:
        refuse(
            "package-pin-mismatch",
            f"dogfood release_candidate={evidence.get('release_candidate')!r} expected={version!r}",
        )
    for name, expected_value in expected.items():
        if constants[name] != expected_value:
            refuse(
                "package-pin-mismatch",
                f"{name} provisioner={constants[name]!r} evidence={expected_value!r}",
            )
    for name in ("PACKAGE_SHA256", "SHA256SUMS_SHA256"):
        if not isinstance(constants[name], str) or HEX64.fullmatch(constants[name]) is None:
            refuse("package-pin-mismatch", f"{name} is not lowercase SHA-256")
    return constants


def _verify_codex_adapter(root: Path, expected_count: int) -> int:
    server_path = root / CODEX_SERVER_PATH
    constants = _python_constants(server_path, {"EXPECTED_TOOL_COUNT"})
    observed = constants["EXPECTED_TOOL_COUNT"]
    if observed != expected_count:
        refuse(
            "codex-tool-count",
            f"wrapper EXPECTED_TOOL_COUNT={observed!r} inventory={expected_count}",
        )
    source = _read_text(server_path)
    for required in (
        '"structuredContent": copy.deepcopy(value)',
        'return backend_result({"status": "refused", "reason": "plugin-busy"})',
    ):
        if required not in source:
            refuse("adapter-mechanism", f"Codex adapter lacks {required!r}")
    return int(observed)


def _verify_plugin_metadata(
    root: Path, expected_count: int, status_vocabulary: set[str]
) -> str:
    manifest = _load_json(root / PLUGIN_MANIFEST_PATH)
    interface = manifest.get("interface")
    if not isinstance(interface, dict):
        refuse("plugin-metadata", "plugin interface is not an object")
    description = interface.get("longDescription")
    if not isinstance(description, str):
        refuse("plugin-metadata", "plugin longDescription is not a string")
    if f"{expected_count}-tool" not in description:
        refuse(
            "current-tool-count",
            f"plugin longDescription does not state {expected_count}-tool",
        )
    if "v1.7.3 candidate runtime" not in description:
        refuse("current-release-state", "plugin metadata does not identify candidate state")
    for clause in NEUTRAL_METADATA_CLAUSES:
        if clause not in description:
            refuse("adapter-metadata", f"plugin metadata lacks mechanism clause {clause!r}")
    lowered = description.lower()
    for forbidden in FORBIDDEN_PROMOTIONAL_CLAIMS:
        if forbidden in lowered:
            refuse("promotional-metadata", f"plugin metadata contains {forbidden!r}")
    missing_statuses = sorted(
        status for status in status_vocabulary
        if re.search(rf"(?<![a-z0-9-]){re.escape(status)}(?![a-z0-9-])", description) is None
    )
    if missing_statuses:
        refuse("status-vocabulary", f"plugin metadata omits {missing_statuses}")
    return description


def _verify_status_assignments(texts: list[tuple[Path, str]], allowed: set[str]) -> None:
    for path, text in texts:
        for status in STATUS_ASSIGNMENT.findall(text):
            if status not in allowed:
                refuse("status-vocabulary", f"{path} uses unknown status {status!r}")


def _verify_current_surfaces(root: Path, expected_count: int) -> list[tuple[Path, str]]:
    design = _read_text(root / DESIGN_PATH)
    for stale in STALE_CURRENT_DESIGN_CLAIMS:
        if stale in design:
            reason = "current-tool-count" if "34 tool" in stale or "34-tool" in stale else "stale-current-pin"
            refuse(reason, f"{DESIGN_PATH} contains stale current claim {stale!r}")

    blocks: list[tuple[Path, str]] = []
    for relative in CURRENT_SURFACES:
        block = _current_surface_block(root / relative)
        if f"{expected_count}-tool" not in block:
            refuse(
                "current-tool-count",
                f"{relative} current block does not state {expected_count}-tool",
            )
        if "v1.7.3-candidate" not in block:
            refuse(
                "current-release-state",
                f"{relative} current block does not state v1.7.3-candidate",
            )
        if "release/capability_inventory_v1.json" not in block:
            refuse(
                "current-inventory-link",
                f"{relative} current block does not name the canonical inventory",
            )
        blocks.append((relative, block))
    return blocks


def verify_surface(root: Path | str) -> dict[str, object]:
    root_path = Path(root).resolve()
    inventory_document = _load_json(root_path / INVENTORY_PATH)
    expected_count = inventory_document.get("tool_count")
    unique_count = inventory_document.get("unique_tool_count")
    records = inventory_document.get("tools")
    release = inventory_document.get("release")
    vocabulary = inventory_document.get("status_vocabulary")
    if (
        not isinstance(expected_count, int)
        or isinstance(expected_count, bool)
        or expected_count != 41
        or unique_count != expected_count
        or not isinstance(records, list)
        or len(records) != expected_count
        or not isinstance(release, dict)
        or release.get("state") != "v1.7.3-candidate"
        or release.get("version") != "v1.7.3"
        or not isinstance(vocabulary, list)
        or not all(isinstance(value, str) for value in vocabulary)
    ):
        refuse("inventory-contract", "committed inventory summary is malformed or stale")
    names = [row.get("name") for row in records if isinstance(row, dict)]
    if len(names) != expected_count or len(set(names)) != expected_count:
        refuse("inventory-contract", "inventory tool names are missing or duplicated")
    known_names = set(names)
    status_vocabulary = set(vocabulary)

    package = _verify_package_pin(root_path, str(release["version"]))
    codex_count = _verify_codex_adapter(root_path, expected_count)
    blocks = _verify_current_surfaces(root_path, expected_count)
    description = _verify_plugin_metadata(root_path, expected_count, status_vocabulary)

    skill_text = _read_text(root_path / SKILL_PATH)
    unknown_skill_names = sorted(skill_tool_names(skill_text) - known_names)
    if unknown_skill_names:
        refuse("unknown-skill-tool", f"Codex skill references {unknown_skill_names}")

    _verify_status_assignments(
        [*blocks, (PLUGIN_MANIFEST_PATH, description), (SKILL_PATH, skill_text)],
        status_vocabulary,
    )

    inventory_module = _load_inventory_module(root_path)
    try:
        inventory_module.check_committed(root_path)
    except Exception as error:
        refuse("inventory-artifact-drift", str(error))
    check_codex_plugin_identity(root_path)

    return {
        "tool_count": expected_count,
        "unique_tool_count": unique_count,
        "codex_tool_count": codex_count,
        "package_epoch": package["EPOCH"],
        "package_sha256": package["PACKAGE_SHA256"],
        "skill_tool_references": len(skill_tool_names(skill_text)),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--write-plugin-identity",
        action="store_true",
        help="regenerate the Codex wrapper identity from its fixed file roster",
    )
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args(argv)
    try:
        if args.write_plugin_identity:
            rendered = render_codex_plugin_identity(args.root)
            _write_atomic(args.root.resolve() / CODEX_PLUGIN_IDENTITY_PATH, rendered)
            print(
                "CODEX_PLUGIN_IDENTITY_WRITTEN "
                f"files={len(CODEX_PLUGIN_IDENTITY_FILES)} "
                f"sha256={hashlib.sha256(rendered).hexdigest()}"
            )
            return 0
        result = verify_surface(args.root)
    except DriftError as error:
        print(
            f"CAPABILITY_DRIFT_REFUSED reason={error.reason} detail={error.detail}",
            file=sys.stderr,
        )
        return 1
    print(
        "CAPABILITY_DRIFT_PASS "
        f"tools={result['tool_count']} unique={result['unique_tool_count']} "
        f"codex={result['codex_tool_count']} package={result['package_epoch']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
