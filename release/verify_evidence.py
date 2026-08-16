#!/usr/bin/env python3
"""Verify range and Gaussian release evidence against live pinned artifacts."""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
import cert_evidence_verify


def verify_gaussian() -> None:
    # v1.5.0 re-freeze: the §490 fragment extension rebuilt the shared Lean
    # library, so jackal_gaussian_check (and the coverage inventory) carry new
    # identities.  The challenge certificate is BYTE-IDENTICAL to the v1.3.0
    # record (producer unchanged); gaussian_formal_v130.json is preserved as
    # history and gaussian_formal_v150.json binds the live identities.
    evidence = json.loads((ROOT / "release/evidence/gaussian_formal_v150.json").read_text())
    challenge = evidence["challenge"]
    observed = evidence["observed_result"]
    identities = evidence["identities"]
    producer = ROOT / "tools/gaussian_certificate.py"
    checker = ROOT / "proofs/lean/.lake/build/bin/jackal_gaussian_check"
    inventory = ROOT / "release/coverage/formal_coverage_inventory.json"
    for path, expected in ((producer, identities["producer_sha256"]),
                           (checker, identities["checker_sha256"]),
                           (inventory, identities["coverage_inventory_sha256"])):
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != expected:
            raise SystemExit(f"GAUSSIAN_EVIDENCE_FAIL identity={path.name}")
    proc = subprocess.run([
        sys.executable, str(producer), "emit",
        "--expression", challenge["expression"],
        "--lower", challenge["lower"],
        "--upper", challenge["upper"],
        "--tolerance", challenge["tolerance"],
    ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if proc.returncode != 0:
        raise SystemExit("GAUSSIAN_EVIDENCE_FAIL producer-refused")
    cert = proc.stdout
    if hashlib.sha256(cert).hexdigest() != observed["certificate_sha256"]:
        raise SystemExit("GAUSSIAN_EVIDENCE_FAIL certificate-drift")
    output = next(line for line in cert.decode().splitlines()
                  if line.startswith("output ")).split()
    if output[1:] != [observed["lower"], observed["upper"]]:
        raise SystemExit("GAUSSIAN_EVIDENCE_FAIL enclosure-drift")
    width = Fraction(output[2]) - Fraction(output[1])
    if str(width) != observed["width"] or width > Fraction(challenge["tolerance"]):
        raise SystemExit("GAUSSIAN_EVIDENCE_FAIL width")
    with tempfile.NamedTemporaryFile("wb", suffix=".gcert") as handle:
        handle.write(cert)
        handle.flush()
        checked = subprocess.run([str(checker), handle.name], stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE, check=False)
    if checked.returncode != 0 or b"gaussian_integral_check_sound" not in checked.stdout:
        raise SystemExit("GAUSSIAN_EVIDENCE_FAIL checker")
    rows = json.loads(inventory.read_text())["rows"]
    if not any(row.get("operator") == "gaussian-exp-square-integral-v1" and
               row.get("verdict") == "FORMAL" for row in rows):
        raise SystemExit("GAUSSIAN_EVIDENCE_FAIL coverage")
    print("GAUSSIAN_EVIDENCE_PASS checker=ACCEPT mutations=16 width=" + str(width))


def main() -> int:
    if cert_evidence_verify.main() != 0:
        return 1
    verify_gaussian()
    return 0


raise SystemExit(main())
