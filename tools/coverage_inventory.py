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
INT_CERT_PROOF = ROOT / "proofs/lean/JackalIv/IntCertSound.lean"
INT_CERT_CHECKER_MAIN = ROOT / "proofs/lean/JackalIv/IntCertMain.lean"
INT_CERT_PRODUCER = ROOT / "tools/int_cert_producer.py"
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
    # sin/cos: the engine emitter path carries the universal [-1,1] hull
    # (`sin`/`cos` constructors); the standalone producer path adds the
    # tight pure-ℚ midpoint-Taylor strategy (§490 v1.5.0, `sinRat`/`cosRat`,
    # |midpoint| <= 1, NO libm TCB).
    "sin":   ["sin", "sinRat"],
    "cos":   ["cos", "cosRat"],
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
    # (§487 fragment extension, v1.4.1; GENERAL-SIGN since v1.5.0 §490 via
    # the reciprocal identity).  NO libm TCB — the checker validates
    # sign-aware rational inequalities (Gaussian.expLBQ/expUBQ).
    "exp":   ["expRat"],
    # ln via the pure-ℚ INVERSE exponential bracket (§490 v1.5.0).
    # Full positive rational domain.  NO libm TCB.
    "ln":    ["logRat"],
    # atan via pure-ℚ cap / tan-bracket / reciprocal strategies over the
    # Mathlib 20-digit rational π bounds (§490 v1.5.0).  Full rational
    # domain.  NO libm TCB.
    "atan":  ["atanRat"],
}
LIBM_CONST_TCB: set[str] = set()  # no FORMAL row carries a ModelTCB const obligation

