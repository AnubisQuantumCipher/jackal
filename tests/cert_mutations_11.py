#!/usr/bin/env python3
"""JACKAL v1.4.1 eleven-category A→B→A mutation harness.

Extends the v1.0.4 two-mutation ABA (`tests/cert_aba_mutations.py`) to the
full trust-boundary matrix defined by the mission brief (§9, the eleven
mutation categories):

  M1  request changed after certificate production           → validator
  M2  canonical AST changed                                  → receipt verifier
  M3  result bound changed                                   → receipt verifier
  M4  certificate changed                                    → receipt verifier
  M5  tolerance / integration limits changed                 → validator
  M6  formal status added to an uncovered operation          → formal-status gate
  M7  checker binary substituted                             → receipt verifier
  M8  evaluator binary substituted                           → validator
  M9  outer digest recomputed after semantic tampering       → receipt verifier
  M10 stale success reused against a different request       → receipt verifier
  M11 public plugin binary replaced                          → plugin startup

Each mutation disables the named source gate with a same-indentation
`pass  # ABA-Mn-mutation`.  (M10 note: the writer never deletes pre-existing
outputs — `require_fresh_output` refuses them — so stale-success reuse is
defeated at verify time by the expected-request binding, which M10 attacks.)
For each row:

  A(pre)   the poison REFUSES for its named reason at its named layer;
  B        the SAME poison is either admitted after the gate is disabled, or
           (M5) remains refused by the independent Lean request matcher;
  A(post)  the EXACT pre-mutation bytes are restored (hash-verified),
           pyc caches purged, the poison refuses again for the same reason.

Writes a durable transcript to `release/evidence/mutations_11.json`.
"""
from __future__ import annotations

import base64
import copy
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = ROOT / "tests" / "release_validate.py"
VERIFIER = ROOT / "tools" / "receipt_verify.py"
VERIFIER_CLI = ROOT / "jackal-receipt-verify"
GATE = ROOT / "tools" / "formal_status_gate.py"
PLUGIN_SERVER = ROOT / "plugin" / "hermes" / "server.py"
PLUGIN_LAUNCHER = ROOT / "plugin" / "hermes" / "jackal_hermes"
PLUGIN_BUNDLE = ROOT / "plugin" / "hermes" / "bundle_hash.py"
INVENTORY = ROOT / "release" / "coverage" / "formal_coverage_inventory.json"
MANIFEST = ROOT / "release" / "MANIFEST.sha256"
EVALUATOR = ROOT / "jackal-native"
CHECKER = ROOT / "proofs" / "lean" / ".lake" / "build" / "bin" / "jackal_cert_check"
EVIDENCE = ROOT / "release" / "evidence" / "mutations_11.json"

sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "plugin" / "hermes"))
import release_validate as rv  # noqa: E402
from formal_receipt import (  # noqa: E402
    CURRENT_PROOF_RELEASE_EPOCH,
    recompute_receipt_digest,
)
from bundle_hash import compute_bundle_hash  # noqa: E402


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sha_file(p: Path) -> str:
    return sha(p.read_bytes())


def _manifest_ids() -> tuple[str, str, str]:
    ev = ck = pl = ""
    for ln in MANIFEST.read_text().splitlines():
        parts = ln.split()
        if len(parts) >= 3 and parts[0] == "evaluator":
            ev = parts[-1]
        elif len(parts) >= 3 and parts[0] == "checker":
            ck = parts[-1]
        elif len(parts) >= 2 and parts[0] == "plugin_hermes":
            pl = parts[-1]
    return ev, ck, pl


EVAL_ID, CHK_ID, PLUGIN_ID = _manifest_ids()
SOURCE_ID = sha_file(ROOT / "jackal_calc.anb")
RANGE_PROOF = ROOT / "release" / "evidence" / "range_proof_identity_v172.json"
RANGE_PROOF_FILE_ID = sha_file(RANGE_PROOF)
RANGE_PROOF_DIGEST = json.loads(RANGE_PROOF.read_text())["identity_digest_sha256"]
INVENTORY_ID = sha_file(INVENTORY)

