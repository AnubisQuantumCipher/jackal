#!/usr/bin/env python3
"""A -> B -> A mutation campaign for the six required failure modes."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
from dataclasses import replace
from pathlib import Path
from typing import Iterable, NamedTuple, Sequence


ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "certify.py"
VERIFIER = ROOT / "verify_receipt.py"
BASELINE = ROOT / "evidence" / "baseline_receipt.json"
PYTHON = Path(sys.executable).resolve()


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

ISOLATED_UNITTEST_RUNNER = r"""
import importlib.util
import sys
import unittest
from pathlib import Path

test_path = Path(sys.argv[1]).resolve()
repository_root = Path(sys.argv[2]).resolve()
selector = sys.argv[3]
sys.path.insert(0, str(repository_root))
module_name = "spacecraft_certifier_contract_tests"
spec = importlib.util.spec_from_file_location(module_name, test_path)
if spec is None or spec.loader is None:
    raise RuntimeError("cannot load snapshotted certifier contract tests")
module = importlib.util.module_from_spec(spec)
sys.modules[module_name] = module
spec.loader.exec_module(module)
loader = unittest.TestLoader()
suite = (
    loader.loadTestsFromName(selector, module)
    if selector
    else loader.loadTestsFromModule(module)
)
result = unittest.TextTestRunner(verbosity=2).run(suite)
raise SystemExit(0 if result.wasSuccessful() else 1)
"""


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


def hash_only_cycle(name: str, source: Path = SOURCE) -> dict:
    original = source.read_bytes()
    mode = source.stat().st_mode & 0o777
    a_before = sha256(original)
    b_data = mutated_bytes(original, name)
    try:
        atomic_bytes(source, b_data, mode)
        b_hash = sha256(source.read_bytes())
    finally:
        atomic_bytes(source, original, mode)
    a_after = sha256(source.read_bytes())
    return {
        "mutation": name,
        "a_before_sha256": a_before,
        "b_sha256": b_hash,
        "a_after_sha256": a_after,
        "restored": a_before == a_after and source.read_bytes() == original,
    }


def run(command: Sequence[str], timeout: int = 150, extra_env: dict[str, str] | None = None) -> dict:
    environment = {
        "LANG": "C",
        "LC_ALL": "C",
        "PATH": "/usr/bin:/bin",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONHASHSEED": "0",
        "TZ": "UTC",
    }
    if extra_env:
        if set(extra_env) != {"SPACECRAFT_CERTIFIER_PATH"}:
            raise ValueError("unsupported mutation subprocess environment")
        environment.update(extra_env)
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
            "output": output,
            "output_excerpt": output[-3000:],
        }
    except subprocess.TimeoutExpired as error:
        def timeout_text(value: str | bytes | None) -> str:
            if value is None:
                return ""
            if isinstance(value, bytes):
                return value.decode("utf-8", errors="replace")
            return value

        output = timeout_text(error.stdout) + timeout_text(error.stderr)
        return {
            "returncode": 124,
            "output_sha256": sha256(output.encode("utf-8")),
            "output": output,
            "output_excerpt": output[-3000:],
        }


def parse_json_output(record: dict) -> dict | None:
    try:
        return json.loads(record["output"])
    except (json.JSONDecodeError, TypeError):
        return None


def completed_mutant_failure(returncode: int) -> bool:
    return returncode not in (0, 124)


def mutant_failure_caught(returncode: int, output: str, expected_reason: str) -> bool:
    return completed_mutant_failure(returncode) and expected_reason in output


def normalized_mutant_test_output(output: str, isolated_source: Path) -> str:
    """Remove nondeterministic diagnostics before binding mutant-test output."""
    normalized = output

    def replace_path(path: Path, replacement: str) -> None:
        nonlocal normalized
        variants = {str(path), str(path.absolute()), str(path.resolve())}
        for value in tuple(variants):
            if value.startswith("/private/"):
                variants.add(value.removeprefix("/private"))
            elif value.startswith("/var/"):
                variants.add("/private" + value)
        for value in sorted(variants, key=len, reverse=True):
            normalized = normalized.replace(value, replacement)

    replace_path(isolated_source, "<MUTANT_CERTIFIER>")
    replace_path(isolated_source.parent, "<MUTANT_DIRECTORY>")
    replace_path(ROOT.parent, "<REPOSITORY_ROOT>")
    return re.sub(r"(?m)^(Ran \d+ tests? in )\d+(?:\.\d+)?s$", r"\1<TIME>s", normalized)


def witness_mutation_caught(returncode: int, parsed: dict | None) -> bool:
    return (
        completed_mutant_failure(returncode)
        and parsed is not None
        and parsed.get("status") == "REFUSED"
        and "witness-hash-mismatch" in parsed.get("reasons", [])
    )


class FormalInputs(NamedTuple):
    receipt: Path
    request: Path
    witness: Path
    checker: Path
    proof_identity: Path
    receipt_sha256: str
    proof_file_sha256: str
    proof_identity_sha256: str
    request_digest: str
    model_id: str
    epoch: str
    nonce: str


def verifier_command(inputs: FormalInputs, witness: Path | None = None) -> tuple[str, ...]:
    return (
        str(PYTHON), "-I", "-B", str(VERIFIER), str(inputs.receipt),
        "--source", str(SOURCE), "--request", str(inputs.request),
        "--witness", str(witness or inputs.witness),
        "--checker", str(inputs.checker), "--proof-identity", str(inputs.proof_identity),
        "--expected-receipt-sha256", inputs.receipt_sha256,
        "--expected-proof-file-sha256", inputs.proof_file_sha256,
        "--expected-proof-identity-sha256", inputs.proof_identity_sha256,
        "--expected-request-digest", inputs.request_digest,
        "--expected-model-id", inputs.model_id, "--expected-epoch", inputs.epoch,
        "--nonce", inputs.nonce,
    )


def certifier_test_command(selector: str = "") -> tuple[str, ...]:
    return (
        str(PYTHON),
        "-I",
        "-B",
        "-c",
        ISOLATED_UNITTEST_RUNNER,
        str(ROOT / "tests" / "test_certifier.py"),
        str(ROOT.parent),
        selector,
    )


def exercise_mutation(name: str) -> dict:
    mutation = MUTATIONS[name]
    original = SOURCE.read_bytes()
    codec_source = SOURCE.with_name("witness_codec.py")
    codec_bytes = codec_source.read_bytes()
    original_mode = SOURCE.stat().st_mode & 0o777
    codec_mode = codec_source.stat().st_mode & 0o777
    a_before = sha256(original)
    mutant = mutated_bytes(original, name)
    test_record = None
    restored_test = None
    b_hash = None
    caught = False
    with tempfile.TemporaryDirectory(prefix="spacecraft-source-mutation-") as directory:
        isolated = Path(directory) / "certify.py"
        isolated_codec = isolated.with_name("witness_codec.py")
        atomic_bytes(isolated, original, original_mode)
        atomic_bytes(isolated_codec, codec_bytes, codec_mode)
        atomic_bytes(isolated, mutant, original_mode)
        b_hash = sha256(isolated.read_bytes())
        test_record = run(
            certifier_test_command(),
            timeout=45,
            extra_env={"SPACECRAFT_CERTIFIER_PATH": str(isolated)},
        )
        reason_observed = mutation["expected_reason"] in test_record["output"]
        caught = mutant_failure_caught(
            test_record["returncode"], test_record["output"], mutation["expected_reason"]
        )
        atomic_bytes(isolated, original, original_mode)
        restored_test = run(
            certifier_test_command(
                "CertifierContractTests."
                "test_baseline_contract_integrates_mass_and_converts_thrust_to_km"
            ),
            timeout=30,
            extra_env={"SPACECRAFT_CERTIFIER_PATH": str(isolated)},
        )
        a_after = sha256(isolated.read_bytes())
        restored = a_after == a_before and isolated.read_bytes() == original
    return {
        "mutation": name,
        "bug": mutation["bug"],
        "expected_reason": mutation["expected_reason"],
        "a_before_sha256": a_before,
        "b_sha256": b_hash,
        "a_after_sha256": a_after,
        "restored": restored,
        "restored_contract_test_passed": restored_test["returncode"] == 0,
        "mutant_tests_failed": completed_mutant_failure(test_record["returncode"]),
        "mutant_tests_timed_out": test_record["returncode"] == 124,
        "reason_observed": reason_observed,
        "mutant_test_output_sha256": sha256(
            normalized_mutant_test_output(test_record["output"], isolated).encode("utf-8")
        ),
        "detection_boundary": "source contract tests; formal publication requires separately pinned immutable bytes",
        "caught": caught,
    }


def verify_baseline(inputs: FormalInputs) -> dict:
    record = run(verifier_command(inputs), timeout=180)
    parsed = parse_json_output(record)
    return parsed or {"status": "ERROR", "record": record}


def mutated_witness(original: bytes, name: str) -> bytes:
    try:
        from spacecraft_burn_cert import witness_codec
    except ModuleNotFoundError:
        import witness_codec  # type: ignore[no-redef]
    witness = witness_codec.decode_witness(original)
    branches = list(witness.branches)
    first = branches[0]
    if name == "coverage":
        components = list(first.initial.components)
        value = components[0]
        components[0] = witness_codec.Interval(value.lo + 1, value.hi)
        branches[0] = replace(first, initial=witness_codec.Box(tuple(components)))
    elif name == "chain":
        steps = list(first.steps)
        step = steps[1]
        components = list(step.tube.components)
        value = components[0]
        components[0] = witness_codec.Interval(value.hi, value.hi)
        steps[1] = replace(step, tube=witness_codec.Box(tuple(components)))
        branches[0] = replace(first, steps=tuple(steps))
    elif name == "corruption":
        return original[:-1] + bytes((original[-1] ^ 1,))
    else:
        raise ValueError(f"unknown witness mutation: {name}")
    return witness_codec.encode_witness(replace(witness, branches=tuple(branches)))


def exercise_witness_mutation(name: str, inputs: FormalInputs) -> dict:
    original = inputs.witness.read_bytes()
    mutant = mutated_witness(original, name)
    with tempfile.TemporaryDirectory(prefix="spacecraft-witness-mutation-") as directory:
        path = Path(directory) / f"{name}.cert"
        path.write_bytes(mutant)
        checker = run((str(inputs.checker), str(path), inputs.request_digest,
                       inputs.model_id, inputs.epoch), timeout=180)
        verifier = run(verifier_command(inputs, path), timeout=30)
        parsed = parse_json_output(verifier)
    checker_refused = completed_mutant_failure(checker["returncode"])
    return {
        "mutation": name,
        "original_sha256": sha256(original),
        "mutant_sha256": sha256(mutant),
        "checker_refused": checker_refused,
        "checker_timed_out": checker["returncode"] == 124,
        "checker_output_excerpt": checker["output_excerpt"],
        "outer_verifier": parsed,
        "caught": witness_mutation_caught(checker["returncode"], parsed),
    }


def campaign(inputs: FormalInputs) -> dict:
    original_hash = sha256(SOURCE.read_bytes())
    before = verify_baseline(inputs)
    if before.get("status") != "ACCEPT":
        raise RuntimeError("baseline verifier did not accept before mutation campaign")
    records = [exercise_mutation(name) for name in MUTATIONS]
    witness_records = [exercise_witness_mutation(name, inputs) for name in (
        "corruption", "chain", "coverage"
    )]
    final_hash = sha256(SOURCE.read_bytes())
    after = verify_baseline(inputs)
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
        and all(record["caught"] for record in witness_records)
        else "FAIL"
    )
    return {
        "schema": "spacecraft-finite-burn-mutation-aba-v2",
        "status": status,
        "baseline_source_sha256": original_hash,
        "final_source_sha256": final_hash,
        "baseline_verifier_before": before,
        "mutations": records,
        "witness_mutations": witness_records,
        "baseline_verifier_after": after,
    }


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
            raise ValueError("mutation output path cannot be inspected") from error
        if stat.S_ISLNK(metadata.st_mode):
            raise ValueError("mutation output path must not be a symlink")
        raise ValueError("mutation output path must not already exist")

    for input_path in input_paths:
        input_lexical = _lexical_absolute(input_path)
        input_resolved_parent = _resolved_parent_leaf(input_lexical)
        if lexical == input_lexical or resolved_parent == input_resolved_parent:
            raise ValueError("mutation output must not alias an input path")
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
    data = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
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
                raise RuntimeError("zero-length mutation output write")
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
    parser.add_argument("--output", type=Path, default=ROOT / "evidence" / "mutation_aba_v2.json")
    parser.add_argument("--baseline", type=Path, required=True)
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
    args = parser.parse_args(argv)
    output_inputs = (
        args.baseline,
        args.request,
        args.witness,
        args.checker,
        args.proof_identity,
        SOURCE,
        VERIFIER,
        ROOT / "witness_codec.py",
        ROOT / "tests" / "test_certifier.py",
    )
    try:
        destination = prepare_output_path(args.output, output_inputs)
    except ValueError as error:
        parser.error(str(error))
    inputs = FormalInputs(
        args.baseline.resolve(), args.request.resolve(), args.witness.resolve(),
        args.checker.resolve(),
        args.proof_identity.resolve(), args.expected_receipt_sha256,
        args.expected_proof_file_sha256, args.expected_proof_identity_sha256,
        args.expected_request_digest, args.expected_model_id,
        args.expected_epoch, args.nonce,
    )
    result = campaign(inputs)
    destination = write_atomic(destination, result, output_inputs)
    print(f"MUTATION_ABA_{result['status']} output={destination}")
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
