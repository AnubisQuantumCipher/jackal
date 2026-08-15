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
GAUSSIAN_PROOF = ROOT / "proofs/lean/JackalIv/GaussianCert.lean"
GAUSSIAN_CHECKER = ROOT / "proofs/lean/JackalIv/GaussianCertMain.lean"
GAUSSIAN_PRODUCER = ROOT / "tools/gaussian_certificate.py"
GAUSSIAN_PLUGIN = ROOT / "plugin/hermes/server.py"
GAUSSIAN_PLUGIN_MANIFEST = ROOT / "plugin/hermes/tools.json"
OUT = ROOT / "release/coverage/formal_coverage_inventory.json"

SCHEMA_VERSION = "jackal-coverage-inventory-v1"

# The FORMAL fragment: operators wired end to end (engine range-bound-cert ->
# certificate -> checker -> Runs constructor(s) -> cert_check_sound). Each maps
# to the Runs constructor(s) that carry its soundness.
FORMAL = {
    "num":   ["num_exact"],
    "var":   ["var"],
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
    # sqrt via pure-ℚ Newton bracket (§487 fragment extension, v1.4.0).
    # NO libm TCB — the checker validates rational inequalities only.
    "sqrt":  ["sqrtRat"],
    # exp via pure-ℚ rational Taylor with certified remainder bound
    # (§487 fragment extension, v1.4.1).  Positive-argument branch only:
    # `[lo, hi]` with `0 <= lo`. NO libm TCB — the checker validates six
    # rational inequalities including expPartial + expRemainder in ℚ.
    "exp":   ["expRat"],
}
LIBM_CONST_TCB: set[str] = set()  # no FORMAL row carries a ModelTCB const obligation

# Refused-from-formal (fail closed in range-bound-cert / request-bound checker):
# true transcendentals, general/negative powers, modulo — and `const`
# (pi/e/tau): a `const_rounded` node's value is bound only by the undischarged
# `ConstTCB` premise (not ℚ-decidable), so the request-bound release checker
# refuses it (§487-const audit, 2026-08-15; Lean lock
# `requestRejects_const_rounded_node`). Constants remain available in weaker
# lanes at their honest epistemic class.  `exp` PROMOTED to FORMAL in v1.4.1
# via `expRat` (rational Taylor + certified remainder, no libm TCB).
REFUSED_FORMAL = ["ln", "tan", "cbrt", "atan", "asin", "acos",
                  "log10", "log2", "hypot", "atan2", "pow_neg", "pow_general",
                  "mod", "const"]

# Weaker (non-formal) lanes that must keep their epistemic class.
WEAK_LANES = [
    ("eval",       "IEEE f64 expression evaluation", "estimated"),
    ("diff",       "symbolic differentiation, numerically checked", "checked"),
    ("integrate",  "fixed-grid Simpson + Richardson estimate", "estimated"),
    ("integrate-adaptive", "adaptive Simpson estimate, refuse-on-unconverged", "estimated"),
    ("integrate-bound",
     "certified interval enclosure, CONDITIONAL on the stated f64/libm model; "
     "implementation campaign-tested, NOT mechanized", "bounded"),
    ("range-bound",
     "certified range enclosure, CONDITIONAL on the stated f64/libm model; "
     "implementation campaign-tested, NOT mechanized", "bounded"),
    ("solve",      "bisection root with conditioning diagnostic", "estimated"),
    ("rat",        "exact rational arithmetic (not yet checker-covered)", "exact"),
    ("big-*",      "exact big-integer arithmetic (not yet checker-covered)", "exact"),
    ("claim-card", "physical model with assumptions", "model-based"),
]