_BASE_EXPR = "x^2+1"
_BASE_LO = "1"
_BASE_HI = "2"


def _fresh_valid_cert(expr: str = _BASE_EXPR, lo: str = _BASE_LO, hi: str = _BASE_HI) -> bytes:
    req = rv.request_commitment_b64(rv.COMMAND_ID, expr, lo, hi)
    cp = subprocess.run(
        [str(EVALUATOR), rv.COMMAND_ID, expr, lo, hi, EVAL_ID, req],
        capture_output=True, timeout=3600)
    if cp.returncode != 0:
        raise RuntimeError(f"evaluator refused: {cp.stderr.decode('utf-8','replace')}")
    return cp.stdout


def _fresh_formal_receipt(expr: str = _BASE_EXPR, lo: str = _BASE_LO, hi: str = _BASE_HI,
                          plugin_sha256: str | None = None) -> dict:
    with tempfile.TemporaryDirectory(prefix="mut11-") as td:
        p = os.path.join(td, "r.json")
        rv.validate_release(
            expr=expr, lo=lo, hi=hi,
            evaluator=str(EVALUATOR), checker=str(CHECKER),
            expected_evaluator=EVAL_ID, expected_checker=CHK_ID,
            formal_receipt_path=p,
            plugin_sha256=plugin_sha256 or PLUGIN_ID,
            release_epoch=CURRENT_PROOF_RELEASE_EPOCH)
        return json.loads(Path(p).read_text())


# --- runners --------------------------------------------------------------


def _run_validator_on_cert(cert_bytes: bytes, expr: str, lo: str, hi: str,
                            expected_evaluator: str | None = None,
                            expected_checker: str | None = None) -> tuple[int, str, str]:
    with tempfile.NamedTemporaryFile("wb", suffix=".cert", delete=False) as f:
        f.write(cert_bytes)
        cp_path = f.name
    try:
        cp = subprocess.run(
            [sys.executable, str(VALIDATOR),
             "--cert", cp_path, "--expr", expr, "--lo", lo, "--hi", hi,
             "--evaluator", str(EVALUATOR), "--checker", str(CHECKER),
             "--expected-evaluator", expected_evaluator or EVAL_ID,
             "--expected-checker", expected_checker or CHK_ID],
            capture_output=True, text=True, timeout=3600)
    finally:
        os.unlink(cp_path)
    reason = ""
    for tok in (cp.stderr or "").split():
        if tok.startswith("reason="):
            reason = tok.split("=", 1)[1]
    return cp.returncode, reason, "validator"


def _run_verifier_on_receipt(receipt: dict, checker: Path | None = None,
                              expected_eval: str | None = None,
                              expected_chk: str | None = None,
                              inventory: Path | None = INVENTORY,
                              expected_plugin: str | None = None) -> tuple[int, str, str]:
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(receipt, f, sort_keys=True, indent=2)
        rp = f.name
    argv = [str(VERIFIER_CLI),
            "--receipt", rp,
            "--checker", str(checker or CHECKER),
            "--expected-evaluator", expected_eval or EVAL_ID,
            "--expected-checker", expected_chk or CHK_ID,
            "--expected-release-epoch", CURRENT_PROOF_RELEASE_EPOCH,
            "--expected-command", "range-bound-cert",
            "--expected-expression", _BASE_EXPR,
            "--expected-input-lo", _BASE_LO,
            "--expected-input-hi", _BASE_HI,
            "--proof-identity", str(RANGE_PROOF),
            "--expected-proof-identity-file", RANGE_PROOF_FILE_ID,
            "--expected-proof-identity-digest", RANGE_PROOF_DIGEST,
            "--expected-inventory", INVENTORY_ID]
    if inventory is not None:
        argv += ["--inventory", str(inventory)]
    argv += ["--expected-source", SOURCE_ID,
             "--expected-plugin", expected_plugin or PLUGIN_ID]
    try:
        cp = subprocess.run(argv, capture_output=True, text=True, timeout=3600)
    finally:
        os.unlink(rp)
    reason = ""
    for tok in (cp.stderr or "").split():
        if tok.startswith("reason="):
            reason = tok.split("=", 1)[1]
    return cp.returncode, reason, "verifier"


