#!/usr/bin/env python3
"""Differential gate: JACKAL's range enclosures vs an independent interval
implementation (mpmath.iv) plus high-precision point sampling.

Two fatal verdicts, mirroring the containment-only discipline of
tests/bound_campaign.py:

  POINT_VIOLATION — a 40-digit sampled value f(x), x in [a,b], falls outside
      JACKAL's printed range enclosure. This is the direct soundness check:
      the enclosure claims to contain f(x) for every x in the interval.
  DISJOINT_IMPLEMENTATIONS — JACKAL's enclosure and mpmath.iv's enclosure of
      the same expression over the same interval do not intersect. Both claim
      to be supersets of the true range, so disjointness proves at least one
      implementation wrong.

Width ratios (JACKAL width / mpmath.iv width) are recorded as a tightness
diagnostic, never as a verdict: two sound interval implementations may differ
in tightness freely. Refusals are legitimate and counted. Each expression is a
single Python lambda evaluated under BOTH namespaces (mpmath for points,
mpmath.iv for intervals), so there is no transcription gap between what the
oracle computes and what JACKAL parses — the JACKAL string and the lambda are
generated from the same template.

Usage: python3 tests/iv_differential.py [cases] [seed]
"""
from __future__ import annotations

import hashlib
import json
import random
import subprocess
import sys
from pathlib import Path

import mpmath

ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "jackal"
OUT_PATH = Path("/tmp/jackal-iv-differential.jsonl")

mpmath.mp.dps = 40
mpmath.iv.prec = 53


def dec(rng: random.Random, lo: float, hi: float, places: int = 4) -> str:
    return f"{round(rng.uniform(lo, hi), places):.{places}f}"


class Gen:
    """Each atom yields (jackal_expr, python_expr) built from one template.

    python_expr uses `x` and namespace `m` (mpmath or mpmath.iv); constants go
    through m.mpf('<literal>') so both namespaces parse the same decimal.
    """

    def __init__(self, rng: random.Random, a: float, b: float):
        self.rng = rng
        self.a = a
        self.b = b

    def atom(self):
        r = self.rng
        kind = r.choice(
            ["poly", "trig", "expdamp", "log", "sqrt", "recip", "gauss", "absx", "powx"]
        )
        if kind == "poly":
            c2, c1, c0 = dec(r, -3, 3), dec(r, -3, 3), dec(r, -3, 3)
            return (f"({c2}*x^2+{c1}*x+{c0})",
                    f"(m.mpf('{c2}')*x**2 + m.mpf('{c1}')*x + m.mpf('{c0}'))")
        if kind == "trig":
            k = r.randint(1, 30)
            c = dec(r, -3, 3)
            fn = r.choice(["sin", "cos"])
            return (f"{fn}({k}*x+{c})", f"m.{fn}({k}*x + m.mpf('{c}'))")
        if kind == "expdamp":
            k = f"{round(r.uniform(-2.0, 2.0), 3):.3f}"
            return (f"exp({k}*x)", f"m.exp(m.mpf('{k}')*x)")
        if kind == "log":
            c = f"{round(-self.a + r.uniform(0.1, 3.0), 4):.4f}"
            return (f"ln(x+{c})", f"m.log(x + m.mpf('{c}'))")
        if kind == "sqrt":
            c = f"{round(-self.a + r.uniform(0.1, 3.0), 4):.4f}"
            return (f"sqrt(x+{c})", f"m.sqrt(x + m.mpf('{c}'))")
        if kind == "recip":
            if r.random() < 0.5:
                c = round(-self.b - r.uniform(0.2, 2.0), 4)
            else:
                c = round(-self.a + r.uniform(0.2, 2.0), 4)
            cj = f"(x+{c:.4f})" if c >= 0 else f"(x-{-c:.4f})"
            return (f"1/{cj}", f"1/(x + m.mpf('{c:.4f}'))")
        if kind == "absx":
            c = dec(r, self.a, self.b)
            return (f"abs(x-{c})", f"abs(x - m.mpf('{c}'))")
        if kind == "powx":
            n = r.randint(2, 6)
            return (f"x^{n}", f"x**{n}")
        s = r.choice([100, 10000, 1000000])
        c = f"{round(r.uniform(self.a - 0.2, self.b + 0.2), 6):.6f}"
        return (f"exp(0-{s}*(x-{c})^2)", f"m.exp(-{s}*(x - m.mpf('{c}'))**2)")

    def build(self):
        r = self.rng
        j1, p1 = self.atom()
        shape = r.random()
        if shape < 0.4:
            return j1, p1
        j2, p2 = self.atom()
        if shape < 0.7:
            return f"{j1}*{j2}", f"({p1})*({p2})"
        return f"{j1}+{j2}", f"({p1})+({p2})"


