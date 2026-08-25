#!/usr/bin/env python3
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
import re
import stat
import subprocess
import sys
import tempfile
from fractions import Fraction
from pathlib import Path
from typing import Iterable, Sequence


PRIVATE_SOURCE_FD_ENV = "JACKAL_SPACECRAFT_PRIVATE_SOURCE_FD"
MAX_WITNESS_BYTES = 64 * 1024 * 1024
MAX_CHECKER_BYTES = 512 * 1024 * 1024
MAX_IDENTITY_BYTES = 16 * 1024 * 1024
MAX_SOURCE_BYTES = 16 * 1024 * 1024

try:
    import witness_codec  # type: ignore[no-redef]
except ModuleNotFoundError:
    from spacecraft_burn_cert import witness_codec


SCALE_BITS = 80
SCALE = 1 << SCALE_BITS

# Mutation targets.  The independent verifier fixes the required values.
THRUST_KM_SCALE_TEXT = "0.001"
INTEGRATE_MASS = True
APOAPSIS_ECCENTRICITY_SIGN = 1
ENERGY_HALF_DENOMINATOR = 2
PROPAGATE_FULL_BOX = True
DECISION_MODE = "exact_lower_bound"

SCHEMA_V2 = "spacecraft-finite-burn-formal-receipt-v2"
VERDICT_CERTIFIED_SAFE = "CERTIFIED SAFE"
VERDICT_INDETERMINATE = "INDETERMINATE"
MODEL_QUALIFIER = (
    "under the stated finite-burn ODE model, supplied input bounds, "
    "and machine-checked interval-certificate assumptions"
)
FORMAL_THEOREM = "spacecraft_burn_certified_safe"
PICARD_PRODUCER_NONCLAIM = (
    "The Python Picard witness generator and its source are not formally verified. "
    "They are outside the mathematical soundness base because the pinned Lean "
    "checker independently checks every accepted tube, but remain trusted for "
    "termination, witness search/completeness, and reproducible generation. A "
    "producer defect may cause refusal, nontermination, or failure to find a "
    "witness, but cannot yield formal ACCEPT absent a defect in the pinned Lean "
    "checker or outer verification gate."
)
FORMAL_RESULT_RE = re.compile(
    r"^ACCEPT theorem=spacecraft_burn_certified_safe status=formal-bounded "
    r"margin_lo=(-?[0-9]+) margin_hi=(-?[0-9]+) "
    r"model=([^ ]+) epoch=([^ ]+)$"
)


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
            "lo_decimal": decimal_lower_text(self.lo_fraction()),
            "hi_decimal": decimal_upper_text(self.hi_fraction()),
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


def _scaled_decimal_text(units: int, digits: int) -> str:
    scale = 10**digits
    sign = "-" if units < 0 else ""
    whole, fractional = divmod(abs(units), scale)
    return f"{sign}{whole}.{fractional:0{digits}d}"


def decimal_lower_text(value: Fraction, digits: int = 28) -> str:
    scale = 10**digits
    units = value.numerator * scale // value.denominator
    return _scaled_decimal_text(units, digits)


