#!/usr/bin/env python3
"""Untrusted producer for compact Gaussian integration certificates.

This program never adjudicates a formal claim.  It emits deterministic exact-
rational witness parameters and a candidate enclosure for the independent Lean
checker to recompute.  Any producer bug must therefore become checker refusal.
"""
from __future__ import annotations

import argparse
import math
import re
import sys
from fractions import Fraction
from functools import lru_cache
from typing import Iterable, Tuple


SCHEMA = "jackal-gaussian-integral-cert v1"
FAMILY = "gaussian-exp-square-v1"
METHOD = "gaussian-total-minus-tails-v1"
CORE = Fraction(6)
EXP_DEGREE = 96
OUTPUT_DECIMALS = 24
SQRT_PI_LO = Fraction(177245385090551, 100000000000000)
SQRT_PI_HI = Fraction(22155673136319, 12500000000000)

_CANON_RAT = re.compile(r"^(-?(?:0|[1-9][0-9]*))(?:/([2-9][0-9]*|1[0-9]+))?$")
_CANON_DEC = r"(?:0|[1-9][0-9]*)(?:\.[0-9]*[1-9])?"
_GAUSSIAN = re.compile(
    rf"^exp\(-(?P<a>{_CANON_DEC})\*\(x-(?P<mu>{_CANON_DEC})\)\^2\)$"
)


class Refusal(ValueError):
    """The requested formal family is not admitted by this producer."""


def parse_canonical_rat(text: str, name: str) -> Fraction:
    match = _CANON_RAT.fullmatch(text)
    if match is None:
        raise Refusal(f"{name} is not a canonical rational")
    numerator = int(match.group(1))
    denominator = int(match.group(2) or "1")
    if denominator != 1 and (numerator == 0 or math.gcd(abs(numerator), denominator) != 1):
        raise Refusal(f"{name} is not reduced canonical rational form")
    return Fraction(numerator, denominator)


def parse_canonical_decimal(text: str, name: str) -> Fraction:
    if re.fullmatch(_CANON_DEC, text) is None:
        raise Refusal(f"{name} is not a canonical nonnegative decimal")
    if "." not in text:
        return Fraction(int(text))
    whole, fractional = text.split(".", 1)
    return Fraction(int(whole + fractional), 10 ** len(fractional))


def rat_text(value: Fraction) -> str:
    if value.denominator == 1:
        return str(value.numerator)
    return f"{value.numerator}/{value.denominator}"


def exact_positive_square_root(value: Fraction) -> Fraction:
    if value <= 0:
        raise Refusal("A must be positive")
    numerator = math.isqrt(value.numerator)
    denominator = math.isqrt(value.denominator)
    if numerator * numerator != value.numerator or denominator * denominator != value.denominator:
        raise Refusal("A must be an exact square of a positive rational")
    return Fraction(numerator, denominator)


@lru_cache(maxsize=None)
def exp_neg_bounds(z: Fraction, degree: int = EXP_DEGREE) -> Tuple[Fraction, Fraction]:
    """Candidate pure-rational enclosure of exp(-z), for z >= 0.

    The Lean checker independently recomputes the same finite sums and proves
    their relation to Real.exp.  This implementation is only a producer.
    """
    if z < 0:
        raise Refusal("internal exp certificate argument must be nonnegative")
    term = Fraction(1)
    partial = term
    # S_degree contains terms 0 .. degree-1, matching Finset.range degree
    # in the independently compiled Lean checker.
    for k in range(1, degree):
        term *= z / k
        partial += term
    if z / (degree + 1) > Fraction(1, 2):
        raise Refusal("exp certificate degree is insufficient for its argument")
    remainder = 2 * z ** degree / math.factorial(degree)
    return 1 / (partial + remainder), 1 / partial


def outward_decimal(value: Fraction, digits: int, upper: bool) -> Fraction:
    denominator = 10 ** digits
    scaled = value * denominator
    if upper:
        integer = -((-scaled.numerator) // scaled.denominator)
    else:
        integer = scaled.numerator // scaled.denominator
    return Fraction(integer, denominator)


def gaussian_enclosure(scale: Fraction) -> Tuple[Fraction, Fraction]:
    # Two infinite tails: 2 * exp(-T^2)/(2T) = exp(-T^2)/T.
    tails_hi = exp_neg_bounds(CORE * CORE)[1] / CORE
    exact_lo = (SQRT_PI_LO - tails_hi) / scale
    exact_hi = SQRT_PI_HI / scale
    return (
        outward_decimal(exact_lo, OUTPUT_DECIMALS, upper=False),
        outward_decimal(exact_hi, OUTPUT_DECIMALS, upper=True),
    )


def emit_certificate(expression: str, lower_text: str, upper_text: str, tolerance_text: str) -> str:
    match = _GAUSSIAN.fullmatch(expression)
    if match is None:
        raise Refusal("expression is outside canonical gaussian-exp-square-v1 grammar")
    a_text = match.group("a")
    mu_text = match.group("mu")
    a_value = parse_canonical_decimal(a_text, "A")
    mu_value = parse_canonical_decimal(mu_text, "mu")
    lower = parse_canonical_rat(lower_text, "lower")
    upper = parse_canonical_rat(upper_text, "upper")
    tolerance = parse_canonical_rat(tolerance_text, "tolerance")
    if lower >= upper:
        raise Refusal("lower must be less than upper")
    if tolerance <= 0:
        raise Refusal("tolerance must be positive")
    scale = exact_positive_square_root(a_value)
    transformed_lower = scale * (lower - mu_value)
    transformed_upper = scale * (upper - mu_value)
    if transformed_lower > -CORE or transformed_upper < CORE:
        raise Refusal("transformed interval does not contain the certified central interval")

    output_lo, output_hi = gaussian_enclosure(scale)
    if output_hi - output_lo > tolerance:
        raise Refusal("formal gaussian configuration cannot meet the requested tolerance")

    lines: Iterable[str] = (
        SCHEMA,
        "operation integrate",
        "assurance formal-bounded",
        f"family {FAMILY}",
        f"expression {expression}",
        f"lower {lower_text}",
        f"upper {upper_text}",
        f"tolerance {tolerance_text}",
        f"A-token {a_text}",
        f"mu-token {mu_text}",
        f"scale {rat_text(scale)}",
        f"method {METHOD}",
        f"core {rat_text(CORE)}",
        f"degree {EXP_DEGREE}",
        f"sqrt-pi-lower {rat_text(SQRT_PI_LO)}",
        f"sqrt-pi-upper {rat_text(SQRT_PI_HI)}",
        f"output {rat_text(output_lo)} {rat_text(output_hi)}",
        "end",
    )
    return "\n".join(lines) + "\n"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    emit = sub.add_parser("emit")
    emit.add_argument("--expression", required=True)
    emit.add_argument("--lower", required=True)
    emit.add_argument("--upper", required=True)
    emit.add_argument("--tolerance", required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        if args.command != "emit":
            raise Refusal("unsupported command")
        sys.stdout.write(emit_certificate(args.expression, args.lower, args.upper, args.tolerance))
        return 0
    except Refusal as exc:
        print(f"REFUSED reason={exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
