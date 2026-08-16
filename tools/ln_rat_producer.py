#!/usr/bin/env python3
"""JACKAL v1.5.0 ln_rat cert producer (UNTRUSTED).

Emits a canonical `jackal-eval-cert v2` two-node certificate for the exact
request `ln(x)` on a positive rational interval `[lower, upper]`, using the
`ln_rat` checker-strategy op (§490 fragment extension).

The compiled Lean-proved `jackal_cert_check` re-validates every claim through
the INVERSE exponential bracket, entirely in ℚ:

    0 < child.lo,  child.lo <= child.hi,
    expDegOKQ(out_lo, n),  expDegOKQ(out_hi, n),
    expUBQ(out_lo, n) <= child.lo,   -- witnesses exp(out_lo) <= lo
    child.hi <= expLBQ(out_hi, n)    -- witnesses hi <= exp(out_hi)

Soundness (`Runs.logRat`, theorem `cert_check_sound` /
`request_bound_certified_release`) rests on `Real.le_log_iff_exp_le` /
`Real.log_le_iff_le_exp` and monotonicity of `Real.log` — NO libm result on
the proof-decision path.

This producer is untrusted: `math.log` is used ONLY to seed the endpoint
search; every emitted endpoint is verified against the exact rational checker
conditions (mirrored below in `Fraction` arithmetic) before the certificate
is written.  If the search cannot verify, it REFUSES — it never guesses.
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
DENOM = 10 ** 12          # dyadic-decimal grid for emitted endpoints
SEED_MARGIN = Fraction(1, 10 ** 9)
MAX_STEPS = 128


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
    """Mirror of Lean `Gaussian.expLBQ`."""
    if q >= 0:
        return exp_partial(q, n)
    z = -q
    return 1 / (exp_partial(z, n) + exp_remainder(z, n))


def exp_ubq(q: Fraction, n: int) -> Fraction:
    """Mirror of Lean `Gaussian.expUBQ`."""
    if q >= 0:
        return exp_partial(q, n) + exp_remainder(q, n)
    z = -q
    return 1 / exp_partial(z, n)


def pick_degree(bound: Fraction) -> int:
    """Degree comfortably past the witness `2*|q| <= n+1` with headroom for
    ~1e-12 partial-sum tightness on the relevant argument scale."""
    n = 20
    while 2 * abs(bound) > n - 8:
        n += 8
    return n


def request_commitment_b64(command: str, expression: str, lo: str, hi: str) -> str:
    def framed(p: str) -> bytes:
        raw = p.encode("utf-8")
        return f"{len(raw)}:".encode() + raw

    framing = b"jackal-req-v2\x00" + b"|".join(
        framed(p) for p in (command, expression, lo, hi))
    return base64.b64encode(hashlib.sha256(framing).hexdigest().encode()).decode()


def producer_sha256() -> str:
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def _grid(x: float) -> Fraction:
    return Fraction(round(x * DENOM), DENOM)


def emit_cert(expression: str, lower: str, upper: str,
              degree: int | None = None) -> bytes:
    if expression.replace(" ", "") != "ln(x)":
        raise ValueError("ln_rat producer only admits the exact form `ln(x)`; "
                         f"got {expression!r}")
    a = parse_canonical_rat(lower)
    b = parse_canonical_rat(upper)
    if a > b:
        raise ValueError("upper must be >= lower")
    if a <= 0:
        raise ValueError("ln_rat requires 0 < lower (log domain)")
    n = pick_degree(Fraction(math.ceil(abs(math.log(float(a)))) +
                             math.ceil(abs(math.log(float(b)))) + 2)) \
        if degree is None else int(degree)
    if n < 1:
        raise ValueError("degree must be >= 1")

    # out_lo: seeded just below ln(lower); step down until the exact
    # rational witness `expUBQ(out_lo, n) <= a` verifies.
    lo_q = _grid(math.log(float(a))) - SEED_MARGIN
    step = SEED_MARGIN
    ok = False
    for _ in range(MAX_STEPS):
        if exp_deg_ok(lo_q, n) and exp_ubq(lo_q, n) <= a:
            ok = True
            break
        lo_q -= step
        step *= 2
    if not ok:
        raise ValueError(f"could not verify a lower ln endpoint for {a} at degree {n}")

    # out_hi: seeded just above ln(upper); step up until
    # `b <= expLBQ(out_hi, n)` verifies.
    hi_q = _grid(math.log(float(b))) + SEED_MARGIN
    step = SEED_MARGIN
    ok = False
    for _ in range(MAX_STEPS):
        if exp_deg_ok(hi_q, n) and b <= exp_lbq(hi_q, n):
            ok = True
            break
        hi_q += step
        step *= 2
    if not ok:
        raise ValueError(f"could not verify an upper ln endpoint for {b} at degree {n}")

    if hi_q < lo_q:
        raise RuntimeError(f"internal: bad enclosure lo={lo_q} hi={hi_q}")

    ev_id = producer_sha256()
    req = request_commitment_b64("range-bound-cert", expression, lower, upper)
    lines = [
        SCHEMA,
        f"model {MODEL}",
        f"exe {ev_id}",
        f"status {STATUS}",
        "expr (call ln (var x))",
        f"source {req}",
        f"input {canonical_rat_str(a)} {canonical_rat_str(b)}",
        "root 1",
        f"output {canonical_rat_str(lo_q)} {canonical_rat_str(hi_q)}",
        f"node 0 var children[] out[{canonical_rat_str(a)},{canonical_rat_str(b)}] name x",
        f"node 1 ln_rat children[0] out[{canonical_rat_str(lo_q)},{canonical_rat_str(hi_q)}] n {n}",
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
    ap = argparse.ArgumentParser(description="JACKAL ln_rat cert producer")
    sub = ap.add_subparsers(dest="cmd", required=True)
    emit = sub.add_parser("emit", help="emit an ln_rat cert to stdout")
    emit.add_argument("--expression", required=True)
    emit.add_argument("--lower", required=True)
    emit.add_argument("--upper", required=True)
    emit.add_argument("--degree", type=int, default=None)
    sub.add_parser("sha256", help="print this producer's SHA-256")
    ns = ap.parse_args(_merge_value_args(sys.argv[1:]))
    if ns.cmd == "emit":
        try:
            cert = emit_cert(ns.expression, ns.lower, ns.upper, degree=ns.degree)
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