def main() -> int:
    cases = int(sys.argv[1]) if len(sys.argv) > 1 else 300
    seed = int(sys.argv[2]) if len(sys.argv) > 2 else 20260813
    rng = random.Random(seed)
    rows = []
    n_ok = n_refused = n_point = n_disjoint = n_iv_skip = 0
    width_ratios = []

    for i in range(cases):
        a = round(rng.uniform(-4.0, 3.0), 3)
        b = round(a + rng.uniform(0.05, 3.0), 3)
        jackal_src, py_src = Gen(rng, a, b).build()
        fn = eval(f"lambda x, m: {py_src}")  # noqa: S307 — our own generated template
        proc = subprocess.run(
            [str(LAUNCHER), "range-bound", jackal_src, str(a), str(b)],
            capture_output=True, text=True, timeout=3600,
        )
        row = {"i": i, "expr": jackal_src, "a": a, "b": b}
        if proc.returncode != 0:
            row["verdict"] = "REFUSED"
            row["reason"] = (proc.stderr.strip().splitlines() or [""])[-1][-200:]
            n_refused += 1
            rows.append(row)
            continue
        line = proc.stdout.strip().splitlines()[-1]
        enclosure = line.split("range-enclosure=[", 1)[1].split("]", 1)[0]
        lo_text, hi_text = enclosure.split(",")
        lo_v, hi_v = mpmath.mpf(lo_text), mpmath.mpf(hi_text)
        row["enclosure"] = [lo_text, hi_text]

        # Check 1: high-precision point sampling must land inside.
        slack = (abs(lo_v) + abs(hi_v) + 1) * mpmath.mpf("1e-35")
        bad_point = None
        xs = [mpmath.mpf(a), mpmath.mpf(b), (mpmath.mpf(a) + mpmath.mpf(b)) / 2]
        xs += [mpmath.mpf(a) + (mpmath.mpf(b) - mpmath.mpf(a)) * mpmath.mpf(rng.random())
               for _ in range(38)]
        for xv in xs:
            try:
                fv = fn(xv, mpmath.mp)
            except (ValueError, ZeroDivisionError, mpmath.libmp.libhyper.NoConvergence):
                continue
            if not (lo_v - slack <= fv <= hi_v + slack):
                bad_point = (mpmath.nstr(xv, 20), mpmath.nstr(fv, 20))
                break
        if bad_point is not None:
            row["verdict"] = "POINT_VIOLATION"
            row["witness"] = bad_point
            n_point += 1
            rows.append(row)
            continue

        # Check 2: cross-implementation intersection with mpmath.iv.
        try:
            xi = mpmath.iv.mpf([a, b])
            ivr = fn(xi, mpmath.iv)
            # iv endpoints stringify as degenerate intervals "[v, v]" — take
            # the raw endpoint via the backend tuple.
            iv_lo = mpmath.mp.make_mpf(ivr._mpi_[0])
            iv_hi = mpmath.mp.make_mpf(ivr._mpi_[1])
            row["iv_enclosure"] = [mpmath.nstr(iv_lo, 20), mpmath.nstr(iv_hi, 20)]
            if hi_v < iv_lo or lo_v > iv_hi:
                row["verdict"] = "DISJOINT_IMPLEMENTATIONS"
                n_disjoint += 1
                rows.append(row)
                continue
            j_width = hi_v - lo_v
            iv_width = iv_hi - iv_lo
            if iv_width > 0:
                width_ratios.append(float(j_width / iv_width))
        except Exception as exc:
            row["iv_skip"] = repr(exc)[:120]
            n_iv_skip += 1

        row["verdict"] = "OK"
        n_ok += 1
        rows.append(row)

    payload = "\n".join(json.dumps(r, sort_keys=True) for r in rows) + "\n"
    OUT_PATH.write_text(payload)
    digest = hashlib.sha256(payload.encode()).hexdigest()
    ratio_note = ""
    if width_ratios:
        width_ratios.sort()
        ratio_note = (f" width-ratio(j/iv) median={width_ratios[len(width_ratios)//2]:.3f}"
                      f" max={width_ratios[-1]:.3f}")
    print(f"cases={cases} seed={seed}")
    print(f"OK={n_ok} REFUSED={n_refused} IV_CROSSCHECK_SKIPPED={n_iv_skip}{ratio_note}")
    print(f"POINT_VIOLATION={n_point} DISJOINT_IMPLEMENTATIONS={n_disjoint}")
    print(f"jsonl={OUT_PATH} sha256={digest}")
    if n_point or n_disjoint:
        print("VERDICT: FAIL — an enclosure excluded a sampled truth or contradicted mpmath.iv")
        return 1
    print("VERDICT: PASS — every enclosure contained all sampled truths and intersects mpmath.iv")
    return 0


if __name__ == "__main__":
    sys.exit(main())
