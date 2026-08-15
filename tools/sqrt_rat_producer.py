#!/usr/bin/env python3
"""JACKAL v1.4.0 sqrt_rat cert producer.

The Anubis engine has no sqrt_rat op — it's a checker-strategy addition
introduced in v1.4.0 (§487-fragment extension).  This standalone producer
emits a canonical `jackal-eval-cert v2` for `sqrt(x)` requests on a rational
interval `[lo, hi]`, using pure-ℚ Newton iteration to bracket the enclosure.

The Lean-proved `jackal_cert_check` (with the new `sqrtRat` Runs constructor
and the `sqrt_rat` checkNode arm) validates the emitted cert — the producer
is completely untrusted, exactly like the range/Gaussian producers.

Usage:
    python3 tools/sqrt_rat_producer.py emit \\
        --expression sqrt\\(x\\) --lower <lo> --upper <hi> \\
        [--digits 40]
"""
from __future__ import annotations

import argparse
import base64
import decimal
import hashlib
import re
import sys
from fractions import Fraction
from pathlib import Path
from typing import Iterable


SCHEMA = "jackal-eval-cert v2"
MODEL = "jackal-iv-model-v1"
STATUS = "bounded"
PRODUCER_ID_LABEL = "sqrt-rat-producer"


def parse_canonical_rat(tok: str) -> Fraction:
    """Parse a canonical rational token or a positive decimal token."""
    tok = tok.strip()
    if "/" in tok:
        n, d = tok.split("/", 1)
        return Fraction(int(n), int(d))
    # Accept integer or simple decimal representation
    return Fraction(tok)


def canonical_rat_str(f: Fraction) -> str:
    """Emit `p/q` in reduced form; drop the /1 for integers."""
    f = Fraction(f.numerator, f.denominator)  # ensure reduced
    if f.denominator == 1:
        return str(f.numerator)
    return f"{f.numerator}/{f.denominator}"


def sqrt_bracket(a: Fraction, b: Fraction, digits: int = 40) -> tuple[Fraction, Fraction]:
    """Return (lo, hi) with 0 ≤ lo, 0 ≤ hi, lo^2 ≤ a, b ≤ hi^2.

    Strategy: decimal.sqrt at `digits` precision for the seed, then integer
    adjustment to guarantee the two inequalities exactly in ℚ.  Never trusts
    the decimal value — the final `lo*lo <= a` and `b <= hi*hi` inequalities
    are exact rational comparisons.
    """
    if a < 0 or b < a:
        raise ValueError(f"sqrt_bracket requires 0 ≤ a ≤ b, got {a}, {b}")
    prev = decimal.getcontext().prec
    try:
        decimal.getcontext().prec = max(digits + 20, 60)
        a_dec = decimal.Decimal(a.numerator) / decimal.Decimal(a.denominator)
        b_dec = decimal.Decimal(b.numerator) / decimal.Decimal(b.denominator)
        sqrt_a = a_dec.sqrt()
        sqrt_b = b_dec.sqrt()
    finally:
        decimal.getcontext().prec = prev
    scale = 10 ** digits
    # lo := floor(sqrt(a) * scale) / scale; hi := ceil(sqrt(b) * scale) / scale
    lo = Fraction(int(sqrt_a * scale), scale)
    hi = Fraction(int(sqrt_b * scale) + 1, scale)
    # Exact-ℚ adjustment loop (bounded; at most a few iterations).
    guard = 0
    while lo > 0 and lo * lo > a:
        lo = Fraction(lo.numerator - 1, lo.denominator)
        guard += 1
        if guard > 128:
            raise RuntimeError("sqrt lo adjustment did not converge")
    guard = 0
    while hi * hi < b:
        hi = Fraction(hi.numerator + 1, hi.denominator)
        guard += 1
        if guard > 128:
            raise RuntimeError("sqrt hi adjustment did not converge")
    if lo < 0:
        lo = Fraction(0)
    assert lo * lo <= a, f"lo^2 > a: {lo}^2 = {lo*lo} > {a}"
    assert b <= hi * hi, f"b > hi^2: {b} > {hi}^2 = {hi*hi}"
    assert lo >= 0 and hi >= 0
    return lo, hi


def request_commitment_b64(command: str, expression: str, lo: str, hi: str) -> str:
    """Mirror of the shared framing (tools/formal_receipt.py)."""
    def framed(p: str) -> bytes:
        b = p.encode("utf-8")
        return str(len(b)).encode() + b":" + b
    framing = (b"jackal-req-v2\x00" + framed(command) + b"|" + framed(expression)
               + b"|" + framed(lo) + b"|" + framed(hi))
    return base64.b64encode(hashlib.sha256(framing).hexdigest().encode()).decode()


def producer_sha256() -> str:
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def emit_cert(expression: str, lower: str, upper: str, digits: int = 40) -> bytes:
    """Emit the canonical jackal-eval-cert v2 for sqrt(x) on [lower, upper]."""
    # Only accept the exact form `sqrt(x)`; anything else refuses fail-closed.
    if expression.replace(" ", "") != "sqrt(x)":
        raise ValueError("sqrt_rat producer only admits the exact form `sqrt(x)`; "
                         f"got {expression!r}")
    a = parse_canonical_rat(lower)
    b = parse_canonical_rat(upper)
    if a > b:
        raise ValueError("upper must be >= lower")
    lo, hi = sqrt_bracket(a, b, digits=digits)
    ev_id = producer_sha256()
    req = request_commitment_b64("range-bound-cert", expression, lower, upper)
    lines: list[str] = [
        SCHEMA,
        f"model {MODEL}",
        f"exe {ev_id}",
        f"status {STATUS}",
        "expr (call sqrt (var x))",
        f"source {req}",
        f"input {canonical_rat_str(a)} {canonical_rat_str(b)}",
        "root 1",
        f"output {canonical_rat_str(lo)} {canonical_rat_str(hi)}",
        f"node 0 var children[] out[{canonical_rat_str(a)},{canonical_rat_str(b)}] name x",
        f"node 1 sqrt_rat children[0] out[{canonical_rat_str(lo)},{canonical_rat_str(hi)}]",
        "end",
    ]
    return ("\n".join(lines) + "\n").encode("utf-8")


def _cli() -> int:
    ap = argparse.ArgumentParser(description="JACKAL sqrt_rat cert producer")
    sub = ap.add_subparsers(dest="cmd", required=True)
    emit = sub.add_parser("emit", help="emit a sqrt_rat cert to stdout")
    emit.add_argument("--expression", required=True)
    emit.add_argument("--lower", required=True)
    emit.add_argument("--upper", required=True)
    emit.add_argument("--digits", type=int, default=40)
    sub.add_parser("sha256", help="print this producer's SHA-256")
    ns = ap.parse_args()
    if ns.cmd == "emit":
        try:
            cert = emit_cert(ns.expression, ns.lower, ns.upper, digits=ns.digits)
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