def _run_plugin_call(tool: str, params: dict) -> tuple[int, str, str, dict]:
    cp = subprocess.run(
        [str(PLUGIN_LAUNCHER), "call", tool, json.dumps(params)],
        capture_output=True, text=True, timeout=3600)
    reason = ""
    obj: dict = {}
    try:
        obj = json.loads(cp.stdout)
        reason = obj.get("reason", "") if obj.get("status") == "refused" else ""
    except Exception:  # noqa: BLE001
        pass
    return cp.returncode, reason, "plugin", obj


# --- single-line raise flip ------------------------------------------------


def _flip_line(path: Path, needle_substring: str, marker: str,
                required_prefix: str | None = None) -> bytes:
    """Find the single line containing ``needle_substring`` and replace it with
    ``<indent>pass  # ABA-<marker>-mutation``.  Returns the pre-mutation bytes.

    ``required_prefix`` (e.g. ``"raise "``) constrains what the matched line
    must look like after leading whitespace is stripped; useful for asserting
    "the gate this test targets is a bare raise statement, not e.g. a helper
    call".  Pass ``None`` to accept any single line (used by M10, whose gate
    is an ``os.remove`` call inside a for-loop body).

    Raises ``RuntimeError`` if the needle is missing, appears on multiple
    lines, or fails the ``required_prefix`` predicate.
    """
    orig = path.read_bytes()
    text = orig.decode("utf-8")
    lines = text.splitlines(keepends=True)
    matches = [i for i, ln in enumerate(lines) if needle_substring in ln]
    if not matches:
        raise RuntimeError(f"needle-not-found in {path.name}: {needle_substring!r}")
    if len(matches) > 1:
        raise RuntimeError(
            f"needle-ambiguous in {path.name}: {needle_substring!r} ({len(matches)} hits)")
    idx = matches[0]
    line = lines[idx]
    stripped = line.lstrip()
    if required_prefix is not None and not stripped.startswith(required_prefix):
        raise RuntimeError(
            f"needle-shape-mismatch in {path.name}:{idx + 1}: expected {required_prefix!r}: {line.rstrip()!r}")
    indent = line[: len(line) - len(stripped)]
    lines[idx] = f"{indent}pass  # ABA-{marker}-mutation\n"
    path.write_text("".join(lines))
    _purge_pycache()
    return orig


def _flip_raise(path: Path, needle_substring: str, marker: str) -> bytes:
    """Wrapper around ``_flip_line`` that additionally asserts the located line
    is a bare ``raise`` statement — the shape of every M1..M9, M11 gate."""
    return _flip_line(path, needle_substring, marker, required_prefix="raise ")


def _restore(path: Path, orig_bytes: bytes) -> None:
    path.write_bytes(orig_bytes)
    _purge_pycache()


def _purge_pycache() -> None:
    for pdir in (ROOT / "tests" / "__pycache__", ROOT / "tools" / "__pycache__",
                 ROOT / "plugin" / "hermes" / "__pycache__"):
        if pdir.exists():
            shutil.rmtree(pdir, ignore_errors=True)


def _import_ok(module: str, path: Path) -> bool:
    cp = subprocess.run(
        [sys.executable, "-c",
         f"import sys; sys.path.insert(0, r'{path}'); import {module}"],
        capture_output=True, text=True)
    return cp.returncode == 0


# --- per-mutation harness --------------------------------------------------


