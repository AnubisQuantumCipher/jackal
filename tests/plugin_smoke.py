#!/usr/bin/env python3
"""JACKAL v1.3.0 Hermes plugin end-to-end smoke.

Fresh-session run against the shipped `plugin/hermes/jackal_hermes`
binary and its pinned bundle hash.  Verifies:

  S1  bundle_hash.py print equals the pinned value in release/MANIFEST.
  S2  server.py selftest reports identity_match=true.
  S3  jackal_range_bound emits a formal-bounded receipt for a case in the
      declared fragment (sin/cos/pow/mul/add), plugin_sha256 pinned in.
  S4  jackal_range_bound refuses for every declared out-of-fragment op
      (exp/sqrt/ln/tan/atan/asin/acos/hypot/log10/log2/cbrt/mod/pow-neg)
      with a stable class, NEVER a bounded fallback.
  S5  jackal_verify_receipt re-runs the checker and accepts a fresh S3
      receipt (round trip).
  S6  jackal_verify_receipt refuses a receipt with `plugin_sha256`
      mutated (plugin-identity binding gate).
  S7  jackal_verify_receipt refuses a receipt with the outer digest
      recomputed but the enclosure tampered (cross-check gate).
  S8  stdio JSON-RPC transport handles list_tools + both tool calls with
      correct id/jsonrpc/result shape and drives the same refusals.

Writes an evidence transcript (JSONL) to `release/evidence/plugin_smoke.jsonl`.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugin" / "hermes" / "jackal_hermes"
MANIFEST = ROOT / "release" / "MANIFEST.sha256"
EVIDENCE = ROOT / "release" / "evidence" / "plugin_smoke.jsonl"

sys.path.insert(0, str(ROOT / "plugin" / "hermes"))
sys.path.insert(0, str(ROOT / "tools"))
from bundle_hash import compute_bundle_hash, load_pinned_bundle_hash_any  # noqa: E402
from formal_receipt import recompute_receipt_digest  # noqa: E402

RANGE_EXPR = "sin(x)+x^2"
RANGE_CONTEXT = {
    "expected_release_epoch": "v1.3.0",
    "expected_command": "range-bound-cert",
    "expected_expression": RANGE_EXPR,
    "expected_input_lo": "0",
    "expected_input_hi": "1",
}
GAUSSIAN_EXPR = "exp(-10000000000*(x-0.5000123456789)^2)"
GAUSSIAN_CONTEXT = {
    "expected_release_epoch": "v1.3.0",
    "expected_command": "integrate",
    "expected_expression": GAUSSIAN_EXPR,
    "expected_input_lo": "0",
    "expected_input_hi": "1",
    "expected_tolerance": "1/1000000000000",
}


def _sha256_str(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _run(argv: list[str], input_bytes: bytes | None = None,
         timeout: int = 3600) -> tuple[int, str, str]:
    cp = subprocess.run(argv, input=input_bytes, capture_output=True, timeout=timeout)
    return cp.returncode, cp.stdout.decode("utf-8", "replace"), cp.stderr.decode("utf-8", "replace")


def _call(tool: str, params: dict, timeout: int = 3600) -> tuple[int, dict]:
    code, out, err = _run([str(PLUGIN), "call", tool, json.dumps(params)], timeout=timeout)
    try:
        obj = json.loads(out)
    except json.JSONDecodeError:
        obj = {"status": "refused", "reason": "plugin-nonjson-stdout", "detail": (err or out)[:400]}
    return code, obj


def _stdio(requests: list[dict], timeout: int = 3600) -> list[dict]:
    payload = ("\n".join(json.dumps(r) for r in requests) + "\n").encode()
    code, out, err = _run([str(PLUGIN), "stdio"], input_bytes=payload, timeout=timeout)
    replies = []
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            replies.append(json.loads(line))
        except json.JSONDecodeError:
            replies.append({"error": "nonjson", "line": line})
    return replies


ROWS: list[dict] = []


def record(sid: str, ok: bool, note: str = "", extra: dict | None = None) -> None:
    row = {"id": sid, "ok": ok, "note": note}
    if extra:
        row.update(extra)
    ROWS.append(row)
    print(f"{sid} {'PASS' if ok else 'FAIL'} {note}")


def _pinned_bundle_hash() -> str:
    return load_pinned_bundle_hash_any(ROOT) or ""


def s1_bundle_hash() -> bool:
    computed = compute_bundle_hash()
    pinned = _pinned_bundle_hash()
    ok = computed == pinned and len(computed) == 64
    record("S1-bundle-hash-pin-matches", ok,
           f"computed={computed} pinned={pinned}")
    return ok


def s2_selftest() -> bool:
    code, out, err = _run([str(PLUGIN), "selftest"])
    ok = code == 0 and "identity_match=true" in out
    record("S2-server-selftest", ok, f"out={out.strip()}"[:200])
    return ok


def s3_formal_bounded_receipt() -> dict | None:
    code, obj = _call("jackal_range_bound",
                      {"expression": RANGE_EXPR, "input_lo": "0", "input_hi": "1"})
    ok = code == 0 and obj.get("status") == "formal-bounded"
    plugin_pin = _pinned_bundle_hash()
    plugin_bound = ok and obj["receipt"]["identities"]["plugin_sha256"] == plugin_pin
    record("S3-range-bound-emit", ok and plugin_bound,
           f"status={obj.get('status')} plugin_sha256={obj.get('receipt', {}).get('identities', {}).get('plugin_sha256', '<none>')}")
    return obj["receipt"] if ok else None


def s4_refuse_outside_fragment() -> bool:
    cases = [
        ("exp(x)", "0", "1"),
        ("sqrt(x)", "1", "2"),
        ("ln(x)", "1", "2"),
        ("tan(x)", "0", "1"),
        ("atan(x)", "0", "1"),
        ("asin(x)", "0", "1"),
        ("acos(x)", "0", "1"),
        ("hypot(x,1)", "0", "1"),
        ("log10(x)", "1", "2"),
        ("log2(x)", "1", "2"),
        ("cbrt(x)", "1", "2"),
        ("x % 2", "1", "2"),
        ("x^(-2)", "1", "2"),
    ]
    all_ok = True
    for expr, lo, hi in cases:
        code, obj = _call("jackal_range_bound",
                          {"expression": expr, "input_lo": lo, "input_hi": hi})
        refused = obj.get("status") == "refused"
        # NEVER bounded fallback
        bounded_leak = obj.get("status") == "formal-bounded"
        ok = refused and not bounded_leak and code != 0
        record(f"S4-refuse:{expr!r}", ok,
               f"status={obj.get('status')} reason={obj.get('reason', '')}")
        all_ok = all_ok and ok
    return all_ok


def s5_verify_round_trip(receipt: dict) -> bool:
    code, obj = _call("jackal_verify_receipt", {"receipt": receipt, **RANGE_CONTEXT})
    ok = code == 0 and obj.get("status") == "verified" and obj.get("verdict") == "ACCEPT"
    record("S5-verify-round-trip", ok,
           f"status={obj.get('status')} verdict={obj.get('verdict')}")
    return ok


def s6_reject_plugin_identity_swap(receipt: dict) -> bool:
    r = copy.deepcopy(receipt)
    r["identities"]["plugin_sha256"] = "0" * 64
    r["receipt_digest_sha256"] = recompute_receipt_digest(r)
    code, obj = _call("jackal_verify_receipt", {"receipt": r, **RANGE_CONTEXT})
    ok = code != 0 and obj.get("status") == "refused" and obj.get("reason") == "plugin-identity"
    record("S6-plugin-identity-swap-refuses", ok,
           f"status={obj.get('status')} reason={obj.get('reason')}")
    return ok


def s7_reject_enclosure_tamper(receipt: dict) -> bool:
    r = copy.deepcopy(receipt)
    r["result"]["enclosure_hi"] = "1000000"
    r["receipt_digest_sha256"] = recompute_receipt_digest(r)
    code, obj = _call("jackal_verify_receipt", {"receipt": r, **RANGE_CONTEXT})
    ok = code != 0 and obj.get("status") == "refused" and obj.get("reason") in {
        "enclosure-hi-mismatch", "enclosure-lo-mismatch"}
    record("S7-enclosure-tamper-refuses", ok,
           f"status={obj.get('status')} reason={obj.get('reason')}")
    return ok


def s8_stdio_transport() -> bool:
    requests = [
        {"jsonrpc": "2.0", "id": "L", "method": "list_tools"},
        {"jsonrpc": "2.0", "id": "OK", "method": "jackal_range_bound",
         "params": {"expression": "cos(x)", "input_lo": "0", "input_hi": "1"}},
        {"jsonrpc": "2.0", "id": "NO", "method": "jackal_range_bound",
         "params": {"expression": "tan(x)", "input_lo": "0", "input_hi": "1"}},
    ]
    replies = _stdio(requests)
    idx = {r.get("id"): r for r in replies}
    listed = [t.get("name") for t in (idx.get("L", {}).get("result", {}).get("tools") or [])]
    expected_tools = {
        "jackal_range_bound", "jackal_gaussian_integral", "jackal_verify_receipt",
        "jackal_exact", "jackal_evaluate", "jackal_diff", "jackal_integrate",
        "jackal_integrate_adaptive", "jackal_integrate_bound", "jackal_solve",
    }
    ok_list = set(listed) == expected_tools and len(listed) == len(expected_tools)
    ok_ok = idx.get("OK", {}).get("result", {}).get("status") == "formal-bounded"
    ok_no = idx.get("NO", {}).get("result", {}).get("status") == "refused"
    ok = ok_list and ok_ok and ok_no
    record("S8-stdio-transport", ok,
           f"list={ok_list} ok={ok_ok} refuse={ok_no}")
    return ok


def s9_gaussian_emit_and_reverify() -> dict | None:
    request = {
        "expression": GAUSSIAN_EXPR,
        "input_lo": "0",
        "input_hi": "1",
        "tolerance": "1/1000000000000",
    }
    code, obj = _call("jackal_gaussian_integral", request)
    emitted = (code == 0 and obj.get("status") == "formal-bounded"
               and obj.get("checker_rerun") == "ACCEPT")
    receipt = obj.get("receipt") if emitted else None
    if not isinstance(receipt, dict):
        record("S9-gaussian-emit-rerun", False, f"status={obj.get('status')}")
        return None
    verify_code, verified = _call(
        "jackal_verify_receipt", {"receipt": receipt, **GAUSSIAN_CONTEXT}
    )
    ok = (verify_code == 0 and verified.get("status") == "verified"
          and verified.get("verdict") == "ACCEPT")
    record("S9-gaussian-emit-rerun", ok,
           f"emit={obj.get('checker_rerun')} verify={verified.get('status')}")
    return receipt if ok else None


def s10_gaussian_unsupported_refuses() -> bool:
    code, obj = _call("jackal_gaussian_integral", {
        "expression": "exp(x)", "input_lo": "0", "input_hi": "1",
        "tolerance": "1/1000000000000",
    })
    ok = code != 0 and obj.get("status") == "refused"
    record("S10-gaussian-unsupported-refuses", ok,
           f"status={obj.get('status')} reason={obj.get('reason')}")
    return ok


def s11_external_context_substitution_refuses(receipt: dict) -> bool:
    wrong = dict(RANGE_CONTEXT)
    wrong["expected_expression"] = "0"
    code, obj = _call("jackal_verify_receipt", {"receipt": receipt, **wrong})
    ok = (code != 0 and obj.get("status") == "refused"
          and obj.get("reason") == "expected-request-mismatch")
    record("S11-external-context-substitution-refuses", ok,
           f"status={obj.get('status')} reason={obj.get('reason')}")
    return ok


def s12_weak_lanes_honest() -> bool:
    """Every weaker-lane tool returns its inventory-derived class VERBATIM,
    reports formal=False, and NEVER prints a formal-* status."""
    cases = [
        ("jackal_exact", {"expression": "0.1+0.2"}, "exact",
         lambda d: d["fields"].get("exact") == "3/10"),
        ("jackal_evaluate", {"expression": "2+3*sin(pi/6)^2"}, "estimated",
         lambda d: d["engine_output"].strip() == "2.75"),
        ("jackal_diff", {"expression": "x^2*sin(x)"}, "checked",
         lambda d: "not-proof-of-identity" in d["fields"].get("assurance", "")),
        ("jackal_integrate",
         {"expression": "sin(x)", "input_lo": "0", "input_hi": "1", "panels": "200"},
         "estimated",
         lambda d: "estimate-not-bound" in d["fields"].get("assurance", "")),
        ("jackal_integrate_adaptive",
         {"expression": "exp(0-x^2)", "input_lo": "0", "input_hi": "1",
          "tolerance": "1e-9"},
         "estimated",
         lambda d: "refuses-when-unconverged" in d["fields"].get("assurance", "")),
        ("jackal_integrate_bound",
         {"expression": "exp(0-1000000*(x-0.1225)^2)", "input_lo": "0",
          "input_hi": "1", "tolerance": "1e-9"},
         "bounded",
         lambda d: "implementation-tested-not-mechanized" in d["fields"].get("assurance", "")),
        ("jackal_solve",
         {"expression": "x^2-2", "input_lo": "1", "input_hi": "2"},
         "estimated",
         lambda d: "estimate-not-bound" in d["fields"].get("assurance", "")),
    ]
    all_ok = True
    for tool, params, expected_status, extra_check in cases:
        code, obj = _call(tool, params)
        status = obj.get("status")
        formal_leak = isinstance(status, str) and status.startswith("formal")
        ok = (code == 0 and status == expected_status and not formal_leak
              and obj.get("formal") is False and extra_check(obj))
        record(f"S12-weak:{tool}", ok,
               f"status={status} formal={obj.get('formal')}")
        all_ok = all_ok and ok
    return all_ok


def s13_weak_lane_refusals() -> bool:
    """Weak lanes refuse with the engine's NAMED reason — never a silent 0 or
    a stronger relabel."""
    cases = [
        ("jackal_exact", {"expression": "sqrt(2)"}, "fail closed"),
        ("jackal_solve", {"expression": "x^2+1", "input_lo": "1", "input_hi": "2"},
         ""),  # no sign change — engine refuses; named reason varies
        ("jackal_integrate_bound",
         {"expression": "tan(x)", "input_lo": "0", "input_hi": "2",
          "tolerance": "1e-6"}, ""),  # pole inside → certification refusal
    ]
    all_ok = True
    for tool, params, needle in cases:
        code, obj = _call(tool, params)
        refused = obj.get("status") == "refused" and code != 0
        named = (needle in obj.get("detail", "")) if needle else bool(obj.get("reason"))
        ok = refused and named
        record(f"S13-weak-refuse:{tool}", ok,
               f"status={obj.get('status')} reason={obj.get('reason','')} "
               f"detail={obj.get('detail','')[:60]}")
        all_ok = all_ok and ok
    return all_ok


def main() -> int:
    if not PLUGIN.exists():
        print(f"plugin-not-installed: {PLUGIN}", file=sys.stderr)
        return 1
    results = []
    results.append(s1_bundle_hash())
    results.append(s2_selftest())
    receipt = s3_formal_bounded_receipt()
    results.append(receipt is not None)
    results.append(s4_refuse_outside_fragment())
    if receipt is not None:
        results.append(s5_verify_round_trip(receipt))
        results.append(s6_reject_plugin_identity_swap(receipt))
        results.append(s7_reject_enclosure_tamper(receipt))
    else:
        record("S5-verify-round-trip", False, "no receipt")
        record("S6-plugin-identity-swap-refuses", False, "no receipt")
        record("S7-enclosure-tamper-refuses", False, "no receipt")
        results.extend([False, False, False])
    results.append(s8_stdio_transport())
    gaussian_receipt = s9_gaussian_emit_and_reverify()
    results.append(gaussian_receipt is not None)
    results.append(s10_gaussian_unsupported_refuses())
    if receipt is not None:
        results.append(s11_external_context_substitution_refuses(receipt))
    else:
        record("S11-external-context-substitution-refuses", False, "no receipt")
        results.append(False)
    results.append(s12_weak_lanes_honest())
    results.append(s13_weak_lane_refusals())

    EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE.write_text("\n".join(json.dumps(r, sort_keys=True) for r in ROWS) + "\n")
    print(f"evidence={EVIDENCE} sha256={_sha256_str(EVIDENCE.read_bytes())}")
    if not all(results):
        print("VERDICT: FAIL — a plugin smoke case did not meet its gate", file=sys.stderr)
        return 1
    print("VERDICT: PASS — plugin bundle pinned, fragment enforced, verify round-tripped,"
          " tamper refused, stdio transport correct, weak lanes honest")
    return 0


if __name__ == "__main__":
    sys.exit(main())
