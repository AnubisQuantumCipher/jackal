#!/usr/bin/env python3
"""JACKAL v1.5.0 sin_rat / cos_rat cert producer (UNTRUSTED).

Emits a canonical `jackal-eval-cert v2` two-node certificate for the exact
request `sin(x)` (or, via --op cos, `cos(x)`) on a rational interval
`[lower, upper]` whose midpoint m = (lower+upper)/2 satisfies |m| <= 1,
using the `sin_rat` / `cos_rat` checker-strategy ops (§490).

The compiled Lean-proved `jackal_cert_check` recomputes the midpoint and
halfwidth ITSELF (no witness fields) and validates, entirely in ℚ:

    child.lo <= child.hi,   |(child.lo+child.hi)/2| <= 1,
    out_lo <= sinLoQ(m) - hw,    sinHiQ(m) + hw <= out_hi     (sin)
    out_lo <= cosLoQ(m) - hw,    cosHiQ(m) + hw <= out_hi     (cos)

where sinLoQ/sinHiQ = (m - m^3/6) -/+ |m|^5/100 and
cosLoQ/cosHiQ = (1 - m^2/2) -/+ m^4*(5/96) are the Mathlib
`Real.sin_bound` / `Real.cos_bound` fixed-degree Taylor enclosures, and hw
widening is the Lipschitz-1 bound |sin'|,|cos'| <= 1.

Soundness: `Runs.sinRat` / `Runs.cosRat` via `Transcend.sin_range` /
`cos_range` — NO libm result on the proof-decision path.

Arguments centered outside [-1, 1] REFUSE (named reason).  This producer
emits the checker-optimal endpoints exactly (closed form; no search, no
floats anywhere).
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import sys
from fractions import Fraction
from pathlib import Path


SCHEMA = "jackal-eval-cert v2"
MODEL = "jackal-iv-model-v1"
STATUS = "bounded"


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


def request_commitment_b64(command: str, expression: str, lo: str, hi: str) -> str:
    def framed(p: str) -> bytes:
        raw = p.encode("utf-8")
        return f"{len(raw)}:".encode() + raw

    framing = b"jackal-req-v2\x00" + b"|".join(
        framed(p) for p in (command, expression, lo, hi))
    return base64.b64encode(hashlib.sha256(framing).hexdigest().encode()).decode()


def producer_sha256() -> str:
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def emit_cert(op: str, expression: str, lower: str, upper: str) -> bytes:
    if op not in ("sin", "cos"):
        raise ValueError(f"op must be sin or cos, got {op!r}")
    if expression.replace(" ", "") != f"{op}(x)":
        raise ValueError(f"{op}_rat producer only admits the exact form `{op}(x)`; "
                         f"got {expression!r}")
    a = parse_canonical_rat(lower)
    b = parse_canonical_rat(upper)
    if a > b:
        raise ValueError("upper must be >= lower")
    m = (a + b) / 2
    hw = (b - a) / 2
    if abs(m) > 1:
        raise ValueError(
            f"{op}_rat requires |midpoint| <= 1 (midpoint {m}); "
            "argument reduction beyond [-1,1] is not in the v1.5.0 formal fragment")
    if op == "sin":
        lo_q = sin_lo_q(m) - hw
        hi_q = sin_hi_q(m) + hw
    else:
        lo_q = cos_lo_q(m) - hw
        hi_q = cos_hi_q(m) + hw
    if hi_q < lo_q:
        raise RuntimeError(f"internal: bad enclosure lo={lo_q} hi={hi_q}")
    node_op = f"{op}_rat"
    ev_id = producer_sha256()
    req = request_commitment_b64("range-bound-cert", expression, lower, upper)
    lines = [
        SCHEMA,
        f"model {MODEL}",
        f"exe {ev_id}",
        f"status {STATUS}",
        f"expr (call {op} (var x))",
        f"source {req}",
        f"input {canonical_rat_str(a)} {canonical_rat_str(b)}",
        "root 1",
        f"output {canonical_rat_str(lo_q)} {canonical_rat_str(hi_q)}",
        f"node 0 var children[] out[{canonical_rat_str(a)},{canonical_rat_str(b)}] name x",
        f"node 1 {node_op} children[0] out[{canonical_rat_str(lo_q)},{canonical_rat_str(hi_q)}]",
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
    ap = argparse.ArgumentParser(description="JACKAL sin_rat/cos_rat cert producer")
    sub = ap.add_subparsers(dest="cmd", required=True)
    emit = sub.add_parser("emit", help="emit a sin_rat/cos_rat cert to stdout")
    emit.add_argument("--op", required=True, choices=["sin", "cos"])
    emit.add_argument("--expression", required=True)
    emit.add_argument("--lower", required=True)
    emit.add_argument("--upper", required=True)
    sub.add_parser("sha256", help="print this producer's SHA-256")
    ns = ap.parse_args(_merge_value_args(sys.argv[1:]))
    if ns.cmd == "emit":
        try:
            cert = emit_cert(ns.op, ns.expression, ns.lower, ns.upper)
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
