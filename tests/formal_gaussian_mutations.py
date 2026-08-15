#!/usr/bin/env python3
"""Fail-closed mutation controls for the Gaussian formal checker."""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PRODUCER = ROOT / "tools" / "gaussian_certificate.py"
CHECKER = ROOT / "proofs" / "lean" / ".lake" / "build" / "bin" / "jackal_gaussian_check"
EXPR = "exp(-10000000000*(x-0.5000123456789)^2)"


def produce() -> str:
    completed = subprocess.run(
        [
            sys.executable,
            str(PRODUCER),
            "emit",
            "--expression",
            EXPR,
            "--lower",
            "0",
            "--upper",
            "1",
            "--tolerance",
            "1/1000000000000",
        ],
        text=True,
        capture_output=True,
        check=True,
        timeout=30,
    )
    return completed.stdout


def replace_line(cert: str, prefix: str, replacement: str) -> str:
    lines = cert.splitlines()
    hits = [index for index, line in enumerate(lines) if line.startswith(prefix)]
    if len(hits) != 1:
        raise RuntimeError(f"expected one {prefix!r} line, found {len(hits)}")
    lines[hits[0]] = replacement
    return "\n".join(lines) + "\n"


def accepted(cert: str) -> bool:
    with tempfile.NamedTemporaryFile("w", suffix=".gcert", delete=False) as handle:
        handle.write(cert)
        path = Path(handle.name)
    try:
        completed = subprocess.run(
            [str(CHECKER), str(path)], text=True, capture_output=True, timeout=30
        )
    finally:
        path.unlink(missing_ok=True)
    return completed.returncode == 0


def main() -> int:
    cert = produce()
    if not accepted(cert):
        print("FAIL baseline certificate rejected")
        return 1

    mutations = {
        "magic": cert.replace("jackal-gaussian-integral-cert v1", "jackal-gaussian-integral-cert v2", 1),
        "operation": replace_line(cert, "operation ", "operation range"),
        "assurance": replace_line(cert, "assurance ", "assurance bounded"),
        "family": replace_line(cert, "family ", "family arbitrary-expression-v1"),
        "expression": replace_line(cert, "expression ", "expression exp(-10000000000*(x-0.5)^2)"),
        "amplitude-token": replace_line(cert, "A-token ", "A-token 10000000001"),
        "mu-token": replace_line(cert, "mu-token ", "mu-token 0.5000123456788"),
        "scale": replace_line(cert, "scale ", "scale 99999"),
        "method": replace_line(cert, "method ", "method gaussian-unchecked-v1"),
        "core": replace_line(cert, "core ", "core 5"),
        "degree": replace_line(cert, "degree ", "degree 95"),
        "sqrt-pi-lower": replace_line(cert, "sqrt-pi-lower ", "sqrt-pi-lower 177245385090552/100000000000000"),
        "sqrt-pi-upper": replace_line(cert, "sqrt-pi-upper ", "sqrt-pi-upper 177245385090551/100000000000000"),
        "output": replace_line(cert, "output ", "output 0 0"),
        "missing-final-newline": cert.rstrip("\n"),
        "extra-line": cert.replace("end\n", "junk\nend\n", 1),
    }

    failures = []
    for name, mutated in mutations.items():
        if accepted(mutated):
            failures.append(name)
            print(f"FAIL mutation accepted: {name}")
        else:
            print(f"PASS mutation rejected: {name}")

    unsupported = subprocess.run(
        [
            sys.executable,
            str(PRODUCER),
            "emit",
            "--expression",
            "exp(x)",
            "--lower",
            "0",
            "--upper",
            "1",
            "--tolerance",
            "1/1000",
        ],
        text=True,
        capture_output=True,
        timeout=30,
    )
    if unsupported.returncode == 0 or "REFUSED" not in unsupported.stderr:
        failures.append("unsupported-producer-request")
        print("FAIL unsupported producer request did not refuse")
    else:
        print("PASS unsupported producer request refused")

    if failures:
        print(f"GAUSSIAN_MUTATIONS_FAIL count={len(failures)} names={','.join(failures)}")
        return 1
    print(f"GAUSSIAN_MUTATIONS_PASS rejected={len(mutations)} unsupported=1")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