class Mutation:
    def __init__(self, tag: str, gate_desc: str, target: Path,
                 needle: str, marker: str,
                 poison: Callable[[], tuple[int, str, str]],
                 expected_reason: str,
                 module_check: tuple[str, Path] | None = None,
                 pre_hooks: list[Callable[[], None]] | None = None,
                 cleanup: Callable[[], None] | None = None,
                 also_flip: list[tuple[Path, str, str]] | None = None,
                 flip_shape: str | None = "raise ",
                 b_policy: str = "admit",
                 expected_b_reason: str = "") -> None:
        self.tag = tag
        self.gate_desc = gate_desc
        self.target = target
        self.needle = needle
        self.marker = marker
        self.poison = poison
        self.expected_reason = expected_reason
        self.module_check = module_check
        self.pre_hooks = pre_hooks or []
        self.cleanup = cleanup
        self.also_flip = also_flip or []  # optional additional (path, needle, marker) sites to flip in tandem
        self.flip_shape = flip_shape
        self.b_policy = b_policy
        self.expected_b_reason = expected_b_reason

    def run(self) -> dict[str, Any]:
        row: dict[str, Any] = {
            "gate": self.tag, "description": self.gate_desc,
            "target_file": str(self.target.relative_to(ROOT)),
            "B_policy": self.b_policy,
        }
        row["source_hash_pre"] = sha_file(self.target)
        for hook in self.pre_hooks:
            hook()

        # A(pre) — poison must refuse for the intended reason.
        code_a, reason_a, layer_a = self.poison()
        row["A_pre"] = ("pass" if code_a != 0 and reason_a == self.expected_reason
                        else f"FAIL(exit={code_a},reason={reason_a})")
        row["A_pre_exit"] = code_a
        row["A_pre_reason"] = reason_a
        row["A_pre_layer"] = layer_a

        # B — disable the governing gate, still runnable, poison admitted.
        orig: bytes = self.target.read_bytes()
        secondary_orig: list[tuple[Path, bytes]] = []
        try:
            orig = _flip_line(self.target, self.needle, self.marker, self.flip_shape)
            for p, n, m in self.also_flip:
                secondary_orig.append((p, _flip_line(p, n, m, self.flip_shape)))
            row["source_hash_mutated"] = sha_file(self.target)
            module_check_ok = True
            if self.module_check is not None:
                module_check_ok = _import_ok(*self.module_check)
            if not module_check_ok:
                row["B"] = "INVALID-compile-error"
                row["B_exit"] = -1
                row["B_reason"] = "module import failed after mutation"
            else:
                code_b, reason_b, _layer_b = self.poison()
                if self.b_policy == "admit":
                    row["B"] = ("red-for-intended-reason" if code_b == 0
                                else "INVALID-still-refused")
                else:
                    row["B"] = (
                        "red-by-independent-gate"
                        if code_b != 0 and reason_b == self.expected_b_reason
                        else "INVALID-independent-gate"
                    )
                row["B_exit"] = code_b
                row["B_reason"] = reason_b
        except RuntimeError as e:
            row["B"] = "INVALID-needle-lookup"
            row["B_exit"] = -1
            row["B_reason"] = str(e)
        finally:
            for p, ob in reversed(secondary_orig):
                _restore(p, ob)
            _restore(self.target, orig)
            row["source_hash_post"] = sha_file(self.target)
            row["restore_hash_verified"] = row["source_hash_post"] == row["source_hash_pre"]

        # A(post) — same poison must refuse for the same reason.
        code_a2, reason_a2, layer_a2 = self.poison()
        row["A_post"] = ("pass" if code_a2 != 0 and reason_a2 == self.expected_reason
                         else f"FAIL(exit={code_a2},reason={reason_a2})")
        row["A_post_exit"] = code_a2
        row["A_post_reason"] = reason_a2
        row["A_post_layer"] = layer_a2

        # Cleanup is deliberately last so A(post) sees the same environment
        # A(pre) did (e.g., a temp checker binary that A(pre) referenced).
        if self.cleanup is not None:
            try:
                self.cleanup()
            except Exception as e:  # noqa: BLE001
                row["cleanup_error"] = str(e)
        return row


# --- poison factories ------------------------------------------------------


