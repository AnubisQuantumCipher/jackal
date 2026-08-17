#!/usr/bin/env python3
"""v1.7.0 aggregate seal-gate driver (additive).

Invokes EVERY v1.5.0 gate and EVERY v1.6.0 gate — imported verbatim from
run_gates_v150.py and run_gates_v160.py, which remain the untouched
regression drivers for their epochs — plus the v1.7.0 certified
composed-integral gates:

    int-cert-matrix          positive/negative certificate matrix for the
                             integrate-bound-cert lane (theorem
                             int_cert_sound, checker jackal_int_cert_check)
    int-cert-aba             A->B->A tamper gates over the int-cert
                             producer/checker/receipt trust layers
    int-cert-differential    certified lane vs engine float integrate-bound
                             lane differential (the float lane stays
                             visibly weaker; no silent escalation)
    int-cert-release         end-to-end release binder + wrapper gate
                             (int_cert_release.py, jackal-int-cert-release)
    proof-identity-int-cert  committed int_cert_proof_identity.json record
                             re-verified against the compiled checker

v1.7.0 = 43 gates total (32 v1.5.0 + 6 v1.6.0 + 5 v1.7.0).

Not a trust surface — a convenience driver; every command can be run by
hand.  Fails on the FIRST red gate.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "release/tools"))

from run_gates_v150 import GATES as GATES_V150  # noqa: E402
from run_gates_v160 import GATES_V160  # noqa: E402

GATES_V170: list[tuple[str, list[str], int]] = [
    ("int-cert-matrix",
     [sys.executable, "tests/int_cert_matrix_test.py"], 1800),
    ("int-cert-aba",
     [sys.executable, "tests/int_cert_aba_test.py"], 3600),
    ("int-cert-differential",
     [sys.executable, "tests/int_cert_differential.py"], 1800),
    ("int-cert-release",
     [sys.executable, "tests/int_cert_release_test.py"], 1800),
    ("proof-identity-int-cert",
     [sys.executable, "release/tools/gaussian_proof_identity.py",
      "check", "--lane", "int-cert"], 1800),
]

GATES = list(GATES_V150) + GATES_V160 + GATES_V170


def main() -> int:
    only = set(sys.argv[1:])
    results: list[tuple[str, str, float]] = []
    for name, argv, timeout in GATES:
        if only and name not in only:
            continue
        cwd = ROOT / "proofs/lean" if name == "lake-build" else ROOT
        t0 = time.time()
        try:
            p = subprocess.run(argv, cwd=cwd, capture_output=True,
                               text=True, timeout=timeout,
                               env=dict(os.environ))
            ok = p.returncode == 0
        except subprocess.TimeoutExpired:
            ok, p = False, None
        dt = time.time() - t0
        tail = ""
        if p is not None:
            lines = [ln for ln in (p.stdout or "").strip().splitlines()
                     if ln.strip()]
            tail = lines[-1][:150] if lines else \
                (p.stderr or "").strip().splitlines()[-1][:150] \
                if (p.stderr or "").strip() else ""
        results.append((name, "PASS" if ok else "FAIL", dt))
        print(f"{'PASS' if ok else 'FAIL'} {name} ({dt:.0f}s) :: {tail}")
        if not ok:
            if p is not None:
                sys.stdout.write("---- stdout tail ----\n"
                                 + (p.stdout or "")[-3000:] + "\n")
                sys.stdout.write("---- stderr tail ----\n"
                                 + (p.stderr or "")[-3000:] + "\n")
            print(f"GATES: FAIL at {name}")
            return 1
    print(f"GATES: PASS ({len(results)} gates)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
