#!/usr/bin/env python3
"""v1.6.0 aggregate seal-gate driver (additive).

Invokes EVERY v1.5.0 gate — imported verbatim from run_gates_v150.py,
which remains the untouched v1.5 regression driver — plus the v1.6.0
claim-kernel gates:

    compat-floor          mechanical v1.5 surface preservation (31 tools,
                          32 gate names, 93 engine commands, variants,
                          coverage rows, wrappers)
    evidence-determinism  seal-audit batteries re-run twice to identical
                          bytes; volatile identifiers forbidden
    claim-hostile         the full hostile semantic matrix (108 rows)
    claim-dogfood         ten end-to-end mixed claim graphs (16 rows)
    claim-aba             A->B->A tamper gates over the seven claim
                          trust layers
    claim-package-parity  double-build byte equality, fresh extraction,
                          every tool exercised, three-way parity

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

GATES_V160: list[tuple[str, list[str], int]] = [
    ("compat-floor",
     [sys.executable, "tools/compat_floor.py", "--check"], 600),
    ("evidence-determinism",
     [sys.executable, "tests/evidence_determinism_test.py"], 1800),
    ("claim-hostile",
     [sys.executable, "tests/claim_hostile_test.py"], 1800),
    ("claim-dogfood",
     [sys.executable, "tests/claim_dogfood_test.py"], 1800),
    ("claim-aba",
     [sys.executable, "tests/claim_aba_test.py"], 3600),
    ("claim-package-parity",
     [sys.executable, "tests/claim_package_parity_test.py"], 3600),
]

GATES = list(GATES_V150) + GATES_V160


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
