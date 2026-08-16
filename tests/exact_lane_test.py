#!/usr/bin/env python3
"""Black-box oracle test for the JACKAL CERTIFIED EXACT ALGEBRA lanes.

Drives the engine strictly through its CLI and checks every answer against an
independent oracle (Python ints/Fraction/math.gcd + sympy). Every emitted
jackal-exact-cert-v1 line must round-trip json.loads and carry EXACTLY the
contract's key sets (early drift detection ahead of tools/exact_verify.py);
bare JSON numbers anywhere in a certificate are a failure (all numbers are
decimal strings; the poly-eq "equal" boolean is the one non-string scalar).

Engine resolution:
  1. $JACKAL_BIN, if set, is invoked directly for every case (the lead may
     point it at a rebuilt ./jackal-native).
  2. Otherwise the ./jackal launcher is warmed once with JACKAL_FORCE_SOURCE=1
     (never the possibly-stale jackal-native) and the compiled artifact
     $JACKAL_OUT/anubis_run is used for the ~2.3k case invocations; if that
     artifact is missing the launcher itself is used per-case (slow but same
     bytes).

Pass criterion: prints "EXACT_LANE_PASS cases=<n>" and exits 0. Any oracle
mismatch prints the case and exits 1. Seeded (20260816), fully deterministic.
"""

import hashlib
import json
import math
import os
import random
import subprocess
import sys
from fractions import Fraction
from pathlib import Path

import sympy
from sympy import symbols

X = symbols("x")
ROOT = Path(__file__).resolve().parent.parent
SEED = 20260816
RNG = random.Random(SEED)

CASES = 0


def fail(case, detail):
    print(f"EXACT_LANE_FAIL case={case}")
    print(f"  {detail}")
    sys.exit(1)


def ok():
    global CASES
    CASES += 1


# --------------------------------------------------------------------------
# engine plumbing
# --------------------------------------------------------------------------

RUN_ARGV = None
RUN_ENV = None


def resolve_engine():
    global RUN_ARGV, RUN_ENV
    override = os.environ.get("JACKAL_BIN")
    if override:
        RUN_ARGV = [override]
        RUN_ENV = dict(os.environ)
        print(f"engine: JACKAL_BIN override -> {override}")
        return
    launcher = str(ROOT / "jackal")
    out_dir = os.environ.get("JACKAL_OUT", "/tmp/jackal-exact-lane-build")
    env = dict(os.environ)
    env.setdefault("JACKAL_FORCE_SOURCE", "1")  # never the stale jackal-native
    env["JACKAL_OUT"] = out_dir
    warm = subprocess.run(
        [launcher, "self-test"], capture_output=True, text=True, env=env, timeout=1800
    )
    if warm.returncode != 0:
        fail("engine-warmup", f"launcher self-test failed rc={warm.returncode}\n{warm.stderr[-2000:]}")
    if "invariants pass" not in warm.stdout:
        fail("engine-warmup", f"unexpected self-test stdout: {warm.stdout!r}")
    fast = Path(out_dir) / "anubis_run"
    if fast.is_file() and os.access(fast, os.X_OK):
        RUN_ARGV = [str(fast)]
        print(f"engine: compiled artifact {fast} (warmed from source via launcher)")
    else:
        RUN_ARGV = [launcher]
        print("engine: launcher per-case (compiled artifact not found; slow path)")
    RUN_ENV = env


def run(*args, timeout=300):
    proc = subprocess.run(
        RUN_ARGV + [str(a) for a in args],
        capture_output=True,
        text=True,
        env=RUN_ENV,
        timeout=timeout,
    )
    return proc.returncode, proc.stdout, proc.stderr


def run_ok(case, *args):
    rc, out, err = run(*args)
    if rc != 0:
        fail(case, f"expected exit 0, got {rc}; stderr tail: {err[-500:]}")
    return out


def expect_refusal(case, reasons, *args):
    rc, out, err = run(*args)
    if rc == 0:
        fail(case, f"expected a refusal, got exit 0 with stdout: {out!r}")
    if not any(r in err for r in reasons):
        fail(case, f"nonzero exit but no named reason {reasons} on stderr: {err[-500:]}")
    ok()


