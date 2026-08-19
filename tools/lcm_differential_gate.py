#!/usr/bin/env python3
"""Differential gate for the `lcm` command's `class=exact` declaration.

Why this gate exists
--------------------
`maturity` declares `lcm` as `class=exact` with
`residual=none-observed-within-grammar-and-budgets`. Before 2026-08-19 the
implementation was `positive_abs(a / gcd_safe(a, b) * b)` evaluated in i64, which
WRAPS once the true lcm exceeds `2^63 - 1`. Two observed failures on shipped
binaries:

    lcm 4611686018427387904 3  ->  4611686018427387904   (true 13835058055282163712)
    lcm 9223372036854775807 3  ->  9223372036854775805   (true 27670116110564327421)

The first is smaller than one of its own inputs, which no least common multiple
can be. A command that declares `exact` and silently returns a wrapped value is a
mislabeled epistemic class, which is the precise failure this engine exists to
prevent. This gate makes that class of regression loud.

What it compares
----------------
Primary oracle, in-engine and authoritative: the engine's own arbitrary-precision
`rat` lane evaluating `(a / gcd(a,b)) * b`. Both sides therefore come from the
same binary under test, and a disagreement is an internal inconsistency the
engine cannot explain away.

Secondary oracle, test-only: Python's `math.lcm`. This is a third opinion for the
gate's own benefit. It is NOT an assurance source and never contributes to a
claim; per `domain_packs/PACK_SPEC.md` §1, Python may verify but may not compute a
substitute answer on the authoritative path.

Exit status is 0 only when every case agrees on both oracles.
"""

from __future__ import annotations

import argparse
import math
import re
import subprocess
import sys
import time
from pathlib import Path

DEFAULT_PIN = "/Users/sicarii/anubis-lang/vm/pins/anubis-a733565f237d"
ENTRY = "jackal_calc.anb"
I64_MAX = 2**63 - 1

# Frozen boundary corpus. Chosen so that the wrapped implementation fails on the
# `overflow` rows and passes on the `fits` rows: a gate that only exercised small
# values would have reported PASS against the defective build.
CORPUS: tuple[tuple[int, int, str], ...] = (
    # --- small, must be unchanged by any fix (regression guard) ---
    (1, 1, "fits"),
    (2, 3, "fits"),
    (4, 6, "fits"),
    (8, 12, "fits"),
    (6, 15, "fits"),
    (12, 18, "fits"),
    (7, 7, "fits"),
    (9, 28, "fits"),
    (100, 250, "fits"),
    (1024, 768, "fits"),
    # --- zero and identity edges ---
    (0, 5, "fits"),
    (5, 0, "fits"),
    (0, 0, "fits"),
    (1, I64_MAX, "fits"),
    (I64_MAX, 1, "fits"),
    (I64_MAX, I64_MAX, "fits"),
    # --- negative inputs; lcm is non-negative ---
    (-12, 18, "fits"),
    (12, -18, "fits"),
    (-12, -18, "fits"),
    (-1, I64_MAX, "fits"),
    # --- just inside the i64 ceiling ---
    (3037000499, 3037000493, "fits"),  # product 9223372012704246007 <= I64_MAX
    (2147483647, 2, "fits"),
    (4294967296, 2147483648, "fits"),  # nested powers of two, lcm = 2^32
    (2**31, 2**32, "fits"),
    (2**62, 2, "fits"),  # lcm = 2^62
    # --- the observed defect rows and their neighbourhood ---
    (2**62, 3, "overflow"),  # 13835058055282163712 > I64_MAX
    (I64_MAX, 3, "overflow"),  # 27670116110564327421
    (I64_MAX, 2, "overflow"),  # 18446744073709551614
    (I64_MAX, I64_MAX - 1, "overflow"),  # ~8.5e37
    (3037000499, 3037000507, "overflow"),  # 9223372055222252993 > I64_MAX
    (4294967296, 4294967297, "overflow"),  # 18446744078004518912
    (2**62, 5, "overflow"),
    (2**62, 7, "overflow"),
    (2**61, 3, "fits"),  # 6917529027641081856 <= I64_MAX (boundary partner)
    # 1000000007 * 1000000009 = 1000000016000000063, which is ~1.0e18 and so
    # comfortably below I64_MAX (~9.22e18). Annotated `overflow` on first write;
    # the gate's band cross-check caught that as a FAIL. Corrected to `fits` —
    # the measurement is the authority, the annotation is only a comment.
    (1000000007, 1000000009, "fits"),
    (999999937, 999999893, "fits"),  # two primes, product ~1e18
    (6, 35, "fits"),
    (2**40, 3**20, "overflow"),
    (12345678901, 98765432109, "overflow"),
)