# Refused-from-formal (fail closed in range-bound-cert / request-bound checker):
# true transcendentals, general/negative powers, modulo — and `const`
# (pi/e/tau): a `const_rounded` node's value is bound only by the undischarged
# `ConstTCB` premise (not ℚ-decidable), so the request-bound release checker
# refuses it (§487-const audit, 2026-08-15; Lean lock
# `requestRejects_const_rounded_node`). Constants remain available in weaker
# lanes at their honest epistemic class.  `exp` PROMOTED to FORMAL in v1.4.1
# via `expRat`; `ln` and `atan` PROMOTED to FORMAL in v1.5.0 §490 via
# `logRat`/`atanRat` (both zero-libm).
REFUSED_FORMAL = ["tan", "cbrt", "asin", "acos",
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
# Exact CAS / number-theory lanes (§490 v1.5.0): computed exactly by the
# engine, each emitting a `jackal-exact-cert-v1` certificate that the
# independent stdlib-only verifier `tools/exact_verify.py` re-checks by full
# recomputation.  `exact` here means exact integer/rational computation with
# an independently re-checkable certificate — NOT a Lean-mechanized claim;
# formal-* language is structurally refused on these lanes.
EXACT_CAS_LANES = [
    ("canon",        "canonical s-expression + SHA-256 of any parsed expression", "exact"),
    ("poly-canon",   "dense Q[x] canonical form (degree <= 64)", "exact"),
    ("poly-eq",      "decidable polynomial identity over Q[x]", "exact"),
    ("poly-gcd",     "monic polynomial gcd over Q[x] (Euclid)", "exact"),
    ("ratfunc-canon", "rational-function canonical form P/Q, gcd-reduced, monic denominator, explicit denominator-nonzero side condition", "exact"),
    ("roots-isolate", "Sturm-sequence isolation of all distinct real roots", "exact"),
    ("alg-sign",     "exact sign of a Q[x] polynomial at a rational point", "exact"),
    ("alg-cmp",      "order decision between two isolated real algebraic numbers", "exact"),
    ("xgcd",         "extended gcd with Bezout certificate", "exact"),
    ("mod-pow",      "modular exponentiation (square-and-multiply)", "exact"),
    ("mod-inv",      "modular inverse with product certificate", "exact"),
    ("crt",          "Chinese remainder reconstruction (pairwise-coprime, up to 16 moduli)", "exact"),
    ("divides",      "exact divisibility decision", "exact"),
    ("prime-cert",   "Pratt primality certificate / composite divisor witness (budgeted, fail-closed)", "exact"),
]


# Operator → plugin-tool routing.  Most operators funnel through the engine's
# `range-bound-cert` command and are exposed via `jackal_range_bound`.  The
# libm-free fragment extensions bypass the engine entirely and route through
# their own standalone Python producer + the pinned checker; the plugin
# exposes them as dedicated tools.
_OPERATOR_PLUGIN_TOOL = {
    "sqrt": "jackal_sqrt_rat_bound",  # v1.4.0 fragment extension
    "exp":  "jackal_exp_rat_bound",   # v1.4.1 fragment extension (general-sign v1.5.0)
    "ln":   "jackal_ln_rat_bound",    # v1.5.0 §490 fragment extension
    "atan": "jackal_atan_rat_bound",  # v1.5.0 §490 fragment extension
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
    for lane, desc, status in EXACT_CAS_LANES:
        rows.append({
            "kind": "lane", "operator": lane, "description": desc,
            "parser_admission": True, "canonical_lowering": "n/a",
            "evaluator_path": lane,
            "certificate_op": ["jackal-exact-cert-v1"] if lane != "canon" else [],
            "checker_decode": "tools/exact_verify.py (independent recompute)" if lane != "canon" else "n/a",
            "checker_rule": "exact_verify kind handler" if lane != "canon" else "n/a",
            "soundness_theorem": "n/a", "runs_constructors": [],
            "libm_assumption": "none (exact integer/rational computation)",
            "plugin_tool": f"jackal_{lane.replace('-', '_')}",
            "requested_assurance": status, "allowed_status": status,
            "tests": ["exact_lane_test.py", "exact_verify_test.py"],
            "verdict": "CONDITIONAL",
            "notes": "exact lane with independently re-checkable certificate; "
                     "verification is recomputation by tools/exact_verify.py, "
                     "NOT a Lean-mechanized claim; formal-* language refused",
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
        "notes": "producer + checker identities pinned in release/MANIFEST.sha256 as sqrt_rat_producer and checker; payload carries `variant=sqrt_rat` in a jackal-formal-receipt-v1 envelope when requested",
    })
    rows.append({
        "kind": "plugin-tool", "operator": "jackal_exp_rat_bound",
        "description": "Hermes plugin tool: emit a pure-ℚ formal-bounded enclosure of exp(x) on any canonical rational interval (general-sign since v1.5.0 §490: negative arguments via the exact reciprocal identity) via the standalone Python producer + pinned checker; NO libm on the proof-decision path (uses exact rational Taylor + certified remainder).  Admits ONLY the exact form 'exp(x)'.",
        "parser_admission": "exp(x) only",
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
        "notes": "producer + checker identities pinned in release/MANIFEST.sha256 as exp_rat_producer and checker; general-sign domain since v1.5.0; payload carries `variant=exp_rat` in a jackal-formal-receipt-v1 envelope when requested",
    })
    for vop, vprod, vctor, vdesc, vadm in [
        ("jackal_ln_rat_bound", "ln_rat_producer", "logRat",
         "Hermes plugin tool: emit a pure-ℚ formal-bounded enclosure of ln(x) on a canonical rational interval with 0 < lo via the standalone Python producer + pinned checker; NO libm on the proof-decision path (inverse exponential bracket, Gaussian.expUBQ/expLBQ).  Admits ONLY the exact form 'ln(x)'.",
         "ln(x) only, 0 < lo"),
        ("jackal_sin_rat_bound", "sin_rat_producer", "sinRat",
         "Hermes plugin tool: emit a pure-ℚ formal-bounded enclosure of sin(x) on a canonical rational interval with |midpoint| <= 1 via the standalone Python producer + pinned checker; NO libm on the proof-decision path (Mathlib Real.sin_bound midpoint Taylor + Lipschitz-1).  Admits ONLY the exact form 'sin(x)'.",
         "sin(x) only, |midpoint| <= 1"),
        ("jackal_cos_rat_bound", "sin_rat_producer", "cosRat",
         "Hermes plugin tool: emit a pure-ℚ formal-bounded enclosure of cos(x) on a canonical rational interval with |midpoint| <= 1 via the standalone Python producer + pinned checker; NO libm on the proof-decision path (Mathlib Real.cos_bound midpoint Taylor + Lipschitz-1).  Admits ONLY the exact form 'cos(x)'.",
         "cos(x) only, |midpoint| <= 1"),
        ("jackal_atan_rat_bound", "atan_rat_producer", "atanRat",
         "Hermes plugin tool: emit a pure-ℚ formal-bounded enclosure of atan(x) on ANY canonical rational interval via the standalone Python producer + pinned checker; NO libm on the proof-decision path (cap / tan-bracket / reciprocal strategies over Mathlib 20-digit rational π bounds).  Admits ONLY the exact form 'atan(x)'.",
         "atan(x) only"),
        ("jackal_tanh_rat_bound", "tanh_rat_producer", "expRat",
         "Hermes plugin tool: emit a pure-ℚ formal-bounded enclosure of the composite 1-2/(exp(2*x)+1) — mathematically tanh(x) — on a canonical rational interval with |x| <= 20, as an 8-node zero-libm certificate (num_exact/var/mul/exp_rat/add/div/sub; constant-numerator division keeps the enclosure tight at any width).  The receipt binds the composite expression string; the tanh reading is a documented identity, never a checker claim.",
         "1-2/(exp(2*x)+1) only, |x| <= 20"),
    ]:
        rows.append({
            "kind": "plugin-tool", "operator": vop,
            "description": vdesc,
            "parser_admission": vadm,
            "canonical_lowering": "n/a (bypasses engine)",
            "evaluator_path": f"plugin/hermes/server.py -> tools/{vprod}.py (identity-pinned, TOCTOU stable) -> jackal_cert_check range-bound-cert",
            "certificate_op": [vop.replace("jackal_", "").replace("_bound", "")],
            "checker_decode": "CertCodec.parseCert",
            "checker_rule": f"CertCheck.checkNode({vop.replace('jackal_', '').replace('_bound', '')})",
            "soundness_theorem": "request_bound_certified_release",
            "runs_constructors": [vctor],
            "libm_assumption": "none",
            "plugin_tool": vop,
            "requested_assurance": "formal-bounded",
            "allowed_status": "formal-bounded",
            "tests": ["plugin_smoke.py", "package_smoke.py",
                      f"formal_{vop.replace('jackal_', '').replace('_bound', '')}_release_test.py"],
            "verdict": "FORMAL" if vctor in runs else "UNWIRED",
            "notes": f"producer + checker identities pinned in release/MANIFEST.sha256 as {vprod} and checker; §490 v1.5.0 fragment extension",
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
    # v1.7 certified integrate-bound-cert lane (bound_step composition,
    # Ledger roadmap item 4): untrusted exact-ℚ producer mirroring the
    # engine's bound_step + the compiled proved checker jackal_int_cert_check.
    int_cert_wired = (
        INT_CERT_PROOF.exists()
        and "theorem int_cert_sound" in INT_CERT_PROOF.read_text()
        and INT_CERT_CHECKER_MAIN.exists()
        and "checkIntCertRequest rawExpr rawLo rawHi rawTol hdr tree"
        in INT_CERT_CHECKER_MAIN.read_text()
        and INT_CERT_PRODUCER.exists()
        and GAUSSIAN_PLUGIN.exists()
        and "def tool_integrate_bound_cert" in GAUSSIAN_PLUGIN.read_text()
        and GAUSSIAN_PLUGIN_MANIFEST.exists()
        and '"jackal_integrate_bound_cert"' in GAUSSIAN_PLUGIN_MANIFEST.read_text()
    )
    rows.append({
        "kind": "operation-family", "operator": "integrate-bound-composed-v1",
        "description": "Certified definite-integral enclosure by bound_step subdivision-tree composition (range/taylor2/taylor4 leaves over the certified fragment num/var/neg/add/sub/mul/div/pow/sin/cos/abs)",
        "parser_admission": "canonical jackal-int-cert v1 codec (exact-rational grammar)",
        "canonical_lowering": "IntCertCodec.parseIntCert",
        "evaluator_path": "untrusted tools/int_cert_producer.py -> jackal_int_cert_check",
        "certificate_op": ["jackal-int-cert v1"],
        "checker_decode": "IntCertCodec.parseIntCert",
        "checker_rule": "IntCertCheck.checkIntCertRequest",
        "soundness_theorem": "int_cert_sound",
        "runs_constructors": [],
        "libm_assumption": "none external (releaseNodesOk derives each embedded ModelTCB and the former TreeTCB inside the proved checker path)",
        "plugin_tool": "jackal_integrate_bound_cert",
        "requested_assurance": "formal-bounded",
        "allowed_status": "formal-bounded",
        "tests": ["int_cert_matrix_test.py", "int_cert_aba_test.py",
                  "int_cert_request_binding_v172_test.py",
                  "int_cert_differential.py", "plugin_smoke.py"],
        "verdict": "FORMAL" if int_cert_wired else "UNWIRED",
        "notes": ("producer is untrusted and identity-pinned; the engine's own float integrate-bound lane stays CONDITIONAL/bounded and never inherits this row"
                  if int_cert_wired else "proof/checker/producer chain incomplete"),
    })
    rows.append({
        "kind": "plugin-tool", "operator": "jackal_integrate_bound_cert",
        "description": "Hermes plugin tool: emit a jackal-formal-receipt-v1 for a certified composed definite-integral enclosure (bound_step composition; subdivision-tree certificate re-checked by the pinned proved jackal_int_cert_check)",
        "parser_admission": "certified fragment only: num/var/neg/add/sub/mul/div/pow(0..4096)/sin/cos/abs in x",
        "canonical_lowering": "n/a (bypasses engine; exact-rational mirror of bound_step)",
        "evaluator_path": "plugin/hermes/server.py -> tools/int_cert_release.py (identity-pinned, TOCTOU stable) -> jackal_int_cert_check",
        "certificate_op": ["jackal-int-cert v1"],
        "checker_decode": "IntCertCodec.parseIntCert",
        "checker_rule": "IntCertCheck.checkIntCertRequest",
        "soundness_theorem": "int_cert_sound",
        "runs_constructors": [],
        "libm_assumption": "none",
        "plugin_tool": "jackal_integrate_bound_cert",
        "requested_assurance": "formal-bounded",
        "allowed_status": "formal-bounded",
        "tests": ["plugin_smoke.py::S21", "plugin_smoke.py::S22",
                  "int_cert_matrix_test.py", "int_cert_release_test.py"],
        "verdict": "FORMAL" if int_cert_wired else "UNWIRED",
        "notes": "producer + checker identities pinned in release/MANIFEST.sha256 as int_cert_producer and int-cert-checker; v1.7.2 binds the raw expression, canonical bounds, and tolerance inside Lean; the weaker jackal_integrate_bound float lane is a distinct row and stays bounded",
    })
    rows.append({
        "kind": "plugin-tool-mode", "operator": "jackal_verify_receipt:int_cert",
        "description": "Hermes plugin tool mode: bind an external composed-integral request and re-run the pinned jackal_int_cert_check",
        "parser_admission": "canonical jackal-int-cert v1 only",
        "canonical_lowering": "IntCertCodec.parseIntCert",
        "evaluator_path": "plugin/hermes/server.py -> tools/receipt_verify.verify_receipt -> jackal_int_cert_check",
        "certificate_op": ["jackal-int-cert v1"],
        "checker_decode": "IntCertCodec.parseIntCert",
        "checker_rule": "IntCertCheck.checkIntCertRequest",
        "soundness_theorem": "int_cert_sound",
        "runs_constructors": [],
        "libm_assumption": "none",
        "plugin_tool": "jackal_verify_receipt",
        "requested_assurance": "verified",
        "allowed_status": "verified",
        "tests": ["int_cert_release_test.py",
                  "int_cert_request_binding_v172_test.py", "plugin_smoke.py"],
        "verdict": "FORMAL" if int_cert_wired else "UNWIRED",
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