# --------------------------------------------------------------------------
# certificate schema validation (jackal-exact-cert-v1, frozen contract)
# --------------------------------------------------------------------------

def _reject_bare_number(s):
    raise ValueError(f"bare JSON number in certificate: {s!r}")


CLAIM_WITNESS_KEYS = {
    "xgcd": ({"a", "b", "g"}, {"u", "v"}),
    "mod-inv": ({"a", "inv", "m"}, set()),
    "mod-pow": ({"base", "exp", "mod", "r"}, set()),
    "crt": ({"M", "residues", "x"}, set()),
    "composite": ({"n"}, {"divisor"}),
    "prime": ({"n"}, None),  # witness is a Pratt node, checked recursively
    "poly-canon": ({"coeffs", "degree", "expr"}, set()),
    "poly-eq": ({"equal", "lhs", "rhs"}, {"lhs_coeffs", "rhs_coeffs"}),
    "poly-gcd": ({"gcd_coeffs", "lhs", "rhs"}, set()),
    "ratfunc-canon": ({"den_coeffs", "expr", "num_coeffs", "side_condition"}, set()),
    "roots-isolate": ({"distinct_real_roots", "expr", "intervals"}, set()),
}


def check_pratt_node_shape(case, node):
    if set(node.keys()) != {"a", "factors"}:
        fail(case, f"pratt node keys {sorted(node)} != ['a', 'factors']")
    if not isinstance(node["a"], str) or not isinstance(node["factors"], list):
        fail(case, "pratt node field types wrong")
    for f in node["factors"]:
        if set(f.keys()) != {"cert", "e", "q"}:
            fail(case, f"pratt factor keys {sorted(f)} != ['cert', 'e', 'q']")
        if not isinstance(f["e"], str) or not isinstance(f["q"], str):
            fail(case, "pratt factor q/e must be strings")
        if f["cert"] is not None:
            check_pratt_node_shape(case, f["cert"])


def parse_cert(case, stdout, kind):
    lines = stdout.rstrip("\n").split("\n")
    last = lines[-1]
    if not last.startswith("exact-cert="):
        fail(case, f"final stdout line is not the certificate: {last!r}")
    try:
        cert = json.loads(
            last[len("exact-cert="):],
            parse_float=_reject_bare_number,
            parse_int=_reject_bare_number,
            parse_constant=_reject_bare_number,
        )
    except ValueError as e:
        fail(case, f"certificate does not round-trip json.loads: {e}")
    if set(cert.keys()) != {"claim", "kind", "schema", "witness"}:
        fail(case, f"top-level keys {sorted(cert)} != [claim, kind, schema, witness]")
    if cert["schema"] != "jackal-exact-cert-v1":
        fail(case, f"schema {cert['schema']!r}")
    if cert["kind"] != kind:
        fail(case, f"kind {cert['kind']!r} != {kind!r}")
    claim_keys, witness_keys = CLAIM_WITNESS_KEYS[kind]
    if set(cert["claim"].keys()) != claim_keys:
        fail(case, f"claim keys {sorted(cert['claim'])} != {sorted(claim_keys)}")
    if witness_keys is None:
        check_pratt_node_shape(case, cert["witness"])
    elif set(cert["witness"].keys()) != witness_keys:
        fail(case, f"witness keys {sorted(cert['witness'])} != {sorted(witness_keys)}")
    if kind == "crt":
        for item in cert["claim"]["residues"]:
            if set(item.keys()) != {"m", "r"}:
                fail(case, f"crt residue keys {sorted(item)} != ['m', 'r']")
    return cert


# --------------------------------------------------------------------------
# rational-string helpers (contract rendering: "3" not "3/1", den > 0)
# --------------------------------------------------------------------------

def frac_of_str(case, s):
    if not isinstance(s, str):
        fail(case, f"expected a decimal string, got {type(s).__name__}: {s!r}")
    try:
        f = Fraction(s)
    except ValueError:
        fail(case, f"malformed rational string {s!r}")
    # canonical rendering check
    if str_of_frac(f) != s:
        fail(case, f"non-canonical rational string {s!r}")
    return f