# Operator → plugin-tool routing.  Most operators funnel through the engine's
# `range-bound-cert` command and are exposed via `jackal_range_bound`.  The
# libm-free fragment extensions bypass the engine entirely and route through
# their own standalone Python producer + the pinned checker; the plugin
# exposes them as dedicated tools.
_OPERATOR_PLUGIN_TOOL = {
    "sqrt": "jackal_sqrt_rat_bound",  # v1.4.0 fragment extension
    "exp":  "jackal_exp_rat_bound",   # v1.4.1 fragment extension
}


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
            "soundness_theorem": "request_bound_certified_release",
            "runs_constructors": ctors,
            "libm_assumption": ("ModelTCB.const (within delta0)" if op in LIBM_CONST_TCB else "none"),
            "plugin_tool": _OPERATOR_PLUGIN_TOOL.get(op, "jackal_range_bound"),
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
            "verdict": "CONDITIONAL" if status in ("exact", "bounded") else "WEAK",
            "notes": "weaker lane; must never inherit formal-* language",
        })
    gaussian_wired = (
        GAUSSIAN_PROOF.exists()
        and "theorem gaussian_integral_check_sound" in GAUSSIAN_PROOF.read_text()
        and GAUSSIAN_CHECKER.exists()
        and "checkCert cert" in GAUSSIAN_CHECKER.read_text()
        and GAUSSIAN_PRODUCER.exists()
        and GAUSSIAN_PLUGIN.exists()
        and "def tool_gaussian_integral" in GAUSSIAN_PLUGIN.read_text()
        and GAUSSIAN_PLUGIN_MANIFEST.exists()
        and '"jackal_gaussian_integral"' in GAUSSIAN_PLUGIN_MANIFEST.read_text()
    )
    rows.append({
        "kind": "operation-family", "operator": "gaussian-exp-square-integral-v1",
        "description": "Canonical exp(-A*(x-mu)^2) integration with exact-square rational A",
        "parser_admission": "Lean canonical certificate codec + decimal source binding",
        "canonical_lowering": "GaussianCert.parseDecimalCanon",
        "evaluator_path": "untrusted gaussian_certificate.py -> jackal_gaussian_check",
        "certificate_op": ["gaussian-total-minus-tails-v1"],
        "checker_decode": "GaussianCert.parseCert",
        "checker_rule": "GaussianCert.checkCert",
        "soundness_theorem": "gaussian_integral_check_sound",
        "runs_constructors": [],
        "libm_assumption": "none",
        "plugin_tool": "jackal_gaussian_integral",
        "requested_assurance": "formal-bounded",
        "allowed_status": "formal-bounded",
        "tests": ["formal_gaussian_checker_test.py", "formal_gaussian_mutations.py",
                  "formal_gaussian_receipt_test.py", "plugin_smoke.py"],
        "verdict": "FORMAL" if gaussian_wired else "UNWIRED",
        "notes": ("zero-libm; generic exp range checking remains refused"
                  if gaussian_wired else "proof/checker/producer chain incomplete"),
    })
    # Plugin-binding rows: the Hermes plugin threads every call through the
    # shared validator and re-runs the pinned checker on receipt verification.
    # These rows document the plugin surface itself, distinct from operator
    # rows.  They ship with the release manifest so a reverifier can bind
    # against the tool name it invoked.
    rows.append({
        "kind": "plugin-tool", "operator": "jackal_range_bound",
        "description": "Hermes plugin tool: emit a jackal-formal-receipt-v1 for a range-bound-cert request",
        "parser_admission": True, "canonical_lowering": "simplify_bound",
        "evaluator_path": "plugin/hermes/server.py -> release_validate.validate_release -> jackal-native range-bound-cert",
        "certificate_op": [], "checker_decode": "CertCodec.parseCert",
        "checker_rule": "CertCheck.checkNode",
        "soundness_theorem": "request_bound_certified_release",
        "runs_constructors": [],
        "libm_assumption": "as per operator rows",
        "plugin_tool": "jackal_range_bound",
        "requested_assurance": "formal-bounded",
        "allowed_status": "formal-bounded",
        "tests": ["plugin_smoke.py", "cert_mutations_11.py::M11"],
        "verdict": "FORMAL",
        "notes": "plugin bundle hash is pinned in release/MANIFEST.sha256 as plugin_hermes",
    })
    rows.append({
        "kind": "plugin-tool", "operator": "jackal_gaussian_integral",
        "description": "Hermes plugin tool: emit and independently reverify a zero-libm Gaussian formal receipt",
        "parser_admission": "canonical gaussian-exp-square-v1 only",
        "canonical_lowering": "GaussianCert.parseDecimalCanon",
        "evaluator_path": "plugin/hermes/server.py -> gaussian_release.release -> receipt_verify.verify_receipt -> jackal_gaussian_check",
        "certificate_op": ["gaussian-total-minus-tails-v1"],
        "checker_decode": "GaussianCert.parseCert",
        "checker_rule": "GaussianCert.checkCert",
        "soundness_theorem": "gaussian_integral_check_sound",
        "runs_constructors": [],
        "libm_assumption": "none",
        "plugin_tool": "jackal_gaussian_integral",
        "requested_assurance": "formal-bounded",
        "allowed_status": "formal-bounded",
        "tests": ["plugin_smoke.py", "package_smoke.py"],
        "verdict": "FORMAL" if gaussian_wired else "UNWIRED",
        "notes": "plugin runs the pinned checker during release and reruns it from the carried receipt before returning",
    })
    rows.append({
        "kind": "plugin-tool", "operator": "jackal_sqrt_rat_bound",
        "description": "Hermes plugin tool: emit a pure-ℚ formal-bounded enclosure of sqrt(x) via the standalone Python producer + pinned checker; NO libm on the proof-decision path.  Admits ONLY the exact form 'sqrt(x)' on a canonical rational interval.",
        "parser_admission": "sqrt(x) only",
        "canonical_lowering": "n/a (bypasses engine)",
        "evaluator_path": "plugin/hermes/server.py -> tools/sqrt_rat_producer.py (identity-pinned, TOCTOU stable) -> jackal_cert_check range-bound-cert",
        "certificate_op": ["sqrt_rat"],
        "checker_decode": "CertCodec.parseCert",
        "checker_rule": "CertCheck.checkNode(sqrt_rat)",
        "soundness_theorem": "request_bound_certified_release",
        "runs_constructors": ["sqrtRat"],
        "libm_assumption": "none",
        "plugin_tool": "jackal_sqrt_rat_bound",
        "requested_assurance": "formal-bounded",
        "allowed_status": "formal-bounded",
        "tests": ["plugin_smoke.py::S14", "package_smoke.py::sqrt-rat-release-cli", "package_smoke.py::plugin-sqrt-rat", "formal_sqrt_rat_release_test.py"],
        "verdict": "FORMAL" if "sqrtRat" in runs else "UNWIRED",
        "notes": "producer + checker identities pinned in release/MANIFEST.sha256 as sqrt_rat_producer and checker; payload is `variant=sqrt_rat` (NOT a jackal-formal-receipt-v1 envelope yet)",
    })
    rows.append({
        "kind": "plugin-tool", "operator": "jackal_exp_rat_bound",
        "description": "Hermes plugin tool: emit a pure-ℚ formal-bounded enclosure of exp(x) on [lo, hi] with lo >= 0 via the standalone Python producer + pinned checker; NO libm on the proof-decision path (uses exact rational Taylor + certified remainder).  Admits ONLY the exact form 'exp(x)' on a canonical rational interval.",
        "parser_admission": "exp(x) only, lo >= 0",
        "canonical_lowering": "n/a (bypasses engine)",
        "evaluator_path": "plugin/hermes/server.py -> tools/exp_rat_producer.py (identity-pinned, TOCTOU stable) -> jackal_cert_check range-bound-cert",
        "certificate_op": ["exp_rat"],
        "checker_decode": "CertCodec.parseCert",
        "checker_rule": "CertCheck.checkNode(exp_rat)",
        "soundness_theorem": "request_bound_certified_release",
        "runs_constructors": ["expRat"],
        "libm_assumption": "none",
        "plugin_tool": "jackal_exp_rat_bound",
        "requested_assurance": "formal-bounded",
        "allowed_status": "formal-bounded",
        "tests": ["plugin_smoke.py::S15", "plugin_smoke.py::S16", "package_smoke.py::exp-rat-release-cli", "package_smoke.py::plugin-exp-rat", "formal_exp_rat_release_test.py"],
        "verdict": "FORMAL" if "expRat" in runs else "UNWIRED",
        "notes": "producer + checker identities pinned in release/MANIFEST.sha256 as exp_rat_producer and checker; positive-argument branch only; payload is `variant=exp_rat` (NOT a jackal-formal-receipt-v1 envelope yet)",
    })
    rows.append({
        "kind": "plugin-tool-mode", "operator": "jackal_verify_receipt:range",
        "description": "Hermes plugin tool mode: bind an external range request and re-run the pinned range checker",
        "parser_admission": True, "canonical_lowering": "n/a",
        "evaluator_path": "plugin/hermes/server.py -> tools/receipt_verify.verify_receipt -> jackal_cert_check request-bound mode",
        "certificate_op": [], "checker_decode": "CertCodec.parseCert",
        "checker_rule": "CertCheck request-bound release rule",
        "soundness_theorem": "request_bound_certified_release",
        "runs_constructors": [],
        "libm_assumption": "as per operator rows",
        "plugin_tool": "jackal_verify_receipt",
        "requested_assurance": "verified",
        "allowed_status": "verified",
        "tests": ["plugin_smoke.py", "cert_mutations_11.py::M2/M3/M4/M7/M9"],
        "verdict": "FORMAL",
        "notes": "external expected request and epoch are mandatory; outer digest alone is NOT sufficient",
    })
    rows.append({
        "kind": "plugin-tool-mode", "operator": "jackal_verify_receipt:gaussian",
        "description": "Hermes plugin tool mode: bind an external Gaussian request and re-run the pinned Gaussian checker",
        "parser_admission": "canonical gaussian-exp-square-v1 only",
        "canonical_lowering": "GaussianCert.parseDecimalCanon",
        "evaluator_path": "plugin/hermes/server.py -> tools/receipt_verify.verify_receipt -> jackal_gaussian_check",
        "certificate_op": ["gaussian-total-minus-tails-v1"],
        "checker_decode": "GaussianCert.parseCert",
        "checker_rule": "GaussianCert.checkCert",
        "soundness_theorem": "gaussian_integral_check_sound",
        "runs_constructors": [],
        "libm_assumption": "none",
        "plugin_tool": "jackal_verify_receipt",
        "requested_assurance": "verified",
        "allowed_status": "verified",
        "tests": ["formal_gaussian_receipt_test.py", "plugin_smoke.py"],
        "verdict": "FORMAL" if gaussian_wired else "UNWIRED",
        "notes": "external expected request, tolerance, and epoch are mandatory; outer digest alone is NOT sufficient",
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