def decimal_upper_text(value: Fraction, digits: int = 28) -> str:
    scale = 10**digits
    numerator = value.numerator * scale
    units = -((-numerator) // value.denominator)
    return _scaled_decimal_text(units, digits)


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
    if acceleration_mass.lo <= 0:
        raise CertificationError("mass must stay strictly positive")
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


def classify_margin(margin: DInterval) -> dict[str, str]:
    lower = reported_lower_bound(margin)
    if lower > 0:
        verdict = VERDICT_CERTIFIED_SAFE
    else:
        verdict = VERDICT_INDETERMINATE
    return {"verdict": verdict, "qualifier": MODEL_QUALIFIER}


def producer_status() -> dict[str, str]:
    return {
        "producer_assurance": "candidate-only",
        "formal_checker_status": "NOT_EXECUTED",
    }


def _strict_identity_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate proof-identity key")
        result[key] = value
    return result


def validate_proof_identity_for_binding(
    identity: dict,
    identity_bytes: bytes,
    checker_digest: str,
    request_digest: str,
    model_id: str,
    epoch: str,
) -> str:
    try:
        reparsed = json.loads(
            identity_bytes.decode("utf-8"),
            object_pairs_hook=_strict_identity_object,
            parse_constant=lambda value: (_ for _ in ()).throw(
                ValueError(f"non-finite proof-identity value: {value}")
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise CertificationError("invalid proof identity") from error
    if type(identity) is not dict or identity != reparsed:
        raise CertificationError("invalid proof identity")
    expected_keys = {
        "build_attestation", "checker", "fragment", "generator",
        "identity_digest_sha256", "proof", "schema", "source_closure",
        "toolchain",
    }
    if (
        set(identity) != expected_keys
        or identity.get("schema") != "jackal-spacecraft-burn-proof-identity-v1"
    ):
        raise CertificationError("invalid proof identity")
    recorded = identity.get("identity_digest_sha256")
    body = {key: value for key, value in identity.items() if key != "identity_digest_sha256"}
    actual = hashlib.sha256(
        json.dumps(
            body, ensure_ascii=False, separators=(",", ":"), sort_keys=True
        ).encode("utf-8")
    ).hexdigest()
    checker = identity.get("checker")
    fragment = identity.get("fragment")
    proof = identity.get("proof")
    if (
        type(recorded) is not str
        or re.fullmatch(r"[0-9a-f]{64}", recorded) is None
        or recorded != actual
        or type(checker) is not dict
        or checker.get("sha256") != checker_digest
        or type(fragment) is not dict
        or fragment.get("request_digest") != request_digest
        or fragment.get("model_id") != model_id
        or fragment.get("release_epoch") != epoch
        or fragment.get("soundness_theorem")
        != "JackalIv.Spacecraft.spacecraft_burn_certified_safe"
        or type(proof) is not dict
        or proof.get("axiom_policy")
        != {
            "allowed_exactly": ["propext", "Classical.choice", "Quot.sound"],
            "forbidden": ["sorryAx", "any additional axiom"],
        }
    ):
        raise CertificationError("proof identity does not bind the checker request")
    return recorded


def read_regular_snapshot(path: Path, maximum_bytes: int, label: str) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    descriptor: int | None = None
    try:
        descriptor = os.open(path, flags)
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_size > maximum_bytes:
            raise CertificationError(f"{label} must be a bounded regular file")
        payload = bytearray()
        while len(payload) <= maximum_bytes:
            block = os.read(descriptor, min(1024 * 1024, maximum_bytes + 1 - len(payload)))
            if not block:
                break
            payload.extend(block)
        after = os.fstat(descriptor)
        stable_fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
        if (
            len(payload) > maximum_bytes
            or len(payload) != before.st_size
            or any(getattr(before, field) != getattr(after, field) for field in stable_fields)
        ):
            raise CertificationError(f"{label} changed during bounded read")
        return bytes(payload)
    except CertificationError:
        raise
    except OSError as error:
        raise CertificationError(f"{label} is not a readable regular file") from error
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass


def bind_formal_checker(
    receipt: dict,
    witness_path: Path,
    checker_path: Path,
    proof_identity_path: Path,
    request_digest: str,
    model_id: str,
    epoch: str,
    nonce: str,
) -> None:
    """Bind an accepted exact checker execution to a publication receipt."""
    try:
        proof_identity_bytes = read_regular_snapshot(
            proof_identity_path, MAX_IDENTITY_BYTES, "proof identity"
        )
        checker_bytes = read_regular_snapshot(
            checker_path, MAX_CHECKER_BYTES, "formal checker"
        )
        witness_bytes = read_regular_snapshot(
            witness_path, MAX_WITNESS_BYTES, "formal witness"
        )
    except CertificationError:
        raise
    try:
        identity = json.loads(proof_identity_bytes)
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
        KeyError,
        TypeError,
    ) as error:
        raise CertificationError("invalid proof identity") from error
    checker_digest = hashlib.sha256(checker_bytes).hexdigest()
    witness_digest = hashlib.sha256(witness_bytes).hexdigest()
    proof_identity_file_digest = hashlib.sha256(proof_identity_bytes).hexdigest()
    identity_digest = validate_proof_identity_for_binding(
        identity,
        proof_identity_bytes,
        checker_digest,
        request_digest,
        model_id,
        epoch,
    )
    completed = run_formal_checker_snapshot(
        checker_bytes, witness_bytes, request_digest, model_id, epoch
    )
    if completed.returncode != 0 or completed.stderr:
        raise CertificationError("formal checker refused or emitted stderr")
    try:
        if (
            read_regular_snapshot(
                checker_path, MAX_CHECKER_BYTES, "formal checker"
            )
            != checker_bytes
            or read_regular_snapshot(
                witness_path, MAX_WITNESS_BYTES, "formal witness"
            )
            != witness_bytes
        ):
            raise CertificationError("formal binding input changed during checker execution")
    except CertificationError as error:
        raise CertificationError("formal binding input became unreadable") from error
    result_line = completed.stdout.removesuffix("\n")
    if "\n" in result_line or "\r" in result_line:
        raise CertificationError("formal checker output is not one canonical line")
    match = FORMAL_RESULT_RE.fullmatch(result_line)
    if match is None or match.group(3) != model_id or match.group(4) != epoch:
        raise CertificationError("formal checker output does not match requested binding")
    margin_lo, margin_hi = int(match.group(1)), int(match.group(2))
    if margin_lo <= 0 or margin_lo > margin_hi:
        raise CertificationError("formal checker returned a non-positive or invalid margin")
    try:
        replayed_margin = receipt["orbital_hulls"]["margin_intersection"]
        candidate_margin = (
            int(replayed_margin["lo_scaled_integer"]),
            int(replayed_margin["hi_scaled_integer"]),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise CertificationError("producer margin hull is invalid") from error
    if (margin_lo, margin_hi) != candidate_margin:
        raise CertificationError(
            "formal checker margin does not match the producer-wide margin hull"
        )
    receipt["formal_checker_status"] = "ACCEPT"
    receipt["formal_checker"] = {
        "checker_sha256": checker_digest,
        "proof_identity_file_sha256": proof_identity_file_digest,
        "proof_identity_digest_sha256": identity_digest,
        "witness_sha256": witness_digest,
        "request_digest": request_digest,
        "model_id": model_id,
        "epoch": epoch,
        "nonce": nonce,
        "theorem": FORMAL_THEOREM,
        "result_line": result_line,
    }
    receipt["formal_decisive_margin"] = {
        "scale_bits": SCALE_BITS,
        "lo_scaled_integer": str(margin_lo),
        "hi_scaled_integer": str(margin_hi),
        "lo_exact": fraction_text(Fraction(margin_lo, SCALE)),
        "hi_exact": fraction_text(Fraction(margin_hi, SCALE)),
        "lo_decimal": decimal_lower_text(Fraction(margin_lo, SCALE)),
        "hi_decimal": decimal_upper_text(Fraction(margin_hi, SCALE)),
    }
    receipt["evidence_classification"].update({
        "ode_reachable_set": "formal-bounded by the pinned Lean certificate checker",
        "orbital_algebra": "formal-bounded by the pinned Lean certificate checker",
        "overall": "formal-bounded",
    })
    receipt["non_claims"] = [
        "The theorem is conditional on the stated finite-burn ODE model and supplied input bounds.",
        PICARD_PRODUCER_NONCLAIM,
        "The Lean kernel, compiler, runtime, checker executable, and declared axioms remain trusted components.",
        "The formal lower endpoint is a certified lower bound, not the exact mathematical infimum.",
        "No Monte Carlo or nominal trajectory supports the universal verdict.",
    ]


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


def write_private_snapshot(path: Path, payload: bytes, mode: int) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    try:
        view = memoryview(payload)
        offset = 0
        while offset < len(view):
            written = os.write(descriptor, view[offset:])
            if written <= 0:
                raise CertificationError("private snapshot write failed")
            offset += written
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def run_formal_checker_snapshot(
    checker_bytes: bytes,
    witness_bytes: bytes,
    request_digest: str,
    model_id: str,
    epoch: str,
) -> subprocess.CompletedProcess[str]:
    """Execute exactly the checker and witness bytes already hashed by the producer."""
    with tempfile.TemporaryDirectory(
        prefix="jackal-spacecraft-formal-binding-"
    ) as directory:
        private = Path(directory)
        checker = private / "jackal_spacecraft_burn_check"
        witness = private / "baseline_witness_v2.cert"
        write_private_snapshot(checker, checker_bytes, 0o500)
        write_private_snapshot(witness, witness_bytes, 0o400)
        return subprocess.run(
            [str(checker), str(witness), request_digest, model_id, epoch],
            cwd=private,
            env={"LANG": "C", "LC_ALL": "C", "PATH": "/usr/bin:/bin"},
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=180,
            check=False,
        )


def run_from_private_source_snapshot(argv: Sequence[str]) -> int:
    source_bytes = read_regular_snapshot(
        Path(__file__), MAX_SOURCE_BYTES, "producer source"
    )
    codec_bytes = read_regular_snapshot(
        Path(__file__).with_name("witness_codec.py"),
        MAX_SOURCE_BYTES,
        "witness codec",
    )
    source_digest = hashlib.sha256(source_bytes).hexdigest()
    with tempfile.TemporaryDirectory(prefix="jackal-spacecraft-producer-") as directory:
        private = Path(directory)
        source_snapshot = private / "certify.py"
        codec_snapshot = private / "witness_codec.py"
        write_private_snapshot(source_snapshot, source_bytes, 0o500)
        write_private_snapshot(codec_snapshot, codec_bytes, 0o400)
        read_fd, write_fd = os.pipe()
        try:
            payload = source_digest.encode("ascii")
            offset = 0
            while offset < len(payload):
                written = os.write(write_fd, payload[offset:])
                if written <= 0:
                    raise CertificationError("private source binding write failed")
                offset += written
            os.close(write_fd)
            write_fd = -1
            child_environment = {
                "LANG": "C",
                "LC_ALL": "C",
                "PATH": "/usr/bin:/bin",
            }
            child_environment[PRIVATE_SOURCE_FD_ENV] = str(read_fd)
            completed = subprocess.run(
                [sys.executable, "-E", "-s", "-S", "-B", str(source_snapshot), *argv],
                cwd=Path.cwd(),
                env=child_environment,
                pass_fds=(read_fd,),
                check=False,
            )
        finally:
            if write_fd >= 0:
                os.close(write_fd)
            os.close(read_fd)
    return completed.returncode


def private_source_snapshot_digest() -> str | None:
    descriptor_text = os.environ.pop(PRIVATE_SOURCE_FD_ENV, None)
    if descriptor_text is None:
        return None
    if re.fullmatch(r"[0-9]+", descriptor_text) is None:
        raise CertificationError("private producer source descriptor is invalid")
    descriptor = int(descriptor_text)
    if descriptor < 3:
        raise CertificationError("private producer source descriptor is invalid")
    payload = bytearray()
    try:
        while len(payload) <= 64:
            block = os.read(descriptor, 65 - len(payload))
            if not block:
                break
            payload.extend(block)
    except OSError as error:
        raise CertificationError("private producer source binding is unreadable") from error
    finally:
        try:
            os.close(descriptor)
        except OSError:
            pass
    try:
        digest = payload.decode("ascii")
    except UnicodeDecodeError as error:
        raise CertificationError("private producer source binding is invalid") from error
    if re.fullmatch(r"[0-9a-f]{64}", digest) is None:
        raise CertificationError("private producer source binding is invalid")
    snapshot_directory = Path(__file__).resolve().parent
    if snapshot_directory.stat().st_mode & 0o077:
        raise CertificationError("private producer source directory is not private")
    return digest


def _witness_interval(value: DInterval) -> witness_codec.Interval:
    value._require_nonempty()
    return witness_codec.Interval(value.lo, value.hi)


def _witness_box(values: Sequence[DInterval]) -> witness_codec.Box:
    return witness_codec.Box(tuple(_witness_interval(value) for value in values))


def certify() -> tuple[dict, witness_codec.BurnWitness]:
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
    witness_branches: list[witness_codec.BranchWitness] = []

    for branch_index, (initial, thrust) in enumerate(branches):
        state = initial
        initial_mass = initial[4]
        witness_steps: list[witness_codec.StepWitness] = []
        for step_index in range(total_steps):
            tube, iterations = picard_tube(state, thrust, STEP, initial_mass)
            witness_steps.append(
                witness_codec.StepWitness(branch_index, step_index, _witness_box(tube))
            )
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
        witness_branches.append(
            witness_codec.BranchWitness(
                branch_index,
                _witness_box(initial),
                _witness_interval(thrust),
                tuple(witness_steps),
            )
        )

    if cutoff_hull is None or minimum_margin is None or minimum_formula_margin is None:
        raise CertificationError("no cutoff states were processed")
    classification = classify_margin(minimum_margin)
    reported = reported_lower_bound(minimum_margin)
    witness = witness_codec.BurnWitness(
        scale_bits=SCALE_BITS,
        step_num=STEP.numerator,
        step_den=STEP.denominator,
        partition_counts=PARTITION_COUNTS,
        steps_per_branch=total_steps,
        first_cutoff_step=lo_step,
        branches=tuple(witness_branches),
    )
    encoded_witness = witness_codec.encode_witness(witness)
    branch_count = len(witness.branches)
    cutoff_cell_count = branch_count * (total_steps - lo_step)
    receipt = {
        "schema": SCHEMA_V2,
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
        "witness": {
            "format": witness_codec.MAGIC.decode("ascii").rstrip("\n"),
            "sha256": hashlib.sha256(encoded_witness).hexdigest(),
            "byte_size": len(encoded_witness),
            "branch_count": branch_count,
            "tube_count": tube_count,
            "cutoff_cell_count": cutoff_cell_count,
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
            "formula_only_global_lower_decimal": decimal_lower_text(
                minimum_formula_margin.lo_fraction()
            ),
            "reported_lower_exact": fraction_text(reported),
            "reported_lower_decimal": decimal_lower_text(reported),
            "minimum_location": minimum_location,
        },
        "verdict": classification["verdict"],
        "verdict_qualifier": classification["qualifier"],
        **producer_status(),
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
            "The non-authoritative producer alone does not certify nonlinear ODE propagation.",
            "The exact dyadic lower endpoint is a certified lower bound, not the exact mathematical infimum.",
            "No Monte Carlo or nominal trajectory supports the universal verdict.",
        ],
    }
    return receipt, witness


def write_json_atomic(path: Path, payload: dict) -> None:
    data = (json.dumps(payload, sort_keys=True, indent=2) + "\n").encode("utf-8")
    write_bytes_atomic(path, data)


def write_bytes_atomic(path: Path, payload: bytes) -> None:
    path = Path(os.path.abspath(path))
    if path.is_symlink():
        raise CertificationError("output path must not be a symlink")
    if os.path.lexists(path):
        raise CertificationError("output path must not already exist")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    try:
        write_private_snapshot(temporary, payload, 0o644)
        os.replace(temporary, path)
    except BaseException:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def format_summary(receipt: dict, path: Path) -> str:
    status = receipt.get("formal_checker_status")
    if status == "NOT_EXECUTED":
        if receipt.get("producer_assurance") != "candidate-only":
            raise CertificationError("candidate summary lacks producer assurance")
        return (
            f"CANDIDATE ONLY producer_assurance=candidate-only "
            f"formal_checker_status=NOT_EXECUTED "
            f"candidate_verdict={receipt['verdict']} {receipt['verdict_qualifier']} "
            f"candidate_margin_lo={receipt['decisive_margin']['reported_lower_decimal']} "
            f"receipt={path}"
        )
    if status != "ACCEPT":
        raise CertificationError("summary requires an explicit formal checker status")
    return (
        f"CHECKER-ACCEPTED CANDIDATE outer_verification=REQUIRED "
        f"candidate_verdict={receipt['verdict']} {receipt['verdict_qualifier']} "
        f"checker_claimed_status=formal-bounded formal_checker_status=ACCEPT "
        f"formal_margin_lo={receipt['formal_decisive_margin']['lo_decimal']} "
        f"receipt={path}"
    )


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    parser.add_argument("--witness", type=Path)
    parser.add_argument("--checker", type=Path)
    parser.add_argument("--proof-identity", type=Path)
    parser.add_argument("--request-digest")
    parser.add_argument("--model-id")
    parser.add_argument("--epoch")
    parser.add_argument("--nonce")
    args = parser.parse_args(arguments)
    formal_values = (
        args.checker, args.proof_identity, args.request_digest,
        args.model_id, args.epoch, args.nonce,
    )
    if any(value is not None for value in formal_values) and (
        any(value is None for value in formal_values)
        or args.witness is None
        or args.output is None
    ):
        parser.error("formal publication requires output, witness, and every formal binding argument")
    if any(
        path is not None and path.is_symlink()
        for path in (args.output, args.witness, args.checker, args.proof_identity)
    ):
        parser.error("output and formal publication paths must not be symlinks")
    if any(
        path is not None and os.path.lexists(Path(os.path.abspath(path)))
        for path in (args.output, args.witness)
    ):
        parser.error("output and witness paths must not already exist")
    named_paths = [
        path for path in (args.output, args.witness, args.checker, args.proof_identity)
        if path is not None
    ]
    lexical_paths = [Path(os.path.abspath(path)) for path in named_paths]
    if len(set(lexical_paths)) != len(lexical_paths):
        parser.error("output, witness, checker, and proof identity paths must be distinct")
    resolved_paths = [path.resolve(strict=False) for path in lexical_paths]
    if len(set(resolved_paths)) != len(resolved_paths):
        parser.error("resolved output and formal input paths must be distinct")
    for index, left in enumerate(lexical_paths):
        for right in lexical_paths[index + 1:]:
            if left.exists() and right.exists() and os.path.samefile(left, right):
                parser.error("output and formal input files must not share an inode")
    source_snapshot_digest = private_source_snapshot_digest()
    if source_snapshot_digest is None:
        return run_from_private_source_snapshot(arguments)
    observed_source_digest = _source_sha256()
    if source_snapshot_digest != observed_source_digest:
        raise CertificationError("private producer source snapshot binding failed")
    receipt, witness = certify()
    encoded_witness = witness_codec.encode_witness(witness)
    if args.witness:
        write_bytes_atomic(args.witness, encoded_witness)
    if args.checker is not None:
        bind_formal_checker(
            receipt, args.witness, args.checker,
            args.proof_identity, args.request_digest, args.model_id,
            args.epoch, args.nonce,
        )
    if _source_sha256() != observed_source_digest:
        raise CertificationError("private producer source snapshot changed during execution")
    if args.output:
        write_json_atomic(args.output, receipt)
        print(format_summary(receipt, args.output.resolve()))
    else:
        print(json.dumps(receipt, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