def str_of_frac(f):
    f = Fraction(f)
    return str(f.numerator) if f.denominator == 1 else f"{f.numerator}/{f.denominator}"


def sympy_rat_str(c):
    c = sympy.Rational(c)
    return str(c.p) if c.q == 1 else f"{c.p}/{c.q}"


# --------------------------------------------------------------------------
# sympy poly oracles (the verifier-side view of the engine grammar)
# --------------------------------------------------------------------------

def sympy_expr(expr):
    return sympy.sympify(expr.replace("^", "**"), rational=True)


def sympy_canon_coeffs(expr):
    """Ascending canonical Q[x] coefficient strings + degree, sympy-computed."""
    e = sympy.expand(sympy_expr(expr))
    if e == 0:
        return ["0"], -1
    p = sympy.Poly(e, X, domain="QQ")
    coeffs = list(reversed(p.all_coeffs()))
    return [sympy_rat_str(c) for c in coeffs], p.degree()


def sympy_ratfunc_canon(expr):
    """(num_coeff_strs, den_coeff_strs) with gcd(P,Q)=1 and Q monic."""
    e = sympy.cancel(sympy.together(sympy_expr(expr)))
    num, den = sympy.fraction(e)
    pn = sympy.Poly(num, X, domain="QQ")
    pd = sympy.Poly(den, X, domain="QQ")
    if pn.is_zero:
        return ["0"], ["1"]
    lc = pd.LC()
    ncs = [sympy_rat_str(c / lc) for c in reversed(pn.all_coeffs())]
    dcs = [sympy_rat_str(c / lc) for c in reversed(pd.all_coeffs())]
    return ncs, dcs


def poly_to_expr(coeffs):
    """Ascending Fraction list -> engine-grammar expression string."""
    terms = []
    for k, c in enumerate(coeffs):
        if c == 0:
            continue
        mag = abs(Fraction(c))
        if k == 0:
            body = str_of_frac(mag)
        else:
            xp = "x" if k == 1 else f"x^{k}"
            body = xp if mag == 1 else f"{str_of_frac(mag)}*{xp}"
        terms.append((c < 0, body))
    if not terms:
        return "0"
    out = []
    for i, (neg, body) in enumerate(terms):
        if i == 0:
            out.append(("-" if neg else "") + body)
        else:
            out.append(("-" if neg else "+") + body)
    return "".join(out)


# --------------------------------------------------------------------------
# lane 1: xgcd / mod-pow / mod-inv / crt vs Python oracles
# --------------------------------------------------------------------------

def rand_signed(digits):
    v = RNG.randint(10 ** (digits - 1), 10 ** digits - 1)
    return -v if RNG.random() < 0.5 else v


def gen_int_cases():
    vals = [0, 1, -1, 2, -2, 240, -46]
    for d in (3, 6, 12, 20, 40, 100):
        vals.append(rand_signed(d))
        vals.append(rand_signed(d))
    return vals


def test_xgcd():
    pool = gen_int_cases()
    pairs = [(0, 0), (0, 7), (-12, 0)]
    while len(pairs) < 40:
        pairs.append((RNG.choice(pool), RNG.choice(pool)))
    for a, b in pairs:
        case = f"xgcd {a} {b}"
        out = run_ok(case, "xgcd", a, b)
        cert = parse_cert(case, out, "xgcd")
        ca = int(cert["claim"]["a"]); cb = int(cert["claim"]["b"])
        g = int(cert["claim"]["g"])
        u = int(cert["witness"]["u"]); v = int(cert["witness"]["v"])
        if (ca, cb) != (a, b):
            fail(case, f"claim echoes ({ca},{cb}) != inputs")
        if g != math.gcd(a, b):
            fail(case, f"g={g} != math.gcd={math.gcd(a, b)}")
        if u * a + v * b != g:
            fail(case, f"Bezout identity fails: {u}*{a}+{v}*{b} != {g}")
        if g < 0 or (g == 0) != (a == 0 and b == 0):
            fail(case, f"g sign/zero convention violated: g={g}")
        if not out.split("\n")[0].startswith("status=exact "):
            fail(case, f"human line: {out.splitlines()[0]!r}")
        ok()


