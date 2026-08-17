#!/usr/bin/env python3
"""A->B->A gate for the JACKAL certified composed-integral checker — ISOLATED.

v1.7.1 hardening: every mutation is built inside a throwaway APFS clone of
`proofs/lean` (copy-on-write sandbox).  The CANONICAL pinned checker
executable is NEVER rebuilt, relinked, or replaced by this audit — its
byte identity against the `int-cert-checker` row of release/MANIFEST.sha256
is asserted BEFORE and AFTER the run.  (The prior in-place design left a
byte-drifted relink artifact of the canonical exe on disk after an audit —
42 bytes of link metadata, behaviorally identical, but a pin violation.)

Protocol:

  A/pre : canonical exe == manifest pin; clean artifact ACCEPTS and the
          tolerance poison (released interval widened beyond the bound
          tolerance) REFUSES `tolerance-unmet` — no build performed.
  B     : in the SANDBOX, one minimal compiling mutation disables the
          tolerance guard; the sandbox exe is rebuilt and ADMITS the same
          poison bytes (the checker is load-bearing).  Defense in depth:
          the sandbox full-library build FAILS (the build-time `#guard`
          tolerance twin in IntCertFixtures.lean fires).
  B-strong: sandbox source restored, then the enclosure guard is disabled;
          the sandbox exe build FAILS — `int_cert_sound` consumes the
          guard, so the mutation breaks the machine-checked proof.
  A/post: canonical source and exe hashes are UNCHANGED (== A/pre == pin);
          the poison refuses and the clean artifact accepts via the
          canonical exe.

Reconstruction metadata: the receipt binds the sha256 of the pinned
`release/evidence/build_environment_v170.json` record (SDK / linker /
compiler / Lean toolchain identities behind the pinned binaries).

Evidence: release/evidence/int_cert_aba.json (jackal-int-cert-aba-v3).
Runnable under `python3 -O`.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LEAN_DIR = ROOT / "proofs" / "lean"
CHECK_REL = Path("JackalIv") / "IntCertCheck.lean"
EXE_TARGET = "jackal_int_cert_check"
CHECKER_EXE = LEAN_DIR / ".lake" / "build" / "bin" / "jackal_int_cert_check"
MANIFEST = ROOT / "release" / "MANIFEST.sha256"
BUILD_ENV = ROOT / "release" / "evidence" / "build_environment_v170.json"
EVIDENCE = ROOT / "release" / "evidence"

sys.path.insert(0, str(ROOT / "tools"))
import int_cert_producer as bsp  # noqa: E402

GUARD_TOL = ('guardE (decide (hdr.out_hi - hdr.out_lo ≤ hdr.tol)) '
             '"tolerance-unmet"')
GUARD_TOL_MUT = 'guardE true "tolerance-unmet"'
GUARD_ENC = ('guardE (decide (t.lo ≤ h * cF.hdr.output_lo)) '
             '"forged-enclosure:lower"')
GUARD_ENC_MUT = 'guardE true "forged-enclosure:lower"'


def sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def manifest_pin(label: str) -> str:
    for line in MANIFEST.read_text().splitlines():
        if line.startswith(f"{label} "):
            return line.split()[-1]
    raise RuntimeError(f"manifest row missing: {label}")


def run_exe(exe: Path, text: str) -> tuple[int, str]:
    with tempfile.NamedTemporaryFile("w", suffix=".jic", delete=False,
                                     encoding="utf-8") as fh:
        fh.write(text)
        p = fh.name
    try:
        proc = subprocess.run([str(exe), p], capture_output=True, text=True,
                              timeout=300)
        return proc.returncode, (proc.stdout or "") + (proc.stderr or "")
    finally:
        os.unlink(p)


def sandbox_build(sandbox: Path, targets: list[str],
                  timeout: int = 1800) -> tuple[int, str]:
    proc = subprocess.run(["lake", "build", *targets], capture_output=True,
                          text=True, timeout=timeout, cwd=sandbox)
    return proc.returncode, (proc.stdout + proc.stderr)[-2000:]


def reason_of(output: str) -> str:
    for ln in output.splitlines():
        if ln.startswith("REFUSE reason="):
            return ln.split("REFUSE reason=", 1)[1].split(":", 1)[0].split()[0]
    return ""


def main() -> int:
    # fixtures: clean single-leaf artifact + tolerance poison
    art = bsp.build("x", "0", "1", "2")
    clean = bsp.emit(art)
    poisoned_art = bsp.clone(art)
    poisoned_art["out_lo"] -= 3
    poisoned_art["out_hi"] += 3
    poison = bsp.emit(poisoned_art)

    pin = manifest_pin("int-cert-checker")
    receipt: dict = {
        "schema": "jackal-int-cert-aba-v3",
        "status": "public",
        "harness": "tests/int_cert_aba_test.py",
        "isolation": "mutations built in a throwaway APFS clone of proofs/lean; "
                     "the canonical pinned executable is never rebuilt",
        "checker_source": "proofs/lean/JackalIv/IntCertCheck.lean",
        "checker_exe": "proofs/lean/.lake/build/bin/jackal_int_cert_check",
        "checker_pin_manifest": pin,
        "build_environment_sha256": sha_file(BUILD_ENV) if BUILD_ENV.exists()
                                    else "MISSING",
        "gate": "tolerance-unmet released-width guard",
        "poison": "released interval widened beyond the bound tolerance",
        "poison_sha256": hashlib.sha256(poison.encode()).hexdigest(),
    }
    canon_src = (LEAN_DIR / CHECK_REL).read_bytes()
    receipt["source_hash_pre"] = sha_file(LEAN_DIR / CHECK_REL)
    receipt["canonical_exe_sha_pre"] = sha_file(CHECKER_EXE)
    pin_pre = receipt["canonical_exe_sha_pre"] == pin
    receipt["canonical_exe_matches_pin_pre"] = pin_pre

    # ---- A/pre (canonical exe, no build) -------------------------------
    rc, out = run_exe(CHECKER_EXE, clean)
    ok_clean_pre = rc == 0 and "ACCEPT status=bounded" in out
    rc, out = run_exe(CHECKER_EXE, poison)
    pre_reason = reason_of(out)
    a_pre = rc == 1 and pre_reason == "tolerance-unmet"
    receipt["A_pre"] = "red-for-intended-reason" if a_pre else "FAILED"
    receipt["A_pre_reason"] = pre_reason
    receipt["A_pre_clean_accepts"] = ok_clean_pre
    print(f"A/pre  pin-match={pin_pre} clean-accept={ok_clean_pre} "
          f"poison-refuse={a_pre} reason={pre_reason}")
    if not (a_pre and ok_clean_pre and pin_pre):
        _write(receipt)
        return 1

    # ---- sandbox --------------------------------------------------------
    with tempfile.TemporaryDirectory(prefix="jackal-aba-sandbox-") as td:
        sandbox = Path(td) / "lean"
        clone = subprocess.run(["cp", "-Rc", str(LEAN_DIR), str(sandbox)],
                               capture_output=True, text=True, timeout=600)
        if clone.returncode != 0:
            # non-APFS fallback: plain copy (slower, same isolation)
            shutil.copytree(LEAN_DIR, sandbox, symlinks=True)
        receipt["sandbox"] = "apfs-clone" if clone.returncode == 0 else "copy"
        sb_src = sandbox / CHECK_REL
        sb_exe = sandbox / ".lake" / "build" / "bin" / EXE_TARGET
        text0 = canon_src.decode("utf-8")
        if GUARD_TOL not in text0:
            raise RuntimeError("tolerance guard text not found")
        if GUARD_ENC not in text0:
            raise RuntimeError("enclosure guard text not found")

        # ---- B: disable the tolerance guard in the SANDBOX --------------
        sb_src.write_text(text0.replace(GUARD_TOL, GUARD_TOL_MUT, 1),
                          encoding="utf-8")
        receipt["source_hash_mutated"] = sha_file(sb_src)
        rcb, outb = sandbox_build(sandbox, [EXE_TARGET])
        receipt["B_exe_build_exit"] = rcb
        if rcb != 0:
            receipt["B"] = "INVALID-compile-error"
            print(f"B      sandbox exe rebuild FAILED (invalid): {outb[-400:]}")
        else:
            rc, out = run_exe(sb_exe, poison)
            admitted = rc == 0 and "ACCEPT status=bounded" in out
            receipt["B"] = ("poison-admitted" if admitted
                            else "INVALID-still-refused")
            receipt["B_exit"] = rc
            receipt["B_reason"] = reason_of(out)
            print(f"B      sandbox poison admitted={admitted} rc={rc}")
            # defense-in-depth: sandbox full lib build refuses via #guard twin
            rcg, _outg = sandbox_build(sandbox, ["JackalIv"])
            receipt["B_full_lib_build_exit"] = rcg
            receipt["B_full_lib_guard_refuses"] = rcg != 0
            print(f"B      sandbox full-lib build under mutation exit={rcg} "
                  f"(nonzero = #guard tolerance twin fired)")

        # ---- B-strong: enclosure guard is proof-load-bearing ------------
        sb_src.write_bytes(canon_src)
        sb_src.write_text(text0.replace(GUARD_ENC, GUARD_ENC_MUT, 1),
                          encoding="utf-8")
        rcs, outs = sandbox_build(sandbox, [EXE_TARGET])
        receipt["B_strong"] = {
            "gate": "forged-enclosure:lower range guard",
            "mutated_build_exit": rcs,
            "proof_load_bearing": rcs != 0,
            "note": ("disabling the enclosure guard breaks the compile of "
                     "int_cert_sound (IntCertSound.lean): the guard is "
                     "consumed by the machine-checked soundness proof, so "
                     "the sandbox exe cannot be rebuilt"),
            "build_tail": outs[-400:],
        }
        print(f"B-strong sandbox enclosure-guard mutation build exit={rcs} "
              f"(nonzero = proof-load-bearing)")

    # ---- A/post (canonical tree was never touched) ----------------------
    receipt["source_hash_post"] = sha_file(LEAN_DIR / CHECK_REL)
    receipt["restore_hash_verified"] = (
        receipt["source_hash_post"] == receipt["source_hash_pre"])
    receipt["canonical_exe_sha_post"] = sha_file(CHECKER_EXE)
    receipt["canonical_exe_matches_pin_post"] = (
        receipt["canonical_exe_sha_post"] == pin)
    rc, out = run_exe(CHECKER_EXE, poison)
    post_reason = reason_of(out)
    a_post = rc == 1 and post_reason == "tolerance-unmet"
    receipt["A_post"] = "red-for-intended-reason" if a_post else "FAILED"
    receipt["A_post_reason"] = post_reason
    rc, out = run_exe(CHECKER_EXE, clean)
    receipt["A_post_clean_accepts"] = rc == 0 and "ACCEPT status=bounded" in out
    print(f"A/post canonical-src-unchanged={receipt['restore_hash_verified']} "
          f"canonical-exe-pin={receipt['canonical_exe_matches_pin_post']} "
          f"poison-refuse={a_post} clean-accept={receipt['A_post_clean_accepts']}")

    ok = (receipt["A_pre"] == "red-for-intended-reason"
          and receipt["canonical_exe_matches_pin_pre"]
          and receipt.get("B") == "poison-admitted"
          and receipt.get("B_full_lib_guard_refuses") is True
          and receipt["restore_hash_verified"]
          and receipt["canonical_exe_matches_pin_post"]
          and receipt["A_post"] == "red-for-intended-reason"
          and receipt["A_post_clean_accepts"]
          and receipt["B_strong"]["proof_load_bearing"])
    receipt["verdict"] = "PASS" if ok else "FAIL"
    _write(receipt)
    print(f"ABA verdict={receipt['verdict']}")
    return 0 if ok else 1


def _write(receipt: dict) -> None:
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    out = EVIDENCE / "int_cert_aba.json"
    out.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n",
                   encoding="utf-8")
    print(f"receipt={out}")


if __name__ == "__main__":
    sys.exit(main())
