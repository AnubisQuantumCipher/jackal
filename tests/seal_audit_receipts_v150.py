#!/usr/bin/env python3
"""v1.5.0 seal audit — archival receipt-envelope adversarial probes.

Five probes on a FRESH v1.5.0 variant receipt beyond the 42 locks in
tests/receipt_semantic_mutations.py, each attacking the result/certificate
binding rather than a single field digest:

  R-A  baseline replay ACCEPT (control);
  R-B  enclosure_lo moved inward + outer digest recomputed  -> refuse;
  R-C  enclosure endpoints swapped + digest recomputed      -> refuse;
  R-D  enclosure_lo retyped as JSON number + digest fixed   -> refuse;
  R-E  COORDINATED tamper: certificate output token flipped
       + certificate.sha256 recomputed + result enclosure matched
       + outer digest recomputed — every hash internally consistent;
       only the Lean checker re-run can catch it              -> refuse.

This battery is a HISTORICAL replay gate: it pins the exact archival
v1.7.0 range checker (05c3518…de8a) plus the archival coverage
inventory (18ff7b1d…ba6) plus the archival range proof identity plus
``release_epoch="v1.5.0"``.  The current v1.7.2 checker/inventory/proof
tuple is intentionally NOT used here; a cross-mixed tuple is a banned
configuration (see docs/superpowers/plans/2026-08-17-jackal-gate0-
checker-contract.md, Blocker C).  For the same probes against the
current v1.7.2 tuple, see the receipt_semantic_mutations sweep and the
claim_hostile matrix.

Writes release/evidence/seal_audit_receipts_v150.json.
"""
from __future__ import annotations

import base64
import copy
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tests"))

import receipt_verify as vr  # noqa: E402
from formal_receipt import (  # noqa: E402
    build_variant_formal_receipt, canonical_rat, load_proof_identity_binding,
    recompute_receipt_digest, request_commitment_b64, sha256_hex,
    _parse_cert_header,
)

# Archival v1.7.0 checker + inventory used for the v1.5.0 receipt replay.
# Env overrides mirror the claim_hostile matrix so a foreign runtime root
# can be pinned without editing this file.
ARCHIVAL_CHECKER = Path(os.environ.get(
    "JACKAL_V170_ARCHIVAL_RANGE_CHECKER",
    str(Path.home() / "Library/Application Support/JACKAL/runtimes/v1.7.0/"
                      "jackal_cert_check")))
ARCHIVAL_INVENTORY = Path(os.environ.get(
    "JACKAL_V170_ARCHIVAL_RANGE_INVENTORY",
    str(ARCHIVAL_CHECKER.parent / "formal_coverage_inventory.json")))
CHECKER = ARCHIVAL_CHECKER
INVENTORY = ARCHIVAL_INVENTORY
PROOF_ID = ROOT / "release/evidence/range_proof_identity.json"
PRODUCER = ROOT / "tools/ln_rat_producer.py"
EVIDENCE = ROOT / "release/evidence/seal_audit_receipts_v150.json"
REQ = {"command": "range-bound-cert", "expression": "ln(x)",
       "input_lo": "2", "input_hi": "3"}
ROWS: list[dict] = []


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def fresh() -> dict:
    proc = subprocess.run(
        [sys.executable, "-I", "-S", "-B", str(PRODUCER), "emit",
         "--expression=ln(x)", "--lower=2", "--upper=3"],
        capture_output=True, check=True)
    cert = proc.stdout
    hdr = _parse_cert_header(cert)
    lo, hi = hdr["output"].split(" ", 1)
    return build_variant_formal_receipt(
        variant="ln_rat", release_epoch="v1.5.0", request=REQ,
        enclosure=(lo, hi), cert_bytes=cert, producer_sha256=sha(PRODUCER),
        checker_sha256=sha(CHECKER), canonical_lo="2", canonical_hi="3",
        request_commitment_b64=request_commitment_b64(
            REQ["command"], REQ["expression"], "2", "3"),
        coverage_inventory_sha256=sha(INVENTORY),
        proof_identity=load_proof_identity_binding(PROOF_ID),
        plugin_sha256=None)