class GateFailure(Exception):
    pass


def _run(pin: str, root: Path, argv: list[str], timeout: int = 120) -> str:
    completed = subprocess.run(
        [pin, "run", ENTRY, "--", *argv],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if completed.returncode != 0:
        raise GateFailure(
            f"engine exited {completed.returncode} for {argv}: "
            f"{(completed.stderr or completed.stdout).strip()[:200]}"
        )
    lines = [
        line
        for line in completed.stdout.splitlines()
        if line.strip() and not line.startswith("anubis run:")
    ]
    if not lines:
        raise GateFailure(f"engine produced no output line for {argv}")
    return lines[-1].strip()


def engine_lcm(pin: str, root: Path, a: int, b: int) -> int:
    text = _run(pin, root, ["lcm", str(a), str(b)])
    if not re.fullmatch(r"[0-9]+", text):
        raise GateFailure(f"lcm {a} {b} returned a non-decimal line: {text!r}")
    return int(text)


def engine_gcd(pin: str, root: Path, a: int, b: int) -> int:
    text = _run(pin, root, ["gcd", str(a), str(b)])
    if not re.fullmatch(r"-?[0-9]+", text):
        raise GateFailure(f"gcd {a} {b} returned a non-decimal line: {text!r}")
    return int(text)


def engine_rat_lcm(pin: str, root: Path, a: int, b: int, gcd: int) -> int:
    """The in-engine authoritative oracle: (a/gcd)*b through the `rat` lane."""
    reduced = abs(a) // gcd
    expression = f"{reduced}*{abs(b)}"
    text = _run(pin, root, ["rat", expression])
    match = re.search(r"exact=(-?[0-9]+)(?:\s|$)", text)
    if not match:
        raise GateFailure(f"rat {expression!r} produced no exact integer: {text!r}")
    return int(match.group(1))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pin", default=DEFAULT_PIN)
    parser.add_argument("--root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--limit", type=int, default=0, help="0 = whole corpus")
    args = parser.parse_args(argv)

    root = Path(args.root)
    if not (root / ENTRY).is_file():
        print(f"FAIL gate-setup: {ENTRY} not found under {root}")
        return 2
    if not Path(args.pin).exists():
        print(f"FAIL gate-setup: Anubis pin not found at {args.pin}")
        return 2

    cases = list(CORPUS)
    if args.limit:
        cases = cases[: args.limit]

    passed = 0
    failed = 0
    overflow_rows = 0
    started = time.time()

    for a, b, band in cases:
        label = f"lcm({a}, {b})"
        try:
            got = engine_lcm(args.pin, root, a, b)
            gcd = engine_gcd(args.pin, root, a, b)
            reference = 0 if gcd == 0 else engine_rat_lcm(args.pin, root, a, b, gcd)
            python_reference = math.lcm(a, b)
        except (GateFailure, subprocess.TimeoutExpired) as exc:
            print(f"FAIL {label:44s} {exc}")
            failed += 1
            continue

        # Record the true band from the reference, not from the corpus annotation:
        # the annotation is a comment, the reference is the measurement.
        true_band = "overflow" if python_reference > I64_MAX else "fits"
        if true_band == "overflow":
            overflow_rows += 1

        problems = []
        if got != python_reference:
            problems.append(f"engine {got} != math.lcm {python_reference}")
        if got != reference:
            problems.append(f"engine {got} != in-engine rat oracle {reference}")
        if got < 0:
            problems.append("lcm is negative")
        if a and b and got and (got % abs(a) or got % abs(b)):
            problems.append("result is not a common multiple of both inputs")
        if a and b and got and got < max(abs(a), abs(b)):
            problems.append("result is smaller than an input, which no lcm can be")
        if band != true_band:
            problems.append(f"corpus band {band!r} disagrees with measured {true_band!r}")

        if problems:
            print(f"FAIL {label:44s} {'; '.join(problems)}")
            failed += 1
        else:
            print(f"ok   {label:44s} = {got}  [{true_band}]")
            passed += 1

    elapsed = time.time() - started
    print(
        f"\ncases={len(cases)} passed={passed} failed={failed} "
        f"overflow_rows={overflow_rows} elapsed={elapsed:.1f}s"
    )
    if overflow_rows == 0:
        print(
            "FAIL gate-not-discriminating: no case exceeded i64, so this run could "
            "not have detected the wrapping defect it exists to catch"
        )
        return 2
    if failed:
        print(f"LCM_DIFFERENTIAL_GATE_FAIL failed={failed}")
        return 2
    print("LCM_DIFFERENTIAL_GATE_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
