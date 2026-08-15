#!/usr/bin/env python3
"""JACKAL v1.4.2 formal-receipt independent verifier.

Consumes a `jackal-formal-receipt-v1` JSON document and mechanically
re-establishes every binding it claims — WITHOUT trusting the release
wrapper, the plugin, or the outer receipt digest alone.  Concretely:

  R1  Schema / release_epoch / theorem_id sanity.
  R2  Recompute request commitment from the embedded fields and compare
      byte-for-byte to `certificate.bytes` (source header) and to
      `request.request_commitment_b64`.
  R3  Recompute canonical rational bounds from `input_lo`/`input_hi`
      and compare to `canonical_lo`/`canonical_hi`.
  R4  Recompute certificate SHA-256 from `certificate.bytes_b64` and
      compare to `certificate.sha256`.
  R5  Compare `identities.evaluator_sha256` / `identities.checker_sha256`
      to the caller-supplied EXPECTED identities (pinned in
      release/MANIFEST.sha256 or the plugin's own manifest).
  R6  Re-hash the checker binary the caller pointed us at, byte-compare
      to `identities.checker_sha256` AND to the caller's expected pin.
  R7  Rehydrate the certificate bytes to disk (mode 0600, in a fresh
      tempdir) and invoke the pinned checker executable on it.  Require
      exit 0 AND the lane's exact, complete ACCEPT line.
  R8  Recompute `receipt_digest_sha256` over the receipt body sans
      that field; require equality.
  R9  Verify `fragment.expression_operators ⊆ fragment.admitted_operators`
      against the mandatory, digest-bound coverage inventory.
  R10 Verify `certificate.model_const_version` matches the pinned model.
  R11 Bind a caller-pinned proof-identity record (Lean source closure,
      toolchain, theorem/axiom audit, checker build attestation) and reject
      unsigned provenance if it is presented as authenticated.

The caller MUST also supply the expected release epoch and exact raw request.
This is deliberately not self-describing verification: an old or different
internally consistent receipt cannot satisfy a current request by replay.

Any failure returns a stable refusal class and a nonzero exit; a success
prints one line per bound so it can be logged / diffed.

USAGE
    python3 tools/receipt_verify.py --receipt RECEIPT.json \
        --checker /path/to/jackal_cert_check \
        --expected-evaluator <sha256> --expected-checker <sha256> \
        --expected-release-epoch v1.3.0 \
        --expected-command integrate --expected-expression 'exp(...)' \
        --expected-input-lo 0 --expected-input-hi 1 \
        --expected-tolerance 1/1000000000000 \
        --inventory release/coverage/formal_coverage_inventory.json \
        --expected-inventory <sha256> \
        --proof-identity release/evidence/gaussian_proof_identity.json \
        --expected-proof-identity-file <sha256> \
        --expected-proof-identity-digest <sha256>
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from fractions import Fraction
from pathlib import Path
from typing import Any

# This module is a mandatory, identity-covered runtime dependency.  Import
# failure is fatal: a verifier must never fall back to weaker local constants.
if "formal_receipt" not in sys.modules:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
from formal_receipt import (  # noqa: E402
    SCHEMA, THEOREM_ID, GAUSSIAN_THEOREM_ID, LEAN_KERNEL_AXIOMS,
    MODEL_ASSUMPTIONS, NON_CLAIMS, GAUSSIAN_ASSUMPTIONS,
    GAUSSIAN_NON_CLAIMS,
    RANGE_VARIANT, GAUSSIAN_VARIANT, SQRT_RAT_VARIANT, EXP_RAT_VARIANT,
    RATIONAL_VARIANTS, ALL_VARIANTS,
    SQRT_RAT_ASSUMPTIONS, SQRT_RAT_NON_CLAIMS,
    EXP_RAT_ASSUMPTIONS, EXP_RAT_NON_CLAIMS,
    recompute_receipt_digest, sha256_hex,
    load_proof_identity_binding, PROOF_IDENTITY_BINDING_KEYS,
    canonical_rat as _shared_canonical_rat,
    request_commitment_b64 as _shared_request_commitment_b64,
    gaussian_request_commitment_b64 as _shared_gaussian_request_commitment_b64,
    receipt_variant,
)


MODEL_CONST = "jackal-iv-model-v1"
CERT_SCHEMA = "jackal-eval-cert v2"
GAUSSIAN_CERT_SCHEMA = "jackal-gaussian-integral-cert v1"
MAX_CERTIFICATE_BYTES = 1 << 20
MAX_HEADER_FIELD_BYTES = 1 << 16


class ReceiptRefusal(Exception):
    def __init__(self, cls: str, detail: str = ""):
        super().__init__(f"{cls}: {detail}")
        self.cls = cls
        self.detail = detail


def _reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Strict JSON object decoder used at every file/transport boundary."""
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-standard JSON constant: {value}")


def _strict_json_bytes(raw: bytes) -> Any:
    """Decode RFC-style JSON: strict UTF-8, no duplicate keys, no NaN/Inf."""
    text = raw.decode("utf-8")
    return json.loads(
        text,
        object_pairs_hook=_reject_duplicate_pairs,
        parse_constant=_reject_json_constant,
    )


def _resolve_executable(path: str) -> str:
    if not isinstance(path, str) or not path:
        raise ReceiptRefusal("checker-missing", str(path))
    if not os.path.exists(path):
        raise ReceiptRefusal("checker-missing", path)
    real = os.path.realpath(path)
    if not os.path.isfile(real):
        raise ReceiptRefusal("checker-not-regular", real)
    if not os.access(real, os.X_OK):
        raise ReceiptRefusal("checker-not-executable", real)
    return real


def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def _canonical_rat(tok: str) -> str:
    """Delegate to the load-bearing shared canonicalization; wrap errors as
    ``ReceiptRefusal`` so a call-site catches a stable class."""
    try:
        return _shared_canonical_rat(tok)
    except ValueError as e:
        raise ReceiptRefusal("input-not-rational", str(e)) from e


def _request_commitment_b64(command: str, expression: str, lo: str, hi: str) -> str:
    """Delegate to the load-bearing shared request-commitment framing."""
    return _shared_request_commitment_b64(command, expression, lo, hi)


def _gaussian_request_commitment_b64(command: str, expression: str, lo: str,
                                     hi: str, tolerance: str) -> str:
    return _shared_gaussian_request_commitment_b64(command, expression, lo, hi, tolerance)