def _forge_source(cert_bytes: bytes) -> bytes:
    lines = cert_bytes.decode("utf-8").split("\n")
    for i, ln in enumerate(lines):
        if ln.startswith("source "):
            lines[i] = "source " + base64.b64encode(b"FORGED-REQUEST-BYTES").decode()
            break
    return "\n".join(lines).encode("utf-8")


def _rebind_source(cert_bytes: bytes, new_req_b64: str) -> bytes:
    lines = cert_bytes.decode("utf-8").split("\n")
    for i, ln in enumerate(lines):
        if ln.startswith("source "):
            lines[i] = "source " + new_req_b64
            break
    return "\n".join(lines).encode("utf-8")


def _make_M1() -> Mutation:
    base = _fresh_valid_cert()
    forged = _forge_source(base)
    return Mutation(
        tag="M1-request-changed-after-cert",
        gate_desc="cert.source (request commitment) MUST equal recomputed argv-derived commitment",
        target=VALIDATOR,
        needle='raise ReleaseRefusal("request-commitment"',
        marker="M1",
        poison=lambda: _run_validator_on_cert(forged, _BASE_EXPR, _BASE_LO, _BASE_HI),
        expected_reason="request-commitment",
        module_check=("release_validate", VALIDATOR.parent),
    )


def _make_M2() -> Mutation:
    r = _fresh_formal_receipt()
    # Add sin (in the FORMAL admitted set) so the "operator-outside-fragment"
    # gate would let it pass; the "operators-vs-certificate" cross-check
    # (comparing declared vs cert-sexp-derived) is what refuses.
    r["fragment"]["expression_operators"] = sorted(
        set(r["fragment"]["expression_operators"]) | {"sin"})
    r["fragment"]["coverage_row_ids"] = sorted(
        set(r["fragment"]["coverage_row_ids"]) | {"sin"})
    r["receipt_digest_sha256"] = recompute_receipt_digest(r)
    return Mutation(
        tag="M2-canonical-ast-changed",
        gate_desc="receipt.fragment.expression_operators MUST equal ops recovered from cert sexp",
        target=VERIFIER,
        needle='raise ReceiptRefusal("operators-vs-certificate"',
        marker="M2",
        poison=lambda: _run_verifier_on_receipt(r),
        expected_reason="operators-vs-certificate",
        module_check=("receipt_verify", VERIFIER.parent),
    )


def _make_M3() -> Mutation:
    r = _fresh_formal_receipt()
    r["result"]["enclosure_hi"] = "1000000"
    r["receipt_digest_sha256"] = recompute_receipt_digest(r)
    return Mutation(
        tag="M3-result-bound-changed",
        gate_desc="receipt.result.enclosure_{lo,hi} MUST equal cert output header",
        target=VERIFIER,
        needle='raise ReceiptRefusal("enclosure-hi-mismatch"',
        marker="M3",
        poison=lambda: _run_verifier_on_receipt(r),
        expected_reason="enclosure-hi-mismatch",
        module_check=("receipt_verify", VERIFIER.parent),
    )


def _make_M4() -> Mutation:
    """M4 — certificate changed: mutate ONLY the cert `source` header.

    Every other cert field (sexp, output, nodes, model, exe) stays identical
    so the target gate (`request-commitment-cert`) is the ONLY one that
    catches the swap — proving it is load-bearing (defense-in-depth gates
    downstream do not mask its absence).
    """
    r = _fresh_formal_receipt()
    cert_bytes = base64.b64decode(r["certificate"]["bytes_b64"])
    lines = cert_bytes.decode("utf-8").split("\n")
    for i, ln in enumerate(lines):
        if ln.startswith("source "):
            lines[i] = "source " + base64.b64encode(b"FORGED-CERT-SOURCE-BYTES").decode()
            break
    mutated_cert = "\n".join(lines).encode("utf-8")
    r["certificate"]["bytes_b64"] = base64.b64encode(mutated_cert).decode("ascii")
    r["certificate"]["sha256"] = sha(mutated_cert)
    r["receipt_digest_sha256"] = recompute_receipt_digest(r)
    return Mutation(
        tag="M4-certificate-changed",
        gate_desc="cert `source` header MUST equal receipt.request_commitment_b64 (single-field forgery)",
        target=VERIFIER,
        needle='raise ReceiptRefusal("request-commitment-cert"',
        marker="M4",
        poison=lambda: _run_verifier_on_receipt(r),
        expected_reason="request-commitment-cert",
        module_check=("receipt_verify", VERIFIER.parent),
    )


