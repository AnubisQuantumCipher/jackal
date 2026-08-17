#!/usr/bin/env python3
"""JACKAL v1.7 SHADOW gate — bound_step composition artifact matrix.

STATUS: research-shadow. NON-AUTHORITATIVE. Not registered in any release gate
driver. This harness exercises the shadow subdivision-tree certificate lane:

  producer : tools/bound_step_shadow_producer.py   (untrusted mirror of bound_step)
  checker  : proofs/lean/JackalIv/ShadowCertMain.lean  via `lake env lean --run`
             (compiled/interpreted directly from the PROVED checkIntCert)

Matrix (mission §8):
  positive  P1..P6   — range leaf, taylor2 leaf, taylor4 leaf, multi-level tree,
                       nontrivial left/right sums, fresh-process exact replay.
  refusal   R1..R7   — producer-side fail-closed classes mirroring engine panics,
                       plus checker-side invalid/malformed/noncanonical.
  poison    X1..X17  — semantic tampers; each must pass byte/schema layers and
                       refuse at the SEMANTIC layer with the exact reason class.

Every row records expected vs observed refusal class; any mismatch fails the
gate. Evidence: research/v170-bound-step-shadow/evidence/shadow_matrix.json
(schema jackal-bound-step-shadow-matrix-v1).

Runnable under `python3 -O` (no load-bearing asserts).
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LEAN_DIR = ROOT / "proofs" / "lean"
PRODUCER = ROOT / "tools" / "bound_step_shadow_producer.py"
CHECKER_SRC = LEAN_DIR / "JackalIv" / "ShadowCertMain.lean"
EVIDENCE_DIR = ROOT / "research" / "v170-bound-step-shadow" / "evidence"

SCHEMA = "jackal-bound-step-shadow-matrix-v1"
ACCEPT_PREFIX = "SHADOW-ACCEPT status=research-shadow theorem=int_cert_sound"
REFUSE_PREFIX = "SHADOW-REFUSE reason="

sys.path.insert(0, str(ROOT / "tools"))

CHECK_TIMEOUT = 300


class HarnessError(Exception):
    pass


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def run_producer(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PRODUCER), *args],
        capture_output=True, text=True, timeout=CHECK_TIMEOUT,
    )


def produce(expr: str, lo: str, hi: str, tol: str) -> str:
    """Run the producer; return artifact text or raise with the refusal line."""
    proc = run_producer(["emit", "--expression", expr, "--lower", lo,
                         "--upper", hi, "--tolerance", tol])
    if proc.returncode != 0:
        raise HarnessError(f"producer refused: {proc.stderr.strip()}")
    return proc.stdout


def producer_refusal(expr: str, lo: str, hi: str, tol: str) -> str:
    """Run the producer expecting refusal; return the reason class."""
    proc = run_producer(["emit", "--expression", expr, "--lower", lo,
                         "--upper", hi, "--tolerance", tol])
    if proc.returncode == 0:
        raise HarnessError("producer unexpectedly accepted")
    line = (proc.stderr or "").strip().splitlines()
    for ln in line:
        if ln.startswith("REFUSE reason="):
            return ln.split("REFUSE reason=", 1)[1].split()[0].split(":", 1)[0]
    raise HarnessError(f"producer refusal line missing: {proc.stderr!r}")


def run_checker(artifact_text: str) -> tuple[int, str, str]:
    """One FRESH checker process on the exact artifact bytes."""
    with tempfile.NamedTemporaryFile("w", suffix=".jic", delete=False,
                                     encoding="utf-8") as fh:
        fh.write(artifact_text)
        path = fh.name
    try:
        proc = subprocess.run(
            ["lake", "env", "lean", "--run",
             str(CHECKER_SRC), path],
            capture_output=True, text=True, timeout=CHECK_TIMEOUT,
            cwd=LEAN_DIR,
        )
        return proc.returncode, proc.stdout or "", proc.stderr or ""
    finally:
        os.unlink(path)


def expect_accept(artifact_text: str) -> tuple[bool, str]:
    rc, out, err = run_checker(artifact_text)
    if rc == 0 and ACCEPT_PREFIX in out:
        return True, out.strip().splitlines()[-1]
    return False, f"rc={rc} out={out.strip()!r} err={err.strip()!r}"


def expect_refuse(artifact_text: str, reason: str) -> tuple[bool, str]:
    """Checker must exit nonzero with the exact SHADOW-REFUSE reason class."""
    rc, out, err = run_checker(artifact_text)
    if rc == 0:
        return False, f"ACCEPTED (wanted refuse:{reason}): {out.strip()!r}"
    stream = err + "\n" + out
    for ln in stream.splitlines():
        ln = ln.strip()
        if ln.startswith(REFUSE_PREFIX):
            observed = ln.split(REFUSE_PREFIX, 1)[1].split(":", 1)[0].split()[0]
            return observed == reason, f"observed={observed} line={ln!r}"
    return False, f"no SHADOW-REFUSE line: rc={rc} err={err.strip()!r}"


# --------------------------------------------------------------------------
# Text-level artifact surgery (poisons that stay inside the wire grammar).
# --------------------------------------------------------------------------

def replace_line(text: str, prefix: str, new_line: str, nth: int = 0) -> str:
    lines = text.splitlines()
    seen = 0
    for i, ln in enumerate(lines):
        if ln.startswith(prefix):
            if seen == nth:
                lines[i] = new_line
                return "\n".join(lines) + "\n"
            seen += 1
    raise HarnessError(f"line with prefix {prefix!r} #{nth} not found")


def get_lines(text: str, prefix: str) -> list[str]:
    return [ln for ln in text.splitlines() if ln.startswith(prefix)]


# --------------------------------------------------------------------------
# Matrix rows
# --------------------------------------------------------------------------

RESULTS: list[dict] = []


def record(row_id: str, kind: str, expected: str, ok: bool, detail: str,
           artifact_sha: str | None = None) -> None:
    RESULTS.append({
        "id": row_id, "kind": kind, "expected": expected,
        "ok": bool(ok), "observed": detail[:400],
        "artifact_sha256": artifact_sha,
    })
    print(f"{'PASS' if ok else 'FAIL'} {row_id:28s} expected={expected} {detail[:160]}")


def main() -> int:
    if not PRODUCER.is_file():
        print(f"RED: producer missing at {PRODUCER}", file=sys.stderr)
        return 2
    if not CHECKER_SRC.is_file():
        print(f"RED: checker main missing at {CHECKER_SRC}", file=sys.stderr)
        return 2

    import bound_step_shadow_producer as bsp  # untrusted producer library

    # ---------------- positives ----------------
    # P1 range-only leaf: abs is smooth-refused by the engine's ast_smooth_ok
    # mirror, so the whole tree is range-only; wide tolerance keeps it single-leaf.
    art_p1 = produce("abs(x)", "-1", "1", "2")
    ok, det = expect_accept(art_p1)
    record("P1-range-leaf", "positive", "accept", ok, det, sha256_text(art_p1))

    # P2 taylor2 leaf: force degree 2 by an integrand whose D2 chain is large
    # enough is fragile; instead the producer accepts --degree-cap to mirror the
    # engine's ast_size fallback deterministically. Policy binding stays honest:
    # kind rank <= header degree.
    art_p2 = produce_with_cap("x^2", "0", "1", "1/2", cap=2)
    ok, det = expect_accept(art_p2)
    record("P2-taylor2-leaf", "positive", "accept", ok, det, sha256_text(art_p2))

    # P3 taylor4 leaf, single node.
    art_p3 = produce("x^2", "0", "1", "1/2")
    ok, det = expect_accept(art_p3)
    if "taylor4" not in art_p3:
        ok, det = False, "no taylor4 leaf in artifact"
    record("P3-taylor4-leaf", "positive", "accept", ok, det, sha256_text(art_p3))

    # P4 multi-level recursive tree (kink forces recursion; range-only mode).
    art_p4 = produce("abs(x-1/3)", "0", "1", "1/40")
    ok, det = expect_accept(art_p4)
    n_split = len([l for l in get_lines(art_p4, "tree ") if " split " in l])
    if n_split < 2:
        ok, det = False, f"tree not multi-level: splits={n_split}"
    record("P4-multi-level", "positive", "accept", ok, det, sha256_text(art_p4))

    # P5 nontrivial left/right sums: integrand with sign change so child
    # contributions have opposite signs and interval addition is exercised.
    art_p5 = produce("x^3-x", "-1", "3/2", "1/8")
    ok, det = expect_accept(art_p5)
    if len([l for l in get_lines(art_p5, "tree ") if " split " in l]) < 1:
        ok, det = False, "no split node"
    record("P5-signed-sums", "positive", "accept", ok, det, sha256_text(art_p5))

    # P6 exact replay through a second FRESH checker process, identical bytes.
    ok1, det1 = expect_accept(art_p3)
    ok2, det2 = expect_accept(art_p3)
    record("P6-fresh-replay", "positive", "accept",
           ok1 and ok2 and det1 == det2,
           f"first={det1!r} second={det2!r}", sha256_text(art_p3))

    # ---------------- boundary / refusal ----------------
    r = producer_refusal("tan(x)", "0", "1", "1/10")
    record("R1-unsupported-expr", "refusal", "unsupported-expression",
           r == "unsupported-expression", f"observed={r}")

    r = producer_refusal("abs(x-1/3)", "0", "1", "1/1000000000")
    record("R2-budget", "refusal", "budget-exhausted",
           r == "budget-exhausted", f"observed={r}")

    r = producer_refusal("1/x", "-1", "1", "1/10")
    record("R3-cannot-certify", "refusal", "cannot-certify",
           r == "cannot-certify", f"observed={r}")

    r = producer_refusal("x^2", "1", "1000000000001/1000000000000", "1/10^40")
    record("R4-float-resolution", "refusal", "float-resolution",
           r == "float-resolution", f"observed={r}")

    r = producer_refusal("x", "1", "0", "1/10")
    record("R5-reversed-domain", "refusal", "invalid-domain",
           r == "invalid-domain", f"observed={r}")

    r = producer_refusal("x", "999999999999", "1000000000001", "1/200")
    record("R6-tolerance-unmet", "refusal", "tolerance-unmet",
           r == "tolerance-unmet", f"observed={r}")

    # R7 checker-side noncanonical value: mutate a canonical rational to an
    # unreduced form; codec layer must refuse with class noncanonical-value.
    bad = art_p3.replace("request 0 1 1/2", "request 0 2/2 1/2", 1)
    ok, det = expect_refuse(bad, "noncanonical-value")
    record("R7-noncanonical", "refusal", "noncanonical-value", ok, det)

    # ---------------- semantic poisons ----------------
    # Baseline artifacts for surgery: taylor4 single leaf (t4) and multi-level (ml).
    t4 = bsp.build("x^2", "0", "1", "1/2")
    ml = bsp.build("abs(x-1/3)", "0", "1", "1/40")

    # X1 expression changed, certificates retained.
    p = bsp.clone(t4); p["expr_sexp"] = "(pow (var x) (num 3))"
    ok, det = expect_refuse(bsp.emit(p), "request-mismatch")
    record("X1-expr-changed", "poison", "request-mismatch", ok, det)

    # X2 bounds changed (request line only; tree/certs retained).
    p = bsp.clone(t4); p["req_hi"] = Fraction(2)
    ok, det = expect_refuse(bsp.emit(p), "request-mismatch")
    record("X2-bounds-changed", "poison", "request-mismatch", ok, det)

    # X3 tolerance tightened after the fact.
    p = bsp.clone(t4); p["tol"] = Fraction(1, 10**12)
    ok, det = expect_refuse(bsp.emit(p), "policy-violation")
    record("X3-tolerance-changed", "poison", "policy-violation", ok, det)

    # X4 epoch/model pin changed.
    bad = replace_line(bsp.emit(t4), "model ", "model jackal-iv-model-v0")
    ok, det = expect_refuse(bad, "stale-identity")
    record("X4-epoch-changed", "poison", "stale-identity", ok, det)

    # X5 leaf mode relabeled (taylor4 -> range keeps extra certs: role mismatch).
    p = bsp.clone(t4); bsp.leaf(p)["kind"] = "range"
    ok, det = expect_refuse(bsp.emit(p), "missing-premise")
    record("X5-mode-relabel", "poison", "missing-premise", ok, det)

    # X6 leaf enclosure narrowed falsely.
    p = bsp.clone(t4)
    lf = bsp.leaf(p)
    width = lf["hi"] - lf["lo"]
    lf["lo"] += width / 4
    lf["hi"] -= width / 4
    p["out_lo"], p["out_hi"] = lf["lo"], lf["hi"]
    ok, det = expect_refuse(bsp.emit(p), "forged-enclosure")
    record("X6-narrowed-leaf", "poison", "forged-enclosure", ok, det)

    # X7 child omitted.
    p = bsp.clone(ml); sp = bsp.first_split(p)
    sp["children"] = sp["children"][:1]
    ok, det = expect_refuse(bsp.emit(p), "malformed-tree")
    record("X7-child-omitted", "poison", "malformed-tree", ok, det)

    # X8 child duplicated.
    p = bsp.clone(ml); sp = bsp.first_split(p)
    sp["children"] = [sp["children"][0], sp["children"][0]]
    ok, det = expect_refuse(bsp.emit(p), "child-partition-mismatch")
    record("X8-child-duplicated", "poison", "child-partition-mismatch", ok, det)

    # X9 child order swapped.
    p = bsp.clone(ml); sp = bsp.first_split(p)
    sp["children"] = [sp["children"][1], sp["children"][0]]
    ok, det = expect_refuse(bsp.emit(p), "child-partition-mismatch")
    record("X9-child-swapped", "poison", "child-partition-mismatch", ok, det)

    # X10 partition gap: shrink the left child's domain and regenerate its
    # certificates so the leaf is internally consistent; only the partition breaks.
    p = bsp.poison_partition(ml, mode="gap")
    ok, det = expect_refuse(bsp.emit(p), "child-partition-mismatch")
    record("X10-partition-gap", "poison", "child-partition-mismatch", ok, det)

    # X11 partition overlap (policy forbids overlap: strict equality required).
    p = bsp.poison_partition(ml, mode="overlap")
    ok, det = expect_refuse(bsp.emit(p), "child-partition-mismatch")
    record("X11-partition-overlap", "poison", "child-partition-mismatch", ok, det)

    # X12 forged parent total.
    p = bsp.clone(ml); sp = bsp.first_split(p)
    w = sp["hi"] - sp["lo"]
    sp["lo"] += w / 3
    sp["hi"] -= w / 3
    if sp["id"] == p["root"]:
        p["out_lo"], p["out_hi"] = sp["lo"], sp["hi"]
    ok, det = expect_refuse(bsp.emit(p), "forged-parent-sum")
    record("X12-forged-parent", "poison", "forged-parent-sum", ok, det)

    # X13 orphan node (well-formed extra leaf unreachable from the root).
    p = bsp.poison_orphan(ml)
    ok, det = expect_refuse(bsp.emit(p), "malformed-tree")
    record("X13-orphan-node", "poison", "malformed-tree", ok, det)

    # X14 forward/self child reference.
    p = bsp.clone(ml); sp = bsp.first_split(p)
    sp["children"] = [sp["children"][0], sp["id"]]
    ok, det = expect_refuse(bsp.emit(p), "malformed-tree")
    record("X14-forward-ref", "poison", "malformed-tree", ok, det)

    # X15 root changed: header points below the true maximal node.
    p = bsp.clone(ml)
    p["root"] = bsp.first_split(p)["children"][0]
    ok, det = expect_refuse(bsp.emit(p), "malformed-tree")
    record("X15-root-changed", "poison", "malformed-tree", ok, det)

    # X16 valid outer digest recomputed after semantic tamper: rehash the
    # poisoned bytes (attacker keeps identity layer green); refusal must still
    # be the SEMANTIC class, proving the checker (not a digest) is load-bearing.
    p = bsp.clone(t4)
    lf = bsp.leaf(p)
    width = lf["hi"] - lf["lo"]
    lf["lo"] += width / 4
    lf["hi"] -= width / 4
    p["out_lo"], p["out_hi"] = lf["lo"], lf["hi"]
    poisoned = bsp.emit(p)
    fresh_digest = sha256_text(poisoned)  # recomputed, self-consistent
    ok, det = expect_refuse(poisoned, "forged-enclosure")
    record("X16-rehash-tamper", "poison", "forged-enclosure", ok,
           f"{det} fresh_sha={fresh_digest[:16]}", fresh_digest)

    # X17 stale checker/proof identity pin.
    bad = replace_line(bsp.emit(t4), "checker ",
                       "checker jackal-iv-bound-step-shadow-v0")
    ok, det = expect_refuse(bad, "stale-identity")
    record("X17-stale-checker", "poison", "stale-identity", ok, det)

    # ---------------- evidence ----------------
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    passed = sum(1 for r in RESULTS if r["ok"])
    payload = {
        "schema": SCHEMA,
        "status": "research-shadow",
        "non_claims": [
            "non-authoritative shadow evidence",
            "does not change any public verifier, tool, or acceptance class",
            "bound_step release composition remains OPEN on the public surface",
        ],
        "producer_sha256": hashlib.sha256(PRODUCER.read_bytes()).hexdigest(),
        "checker_source_sha256":
            hashlib.sha256(CHECKER_SRC.read_bytes()).hexdigest(),
        "rows": RESULTS,
        "total": len(RESULTS),
        "passed": passed,
    }
    out = EVIDENCE_DIR / "shadow_matrix.json"
    out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n",
                   encoding="utf-8")
    print(f"TOTAL {passed}/{len(RESULTS)}  evidence={out}")
    return 0 if passed == len(RESULTS) else 1


def produce_with_cap(expr: str, lo: str, hi: str, tol: str, cap: int) -> str:
    proc = run_producer(["emit", "--expression", expr, "--lower", lo,
                         "--upper", hi, "--tolerance", tol,
                         "--degree-cap", str(cap)])
    if proc.returncode != 0:
        raise HarnessError(f"producer refused: {proc.stderr.strip()}")
    return proc.stdout


if __name__ == "__main__":
    sys.exit(main())
