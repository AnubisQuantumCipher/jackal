#!/usr/bin/env python3 -B
"""Exact-rational checker for the fixed HELLGATE nonlinear Barta certificate.

The producer is deliberately not imported.  This verifier uses only Python's
integer and ``Fraction`` arithmetic.  Transcendentals are enclosed by a second
implementation based on rational Taylor bounds.  Acceptance means the encoded
positive normalized trial function has a globally bounded nonlinear Rayleigh
quotient; the nonlinear Barta comparison theorem then encloses the unique
positive normalized ground-state eigenvalue.

The same replay additionally encloses diagnostics of the normalized trial and,
under a stated strong-convexity theorem, transfers only the quartic norm and
energy functional to the ground state.  Subject fields and non-claims prevent
the trial moments from being presented as ground-state quantities.

This checker is not a Lean theorem and never returns ``formal-bounded``.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import sys
from fractions import Fraction
from math import comb, factorial, isqrt, lcm
from pathlib import Path
from typing import Any


SCHEMA = "jackal-hellgate-barta-certificate-v1"
RESULT_SCHEMA = "jackal-hellgate-barta-verification-v1"
MAX_CERTIFICATE_BYTES = 4 * 1024 * 1024
MAX_JSON_DEPTH = 16
MAX_JSON_NODES = 40000
MAX_INTEGER_DIGITS = 384
MAX_PIECES = 512
MAX_POLYNOMIAL_DEGREE = 64
MAX_TAIL_TERMS = 128
MAX_EIGENVALUE_WIDTH = Fraction(1, 500000000000)
EXP_TAYLOR_DEGREE = 60
EXP_DYADIC_BITS = 256
SQRT_DYADIC_BITS = 192
MAX_TRIAL_VIRIAL_ABS = Fraction(1, 100000000000)
MAX_TRIAL_IDENTITY_ABS = Fraction(1, 1000000000000)
MAX_DENSITY_L2_DISTANCE = Fraction(1, 1000000)
RATIONAL = re.compile(r"-?(?:0|[1-9][0-9]*)(?:/[1-9][0-9]*)?\Z", re.ASCII)
SHA256 = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)


class VerificationRefusal(RuntimeError):
    def __init__(self, reason: str, detail: str):
        super().__init__(detail)
        self.reason = reason
        self.detail = detail


def refuse(reason: str, detail: str) -> None:
    raise VerificationRefusal(reason, detail)


def canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def strict_json(raw: bytes) -> object:
    if not raw or len(raw) > MAX_CERTIFICATE_BYTES or not raw.endswith(b"\n"):
        refuse("certificate-bytes", "certificate must be bounded and end in one LF")
    try:
        text = raw[:-1].decode("utf-8")
    except UnicodeDecodeError as error:
        refuse("certificate-encoding", "certificate is not UTF-8")

    def pairs(items: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in items:
            if key in result:
                refuse("duplicate-json-key", f"duplicate JSON key {key!r}")
            result[key] = value
        return result

    def integer(token: str) -> int:
        digits = token.lstrip("-")
        if len(digits) > MAX_INTEGER_DIGITS:
            refuse("integer-budget", "JSON integer exceeds the digit budget")
        return int(token)

    try:
        value = json.loads(
            text,
            object_pairs_hook=pairs,
            parse_int=integer,
            parse_float=lambda unused: refuse(
                "json-number", "JSON floating-point literals are forbidden"
            ),
            parse_constant=lambda unused: refuse(
                "json-number", "non-finite JSON literals are forbidden"
            ),
        )
    except VerificationRefusal:
        raise
    except (ValueError, RecursionError) as error:
        refuse("certificate-json", f"certificate JSON refused: {error}")

    stack: list[tuple[object, int]] = [(value, 1)]
    nodes = 0
    while stack:
        item, depth = stack.pop()
        nodes += 1
        if nodes > MAX_JSON_NODES or depth > MAX_JSON_DEPTH:
            refuse("certificate-structure", "certificate structure budget exceeded")
        if isinstance(item, dict):
            stack.extend((child, depth + 1) for child in item.values())
        elif isinstance(item, list):
            stack.extend((child, depth + 1) for child in item)
    return value


def rational(value: object, context: str) -> Fraction:
    if not isinstance(value, str) or len(value) > 2 * MAX_INTEGER_DIGITS + 2:
        refuse("rational-token", f"{context} is not a bounded rational token")
    if RATIONAL.fullmatch(value) is None:
        refuse("rational-token", f"{context} is not canonical rational syntax")
    numerator, separator, denominator = value.partition("/")
    if len(numerator.lstrip("-")) > MAX_INTEGER_DIGITS or (
        separator and len(denominator) > MAX_INTEGER_DIGITS
    ):
        refuse("integer-budget", f"{context} exceeds the integer digit budget")
    try:
        result = Fraction(value)
    except (ValueError, ZeroDivisionError) as error:
        refuse("rational-token", f"{context} is not a rational: {error}")
    if str(result) != value:
        refuse("rational-canonical", f"{context} is not reduced canonical form")
    return result


def exact_keys(value: object, expected: set[str], context: str) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != expected:
        refuse("certificate-shape", f"{context} keys do not match the closed schema")
    return value


def poly_trim(value: list[Fraction]) -> list[Fraction]:
    result = list(value)
    while len(result) > 1 and result[-1] == 0:
        result.pop()
    return result


def poly_add(left: list[Fraction], right: list[Fraction]) -> list[Fraction]:
    size = max(len(left), len(right))
    result = [Fraction(0)] * size
    for index in range(size):
        if index < len(left):
            result[index] += left[index]
        if index < len(right):
            result[index] += right[index]
    return poly_trim(result)


def poly_scale(value: list[Fraction], factor: Fraction) -> list[Fraction]:
    return poly_trim([factor * coefficient for coefficient in value])


def poly_mul(left: list[Fraction], right: list[Fraction]) -> list[Fraction]:
    left_denominator = lcm(*(coefficient.denominator for coefficient in left))
    right_denominator = lcm(*(coefficient.denominator for coefficient in right))
    left_integers = [
        coefficient.numerator * (left_denominator // coefficient.denominator)
        for coefficient in left
    ]
    right_integers = [
        coefficient.numerator * (right_denominator // coefficient.denominator)
        for coefficient in right
    ]
    integer_result = [0] * (len(left) + len(right) - 1)
    for left_index, left_value in enumerate(left_integers):
        for right_index, right_value in enumerate(right_integers):
            integer_result[left_index + right_index] += left_value * right_value
    denominator = left_denominator * right_denominator
    return poly_trim([Fraction(value, denominator) for value in integer_result])


def poly_pow(value: list[Fraction], exponent: int) -> list[Fraction]:
    result = [Fraction(1)]
    base = list(value)
    power = exponent
    while power:
        if power & 1:
            result = poly_mul(result, base)
        power //= 2
        if power:
            base = poly_mul(base, base)
    return result


def poly_derivative(value: list[Fraction]) -> list[Fraction]:
    if len(value) <= 1:
        return [Fraction(0)]
    return [Fraction(index) * value[index] for index in range(1, len(value))]


def poly_at_one(value: list[Fraction]) -> Fraction:
    return sum(value, Fraction(0))


def poly_abs_sum(value: list[Fraction]) -> Fraction:
    return sum((abs(coefficient) for coefficient in value), Fraction(0))


def poly_integral_unit(value: list[Fraction]) -> Fraction:
    """Integrate a power-basis polynomial exactly over ``0 <= s <= 1``."""
    coefficient_denominator = lcm(
        *(coefficient.denominator for coefficient in value)
    )
    integral_denominator = lcm(*range(1, len(value) + 1))
    numerator = sum(
        coefficient.numerator
        * (coefficient_denominator // coefficient.denominator)
        * (integral_denominator // (index + 1))
        for index, coefficient in enumerate(value)
    )
    return Fraction(numerator, coefficient_denominator * integral_denominator)


def poly_product_integral_unit(
    left: list[Fraction], right: list[Fraction]
) -> Fraction:
    """Integrate a polynomial product with one final rational reduction.

    Accumulating every product through ``Fraction`` repeatedly computes very
    large gcds.  Common coefficient and monomial-integral denominators make the
    same exact sum an integer accumulation followed by one reduction.
    """
    left_denominator = lcm(*(coefficient.denominator for coefficient in left))
    right_denominator = lcm(*(coefficient.denominator for coefficient in right))
    integral_denominator = lcm(*range(1, len(left) + len(right)))
    left_integers = [
        coefficient.numerator * (left_denominator // coefficient.denominator)
        for coefficient in left
    ]
    right_integers = [
        coefficient.numerator * (right_denominator // coefficient.denominator)
        for coefficient in right
    ]
    numerator = sum(
        left_value
        * right_value
        * (integral_denominator // (left_index + right_index + 1))
        for left_index, left_value in enumerate(left_integers)
        for right_index, right_value in enumerate(right_integers)
    )
    return Fraction(
        numerator,
        left_denominator * right_denominator * integral_denominator,
    )


def power_to_bernstein(value: list[Fraction]) -> list[Fraction]:
    """Return exact same-degree Bernstein coefficients on the unit interval."""
    degree = len(value) - 1
    return [
        sum(
            (
                value[power] * Fraction(comb(index, power), comb(degree, power))
                for power in range(index + 1)
            ),
            Fraction(0),
        )
        for index in range(degree + 1)
    ]


Interval = tuple[Fraction, Fraction]


def interval_add(left: Interval, right: Interval) -> Interval:
    return left[0] + right[0], left[1] + right[1]


def interval_sub(left: Interval, right: Interval) -> Interval:
    return left[0] - right[1], left[1] - right[0]


def interval_scale(value: Interval, factor: Fraction) -> Interval:
    if factor >= 0:
        return value[0] * factor, value[1] * factor
    return value[1] * factor, value[0] * factor


def interval_divide_positive(numerator: Interval, denominator: Interval) -> Interval:
    if numerator[0] < 0 or denominator[0] <= 0:
        refuse("checker-internal", "positive interval division received an invalid input")
    return numerator[0] / denominator[1], numerator[1] / denominator[0]


def interval_square_positive(value: Interval) -> Interval:
    if value[0] < 0:
        refuse("checker-internal", "positive interval square received a negative input")
    return value[0] * value[0], value[1] * value[1]


def sqrt_fraction_bound(value: Fraction) -> Interval:
    """Enclose a nonnegative rational square root on an exact dyadic grid."""
    if value < 0:
        refuse("checker-internal", "rational square root received a negative input")
    scale = 1 << SQRT_DYADIC_BITS
    scaled_numerator = value.numerator * scale * scale
    quotient = scaled_numerator // value.denominator
    lower_integer = isqrt(quotient)
    lower = Fraction(lower_integer, scale)
    if lower * lower == value:
        return lower, lower
    return lower, Fraction(lower_integer + 1, scale)


def interval_text(value: Interval) -> list[str]:
    if value[0] > value[1]:
        refuse("checker-internal", "attempted to render a reversed interval")
    return [str(value[0]), str(value[1])]


def outward_decimal_interval(
    lower: Fraction, upper: Fraction, places: int
) -> list[str]:
    scale = 10**places
    scaled_lower = lower * scale
    scaled_upper = upper * scale
    lower_integer = scaled_lower.numerator // scaled_lower.denominator
    upper_integer = -((-scaled_upper.numerator) // scaled_upper.denominator)

    def render(value: int) -> str:
        sign = "-" if value < 0 else ""
        digits = str(abs(value)).rjust(places + 1, "0")
        return f"{sign}{digits[:-places]}.{digits[-places:]}"

    return [render(lower_integer), render(upper_integer)]


def exp_positive_bound(value: Fraction) -> tuple[Fraction, Fraction]:
    if value < 0:
        refuse("checker-internal", "positive exponential helper received a negative input")
    halvings = 0
    reduced = value
    while reduced > Fraction(1, 2):
        reduced /= 2
        halvings += 1
        if halvings > 32:
            refuse("exp-budget", "exponential range reduction budget exceeded")
    term = Fraction(1)
    partial = Fraction(1)
    for index in range(1, EXP_TAYLOR_DEGREE + 1):
        term *= reduced / index
        partial += term
    next_term = term * reduced / (EXP_TAYLOR_DEGREE + 1)
    ratio = reduced / (EXP_TAYLOR_DEGREE + 2)
    upper = partial + next_term / (1 - ratio)
    lower = partial
    lower, upper = outward_dyadic(lower, upper)
    for _ in range(halvings):
        lower, upper = outward_dyadic(lower * lower, upper * upper)
    return lower, upper


def exp_bound(value: Fraction) -> tuple[Fraction, Fraction]:
    if value >= 0:
        return exp_positive_bound(value)
    lower, upper = exp_positive_bound(-value)
    return outward_dyadic(1 / upper, 1 / lower)


def outward_dyadic(lower: Fraction, upper: Fraction) -> tuple[Fraction, Fraction]:
    """Round an established enclosure outward to a fixed exact dyadic grid."""
    if lower > upper:
        refuse("checker-internal", "attempted to round a reversed enclosure")
    scale = 1 << EXP_DYADIC_BITS
    lower_scaled = lower * scale
    upper_scaled = upper * scale
    lower_integer = lower_scaled.numerator // lower_scaled.denominator
    upper_integer = -((-upper_scaled.numerator) // upper_scaled.denominator)
    return Fraction(lower_integer, scale), Fraction(upper_integer, scale)


def validate_density_polynomial(
    q: list[Fraction], density: list[Fraction]
) -> Fraction:
    """Bound |exp(q(s))-density(s)| by an exact Gronwall calculation."""
    initial_lower, initial_upper = exp_bound(q[0])
    initial_error = max(
        abs(density[0] - initial_lower), abs(density[0] - initial_upper)
    )
    q_derivative = poly_derivative(q)
    defect = poly_add(
        poly_derivative(density),
        poly_scale(poly_mul(q_derivative, density), Fraction(-1)),
    )
    integrated_defect_bound = poly_abs_sum(defect)
    logarithmic_variation = poly_abs_sum(q_derivative)
    growth = exp_bound(logarithmic_variation)[1]
    return (initial_error + integrated_defect_bound) * growth


def parse_piece(value: object, context: str) -> dict[str, object]:
    piece = exact_keys(
        value,
        {"origin", "step", "coefficients", "density_coefficients"},
        context,
    )
    origin = rational(piece["origin"], f"{context}.origin")
    step = rational(piece["step"], f"{context}.step")
    raw_coefficients = piece["coefficients"]
    if (
        not isinstance(raw_coefficients, list)
        or not 3 <= len(raw_coefficients) <= MAX_POLYNOMIAL_DEGREE + 1
    ):
        refuse("polynomial-budget", f"{context} polynomial degree is outside the budget")
    coefficients = [
        rational(item, f"{context}.coefficients[{index}]")
        for index, item in enumerate(raw_coefficients)
    ]
    raw_density = piece["density_coefficients"]
    if (
        not isinstance(raw_density, list)
        or not 2 <= len(raw_density) <= MAX_POLYNOMIAL_DEGREE + 1
    ):
        refuse("polynomial-budget", f"{context} density polynomial is outside the budget")
    density = [
        rational(item, f"{context}.density_coefficients[{index}]")
        for index, item in enumerate(raw_density)
    ]
    return {
        "origin": origin,
        "step": step,
        "coefficients": coefficients,
        "density_coefficients": density,
    }


def parse_chain(value: object, name: str) -> list[dict[str, object]]:
    if not isinstance(value, list) or not value or len(value) > MAX_PIECES:
        refuse("piece-budget", f"{name} is not a nonempty bounded piece list")
    return [parse_piece(piece, f"{name}[{index}]") for index, piece in enumerate(value)]


def endpoint(piece: dict[str, object]) -> tuple[Fraction, Fraction, Fraction]:
    origin = piece["origin"]
    step = piece["step"]
    coefficients = piece["coefficients"]
    assert isinstance(origin, Fraction) and isinstance(step, Fraction)
    assert isinstance(coefficients, list)
    value = poly_at_one(coefficients)
    derivative = poly_at_one(poly_derivative(coefficients)) / step
    return origin + step, value, derivative


def validate_chain(
    chain: list[dict[str, object]], start: Fraction, stop: Fraction, direction: int, name: str
) -> None:
    expected_origin = start
    prior_value: Fraction | None = None
    prior_derivative: Fraction | None = None
    for index, piece in enumerate(chain):
        origin = piece["origin"]
        step = piece["step"]
        coefficients = piece["coefficients"]
        assert isinstance(origin, Fraction) and isinstance(step, Fraction)
        assert isinstance(coefficients, list)
        if origin != expected_origin or step * direction <= 0:
            refuse("piece-coverage", f"{name}[{index}] does not continue the chain")
        if prior_value is not None and (
            coefficients[0] != prior_value
            or coefficients[1] / step != prior_derivative
        ):
            refuse("piece-continuity", f"{name}[{index}] is not C1-continuous")
        expected_origin, prior_value, prior_derivative = endpoint(piece)
    if expected_origin != stop:
        refuse("piece-coverage", f"{name} does not end at its declared boundary")


def laurent_add(target: dict[int, Fraction], exponent: int, value: Fraction) -> None:
    target[exponent] = target.get(exponent, Fraction(0)) + value
    if target[exponent] == 0:
        del target[exponent]


def tail_residual_bound(
    coefficients: list[Fraction], eigenvalue: Fraction, right: Fraction
) -> tuple[Fraction, Fraction, Fraction]:
    epsilon = Fraction(1, 20)
    w = {2 * index - 3: value for index, value in enumerate(coefficients)}
    derivative: dict[int, Fraction] = {}
    for exponent, value in w.items():
        laurent_add(derivative, exponent + 1, -exponent * value)
    square: dict[int, Fraction] = {}
    for left_power, left_value in w.items():
        for right_power, right_value in w.items():
            laurent_add(square, left_power + right_power, left_value * right_value)
    residual: dict[int, Fraction] = {}
    for exponent, value in derivative.items():
        laurent_add(residual, exponent, -epsilon * epsilon * value)
    for exponent, value in square.items():
        laurent_add(residual, exponent, -epsilon * epsilon * value)
    laurent_add(residual, -6, Fraction(1))
    laurent_add(residual, -4, Fraction(-5))
    laurent_add(residual, -2, Fraction(4))
    laurent_add(residual, 0, -eigenvalue)
    if residual and min(residual) < 0:
        refuse("tail-recurrence", "tail recurrence leaves an uncancelled growing term")
    y_max = 1 / right
    absolute_residual = sum(
        (abs(value) * y_max**exponent for exponent, value in residual.items()),
        Fraction(0),
    )

    # w'(x) = sum -p*a_p*y^(p+1).  The leading term is -60/y^2.
    derivative_upper = Fraction(-60) / (y_max * y_max)
    for exponent, value in derivative.items():
        if exponent == -2:
            continue
        contribution = value * y_max**exponent
        if contribution > 0:
            derivative_upper += contribution
    if derivative_upper >= 0:
        refuse("tail-monotonicity", "tail logarithmic derivative is not proved decreasing")
    w_at_right = sum(
        (value * y_max**exponent for exponent, value in w.items()), Fraction(0)
    )
    if w_at_right >= 0:
        refuse("tail-sign", "tail logarithmic derivative is not negative")
    return absolute_residual, derivative_upper, w_at_right


def potential_polynomial(origin: Fraction, step: Fraction) -> list[Fraction]:
    x = [origin, step]
    return poly_add(
        poly_add(poly_pow(x, 6), poly_scale(poly_pow(x, 4), Fraction(-5))),
        poly_scale(poly_pow(x, 2), Fraction(4)),
    )


def exponential_moment_tail_upper(
    power: int,
    right: Fraction,
    decay_rate: Fraction,
    amplitude_upper: Fraction,
) -> Fraction:
    """Bound ``integral_right^infinity x^power amplitude*exp(-rate*t)``."""
    if power < 0 or decay_rate <= 0 or amplitude_upper <= 0:
        refuse("checker-internal", "exponential tail moment inputs are invalid")
    moment = sum(
        (
            Fraction(comb(power, index) * factorial(index))
            * right ** (power - index)
            / decay_rate ** (index + 1)
            for index in range(power + 1)
        ),
        Fraction(0),
    )
    return amplitude_upper * moment


def raw_density_moment_interval(
    pieces: list[dict[str, object]],
    exponentials: list[tuple[list[Fraction], Fraction]],
    power: int,
    right: Fraction,
    tail_decay_rate: Fraction,
    tail_amplitude_upper: Fraction,
) -> Interval:
    half_interval: Interval = (Fraction(0), Fraction(0))
    for piece, (density, density_error) in zip(pieces, exponentials, strict=True):
        origin = piece["origin"]
        step = piece["step"]
        assert isinstance(origin, Fraction) and isinstance(step, Fraction)
        weight = poly_pow([origin, step], power)
        weight_integral = poly_integral_unit(weight)
        if weight_integral < 0:
            refuse("checker-internal", "nonnegative moment weight integrated negative")
        nominal = abs(step) * poly_product_integral_unit(weight, density)
        allowance = abs(step) * density_error * weight_integral
        lower = max(Fraction(0), nominal - allowance)
        upper = nominal + allowance
        if upper < lower:
            refuse("diagnostic-moment", "piece moment enclosure is reversed")
        half_interval = interval_add(half_interval, (lower, upper))
    tail_upper = exponential_moment_tail_upper(
        power, right, tail_decay_rate, tail_amplitude_upper
    )
    return 2 * half_interval[0], 2 * (half_interval[1] + tail_upper)


def raw_quartic_interval(
    pieces: list[dict[str, object]],
    exponentials: list[tuple[list[Fraction], Fraction]],
    tail_q: Fraction,
    tail_w: Fraction,
) -> Interval:
    half_interval: Interval = (Fraction(0), Fraction(0))
    for index, (piece, (density, density_error)) in enumerate(
        zip(pieces, exponentials, strict=True)
    ):
        step = piece["step"]
        assert isinstance(step, Fraction)
        lower_density = list(density)
        upper_density = list(density)
        lower_density[0] -= density_error
        upper_density[0] += density_error
        if min(power_to_bernstein(lower_density)) <= 0:
            refuse(
                "diagnostic-density-positivity",
                f"piece {index} does not prove a positive density lower bound",
            )
        lower = abs(step) * poly_product_integral_unit(
            lower_density, lower_density
        )
        upper = abs(step) * poly_product_integral_unit(
            upper_density, upper_density
        )
        if lower < 0 or upper < lower:
            refuse("diagnostic-quartic", "piece quartic enclosure is invalid")
        half_interval = interval_add(half_interval, (lower, upper))
    tail_upper = exp_bound(2 * tail_q)[1] / (-4 * tail_w)
    return 2 * half_interval[0], 2 * (half_interval[1] + tail_upper)


def raw_kinetic_integral_interval(
    pieces: list[dict[str, object]],
    exponentials: list[tuple[list[Fraction], Fraction]],
    tail: list[Fraction],
    right: Fraction,
    tail_q: Fraction,
    tail_w: Fraction,
) -> Interval:
    half_interval: Interval = (Fraction(0), Fraction(0))
    for piece, (density, density_error) in zip(pieces, exponentials, strict=True):
        step = piece["step"]
        q = piece["coefficients"]
        assert isinstance(step, Fraction) and isinstance(q, list)
        q_x = poly_scale(poly_derivative(q), 1 / step)
        weight = poly_mul(q_x, q_x)
        weight_integral = poly_integral_unit(weight)
        nominal = abs(step) * poly_product_integral_unit(weight, density)
        allowance = abs(step) * density_error * weight_integral
        lower = max(Fraction(0), nominal - allowance)
        upper = nominal + allowance
        if weight_integral < 0 or upper < lower:
            refuse("diagnostic-kinetic", "piece kinetic enclosure is invalid")
        half_interval = interval_add(half_interval, (lower, upper))

    w = {2 * index - 3: value for index, value in enumerate(tail)}
    w_square: dict[int, Fraction] = {}
    for left_power, left_value in w.items():
        for right_power, right_value in w.items():
            laurent_add(
                w_square, left_power + right_power, left_value * right_value
            )
    tail_amplitude_upper = exp_bound(tail_q)[1]
    decay_rate = -2 * tail_w
    tail_mass_upper = tail_amplitude_upper / decay_rate
    tail_w_square_upper = Fraction(0)
    for y_power, coefficient in w_square.items():
        x_power = -y_power
        if x_power >= 0:
            weighted_tail = exponential_moment_tail_upper(
                x_power, right, decay_rate, tail_amplitude_upper
            )
        else:
            weighted_tail = right**x_power * tail_mass_upper
        tail_w_square_upper += abs(coefficient) * weighted_tail

    # q' = 2*w, so q'^2 = 4*w^2.
    return 2 * half_interval[0], 2 * (
        half_interval[1] + 4 * tail_w_square_upper
    )


def compute_trial_and_ground_diagnostics(
    *,
    pieces: list[dict[str, object]],
    exponentials: list[tuple[list[Fraction], Fraction]],
    normalization: Interval,
    tail: list[Fraction],
    right: Fraction,
    tail_q: Fraction,
    tail_w: Fraction,
    eigenvalue_interval: Interval,
    quotient_residual_radius: Fraction,
) -> tuple[dict[str, object], dict[str, object]]:
    epsilon = Fraction(1, 20)
    coupling = Fraction(7, 10)
    tail_amplitude_upper = exp_bound(tail_q)[1]
    tail_decay_rate = -2 * tail_w

    raw_moments = {
        power: raw_density_moment_interval(
            pieces,
            exponentials,
            power,
            right,
            tail_decay_rate,
            tail_amplitude_upper,
        )
        for power in (2, 4, 6)
    }
    moments = {
        power: interval_divide_positive(raw, normalization)
        for power, raw in raw_moments.items()
    }
    raw_quartic = raw_quartic_interval(
        pieces, exponentials, tail_q, tail_w
    )
    normalization_squared = interval_square_positive(normalization)
    quartic = interval_divide_positive(raw_quartic, normalization_squared)
    raw_q_derivative_squared = raw_kinetic_integral_interval(
        pieces, exponentials, tail, right, tail_q, tail_w
    )
    kinetic = interval_scale(
        interval_divide_positive(raw_q_derivative_squared, normalization),
        epsilon * epsilon / 4,
    )
    potential = interval_add(
        interval_add(moments[6], interval_scale(moments[4], Fraction(-5))),
        interval_scale(moments[2], Fraction(4)),
    )
    energy = interval_add(
        interval_add(kinetic, potential),
        interval_scale(quartic, coupling / 2),
    )
    eigenvalue_from_energy = interval_add(
        energy, interval_scale(quartic, coupling / 2)
    )
    energy_identity_residual = interval_sub(
        eigenvalue_interval, eigenvalue_from_energy
    )
    virial_residual = interval_add(
        interval_add(
            interval_add(
                interval_scale(kinetic, Fraction(2)),
                interval_scale(moments[6], Fraction(-6)),
            ),
            interval_scale(moments[4], Fraction(20)),
        ),
        interval_add(
            interval_scale(moments[2], Fraction(-8)),
            interval_scale(quartic, coupling / 2),
        ),
    )
    if not (
        energy_identity_residual[0] <= 0 <= energy_identity_residual[1]
        and max(map(abs, energy_identity_residual)) < MAX_TRIAL_IDENTITY_ABS
    ):
        refuse(
            "diagnostic-energy-identity",
            "trial energy/eigenvalue identity residual misses its exact-rational gate",
        )
    if not (
        virial_residual[0] <= 0 <= virial_residual[1]
        and max(map(abs, virial_residual)) < MAX_TRIAL_VIRIAL_ABS
    ):
        refuse(
            "diagnostic-virial",
            "trial virial residual misses its exact-rational gate",
        )

    density_distance_squared_upper = (
        4 * quotient_residual_radius / coupling
    )
    density_distance_upper = sqrt_fraction_bound(
        density_distance_squared_upper
    )[1]
    if density_distance_upper >= MAX_DENSITY_L2_DISTANCE:
        refuse(
            "ground-transfer-distance",
            "strong-convexity density transfer is too wide to admit",
        )
    trial_density_norm = sqrt_fraction_bound(quartic[0])[0], sqrt_fraction_bound(
        quartic[1]
    )[1]
    ground_density_norm_lower = max(
        Fraction(0), trial_density_norm[0] - density_distance_upper
    )
    ground_density_norm_upper = trial_density_norm[1] + density_distance_upper
    ground_quartic = (
        ground_density_norm_lower * ground_density_norm_lower,
        ground_density_norm_upper * ground_density_norm_upper,
    )
    ground_energy = interval_sub(
        eigenvalue_interval, interval_scale(ground_quartic, coupling / 2)
    )

    trial = {
        "schema": "jackal-hellgate-trial-diagnostics-v1",
        "status": "bounded",
        "subject": "normalized-certificate-trial-phi",
        "quartic_norm_interval": interval_text(quartic),
        "quartic_norm_decimal_interval": outward_decimal_interval(
            quartic[0], quartic[1], 18
        ),
        "moment_intervals": {
            "x2": interval_text(moments[2]),
            "x4": interval_text(moments[4]),
            "x6": interval_text(moments[6]),
        },
        "moment_decimal_intervals": {
            "x2": outward_decimal_interval(moments[2][0], moments[2][1], 18),
            "x4": outward_decimal_interval(moments[4][0], moments[4][1], 18),
            "x6": outward_decimal_interval(moments[6][0], moments[6][1], 18),
        },
        "kinetic_energy_interval": interval_text(kinetic),
        "kinetic_energy_decimal_interval": outward_decimal_interval(
            kinetic[0], kinetic[1], 18
        ),
        "energy_functional_interval": interval_text(energy),
        "energy_functional_decimal_interval": outward_decimal_interval(
            energy[0], energy[1], 18
        ),
        "energy_eigenvalue_identity_residual_interval": interval_text(
            energy_identity_residual
        ),
        "energy_eigenvalue_identity_residual_decimal_interval": (
            outward_decimal_interval(
                energy_identity_residual[0],
                energy_identity_residual[1],
                21,
            )
        ),
        "virial_residual_interval": interval_text(virial_residual),
        "virial_residual_decimal_interval": outward_decimal_interval(
            virial_residual[0], virial_residual[1], 21
        ),
        "assumptions": [
            "the Bernstein convex-hull property bounds each power-basis density polynomial on the unit interval",
            "the proved decreasing negative tail logarithmic derivative gives the declared exponential-moment tail majorants",
        ],
        "non_claims": [
            "these diagnostics enclose the normalized certificate trial phi, not the exact ground state u0",
            "a narrow trial virial or energy-identity residual does not by itself transfer trial moments to u0",
            "bounded is not formal-bounded; the diagnostic integration is exact-rational Python outside the Lean and SPARK certificate chains",
        ],
    }
    ground = {
        "schema": "jackal-hellgate-ground-transfer-v1",
        "status": "bounded",
        "subject": "positive-normalized-ground-state-u0",
        "method": "lambda-strong-convexity-density-transfer-v1",
        "derivation": [
            "strong convexity gives (lambda/2)*norm(rho_phi-rho_0,L2)^2 <= -integral((R_phi-c)*(rho_0-rho_phi))",
            "the mass constraint cancels c and nonnegative mass-one densities give norm(rho_phi-rho_0,L1) <= 2",
            "the global quotient residual therefore gives norm(rho_phi-rho_0,L2)^2 <= 4*delta/lambda",
            "the reverse triangle inequality transfers the density L2 norm, whose square is integral(u^4)",
        ],
        "density_l2_distance_squared_upper": str(
            density_distance_squared_upper
        ),
        "density_l2_distance_upper": str(density_distance_upper),
        "density_l2_distance_decimal_upper": outward_decimal_interval(
            density_distance_upper, density_distance_upper, 18
        )[1],
        "quartic_norm_interval": interval_text(ground_quartic),
        "quartic_norm_decimal_interval": outward_decimal_interval(
            ground_quartic[0], ground_quartic[1], 18
        ),
        "energy_functional_interval": interval_text(ground_energy),
        "energy_functional_decimal_interval": outward_decimal_interval(
            ground_energy[0], ground_energy[1], 18
        ),
        "assumptions": [
            "the mass-one density energy is lambda-strongly convex in L2 because Fisher information is convex and lambda/2 times integral rho^2 supplies the modulus",
            "the nonlinear quotient is the density energy first variation and its global residual radius is valid",
            "both rho_phi and rho_0 are nonnegative mass-one finite-energy densities",
        ],
        "non_claims": [
            "the transfer encloses the ground-state quartic norm and energy functional only",
            "the transfer does not enclose polynomial moments, lambda sensitivity, tunneling, or Bogoliubov frequencies",
            "the strong-convexity theorem is stated and applied by the checker but is not Lean- or SPARK-proved here",
        ],
    }
    return trial, ground


def verify_document(document: object) -> dict[str, object]:
    root = exact_keys(
        document,
        {
            "schema",
            "problem",
            "representation",
            "center_eigenvalue",
            "right_endpoint",
            "match_point",
            "tail_terms",
            "tail_coefficients",
            "forward_pieces",
            "backward_pieces",
            "nonclaims",
            "certificate_sha256",
        },
        "certificate",
    )
    if root["schema"] != SCHEMA or root["representation"] != "piecewise-log-density-power-v1":
        refuse("certificate-schema", "certificate schema or representation is unsupported")
    problem = exact_keys(
        root["problem"],
        {"epsilon", "lambda", "potential", "mass", "parity", "positivity"},
        "problem",
    )
    expected_problem = {
        "epsilon": "1/20",
        "lambda": "7/10",
        "potential": "x^6-5*x^4+4*x^2",
        "mass": "1",
        "parity": "even",
        "positivity": "strict",
    }
    if problem != expected_problem:
        refuse("unsupported-problem", "certificate is not for the fixed HELLGATE problem")
    supplied_digest = root["certificate_sha256"]
    if not isinstance(supplied_digest, str) or SHA256.fullmatch(supplied_digest) is None:
        refuse("certificate-digest", "certificate digest is malformed")
    digest_document = {key: value for key, value in root.items() if key != "certificate_sha256"}
    actual_digest = hashlib.sha256(canonical_bytes(digest_document)).hexdigest()
    if not hmac.compare_digest(actual_digest, supplied_digest):
        refuse("certificate-digest", "certificate self-digest mismatch")

    eigenvalue = rational(root["center_eigenvalue"], "center_eigenvalue")
    right = rational(root["right_endpoint"], "right_endpoint")
    match = rational(root["match_point"], "match_point")
    if not Fraction(0) < match < right:
        refuse("certificate-domain", "match and right endpoints are not ordered")
    tail_terms = root["tail_terms"]
    if (
        isinstance(tail_terms, bool)
        or not isinstance(tail_terms, int)
        or not 8 <= tail_terms <= MAX_TAIL_TERMS
    ):
        refuse("tail-budget", "tail term count is outside the closed budget")
    raw_tail = root["tail_coefficients"]
    if not isinstance(raw_tail, list) or len(raw_tail) != tail_terms:
        refuse("tail-shape", "tail coefficient list does not match tail_terms")
    tail = [
        rational(value, f"tail_coefficients[{index}]")
        for index, value in enumerate(raw_tail)
    ]
    nonclaims = root["nonclaims"]
    expected_nonclaims = [
        "producer arithmetic is untrusted until independent exact-rational replay accepts",
        "certificate is specific to the declared HELLGATE parameters",
        "bounded is not formal-bounded; no Lean theorem checks this certificate",
    ]
    if nonclaims != expected_nonclaims:
        refuse("certificate-nonclaims", "certificate nonclaims were weakened or changed")

    forward = parse_chain(root["forward_pieces"], "forward_pieces")
    backward = parse_chain(root["backward_pieces"], "backward_pieces")
    validate_chain(forward, Fraction(0), match, 1, "forward_pieces")
    validate_chain(backward, right, match, -1, "backward_pieces")
    first_coefficients = forward[0]["coefficients"]
    assert isinstance(first_coefficients, list)
    if first_coefficients[1] != 0:
        refuse("even-boundary", "trial log-density derivative is not zero at the origin")
    _, forward_value, forward_derivative = endpoint(forward[-1])
    _, backward_value, backward_derivative = endpoint(backward[-1])
    if forward_value != backward_value or forward_derivative != backward_derivative:
        refuse("match-continuity", "forward and backward trial chains do not meet C1")

    tail_linear_error, _, tail_w = tail_residual_bound(tail, eigenvalue, right)
    backward_origin = backward[0]
    backward_coefficients = backward_origin["coefficients"]
    backward_step = backward_origin["step"]
    assert isinstance(backward_coefficients, list) and isinstance(backward_step, Fraction)
    if backward_coefficients[1] / backward_step != 2 * tail_w:
        refuse("tail-continuity", "interior trial derivative does not match the tail")
    tail_q = backward_coefficients[0]

    pieces = forward + backward
    exponentials: list[tuple[list[Fraction], Fraction]] = []
    half_mass_lower = Fraction(0)
    half_mass_upper = Fraction(0)
    for index, piece in enumerate(pieces):
        coefficients = piece["coefficients"]
        density_polynomial = piece["density_coefficients"]
        step = piece["step"]
        assert (
            isinstance(coefficients, list)
            and isinstance(density_polynomial, list)
            and isinstance(step, Fraction)
        )
        polynomial = density_polynomial
        error = validate_density_polynomial(coefficients, polynomial)
        integral = abs(step) * sum(
            (value / (power + 1) for power, value in enumerate(polynomial)),
            Fraction(0),
        )
        allowance = abs(step) * error
        lower = integral - allowance
        if lower <= 0:
            refuse("normalization-lower", f"piece {index} has no positive mass lower bound")
        half_mass_lower += lower
        half_mass_upper += integral + allowance
        exponentials.append((polynomial, error))

    tail_exp_upper = exp_bound(tail_q)[1]
    tail_mass_upper = tail_exp_upper / (-2 * tail_w)
    normalization_lower = 2 * half_mass_lower
    normalization_upper = 2 * (half_mass_upper + tail_mass_upper)
    if not normalization_lower > 0 or normalization_lower > normalization_upper:
        refuse("normalization", "normalization enclosure is invalid")
    inverse_lower = 1 / normalization_upper
    inverse_upper = 1 / normalization_lower
    inverse_center = (inverse_lower + inverse_upper) / 2
    inverse_error = max(inverse_center - inverse_lower, inverse_upper - inverse_center)

    epsilon = Fraction(1, 20)
    coupling = Fraction(7, 10)
    residual_radius = Fraction(0)
    for piece, (density_poly, density_error) in zip(pieces, exponentials, strict=True):
        origin = piece["origin"]
        step = piece["step"]
        q = piece["coefficients"]
        assert isinstance(origin, Fraction) and isinstance(step, Fraction)
        assert isinstance(q, list)
        q_x = poly_scale(poly_derivative(q), 1 / step)
        q_xx = poly_scale(poly_derivative(q_x), 1 / step)
        residual = poly_scale(q_xx, -epsilon * epsilon / 2)
        residual = poly_add(
            residual, poly_scale(poly_mul(q_x, q_x), -epsilon * epsilon / 4)
        )
        residual = poly_add(residual, potential_polynomial(origin, step))
        residual[0] -= eigenvalue
        residual = poly_add(
            residual, poly_scale(density_poly, coupling * inverse_center)
        )
        normalization_error = coupling * (
            density_error * inverse_upper
            + poly_abs_sum(density_poly) * inverse_error
        )
        piece_radius = poly_abs_sum(residual) + normalization_error
        residual_radius = max(residual_radius, piece_radius)

    tail_nonlinear = coupling * tail_exp_upper * inverse_upper
    residual_radius = max(residual_radius, tail_linear_error + tail_nonlinear)
    eigen_lower = eigenvalue - residual_radius
    eigen_upper = eigenvalue + residual_radius
    width = 2 * residual_radius
    if width >= MAX_EIGENVALUE_WIDTH:
        refuse(
            "target-width",
            "exact-rational quotient enclosure does not meet the HELLGATE width requirement",
        )
    trial_diagnostics, ground_transfer = compute_trial_and_ground_diagnostics(
        pieces=pieces,
        exponentials=exponentials,
        normalization=(normalization_lower, normalization_upper),
        tail=tail,
        right=right,
        tail_q=tail_q,
        tail_w=tail_w,
        eigenvalue_interval=(eigen_lower, eigen_upper),
        quotient_residual_radius=residual_radius,
    )
    return {
        "schema": RESULT_SCHEMA,
        "status": "bounded",
        "lane": "nonlinear-barta-exact-rational-v1",
        "formal": False,
        "checker_verdict": "ACCEPT",
        "parsed": "epsilon=1/20; lambda=7/10; V=x^6-5*x^4+4*x^2; mass=1; positive-even-ground-state",
        "fields": {
            "eigenvalue_interval": [str(eigen_lower), str(eigen_upper)],
            "eigenvalue_decimal_interval": outward_decimal_interval(
                eigen_lower, eigen_upper, 18
            ),
            "interval_width": str(width),
            "center_eigenvalue": str(eigenvalue),
            "quotient_residual_radius": str(residual_radius),
            "normalization_interval": [
                str(normalization_lower),
                str(normalization_upper),
            ],
            "certificate_sha256": supplied_digest,
            "piece_count": len(pieces),
            "tail_terms": tail_terms,
            "trial_diagnostics": trial_diagnostics,
            "ground_state_transfer": ground_transfer,
        },
        "theorem": {
            "name": "normalized defocusing nonlinear Barta comparison",
            "statement": "For lambda>=0, a positive normalized trial phi with quotient R=(-epsilon^2 phi''+V phi+lambda phi^3)/phi in [a,b] encloses the positive normalized ground-state eigenvalue E in [a,b].",
            "application": "phi=exp(q/2)/sqrt(integral exp(q)); exact-rational piece and tail bounds enclose R globally.",
        },
        "assumptions": [
            "the normalized defocusing nonlinear Barta comparison theorem is valid for positive C1 piecewise-C2 trials with the stated confining potential",
            "the stated lambda-strong-convexity density-transfer argument is valid for the admitted finite-energy densities",
            "Python arbitrary-precision integer, Fraction, and integer-square-root operations implement their documented exact arithmetic",
        ],
        "non_claims": expected_nonclaims
        + [
            "checker acceptance does not establish implementation correctness of the Python interpreter",
            "checker acceptance encloses E0 plus the explicitly scoped ground-state quartic norm and energy-functional transfer only",
            "reported polynomial moments and consistency residuals belong to the certificate trial phi, not the exact ground state u0",
            "ground-state polynomial moments, lambda sensitivity, tunneling, and Bogoliubov frequencies require separate certificates",
        ],
    }


def verify_bytes(raw: bytes) -> dict[str, object]:
    return verify_document(strict_json(raw))


def refusal_body(error: VerificationRefusal) -> dict[str, object]:
    return {
        "schema": RESULT_SCHEMA,
        "status": "refused",
        "reason": error.reason,
        "detail": error.detail,
        "formal": False,
        "non_claims": [
            "a refusal is an answer and no weaker numerical lane was substituted",
            "no eigenvalue enclosure was established",
        ],
    }


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: hellgate_verify.py CERTIFICATE.json", file=sys.stderr)
        return 2
    path = Path(sys.argv[1])
    try:
        raw = path.read_bytes()
        result = verify_bytes(raw)
    except VerificationRefusal as error:
        result = refusal_body(error)
    except OSError as error:
        result = refusal_body(VerificationRefusal("certificate-io", str(error)))
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0 if result["status"] == "bounded" else 1


if __name__ == "__main__":
    raise SystemExit(main())
