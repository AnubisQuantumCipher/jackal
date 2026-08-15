#!/usr/bin/env python3
"""JACKAL v1.0.4 durable positive corpus (mission §389).

Every case is RELEASED through the shared release validator (not the checker
alone), covering the declared certified fragment. Each row carries the source
commit, evaluator/checker identities, model/schema, request commitment,
certificate digest, released output, and verdict. Written to a repository-
owned evidence path (NOT /tmp — the v1.0.3 Counterexample E defect) and
verified independently by tests/cert_evidence_verify.py. Normal and
`python3 -O` runs must agree.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
import release_validate as rv  # noqa: E402

EVALUATOR = ROOT / "jackal-native"
CHECKER = ROOT / "proofs/lean/.lake/build/bin/jackal_cert_check"
OUT = ROOT / "release/evidence/positive_corpus.jsonl"

# Declared certified fragment coverage: every supported constructor appears.
# `const` was REMOVED from the release fragment 2026-08-15 (§487-const audit):
# a `const_rounded` node's value is bound only by the undischarged `ConstTCB`
# premise, so the request-bound checker refuses it — locked below by
# REFUSAL_CASES and in Lean by `requestRejects_const_rounded_node`.
CASES = [
    ("P01-num-var-add", "x+1", "1", "2"),
    ("P02-sub", "x-3", "1", "2"),
    ("P03-mul", "x*x", "1", "2"),
    ("P04-div", "1/(x+2)", "1", "2"),
    ("P05-neg", "0-x", "1", "2"),
    ("P06-pow-even", "x^2", "-1", "2"),
    ("P07-pow-odd", "x^3", "1", "2"),
    ("P08-pow-zero", "x^0", "1", "2"),
    ("P09-poly", "x^2+x-1", "0", "3"),
    ("P10-sin", "sin(x)", "0", "3"),
    ("P11-cos", "cos(x)", "0", "3"),
    ("P12-abs", "abs(x-1)", "0", "2"),
    ("P13-floor", "floor(x)", "1", "3"),
    ("P14-ceil", "ceil(x)", "1", "3"),
    ("P15-round", "round(x)", "1", "3"),
    ("P16-trunc", "trunc(x)", "1", "3"),
    ("P17-min", "min(x,1)", "0", "3"),
    ("P18-max", "max(x,1)", "0", "3"),
    ("P19-rational-scale", "(22/7)*x", "1", "2"),
    ("P20-nested", "min(x^2, sin(x)+2)", "0", "2"),
]

# Expressions that MUST refuse formal release (policy-excluded constructors).
REFUSAL_CASES = [
    ("R01-const-pi-excluded", "pi*x", "1", "2"),
    ("R02-const-e-excluded", "e+x", "1", "2"),
    ("R03-const-tau-excluded", "tau*x", "1", "2"),
]

FRAGMENT = {"num", "var", "add", "sub", "mul", "div", "neg", "pow", "sin", "cos",
            "abs", "floor", "ceil", "round", "trunc", "min", "max"}


def source_sha() -> str:
    """Commit-independent provenance anchor: the SHA-256 of the engine source
    the evaluator was built from. Stable regardless of which git commit ships,
    so the evidence never carries a self-referential (off-by-one) commit label.
    The git release commit is recorded once, at the release receipt level."""
    return hashlib.sha256((ROOT / "jackal_calc.anb").read_bytes()).hexdigest()


def manifest_ids():
    ev = ck = ""
    for ln in (ROOT / "release/MANIFEST.sha256").read_text().splitlines():
        if ln.startswith("evaluator "):
            ev = ln.split()[2]
        if ln.startswith("checker "):
            ck = ln.split()[2]
    return ev, ck


def main() -> int:
    ev_id, chk_id = manifest_ids()
    src = source_sha()
    rows = []
    covered = set()
    for cid, expr, lo, hi in CASES:
        try:
            receipt = rv.validate_release(
                expr=expr, lo=lo, hi=hi, evaluator=str(EVALUATOR), checker=str(CHECKER),
                expected_evaluator=ev_id, expected_checker=chk_id)
            verdict = receipt["status"]  # gate-derived, e.g. "formal-bounded"
        except rv.ReleaseRefusal as r:
            receipt, verdict = {"refusal": r.cls}, "refused"
        # Constructor coverage: inspect operator characters and function names
        # directly (do NOT split on operators — that erases the tokens).
        if "x" in expr:
            covered.add("var")
        if any(c.isdigit() for c in expr):
            covered.add("num")
        for ch, name in (("+", "add"), ("*", "mul"), ("/", "div"), ("^", "pow")):
            if ch in expr:
                covered.add(name)
        if "-" in expr:
            covered.add("sub")            # binary minus
        if expr.startswith("0-") or expr.startswith("-"):
            covered.add("neg")
        for fn in ("sin", "cos", "abs", "floor", "ceil", "round", "trunc", "min", "max"):
            if fn + "(" in expr:
                covered.add(fn)
        # NOTE: `const` intentionally NOT counted — excluded from the release
        # fragment (§487-const audit); its refusal is asserted by REFUSAL_CASES.
        rows.append({
            "id": cid, "expr": expr, "lo": lo, "hi": hi, "verdict": verdict,
            "source_sha256": src, "evaluator_sha256": ev_id, "checker_sha256": chk_id,
            "model": rv.MODEL_CONST, "schema": rv.SCHEMA_MAGIC,
            "request_commitment": receipt.get("request_commitment", ""),
            "certificate_sha256": receipt.get("certificate_sha256", ""),
            "output": receipt.get("certified_enclosure", []),
        })
    # Policy-excluded constructors MUST refuse formal release (fail closed).
    refusal_ok = True
    for cid, expr, lo, hi in REFUSAL_CASES:
        try:
            rv.validate_release(
                expr=expr, lo=lo, hi=hi, evaluator=str(EVALUATOR), checker=str(CHECKER),
                expected_evaluator=ev_id, expected_checker=chk_id)
            verdict, cls = "RELEASED", ""
            refusal_ok = False
        except rv.ReleaseRefusal as r:
            verdict, cls = "refused", r.cls
        rows.append({
            "id": cid, "expr": expr, "lo": lo, "hi": hi, "verdict": verdict,
            "refusal_class": cls, "source_sha256": src,
            "evaluator_sha256": ev_id, "checker_sha256": chk_id,
            "model": rv.MODEL_CONST, "schema": rv.SCHEMA_MAGIC,
        })
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(json.dumps(r, sort_keys=True) for r in rows) + "\n")
    digest = hashlib.sha256(OUT.read_bytes()).hexdigest()
    n_bounded = sum(1 for r in rows if r["verdict"] == "formal-bounded")
    n_refused = sum(1 for r in rows if r["verdict"] == "refused")
    missing = FRAGMENT - covered
    print(f"positive_cases={len(CASES)} formal_bounded={n_bounded} "
          f"refusal_cases={len(REFUSAL_CASES)} refused={n_refused} "
          f"fragment_covered={len(covered & FRAGMENT)}/{len(FRAGMENT)}")
    print(f"jsonl={OUT} sha256={digest}")
    if n_bounded != len(CASES):
        print("VERDICT: FAIL — a positive case did not release bounded")
        return 1
    if not refusal_ok or n_refused != len(REFUSAL_CASES):
        print("VERDICT: FAIL — a policy-excluded constructor released formal status")
        return 1
    if missing:
        print(f"VERDICT: FAIL — fragment not fully covered, missing={sorted(missing)}")
        return 1
    print("VERDICT: PASS — full certified fragment released bounded; "
          "policy-excluded constants refused")
    return 0


if __name__ == "__main__":
    sys.exit(main())
