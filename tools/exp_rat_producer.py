#!/usr/bin/env python3
"""JACKAL v1.4.1 exp_rat cert producer.

The Anubis engine has no exp_rat op — it's a checker-strategy addition
introduced in v1.4.1 (§487-fragment extension: first libm-free
transcendental beyond `sqrt`).  This standalone producer emits a canonical
`jackal-eval-cert v2` for `exp(x)` requests on a rational interval
`[lo, hi]` (with `lo >= 0`), using exact rational Taylor arithmetic to
build a certified enclosure.

The Lean-proved `jackal_cert_check` (with the new `expRat` Runs constructor
and the `exp_rat` checkNode arm) validates the emitted cert — the producer
is completely untrusted, exactly like every other JACKAL producer.

The checker verifies, at exact rational precision:

  * `0 <= child.out_lo`                                 (nonneg guard)
  * `child.out_lo <= child.out_hi`                      (interval order)
  * `2 * child.out_hi <= n + 1`                         (degree witness ⇔ z/(n+1) ≤ 1/2)
  * `out_lo <= expPartial(child.out_lo, n)`             (lower Taylor bound)
  * `expPartial(child.out_hi, n) + expRemainder(child.out_hi, n) <= out_hi`
                                                        (upper Taylor bound)

Usage:
    python3 tools/exp_rat_producer.py emit \\
        --expression exp\\(x\\) --lower <lo> --upper <hi> \\
        [--degree N]
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
PRODUCER_ID_LABEL = "exp-rat-producer"


def parse_canonical_rat(tok: str) -> Fraction:
    tok = tok.strip()
    if "/" in tok:
        n, d = tok.split("/", 1)
        return Fraction(int(n), int(d))
    return Fraction(tok)


def canonical_rat_str(f: Fraction) -> str:
    f = Fraction(f.numerator, f.denominator)
    if f.denominator == 1:
        return str(f.numerator)
    return f"{f.numerator}/{f.denominator}"


def exp_partial(z: Fraction, n: int) -> Fraction:
    """Exact rational Taylor partial sum ∑_{k=0..n-1} z^k / k!."""
    total = Fraction(0)
    term = Fraction(1)  # z^0 / 0! = 1
    for k in range(n):
        if k > 0:
            term = term * z / k
        total += term
    return total


def exp_remainder(z: Fraction, n: int) -> Fraction:
    """Exact rational Taylor remainder bound 2 * z^n / n! valid for
    0 <= z and z/(n+1) <= 1/2 (per Complex.exp_bound')."""
    z_pow_n = Fraction(1)
    for _ in range(n):
        z_pow_n *= z
    return 2 * z_pow_n / math.factorial(n)


def pick_degree(z_hi: Fraction) -> int:
    """Smallest n with `2*z_hi <= n+1` (i.e., z_hi/(n+1) <= 1/2)."""
    # 2*z_hi <= n+1  =>  n >= 2*z_hi - 1.  Round up.
    #  z_hi is a Fraction; use ceil((2*z_hi - 1).numerator / .denominator).
    thresh = 2 * z_hi - 1
    if thresh <= 0:
        n = 1
    else:
        n = -(-thresh.numerator // thresh.denominator)  # ceiling division
    # Round up to a safety margin so the remainder term is reasonably tight.
    return max(n, 6)


def request_commitment_b64(command: str, expression: str, lo: str, hi: str) -> str:
    def framed(p: str) -> bytes:
        b = p.encode("utf-8")
        return str(len(b)).encode() + b":" + b
    framing = (b"jackal-req-v2\x00" + framed(command) + b"|" + framed(expression)
               + b"|" + framed(lo) + b"|" + framed(hi))
    return base64.b64encode(hashlib.sha256(framing).hexdigest().encode()).decode()


def producer_sha256() -> str:
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def emit_cert(expression: str, lower: str, upper: str, degree: int | None = None) -> bytes:
    """Emit the canonical jackal-eval-cert v2 for exp(x) on [lower, upper]."""
    if expression.replace(" ", "") != "exp(x)":
        raise ValueError("exp_rat producer only admits the exact form `exp(x)`; "
                         f"got {expression!r}")
    a = parse_canonical_rat(lower)
    b = parse_canonical_rat(upper)
    if a > b:
        raise ValueError("upper must be >= lower")
    if a < 0:
        raise ValueError("exp_rat requires 0 <= lower (positive-argument branch)")
    if degree is None:
        n = pick_degree(b)
    else:
        n = int(degree)
        if n < 1:
            raise ValueError("degree must be >= 1")
    # Degree witness: 2*b <= n+1.
    if 2 * b > n + 1:
        raise ValueError(
            f"degree {n} too small for upper={b}: 2*upper={2*b} > n+1={n+1}"
        )
    # Enclosure endpoints:
    #   lo := expPartial(a, n)                                (>= 0 by term)
    #   hi := expPartial(b, n) + expRemainder(b, n)
    lo = exp_partial(a, n)
    hi = exp_partial(b, n) + exp_remainder(b, n)
    if lo < 0 or hi < lo:
        raise RuntimeError(f"internal: bad enclosure lo={lo} hi={hi}")
    ev_id = producer_sha256()
    req = request_commitment_b64("range-bound-cert", expression, lower, upper)
    lines: list[str] = [
        SCHEMA,
        f"model {MODEL}",
        f"exe {ev_id}",
        f"status {STATUS}",
        "expr (call exp (var x))",
        f"source {req}",
        f"input {canonical_rat_str(a)} {canonical_rat_str(b)}",
        "root 1",
        f"output {canonical_rat_str(lo)} {canonical_rat_str(hi)}",
        f"node 0 var children[] out[{canonical_rat_str(a)},{canonical_rat_str(b)}] name x",
        f"node 1 exp_rat children[0] out[{canonical_rat_str(lo)},{canonical_rat_str(hi)}] n {n}",
        "end",
    ]
    return ("\n".join(lines) + "\n").encode("utf-8")


def _cli() -> int:
    ap = argparse.ArgumentParser(description="JACKAL exp_rat cert producer")
    sub = ap.add_subparsers(dest="cmd", required=True)
    emit = sub.add_parser("emit", help="emit an exp_rat cert to stdout")
    emit.add_argument("--expression", required=True)
    emit.add_argument("--lower", required=True)
    emit.add_argument("--upper", required=True)
    emit.add_argument("--degree", type=int, default=None,
                      help="Taylor degree (default: chosen automatically)")
    sub.add_parser("sha256", help="print this producer's SHA-256")
    ns = ap.parse_args()
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
