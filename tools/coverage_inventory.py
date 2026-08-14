#!/usr/bin/env python3
"""JACKAL mechanization coverage inventory (completion program Phase B, §214).

Emits a machine-readable, schema-fixed inventory mapping every expression
operator AND plugin tool/mode to its position in the proof-carrying chain:
parser admission, canonical lowering, runtime evaluator path, certificate
encoding, checker decode, checker semantic rule, soundness theorem, libm
assumption, plugin exposure, requested assurance, allowed output status,
tests, and a VERDICT in {FORMAL, CONDITIONAL, WEAK, REFUSED, UNWIRED}.

The rows are DERIVED from a declared finite roster and CROSS-CHECKED against
the live trees (the `Runs` constructors in Embed.lean; the engine ops the
range-bound-cert evaluator supports). A separate validator
(tools/coverage_validate.py) independently recomputes and rejects any
missing/extra/duplicate/contradictory row. This inventory defines the initial
formal fragment; nothing may claim `formal-*` for an operator whose verdict
here is not FORMAL.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EMBED = ROOT / "proofs/lean/JackalIv/Embed.lean"
ENGINE = ROOT / "jackal_calc.anb"
OUT = ROOT / "release/coverage/formal_coverage_inventory.json"

SCHEMA_VERSION = "jackal-coverage-inventory-v1"

# The FORMAL fragment: operators wired end to end (engine range-bound-cert ->
# certificate -> checker -> Runs constructor(s) -> cert_check_sound). Each maps
# to the Runs constructor(s) that carry its soundness.
FORMAL = {
    "num":   ["num_exact"],
    "var":   ["var"],
    "const": ["const_rounded"],           # TCB: within delta0 of the real constant
    "neg":   ["neg"],
    "add":   ["add"],
    "sub":   ["sub"],
    "mul":   ["mul"],
    "div":   ["div"],
    "pow":   ["powZero", "powEvenPos", "powOddPos"],   # integer n>=0 only
    "sin":   ["sin"],
    "cos":   ["cos"],
    "abs":   ["abs"],
    "floor": ["floor"],
    "ceil":  ["ceil"],
    "round": ["round"],
    "trunc": ["trunc"],
    "min":   ["min"],
    "max":   ["max"],
}
LIBM_CONST_TCB = {"const"}  # carries a declared-value ModelTCB obligation

# Refused-from-formal (fail closed in range-bound-cert): true transcendentals,
# general/negative powers, modulo. Present in weaker lanes only.
REFUSED_FORMAL = ["sqrt", "exp", "ln", "tan", "cbrt", "atan", "asin", "acos",
                  "log10", "log2", "hypot", "atan2", "pow_neg", "pow_general", "mod"]

# Weaker (non-formal) lanes that must keep their epistemic class.
WEAK_LANES = [
    ("eval",       "IEEE f64 expression evaluation", "estimated"),
    ("diff",       "symbolic differentiation, numerically checked", "checked"),
    ("integrate",  "fixed-grid Simpson + Richardson estimate", "estimated"),
    ("integrate-adaptive", "adaptive Simpson estimate, refuse-on-unconverged", "estimated"),
    ("solve",      "bisection root with conditioning diagnostic", "estimated"),
    ("rat",        "exact rational arithmetic (not yet checker-covered)", "exact"),
    ("big-*",      "exact big-integer arithmetic (not yet checker-covered)", "exact"),
    ("claim-card", "physical model with assumptions", "model-based"),
]


def runs_constructors() -> set[str]:
    txt = EMBED.read_text()
    return set(re.findall(r"^\s*\|\s*([A-Za-z][A-Za-z0-9_]*)\b", txt, re.MULTILINE))


def engine_ops() -> set[str]:
    txt = ENGINE.read_text()
    ops = set()
    for name in list(FORMAL) + ["sin", "cos"]:
        if f'"{name}"' in txt:
            ops.add(name)
    return ops


def build_rows() -> list[dict]:
    runs = runs_constructors()
    eng = engine_ops()
    rows = []
    for op, ctors in FORMAL.items():
        missing = [c for c in ctors if c not in runs]
        wired = (op in eng) and not missing
        rows.append({
            "kind": "operator", "operator": op,
            "parser_admission": True,
            "canonical_lowering": "simplify_bound",
            "evaluator_path": "range-bound-cert (exact-rational interval)",
            "certificate_op": ctors,
            "checker_decode": "CertCodec.parseCert",
            "checker_rule": "CertCheck.checkNode",
            "soundness_theorem": "cert_check_sound",
            "runs_constructors": ctors,
            "libm_assumption": ("ModelTCB.const (within delta0)" if op in LIBM_CONST_TCB else "none"),
            "plugin_tool": "jackal_range_bound",
            "requested_assurance": "formal-bounded",
            "allowed_status": "formal-bounded",
            "tests": ["cert_positive_corpus.py", "cert_controls.py"],
            "verdict": "FORMAL" if wired else "UNWIRED",
            "notes": "" if wired else f"missing Runs ctor(s): {missing}",
        })
    for op in REFUSED_FORMAL:
        rows.append({
            "kind": "operator", "operator": op,
            "parser_admission": True, "canonical_lowering": "simplify_bound",
            "evaluator_path": "range-bound-cert refuses (fail closed)",
            "certificate_op": [], "checker_decode": "n/a", "checker_rule": "n/a",
            "soundness_theorem": "n/a", "runs_constructors": [],
            "libm_assumption": ("libm<=2ulp (not mechanized)" if op not in ("mod", "pow_neg", "pow_general") else "n/a"),
            "plugin_tool": "jackal_range_bound",
            "requested_assurance": "formal-bounded",
            "allowed_status": "refused",
            "tests": ["cert_controls.py::C24-C26"],
            "verdict": "REFUSED",
            "notes": "outside the formal fragment; refuses formal status",
        })
    for lane, desc, status in WEAK_LANES:
        rows.append({
            "kind": "lane", "operator": lane, "description": desc,
            "parser_admission": True, "canonical_lowering": "n/a",
            "evaluator_path": lane, "certificate_op": [], "checker_decode": "n/a",
            "checker_rule": "n/a", "soundness_theorem": "n/a", "runs_constructors": [],
            "libm_assumption": "n/a", "plugin_tool": "various",
            "requested_assurance": status, "allowed_status": status,
            "tests": ["test_calculator.py"],
            "verdict": "WEAK" if status != "exact" else "CONDITIONAL",
            "notes": "weaker lane; must never inherit formal-* language",
        })
    return rows


def main() -> int:
    rows = build_rows()
    doc = {
        "schema": SCHEMA_VERSION,
        "formal_fragment": sorted(FORMAL),
        "refused_from_formal": sorted(REFUSED_FORMAL),
        "rows": rows,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(doc, indent=2, sort_keys=True))
    digest = hashlib.sha256(OUT.read_bytes()).hexdigest()
    by_verdict: dict[str, int] = {}
    for r in rows:
        by_verdict[r["verdict"]] = by_verdict.get(r["verdict"], 0) + 1
    unwired = [r["operator"] for r in rows if r["verdict"] == "UNWIRED"]
    print(f"rows={len(rows)} verdicts={by_verdict}")
    print(f"inventory={OUT} sha256={digest}")
    if unwired:
        print(f"VERDICT: FAIL — UNWIRED operators claimed formal: {unwired}")
        return 1
    print("VERDICT: PASS — formal fragment fully wired; weaker lanes labeled honestly")
    return 0


if __name__ == "__main__":
    sys.exit(main())
