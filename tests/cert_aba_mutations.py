#!/usr/bin/env python3
"""JACKAL v1.0.4 semantic A→B→A mutation harness (mission §471).

Two mandatory mutations, each disabling ONE governing gate in the shared
validator while it still compiles and runs:

  M1 — request-commitment binding gate.
  M2 — evaluator-identity binding gate.

For each: A(pre) a poison refuses; B the SAME poison is incorrectly admitted
by the mutated (still-runnable) code, so the governing gate is RED for exactly
that reason; A(post) the EXACT pre-mutation bytes are restored (hash-verified),
the poison refuses again, and stale artifacts are purged. A compile error,
stale binary, or crash is NOT a valid B. Writes a durable transcript to
release/evidence/aba_mutations.json (parsed by control C30).
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = ROOT / "tests/release_validate.py"
EVALUATOR = ROOT / "jackal-native"
CHECKER = ROOT / "proofs/lean/.lake/build/bin/jackal_cert_check"
EVIDENCE = ROOT / "release/evidence/aba_mutations.json"
sys.path.insert(0, str(ROOT / "tests"))
import release_validate as rv  # noqa: E402


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def manifest_ids():
    ev = ck = ""
    for ln in (ROOT / "release/MANIFEST.sha256").read_text().splitlines():
        if ln.startswith("evaluator "):
            ev = ln.split()[2]
        if ln.startswith("checker "):
            ck = ln.split()[2]
    return ev, ck


EVAL_ID, CHK_ID = manifest_ids()


def make_cert(expr, lo, hi, forge_source=False):
    req = rv.request_commitment_b64(rv.COMMAND_ID, expr, lo, hi)
    cp = subprocess.run([str(EVALUATOR), "range-bound-cert", expr, lo, hi, EVAL_ID, req],
                        capture_output=True, text=True, timeout=3600)
    if cp.returncode != 0:
        raise RuntimeError(cp.stderr)
    text = cp.stdout
    if forge_source:
        lines = text.split("\n")
        for i, ln in enumerate(lines):
            if ln.startswith("source "):
                lines[i] = "source " + base64.b64encode(b"FORGED-REQUEST").decode()
                break
        text = "\n".join(lines)
    return text


def run_validate_cert(cert_text, expr, lo, hi, expected_eval=None):
    with tempfile.NamedTemporaryFile("w", suffix=".cert", delete=False) as f:
        f.write(cert_text)
        p = f.name
    try:
        cp = subprocess.run(
            [sys.executable, str(VALIDATOR), "--cert", p, "--expr", expr,
             "--lo", lo, "--hi", hi, "--evaluator", str(EVALUATOR),
             "--checker", str(CHECKER), "--expected-evaluator", expected_eval or EVAL_ID,
             "--expected-checker", CHK_ID],
            capture_output=True, text=True, timeout=3600)
        reason = ""
        for tok in (cp.stderr or "").split():
            if tok.startswith("reason="):
                reason = tok[7:]
        return cp.returncode, reason
    finally:
        os.unlink(p)


def mutate(orig: str, needle: str, replacement: str) -> str:
    if needle not in orig:
        raise RuntimeError(f"mutation needle not found: {needle!r}")
    return orig.replace(needle, replacement, 1)


def import_ok() -> bool:
    cp = subprocess.run([sys.executable, "-c",
                         f"import sys; sys.path.insert(0,'{ROOT}/tests'); import release_validate"],
                        capture_output=True, text=True)
    return cp.returncode == 0


def run_mutation(name, poison_fn, needle, replacement):
    orig_bytes = VALIDATOR.read_bytes()
    orig_hash = sha(orig_bytes)
    result = {"gate": name, "source_hash_pre": orig_hash}

    # A(pre): poison refuses.
    code, reason = poison_fn()
    result["A_pre"] = "pass" if code != 0 else "FAIL-admitted"
    result["A_pre_exit"] = code
    result["A_pre_reason"] = reason

    # B: apply semantic mutation, still-runnable, poison now admitted.
    mutated = mutate(orig_bytes.decode(), needle, replacement)
    VALIDATOR.write_text(mutated)
    result["source_hash_mutated"] = sha(VALIDATOR.read_bytes())
    try:
        if not import_ok():
            result["B"] = "INVALID-compile-error"
        else:
            code_b, reason_b = poison_fn()
            # RED = the poison is now admitted (governing gate disabled).
            result["B"] = "red-for-intended-reason" if code_b == 0 else "INVALID-still-refused"
            result["B_exit"] = code_b
            result["B_reason"] = reason_b
    finally:
        # A(post): restore EXACT bytes, verify hash, purge stale.
        VALIDATOR.write_bytes(orig_bytes)
        for pyc in ROOT.glob("tests/__pycache__/release_validate*.pyc"):
            pyc.unlink()
    result["source_hash_post"] = sha(VALIDATOR.read_bytes())
    result["restore_hash_verified"] = (result["source_hash_post"] == orig_hash)
    code_a, reason_a = poison_fn()
    result["A_post"] = "pass" if code_a != 0 else "FAIL-admitted"
    result["A_post_exit"] = code_a
    result["A_post_reason"] = reason_a
    return result


def main() -> int:
    # M1 poison: a forged-source (altered request) cert.
    fsrc = make_cert("x^2+1", "1", "2", forge_source=True)
    m1 = run_mutation(
        "M1-request-binding",
        lambda: run_validate_cert(fsrc, "x^2+1", "1", "2"),
        needle='raise ReleaseRefusal("request-commitment", "cert source != recomputed request commitment")',
        replacement='pass  # ABA-M1-mutation')

    # M2 poison: a substituted evaluator identity (wrong expected hash).
    good = make_cert("x^2+1", "1", "2")
    m2 = run_mutation(
        "M2-evaluator-identity",
        lambda: run_validate_cert(good, "x^2+1", "1", "2", expected_eval="b" * 64),
        needle='raise ReleaseRefusal("evaluator-identity", f"{eval_id} != {expected_evaluator}")',
        replacement='pass  # ABA-M2-mutation')

    data = {
        "harness": "cert_aba_mutations.py",
        "validator": str(VALIDATOR.relative_to(ROOT)),
        "evaluator_sha256": EVAL_ID,
        "checker_sha256": CHK_ID,
        "mutations": {"M1": m1, "M2": m2},
    }
    EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE.write_text(json.dumps(data, indent=2, sort_keys=True))

    ok = True
    for tag, m in (("M1", m1), ("M2", m2)):
        good_row = (m["A_pre"] == "pass" and m["B"] == "red-for-intended-reason"
                    and m["A_post"] == "pass" and m["restore_hash_verified"])
        print(f"{tag} {m['gate']}: A_pre={m['A_pre']}({m['A_pre_reason']}) "
              f"B={m['B']} A_post={m['A_post']} restore_hash_verified={m['restore_hash_verified']}")
        ok = ok and good_row
    print(f"evidence={EVIDENCE} sha256={sha(EVIDENCE.read_bytes())}")
    # final: validator bytes restored + tree clean check is the caller's gate
    if VALIDATOR.read_bytes() and sha(VALIDATOR.read_bytes()) != m1["source_hash_pre"]:
        print("VERDICT: FAIL — validator not restored to pre-mutation bytes")
        return 1
    print("VERDICT: PASS — both semantic mutations RED-on-disable, restored by hash"
          if ok else "VERDICT: FAIL — a mutation did not show the required A→B→A transitions")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