def _make_M5() -> Mutation:
    """M5 — integration limits changed.

    Cert bytes are for [1,2] but caller passes lo=1, hi=3 to the validator
    AND we forge the cert's `source` header to the (1,3) commitment so only
    the input-canonicalization gate can catch it — otherwise `request-
    commitment` catches it first.
    """
    fake_lo, fake_hi = "1", "3"
    argv_req = rv.request_commitment_b64(rv.COMMAND_ID, _BASE_EXPR, fake_lo, fake_hi)
    base = _fresh_valid_cert(_BASE_EXPR, _BASE_LO, _BASE_HI)
    forged = _rebind_source(base, argv_req)
    return Mutation(
        tag="M5-integration-limits-changed",
        gate_desc="cert.input MUST equal canonical_rat(argv lo/hi)",
        target=VALIDATOR,
        needle='raise ReleaseRefusal("request-input"',
        marker="M5",
        poison=lambda: _run_validator_on_cert(forged, _BASE_EXPR, fake_lo, fake_hi),
        expected_reason="request-input",
        module_check=("release_validate", VALIDATOR.parent),
        b_policy="independent-refusal",
        expected_b_reason="checker-rejected",
    )


def _make_M6() -> Mutation:
    """M6 — formal status added to an uncovered operation.

    Poison: hand-forge a row in the coverage inventory promoting `asin`
    (uncovered, fail-closed) to `FORMAL`.  The validator's release path
    invokes the formal-status gate, whose live-inventory-integrity check
    recomputes the FORMAL set from `Runs` constructors + engine ops and
    refuses on `inventory-integrity`.  The validator wraps that in
    `formal-status-refused`.  (Was `exp` prior to v1.4.1 — promoted via
    `expRat`; was `ln` prior to v1.5.0 — promoted via `logRat` §490.  Each
    fragment extension retires the previous probe operator; `asin` remains
    outside the zero-libm fragment because Mathlib offers no arcsin partial
    with a certified rational remainder on the closed domain.)
    """
    base = _fresh_valid_cert()
    orig_inv = INVENTORY.read_bytes()

    def apply_poison() -> tuple[int, str, str]:
        doc = json.loads(orig_inv.decode("utf-8"))
        for r in doc["rows"]:
            if r["operator"] == "asin":
                r["verdict"] = "FORMAL"
                r["allowed_status"] = "formal-bounded"
                r["soundness_theorem"] = "request_bound_certified_release"
                r["runs_constructors"] = ["asin"]
                break
        INVENTORY.write_bytes(json.dumps(doc, sort_keys=True, indent=2).encode("utf-8"))
        try:
            return _run_validator_on_cert(base, _BASE_EXPR, _BASE_LO, _BASE_HI)
        finally:
            INVENTORY.write_bytes(orig_inv)

    return Mutation(
        tag="M6-formal-status-uncovered-op",
        gate_desc="coverage inventory FORMAL set MUST equal live `Runs` constructors ⊂ engine ops",
        target=GATE,
        needle='raise StatusRefusal("inventory-integrity"',
        marker="M6",
        poison=apply_poison,
        expected_reason="formal-status-refused",
        module_check=("formal_status_gate", GATE.parent),
    )


