#!/usr/bin/env python3
"""JACKAL v1.3.0 executed negative-control roster.

Every mandatory control is exercised against a REAL trust boundary — the
Anubis evaluator (`range-bound-cert`), the Lean-proved checker
(`jackal_cert_check`), or the shared release validator
(`tests/release_validate.py`) — and each row records the actual child exit
code and the observed refusal layer/reason derived from live output. There are
NO documentary `True` rows (the v1.0.3 Counterexample D defect). A separate
independent verifier (`tests/cert_evidence_verify.py`) rejects any vacuity.

Load-bearing checks raise; no `assert`. Run under `python3` and `python3 -O`:
identical verdicts and identical nonzero-safe counts.

Usage:
  python3 tests/cert_controls.py           # run roster, write JSONL + summary
Environment:
  ANUBIS_BIN pinned compiler (for source builds; native binary preferred)
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
import release_validate as rv  # noqa: E402

EVALUATOR = ROOT / "jackal-native"
CHECKER = ROOT / "proofs/lean/.lake/build/bin/jackal_cert_check"
MANIFEST = ROOT / "release/MANIFEST.sha256"
OUT_JSONL = Path(os.environ.get("JACKAL_CONTROLS_OUT", "/tmp/jackal-cert-controls.jsonl"))
REPO_EVIDENCE = ROOT / "release/evidence/negative_controls.jsonl"


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def manifest_ids() -> tuple[str, str]:
    ev = ck = ""
    for ln in MANIFEST.read_text().splitlines():
        if ln.startswith("evaluator "):
            ev = ln.split()[2]
        elif ln.startswith("checker "):
            ck = ln.split()[2]
    return ev, ck


EVAL_ID, CHK_ID = manifest_ids()
DIG = lambda b: hashlib.sha256(b if isinstance(b, bytes) else b.encode()).hexdigest()[:16]


def run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=3600, **kw)


def emit_cert(expr: str, lo: str, hi: str, exe_id: str | None = None,
              req: str | None = None) -> subprocess.CompletedProcess:
    if exe_id is None:
        exe_id = EVAL_ID
    if req is None:
        req = rv.request_commitment_b64(rv.COMMAND_ID, expr, lo, hi)
    return run([str(EVALUATOR), "range-bound-cert", expr, lo, hi, exe_id, req])


def valid_cert(expr="x^2+1", lo="1", hi="2") -> str:
    cp = emit_cert(expr, lo, hi)
    if cp.returncode != 0:
        raise RuntimeError(f"base cert emission failed: {cp.stderr}")
    return cp.stdout


def check_cert_text(text: str) -> subprocess.CompletedProcess:
    with tempfile.NamedTemporaryFile("w", suffix=".cert", delete=False) as f:
        f.write(text)
        path = f.name
    try:
        return run([str(CHECKER), path])
    finally:
        os.unlink(path)


def validate_cert_text(text: str, expr="x^2+1", lo="1", hi="2",
                       exp_eval=None, exp_chk=None) -> tuple[int, str]:
    """Run the shared validator on an EXISTING (possibly forged) cert file."""
    with tempfile.NamedTemporaryFile("w", suffix=".cert", delete=False) as f:
        f.write(text)
        path = f.name
    try:
        cp = run([sys.executable, str(ROOT / "tests/release_validate.py"),
                  "--cert", path, "--expr", expr, "--lo", lo, "--hi", hi,
                  "--evaluator", str(EVALUATOR), "--checker", str(CHECKER),
                  "--expected-evaluator", exp_eval or EVAL_ID,
                  "--expected-checker", exp_chk or CHK_ID])
        return cp.returncode, (cp.stderr or cp.stdout)
    finally:
        os.unlink(path)


def observed_reason(stderr: str) -> str:
    for tok in stderr.split():
        if tok.startswith("reason="):
            return tok[len("reason="):]
    return ""


ROWS: list[dict] = []


def stable_diagnostic(text: str) -> str:
    """Remove runtime-only identifiers while preserving refusal semantics.

    Rust panic diagnostics include a per-thread numeric id.  Recording that id
    made the durable evidence and every package containing it change on each
    otherwise identical run.  Normalize only that known volatile field.
    """
    return re.sub(r"(thread '<unnamed>' \()\d+(\) panicked at)", r"\1<TID>\2", text)


def record(cid: str, layer_expected: str, invoked: str, argv_sanitized: str,
           exit_code: int, reason_observed: str, layer_observed: str,
           marker_expected: str, stderr: str) -> None:
    stderr = stable_diagnostic(stderr)
    reason_observed = stable_diagnostic(reason_observed)
    failed = (exit_code != 0 and layer_observed == layer_expected
              and (marker_expected == "" or marker_expected in reason_observed
                   or marker_expected in stderr))
    ROWS.append({
        "id": cid,
        "evaluator_sha256": EVAL_ID,
        "checker_sha256": CHK_ID,
        "invoked_boundary": invoked,
        "argv": argv_sanitized,
        "exit_code": exit_code,
        "layer_expected": layer_expected,
        "layer_observed": layer_observed,
        "reason_observed": reason_observed,
        "marker_expected": marker_expected,
        "stderr_digest": DIG(stderr),
        "executed": True,
        "failed_as_intended": failed,
    })


def ctl_validator(cid: str, cert_text: str, expected_reason: str, *,
                  expr="x^2+1", lo="1", hi="2", exp_eval=None, exp_chk=None) -> None:
    code, err = validate_cert_text(cert_text, expr, lo, hi, exp_eval, exp_chk)
    record(cid, "VALIDATE_REFUSE", "release_validate.py --cert",
           f"expr={expr} lo={lo} hi={hi}", code, observed_reason(err),
           "VALIDATE_REFUSE" if code != 0 else "NONE", expected_reason, err)


def ctl_checker(cid: str, cert_text: str, marker: str = "REJECT") -> None:
    cp = check_cert_text(cert_text)
    layer = "CHECK_REJECT" if cp.returncode != 0 else "NONE"
    record(cid, "CHECK_REJECT", "jackal_cert_check", "<cert file>",
           cp.returncode, (cp.stderr or cp.stdout).strip()[:80], layer, marker,
           cp.stderr or cp.stdout)


def ctl_engine(cid: str, expr: str, lo: str, hi: str, marker: str) -> None:
    cp = emit_cert(expr, lo, hi)
    layer = "ENGINE_REFUSE" if cp.returncode != 0 else "NONE"
    record(cid, "ENGINE_REFUSE", "range-bound-cert", f"expr={expr} lo={lo} hi={hi}",
           cp.returncode, cp.stderr.strip()[:80], layer, marker, cp.stderr)


def main() -> int:
    base = valid_cert()

    # ---- request / source / input binding (validator layer) ----
    ctl_validator("C01-source-altered",
                  _replace_line(base, "source ", "source Rk9SR0VELVNPVVJDRQ=="), "request-commitment")
    ctl_validator("C02-request-framing-altered",
                  _replace_line(base, "source ", "source " + base64.b64encode(b"deadbeef").decode()),
                  "request-commitment")
    ctl_validator("C03-input-replay", base, "request-commitment", lo="1", hi="3")
    ctl_validator("C04-expr-replay", valid_cert("x^3", "1", "2"), "request-commitment",
                  expr="x^2+1", lo="1", hi="2")

    # ---- evaluator identity (validator layer) ----
    ctl_validator("C05-exe-empty", _replace_line(base, "exe ", "exe"), "evaluator-cert-identity")
    ctl_validator("C06-exe-forged", _replace_line(base, "exe ", "exe forged-evaluator-sha256"),
                  "evaluator-cert-identity")
    ctl_validator("C07-exe-stale", _replace_line(base, "exe ", "exe " + ("a" * 64)),
                  "evaluator-cert-identity")
    ctl_validator("C08-eval-substituted", base, "evaluator-identity", exp_eval="b" * 64)
    ctl_validator("C09-eval-expected-malformed", base, "evaluator-expected-malformed",
                  exp_eval="not-a-hash")

    # ---- checker identity (validator layer) ----
    ctl_validator("C10-checker-substituted", base, "checker-identity", exp_chk="c" * 64)
    ctl_validator("C11-checker-expected-malformed", base, "checker-expected-malformed",
                  exp_chk="short")

    # ---- model / status (validator + checker) ----
    ctl_validator("C12-model-replay", _replace_line(base, "model ", "model jackal-iv-model-vX"),
                  "cert-model")
    ctl_validator("C13-status-escalation", _replace_line(base, "status ", "status estimated"),
                  "cert-status")

    # ---- certificate mutation before check (checker layer) ----
    ctl_checker("C14-output-mutated", _mutate_first_node_out(base))
    ctl_checker("C15-dup-node-id", _dup_first_node(base))
    ctl_checker("C16-dup-header-key", _dup_line(base, "model "))
    ctl_checker("C17-truncated", "\n".join(base.rstrip("\n").split("\n")[:-1]) + "\n")
    ctl_checker("C18-appended-bytes", base + "GARBAGE\n")
    ctl_checker("C19-noncanonical-rat", _replace_line(base, "input ", "input 2/1 2"))
    ctl_checker("C20-swapped-noncommutative", _swap_sub_children(valid_cert("x-1", "1", "2")))
    ctl_checker("C21-forged-den-guard", _flip_div_den(valid_cert("1/(x+2)", "1", "2")))
    ctl_checker("C22-unreachable-node", _add_unreachable_node(base))
    ctl_checker("C23-self-cycle", _make_self_child(base))

    # ---- engine fail-closed (engine layer) ----
    ctl_engine("C24-unsupported-op", "sqrt(x)", "1", "2", "fail closed")
    ctl_engine("C25-invalid-domain-divzero", "1/x", "-1", "1", "containing zero")
    ctl_engine("C26-neg-power-fail-closed", "x^-2", "1", "2", "negative integer powers")

    # ---- TOCTOU: mutate cert after binding, before check (validator seam) ----
    ctl_toctou("C27-cert-post-check-mutation")

    # ---- missing executables (validator) ----
    ctl_missing("C28-missing-evaluator", which="evaluator")
    ctl_missing("C29-missing-checker", which="checker")

    # ---- A→B→A receipt validation row ----
    ctl_aba_receipt("C30-aba-receipt")

    OUT_JSONL.write_text("\n".join(json.dumps(r, sort_keys=True) for r in ROWS) + "\n")
    REPO_EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    REPO_EVIDENCE.write_text(OUT_JSONL.read_text())
    digest = hashlib.sha256(OUT_JSONL.read_bytes()).hexdigest()
    passed = sum(1 for r in ROWS if r["failed_as_intended"])
    total = len(ROWS)
    print(f"controls={total} executed={sum(1 for r in ROWS if r['executed'])} "
          f"failed_as_intended={passed}")
    print(f"jsonl={OUT_JSONL} repo={REPO_EVIDENCE} sha256={digest}")
    if passed != total:
        for r in ROWS:
            if not r["failed_as_intended"]:
                print(f"  UNMET {r['id']}: exit={r['exit_code']} "
                      f"expected={r['layer_expected']} observed={r['layer_observed']} "
                      f"reason={r['reason_observed']!r}", file=sys.stderr)
        print("VERDICT: FAIL — a control did not refuse at its intended layer")
        return 1
    print("VERDICT: PASS — every control executed and refused at its intended layer")
    return 0


# ---- poison constructors (pure string surgery over the canonical cert) ----
def _replace_line(cert: str, prefix: str, newline: str) -> str:
    """Replace the FIRST line equal to prefix (trimmed) or starting with it."""
    lines = cert.split("\n")
    for i, ln in enumerate(lines):
        if ln == prefix.rstrip() or ln.startswith(prefix):
            lines[i] = newline
            return "\n".join(lines)
    return cert


def _dup_line(cert: str, prefix: str) -> str:
    lines = cert.split("\n")
    for i, ln in enumerate(lines):
        if ln.startswith(prefix):
            return "\n".join(lines[:i + 1] + [ln] + lines[i + 1:])
    return cert


def _mutate_first_node_out(cert: str) -> str:
    lines = cert.split("\n")
    for i, ln in enumerate(lines):
        if ln.startswith("node ") and "out[" in ln:
            a, _, rest = ln.partition("out[")
            inner, _, tail = rest.partition("]")
            lines[i] = f"{a}out[999,{inner.split(',')[1]}]{tail}"
            break
    return "\n".join(lines)


def _dup_first_node(cert: str) -> str:
    lines = cert.split("\n")
    for i, ln in enumerate(lines):
        if ln.startswith("node "):
            return "\n".join(lines[:i + 1] + [ln] + lines[i + 1:])
    return cert


def _swap_sub_children(cert: str) -> str:
    lines = cert.split("\n")
    for i, ln in enumerate(lines):
        if ln.startswith("node ") and " sub " in ln and "children[" in ln:
            a, _, rest = ln.partition("children[")
            inner, _, tail = rest.partition("]")
            ch = inner.split(",")
            if len(ch) == 2:
                lines[i] = f"{a}children[{ch[1]},{ch[0]}]{tail}"
            break
    return "\n".join(lines)


def _flip_div_den(cert: str) -> str:
    lines = cert.split("\n")
    for i, ln in enumerate(lines):
        if ln.startswith("node ") and " div " in ln and " den " in ln:
            parts = ln.split(" den ")
            sign = parts[1].strip()
            lines[i] = parts[0] + " den " + ("-1" if sign == "1" else "1")
            break
    return "\n".join(lines)


def _add_unreachable_node(cert: str) -> str:
    lines = cert.split("\n")
    # insert a node with a fresh id not referenced by the root subtree
    ids = [int(ln.split()[1]) for ln in lines if ln.startswith("node ")]
    newid = max(ids) + 5
    extra = f"node {newid} var children[] out[1,2] name x"
    for i, ln in enumerate(lines):
        if ln == "end":
            return "\n".join(lines[:i] + [extra] + lines[i:])
    return cert


def _make_self_child(cert: str) -> str:
    """Point the highest-id (root) node's first child at its own id, creating a
    child id == parent id (childrenOk requires child < parent → reject)."""
    lines = cert.split("\n")
    node_idx = [(int(ln.split()[1]), i) for i, ln in enumerate(lines) if ln.startswith("node ")]
    _, i = max(node_idx)
    ln = lines[i]
    nid = ln.split()[1]
    a, _, rest = ln.partition("children[")
    inner, _, tail = rest.partition("]")
    lines[i] = f"{a}children[{nid}{(',' + inner) if inner else ''}]{tail}"
    return "\n".join(lines)


def ctl_toctou(cid: str) -> None:
    """Mutate the cert AFTER binding but BEFORE check via the explicit seam;
    the validator's post-check hash-stability gate must refuse."""
    req = rv.request_commitment_b64(rv.COMMAND_ID, "x^2+1", "1", "2")
    wd = tempfile.mkdtemp(prefix="jackal-toctou-")
    reason = ""
    code = 0
    try:
        def mutate(path):
            with open(path, "a") as f:
                f.write("GARBAGE\n")
        try:
            rv.validate_release(expr="x^2+1", lo="1", hi="2",
                                evaluator=str(EVALUATOR), checker=str(CHECKER),
                                expected_evaluator=EVAL_ID, expected_checker=CHK_ID,
                                workdir=wd, post_check_mutate=mutate)
            code, reason = 0, "NO-REFUSAL"
        except rv.ReleaseRefusal as r:
            code, reason = 1, r.cls
    finally:
        pass
    record(cid, "VALIDATE_REFUSE", "release_validate.validate_release(seam)",
           "expr=x^2+1 lo=1 hi=2", code, reason,
           "VALIDATE_REFUSE" if code != 0 else "NONE",
           "cert-toctou", reason)


