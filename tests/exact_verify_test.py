#!/usr/bin/env python3
"""Adversarial test battery for tools/exact_verify.py (jackal-exact-cert-v1).

Self-contained: builds golden certificates honestly in-test (no engine),
runs the verifier as a subprocess under interpreter isolation, and then
mutates every load-bearing field one at a time, requiring a NAMED reject
class for each tamper.  A tamper that still ACCEPTs is a test failure.

Run:  python3 tests/exact_verify_test.py
Pass: prints EXACT_VERIFY_TEST_PASS positives=<n> tampers=<m> and exits 0.
"""
from __future__ import annotations

import copy
import hashlib
import json
import random
import subprocess
import sys
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VERIFIER = ROOT / "tools" / "exact_verify.py"
SCHEMA = "jackal-exact-cert-v1"

# The verifier's documented stable reject classes (must match
# REASON_CLASSES in tools/exact_verify.py).
CLASSES = {
    "cert-json",
    "cert-schema",
    "int-malformed",
    "int-budget",
    "rat-not-canonical",
    "poly-fragment",
    "poly-budget",
    "ratfunc-zero-den",
    "pratt-missing-subcert",
    "pratt-budget",
    "xgcd-invalid",
    "mod-inv-invalid",
    "mod-pow-invalid",
    "crt-invalid",
    "prime-invalid",
    "composite-invalid",
    "poly-canon-mismatch",
    "poly-eq-mismatch",
    "poly-gcd-mismatch",
    "ratfunc-canon-mismatch",
    "roots-invalid",
    "verifier-internal",
}

positives = 0
tampers = 0
failures: list[str] = []


