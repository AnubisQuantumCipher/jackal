#!/usr/bin/env python3
"""A->B->A gate for the JACKAL v1.7 shadow composition checker.

STATUS: research-shadow. NON-AUTHORITATIVE.

Demonstrates the shadow checker is LOAD-BEARING (mission section 9):

  A/pre : exact checker source bytes hashed; a clean artifact ACCEPTS and the
          designated semantic poison (released interval widened beyond the
          bound tolerance) REFUSES with reason `tolerance-unmet` in fresh
          checker processes.
  B     : one minimal, compiling, runnable mutation disables the governing
          semantic rejection (`guardE (decide (hdr.out_hi - hdr.out_lo <=
          hdr.tol))` -> `guardE true`).  The same poison bytes are ADMITTED
          by the mutated checker (driver modules rebuild and run green).
          Defense-in-depth is recorded separately: the FULL library build
          under B fails, because the build-time `#guard` tolerance twin in
          ShadowCertFixtures.lean trips.
  A/post: exact pre-mutation bytes restored (verified by SHA-256), the lib
          rebuilt, and the poison REFUSES again for the original reason.

Supplementary (B-strong): the enclosure guard `forged-enclosure:lower`
CANNOT be disabled at all — the mutation breaks the machine-checked
soundness proof (`int_cert_sound` in ShadowCertSound.lean no longer
compiles).  The compile refusal is recorded as evidence that the enclosure
guards are proof-load-bearing; it is NOT counted as the admitted-B step.

Never commits B.  Receipt: research/v170-bound-step-shadow/evidence/aba_shadow.json
(schema jackal-bound-step-shadow-aba-v1).
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LEAN_DIR = ROOT / "proofs" / "lean"
CHECK_SRC = LEAN_DIR / "JackalIv" / "ShadowCertCheck.lean"
DRIVER = LEAN_DIR / "JackalIv" / "ShadowCertMain.lean"
EVIDENCE = ROOT / "research" / "v170-bound-step-shadow" / "evidence"

sys.path.insert(0, str(ROOT / "tools"))
import bound_step_shadow_producer as bsp  # noqa: E402

GUARD_TOL = ('guardE (decide (hdr.out_hi - hdr.out_lo ≤ hdr.tol)) '
             '"tolerance-unmet"')
GUARD_TOL_MUT = 'guardE true "tolerance-unmet"'
GUARD_ENC = ('guardE (decide (t.lo ≤ h * cF.hdr.output_lo)) '
             '"forged-enclosure:lower"')
GUARD_ENC_MUT = 'guardE true "forged-enclosure:lower"'


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_checker(text: str) -> tuple[int, str]:
    with tempfile.NamedTemporaryFile("w", suffix=".jic", delete=False,
                                     encoding="utf-8") as fh:
        fh.write(text)
        p = fh.name
    try:
        proc = subprocess.run(
            ["lake", "env", "lean", "--run", str(DRIVER), p],
            capture_output=True, text=True, timeout=600, cwd=LEAN_DIR)
        return proc.returncode, (proc.stdout + proc.stderr).strip()
    finally:
        os.unlink(p)


def build(targets: list[str], timeout: int = 1800) -> tuple[int, str]:
    proc = subprocess.run(["lake", "build", *targets], capture_output=True,
                          text=True, timeout=timeout, cwd=LEAN_DIR)
    return proc.returncode, (proc.stdout + proc.stderr)[-2000:]


def reason_of(output: str) -> str:
    for ln in output.splitlines():
        if ln.startswith("SHADOW-REFUSE reason="):
            return ln.split("reason=", 1)[1].split(":", 1)[0].split()[0]
    return ""


def main() -> int:
    # fixtures: clean single-leaf artifact + tolerance poison
    art = bsp.build("x", "0", "1", "2")
    clean = bsp.emit(art)
    poisoned_art = bsp.clone(art)
    poisoned_art["out_lo"] -= 3
    poisoned_art["out_hi"] += 3
    poison = bsp.emit(poisoned_art)
    poison_sha = hashlib.sha256(poison.encode()).hexdigest()

    receipt: dict = {
        "schema": "jackal-bound-step-shadow-aba-v1",
        "status": "research-shadow",
        "harness": "tests/bound_step_shadow_aba.py",
        "checker_source": "proofs/lean/JackalIv/ShadowCertCheck.lean",
        "gate": "tolerance-unmet released-width guard",
        "poison": "released interval widened beyond the bound tolerance",
        "poison_sha256": poison_sha,
    }

    src0 = CHECK_SRC.read_bytes()
    receipt["source_hash_pre"] = sha(CHECK_SRC)

    # ---- A/pre --------------------------------------------------------
    rc, out = run_checker(clean)
    ok_clean_pre = rc == 0 and "SHADOW-ACCEPT" in out
    rc, out = run_checker(poison)
    pre_reason = reason_of(out)
    a_pre = rc == 1 and pre_reason == "tolerance-unmet"
    receipt["A_pre"] = "red-for-intended-reason" if a_pre else "FAILED"
    receipt["A_pre_reason"] = pre_reason
    receipt["A_pre_clean_accepts"] = ok_clean_pre
    print(f"A/pre  clean-accept={ok_clean_pre} poison-refuse={a_pre} "
          f"reason={pre_reason}")
    if not (a_pre and ok_clean_pre):
        _write(receipt)
        return 1

    try:
        # ---- B --------------------------------------------------------
        text = src0.decode("utf-8")
        if GUARD_TOL not in text:
            raise RuntimeError("tolerance guard text not found")
        CHECK_SRC.write_text(text.replace(GUARD_TOL, GUARD_TOL_MUT, 1),
                             encoding="utf-8")
        receipt["source_hash_mutated"] = sha(CHECK_SRC)
        rcb, outb = build(["JackalIv.ShadowCertSound",
                           "JackalIv.ShadowCertCodec"])
        receipt["B_driver_build_exit"] = rcb
        if rcb != 0:
            receipt["B"] = "INVALID-compile-error"
            print(f"B      driver rebuild FAILED (invalid): {outb[-400:]}")
        else:
            rc, out = run_checker(poison)
            admitted = rc == 0 and "SHADOW-ACCEPT" in out
            receipt["B"] = ("poison-admitted" if admitted
                            else "INVALID-still-refused")
            receipt["B_exit"] = rc
            receipt["B_reason"] = reason_of(out)
            print(f"B      poison admitted={admitted} rc={rc}")
            # defense-in-depth: the full lib build refuses via #guard twin
            rcg, outg = build(["JackalIv"])
            receipt["B_full_lib_build_exit"] = rcg
            receipt["B_full_lib_guard_refuses"] = rcg != 0
            print(f"B      full-lib build under mutation exit={rcg} "
                  f"(nonzero = #guard tolerance twin fired)")
    finally:
        # ---- A/post ---------------------------------------------------
        CHECK_SRC.write_bytes(src0)
    receipt["source_hash_post"] = sha(CHECK_SRC)
    receipt["restore_hash_verified"] = (
        receipt["source_hash_post"] == receipt["source_hash_pre"])
    rcr, _ = build(["JackalIv"])
    receipt["A_post_rebuild_exit"] = rcr
    rc, out = run_checker(poison)
    post_reason = reason_of(out)
    a_post = rc == 1 and post_reason == "tolerance-unmet"
    receipt["A_post"] = "red-for-intended-reason" if a_post else "FAILED"
    receipt["A_post_reason"] = post_reason
    rc, out = run_checker(clean)
    receipt["A_post_clean_accepts"] = rc == 0 and "SHADOW-ACCEPT" in out
    print(f"A/post restore={receipt['restore_hash_verified']} "
          f"poison-refuse={a_post} reason={post_reason} "
          f"clean-accept={receipt['A_post_clean_accepts']}")

    # ---- supplementary strong-B: enclosure guard is proof-load-bearing
    try:
        text = src0.decode("utf-8")
        if GUARD_ENC not in text:
            raise RuntimeError("enclosure guard text not found")
        CHECK_SRC.write_text(text.replace(GUARD_ENC, GUARD_ENC_MUT, 1),
                             encoding="utf-8")
        rcs, outs = build(["JackalIv.ShadowCertSound"])
        receipt["B_strong"] = {
            "gate": "forged-enclosure:lower range guard",
            "mutated_build_exit": rcs,
            "proof_load_bearing": rcs != 0,
            "note": ("disabling the enclosure guard breaks the compile of "
                     "int_cert_sound: the guard is consumed by the "
                     "machine-checked soundness proof"),
            "build_tail": outs[-400:],
        }
        print(f"B-strong enclosure-guard mutation build exit={rcs} "
              f"(nonzero = proof-load-bearing)")
    finally:
        CHECK_SRC.write_bytes(src0)
    receipt["final_source_hash"] = sha(CHECK_SRC)
    receipt["final_restore_verified"] = (
        receipt["final_source_hash"] == receipt["source_hash_pre"])
    rcf, _ = build(["JackalIv"])
    receipt["final_rebuild_exit"] = rcf

    ok = (receipt["A_pre"] == "red-for-intended-reason"
          and receipt.get("B") == "poison-admitted"
          and receipt.get("B_full_lib_guard_refuses") is True
          and receipt["restore_hash_verified"]
          and receipt["A_post"] == "red-for-intended-reason"
          and receipt["A_post_clean_accepts"]
          and receipt["B_strong"]["proof_load_bearing"]
          and receipt["final_restore_verified"]
          and rcf == 0)
    receipt["verdict"] = "PASS" if ok else "FAIL"
    _write(receipt)
    print(f"ABA verdict={receipt['verdict']}")
    return 0 if ok else 1


def _write(receipt: dict) -> None:
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    out = EVIDENCE / "aba_shadow.json"
    out.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n",
                   encoding="utf-8")
    print(f"receipt={out}")


if __name__ == "__main__":
    sys.exit(main())