def test_mod_pow():
    pool = gen_int_cases()
    triples = [(0, 0, 1), (5, 0, 7), (-2, 3, 5), (2, 10, 1)]
    while len(triples) < 40:
        b = RNG.choice(pool)
        e = abs(RNG.choice(pool))
        m = abs(RNG.choice(pool)) or 1
        triples.append((b, e, m))
    for b, e, m in triples:
        case = f"mod-pow {b} {e} {m}"
        out = run_ok(case, "mod-pow", b, e, m)
        cert = parse_cert(case, out, "mod-pow")
        r = int(cert["claim"]["r"])
        expect = pow(b, e, m)
        if r != expect:
            fail(case, f"r={r} != pow oracle {expect}")
        if not (0 <= r < m):
            fail(case, f"r={r} outside [0,{m})")
        if (int(cert["claim"]["base"]), int(cert["claim"]["exp"]), int(cert["claim"]["mod"])) != (b, e, m):
            fail(case, "claim echo mismatch")
        ok()
    expect_refusal("mod-pow negative exponent", ["nonnegative"], "mod-pow", 2, -3, 7)
    expect_refusal("mod-pow zero modulus", ["modulus"], "mod-pow", 2, 3, 0)


def test_mod_inv():
    attempts = [(3, 7), (12345, 1000003), (-5, 9)]
    while len(attempts) < 35:
        digits = RNG.choice([2, 4, 8, 15, 40, 100])
        a = rand_signed(RNG.choice([2, 4, 8, 15, 40, 100]))
        m = abs(rand_signed(digits)) + 2
        if math.gcd(a, m) != 1:
            continue
        attempts.append((a, m))
    for a, m in attempts:
        case = f"mod-inv {a} {m}"
        out = run_ok(case, "mod-inv", a, m)
        cert = parse_cert(case, out, "mod-inv")
        inv = int(cert["claim"]["inv"])
        if inv != pow(a, -1, m):
            fail(case, f"inv={inv} != pow(a,-1,m)={pow(a, -1, m)}")
        if not (0 <= inv < m) or (a * inv) % m != 1:
            fail(case, f"inverse property fails: inv={inv}")
        ok()
    # refusals: shared factor
    for a, m in [(6, 9), (10, 1000), (0, 5), (2, 2), (-4, 8)]:
        expect_refusal(f"mod-inv non-coprime {a} {m}", ["mod-inv-not-coprime"], "mod-inv", a, m)


def crt_oracle(rs, ms):
    x, M = rs[0] % ms[0], ms[0]
    for r, m in zip(rs[1:], ms[1:]):
        t = ((r - x) * pow(M, -1, m)) % m
        x += M * t
        M *= m
    return x % M, M


def test_crt():
    prime_pool = [sympy.prime(i) for i in range(1, 120)]
    made = 0
    for i in range(37):
        k = RNG.randint(2, 6) if i < 35 else 16
        picks = RNG.sample(prime_pool, k)
        ms = [p ** RNG.randint(1, 2) for p in picks]
        rs = [RNG.randint(-2 * m, 2 * m) for m in ms]
        case = f"crt#{i} k={k}"
        args = []
        for r, m in zip(rs, ms):
            args += [r, m]
        out = run_ok(case, "crt", *args)
        cert = parse_cert(case, out, "crt")
        x = int(cert["claim"]["x"]); M = int(cert["claim"]["M"])
        ex, eM = crt_oracle(rs, ms)
        if (x, M) != (ex, eM):
            fail(case, f"(x,M)=({x},{M}) != oracle ({ex},{eM})")
        for item, (r, m) in zip(cert["claim"]["residues"], zip(rs, ms)):
            if int(item["r"]) != r or int(item["m"]) != m:
                fail(case, "residue echo mismatch")
        if not (0 <= x < M):
            fail(case, f"x={x} outside [0,M)")
        made += 1
        ok()
    if made < 37:
        fail("crt-generation", f"only {made} cases")
    expect_refusal("crt non-coprime", ["crt-not-coprime"], "crt", 1, 4, 1, 6)
    expect_refusal("crt too many pairs", ["int-budget"], "crt", *([1, 0] * 0 + sum(([i, p] for i, p in enumerate([sympy.prime(j) for j in range(1, 18)])), [])))
    expect_refusal("crt one pair", ["crt"], "crt", 1, 5)


