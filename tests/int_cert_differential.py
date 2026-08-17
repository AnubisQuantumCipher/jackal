#!/usr/bin/env python3
"""Engine-vs-producer differential gate (public v1.7 lane).

For each positive fixture, compares three quantities:

  engine   : `./jackal integrate-bound <expr> <lo> <hi> <tol>` printed
             enclosure (the shipped float lane, via the PINNED jackal-native);
  producer : the certified lane producer's artifact released interval
             (exact ℚ, checker-accepted in the focused matrix);
  oracle   : mpmath 60-dps evaluation of the true integral.

Assertions per case (mission trust boundary D7(iii): producer fidelity is
differential evidence, never byte identity — the certified lane uses Lean-D
chains and exact-ℚ acceptance, so trees may differ):

  1. oracle ∈ engine enclosure;
  2. oracle ∈ producer enclosure;
  3. the enclosures OVERLAP (they enclose the same real number).

Evidence: release/evidence/int_cert_differential.json.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from fractions import Fraction
from pathlib import Path

import mpmath

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "release" / "evidence"
sys.path.insert(0, str(ROOT / "tools"))
import int_cert_producer as bsp  # noqa: E402

mpmath.mp.dps = 60

CASES = [
    # (name, expr, lo, hi, tol, engine args (decimal), oracle fn, degree_cap)
    ("abs-range", "abs(x)", "-1", "1", "2", ["-1", "1", "2"],
     lambda: mpmath.quad(lambda x: abs(x), [-1, 0, 1]), None),
    ("x2-taylor2", "x^2", "0", "1", "1/2", ["0", "1", "0.5"],
     lambda: mpmath.mpf(1) / 3, 2),
    ("sin-taylor4", "sin(x)", "0", "1", "1/100", ["0", "1", "0.01"],
     lambda: 1 - mpmath.cos(1), None),
    ("abs-kink-multi", "abs(x-1/3)", "0", "1", "1/40", ["0", "1", "0.025"],
     lambda: mpmath.quad(lambda x: abs(x - mpmath.mpf(1) / 3),
                         [0, mpmath.mpf(1) / 3, 1]), None),
    ("cubic-signed", "x^3-x", "-1", "3/2", "1/8", ["-1", "1.5", "0.125"],
     lambda: mpmath.mpf(25) / 64, 0),
]


def engine_enclosure(expr: str, args: list[str]) -> tuple[Fraction, Fraction, str]:
    proc = subprocess.run(["./jackal", "integrate-bound", expr, *args],
                          capture_output=True, text=True, timeout=600,
                          cwd=ROOT)
    if proc.returncode != 0:
        raise RuntimeError(f"engine refused: {proc.stderr.strip()[:200]}")
    m = re.search(r"integral-enclosure=\[([^,]+),([^\]]+)\]", proc.stdout)
    if not m:
        raise RuntimeError(f"no enclosure in: {proc.stdout[:200]}")
    return (Fraction(float(m.group(1))), Fraction(float(m.group(2))),
            proc.stdout.strip())


def main() -> int:
    rows = []
    ok_all = True
    for name, expr, lo, hi, tol, eargs, oracle_fn, cap in CASES:
        art = bsp.build(expr, lo, hi, tol, degree_cap=cap)
        p_lo, p_hi = art["out_lo"], art["out_hi"]
        e_lo, e_hi, e_line = engine_enclosure(expr, eargs)
        oracle = oracle_fn()
        o = Fraction(str(oracle))
        in_engine = e_lo <= o <= e_hi
        in_producer = p_lo <= o <= p_hi
        overlap = max(e_lo, p_lo) <= min(e_hi, p_hi)
        ok = in_engine and in_producer and overlap
        ok_all &= ok
        rows.append({
            "case": name, "expr": expr,
            "engine": [float(e_lo), float(e_hi)],
            "producer": [float(p_lo), float(p_hi)],
            "oracle": str(oracle),
            "oracle_in_engine": in_engine,
            "oracle_in_producer": in_producer,
            "enclosures_overlap": overlap,
            "engine_line_head": e_line.split("assurance=")[0][-160:],
            "ok": ok,
        })
        print(f"{'PASS' if ok else 'FAIL'} {name:18s} "
              f"engine=[{float(e_lo):.6g},{float(e_hi):.6g}] "
              f"producer=[{float(p_lo):.6g},{float(p_hi):.6g}] "
              f"oracle={float(oracle):.6g}")
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": "jackal-int-cert-differential-v1",
        "status": "public",
        "non_claims": ["producer fidelity is differential evidence, not proof",
                       "engine float lane (integrate-bound) stays status=bounded, "
                       "implementation-tested-not-mechanized"],
        "rows": rows,
        "passed": sum(1 for r in rows if r["ok"]),
        "total": len(rows),
    }
    out = EVIDENCE / "int_cert_differential.json"
    out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n",
                   encoding="utf-8")
    print(f"TOTAL {payload['passed']}/{payload['total']} evidence={out}")
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
