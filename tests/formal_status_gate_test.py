#!/usr/bin/env python3
"""Permanent Phase-F regression: the formal-status gate + its aggregate
inventory-integrity mutation (§382). No load-bearing assert; runnable under -O."""
import copy, json, os, sys, tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import formal_status_gate as g


def main() -> int:
    bad = 0
    if g._selftest() != 0:
        bad += 1
    # mutation: promote a weak op to FORMAL without proof coverage -> aggregate refuse
    inv = json.load(open(ROOT / "release/coverage/formal_coverage_inventory.json"))
    mut = copy.deepcopy(inv)
    for r in mut["rows"]:
        if r["operator"] == "eval":
            r["verdict"] = "FORMAL"; r["allowed_status"] = "formal-bounded"
            r["soundness_theorem"] = "cert_check_sound"
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(mut, f); p = f.name
    try:
        g.load_inventory(path=Path(p))
        print("MUTATION-ESCAPED: FAIL"); bad += 1
    except g.StatusRefusal as r:
        if r.cls == "inventory-integrity":
            print(f"mutation caught: {r.cls} (PASS)")
        else:
            print(f"mutation wrong-class: {r.cls} (FAIL)"); bad += 1
    finally:
        os.unlink(p)
    print("VERDICT:", "PASS" if bad == 0 else "FAIL")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
