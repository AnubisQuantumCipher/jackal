#!/usr/bin/env python3
"""Recompute the volatile rows of release/MANIFEST.sha256 from live bytes.

v1.7.0 mechanization of the seal-time repin (mission §9.5): every row value
is derived from the exact file bytes on disk — never hand-typed.  Frozen
rows (compiler_pin, producer pins for untouched producers) are rewritten
from bytes too, so a drifted file surfaces as a changed pin in `git diff`
rather than a stale manifest.

Usage: python3 release/tools/repin_v170.py [--check]
  --check  verify every row matches live bytes; exit 1 on any drift.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "release/MANIFEST.sha256"

HEADER = ("# JACKAL v1.7.0 pinned release identities (range schema v2 + "
          "Gaussian schema v1 + certified composed-integral int-cert lane + "
          "sqrt_rat/exp_rat/ln_rat/sin_rat/cos_rat/atan_rat/tanh_rat variants "
          "+ exact CAS lane verifier + claim kernel)")

FILE_ROWS = [
    ("evaluator", "jackal-native"),
    ("checker", "proofs/lean/.lake/build/bin/jackal_cert_check"),
    ("gaussian-producer", "tools/gaussian_certificate.py"),
    ("gaussian-checker", "proofs/lean/.lake/build/bin/jackal_gaussian_check"),
    ("range-proof-identity", "release/evidence/range_proof_identity.json"),
    ("gaussian-proof-identity", "release/evidence/gaussian_proof_identity.json"),
    ("int-cert-producer", "tools/int_cert_producer.py"),
    ("int-cert-checker", "proofs/lean/.lake/build/bin/jackal_int_cert_check"),
    ("int-cert-proof-identity", "release/evidence/int_cert_proof_identity.json"),
    ("coverage-inventory", "release/coverage/formal_coverage_inventory.json"),
    ("source", "jackal_calc.anb"),
    ("sqrt_rat_producer", "tools/sqrt_rat_producer.py"),
    ("exp_rat_producer", "tools/exp_rat_producer.py"),
    ("ln_rat_producer", "tools/ln_rat_producer.py"),
    ("sin_rat_producer", "tools/sin_rat_producer.py"),
    ("atan_rat_producer", "tools/atan_rat_producer.py"),
    ("tanh_rat_producer", "tools/tanh_rat_producer.py"),
    ("exact_verifier", "tools/exact_verify.py"),
    ("claim_kernel", "tools/claim_kernel.py"),
    ("claim_router", "tools/claim_router.py"),
    ("claim_verifier", "tools/claim_bundle_verify.py"),
    ("claim_inference_registry", "release/claim/inference_registry_v1.json"),
    ("claim_unit_registry", "release/claim/unit_registry_v1.json"),
]

# label -> (manifest display path, repo path); display differs for binaries.
DISPLAY = {
    "checker": "jackal_cert_check",
    "gaussian-checker": "jackal_gaussian_check",
    "int-cert-checker": "jackal_int_cert_check",
}

COMPILER_PIN_ROW = ("compiler_pin", "anubis-a733565f237d",
                    Path.home() / "anubis-lang/vm/pins/anubis-a733565f237d")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_rows() -> list[str]:
    rows = [HEADER]
    for label, rel in FILE_ROWS:
        display = DISPLAY.get(label, rel)
        rows.append(f"{label} {display} {sha(ROOT / rel)}")
        if label in ("range-proof-identity", "gaussian-proof-identity",
                     "int-cert-proof-identity"):
            digest = json.loads((ROOT / rel).read_text())["identity_digest_sha256"]
            rows.append(f"{label.rsplit('-', 1)[0]}-digest {digest}")
    label, display, pin_path = COMPILER_PIN_ROW
    rows.append(f"{label} {display} {sha(pin_path)}")
    bundle = subprocess.run(
        [sys.executable, "-c",
         "import sys; sys.path.insert(0, 'plugin/hermes'); "
         "from bundle_hash import compute_bundle_hash; "
         "print(compute_bundle_hash())"],
        capture_output=True, text=True, cwd=ROOT, check=True,
    ).stdout.strip()
    rows.append(f"plugin_hermes {bundle}")
    # canonical order: match the shipped manifest's historical layout
    order = ["#", "evaluator", "checker", "gaussian-producer",
             "gaussian-checker", "range-proof-identity", "range-proof-digest",
             "gaussian-proof-identity", "gaussian-proof-digest",
             "int-cert-producer", "int-cert-checker",
             "int-cert-proof-identity", "int-cert-proof-digest",
             "coverage-inventory", "source", "compiler_pin", "plugin_hermes",
             "sqrt_rat_producer", "exp_rat_producer", "ln_rat_producer",
             "sin_rat_producer", "atan_rat_producer", "tanh_rat_producer",
             "exact_verifier", "claim_kernel", "claim_router",
             "claim_verifier", "claim_inference_registry",
             "claim_unit_registry"]
    keyed = {r.split()[0] if not r.startswith("#") else "#": r for r in rows}
    missing = [k for k in order if k not in keyed]
    if missing:
        raise SystemExit(f"repin: internal row set incomplete: {missing}")
    return [keyed[k] for k in order]


def main() -> int:
    rows = build_rows()
    text = "\n".join(rows) + "\n"
    if "--check" in sys.argv[1:]:
        current = MANIFEST.read_text()
        if current != text:
            for want, have in zip(rows, current.splitlines()):
                if want != have:
                    print(f"DRIFT:\n  manifest: {have}\n  live:     {want}")
            print("REPIN_CHECK_FAIL")
            return 1
        print(f"REPIN_CHECK_PASS rows={len(rows)}")
        return 0
    MANIFEST.write_text(text)
    print(f"REPIN_WRITTEN rows={len(rows)} manifest={MANIFEST}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
