#!/usr/bin/env python3
"""JACKAL v1.4.2 formal-bounded receipt — schema, emitter, and outer digest.

A "formal receipt" carries EVERY field a downstream reverifier needs to
mechanically re-establish the release verdict without trusting anything
except:

  * caller-supplied pins for the checker, producer/evaluator, proof identity,
    coverage inventory, release epoch, and exact request;
  * the Lean/kernel/compiler/OS/CPU TCB explicitly retained as assumptions;
  * the canonical rational codec compiled into the checker binary.

In particular the receipt embeds the certificate BYTES base64-encoded, so
the independent verifier (`tools/receipt_verify.py`) can rehydrate them to
disk and RE-RUN the compiled `jackal_cert_check` executable.  Recomputing
`receipt_digest_sha256` alone is NOT sufficient to accept a receipt — the
digest binds the fields together and defeats trivial substitution, but
soundness comes from the checker actually accepting the exact certificate
bytes, on this machine, at verify time.

Schema fields (all mandatory; missing/null on a formal receipt = refuse):

  schema                   fixed string "jackal-formal-receipt-v1"
  release_epoch            release version tag ("v1.3.0", …)
  emitted_at_unix          integer wall-clock seconds — informational
  request                  { command, expression, input_lo, input_hi,
                             canonical_lo, canonical_hi,
                             request_commitment_b64 }
  result                   { status: "formal-bounded",
                             enclosure_lo, enclosure_hi,
                             cert_status: "bounded" }
  certificate              { schema, model_const_version, sexp,
                             bytes_b64, sha256 }
  identities               { evaluator_sha256, checker_sha256,
                             plugin_sha256|null, source_anb_sha256|null }
  theorem                  { id: "request_bound_certified_release",
                             lean_kernel_axioms: [...] }
  proof_identity           exact proof-source/toolchain/build binding
  fragment                 { admitted_operators, expression_operators,
                             coverage_row_ids, coverage_inventory_sha256,
                             unsupported_refused }
  checker                  { verdict: "ACCEPT",
                             reverify_required: true }
  assumptions              [str, ...]    — model + toolchain TCB
  non_claims               [str, ...]    — explicit scope refusals
  receipt_digest_sha256    hex; SHA-256 of the canonical JSON of every
                           field EXCEPT this one (sort_keys, separators).

`receipt_digest_sha256` is an integrity fingerprint over the receipt fields.
It is NOT a proof, a signature, freshness evidence, or a substitute for
re-running the checker against caller-authorized external context.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import stat
import tempfile
import time
from fractions import Fraction
from pathlib import Path
from typing import Any, Iterable

SCHEMA = "jackal-formal-receipt-v1"
THEOREM_ID = "request_bound_certified_release"
GAUSSIAN_THEOREM_ID = "gaussian_integral_check_sound"


def require_fresh_output(path: str | Path) -> Path:
    """Resolve a caller output name without following its final component.

    Formal-release output is write-once: an existing file, directory, or
    symlink is never removed or overwritten.  The parent must already exist.
    """
    destination = Path(os.path.abspath(os.path.expanduser(os.fspath(path))))
    if os.path.lexists(destination):
        raise FileExistsError(os.fspath(destination))
    if not destination.parent.is_dir():
        raise FileNotFoundError(os.fspath(destination.parent))
    return destination


def _unlink_same_inode(path: Path, identity: os.stat_result) -> None:
    """Best-effort cleanup without deleting a path that was swapped in."""
    try:
        observed = os.lstat(path)
        if (observed.st_dev, observed.st_ino) == (identity.st_dev, identity.st_ino):
            os.unlink(path)
    except FileNotFoundError:
        pass


def write_new_file_atomic(path: str | Path, data: bytes, mode: int = 0o600) -> Path:
    """Publish complete bytes atomically at a fresh path, never overwriting.

    Bytes are fsynced in a same-directory temporary file, then published with
    a hard-link operation that fails if the destination appeared concurrently.
    """
    destination = require_fresh_output(path)
    fd, temporary_raw = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
    )
    temporary = Path(temporary_raw)
    temporary_identity: os.stat_result | None = None
    destination_identity: os.stat_result | None = None
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, "wb") as handle:
            fd = -1
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        temporary_identity = os.lstat(temporary)
        if not stat.S_ISREG(temporary_identity.st_mode):
            raise OSError("temporary receipt is not a regular file")
        os.link(temporary, destination, follow_symlinks=False)
        destination_identity = os.lstat(destination)
        if (destination_identity.st_dev, destination_identity.st_ino) != \
                (temporary_identity.st_dev, temporary_identity.st_ino):
            raise OSError("published receipt inode mismatch")
        _unlink_same_inode(temporary, temporary_identity)
        directory_fd = os.open(destination.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        return destination
    except Exception:
        if fd >= 0:
            os.close(fd)
        if temporary_identity is None:
            try:
                temporary_identity = os.lstat(temporary)
            except FileNotFoundError:
                temporary_identity = None
        if temporary_identity is not None:
            _unlink_same_inode(temporary, temporary_identity)
        if destination_identity is not None:
            _unlink_same_inode(destination, destination_identity)
        raise


LEAN_KERNEL_AXIOMS = ["Classical.choice", "Quot.sound", "propext"]
MODEL_ASSUMPTIONS = [
    "Range theorem premise: ModelTCB hdr nodes = LibmModel hdr nodes ∧ ConstTCB nodes",
    "Formal range admission refuses every node with a nontrivial LibmModel obligation; ConstTCB remains an explicit declared-value premise for pi/e/tau",
    "Lean 4 kernel + pinned Mathlib toolchain that compiled jackal_cert_check",
    "Canonical exact-rational request/certificate codecs compiled into jackal_cert_check",
    "The pinned evaluator and checker bytes executed as their hashes describe",
    "Lean native code generation, the C/C++ compiler and linker, and the dynamic loader preserve the checker semantics",
    "The operating system, CPU, memory, and storage execute and retain the pinned bytes correctly",
]
NON_CLAIMS = [
    "NOT universal correctness across all operators or expressions",
    "Transcendental operators sqrt/exp/ln/tan/cbrt/atan/asin/acos/log10/log2/hypot/atan2 FAIL CLOSED (refused)",
    "Non-integer / general powers, negative integer powers, and modulo FAIL CLOSED (refused)",
    "The Anubis emitter faithfully producing the certificate for its computation is TESTED, not proven",
    "Source parsing correspondence to the shipped parser is differential-gated, not proven",
    "Source-to-native refinement (verified compilation of the Anubis lane) remains OPEN",
    "bound_step release composition (adaptive integration) remains OPEN",
    "SHA-256 identifies bytes; it does NOT authenticate an author",
    "The artifact is unsigned and has not received an independent external proof audit",
]

GAUSSIAN_ASSUMPTIONS = [
    "Lean 4 kernel + pinned Mathlib toolchain that compiled jackal_gaussian_check",
    "Mathlib's proved Gaussian integral and pi bounds used by gaussian_integral_check_sound",
    "Canonical exact-rational codec and decimal parser compiled into jackal_gaussian_check",
    "The pinned certificate producer and checker bytes executed as their hashes describe",
    "Lean native code generation, the C/C++ compiler and linker, and the dynamic loader preserve the checker semantics",
    "The operating system, CPU, memory, and storage execute and retain the pinned bytes correctly",
]
GAUSSIAN_NON_CLAIMS = [
    "NOT universal correctness across all expressions or integration algorithms",
    "Only canonical exp(-A*(x-mu)^2) with positive exact-rational-square A and checker-covered domain is admitted",
    "Unsupported formal expressions and insufficient requested tolerances FAIL CLOSED",
    "The Python certificate producer is untrusted; formal release requires independent checker ACCEPT",
    "SHA-256 identifies bytes; it does NOT authenticate an author",
    "The artifact is unsigned and has not received an independent external proof audit",
]

# Variant identifiers ship inside the envelope so the verifier can dispatch
# without inferring from the cert schema alone (sqrt_rat and exp_rat both
# use `jackal-eval-cert v2`, same as the general range lane, so a separate
# marker is needed to distinguish them and select the right identity shape
# and admitted-operator lock).
RANGE_VARIANT = "range"
GAUSSIAN_VARIANT = "gaussian"
SQRT_RAT_VARIANT = "sqrt_rat"
EXP_RAT_VARIANT = "exp_rat"
RATIONAL_VARIANTS = {SQRT_RAT_VARIANT, EXP_RAT_VARIANT}
ALL_VARIANTS = {RANGE_VARIANT, GAUSSIAN_VARIANT, SQRT_RAT_VARIANT, EXP_RAT_VARIANT}

_VARIANT_ADMITTED_OPERATOR: dict[str, str] = {
    SQRT_RAT_VARIANT: "sqrt",
    EXP_RAT_VARIANT: "exp",
}
_VARIANT_ADMITTED_EXPRESSION: dict[str, str] = {
    SQRT_RAT_VARIANT: "sqrt(x)",
    EXP_RAT_VARIANT: "exp(x)",
}
_VARIANT_COVERAGE_ROW: dict[str, str] = {
    SQRT_RAT_VARIANT: "jackal_sqrt_rat_bound",
    EXP_RAT_VARIANT: "jackal_exp_rat_bound",
}

SQRT_RAT_ASSUMPTIONS = [
    "Range theorem premise: ModelTCB hdr nodes = LibmModel hdr nodes ∧ ConstTCB nodes",
    "The sqrt_rat cert node bypasses every LibmModel obligation (Runs.sqrtRat carries no `Approx δlib` fact)",
    "The Lean releaseNodeOp allowlist admits the `sqrt_rat` constructor with zero libm TCB",
    "Lean 4 kernel + pinned Mathlib toolchain that compiled jackal_cert_check",
    "Canonical exact-rational request/certificate codecs compiled into jackal_cert_check",
    "The pinned sqrt_rat producer and checker bytes executed as their hashes describe",
    "Lean native code generation, the C/C++ compiler and linker, and the dynamic loader preserve the checker semantics",
    "The operating system, CPU, memory, and storage execute and retain the pinned bytes correctly",
]
SQRT_RAT_NON_CLAIMS = [
    "NOT universal correctness across all operators or expressions",
    "sqrt_rat admits ONLY the exact form `sqrt(x)` on a canonical rational interval",
    "Every other transcendental operator (exp/ln/tan/cbrt/atan/asin/acos/log10/log2/hypot/atan2) FAIL CLOSED on this variant",
    "The Python sqrt_rat producer is untrusted; formal release requires independent checker ACCEPT",
    "SHA-256 identifies bytes; it does NOT authenticate an author",
    "The artifact is unsigned and has not received an independent external proof audit",
]

EXP_RAT_ASSUMPTIONS = [
    "Range theorem premise: ModelTCB hdr nodes = LibmModel hdr nodes ∧ ConstTCB nodes",
    "The exp_rat cert node bypasses every LibmModel obligation (Runs.expRat carries no `Approx δlib` fact; the Taylor partial + remainder are pure ℚ)",
    "The Lean releaseNodeOp allowlist admits the `exp_rat` constructor with zero libm TCB",
    "Lean 4 kernel + pinned Mathlib toolchain that compiled jackal_cert_check",
    "Canonical exact-rational request/certificate codecs compiled into jackal_cert_check",
    "The pinned exp_rat producer and checker bytes executed as their hashes describe",
    "Lean native code generation, the C/C++ compiler and linker, and the dynamic loader preserve the checker semantics",
    "The operating system, CPU, memory, and storage execute and retain the pinned bytes correctly",
]
EXP_RAT_NON_CLAIMS = [
    "NOT universal correctness across all operators or expressions",
    "exp_rat admits ONLY the exact form `exp(x)` on a canonical rational interval `[lo, hi]` with `lo >= 0`",
    "The negative-argument branch of `exp` is NOT covered by this variant",
    "Every other transcendental operator (sqrt/ln/tan/cbrt/atan/asin/acos/log10/log2/hypot/atan2) FAIL CLOSED on this variant",
    "The Python exp_rat producer is untrusted; formal release requires independent checker ACCEPT",
    "SHA-256 identifies bytes; it does NOT authenticate an author",
    "The artifact is unsigned and has not received an independent external proof audit",
]

_VARIANT_ASSUMPTIONS: dict[str, list[str]] = {
    SQRT_RAT_VARIANT: SQRT_RAT_ASSUMPTIONS,
    EXP_RAT_VARIANT: EXP_RAT_ASSUMPTIONS,
}
_VARIANT_NON_CLAIMS: dict[str, list[str]] = {
    SQRT_RAT_VARIANT: SQRT_RAT_NON_CLAIMS,
    EXP_RAT_VARIANT: EXP_RAT_NON_CLAIMS,
}

PROOF_IDENTITY_BINDING_KEYS = {
    "schema", "file_sha256", "identity_digest_sha256",
    "source_closure_sha256", "checker_sha256", "lean_commit",
    "lean_executable_sha256", "mathlib_commit",
    "build_attestation_digest_sha256", "soundness_theorem", "authenticated",
}


def canonical_json_bytes(obj: Any) -> bytes:
    """Canonical JSON encoding used for every digest in the receipt system.

    sort_keys + tightest separators + ensure_ascii=False for reproducibility.
    """
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sha256_hex(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def load_proof_identity_binding(path: str | Path) -> dict[str, Any]:
    """Load and self-check one deterministic proof/build identity record.

    This is a byte/digest binding, not authentication.  The independent
    receipt verifier repeats these checks against a caller-supplied record.
    """
    identity_path = Path(path)
    raw = identity_path.read_bytes()
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate proof identity key: {key}")
            result[key] = value
        return result
    record = json.loads(raw, object_pairs_hook=reject_duplicates)
    if not isinstance(record, dict):
        raise ValueError("proof identity must be an object")
    required = {
        "schema", "identity_digest_sha256", "checker", "fragment",
        "source_closure", "toolchain", "build_attestation",
    }
    if not required.issubset(record):
        raise ValueError(f"proof identity missing fields: {sorted(required - set(record))}")
    body = {key: value for key, value in record.items()
            if key != "identity_digest_sha256"}
    observed_identity = sha256_hex(canonical_json_bytes(body))
    if record["identity_digest_sha256"] != observed_identity:
        raise ValueError("proof identity self-digest mismatch")
    attestation = record["build_attestation"]
    if not isinstance(attestation, dict):
        raise ValueError("proof build attestation must be an object")
    attestation_body = {key: value for key, value in attestation.items()
                        if key != "attestation_digest_sha256"}
    observed_attestation = sha256_hex(canonical_json_bytes(attestation_body))
    if attestation.get("attestation_digest_sha256") != observed_attestation:
        raise ValueError("proof build-attestation self-digest mismatch")
    authenticated = attestation.get("authentication", {}).get("authenticated")
    if authenticated is not False:
        raise ValueError("unsigned proof identity must record authenticated=false")
    binding = {
        "schema": record["schema"],
        "file_sha256": sha256_hex(raw),
        "identity_digest_sha256": record["identity_digest_sha256"],
        "source_closure_sha256": record["source_closure"]["aggregate_sha256"],
        "checker_sha256": record["checker"]["sha256"],
        "lean_commit": record["toolchain"]["lean"]["commit"],
        "lean_executable_sha256":
            attestation["compiler_observed_for_build_platform"]["executable_sha256"],
        "mathlib_commit": record["toolchain"]["mathlib_commit"],
        "build_attestation_digest_sha256": attestation["attestation_digest_sha256"],
        "soundness_theorem": record["fragment"]["soundness_theorem"],
        "authenticated": False,
    }
    if set(binding) != PROOF_IDENTITY_BINDING_KEYS:
        raise ValueError("internal proof identity binding schema mismatch")
    return binding


def canonical_rat(tok: str) -> str:
    """Canonicalize a decimal / integer / rational token to the engine's
    reduced ℚ string.  Integers stay unwrapped (``"2"``, not ``"2/1"``) to
    match the cert `input`/`output` header format emitted by the evaluator.

    Load-bearing shared canonicalization: `release_validate.py`,
    `receipt_verify.py`, and the Hermes plugin ALL import this so a
    request's canonical bounds are byte-comparable across every layer.
    Raises ``ValueError`` on any malformed input; call-sites wrap in
    their own ``*Refusal`` type.
    """
    tok = (tok or "").strip()
    if not tok:
        raise ValueError("canonical_rat: empty token")
    if "/" in tok:
        try:
            n, d = tok.split("/", 1)
            fr = Fraction(int(n), int(d))
        except Exception as e:  # noqa: BLE001
            raise ValueError(f"canonical_rat: not a rational: {tok!r}") from e
    else:
        try:
            fr = Fraction(tok)
        except Exception as e:  # noqa: BLE001
            raise ValueError(f"canonical_rat: not a rational: {tok!r}") from e
    if fr.denominator == 1:
        return str(fr.numerator)
    return f"{fr.numerator}/{fr.denominator}"


def request_commitment_b64(cmd: str, expr: str, lo: str, hi: str) -> str:
    """Injective, length-delimited framing of the exact request bytes.

    Framing: ``jackal-req-v2\\x00`` then, for each of (cmd, expr, lo, hi),
    ``<len-as-ascii-decimal>:<utf8 bytes>`` joined with ``|``.  SHA-256
    of the framing, hex, base64-wrapped.

    Length prefixes make the framing unambiguous under any payload
    (embedded delimiters, whitespace, newlines, Unicode).  The framing
    MUST match `tests/release_validate.py` byte-for-byte — both import
    this function so drift is a compile error, not a silent divergence.
    """
    def framed(p: str) -> bytes:
        b = p.encode("utf-8")
        return str(len(b)).encode() + b":" + b
    framing = (b"jackal-req-v2\x00" + framed(cmd) + b"|" + framed(expr)
               + b"|" + framed(lo) + b"|" + framed(hi))
    hexd = hashlib.sha256(framing).hexdigest()
    return base64.b64encode(hexd.encode()).decode()


def gaussian_request_commitment_b64(cmd: str, expr: str, lo: str, hi: str,
                                    tolerance: str) -> str:
    """Injective commitment for formal integration requests, including tolerance."""
    def framed(part: str) -> bytes:
        raw = part.encode("utf-8")
        return str(len(raw)).encode() + b":" + raw
    framing = (b"jackal-req-v3-gaussian\x00" + framed(cmd) + b"|" + framed(expr)
               + b"|" + framed(lo) + b"|" + framed(hi) + b"|" + framed(tolerance))
    return base64.b64encode(hashlib.sha256(framing).hexdigest().encode()).decode()


def _operators_in_sexp(sexp: str) -> set[str]:
    """Recover the operator/leaf tags emitted by the engine's `ast_sexp`.

    The tags are the second token of every `(tag …)` form.  Function-call
    forms `(call NAME …)` expose NAME (sin/cos/...).  Leaves: `num`, `var`,
    `const`.
    """
    ops: set[str] = set()
    toks = sexp.replace("(", " ( ").replace(")", " ) ").split()
    i = 0
    while i < len(toks):
        if toks[i] == "(" and i + 1 < len(toks):
            tag = toks[i + 1]
            if tag == "call" and i + 2 < len(toks):
                ops.add(toks[i + 2])
            elif tag not in {"(", ")"}:
                ops.add(tag)
        i += 1
    return ops


def _parse_cert_header(cert_bytes: bytes) -> dict[str, str]:
    """Minimal header extractor for the fields the receipt binds.

    Header rows are `<key> <value>` up to the first `node …` or `end` row.
    """
    hdr: dict[str, str] = {}
    try:
        text = cert_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"certificate is not UTF-8: {exc}") from exc
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("node ") or line == "end":
            break
        if line in {"jackal-eval-cert v2", "jackal-gaussian-integral-cert v1"}:
            hdr["schema"] = line
            continue
        parts = line.split(" ", 1)
        if len(parts) == 2:
            if parts[0] in hdr:
                raise ValueError(f"duplicate certificate header: {parts[0]}")
            hdr[parts[0]] = parts[1]
    return hdr


def build_formal_receipt(*, release_epoch: str, request: dict[str, str], enclosure: tuple[str, str],
                         cert_bytes: bytes, evaluator_sha256: str, checker_sha256: str,
                         source_anb_sha256: str | None, plugin_sha256: str | None,
                         admitted_operators: Iterable[str], coverage_row_ids: Iterable[str],
                         unsupported_refused: Iterable[str], canonical_lo: str, canonical_hi: str,
                         request_commitment_b64: str, coverage_inventory_sha256: str,
                         proof_identity: dict[str, Any],
                         cert_status: str = "bounded",
                         emitted_at_unix: int | None = None) -> dict[str, Any]:
    """Assemble a formal-bounded receipt and compute its outer digest.

    Callers MUST provide the certificate bytes actually accepted by the
    proved checker and the identities the release validator pinned.  This
    function does NOT re-run the checker — it only serializes the evidence
    the reverifier will consume.
    """
    hdr = _parse_cert_header(cert_bytes)
    sexp = hdr.get("expr", "")
    expr_ops = _operators_in_sexp(sexp) if sexp else set()
    admitted = sorted(set(admitted_operators))
    refused = sorted(set(unsupported_refused))
    receipt: dict[str, Any] = {
        "schema": SCHEMA,
        "variant": RANGE_VARIANT,
        "release_epoch": release_epoch,
        "emitted_at_unix": int(emitted_at_unix if emitted_at_unix is not None else time.time()),
        "request": {
            "command": request["command"],
            "expression": request["expression"],
            "input_lo": request["input_lo"],
            "input_hi": request["input_hi"],
            "canonical_lo": canonical_lo,
            "canonical_hi": canonical_hi,
            "request_commitment_b64": request_commitment_b64,
        },
        "result": {
            "status": "formal-bounded",
            "enclosure_lo": enclosure[0],
            "enclosure_hi": enclosure[1],
            "cert_status": cert_status,
        },
        "certificate": {
            "schema": hdr.get("schema", ""),
            "model_const_version": hdr.get("model", ""),
            "sexp": sexp,
            "bytes_b64": base64.b64encode(cert_bytes).decode("ascii"),
            "sha256": sha256_hex(cert_bytes),
        },
        "identities": {
            "evaluator_sha256": evaluator_sha256,
            "checker_sha256": checker_sha256,
            "plugin_sha256": plugin_sha256,
            "source_anb_sha256": source_anb_sha256,
        },
        "theorem": {
            "id": THEOREM_ID,
            "lean_kernel_axioms": sorted(set(LEAN_KERNEL_AXIOMS)),
        },
        "proof_identity": proof_identity,
        "fragment": {
            "admitted_operators": admitted,
            "expression_operators": sorted(expr_ops),
            "coverage_row_ids": sorted(set(coverage_row_ids)),
            "coverage_inventory_sha256": coverage_inventory_sha256,
            "unsupported_refused": refused,
        },
        "checker": {
            "verdict": "ACCEPT",
            "reverify_required": True,
        },
        "assumptions": list(MODEL_ASSUMPTIONS),
        "non_claims": list(NON_CLAIMS),
    }
    receipt["receipt_digest_sha256"] = sha256_hex(canonical_json_bytes(_receipt_body(receipt)))
    return receipt


def build_gaussian_formal_receipt(*, release_epoch: str, request: dict[str, str],
                                  enclosure: tuple[str, str], cert_bytes: bytes,
                                  producer_sha256: str, checker_sha256: str,
                                  canonical_lo: str, canonical_hi: str,
                                  canonical_tolerance: str,
                                  request_commitment_b64: str,
                                  coverage_inventory_sha256: str,
                                  proof_identity: dict[str, Any],
                                  plugin_sha256: str | None = None,
                                  emitted_at_unix: int | None = None) -> dict[str, Any]:
    """Assemble the theorem-backed Gaussian variant of jackal-formal-receipt-v1."""
    hdr = _parse_cert_header(cert_bytes)
    receipt: dict[str, Any] = {
        "schema": SCHEMA,
        "variant": GAUSSIAN_VARIANT,
        "release_epoch": release_epoch,
        "emitted_at_unix": int(emitted_at_unix if emitted_at_unix is not None else time.time()),
        "request": {
            "command": request["command"],
            "expression": request["expression"],
            "input_lo": request["input_lo"],
            "input_hi": request["input_hi"],
            "tolerance": request["tolerance"],
            "canonical_lo": canonical_lo,
            "canonical_hi": canonical_hi,
            "canonical_tolerance": canonical_tolerance,
            "request_commitment_scheme": "jackal-req-v3-gaussian",
            "request_commitment_b64": request_commitment_b64,
        },
        "result": {
            "status": "formal-bounded",
            "enclosure_lo": enclosure[0],
            "enclosure_hi": enclosure[1],
            "cert_status": "gaussian-formal-bounded",
        },
        "certificate": {
            "schema": hdr.get("schema", ""),
            "family": hdr.get("family", ""),
            "method": hdr.get("method", ""),
            "bytes_b64": base64.b64encode(cert_bytes).decode("ascii"),
            "sha256": sha256_hex(cert_bytes),
        },
        "identities": {
            "evaluator_sha256": producer_sha256,
            "producer_sha256": producer_sha256,
            "checker_sha256": checker_sha256,
            "plugin_sha256": plugin_sha256,
            "source_anb_sha256": None,
        },
        "theorem": {
            "id": GAUSSIAN_THEOREM_ID,
            "lean_kernel_axioms": sorted(set(LEAN_KERNEL_AXIOMS)),
        },
        "proof_identity": proof_identity,
        "fragment": {
            "admitted_operators": ["exp", "mul", "neg", "pow2", "sub"],
            "expression_operators": ["exp", "mul", "neg", "pow2", "sub"],
            "coverage_row_ids": ["gaussian-exp-square-integral-v1"],
            "coverage_inventory_sha256": coverage_inventory_sha256,
            "unsupported_refused": ["all expressions outside gaussian-exp-square-v1"],
        },
        "checker": {"verdict": "ACCEPT", "reverify_required": True},
        "assumptions": list(GAUSSIAN_ASSUMPTIONS),
        "non_claims": list(GAUSSIAN_NON_CLAIMS),
    }
    receipt["receipt_digest_sha256"] = sha256_hex(canonical_json_bytes(_receipt_body(receipt)))
    return receipt


def _receipt_body(receipt: dict[str, Any]) -> dict[str, Any]:
    """Return the receipt sans `receipt_digest_sha256` for digest computation."""
    return {k: v for k, v in receipt.items() if k != "receipt_digest_sha256"}


def recompute_receipt_digest(receipt: dict[str, Any]) -> str:
    return sha256_hex(canonical_json_bytes(_receipt_body(receipt)))


def dump_receipt(receipt: dict[str, Any]) -> str:
    """Serialize a receipt canonically (JSON, sort_keys, 2-space indent for eyes)."""
    return json.dumps(receipt, sort_keys=True, indent=2, ensure_ascii=False)


def build_variant_formal_receipt(
    *,
    variant: str,
    release_epoch: str,
    request: dict[str, str],
    enclosure: tuple[str, str],
    cert_bytes: bytes,
    producer_sha256: str,
    checker_sha256: str,
    canonical_lo: str,
    canonical_hi: str,
    request_commitment_b64: str,
    coverage_inventory_sha256: str,
    proof_identity: dict[str, Any],
    plugin_sha256: str | None = None,
    emitted_at_unix: int | None = None,
) -> dict[str, Any]:
    """Assemble a `jackal-formal-receipt-v1` for one of the pure-ℚ fragment
    extensions (`sqrt_rat` v1.4.0 / `exp_rat` v1.4.1).

    The envelope reuses the range-lane framing exactly (same cert schema,
    same theorem, same request commitment scheme, same checker) but binds
    the STANDALONE Python producer's SHA-256 instead of `jackal-native` —
    the standalone lane never invokes the engine — and locks the
    admitted-operator set to `{sqrt}` or `{exp}` per variant.  The
    `variant` field lets the verifier dispatch without inferring from cert
    contents.
    """
    if variant not in RATIONAL_VARIANTS:
        raise ValueError(f"build_variant_formal_receipt: unknown variant {variant!r}")
    admitted_op = _VARIANT_ADMITTED_OPERATOR[variant]
    admitted_expr = _VARIANT_ADMITTED_EXPRESSION[variant]
    coverage_row = _VARIANT_COVERAGE_ROW[variant]
    hdr = _parse_cert_header(cert_bytes)
    sexp = hdr.get("expr", "")
    expr_ops = _operators_in_sexp(sexp) if sexp else set()
    # `var` is a leaf tag, not an operator lock — the variant's operator is
    # what wraps it.  For the sqrt_rat/exp_rat variants the wrapping call
    # must be exactly the admitted operator and nothing else.
    non_leaf_ops = expr_ops - {"var"}
    if non_leaf_ops != {admitted_op}:
        raise ValueError(
            f"variant {variant!r} expected wrapping operator {{{admitted_op!r}}}; "
            f"got {sorted(expr_ops)!r}"
        )
    if request.get("expression", "").replace(" ", "") != admitted_expr:
        raise ValueError(
            f"variant {variant!r} admits only {admitted_expr!r}; got {request.get('expression')!r}"
        )
    receipt: dict[str, Any] = {
        "schema": SCHEMA,
        "variant": variant,
        "release_epoch": release_epoch,
        "emitted_at_unix": int(emitted_at_unix if emitted_at_unix is not None else time.time()),
        "request": {
            "command": request["command"],
            "expression": request["expression"],
            "input_lo": request["input_lo"],
            "input_hi": request["input_hi"],
            "canonical_lo": canonical_lo,
            "canonical_hi": canonical_hi,
            "request_commitment_b64": request_commitment_b64,
        },
        "result": {
            "status": "formal-bounded",
            "enclosure_lo": enclosure[0],
            "enclosure_hi": enclosure[1],
            "cert_status": "bounded",
        },
        "certificate": {
            "schema": hdr.get("schema", ""),
            "model_const_version": hdr.get("model", ""),
            "sexp": sexp,
            "bytes_b64": base64.b64encode(cert_bytes).decode("ascii"),
            "sha256": sha256_hex(cert_bytes),
        },
        "identities": {
            "evaluator_sha256": producer_sha256,
            "producer_sha256": producer_sha256,
            "checker_sha256": checker_sha256,
            "plugin_sha256": plugin_sha256,
            "source_anb_sha256": None,
        },
        "theorem": {
            "id": THEOREM_ID,
            "lean_kernel_axioms": sorted(set(LEAN_KERNEL_AXIOMS)),
        },
        "proof_identity": proof_identity,
        "fragment": {
            "admitted_operators": sorted({admitted_op, "var"}),
            "expression_operators": sorted({admitted_op, "var"}),
            "coverage_row_ids": [coverage_row],
            "coverage_inventory_sha256": coverage_inventory_sha256,
            "unsupported_refused": [f"every expression except {admitted_expr}"],
        },
        "checker": {"verdict": "ACCEPT", "reverify_required": True},
        "assumptions": list(_VARIANT_ASSUMPTIONS[variant]),
        "non_claims": list(_VARIANT_NON_CLAIMS[variant]),
    }
    receipt["receipt_digest_sha256"] = sha256_hex(canonical_json_bytes(_receipt_body(receipt)))
    return receipt


def receipt_variant(receipt: dict[str, Any]) -> str:
    """Return the receipt's declared variant, defaulting to RANGE.

    Missing = "range" is intentional backward-compat for receipts emitted
    before v1.4.2; the verifier never dispatches on an unknown variant.
    """
    v = receipt.get("variant")
    if v is None:
        return RANGE_VARIANT
    if v not in ALL_VARIANTS:
        raise ValueError(f"unknown receipt variant: {v!r}")
    return v
