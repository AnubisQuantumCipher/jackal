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
from typing import Any, NoReturn

INVENTORY_PATH = Path("release/capability_inventory_v1.json")
PLUGIN_MANIFEST_PATH = Path("plugins/jackel/.codex-plugin/plugin.json")
CODEX_SERVER_PATH = Path("plugins/jackel/mcp/server.py")
PROVISIONER_PATH = Path("plugins/jackel/scripts/provision_runtime.py")
PACKAGE_EVIDENCE_PATH = Path("release/evidence/package_alignment_v173_release.json")
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
    "assets/jackal-linked-evidence-workspace.png",
    "assets/jackal-thoth-hellgate-graph.png",
    "mcp/advanced.py",
    "mcp/certificates/README.md",
    "mcp/certificates/hellgate_v1.json.zlib",
    "mcp/hellgate_verify.py",
    "mcp/measurement.py",
    "mcp/server.py",
    "mcp/stem.py",
    "scripts/launch_mcp.sh",
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
TOOL_NAME = re.compile(r"jackal_[a-z0-9_]+\Z")
STATUS_ASSIGNMENT = re.compile(r"\bstatus\s*(?:=|:)\s*`?([a-z][a-z0-9-]*)")
HEX64 = re.compile(r"[0-9a-f]{64}\Z")

NEUTRAL_METADATA_CLAUSES = (
    "copies each parsed sealed-runtime result object into structuredContent unchanged",
    "removes only the identity-validated _mcp_content transport envelope",
    "only transport-local refusal is status=refused reason=plugin-busy",
)
WRAPPER_ONLY_STATUSES = frozenset({"exact-given"})
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


def refuse(reason: str, detail: str) -> NoReturn:
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


def _python_frozenset_constants(
    path: Path, required: set[str]
) -> dict[str, frozenset[str]]:
    try:
        tree = ast.parse(_read_text(path), filename=str(path))
    except SyntaxError as error:
        refuse("python-parse", f"{path}: {error}")
    values: dict[str, frozenset[str]] = {}
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        for target in targets:
            if not isinstance(target, ast.Name) or target.id not in required:
                continue
            if target.id in values:
                refuse("python-constant", f"{path} repeats {target.id}")
            call = node.value
            if (
                not isinstance(call, ast.Call)
                or not isinstance(call.func, ast.Name)
                or call.func.id != "frozenset"
                or len(call.args) != 1
                or call.keywords
                or not isinstance(call.args[0], (ast.Set, ast.List, ast.Tuple))
            ):
                refuse(
                    "python-constant",
                    f"{path} {target.id} is not a literal frozenset",
                )
            items = call.args[0].elts
            strings = [
                item.value
                for item in items
                if isinstance(item, ast.Constant) and isinstance(item.value, str)
            ]
            if len(strings) != len(items) or len(strings) != len(set(strings)):
                refuse(
                    "python-constant",
                    f"{path} {target.id} has non-string or duplicate members",
                )
            invalid = sorted(value for value in strings if TOOL_NAME.fullmatch(value) is None)
            if invalid:
                refuse(
                    "python-constant",
                    f"{path} {target.id} has invalid tool names {invalid}",
                )
            values[target.id] = frozenset(strings)
    missing = sorted(required - set(values))
    if missing:
        refuse("python-constant", f"{path} lacks constants {missing}")
    return values


def _verify_backend_result_mechanism(path: Path, source: str) -> None:
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as error:
        refuse("python-parse", f"{path}: {error}")
    functions = [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "backend_result"
    ]
    if len(functions) != 1:
        refuse("adapter-mechanism", "Codex adapter must define backend_result once")
    function = functions[0]

    def assigned_name(node: ast.stmt, name: str) -> ast.expr | None:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            return None
        target = node.targets[0]
        return node.value if isinstance(target, ast.Name) and target.id == name else None

    deep_copy_indices: list[int] = []
    pop_indices: list[int] = []
    return_indices: list[int] = []
    for index, node in enumerate(function.body):
        structured_value = assigned_name(node, "structured")
        if (
            isinstance(structured_value, ast.Call)
            and isinstance(structured_value.func, ast.Attribute)
            and isinstance(structured_value.func.value, ast.Name)
            and structured_value.func.value.id == "copy"
            and structured_value.func.attr == "deepcopy"
            and len(structured_value.args) == 1
            and isinstance(structured_value.args[0], ast.Name)
            and structured_value.args[0].id == "value"
            and not structured_value.keywords
        ):
            deep_copy_indices.append(index)

        content_value = assigned_name(node, "raw_content")
        if (
            isinstance(content_value, ast.Call)
            and isinstance(content_value.func, ast.Attribute)
            and isinstance(content_value.func.value, ast.Name)
            and content_value.func.value.id == "structured"
            and content_value.func.attr == "pop"
            and len(content_value.args) == 2
            and isinstance(content_value.args[0], ast.Constant)
            and content_value.args[0].value == "_mcp_content"
            and isinstance(content_value.args[1], ast.Constant)
            and content_value.args[1].value is None
            and not content_value.keywords
        ):
            pop_indices.append(index)

        if isinstance(node, ast.Return) and isinstance(node.value, ast.Dict):
            pairs = {
                key.value: value
                for key, value in zip(node.value.keys, node.value.values)
                if isinstance(key, ast.Constant) and isinstance(key.value, str)
            }
            if (
                set(pairs) == {"content", "structuredContent"}
                and isinstance(pairs["content"], ast.Name)
                and pairs["content"].id == "content"
                and isinstance(pairs["structuredContent"], ast.Name)
                and pairs["structuredContent"].id == "structured"
            ):
                return_indices.append(index)
    if (
        len(deep_copy_indices) != 1
        or len(pop_indices) != 1
        or len(return_indices) != 1
        or not deep_copy_indices[0] < pop_indices[0] < return_indices[0]
    ):
        refuse(
            "adapter-mechanism",
            "backend_result must deep-copy the result, extract only _mcp_content, "
            "and return the remaining object as structuredContent",
        )


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
        refuse("package-pin-mismatch", "package alignment receipt lacks package object")
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
            f"alignment release_candidate={evidence.get('release_candidate')!r} expected={version!r}",
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


