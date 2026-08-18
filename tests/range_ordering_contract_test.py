#!/usr/bin/env python3
"""Coherent reversed-interval regression for the public range checker."""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INSTALLED_RUNTIME = (
    Path.home()
    / "Library"
    / "Application Support"
    / "JACKAL"
    / "runtimes"
    / "v1.7.0"
)
CANDIDATE_CHECKER = (
    ROOT / "proofs" / "lean" / ".lake" / "build" / "bin" / "jackal_cert_check"
)
MAX_ARTIFACT_BYTES = 256 * 1024 * 1024
MAX_CERTIFICATE_BYTES = 1024 * 1024
NODE_RE = re.compile(
    rb"node 0 var children\[\] out\[1,2\] name x"
)


class ContractFailure(RuntimeError):
    """Stable test-fixture or execution refusal."""


def read_regular(path: Path, maximum: int = MAX_ARTIFACT_BYTES) -> bytes:
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or before.st_size > maximum:
        raise ContractFailure(f"not a bounded regular file: {path}")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        opened = os.fstat(descriptor)
        if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
            raise ContractFailure(f"path identity changed before read: {path}")
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(descriptor, min(65_536, maximum + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > maximum:
                raise ContractFailure(f"file exceeds byte bound: {path}")
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    current = path.lstat()
    def identity(value: os.stat_result) -> tuple[int, int, int, int, int, int]:
        return (
            value.st_dev,
            value.st_ino,
            value.st_mode,
            value.st_size,
            value.st_mtime_ns,
            value.st_ctime_ns,
        )
    if identity(opened) != identity(after) or identity(after) != identity(current):
        raise ContractFailure(f"file changed while reading: {path}")
    return b"".join(chunks)


def file_sha256(path: Path) -> str:
    return hashlib.sha256(read_regular(path)).hexdigest()


def run_bounded(command: list[str], *, timeout: int = 30) -> subprocess.CompletedProcess:
    return subprocess.run(
        command,
        cwd=ROOT,
        env={"PATH": "/usr/bin:/bin:/usr/sbin:/sbin"},
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
    )


def clean_certificate(producer: Path) -> bytes:
    completed = run_bounded(
        [os.fspath(producer), "range-bound-cert", "x", "1", "2"]
    )
    if completed.returncode != 0:
        raise ContractFailure(
            "producer refused clean fixture: "
            + completed.stderr.decode(errors="replace")[:512]
        )
    certificate = completed.stdout
    if not certificate or len(certificate) > MAX_CERTIFICATE_BYTES:
        raise ContractFailure("producer emitted an empty or over-budget certificate")
    return certificate


def coherent_reversal(certificate: bytes) -> bytes:
    if not certificate.endswith(b"\n"):
        raise ContractFailure("certificate must end in one newline")
    lines = certificate.splitlines()
    expected_exact = {
        b"jackal-eval-cert v2",
        b"model jackal-iv-model-v1",
        b"status bounded",
        b"expr (var x)",
        b"input 1 2",
        b"root 0",
        b"output 1 2",
        b"end",
    }
    if not expected_exact.issubset(set(lines)):
        raise ContractFailure("clean producer fixture has unexpected fixed fields")
    prefixes = [
        b"model ", b"exe ", b"status ", b"expr ", b"source ", b"input ",
        b"root ", b"output ", b"node ",
    ]
    for prefix in prefixes:
        if sum(line.startswith(prefix) for line in lines) != 1:
            raise ContractFailure(f"certificate field is missing or duplicated: {prefix!r}")
    node_index = next(index for index, line in enumerate(lines) if line.startswith(b"node "))
    if NODE_RE.fullmatch(lines[node_index]) is None:
        raise ContractFailure("clean variable-node fixture has unexpected shape")
    replacements = {
        b"input 1 2": b"input 2 1",
        b"output 1 2": b"output 2 1",
        lines[node_index]: b"node 0 var children[] out[2,1] name x",
    }
    mutated = [replacements.get(line, line) for line in lines]
    if sum(left != right for left, right in zip(lines, mutated)) != 3:
        raise ContractFailure("coherent reversal did not alter exactly three fields")
    return b"\n".join(mutated) + b"\n"


def run_checker(checker: Path, certificate: bytes, lo: str, hi: str) -> subprocess.CompletedProcess:
    with tempfile.TemporaryDirectory(prefix="jackal-range-ordering-") as temporary:
        cert_path = Path(temporary) / "certificate.txt"
        cert_path.write_bytes(certificate)
        return run_bounded(
            [
                os.fspath(checker),
                os.fspath(cert_path),
                "range-bound-cert",
                "x",
                lo,
                hi,
            ]
        )


class RangeOrderingContractTests(unittest.TestCase):
    checker = (
        CANDIDATE_CHECKER
        if CANDIDATE_CHECKER.is_file()
        else INSTALLED_RUNTIME / "jackal_cert_check"
    )
    producer = INSTALLED_RUNTIME / "jackal-native"
    wrapper = INSTALLED_RUNTIME / "jackal-cert-release"
    expect_vulnerable = False

    @classmethod
    def setUpClass(cls) -> None:
        for label, path in (
            ("checker", cls.checker),
            ("producer", cls.producer),
            ("wrapper", cls.wrapper),
        ):
            if not path.is_file():
                raise ContractFailure(f"{label} is missing: {path}")
        cls.clean = clean_certificate(cls.producer)
        cls.poison = coherent_reversal(cls.clean)

    def test_clean_ordered_control_accepts(self) -> None:
        completed = run_checker(self.checker, self.clean, "1", "2")
        self.assertEqual(completed.returncode, 0, completed.stderr.decode())
        self.assertEqual(
            completed.stdout,
            b"ACCEPT request-bound theorem=request_bound_certified_release "
            b"command=range-bound-cert output 1 2\n",
        )

    def test_coherent_reversed_interval_contract(self) -> None:
        completed = run_checker(self.checker, self.poison, "2", "1")
        combined = completed.stdout + completed.stderr
        if self.expect_vulnerable:
            self.assertEqual(completed.returncode, 0, completed.stderr.decode())
            self.assertIn(b"ACCEPT request-bound", completed.stdout)
            self.assertIn(b"output 2 1", completed.stdout)
        else:
            self.assertNotEqual(completed.returncode, 0)
            self.assertIn(b"REJECT", combined)
            self.assertIn(b"interval-order", combined)
            self.assertNotIn(b"ACCEPT", combined)

    def test_outer_release_wrapper_remains_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="jackal-range-wrapper-") as temporary:
            receipt = Path(temporary) / "receipt.json"
            completed = run_bounded(
                [os.fspath(self.wrapper), "x", "2", "1", os.fspath(receipt)]
            )
            self.assertNotEqual(completed.returncode, 0)
            self.assertIn(b"status=refused", completed.stdout + completed.stderr)
            self.assertIn(b"requires lo <= hi", completed.stdout + completed.stderr)
            self.assertFalse(receipt.exists())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expect-vulnerable", action="store_true")
    parser.add_argument(
        "--checker",
        type=Path,
        default=(
            CANDIDATE_CHECKER
            if CANDIDATE_CHECKER.is_file()
            else INSTALLED_RUNTIME / "jackal_cert_check"
        ),
    )
    parser.add_argument(
        "--producer", type=Path, default=INSTALLED_RUNTIME / "jackal-native"
    )
    parser.add_argument(
        "--wrapper", type=Path, default=INSTALLED_RUNTIME / "jackal-cert-release"
    )
    arguments, remaining = parser.parse_known_args()
    RangeOrderingContractTests.checker = arguments.checker.resolve()
    RangeOrderingContractTests.producer = arguments.producer.resolve()
    RangeOrderingContractTests.wrapper = arguments.wrapper.resolve()
    RangeOrderingContractTests.expect_vulnerable = arguments.expect_vulnerable
    print(
        "range_ordering_contract "
        f"checker_sha256={file_sha256(RangeOrderingContractTests.checker)} "
        f"producer_sha256={file_sha256(RangeOrderingContractTests.producer)} "
        f"wrapper_sha256={file_sha256(RangeOrderingContractTests.wrapper)} "
        f"expect_vulnerable={str(arguments.expect_vulnerable).lower()}"
    )
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(
        RangeOrderingContractTests
    )
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if remaining:
        raise ContractFailure(f"unexpected arguments: {remaining}")
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
