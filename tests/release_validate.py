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
from pathlib import Path

# Load-bearing shared canonicalization used by BOTH this validator and the
# independent receipt verifier / Hermes plugin.  Import order picks the repo
# layout (tools/…) first, then the shipped-package layout (sibling).
_HERE = os.path.dirname(os.path.abspath(__file__))
if "formal_receipt" not in sys.modules:
    for _cand in (os.path.join(_HERE, "..", "tools"), _HERE):
        if os.path.exists(os.path.join(_cand, "formal_receipt.py")):
            sys.path.insert(0, _cand)
            break
from formal_receipt import (  # noqa: E402
    canonical_rat as _shared_canonical_rat,
    request_commitment_b64 as _shared_request_commitment_b64,
    build_formal_receipt, dump_receipt, load_proof_identity_binding,
    require_fresh_output, write_new_file_atomic,
)

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


# Backward-compatible re-exports of the shared helpers.  The load-bearing
# definitions live in `tools/formal_receipt.py` (§Bridge-3) so the release
# validator, the independent receipt verifier, and the Hermes plugin share
# the SAME framing byte-for-byte.
def request_commitment_b64(cmd: str, expr: str, lo: str, hi: str) -> str:
    return _shared_request_commitment_b64(cmd, expr, lo, hi)

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
    """Delegate to the shared canonicalization (see `tools/formal_receipt.py`).

    Wraps `ValueError` in `ReleaseRefusal("request-input-malformed", …)` so
    the caller's refusal-class contract is preserved."""
    try:
        return _shared_canonical_rat(tok)
    except ValueError as e:
        raise ReleaseRefusal("request-input-malformed", f"not a rational: {tok!r}") from e


