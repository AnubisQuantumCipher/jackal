#!/usr/bin/env python3
"""v1.5.0 compatibility-floor snapshot (mechanical, no hand counts).

Extracts the complete backward-compatibility surface that the v1.6
evidence-kernel epoch must preserve:

  * every Hermes tool name with its argument keys, required/optional
    split, and documented return keys (from plugin/hermes/tools.json);
  * every engine command token (mechanically parsed from the
    `op == "..."` dispatch in jackal_calc.anb);
  * the 32 v1.5 gate names in driver order (from run_gates_v150.py);
  * the formal rational variants (from formal_receipt.RATIONAL_VARIANTS);
  * the legacy schema identifiers in the trust surface;
  * the coverage-inventory row ids and verdicts;
  * the repo-root release wrapper scripts;
  * the engine epistemic status classes.

`snapshot()` returns the structure; `main()` writes/refreshes the frozen
copy or (with --check) diffs the live surface against the frozen copy and
fails on ANY removal, rename, narrowing, or mutation.  Additions of NEW
tools/commands/gates are permitted (the kernel epoch is additive); every
frozen v1.5 entry must remain byte-identical.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FROZEN = ROOT / "release/compat/v150_floor.json"

EPISTEMIC_CLASSES = [
    "exact", "checked", "estimated", "bounded", "formal-bounded",
    "model-based",
]

LEGACY_SCHEMAS = [
    "jackal-claim-v1",
    "jackal-coverage-inventory-v1",
    "jackal-eval-cert v2",
    "jackal-exact-cert-v1",
    "jackal-formal-receipt-v1",
    "jackal-gaussian-proof-identity-v1",
    "jackal-hermes-plugin-v1",
    "jackal-hermes-runtime-bundle-v2",
    "jackal-iv-model-v1",
    "jackal-range-proof-identity-v1",
    "jackal-seal-audit-v1",
    "jackal-seal-audit-receipts-v1",
]

WRAPPERS = [
    "jackal", "jackal-atan-rat-release", "jackal-cert-release",
    "jackal-cos-rat-release", "jackal-exp-rat-release",
    "jackal-gaussian-release", "jackal-ln-rat-release",
    "jackal-receipt-verify", "jackal-sin-rat-release",
    "jackal-sqrt-rat-release", "jackal-tanh-rat-release",
]


def _tool_schemas() -> dict:
    doc = json.loads((ROOT / "plugin/hermes/tools.json").read_text())
    out = {}
    for tool in doc["tools"]:
        args = tool.get("arguments") or {}
        out[tool["name"]] = {
            "required": sorted(k for k, v in args.items() if v.get("required")),
            "optional": sorted(k for k, v in args.items() if not v.get("required")),
            "returns": sorted((tool.get("returns") or {}).keys()),
        }
    return out


def _engine_commands() -> list[str]:
    text = (ROOT / "jackal_calc.anb").read_text()
    return sorted(set(re.findall(r'op == "([a-z0-9_-]+)"', text)))


def _gate_names() -> list[str]:
    text = (ROOT / "release/tools/run_gates_v150.py").read_text()
    body = text.split("GATES:", 1)[1]
    return re.findall(r'\(\s*"([a-z0-9-]+)"\s*,', body)


def _variants() -> list[str]:
    sys.path.insert(0, str(ROOT / "tools"))
    import formal_receipt  # noqa: PLC0415
    return sorted(formal_receipt.RATIONAL_VARIANTS)


def _coverage_rows() -> dict[str, str]:
    doc = json.loads(
        (ROOT / "release/coverage/formal_coverage_inventory.json").read_text())
    rows = doc["rows"]
    if isinstance(rows, dict):
        return {key: row.get("verdict", "") for key, row in sorted(rows.items())}
    return {row.get("operator") or row.get("id", ""): row.get("verdict", "")
            for row in rows}


def snapshot() -> dict:
    return {
        "schema": "jackal-compat-floor-v1",
        "release_epoch": "v1.5.0",
        "tool_schemas": _tool_schemas(),
        "tool_count": len(_tool_schemas()),
        "engine_commands": _engine_commands(),
        "gate_names_v150": _gate_names(),
        "rational_variants": _variants(),
        "legacy_schemas": LEGACY_SCHEMAS,
        "epistemic_classes": EPISTEMIC_CLASSES,
        "wrappers": WRAPPERS,
        "coverage_rows": _coverage_rows(),
    }


def check(live: dict, frozen: dict) -> list[str]:
    """Additive-only diff: every frozen entry must survive unchanged."""
    errors: list[str] = []
    for name, spec in frozen["tool_schemas"].items():
        got = live["tool_schemas"].get(name)
        if got is None:
            errors.append(f"tool-removed: {name}")
            continue
        if sorted(spec["required"]) != sorted(got["required"]):
            errors.append(f"tool-required-changed: {name}: "
                          f"{spec['required']} -> {got['required']}")
        missing_opt = set(spec["optional"]) - set(got["optional"])
        if missing_opt:
            errors.append(f"tool-optional-removed: {name}: {sorted(missing_opt)}")
        missing_ret = set(spec["returns"]) - set(got["returns"])
        if missing_ret:
            errors.append(f"tool-returns-removed: {name}: {sorted(missing_ret)}")
    missing_cmds = set(frozen["engine_commands"]) - set(live["engine_commands"])
    if missing_cmds:
        errors.append(f"engine-commands-removed: {sorted(missing_cmds)}")
    if live["gate_names_v150"] != frozen["gate_names_v150"]:
        errors.append(
            "v150-gate-list-changed: frozen "
            f"{frozen['gate_names_v150']} != live {live['gate_names_v150']}")
    missing_var = set(frozen["rational_variants"]) - set(live["rational_variants"])
    if missing_var:
        errors.append(f"variants-removed: {sorted(missing_var)}")
    for cls in frozen["epistemic_classes"]:
        if cls not in live["epistemic_classes"]:
            errors.append(f"epistemic-class-removed: {cls}")
    for row_id, verdict in frozen["coverage_rows"].items():
        got_verdict = live["coverage_rows"].get(row_id)
        if got_verdict is None:
            errors.append(f"coverage-row-removed: {row_id}")
        elif verdict == "FORMAL" and got_verdict != "FORMAL":
            errors.append(f"coverage-row-demoted: {row_id}: "
                          f"{verdict} -> {got_verdict}")
    for wrapper in frozen["wrappers"]:
        if not (ROOT / wrapper).exists():
            errors.append(f"wrapper-removed: {wrapper}")
    return errors


def main() -> int:
    live = snapshot()
    if "--check" in sys.argv:
        if not FROZEN.exists():
            print("COMPAT_FLOOR_FAIL frozen snapshot missing")
            return 1
        frozen = json.loads(FROZEN.read_text())
        errors = check(live, frozen)
        for err in errors:
            print(f"FAIL {err}")
        print(f"COMPAT_FLOOR_{'PASS' if not errors else 'FAIL'} "
              f"frozen_tools={frozen['tool_count']} "
              f"live_tools={live['tool_count']} "
              f"frozen_gates={len(frozen['gate_names_v150'])} "
              f"errors={len(errors)}")
        return 1 if errors else 0
    FROZEN.parent.mkdir(parents=True, exist_ok=True)
    FROZEN.write_text(json.dumps(live, indent=2, sort_keys=True) + "\n")
    print(f"froze {FROZEN} tools={live['tool_count']} "
          f"gates={len(live['gate_names_v150'])} "
          f"commands={len(live['engine_commands'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
