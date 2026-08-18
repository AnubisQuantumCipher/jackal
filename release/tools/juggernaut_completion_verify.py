#!/usr/bin/env python3
"""JUGGERNAUT completion verifier (W11) — fail-closed.

Emits ``JUGGERNAUT_COMPLETION=PASS`` on exit 0 ONLY when every required
workstream row in the completion record is ``status=VERIFIED`` AND every
declared artifact exists on disk (and hash-matches when a sha256 is given),
AND there are zero open P0s.  Anything else — a missing/OPEN/BLOCKED/
EXTERNAL/SIGNOFF_REQUIRED row, a VERIFIED row without a present artifact, an
open P0, a malformed record, or a required id absent from the record —
prints ``JUGGERNAUT_COMPLETION=INCOMPLETE`` on exit 1 with the exact
reasons.

The required-id set is hard-coded here, NOT read from the record, so the
record cannot fake completion by dropping a row.  A VERIFIED claim is only
honoured when its artifact is physically present (and hash-verified), so the
record cannot fake completion by asserting a status without evidence.

Usage:  python3 release/tools/juggernaut_completion_verify.py [record.json]
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RECORD = ROOT / "release/evidence/juggernaut_completion_v1.json"
SCHEMA = "jackal-juggernaut-completion-v1"
ACCEPT = {"VERIFIED"}

# Mission Stage 6 + W2-W11: every id below MUST be VERIFIED-with-artifact.
REQUIRED = (
    "stage3_chronology_merged",
    "w2_capability_manifest",
    "w3_profiles_eval",
    "w4_domain_pack_protocol",
    "w5_navier_pack",
    "w6_stem_prog_decision_packs",
    "w7_native_mac_app",
    "w8_enterprise_plane",
    "w9_website",
    "w10_conformance_eval",
    "navier_v180_released_readback",
    "vm_seal_or_declared_external",
    "two_clean_builds_adhoc_ok",
)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(argv: list[str]) -> int:
    record_path = Path(argv[1]) if len(argv) > 1 else DEFAULT_RECORD
    fails: list[str] = []

    if not record_path.exists():
        print(f"JUGGERNAUT_COMPLETION=INCOMPLETE  reason=record-missing:{record_path}")
        return 1
    try:
        doc = json.loads(record_path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - report any parse failure verbatim
        print(f"JUGGERNAUT_COMPLETION=INCOMPLETE  reason=record-malformed:{exc}")
        return 1

    if not isinstance(doc, dict) or doc.get("schema") != SCHEMA:
        print(f"JUGGERNAUT_COMPLETION=INCOMPLETE  reason=bad-schema:{doc.get('schema') if isinstance(doc, dict) else type(doc).__name__}")
        return 1

    rows = {r.get("id"): r for r in doc.get("rows", []) if isinstance(r, dict)}

    for open_p0 in doc.get("open_p0", []) or []:
        fails.append(f"open-P0: {open_p0}")

    for rid in REQUIRED:
        row = rows.get(rid)
        if row is None:
            fails.append(f"{rid}: MISSING from record")
            continue
        status = row.get("status")
        if status not in ACCEPT:
            fails.append(f"{rid}: status={status!r} (require VERIFIED)")
            continue
        artifacts = row.get("artifacts") or []
        if not artifacts:
            fails.append(f"{rid}: VERIFIED but declares no artifact")
            continue
        for art in artifacts:
            raw = art.get("path", "")
            ap = Path(raw) if Path(raw).is_absolute() else (ROOT / raw)
            if not ap.exists():
                fails.append(f"{rid}: artifact missing: {raw}")
                continue
            want = art.get("sha256")
            if want and sha256_file(ap) != want:
                fails.append(f"{rid}: artifact sha256 mismatch: {raw}")

    if fails:
        print(f"JUGGERNAUT_COMPLETION=INCOMPLETE  required={len(REQUIRED)} failures={len(fails)}")
        for f in fails:
            print(f"  - {f}")
        return 1

    print(f"JUGGERNAUT_COMPLETION=PASS  required={len(REQUIRED)} all VERIFIED with present artifacts")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