def validate_release(*, expr: str, lo: str, hi: str, evaluator: str, checker: str,
                     expected_evaluator: str, expected_checker: str,
                     workdir: str | None = None, receipt_path: str | None = None,
                     formal_receipt_path: str | None = None,
                     plugin_sha256: str | None = None,
                     release_epoch: str = "v1.3.0",
                     post_check_mutate=None) -> dict:
    """Run the full bound release pipeline. Returns a receipt dict on success;
    raises ReleaseRefusal (stable class) on any failure. `post_check_mutate` is
    an EXPLICIT test seam (a callable(cert_path) run once after checking) used
    only by the TOCTOU control; it is None in production and structurally
    unreachable there.

    When `formal_receipt_path` is supplied, additionally writes the canonical
    `jackal-formal-receipt-v1` JSON receipt (§7 of the mission brief) with
    the certificate bytes EMBEDDED so an independent verifier can re-run the
    proved checker without seeing the original cert file.  The receipt's
    `identities.plugin_sha256` is populated from `plugin_sha256` when the
    caller is the Hermes plugin (else `null`).
    """
    # Gate 11 (pre): release output is write-once.  Never remove or overwrite a
    # caller path—even on failure—because it may alias a manifest, checker, or
    # unrelated user file.  Atomic publication below independently repeats the
    # no-clobber guarantee to close the check/create race.
    output_paths: dict[str, Path] = {}
    for label, raw in (("receipt", receipt_path),
                       ("formal-receipt", formal_receipt_path)):
        if raw:
            try:
                output_paths[label] = require_fresh_output(raw)
            except FileExistsError as exc:
                raise ReleaseRefusal("receipt-output-exists", str(exc)) from exc
            except OSError as exc:
                raise ReleaseRefusal("receipt-output-path", str(exc)) from exc
    if len(set(output_paths.values())) != len(output_paths):
        raise ReleaseRefusal("receipt-output-alias", "receipt outputs must differ")

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
    created: list[tuple[Path, os.stat_result]] = []
    try:
        if receipt_path:
            basic_bytes = (json.dumps(receipt, sort_keys=True, indent=2) + "\n").encode("utf-8")
            created_path = write_new_file_atomic(output_paths["receipt"], basic_bytes)
            created.append((created_path, os.lstat(created_path)))
        if formal_receipt_path:
            with open(cert_path, "rb") as f:
                cert_bytes = f.read()
            created_path = _emit_formal_receipt(
                output_paths["formal-receipt"], receipt=receipt,
                cert_bytes=cert_bytes, expr=expr, lo=lo, hi=hi,
                plugin_sha256=plugin_sha256, release_epoch=release_epoch)
            created.append((created_path, os.lstat(created_path)))
    except Exception as exc:
        for created_path, identity in reversed(created):
            try:
                observed = os.lstat(created_path)
                if (observed.st_dev, observed.st_ino) == \
                        (identity.st_dev, identity.st_ino):
                    os.unlink(created_path)
            except FileNotFoundError:
                pass
        if isinstance(exc, ReleaseRefusal):
            raise
        if isinstance(exc, FileExistsError):
            raise ReleaseRefusal("receipt-output-exists", str(exc)) from exc
        raise ReleaseRefusal("receipt-output-create", str(exc)) from exc
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

    # Gate 1/7: the proved checker adjudicates the EXACT cert bytes on disk in
    # request-bound mode.  Since the §487-parserdiff audit the ACCEPT line
    # carries the checker's AUTHORITATIVE `output <lo> <hi>` echo (the root
    # enclosure `structuralOk` binds and `request_bound_certified_release`
    # encloses).  The release gate requires:
    #   (a) exit 0 AND the exact ACCEPT prefix;
    #   (b) a well-formed two-token rational echo;
    #   (c) echo == the independently parsed header output (parser-differential
    #       divergence between Lean's and Python's view is a REFUSAL, never a
    #       "pick one").
    cproc = subprocess.run(
        [chk_real, cert_path, COMMAND_ID, expr, canonical_rat(lo), canonical_rat(hi)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=3600,
    )
    expected_accept_prefix = (
        "ACCEPT request-bound theorem=request_bound_certified_release "
        "command=range-bound-cert output "
    )
    accept_line = cproc.stdout.strip()
    if cproc.returncode != 0 or not accept_line.startswith(expected_accept_prefix):
        raise ReleaseRefusal("checker-rejected",
                             (cproc.stderr.strip() or accept_line)[:200])
    echo_tokens = accept_line[len(expected_accept_prefix):].split(" ")
    if len(echo_tokens) != 2:
        raise ReleaseRefusal("checker-echo-malformed", accept_line[:200])
    echo_lo, echo_hi = echo_tokens
    if echo_lo != hdr["output_lo"] or echo_hi != hdr["output_hi"]:
        raise ReleaseRefusal("checker-echo-divergence",
                             f"checker attested [{echo_lo},{echo_hi}] != header "
                             f"[{hdr['output_lo']},{hdr['output_hi']}]")

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
    if "formal_status_gate" not in sys.modules:
        sys.path.insert(0, _here)                               # package: sibling
        sys.path.insert(0, os.path.join(_here, "..", "tools"))  # repo: tools/
    import formal_status_gate as fsg
    try:
        inv = fsg.load_inventory()
        formal_ops = fsg.formal_operators(inv)
        nonformal = sorted(ops - formal_ops)
        if nonformal:
            raise ReleaseRefusal("not-formal-fragment", f"operators outside formal fragment: {nonformal}")
        for op in sorted(ops):
            fsg.derive_status(operator=op, requested="formal-bounded", checker_accepted=True,
                              certificate_sha256=cert_hash_pre,
                              theorem_id="request_bound_certified_release",
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



def _emit_formal_receipt(path: str | Path, *, receipt: dict, cert_bytes: bytes,
                         expr: str, lo: str, hi: str,
                         plugin_sha256: str | None,
                         release_epoch: str) -> Path:
    """Emit the canonical `jackal-formal-receipt-v1` JSON receipt (§7).

    Populates `identities.source_anb_sha256` from the repo's `jackal_calc.anb`
    when it is discoverable next to this validator; None in the shipped
    package layout (integrity is via SHA256SUMS there).
    """
    _here = os.path.dirname(os.path.abspath(__file__))
    src_candidates = [
        os.path.join(_here, "..", "jackal_calc.anb"),
        os.path.join(_here, "jackal_calc.anb"),
    ]
    source_anb_sha256 = None
    for cand in src_candidates:
        if os.path.exists(cand):
            source_anb_sha256 = sha256_file(os.path.realpath(cand))
            break
    # `admitted_operators` = the FULL live-verified FORMAL fragment (§Fragment).
    # `coverage_row_ids` = the operators the accepted cert actually used.
    # `unsupported_refused` = the fragment-adjacent operators that fail closed.
    coverage = sorted(receipt["operators"])
    admitted: list[str]
    refused: list[str]
    coverage_inventory_sha256: str
    try:
        if "formal_status_gate" not in sys.modules:
            sys.path.insert(0, os.path.join(_here, "..", "tools"))
            sys.path.insert(0, _here)
        import formal_status_gate as fsg  # noqa: E402
        inv = fsg.load_inventory(verify_integrity=False)
        admitted = sorted(fsg.formal_operators(inv))
        refused = sorted(op for op, r in inv["by_op"].items() if r["verdict"] == "REFUSED")
        coverage_inventory_sha256 = sha256_file(str(fsg.INVENTORY))
    except Exception as exc:  # noqa: BLE001
        raise ReleaseRefusal("receipt-inventory", str(exc)) from exc
    proof_candidates = [
        os.path.join(_here, "..", "release", "evidence", "range_proof_identity.json"),
        os.path.join(_here, "range_proof_identity.json"),
    ]
    proof_path = next((candidate for candidate in proof_candidates
                       if os.path.isfile(candidate)), None)
    if proof_path is None:
        raise ReleaseRefusal("receipt-proof-identity", "range proof identity missing")
    try:
        proof_identity = load_proof_identity_binding(proof_path)
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ReleaseRefusal("receipt-proof-identity", str(exc)) from exc
    if proof_identity["checker_sha256"] != receipt["checker_sha256"]:
        raise ReleaseRefusal("receipt-proof-checker", "range proof/checker identity mismatch")
    if proof_identity["soundness_theorem"] != \
            "JackalIv.Cert.request_bound_certified_release":
        raise ReleaseRefusal("receipt-proof-theorem", proof_identity["soundness_theorem"])
    formal_receipt = build_formal_receipt(
        release_epoch=release_epoch,
        request={"command": COMMAND_ID, "expression": expr,
                 "input_lo": lo, "input_hi": hi},
        enclosure=(receipt["certified_enclosure"][0], receipt["certified_enclosure"][1]),
        cert_bytes=cert_bytes,
        evaluator_sha256=receipt["evaluator_sha256"],
        checker_sha256=receipt["checker_sha256"],
        source_anb_sha256=source_anb_sha256,
        plugin_sha256=plugin_sha256,
        admitted_operators=admitted,
        coverage_row_ids=coverage,
        unsupported_refused=refused,
        canonical_lo=canonical_rat(lo),
        canonical_hi=canonical_rat(hi),
        request_commitment_b64=receipt["request_commitment"],
        coverage_inventory_sha256=coverage_inventory_sha256,
        proof_identity=proof_identity,
        cert_status=receipt["cert_status"],
    )
    return write_new_file_atomic(
        path, (dump_receipt(formal_receipt) + "\n").encode("utf-8")
    )

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
    ap.add_argument("--formal-receipt", default=None,
                    help="emit jackal-formal-receipt-v1 JSON (embedded cert; §7)")
    ap.add_argument("--plugin-sha256", default=None,
                    help="pin the Hermes plugin binary hash into the formal receipt")
    ap.add_argument("--release-epoch", default="v1.3.0",
                    help="release epoch label recorded in the formal receipt")
    ap.add_argument("--expected-source", default=None,
                    help="caller-pinned jackal_calc.anb SHA-256")
    ap.add_argument("--inventory", default=None,
                    help="caller-pinned coverage inventory JSON")
    ap.add_argument("--expected-inventory", default=None,
                    help="caller-pinned coverage inventory SHA-256")
    ap.add_argument("--proof-identity", default=None,
                    help="caller-pinned range proof identity JSON")
    ap.add_argument("--expected-proof-identity-file", default=None,
                    help="caller-pinned proof identity file SHA-256")
    ap.add_argument("--expected-proof-identity-digest", default=None,
                    help="caller-pinned internal proof identity digest")
    ap.add_argument("--cert", default=None,
                    help="validate an EXISTING cert file (no emission); for controls")
    args = ap.parse_args()
    created_outputs: list[tuple[Path, os.stat_result]] = []
    try:
        if args.cert is None and args.formal_receipt is None:
            raise ReleaseRefusal(
                "formal-receipt-required",
                "release mode must emit and independently reverify a receipt",
            )
        if args.cert is None and not (sys.flags.isolated and sys.flags.no_site):
            raise ReleaseRefusal(
                "python-not-isolated", "invoke jackal-cert-release"
            )
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
                expected_checker=args.expected_checker,
                receipt_path=args.receipt,
                formal_receipt_path=args.formal_receipt,
                plugin_sha256=args.plugin_sha256,
                release_epoch=args.release_epoch)
            for raw in (args.receipt, args.formal_receipt):
                if raw:
                    created_path = Path(os.path.abspath(os.path.expanduser(raw)))
                    created_outputs.append((created_path, os.lstat(created_path)))
            if args.formal_receipt is not None:
                required_reverify = {
                    "expected-source": args.expected_source,
                    "inventory": args.inventory,
                    "expected-inventory": args.expected_inventory,
                    "proof-identity": args.proof_identity,
                    "expected-proof-identity-file": args.expected_proof_identity_file,
                    "expected-proof-identity-digest": args.expected_proof_identity_digest,
                }
                missing = sorted(k for k, v in required_reverify.items() if not v)
                if missing:
                    raise ReleaseRefusal("receipt-reverify-context", str(missing))
                import receipt_verify as vr  # noqa: E402
                try:
                    formal_doc = vr._strict_json_bytes(  # noqa: SLF001
                        Path(args.formal_receipt).read_bytes()
                    )
                    rerun = vr.verify_receipt(
                        receipt=formal_doc,
                        checker=args.checker,
                        expected_evaluator=args.expected_evaluator,
                        expected_checker=args.expected_checker,
                        inventory_path=Path(args.inventory),
                        expected_inventory_sha256=args.expected_inventory,
                        proof_identity_path=Path(args.proof_identity),
                        expected_proof_identity_file=args.expected_proof_identity_file,
                        expected_proof_identity_digest=args.expected_proof_identity_digest,
                        expected_plugin=args.plugin_sha256,
                        expected_source=args.expected_source,
                        expected_release_epoch=args.release_epoch,
                        expected_request={
                            "command": COMMAND_ID,
                            "expression": args.expr,
                            "input_lo": args.lo,
                            "input_hi": args.hi,
                        },
                    )
                except (OSError, UnicodeDecodeError, ValueError,
                        vr.ReceiptRefusal) as exc:
                    if isinstance(exc, vr.ReceiptRefusal):
                        detail = f"{exc.cls}: {exc.detail}"
                    else:
                        detail = str(exc)
                    raise ReleaseRefusal("receipt-reverify", detail) from exc
                if rerun.get("verdict") != "ACCEPT":
                    raise ReleaseRefusal("receipt-reverify", str(rerun.get("verdict")))
    except (ReleaseRefusal, OSError) as exc:
        for created_path, identity in reversed(created_outputs):
            try:
                observed = os.lstat(created_path)
                if (observed.st_dev, observed.st_ino) == \
                        (identity.st_dev, identity.st_ino):
                    os.unlink(created_path)  # GATE-M10-owned-output-cleanup
            except FileNotFoundError:
                pass
        r = (exc if isinstance(exc, ReleaseRefusal)
             else ReleaseRefusal("receipt-output-lifecycle", str(exc)))
        print(f"status=refused reason={r.cls} detail=\"{r.detail}\"", file=sys.stderr)
        return 1
    if args.cert is not None:
        print("status=diagnostic-checker-accepted")
    else:
        print(f"status={receipt['status']}")
    print(f"cert-status={receipt['cert_status']}")
    print(f"certified-enclosure=[{receipt['certified_enclosure'][0]},{receipt['certified_enclosure'][1]}]")
    print(f"input=[{receipt['input'][0]},{receipt['input'][1]}]")
    print(f"assurance={receipt['assurance']}")
    print(f"evaluator.sha256={receipt['evaluator_sha256']}")
    print(f"checker.sha256={receipt['checker_sha256']}")
    print(f"certificate.sha256={receipt['certificate_sha256']}")
    print(f"request.commitment={receipt['request_commitment']}")
    if args.formal_receipt is not None:
        print("receipt.reverified=true")
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
