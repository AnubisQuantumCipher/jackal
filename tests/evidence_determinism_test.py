#!/usr/bin/env python3
"""Deterministic-evidence regression gate (v1.6, additive).

Guards the repair recorded in PROVENANCE.md §"deterministic-evidence
repair": durable evidence transcripts must be run-to-run reproducible
from identical engine/checker bytes, and must never re-acquire
host-volatile identifiers (thread ids, random temp paths).

Checks:
  1. `tests/seal_audit_v150.py` runs green twice; the two runs emit
     byte-identical `release/evidence/seal_audit_v150.json`.
  2. `tests/seal_audit_receipts_v150.py` runs green twice; byte-identical
     `release/evidence/seal_audit_receipts_v150.json`.
  3. Neither evidence file contains a volatile pattern:
     `thread '<...>' (<digits>)`, `/var/folders/...`, or a random
     `/tmp/...` sandbox path.

This gate does not change what either audit accepts; it re-runs them
verbatim and compares bytes.  Evidence files are left in their final
(identical) state.
"""
from __future__ import annotations

import hashlib
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

BATTERIES = [
    ("seal-audit", "tests/seal_audit_v150.py",
     ROOT / "release/evidence/seal_audit_v150.json"),
    ("seal-audit-receipts", "tests/seal_audit_receipts_v150.py",
     ROOT / "release/evidence/seal_audit_receipts_v150.json"),
]

VOLATILE_PATTERNS = [
    re.compile(r"thread '[^']*' \(\d+\)"),
    re.compile(r"/private/var/folders/"),
    re.compile(r"(?<!<)/var/folders/"),
    re.compile(r"/tmp/[A-Za-z0-9._-]*tmp[A-Za-z0-9._-]{4,}"),
]


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main() -> int:
    failures = 0
    for name, script, evidence in BATTERIES:
        hashes: list[str] = []
        for attempt in (1, 2):
            p = subprocess.run([sys.executable, str(ROOT / script)],
                               cwd=ROOT, capture_output=True, text=True,
                               timeout=1800)
            if p.returncode != 0:
                print(f"FAIL {name} run{attempt}: rc={p.returncode} "
                      f"{(p.stdout or p.stderr)[-200:]}")
                failures += 1
                break
            hashes.append(sha(evidence))
        else:
            if hashes[0] != hashes[1]:
                print(f"FAIL {name}: nondeterministic evidence "
                      f"run1={hashes[0][:16]} run2={hashes[1][:16]}")
                failures += 1
            else:
                print(f"PASS {name}: two runs byte-identical "
                      f"sha256={hashes[0][:16]}…")
        text = evidence.read_text()
        vol = [pat.pattern for pat in VOLATILE_PATTERNS if pat.search(text)]
        if vol:
            print(f"FAIL {name}: volatile patterns present: {vol}")
            failures += 1
        else:
            print(f"PASS {name}: no volatile identifiers in evidence")
    print(f"EVIDENCE_DETERMINISM_{'PASS' if not failures else 'FAIL'} "
          f"failures={failures}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
