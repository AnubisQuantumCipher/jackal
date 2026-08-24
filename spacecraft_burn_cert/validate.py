#!/opt/homebrew/bin/python3
"""Independent reconciliation and diagnostic validation of the certifier.

Nothing in this file is used to prove the universal mission result.  It checks
the proof instrument against an analytic mass solution, deterministic corner
trajectories, an independently coded RK4 nominal trajectory, exact arithmetic
properties, and a step-halving study.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import itertools
import json
import math
import os
from fractions import Fraction
from pathlib import Path
from typing import Sequence


ROOT = Path(__file__).resolve().parent
CERTIFIER_PATH = ROOT / "certify.py"


def receipt_interval(payload: dict) -> tuple[Fraction, Fraction]:
    return Fraction(payload["lo_exact"]), Fraction(payload["hi_exact"])


def analytic_mass_reachable() -> tuple[Fraction, Fraction]:
    denominator = Fraction(450) * Fraction("9.80665")
    lower = Fraction("1198.5") - Fraction(2005) * Fraction("121.5") / denominator
    upper = Fraction("1201.5") - Fraction(1995) * Fraction("118.5") / denominator
    return lower, upper


def rhs(state: Sequence[float], thrust: float) -> tuple[float, ...]:
    x, y, vx, vy, mass = state
    mu = 398600.4418
    radius = math.hypot(x, y)
    speed = math.hypot(vx, vy)
    thrust_accel = thrust / mass / 1000.0
    return (
        vx,
        vy,
        -mu * x / radius**3 + thrust_accel * vx / speed,
        -mu * y / radius**3 + thrust_accel * vy / speed,
        -thrust / (450.0 * 9.80665),
    )


def rk4(initial: Sequence[float], thrust: float, cutoff: float, step: Fraction) -> tuple[float, ...]:
    state = tuple(float(value) for value in initial)
    base_step = float(step)
    time = 0.0
    while time < cutoff:
        h = min(base_step, cutoff - time)
        k1 = rhs(state, thrust)
        z2 = tuple(value + h * slope / 2 for value, slope in zip(state, k1))
        k2 = rhs(z2, thrust)
        z3 = tuple(value + h * slope / 2 for value, slope in zip(state, k2))
        k3 = rhs(z3, thrust)
        z4 = tuple(value + h * slope for value, slope in zip(state, k3))
        k4 = rhs(z4, thrust)
        state = tuple(
            value + h * (a + 2 * b + 2 * c + d) / 6
            for value, a, b, c, d in zip(state, k1, k2, k3, k4)
        )
        time += h
    return state


def float_margin(state: Sequence[float]) -> float:
    x, y, vx, vy, _mass = state
    mu = 398600.4418
    radius = math.hypot(x, y)
    speed_squared = vx * vx + vy * vy
    energy = speed_squared / 2 - mu / radius
    semimajor = -mu / (2 * energy)
    momentum = x * vy - y * vx
    eccentricity = math.sqrt(1 + 2 * energy * momentum * momentum / mu**2)
    apoapsis = semimajor * (1 + eccentricity)
    return apoapsis - 6378.1363 - 1000.0


def nominal_rk4(step: Fraction = Fraction(1, 64)) -> tuple[tuple[float, ...], float]:
    state = rk4((6679.0, 0.0, 0.0, 7.726, 1200.0), 2000.0, 120.0, step)
    return state, float_margin(state)


def load_certifier():
    spec = importlib.util.spec_from_file_location("validation_certifier", CERTIFIER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load certifier")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def arithmetic_corpus() -> dict:
    certifier = load_certifier()
    values = (
        Fraction(-17, 13),
        Fraction(-1, 1000),
        Fraction(0),
        Fraction(1, 3),
        Fraction(7, 11),
        Fraction(2),
        Fraction(6679),
    )
    checks = 0
    for left, right in itertools.product(values, repeat=2):
        a = certifier.DInterval.point(left)
        b = certifier.DInterval.point(right)
        operations = ((a + b, left + right), (a * b, left * right))
        if right:
            operations += ((a / b, left / right),)
        for observed, exact in operations:
            if not (observed.lo_fraction() <= exact <= observed.hi_fraction()):
                raise RuntimeError("dyadic arithmetic corpus containment failed")
            checks += 1
    for value in (Fraction(0), Fraction(1, 10), Fraction(2), Fraction(1234567, 89)):
        observed = certifier.DInterval.point(value).sqrt()
        if observed.lo * observed.lo > value * certifier.SCALE * certifier.SCALE:
            raise RuntimeError("sqrt lower witness failed")
        if observed.hi * observed.hi < value * certifier.SCALE * certifier.SCALE:
            raise RuntimeError("sqrt upper witness failed")
        checks += 1
    return {"status": "PASS", "deterministic_checks": checks}


def corner_diagnostics(receipt: dict, step: Fraction = Fraction(1, 32)) -> dict:
    bounds = (
        (6677.9995, 6680.0005),
        (-0.0005, 0.0005),
        (-0.00002, 0.00002),
        (7.7258, 7.7262),
        (1198.5, 1201.5),
        (1995.0, 2005.0),
        (118.5, 121.5),
    )
    hulls = {
        name: tuple(map(float, receipt_interval(receipt["cutoff_state_hull"][name])))
        for name in ("x", "y", "vx", "vy", "mass")
    }
    certified_lower = float(Fraction(receipt["decisive_margin"]["reported_lower_exact"]))
    minimum_margin = math.inf
    minimum_inputs = None
    containment_failures = []
    sample_count = 0
    for values in itertools.product(*bounds):
        initial = values[:5]
        thrust = values[5]
        cutoff = values[6]
        state = rk4(initial, thrust, cutoff, step)
        margin = float_margin(state)
        sample_count += 1
        if margin < minimum_margin:
            minimum_margin = margin
            minimum_inputs = values
        for name, value in zip(("x", "y", "vx", "vy", "mass"), state):
            lo, hi = hulls[name]
            if not lo <= value <= hi:
                containment_failures.append({"sample": values, "field": name, "value": value})
    if containment_failures:
        raise RuntimeError("corner diagnostic escaped the certified cutoff hull")
    if minimum_margin < certified_lower:
        raise RuntimeError("corner diagnostic fell below the certified lower bound")
    return {
        "status": "PASS",
        "classification": "deterministic corner samples; diagnostic only, not proof",
        "sample_count": sample_count,
        "rk4_step_exact": f"{step.numerator}/{step.denominator}",
        "minimum_sampled_margin_km": format(minimum_margin, ".16g"),
        "minimum_sample_inputs": [format(value, ".16g") for value in minimum_inputs],
        "certified_lower_margin_km": format(certified_lower, ".16g"),
    }


def step_refinement(receipt: dict) -> dict:
    certifier = load_certifier()
    original_step = certifier.STEP
    records = []
    try:
        for step_size in (Fraction(1, 16), Fraction(1, 64)):
            certifier.STEP = step_size
            result = certifier.certify()
            records.append(
                {
                    "step_exact": f"{step_size.numerator}/{step_size.denominator}",
                    "lower_exact": result["decisive_margin"]["reported_lower_exact"],
                    "lower_decimal": result["decisive_margin"]["reported_lower_decimal"],
                    "formula_only_lower_exact": result["decisive_margin"][
                        "formula_only_global_lower_exact"
                    ],
                    "verdict": result["verdict"],
                    "tube_count": result["method"]["tube_count"],
                    "trace_sha256": result["method"]["trace_sha256"],
                }
            )
    finally:
        certifier.STEP = original_step
    baseline = {
        "step_exact": receipt["method"]["step_exact"],
        "lower_exact": receipt["decisive_margin"]["reported_lower_exact"],
        "lower_decimal": receipt["decisive_margin"]["reported_lower_decimal"],
        "formula_only_lower_exact": receipt["decisive_margin"][
            "formula_only_global_lower_exact"
        ],
        "verdict": receipt["verdict"],
        "tube_count": receipt["method"]["tube_count"],
        "trace_sha256": receipt["method"]["trace_sha256"],
    }
    records.insert(1, baseline)
    if any(record["verdict"] != "PROVED SAFE" for record in records):
        raise RuntimeError("step refinement did not preserve the safe decision")
    return {
        "status": "PASS",
        "classification": "rigorous step-size cross-check; not a formal convergence theorem",
        "runs": records,
    }


def validate(baseline_path: Path, include_refinement: bool = True) -> dict:
    receipt = json.loads(baseline_path.read_text(encoding="utf-8"))
    actual_tubes = receipt["method"]["tube_count"]
    expected_tubes = receipt["method"]["branch_count"] * int(Fraction("121.5") / Fraction(1, 32))
    actual_posts = receipt["method"]["postprocess_count"]
    expected_posts = receipt["method"]["branch_count"] * int(Fraction(3) / Fraction(1, 32))
    reconciliation = {
        "status": "PASS" if (actual_tubes, actual_posts) == (expected_tubes, expected_posts) else "FAIL",
        "tube_count": actual_tubes,
        "expected_tube_count": expected_tubes,
        "postprocess_count": actual_posts,
        "expected_postprocess_count": expected_posts,
    }
    if reconciliation["status"] != "PASS":
        raise RuntimeError("instrument counts do not reconcile")

    exact_mass = analytic_mass_reachable()
    hull_mass = receipt_interval(receipt["cutoff_state_hull"]["mass"])
    mass_check = {
        "status": "PASS"
        if hull_mass[0] <= exact_mass[0] <= exact_mass[1] <= hull_mass[1]
        else "FAIL",
        "analytic_exact": [str(exact_mass[0]), str(exact_mass[1])],
        "certified_hull_exact": [str(hull_mass[0]), str(hull_mass[1])],
    }
    if mass_check["status"] != "PASS":
        raise RuntimeError("analytic mass solution is not enclosed")

    nominal_state, nominal_margin = nominal_rk4()
    result = {
        "schema": "spacecraft-finite-burn-instrument-validation-v1",
        "baseline_receipt_sha256": hashlib.sha256(baseline_path.read_bytes()).hexdigest(),
        "reconciliation": reconciliation,
        "arithmetic_corpus": arithmetic_corpus(),
        "analytic_mass": mass_check,
        "nominal_diagnostic": {
            "classification": "numerically estimated diagnostic only",
            "rk4_step_exact": "1/64",
            "cutoff_state": [format(value, ".16g") for value in nominal_state],
            "margin_km": format(nominal_margin, ".16g"),
        },
        "corner_diagnostics": corner_diagnostics(receipt),
    }
    if include_refinement:
        result["step_refinement"] = step_refinement(receipt)
    result["status"] = "PASS"
    return result


def write_atomic(path: Path, payload: dict) -> None:
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
    parser.add_argument("--baseline", type=Path, default=ROOT / "evidence" / "baseline_receipt.json")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--skip-refinement", action="store_true")
    args = parser.parse_args(argv)
    result = validate(args.baseline, include_refinement=not args.skip_refinement)
    if args.output:
        write_atomic(args.output, result)
        print(f"INSTRUMENT_VALIDATION_{result['status']} output={args.output.resolve()}")
    else:
        print(json.dumps(result, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
