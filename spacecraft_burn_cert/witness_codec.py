"""Canonical bounded codec for spacecraft Picard-tube witnesses.

The producer supplies only branch roots and non-derivable tube boxes.  A
formal checker must derive endpoints, chained states, domain bounds, cutoff
coverage, orbital post-processing, and the final decision.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import gcd, prod


MAGIC = b"jackal-spacecraft-burn-cert v2\n"
MAX_WITNESS_BYTES = 64 * 1024 * 1024
MAX_BRANCHES = 1024
MAX_STEPS_PER_BRANCH = 1_000_000
MAX_TUBE_RECORDS = 200_000
MAX_INTEGER_DIGITS = 128
MAX_INTEGER_MAGNITUDE = 10 ** MAX_INTEGER_DIGITS
MAX_WITNESS_RECORD_CHARS = 4096
MAX_WITNESS_RECORDS = MAX_TUBE_RECORDS + MAX_BRANCHES + 3


class WitnessRefusal(ValueError):
    pass


@dataclass(frozen=True)
class Interval:
    lo: int
    hi: int

    def __post_init__(self) -> None:
        if type(self.lo) is not int or type(self.hi) is not int:
            raise WitnessRefusal("invalid-integer")
        if abs(self.lo) >= MAX_INTEGER_MAGNITUDE or abs(self.hi) >= MAX_INTEGER_MAGNITUDE:
            raise WitnessRefusal("integer-digit-limit")
        if self.lo > self.hi:
            raise WitnessRefusal("interval-order")


@dataclass(frozen=True)
class Box:
    components: tuple[Interval, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.components, tuple) or len(self.components) != 5:
            raise WitnessRefusal("box-dimension")
        if not all(isinstance(value, Interval) for value in self.components):
            raise WitnessRefusal("box-component")


@dataclass(frozen=True)
class StepWitness:
    branch: int
    step: int
    tube: Box


@dataclass(frozen=True)
class BranchWitness:
    branch: int
    initial: Box
    thrust: Interval
    steps: tuple[StepWitness, ...]


@dataclass(frozen=True)
class BurnWitness:
    scale_bits: int
    step_num: int
    step_den: int
    partition_counts: tuple[int, int, int, int, int, int]
    steps_per_branch: int
    first_cutoff_step: int
    branches: tuple[BranchWitness, ...]


def _refuse(condition: bool, reason: str) -> None:
    if condition:
        raise WitnessRefusal(reason)


def _validate_nat(value: int, reason: str) -> None:
    _refuse(type(value) is not int or value < 0, reason)
    _refuse(value >= MAX_INTEGER_MAGNITUDE, "integer-digit-limit")


def _validate_witness(witness: BurnWitness) -> tuple[int, int, int]:
    _refuse(type(witness) is not BurnWitness, "witness-record")
    _validate_nat(witness.scale_bits, "scale-bits")
    _refuse(witness.scale_bits == 0 or witness.scale_bits > 4096, "scale-bits")
    _validate_nat(witness.step_num, "step-rational")
    _validate_nat(witness.step_den, "step-rational")
    _refuse(witness.step_num == 0 or witness.step_den == 0, "step-rational")
    _refuse(gcd(witness.step_num, witness.step_den) != 1, "step-rational-not-reduced")
    _refuse(
        not isinstance(witness.partition_counts, tuple)
        or len(witness.partition_counts) != 6,
        "partition-dimension",
    )
    for count in witness.partition_counts:
        _validate_nat(count, "partition-count")
        _refuse(count == 0, "partition-count")
    _validate_nat(witness.steps_per_branch, "steps-per-branch")
    _validate_nat(witness.first_cutoff_step, "first-cutoff-step")
    _refuse(
        witness.steps_per_branch == 0
        or witness.steps_per_branch > MAX_STEPS_PER_BRANCH,
        "steps-per-branch",
    )
    _refuse(
        witness.first_cutoff_step > witness.steps_per_branch,
        "first-cutoff-step",
    )
    _refuse(type(witness.branches) is not tuple, "branches-record")
    branch_count = prod(witness.partition_counts)
    _refuse(branch_count > MAX_BRANCHES, "branch-count-limit")
    _refuse(len(witness.branches) != branch_count, "branch-count")
    tube_count = branch_count * witness.steps_per_branch
    cutoff_count = branch_count * (witness.steps_per_branch - witness.first_cutoff_step)
    _refuse(tube_count > MAX_TUBE_RECORDS, "tube-count-limit")
    for branch_index, branch in enumerate(witness.branches):
        _refuse(type(branch) is not BranchWitness, "branch-record")
        _validate_nat(branch.branch, "branch-order")
        _refuse(branch.branch != branch_index, "branch-order")
        _refuse(type(branch.initial) is not Box, "branch-initial")
        _refuse(type(branch.thrust) is not Interval, "branch-thrust")
        _refuse(type(branch.steps) is not tuple, "steps-record")
        _refuse(len(branch.steps) != witness.steps_per_branch, "step-count")
        for step_index, step in enumerate(branch.steps):
            _refuse(type(step) is not StepWitness, "tube-record")
            _validate_nat(step.branch, "step-order")
            _validate_nat(step.step, "step-order")
            _refuse(step.branch != branch_index or step.step != step_index, "step-order")
            _refuse(type(step.tube) is not Box, "tube-box")
    return branch_count, tube_count, cutoff_count


def _box_tokens(box: Box) -> list[str]:
    answer: list[str] = []
    for value in box.components:
        answer.extend((str(value.lo), str(value.hi)))
    return answer


def encode_witness(witness: BurnWitness) -> bytes:
    branch_count, tube_count, cutoff_count = _validate_witness(witness)
    lines = [MAGIC]
    config = (
        "config",
        str(witness.scale_bits),
        str(witness.step_num),
        str(witness.step_den),
        *(str(value) for value in witness.partition_counts),
        str(witness.steps_per_branch),
        str(witness.first_cutoff_step),
        str(branch_count),
        str(tube_count),
        str(cutoff_count),
    )
    lines.append((" ".join(config) + "\n").encode("ascii"))
    for branch in witness.branches:
        branch_tokens = [
            "branch",
            str(branch.branch),
            *_box_tokens(branch.initial),
            str(branch.thrust.lo),
            str(branch.thrust.hi),
        ]
        lines.append((" ".join(branch_tokens) + "\n").encode("ascii"))
        for step in branch.steps:
            step_tokens = [
                "tube",
                str(step.branch),
                str(step.step),
                *_box_tokens(step.tube),
            ]
            lines.append((" ".join(step_tokens) + "\n").encode("ascii"))
    lines.append(f"end {branch_count} {tube_count} {cutoff_count}\n".encode("ascii"))
    encoded = b"".join(lines)
    _refuse(len(encoded) > MAX_WITNESS_BYTES, "witness-too-large")
    return encoded


def _parse_integer(token: str) -> int:
    if token == "0":
        return 0
    negative = token.startswith("-")
    digits = token[1:] if negative else token
    if not digits or not digits.isascii() or not digits.isdecimal():
        raise WitnessRefusal("noncanonical-integer")
    if digits[0] == "0":
        raise WitnessRefusal("noncanonical-integer")
    if len(digits) > MAX_INTEGER_DIGITS:
        raise WitnessRefusal("integer-digit-limit")
    value = int(token)
    if value == 0:
        raise WitnessRefusal("noncanonical-integer")
    return value


def _parse_nat(token: str, reason: str) -> int:
    value = _parse_integer(token)
    if value < 0:
        raise WitnessRefusal(reason)
    return value


def _parse_box(tokens: list[str]) -> Box:
    if len(tokens) != 10:
        raise WitnessRefusal("box-dimension")
    values = []
    for index in range(0, 10, 2):
        values.append(Interval(_parse_integer(tokens[index]), _parse_integer(tokens[index + 1])))
    return Box(tuple(values))


def decode_witness(encoded: bytes) -> BurnWitness:
    if not isinstance(encoded, bytes):
        raise WitnessRefusal("witness-not-bytes")
    _refuse(len(encoded) > MAX_WITNESS_BYTES, "witness-too-large")
    _refuse(not encoded.endswith(b"\n"), "missing-final-newline")
    _refuse(encoded.count(b"\n") > MAX_WITNESS_RECORDS, "record-count-limit")
    record_start = 0
    while record_start < len(encoded):
        record_end = encoded.find(b"\n", record_start)
        _refuse(record_end < 0, "missing-final-newline")
        _refuse(
            record_end - record_start > MAX_WITNESS_RECORD_CHARS,
            "record-length-limit",
        )
        record_start = record_end + 1
    _refuse(b"\r" in encoded, "noncanonical-line-ending")
    _refuse(
        any(byte < 0x20 and byte != 0x0A for byte in encoded),
        "noncanonical-control-character",
    )
    try:
        text = encoded.decode("ascii")
    except UnicodeDecodeError as exc:
        raise WitnessRefusal("non-ascii") from exc
    lines = text.split("\n")[:-1]
    _refuse(not lines or lines[0] != MAGIC.decode("ascii").rstrip("\n"), "witness-magic")
    _refuse(len(lines) < 3, "missing-terminal")
    config = lines[1].split(" ")
    _refuse(len(config) != 15 or config[0] != "config", "config-record")
    scale_bits = _parse_nat(config[1], "scale-bits")
    step_num = _parse_nat(config[2], "step-rational")
    step_den = _parse_nat(config[3], "step-rational")
    _refuse(
        step_num == 0 or step_den == 0 or gcd(step_num, step_den) != 1,
        "step-rational-not-reduced",
    )
    partition_counts = tuple(_parse_nat(value, "partition-count") for value in config[4:10])
    steps_per_branch = _parse_nat(config[10], "steps-per-branch")
    first_cutoff_step = _parse_nat(config[11], "first-cutoff-step")
    declared_branches = _parse_nat(config[12], "branch-count")
    declared_tubes = _parse_nat(config[13], "tube-count")
    declared_cutoffs = _parse_nat(config[14], "cutoff-count")
    _refuse(declared_branches > MAX_BRANCHES, "branch-count-limit")
    _refuse(declared_tubes > MAX_TUBE_RECORDS, "tube-count-limit")

    cursor = 2
    branches = []
    for branch_index in range(declared_branches):
        if cursor >= len(lines) or lines[cursor].startswith("end "):
            raise WitnessRefusal("branch-count")
        branch_tokens = lines[cursor].split(" ")
        cursor += 1
        _refuse(len(branch_tokens) != 14 or branch_tokens[0] != "branch", "unexpected-record")
        observed_branch = _parse_nat(branch_tokens[1], "branch-order")
        _refuse(observed_branch != branch_index, "branch-order")
        initial = _parse_box(branch_tokens[2:12])
        thrust = Interval(_parse_integer(branch_tokens[12]), _parse_integer(branch_tokens[13]))
        steps = []
        for step_index in range(steps_per_branch):
            if cursor >= len(lines) or lines[cursor].startswith("end "):
                raise WitnessRefusal("step-count")
            step_tokens = lines[cursor].split(" ")
            cursor += 1
            _refuse(len(step_tokens) != 13 or step_tokens[0] != "tube", "unexpected-record")
            step_branch = _parse_nat(step_tokens[1], "step-order")
            observed_step = _parse_nat(step_tokens[2], "step-order")
            _refuse(step_branch != branch_index or observed_step != step_index, "step-order")
            steps.append(StepWitness(branch_index, step_index, _parse_box(step_tokens[3:13])))
        branches.append(BranchWitness(branch_index, initial, thrust, tuple(steps)))

    if cursor >= len(lines):
        raise WitnessRefusal("missing-terminal")
    terminal = lines[cursor].split(" ")
    _refuse(len(terminal) != 4 or terminal[0] != "end", "unexpected-record")
    terminal_counts = tuple(_parse_nat(value, "terminal-count") for value in terminal[1:])
    _refuse(
        terminal_counts != (declared_branches, declared_tubes, declared_cutoffs),
        "terminal-count",
    )
    cursor += 1
    _refuse(cursor != len(lines), "trailing-record")

    witness = BurnWitness(
        scale_bits=scale_bits,
        step_num=step_num,
        step_den=step_den,
        partition_counts=partition_counts,  # type: ignore[arg-type]
        steps_per_branch=steps_per_branch,
        first_cutoff_step=first_cutoff_step,
        branches=tuple(branches),
    )
    branch_count, tube_count, cutoff_count = _validate_witness(witness)
    _refuse(branch_count != declared_branches, "branch-count")
    _refuse(tube_count != declared_tubes, "tube-count")
    _refuse(cutoff_count != declared_cutoffs, "cutoff-count")
    return witness
