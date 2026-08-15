#!/usr/bin/env python3
"""JACKAL v1.2.0 formal-bounded receipt — schema, emitter, and outer digest.

A "formal receipt" carries EVERY field a downstream reverifier needs to
mechanically re-establish the release verdict without trusting anything
except:

  * the exact pinned checker executable identity (hash-pinned in the receipt);
  * the Lean kernel that compiled it (theorem id + axioms recorded);
  * the canonical rational codec (part of the checker binary).

In particular the receipt embeds the certificate BYTES base64-encoded, so
the independent verifier (`tools/receipt_verify.py`) can rehydrate them to
disk and RE-RUN the compiled `jackal_cert_check` executable.  Recomputing
`receipt_digest_sha256` alone is NOT sufficient to accept a receipt — the
digest binds the fields together and defeats trivial substitution, but
soundness comes from the checker actually accepting the exact certificate
bytes, on this machine, at verify time.

Schema fields (all mandatory; missing/null on a formal receipt = refuse):

  schema                   fixed string "jackal-formal-receipt-v1"
  release_epoch            release version tag ("v1.2.0", …)
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
  theorem                  { id: "cert_check_sound",
                             lean_kernel_axioms: [...] }
  fragment                 { admitted_operators, expression_operators,
                             coverage_row_ids, unsupported_refused }
  checker                  { verdict: "ACCEPT",
                             reverify_required: true }
  assumptions              [str, ...]    — model + toolchain TCB
  non_claims               [str, ...]    — explicit scope refusals
  receipt_digest_sha256    hex; SHA-256 of the canonical JSON of every
                           field EXCEPT this one (sort_keys, separators).

`receipt_digest_sha256` is the outer canonical fingerprint referenced by
the user request (§7).  It is a fingerprint over the receipt fields; it is
NOT a proof by itself and NOT a substitute for re-running the checker.
"""
from __future__ import annotations

import base64
import hashlib
import json
import time
from fractions import Fraction
from typing import Any, Iterable

SCHEMA = "jackal-formal-receipt-v1"
THEOREM_ID = "cert_check_sound"
LEAN_KERNEL_AXIOMS = ["Classical.choice", "Quot.sound", "propext"]
MODEL_ASSUMPTIONS = [
    "IEEE-754 correctly rounded basic float ops (+, -, *, /)",
    "libm calls within 2 ulp on the const_rounded lane (ModelTCB.const on pi/e/tau)",
    "Lean 4 kernel + Mathlib toolchain that compiled jackal_cert_check",
    "Canonical rational codec (Lean/Mathlib Rat) as reduced-lowest-terms num/den",
    "The pinned evaluator and checker binaries executed as their hashes describe",
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
]


def canonical_json_bytes(obj: Any) -> bytes:
    """Canonical JSON encoding used for every digest in the receipt system.

    sort_keys + tightest separators + ensure_ascii=False for reproducibility.
    """
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sha256_hex(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


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
    text = cert_bytes.decode("utf-8", errors="replace")
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("node ") or line == "end":
            break
        if line == "jackal-eval-cert v2":
            hdr["schema"] = line
            continue
        parts = line.split(" ", 1)
        if len(parts) == 2:
            hdr[parts[0]] = parts[1]
    return hdr


def build_formal_receipt(*, release_epoch: str, request: dict[str, str], enclosure: tuple[str, str],
                         cert_bytes: bytes, evaluator_sha256: str, checker_sha256: str,
                         source_anb_sha256: str | None, plugin_sha256: str | None,
                         admitted_operators: Iterable[str], coverage_row_ids: Iterable[str],
                         unsupported_refused: Iterable[str], canonical_lo: str, canonical_hi: str,
                         request_commitment_b64: str, cert_status: str = "bounded",
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
        "fragment": {
            "admitted_operators": admitted,
            "expression_operators": sorted(expr_ops),
            "coverage_row_ids": sorted(set(coverage_row_ids)),
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


def _receipt_body(receipt: dict[str, Any]) -> dict[str, Any]:
    """Return the receipt sans `receipt_digest_sha256` for digest computation."""
    return {k: v for k, v in receipt.items() if k != "receipt_digest_sha256"}


def recompute_receipt_digest(receipt: dict[str, Any]) -> str:
    return sha256_hex(canonical_json_bytes(_receipt_body(receipt)))


def dump_receipt(receipt: dict[str, Any]) -> str:
    """Serialize a receipt canonically (JSON, sort_keys, 2-space indent for eyes)."""
    return json.dumps(receipt, sort_keys=True, indent=2, ensure_ascii=False)