def _verify_codex_adapter(
    root: Path, expected_count: int, runtime_names: set[str]
) -> tuple[int, set[str]]:
    server_path = root / CODEX_SERVER_PATH
    constants = _python_constants(
        server_path,
        {
            "EXPECTED_TOOL_COUNT",
            "EXPECTED_MEASUREMENT_TOOL_COUNT",
            "EXPECTED_ADVANCED_TOOL_COUNT",
            "EXPECTED_STEM_TOOL_COUNT",
            "EXPECTED_UNIFIED_TOOL_COUNT",
        },
    )
    observed = constants["EXPECTED_TOOL_COUNT"]
    if observed != expected_count:
        refuse(
            "codex-tool-count",
            f"wrapper EXPECTED_TOOL_COUNT={observed!r} inventory={expected_count}",
        )
    groups = _python_frozenset_constants(
        server_path,
        {"MEASUREMENT_TOOL_NAMES", "ADVANCED_TOOL_NAMES", "STEM_TOOL_NAMES"},
    )
    count_bindings = {
        "MEASUREMENT_TOOL_NAMES": "EXPECTED_MEASUREMENT_TOOL_COUNT",
        "ADVANCED_TOOL_NAMES": "EXPECTED_ADVANCED_TOOL_COUNT",
        "STEM_TOOL_NAMES": "EXPECTED_STEM_TOOL_COUNT",
    }
    additive_names: set[str] = set()
    for group_name, count_name in count_bindings.items():
        names = groups[group_name]
        if len(names) != constants[count_name]:
            refuse(
                "codex-tool-count",
                f"{group_name} has {len(names)} names but {count_name}="
                f"{constants[count_name]!r}",
            )
        overlap = sorted(additive_names & names)
        if overlap:
            refuse("codex-tool-count", f"additive tool groups overlap at {overlap}")
        additive_names.update(names)
    runtime_overlap = sorted(runtime_names & additive_names)
    if runtime_overlap:
        refuse("codex-tool-count", f"runtime and additive tools overlap at {runtime_overlap}")
    unified_names = runtime_names | additive_names
    unified_count = constants["EXPECTED_UNIFIED_TOOL_COUNT"]
    if len(unified_names) != unified_count:
        refuse(
            "codex-tool-count",
            f"wrapper EXPECTED_UNIFIED_TOOL_COUNT={unified_count!r} "
            f"but the disjoint roster has {len(unified_names)} names",
        )
    source = _read_text(server_path)
    _verify_backend_result_mechanism(server_path, source)
    busy_refusal = 'return backend_result({"status": "refused", "reason": "plugin-busy"})'
    if busy_refusal not in source:
        refuse("adapter-mechanism", f"Codex adapter lacks {busy_refusal!r}")
    return int(unified_count), additive_names


def _verify_plugin_metadata(
    root: Path,
    expected_count: int,
    unified_count: int,
    status_vocabulary: set[str],
) -> str:
    manifest = _load_json(root / PLUGIN_MANIFEST_PATH)
    interface = manifest.get("interface")
    if not isinstance(interface, dict):
        refuse("plugin-metadata", "plugin interface is not an object")
    description = interface.get("longDescription")
    if not isinstance(description, str):
        refuse("plugin-metadata", "plugin longDescription is not a string")
    if f"sealed {expected_count}-tool" not in description:
        refuse(
            "current-tool-count",
            f"plugin longDescription does not state sealed {expected_count}-tool",
        )
    if f"unified {unified_count}-tool" not in description:
        refuse(
            "current-tool-count",
            f"plugin longDescription does not state unified {unified_count}-tool",
        )
    if "v1.7.3 release runtime" not in description:
        refuse("current-release-state", "plugin metadata does not identify release state")
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
        if "v1.7.3" not in block or "release" not in block:
            refuse(
                "current-release-state",
                f"{relative} current block does not state the v1.7.3 release",
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
        or release.get("state") != "v1.7.3"
        or release.get("version") != "v1.7.3"
        or not isinstance(vocabulary, list)
        or not all(isinstance(value, str) for value in vocabulary)
    ):
        refuse("inventory-contract", "committed inventory summary is malformed or stale")
    names = [row.get("name") for row in records if isinstance(row, dict)]
    if len(names) != expected_count or len(set(names)) != expected_count:
        refuse("inventory-contract", "inventory tool names are missing or duplicated")
    runtime_names = set(names)
    status_vocabulary = set(vocabulary) | set(WRAPPER_ONLY_STATUSES)

    package = _verify_package_pin(root_path, str(release["version"]))
    codex_count, additive_names = _verify_codex_adapter(
        root_path, expected_count, runtime_names
    )
    known_names = runtime_names | additive_names
    blocks = _verify_current_surfaces(root_path, expected_count)
    description = _verify_plugin_metadata(
        root_path, expected_count, codex_count, status_vocabulary
    )

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
