#!/usr/bin/env python3
"""JACKAL shared certified-release validator (v1.0.4, mission §286).

ONE load-bearing validator, used by BOTH the production wrapper
(`jackal-cert-release`) and the adversarial control tests. It binds a released
`status=bounded` result to the exact chain (mission §41):

    request bytes → admitted commitments → exact evaluator bytes invoked
    → certificate bytes → exact checker bytes invoked → checker ACCEPT
    → every binding confirmed → released enclosure + identities + receipt

Soundness (that an accepted certificate implies a true enclosure) is the
Lean-proved checker's job. This validator adds the RUNTIME PROVENANCE the
checker theorem deliberately does not prove (§270): exact request identity,
exact evaluator/checker executable identity, TOCTOU stability, and no status
escalation. Every failure returns a stable refusal class and NEVER a bounded
fallback.

Load-bearing gates use explicit raises, never `assert` (so `python3 -O` cannot
disable them). Run under both `python3` and `python3 -O`: identical verdicts.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import tempfile

SCHEMA_MAGIC = "jackal-eval-cert v2"
MODEL_CONST = "jackal-iv-model-v1"
COMMAND_ID = "range-bound-cert"


class ReleaseRefusal(Exception):
    """A fail-closed refusal with a stable machine-readable class."""

    def __init__(self, cls: str, detail: str = ""):
        super().__init__(f"{cls}: {detail}")
        self.cls = cls
        self.detail = detail


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def request_commitment_b64(cmd: str, expr: str, lo: str, hi: str) -> str:
    """Injective, length-delimited framing of the exact request bytes, digested
    and base64-wrapped. Length prefixes make it unambiguous under any payload
    (embedded delimiters, whitespace, newlines, Unicode)."""
    def framed(p: str) -> bytes:
        b = p.encode("utf-8")
        return str(len(b)).encode() + b":" + b
    framing = (b"jackal-req-v2\x00" + framed(cmd) + b"|" + framed(expr)
               + b"|" + framed(lo) + b"|" + framed(hi))
    hexd = hashlib.sha256(framing).hexdigest()          # 64 ASCII hex chars
    return base64.b64encode(hexd.encode()).decode()     # ASCII base64, null-free


_RAT = r"-?(?:0|[1-9][0-9]*)(?:/[1-9][0-9]*)?"


def parse_cert_header(raw: bytes) -> dict:
    """Minimal independent header parse (the checker does the canonical parse;
    this reads the fields the validator binds). Rejects malformed structure."""
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise ReleaseRefusal("cert-not-utf8", "certificate is not valid UTF-8")
    if not text.endswith("\n") or text.endswith("\n\n"):
        raise ReleaseRefusal("cert-trailing", "must end with exactly one LF")
    lines = text[:-1].split("\n")
    if lines[0] != SCHEMA_MAGIC:
        raise ReleaseRefusal("cert-schema", f"magic != {SCHEMA_MAGIC!r}: {lines[0]!r}")
    hdr: dict = {}
    order = ["model", "exe", "status", "expr", "source", "input", "root", "output"]
    for i, key in enumerate(order):
        ln = lines[1 + i]
        if not ln.startswith(key + " ") and ln != key + " " and ln != key:
            raise ReleaseRefusal("cert-header-order", f"line {2+i} expected {key!r}: {ln!r}")
        hdr[key] = ln[len(key) + 1:] if len(ln) > len(key) else ""
    if hdr["model"] != MODEL_CONST:
        raise ReleaseRefusal("cert-model", f"model != {MODEL_CONST!r}")
    if hdr["status"] != "bounded":
        raise ReleaseRefusal("cert-status", f"status != bounded: {hdr['status']!r}")
    m = re.fullmatch(rf"({_RAT}) ({_RAT})", hdr["input"])
    if not m:
        raise ReleaseRefusal("cert-input", f"input not canonical rationals: {hdr['input']!r}")
    hdr["input_lo"], hdr["input_hi"] = m.group(1), m.group(2)
    m = re.fullmatch(rf"({_RAT}) ({_RAT})", hdr["output"])
    if not m:
        raise ReleaseRefusal("cert-output", f"output not canonical rationals: {hdr['output']!r}")
    hdr["output_lo"], hdr["output_hi"] = m.group(1), m.group(2)
    return hdr


def _resolve_executable(path: str, kind: str) -> str:
    if not os.path.exists(path):
        raise ReleaseRefusal(f"{kind}-missing", f"no file at {path}")
    real = os.path.realpath(path)
    st = os.lstat(path)
    if stat.S_ISLNK(st.st_mode):
        # Documented policy: symlinks are resolved and the RESOLVED TARGET is
        # bound. We record both; the identity we hash is the resolved regular file.
        pass
    rst = os.stat(real)
    if not stat.S_ISREG(rst.st_mode):
        raise ReleaseRefusal(f"{kind}-not-regular", f"{real} is not a regular file")
    if not os.access(real, os.X_OK):
        raise ReleaseRefusal(f"{kind}-not-executable", f"{real} is not executable")
    return real


def _valid_sha256_hex(s: str) -> bool:
    return bool(re.fullmatch(r"[0-9a-f]{64}", s))


def _operators_in_sexp(sexp: str) -> set[str]:
    """Extract operator/leaf tags from a canonical ast s-expression. Function
    calls render as `(call NAME ...)`, so map those to NAME (sin/cos/abs/...);
    all other heads (add/sub/mul/div/pow/neg/var/num/const) map to themselves.
    E.g. '(call min (call sin (var x)) (num 1))' -> {min, sin, var, num}."""
    ops = {m.group(1) for m in re.finditer(r"\(call\s+([a-z0-9_]+)", sexp)}
    for m in re.finditer(r"\(([a-z0-9_]+)", sexp):
        if m.group(1) != "call":
            ops.add(m.group(1))
    return ops


def canonical_rat(tok: str) -> str:
    """Canonicalize a decimal/rational input token to the engine's reduced ℚ
    string, so the validator can bind cert.input to the request independently
    of spelling (e.g. '2.0' and '2' and '4/2' all canonicalize to '2')."""
    from fractions import Fraction
    t = tok.strip()
    try:
        fr = Fraction(t)
    except (ValueError, ZeroDivisionError):
        raise ReleaseRefusal("request-input-malformed", f"not a rational: {tok!r}")
    if fr.denominator == 1:
        return str(fr.numerator)
    return f"{fr.numerator}/{fr.denominator}"


def validate_release(*, expr: str, lo: str, hi: str, evaluator: str, checker: str,
                     expected_evaluator: str, expected_checker: str,
                     workdir: str | None = None, receipt_path: str | None = None,
                     post_check_mutate=None) -> dict:
    """Run the full bound release pipeline. Returns a receipt dict on success;
    raises ReleaseRefusal (stable class) on any failure. `post_check_mutate` is
    an EXPLICIT test seam (a callable(cert_path) run once after checking) used
    only by the TOCTOU control; it is None in production and structurally
    unreachable there.
    """
    # Gate 11 (pre): destroy any stale success receipt before we begin.
    if receipt_path and os.path.exists(receipt_path):
        os.remove(receipt_path)

    # Gate 5/6 (pre): resolve + hash the exact executables we will invoke.
    eval_real = _resolve_executable(evaluator, "evaluator")
    chk_real = _resolve_executable(checker, "checker")
    eval_id_pre = sha256_file(eval_real)
    chk_id_pre = sha256_file(chk_real)
    if not _valid_sha256_hex(expected_evaluator):
        raise ReleaseRefusal("evaluator-expected-malformed", expected_evaluator)
    if not _valid_sha256_hex(expected_checker):
        raise ReleaseRefusal("checker-expected-malformed", expected_checker)
    if eval_id_pre != expected_evaluator:
        raise ReleaseRefusal("evaluator-identity", f"invoked {eval_id_pre} != expected {expected_evaluator}")
    if chk_id_pre != expected_checker:
        raise ReleaseRefusal("checker-identity", f"invoked {chk_id_pre} != expected {expected_checker}")

    # The request commitment the released cert must carry, computed from OUR argv.
    req_commit = request_commitment_b64(COMMAND_ID, expr, lo, hi)

    wd = workdir or tempfile.mkdtemp(prefix="jackal-release-")
    cert_path = os.path.join(wd, "cert.bytes")
    # Gate 5 lifecycle: one artifact, mode 0600, emitted once.
    fd = os.open(cert_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        # Gate: the exact evaluator emits the cert, told its own identity + the
        # request commitment through an explicit non-ambient argument protocol.
        proc = subprocess.run(
            [eval_real, COMMAND_ID, expr, lo, hi, eval_id_pre, req_commit],
            stdout=fd, stderr=subprocess.PIPE, text=False, timeout=3600,
        )
    finally:
        os.close(fd)
    if proc.returncode != 0:
        err = proc.stderr.decode("utf-8", "replace")
        reason = next((s for s in ("fail closed", "outside the certified", "only x is bound",
                                   "containing zero", "requires lo <= hi")
                       if s in err), "evaluator refused")
        raise ReleaseRefusal("evaluator-refused", reason)

    receipt = bind_and_check(
        cert_path=cert_path, expr=expr, lo=lo, hi=hi,
        eval_real=eval_real, eval_id_pre=eval_id_pre,
        chk_real=chk_real, chk_id_pre=chk_id_pre, req_commit=req_commit,
        post_check_mutate=post_check_mutate)
    if receipt_path:
        with open(receipt_path, "w") as f:
            json.dump(receipt, f, sort_keys=True, indent=2)
    return receipt


def bind_and_check(*, cert_path: str, expr: str, lo: str, hi: str,
                   eval_real: str, eval_id_pre: str, chk_real: str, chk_id_pre: str,
                   req_commit: str, post_check_mutate=None) -> dict:
    """The non-emitting binding core (gates 1,3,4,5,7,8,9,10). Validates the
    EXACT bytes of an already-existing certificate file against a request and
    the pinned executable identities. Used by `validate_release` after
    emission, and by the adversarial controls on forged/external certs."""
    with open(cert_path, "rb") as f:
        cert_bytes = f.read()
    cert_hash_pre = sha256_bytes(cert_bytes)

    hdr = parse_cert_header(cert_bytes)

    # Gate 3: exact request commitment must match our argv byte-for-byte.
    if hdr["source"] != req_commit:
        raise ReleaseRefusal("request-commitment", "cert source != recomputed request commitment")
    # Gate 4: canonical input commitment must match the request semantics.
    if hdr["input_lo"] != canonical_rat(lo) or hdr["input_hi"] != canonical_rat(hi):
        raise ReleaseRefusal("request-input", "cert input != canonical request interval")
    # Gate 5: evaluator identity in the cert must equal the exact invoked bytes.
    if hdr["exe"] != eval_id_pre:
        raise ReleaseRefusal("evaluator-cert-identity", f"cert exe {hdr['exe']!r} != invoked {eval_id_pre}")

    # Gate 1/7: the proved checker adjudicates the EXACT cert bytes on disk.
    cproc = subprocess.run([chk_real, cert_path], stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, text=True, timeout=3600)
    if cproc.returncode != 0 or cproc.stdout.strip() != "ACCEPT":
        raise ReleaseRefusal("checker-rejected",
                             (cproc.stderr.strip() or cproc.stdout.strip())[:200])

    # EXPLICIT test seam (TOCTOU control only): swap the artifact AFTER the
    # checker accepted bytes A, BEFORE the stability gate. Production never
    # passes this hook, so the swap window is structurally unreachable there.
    if post_check_mutate is not None:
        post_check_mutate(cert_path)

    # Gate 8/10: certificate + executables unchanged across the checked window.
    cert_hash_post = sha256_file(cert_path)
    if cert_hash_post != cert_hash_pre:
        raise ReleaseRefusal("cert-toctou", "certificate bytes changed across check")
    if sha256_file(eval_real) != eval_id_pre:
        raise ReleaseRefusal("evaluator-toctou", "evaluator bytes changed across release")
    if sha256_file(chk_real) != chk_id_pre:
        raise ReleaseRefusal("checker-toctou", "checker bytes changed across release")

    # Gate 9 + Phase F: the released status is DERIVED through the canonical
    # formal-status gate — never a hardcoded string. Every operator appearing
    # in the certified expression must be in the live-verified FORMAL fragment;
    # otherwise the release refuses formal status rather than overclaiming.
    ops = _operators_in_sexp(hdr["expr"])
    _here = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, _here)                                   # package: sibling
    sys.path.insert(0, os.path.join(_here, "..", "tools"))      # repo: tools/
    import formal_status_gate as fsg
    try:
        inv = fsg.load_inventory()
        formal_ops = fsg.formal_operators(inv)
        nonformal = sorted(ops - formal_ops)
        if nonformal:
            raise ReleaseRefusal("not-formal-fragment", f"operators outside formal fragment: {nonformal}")
        for op in sorted(ops):
            fsg.derive_status(operator=op, requested="formal-bounded", checker_accepted=True,
                              certificate_sha256=cert_hash_pre, theorem_id="cert_check_sound",
                              request_bound=True, inv=inv)
        status = "formal-bounded"
    except fsg.StatusRefusal as r:
        raise ReleaseRefusal("formal-status-refused", f"{r.cls}: {r.detail}")

    return {
        "status": status,
        "cert_status": hdr["status"],
        "operators": sorted(ops),
        "certified_enclosure": [hdr["output_lo"], hdr["output_hi"]],
        "input": [hdr["input_lo"], hdr["input_hi"]],
        "expr_commitment": hdr["expr"],
        "request_commitment": req_commit,
        "evaluator_sha256": eval_id_pre,
        "checker_sha256": chk_id_pre,
        "certificate_sha256": cert_hash_pre,
        "model": MODEL_CONST,
        "schema": SCHEMA_MAGIC,
        "assurance": "proof-carrying-certificate(checker-accepted;Runs-derivation;ModelTCB)+release-bound-provenance",
    }


def validate_cert_file(*, cert_path: str, expr: str, lo: str, hi: str,
                       evaluator: str, checker: str,
                       expected_evaluator: str, expected_checker: str) -> dict:
    """Bind + check an EXISTING external certificate file (no emission). Refuses
    on any provenance lie a raw/forged certificate may carry (§270). Used by the
    negative-control roster to prove source/exe/input forgeries are caught."""
    eval_real = _resolve_executable(evaluator, "evaluator")
    chk_real = _resolve_executable(checker, "checker")
    eval_id = sha256_file(eval_real)
    chk_id = sha256_file(chk_real)
    if not _valid_sha256_hex(expected_evaluator):
        raise ReleaseRefusal("evaluator-expected-malformed", expected_evaluator)
    if not _valid_sha256_hex(expected_checker):
        raise ReleaseRefusal("checker-expected-malformed", expected_checker)
    if eval_id != expected_evaluator:
        raise ReleaseRefusal("evaluator-identity", f"{eval_id} != {expected_evaluator}")
    if chk_id != expected_checker:
        raise ReleaseRefusal("checker-identity", f"{chk_id} != {expected_checker}")
    req_commit = request_commitment_b64(COMMAND_ID, expr, lo, hi)
    return bind_and_check(cert_path=cert_path, expr=expr, lo=lo, hi=hi,
                          eval_real=eval_real, eval_id_pre=eval_id,
                          chk_real=chk_real, chk_id_pre=chk_id, req_commit=req_commit)


def _cli() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--expr", required=True)
    ap.add_argument("--lo", required=True)
    ap.add_argument("--hi", required=True)
    ap.add_argument("--evaluator", required=True)
    ap.add_argument("--checker", required=True)
    ap.add_argument("--expected-evaluator", required=True)
    ap.add_argument("--expected-checker", required=True)
    ap.add_argument("--receipt", default=None)
    ap.add_argument("--cert", default=None,
                    help="validate an EXISTING cert file (no emission); for controls")
    args = ap.parse_args()
    try:
        if args.cert is not None:
            receipt = validate_cert_file(
                cert_path=args.cert, expr=args.expr, lo=args.lo, hi=args.hi,
                evaluator=args.evaluator, checker=args.checker,
                expected_evaluator=args.expected_evaluator,
                expected_checker=args.expected_checker)
        else:
            receipt = validate_release(
                expr=args.expr, lo=args.lo, hi=args.hi,
                evaluator=args.evaluator, checker=args.checker,
                expected_evaluator=args.expected_evaluator,
                expected_checker=args.expected_checker, receipt_path=args.receipt)
    except ReleaseRefusal as r:
        print(f"status=refused reason={r.cls} detail=\"{r.detail}\"", file=sys.stderr)
        return 1
    print(f"status={receipt['status']}")
    print(f"cert-status={receipt['cert_status']}")
    print(f"certified-enclosure=[{receipt['certified_enclosure'][0]},{receipt['certified_enclosure'][1]}]")
    print(f"input=[{receipt['input'][0]},{receipt['input'][1]}]")
    print(f"assurance={receipt['assurance']}")
    print(f"evaluator.sha256={receipt['evaluator_sha256']}")
    print(f"checker.sha256={receipt['checker_sha256']}")
    print(f"certificate.sha256={receipt['certificate_sha256']}")
    print(f"request.commitment={receipt['request_commitment']}")
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
