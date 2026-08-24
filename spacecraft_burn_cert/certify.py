#!/opt/homebrew/bin/python3
"""Rigorous interval enclosure for the uncertain finite-burn challenge.

The proof-producing lane uses fixed-denominator dyadic intervals.  Every
arithmetic endpoint operation is performed with Python integers and rounded
outward.  Square-root endpoints are obtained with ``math.isqrt`` and verified
by integer inequalities.  No binary floating-point value participates in the
proof decision.

The ODE enclosure is a first-order validated Picard step.  For each step it
constructs a box B and checks

    X_n union (X_n + [0,h] f(B))  subset  interior(B).

This proves that the exact solution tube is in B; X_n + h f(B) then encloses
the exact endpoint.  The implementation is rigorous interval computation, not
a mechanized proof of the nonlinear ODE algorithm or of this source code.
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
import os
from decimal import Decimal, localcontext
from fractions import Fraction
from pathlib import Path
from typing import Iterable, Sequence


SCALE_BITS = 80
SCALE = 1 << SCALE_BITS

# Mutation targets.  The independent verifier fixes the required values.
THRUST_KM_SCALE_TEXT = "0.001"
INTEGRATE_MASS = True
APOAPSIS_ECCENTRICITY_SIGN = 1
ENERGY_HALF_DENOMINATOR = 2
PROPAGATE_FULL_BOX = True
DECISION_MODE = "exact_lower_bound"


class CertificationError(RuntimeError):
    pass


def _floor_scaled(value: Fraction) -> int:
    return (value.numerator * SCALE) // value.denominator


def _ceil_scaled(value: Fraction) -> int:
    return -((-value.numerator * SCALE) // value.denominator)


def _ceil_div(numerator: int, denominator: int) -> int:
    if denominator < 0:
        numerator = -numerator
        denominator = -denominator
    return -((-numerator) // denominator)


def _floor_ratio_scaled(numerator: int, denominator: int) -> int:
    if denominator < 0:
        numerator = -numerator
        denominator = -denominator
    return (numerator * SCALE) // denominator


def _ceil_ratio_scaled(numerator: int, denominator: int) -> int:
    if denominator < 0:
        numerator = -numerator
        denominator = -denominator
    return _ceil_div(numerator * SCALE, denominator)


class DInterval:
    __slots__ = ("lo", "hi")

    def __init__(self, lo: int, hi: int):
        self.lo = int(lo)
        self.hi = int(hi)

    @classmethod
    def point(cls, value: Fraction | int | str) -> "DInterval":
        exact = value if isinstance(value, Fraction) else Fraction(value)
        return cls(_floor_scaled(exact), _ceil_scaled(exact))

    @classmethod
    def from_fractions(
        cls, lo: Fraction | int | str, hi: Fraction | int | str
    ) -> "DInterval":
        low = lo if isinstance(lo, Fraction) else Fraction(lo)
        high = hi if isinstance(hi, Fraction) else Fraction(hi)
        if low > high:
            return cls(1, 0)
        return cls(_floor_scaled(low), _ceil_scaled(high))

    def is_empty(self) -> bool:
        return self.lo > self.hi

    def _require_nonempty(self) -> None:
        if self.is_empty():
            raise CertificationError("empty interval used in arithmetic")

    def lo_fraction(self) -> Fraction:
        return Fraction(self.lo, SCALE)

    def hi_fraction(self) -> Fraction:
        return Fraction(self.hi, SCALE)

    def width_units(self) -> int:
        self._require_nonempty()
        return self.hi - self.lo

    def contains_zero(self) -> bool:
        return self.lo <= 0 <= self.hi

    def __neg__(self) -> "DInterval":
        self._require_nonempty()
        return DInterval(-self.hi, -self.lo)

    def __add__(self, other) -> "DInterval":
        rhs = as_interval(other)
        self._require_nonempty()
        rhs._require_nonempty()
        return DInterval(self.lo + rhs.lo, self.hi + rhs.hi)

    __radd__ = __add__

    def __sub__(self, other) -> "DInterval":
        return self + (-as_interval(other))

    def __rsub__(self, other) -> "DInterval":
        return as_interval(other) - self

    def __mul__(self, other) -> "DInterval":
        rhs = as_interval(other)
        self._require_nonempty()
        rhs._require_nonempty()
        products = (
            self.lo * rhs.lo,
            self.lo * rhs.hi,
            self.hi * rhs.lo,
            self.hi * rhs.hi,
        )
        return DInterval(min(products) // SCALE, _ceil_div(max(products), SCALE))

    __rmul__ = __mul__

    def __truediv__(self, other) -> "DInterval":
        rhs = as_interval(other)
        self._require_nonempty()
        rhs._require_nonempty()
        if rhs.contains_zero():
            raise CertificationError("division interval contains zero")
        endpoint_pairs = (
            (self.lo, rhs.lo),
            (self.lo, rhs.hi),
            (self.hi, rhs.lo),
            (self.hi, rhs.hi),
        )
        lows = [_floor_ratio_scaled(a, b) for a, b in endpoint_pairs]
        highs = [_ceil_ratio_scaled(a, b) for a, b in endpoint_pairs]
        return DInterval(min(lows), max(highs))

    def __rtruediv__(self, other) -> "DInterval":
        return as_interval(other) / self

    def square(self) -> "DInterval":
        self._require_nonempty()
        if self.contains_zero():
            maximum = max(self.lo * self.lo, self.hi * self.hi)
            return DInterval(0, _ceil_div(maximum, SCALE))
        squares = (self.lo * self.lo, self.hi * self.hi)
        return DInterval(min(squares) // SCALE, _ceil_div(max(squares), SCALE))

    def sqrt(self) -> "DInterval":
        self._require_nonempty()
        if self.lo < 0:
            raise CertificationError("sqrt interval has a negative lower endpoint")
        low_radicand = self.lo * SCALE
        high_radicand = self.hi * SCALE
        lo = math.isqrt(low_radicand)
        hi = math.isqrt(high_radicand)
        if hi * hi < high_radicand:
            hi += 1
        if lo * lo > low_radicand or hi * hi < high_radicand:
            raise CertificationError("integer sqrt enclosure check failed")
        return DInterval(lo, hi)

    def hull(self, other) -> "DInterval":
        rhs = as_interval(other)
        if self.is_empty():
            return DInterval(rhs.lo, rhs.hi)
        if rhs.is_empty():
            return DInterval(self.lo, self.hi)
        return DInterval(min(self.lo, rhs.lo), max(self.hi, rhs.hi))

    def intersection(self, other) -> "DInterval":
        rhs = as_interval(other)
        return DInterval(max(self.lo, rhs.lo), min(self.hi, rhs.hi))

    def to_json(self) -> dict:
        self._require_nonempty()
        return {
            "lo_scaled_integer": str(self.lo),
            "hi_scaled_integer": str(self.hi),
            "lo_exact": fraction_text(self.lo_fraction()),
            "hi_exact": fraction_text(self.hi_fraction()),
            "lo_decimal": decimal_text(self.lo_fraction()),
            "hi_decimal": decimal_text(self.hi_fraction()),
        }

    def __repr__(self) -> str:
        if self.is_empty():
            return "DInterval(empty)"
        return f"DInterval({fraction_text(self.lo_fraction())}, {fraction_text(self.hi_fraction())})"


def as_interval(value) -> DInterval:
    if isinstance(value, DInterval):
        return value
    return DInterval.point(value)


def fraction_text(value: Fraction) -> str:
    if value.denominator == 1:
        return str(value.numerator)
    return f"{value.numerator}/{value.denominator}"


def decimal_text(value: Fraction, digits: int = 28) -> str:
    with localcontext() as context:
        context.prec = digits + 12
        result = Decimal(value.numerator) / Decimal(value.denominator)
        return format(result, f".{digits}f")


ZERO = DInterval.point(0)
ONE = DInterval.point(1)
TWO = DInterval.point(2)
THOUSAND = DInterval.point(1000)
MU = DInterval.point(Fraction("398600.4418"))
G0 = DInterval.point(Fraction("9.80665"))
ISP = DInterval.point(450)
EARTH_RADIUS = DInterval.point(Fraction("6378.1363"))
THRUST_KM_SCALE = DInterval.point(Fraction(THRUST_KM_SCALE_TEXT))

INITIAL_BOUNDS = (
    (Fraction("6677.9995"), Fraction("6680.0005")),
    (Fraction("-0.0005"), Fraction("0.0005")),
    (Fraction("-0.00002"), Fraction("0.00002")),
    (Fraction("7.7258"), Fraction("7.7262")),
    (Fraction("1198.5"), Fraction("1201.5")),
)
THRUST_BOUNDS = (Fraction(1995), Fraction(2005))
BURN_TIME_BOUNDS = (Fraction("118.5"), Fraction("121.5"))
STEP = Fraction(1, 32)
PARTITION_COUNTS = (4, 1, 1, 2, 2, 2)  # x,y,vx,vy,m,T = 32 branches


def center_state_and_thrust() -> tuple[tuple[DInterval, ...], DInterval]:
    state = tuple(DInterval.point((lo + hi) / 2) for lo, hi in INITIAL_BOUNDS)
    thrust = DInterval.point(sum(THRUST_BOUNDS, Fraction(0)) / 2)
    return state, thrust


def derivative(
    state: Sequence[DInterval],
    thrust: DInterval,
    initial_mass: DInterval,
) -> tuple[DInterval, ...]:
    x, y, vx, vy, mass = state
    r2 = x.square() + y.square()
    v2 = vx.square() + vy.square()
    if r2.lo <= 0 or v2.lo <= 0:
        raise CertificationError("position or velocity norm can reach zero")
    radius = r2.sqrt()
    speed = v2.sqrt()
    acceleration_mass = mass if INTEGRATE_MASS else initial_mass
    thrust_accel = thrust / acceleration_mass * THRUST_KM_SCALE
    gravity_denom = r2 * radius
    ax = -MU * x / gravity_denom + thrust_accel * vx / speed
    ay = -MU * y / gravity_denom + thrust_accel * vy / speed
    dm = -thrust / (ISP * G0) if INTEGRATE_MASS else ZERO
    return vx, vy, ax, ay, dm


def inflate_box(box: Sequence[DInterval]) -> tuple[DInterval, ...]:
    inflated = []
    for component in box:
        pad = max(32, component.width_units() // 20 + 1)
        inflated.append(DInterval(component.lo - pad, component.hi + pad))
    return tuple(inflated)


def box_hull(
    left: Sequence[DInterval], right: Sequence[DInterval]
) -> tuple[DInterval, ...]:
    return tuple(a.hull(b) for a, b in zip(left, right))


def box_strictly_inside(
    inner: Sequence[DInterval], outer: Sequence[DInterval]
) -> bool:
    return all(b.lo < a.lo and a.hi < b.hi for a, b in zip(inner, outer))


def picard_mapping(
    initial: Sequence[DInterval],
    tube: Sequence[DInterval],
    thrust: DInterval,
    step: Fraction,
    initial_mass: DInterval,
) -> tuple[DInterval, ...]:
    time_interval = DInterval.from_fractions(0, step)
    vector_field = derivative(tube, thrust, initial_mass)
    displaced = tuple(x + time_interval * dx for x, dx in zip(initial, vector_field))
    return box_hull(initial, displaced)


def picard_tube(
    initial: Sequence[DInterval],
    thrust: DInterval,
    step: Fraction,
    initial_mass: DInterval,
) -> tuple[tuple[DInterval, ...], int]:
    seed = picard_mapping(initial, initial, thrust, step, initial_mass)
    tube = inflate_box(seed)
    for iteration in range(1, 17):
        mapped = picard_mapping(initial, tube, thrust, step, initial_mass)
        if box_strictly_inside(mapped, tube):
            return tube, iteration
        tube = inflate_box(box_hull(tube, mapped))
    raise CertificationError("Picard self-map inclusion did not close")


def endpoint_from_tube(
    initial: Sequence[DInterval],
    tube: Sequence[DInterval],
    thrust: DInterval,
    step: Fraction,
    initial_mass: DInterval,
) -> tuple[DInterval, ...]:
    step_interval = DInterval.point(step)
    return tuple(
        x + step_interval * dx
        for x, dx in zip(initial, derivative(tube, thrust, initial_mass))
    )


def postprocess(state: Sequence[DInterval]) -> dict[str, DInterval]:
    x, y, vx, vy, _mass = state
    r2 = x.square() + y.square()
    radius = r2.sqrt()
    speed_squared = vx.square() + vy.square()
    epsilon = speed_squared / DInterval.point(ENERGY_HALF_DENOMINATOR) - MU / radius
    if epsilon.hi >= 0:
        raise CertificationError("cutoff energy enclosure is not elliptic")
    semimajor_axis = -MU / (TWO * epsilon)
    angular_momentum = x * vy - y * vx
    eccentricity_squared = (
        ONE
        + TWO
        * epsilon
        * angular_momentum.square()
        / MU.square()
    )
    if eccentricity_squared.lo < 0:
        raise CertificationError("eccentricity radicand enclosure crosses zero")
    eccentricity = eccentricity_squared.sqrt()

    radial_velocity_product = x * vx + y * vy
    common = speed_squared - MU / radius
    eccentricity_x = (common * x - radial_velocity_product * vx) / MU
    eccentricity_y = (common * y - radial_velocity_product * vy) / MU
    eccentricity_vector_squared = eccentricity_x.square() + eccentricity_y.square()
    eccentricity_vector = eccentricity_vector_squared.sqrt()
    eccentricity_intersection = eccentricity.intersection(eccentricity_vector)
    if eccentricity_intersection.is_empty():
        raise CertificationError("independent eccentricity enclosures are disjoint")

    sign = DInterval.point(APOAPSIS_ECCENTRICITY_SIGN)
    apoapsis_formula = semimajor_axis * (ONE + sign * eccentricity)
    apoapsis = semimajor_axis * (ONE + sign * eccentricity_intersection)
    altitude_formula = apoapsis_formula - EARTH_RADIUS
    altitude = apoapsis - EARTH_RADIUS
    margin_formula = altitude_formula - THOUSAND
    margin = altitude - THOUSAND
    return {
        "radius": radius,
        "speed_squared": speed_squared,
        "energy": epsilon,
        "semimajor_axis": semimajor_axis,
        "angular_momentum": angular_momentum,
        "eccentricity_squared": eccentricity_squared,
        "eccentricity": eccentricity,
        "eccentricity_vector_squared": eccentricity_vector_squared,
        "eccentricity_vector": eccentricity_vector,
        "eccentricity_intersection": eccentricity_intersection,
        "apoapsis_formula": apoapsis_formula,
        "apoapsis": apoapsis,
        "altitude_formula": altitude_formula,
        "altitude": altitude,
        "margin_formula": margin_formula,
        "margin_intersection": margin,
    }


def reported_lower_bound(margin: DInterval) -> Fraction:
    exact = margin.lo_fraction()
    if DECISION_MODE == "exact_lower_bound":
        return exact
    if DECISION_MODE == "ceil_display":
        places = 1_000_000
        return Fraction(_ceil_div(exact.numerator * places, exact.denominator), places)
    raise CertificationError("unknown decision mode")


def decide(margin: DInterval) -> str:
    lower = reported_lower_bound(margin)
    if lower > 0:
        return "PROVED SAFE"
    if margin.hi_fraction() <= 0:
        return "PROVED UNSAFE"
    return "INDETERMINATE"


def partition(lo: Fraction, hi: Fraction, count: int) -> tuple[DInterval, ...]:
    width = (hi - lo) / count
    return tuple(
        DInterval.from_fractions(lo + index * width, lo + (index + 1) * width)
        for index in range(count)
    )


def branch_boxes() -> tuple[tuple[tuple[DInterval, ...], DInterval], ...]:
    if not PROPAGATE_FULL_BOX:
        state, thrust = center_state_and_thrust()
        return ((state, thrust),)
    pieces = [
        partition(lo, hi, count)
        for (lo, hi), count in zip(INITIAL_BOUNDS, PARTITION_COUNTS[:5])
    ]
    thrust_pieces = partition(*THRUST_BOUNDS, PARTITION_COUNTS[5])
    branches = []
    for values in itertools.product(*pieces, thrust_pieces):
        branches.append((tuple(values[:5]), values[5]))
    return tuple(branches)


def _update_trace(hasher, branch: int, step: int, boxes: Iterable[Sequence[DInterval]]):
    hasher.update(f"b={branch};s={step};".encode("ascii"))
    for box in boxes:
        for interval in box:
            hasher.update(str(interval.lo).encode("ascii"))
            hasher.update(b",")
            hasher.update(str(interval.hi).encode("ascii"))
            hasher.update(b";")


def _hull_dict(
    aggregate: dict[str, DInterval], values: dict[str, DInterval]
) -> dict[str, DInterval]:
    if not aggregate:
        return {name: DInterval(value.lo, value.hi) for name, value in values.items()}
    for name, value in values.items():
        aggregate[name] = aggregate[name].hull(value)
    return aggregate


def _source_sha256() -> str:
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def certify() -> dict:
    branches = branch_boxes()
    burn_lo_steps = BURN_TIME_BOUNDS[0] / STEP
    burn_hi_steps = BURN_TIME_BOUNDS[1] / STEP
    if burn_lo_steps.denominator != 1 or burn_hi_steps.denominator != 1:
        raise CertificationError("step does not exactly divide burn-time endpoints")
    lo_step = burn_lo_steps.numerator
    total_steps = burn_hi_steps.numerator

    cutoff_hull: tuple[DInterval, ...] | None = None
    orbital_hulls: dict[str, DInterval] = {}
    trace = hashlib.sha256()
    max_picard_iterations = 0
    tube_count = 0
    post_count = 0
    minimum_margin: DInterval | None = None
    minimum_formula_margin: DInterval | None = None
    minimum_location = None
    domain_radius_squared_lo = None
    domain_speed_squared_lo = None
    domain_mass_lo = None

    for branch_index, (initial, thrust) in enumerate(branches):
        state = initial
        initial_mass = initial[4]
        for step_index in range(total_steps):
            tube, iterations = picard_tube(state, thrust, STEP, initial_mass)
            endpoint = endpoint_from_tube(state, tube, thrust, STEP, initial_mass)
            max_picard_iterations = max(max_picard_iterations, iterations)
            tube_count += 1
            radius_squared_lo = (tube[0].square() + tube[1].square()).lo
            speed_squared_lo = (tube[2].square() + tube[3].square()).lo
            mass_lo = tube[4].lo
            domain_radius_squared_lo = (
                radius_squared_lo
                if domain_radius_squared_lo is None
                else min(domain_radius_squared_lo, radius_squared_lo)
            )
            domain_speed_squared_lo = (
                speed_squared_lo
                if domain_speed_squared_lo is None
                else min(domain_speed_squared_lo, speed_squared_lo)
            )
            domain_mass_lo = mass_lo if domain_mass_lo is None else min(domain_mass_lo, mass_lo)
            _update_trace(trace, branch_index, step_index, (state, tube, endpoint))
            if step_index >= lo_step:
                cutoff_hull = tube if cutoff_hull is None else box_hull(cutoff_hull, tube)
                post = postprocess(tube)
                orbital_hulls = _hull_dict(orbital_hulls, post)
                post_count += 1
                margin = post["margin_intersection"]
                formula_margin = post["margin_formula"]
                if minimum_margin is None or margin.lo < minimum_margin.lo:
                    minimum_margin = margin
                    minimum_location = {
                        "branch_index": branch_index,
                        "step_index": step_index,
                        "time_lo_exact": fraction_text(Fraction(step_index) * STEP),
                        "time_hi_exact": fraction_text(Fraction(step_index + 1) * STEP),
                    }
                if (
                    minimum_formula_margin is None
                    or formula_margin.lo < minimum_formula_margin.lo
                ):
                    minimum_formula_margin = formula_margin
            state = endpoint

    if cutoff_hull is None or minimum_margin is None or minimum_formula_margin is None:
        raise CertificationError("no cutoff states were processed")
    verdict = decide(minimum_margin)
    reported = reported_lower_bound(minimum_margin)
    return {
        "schema": "spacecraft-finite-burn-interval-receipt-v1",
        "source_sha256": _source_sha256(),
        "method": {
            "arithmetic": "exact-integer outward-rounded dyadic intervals",
            "scale_bits": SCALE_BITS,
            "ode_enclosure": "validated Picard self-map plus interval endpoint integral",
            "step_exact": fraction_text(STEP),
            "partition_counts": list(PARTITION_COUNTS),
            "branch_count": len(branches),
            "tube_count": tube_count,
            "postprocess_count": post_count,
            "maximum_picard_iterations": max_picard_iterations,
            "trace_sha256": trace.hexdigest(),
            "domain_lower_bounds": {
                "radius_squared_exact": fraction_text(
                    Fraction(domain_radius_squared_lo, SCALE)
                ),
                "speed_squared_exact": fraction_text(
                    Fraction(domain_speed_squared_lo, SCALE)
                ),
                "mass_exact": fraction_text(Fraction(domain_mass_lo, SCALE)),
            },
        },
        "model_contract": {
            "thrust_acceleration_scale": THRUST_KM_SCALE_TEXT,
            "integrate_mass": INTEGRATE_MASS,
            "apoapsis_eccentricity_sign": APOAPSIS_ECCENTRICITY_SIGN,
            "energy_denominator": ENERGY_HALF_DENOMINATOR,
            "propagate_full_box": PROPAGATE_FULL_BOX,
            "decision_mode": DECISION_MODE,
        },
        "problem": {
            "mu_km3_s2": "398600.4418",
            "g0_m_s2": "9.80665",
            "isp_s": "450",
            "earth_radius_km": "6378.1363",
            "initial_bounds": [
                [fraction_text(lo), fraction_text(hi)] for lo, hi in INITIAL_BOUNDS
            ],
            "thrust_bounds_N": [fraction_text(value) for value in THRUST_BOUNDS],
            "burn_time_bounds_s": [fraction_text(value) for value in BURN_TIME_BOUNDS],
        },
        "cutoff_state_hull": {
            name: interval.to_json()
            for name, interval in zip(("x", "y", "vx", "vy", "mass"), cutoff_hull)
        },
        "orbital_hulls": {
            name: value.to_json() for name, value in orbital_hulls.items()
        },
        "decisive_margin": {
            "interval": minimum_margin.to_json(),
            "formula_only_global_lower_exact": fraction_text(
                minimum_formula_margin.lo_fraction()
            ),
            "formula_only_global_lower_decimal": decimal_text(
                minimum_formula_margin.lo_fraction()
            ),
            "reported_lower_exact": fraction_text(reported),
            "reported_lower_decimal": decimal_text(reported),
            "minimum_location": minimum_location,
        },
        "verdict": verdict,
        "evidence_classification": {
            "inputs_and_unit_constants": "exact",
            "interval_arithmetic": "exact integer implementation with outward rounding",
            "ode_reachable_set": "rigorously interval-bounded; algorithm/source not formally verified",
            "orbital_algebra": "rigorously interval-bounded plus independent exact identity check required",
            "nominal_reference": "numerically estimated diagnostic only",
            "sampling": "not used for the decisive result",
            "overall": "rigorously interval-bounded, not formal-bounded",
        },
        "non_claims": [
            "JACKAL v1.7.3 does not formally certify this nonlinear ODE propagation.",
            "The exact dyadic lower endpoint is a certified lower bound, not the exact mathematical infimum.",
            "No Monte Carlo or nominal trajectory supports the universal verdict.",
        ],
    }


def write_json_atomic(path: Path, payload: dict) -> None:
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    data = (json.dumps(payload, sort_keys=True, indent=2) + "\n").encode("utf-8")
    with temporary.open("xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    receipt = certify()
    if args.output:
        write_json_atomic(args.output, receipt)
        print(
            f"{receipt['verdict']} margin_lo={receipt['decisive_margin']['reported_lower_decimal']} "
            f"receipt={args.output.resolve()}"
        )
    else:
        print(json.dumps(receipt, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
