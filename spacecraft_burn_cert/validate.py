#!/usr/bin/env python3
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
import stat
import tempfile
from fractions import Fraction
from pathlib import Path
from typing import Iterable, Sequence


ROOT = Path(__file__).resolve().parent
CERTIFIER_PATH = ROOT / "certify.py"
MODEL_QUALIFIER = (
    "under the stated finite-burn ODE model, supplied input bounds, "
    "and machine-checked interval-certificate assumptions"
)


def receipt_interval(payload: dict) -> tuple[Fraction, Fraction]:
    return Fraction(payload["lo_exact"]), Fraction(payload["hi_exact"])


def answer_controls() -> dict:
    """Check a small exact oracle corpus and reject one wrong answer per case."""
    cases = (
        ("thrust-scale", Fraction(2000, 1200 * 1000), Fraction(1, 600)),
        ("mass-flow", Fraction(2000, 450) / Fraction("9.80665"), Fraction(800000, 1765197)),
        ("kinetic-half", Fraction(8) ** 2 / 2, Fraction(32)),
        ("apoapsis-plus", Fraction(7000) * (1 + Fraction(1, 10)), Fraction(7700)),
    )
    records = []
    for name, observed, expected in cases:
        true_pass = observed == expected
        wrong_pass = observed == expected + 1
        records.append({"case": name, "true_answer_passed": true_pass, "wrong_answer_passed": wrong_pass})
    true_passes = sum(record["true_answer_passed"] for record in records)
    wrong_passes = sum(record["wrong_answer_passed"] for record in records)
    return {
        "status": "PASS" if true_passes == len(records) and wrong_passes == 0 else "FAIL",
        "case_count": len(records),
        "true_answer_pass_rate": f"{true_passes}/{len(records)}",
        "wrong_answer_pass_rate": f"{wrong_passes}/{len(records)}",
        "cases": records,
    }


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
    certified_lower = float(Fraction(receipt["formal_decisive_margin"]["lo_exact"]))
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


def validate_refinement_assurance(records: Sequence[dict], baseline_step: str) -> None:
    candidate_tuple = (
        "CERTIFIED SAFE",
        MODEL_QUALIFIER,
        "candidate-only",
        "NOT_EXECUTED",
        "rigorously interval-bounded, not formal-bounded",
    )
    formal_tuple = (
        "CERTIFIED SAFE",
        MODEL_QUALIFIER,
        "candidate-only",
        "ACCEPT",
        "formal-bounded",
    )
    accepted = 0
    for record in records:
        observed = (
            record.get("verdict"),
            record.get("verdict_qualifier"),
            record.get("producer_assurance"),
            record.get("formal_checker_status"),
            record.get("evidence_classification"),
        )
        expected = formal_tuple if record.get("step_exact") == baseline_step else candidate_tuple
        if observed != expected:
            raise RuntimeError("step refinement assurance mismatch")
        accepted += int(record["formal_checker_status"] == "ACCEPT")
    if accepted != 1:
        raise RuntimeError("step refinement requires exactly one accepted baseline")