def test_divides():
    cases = [(7, -49, True), (0, 5, False), (0, 0, True), (-3, 10, False), (25, 5, False), (13, 13 * 10**50, True)]
    for a, b, expect in cases:
        case = f"divides {a} {b}"
        out = run_ok(case, "divides", a, b)
        line = out.strip().split("\n")[-1]
        want = f"status=exact divides={'true' if expect else 'false'}"
        if line != want:
            fail(case, f"{line!r} != {want!r}")
        ok()


# --------------------------------------------------------------------------
# lane 2: prime-cert vs sympy.isprime + full independent Pratt verification
# --------------------------------------------------------------------------

def verify_pratt(case, n, node):
    if n in (2, 3):
        return  # base case accepted directly
    a = int(node["a"])
    n1 = n - 1
    prod = 1
    qs = []
    for f in node["factors"]:
        q, e = int(f["q"]), int(f["e"])
        if q < 2 or e < 1:
            fail(case, f"bad factor q={q} e={e}")
        prod *= q ** e
        qs.append(q)
        if q == 2:
            if f["cert"] is not None:
                verify_pratt(case, 2, f["cert"])
        else:
            if f["cert"] is None:
                fail(case, f"missing subcert for q={q}")
            verify_pratt(case, q, f["cert"])
    if len(set(qs)) != len(qs):
        fail(case, f"duplicate factor bases {qs}")
    if prod != n1:
        fail(case, f"prod(q^e)={prod} != n-1={n1}")
    if not (2 <= a < n):
        fail(case, f"witness a={a} outside [2,n)")
    if pow(a, n1, n) != 1:
        fail(case, f"a^(n-1) != 1 mod n for a={a}")
    for q in qs:
        if pow(a, n1 // q, n) == 1:
            fail(case, f"a^((n-1)/{q}) == 1 mod n; order not n-1")


def check_prime_cert(n):
    case = f"prime-cert {n}"
    out = run_ok(case, "prime-cert", n)
    first = out.split("\n")[0]
    expect_prime = sympy.isprime(n)
    if expect_prime:
        if "verdict=prime" not in first:
            fail(case, f"sympy says prime, engine: {first!r}")
        cert = parse_cert(case, out, "prime")
        if int(cert["claim"]["n"]) != n:
            fail(case, "claim n mismatch")
        verify_pratt(case, n, cert["witness"])
    else:
        if "verdict=composite" not in first:
            fail(case, f"sympy says composite, engine: {first!r}")
        cert = parse_cert(case, out, "composite")
        if int(cert["claim"]["n"]) != n:
            fail(case, "claim n mismatch")
        d = int(cert["witness"]["divisor"])
        if not (1 < d < n) or n % d != 0:
            fail(case, f"divisor {d} does not witness compositeness of {n}")
    ok()


def test_prime_cert():
    for n in range(2, 2001):
        check_prime_cert(n)
    for _ in range(20):
        check_prime_cert(RNG.randint(10 ** 11, 10 ** 12 - 1))
    for n in [1000003, 10 ** 18 + 9, 561, 1105, 1729, 41041, 825265, 321197185, 2, 3, 4]:
        check_prime_cert(n)
    # Carmichael numbers MUST come out composite (they did, via sympy match,
    # but assert the verdict explicitly rather than trusting the loop above).
    for n in [561, 1105, 1729, 41041, 825265, 321197185]:
        rc, out, _ = run("prime-cert", n)
        if rc != 0 or "verdict=composite" not in out:
            fail(f"carmichael {n}", f"rc={rc} out={out!r}")
        ok()


# --------------------------------------------------------------------------
# lane 3: poly-canon / poly-eq / poly-gcd / ratfunc-canon vs sympy
# --------------------------------------------------------------------------

def rand_coeff():
    if RNG.random() < 0.5:
        return Fraction(RNG.randint(-9, 9))
    return Fraction(RNG.randint(-9, 9), RNG.randint(1, 9))


def rand_poly(max_deg, nonzero=True):
    deg = RNG.randint(0, max_deg)
    coeffs = [rand_coeff() for _ in range(deg + 1)]
    while coeffs and coeffs[-1] == 0:
        coeffs[-1] = rand_coeff()
    if nonzero and all(c == 0 for c in coeffs):
        coeffs[0] = Fraction(1)
    return coeffs


def check_poly_canon(expr):
    case = f"poly-canon {expr!r}"
    out = run_ok(case, "poly-canon", expr)
    cert = parse_cert(case, out, "poly-canon")
    want_coeffs, want_deg = sympy_canon_coeffs(expr)
    got = cert["claim"]["coeffs"]
    for s in got:
        frac_of_str(case, s)
    if got != want_coeffs or int(cert["claim"]["degree"]) != want_deg:
        fail(case, f"coeffs {got} deg {cert['claim']['degree']} != sympy {want_coeffs} deg {want_deg}")
    if cert["claim"]["expr"] != expr:
        fail(case, "expr echo mismatch")
    ok()


def check_poly_eq(lhs, rhs):
    case = f"poly-eq {lhs!r} {rhs!r}"
    out = run_ok(case, "poly-eq", lhs, rhs)
    cert = parse_cert(case, out, "poly-eq")
    lw, _ = sympy_canon_coeffs(lhs)
    rw, _ = sympy_canon_coeffs(rhs)
    expect = lw == rw
    if cert["claim"]["equal"] is not expect:
        fail(case, f"equal={cert['claim']['equal']} but sympy says {expect}")
    if cert["witness"]["lhs_coeffs"] != lw or cert["witness"]["rhs_coeffs"] != rw:
        fail(case, f"witness coeffs disagree with sympy recompute")
    human = out.split("\n")[0]
    if human != f"status=exact equal={'true' if expect else 'false'}":
        fail(case, f"human line {human!r}")
    ok()
    return out


def check_poly_gcd(lhs, rhs):
    case = f"poly-gcd {lhs!r} {rhs!r}"
    out = run_ok(case, "poly-gcd", lhs, rhs)
    cert = parse_cert(case, out, "poly-gcd")
    el, er = sympy_expr(lhs), sympy_expr(rhs)
    g = sympy.gcd(el, er)
    if g == 0:
        want = ["0"]
    else:
        pg = sympy.Poly(sympy.expand(g), X, domain="QQ").monic()
        want = [sympy_rat_str(c) for c in reversed(pg.all_coeffs())]
    if cert["claim"]["gcd_coeffs"] != want:
        fail(case, f"gcd {cert['claim']['gcd_coeffs']} != sympy monic gcd {want}")
    ok()


def check_ratfunc(expr):
    case = f"ratfunc-canon {expr!r}"
    out = run_ok(case, "ratfunc-canon", expr)
    cert = parse_cert(case, out, "ratfunc-canon")
    wn, wd = sympy_ratfunc_canon(expr)
    if cert["claim"]["num_coeffs"] != wn or cert["claim"]["den_coeffs"] != wd:
        fail(case, f"({cert['claim']['num_coeffs']},{cert['claim']['den_coeffs']}) != sympy ({wn},{wd})")
    if cert["claim"]["side_condition"] != "denominator-nonzero":
        fail(case, "side_condition drifted")
    if "side-condition=denominator-nonzero" not in out.split("\n")[0]:
        fail(case, "human line lacks side condition")
    ok()


def test_poly_lanes():
    # fixed counterexample set
    check_poly_eq("(x+1)^2", "x^2+2*x+1")
    check_poly_eq("x^2-1", "(x-1)^2")
    check_ratfunc("(x^2-1)/(x-1)")
    check_poly_canon("0*x")
    check_poly_canon("x^12/3-0.5")
    # >= 30 seeded identities and non-identities (degree <= 12)
    for i in range(15):
        a = rand_poly(6)
        b = rand_poly(6)
        lhs = f"({poly_to_expr(a)})*({poly_to_expr(b)})"
        prod = sympy.expand(sympy_expr(lhs))
        if prod == 0:
            rhs = "0"
        else:
            p = sympy.Poly(prod, X, domain="QQ")
            rhs = poly_to_expr([Fraction(c.p, c.q) for c in map(sympy.Rational, reversed(p.all_coeffs()))])
        check_poly_eq(lhs, rhs)
    for i in range(15):
        a = rand_poly(6)
        b = rand_poly(6)
        lhs = f"({poly_to_expr(a)})*({poly_to_expr(b)})"
        prod = sympy.expand(sympy_expr(lhs))
        coeffs = [Fraction(0)] if prod == 0 else [
            Fraction(c.p, c.q) for c in map(sympy.Rational, reversed(sympy.Poly(prod, X, domain="QQ").all_coeffs()))
        ]
        k = RNG.randrange(len(coeffs))
        coeffs[k] += RNG.choice([Fraction(1), Fraction(-1), Fraction(1, 7)])
        check_poly_eq(lhs, poly_to_expr(coeffs))
    for i in range(8):
        check_poly_canon(poly_to_expr(rand_poly(12)))
    for i in range(5):
        c = rand_poly(3)
        a = rand_poly(3)
        b = rand_poly(3)
        lhs = f"({poly_to_expr(a)})*({poly_to_expr(c)})"
        rhs = f"({poly_to_expr(b)})*({poly_to_expr(c)})"
        check_poly_gcd(lhs, rhs)
    for i in range(5):
        n = rand_poly(4)
        d = rand_poly(3)
        check_ratfunc(f"({poly_to_expr(n)})/({poly_to_expr(d)})")


# --------------------------------------------------------------------------
# lane 4: roots-isolate vs sympy real_roots
# --------------------------------------------------------------------------

def check_roots(expr):
    case = f"roots-isolate {expr!r}"
    out = run_ok(case, "roots-isolate", expr)
    cert = parse_cert(case, out, "roots-isolate")
    k = int(cert["claim"]["distinct_real_roots"])
    intervals = cert["claim"]["intervals"]
    if len(intervals) != k:
        fail(case, f"k={k} but {len(intervals)} intervals")
    e = sympy.expand(sympy_expr(expr))
    p = sympy.Poly(e, X, domain="QQ")
    roots = p.real_roots()
    distinct = []
    for r in roots:
        if not distinct or r != distinct[-1]:
            distinct.append(r)
    if k != len(distinct):
        fail(case, f"engine k={k} != sympy distinct real roots {len(distinct)}")
    ivs = []
    prev_b = None
    for a_s, b_s in intervals:
        a = sympy.Rational(a_s)
        b = sympy.Rational(b_s)
        if a > b:
            fail(case, f"interval [{a_s},{b_s}] reversed")
        if prev_b is not None and not (prev_b < a):
            fail(case, f"intervals not strictly ordered at [{a_s},{b_s}]")
        prev_b = b
        ivs.append((a, b))
    for r in distinct:
        holders = [i for i, (a, b) in enumerate(ivs) if a < r and r <= b]
        if len(holders) != 1:
            fail(case, f"root {r} lies in {len(holders)} intervals, want exactly 1")
    ok()


def test_roots():
    check_roots("x^2-2")
    check_roots("(x-1)^2*(x+2)")       # distinct roots: 2
    check_roots("x^3-2*x+1/2")
    check_roots("63/8*x^5-70/8*x^3+15/8*x")  # legendre-like wiggle, 5 roots
    check_roots("(x^2-2)*(x-3)")
    check_roots("x^2+1")               # no real roots
    check_roots("7")                   # constant: no roots
    made = 0
    while made < 20:
        deg = RNG.randint(1, 8)
        coeffs = [Fraction(RNG.randint(-20, 20)) for _ in range(deg + 1)]
        if all(c == 0 for c in coeffs):
            continue
        check_roots(poly_to_expr(coeffs))
        made += 1


# --------------------------------------------------------------------------
# lane 5: alg-sign / alg-cmp
# --------------------------------------------------------------------------

def test_alg():
    for expr, at, want in [
        ("x^2-2", "3/2", 1),
        ("x^2-2", "7/5", -1),
        ("x^2-2", "-3/2", 1),
        ("x-3/2", "3/2", 0),
        ("x^3-1/2", "1/2", -1),
    ]:
        case = f"alg-sign {expr!r} {at}"
        out = run_ok(case, "alg-sign", expr, at)
        line = out.strip().split("\n")[-1]
        if line != f"status=exact sign={want}":
            fail(case, f"{line!r}, want sign={want}")
        ok()
    for args, want in [
        (("x^2-2", "1", "3/2", "x^2-3", "3/2", "2"), "less"),
        (("x^2-4", "1", "3", "x-2", "3/2", "5/2"), "equal"),
        (("x^2-3", "3/2", "2", "x^2-2", "1", "3/2"), "greater"),
    ]:
        case = f"alg-cmp {args}"
        out = run_ok(case, "alg-cmp", *args)
        line = out.strip().split("\n")[-1]
        if line != f"status=exact order={want}":
            fail(case, f"{line!r}, want order={want}")
        ok()
    expect_refusal(
        "alg-cmp not isolating", ["alg-cmp-not-isolating"],
        "alg-cmp", "x^2-2", "-5", "5", "x-1", "0", "2",
    )


# --------------------------------------------------------------------------
# lane 6: canon (sexp + sha256, no cert JSON)
# --------------------------------------------------------------------------

def test_canon():
    for expr in ["x^2 + 2*x + 1", "sin(x)*ln(x)"]:
        case = f"canon {expr!r}"
        out = run_ok(case, "canon", expr).strip()
        if not out.startswith("status=exact canonical="):
            fail(case, f"unexpected line {out!r}")
        body, _, sha = out.rpartition(" sha256=")
        sexp = body[len("status=exact canonical="):]
        if hashlib.sha256(sexp.encode()).hexdigest() != sha.lower():
            fail(case, f"sha256 does not match the printed sexp")
        ok()


# --------------------------------------------------------------------------
# lane 7: budget refusals — nonzero exit + named reason, never a wrong answer
# --------------------------------------------------------------------------

def test_budgets():
    expect_refusal("poly degree 65 (pow)", ["poly-budget"], "poly-canon", "x^65")
    expect_refusal("poly degree 65 (mul)", ["poly-budget"], "poly-canon", "x^60*x^5")
    expect_refusal("xgcd 4097-digit", ["int-budget"], "xgcd", "1" * 4097, 5)
    expect_refusal(
        "prime-cert 70-digit", ["prime-cert-budget", "int-budget"],
        "prime-cert", "1" + "0" * 68 + "1",
    )
    expect_refusal("poly fragment: function", ["poly-fragment"], "poly-canon", "sin(x)")
    expect_refusal("poly fragment: constant pi", ["poly-fragment"], "poly-canon", "pi*x")
    expect_refusal("poly fragment: non-constant divisor", ["poly-fragment"], "poly-canon", "x/(x+1)")
    expect_refusal("ratfunc zero denominator", ["ratfunc-zero-den"], "ratfunc-canon", "x/(x-x)")
    expect_refusal("roots zero polynomial", ["roots-zero-poly"], "roots-isolate", "0*x")


# --------------------------------------------------------------------------
# lane 8: determinism — byte-identical stdout across runs
# --------------------------------------------------------------------------

def test_determinism():
    a = run_ok("determinism-run-1", "poly-eq", "(x+1)^2", "x^2+2*x+1")
    b = run_ok("determinism-run-2", "poly-eq", "(x+1)^2", "x^2+2*x+1")
    if a != b:
        fail("determinism", f"stdout differs between runs:\n{a!r}\n{b!r}")
    ok()


def main():
    resolve_engine()
    test_xgcd()
    test_mod_pow()
    test_mod_inv()
    test_crt()
    test_divides()
    test_poly_lanes()
    test_roots()
    test_alg()
    test_canon()
    test_budgets()
    test_determinism()
    test_prime_cert()
    print(f"EXACT_LANE_PASS cases={CASES}")


if __name__ == "__main__":
    main()
