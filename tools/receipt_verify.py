#!/usr/bin/env python3
"""JACKAL v1.2.0 formal-receipt independent verifier.

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
      exit 0 AND stdout starting with "ACCEPT".
  R8  Recompute `receipt_digest_sha256` over the receipt body sans
      that field; require equality.
  R9  Verify `fragment.expression_operators ⊆ fragment.admitted_operators`.
      Also verify that `theorem.id` matches an inventory entry when a
      coverage inventory is supplied (opt-in via `--inventory`).
  R10 Verify `certificate.model_const_version` matches the pinned model.

Any failure returns a stable refusal class and a nonzero exit; a success
prints one line per bound so it can be logged / diffed.

USAGE
    python3 tools/receipt_verify.py --receipt RECEIPT.json \
        --checker /path/to/jackal_cert_check \
        --expected-evaluator <sha256> --expected-checker <sha256> \
        [--inventory release/coverage/formal_coverage_inventory.json]
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

# Keep in sync with tools/formal_receipt.py; imported when this file is a
# sibling of that one (repo mode), otherwise defined locally (package mode).
try:  # pragma: no cover — sibling import in repo/CI mode
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from formal_receipt import (  # noqa: F401
        SCHEMA, THEOREM_ID, LEAN_KERNEL_AXIOMS, MODEL_ASSUMPTIONS, NON_CLAIMS,
        recompute_receipt_digest, canonical_json_bytes, sha256_hex,
        canonical_rat as _shared_canonical_rat,
        request_commitment_b64 as _shared_request_commitment_b64,
    )
except Exception:  # pragma: no cover — defensive fallback
    SCHEMA = "jackal-formal-receipt-v1"
    THEOREM_ID = "cert_check_sound"
    LEAN_KERNEL_AXIOMS = ["Classical.choice", "Quot.sound", "propext"]
    MODEL_ASSUMPTIONS: list[str] = []
    NON_CLAIMS: list[str] = []

    def canonical_json_bytes(obj: Any) -> bytes:
        return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()

    def sha256_hex(b: bytes) -> str:
        return hashlib.sha256(b).hexdigest()

    def recompute_receipt_digest(receipt: dict) -> str:
        body = {k: v for k, v in receipt.items() if k != "receipt_digest_sha256"}
        return sha256_hex(canonical_json_bytes(body))


MODEL_CONST = "jackal-iv-model-v1"
CERT_SCHEMA = "jackal-eval-cert v2"


class ReceiptRefusal(Exception):
    def __init__(self, cls: str, detail: str = ""):
        super().__init__(f"{cls}: {detail}")
        self.cls = cls
        self.detail = detail


def _resolve_executable(path: str) -> str:
    if not os.path.exists(path):
        raise ReceiptRefusal("checker-missing", path)
    real = os.path.realpath(path)
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


def _parse_cert_header(cert_bytes: bytes) -> dict[str, str]:
    hdr: dict[str, str] = {}
    text = cert_bytes.decode("utf-8", errors="replace")
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("node ") or line == "end":
            break
        if line == CERT_SCHEMA:
            hdr["schema"] = line
            continue
        parts = line.split(" ", 1)
        if len(parts) == 2:
            hdr[parts[0]] = parts[1]
    return hdr


def verify_receipt(*, receipt: dict, checker: str, expected_evaluator: str,
                   expected_checker: str, inventory_path: Path | None = None,
                   expected_plugin: str | None = None) -> dict:
    """Independent verification pipeline (see module docstring for R1..R10).

    Returns a diagnostic dict on success; raises ReceiptRefusal otherwise.
    """
    # R1 — schema / theorem
    if receipt.get("schema") != SCHEMA:
        raise ReceiptRefusal("receipt-schema", str(receipt.get("schema")))
    thm = receipt.get("theorem", {})
    if thm.get("id") != THEOREM_ID:
        raise ReceiptRefusal("theorem-id", str(thm.get("id")))
    lka = sorted(set(thm.get("lean_kernel_axioms") or []))
    if lka != sorted(set(LEAN_KERNEL_AXIOMS)):
        raise ReceiptRefusal("theorem-axioms", str(lka))

    # R10 — model pin
    cert = receipt.get("certificate", {})
    if cert.get("model_const_version") != MODEL_CONST:
        raise ReceiptRefusal("model-const-version", str(cert.get("model_const_version")))
    if cert.get("schema") != CERT_SCHEMA:
        raise ReceiptRefusal("cert-schema", str(cert.get("schema")))

    req = receipt.get("request", {})
    for key in ("command", "expression", "input_lo", "input_hi", "canonical_lo",
                "canonical_hi", "request_commitment_b64"):
        if not isinstance(req.get(key), str) or not req[key]:
            raise ReceiptRefusal("request-field-missing", key)

    # R3 — canonical rationals recomputed
    if _canonical_rat(req["input_lo"]) != req["canonical_lo"]:
        raise ReceiptRefusal("request-canonical-lo",
                             f"{_canonical_rat(req['input_lo'])} != {req['canonical_lo']}")
    if _canonical_rat(req["input_hi"]) != req["canonical_hi"]:
        raise ReceiptRefusal("request-canonical-hi",
                             f"{_canonical_rat(req['input_hi'])} != {req['canonical_hi']}")

    # R2 — recomputed request commitment must equal both the embedded certificate's
    # `source` header AND the receipt's own `request_commitment_b64` field.
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
    computed = sha256_hex(cert_bytes)
    if computed != cert.get("sha256"):
        raise ReceiptRefusal("cert-sha256",
                             f"recomputed {computed} != receipt {cert.get('sha256')}")

    # R2 (cont.) — cert `source` header must equal the receipt's recomputed commitment
    hdr = _parse_cert_header(cert_bytes)
    if hdr.get("source") != recomputed:
        raise ReceiptRefusal("request-commitment-cert", f"cert source {hdr.get('source')} != recomputed {recomputed}")

    # R5 — identities in the receipt vs the caller's expected pin
    ids = receipt.get("identities", {})
    for label, expected, present in (
        ("evaluator", expected_evaluator, ids.get("evaluator_sha256")),
        ("checker",   expected_checker,   ids.get("checker_sha256")),
    ):
        if not _valid_hex(expected or ""):
            raise ReceiptRefusal(f"expected-{label}-malformed", str(expected))
        if present != expected:
            raise ReceiptRefusal(f"{label}-identity", f"receipt {present} != expected {expected}")
    if expected_plugin is not None:
        if not _valid_hex(expected_plugin):
            raise ReceiptRefusal("expected-plugin-malformed", expected_plugin)
        if ids.get("plugin_sha256") != expected_plugin:
            raise ReceiptRefusal("plugin-identity", f"receipt {ids.get('plugin_sha256')} != expected {expected_plugin}")

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
        cproc = subprocess.run([chk_real, cert_path], capture_output=True,
                               text=True, timeout=3600)
        if cproc.returncode != 0 or cproc.stdout.strip() != "ACCEPT":
            raise ReceiptRefusal("checker-rejected-on-rerun",
                                 (cproc.stderr.strip() or cproc.stdout.strip())[:200])
        chk_post = _sha256_file(chk_real)
        if chk_post != chk_pre:
            raise ReceiptRefusal("checker-toctou", "checker binary changed during rerun")

    # R9 — expression operators must be a subset of the admitted fragment.
    frag = receipt.get("fragment", {})
    admitted = set(frag.get("admitted_operators") or [])
    expr_ops = set(frag.get("expression_operators") or [])
    if not expr_ops:
        raise ReceiptRefusal("no-expression-operators", "")
    stray = sorted(expr_ops - admitted)
    if stray:
        raise ReceiptRefusal("operator-outside-fragment", str(stray))
    # Re-derive from the cert sexp to catch a receipt whose declared
    # operators disagree with the certificate it embeds.
    rederived = _operators_in_sexp(hdr.get("expr", ""))
    if rederived != expr_ops:
        raise ReceiptRefusal("operators-vs-certificate", f"receipt {sorted(expr_ops)} != cert-derived {sorted(rederived)}")

    # R9 (cont.) — coverage inventory theorem-id, if supplied
    if inventory_path is not None:
        doc = json.loads(Path(inventory_path).read_text())
        rows = {r["operator"]: r for r in doc.get("rows", [])}
        for op in sorted(expr_ops):
            row = rows.get(op)
            if row is None:
                raise ReceiptRefusal("coverage-row-missing", op)
            if row.get("verdict") != "FORMAL":
                raise ReceiptRefusal("coverage-row-not-formal", op)
            if row.get("soundness_theorem") != THEOREM_ID:
                raise ReceiptRefusal("coverage-row-theorem-mismatch", f"{op}:{row.get('soundness_theorem')}")

    # Result-status must be exactly formal-bounded (no silent downgrade).
    res = receipt.get("result", {})
    if res.get("status") != "formal-bounded":
        raise ReceiptRefusal("result-status", str(res.get("status")))
    if not isinstance(res.get("enclosure_lo"), str) or not isinstance(res.get("enclosure_hi"), str):
        raise ReceiptRefusal("result-enclosure-format", "")
    if hdr.get("output_lo" if "output_lo" in hdr else "output") is None:
        pass  # engine writes `output <lo> <hi>` on one line, parsed as a single field
    # Cross-check the enclosure against the certificate header (the cert
    # writes `output <lo> <hi>` as one string; split and normalize).
    cert_out = hdr.get("output", "")
    if not cert_out or " " not in cert_out:
        raise ReceiptRefusal("cert-output-format", cert_out)
    ce_lo, ce_hi = cert_out.split(" ", 1)
    if _canonical_rat(ce_lo) != _canonical_rat(res["enclosure_lo"]):
        raise ReceiptRefusal("enclosure-lo-mismatch", f"cert {_canonical_rat(ce_lo)} != receipt {_canonical_rat(res['enclosure_lo'])}")
    if _canonical_rat(ce_hi) != _canonical_rat(res["enclosure_hi"]):
        raise ReceiptRefusal("enclosure-hi-mismatch", f"cert {_canonical_rat(ce_hi)} != receipt {_canonical_rat(res['enclosure_hi'])}")

    return {
        "verdict": "ACCEPT",
        "receipt_digest_sha256": recomputed_digest,
        "certificate_sha256": computed,
        "checker_sha256": chk_pre,
        "evaluator_sha256": ids["evaluator_sha256"],
        "plugin_sha256": ids.get("plugin_sha256"),
        "request_commitment": recomputed,
        "expression_operators": sorted(expr_ops),
        "enclosure": [res["enclosure_lo"], res["enclosure_hi"]],
    }


def _cli() -> int:
    ap = argparse.ArgumentParser(description="JACKAL formal-receipt independent verifier")
    ap.add_argument("--receipt", required=True, help="path to a formal-bounded receipt JSON")
    ap.add_argument("--checker", required=True, help="pinned jackal_cert_check executable")
    ap.add_argument("--expected-evaluator", required=True, help="pinned evaluator SHA-256")
    ap.add_argument("--expected-checker", required=True, help="pinned checker SHA-256")
    ap.add_argument("--inventory", default=None,
                    help="optional coverage inventory to cross-check theorem row IDs")
    ap.add_argument("--expected-plugin", default=None,
                    help="optional plugin binary SHA-256 to bind (Hermes plugin path)")
    args = ap.parse_args()
    try:
        receipt = json.loads(Path(args.receipt).read_text())
    except Exception as e:  # noqa: BLE001
        print(f"status=refused reason=receipt-unreadable detail=\"{e}\"", file=sys.stderr)
        return 1
    try:
        r = verify_receipt(receipt=receipt, checker=args.checker,
                           expected_evaluator=args.expected_evaluator,
                           expected_checker=args.expected_checker,
                           inventory_path=Path(args.inventory) if args.inventory else None,
                           expected_plugin=args.expected_plugin)
    except ReceiptRefusal as r:  # noqa: F841
        # shadowed on purpose — the exception carries the class/detail we print
        exc = sys.exc_info()[1]
        print(f"status=refused reason={exc.cls} detail=\"{exc.detail}\"", file=sys.stderr)
        return 1
    print(f"status=verified verdict={r['verdict']}")
    print(f"receipt.digest={r['receipt_digest_sha256']}")
    print(f"certificate.sha256={r['certificate_sha256']}")
    print(f"checker.sha256={r['checker_sha256']}")
    print(f"evaluator.sha256={r['evaluator_sha256']}")
    if r.get("plugin_sha256"):
        print(f"plugin.sha256={r['plugin_sha256']}")
    print(f"expression.operators={','.join(r['expression_operators'])}")
    print(f"enclosure=[{r['enclosure'][0]},{r['enclosure'][1]}]")
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