def step_refinement(receipt: dict) -> dict:
    certifier = load_certifier()
    original_step = certifier.STEP
    records = []
    try:
        # 1/48 is a strict refinement of the 1/32 baseline while remaining
        # inside the formal codec's 200,000-tube bound (1/64 would not).
        for step_size in (Fraction(1, 16), Fraction(1, 48)):
            certifier.STEP = step_size
            result, _witness = certifier.certify()
            records.append(
                {
                    "step_exact": f"{step_size.numerator}/{step_size.denominator}",
                    "lower_exact": result["decisive_margin"]["reported_lower_exact"],
                    "lower_decimal": result["decisive_margin"]["reported_lower_decimal"],
                    "formula_only_lower_exact": result["decisive_margin"][
                        "formula_only_global_lower_exact"
                    ],
                    "verdict": result["verdict"],
                    "verdict_qualifier": result["verdict_qualifier"],
                    "producer_assurance": result["producer_assurance"],
                    "formal_checker_status": result["formal_checker_status"],
                    "evidence_classification": result["evidence_classification"]["overall"],
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
        "verdict_qualifier": receipt["verdict_qualifier"],
        "producer_assurance": receipt["producer_assurance"],
        "formal_checker_status": receipt["formal_checker_status"],
        "evidence_classification": receipt["evidence_classification"]["overall"],
        "tube_count": receipt["method"]["tube_count"],
        "trace_sha256": receipt["method"]["trace_sha256"],
    }
    records.insert(1, baseline)
    validate_refinement_assurance(records, baseline["step_exact"])
    if any(record["verdict"] != "CERTIFIED SAFE" for record in records):
        raise RuntimeError("step refinement did not preserve the safe decision")
    return {
        "status": "PASS",
        "classification": "rigorous step-size cross-check; not a formal convergence theorem",
        "runs": records,
    }


def validate(baseline_path: Path, include_refinement: bool = True) -> dict:
    baseline_bytes = baseline_path.read_bytes()
    receipt = json.loads(baseline_bytes.decode("utf-8"))
    if receipt.get("formal_checker_status") != "ACCEPT":
        raise RuntimeError("baseline is not bound to an accepted formal checker execution")
    formal_margin = receipt_interval(receipt["formal_decisive_margin"])
    if formal_margin[0] <= 0 or formal_margin[0] > formal_margin[1]:
        raise RuntimeError("formal decisive margin is not strictly positive")
    step = Fraction(receipt["method"]["step_exact"])
    if step <= 0:
        raise RuntimeError("receipt declares a non-positive integration step")
    tube_steps = Fraction("121.5") / step
    post_steps = Fraction(3) / step
    if tube_steps.denominator != 1 or post_steps.denominator != 1:
        raise RuntimeError("receipt step does not exactly partition burn bounds")
    actual_tubes = receipt["method"]["tube_count"]
    expected_tubes = receipt["method"]["branch_count"] * tube_steps.numerator
    actual_posts = receipt["method"]["postprocess_count"]
    expected_posts = receipt["method"]["branch_count"] * post_steps.numerator
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
        "schema": "spacecraft-finite-burn-instrument-validation-v2",
        "baseline_receipt_sha256": hashlib.sha256(baseline_bytes).hexdigest(),
        "formal_checker_status": receipt["formal_checker_status"],
        "formal_checker_binding": receipt["formal_checker"],
        "formal_decisive_margin": receipt["formal_decisive_margin"],
        "reconciliation": reconciliation,
        "arithmetic_corpus": arithmetic_corpus(),
        "answer_controls": answer_controls(),
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
    lexical = _lexical_absolute(path)
    resolved_parent = _resolved_parent_leaf(lexical)
    output_candidates = tuple(dict.fromkeys((lexical, resolved_parent)))
    for candidate in output_candidates:
        try:
            metadata = os.lstat(candidate)
        except FileNotFoundError:
            continue
        except OSError as error:
            raise ValueError("validation output path cannot be inspected") from error
        if stat.S_ISLNK(metadata.st_mode):
            raise ValueError("validation output path must not be a symlink")
        raise ValueError("validation output path must not already exist")

    for input_path in input_paths:
        input_lexical = _lexical_absolute(input_path)
        input_resolved_parent = _resolved_parent_leaf(input_lexical)
        if lexical == input_lexical or resolved_parent == input_resolved_parent:
            raise ValueError("validation output must not alias an input path")
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


def write_atomic(
    path: Path | str,
    payload: dict,
    input_paths: Iterable[Path | str] = (),
) -> Path:
    inputs = tuple(input_paths)
    target = prepare_output_path(path, inputs)
    target.parent.mkdir(parents=True, exist_ok=True)
    target = prepare_output_path(target, inputs)
    data = (json.dumps(payload, sort_keys=True, indent=2) + "\n").encode("utf-8")
    descriptor: int | None = None
    temporary: Path | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{target.name}.tmp-", dir=target.parent
        )
        temporary = Path(temporary_name)
        os.fchmod(descriptor, 0o644)
        view = memoryview(data)
        offset = 0
        while offset < len(view):
            written = os.write(descriptor, view[offset:])
            if written <= 0:
                raise RuntimeError("zero-length validation output write")
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


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", type=Path, default=ROOT / "evidence" / "baseline_receipt_v2.json")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--skip-refinement", action="store_true")
    args = parser.parse_args(argv)
    destination: Path | None = None
    if args.output is not None:
        try:
            destination = prepare_output_path(args.output, (args.baseline,))
        except ValueError as error:
            parser.error(str(error))
    result = validate(args.baseline, include_refinement=not args.skip_refinement)
    if destination is not None:
        destination = write_atomic(destination, result, (args.baseline,))
        print(f"INSTRUMENT_VALIDATION_{result['status']} output={destination}")
    else:
        print(json.dumps(result, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
