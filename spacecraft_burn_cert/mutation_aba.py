#!/opt/homebrew/bin/python3
"""A -> B -> A mutation campaign for the six required failure modes."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Sequence


ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "certify.py"
VERIFIER = ROOT / "verify_receipt.py"
BASELINE = ROOT / "evidence" / "baseline_receipt.json"
PYTHON = Path("/opt/homebrew/bin/python3")


MUTATIONS = {
    "meters_as_kilometers": {
        "old": 'THRUST_KM_SCALE_TEXT = "0.001"',
        "new": 'THRUST_KM_SCALE_TEXT = "1"',
        "expected_reason": "unit-scale-mismatch",
        "bug": "uses m/s^2 thrust acceleration in a km/s^2 state model",
    },
    "frozen_mass": {
        "old": "INTEGRATE_MASS = True",
        "new": "INTEGRATE_MASS = False",
        "expected_reason": "mass-integration-mismatch",
        "bug": "freezes mass and sets propellant mass flow to zero",
    },
    "periapsis_instead_of_apoapsis": {
        "old": "APOAPSIS_ECCENTRICITY_SIGN = 1",
        "new": "APOAPSIS_ECCENTRICITY_SIGN = -1",
        "expected_reason": "apoapsis-plus-mismatch",
        "bug": "uses a(1-e) instead of a(1+e)",
    },
    "double_kinetic_energy": {
        "old": "ENERGY_HALF_DENOMINATOR = 2",
        "new": "ENERGY_HALF_DENOMINATOR = 1",
        "expected_reason": "energy-half-mismatch",
        "bug": "uses v^2 instead of v^2/2 in specific orbital energy",
    },
    "center_only": {
        "old": "PROPAGATE_FULL_BOX = True",
        "new": "PROPAGATE_FULL_BOX = False",
        "expected_reason": "full-box-coverage-mismatch",
        "bug": "uses the center of each uncertainty interval",
    },
    "round_margin_upward": {
        "old": 'DECISION_MODE = "exact_lower_bound"',
        "new": 'DECISION_MODE = "ceil_display"',
        "expected_reason": "decision-rounding-mismatch",
        "bug": "ceil-rounds a lower bound before reporting and deciding",
    },
}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def atomic_bytes(path: Path, data: bytes, mode: int) -> None:
    temporary = path.with_name(f".{path.name}.mutation-{os.getpid()}")
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
        try:
            written = os.write(descriptor, data)
            if written != len(data):
                raise RuntimeError("short mutation write")
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def mutated_bytes(original: bytes, name: str) -> bytes:
    mutation = MUTATIONS[name]
    old = mutation["old"].encode("utf-8")
    new = mutation["new"].encode("utf-8")
    if original.count(old) != 1:
        raise RuntimeError(f"mutation target for {name} is not unique")
    return original.replace(old, new, 1)


def hash_only_cycle(name: str) -> dict:
    original = SOURCE.read_bytes()
    mode = SOURCE.stat().st_mode & 0o777
    a_before = sha256(original)
    b_data = mutated_bytes(original, name)
    try:
        atomic_bytes(SOURCE, b_data, mode)
        b_hash = sha256(SOURCE.read_bytes())
    finally:
        atomic_bytes(SOURCE, original, mode)
    a_after = sha256(SOURCE.read_bytes())
    return {
        "mutation": name,
        "a_before_sha256": a_before,
        "b_sha256": b_hash,
        "a_after_sha256": a_after,
        "restored": a_before == a_after and SOURCE.read_bytes() == original,
    }


def run(command: Sequence[str], timeout: int = 150) -> dict:
    environment = dict(os.environ)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    try:
        completed = subprocess.run(
            list(command),
            cwd=ROOT.parent,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            check=False,
            text=True,
        )
        output = completed.stdout
        return {
            "returncode": completed.returncode,
            "output_sha256": sha256(output.encode("utf-8")),
            "output_excerpt": output[-3000:],
        }
    except subprocess.TimeoutExpired as error:
        output = (error.stdout or "") + (error.stderr or "")
        return {
            "returncode": 124,
            "output_sha256": sha256(output.encode("utf-8")),
            "output_excerpt": output[-3000:],
        }


def parse_json_output(record: dict) -> dict | None:
    try:
        return json.loads(record["output_excerpt"])
    except (json.JSONDecodeError, TypeError):
        return None


def exercise_mutation(name: str) -> dict:
    mutation = MUTATIONS[name]
    original = SOURCE.read_bytes()
    original_mode = SOURCE.stat().st_mode & 0o777
    a_before = sha256(original)
    mutant = mutated_bytes(original, name)
    producer_record = None
    test_record = None
    verifier_record = None
    verifier_result = None
    restored_test = None
    b_hash = None
    candidate_summary = None
    caught = False
    try:
        atomic_bytes(SOURCE, mutant, original_mode)
        b_hash = sha256(SOURCE.read_bytes())
        test_record = run(
            (
                str(PYTHON),
                "-B",
                "-m",
                "unittest",
                "spacecraft_burn_cert/tests/test_certifier.py",
                "-v",
            ),
            timeout=45,
        )
        with tempfile.TemporaryDirectory(prefix="spacecraft-mutation-") as directory:
            candidate = Path(directory) / "candidate.json"
            producer_record = run(
                (str(PYTHON), "-B", str(SOURCE), "--output", str(candidate)),
                timeout=150,
            )
            evidence = candidate if candidate.is_file() else BASELINE
            if candidate.is_file():
                payload = json.loads(candidate.read_text(encoding="utf-8"))
                candidate_summary = {
                    "verdict": payload.get("verdict"),
                    "reported_lower_exact": payload.get("decisive_margin", {}).get(
                        "reported_lower_exact"
                    ),
                    "model_contract": payload.get("model_contract"),
                }
            verifier_record = run(
                (
                    str(PYTHON),
                    "-B",
                    str(VERIFIER),
                    str(evidence),
                    "--source",
                    str(SOURCE),
                ),
                timeout=45,
            )
            verifier_result = parse_json_output(verifier_record)
        reasons = verifier_result.get("reasons", []) if verifier_result else []
        caught = (
            test_record["returncode"] != 0
            and verifier_result is not None
            and verifier_result.get("status") == "REFUSED"
            and mutation["expected_reason"] in reasons
        )
    finally:
        atomic_bytes(SOURCE, original, original_mode)
        restored_test = run(
            (
                str(PYTHON),
                "-B",
                "-m",
                "unittest",
                "spacecraft_burn_cert.tests.test_certifier.CertifierContractTests.test_baseline_contract_integrates_mass_and_converts_thrust_to_km",
                "-v",
            ),
            timeout=30,
        )
    a_after = sha256(SOURCE.read_bytes())
    restored = a_after == a_before and SOURCE.read_bytes() == original
    return {
        "mutation": name,
        "bug": mutation["bug"],
        "expected_reason": mutation["expected_reason"],
        "a_before_sha256": a_before,
        "b_sha256": b_hash,
        "a_after_sha256": a_after,
        "restored": restored,
        "restored_contract_test_passed": restored_test["returncode"] == 0,
        "mutant_tests_failed": test_record["returncode"] != 0,
        "mutant_test_output_sha256": test_record["output_sha256"],
        "producer_returncode": producer_record["returncode"],
        "producer_output_excerpt": producer_record["output_excerpt"],
        "candidate_summary": candidate_summary,
        "verifier": verifier_result,
        "caught": caught,
    }


def verify_baseline() -> dict:
    record = run(
        (
            str(PYTHON),
            "-B",
            str(VERIFIER),
            str(BASELINE),
            "--source",
            str(SOURCE),
        ),
        timeout=150,
    )
    parsed = parse_json_output(record)
    return parsed or {"status": "ERROR", "record": record}


def campaign() -> dict:
    original_hash = sha256(SOURCE.read_bytes())
    before = verify_baseline()
    if before.get("status") != "ACCEPT":
        raise RuntimeError("baseline verifier did not accept before mutation campaign")
    records = [exercise_mutation(name) for name in MUTATIONS]
    final_hash = sha256(SOURCE.read_bytes())
    after = verify_baseline()
    status = (
        "PASS"
        if original_hash == final_hash
        and before.get("status") == "ACCEPT"
        and after.get("status") == "ACCEPT"
        and all(
            record["caught"]
            and record["restored"]
            and record["restored_contract_test_passed"]
            for record in records
        )
        else "FAIL"
    )
    return {
        "schema": "spacecraft-finite-burn-mutation-aba-v1",
        "status": status,
        "baseline_source_sha256": original_hash,
        "final_source_sha256": final_hash,
        "baseline_verifier_before": before,
        "mutations": records,
        "baseline_verifier_after": after,
    }


def write_atomic(path: Path, payload: dict) -> None:
    data = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    with temporary.open("xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "evidence" / "mutation_aba.json")
    args = parser.parse_args(argv)
    result = campaign()
    write_atomic(args.output, result)
    print(f"MUTATION_ABA_{result['status']} output={args.output.resolve()}")
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
