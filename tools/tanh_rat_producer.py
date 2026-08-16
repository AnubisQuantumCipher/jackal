#!/usr/bin/env python3
"""JACKAL v1.5.0 tanh composite cert producer (UNTRUSTED).

tanh is NOT an engine grammar token.  Mathematically,

    tanh(x) = 1 - 2/(exp(2*x) + 1),

and the right-hand side IS inside the engine grammar and inside the pure-ℚ
release fragment once `exp_rat` covers general-sign arguments (§490).  This
producer emits a canonical `jackal-eval-cert v2` EIGHT-node composite
certificate for the exact request

    1-2/(exp(2*x)+1)   on [lower, upper]

in which every node is a zero-libm-TCB release-fragment constructor:
`num_exact`, `var`, `mul`, `exp_rat`, `add`, `div`, `sub`.  This form is
used (rather than `(exp(2x)-1)/(exp(2x)+1)`) because its division has a
CONSTANT numerator: the interval division loses no numerator/denominator
correlation, so the certified enclosure stays tight on arbitrarily wide
input intervals.  The recorded "float" fields are EXACT rationals
(algApproxQ passes with equality), the outward ε/τ pads are applied exactly
as the checker demands, and the div denominator interval is strictly
positive (exp(2x) + 1 > 1).

The released receipt binds the COMPOSITE EXPRESSION STRING, not the name
"tanh"; the tanh reading is a documented mathematical identity, stated in
the wrapper's assumptions — the certificate itself never mentions tanh.

Budget: |lower|, |upper| <= 20 (tanh is within 2^-57 of ±1 beyond that, and
the Taylor degree needed for exp(2x) grows past usefulness).  Refuses
otherwise.  No libm anywhere — not even as a seed.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import math
import sys
from fractions import Fraction
from pathlib import Path


SCHEMA = "jackal-eval-cert v2"
MODEL = "jackal-iv-model-v1"
STATUS = "bounded"
CANONICAL_EXPR = "1-2/(exp(2*x)+1)"
CANONICAL_SEXP = ("(sub (num 1) (div (num 2) "
                  "(add (call exp (mul (num 2) (var x))) (num 1))))")
EPS = Fraction(1, 10 ** 15)
TAU = Fraction(1, 10 ** 300)
ARG_BUDGET = 20


def parse_canonical_rat(tok: str) -> Fraction:
    tok = tok.strip()
    if not tok:
        raise ValueError("empty rational token")
    return Fraction(tok)


def canonical_rat_str(f: Fraction) -> str:
    f = Fraction(f.numerator, f.denominator)
    if f.denominator == 1:
        return str(f.numerator)
    return f"{f.numerator}/{f.denominator}"


def pad_lo(v: Fraction) -> Fraction:
    return v - (EPS * abs(v) + TAU)


def pad_hi(v: Fraction) -> Fraction:
    return v + (EPS * abs(v) + TAU)


def exp_partial(z: Fraction, n: int) -> Fraction:
    total = Fraction(0)
    term = Fraction(1)
    for k in range(n):
        if k > 0:
            term = term * z / k
        total += term
    return total


def exp_remainder(z: Fraction, n: int) -> Fraction:
    return 2 * z ** n / math.factorial(n)


def exp_deg_ok(q: Fraction, n: int) -> bool:
    return n > 0 and 2 * abs(q) <= n + 1


def exp_lbq(q: Fraction, n: int) -> Fraction:
    if q >= 0:
        return exp_partial(q, n)
    z = -q
    return 1 / (exp_partial(z, n) + exp_remainder(z, n))


def exp_ubq(q: Fraction, n: int) -> Fraction:
    if q >= 0:
        return exp_partial(q, n) + exp_remainder(q, n)
    z = -q
    return 1 / exp_partial(z, n)


def request_commitment_b64(command: str, expression: str, lo: str, hi: str) -> str:
    def framed(p: str) -> bytes:
        raw = p.encode("utf-8")
        return f"{len(raw)}:".encode() + raw

    framing = b"jackal-req-v2\x00" + b"|".join(
        framed(p) for p in (command, expression, lo, hi))
    return base64.b64encode(hashlib.sha256(framing).hexdigest().encode()).decode()


def producer_sha256() -> str:
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def emit_cert(expression: str, lower: str, upper: str) -> bytes:
    if expression.replace(" ", "") != CANONICAL_EXPR:
        raise ValueError(
            "tanh composite producer only admits the exact form "
            f"`{CANONICAL_EXPR}` (= tanh(x) mathematically); got {expression!r}")
    a = parse_canonical_rat(lower)
    b = parse_canonical_rat(upper)
    if a > b:
        raise ValueError("upper must be >= lower")
    if abs(a) > ARG_BUDGET or abs(b) > ARG_BUDGET:
        raise ValueError(f"tanh composite budget is |x| <= {ARG_BUDGET}")

    R = canonical_rat_str
    # node 2: mul [2,2] x [a,b] — exact corners, padded out.
    p1, p2 = 2 * a, 2 * b
    mul_lo, mul_hi = pad_lo(min(p1, p2)), pad_hi(max(p1, p2))
    # node 3: exp_rat on [mul_lo, mul_hi].
    n = 24
    while 2 * max(abs(mul_lo), abs(mul_hi)) > n - 8:
        n += 8
    if not (exp_deg_ok(mul_lo, n) and exp_deg_ok(mul_hi, n)):
        raise ValueError(f"degree witness failed at n={n}")
    # The exact expLBQ/expUBQ values over the ε/τ-padded child carry
    # ~10^300-scale denominators raised to the Taylor degree (thousands of
    # digits).  The checker conditions are INEQUALITIES, so round the exp
    # bracket OUTWARD to a short decimal grid — soundness is unchanged and
    # every downstream rational stays compact.
    GRID = 10 ** 30
    e_lo_exact = exp_lbq(mul_lo, n)
    e_hi_exact = exp_ubq(mul_hi, n)
    e_lo = Fraction(e_lo_exact.numerator * GRID // e_lo_exact.denominator, GRID)
    e_hi = -Fraction((-e_hi_exact.numerator * GRID) // e_hi_exact.denominator, GRID)
    if not (0 < e_lo <= e_lo_exact and e_hi_exact <= e_hi):
        raise RuntimeError("internal: bad exp bracket rounding")
    # node 5: add (exp + 1) — exact fl, padded out.  Strictly positive.
    add_flo, add_fhi = e_lo + 1, e_hi + 1
    add_lo, add_hi = pad_lo(add_flo), pad_hi(add_fhi)
    if not add_lo > 0:
        raise RuntimeError("internal: denominator interval not positive")
    # node 6: div [2,2] / [add_lo, add_hi] — CONSTANT numerator, so the four
    # corners collapse to two values and no correlation is lost.
    q1 = Fraction(2) / add_lo
    q2 = Fraction(2) / add_hi
    div_lo = pad_lo(min(q1, q2))
    div_hi = pad_hi(max(q1, q2))
    # node 7: sub [1,1] - [div_lo, div_hi] — exact fl, padded out.
    sub_flo = 1 - div_hi
    sub_fhi = 1 - div_lo
    out_lo = pad_lo(sub_flo)
    out_hi = pad_hi(sub_fhi)

    ev_id = producer_sha256()
    req = request_commitment_b64("range-bound-cert", expression, lower, upper)
    lines = [
        SCHEMA,
        f"model {MODEL}",
        f"exe {ev_id}",
        f"status {STATUS}",
        f"expr {CANONICAL_SEXP}",
        f"source {req}",
        f"input {R(a)} {R(b)}",
        "root 7",
        f"output {R(out_lo)} {R(out_hi)}",
        "node 0 num_exact children[] out[2,2] val 2 name 2",
        f"node 1 var children[] out[{R(a)},{R(b)}] name x",
        f"node 2 mul children[0,1] out[{R(mul_lo)},{R(mul_hi)}] "
        f"p[{R(p1)},{R(p2)},{R(p1)},{R(p2)}]",
        f"node 3 exp_rat children[2] out[{R(e_lo)},{R(e_hi)}] n {n}",
        "node 4 num_exact children[] out[1,1] val 1 name 1",
        f"node 5 add children[3,4] out[{R(add_lo)},{R(add_hi)}] "
        f"f[{R(add_flo)},{R(add_fhi)}]",
        f"node 6 div children[0,5] out[{R(div_lo)},{R(div_hi)}] "
        f"p[{R(q1)},{R(q2)},{R(q1)},{R(q2)}] den 1",
        f"node 7 sub children[4,6] out[{R(out_lo)},{R(out_hi)}] "
        f"f[{R(sub_flo)},{R(sub_fhi)}]",
        "end",
    ]
    return ("\n".join(lines) + "\n").encode("utf-8")



def _merge_value_args(argv: list[str]) -> list[str]:
    """argparse treats a leading-dash VALUE like `-1/2` as an option token
    (its negative-number heuristic only covers plain numerics).  Merge
    `--opt value` into `--opt=value` so canonical rational tokens with any
    sign parse identically for every caller."""
    merged: list[str] = []
    i = 0
    value_opts = {"--expression", "--lower", "--upper", "--degree", "--op"}
    while i < len(argv):
        a = argv[i]
        if a in value_opts and i + 1 < len(argv):
            merged.append(f"{a}={argv[i + 1]}")
            i += 2
        else:
            merged.append(a)
            i += 1
    return merged

def _cli() -> int:
    ap = argparse.ArgumentParser(description="JACKAL tanh composite cert producer")
    sub = ap.add_subparsers(dest="cmd", required=True)
    emit = sub.add_parser("emit", help="emit the composite cert to stdout")
    emit.add_argument("--expression", required=True)
    emit.add_argument("--lower", required=True)
    emit.add_argument("--upper", required=True)
    sub.add_parser("sha256", help="print this producer's SHA-256")
    ns = ap.parse_args(_merge_value_args(sys.argv[1:]))
    if ns.cmd == "emit":
        try:
            cert = emit_cert(ns.expression, ns.lower, ns.upper)
        except ValueError as e:
            print(f"REFUSE {e}", file=sys.stderr)
            return 2
        sys.stdout.buffer.write(cert)
        return 0
    if ns.cmd == "sha256":
        print(producer_sha256())
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(_cli())