def ser(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def run_verifier(raw: bytes, isolated: bool = True):
    flags = ["-I", "-S", "-B"] if isolated else ["-B"]
    return subprocess.run(
        [sys.executable, *flags, str(VERIFIER), "-"],
        input=raw,
        capture_output=True,
    )


def cert(kind, claim, witness):
    return {"claim": claim, "kind": kind, "schema": SCHEMA, "witness": witness}


def expect_accept(label, obj):
    global positives
    raw = ser(obj)
    proc = run_verifier(raw)
    out = proc.stdout.decode()
    want_sha = hashlib.sha256(raw).hexdigest()
    kind = obj["kind"]
    expected = (
        f"exact-verify=ACCEPT kind={kind} cert_sha256={want_sha} "
        "method=independent-recompute"
    )
    if proc.returncode != 0 or out.strip() != expected:
        failures.append(
            f"ACCEPT expected [{label}]: rc={proc.returncode} out={out.strip()!r} "
            f"err={proc.stderr.decode().strip()!r}"
        )
        return
    lowered = out.lower()
    if "formal" in lowered or "proof" in lowered:
        failures.append(f"ACCEPT line leaks banned vocabulary [{label}]: {out!r}")
        return
    positives += 1


def expect_reject(label, payload, expected_cls=None):
    global tampers
    raw = payload if isinstance(payload, bytes) else ser(payload)
    proc = run_verifier(raw)
    out = proc.stdout.decode().strip()
    if proc.returncode != 1:
        failures.append(
            f"REJECT expected [{label}]: rc={proc.returncode} out={out!r} "
            f"err={proc.stderr.decode().strip()!r}"
        )
        return
    prefix = "exact-verify=REJECT reason="
    if not out.startswith(prefix):
        failures.append(f"REJECT line malformed [{label}]: {out!r}")
        return
    reason = out[len(prefix):]
    if reason not in CLASSES:
        failures.append(f"REJECT reason not in documented set [{label}]: {reason!r}")
        return
    if expected_cls is not None and reason != expected_cls:
        failures.append(f"REJECT wrong class [{label}]: got {reason!r} want {expected_cls!r}")
        return
    tampers += 1


def mutated(base, fn):
    obj = copy.deepcopy(base)
    fn(obj)
    return obj


def rat_s(f: Fraction) -> str:
    return str(f.numerator) if f.denominator == 1 else f"{f.numerator}/{f.denominator}"


# ---------------------------------------------------------------------------
# sympy is required for the honest Pratt builder and the cross-check block.
# ---------------------------------------------------------------------------
import sympy  # noqa: E402

X = sympy.symbols("x")


def pratt_node(n: int) -> dict:
    """Honest Pratt certificate built from sympy factorization + search."""
    if n in (2, 3):
        return {"a": "1", "factors": []}
    assert sympy.isprime(n), n
    fs = sympy.factorint(n - 1)
    a = next(
        cand
        for cand in range(2, n)
        if pow(cand, n - 1, n) == 1
        and all(pow(cand, (n - 1) // q, n) != 1 for q in fs)
    )
    return {
        "a": str(a),
        "factors": [
            {"q": str(q), "e": str(e), "cert": None if q == 2 else pratt_node(int(q))}
            for q, e in sorted(fs.items())
        ],
    }


def sympy_poly_canon_cert(expr: str) -> dict:
    """Canonical coefficients computed by sympy, NOT by the verifier."""
    sym = sympy.expand(sympy.sympify(expr.replace("^", "**")))
    if sym == 0:
        return cert("poly-canon", {"expr": expr, "degree": "-1", "coeffs": ["0"]}, {})
    poly = sympy.Poly(sym, X, domain="QQ")
    asc = list(reversed(poly.all_coeffs()))
    coeffs = [rat_s(Fraction(int(c.p), int(c.q))) for c in map(sympy.Rational, asc)]
    return cert(
        "poly-canon",
        {"expr": expr, "degree": str(poly.degree()), "coeffs": coeffs},
        {},
    )


# ===========================================================================
# Golden certificates (one honest construction per kind, plus extras)
# ===========================================================================

xgcd_g = cert("xgcd", {"a": "240", "b": "46", "g": "2"}, {"u": "-9", "v": "47"})
assert -9 * 240 + 47 * 46 == 2
xgcd_neg = cert("xgcd", {"a": "-240", "b": "46", "g": "2"}, {"u": "9", "v": "47"})
xgcd_zero = cert("xgcd", {"a": "0", "b": "0", "g": "0"}, {"u": "0", "v": "0"})

modinv_g = cert("mod-inv", {"a": "3", "m": "7", "inv": "5"}, {})

modpow_r = str(pow(5, 117, 19))
modpow_g = cert("mod-pow", {"base": "5", "exp": "117", "mod": "19", "r": modpow_r}, {})

crt_pairs = [(2, 3), (3, 5), (2, 7)]
crt_m = 3 * 5 * 7
crt_x = next(x for x in range(crt_m) if all(x % m == r for r, m in crt_pairs))
crt_g = cert(
    "crt",
    {
        "residues": [{"r": str(r), "m": str(m)} for r, m in crt_pairs],
        "x": str(crt_x),
        "M": str(crt_m),
    },
    {},
)

prime97 = cert("prime", {"n": "97"}, pratt_node(97))
prime_big = cert("prime", {"n": "1000003"}, pratt_node(1000003))
prime_base2 = cert("prime", {"n": "2"}, {"a": "1", "factors": []})

composite_g = cert("composite", {"n": "91"}, {"divisor": "7"})

pc_square = cert(
    "poly-canon",
    {"expr": "(x+1)^2", "degree": "2", "coeffs": ["1", "2", "1"]},
    {},
)
pc_zero = cert("poly-canon", {"expr": "x-x", "degree": "-1", "coeffs": ["0"]}, {})
pc_rat = cert(
    "poly-canon",
    {"expr": "x/2+1/2", "degree": "1", "coeffs": ["1/2", "1/2"]},
    {},
)

pe_true = cert(
    "poly-eq",
    {"lhs": "(x+1)^2", "rhs": "x^2+2*x+1", "equal": True},
    {"lhs_coeffs": ["1", "2", "1"], "rhs_coeffs": ["1", "2", "1"]},
)
pe_false = cert(
    "poly-eq",
    {"lhs": "(x+1)^2", "rhs": "x^2+1", "equal": False},
    {"lhs_coeffs": ["1", "2", "1"], "rhs_coeffs": ["1", "0", "1"]},
)

pg_g = cert(
    "poly-gcd",
    {"lhs": "x^2-1", "rhs": "x^2-2*x+1", "gcd_coeffs": ["-1", "1"]},
    {},
)
pg_zero_rhs = cert(
    "poly-gcd",
    {"lhs": "2*x^2-2", "rhs": "0", "gcd_coeffs": ["-1", "0", "1"]},
    {},
)
pg_zero_zero = cert("poly-gcd", {"lhs": "0", "rhs": "x-x", "gcd_coeffs": ["0"]}, {})

rf_g = cert(
    "ratfunc-canon",
    {
        "expr": "(x^2-1)/(x+1)",
        "num_coeffs": ["-1", "1"],
        "den_coeffs": ["1"],
        "side_condition": "denominator-nonzero",
    },
    {},
)
rf_sum = cert(
    "ratfunc-canon",
    {
        "expr": "1/(x^2-1)+1/(x+1)",
        "num_coeffs": ["0", "1"],
        "den_coeffs": ["-1", "0", "1"],
        "side_condition": "denominator-nonzero",
    },
    {},
)

ri_sqrt2 = cert(
    "roots-isolate",
    {
        "expr": "x^2-2",
        "distinct_real_roots": "2",
        "intervals": [["-3/2", "-1"], ["1", "3/2"]],
    },
    {},
)
ri_endpoint = cert(
    "roots-isolate",
    {
        "expr": "x^2-4",
        "distinct_real_roots": "2",
        "intervals": [["-3", "-2"], ["1", "2"]],
    },
    {},
)
ri_const = cert(
    "roots-isolate",
    {"expr": "5", "distinct_real_roots": "0", "intervals": []},
    {},
)
ri_multiple = cert(
    "roots-isolate",
    {"expr": "(x-1)^2", "distinct_real_roots": "1", "intervals": [["0", "2"]]},
    {},
)

GOLDENS = [
    ("xgcd", xgcd_g),
    ("xgcd negative input", xgcd_neg),
    ("xgcd zero", xgcd_zero),
    ("mod-inv", modinv_g),
    ("mod-pow", modpow_g),
    ("crt", crt_g),
    ("prime 97", prime97),
    ("prime 1000003", prime_big),
    ("prime base case 2", prime_base2),
    ("composite", composite_g),
    ("poly-canon square", pc_square),
    ("poly-canon zero", pc_zero),
    ("poly-canon rational", pc_rat),
    ("poly-eq true", pe_true),
    ("poly-eq false", pe_false),
    ("poly-gcd", pg_g),
    ("poly-gcd rhs zero", pg_zero_rhs),
    ("poly-gcd both zero", pg_zero_zero),
    ("ratfunc-canon cancel", rf_g),
    ("ratfunc-canon sum", rf_sum),
    ("roots sqrt2", ri_sqrt2),
    ("roots endpoint hit", ri_endpoint),
    ("roots constant", ri_const),
    ("roots multiple root", ri_multiple),
]

for label, golden in GOLDENS:
    expect_accept(label, golden)

# ---------------------------------------------------------------------------
# sympy cross-check: 10 seeded random poly-canon certificates whose
# canonical coefficients come from sympy — the verifier must agree.
# ---------------------------------------------------------------------------
rng = random.Random(20260816)


def rand_poly_expr(max_deg: int) -> str:
    deg = rng.randint(1, max_deg)
    coeffs = [rng.randint(-9, 9) for _ in range(deg)] + [rng.choice([-9, -3, -1, 1, 2, 5, 9])]
    terms = [f"({c})*x^{k}" for k, c in enumerate(coeffs) if c != 0]
    return "+".join(terms) if terms else "0"


for case in range(10):
    expr = f"({rand_poly_expr(4)})*({rand_poly_expr(4)})+({rand_poly_expr(4)})"
    expect_accept(f"sympy cross-check #{case}", sympy_poly_canon_cert(expr))

# ===========================================================================
# Tamper matrix: every load-bearing field mutated one at a time.
# ===========================================================================

def T(label, base, fn, expected=None):
    expect_reject(label, mutated(base, fn), expected)


# --- envelope / JSON layer -------------------------------------------------
T("wrong schema string", xgcd_g, lambda c: c.update(schema="jackal-exact-cert-v2"), "cert-schema")
T("unknown kind", xgcd_g, lambda c: c.update(kind="xgcd2"), "cert-schema")
T("extra top-level key", xgcd_g, lambda c: c.update(extra="1"), "cert-schema")
T("missing witness", xgcd_g, lambda c: c.pop("witness"), "cert-schema")
T("claim not an object", xgcd_g, lambda c: c.update(claim="240"), "cert-schema")
T("bare JSON number", xgcd_g, lambda c: c["claim"].update(a=240), "cert-schema")
expect_reject(
    "duplicate top-level JSON key",
    b'{"claim":{"a":"240","b":"46","g":"2"},"kind":"xgcd",'
    b'"schema":"jackal-exact-cert-v1","witness":{"u":"-9","v":"47"},'
    b'"witness":{"u":"-9","v":"47"}}',
    "cert-json",
)
expect_reject(
    "NaN constant",
    b'{"claim":NaN,"kind":"xgcd","schema":"jackal-exact-cert-v1","witness":{}}',
    "cert-json",
)
expect_reject("oversized certificate", b"x" * (4 * 1024 * 1024 + 1), "cert-json")
expect_reject("not JSON at all", b"exact-cert=hello", "cert-json")

# --- integer / rational form (via xgcd + poly-canon carriers) ---------------
T("int with plus sign", xgcd_g, lambda c: c["claim"].update(a="+240"), "int-malformed")
T("int leading zero", xgcd_g, lambda c: c["claim"].update(a="0240"), "int-malformed")
T("negative zero", xgcd_g, lambda c: c["claim"].update(a="-0"), "int-malformed")
T("int over digit budget", xgcd_g, lambda c: c["claim"].update(a="1" * 4097), "int-budget")
T("non-canonical rational 2/4", pc_rat,
  lambda c: c["claim"].update(coeffs=["2/4", "1/2"]), "rat-not-canonical")
T("rational with denominator 1", ri_sqrt2,
  lambda c: c["claim"].update(intervals=[["-3/2", "-1"], ["1/1", "3/2"]]),
  "rat-not-canonical")

# --- xgcd -------------------------------------------------------------------
T("xgcd flip g", xgcd_g, lambda c: c["claim"].update(g="3"), "xgcd-invalid")
T("xgcd flip u", xgcd_g, lambda c: c["witness"].update(u="-8"), "xgcd-invalid")
T("xgcd flip v", xgcd_g, lambda c: c["witness"].update(v="46"), "xgcd-invalid")
T("xgcd negative g", xgcd_g,
  lambda c: (c["claim"].update(g="-2"), c["witness"].update(u="9", v="-47")),
  "xgcd-invalid")
T("xgcd g zero with nonzero inputs", xgcd_g, lambda c: c["claim"].update(g="0"), "xgcd-invalid")
T("xgcd drop witness u", xgcd_g, lambda c: c["witness"].pop("u"), "cert-schema")
T("xgcd extra claim key", xgcd_g, lambda c: c["claim"].update(gg="2"), "cert-schema")

# --- mod-inv ----------------------------------------------------------------
T("mod-inv flip inv", modinv_g, lambda c: c["claim"].update(inv="4"), "mod-inv-invalid")
T("mod-inv modulus 1", modinv_g, lambda c: c["claim"].update(m="1"), "mod-inv-invalid")
T("mod-inv inv == m", modinv_g, lambda c: c["claim"].update(inv="7"), "mod-inv-invalid")
T("mod-inv negative modulus", modinv_g, lambda c: c["claim"].update(m="-7"), "mod-inv-invalid")

# --- mod-pow ----------------------------------------------------------------
T("mod-pow flip r", modpow_g,
  lambda c: c["claim"].update(r=str((int(modpow_r) + 1) % 19)), "mod-pow-invalid")
T("mod-pow negative exp", modpow_g, lambda c: c["claim"].update(exp="-2"), "mod-pow-invalid")
T("mod-pow r == mod", modpow_g, lambda c: c["claim"].update(r="19"), "mod-pow-invalid")
assert pow(2, 117, 19) != pow(5, 117, 19)  # base flip must be load-bearing
T("mod-pow flip base", modpow_g, lambda c: c["claim"].update(base="2"), "mod-pow-invalid")
T("mod-pow modulus 0", modpow_g, lambda c: c["claim"].update(mod="0"), "mod-pow-invalid")

# --- crt ---------------------------------------------------------------------
T("crt flip x", crt_g, lambda c: c["claim"].update(x=str((crt_x + 1) % crt_m)), "crt-invalid")
T("crt flip M", crt_g, lambda c: c["claim"].update(M=str(crt_m + 1)), "crt-invalid")
T("crt non-coprime moduli", crt_g,
  lambda c: c["claim"]["residues"].__setitem__(1, {"r": "3", "m": "6"}), "crt-invalid")
T("crt single residue", crt_g,
  lambda c: c["claim"].update(residues=c["claim"]["residues"][:1]), "cert-schema")
T("crt seventeen residues", crt_g,
  lambda c: c["claim"].update(residues=c["claim"]["residues"] * 6), "cert-schema")
T("crt x == M", crt_g, lambda c: c["claim"].update(x=str(crt_m)), "crt-invalid")
T("crt residue extra key", crt_g,
  lambda c: c["claim"]["residues"][0].update(s="1"), "cert-schema")

# --- prime / Pratt -----------------------------------------------------------
T("pratt null subcert for q=3", prime97,
  lambda c: c["witness"]["factors"][1].update(cert=None), "pratt-missing-subcert")
T("pratt wrong exponent", prime97,
  lambda c: c["witness"]["factors"][0].update(e="4"), "prime-invalid")
T("pratt witness a=1", prime97, lambda c: c["witness"].update(a="1"), "prime-invalid")
bad_a = next(a for a in range(2, 97) if pow(a, 48, 97) == 1)
T("pratt a with a^((n-1)/q)==1", prime97,
  lambda c: c["witness"].update(a=str(bad_a)), "prime-invalid")
T("pratt duplicate q", prime97,
  lambda c: c["witness"].update(factors=[
      {"q": "2", "e": "4", "cert": None},
      {"q": "2", "e": "1", "cert": None},
      {"q": "3", "e": "1", "cert": {"a": "1", "factors": []}},
  ]), "prime-invalid")
T("prime composite n with 97 witness", prime97,
  lambda c: c["claim"].update(n="91"), "prime-invalid")
T("pratt factor missing cert key", prime97,
  lambda c: c["witness"]["factors"][0].pop("cert"), "cert-schema")

deep = {"a": "2", "factors": []}
for _ in range(70):
    deep = {"a": "2", "factors": [{"q": "7", "e": "1", "cert": deep}]}
expect_reject("pratt depth bomb", cert("prime", {"n": "29"}, deep), "pratt-budget")

wide = {"a": "2", "factors": []}
for _ in range(11):
    wide = {"a": "2", "factors": [
        {"q": "7", "e": "1", "cert": copy.deepcopy(wide)},
        {"q": "11", "e": "1", "cert": copy.deepcopy(wide)},
    ]}
expect_reject("pratt node bomb", cert("prime", {"n": "29"}, wide), "pratt-budget")

# --- composite ----------------------------------------------------------------
T("composite divisor 1", composite_g, lambda c: c["witness"].update(divisor="1"), "composite-invalid")
T("composite divisor == n", composite_g, lambda c: c["witness"].update(divisor="91"), "composite-invalid")
T("composite non-divisor", composite_g, lambda c: c["witness"].update(divisor="6"), "composite-invalid")
T("composite prime n", composite_g, lambda c: c["claim"].update(n="97"), "composite-invalid")
T("composite drop divisor", composite_g, lambda c: c["witness"].pop("divisor"), "cert-schema")

# --- poly-canon ----------------------------------------------------------------
T("poly-canon flip coeff", pc_square,
  lambda c: c["claim"].update(coeffs=["1", "3", "1"]), "poly-canon-mismatch")
T("poly-canon wrong degree", pc_square, lambda c: c["claim"].update(degree="3"), "poly-canon-mismatch")
T("poly-canon drop coeff", pc_square,
  lambda c: c["claim"].update(coeffs=["1", "2"]), "poly-canon-mismatch")
T("poly-canon empty coeff list", pc_square, lambda c: c["claim"].update(coeffs=[]), "cert-schema")
T("poly-canon foreign variable", pc_square, lambda c: c["claim"].update(expr="y+1"), "poly-fragment")
T("poly-canon non-constant divisor", pc_square, lambda c: c["claim"].update(expr="x/x"), "poly-fragment")
T("poly-canon zero-constant divisor", pc_square, lambda c: c["claim"].update(expr="1/0"), "poly-fragment")
T("poly-canon negative exponent", pc_square, lambda c: c["claim"].update(expr="x^-2"), "poly-fragment")
T("poly-canon fractional exponent", pc_square, lambda c: c["claim"].update(expr="x^1.5"), "poly-fragment")
T("poly-canon chained exponent", pc_square, lambda c: c["claim"].update(expr="x^2^3"), "poly-fragment")
T("poly-canon function call", pc_square, lambda c: c["claim"].update(expr="sin(x)"), "poly-fragment")
T("poly-canon empty expr", pc_square, lambda c: c["claim"].update(expr=""), "poly-fragment")
T("poly-canon exponent 65", pc_square, lambda c: c["claim"].update(expr="x^65"), "poly-budget")
T("poly-canon expanded degree 65", pc_square,
  lambda c: c["claim"].update(expr="(x+1)^64*(x+1)"), "poly-budget")
T("poly-canon bare dot literal", pc_square, lambda c: c["claim"].update(expr="x+1."), "poly-fragment")

# --- poly-eq --------------------------------------------------------------------
T("poly-eq flip equal", pe_true, lambda c: c["claim"].update(equal=False), "poly-eq-mismatch")
T("poly-eq flip equal (false golden)", pe_false,
  lambda c: c["claim"].update(equal=True), "poly-eq-mismatch")
T("poly-eq tamper lhs witness", pe_true,
  lambda c: c["witness"].update(lhs_coeffs=["1", "2", "2"]), "poly-eq-mismatch")
T("poly-eq tamper rhs witness", pe_true,
  lambda c: c["witness"].update(rhs_coeffs=["1", "2"]), "poly-eq-mismatch")

# --- poly-gcd --------------------------------------------------------------------
T("poly-gcd flip coeff", pg_g, lambda c: c["claim"].update(gcd_coeffs=["1", "1"]), "poly-gcd-mismatch")
T("poly-gcd non-monic claim", pg_g,
  lambda c: c["claim"].update(gcd_coeffs=["-2", "2"]), "poly-gcd-mismatch")
T("poly-gcd constant claim", pg_g, lambda c: c["claim"].update(gcd_coeffs=["1"]), "poly-gcd-mismatch")

# --- ratfunc-canon ----------------------------------------------------------------
T("ratfunc flip num coeff", rf_g,
  lambda c: c["claim"].update(num_coeffs=["1", "1"]), "ratfunc-canon-mismatch")
T("ratfunc flip den coeff", rf_sum,
  lambda c: c["claim"].update(den_coeffs=["1", "0", "1"]), "ratfunc-canon-mismatch")
T("ratfunc wrong side_condition", rf_g,
  lambda c: c["claim"].update(side_condition="denominator-positive"), "cert-schema")
T("ratfunc zero-polynomial divisor", rf_g,
  lambda c: c["claim"].update(expr="x/(x-x)"), "ratfunc-zero-den")
T("ratfunc non-canonical num", rf_g,
  lambda c: c["claim"].update(num_coeffs=["-2/2", "1"]), "rat-not-canonical")
T("ratfunc non-monic den claim", rf_sum,
  lambda c: c["claim"].update(den_coeffs=["-2", "0", "2"]), "ratfunc-canon-mismatch")

# --- roots-isolate ------------------------------------------------------------------
T("roots unsorted intervals", ri_sqrt2,
  lambda c: c["claim"].update(intervals=[["1", "3/2"], ["-3/2", "-1"]]), "roots-invalid")
T("roots overlapping intervals", ri_sqrt2,
  lambda c: c["claim"].update(intervals=[["-3/2", "1"], ["-1", "3/2"]]), "roots-invalid")
T("roots count/interval mismatch", ri_sqrt2,
  lambda c: c["claim"].update(distinct_real_roots="1"), "roots-invalid")
T("roots undercount", ri_sqrt2,
  lambda c: c["claim"].update(distinct_real_roots="1", intervals=[["1", "3/2"]]),
  "roots-invalid")
T("roots empty interval region", ri_sqrt2,
  lambda c: c["claim"].update(intervals=[["-3/2", "-1"], ["1", "7/5"]]), "roots-invalid")
T("roots interval a > b", ri_sqrt2,
  lambda c: c["claim"].update(intervals=[["-1", "-3/2"], ["1", "3/2"]]), "roots-invalid")
T("roots left endpoint is root", ri_endpoint,
  lambda c: c["claim"].update(intervals=[["-2", "0"], ["1", "2"]]), "roots-invalid")
T("roots zero polynomial", ri_const,
  lambda c: c["claim"].update(expr="x-x"), "roots-invalid")
T("roots interval arity 3", ri_sqrt2,
  lambda c: c["claim"].update(intervals=[["-3/2", "-1", "0"], ["1", "3/2"]]), "cert-schema")
T("roots two roots in one interval", ri_endpoint,
  lambda c: c["claim"].update(intervals=[["-5/2", "5/2"], ["3", "4"]]), "roots-invalid")

# ---------------------------------------------------------------------------
# Isolation discipline: without -I -S the verifier must refuse (exit 126).
# ---------------------------------------------------------------------------
iso = run_verifier(ser(xgcd_g), isolated=False)
if iso.returncode != 126:
    failures.append(f"isolation check: expected exit 126, got {iso.returncode}")
iso_partial = subprocess.run(
    [sys.executable, "-I", "-B", str(VERIFIER), "-"],
    input=ser(xgcd_g),
    capture_output=True,
)
if iso_partial.returncode != 126:
    failures.append(f"isolation check (-I only): expected exit 126, got {iso_partial.returncode}")

# ---------------------------------------------------------------------------
# Verdict
# ---------------------------------------------------------------------------
if failures:
    for line in failures:
        print(f"FAIL: {line}", file=sys.stderr)
    print(f"EXACT_VERIFY_TEST_FAIL failures={len(failures)}")
    raise SystemExit(1)

print(f"EXACT_VERIFY_TEST_PASS positives={positives} tampers={tampers}")
raise SystemExit(0)