def _valid_hex(s: str) -> bool:
    return bool(re.fullmatch(r"[0-9a-f]{64}", s or ""))


def _operators_in_sexp(sexp: str) -> set[str]:
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


_RANGE_RELEASE_NODE_OPS: dict[str, set[str]] = {
    "num_exact": {"num"},
    "var": {"var"},
    # `const_rounded` deliberately ABSENT (2026-08-15, §487-const audit): its
    # value/fl_lo fields are bound only by the undischarged `ConstTCB` premise,
    # so the Lean `releaseNodeOp` refuses it and this mirror MUST refuse too
    "sqrt_rat": {"sqrt"},
    # exp_rat (§487 fragment extension, v1.4.1): pure-ℚ exp via rational
    # Taylor + certified remainder.  The Lean `releaseNodeOp` allowlist
    # accepts this and `Runs.expRat` is checker-sound with no libm TCB.
    "exp_rat": {"exp"},
    # the release fragment identical.  `num_rounded` likewise absent.
    # sqrt_rat (§487 fragment extension, v1.4.0): pure-ℚ sqrt via rational
    # square bracket.  The Lean `releaseNodeOp` allowlist accepts this and
    # `Runs.sqrtRat` is checker-sound with no libm TCB.
    "sqrt_rat": {"sqrt"},
    "neg": {"neg"},
    "add": {"add"},
    "sub": {"sub"},
    "mul": {"mul"},
    "div": {"div"},
    # The exponent is stored in the power node rather than as a child node,
    # but it appears as a numeric literal in the certificate s-expression.
    "powZero": {"pow", "num"},
    "powEvenPos": {"pow", "num"},
    "powOddPos": {"pow", "num"},
    "sin": {"sin"},
    "cos": {"cos"},
    "abs": {"abs"},
    "floor": {"floor"},
    "ceil": {"ceil"},
    "round": {"round"},
    "trunc": {"trunc"},
    "min": {"min"},
    "max": {"max"},
}


def _range_release_operators(cert_bytes: bytes) -> set[str]:
    """Derive the released operator set from exact certificate node variants.

    The s-expression deliberately erases distinctions such as nonnegative
    versus negative/general power.  Release policy does not: only node
    constructors covered by the published FORMAL fragment may reach ACCEPT.
    """
    try:
        text = cert_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ReceiptRefusal("cert-not-utf8", str(exc)) from exc
    logical_ops: set[str] = set()
    node_count = 0
    for raw in text.splitlines():
        if not raw.startswith("node "):
            continue
        parts = raw.split(" ", 3)
        if len(parts) < 3 or not parts[1].isdigit() or not parts[2]:
            raise ReceiptRefusal("certificate-node-framing", raw[:200])
        node_count += 1
        node_op = parts[2]
        mapped = _RANGE_RELEASE_NODE_OPS.get(node_op)
        if mapped is None:
            raise ReceiptRefusal("node-op-outside-release-fragment", node_op)
        logical_ops.update(mapped)
    if node_count == 0:
        raise ReceiptRefusal("certificate-node-framing", "no nodes")
    return logical_ops


_LEAN_ONLY_LINE_BOUNDARIES = frozenset(
    # Every byte str.splitlines() splits on that Lean's `splitOn '\n'` does NOT:
    # CR, VT, FF, NEL (U+0085), LINE SEP (U+2028), PARA SEP (U+2029).
    # Any of them inside an otherwise well-formed header line would make Python
    # break lines where Lean does not, opening a parser-differential injection
    # channel (2026-08-15, §487-parserdiff audit).
    ("\r", "\v", "\f", "\x1c", "\x1d", "\x1e", "\x85", " ", " ")
)


def _parse_cert_header(cert_bytes: bytes) -> dict[str, str]:
    """Independent header parse used as a defense-in-depth cross-check.

    Bound to Lean's `parseCert` (CertCodec.lean) which splits *only* on `'\\n'`
    and treats every line positionally without stripping. Any deviation from
    that model is a divergence channel — we refuse rather than silently drift.

    Load-bearing acceptance now flows through the checker's ACCEPT echo (the
    checker prints its authoritative `output <lo> <hi>` in the ACCEPT line); this
    parser only informs earlier structural sanity checks and never overrides
    what the checker attested.
    """
    hdr: dict[str, str] = {}
    try:
        text = cert_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ReceiptRefusal("cert-not-utf8", str(exc)) from exc
    for boundary in _LEAN_ONLY_LINE_BOUNDARIES:
        if boundary in text:
            raise ReceiptRefusal(
                "cert-illegal-line-boundary",
                f"contains U+{ord(boundary):04X} which Python treats as a line "
                "boundary but the Lean checker does not",
            )
    for line in text.split("\n"):
        if not line:
            continue
        if line.startswith("node ") or line == "end":
            break
        if line in {CERT_SCHEMA, GAUSSIAN_CERT_SCHEMA}:
            if "schema" in hdr:
                raise ReceiptRefusal("cert-header-duplicate", "schema")
            hdr["schema"] = line
            continue
        parts = line.split(" ", 1)
        if len(parts) == 2:
            if parts[0] in hdr:
                raise ReceiptRefusal("cert-header-duplicate", parts[0])
            hdr[parts[0]] = parts[1]
    return hdr


