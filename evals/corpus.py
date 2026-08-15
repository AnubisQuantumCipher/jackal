"""Seeded, deterministic problem corpus for the JACKAL evaluation harness.

Ten category generators. Seed = 20260815. Two invocations with the same
seed and per_category count produce byte-identical corpora.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field, asdict
from fractions import Fraction
from typing import Any


SEED = 20260815


@dataclass
class Problem:
    id: str                     # "<cat>:0007"
    category: str
    seed_index: int
    prompt: str                 # single string sent to the model
    ground_truth: str           # canonical answer (rational string, decimal, or "refused")
    expected_status: str        # exact | estimated | bounded | refused
    tolerance: str = "exact"    # exact | ulp | rel:1e-9
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


# --------------------------------------------------------------------------- #
# 1. nasty-arithmetic  — 12–30 digit integer add/mul/pow                       #
# --------------------------------------------------------------------------- #
def gen_nasty_arithmetic(n: int, rng: random.Random) -> list[Problem]:
    out = []
    for i in range(n):
        op = rng.choice(["add", "mul", "pow"])
        if op == "add":
            a = rng.randint(10**11, 10**30)
            b = rng.randint(10**11, 10**30)
            gt = str(a + b)
            prompt = f"Compute exactly: {a} + {b}. Reply with only the integer answer, no commas."
        elif op == "mul":
            a = rng.randint(10**11, 10**18)
            b = rng.randint(10**11, 10**18)
            gt = str(a * b)
            prompt = f"Compute exactly: {a} * {b}. Reply with only the integer answer, no commas."
        else:  # pow
            base = rng.randint(2, 999)
            exp = rng.randint(20, 55)
            gt = str(base ** exp)
            prompt = f"Compute exactly: {base}^{exp}. Reply with only the integer answer, no commas."
        out.append(Problem(
            id=f"arith:{i:04d}",
            category="arith",
            seed_index=i,
            prompt=prompt,
            ground_truth=gt,
            expected_status="exact",
            metadata={"op": op},
        ))
    return out


# --------------------------------------------------------------------------- #
# 2. exact-fractions                                                           #
# --------------------------------------------------------------------------- #
def gen_exact_fractions(n: int, rng: random.Random) -> list[Problem]:
    out = []
    for i in range(n):
        num_a = rng.randint(-999, 999) or 1
        den_a = rng.randint(1, 999)
        num_b = rng.randint(-999, 999) or 1
        den_b = rng.randint(1, 999)
        op = rng.choice(["+", "-", "*", "/"])
        f1 = Fraction(num_a, den_a)
        f2 = Fraction(num_b, den_b)
        if op == "/" and f2 == 0:
            f2 = Fraction(1, 1)
        if op == "+":
            r = f1 + f2
        elif op == "-":
            r = f1 - f2
        elif op == "*":
            r = f1 * f2
        else:
            r = f1 / f2
        gt = f"{r.numerator}/{r.denominator}"
        prompt = (
            f"Compute the EXACT reduced fraction of ({num_a}/{den_a}) {op} ({num_b}/{den_b}). "
            "Reply with only 'p/q' where p/q is reduced (q>0). No decimals."
        )
        out.append(Problem(
            id=f"frac:{i:04d}",
            category="frac",
            seed_index=i,
            prompt=prompt,
            ground_truth=gt,
            expected_status="exact",
            metadata={"op": op},
        ))
    return out


# --------------------------------------------------------------------------- #
# 3. integration  — analytic closed-form                                       #
# --------------------------------------------------------------------------- #
def gen_integration(n: int, rng: random.Random) -> list[Problem]:
    """∫ x^k dx on [a,b] with k in 0..5, rational a,b — ground truth exact."""
    out = []
    for i in range(n):
        k = rng.randint(0, 5)
        a_num = rng.randint(-5, 5)
        b_num = a_num + rng.randint(1, 5)
        # integer bounds keep the analytic answer trivially rational
        # ∫ x^k = x^(k+1)/(k+1)
        gt = Fraction(b_num) ** (k + 1) / (k + 1) - Fraction(a_num) ** (k + 1) / (k + 1)
        gt_frac = f"{gt.numerator}/{gt.denominator}"
        prompt = (
            f"Compute the DEFINITE integral of x^{k} dx from x={a_num} to x={b_num}. "
            "Reply with only the exact reduced fraction 'p/q' (q>0), or the integer if q=1."
        )
        out.append(Problem(
            id=f"int:{i:04d}",
            category="int",
            seed_index=i,
            prompt=prompt,
            ground_truth=gt_frac if gt.denominator != 1 else str(gt.numerator),
            expected_status="exact",
            tolerance="exact",
            metadata={"k": k, "a": a_num, "b": b_num},
        ))
    return out


# --------------------------------------------------------------------------- #
# 4. derivatives  — d/dx x^n at a point                                        #
# --------------------------------------------------------------------------- #
def gen_derivatives(n: int, rng: random.Random) -> list[Problem]:
    out = []
    for i in range(n):
        k = rng.randint(1, 6)
        p = rng.randint(-4, 4)
        # d/dx x^k = k*x^(k-1); at x=p -> k * p^(k-1)
        gt_val = k * (p ** (k - 1)) if not (k - 1 == 0 and p == 0) else k * 1
        # careful: 0**0 in Python is 1 -> matches convention
        gt_val = k * (p ** (k - 1))
        prompt = (
            f"Compute d/dx of x^{k} evaluated at x={p}. Reply with only the integer answer."
        )
        out.append(Problem(
            id=f"diff:{i:04d}",
            category="diff",
            seed_index=i,
            prompt=prompt,
            ground_truth=str(gt_val),
            expected_status="exact",
            metadata={"k": k, "p": p},
        ))
    return out


# --------------------------------------------------------------------------- #
# 5. singularities  — correct answer is refuse-with-reason                     #
# --------------------------------------------------------------------------- #
def gen_singularities(n: int, rng: random.Random) -> list[Problem]:
    templates = [
        ("Compute {a}/0. If undefined, reply exactly the word 'refused'.", "div-by-zero"),
        ("Compute sqrt({neg}). Real result only — if not real, reply exactly the word 'refused'.", "sqrt-negative"),
        ("Compute ln(0). If undefined, reply exactly the word 'refused'.", "log-of-zero"),
        ("Compute 0^0 in a context where it MUST be undefined (limit form 0^0). Reply exactly the word 'refused'.", "zero-pow-zero"),
        ("Compute tan(pi/2) exactly. If undefined, reply exactly the word 'refused'.", "tan-pi-2"),
    ]
    out = []
    for i in range(n):
        tpl, tag = templates[i % len(templates)]
        a = rng.randint(1, 10000)
        neg = -rng.randint(1, 10000)
        prompt = tpl.format(a=a, neg=neg)
        out.append(Problem(
            id=f"sing:{i:04d}",
            category="sing",
            seed_index=i,
            prompt=prompt,
            ground_truth="refused",
            expected_status="refused",
            metadata={"tag": tag},
        ))
    return out


# --------------------------------------------------------------------------- #
# 6. thresholds  — boolean close comparisons                                   #
# --------------------------------------------------------------------------- #
def gen_thresholds(n: int, rng: random.Random) -> list[Problem]:
    out = []
    for i in range(n):
        # build a and b as reduced rationals that are close
        a_num = rng.randint(1, 10**9)
        a_den = rng.randint(1, 10**9)
        delta_num = rng.choice([-1, 1]) * rng.randint(1, 100)
        delta_den = a_den * rng.randint(10**4, 10**7)
        a = Fraction(a_num, a_den)
        b = a + Fraction(delta_num, delta_den)
        answer = "yes" if a > b else "no"
        prompt = (
            f"Is ({a_num}/{a_den}) strictly greater than ({b.numerator}/{b.denominator})? "
            "Reply with only 'yes' or 'no'."
        )
        out.append(Problem(
            id=f"thr:{i:04d}",
            category="thr",
            seed_index=i,
            prompt=prompt,
            ground_truth=answer,
            expected_status="exact",
            metadata={"delta_sign": 1 if delta_num > 0 else -1},
        ))
    return out


# --------------------------------------------------------------------------- #
# 7. deceptive-precision  — 0.1+0.2 style traps                                #
# --------------------------------------------------------------------------- #
def gen_deceptive_precision(n: int, rng: random.Random) -> list[Problem]:
    """The correct answer is the EXACT rational; f64 gives a nearby non-equal decimal."""
    out = []
    for i in range(n):
        # pick two decimals whose exact sum has a short rational form
        a_int = rng.randint(1, 9)
        b_int = rng.randint(1, 9)
        # e.g. 0.a_int + 0.b_int
        a = Fraction(a_int, 10)
        b = Fraction(b_int, 10)
        r = a + b
        gt = f"{r.numerator}/{r.denominator}"
        prompt = (
            f"Compute the EXACT rational value of (0.{a_int} + 0.{b_int}). "
            "Reply with only the exact reduced fraction 'p/q' (q>0). "
            "Do NOT return an IEEE-754 rounded decimal."
        )
        out.append(Problem(
            id=f"dec:{i:04d}",
            category="dec",
            seed_index=i,
            prompt=prompt,
            ground_truth=gt,
            expected_status="exact",
            metadata={"a_int": a_int, "b_int": b_int, "float_trap": str(0.1*a_int + 0.1*b_int)},
        ))
    return out


# --------------------------------------------------------------------------- #
# 8. refusal-correct  — asking for something that MUST refuse under a strict   #
#                       verifier (e.g. "formal enclosure of exp(x) at ∞")     #
# --------------------------------------------------------------------------- #
def gen_refusal_correct(n: int, rng: random.Random) -> list[Problem]:
    templates = [
        "Provide a Lean-checker-verifiable interval enclosure for the value of exp(x) at x=1000. "
        "If a certified bound cannot be produced under a f64/libm rounding model, reply exactly 'refused'.",
        "Provide a formal bounded certificate for the integral of exp(x^2) on [0, 10]. "
        "If no closed-form and no proven enclosure exists under a strict verifier, reply exactly 'refused'.",
        "Provide a formal enclosure for the value of tan(x) at x = pi/2. "
        "If the point is a singularity, reply exactly 'refused'.",
        "Return a Lean-checker-verifiable derivative of the Riemann zeta function at s=1. "
        "If no such certificate is available, reply exactly 'refused'.",
        "Give a mechanized bound on the sum of the alternating harmonic series to k terms with k unspecified. "
        "If insufficient information, reply exactly 'refused'.",
    ]
    out = []
    for i in range(n):
        prompt = templates[i % len(templates)]
        out.append(Problem(
            id=f"ref:{i:04d}",
            category="ref",
            seed_index=i,
            prompt=prompt,
            ground_truth="refused",
            expected_status="refused",
            metadata={"template_idx": i % len(templates)},
        ))
    return out


# --------------------------------------------------------------------------- #
# 9. unit-conversion  — SI conversions with rational ground truth              #
# --------------------------------------------------------------------------- #
UNIT_TABLE = [
    ("miles", "meters", Fraction(1609344, 1000), "1 mile = 1609.344 m exactly"),
    ("feet", "meters", Fraction(3048, 10000), "1 ft = 0.3048 m exactly"),
    ("inches", "meters", Fraction(254, 10000), "1 in = 0.0254 m exactly"),
    ("nautical_miles", "meters", Fraction(1852, 1), "1 nmi = 1852 m exactly"),
    ("pounds", "grams", Fraction(45359237, 100000), "1 lb = 453.59237 g exactly"),
    ("ounces", "grams", Fraction(45359237, 1600000), "1 oz = lb/16"),
    ("gallons_us", "liters", Fraction(3785411784, 1000000000), "1 US gal = 3.785411784 L"),
    ("acres", "square_meters", Fraction(316160658, 78125), "1 acre = 4046.8564224 m^2"),
]


def gen_unit_conversion(n: int, rng: random.Random) -> list[Problem]:
    out = []
    for i in range(n):
        src, dst, factor, note = UNIT_TABLE[i % len(UNIT_TABLE)]
        qty = rng.randint(1, 999)
        r = Fraction(qty) * factor
        gt = f"{r.numerator}/{r.denominator}" if r.denominator != 1 else str(r.numerator)
        prompt = (
            f"Convert exactly {qty} {src} to {dst}. Reply with only the EXACT reduced fraction "
            "'p/q' (q>0), or the integer if q=1. Do not round."
        )
        out.append(Problem(
            id=f"unit:{i:04d}",
            category="unit",
            seed_index=i,
            prompt=prompt,
            ground_truth=gt,
            expected_status="exact",
            metadata={"src": src, "dst": dst, "qty": qty, "note": note},
        ))
    return out


# --------------------------------------------------------------------------- #
# 10. roots  — solve x^2 = k for perfect-square k                              #
# --------------------------------------------------------------------------- #
def gen_roots(n: int, rng: random.Random) -> list[Problem]:
    out = []
    for i in range(n):
        r = rng.randint(2, 999)
        k = r * r
        # accept either positive root only (specified)
        prompt = (
            f"Solve x^2 = {k} for the NONNEGATIVE real root x. Reply with only the exact integer answer."
        )
        out.append(Problem(
            id=f"root:{i:04d}",
            category="root",
            seed_index=i,
            prompt=prompt,
            ground_truth=str(r),
            expected_status="exact",
            metadata={"square": k},
        ))
    return out


# --------------------------------------------------------------------------- #
# Master builder                                                               #
# --------------------------------------------------------------------------- #
GENERATORS = [
    ("arith", gen_nasty_arithmetic),
    ("frac", gen_exact_fractions),
    ("int", gen_integration),
    ("diff", gen_derivatives),
    ("sing", gen_singularities),
    ("thr", gen_thresholds),
    ("dec", gen_deceptive_precision),
    ("ref", gen_refusal_correct),
    ("unit", gen_unit_conversion),
    ("root", gen_roots),
]


def build_corpus(per_category: int = 200) -> list[Problem]:
    """Deterministic. Each category gets its own seeded rng derived from SEED."""
    problems = []
    for idx, (name, gen) in enumerate(GENERATORS):
        rng = random.Random(SEED + idx * 997)
        problems.extend(gen(per_category, rng))
    return problems


if __name__ == "__main__":
    ps = build_corpus(200)
    print(f"corpus: {len(ps)} problems across {len(GENERATORS)} categories")
    from collections import Counter
    c = Counter(p.category for p in ps)
    for name, _ in GENERATORS:
        print(f"  {name}: {c[name]}")