def _make_M7() -> Mutation:
    """M7 — checker binary substituted.

    The bogus checker emits a BYTE-PERFECT request-bound ACCEPT line —
    including the authoritative `output <lo> <hi>` echo matching this exact
    receipt — so every downstream protocol gate (ACCEPT-prefix, echo shape,
    echo-vs-header agreement) passes.  The ONLY gate standing between the
    substituted binary and acceptance is the binary-hash identity check;
    disabling that single raise admits the poison, proving it load-bearing.
    """
    r = _fresh_formal_receipt()
    tmpdir = Path(tempfile.mkdtemp(prefix="mut11-bogus-chk-"))
    bogus = tmpdir / "jackal_cert_check"
    echo_lo = r["result"]["enclosure_lo"]
    echo_hi = r["result"]["enclosure_hi"]
    bogus.write_text(
        "#!/bin/sh\n"
        "echo 'ACCEPT request-bound theorem=request_bound_certified_release "
        f"command=range-bound-cert output {echo_lo} {echo_hi}'\n"
    )
    bogus.chmod(0o755)
    return Mutation(
        tag="M7-checker-substituted",
        gate_desc="checker file SHA-256 MUST equal receipt.identities.checker_sha256",
        target=VERIFIER,
        needle='raise ReceiptRefusal("checker-binary-mismatch"',
        marker="M7",
        poison=lambda: _run_verifier_on_receipt(r, checker=bogus),
        expected_reason="checker-binary-mismatch",
        module_check=("receipt_verify", VERIFIER.parent),
        cleanup=lambda: shutil.rmtree(tmpdir, ignore_errors=True),
    )


def _make_M8() -> Mutation:
    """M8 — evaluator binary substituted (validator's expected-eval mismatch)."""
    base = _fresh_valid_cert()
    return Mutation(
        tag="M8-evaluator-substituted",
        gate_desc="pinned expected-evaluator MUST equal file SHA-256 of the invoked evaluator",
        target=VALIDATOR,
        needle='raise ReleaseRefusal("evaluator-identity", f"{eval_id} != {expected_evaluator}")',
        marker="M8",
        poison=lambda: _run_validator_on_cert(base, _BASE_EXPR, _BASE_LO, _BASE_HI,
                                              expected_evaluator="b" * 64),
        expected_reason="evaluator-identity",
        module_check=("release_validate", VALIDATOR.parent),
    )


def _make_M9() -> Mutation:
    """M9 — outer digest recomputed after semantic tampering.

    Mutate enclosure_hi AND recompute `receipt_digest_sha256`; the outer
    digest now accepts, but the cert-output vs receipt.result cross-check
    refuses on `enclosure-hi-mismatch`.  Proves outer-digest recomputation
    ALONE is not sufficient.
    """
    r = _fresh_formal_receipt()
    r["result"]["enclosure_hi"] = "9999999"
    r["receipt_digest_sha256"] = recompute_receipt_digest(r)
    return Mutation(
        tag="M9-outer-digest-recomputed-after-tamper",
        gate_desc="cert output header (source of truth) MUST equal receipt.result enclosure",
        target=VERIFIER,
        needle='raise ReceiptRefusal("enclosure-hi-mismatch"',
        marker="M9",
        poison=lambda: _run_verifier_on_receipt(r),
        expected_reason="enclosure-hi-mismatch",
        module_check=("receipt_verify", VERIFIER.parent),
    )


def _make_M10() -> Mutation:
    """M10 — stale success reused against a different request.

    The current writer NEVER deletes or overwrites a pre-existing receipt
    (``require_fresh_output`` refuses ``receipt-output-exists`` and never
    follows symlinks — see tests/output_path_safety_test.py).  Reuse is
    therefore defeated at VERIFY time: the verifier requires the caller's
    exact expected request, so a genuine prior success receipt for a
    DIFFERENT request must refuse.  This mutation proves that gate is
    load-bearing:

      A(pre)  a genuine receipt for x^2+1 over [1,3] is verified against
              the expected request [1,2] → REFUSED
              (reason=expected-request-mismatch).
      B       the ``expected-request-mismatch`` raise is disabled → the
              stale receipt is receipt-internally consistent (it IS a real
              success), so verification ACCEPTS it for the wrong request
              → poison ADMITTED (exit 0).
      A(post) gate restored (hash-verified) → refuses again.
    """
    stale = _fresh_formal_receipt(hi="3")  # genuine success for [1,3]

    def apply_poison() -> tuple[int, str, str]:
        # Verify the [1,3] receipt against the expected [1,2] request.
        return _run_verifier_on_receipt(stale)

    return Mutation(
        tag="M10-stale-success-reuse",
        gate_desc="a prior success receipt MUST NOT verify against a different expected request",
        target=VERIFIER,
        needle='raise ReceiptRefusal("expected-request-mismatch"',
        marker="M10",
        poison=apply_poison,
        expected_reason="expected-request-mismatch",
        module_check=("receipt_verify", VERIFIER.parent),
    )


