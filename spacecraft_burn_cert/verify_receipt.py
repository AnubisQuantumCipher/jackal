#!/usr/bin/env python3
"""Independent verifier for spacecraft finite-burn interval receipts.

This file deliberately imports nothing from ``certify.py``.  It uses a second
interval implementation (pairs of scaled integers and free functions), parses
the producer's source contract with ``ast``, exactly checks the orbital
polynomial identities, and replays every ODE tube and cutoff post-processing
operation before accepting a baseline receipt.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import itertools
import json
import math
import os
import re
import stat
import subprocess
import tempfile
from fractions import Fraction
from pathlib import Path
from typing import Iterable, Sequence


BITS = 80
DEN = 1 << BITS
MAX_RECEIPT_BYTES = 16 * 1024 * 1024
MAX_SOURCE_BYTES = 16 * 1024 * 1024
MAX_REQUEST_BYTES = 1024 * 1024
MAX_WITNESS_BYTES = 64 * 1024 * 1024
MAX_CHECKER_BYTES = 512 * 1024 * 1024
MAX_IDENTITY_BYTES = 16 * 1024 * 1024
PINNED_TOOLCHAIN_CONFIGURATIONS = [
    {
        "path": "proofs/lean/lakefile.toml",
        "sha256": "48b4a93ddda8ea85bda3fe65ac2f94dc43d6629641cdaf7bead228ec26d90bfe",
    },
    {
        "path": "proofs/lean/lake-manifest.json",
        "sha256": "f521808691ba1ab175c5cdeec098a76586d345fea93370a38c2d2b73645f69d4",
    },
    {
        "path": "proofs/lean/lean-toolchain",
        "sha256": "2773c517aa90b66ea8a2c52bddddf84393157797f8341be0df45294fff7fd32e",
    },
]
Interval = tuple[int, int]
Box = tuple[Interval, ...]

RECEIPT_TOP_LEVEL_KEYS = {
    "cutoff_state_hull",
    "decisive_margin",
    "evidence_classification",
    "formal_checker",
    "formal_checker_status",
    "formal_decisive_margin",
    "method",
    "model_contract",
    "non_claims",
    "orbital_hulls",
    "problem",
    "producer_assurance",
    "schema",
    "source_sha256",
    "verdict",
    "verdict_qualifier",
    "witness",
}
INTERVAL_KEYS = {
    "lo_scaled_integer",
    "hi_scaled_integer",
    "lo_exact",
    "hi_exact",
    "lo_decimal",
    "hi_decimal",
}
EXPECTED_MODEL_CONTRACT = {
    "thrust_acceleration_scale": "0.001",
    "integrate_mass": True,
    "apoapsis_eccentricity_sign": 1,
    "energy_denominator": 2,
    "propagate_full_box": True,
    "decision_mode": "exact_lower_bound",
}
EXPECTED_PROBLEM = {
    "mu_km3_s2": "398600.4418",
    "g0_m_s2": "9.80665",
    "isp_s": "450",
    "earth_radius_km": "6378.1363",
    "initial_bounds": [
        ["13355999/2000", "13360001/2000"],
        ["-1/2000", "1/2000"],
        ["-1/50000", "1/50000"],
        ["38629/5000", "38631/5000"],
        ["2397/2", "2403/2"],
    ],
    "thrust_bounds_N": ["1995", "2005"],
    "burn_time_bounds_s": ["237/2", "243/2"],
}
EXPECTED_EVIDENCE_CLASSIFICATION = {
    "inputs_and_unit_constants": "exact",
    "interval_arithmetic": "exact integer implementation with outward rounding",
    "ode_reachable_set": "formal-bounded by the pinned Lean certificate checker",
    "orbital_algebra": "formal-bounded by the pinned Lean certificate checker",
    "nominal_reference": "numerically estimated diagnostic only",
    "sampling": "not used for the decisive result",
    "overall": "formal-bounded",
}
PICARD_PRODUCER_NONCLAIM = (
    "The Python Picard witness generator and its source are not formally verified. "
    "They are outside the mathematical soundness base because the pinned Lean "
    "checker independently checks every accepted tube, but remain trusted for "
    "termination, witness search/completeness, and reproducible generation. A "
    "producer defect may cause refusal, nontermination, or failure to find a "
    "witness, but cannot yield formal ACCEPT absent a defect in the pinned Lean "
    "checker or outer verification gate."
)
EXPECTED_NON_CLAIMS = [
    "The theorem is conditional on the stated finite-burn ODE model and supplied input bounds.",
    PICARD_PRODUCER_NONCLAIM,
    "The Lean kernel, compiler, runtime, checker executable, and declared axioms remain trusted components.",
    "The formal lower endpoint is a certified lower bound, not the exact mathematical infimum.",
    "No Monte Carlo or nominal trajectory supports the universal verdict.",
]
EXPECTED_REQUEST = {
    "burn_time_bounds_s": ["237/2", "243/2"],
    "earth_radius_km": "63781363/10000",
    "g0_m_s2": "196133/20000",
    "initial_bounds": [
        ["13355999/2000", "13360001/2000"],
        ["-1/2000", "1/2000"],
        ["-1/50000", "1/50000"],
        ["38629/5000", "38631/5000"],
        ["2397/2", "2403/2"],
    ],
    "isp_s": "450",
    "minimum_apoapsis_altitude_km": "1000",
    "model_id": "jackal-spacecraft-finite-burn-ode-v2",
    "mu_km3_s2": "1993002209/5000",
    "partition_counts": [4, 1, 1, 2, 2, 2],
    "schema": "jackal-spacecraft-burn-request-v2",
    "step_s": "1/32",
    "thrust_bounds_N": ["1995", "2005"],
    "thrust_km_scale": "1/1000",
}
ALLOWED_AXIOMS = ["propext", "Classical.choice", "Quot.sound"]
EXPECTED_PROOF_THEOREMS = [
    "JackalIv.Spacecraft.spacecraft_burn_certified_safe",
    "JackalIv.Spacecraft.spacecraft_burn_universal_safe",
    "JackalIv.Spacecraft.spacecraft_burn_certificate_sound",
    "JackalIv.Spacecraft.checkBurnWitness_sound",
    "JackalIv.Spacecraft.checkBurnWitness_universal_sound",
    "JackalIv.Spacecraft.checkBurnWitness_margin_bound",
    "JackalIv.Spacecraft.checkBranchesCert_sound",
    "JackalIv.Spacecraft.checkBranchesCert_universal_sound",
    "JackalIv.Spacecraft.checkBranchesCert_margin_bound",
    "JackalIv.Spacecraft.checkBranchCert_sound",
    "JackalIv.Spacecraft.checkBranchCert_universal_sound",
    "JackalIv.Spacecraft.checkBranchCert_margin_bound",
    "JackalIv.Spacecraft.checkOrbitSteps_sound",
    "JackalIv.Spacecraft.checkOrbitSteps_margin_bound",
    "JackalIv.Spacecraft.checked_chain_state_safe",
    "JackalIv.Spacecraft.checked_chain_state_margin_bound",
    "JackalIv.Spacecraft.chain_state_at_exists",
    "JackalIv.Spacecraft.checked_steps_nonvacuous",
    "JackalIv.Spacecraft.checked_steps_compose",
    "JackalIv.Spacecraft.exists_classicalSolution_of_checkStep",
    "JackalIv.Spacecraft.orbitPostprocess_sound",
    "JackalIv.Spacecraft.orbitalEccentricityFormula_eq_vector",
    "JackalIv.Spacecraft.intersection_sound",
    "JackalIv.Spacecraft.supplied_inputs_covered",
    "JackalIv.Spacecraft.supplied_cutoff_time_covered",
    "JackalIv.Spacecraft.checkCutoffCoverage_sound",
    "JackalIv.Spacecraft.fieldEnclosed",
    "JackalIv.Spacecraft.burnField_contDiffOn_of_domain",
    "JackalIv.Spacecraft.burnField_locallyLipschitzOn_of_domain",
]
EXPECTED_BUILD_ISOLATION_POLICY = (
    "Publication generation copies an explicit local Lean source closure, every pinned "
    "dependency blob, and the complete pinned Lean toolchain regular-file tree into a "
    "private mode-0700 workspace. Deterministic path overrides make Lake consume only "
    "those verified dependency snapshots. Lake is invoked with the absolute pinned "
    "lakefile, rehashing, reconfiguration, no remote cache, and the private toolchain. macOS "
    "sandbox policy denies the build subprocess writes to source and toolchain bytes "
    "while permitting dedicated .lake build/configuration directories and one exact "
    "ProofWidgets hash sidecar that --rehash recomputes but never trusts as an input. "
    "That sidecar and exact source/dependency manifests are checked around every Lake "
    "command, and the complete toolchain tree is checked before and after the build. "
    "This boundary trusts the "
    "owning macOS kernel, sandbox facility, dyld, libSystem, hardware, and the invoking "
    "Python interpreter; it is not a proof of that platform supply chain."
)
EXPECTED_LAKE_GENERATED_BOOKKEEPING = {
    "definition": (
        "Exact non-source Lake hash sidecars required to replay pinned dependency "
        "targets under --rehash; each is recomputed, never trusted as an input, and "
        "validated after every Lake command."
    ),
    "files": [
        {
            "bytes": 16,
            "path": ".lake/packages/proofwidgets/widget/package-lock.json.hash",
            "sha256": "971a4e08a78d3b185902cde49867376deb03135a517d4380eb1cb6604cfcb38b",
        },
    ],
}


class DuplicateJsonKey(ValueError):
    pass


def reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateJsonKey(key)
        result[key] = value
    return result


def reject_nonfinite_json(value: str) -> None:
    raise ValueError(f"non-finite JSON number: {value}")


def strict_json_bytes(raw: bytes) -> object:
    return json.loads(
        raw.decode("utf-8"),
        object_pairs_hook=reject_duplicate_keys,
        parse_constant=reject_nonfinite_json,
    )


def first_difference(expected: object, actual: object, path: str = "$") -> str | None:
    if type(expected) is not type(actual):
        return f"{path}:type"
    if isinstance(expected, dict):
        if set(expected) != set(actual):
            return f"{path}:keys"
        for key in sorted(expected):
            difference = first_difference(expected[key], actual[key], f"{path}.{key}")
            if difference is not None:
                return difference
        return None
    if isinstance(expected, list):
        if len(expected) != len(actual):
            return f"{path}:length"
        for index, (left, right) in enumerate(zip(expected, actual)):
            difference = first_difference(left, right, f"{path}[{index}]")
            if difference is not None:
                return difference
        return None
    return None if expected == actual else f"{path}:value"


def floor_q(value: Fraction) -> int:
    return value.numerator * DEN // value.denominator


def ceil_i(n: int, d: int) -> int:
    if d < 0:
        n, d = -n, -d
    return -((-n) // d)


def ceil_q(value: Fraction) -> int:
    return ceil_i(value.numerator * DEN, value.denominator)


def point(value: Fraction | str | int) -> Interval:
    q = value if isinstance(value, Fraction) else Fraction(value)
    return floor_q(q), ceil_q(q)


def interval(lo: Fraction | str | int, hi: Fraction | str | int) -> Interval:
    return floor_q(Fraction(lo)), ceil_q(Fraction(hi))


def add(a: Interval, b: Interval) -> Interval:
    return a[0] + b[0], a[1] + b[1]


def neg(a: Interval) -> Interval:
    return -a[1], -a[0]


def sub(a: Interval, b: Interval) -> Interval:
    return add(a, neg(b))


def mul(a: Interval, b: Interval) -> Interval:
    products = (a[0] * b[0], a[0] * b[1], a[1] * b[0], a[1] * b[1])
    return min(products) // DEN, ceil_i(max(products), DEN)


def ratio_floor(a: int, b: int) -> int:
    if b < 0:
        a, b = -a, -b
    return a * DEN // b


def ratio_ceil(a: int, b: int) -> int:
    if b < 0:
        a, b = -a, -b
    return ceil_i(a * DEN, b)


def div(a: Interval, b: Interval) -> Interval:
    if b[0] <= 0 <= b[1]:
        raise ValueError("zero denominator in independent replay")
    pairs = ((a[0], b[0]), (a[0], b[1]), (a[1], b[0]), (a[1], b[1]))
    return min(ratio_floor(x, y) for x, y in pairs), max(
        ratio_ceil(x, y) for x, y in pairs
    )


def sq(a: Interval) -> Interval:
    if a[0] <= 0 <= a[1]:
        return 0, ceil_i(max(a[0] * a[0], a[1] * a[1]), DEN)
    endpoints = (a[0] * a[0], a[1] * a[1])
    return min(endpoints) // DEN, ceil_i(max(endpoints), DEN)


def root(a: Interval) -> Interval:
    if a[0] < 0:
        raise ValueError("negative radicand in independent replay")
    lo_n = a[0] * DEN
    hi_n = a[1] * DEN
    lo = math.isqrt(lo_n)
    hi = math.isqrt(hi_n)
    if hi * hi < hi_n:
        hi += 1
    if lo * lo > lo_n or hi * hi < hi_n:
        raise ValueError("sqrt integer witness failed")
    return lo, hi


def hull(a: Interval, b: Interval) -> Interval:
    return min(a[0], b[0]), max(a[1], b[1])


def meet(a: Interval, b: Interval) -> Interval:
    answer = max(a[0], b[0]), min(a[1], b[1])
    if answer[0] > answer[1]:
        raise ValueError("independent eccentricity enclosures are disjoint")
    return answer


def hull_box(a: Box, b: Box) -> Box:
    return tuple(hull(x, y) for x, y in zip(a, b))


def inflate(a: Box) -> Box:
    result = []
    for lo, hi in a:
        pad = max(32, (hi - lo) // 20 + 1)
        result.append((lo - pad, hi + pad))
    return tuple(result)


def interior(a: Box, b: Box) -> bool:
    return all(outer[0] < inner[0] and inner[1] < outer[1] for inner, outer in zip(a, b))


Z = point(0)
ONE = point(1)
TWO = point(2)
KILO = point(1000)
MU = point("398600.4418")
G0 = point("9.80665")
ISP = point(450)
RE = point("6378.1363")
UNIT_SCALE = point("0.001")
H = Fraction(1, 32)
H_POINT = point(H)
H_TUBE = interval(0, H)
INITIAL = (
    (Fraction("6677.9995"), Fraction("6680.0005")),
    (Fraction("-0.0005"), Fraction("0.0005")),
    (Fraction("-0.00002"), Fraction("0.00002")),
    (Fraction("7.7258"), Fraction("7.7262")),
    (Fraction("1198.5"), Fraction("1201.5")),
)
THRUST = (Fraction(1995), Fraction(2005))
PARTS = (4, 1, 1, 2, 2, 2)
FIRST_CUTOFF_STEP = int(Fraction("118.5") / H)
TOTAL_STEPS = int(Fraction("121.5") / H)


def field(z: Box, thrust: Interval) -> Box:
    x, y, vx, vy, mass = z
    r2 = add(sq(x), sq(y))
    v2 = add(sq(vx), sq(vy))
    radius = root(r2)
    speed = root(v2)
    thrust_a = mul(div(thrust, mass), UNIT_SCALE)
    r3 = mul(r2, radius)
    ax = add(neg(div(mul(MU, x), r3)), div(mul(thrust_a, vx), speed))
    ay = add(neg(div(mul(MU, y), r3)), div(mul(thrust_a, vy), speed))
    dm = neg(div(thrust, mul(ISP, G0)))
    return vx, vy, ax, ay, dm


def mapping(x: Box, b: Box, thrust: Interval) -> Box:
    moved = tuple(add(value, mul(H_TUBE, slope)) for value, slope in zip(x, field(b, thrust)))
    return hull_box(x, moved)


def step(x: Box, thrust: Interval) -> tuple[Box, Box, int]:
    b = inflate(mapping(x, x, thrust))
    for iterations in range(1, 17):
        candidate = mapping(x, b, thrust)
        if interior(candidate, b):
            end = tuple(add(value, mul(H_POINT, slope)) for value, slope in zip(x, field(b, thrust)))
            return b, end, iterations
        b = inflate(hull_box(b, candidate))
    raise ValueError("independent Picard replay did not close")


def post(z: Box) -> dict[str, Interval]:
    x, y, vx, vy, _mass = z
    radius = root(add(sq(x), sq(y)))
    v2 = add(sq(vx), sq(vy))
    energy = sub(div(v2, TWO), div(MU, radius))
    if energy[1] >= 0:
        raise ValueError("non-elliptic energy in independent replay")
    semimajor = div(neg(MU), mul(TWO, energy))
    momentum = sub(mul(x, vy), mul(y, vx))
    e2 = add(ONE, div(mul(mul(TWO, energy), sq(momentum)), sq(MU)))
    eccentricity = root(e2)

    radial_dot = add(mul(x, vx), mul(y, vy))
    common = sub(v2, div(MU, radius))
    ex = div(sub(mul(common, x), mul(radial_dot, vx)), MU)
    ey = div(sub(mul(common, y), mul(radial_dot, vy)), MU)
    ev2 = add(sq(ex), sq(ey))
    ev = root(ev2)
    e = meet(eccentricity, ev)
    apo_formula = mul(semimajor, add(ONE, eccentricity))
    apo = mul(semimajor, add(ONE, e))
    alt_formula = sub(apo_formula, RE)
    alt = sub(apo, RE)
    return {
        "radius": radius,
        "speed_squared": v2,
        "energy": energy,
        "semimajor_axis": semimajor,
        "angular_momentum": momentum,
        "eccentricity_squared": e2,
        "eccentricity": eccentricity,
        "eccentricity_vector_squared": ev2,
        "eccentricity_vector": ev,
        "eccentricity_intersection": e,
        "apoapsis_formula": apo_formula,
        "apoapsis": apo,
        "altitude_formula": alt_formula,
        "altitude": alt,
        "margin_formula": sub(alt_formula, KILO),
        "margin_intersection": sub(alt, KILO),
    }


def split(lo: Fraction, hi: Fraction, count: int) -> tuple[Interval, ...]:
    width = (hi - lo) / count
    return tuple(interval(lo + k * width, lo + (k + 1) * width) for k in range(count))


def branches() -> tuple[tuple[Box, Interval], ...]:
    arms = [split(lo, hi, count) for (lo, hi), count in zip(INITIAL, PARTS[:5])]
    thrusts = split(*THRUST, PARTS[5])
    return tuple((tuple(row[:5]), row[5]) for row in itertools.product(*arms, thrusts))


def trace_update(hasher, branch: int, index: int, boxes: Iterable[Box]) -> None:
    hasher.update(f"b={branch};s={index};".encode("ascii"))
    for box in boxes:
        for lo, hi in box:
            hasher.update(str(lo).encode("ascii"))
            hasher.update(b",")
            hasher.update(str(hi).encode("ascii"))
            hasher.update(b";")


def canonical_witness_record(hasher, tokens: Sequence[object]) -> int:
    encoded = (" ".join(str(token) for token in tokens) + "\n").encode("ascii")
    hasher.update(encoded)
    return len(encoded)


def canonical_box_tokens(box: Box) -> tuple[int, ...]:
    return tuple(endpoint for value in box for endpoint in value)


def replay() -> dict:
    digest = hashlib.sha256()
    witness_digest = hashlib.sha256()
    witness_magic = b"jackal-spacecraft-burn-cert v2\n"
    witness_digest.update(witness_magic)
    witness_byte_size = len(witness_magic)
    state_hull = None
    post_hulls: dict[str, Interval] = {}
    minimum_cell = None
    minimum_formula_lo = None
    minimum_location = None
    max_iterations = 0
    tube_count = 0
    post_count = 0
    domain_radius_squared_lo = None
    domain_speed_squared_lo = None
    domain_mass_lo = None
    arms = branches()
    cutoff_count = len(arms) * (TOTAL_STEPS - FIRST_CUTOFF_STEP)
    witness_byte_size += canonical_witness_record(
        witness_digest,
        (
            "config",
            BITS,
            H.numerator,
            H.denominator,
            *PARTS,
            TOTAL_STEPS,
            FIRST_CUTOFF_STEP,
            len(arms),
            len(arms) * TOTAL_STEPS,
            cutoff_count,
        ),
    )
    for branch_id, (initial, thrust) in enumerate(arms):
        witness_byte_size += canonical_witness_record(
            witness_digest,
            ("branch", branch_id, *canonical_box_tokens(initial), *thrust),
        )
        state = initial
        for index in range(TOTAL_STEPS):
            tube, endpoint, iterations = step(state, thrust)
            witness_byte_size += canonical_witness_record(
                witness_digest,
                ("tube", branch_id, index, *canonical_box_tokens(tube)),
            )
            max_iterations = max(max_iterations, iterations)
            tube_count += 1
            radius_squared_lo = add(sq(tube[0]), sq(tube[1]))[0]
            speed_squared_lo = add(sq(tube[2]), sq(tube[3]))[0]
            mass_lo = tube[4][0]
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
            trace_update(digest, branch_id, index, (state, tube, endpoint))
            if index >= FIRST_CUTOFF_STEP:
                state_hull = tube if state_hull is None else hull_box(state_hull, tube)
                values = post(tube)
                post_count += 1
                for name, value in values.items():
                    post_hulls[name] = value if name not in post_hulls else hull(post_hulls[name], value)
                margin = values["margin_intersection"]
                if minimum_cell is None or margin[0] < minimum_cell[0]:
                    minimum_cell = margin
                    minimum_location = {
                        "branch_index": branch_id,
                        "step_index": index,
                        "time_lo_exact": frac_text(Fraction(index) * H),
                        "time_hi_exact": frac_text(Fraction(index + 1) * H),
                    }
                f_lo = values["margin_formula"][0]
                if minimum_formula_lo is None or f_lo < minimum_formula_lo:
                    minimum_formula_lo = f_lo
            state = endpoint
    witness_byte_size += canonical_witness_record(
        witness_digest,
        ("end", len(arms), len(arms) * TOTAL_STEPS, cutoff_count),
    )
    return {
        "trace_sha256": digest.hexdigest(),
        "branch_count": len(arms),
        "tube_count": tube_count,
        "postprocess_count": post_count,
        "maximum_picard_iterations": max_iterations,
        "cutoff": state_hull,
        "post": post_hulls,
        "minimum_cell": minimum_cell,
        "minimum_formula_lo": minimum_formula_lo,
        "minimum_location": minimum_location,
        "domain_lower_bounds": {
            "radius_squared_exact": frac_text(Fraction(domain_radius_squared_lo, DEN)),
            "speed_squared_exact": frac_text(Fraction(domain_speed_squared_lo, DEN)),
            "mass_exact": frac_text(Fraction(domain_mass_lo, DEN)),
        },
        "canonical_witness_sha256": witness_digest.hexdigest(),
        "canonical_witness_byte_size": witness_byte_size,
    }


def frac_text(q: Fraction) -> str:
    return str(q.numerator) if q.denominator == 1 else f"{q.numerator}/{q.denominator}"


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


def interval_document(value: Interval) -> dict[str, str]:
    lo, hi = value
    lo_fraction = Fraction(lo, DEN)
    hi_fraction = Fraction(hi, DEN)
    return {
        "lo_scaled_integer": str(lo),
        "hi_scaled_integer": str(hi),
        "lo_exact": frac_text(lo_fraction),
        "hi_exact": frac_text(hi_fraction),
        "lo_decimal": decimal_lower_text(lo_fraction),
        "hi_decimal": decimal_upper_text(hi_fraction),
    }


def poly_const(value: Fraction | int, variables: int) -> dict[tuple[int, ...], Fraction]:
    q = Fraction(value)
    return {} if q == 0 else {(0,) * variables: q}


def poly_var(index: int, variables: int) -> dict[tuple[int, ...], Fraction]:
    powers = [0] * variables
    powers[index] = 1
    return {tuple(powers): Fraction(1)}


def poly_add(a, b):
    out = dict(a)
    for monomial, coefficient in b.items():
        out[monomial] = out.get(monomial, Fraction(0)) + coefficient
        if out[monomial] == 0:
            del out[monomial]
    return out


def poly_neg(a):
    return {m: -c for m, c in a.items()}


def poly_sub(a, b):
    return poly_add(a, poly_neg(b))


def poly_mul(a, b):
    out = {}
    for ma, ca in a.items():
        for mb, cb in b.items():
            monomial = tuple(x + y for x, y in zip(ma, mb))
            out[monomial] = out.get(monomial, Fraction(0)) + ca * cb
    return {m: c for m, c in out.items() if c}


def poly_pow(a, exponent: int):
    variables = len(next(iter(a))) if a else 1
    result = poly_const(1, variables)
    for _ in range(exponent):
        result = poly_mul(result, a)
    return result


def verify_symbolic_identities() -> dict[str, bool]:
    variables = 4
    x, y, vx, vy = (poly_var(i, variables) for i in range(variables))
    r2 = poly_add(poly_pow(x, 2), poly_pow(y, 2))
    v2 = poly_add(poly_pow(vx, 2), poly_pow(vy, 2))
    rv = poly_add(poly_mul(x, vx), poly_mul(y, vy))
    h = poly_sub(poly_mul(x, vy), poly_mul(y, vx))
    lagrange = poly_sub(poly_sub(poly_mul(v2, r2), poly_pow(rv, 2)), poly_pow(h, 2))

    variables2 = 5
    velocity, q, radius2, radial2, h2 = (
        poly_var(i, variables2) for i in range(variables2)
    )
    two_q = poly_mul(poly_const(2, variables2), q)
    v_minus_q = poly_sub(velocity, q)
    raw = poly_add(
        poly_mul(poly_pow(v_minus_q, 2), radius2),
        poly_mul(poly_sub(two_q, velocity), radial2),
    )
    target = poly_add(
        poly_mul(poly_pow(q, 2), radius2),
        poly_mul(poly_sub(velocity, two_q), h2),
    )
    relation = poly_sub(poly_sub(poly_mul(velocity, radius2), radial2), h2)
    factored = poly_mul(poly_sub(velocity, two_q), relation)

    variables3 = 7
    radius, speed2, energy, axis3, eccentricity2, h_squared, mu = (
        poly_var(i, variables3) for i in range(variables3)
    )
    two = poly_const(2, variables3)
    radius_speed_minus_gravity = poly_sub(
        poly_mul(radius, speed2), poly_mul(two, mu)
    )
    energy_residual = poly_sub(
        poly_mul(poly_mul(two, radius), energy), radius_speed_minus_gravity
    )
    axis_residual = poly_add(
        poly_mul(poly_mul(two, energy), axis3), mu
    )
    vis_viva_residual = poly_add(
        poly_mul(axis3, radius_speed_minus_gravity), poly_mul(mu, radius)
    )
    vis_viva_from_definitions = poly_sub(
        poly_mul(radius, axis_residual), poly_mul(axis3, energy_residual)
    )
    mu_squared = poly_pow(mu, 2)
    eccentricity_residual = poly_sub(
        poly_sub(poly_mul(mu_squared, eccentricity2), mu_squared),
        poly_mul(poly_mul(two, energy), h_squared),
    )
    eccentricity_energy_momentum_residual = poly_sub(
        poly_sub(
            poly_mul(poly_mul(radius, mu_squared), eccentricity2),
            poly_mul(radius, mu_squared),
        ),
        poly_mul(h_squared, radius_speed_minus_gravity),
    )
    eccentricity_from_definitions = poly_add(
        poly_mul(radius, eccentricity_residual),
        poly_mul(h_squared, energy_residual),
    )

    variables4 = 2
    axis, eccentricity = (poly_var(i, variables4) for i in range(variables4))
    apo = poly_mul(axis, poly_add(poly_const(1, variables4), eccentricity))
    apo_expanded = poly_add(axis, poly_mul(axis, eccentricity))
    return {
        "angular_momentum_lagrange_identity": not lagrange,
        "eccentricity_vector_reduction": not poly_sub(poly_sub(raw, target), factored),
        "vis_viva_cleared_denominator_identity": not poly_sub(
            vis_viva_residual, vis_viva_from_definitions
        ),
        "eccentricity_energy_momentum_identity": not poly_sub(
            eccentricity_energy_momentum_residual, eccentricity_from_definitions
        ),
        "apoapsis_plus_expansion": not poly_sub(apo, apo_expanded),
    }


CONTRACT = {
    "THRUST_KM_SCALE_TEXT": ("0.001", "unit-scale-mismatch"),
    "INTEGRATE_MASS": (True, "mass-integration-mismatch"),
    "APOAPSIS_ECCENTRICITY_SIGN": (1, "apoapsis-plus-mismatch"),
    "ENERGY_HALF_DENOMINATOR": (2, "energy-half-mismatch"),
    "PROPAGATE_FULL_BOX": (True, "full-box-coverage-mismatch"),
    "DECISION_MODE": ("exact_lower_bound", "decision-rounding-mismatch"),
}


def source_literals(raw: bytes, path: Path) -> dict[str, object]:
    tree = ast.parse(raw.decode("utf-8"), filename=str(path))
    values = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            if name in CONTRACT:
                values[name] = ast.literal_eval(node.value)
    return values


def parse_receipt_interval(payload: dict, reasons: list[str], label: str) -> Interval | None:
    try:
        if type(payload) is not dict or set(payload) != INTERVAL_KEYS:
            raise ValueError
        if not all(type(payload[key]) is str for key in INTERVAL_KEYS):
            raise ValueError
        if re.fullmatch(r"-?(?:0|[1-9][0-9]*)", payload["lo_scaled_integer"]) is None:
            raise ValueError
        if re.fullmatch(r"-?(?:0|[1-9][0-9]*)", payload["hi_scaled_integer"]) is None:
            raise ValueError
        lo = int(payload["lo_scaled_integer"])
        hi = int(payload["hi_scaled_integer"])
        if lo > hi:
            raise ValueError
        expected = interval_document((lo, hi))
        if first_difference(expected, payload) is not None:
            raise ValueError
        return lo, hi
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        reasons.append(f"invalid-interval:{label}")
        return None


def compare_interval(candidate: dict, expected: Interval, reasons: list[str], label: str) -> None:
    observed = parse_receipt_interval(candidate, reasons, label)
    if observed is not None and observed != expected:
        reasons.append(f"interval-mismatch:{label}")


MODEL_QUALIFIER = (
    "under the stated finite-burn ODE model, supplied input bounds, "
    "and machine-checked interval-certificate assumptions"
)


def expected_receipt_document(
    expected: dict,
    *,
    source_digest: str,
    witness_digest: str,
    witness_byte_size: int,
    checker_digest: str,
    proof_file_digest: str,
    proof_identity_digest: str,
    request_digest: str,
    model_id: str,
    epoch: str,
    nonce: str,
    result_line: str,
    formal_margin: Interval,
) -> dict:
    cutoff_names = ("x", "y", "vx", "vy", "mass")
    minimum_cell = expected["minimum_cell"]
    minimum_formula = Fraction(expected["minimum_formula_lo"], DEN)
    reported_lower = Fraction(minimum_cell[0], DEN)
    return {
        "schema": "spacecraft-finite-burn-formal-receipt-v2",
        "source_sha256": source_digest,
        "method": {
            "arithmetic": "exact-integer outward-rounded dyadic intervals",
            "scale_bits": BITS,
            "ode_enclosure": "validated Picard self-map plus interval endpoint integral",
            "step_exact": "1/32",
            "partition_counts": list(PARTS),
            "branch_count": expected["branch_count"],
            "tube_count": expected["tube_count"],
            "postprocess_count": expected["postprocess_count"],
            "maximum_picard_iterations": expected["maximum_picard_iterations"],
            "trace_sha256": expected["trace_sha256"],
            "domain_lower_bounds": expected["domain_lower_bounds"],
        },
        "model_contract": EXPECTED_MODEL_CONTRACT,
        "witness": {
            "format": "jackal-spacecraft-burn-cert v2",
            "sha256": witness_digest,
            "byte_size": witness_byte_size,
            "branch_count": expected["branch_count"],
            "tube_count": expected["tube_count"],
            "cutoff_cell_count": expected["postprocess_count"],
        },
        "problem": EXPECTED_PROBLEM,
        "cutoff_state_hull": {
            name: interval_document(value)
            for name, value in zip(cutoff_names, expected["cutoff"])
        },
        "orbital_hulls": {
            name: interval_document(value) for name, value in expected["post"].items()
        },
        "decisive_margin": {
            "interval": interval_document(minimum_cell),
            "formula_only_global_lower_exact": frac_text(minimum_formula),
            "formula_only_global_lower_decimal": decimal_lower_text(minimum_formula),
            "reported_lower_exact": frac_text(reported_lower),
            "reported_lower_decimal": decimal_lower_text(reported_lower),
            "minimum_location": expected["minimum_location"],
        },
        "verdict": "CERTIFIED SAFE" if reported_lower > 0 else "INDETERMINATE",
        "verdict_qualifier": MODEL_QUALIFIER,
        "producer_assurance": "candidate-only",
        "formal_checker_status": "ACCEPT",
        "formal_checker": {
            "checker_sha256": checker_digest,
            "proof_identity_file_sha256": proof_file_digest,
            "proof_identity_digest_sha256": proof_identity_digest,
            "witness_sha256": witness_digest,
            "request_digest": request_digest,
            "model_id": model_id,
            "epoch": epoch,
            "nonce": nonce,
            "theorem": "spacecraft_burn_certified_safe",
            "result_line": result_line,
        },
        "formal_decisive_margin": {
            "scale_bits": BITS,
            **interval_document(formal_margin),
        },
        "evidence_classification": EXPECTED_EVIDENCE_CLASSIFICATION,
        "non_claims": EXPECTED_NON_CLAIMS,
    }


def checker_acceptance_margin(
    line: str, model_id: str, epoch: str
) -> tuple[int, int] | None:
    match = re.fullmatch(
        r"ACCEPT theorem=spacecraft_burn_certified_safe status=formal-bounded "
        r"margin_lo=([0-9]+) margin_hi=([0-9]+) model="
        + re.escape(model_id)
        + r" epoch="
        + re.escape(epoch),
        line,
    )
    if match is None:
        return None
    margin_lo, margin_hi = map(int, match.groups())
    return (margin_lo, margin_hi) if 0 < margin_lo <= margin_hi else None


def checker_acceptance_line(line: str, model_id: str, epoch: str) -> bool:
    return checker_acceptance_margin(line, model_id, epoch) is not None


def formal_margin_matches_replay(formal_margin: Interval, expected: dict) -> bool:
    """Bind the checker-wide hull to the independently replayed cell hull."""
    post_hulls = expected.get("post")
    return (
        isinstance(post_hulls, dict)
        and post_hulls.get("margin_intersection") == formal_margin
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_regular_snapshot(path: Path, maximum_bytes: int) -> bytes:
    """Open once without following the final symlink, bound, and snapshot a file."""
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    descriptor: int | None = None
    try:
        descriptor = os.open(path, flags)
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_size > maximum_bytes:
            raise ValueError("input is not a bounded regular file")
        payload = bytearray()
        while len(payload) <= maximum_bytes:
            block = os.read(
                descriptor,
                min(1024 * 1024, maximum_bytes + 1 - len(payload)),
            )
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
            raise ValueError("input changed during bounded read")
        return bytes(payload)
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass


def write_output_atomic(path: Path, payload: bytes) -> None:
    write_output_atomic_bound(path, payload, ())


def _lexical_absolute(path: Path | str) -> Path:
    return Path(os.path.abspath(os.fspath(path)))


def _resolved_parent_leaf(path: Path | str) -> Path:
    lexical = _lexical_absolute(path)
    if not lexical.name:
        raise ValueError("output path has no filename")
    return lexical.parent.resolve(strict=False) / lexical.name


def prepare_output_path(
    path: Path | str, input_paths: Iterable[Path | str]
) -> Path:
    """Validate an output without ever resolving or following its leaf."""
    lexical = _lexical_absolute(path)
    resolved_parent = _resolved_parent_leaf(lexical)
    output_candidates = tuple(dict.fromkeys((lexical, resolved_parent)))
    for candidate in output_candidates:
        try:
            metadata = os.lstat(candidate)
        except FileNotFoundError:
            continue
        except OSError as error:
            raise ValueError("verification output path cannot be inspected") from error
        if stat.S_ISLNK(metadata.st_mode):
            raise ValueError("verification output path must not be a symlink")
        raise ValueError("verification output path must not already exist")

    for input_path in input_paths:
        input_lexical = _lexical_absolute(input_path)
        input_resolved_parent = _resolved_parent_leaf(input_lexical)
        if lexical == input_lexical or resolved_parent == input_resolved_parent:
            raise ValueError("verification output must not alias an input path")
    return resolved_parent


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(
        path,
        os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_CLOEXEC", 0),
    )
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def write_output_atomic_bound(
    path: Path | str,
    payload: bytes,
    input_paths: Iterable[Path | str],
) -> Path:
    inputs = tuple(input_paths)
    target = prepare_output_path(path, inputs)
    target.parent.mkdir(parents=True, exist_ok=True)
    target = prepare_output_path(target, inputs)
    descriptor: int | None = None
    temporary: Path | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{target.name}.tmp-", dir=target.parent
        )
        temporary = Path(temporary_name)
        os.fchmod(descriptor, 0o644)
        view = memoryview(payload)
        offset = 0
        while offset < len(view):
            written = os.write(descriptor, view[offset:])
            if written <= 0:
                raise RuntimeError("zero-length verifier output write")
            offset += written
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = None
        os.replace(temporary, target)
        temporary = None
        _fsync_directory(target.parent)
        return target
    except BaseException:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
        raise


def canonical_json_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()


def _identity_bound_relative_candidates(recorded: str) -> tuple[Path, ...]:
    relative = Path(recorded)
    if (
        not recorded
        or relative.is_absolute()
        or relative == Path(".")
        or ".." in relative.parts
    ):
        raise ValueError("identity-bound path is not a confined relative path")
    candidates = [relative]
    if relative.parts[:2] == ("proofs", "lean"):
        candidates.append(Path("proofs", *relative.parts[2:]))
    return tuple(dict.fromkeys(candidates))


def _open_directory_snapshot(path: Path) -> tuple[Path, int]:
    """Open a resolved directory component-by-component without following links."""
    nofollow = getattr(os, "O_NOFOLLOW", None)
    directory = getattr(os, "O_DIRECTORY", None)
    if nofollow is None or directory is None:
        raise OSError("required no-follow directory-open support is unavailable")
    resolved = path.resolve(strict=True)
    if not resolved.is_absolute():
        raise ValueError("identity source root must resolve to an absolute path")
    flags = os.O_RDONLY | nofollow | directory | getattr(os, "O_CLOEXEC", 0)
    descriptor = os.open(os.sep, flags)
    try:
        for component in resolved.parts[1:]:
            child = os.open(component, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        if not stat.S_ISDIR(os.fstat(descriptor).st_mode):
            raise ValueError("identity source root is not a directory")
        return resolved, descriptor
    except BaseException:
        try:
            os.close(descriptor)
        except OSError:
            pass
        raise


def _read_regular_at(
    root_descriptor: int, relative: Path, maximum_bytes: int
) -> bytes:
    """Read one stable regular file beneath an already-open directory root."""
    nofollow = getattr(os, "O_NOFOLLOW", None)
    directory = getattr(os, "O_DIRECTORY", None)
    if nofollow is None or directory is None:
        raise OSError("required no-follow open support is unavailable")
    directory_flags = (
        os.O_RDONLY | nofollow | directory | getattr(os, "O_CLOEXEC", 0)
    )
    file_flags = (
        os.O_RDONLY
        | nofollow
        | getattr(os, "O_NONBLOCK", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )
    descriptor = os.dup(root_descriptor)
    try:
        for component in relative.parts[:-1]:
            child = os.open(component, directory_flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        leaf = os.open(relative.parts[-1], file_flags, dir_fd=descriptor)
        os.close(descriptor)
        descriptor = leaf
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_size > maximum_bytes:
            raise ValueError("identity-bound input is not a bounded regular file")
        payload = bytearray()
        while len(payload) <= maximum_bytes:
            block = os.read(
                descriptor,
                min(1024 * 1024, maximum_bytes + 1 - len(payload)),
            )
            if not block:
                break
            payload.extend(block)
        after = os.fstat(descriptor)
        stable_fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
        if (
            len(payload) > maximum_bytes
            or len(payload) != before.st_size
            or any(
                getattr(before, field) != getattr(after, field)
                for field in stable_fields
            )
        ):
            raise ValueError("identity-bound input changed during bounded read")
        return bytes(payload)
    finally:
        try:
            os.close(descriptor)
        except OSError:
            pass


class IdentityBoundSource:
    """Open-once authority for every source byte named by a proof identity."""

    def __init__(self, identity_path: Path, source_root: Path | None = None):
        self._roots: list[tuple[Path, int]] = []
        seen: set[Path] = set()
        try:
            for ancestor in identity_bound_ancestors(identity_path, source_root):
                resolved, descriptor = _open_directory_snapshot(ancestor)
                if resolved in seen:
                    os.close(descriptor)
                    continue
                seen.add(resolved)
                self._roots.append((resolved, descriptor))
        except BaseException:
            self.close()
            raise
        if not self._roots:
            raise ValueError("no identity-bound source root is available")

    def close(self) -> None:
        while self._roots:
            _, descriptor = self._roots.pop()
            try:
                os.close(descriptor)
            except OSError:
                pass

    def __enter__(self) -> "IdentityBoundSource":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def read(self, recorded: str, maximum_bytes: int) -> bytes | None:
        candidates = _identity_bound_relative_candidates(recorded)
        for _root, descriptor in self._roots:
            for relative in candidates:
                try:
                    return _read_regular_at(descriptor, relative, maximum_bytes)
                except FileNotFoundError:
                    continue
        return None

    def entry_exists(self, recorded: str) -> bool:
        """Conservatively detect a local entry without following any symlink."""
        nofollow = getattr(os, "O_NOFOLLOW", None)
        directory = getattr(os, "O_DIRECTORY", None)
        if nofollow is None or directory is None:
            return True
        flags = os.O_RDONLY | nofollow | directory | getattr(os, "O_CLOEXEC", 0)
        for _root, root_descriptor in self._roots:
            for relative in _identity_bound_relative_candidates(recorded):
                descriptor = os.dup(root_descriptor)
                try:
                    missing = False
                    for component in relative.parts[:-1]:
                        try:
                            child = os.open(component, flags, dir_fd=descriptor)
                        except FileNotFoundError:
                            missing = True
                            break
                        except OSError:
                            return True
                        os.close(descriptor)
                        descriptor = child
                    if missing:
                        continue
                    try:
                        os.stat(
                            relative.parts[-1],
                            dir_fd=descriptor,
                            follow_symlinks=False,
                        )
                    except FileNotFoundError:
                        continue
                    except (OSError, ValueError):
                        return True
                    return True
                finally:
                    try:
                        os.close(descriptor)
                    except OSError:
                        pass
        return False

    def locate(self, recorded: str) -> Path | None:
        candidates = _identity_bound_relative_candidates(recorded)
        for root, descriptor in self._roots:
            for relative in candidates:
                try:
                    _read_regular_at(descriptor, relative, MAX_SOURCE_BYTES)
                except FileNotFoundError:
                    continue
                return root / relative
        return None


def identity_bound_ancestors(
    identity_path: Path, source_root: Path | None = None
) -> tuple[Path, ...]:
    if source_root is not None:
        return (source_root,)
    return tuple(dict.fromkeys((identity_path.parent, *tuple(identity_path.parents)[:4])))


def resolve_identity_bound_path(
    identity_path: Path, recorded: str, source_root: Path | None = None
) -> Path | None:
    try:
        with IdentityBoundSource(identity_path, source_root) as source:
            return source.locate(recorded)
    except (OSError, RuntimeError, ValueError):
        return None


def read_identity_bound_snapshot(
    identity_path: Path,
    recorded: str,
    maximum_bytes: int,
    source_root: Path | None = None,
    *,
    source: IdentityBoundSource | None = None,
) -> bytes | None:
    if source is not None:
        return source.read(recorded, maximum_bytes)
    with IdentityBoundSource(identity_path, source_root) as opened_source:
        return opened_source.read(recorded, maximum_bytes)


def repository_local_lean_module_exists(
    identity_path: Path,
    module: str,
    source_root: Path | None = None,
    *,
    source: IdentityBoundSource | None = None,
) -> bool:
    if LEAN_MODULE_RE.fullmatch(module) is None:
        return True
    recorded = "proofs/lean/" + module.replace(".", "/") + ".lean"
    try:
        if source is not None:
            return source.entry_exists(recorded)
        with IdentityBoundSource(identity_path, source_root) as opened_source:
            return opened_source.entry_exists(recorded)
    except (OSError, RuntimeError, ValueError):
        return True


def normalized_manifest_packages(manifest: object) -> list[dict] | None:
    packages = manifest.get("packages") if type(manifest) is dict else None
    if type(packages) is not list:
        return None
    normalized = []
    for package in packages:
        if (
            type(package) is not dict
            or type(package.get("name")) is not str
            or package.get("type") != "git"
            or type(package.get("rev")) is not str
            or type(package.get("inherited")) is not bool
            or type(package.get("configFile")) is not str
            or not package["configFile"]
            or Path(package["configFile"]).is_absolute()
            or ".." in Path(package["configFile"]).parts
            or type(package.get("manifestFile")) is not str
            or not package["manifestFile"]
            or Path(package["manifestFile"]).is_absolute()
            or ".." in Path(package["manifestFile"]).parts
            or type(package.get("scope", "")) is not str
            or (
                package.get("subDir") is not None
                and (
                    type(package["subDir"]) is not str
                    or Path(package["subDir"]).is_absolute()
                    or ".." in Path(package["subDir"]).parts
                )
            )
            or Path(package["name"]).is_absolute()
            or len(Path(package["name"]).parts) != 1
            or package["name"] in {"", ".", ".."}
        ):
            return None
        if package["type"] == "git" and re.fullmatch(
            r"[0-9a-f]{40}", package["rev"]
        ) is None:
            return None
        normalized.append({
            "config_file": package.get("configFile"),
            "inherited": package.get("inherited"),
            "input_revision": package.get("inputRev"),
            "manifest_file": package.get("manifestFile"),
            "name": package["name"],
            "revision": package["rev"],
            "scope": package.get("scope"),
            "subdirectory": package.get("subDir"),
            "type": package["type"],
            "url": package.get("url"),
        })
    normalized.sort(key=lambda row: row["name"])
    if len({row["name"] for row in normalized}) != len(normalized):
        return None
    return normalized


def private_dependency_override_bytes(packages: list[dict]) -> bytes:
    entries = []
    for package in packages:
        relative = Path(".lake/packages") / package["name"]
        if package["subdirectory"] is not None:
            relative /= package["subdirectory"]
        entries.append({
            "configFile": package["config_file"],
            "dir": relative.as_posix(),
            "inherited": package["inherited"],
            "manifestFile": package["manifest_file"],
            "name": package["name"],
            "scope": package["scope"] or "",
            "type": "path",
        })
    return (
        json.dumps(
            {"packages": entries, "version": "1.2.0"},
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def valid_lower_hex_digest(value: object, *, length: int = 64) -> bool:
    return (
        length in (40, 64)
        and type(value) is str
        and len(value) == length
        and all(character in "0123456789abcdef" for character in value)
    )


def trusted_platform_launchers_valid(rows: object) -> bool:
    expected_roles = [
        "python-launcher",
        "python-interpreter",
        "git-client",
        "sandbox-launcher",
    ]
    fixed_invocation_paths = {
        "python-launcher": "/usr/bin/python3",
        "git-client": "/usr/bin/git",
        "sandbox-launcher": "/usr/bin/sandbox-exec",
    }
    if (
        type(rows) is not list
        or [row.get("role") if type(row) is dict else None for row in rows]
        != expected_roles
    ):
        return False
    for row in rows:
        invocation_path = row.get("invocation_path")
        resolved_path = row.get("resolved_path")
        symlink_target = row.get("invocation_symlink_target")
        expected_path = fixed_invocation_paths.get(row["role"])
        if (
            set(row)
            != {
                "bytes",
                "invocation_path",
                "invocation_symlink_target",
                "resolved_path",
                "role",
                "sha256",
            }
            or type(row.get("bytes")) is not int
            or row["bytes"] <= 0
            or type(invocation_path) is not str
            or not Path(invocation_path).is_absolute()
            or ".." in Path(invocation_path).parts
            or type(resolved_path) is not str
            or not Path(resolved_path).is_absolute()
            or ".." in Path(resolved_path).parts
            or (symlink_target is not None and type(symlink_target) is not str)
            or (
                expected_path is not None
                and (
                    invocation_path != expected_path
                    or resolved_path != expected_path
                    or symlink_target is not None
                )
            )
            or not valid_lower_hex_digest(row.get("sha256"))
        ):
            return False
    return True


def lean_code_without_comments_or_strings(source: str) -> str:
    output: list[str] = []
    index = 0
    block_depth = 0
    in_string = False
    while index < len(source):
        char = source[index]
        pair = source[index:index + 2]
        if block_depth:
            if pair == "/-":
                output.extend("  ")
                block_depth += 1
                index += 2
            elif pair == "-/":
                output.extend("  ")
                block_depth -= 1
                index += 2
            else:
                output.append("\n" if char == "\n" else " ")
                index += 1
            continue
        if in_string:
            if char == "\\" and index + 1 < len(source):
                output.extend("  ")
                index += 2
            elif char == '"':
                output.append(" ")
                in_string = False
                index += 1
            else:
                output.append("\n" if char == "\n" else " ")
                index += 1
            continue
        if pair == "/-":
            output.extend("  ")
            block_depth = 1
            index += 2
        elif pair == "--":
            while index < len(source) and source[index] != "\n":
                output.append(" ")
                index += 1
        elif char == '"':
            output.append(" ")
            in_string = True
            index += 1
        else:
            output.append(char)
            index += 1
    if block_depth or in_string:
        raise ValueError("unterminated Lean comment or string")
    return "".join(output)


FORBIDDEN_LEAN_CONSTRUCT_PATTERNS = (
    r"\bsorry\b",
    r"\badmit\b",
    r"\bunsafe\b",
    r"\bpartial\b",
    r"\bextern\b",
    r"\bnative_decide\b",
    r"\bimplemented_by\b",
    r"\baxioms?\b",
)


def has_forbidden_lean_construct(code: str) -> bool:
    return any(
        re.search(pattern, code) is not None
        for pattern in FORBIDDEN_LEAN_CONSTRUCT_PATTERNS
    )


LEAN_MODULE_RE = re.compile(
    r"[A-Z][A-Za-z0-9_']*(?:\.[A-Z][A-Za-z0-9_']*)*"
)


def parse_lean_imports(code: str) -> list[str]:
    imports: list[str] = []
    for line in code.splitlines():
        contains_import = re.search(r"\bimport\b", line) is not None
        match = re.fullmatch(r"\s*import\s+(.+?)\s*", line)
        if not contains_import:
            continue
        if match is None:
            raise ValueError("unsupported Lean import syntax")
        tokens = match.group(1).split()
        if not tokens or any(LEAN_MODULE_RE.fullmatch(token) is None for token in tokens):
            raise ValueError("unsupported Lean import module")
        imports.extend(tokens)
    return imports


def _validate_identity_semantics(
    document: dict,
    path: Path,
    *,
    checker_digest: str,
    checker_size: int | None,
    request_digest: str,
    model_id: str,
    epoch: str,
    reasons: list[str],
    source_root: Path | None = None,
    source: IdentityBoundSource,
) -> None:
    expected_top = {
        "build_attestation",
        "checker",
        "fragment",
        "generator",
        "identity_digest_sha256",
        "proof",
        "schema",
        "source_closure",
        "toolchain",
    }
    if set(document) != expected_top or document.get("schema") != "jackal-spacecraft-burn-proof-identity-v1":
        reasons.append("proof-identity-schema-mismatch")
        return

    checker = document.get("checker")
    expected_checker_keys = {"bytes", "path", "sha256", "target"}
    if (
        type(checker) is not dict
        or set(checker) != expected_checker_keys
        or checker.get("path")
        != "proofs/lean/.lake/build/bin/jackal_spacecraft_burn_check"
        or checker.get("target") != "jackal_spacecraft_burn_check"
        or checker.get("sha256") != checker_digest
        or type(checker.get("bytes")) is not int
        or checker["bytes"] <= 0
        or (checker_size is not None and checker["bytes"] != checker_size)
    ):
        reasons.append("proof-identity-checker-mismatch")

    expected_fragment = {
        "assurance": "formal-bounded",
        "certificate_magic": "jackal-spacecraft-burn-cert v2",
        "checker_boolean_definition": "JackalIv.Spacecraft.checkBurnCert",
        "checker_entrypoint_definition": "main (Spacecraft.CertMain)",
        "checker_executable": "jackal_spacecraft_burn_check",
        "checker_root_module": "JackalIv.Spacecraft.CertMain",
        "checker_build_cache_policy": (
            "identity generation builds only open-once snapshots of local and pinned "
            "dependency source bytes in a private fresh workspace without live caches"
        ),
        "family": "spacecraft-finite-burn-model-conditional-v2",
        "lane": "spacecraft-burn",
        "model_id": model_id,
        "parser_definition": "JackalIv.Spacecraft.parseBurnWitness",
        "premises_not_discharged_by_checker": [],
        "release_epoch": epoch,
        "request_digest": request_digest,
        "runtime_alternate_implementation_boundary": (
            "none in the local source closure; no native_decide or implemented_by"
        ),
        "soundness_theorem": "JackalIv.Spacecraft.spacecraft_burn_certified_safe",
        "theorem_premises": [
            "checkBurnCert raw requestDigest modelId epoch = .ok accepted (runtime checked)"
        ],
    }
    if first_difference(expected_fragment, document.get("fragment")) is not None:
        reasons.append("proof-identity-fragment-mismatch")

    proof = document.get("proof")
    if type(proof) is not dict or set(proof) != {
        "axiom_audit_command", "axiom_policy", "theorems"
    }:
        reasons.append("proof-identity-axiom-policy-mismatch")
    else:
        expected_policy = {
            "allowed_exactly": ALLOWED_AXIOMS,
            "forbidden": ["sorryAx", "any additional axiom"],
        }
        theorem_rows = proof.get("theorems")
        expected_theorem_rows = [
            {"axioms": ALLOWED_AXIOMS, "theorem": theorem}
            for theorem in EXPECTED_PROOF_THEOREMS
        ]
        if (
            proof.get("axiom_audit_command")
            != "lake env lean /dev/stdin with checked-in #print axioms set"
            or first_difference(expected_policy, proof.get("axiom_policy")) is not None
            or first_difference(expected_theorem_rows, theorem_rows) is not None
        ):
            reasons.append("proof-identity-axiom-policy-mismatch")

    closure = document.get("source_closure")
    closure_keys = {
        "aggregate_sha256",
        "definition",
        "external_imports",
        "files",
        "local_construct_policy",
        "root_modules",
    }
    if type(closure) is not dict or set(closure) != closure_keys:
        reasons.append("proof-identity-source-closure-mismatch")
        return
    closure_payload = {
        "external_imports": closure.get("external_imports"),
        "files": closure.get("files"),
        "root_modules": closure.get("root_modules"),
    }
    aggregate = hashlib.sha256(canonical_json_bytes(closure_payload)).hexdigest()
    expected_construct_policy = {
        "allowed_exact_source_lines": [],
        "forbidden_by_default": [
            "admit", "axiom_declaration", "extern", "implemented_by",
            "native_decide", "partial", "sorry", "unsafe",
        ],
    }
    if (
        closure.get("aggregate_sha256") != aggregate
        or closure.get("root_modules") != ["JackalIv.Spacecraft.CertMain"]
        or closure.get("definition")
        != (
            "Every repository-local transitive Lean import reachable from root_modules; "
            "external imports are bound through lake-manifest.json and named here."
        )
        or first_difference(
            expected_construct_policy, closure.get("local_construct_policy")
        )
        is not None
        or type(closure.get("external_imports")) is not list
        or not all(type(item) is str for item in closure["external_imports"])
    ):
        reasons.append("proof-identity-source-closure-mismatch")
    files = closure.get("files")
    if type(files) is not list or not files:
        reasons.append("proof-identity-source-closure-mismatch")
    else:
        observed_paths: set[str] = set()
        observed_modules: set[str] = set()
        observed_imports_by_module: dict[str, list[str]] = {}
        for row in files:
            if type(row) is not dict or set(row) != {
                "bytes", "imports", "module", "path", "sha256"
            }:
                reasons.append("proof-identity-source-closure-mismatch")
                break
            recorded_path = row.get("path")
            module = row.get("module")
            expected_path = (
                "proofs/lean/" + module.replace(".", "/") + ".lean"
                if type(module) is str
                else None
            )
            try:
                source_raw = (
                    read_identity_bound_snapshot(
                        path,
                        recorded_path,
                        MAX_SOURCE_BYTES,
                        source_root,
                        source=source,
                    )
                    if type(recorded_path) is str
                    else None
                )
            except (OSError, RuntimeError, ValueError):
                source_raw = None
            if (
                type(recorded_path) is not str
                or recorded_path != expected_path
                or recorded_path in observed_paths
                or module in observed_modules
                or type(row.get("imports")) is not list
                or not all(type(item) is str for item in row["imports"])
                or type(row.get("bytes")) is not int
                or row["bytes"] < 0
                or type(row.get("sha256")) is not str
                or source_raw is None
            ):
                reasons.append("proof-identity-source-closure-mismatch")
                break
            raw = source_raw
            if len(raw) != row["bytes"] or hashlib.sha256(raw).hexdigest() != row["sha256"]:
                reasons.append("proof-identity-source-closure-mismatch")
                break
            try:
                code = lean_code_without_comments_or_strings(raw.decode("utf-8"))
            except (UnicodeDecodeError, ValueError):
                reasons.append("proof-identity-source-closure-mismatch")
                break
            try:
                imports = parse_lean_imports(code)
            except ValueError:
                reasons.append("proof-identity-source-closure-mismatch")
                break
            if imports != row["imports"] or has_forbidden_lean_construct(code):
                reasons.append("proof-identity-source-closure-mismatch")
                break
            observed_paths.add(recorded_path)
            observed_modules.add(module)
            observed_imports_by_module[module] = imports
        if len(observed_modules) == len(files):
            pending = ["JackalIv.Spacecraft.CertMain"]
            reached: set[str] = set()
            external: set[str] = set()
            while pending:
                module = pending.pop()
                if module in reached:
                    continue
                if module not in observed_imports_by_module:
                    reasons.append("proof-identity-source-closure-mismatch")
                    break
                reached.add(module)
                for imported in observed_imports_by_module[module]:
                    if imported in observed_imports_by_module:
                        pending.append(imported)
                    elif repository_local_lean_module_exists(
                        path, imported, source_root, source=source
                    ):
                        reasons.append("proof-identity-source-closure-mismatch")
                        break
                    else:
                        external.add(imported)
            if (
                reached != observed_modules
                or sorted(external) != closure.get("external_imports")
            ):
                reasons.append("proof-identity-source-closure-mismatch")

    generator = document.get("generator")
    expected_generator_paths = (
        "release/tools/spacecraft_burn_proof_identity.py",
        "release/tools/gaussian_proof_identity.py",
    )
    if type(generator) is not dict or set(generator) != {"definition", "files"}:
        reasons.append("proof-identity-generator-mismatch")
    else:
        generator_files = generator.get("files")
        valid_generator = (
            generator.get("definition")
            == (
                "Complete repository-local Python generator source closure used to construct "
                "and verify this identity. The interpreter and standard library remain in "
                "the explicit build-platform trusted base."
            )
            and type(generator_files) is list
            and len(generator_files) == len(expected_generator_paths)
        )
        if valid_generator:
            for row, expected_path in zip(generator_files, expected_generator_paths):
                try:
                    generator_raw = (
                        read_identity_bound_snapshot(
                            path,
                            row.get("path"),
                            MAX_SOURCE_BYTES,
                            source_root,
                            source=source,
                        )
                        if type(row) is dict and type(row.get("path")) is str
                        else None
                    )
                    observed_generator_digest = (
                        hashlib.sha256(generator_raw).hexdigest()
                        if generator_raw is not None
                        else None
                    )
                except (OSError, RuntimeError, ValueError):
                    generator_raw = None
                    observed_generator_digest = None
                if (
                    type(row) is not dict
                    or set(row) != {"path", "sha256"}
                    or row.get("path") != expected_path
                    or not valid_lower_hex_digest(row.get("sha256"))
                    or generator_raw is None
                    or observed_generator_digest != row["sha256"]
                ):
                    valid_generator = False
                    break
        if not valid_generator:
            reasons.append("proof-identity-generator-mismatch")

    toolchain = document.get("toolchain")
    toolchain_keys = {
        "configuration_files",
        "lake_version",
        "lean",
        "lean_toolchain",
        "manifest_packages",
        "mathlib_commit",
        "package_checkout_policy",
        "verified_package_trees",
    }
    toolchain_valid = type(toolchain) is dict and set(toolchain) == toolchain_keys
    expected_configurations = []
    configuration_raw: dict[str, bytes] = {}
    for recorded_path in (
        "proofs/lean/lakefile.toml",
        "proofs/lean/lake-manifest.json",
        "proofs/lean/lean-toolchain",
    ):
        try:
            raw = read_identity_bound_snapshot(
                path,
                recorded_path,
                MAX_SOURCE_BYTES,
                source_root,
                source=source,
            )
        except (OSError, RuntimeError, ValueError):
            raw = None
        if raw is None:
            toolchain_valid = False
            continue
        configuration_raw[recorded_path] = raw
        expected_configurations.append({
            "path": recorded_path,
            "sha256": hashlib.sha256(raw).hexdigest(),
        })
    if toolchain_valid:
        lean = toolchain.get("lean")
        toolchain_name = toolchain.get("lean_toolchain")
        try:
            manifest = strict_json_bytes(
                configuration_raw["proofs/lean/lake-manifest.json"]
            )
            packages = normalized_manifest_packages(manifest)
            toolchain_token = configuration_raw[
                "proofs/lean/lean-toolchain"
            ].decode("utf-8").strip()
        except (KeyError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
            packages = None
            toolchain_token = ""
        mathlib = (
            [row for row in packages if row["name"] == "mathlib"]
            if packages is not None
            else []
        )
        git_packages = (
            [row for row in packages if row["type"] == "git"]
            if packages is not None
            else []
        )
        verified_package_trees = toolchain.get("verified_package_trees")
        verified_trees_valid = (
            type(verified_package_trees) is list
            and len(verified_package_trees) == len(git_packages)
        )
        if verified_trees_valid:
            for recorded, package in zip(verified_package_trees, git_packages):
                if (
                    type(recorded) is not dict
                    or set(recorded) != {
                        "entry_count", "name", "revision", "tree_sha1",
                        "verified_worktree_sha256",
                    }
                    or recorded.get("name") != package["name"]
                    or recorded.get("revision") != package["revision"]
                    or type(recorded.get("entry_count")) is not int
                    or recorded["entry_count"] <= 0
                    or not valid_lower_hex_digest(
                        recorded.get("tree_sha1"), length=40
                    )
                    or not valid_lower_hex_digest(
                        recorded.get("verified_worktree_sha256")
                    )
                ):
                    verified_trees_valid = False
                    break
        toolchain_valid = (
            first_difference(
                expected_configurations, toolchain.get("configuration_files")
            )
            is None
            and first_difference(
                PINNED_TOOLCHAIN_CONFIGURATIONS, expected_configurations
            )
            is None
            and type(lean) is dict
            and set(lean) == {"build", "commit", "version"}
            and all(type(lean[key]) is str and lean[key] for key in lean)
            and valid_lower_hex_digest(lean["commit"], length=40)
            and type(toolchain_name) is str
            and toolchain_name == toolchain_token
            and toolchain_name == f"leanprover/lean4:v{lean['version']}"
            and type(toolchain.get("lake_version")) is str
            and f"Lean version {lean['version']}" in toolchain["lake_version"]
            and first_difference(packages, toolchain.get("manifest_packages")) is None
            and len(mathlib) == 1
            and toolchain.get("mathlib_commit") == mathlib[0]["revision"]
            and verified_trees_valid
            and toolchain.get("package_checkout_policy")
            == (
                "Every git dependency is pinned to a full commit; replacement refs, "
                "grafts, alternates, index hiding flags, object corruption, and "
                "tracked-byte drift are rejected. Tracked symlinks must remain lexically "
                "confined to real package paths. Identity generation admits only open-once "
                "snapshots of tracked dependency bytes into a private fresh workspace and "
                "rebuilds without live caches."
            )
        )
    if not toolchain_valid:
        reasons.append("proof-identity-toolchain-mismatch")

    attestation = document.get("build_attestation")
    attestation_keys = {
        "attestation_digest_sha256",
        "authentication",
        "build_command",
        "build_environment",
        "checker",
        "claim_boundary",
        "compiler_observed_for_build_platform",
        "inputs",
        "kind",
        "working_directory",
    }
    attestation_valid = type(attestation) is dict and set(attestation) == attestation_keys
    if attestation_valid:
        lean_record = (
            toolchain.get("lean")
            if type(toolchain) is dict and type(toolchain.get("lean")) is dict
            else {}
        )
        attestation_body = {
            key: value for key, value in attestation.items()
            if key != "attestation_digest_sha256"
        }
        inputs = attestation.get("inputs")
        compiler = attestation.get("compiler_observed_for_build_platform")
        authentication = attestation.get("authentication")
        build_environment = attestation.get("build_environment")
        dependency_overrides = (
            build_environment.get("dependency_path_overrides")
            if type(build_environment) is dict
            else None
        )
        recorded_manifest_packages_value = (
            toolchain.get("manifest_packages", [])
            if type(toolchain) is dict
            else None
        )
        recorded_manifest_packages_valid = type(recorded_manifest_packages_value) is list
        recorded_manifest_packages = (
            recorded_manifest_packages_value
            if recorded_manifest_packages_valid
            else []
        )
        try:
            expected_override_names = [row["name"] for row in recorded_manifest_packages]
            expected_override_sha256 = hashlib.sha256(
                private_dependency_override_bytes(recorded_manifest_packages)
            ).hexdigest()
        except (KeyError, TypeError, ValueError):
            expected_override_names = None
            expected_override_sha256 = None
        dependency_overrides_valid = (
            recorded_manifest_packages_valid
            and type(dependency_overrides) is dict
            and set(dependency_overrides)
            == {"definition", "package_count", "package_names", "sha256"}
            and dependency_overrides.get("definition")
            == (
                "Deterministic Lake path overrides that force every manifest-pinned Git "
                "dependency to load only from its already verified private tracked-blob "
                "snapshot."
            )
            and dependency_overrides.get("package_count")
            == len(recorded_manifest_packages)
            and dependency_overrides.get("package_names")
            == expected_override_names
            and valid_lower_hex_digest(dependency_overrides.get("sha256"))
            and dependency_overrides.get("sha256") == expected_override_sha256
        )
        lake_bookkeeping = (
            build_environment.get("lake_generated_bookkeeping")
            if type(build_environment) is dict
            else None
        )
        lake_bookkeeping_valid = (
            first_difference(
                EXPECTED_LAKE_GENERATED_BOOKKEEPING,
                lake_bookkeeping,
            )
            is None
        )
        launchers = (
            build_environment.get("lean_launcher_binaries")
            if type(build_environment) is dict
            else None
        )
        launchers_valid = (
            type(launchers) is list
            and [row.get("name") if type(row) is dict else None for row in launchers]
            == ["lake", "lean", "leanc"]
        )
        if launchers_valid:
            for row in launchers:
                if (
                    set(row) != {"bytes", "name", "sha256"}
                    or type(row.get("bytes")) is not int
                    or row["bytes"] <= 0
                    or not valid_lower_hex_digest(row.get("sha256"))
                ):
                    launchers_valid = False
                    break
        toolchain_tree = (
            build_environment.get("lean_toolchain_tree")
            if type(build_environment) is dict
            else None
        )
        recorded_toolchain_name = (
            toolchain.get("lean_toolchain") if type(toolchain) is dict else None
        )
        tree_valid = (
            type(toolchain_tree) is dict
            and set(toolchain_tree)
            == {
                "aggregate_sha256",
                "definition",
                "directory_count",
                "directory_name",
                "entry_count",
                "file_count",
                "lean_toolchain",
                "total_bytes",
            }
            and valid_lower_hex_digest(toolchain_tree.get("aggregate_sha256"))
            and toolchain_tree.get("definition")
            == (
                "SHA-256 aggregate over every relative directory path/mode and regular "
                "file path/mode/size/SHA-256 in the private Lean toolchain snapshot; "
                "symlinks and special files are forbidden."
            )
            and all(
                type(toolchain_tree.get(key)) is int and toolchain_tree[key] > 0
                for key in ("directory_count", "entry_count", "file_count", "total_bytes")
            )
            and toolchain_tree.get("entry_count")
            == toolchain_tree.get("directory_count", 0) + toolchain_tree.get("file_count", 0)
            and toolchain_tree.get("lean_toolchain") == recorded_toolchain_name
            and toolchain_tree.get("directory_name")
            == str(recorded_toolchain_name or "").replace("/", "--").replace(":", "---")
        )
        platform_launchers = (
            build_environment.get("trusted_platform_launchers")
            if type(build_environment) is dict
            else None
        )
        platform_launchers_valid = trusted_platform_launchers_valid(
            platform_launchers
        )
        expected_inputs = {
            "lean_commit": lean_record.get("commit"),
            "mathlib_commit": toolchain.get("mathlib_commit")
            if type(toolchain) is dict
            else None,
            "source_closure_sha256": closure.get("aggregate_sha256"),
            "toolchain_configuration": expected_configurations,
        }
        attestation_valid = (
            hashlib.sha256(canonical_json_bytes(attestation_body)).hexdigest()
            == attestation.get("attestation_digest_sha256")
            and first_difference(checker, attestation.get("checker")) is None
            and first_difference(expected_inputs, inputs) is None
            and type(compiler) is dict
            and set(compiler)
            == {
                "build", "commit", "executable_bytes", "executable_sha256",
                "target", "version",
            }
            and type(compiler.get("executable_bytes")) is int
            and compiler["executable_bytes"] > 0
            and valid_lower_hex_digest(compiler.get("executable_sha256"))
            and all(
                compiler.get(key) == lean_record.get(key)
                for key in ("build", "commit", "version")
            )
            and type(build_environment) is dict
            and set(build_environment)
            == {
                "dependency_path_overrides",
                "isolation_policy",
                "lake_generated_bookkeeping",
                "lean_launcher_binaries",
                "lean_toolchain_tree",
                "trusted_platform_launchers",
            }
            and build_environment.get("isolation_policy")
            == EXPECTED_BUILD_ISOLATION_POLICY
            and dependency_overrides_valid
            and lake_bookkeeping_valid
            and launchers_valid
            and launchers[1]["bytes"] == compiler["executable_bytes"]
            and launchers[1]["sha256"] == compiler["executable_sha256"]
            and tree_valid
            and platform_launchers_valid
            and type(compiler.get("target")) is str
            and bool(compiler["target"])
            and authentication
            == {
                "authenticated": False,
                "scheme": "none",
                "statement": (
                    "This deterministic record binds observed checker bytes to named inputs. "
                    "It is not a signature and does not authenticate the builder or artifact."
                ),
            }
            and attestation.get("build_command")
            == ["lake", "build", "jackal_spacecraft_burn_check"]
            and attestation.get("kind") == "unsigned-local-build-binding-v1"
            and attestation.get("working_directory") == "proofs/lean"
            and attestation.get("claim_boundary")
            == (
                "This binds the complete private Lean toolchain regular-file tree, admitted "
                "source and dependency bytes, observed checker bytes, and named platform "
                "launchers. It is reproducibility/build-provenance evidence, not a proof of "
                "Python, Git, macOS, sandbox-exec, dyld, libSystem, the kernel, hardware, or "
                "supply-chain correctness."
            )
        )
    if not attestation_valid:
        reasons.append("proof-identity-build-attestation-mismatch")


def validate_identity_semantics(
    document: dict,
    path: Path,
    *,
    checker_digest: str,
    checker_size: int | None,
    request_digest: str,
    model_id: str,
    epoch: str,
    reasons: list[str],
    source_root: Path | None = None,
) -> None:
    try:
        with IdentityBoundSource(path, source_root) as source:
            _validate_identity_semantics(
                document,
                path,
                checker_digest=checker_digest,
                checker_size=checker_size,
                request_digest=request_digest,
                model_id=model_id,
                epoch=epoch,
                reasons=reasons,
                source_root=source_root,
                source=source,
            )
    except (OSError, RuntimeError, ValueError):
        for reason in (
            "proof-identity-source-closure-mismatch",
            "proof-identity-generator-mismatch",
            "proof-identity-toolchain-mismatch",
        ):
            if reason not in reasons:
                reasons.append(reason)


def verify_identity_file(
    path: Path, expected_file_digest: str, expected_internal_digest: str,
    checker_digest: str, request_digest: str, model_id: str, epoch: str,
    reasons: list[str], raw: bytes | None = None, checker_size: int | None = None,
    source_root: Path | None = None,
) -> str | None:
    try:
        raw = read_regular_snapshot(path, MAX_IDENTITY_BYTES) if raw is None else raw
        document = strict_json_bytes(raw)
    except (
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        DuplicateJsonKey,
        ValueError,
    ):
        reasons.append("proof-identity-invalid")
        return None
    file_digest = hashlib.sha256(raw).hexdigest()
    if file_digest != expected_file_digest:
        reasons.append("proof-identity-file-hash-mismatch")
    if not isinstance(document, dict):
        reasons.append("proof-identity-invalid")
        return file_digest
    recorded_internal = document.get("identity_digest_sha256")
    body = {key: value for key, value in document.items() if key != "identity_digest_sha256"}
    actual_internal = hashlib.sha256(canonical_json_bytes(body)).hexdigest()
    if (
        recorded_internal != actual_internal
        or recorded_internal != expected_internal_digest
    ):
        reasons.append("proof-identity-internal-digest-mismatch")
    validate_identity_semantics(
        document,
        path,
        checker_digest=checker_digest,
        checker_size=checker_size,
        request_digest=request_digest,
        model_id=model_id,
        epoch=epoch,
        reasons=reasons,
        source_root=source_root,
    )
    return file_digest


def run_checker_snapshot(
    checker_bytes: bytes,
    witness_bytes: bytes,
    request_digest: str,
    model_id: str,
    epoch: str,
    timeout: int,
) -> subprocess.CompletedProcess[str]:
    environment = {"LANG": "C", "LC_ALL": "C", "PATH": "/usr/bin:/bin"}
    with tempfile.TemporaryDirectory(prefix="jackal-checker-snapshot-") as directory:
        private = Path(directory)
        checker = private / "jackal_spacecraft_burn_check"
        witness = private / "witness.cert"
        write_output_atomic(checker, checker_bytes)
        write_output_atomic(witness, witness_bytes)
        checker.chmod(0o700)
        witness.chmod(0o600)
        return subprocess.run(
            [str(checker), str(witness), request_digest, model_id, epoch],
            cwd=private,
            env=environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )


def verify_formal_binding(
    candidate: dict,
    receipt_path: Path,
    *,
    witness_path: Path | None,
    checker_path: Path | None,
    proof_identity_path: Path | None,
    expected_receipt_sha256: str | None,
    expected_proof_file_sha256: str | None,
    expected_proof_identity_sha256: str | None,
    expected_request_digest: str | None,
    expected_model_id: str | None,
    expected_epoch: str | None,
    nonce: str | None,
    receipt_bytes: bytes | None = None,
    proof_source_root: Path | None = None,
) -> tuple[list[str], dict[str, object]]:
    pins = (
        witness_path, checker_path, proof_identity_path, expected_receipt_sha256,
        expected_proof_file_sha256, expected_proof_identity_sha256,
        expected_request_digest, expected_model_id, expected_epoch, nonce,
    )
    if any(value is None for value in pins):
        return ["caller-pins-required"], {}
    assert witness_path is not None and checker_path is not None
    assert proof_identity_path is not None and expected_receipt_sha256 is not None
    assert expected_proof_file_sha256 is not None
    assert expected_proof_identity_sha256 is not None
    assert expected_request_digest is not None and expected_model_id is not None
    assert expected_epoch is not None and nonce is not None

    reasons: list[str] = []
    try:
        receipt_bytes = receipt_path.read_bytes() if receipt_bytes is None else receipt_bytes
    except OSError:
        return ["receipt-unreadable"], {}
    receipt_digest = hashlib.sha256(receipt_bytes).hexdigest()
    if receipt_digest != expected_receipt_sha256:
        reasons.append("receipt-hash-mismatch")
    try:
        witness_bytes = read_regular_snapshot(witness_path, MAX_WITNESS_BYTES)
        checker_bytes = read_regular_snapshot(checker_path, MAX_CHECKER_BYTES)
        proof_identity_bytes = read_regular_snapshot(
            proof_identity_path, MAX_IDENTITY_BYTES
        )
    except (OSError, ValueError):
        return ["binding-input-unreadable"], {}
    witness_digest = hashlib.sha256(witness_bytes).hexdigest()
    checker_digest = hashlib.sha256(checker_bytes).hexdigest()
    proof_file_digest = verify_identity_file(
        proof_identity_path, expected_proof_file_sha256,
        expected_proof_identity_sha256, checker_digest, expected_request_digest,
        expected_model_id, expected_epoch, reasons, raw=proof_identity_bytes,
        checker_size=len(checker_bytes),
        source_root=proof_source_root,
    )

    binding = candidate.get("formal_checker")
    if not isinstance(binding, dict):
        reasons.append("formal-checker-binding-invalid")
        return sorted(set(reasons)), {}
    expected_fields = {
        "checker_sha256": checker_digest,
        "proof_identity_file_sha256": expected_proof_file_sha256,
        "proof_identity_digest_sha256": expected_proof_identity_sha256,
        "witness_sha256": witness_digest,
        "request_digest": expected_request_digest,
        "model_id": expected_model_id,
        "epoch": expected_epoch,
        "nonce": nonce,
        "theorem": "spacecraft_burn_certified_safe",
    }
    if set(binding) != {*expected_fields, "result_line"}:
        reasons.append("formal-checker-binding-invalid")
    reason_by_field = {
        "checker_sha256": "checker-hash-mismatch",
        "proof_identity_file_sha256": "proof-identity-file-hash-mismatch",
        "proof_identity_digest_sha256": "proof-identity-internal-digest-mismatch",
        "witness_sha256": "witness-hash-mismatch",
        "request_digest": "request-digest-mismatch",
        "model_id": "model-id-mismatch",
        "epoch": "release-epoch-mismatch",
        "nonce": "nonce-mismatch",
        "theorem": "theorem-name-mismatch",
    }
    for field, expected in expected_fields.items():
        if binding.get(field) != expected:
            reasons.append(reason_by_field[field])
    if candidate.get("verdict_qualifier") != MODEL_QUALIFIER:
        reasons.append("verdict-qualifier-mismatch")
    result_line = binding.get("result_line")
    formal_margin = (
        checker_acceptance_margin(result_line, expected_model_id, expected_epoch)
        if isinstance(result_line, str)
        else None
    )
    if formal_margin is None:
        reasons.append("checker-result-line-invalid")
    if reasons:
        return sorted(set(reasons)), {}

    try:
        completed = run_checker_snapshot(
            checker_bytes, witness_bytes, expected_request_digest,
            expected_model_id, expected_epoch, 180,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ["checker-execution-failed"], {}
    if completed.returncode != 0:
        reasons.append("checker-refused")
    if completed.stderr:
        reasons.append("checker-stderr")
    if completed.stdout != result_line + "\n":
        reasons.append("checker-result-mismatch")
    digests = {
        "receipt_sha256": receipt_digest,
        "witness_sha256": witness_digest,
        "witness_byte_size": len(witness_bytes),
        "checker_sha256": checker_digest,
        "proof_identity_file_sha256": proof_file_digest or "",
        "checker_result_line": result_line,
        "formal_margin_lo": formal_margin[0],
        "formal_margin_hi": formal_margin[1],
    }
    return sorted(set(reasons)), digests


def verify_receipt(
    receipt_path: Path | str,
    source_path: Path | str,
    *,
    request_path: Path | str | None = None,
    witness_path: Path | str | None = None,
    checker_path: Path | str | None = None,
    proof_identity_path: Path | str | None = None,
    expected_receipt_sha256: str | None = None,
    expected_proof_file_sha256: str | None = None,
    expected_proof_identity_sha256: str | None = None,
    expected_request_digest: str | None = None,
    expected_model_id: str | None = None,
    expected_epoch: str | None = None,
    nonce: str | None = None,
) -> dict:
    raw_receipt_path = Path(receipt_path)
    raw_source_path = Path(source_path)
    if "\0" in os.fspath(raw_source_path):
        return {"status": "REFUSED", "reasons": ["invalid-producer-source"]}
    caller_paths = (
        (raw_receipt_path, "receipt-unreadable"),
        (raw_source_path, "invalid-producer-source"),
        (request_path, "request-file-invalid"),
        (witness_path, "witness-unreadable"),
        (checker_path, "checker-unreadable"),
        (proof_identity_path, "proof-identity-invalid"),
    )
    symlink_reasons = []
    for value, reason in caller_paths:
        if value is None:
            continue
        try:
            if Path(value).is_symlink():
                symlink_reasons.append(reason)
        except (OSError, RuntimeError, TypeError, ValueError):
            symlink_reasons.append(reason)
    if symlink_reasons:
        return {"status": "REFUSED", "reasons": sorted(set(symlink_reasons))}
    receipt_path = raw_receipt_path.absolute()
    source_path = raw_source_path.absolute()
    try:
        proof_source_root = source_path.parent.parent.resolve(strict=True)
    except (OSError, RuntimeError, ValueError):
        return {"status": "REFUSED", "reasons": ["invalid-producer-source"]}
    reasons: list[str] = []
    try:
        receipt_bytes = read_regular_snapshot(receipt_path, MAX_RECEIPT_BYTES)
        candidate = strict_json_bytes(receipt_bytes)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, DuplicateJsonKey, ValueError):
        return {"status": "REFUSED", "reasons": ["invalid-receipt-json"]}
    if not isinstance(candidate, dict):
        return {"status": "REFUSED", "reasons": ["invalid-receipt-schema"]}
    schema = candidate.get("schema")
    if schema == "spacecraft-finite-burn-interval-receipt-v1":
        return {"status": "REFUSED", "reasons": ["legacy-unproved-verdict-schema"]}
    if schema != "spacecraft-finite-burn-formal-receipt-v2":
        return {"status": "REFUSED", "reasons": ["invalid-receipt-schema"]}
    if candidate.get("formal_checker_status") != "ACCEPT":
        return {"status": "REFUSED", "reasons": ["formal-checker-not-bound"]}
    for field, reason in (
        ("method", "invalid-method-section"),
        ("cutoff_state_hull", "invalid-cutoff-state-hull"),
        ("orbital_hulls", "invalid-orbital-hulls"),
    ):
        if not isinstance(candidate.get(field), dict):
            return {"status": "REFUSED", "reasons": [reason]}
    if set(candidate) != RECEIPT_TOP_LEVEL_KEYS:
        return {"status": "REFUSED", "reasons": ["invalid-receipt-schema"]}
    if request_path is None:
        return {"status": "REFUSED", "reasons": ["caller-pins-required"]}
    resolved_request = Path(request_path).absolute()
    try:
        request_bytes = read_regular_snapshot(resolved_request, MAX_REQUEST_BYTES)
        request_document = strict_json_bytes(request_bytes)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, DuplicateJsonKey, ValueError):
        return {"status": "REFUSED", "reasons": ["request-file-invalid"]}
    if expected_request_digest is None or hashlib.sha256(request_bytes).hexdigest() != expected_request_digest:
        return {"status": "REFUSED", "reasons": ["request-file-hash-mismatch"]}
    if first_difference(EXPECTED_REQUEST, request_document) is not None:
        return {"status": "REFUSED", "reasons": ["request-schema-mismatch"]}

    formal_reasons, formal_digests = verify_formal_binding(
        candidate,
        receipt_path,
        witness_path=None if witness_path is None else Path(witness_path).absolute(),
        checker_path=None if checker_path is None else Path(checker_path).absolute(),
        proof_identity_path=None if proof_identity_path is None else Path(proof_identity_path).absolute(),
        expected_receipt_sha256=expected_receipt_sha256,
        expected_proof_file_sha256=expected_proof_file_sha256,
        expected_proof_identity_sha256=expected_proof_identity_sha256,
        expected_request_digest=expected_request_digest,
        expected_model_id=expected_model_id,
        expected_epoch=expected_epoch,
        nonce=nonce,
        receipt_bytes=receipt_bytes,
        proof_source_root=proof_source_root,
    )
    if formal_reasons:
        return {"status": "REFUSED", "reasons": formal_reasons}

    try:
        source_raw = read_regular_snapshot(source_path, MAX_SOURCE_BYTES)
        literals = source_literals(source_raw, source_path)
    except (OSError, UnicodeDecodeError, SyntaxError, ValueError):
        return {"status": "REFUSED", "reasons": ["invalid-producer-source"]}
    for name, (required, reason) in CONTRACT.items():
        if literals.get(name) != required:
            reasons.append(reason)
    source_digest = hashlib.sha256(source_raw).hexdigest()
    if candidate.get("source_sha256") != source_digest:
        reasons.append("source-hash-mismatch")

    if first_difference(EXPECTED_MODEL_CONTRACT, candidate.get("model_contract")) is not None:
        reasons.append("model-contract-mismatch")
    identities = verify_symbolic_identities()
    if not identities or not all(identities.values()):
        reasons.append("symbolic-orbital-identity-failure")

    if reasons:
        return {"status": "REFUSED", "reasons": sorted(set(reasons)), "symbolic_identities": identities}

    expected = replay()
    if (
        expected["canonical_witness_sha256"] != formal_digests["witness_sha256"]
        or expected["canonical_witness_byte_size"]
        != formal_digests["witness_byte_size"]
    ):
        reasons.append("witness-not-canonical-replay")
    formal_margin = (
        int(formal_digests["formal_margin_lo"]),
        int(formal_digests["formal_margin_hi"]),
    )
    if not formal_margin_matches_replay(formal_margin, expected):
        reasons.append("formal-margin-replay-mismatch")
    replayed_formal_margin = expected["post"]["margin_intersection"]
    formula_exact = frac_text(Fraction(expected["minimum_formula_lo"], DEN))
    expected_lower = Fraction(expected["minimum_cell"][0], DEN)
    assert expected_proof_identity_sha256 is not None
    assert expected_request_digest is not None and expected_model_id is not None
    assert expected_epoch is not None and nonce is not None
    expected_document = expected_receipt_document(
        expected,
        source_digest=source_digest,
        witness_digest=str(formal_digests["witness_sha256"]),
        witness_byte_size=int(formal_digests["witness_byte_size"]),
        checker_digest=str(formal_digests["checker_sha256"]),
        proof_file_digest=str(formal_digests["proof_identity_file_sha256"]),
        proof_identity_digest=expected_proof_identity_sha256,
        request_digest=expected_request_digest,
        model_id=expected_model_id,
        epoch=expected_epoch,
        nonce=nonce,
        result_line=str(formal_digests["checker_result_line"]),
        formal_margin=replayed_formal_margin,
    )
    receipt_difference = first_difference(expected_document, candidate)
    if receipt_difference is not None:
        reasons.append(f"receipt-document-mismatch:{receipt_difference}")

    return {
        "status": "ACCEPT" if not reasons else "REFUSED",
        "reasons": sorted(set(reasons)),
        "binding": {
            **formal_digests,
            "proof_identity_digest_sha256": expected_proof_identity_sha256,
            "request_digest": expected_request_digest,
            "model_id": expected_model_id,
            "epoch": expected_epoch,
            "nonce": nonce,
        },
        "symbolic_identities": identities,
        "replay": {
            "trace_sha256": expected["trace_sha256"],
            "exact_lower_bound": frac_text(expected_lower),
            "formula_only_exact_lower_bound": formula_exact,
            "domain_lower_bounds": expected["domain_lower_bounds"],
        },
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("receipt", type=Path)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--witness", type=Path, required=True)
    parser.add_argument("--checker", type=Path, required=True)
    parser.add_argument("--proof-identity", type=Path, required=True)
    parser.add_argument("--expected-receipt-sha256", required=True)
    parser.add_argument("--expected-proof-file-sha256", required=True)
    parser.add_argument("--expected-proof-identity-sha256", required=True)
    parser.add_argument("--expected-request-digest", required=True)
    parser.add_argument("--expected-model-id", required=True)
    parser.add_argument("--expected-epoch", required=True)
    parser.add_argument("--nonce", required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    input_paths = (
        args.receipt,
        args.source,
        args.request,
        args.witness,
        args.checker,
        args.proof_identity,
    )
    destination: Path | None = None
    if args.output is not None:
        try:
            destination = prepare_output_path(args.output, input_paths)
        except ValueError as error:
            parser.error(str(error))
    result = verify_receipt(
        args.receipt, args.source,
        request_path=args.request,
        witness_path=args.witness,
        checker_path=args.checker,
        proof_identity_path=args.proof_identity,
        expected_receipt_sha256=args.expected_receipt_sha256,
        expected_proof_file_sha256=args.expected_proof_file_sha256,
        expected_proof_identity_sha256=args.expected_proof_identity_sha256,
        expected_request_digest=args.expected_request_digest,
        expected_model_id=args.expected_model_id,
        expected_epoch=args.expected_epoch,
        nonce=args.nonce,
    )
    rendered = json.dumps(result, sort_keys=True, indent=2) + "\n"
    if destination is not None:
        destination = write_output_atomic_bound(
            destination, rendered.encode("utf-8"), input_paths
        )
        print(f"INDEPENDENT_VERIFICATION_{result['status']} output={destination}")
    else:
        print(rendered, end="")
    return 0 if result["status"] == "ACCEPT" else 2


if __name__ == "__main__":
    raise SystemExit(main())
