#!/usr/bin/env python3
"""JACKAL v1.5.0 atan_rat cert producer (UNTRUSTED).

Emits a canonical `jackal-eval-cert v2` two-node certificate for the exact
request `atan(x)` on ANY rational interval `[lower, upper]`, using the
`atan_rat` checker-strategy op (§490 fragment extension).

The compiled Lean-proved `jackal_cert_check` validates each endpoint through
one of FOUR decidable strategies, entirely in ℚ (`Transcend.atanLoOK` /
`atanHiOK`, proved sound in `Transcend.atanLo_sound` / `atanHi_sound`):

  CAP        endpoint clears ±piHiQ/2 (outside arctan's whole range);
  BRACKET    |t| <= 1 tan-bracket: tanHiQ(lo) <= child.lo  /
             child.hi <= tanLoQ(hi);
  POS-RECIP  0 < child endpoint, reciprocal identity
             arctan q = π/2 − arctan(1/q) with a tan-bracket at
             piLoQ/2 − lo  /  piHiQ/2 − hi;
  NEG-RECIP  child endpoint < 0, arctan q = −π/2 − arctan(1/q) with a
             tan-bracket at −piHiQ/2 − lo  /  −piLoQ/2 − hi.

piLoQ/piHiQ are the Mathlib 20-digit rational π bounds.  The tan brackets
come from the fixed-degree sin/cos Taylor enclosures, so certified endpoint
slack is ~5e-2 near |q| = 1 and tighter elsewhere; that is an enclosure-width
residual, never a soundness one.

`math.atan` seeds the endpoint search ONLY; every emitted endpoint is
verified against the exact rational checker conditions (mirrored below)
before the certificate is written.  Refuses when verification fails.
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
PI_LO_Q = Fraction(314159265358979323846, 10 ** 20)
PI_HI_Q = Fraction(314159265358979323847, 10 ** 20)
DENOM = 10 ** 12
SEED_MARGIN = Fraction(1, 100)     # tan-bracket slack floor (~5e-2 near 1)
MAX_STEPS = 64


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


def sin_lo_q(m: Fraction) -> Fraction:
    return (m - m ** 3 / 6) - abs(m) ** 5 / 100


def sin_hi_q(m: Fraction) -> Fraction:
    return (m - m ** 3 / 6) + abs(m) ** 5 / 100


def cos_lo_q(m: Fraction) -> Fraction:
    return (1 - m ** 2 / 2) - m ** 4 * Fraction(5, 96)


def cos_hi_q(m: Fraction) -> Fraction:
    return (1 - m ** 2 / 2) + m ** 4 * Fraction(5, 96)


def tan_lo_q(t: Fraction) -> Fraction:
    s = sin_lo_q(t)
    return s / cos_hi_q(t) if s >= 0 else s / cos_lo_q(t)


def tan_hi_q(t: Fraction) -> Fraction:
    s = sin_hi_q(t)
    return s / cos_lo_q(t) if s >= 0 else s / cos_hi_q(t)


def atan_lo_ok(lo: Fraction, c_lo: Fraction) -> bool:
    """Mirror of Lean `Transcend.atanLoOK`."""
    if lo <= -(PI_HI_Q / 2):
        return True
    if abs(lo) <= 1 and tan_hi_q(lo) <= c_lo:
        return True
    if c_lo > 0:
        t = PI_LO_Q / 2 - lo
        if abs(t) <= 1 and Fraction(1) / c_lo <= tan_lo_q(t):
            return True
    if c_lo < 0:
        t = -(PI_HI_Q / 2) - lo
        if abs(t) <= 1 and Fraction(1) / c_lo <= tan_lo_q(t):
            return True
    return False


def atan_hi_ok(hi: Fraction, c_hi: Fraction) -> bool:
    """Mirror of Lean `Transcend.atanHiOK`."""
    if PI_HI_Q / 2 <= hi:
        return True
    if abs(hi) <= 1 and c_hi <= tan_lo_q(hi):
        return True
    if c_hi > 0:
        t = PI_HI_Q / 2 - hi
        if abs(t) <= 1 and tan_hi_q(t) <= Fraction(1) / c_hi:
            return True
    if c_hi < 0:
        t = -(PI_LO_Q / 2) - hi
        if abs(t) <= 1 and tan_hi_q(t) <= Fraction(1) / c_hi:
            return True
    return False


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


def emit_cert(expression: str, lower: str, upper: str) -> bytes:
    if expression.replace(" ", "") != "atan(x)":
        raise ValueError("atan_rat producer only admits the exact form `atan(x)`; "
                         f"got {expression!r}")
    a = parse_canonical_rat(lower)
    b = parse_canonical_rat(upper)
    if a > b:
        raise ValueError("upper must be >= lower")

    lo_q = _grid(math.atan(float(a))) - SEED_MARGIN
    step = SEED_MARGIN
    ok = False
    for _ in range(MAX_STEPS):
        if atan_lo_ok(lo_q, a):
            ok = True
            break
        lo_q -= step
        step *= 2
    if not ok:
        raise ValueError(f"could not verify a lower atan endpoint for {a}")

    hi_q = _grid(math.atan(float(b))) + SEED_MARGIN
    step = SEED_MARGIN
    ok = False
    for _ in range(MAX_STEPS):
        if atan_hi_ok(hi_q, b):
            ok = True
            break
        hi_q += step
        step *= 2
    if not ok:
        raise ValueError(f"could not verify an upper atan endpoint for {b}")

    if hi_q < lo_q:
        raise RuntimeError(f"internal: bad enclosure lo={lo_q} hi={hi_q}")

    ev_id = producer_sha256()
    req = request_commitment_b64("range-bound-cert", expression, lower, upper)
    lines = [
        SCHEMA,
        f"model {MODEL}",
        f"exe {ev_id}",
        f"status {STATUS}",
        "expr (call atan (var x))",
        f"source {req}",
        f"input {canonical_rat_str(a)} {canonical_rat_str(b)}",
        "root 1",
        f"output {canonical_rat_str(lo_q)} {canonical_rat_str(hi_q)}",
        f"node 0 var children[] out[{canonical_rat_str(a)},{canonical_rat_str(b)}] name x",
        f"node 1 atan_rat children[0] out[{canonical_rat_str(lo_q)},{canonical_rat_str(hi_q)}]",
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
    ap = argparse.ArgumentParser(description="JACKAL atan_rat cert producer")
    sub = ap.add_subparsers(dest="cmd", required=True)
    emit = sub.add_parser("emit", help="emit an atan_rat cert to stdout")
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