def _make_M11() -> Mutation:
    """M11 — public plugin binary replaced.

    Poison: mutate a DIFFERENT bundle file (``jackal_hermes``, the shell
    launcher) so the recomputed bundle hash drifts from the pin — the
    startup gate refuses `plugin-bundle-mismatch`.  We DO NOT touch
    ``server.py`` in the poison factory because the harness mutation
    targets a raise inside that same file; touching it here would
    clobber the harness's disable-flip.  Every bundle file is fair game
    for M11: the essence of "public plugin binary replaced" is any
    modification of any file in ``bundle_files``.
    """
    launcher = PLUGIN_LAUNCHER
    original = launcher.read_bytes()

    def apply_poison() -> tuple[int, str, str]:
        try:
            launcher.write_bytes(original + b"\n# ABA-M11-launcher-marker\n")
            code, reason, layer, _obj = _run_plugin_call(
                "jackal_range_bound",
                {"expression": _BASE_EXPR, "input_lo": _BASE_LO, "input_hi": _BASE_HI})
            return code, reason, layer
        finally:
            launcher.write_bytes(original)

    return Mutation(
        tag="M11-plugin-binary-replaced",
        gate_desc="plugin bundle hash MUST equal pinned plugin_hermes value at startup",
        target=PLUGIN_SERVER,
        needle='raise PluginRefusal("plugin-bundle-mismatch"',
        marker="M11",
        poison=apply_poison,
        expected_reason="plugin-bundle-mismatch",
        module_check=None,
    )


ALL_MUTATIONS = [_make_M1, _make_M2, _make_M3, _make_M4, _make_M5,
                 _make_M6, _make_M7, _make_M8, _make_M9, _make_M10, _make_M11]


def main() -> int:
    rows: list[dict] = []
    for maker in ALL_MUTATIONS:
        m = maker()
        row = m.run()
        rows.append(row)
        ok = (row["A_pre"] == "pass" and row["B"] in {
                  "red-for-intended-reason", "red-by-independent-gate"}
              and row["A_post"] == "pass" and row["restore_hash_verified"])
        print(f"{row['gate']:40s} A_pre={row['A_pre']}({row['A_pre_reason']}) "
              f"B={row['B']} A_post={row['A_post']} restore={row['restore_hash_verified']} "
              f"{'PASS' if ok else 'FAIL'}")

    EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "harness": "cert_mutations_11.py",
        "release_epoch": CURRENT_PROOF_RELEASE_EPOCH,
        "evaluator_sha256": EVAL_ID,
        "checker_sha256": CHK_ID,
        "plugin_hermes_sha256": PLUGIN_ID,
        "mutations": rows,
    }
    EVIDENCE.write_text(json.dumps(data, sort_keys=True, indent=2))
    print(f"evidence={EVIDENCE} sha256={sha(EVIDENCE.read_bytes())}")

    ok_all = all(
        r["A_pre"] == "pass" and r["B"] in {
            "red-for-intended-reason", "red-by-independent-gate"}
        and r["A_post"] == "pass" and r["restore_hash_verified"]
        for r in rows)
    if not ok_all:
        print("VERDICT: FAIL — a mutation did not show the required A→B→A transitions",
              file=sys.stderr)
        return 1
    print(f"VERDICT: PASS — {len(rows)}/{len(rows)} semantic mutations admitted or independently refused on disable, restored by hash")
    return 0


if __name__ == "__main__":
    sys.exit(main())