def verify_receipt(*, receipt: dict, checker: str, expected_evaluator: str,
                   expected_checker: str, inventory_path: Path | None = None,
                   expected_inventory_sha256: str | None = None,
                   proof_identity_path: Path | None = None,
                   expected_proof_identity_file: str | None = None,
                   expected_proof_identity_digest: str | None = None,
                   expected_plugin: str | None = None,
                   expected_source: str | None = None,
                   expected_release_epoch: str | None = None,
                   expected_request: dict[str, str] | None = None) -> dict:
    """Independent verification pipeline (see module docstring for R1..R11).

    Returns a diagnostic dict on success; raises ReceiptRefusal otherwise.
    """
    # R1 — schema / theorem; the certificate schema selects the proved theorem.
    if not isinstance(receipt, dict):
        raise ReceiptRefusal("receipt-schema", "not an object")
    base_top_level = {
        "schema", "release_epoch", "emitted_at_unix", "request", "result",
        "certificate", "identities", "theorem", "proof_identity", "fragment",
        "checker", "assumptions", "non_claims", "receipt_digest_sha256",
    }
    # variant is optional on the outer envelope; if present it must be one of
    # the declared set.  Absent = RANGE_VARIANT (backward compat for receipts
    # emitted before v1.4.2).
    extra = set(receipt) - base_top_level
    if extra - {"variant"}:
        raise ReceiptRefusal(
            "receipt-fields", str(sorted((set(receipt) ^ base_top_level) - {"variant"}))
        )
    if not base_top_level.issubset(set(receipt)):
        raise ReceiptRefusal(
            "receipt-fields", str(sorted(base_top_level - set(receipt)))
        )
    try:
        variant = receipt_variant(receipt)
    except ValueError as exc:
        raise ReceiptRefusal("receipt-variant", str(exc)) from exc
    if receipt.get("schema") != SCHEMA:
        raise ReceiptRefusal("receipt-schema", str(receipt.get("schema")))
    if not isinstance(expected_release_epoch, str) or not expected_release_epoch:
        raise ReceiptRefusal("expected-context-missing", "release_epoch")
    if receipt.get("release_epoch") != expected_release_epoch:
        raise ReceiptRefusal(
            "release-epoch",
            f"receipt {receipt.get('release_epoch')!r} != expected {expected_release_epoch!r}",
        )
    if type(receipt.get("emitted_at_unix")) is not int or receipt["emitted_at_unix"] < 0:
        raise ReceiptRefusal("receipt-emitted-at", str(receipt.get("emitted_at_unix")))
    if not isinstance(expected_request, dict):
        raise ReceiptRefusal("expected-context-missing", "request")
    cert = receipt.get("certificate", {})
    if not isinstance(cert, dict):
        raise ReceiptRefusal("certificate-schema", "not an object")
    cert_schema = cert.get("schema")
    if cert_schema not in {CERT_SCHEMA, GAUSSIAN_CERT_SCHEMA}:
        raise ReceiptRefusal("cert-schema", str(cert_schema))
    is_gaussian = cert_schema == GAUSSIAN_CERT_SCHEMA
    is_variant = variant in RATIONAL_VARIANTS
    # variant must line up with cert schema: gaussian ↔ gaussian cert; every
    # range-family variant (range / sqrt_rat / exp_rat) uses the range cert.
    if is_gaussian and variant != GAUSSIAN_VARIANT:
        raise ReceiptRefusal("variant-cert-schema",
                             f"variant {variant!r} incompatible with cert schema {cert_schema!r}")
    if not is_gaussian and variant == GAUSSIAN_VARIANT:
        raise ReceiptRefusal("variant-cert-schema",
                             f"variant {variant!r} incompatible with cert schema {cert_schema!r}")
    expected_cert_keys = (
        {"schema", "family", "method", "bytes_b64", "sha256"}
        if is_gaussian else
        {"schema", "model_const_version", "sexp", "bytes_b64", "sha256"}
    )
    if set(cert) != expected_cert_keys:
        raise ReceiptRefusal(
            "certificate-schema", str(sorted(set(cert) ^ expected_cert_keys))
        )
    expected_theorem = GAUSSIAN_THEOREM_ID if is_gaussian else THEOREM_ID
    thm = receipt.get("theorem", {})
    if not isinstance(thm, dict) or set(thm) != {"id", "lean_kernel_axioms"}:
        keys = sorted(thm) if isinstance(thm, dict) else type(thm).__name__
        raise ReceiptRefusal("theorem-schema", str(keys))
    if thm.get("id") != expected_theorem:
        raise ReceiptRefusal("theorem-id", str(thm.get("id")))
    lka = sorted(set(thm.get("lean_kernel_axioms") or []))
    if lka != sorted(set(LEAN_KERNEL_AXIOMS)):
        raise ReceiptRefusal("theorem-axioms", str(lka))
    if variant == SQRT_RAT_VARIANT:
        expected_assumptions = SQRT_RAT_ASSUMPTIONS
        expected_non_claims = SQRT_RAT_NON_CLAIMS
    elif variant == EXP_RAT_VARIANT:
        expected_assumptions = EXP_RAT_ASSUMPTIONS
        expected_non_claims = EXP_RAT_NON_CLAIMS
    elif is_gaussian:
        expected_assumptions = GAUSSIAN_ASSUMPTIONS
        expected_non_claims = GAUSSIAN_NON_CLAIMS
    else:
        expected_assumptions = MODEL_ASSUMPTIONS
        expected_non_claims = NON_CLAIMS
    if receipt.get("assumptions") != expected_assumptions:
        raise ReceiptRefusal("receipt-assumptions", "mandatory assumptions changed")
    if receipt.get("non_claims") != expected_non_claims:
        raise ReceiptRefusal("receipt-non-claims", "mandatory non-claims changed")
    if receipt.get("checker") != {"verdict": "ACCEPT", "reverify_required": True}:
        raise ReceiptRefusal("receipt-checker-policy", str(receipt.get("checker")))

    # R10 — the range checker has a model pin; Gaussian is zero-libm and binds
    # its exact method/family instead.
    if not is_gaussian and cert.get("model_const_version") != MODEL_CONST:
        raise ReceiptRefusal("model-const-version", str(cert.get("model_const_version")))
    range_release_ops: set[str] | None = None
    if is_gaussian:
        if cert.get("family") != "gaussian-exp-square-v1":
            raise ReceiptRefusal("gaussian-family", str(cert.get("family")))
        if cert.get("method") != "gaussian-total-minus-tails-v1":
            raise ReceiptRefusal("gaussian-method", str(cert.get("method")))

    req = receipt.get("request", {})
    if not isinstance(req, dict):
        raise ReceiptRefusal("request-schema", "not an object")
    required_request = ["command", "expression", "input_lo", "input_hi", "canonical_lo",
                        "canonical_hi", "request_commitment_b64"]
    if is_gaussian:
        required_request += ["tolerance", "canonical_tolerance", "request_commitment_scheme"]
    if set(req) != set(required_request):
        raise ReceiptRefusal("request-schema", str(sorted(set(req) ^ set(required_request))))
    for key in required_request:
        if not isinstance(req.get(key), str) or not req[key]:
            raise ReceiptRefusal("request-field-missing", key)
    expected_keys = {"command", "expression", "input_lo", "input_hi"}
    if is_gaussian:
        expected_keys.add("tolerance")
    if set(expected_request) != expected_keys:
        raise ReceiptRefusal(
            "expected-request-schema",
            str(sorted(set(expected_request) ^ expected_keys)),
        )
    for key in sorted(expected_keys):
        if not isinstance(expected_request.get(key), str):
            raise ReceiptRefusal("expected-request-field", key)
        if req[key] != expected_request[key]:
            raise ReceiptRefusal("expected-request-mismatch", f"{key}: receipt {req[key]!r} != expected {expected_request[key]!r}")
    expected_command = "integrate" if is_gaussian else "range-bound-cert"
    if req["command"] != expected_command:
        raise ReceiptRefusal("request-command", req["command"])

    # R3 — canonical rationals recomputed
    if _canonical_rat(req["input_lo"]) != req["canonical_lo"]:
        raise ReceiptRefusal("request-canonical-lo",
                             f"{_canonical_rat(req['input_lo'])} != {req['canonical_lo']}")
    if _canonical_rat(req["input_hi"]) != req["canonical_hi"]:
        raise ReceiptRefusal("request-canonical-hi",
                             f"{_canonical_rat(req['input_hi'])} != {req['canonical_hi']}")
    if is_gaussian and _canonical_rat(req["tolerance"]) != req["canonical_tolerance"]:
        raise ReceiptRefusal("request-canonical-tolerance",
                             f"{_canonical_rat(req['tolerance'])} != {req['canonical_tolerance']}")
    canonical_lo_q = Fraction(req["canonical_lo"])
    canonical_hi_q = Fraction(req["canonical_hi"])
    if is_gaussian and canonical_lo_q >= canonical_hi_q:
        raise ReceiptRefusal("request-domain", "Gaussian lower must be below upper")
    if not is_gaussian and canonical_lo_q > canonical_hi_q:
        raise ReceiptRefusal("request-domain", "range lower must not exceed upper")
    if is_gaussian and Fraction(req["canonical_tolerance"]) <= 0:
        raise ReceiptRefusal("request-tolerance", "must be positive")

    # R2 — recomputed request commitment must equal both the embedded certificate's
    # `source` header AND the receipt's own `request_commitment_b64` field.
    if is_gaussian:
        if req["request_commitment_scheme"] != "jackal-req-v3-gaussian":
            raise ReceiptRefusal("request-commitment-scheme", req["request_commitment_scheme"])
        recomputed = _gaussian_request_commitment_b64(
            req["command"], req["expression"], req["canonical_lo"],
            req["canonical_hi"], req["canonical_tolerance"])
    else:
        recomputed = _request_commitment_b64(
            req["command"], req["expression"], req["input_lo"], req["input_hi"])
    if recomputed != req["request_commitment_b64"]:
        raise ReceiptRefusal("request-commitment-outer",
                             f"recomputed {recomputed} != receipt {req['request_commitment_b64']}")

    # R4 — certificate bytes SHA-256
    try:
        cert_bytes = base64.b64decode(cert["bytes_b64"].encode("ascii"), validate=True)
    except Exception as e:  # noqa: BLE001
        raise ReceiptRefusal("cert-bytes-encoding", str(e)) from e
    if not cert_bytes or len(cert_bytes) > MAX_CERTIFICATE_BYTES:
        raise ReceiptRefusal(
            "cert-size", f"{len(cert_bytes)} bytes (limit {MAX_CERTIFICATE_BYTES})"
        )
    if any(len(line) > MAX_HEADER_FIELD_BYTES for line in cert_bytes.splitlines()):
        raise ReceiptRefusal("cert-field-size", f"line exceeds {MAX_HEADER_FIELD_BYTES} bytes")
    computed = sha256_hex(cert_bytes)
    if computed != cert.get("sha256"):
        raise ReceiptRefusal("cert-sha256",
                             f"recomputed {computed} != receipt {cert.get('sha256')}")

    # R2 (cont.) — bind the exact request to the certificate.  The general
    # range certificate carries a source commitment; the Gaussian checker
    # directly parses and checks all canonical request fields.
    hdr = _parse_cert_header(cert_bytes)
    if hdr.get("schema") != cert_schema:
        raise ReceiptRefusal("cert-schema-bytes", str(hdr.get("schema")))
    if is_gaussian:
        cert_bindings = {
            "operation": req["command"],
            "expression": req["expression"],
            "lower": req["canonical_lo"],
            "upper": req["canonical_hi"],
            "tolerance": req["canonical_tolerance"],
            "family": "gaussian-exp-square-v1",
            "method": "gaussian-total-minus-tails-v1",
        }
        for key, expected in cert_bindings.items():
            if hdr.get(key) != expected:
                raise ReceiptRefusal("request-vs-gaussian-cert",
                                     f"{key}: {hdr.get(key)!r} != {expected!r}")
    else:
        if hdr.get("source") != recomputed:
            raise ReceiptRefusal("request-commitment-cert", f"cert source {hdr.get('source')} != recomputed {recomputed}")
        if hdr.get("status") != "bounded":
            raise ReceiptRefusal("cert-status-bytes", str(hdr.get("status")))
        if hdr.get("expr") != cert.get("sexp"):
            raise ReceiptRefusal("cert-sexpression", "receipt copy differs from certificate")
        expected_input = f"{req['canonical_lo']} {req['canonical_hi']}"
        if hdr.get("input") != expected_input:
            raise ReceiptRefusal(
                "request-vs-range-cert",
                f"input: {hdr.get('input')!r} != {expected_input!r}",
            )
        # Static defense in depth before invoking the checker: the expression
        # s-expression erases release-policy distinctions (for example,
        # nonnegative versus negative powers), so inspect exact node variants.
        range_release_ops = _range_release_operators(cert_bytes)
    # R5 — identities in the receipt vs the caller's expected pin
    ids = receipt.get("identities", {})
    if not isinstance(ids, dict):
        raise ReceiptRefusal("identity-schema", "not an object")
    required_identity_keys = {
        "evaluator_sha256", "checker_sha256", "plugin_sha256", "source_anb_sha256"
    }
    if is_gaussian or is_variant:
        required_identity_keys.add("producer_sha256")
    if set(ids) != required_identity_keys:
        raise ReceiptRefusal(
            "identity-schema", str(sorted(set(ids) ^ required_identity_keys))
        )
    for label, expected, present in (
        ("evaluator", expected_evaluator, ids.get("evaluator_sha256")),
        ("checker",   expected_checker,   ids.get("checker_sha256")),
    ):
        if not _valid_hex(expected or ""):
            raise ReceiptRefusal(f"expected-{label}-malformed", str(expected))
        if present != expected:
            raise ReceiptRefusal(f"{label}-identity", f"receipt {present} != expected {expected}")
    # For the range lane the certificate's `exe` field binds the invoking
    # jackal-native evaluator; every other variant bypasses jackal-native.
    if not is_gaussian and not is_variant and hdr.get("exe") != ids.get("evaluator_sha256"):
        raise ReceiptRefusal(
            "evaluator-vs-certificate",
            f"cert {hdr.get('exe')} != receipt {ids.get('evaluator_sha256')}",
        )
    if is_gaussian or is_variant:
        if ids.get("producer_sha256") != expected_evaluator:
            raise ReceiptRefusal(
                "producer-identity",
                f"receipt {ids.get('producer_sha256')} != expected {expected_evaluator}",
            )
        if ids.get("source_anb_sha256") is not None:
            raise ReceiptRefusal("variant-source-identity",
                                 str(ids.get("source_anb_sha256")))
        if expected_source is not None:
            raise ReceiptRefusal("expected-source-unexpected", expected_source)
        # sqrt_rat / exp_rat certs also carry the producer SHA in `exe`
        # (mirroring the range lane's convention) so the exe/receipt bind is
        # still enforced end-to-end.
        if is_variant and hdr.get("exe") != ids.get("producer_sha256"):
            raise ReceiptRefusal(
                "producer-vs-certificate",
                f"cert {hdr.get('exe')} != receipt {ids.get('producer_sha256')}",
            )
    else:
        source_id = ids.get("source_anb_sha256")
        if not _valid_hex(expected_source or ""):
            raise ReceiptRefusal("expected-source-malformed", str(expected_source))
        if source_id != expected_source:
            raise ReceiptRefusal(
                "source-identity", f"receipt {source_id} != expected {expected_source}"
            )
    if expected_plugin is not None:
        if not _valid_hex(expected_plugin):
            raise ReceiptRefusal("expected-plugin-malformed", expected_plugin)
        if ids.get("plugin_sha256") != expected_plugin:
            raise ReceiptRefusal("plugin-identity", f"receipt {ids.get('plugin_sha256')} != expected {expected_plugin}")
    elif ids.get("plugin_sha256") is not None:
        raise ReceiptRefusal("expected-plugin-missing", "receipt is plugin-bound")

    # Bind the checker bytes to the exact audited Lean source/toolchain record.
    proof_binding = receipt.get("proof_identity")
    if not isinstance(proof_binding, dict) or set(proof_binding) != \
            PROOF_IDENTITY_BINDING_KEYS:
        raise ReceiptRefusal("proof-identity-schema", "missing/extra binding fields")
    if proof_identity_path is None:
        raise ReceiptRefusal("proof-identity-required", "")
    try:
        observed_proof = load_proof_identity_binding(proof_identity_path)
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ReceiptRefusal("proof-identity-unreadable", str(exc)) from exc
    if proof_binding != observed_proof:
        raise ReceiptRefusal("proof-identity-mismatch", "receipt != caller-supplied record")
    if not _valid_hex(expected_proof_identity_file or ""):
        raise ReceiptRefusal(
            "expected-proof-file-malformed", str(expected_proof_identity_file)
        )
    if not _valid_hex(expected_proof_identity_digest or ""):
        raise ReceiptRefusal(
            "expected-proof-digest-malformed", str(expected_proof_identity_digest)
        )
    if proof_binding["file_sha256"] != expected_proof_identity_file:
        raise ReceiptRefusal(
            "proof-identity-file",
            f"record {proof_binding['file_sha256']} != expected {expected_proof_identity_file}",
        )
    if proof_binding["identity_digest_sha256"] != expected_proof_identity_digest:
        raise ReceiptRefusal(
            "proof-identity-digest",
            f"record {proof_binding['identity_digest_sha256']} != expected "
            f"{expected_proof_identity_digest}",
        )
    expected_proof_schema = (
        "jackal-gaussian-proof-identity-v1" if is_gaussian
        else "jackal-range-proof-identity-v1"
    )
    expected_proof_theorem = (
        "JackalIv.GaussianCert.gaussian_integral_check_sound" if is_gaussian
        else "JackalIv.Cert.request_bound_certified_release"
    )
    if proof_binding["schema"] != expected_proof_schema:
        raise ReceiptRefusal("proof-identity-lane", proof_binding["schema"])
    if proof_binding["soundness_theorem"] != expected_proof_theorem:
        raise ReceiptRefusal("proof-identity-theorem", proof_binding["soundness_theorem"])
    if proof_binding["checker_sha256"] != expected_checker:
        raise ReceiptRefusal("proof-identity-checker", proof_binding["checker_sha256"])
    if proof_binding["authenticated"] is not False:
        raise ReceiptRefusal("proof-identity-authentication", "must state false")

    # R6 — the checker executable this verifier is about to run must MATCH.
    chk_real = _resolve_executable(checker)
    chk_pre = _sha256_file(chk_real)
    if chk_pre != ids.get("checker_sha256"):
        raise ReceiptRefusal("checker-binary-mismatch", f"file {chk_pre} != receipt {ids.get('checker_sha256')}")

    # R8 — outer digest must be over these exact bytes
    recomputed_digest = recompute_receipt_digest(receipt)
    if recomputed_digest != receipt.get("receipt_digest_sha256"):
        raise ReceiptRefusal("receipt-digest", f"recomputed {recomputed_digest} != receipt {receipt.get('receipt_digest_sha256')}")

    # R7 — RE-RUN the proved checker on the exact rehydrated bytes.
    #
    # This is the load-bearing step: outer-digest identity alone is NOT proof.
    # The receipt is trusted only when the pinned checker binary actually
    # accepts the embedded certificate on this machine right now.
    with tempfile.TemporaryDirectory(prefix="jackal-receipt-verify-") as td:
        cert_path = os.path.join(td, "rehydrated.cert")
        fd = os.open(cert_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            os.write(fd, cert_bytes)
        finally:
            os.close(fd)
        checker_argv = [chk_real, cert_path]
        if not is_gaussian:
            checker_argv.extend([
                req["command"], req["expression"], req["canonical_lo"],
                req["canonical_hi"],
            ])
        try:
            cproc = subprocess.run(
                checker_argv, capture_output=True, text=False, timeout=3600
            )
        except subprocess.TimeoutExpired as exc:
            raise ReceiptRefusal("checker-timeout", str(exc)) from exc
        except OSError as exc:
            raise ReceiptRefusal("checker-exec-failed", str(exc)) from exc
        # Range-lane ACCEPT now carries the checker's AUTHORITATIVE
        # `output <lo> <hi>` (2026-08-15, §487-parserdiff audit) so downstream
        # verification binds to what the Lean checker attested — never to a
        # second, potentially divergent Python re-parse of the header. Gaussian
        # ACCEPT remains a fixed-shape token.
        gauss_accept = (
            b"ACCEPT theorem=gaussian_integral_check_sound "
            b"family=gaussian-exp-square-v1\n"
        )
        range_prefix = (
            b"ACCEPT request-bound theorem=request_bound_certified_release "
            b"command=range-bound-cert output "
        )
        stdout_bytes = cproc.stdout
        if cproc.returncode != 0:
            raise ReceiptRefusal(
                "checker-rejected-on-rerun",
                (cproc.stderr or stdout_bytes)[:200].decode("utf-8", errors="replace"),
            )
        checker_output_lo: str | None = None
        checker_output_hi: str | None = None
        if is_gaussian:
            if stdout_bytes != gauss_accept:
                raise ReceiptRefusal(
                    "checker-rejected-on-rerun",
                    (cproc.stderr or stdout_bytes)[:200].decode("utf-8", errors="replace"),
                )
        else:
            if not stdout_bytes.startswith(range_prefix) or not stdout_bytes.endswith(b"\n"):
                raise ReceiptRefusal(
                    "checker-rejected-on-rerun",
                    (cproc.stderr or stdout_bytes)[:200].decode("utf-8", errors="replace"),
                )
            tail = stdout_bytes[len(range_prefix):-1]  # strip trailing '\n'
            # ratToStr never emits whitespace, '/' appears only inside numerator/denominator;
            # split on the SINGLE separating space between lo and hi.
            try:
                lo_bytes, hi_bytes = tail.split(b" ", 1)
                if b" " in hi_bytes:
                    raise ValueError("extra tokens after checker output_hi")
                checker_output_lo = lo_bytes.decode("ascii")
                checker_output_hi = hi_bytes.decode("ascii")
            except (ValueError, UnicodeDecodeError) as exc:
                raise ReceiptRefusal("checker-accept-malformed", str(exc)) from exc
        chk_post = _sha256_file(chk_real)
        if chk_post != chk_pre:
            raise ReceiptRefusal("checker-toctou", "checker binary changed during rerun")

    # R9 — the exact coverage inventory is mandatory and digest-bound.
    if inventory_path is None:
        raise ReceiptRefusal("coverage-inventory-required", "")
    inv_path = Path(inventory_path)
    try:
        inv_bytes = inv_path.read_bytes()
        doc = _strict_json_bytes(inv_bytes)
    except Exception as exc:  # noqa: BLE001
        raise ReceiptRefusal("coverage-inventory-unreadable", str(exc)) from exc
    if not isinstance(doc, dict) or set(doc) != {
        "schema", "formal_fragment", "refused_from_formal", "rows"
    }:
        keys = sorted(doc) if isinstance(doc, dict) else type(doc).__name__
        raise ReceiptRefusal("coverage-inventory-fields", str(keys))
    if doc.get("schema") != "jackal-coverage-inventory-v1":
        raise ReceiptRefusal("coverage-inventory-schema", str(doc.get("schema")))
    row_list = doc.get("rows")
    if not isinstance(row_list, list) or not row_list:
        raise ReceiptRefusal("coverage-inventory-rows", "empty/malformed")
    rows: dict[str, dict] = {}
    for row in row_list:
        key = row.get("operator") if isinstance(row, dict) else None
        if not isinstance(key, str) or not key or key in rows:
            raise ReceiptRefusal("coverage-inventory-duplicate", str(key))
        rows[key] = row

    frag = receipt.get("fragment", {})
    if not isinstance(frag, dict):
        raise ReceiptRefusal("fragment-schema", "not an object")
    required_fragment_keys = {
        "admitted_operators", "expression_operators", "coverage_row_ids",
        "coverage_inventory_sha256", "unsupported_refused",
    }
    if set(frag) != required_fragment_keys:
        raise ReceiptRefusal(
            "fragment-schema", str(sorted(set(frag) ^ required_fragment_keys))
        )
    inventory_sha = hashlib.sha256(inv_bytes).hexdigest()
    if not _valid_hex(expected_inventory_sha256 or ""):
        raise ReceiptRefusal(
            "expected-inventory-malformed", str(expected_inventory_sha256)
        )
    if inventory_sha != expected_inventory_sha256:
        raise ReceiptRefusal(
            "coverage-inventory-expected",
            f"observed {inventory_sha} != expected {expected_inventory_sha256}",
        )
    if frag.get("coverage_inventory_sha256") != inventory_sha:
        raise ReceiptRefusal(
            "coverage-inventory-identity",
            f"receipt {frag.get('coverage_inventory_sha256')} != observed {inventory_sha}",
        )

    admitted = set(frag.get("admitted_operators") or [])
    expr_ops = set(frag.get("expression_operators") or [])
    if not expr_ops:
        raise ReceiptRefusal("no-expression-operators", "")
    # Re-derive from the checker-covered certificate representation.  Range
    # certificates are checked at BOTH levels: exact node variants enforce the
    # release allowlist, while the s-expression comparison prevents the node
    # and expression views from drifting apart.
    if is_gaussian:
        rederived = {"exp", "mul", "neg", "pow2", "sub"}
    else:
        if range_release_ops is None:
            raise ReceiptRefusal("certificate-node-framing", "range nodes not derived")
        rederived = range_release_ops
        sexp_ops = _operators_in_sexp(hdr.get("expr", ""))
        if rederived != sexp_ops:
            raise ReceiptRefusal(
                "node-operators-vs-sexpression",
                f"nodes {sorted(rederived)} != sexp {sorted(sexp_ops)}",
            )
    if rederived != expr_ops:
        raise ReceiptRefusal("operators-vs-certificate", f"receipt {sorted(expr_ops)} != cert-derived {sorted(rederived)}")

    if is_gaussian:
        expected_admitted = {"exp", "mul", "neg", "pow2", "sub"}
        expected_coverage = ["gaussian-exp-square-integral-v1"]
        expected_refused = ["all expressions outside gaussian-exp-square-v1"]
    elif variant == SQRT_RAT_VARIANT:
        # sqrt_rat variant restricts the release fragment to `sqrt` alone
        # (plus the `var` leaf every range expression carries).  The
        # coverage-row id points at the plugin-tool row rather than the
        # per-operator row; the operator row still exists and must be FORMAL.
        expected_admitted = {"sqrt", "var"}
        expected_coverage = ["jackal_sqrt_rat_bound"]
        expected_refused = ["every expression except sqrt(x)"]
    elif variant == EXP_RAT_VARIANT:
        expected_admitted = {"exp", "var"}
        expected_coverage = ["jackal_exp_rat_bound"]
        expected_refused = ["every expression except exp(x)"]
    else:
        expected_admitted = {
            key for key, row in rows.items()
            if row.get("kind") == "operator" and row.get("verdict") == "FORMAL"
        }
        expected_coverage = sorted(expr_ops)
        expected_refused = sorted(
            key for key, row in rows.items() if row.get("verdict") == "REFUSED"
        )
    if admitted != expected_admitted:
        raise ReceiptRefusal(
            "fragment-admitted", f"receipt {sorted(admitted)} != inventory {sorted(expected_admitted)}"
        )
    if frag.get("coverage_row_ids") != expected_coverage:
        raise ReceiptRefusal("coverage-row-set", str(frag.get("coverage_row_ids")))
    if frag.get("unsupported_refused") != expected_refused:
        raise ReceiptRefusal("fragment-refusal-set", str(frag.get("unsupported_refused")))
    stray = sorted(expr_ops - admitted)
    if stray:
        raise ReceiptRefusal("operator-outside-fragment", str(stray))
    for key in expected_coverage:
        row = rows.get(key)
        if row is None:
            raise ReceiptRefusal("coverage-row-missing", key)
        if row.get("verdict") != "FORMAL":
            raise ReceiptRefusal("coverage-row-not-formal", key)
        if row.get("soundness_theorem") != expected_theorem:
            raise ReceiptRefusal("coverage-row-theorem-mismatch",
                                 f"{key}:{row.get('soundness_theorem')}")
    # For rational-fragment variants, the coverage-row loop above locks
    # the plugin-tool row.  Also require the underlying operator row (sqrt/exp)
    # to still be FORMAL in the inventory so a mutation that quietly demotes
    # the operator from FORMAL cannot be masked by a plugin-tool-row alone.
    if variant == SQRT_RAT_VARIANT:
        op_row = rows.get("sqrt")
        if op_row is None or op_row.get("verdict") != "FORMAL":
            raise ReceiptRefusal("variant-operator-row",
                                 f"sqrt operator row must be FORMAL for sqrt_rat variant")
    elif variant == EXP_RAT_VARIANT:
        op_row = rows.get("exp")
        if op_row is None or op_row.get("verdict") != "FORMAL":
            raise ReceiptRefusal("variant-operator-row",
                                 f"exp operator row must be FORMAL for exp_rat variant")

    # Result-status must be exactly formal-bounded (no silent downgrade).
    res = receipt.get("result", {})
    if not isinstance(res, dict):
        raise ReceiptRefusal("result-schema", "not an object")
    required_result_keys = {"status", "enclosure_lo", "enclosure_hi", "cert_status"}
    if set(res) != required_result_keys:
        raise ReceiptRefusal("result-schema", str(sorted(set(res) ^ required_result_keys)))
    if res.get("status") != "formal-bounded":
        raise ReceiptRefusal("result-status", str(res.get("status")))
    expected_cert_status = "gaussian-formal-bounded" if is_gaussian else "bounded"
    if res.get("cert_status") != expected_cert_status:
        raise ReceiptRefusal("result-cert-status", str(res.get("cert_status")))
    if not isinstance(res.get("enclosure_lo"), str) or not isinstance(res.get("enclosure_hi"), str):
        raise ReceiptRefusal("result-enclosure-format", "")
    canonical_result_lo = _canonical_rat(res["enclosure_lo"])
    canonical_result_hi = _canonical_rat(res["enclosure_hi"])
    if canonical_result_lo != res["enclosure_lo"]:
        raise ReceiptRefusal("result-enclosure-canonical", "lower")
    if canonical_result_hi != res["enclosure_hi"]:
        raise ReceiptRefusal("result-enclosure-canonical", "upper")
    if Fraction(canonical_result_lo) > Fraction(canonical_result_hi):
        raise ReceiptRefusal("result-enclosure-order", "lower exceeds upper")
    # Cross-check the reported enclosure against the CHECKER's authoritative
    # attestation. For the range lane the Lean checker echoes its proven
    # `output <lo> <hi>` (= the root enclosure `structuralOk` binds and the
    # theorem encloses) directly in the ACCEPT line, so the load-bearing source
    # is the checker echo — never a second Python re-parse of the header. The
    # header parse (itself now refused on any Lean/Python line-boundary
    # divergence) is kept only as a defense-in-depth agreement check.
    # For the Gaussian lane the ACCEPT token is fixed-shape; its enclosure is
    # bound through the header, whose parse is boundary-hardened.
    if is_gaussian:
        cert_out = hdr.get("output", "")
        if not cert_out or " " not in cert_out:
            raise ReceiptRefusal("cert-output-format", cert_out)
        ce_lo, ce_hi = cert_out.split(" ", 1)
    else:
        if checker_output_lo is None or checker_output_hi is None:
            raise ReceiptRefusal("checker-echo-missing", "range ACCEPT carried no output echo")
        ce_lo, ce_hi = checker_output_lo, checker_output_hi
        # Defense-in-depth: the independent header re-parse must AGREE with the
        # checker's echo. Any divergence is a parser-differential signal → refuse.
        hdr_out = hdr.get("output", "")
        h_parts = hdr_out.split(" ", 1) if hdr_out else []
        if len(h_parts) != 2 or _canonical_rat(h_parts[0]) != _canonical_rat(ce_lo) \
                or _canonical_rat(h_parts[1]) != _canonical_rat(ce_hi):
            raise ReceiptRefusal("checker-echo-header-divergence",
                                 f"header {hdr_out!r} != checker echo {ce_lo} {ce_hi}")
    if _canonical_rat(ce_lo) != canonical_result_lo:
        raise ReceiptRefusal("enclosure-lo-mismatch", f"checker {_canonical_rat(ce_lo)} != receipt {canonical_result_lo}")
    if _canonical_rat(ce_hi) != canonical_result_hi:
        raise ReceiptRefusal("enclosure-hi-mismatch", f"checker {_canonical_rat(ce_hi)} != receipt {canonical_result_hi}")

    return {
        "verdict": "ACCEPT",
        "receipt_digest_sha256": recomputed_digest,
        "certificate_sha256": computed,
        "checker_sha256": chk_pre,
        "evaluator_sha256": ids["evaluator_sha256"],
        "plugin_sha256": ids.get("plugin_sha256"),
        "request_commitment": recomputed,
        "coverage_inventory_sha256": inventory_sha,
        "proof_identity_file_sha256": proof_binding["file_sha256"],
        "proof_identity_digest_sha256": proof_binding["identity_digest_sha256"],
        "expression_operators": sorted(expr_ops),
        "enclosure": [res["enclosure_lo"], res["enclosure_hi"]],
    }


def _cli() -> int:
    if not (sys.flags.isolated and sys.flags.no_site):
        print(
            "status=refused reason=python-not-isolated "
            "detail=\"invoke jackal-receipt-verify\"",
            file=sys.stderr,
        )
        return 126
    ap = argparse.ArgumentParser(description="JACKAL formal-receipt independent verifier")
    ap.add_argument("--receipt", required=True, help="path to a formal-bounded receipt JSON")
    ap.add_argument("--checker", required=True, help="pinned jackal_cert_check executable")
    ap.add_argument("--expected-evaluator", required=True, help="pinned evaluator SHA-256")
    ap.add_argument("--expected-checker", required=True, help="pinned checker SHA-256")
    ap.add_argument("--expected-source", default=None,
                    help="pinned source SHA-256; required for range receipts only")
    ap.add_argument("--expected-release-epoch", required=True,
                    help="caller-authorized release epoch (for example v1.3.0)")
    ap.add_argument("--expected-command", required=True,
                    help="caller-authorized operation")
    ap.add_argument("--expected-expression", required=True,
                    help="exact raw expression from the caller's request")
    ap.add_argument("--expected-input-lo", required=True,
                    help="exact raw lower-bound token from the caller's request")
    ap.add_argument("--expected-input-hi", required=True,
                    help="exact raw upper-bound token from the caller's request")
    ap.add_argument("--expected-tolerance", default=None,
                    help="exact raw tolerance token; required for Gaussian receipts only")
    ap.add_argument("--inventory", required=True,
                    help="exact digest-bound coverage inventory")
    ap.add_argument("--expected-inventory", required=True,
                    help="caller-pinned coverage inventory SHA-256")
    ap.add_argument("--proof-identity", required=True,
                    help="caller-pinned range/Gaussian proof identity JSON")
    ap.add_argument("--expected-proof-identity-file", required=True,
                    help="caller-pinned SHA-256 of the exact proof identity file")
    ap.add_argument("--expected-proof-identity-digest", required=True,
                    help="caller-pinned internal proof identity digest")
    ap.add_argument("--expected-plugin", default=None,
                    help="optional plugin binary SHA-256 to bind (Hermes plugin path)")
    args = ap.parse_args()
    try:
        receipt = _strict_json_bytes(Path(args.receipt).read_bytes())
    except Exception as e:  # noqa: BLE001
        print(f"status=refused reason=receipt-unreadable detail=\"{e}\"", file=sys.stderr)
        return 1
    try:
        expected_request = {
            "command": args.expected_command,
            "expression": args.expected_expression,
            "input_lo": args.expected_input_lo,
            "input_hi": args.expected_input_hi,
        }
        is_gaussian = (
            receipt.get("certificate", {}).get("schema") == GAUSSIAN_CERT_SCHEMA
        )
        if is_gaussian:
            if args.expected_tolerance is None:
                raise ReceiptRefusal("expected-context-missing", "tolerance")
            expected_request["tolerance"] = args.expected_tolerance
        elif args.expected_tolerance is not None:
            raise ReceiptRefusal("expected-request-schema", "tolerance on range receipt")
        r = verify_receipt(receipt=receipt, checker=args.checker,
                           expected_evaluator=args.expected_evaluator,
                           expected_checker=args.expected_checker,
                           inventory_path=Path(args.inventory),
                           expected_inventory_sha256=args.expected_inventory,
                           proof_identity_path=Path(args.proof_identity),
                           expected_proof_identity_file=args.expected_proof_identity_file,
                           expected_proof_identity_digest=args.expected_proof_identity_digest,
                           expected_plugin=args.expected_plugin,
                           expected_source=args.expected_source,
                           expected_release_epoch=args.expected_release_epoch,
                           expected_request=expected_request)
    except ReceiptRefusal as exc:
        print(f"status=refused reason={exc.cls} detail=\"{exc.detail}\"", file=sys.stderr)
        return 1
    print(f"status=verified verdict={r['verdict']}")
    print("receipt_valid=true")
    print("checker_verdict=ACCEPT")
    print(f"receipt.digest={r['receipt_digest_sha256']}")
    print(f"certificate.sha256={r['certificate_sha256']}")
    print(f"checker.sha256={r['checker_sha256']}")
    print(f"evaluator.sha256={r['evaluator_sha256']}")
    print(f"coverage_inventory.sha256={r['coverage_inventory_sha256']}")
    print(f"proof_identity.file_sha256={r['proof_identity_file_sha256']}")
    print(f"proof_identity.digest_sha256={r['proof_identity_digest_sha256']}")
    if r.get("plugin_sha256"):
        print(f"plugin.sha256={r['plugin_sha256']}")
    print(f"expression.operators={','.join(r['expression_operators'])}")
    print(f"enclosure=[{r['enclosure'][0]},{r['enclosure'][1]}]")
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
