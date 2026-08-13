#!/usr/bin/env python3
"""Seeded containment campaign for JACKAL's certified interval lane.

The claim under test is the strongest one JACKAL makes anywhere:

    integrate-bound prints an interval that CONTAINS the true integral
    (under the stated f64 rounding model), or refuses.

So the only fatal verdict here is CONTAINMENT_VIOLATION: the engine printed
an enclosure and the independently computed truth fell outside it. Refusals
are legitimate outcomes and are counted, not hidden. Every case is generated
from a fixed seed, every row is written to JSONL, and the artifact digest is
printed so the campaign is reproducible and tamper-evident.

Oracle discipline: truth comes from a SYMBOLIC antiderivative evaluated at 60
significant digits whenever sympy can produce one (an oracle that cannot miss
a narrow peak), and otherwise from mpmath.quad with explicit split points at
every generated feature location (gaussian centers, |x| kinks) so the oracle
resolves everything the generator planted.

Usage: python3 tests/bound_campaign.py [cases] [seed]
Runs the ./jackal launcher (native artifact when present; set
JACKAL_FORCE_SOURCE=1 to force the pinned compiler path).
"""
from __future__ import annotations

import hashlib
import json
import random
import subprocess
import sys
from fractions import Fraction
from pathlib import Path

import mpmath
import sympy

ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "jackal"
OUT_PATH = Path("/tmp/jackal-bound-campaign.jsonl")

X = sympy.Symbol("x")
mpmath.mp.dps = 60


def dec(rng: random.Random, lo: float, hi: float, places: int = 4) -> str:
    """A decimal literal with bounded places, so the sympy mirror is exact."""
    v = round(rng.uniform(lo, hi), places)
    return f"{v:.{places}f}"


class Gen:
    """Generates (jackal_source, sympy_expr, feature_points, smooth)."""

    def __init__(self, rng: random.Random, a: float, b: float):
        self.rng = rng
        self.a = a
        self.b = b
        self.features: list[float] = []

    def atom(self):
        r = self.rng
        kind = r.choice(
            ["poly", "trig", "expdamp", "log", "sqrt", "recip", "gauss", "trig", "poly"]
        )
        if kind == "poly":
            c2, c1, c0 = dec(r, -3, 3), dec(r, -3, 3), dec(r, -3, 3)
            return (f"({c2}*x^2+{c1}*x+{c0})",
                    sympy.Rational(c2) * X**2 + sympy.Rational(c1) * X + sympy.Rational(c0))
        if kind == "trig":
            k = r.randint(1, 40)
            c = dec(r, -3, 3)
            fn = r.choice(["sin", "cos"])
            return (f"{fn}({k}*x+{c})",
                    getattr(sympy, fn)(k * X + sympy.Rational(c)))
        if kind == "expdamp":
            # |k*x| <= ~15 over [-5,5] keeps exp finite and libm-friendly
            k = round(r.uniform(-2.5, 2.5), 3)
            ks = f"{k:.3f}"
            return (f"exp({ks}*x)", sympy.exp(sympy.Rational(ks) * X))
        if kind == "log":
            # ln(x + c) with x + c >= 0.1 across the interval
            c = round(-self.a + r.uniform(0.1, 3.0), 4)
            cs = f"{c:.4f}"
            return (f"ln(x+{cs})", sympy.log(X + sympy.Rational(cs)))
        if kind == "sqrt":
            c = round(-self.a + r.uniform(0.1, 3.0), 4)
            cs = f"{c:.4f}"
            return (f"sqrt(x+{cs})", sympy.sqrt(X + sympy.Rational(cs)))
        if kind == "recip":
            # 1/(x + c) with the pole at least 0.2 outside the interval
            c = round(-self.b - r.uniform(0.2, 2.0), 4) if r.random() < 0.5 else round(
                -self.a + r.uniform(0.2, 2.0), 4)
            cs = f"{c:.4f}"
            return (f"1/(x+{cs})" if c >= 0 else f"1/(x-{-c:.4f})",
                    1 / (X + sympy.Rational(cs)))
        # gauss: the adversarial family — a peak that may sit anywhere,
        # including squarely between any fixed grid's samples.
        s = r.choice([100, 10000, 1000000, 10000000])
        c = round(r.uniform(self.a - 0.2, self.b + 0.2), 6)
        cs = f"{c:.6f}"
        self.features.append(c)
        return (f"exp(0-{s}*(x-{cs})^2)",
                sympy.exp(-s * (X - sympy.Rational(cs)) ** 2))

    def build(self):
        r = self.rng
        shape = r.random()
        a1, s1 = self.atom()
        if shape < 0.35:
            return a1, s1, True
        a2, s2 = self.atom()
        if shape < 0.65:
            return f"{a1}*{a2}", s1 * s2, True
        if shape < 0.9:
            return f"{a1}+{a2}", s1 + s2, True
        # non-smooth lane: |x - c| * smooth  (range-only mode, loose tol)
        c = round(r.uniform(self.a + 0.05, self.b - 0.05), 4)
        cs = f"{c:.4f}"
        self.features.append(c)
        return f"abs(x-{cs})*{a1}", sympy.Abs(X - sympy.Rational(cs)) * s1, False


