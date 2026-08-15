#!/usr/bin/env python3
"""JACKAL v1.4.1 fail-closed sweep.

Confirms every load-bearing surface — the release wrapper, the Hermes plugin,
and the independent receipt verifier — refuses with a stable class for every
poison in the roster and NEVER emits ``formal-*`` under any of them.

Rows covered:

* Wrapper (`jackal-cert-release`) x 7 unsupported / malformed requests:
    exp / sqrt / tan / mod / 1/x-through-zero / negative-power / hi<lo.
* Plugin (`plugin/hermes/server.py call jackal_range_bound`) x same 7.
* Verifier (`tools/receipt_verify.py`) x 7 semantic-tamper receipts:
    request.expression / request.input_hi / result.enclosure_hi /
    identities.evaluator / theorem.id / fragment.expression_operators /
    certificate.sha256.

Emits `release/evidence/fail_closed_sweep.jsonl` with a per-row transcript
and a SHA-256 footer.  Exit 0 iff every row refuses (never bounded), the
sweep is 21/21.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "release" / "evidence" / "fail_closed_sweep.jsonl"

sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "plugin" / "hermes"))
import release_validate as rv  # noqa: E402
from formal_receipt import recompute_receipt_digest  # noqa: E402

MANIFEST = ROOT / "release" / "MANIFEST.sha256"


def _pinned() -> tuple[str, str]:
    ev = ck = ""
    for ln in MANIFEST.read_text().splitlines():
        parts = ln.split()
        if len(parts) >= 3 and parts[0] == "evaluator":
            ev = parts[-1]
        elif len(parts) >= 3 and parts[0] == "checker":
            ck = parts[-1]
    return ev, ck


EV, CK = _pinned()
PLUGIN = ROOT / "plugin" / "hermes" / "jackal_hermes"
WRAPPER = ROOT / "jackal-cert-release"
CHECKER = ROOT / "proofs" / "lean" / ".lake" / "build" / "bin" / "jackal_cert_check"
SOURCE_ID = hashlib.sha256((ROOT / "jackal_calc.anb").read_bytes()).hexdigest()
RANGE_PROOF = ROOT / "release" / "evidence" / "range_proof_identity.json"
RANGE_PROOF_FILE_ID = hashlib.sha256(RANGE_PROOF.read_bytes()).hexdigest()
RANGE_PROOF_DIGEST = json.loads(RANGE_PROOF.read_text())["identity_digest_sha256"]
INVENTORY_ID = hashlib.sha256((ROOT / "release" / "coverage" /
                               "formal_coverage_inventory.json").read_bytes()).hexdigest()


WRAPPER_CASES = [
    ("wrapper-transcendental",   "exp(x)",  "0", "1"),
    ("wrapper-sqrt",             "sqrt(x)", "1", "2"),
    ("wrapper-tan",              "tan(x)",  "0", "1"),
    ("wrapper-mod",              "x % 2",   "1", "2"),
    ("wrapper-divzero",          "1/x",     "-1", "1"),
    ("wrapper-neg-power",        "x^(-2)",  "1", "2"),
    ("wrapper-hi-lt-lo",         "x",       "3", "1"),
]


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _classify_stderr_stdout(err: str, out: str) -> str:
    for tok in (err or "").split() + (out or "").split():
        if tok.startswith("reason="):
            return tok.split("=", 1)[1]
    return ""


def _run(argv: list[str]) -> tuple[int, str, str]:
    cp = subprocess.run(argv, capture_output=True, text=True, timeout=120)
    return cp.returncode, cp.stdout, cp.stderr


def sweep_wrapper() -> list[dict]:
    rows = []
    with tempfile.TemporaryDirectory(prefix="jackal-refusal-sweep-") as td:
        for tag, expr, lo, hi in WRAPPER_CASES:
            receipt = Path(td) / f"{tag}.json"
            code, out, err = _run([str(WRAPPER), expr, lo, hi, str(receipt)])
            formal_leak = "formal-" in out
            reason = _classify_stderr_stdout(err, out)
            ok = code != 0 and not formal_leak and not receipt.exists()
            rows.append({"surface": "wrapper", "id": tag, "exit": code,
                         "reason": reason, "formal_leak": formal_leak, "ok": ok})
    return rows


def sweep_plugin() -> list[dict]:
    rows = []
    for tag, expr, lo, hi in WRAPPER_CASES:
        code, out, err = _run([str(PLUGIN), "call", "jackal_range_bound",
                                json.dumps({"expression": expr, "input_lo": lo, "input_hi": hi})])
        try:
            obj = json.loads(out)
        except Exception:  # noqa: BLE001
            obj = {}
        formal_leak = obj.get("status") == "formal-bounded"
        ok = code != 0 and obj.get("status") == "refused" and not formal_leak
        rows.append({"surface": "plugin", "id": tag.replace("wrapper", "plugin"),
                     "exit": code, "reason": obj.get("reason", ""),
                     "formal_leak": formal_leak, "ok": ok})
    return rows


def _fresh_receipt() -> dict:
    with tempfile.TemporaryDirectory() as td:
        p = os.path.join(td, "r.json")
        rv.validate_release(expr="x^2+1", lo="1", hi="2",
                            evaluator="jackal-native", checker=str(CHECKER),
                            expected_evaluator=EV, expected_checker=CK,
                            formal_receipt_path=p, release_epoch="v1.3.0")
        return json.loads(Path(p).read_text())


def _run_verifier(receipt: dict, extra: list[str] | None = None) -> tuple[int, str]:
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(receipt, f)
        p = f.name
    try:
        code, out, err = _run([str(ROOT / "jackal-receipt-verify"),
                                "--receipt", p,
                                "--checker", str(CHECKER),
                                "--expected-evaluator", EV,
                                "--expected-checker", CK,
                                "--expected-source", SOURCE_ID,
                                "--expected-release-epoch", "v1.3.0",
                                "--expected-command", "range-bound-cert",
                                "--expected-expression", "x^2+1",
                                "--expected-input-lo", "1",
                                "--expected-input-hi", "2",
                                "--proof-identity", str(ROOT / "release" / "evidence" /
                                                         "range_proof_identity.json"),
                                "--expected-proof-identity-file", RANGE_PROOF_FILE_ID,
                                "--expected-proof-identity-digest", RANGE_PROOF_DIGEST,
                                "--expected-inventory", INVENTORY_ID,
                                "--inventory", str(ROOT / "release" / "coverage" /
                                                    "formal_coverage_inventory.json")] +
                               (extra or []))
    finally:
        os.unlink(p)
    return code, _classify_stderr_stdout(err, out)


def sweep_verifier(r0: dict) -> list[dict]:
    def tamper(path: list[str], new) -> dict:
        r = copy.deepcopy(r0)
        obj = r
        for k in path[:-1]:
            obj = obj[k]
        obj[path[-1]] = new
        r["receipt_digest_sha256"] = recompute_receipt_digest(r)
        return r

    cases = [
        ("verifier-request-expression",    ["request", "expression"],   "y^2+1"),
        ("verifier-request-input-hi",      ["request", "input_hi"],     "9"),
        ("verifier-result-enclosure-hi",   ["result", "enclosure_hi"],  "9999"),
        ("verifier-identity-evaluator",    ["identities", "evaluator_sha256"], "0" * 64),
        ("verifier-theorem-id",            ["theorem", "id"],           "fake_theorem"),
        ("verifier-fragment-ops",          ["fragment", "expression_operators"],
                                            sorted(list(r0["fragment"]["expression_operators"]) + ["sin"])),
        ("verifier-cert-sha256",           ["certificate", "sha256"],   "0" * 64),
    ]
    rows = []
    for tag, path, new in cases:
        r = tamper(path, new)
        code, reason = _run_verifier(r)
        ok = code != 0 and bool(reason)
        rows.append({"surface": "verifier", "id": tag, "exit": code,
                     "reason": reason, "formal_leak": False, "ok": ok})
    return rows


def main() -> int:
    rows: list[dict] = []
    rows.extend(sweep_wrapper())
    rows.extend(sweep_plugin())
    rows.extend(sweep_verifier(_fresh_receipt()))
    EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE.write_text("\n".join(json.dumps(r, sort_keys=True) for r in rows) + "\n")
    for r in rows:
        print(f"{'ok' if r['ok'] else 'LEAK':>4}  {r['surface']}/{r['id']:32s} "
              f"exit={r['exit']} reason={r['reason']!r}")
    ok = sum(1 for r in rows if r["ok"])
    print(f"evidence={EVIDENCE} sha256={sha(EVIDENCE.read_bytes())}")
    if ok != len(rows):
        print(f"VERDICT: FAIL — {len(rows) - ok} row(s) did not refuse cleanly", file=sys.stderr)
        return 1
    print(f"VERDICT: PASS — {ok}/{len(rows)} rows refused; NEVER a formal-* leak")
    return 0


if __name__ == "__main__":
    sys.exit(main())