def verify(receipt: dict):
    return vr.verify_receipt(
        receipt=receipt, checker=str(CHECKER),
        expected_evaluator=sha(PRODUCER), expected_checker=sha(CHECKER),
        expected_source=None, inventory_path=INVENTORY,
        expected_inventory_sha256=sha(INVENTORY),
        proof_identity_path=PROOF_ID,
        expected_proof_identity_file=sha(PROOF_ID),
        expected_proof_identity_digest=json.loads(PROOF_ID.read_text())["identity_digest_sha256"],
        expected_release_epoch="v1.5.0", expected_request=REQ)


def probe(rid: str, receipt: dict, expect_refusal: bool) -> None:
    try:
        out = verify(receipt)
        observed = f"ACCEPT {out.get('verdict')}"
        ok = not expect_refusal and out.get("verdict") == "ACCEPT"
    except vr.ReceiptRefusal as r:
        observed = f"refused {r.cls}"
        ok = expect_refusal
    ROWS.append({"id": rid, "ok": ok, "observed": observed})
    print(f"{'PASS' if ok else 'FAIL'} {rid}: {observed}")


def redigest(r: dict) -> dict:
    r["receipt_digest_sha256"] = recompute_receipt_digest(r)
    return r


def main() -> int:
    base = fresh()
    probe("R-A-baseline-replay", copy.deepcopy(base), expect_refusal=False)

    rb = copy.deepcopy(base)
    lo = rb["result"]["enclosure_lo"]
    n, d = (lo.split("/") + ["1"])[:2]
    rb["result"]["enclosure_lo"] = f"{int(n) + 1}/{d}" if d != "1" else str(int(n) + 1)
    probe("R-B-enclosure-inward", redigest(rb), expect_refusal=True)

    rc = copy.deepcopy(base)
    rc["result"]["enclosure_lo"], rc["result"]["enclosure_hi"] = \
        rc["result"]["enclosure_hi"], rc["result"]["enclosure_lo"]
    probe("R-C-endpoints-swapped", redigest(rc), expect_refusal=True)

    rd = copy.deepcopy(base)
    rd["result"]["enclosure_lo"] = 0.69314
    probe("R-D-type-confusion-number", redigest(rd), expect_refusal=True)

    # R-E coordinated: tamper cert bytes (widen the claimed ln upper bound in
    # BOTH the node out and the header output), recompute cert sha, match the
    # receipt result to the tampered cert, recompute the outer digest.  All
    # hashes self-consistent; only the checker re-run can refuse.
    re_ = copy.deepcopy(base)
    raw = base64.b64decode(re_["certificate"]["bytes_b64"], validate=True)
    hi = re_["result"]["enclosure_hi"]
    hn, hd = (hi.split("/") + ["1"])[:2]
    # a LOWER upper bound than ln 3 admits — semantically false claim
    forged_hi = f"{int(hn) - int(hd)}/{hd}" if hd != "1" else str(int(hn) - 1)
    if raw.count(hi.encode()) < 1:
        raise SystemExit("R-E setup: enclosure token not found in cert bytes")
    raw = raw.replace(hi.encode(), forged_hi.encode())
    re_["certificate"]["bytes_b64"] = base64.b64encode(raw).decode()
    re_["certificate"]["sha256"] = sha256_hex(raw)
    re_["result"]["enclosure_hi"] = forged_hi
    probe("R-E-coordinated-cert-tamper", redigest(re_), expect_refusal=True)

    failures = [r for r in ROWS if not r["ok"]]
    EVIDENCE.write_text(json.dumps({
        "schema": "jackal-seal-audit-receipts-v1",
        "release_epoch": "v1.5.0",
        "checker": sha(CHECKER),
        "rows": ROWS,
        "verdict": "PASS" if not failures else "FAIL",
    }, indent=2, sort_keys=True) + "\n")
    print(f"evidence={EVIDENCE}")
    print(f"SEAL_AUDIT_RECEIPTS_{'PASS' if not failures else 'FAIL'} "
          f"rows={len(ROWS)} failures={len(failures)}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
