#!/usr/bin/env python3 -B
"""Untrusted high-precision differential oracle for the HELLGATE trial.

This module is intentionally outside the certificate decision path.  It
numerically integrates the encoded piecewise log density with mpmath so tests
can detect disagreement between an independent floating-point path and the
exact-rational verifier.  Its output is never evidence and never upgrades a
JACKAL status.
"""

from __future__ import annotations

import argparse
import json
import zlib
from pathlib import Path

import mpmath as mp


def _mp_rational(token: str) -> mp.mpf:
    numerator, separator, denominator = token.partition("/")
    if separator:
        return mp.mpf(numerator) / mp.mpf(denominator)
    return mp.mpf(numerator)


def _evaluate(coefficients: list[mp.mpf], point: mp.mpf) -> mp.mpf:
    value = mp.mpf(0)
    for coefficient in reversed(coefficients):
        value = value * point + coefficient
    return value


def compute_oracle(
    document: dict[str, object], *, decimal_places: int = 80, quadrature_order: int = 24
) -> dict[str, object]:
    """Return an unverified numerical differential oracle for one certificate."""
    mp.mp.dps = decimal_places
    nodes, weights = mp.gauss_quadrature(quadrature_order, "legendre")
    raw = {
        key: mp.mpf(0)
        for key in ("mass", "quartic", "x2", "x4", "x6", "q_derivative_squared")
    }
    pieces = document["forward_pieces"] + document["backward_pieces"]
    for piece in pieces:
        origin = _mp_rational(piece["origin"])
        step = _mp_rational(piece["step"])
        coefficients = [_mp_rational(item) for item in piece["coefficients"]]
        derivative = [
            (index + 1) * coefficients[index + 1] / step
            for index in range(len(coefficients) - 1)
        ]
        for node, weight in zip(nodes, weights, strict=True):
            unit_point = (node + 1) / 2
            physical_weight = weight * abs(step) / 2
            x_value = origin + step * unit_point
            q_value = _evaluate(coefficients, unit_point)
            density = mp.exp(q_value)
            q_derivative = _evaluate(derivative, unit_point)
            raw["mass"] += physical_weight * density
            raw["quartic"] += physical_weight * density * density
            raw["x2"] += physical_weight * x_value**2 * density
            raw["x4"] += physical_weight * x_value**4 * density
            raw["x6"] += physical_weight * x_value**6 * density
            raw["q_derivative_squared"] += (
                physical_weight * q_derivative * q_derivative * density
            )

    right = _mp_rational(document["right_endpoint"])
    tail = [_mp_rational(item) for item in document["tail_coefficients"]]
    tail_q = _mp_rational(document["backward_pieces"][0]["coefficients"][0])

    def tail_w(x_value: mp.mpf) -> mp.mpf:
        return mp.fsum(
            coefficient * x_value ** (3 - 2 * index)
            for index, coefficient in enumerate(tail)
        )

    def tail_log_density(x_value: mp.mpf) -> mp.mpf:
        value = tail_q
        for index, coefficient in enumerate(tail):
            power = 3 - 2 * index
            if power == -1:
                value += 2 * coefficient * mp.log(x_value / right)
            else:
                value += (
                    2
                    * coefficient
                    * (x_value ** (power + 1) - right ** (power + 1))
                    / (power + 1)
                )
        return value

    def tail_integral(quantity: str) -> mp.mpf:
        def integrand(x_value: mp.mpf) -> mp.mpf:
            density = mp.exp(tail_log_density(x_value))
            if quantity == "mass":
                return density
            if quantity == "quartic":
                return density * density
            if quantity == "q_derivative_squared":
                return 4 * tail_w(x_value) ** 2 * density
            return x_value ** int(quantity[1:]) * density

        return mp.quad(
            integrand,
            [right, right + mp.mpf("0.25"), right + 1, mp.inf],
        )

    for quantity in raw:
        raw[quantity] = 2 * (raw[quantity] + tail_integral(quantity))

    normalization = raw["mass"]
    quartic = raw["quartic"] / normalization**2
    moments = {
        key: raw[key] / normalization
        for key in ("x2", "x4", "x6")
    }
    # JACKAL exact: parsed=(1/20)^2/4; exact=1/1600; status=exact (not formal).
    kinetic = raw["q_derivative_squared"] / normalization / 1600
    potential = moments["x6"] - 5 * moments["x4"] + 4 * moments["x2"]
    energy = kinetic + potential + mp.mpf(7) * quartic / 20
    eigenvalue_from_energy = energy + mp.mpf(7) * quartic / 20
    virial = (
        2 * kinetic
        - 6 * moments["x6"]
        + 20 * moments["x4"]
        - 8 * moments["x2"]
        + mp.mpf(7) * quartic / 20
    )

    def render(value: mp.mpf) -> str:
        return mp.nstr(value, decimal_places - 20, strip_zeros=False)

    return {
        "schema": "jackal-hellgate-untrusted-trial-oracle-v1",
        "status": "unverified-numerical-oracle",
        "fields": {
            "normalization": render(normalization),
            "quartic_norm": render(quartic),
            "moments": {key: render(value) for key, value in moments.items()},
            "kinetic_energy": render(kinetic),
            "energy_functional": render(energy),
            "eigenvalue_from_energy": render(eigenvalue_from_energy),
            "virial_residual": render(virial),
        },
        "non_claims": [
            "mpmath floating-point quadrature is an untrusted test oracle, not certificate evidence",
            "agreement with the exact-rational checker does not upgrade bounded to formal-bounded",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("certificate", type=Path)
    arguments = parser.parse_args()
    raw = zlib.decompress(arguments.certificate.read_bytes())
    document = json.loads(raw)
    print(json.dumps(compute_oracle(document), sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