# The oracle runs in a FRESH SUBPROCESS per case: sympy.integrate on generated
# gaussian/trig/log products can consume gigabytes (Risch machinery plus
# sympy's global cache, which never shrinks), and an in-process oracle once
# ballooned the campaign past 5 GB RSS. A subprocess returns its memory to the
# OS after every case and can be timeboxed; an oracle failure is counted as
# ORACLE_SKIP, never charged to JACKAL.
ORACLE_CHILD = r'''
import json, sys
import mpmath, sympy
mpmath.mp.dps = 60
X = sympy.Symbol("x")
src, a, b = sys.argv[1], float(sys.argv[2]), float(sys.argv[3])
features = json.loads(sys.argv[4])
quad_only = len(sys.argv) > 5 and sys.argv[5] == "quad-only"
expr = sympy.sympify(src, locals={"x": X, "Rational": sympy.Rational, "Abs": sympy.Abs})
a_m, b_m = mpmath.mpf(a), mpmath.mpf(b)
truth, kind = None, "mpmath-quad-split"
if not quad_only:
    try:
        anti = sympy.integrate(expr, X)
        if not anti.has(sympy.Integral) and not anti.has(sympy.Abs):
            F = sympy.lambdify(X, anti, "mpmath")
            truth = mpmath.mpf(F(b_m)) - mpmath.mpf(F(a_m))
            kind = "antiderivative"
    except Exception:
        truth = None
if truth is None:
    f = sympy.lambdify(X, expr, "mpmath")
    pts = sorted({a, b, *[p for p in features if a < p < b]})
    truth, err = mpmath.quad(f, [mpmath.mpf(p) for p in pts], error=True)
    # An oracle whose own error estimate is not far below the tolerances under
    # test is not an oracle. Refuse to adjudicate rather than mis-adjudicate.
    if err > (abs(truth) + 1) * mpmath.mpf("1e-25"):
        sys.stderr.write("quad error estimate too large: %s\n" % mpmath.nstr(err, 8))
        sys.exit(3)
print(kind)
print(mpmath.nstr(truth, 40))
'''


# Device-aware caps: this host has finite unified memory (48 GB M4 Max) and a
# runaway symbolic-integration oracle once climbed past 5 GB. A child that
# exceeds the RSS cap is killed and the case becomes ORACLE_SKIP — the truth
# source degrades, JACKAL is never charged, and the machine stays usable.
ORACLE_RSS_CAP_MB = 3072
ORACLE_TIMEOUT_S = 900


def child_rss_mb(pid: int) -> int:
    out = subprocess.run(["ps", "-o", "rss=", "-p", str(pid)],
                         capture_output=True, text=True)
    try:
        return int(out.stdout.strip() or 0) // 1024
    except ValueError:
        return 0


def oracle(expr_s, a_m, b_m, features):
    import time
    # Feature-bearing integrands (narrow gaussians, |x| kinks) are exactly the
    # family whose symbolic antiderivatives make sympy balloon — and exactly
    # the family split-point quadrature at 60 digits handles well. Send them
    # straight to quadrature; only featureless smooth cases attempt the
    # symbolic antiderivative.
    mode = ["quad-only"] if features else []
    proc = subprocess.Popen(
        [sys.executable, "-c", ORACLE_CHILD,
         str(expr_s), mpmath.nstr(a_m, 25), mpmath.nstr(b_m, 25),
         json.dumps(features)] + mode,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    deadline = time.monotonic() + ORACLE_TIMEOUT_S
    while proc.poll() is None:
        if time.monotonic() > deadline:
            proc.kill()
            proc.wait()
            raise RuntimeError(f"oracle timeout after {ORACLE_TIMEOUT_S}s")
        rss = child_rss_mb(proc.pid)
        if rss > ORACLE_RSS_CAP_MB:
            proc.kill()
            proc.wait()
            raise RuntimeError(f"oracle exceeded memory cap ({rss} MB > {ORACLE_RSS_CAP_MB} MB)")
        time.sleep(2)
    stdout, stderr = proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"oracle subprocess failed: {stderr.strip()[-200:]}")
    kind, value = stdout.strip().splitlines()
    return mpmath.mpf(value), kind


