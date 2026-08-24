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
import subprocess
import tempfile
from fractions import Fraction
from pathlib import Path
from typing import Iterable, Sequence


BITS = 80
DEN = 1 << BITS
Interval = tuple[int, int]
Box = tuple[Interval, ...]


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
O = point(1)
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
    e2 = add(O, div(mul(mul(TWO, energy), sq(momentum)), sq(MU)))
    eccentricity = root(e2)

    radial_dot = add(mul(x, vx), mul(y, vy))
    common = sub(v2, div(MU, radius))
    ex = div(sub(mul(common, x), mul(radial_dot, vx)), MU)
    ey = div(sub(mul(common, y), mul(radial_dot, vy)), MU)
    ev2 = add(sq(ex), sq(ey))
    ev = root(ev2)
    e = meet(eccentricity, ev)
    apo_formula = mul(semimajor, add(O, eccentricity))
    apo = mul(semimajor, add(O, e))
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


def replay() -> dict:
    digest = hashlib.sha256()
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
    for branch_id, (initial, thrust) in enumerate(arms):
        state = initial
        for index in range(TOTAL_STEPS):
            tube, endpoint, iterations = step(state, thrust)
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
    }


def frac_text(q: Fraction) -> str:
    return str(q.numerator) if q.denominator == 1 else f"{q.numerator}/{q.denominator}"


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

    variables3 = 4
    speed2, radius, axis3, mu = (poly_var(i, variables3) for i in range(variables3))
    two = poly_const(2, variables3)
    cleared_vis_viva = poly_add(
        poly_sub(
            poly_mul(poly_mul(axis3, radius), speed2),
            poly_mul(poly_mul(two, axis3), mu),
        ),
        poly_mul(mu, radius),
    )
    factored_vis_viva = poly_add(
        poly_mul(axis3, poly_sub(poly_mul(radius, speed2), poly_mul(two, mu))),
        poly_mul(mu, radius),
    )

    variables4 = 2
    axis, eccentricity = (poly_var(i, variables4) for i in range(variables4))
    apo = poly_mul(axis, poly_add(poly_const(1, variables4), eccentricity))
    apo_expanded = poly_add(axis, poly_mul(axis, eccentricity))
    return {
        "angular_momentum_lagrange_identity": not lagrange,
        "eccentricity_vector_reduction": not poly_sub(poly_sub(raw, target), factored),
        "vis_viva_cleared_denominator_expansion": not poly_sub(
            cleared_vis_viva, factored_vis_viva
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
        lo = int(payload["lo_scaled_integer"])
        hi = int(payload["hi_scaled_integer"])
        if lo > hi:
            raise ValueError
        if Fraction(payload["lo_exact"]) != Fraction(lo, DEN):
            raise ValueError
        if Fraction(payload["hi_exact"]) != Fraction(hi, DEN):
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


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_json_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()


def verify_identity_file(
    path: Path, expected_file_digest: str, expected_internal_digest: str,
    checker_digest: str, request_digest: str, model_id: str, epoch: str,
    reasons: list[str], raw: bytes | None = None,
) -> str | None:
    try:
        raw = path.read_bytes() if raw is None else raw
        document = json.loads(raw)
    except (OSError, json.JSONDecodeError):
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
    if recorded_internal != actual_internal or recorded_internal != expected_internal_digest:
        reasons.append("proof-identity-internal-digest-mismatch")
    checker = document.get("checker")
    if not isinstance(checker, dict) or checker.get("sha256") != checker_digest:
        reasons.append("proof-identity-checker-mismatch")
    fragment = document.get("fragment")
    expected_fragment = {
        "soundness_theorem": "JackalIv.Spacecraft.spacecraft_burn_certified_safe",
        "request_digest": request_digest,
        "model_id": model_id,
        "release_epoch": epoch,
    }
    if not isinstance(fragment, dict) or any(
        fragment.get(key) != value for key, value in expected_fragment.items()
    ):
        reasons.append("proof-identity-fragment-mismatch")
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
        checker.write_bytes(checker_bytes)
        witness.write_bytes(witness_bytes)
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
) -> tuple[list[str], dict[str, str]]:
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
    for path, reason in (
        (witness_path, "witness-unreadable"),
        (checker_path, "checker-unreadable"),
        (proof_identity_path, "proof-identity-invalid"),
    ):
        if not path.is_file() or path.is_symlink():
            reasons.append(reason)
    if reasons:
        return reasons, {}
    receipt_digest = sha256_file(receipt_path)
    if receipt_digest != expected_receipt_sha256:
        reasons.append("receipt-hash-mismatch")
    try:
        witness_bytes = witness_path.read_bytes()
        checker_bytes = checker_path.read_bytes()
        proof_identity_bytes = proof_identity_path.read_bytes()
    except OSError:
        return ["binding-input-unreadable"], {}
    witness_digest = hashlib.sha256(witness_bytes).hexdigest()
    checker_digest = hashlib.sha256(checker_bytes).hexdigest()
    proof_file_digest = verify_identity_file(
        proof_identity_path, expected_proof_file_sha256,
        expected_proof_identity_sha256, checker_digest, expected_request_digest,
        expected_model_id, expected_epoch, reasons, raw=proof_identity_bytes,
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
    if not isinstance(result_line, str) or "\n" in result_line or "\r" in result_line:
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
        "checker_sha256": checker_digest,
        "proof_identity_file_sha256": proof_file_digest or "",
    }
    return sorted(set(reasons)), digests


def verify_receipt(
    receipt_path: Path | str,
    source_path: Path | str,
    *,
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
    caller_paths = (
        (witness_path, "witness-unreadable"),
        (checker_path, "checker-unreadable"),
        (proof_identity_path, "proof-identity-invalid"),
    )
    symlink_reasons = [
        reason for value, reason in caller_paths
        if value is not None and Path(value).is_symlink()
    ]
    if symlink_reasons:
        return {"status": "REFUSED", "reasons": sorted(set(symlink_reasons))}
    receipt_path = Path(receipt_path).resolve()
    source_path = Path(source_path).resolve()
    reasons: list[str] = []
    try:
        candidate = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
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

    formal_reasons, formal_digests = verify_formal_binding(
        candidate,
        receipt_path,
        witness_path=None if witness_path is None else Path(witness_path).resolve(),
        checker_path=None if checker_path is None else Path(checker_path).resolve(),
        proof_identity_path=None if proof_identity_path is None else Path(proof_identity_path).resolve(),
        expected_receipt_sha256=expected_receipt_sha256,
        expected_proof_file_sha256=expected_proof_file_sha256,
        expected_proof_identity_sha256=expected_proof_identity_sha256,
        expected_request_digest=expected_request_digest,
        expected_model_id=expected_model_id,
        expected_epoch=expected_epoch,
        nonce=nonce,
    )
    if formal_reasons:
        return {"status": "REFUSED", "reasons": formal_reasons}

    try:
        source_raw = source_path.read_bytes()
        literals = source_literals(source_raw, source_path)
    except (OSError, UnicodeDecodeError, SyntaxError, ValueError):
        return {"status": "REFUSED", "reasons": ["invalid-producer-source"]}
    for name, (required, reason) in CONTRACT.items():
        if literals.get(name) != required:
            reasons.append(reason)
    source_digest = hashlib.sha256(source_raw).hexdigest()
    if candidate.get("source_sha256") != source_digest:
        reasons.append("source-hash-mismatch")

    expected_contract = {
        "thrust_acceleration_scale": "0.001",
        "integrate_mass": True,
        "apoapsis_eccentricity_sign": 1,
        "energy_denominator": 2,
        "propagate_full_box": True,
        "decision_mode": "exact_lower_bound",
    }
    if candidate.get("model_contract") != expected_contract:
        reasons.append("model-contract-mismatch")
    identities = verify_symbolic_identities()
    if not identities or not all(identities.values()):
        reasons.append("symbolic-orbital-identity-failure")

    decisive = candidate.get("decisive_margin")
    if not isinstance(decisive, dict) or not isinstance(decisive.get("interval"), dict):
        reasons.append("invalid-decisive-margin")
    else:
        observed = parse_receipt_interval(decisive["interval"], reasons, "decisive_margin")
        try:
            reported = Fraction(decisive["reported_lower_exact"])
        except (KeyError, TypeError, ValueError, ZeroDivisionError):
            reasons.append("reported-lower-bound-mismatch")
        else:
            if observed is None or reported != Fraction(observed[0], DEN):
                reasons.append("reported-lower-bound-mismatch")
    if reasons:
        return {"status": "REFUSED", "reasons": sorted(set(reasons)), "symbolic_identities": identities}

    expected = replay()
    method = candidate["method"]
    for field_name in (
        "trace_sha256",
        "branch_count",
        "tube_count",
        "postprocess_count",
        "maximum_picard_iterations",
    ):
        if method.get(field_name) != expected[field_name]:
            reasons.append(f"replay-mismatch:{field_name}")
    if method.get("step_exact") != "1/32" or method.get("partition_counts") != list(PARTS):
        reasons.append("replay-method-mismatch")
    if method.get("domain_lower_bounds") != expected["domain_lower_bounds"]:
        reasons.append("replay-domain-mismatch")

    cutoff_names = ("x", "y", "vx", "vy", "mass")
    cutoff = candidate["cutoff_state_hull"]
    for name, value in zip(cutoff_names, expected["cutoff"]):
        if not isinstance(cutoff.get(name), dict):
            reasons.append(f"missing-interval:cutoff.{name}")
        else:
            compare_interval(cutoff[name], value, reasons, f"cutoff.{name}")
    orbit = candidate["orbital_hulls"]
    for name, value in expected["post"].items():
        if not isinstance(orbit.get(name), dict):
            reasons.append(f"missing-interval:orbital.{name}")
        else:
            compare_interval(orbit[name], value, reasons, f"orbital.{name}")

    decisive = candidate["decisive_margin"]
    compare_interval(decisive["interval"], expected["minimum_cell"], reasons, "decisive_margin")
    formula_exact = frac_text(Fraction(expected["minimum_formula_lo"], DEN))
    if decisive.get("formula_only_global_lower_exact") != formula_exact:
        reasons.append("formula-lower-bound-mismatch")
    if decisive.get("minimum_location") != expected["minimum_location"]:
        reasons.append("minimum-location-mismatch")
    expected_lower = Fraction(expected["minimum_cell"][0], DEN)
    if Fraction(decisive.get("reported_lower_exact")) != expected_lower:
        reasons.append("reported-lower-bound-mismatch")
    if candidate.get("verdict") != ("CERTIFIED SAFE" if expected_lower > 0 else "INDETERMINATE"):
        reasons.append("verdict-mismatch")

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
    result = verify_receipt(
        args.receipt, args.source,
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
    if args.output:
        destination = args.output.resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(f".{destination.name}.tmp-{os.getpid()}")
        with temporary.open("xb") as stream:
            stream.write(rendered.encode("utf-8"))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
        print(f"INDEPENDENT_VERIFICATION_{result['status']} output={destination}")
    else:
        print(rendered, end="")
    return 0 if result["status"] == "ACCEPT" else 2


if __name__ == "__main__":
    raise SystemExit(main())
