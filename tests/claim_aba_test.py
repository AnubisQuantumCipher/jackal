#!/usr/bin/env python3
"""A→B→A tamper gates for the claim-kernel trust layers (mission §14.7).

For each of the seven trust layers — canonicalizer, inference registry,
policy evaluation, legacy evidence adapter, unit registry, machine
verifier, renderer — this gate:

  A. records the exact source bytes/hash and confirms the designated
     control case passes;
  B. applies ONE compiling, runnable semantic poison that would launder
     or misbind a claim, re-runs the hostile matrix, and REQUIRES the
     designated case to fail for the intended reason;
  A. restores byte-identical originals, re-runs green, and records
     hashes, outputs, and refusal codes.

No poison bytes remain in the tree: restoration is verified by hash, and
the only regenerated artifact (claim_hostile_matrix_v160.json) is
rewritten by the final green run.

Writes durable evidence to release/evidence/claim_aba_v160.json.

Run: python3 tests/claim_aba_test.py
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERIFIER = ROOT / "tools/claim_bundle_verify.py"
INF_REG = ROOT / "release/claim/inference_registry_v1.json"
UNIT_REG = ROOT / "release/claim/unit_registry_v1.json"
HOSTILE = ROOT / "tests/claim_hostile_test.py"
MATRIX_EVIDENCE = ROOT / "release/evidence/claim_hostile_matrix_v160.json"
EVIDENCE_OUT = ROOT / "release/evidence/claim_aba_v160.json"

ROWS: list[dict] = []


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def run_matrix() -> tuple[bool, dict[str, dict]]:
    proc = subprocess.run([sys.executable, str(HOSTILE)],
                          capture_output=True, text=True, timeout=1800,
                          cwd=ROOT)
    rows: dict[str, dict] = {}
    if MATRIX_EVIDENCE.exists():
        doc = json.loads(MATRIX_EVIDENCE.read_text())
        rows = {r["id"]: r for r in doc.get("rows", [])}
    return proc.returncode == 0, rows


LAYERS = [
    {
        "layer": "canonicalizer",
        "file": VERIFIER,
        "poison": ('return json.dumps(obj, sort_keys=True, '
                   'separators=(",", ":"),',
                   'return json.dumps(obj, sort_keys=True, '
                   'separators=(",", ": "),'),
        "case": "S-pos-baseline",
        "intent": "whitespace-divergent canonical bytes break every "
                  "content address and digest recomputation",
    },
    {
        "layer": "inference-registry",
        "file": INF_REG,
        "poison": ('"interval_add": {\n      "parents": [2, 2],\n'
                   '      "params_keys": [],\n'
                   '      "mathematical_cap": "bounded"',
                   '"interval_add": {\n      "parents": [2, 2],\n'
                   '      "params_keys": [],\n'
                   '      "mathematical_cap": null'),
        "case": "S-pos-baseline",
        "intent": "widening a rule cap in the shipped registry must be "
                  "caught by the verifier's embedded semantic cross-check",
    },
    {
        "layer": "policy-evaluation",
        "file": VERIFIER,
        "poison": ('if a[axis] not in accept[axis]:',
                   'if False and a[axis] not in accept[axis]:'),
        "case": "L-fallback-disabled-policy",
        "intent": "skipping the axis accept-set turns policy refusals "
                  "into silent acceptance",
    },
    {
        "layer": "legacy-evidence-adapter",
        "file": VERIFIER,
        "poison": ('"lo": result["enclosure_lo"],',
                   '"lo": "0",'),
        "case": "LEG-pos-receipt",
        "intent": "misbinding the receipt enclosure into the derived "
                  "proposition launders the formal bound",
    },
    {
        "layer": "unit-registry",
        "file": UNIT_REG,
        "poison": ('"cm":    {"dim": [0, 1, 0, 0, 0, 0, 0], '
                   '"scale": "1/100"',
                   '"cm":    {"dim": [0, 1, 0, 0, 0, 0, 0], '
                   '"scale": "1/10"'),
        "case": "U-pos-linear-convert",
        "intent": "a forged scale factor must surface as a rule "
                  "recompute divergence",
    },
    {
        "layer": "machine-verifier",
        "file": VERIFIER,
        "poison": ('overflow = math != machine',
                   'overflow = False'),
        "case": "M-pos-checked-overflow-fact",
        "intent": "suppressing overflow recomputation would accept "
                  "false checked-arithmetic claims",
    },
    {
        "layer": "renderer",
        "file": VERIFIER,
        "poison": ("        f\"input provenance {a['input_provenance']}\",\n",
                   ""),
        "case": "R-pos-conditions-present",
        "intent": "dropping the provenance condition from the permitted "
                  "rendering hides a load-bearing axis",
    },
]


def main() -> int:
    failures = 0
    ok0, rows0 = run_matrix()
    if not ok0:
        print("FAIL pre-flight: hostile matrix not green before A-B-A")
        return 1
    print(f"PASS pre-flight green ({len(rows0)} rows)")

    for spec in LAYERS:
        layer = spec["layer"]
        path: Path = spec["file"]
        original = path.read_bytes()
        sha_a = sha(path)
        old, new = spec["poison"]
        text = original.decode("utf-8")
        if text.count(old) != 1:
            print(f"FAIL {layer}: poison anchor count "
                  f"{text.count(old)} != 1")
            failures += 1
            continue
        path.write_bytes(text.replace(old, new, 1).encode("utf-8"))
        sha_b = sha(path)
        ok_b, rows_b = run_matrix()
        case = rows_b.get(spec["case"], {})
        case_failed = case.get("ok") is False
        observed = case.get("observed", "<case missing>")
        poisoned_detected = (not ok_b) and case_failed
        path.write_bytes(original)
        sha_r = sha(path)
        restored = sha_r == sha_a
        status = poisoned_detected and restored
        ROWS.append({
            "layer": layer,
            "intent": spec["intent"],
            "designated_case": spec["case"],
            "sha_a": sha_a,
            "sha_poisoned": sha_b,
            "sha_restored": sha_r,
            "matrix_failed_under_poison": not ok_b,
            "case_failed_under_poison": case_failed,
            "observed_under_poison": str(observed)[:400],
            "restored_byte_identical": restored,
            "ok": status,
        })
        print(f"{'PASS' if status else 'FAIL'} A-B-A {layer}: "
              f"case={spec['case']} observed={str(observed)[:80]} "
              f"restored={restored}")
        if not status:
            failures += 1

    ok_final, rows_final = run_matrix()
    print(f"{'PASS' if ok_final else 'FAIL'} post-restore green "
          f"({len(rows_final)} rows)")
    if not ok_final:
        failures += 1

    doc = {
        "schema": "jackal-claim-aba-v1",
        "release_epoch": "v1.6.0",
        "verifier_sha256": sha(VERIFIER),
        "inference_registry_sha256": sha(INF_REG),
        "unit_registry_sha256": sha(UNIT_REG),
        "layers": ROWS,
        "post_restore_green": ok_final,
        "verdict": "PASS" if not failures else "FAIL",
    }
    EVIDENCE_OUT.write_text(json.dumps(doc, indent=2, sort_keys=True)
                            + "\n")
    print(f"evidence={EVIDENCE_OUT}")
    print(f"CLAIM_ABA_{'PASS' if not failures else 'FAIL'} "
          f"layers={len(ROWS)} failures={failures}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
