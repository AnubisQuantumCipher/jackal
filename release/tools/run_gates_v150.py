#!/usr/bin/env python3
"""v1.5.0 seal-gate driver: runs the full release-readiness suite in order,
captures each command's verdict line, and fails on the FIRST red gate.

This mirrors the mechanical gate list PROVENANCE.md seals record, extended
with the v1.5.0 surfaces.  Not a trust surface — a convenience driver; every
command here can be run by hand.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

GATES: list[tuple[str, list[str], int]] = [
    # (name, argv, timeout_s)
    ("lake-build", ["lake", "build", "JackalIv", "jackal_cert_check",
                    "jackal_gaussian_check", "jackal_parse_dump"], 3600),
    ("proof-identity-range",
     [sys.executable, "release/tools/gaussian_proof_identity.py", "check", "--lane", "range"], 600),
    ("proof-identity-gaussian",
     [sys.executable, "release/tools/gaussian_proof_identity.py", "check", "--lane", "gaussian"], 600),
    ("engine-self-test", ["./jackal", "self-test"], 600),
    ("positive-corpus", [sys.executable, "tests/cert_positive_corpus.py"], 1800),
    ("negative-controls", [sys.executable, "tests/cert_controls.py"], 1800),
    ("aba-mutations", [sys.executable, "tests/cert_aba_mutations.py"], 1800),
    ("mutations-11", [sys.executable, "tests/cert_mutations_11.py"], 3600),
    ("formal-status-gate", [sys.executable, "tests/formal_status_gate_test.py"], 600),
    ("sqrt-rat-release", [sys.executable, "tests/formal_sqrt_rat_release_test.py"], 900),
    ("exp-rat-release", [sys.executable, "tests/formal_exp_rat_release_test.py"], 900),
    ("ln-rat-release", [sys.executable, "tests/formal_ln_rat_release_test.py"], 900),
    ("sin-rat-release", [sys.executable, "tests/formal_sin_rat_release_test.py"], 900),
    ("cos-rat-release", [sys.executable, "tests/formal_cos_rat_release_test.py"], 900),
    ("atan-rat-release", [sys.executable, "tests/formal_atan_rat_release_test.py"], 900),
    ("tanh-rat-release", [sys.executable, "tests/formal_tanh_rat_release_test.py"], 900),
    ("gaussian-emitter", [sys.executable, "tests/formal_gaussian_emitter_test.py"], 900),
    ("gaussian-checker", [sys.executable, "tests/formal_gaussian_checker_test.py"], 900),
    ("gaussian-mutations", [sys.executable, "tests/formal_gaussian_mutations.py"], 1800),
    ("gaussian-receipt", [sys.executable, "tests/formal_gaussian_receipt_test.py"], 1800),
    ("receipt-semantic-mutations", [sys.executable, "tests/receipt_semantic_mutations.py"], 3600),
    ("plugin-smoke", [sys.executable, "tests/plugin_smoke.py"], 3600),
    ("plugin-bundle-identity", [sys.executable, "tests/plugin_bundle_identity_test.py"], 1800),
    ("output-path-safety", [sys.executable, "tests/output_path_safety_test.py"], 600),
    ("fail-closed-sweep", [sys.executable, "tests/fail_closed_sweep.py"], 3600),
    ("exact-lane", [sys.executable, "tests/exact_lane_test.py"], 1800),
    ("seal-audit", [sys.executable, "tests/seal_audit_v150.py"], 1800),
    ("seal-audit-receipts", [sys.executable, "tests/seal_audit_receipts_v150.py"], 900),
    ("exact-verify", [sys.executable, "tests/exact_verify_test.py"], 900),
    ("branch-discontinuity", [sys.executable, "tests/branch_discontinuity_test.py"], 900),
    ("evidence-verify", [sys.executable, "release/verify_evidence.py"], 1800),
    ("black-box-acceptance", [sys.executable, "tests/test_calculator.py"], 3600),
]


def main() -> int:
    only = set(sys.argv[1:])
    results: list[tuple[str, str, float]] = []
    for name, argv, timeout in GATES:
        if only and name not in only:
            continue
        cwd = ROOT / "proofs/lean" if name == "lake-build" else ROOT
        t0 = time.time()
        try:
            p = subprocess.run(argv, cwd=cwd, capture_output=True, text=True,
                               timeout=timeout, env=dict(os.environ))
            ok = p.returncode == 0
        except subprocess.TimeoutExpired:
            ok, p = False, None
        dt = time.time() - t0
        tail = ""
        if p is not None:
            lines = [ln for ln in (p.stdout or "").strip().splitlines() if ln.strip()]
            tail = lines[-1][:150] if lines else (p.stderr or "").strip().splitlines()[-1][:150] if (p.stderr or "").strip() else ""
        results.append((name, "PASS" if ok else "FAIL", dt))
        print(f"{'PASS' if ok else 'FAIL'} {name} ({dt:.0f}s) :: {tail}")
        if not ok:
            if p is not None:
                sys.stdout.write("---- stdout tail ----\n" + (p.stdout or "")[-3000:] + "\n")
                sys.stdout.write("---- stderr tail ----\n" + (p.stderr or "")[-3000:] + "\n")
            print(f"GATES: FAIL at {name}")
            return 1
    print(f"GATES: PASS ({len(results)} gates)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