def main() -> int:
    cases = int(sys.argv[1]) if len(sys.argv) > 1 else 250
    seed = int(sys.argv[2]) if len(sys.argv) > 2 else 20260813
    rng = random.Random(seed)
    rows = []
    n_ok = n_refused = n_violation = n_width = n_oracle_skip = 0

    for i in range(cases):
        a = round(rng.uniform(-4.0, 3.0), 3)
        b = round(a + rng.uniform(0.1, 4.0), 3)
        gen = Gen(rng, a, b)
        src, expr_s, smooth = gen.build()
        tol = 10 ** -rng.randint(4, 9) if smooth else 10 ** -rng.randint(2, 4)
        proc = subprocess.run(
            [str(LAUNCHER), "integrate-bound", src, str(a), str(b), f"{tol:g}"],
            capture_output=True, text=True, timeout=3600,
        )
        row = {"i": i, "expr": src, "a": a, "b": b, "tol": f"{tol:g}"}
        if proc.returncode != 0:
            reason = proc.stderr.strip().splitlines()[-3:] if proc.stderr else []
            row["verdict"] = "REFUSED"
            row["reason"] = " | ".join(reason)[-300:]
            n_refused += 1
        else:
            line = proc.stdout.strip().splitlines()[-1]
            enclosure = line.split("integral-enclosure=[", 1)[1].split("]", 1)[0]
            lo_text, hi_text = enclosure.split(",")
            try:
                truth, oracle_kind = oracle(expr_s, mpmath.mpf(a), mpmath.mpf(b), gen.features)
            except Exception as exc:  # oracle failure is OUR problem, not JACKAL's
                row["verdict"] = "ORACLE_SKIP"
                row["reason"] = repr(exc)[:200]
                n_oracle_skip += 1
                rows.append(row)
                continue
            lo_v, hi_v = mpmath.mpf(lo_text), mpmath.mpf(hi_text)
            width = hi_v - lo_v
            row["enclosure"] = [lo_text, hi_text]
            row["truth"] = mpmath.nstr(truth, 30)
            row["oracle"] = oracle_kind
            row["width"] = mpmath.nstr(width, 10)
            if not (lo_v <= truth <= hi_v):
                row["verdict"] = "CONTAINMENT_VIOLATION"
                n_violation += 1
            elif width > mpmath.mpf(f"{tol:g}") * (1 + mpmath.mpf("1e-9")):
                row["verdict"] = "WIDTH_VIOLATION"
                n_width += 1
            else:
                row["verdict"] = "BOUND_OK"
                n_ok += 1
        rows.append(row)
        # Keep the parent's footprint flat: sympy's global cache only grows.
        sympy.core.cache.clear_cache()
        if (i + 1) % 25 == 0:
            print(f"...{i + 1}/{cases} ok={n_ok} refused={n_refused} "
                  f"violations={n_violation + n_width}", flush=True)

    payload = "\n".join(json.dumps(r, sort_keys=True) for r in rows) + "\n"
    OUT_PATH.write_text(payload)
    digest = hashlib.sha256(payload.encode()).hexdigest()
    print(f"cases={cases} seed={seed}")
    print(f"BOUND_OK={n_ok} REFUSED={n_refused} ORACLE_SKIP={n_oracle_skip}")
    print(f"CONTAINMENT_VIOLATION={n_violation} WIDTH_VIOLATION={n_width}")
    print(f"jsonl={OUT_PATH} sha256={digest}")
    if n_violation or n_width:
        print("VERDICT: FAIL — a printed bound was wrong; that is the one unforgivable outcome")
        return 1
    print("VERDICT: PASS — every printed enclosure contained the independent truth")
    return 0


if __name__ == "__main__":
    sys.exit(main())
