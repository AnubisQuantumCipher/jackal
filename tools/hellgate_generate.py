#!/usr/bin/env python3
"""Generate the fixed HELLGATE nonlinear-ground-state trial certificate.

This is an untrusted numerical producer.  It uses high-precision Taylor
multiple shooting to construct a positive even trial density.  The emitted
decimal coefficients are only candidate data; ``mcp/hellgate_verify.py``
independently reparses them as exact rationals and decides whether they prove
anything.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import zlib
import sys
from fractions import Fraction
from pathlib import Path

import mpmath as mp


if hasattr(sys, "set_int_max_str_digits"):
    # Exact-rational continuity propagation can legitimately create long
    # denominators.  This is an offline producer; the verifier has independent
    # byte and integer-digit budgets and does not inherit this setting.
    sys.set_int_max_str_digits(0)

mp.mp.dps = 110

EPSILON = mp.mpf(1) / 20
LAMBDA = mp.mpf(7) / 10
RIGHT = mp.mpf("2.5")
MATCH = mp.mpf("1.7")
SHOOT_STEP = mp.mpf("0.005")
CERT_STEP = mp.mpf("0.01")
SHOOT_DEGREE = 50
CERT_DEGREE = 38
TAIL_TERMS = 80
PARAMETERS = 3


def canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def rational_text(value: mp.mpf, digits: int = 60) -> str:
    """Round producer data to a decimal that the checker treats as rational."""
    text = mp.nstr(value, digits, strip_zeros=False)
    return str(Fraction(text))


def potential_series(origin: mp.mpf, degree: int) -> mp.mpf:
    value = mp.mpf(0)
    if degree <= 6:
        value += mp.binomial(6, degree) * origin ** (6 - degree)
    if degree <= 4:
        value -= 5 * mp.binomial(4, degree) * origin ** (4 - degree)
    if degree <= 2:
        value += 4 * mp.binomial(2, degree) * origin ** (2 - degree)
    return value


def convolution(left: list[mp.mpf], right: list[mp.mpf], degree: int) -> mp.mpf:
    return mp.fsum(left[index] * right[degree - index] for index in range(degree + 1))


def taylor_coefficients(
    state: tuple[mp.mpf, ...], origin: mp.mpf, eigenvalue: mp.mpf, degree: int
) -> tuple[list[mp.mpf], list[mp.mpf], list[mp.mpf], list[list[mp.mpf]], list[list[mp.mpf]], list[list[mp.mpf]]]:
    q = [state[0]] + [mp.mpf(0)] * degree
    w = [state[1]] + [mp.mpf(0)] * degree
    mass = [state[2]] + [mp.mpf(0)] * degree
    q_sens: list[list[mp.mpf]] = []
    w_sens: list[list[mp.mpf]] = []
    mass_sens: list[list[mp.mpf]] = []
    for parameter in range(PARAMETERS):
        offset = 3 + 3 * parameter
        q_sens.append([state[offset]] + [mp.mpf(0)] * degree)
        w_sens.append([state[offset + 1]] + [mp.mpf(0)] * degree)
        mass_sens.append([state[offset + 2]] + [mp.mpf(0)] * degree)
    density = [mp.exp(q[0])] + [mp.mpf(0)] * degree

    for order in range(degree):
        divisor = order + 1
        q[divisor] = 2 * w[order] / divisor
        w[divisor] = (
            (
                potential_series(origin, order)
                + LAMBDA * density[order]
                - (eigenvalue if order == 0 else 0)
            )
            / (EPSILON * EPSILON)
            - convolution(w, w, order)
        ) / divisor
        mass[divisor] = density[order] / divisor

        for parameter in range(PARAMETERS):
            q_sens[parameter][divisor] = 2 * w_sens[parameter][order] / divisor
            eigen_source = -1 if parameter == 2 and order == 0 else 0
            w_sens[parameter][divisor] = (
                (
                    LAMBDA
                    * convolution(density, q_sens[parameter], order)
                    + eigen_source
                )
                / (EPSILON * EPSILON)
                - 2 * convolution(w, w_sens[parameter], order)
            ) / divisor
            mass_sens[parameter][divisor] = convolution(
                density, q_sens[parameter], order
            ) / divisor

        density[divisor] = mp.fsum(
            index * q[index] * density[divisor - index]
            for index in range(1, divisor + 1)
        ) / divisor

    return q, w, mass, q_sens, w_sens, mass_sens


def evaluate(coefficients: list[mp.mpf], step: mp.mpf) -> mp.mpf:
    value = mp.mpf(0)
    for coefficient in reversed(coefficients):
        value = value * step + coefficient
    return value


def advance(
    state: tuple[mp.mpf, ...], origin: mp.mpf, step: mp.mpf, eigenvalue: mp.mpf, degree: int
) -> tuple[mp.mpf, ...]:
    q, w, mass, q_sens, w_sens, mass_sens = taylor_coefficients(
        state, origin, eigenvalue, degree
    )
    result = [evaluate(q, step), evaluate(w, step), evaluate(mass, step)]
    for parameter in range(PARAMETERS):
        result.extend(
            [
                evaluate(q_sens[parameter], step),
                evaluate(w_sens[parameter], step),
                evaluate(mass_sens[parameter], step),
            ]
        )
    return tuple(result)


def integrate(
    start: mp.mpf,
    stop: mp.mpf,
    state: tuple[mp.mpf, ...],
    eigenvalue: mp.mpf,
    *,
    step: mp.mpf = SHOOT_STEP,
    degree: int = SHOOT_DEGREE,
) -> tuple[mp.mpf, ...]:
    direction = 1 if stop >= start else -1
    signed_step = direction * abs(step)
    position = start
    while direction * (stop - position) > 0:
        current = signed_step
        if direction * (position + current - stop) > 0:
            current = stop - position
        state = advance(state, position, current, eigenvalue, degree)
        position += current
    return state


def potential(x: mp.mpf) -> mp.mpf:
    return x**6 - 5 * x**4 + 4 * x**2


def potential_derivative(x: mp.mpf) -> mp.mpf:
    return 6 * x**5 - 20 * x**3 + 8 * x


def tail_coefficients(eigenvalue: mp.mpf, count: int) -> list[mp.mpf]:
    """Formal decaying Riccati coefficients w=sum a_k*x^(3-2k)."""
    epsilon = EPSILON
    coefficients: list[mp.mpf] = []
    for index in range(count):
        potential_coefficient = mp.mpf(0)
        if index == 0:
            potential_coefficient = 1
        elif index == 1:
            potential_coefficient = -5
        elif index == 2:
            potential_coefficient = 4
        elif index == 3:
            potential_coefficient = -eigenvalue
        derivative = mp.mpf(0)
        prior = index - 2
        if prior >= 0:
            derivative = -epsilon * epsilon * coefficients[prior] * (3 - 2 * prior)
        known_square = mp.fsum(
            coefficients[left] * coefficients[index - left]
            for left in range(1, index)
        )
        if index == 0:
            coefficient = mp.mpf(-20)
        else:
            coefficient = (
                potential_coefficient
                + derivative
                - epsilon * epsilon * known_square
            ) / (2 * epsilon * epsilon * coefficients[0])
        coefficients.append(coefficient)
    return coefficients


def tail_value(eigenvalue: mp.mpf) -> mp.mpf:
    coefficients = tail_coefficients(eigenvalue, TAIL_TERMS)
    return mp.fsum(
        coefficient * RIGHT ** (3 - 2 * index)
        for index, coefficient in enumerate(coefficients)
    )


def tail_value_derivative(eigenvalue: mp.mpf) -> mp.mpf:
    return mp.diff(tail_value, eigenvalue)


def solve_parameters() -> tuple[mp.mpf, mp.mpf, mp.mpf]:
    left_q = mp.mpf("-120.048245944203569382657017663048096374")
    right_q = mp.mpf("-116.633507058547647528503576301885412018")
    eigenvalue = mp.mpf("-4.615978698574496507441387083141344198")

    for _ in range(9):
        forward = (
            left_q,
            mp.mpf(0),
            mp.mpf(0),
            mp.mpf(1), 0, 0,
            0, 0, 0,
            0, 0, 0,
        )
        backward = (
            right_q,
            tail_value(eigenvalue),
            mp.mpf(0),
            0, 0, 0,
            mp.mpf(1), 0, 0,
            0, tail_value_derivative(eigenvalue), 0,
        )
        left = integrate(mp.mpf(0), MATCH, forward, eigenvalue)
        right = integrate(RIGHT, MATCH, backward, eigenvalue)
        residual = mp.matrix(
            [left[0] - right[0], left[1] - right[1], left[2] - right[2] - mp.mpf("0.5")]
        )
        jacobian = mp.matrix(PARAMETERS, PARAMETERS)
        for parameter in range(PARAMETERS):
            jacobian[0, parameter] = left[3 + 3 * parameter] - right[3 + 3 * parameter]
            jacobian[1, parameter] = left[4 + 3 * parameter] - right[4 + 3 * parameter]
            jacobian[2, parameter] = left[5 + 3 * parameter] - right[5 + 3 * parameter]
        correction = mp.lu_solve(jacobian, -residual)
        left_q += correction[0]
        right_q += correction[1]
        eigenvalue += correction[2]
        if max(abs(value) for value in residual) < mp.mpf("1e-90"):
            break
    return left_q, right_q, eigenvalue


def q_piece(
    state: tuple[mp.mpf, ...], origin: mp.mpf, step: mp.mpf, eigenvalue: mp.mpf
) -> tuple[list[mp.mpf], list[mp.mpf], tuple[mp.mpf, ...]]:
    q, *_ = taylor_coefficients(state, origin, eigenvalue, CERT_DEGREE)
    density = [mp.exp(q[0])] + [mp.mpf(0)] * CERT_DEGREE
    for order in range(1, CERT_DEGREE + 1):
        density[order] = mp.fsum(
            index * q[index] * density[order - index]
            for index in range(1, order + 1)
        ) / order
    scaled_q = [coefficient * step**index for index, coefficient in enumerate(q)]
    scaled_density = [
        coefficient * step**index for index, coefficient in enumerate(density)
    ]
    return (
        scaled_q,
        scaled_density,
        advance(state, origin, step, eigenvalue, CERT_DEGREE),
    )


def polynomial_value(coefficients: list[Fraction]) -> Fraction:
    return sum(coefficients, Fraction(0))


def polynomial_derivative_at_one(coefficients: list[Fraction]) -> Fraction:
    return sum(
        Fraction(index) * coefficient
        for index, coefficient in enumerate(coefficients)
        if index
    )


def quantize_piece(coefficients: list[mp.mpf]) -> list[Fraction]:
    return [Fraction(rational_text(value)) for value in coefficients]


def build_chain(
    start: mp.mpf,
    stop: mp.mpf,
    q_value: mp.mpf,
    w_value: mp.mpf,
    eigenvalue: mp.mpf,
) -> list[dict[str, object]]:
    direction = 1 if stop >= start else -1
    count = int(mp.nint(abs((stop - start) / CERT_STEP)))
    if count < 1:
        raise RuntimeError("certificate chain must contain at least one piece")
    step = (stop - start) / count
    state: tuple[mp.mpf, ...] = (
        q_value, w_value, mp.mpf(0),
        0, 0, 0, 0, 0, 0, 0, 0, 0,
    )
    pieces: list[dict[str, object]] = []
    prior_value: Fraction | None = None
    prior_derivative: Fraction | None = None
    for index in range(count):
        position = start + index * step
        current = step
        raw, raw_density, state = q_piece(state, position, current, eigenvalue)
        coefficients = quantize_piece(raw)
        density_coefficients = quantize_piece(raw_density)
        if prior_value is not None and prior_derivative is not None:
            coefficients[0] = prior_value
            coefficients[1] = Fraction(rational_text(current)) * prior_derivative
        elif position == 0:
            coefficients[1] = Fraction(0)
        value_at_end = polynomial_value(coefficients)
        derivative_at_end = polynomial_derivative_at_one(coefficients) / Fraction(
            rational_text(current)
        )
        pieces.append(
            {
                "origin": rational_text(position),
                "step": rational_text(current),
                "coefficients": [str(value) for value in coefficients],
                "density_coefficients": [
                    str(value) for value in density_coefficients
                ],
            }
        )
        prior_value = value_at_end
        prior_derivative = derivative_at_end
    return pieces


def join_chains(forward: list[dict[str, object]], backward: list[dict[str, object]]) -> None:
    left = forward[-1]
    right = backward[-1]
    left_coefficients = [Fraction(value) for value in left["coefficients"]]  # type: ignore[index]
    right_coefficients = [Fraction(value) for value in right["coefficients"]]  # type: ignore[index]
    left_step = Fraction(left["step"])  # type: ignore[arg-type]
    right_step = Fraction(right["step"])  # type: ignore[arg-type]
    left_value = polynomial_value(left_coefficients)
    left_slope_s = polynomial_derivative_at_one(left_coefficients)
    right_value = polynomial_value(right_coefficients)
    right_slope_x = polynomial_derivative_at_one(right_coefficients) / right_step
    value_delta = right_value - left_value
    slope_delta = left_step * right_slope_x - left_slope_s
    left_coefficients[2] += 3 * value_delta - slope_delta
    left_coefficients[3] += slope_delta - 2 * value_delta
    left["coefficients"] = [str(value) for value in left_coefficients]


def bind_backward_tail_and_continuity(
    backward: list[dict[str, object]], tail: list[Fraction]
) -> None:
    right = Fraction(5, 2)
    tail_w = sum(
        (
            coefficient * right ** (3 - 2 * index)
            for index, coefficient in enumerate(tail)
        ),
        Fraction(0),
    )
    prior_value: Fraction | None = None
    prior_derivative: Fraction | None = None
    for index, piece in enumerate(backward):
        coefficients = [Fraction(value) for value in piece["coefficients"]]  # type: ignore[index]
        step = Fraction(piece["step"])  # type: ignore[arg-type]
        if index == 0:
            coefficients[1] = step * 2 * tail_w
        else:
            assert prior_value is not None and prior_derivative is not None
            coefficients[0] = prior_value
            coefficients[1] = step * prior_derivative
        prior_value = polynomial_value(coefficients)
        prior_derivative = polynomial_derivative_at_one(coefficients) / step
        piece["coefficients"] = [str(value) for value in coefficients]


def generate() -> dict[str, object]:
    left_q, right_q, eigenvalue = solve_parameters()
    eigenvalue_fraction = Fraction(rational_text(eigenvalue))
    tail_fraction = [
        Fraction(rational_text(value))
        for value in tail_coefficients(eigenvalue, TAIL_TERMS)
    ]
    tail_fraction[:3] = [Fraction(-20), Fraction(50), Fraction(21)]
    forward = build_chain(mp.mpf(0), MATCH, left_q, mp.mpf(0), eigenvalue)
    backward = build_chain(
        RIGHT, MATCH, right_q, tail_value(eigenvalue), eigenvalue
    )
    bind_backward_tail_and_continuity(backward, tail_fraction)
    join_chains(forward, backward)
    document: dict[str, object] = {
        "schema": "jackal-hellgate-barta-certificate-v1",
        "problem": {
            "epsilon": "1/20",
            "lambda": "7/10",
            "potential": "x^6-5*x^4+4*x^2",
            "mass": "1",
            "parity": "even",
            "positivity": "strict",
        },
        "representation": "piecewise-log-density-power-v1",
        "center_eigenvalue": str(eigenvalue_fraction),
        "right_endpoint": rational_text(RIGHT),
        "match_point": rational_text(MATCH),
        "tail_terms": TAIL_TERMS,
        "tail_coefficients": [str(value) for value in tail_fraction],
        "forward_pieces": forward,
        "backward_pieces": backward,
        "nonclaims": [
            "producer arithmetic is untrusted until independent exact-rational replay accepts",
            "certificate is specific to the declared HELLGATE parameters",
            "bounded is not formal-bounded; no Lean theorem checks this certificate",
        ],
    }
    document["certificate_sha256"] = hashlib.sha256(canonical_bytes(document)).hexdigest()
    return document


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    arguments = parser.parse_args()
    document = generate()
    payload = canonical_bytes(document) + b"\n"
    if arguments.output.suffix == ".zlib":
        payload = zlib.compress(payload, 9)
    arguments.output.write_bytes(payload)
    print(document["certificate_sha256"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
