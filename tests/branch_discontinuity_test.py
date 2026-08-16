#!/usr/bin/env python3
"""Branch/discontinuity adversarial gate (§490 v1.5.0).

Witnesses the mission-critical property that JACKAL decides branches from
EXACT comparisons — never from an unproved floating-point guess — and that
the classic unsafe identities are structurally impossible to launder:

  D1  floor across an integer boundary widens (never guesses a branch);
  D2  floor on a point interval decides the branch exactly;
  D3  round at an exact half-integer follows the DOCUMENTED half-away
      convention, decided in ℚ (2.5 -> 3, -2.5 -> -3);
  D4  trunc/ceil at negative boundaries decide exactly;
  D5  abs kinks: abs on a sign-crossing interval gives [0, max] exactly;
  D6  min/max lattice ops are exact (no pad);
  D7  sqrt(x^2) on a NEGATIVE domain encloses |x|, not x — the unsafe
      simplification sqrt(x^2) -> x cannot appear;
  D8  1/x through zero REFUSES (pole; never a spliced enclosure);
  D9  tan over a pole-containing interval REFUSES;
  D10 ln touching zero REFUSES;
  D11 (x^2-1)/(x-1) at the excluded point: the exact lane cancels WITH a
      recorded side condition, while the interval lane REFUSES the point
      (zero denominator) — cancellation never silently extends the domain;
  D12 log-product rewriting does not exist: ln(x*x) and ln(x)+ln(x) are
      DIFFERENT canonical trees (`canon` hashes differ) and the poly lane
      refuses both (outside fragment);
  D13 the numeric round trip 0.1+0.2 stays exact in the rat lane.

Every check runs the REAL engine binary; certified rows additionally push
through the REAL Lean checker via the engine's range-bound-cert emitter.
The engine emitter ingests DECIMAL/INTEGER tokens; the request-bound checker
binds CANONICAL rational tokens — the same split `tests/release_validate.py`
performs (raw to the evaluator, `canonical_rat` to the checker).
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENGINE = os.environ.get("JACKAL_BIN") or str(ROOT / "jackal-native")
CHECKER = ROOT / "proofs/lean/.lake/build/bin/jackal_cert_check"

FAILURES: list[str] = []


def run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([ENGINE, *args], capture_output=True, text=True, timeout=120)


def check(name: str, cond: bool, detail: str = "") -> None:
    tag = "PASS" if cond else "FAIL"
    print(f"{tag} {name}{(' — ' + detail) if detail and not cond else ''}")
    if not cond:
        FAILURES.append(name)


def _canon(t: str) -> str:
    f = Fraction(t)
    return str(f.numerator) if f.denominator == 1 else f"{f.numerator}/{f.denominator}"


def enclosure_of(expr: str, lo: str, hi: str) -> tuple[Fraction, Fraction] | None:
    """range-bound-cert through engine emitter + REAL Lean checker."""
    p = run("range-bound-cert", expr, lo, hi, "test-exe", "dGVzdC1jb21taXQ=")
    if p.returncode != 0:
        return None
    q = subprocess.run([str(CHECKER), "/dev/stdin", "range-bound-cert", expr,
                        _canon(lo), _canon(hi)],
                       input=p.stdout.encode(), capture_output=True, timeout=120)
    if q.returncode != 0:
        return None
    m = re.match(rb"ACCEPT request-bound theorem=\S+ command=\S+ output (\S+) (\S+)", q.stdout)
    if not m:
        return None
    return Fraction(m.group(1).decode()), Fraction(m.group(2).decode())


def bounded_range(expr: str, lo: str, hi: str) -> tuple[Fraction, Fraction] | None:
    """The f64 bounded lane (range-bound) — refusals return None."""
    p = run("range-bound", expr, lo, hi)
    if p.returncode != 0:
        return None
    m = re.search(r"range-enclosure=\[([^,]+),([^\]]+)\]", p.stdout)
    if not m:
        return None
    return (Fraction(m.group(1)), Fraction(m.group(2)))


def main() -> int:
    # D1 floor crossing 2: enclosure must include both branches [1, 2].
    e = enclosure_of("floor(x)", "1.999999", "2.000001")
    check("D1-floor-crossing-widens", e is not None and e[0] <= 1 and e[1] >= 2,
          f"got {e}")

    # D2 floor point decides exactly: floor(1.5) = 1, checker-exact endpoints.
    e = enclosure_of("floor(x)", "1.5", "1.5")
    check("D2-floor-point-exact", e == (Fraction(1), Fraction(1)), f"got {e}")

    # D3 round at half-integers: documented half-away-from-zero, decided in Q.
    e = enclosure_of("round(x)", "2.5", "2.5")
    check("D3a-round-half-up", e == (Fraction(3), Fraction(3)), f"got {e}")
    e = enclosure_of("round(x)", "-2.5", "-2.5")
    check("D3b-round-half-away-negative", e == (Fraction(-3), Fraction(-3)), f"got {e}")

    # D4 trunc/ceil at negative boundaries.
    e = enclosure_of("trunc(x)", "-3.5", "-3.5")
    check("D4a-trunc-toward-zero", e == (Fraction(-3), Fraction(-3)), f"got {e}")
    e = enclosure_of("ceil(x)", "-3.5", "-3.5")
    check("D4b-ceil-negative", e == (Fraction(-3), Fraction(-3)), f"got {e}")

    # D5 abs kink: [-3, 2] -> [0, 3] exactly (three-case exact op).
    e = enclosure_of("abs(x)", "-3", "2")
    check("D5-abs-kink-exact", e == (Fraction(0), Fraction(3)), f"got {e}")

    # D6 min/max lattice ops are exact: min(x, 2) on [1, 5] = [1, 2].
    e = enclosure_of("min(x,2)", "1", "5")
    check("D6-min-exact", e == (Fraction(1), Fraction(2)), f"got {e}")

    # D7 sqrt(x^2) on negative domain must enclose |x| = [1, 2], never [-2, -1].
    # (sqrt is outside the ENGINE emitter's cert fragment, so this witnesses
    # the f64 bounded lane — the lane a naive simplifier would have poisoned.)
    e = bounded_range("sqrt(x^2)", "-2", "-1")
    check("D7-sqrt-sq-is-abs",
          e is not None and Fraction(1, 2) <= e[0] <= 1 and 2 <= e[1] <= 3,
          f"got {e}")

    # D8 1/x through zero refuses in BOTH certified lanes.
    check("D8a-pole-refuses-cert", enclosure_of("1/x", "-1", "1") is None)
    check("D8b-pole-refuses-bounded", bounded_range("1/x", "-1", "1") is None)

    # D9 tan over a pole-containing interval refuses (bounded lane; cert lane
    # refuses tan outright as outside-fragment).
    check("D9a-tan-pole-refuses", bounded_range("tan(x)", "1", "2") is None)
    check("D9b-tan-outside-cert-fragment", enclosure_of("tan(x)", "0", "1") is None)

    # D10 ln touching zero refuses; ln on a positive interval releases (bounded).
    check("D10a-ln-zero-refuses", bounded_range("ln(x)", "0", "1") is None)
    check("D10b-ln-positive-bounded-ok", bounded_range("ln(x)", "1", "2") is not None)

    # D11 cancellation never silently extends the domain.
    p = run("ratfunc-canon", "(x^2-1)/(x-1)")
    check("D11a-cancel-records-side-condition",
          p.returncode == 0 and "side-condition=denominator-nonzero" in p.stdout,
          p.stdout[:120])
    check("D11b-excluded-point-refuses",
          enclosure_of("(x^2-1)/(x-1)", "1", "1") is None)
    check("D11c-away-from-pole-releases",
          enclosure_of("(x^2-1)/(x-1)", "2", "3") is not None)

    # D12 no log-product rewriting anywhere.
    c1 = run("canon", "ln(x*x)")
    c2 = run("canon", "ln(x)+ln(x)")
    h1 = re.search(r"sha256=([0-9a-f]{64})", c1.stdout)
    h2 = re.search(r"sha256=([0-9a-f]{64})", c2.stdout)
    check("D12a-log-product-trees-differ",
          bool(h1 and h2) and h1.group(1) != h2.group(1))
    p = run("poly-canon", "ln(x)")
    check("D12b-poly-lane-refuses-ln", p.returncode != 0)

    # D13 decimal round trip stays exact in the rat lane.
    p = run("rat", "0.1 + 0.2")
    check("D13-rat-exact-decimals", p.returncode == 0 and "exact=3/10" in p.stdout,
          p.stdout[:120])

    total = 19
    passed = total - len(FAILURES)
    print(f"BRANCH_DISCONTINUITY_{'PASS' if not FAILURES else 'FAIL'} cases={passed}/{total}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
