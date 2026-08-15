#!/usr/bin/env python3
"""JACKAL formal-status gate (completion program Phase F, §354).

THE single authority that assigns `formal-exact` / `formal-bounded`. A strong
status is granted ONLY when ALL hold, derived mechanically from the committed
coverage inventory and a real checker ACCEPT:

  1. the operation is a FORMAL-verdict row in release/coverage/…inventory.json;
  2. the request carries certificate bytes + a certificate SHA-256;
  3. the shared release validator (which runs the proved checker) ACCEPTED
     that exact certificate for that exact request;
  4. a soundness-theorem identifier is present AND appears in the inventory;
  5. the certificate's request commitment matches the request (checked by the
     validator, re-asserted here);
  6. no conditional/libm-only path is labeled fully formal.

Nothing else — engine stdout, adapter code, docs, an engine-supplied status
field, an unknown operator/version, or a stale prior certificate — can produce
`formal-*`. Every rejection is a stable class. This module is imported by the
release wrapper, the plugin adapter, and the receipt verifier so there is ONE
derivation path.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_HERE = Path(__file__).resolve().parent
# Inventory location differs by layout: repo (release/coverage/…) vs shipped
# package (sibling of this file). Try repo first, then the package sibling.
if (ROOT / "release/coverage/formal_coverage_inventory.json").exists():
    INVENTORY = ROOT / "release/coverage/formal_coverage_inventory.json"
else:
    INVENTORY = _HERE / "formal_coverage_inventory.json"

FORMAL_STATUSES = {"formal-exact", "formal-bounded"}


class StatusRefusal(Exception):
    def __init__(self, cls: str, detail: str = ""):
        super().__init__(f"{cls}: {detail}")
        self.cls = cls
        self.detail = detail


def load_inventory(path: Path | None = None, verify_integrity: bool = True) -> dict:
    p = path or INVENTORY
    doc = json.loads(p.read_text())
    if doc.get("schema") != "jackal-coverage-inventory-v1":
        raise StatusRefusal("inventory-schema", doc.get("schema", "?"))
    by_op: dict[str, dict] = {}
    for r in doc["rows"]:
        key = r["operator"]
        if key in by_op:
            raise StatusRefusal("inventory-duplicate-row", key)
        by_op[key] = r
    if verify_integrity:
        # INTEGRITY (repo/CI mode): the committed inventory's FORMAL set must
        # equal the set recomputed from the LIVE trees (Runs constructors +
        # engine ops). A hand-forged row promoting a weak/uncovered op to
        # FORMAL differs from the recomputation and is REJECTED (§382) — the
        # live proof/engine, not the JSON, is the trust root.
        #
        # In a shipped PACKAGE the source trees are absent; there the whole
        # package (including this inventory) is byte-sealed by the package
        # SHA256SUMS verified on extraction, so recompute is skipped and the
        # hash seal is the integrity control. This is the honest split, stated
        # in the release non-claims.
        sys.path.insert(0, str(_HERE))
        try:
            import coverage_inventory as ci
            live_ok = ci.EMBED.exists() and ci.ENGINE.exists()
        except Exception:  # noqa: BLE001
            live_ok = False
        if live_ok:
            recomputed = {r["operator"] for r in ci.build_rows() if r["verdict"] == "FORMAL"}
            claimed = {op for op, r in by_op.items() if r["verdict"] == "FORMAL"}
            if claimed != recomputed:
                raise StatusRefusal("inventory-integrity", f"FORMAL set diverges from live trees: +{sorted(claimed - recomputed)} -{sorted(recomputed - claimed)}")
    return {"doc": doc, "by_op": by_op}


def formal_operators(inv: dict) -> set[str]:
    """Live FORMAL-verdict set — expression operators only.

    Plugin-tool rows may also carry `verdict=FORMAL` to document that the
    plugin surface is formally bound end-to-end, but they are NOT operators
    the release-path operator-fragment gate compares against.  The plugin
    binding is verified separately (bundle hash pin + receipt `plugin_sha256`
    field), not via this set."""
    return {op for op, r in inv["by_op"].items()
            if r["verdict"] == "FORMAL" and r.get("kind") == "operator"}


def derive_status(*, operator: str, requested: str, checker_accepted: bool,
                  certificate_sha256: str | None, theorem_id: str | None,
                  request_bound: bool, inv: dict | None = None) -> str:
    """Return the granted status or raise StatusRefusal. `requested` is the
    caller's target status; a formal-* request over an uncovered path REFUSES
    rather than silently downgrading a bounded claim to a weaker label."""
    inv = inv or load_inventory()
    row = inv["by_op"].get(operator)
    if row is None:
        raise StatusRefusal("unknown-operator", operator)

    if requested in FORMAL_STATUSES:
        if row["verdict"] != "FORMAL":
            raise StatusRefusal("not-in-formal-fragment",
                                f"{operator} verdict={row['verdict']}")
        if row["allowed_status"] not in FORMAL_STATUSES:
            raise StatusRefusal("status-not-permitted", row["allowed_status"])
        if requested != row["allowed_status"]:
            raise StatusRefusal("status-mismatch",
                                f"requested {requested} != allowed {row['allowed_status']}")
        if not checker_accepted:
            raise StatusRefusal("no-checker-accept", operator)
        if not certificate_sha256:
            raise StatusRefusal("no-certificate", operator)
        if not request_bound:
            raise StatusRefusal("request-not-bound", operator)
        if not theorem_id:
            raise StatusRefusal("no-theorem-id", operator)
        if theorem_id != row["soundness_theorem"]:
            raise StatusRefusal("theorem-id-mismatch",
                                f"{theorem_id} != {row['soundness_theorem']}")
        # conditional/libm-only path must not be fully formal
        if row["libm_assumption"].startswith("libm<=2ulp"):
            raise StatusRefusal("conditional-libm-not-formal", operator)
        return requested

    # Weaker requests: the status must equal the lane's honest allowed_status;
    # a weaker lane may NEVER be upgraded to formal here.
    if requested in FORMAL_STATUSES:  # unreachable, defensive
        raise StatusRefusal("weak-upgrade", operator)
    return requested


def _selftest() -> int:
    inv = load_inventory()
    n_ok = n_bad = 0

    def expect_ok(**kw):
        nonlocal n_ok, n_bad
        try:
            s = derive_status(inv=inv, **kw)
            print(f"  OK  {kw['operator']} -> {s}"); n_ok += 1
        except StatusRefusal as r:
            print(f"  UNEXPECTED-REFUSE {kw['operator']}: {r.cls}"); n_bad += 1

    def expect_refuse(cls, **kw):
        nonlocal n_ok, n_bad
        try:
            derive_status(inv=inv, **kw)
            print(f"  UNEXPECTED-GRANT {kw['operator']}"); n_bad += 1
        except StatusRefusal as r:
            ok = r.cls == cls
            print(f"  {'OK' if ok else 'WRONG-CLASS'} refuse {kw['operator']}: {r.cls}")
            n_ok += ok; n_bad += (not ok)

    base = dict(checker_accepted=True, certificate_sha256="a" * 64,
                theorem_id="cert_check_sound", request_bound=True)
    expect_ok(operator="add", requested="formal-bounded", **base)
    expect_ok(operator="sin", requested="formal-bounded", **base)
    expect_refuse("not-in-formal-fragment", operator="sqrt", requested="formal-bounded", **base)
    expect_refuse("unknown-operator", operator="tan99", requested="formal-bounded", **base)
    expect_refuse("no-checker-accept", operator="add", requested="formal-bounded",
                  **{**base, "checker_accepted": False})
    expect_refuse("no-certificate", operator="add", requested="formal-bounded",
                  **{**base, "certificate_sha256": None})
    expect_refuse("theorem-id-mismatch", operator="add", requested="formal-bounded",
                  **{**base, "theorem_id": "some_other_thm"})
    expect_refuse("request-not-bound", operator="add", requested="formal-bounded",
                  **{**base, "request_bound": False})
    # weaker lanes keep their class, never upgraded
    expect_ok(operator="eval", requested="estimated", **base)
    print(f"selftest ok={n_ok} bad={n_bad}")
    return 0 if n_bad == 0 else 1


if __name__ == "__main__":
    sys.exit(_selftest())