def ctl_missing(cid: str, which: str) -> None:
    req = rv.request_commitment_b64(rv.COMMAND_ID, "x^2+1", "1", "2")
    ev = str(EVALUATOR) if which != "evaluator" else str(ROOT / "no-such-evaluator")
    ck = str(CHECKER) if which != "checker" else str(ROOT / "no-such-checker")
    code = 0
    reason = "NO-REFUSAL"
    try:
        rv.validate_release(expr="x^2+1", lo="1", hi="2", evaluator=ev, checker=ck,
                            expected_evaluator=EVAL_ID, expected_checker=CHK_ID)
    except rv.ReleaseRefusal as r:
        code, reason = 1, r.cls
    record(cid, "VALIDATE_REFUSE", "release_validate.validate_release",
           f"missing={which}", code, reason,
           "VALIDATE_REFUSE" if code != 0 else "NONE",
           f"{which}-missing", reason)


def ctl_aba_receipt(cid: str) -> None:
    """Validate the M1/M2 A→B→A receipt if present; refuse (fail row) if the
    receipt is absent or does not show the required transitions."""
    receipt = ROOT / "release/evidence/aba_mutations.json"
    ok = False
    detail = "receipt-absent"
    if receipt.exists():
        try:
            data = json.loads(receipt.read_text())
            muts = data.get("mutations", {})
            ok = all(
                muts.get(m, {}).get("A_pre") == "pass"
                and muts.get(m, {}).get("B") == "red-for-intended-reason"
                and muts.get(m, {}).get("A_post") == "pass"
                and muts.get(m, {}).get("restore_hash_verified") is True
                for m in ("M1", "M2"))
            detail = "transitions-verified" if ok else "transitions-incomplete"
        except Exception as e:  # noqa: BLE001
            detail = f"receipt-malformed:{e}"
    ROWS.append({
        "id": cid, "evaluator_sha256": EVAL_ID, "checker_sha256": CHK_ID,
        "invoked_boundary": "aba-receipt-parse", "argv": str(receipt.name),
        "exit_code": 0 if ok else 1, "layer_expected": "ABA_RECEIPT",
        "layer_observed": "ABA_RECEIPT" if ok else "MISSING",
        "reason_observed": detail, "marker_expected": "transitions-verified",
        "stderr_digest": DIG(detail), "executed": True, "failed_as_intended": ok,
    })


if __name__ == "__main__":
    sys.exit(main())
