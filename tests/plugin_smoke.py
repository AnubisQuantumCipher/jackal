#!/usr/bin/env python3
"""JACKAL v1.7.2 Hermes plugin end-to-end smoke.

Fresh-session run against the shipped `plugin/hermes/jackal_hermes`
binary and its pinned bundle hash.  Verifies:

  S1  bundle_hash.py print equals the pinned value in release/MANIFEST.
  S2  server.py selftest reports identity_match=true.
  S3  jackal_range_bound emits a formal-bounded receipt for a case in the
      declared range-bound-cert fragment (sin/cos/pow/mul/add), with
      plugin_sha256 pinned in.
  S4  jackal_range_bound refuses for every op outside the jackal-native
      +range-bound-cert lane (ln/tan/atan/asin/acos/hypot/log10/log2/cbrt/
      mod/pow-neg), plus sqrt/exp which route through separate tools
      (see S14/S15). NEVER a bounded fallback.
  S5  jackal_verify_receipt re-runs the checker and accepts a fresh S3
      receipt (round trip).
  S6  jackal_verify_receipt refuses a receipt with `plugin_sha256`
      mutated (plugin-identity binding gate).
  S7  jackal_verify_receipt refuses a receipt with the outer digest
      recomputed but the enclosure tampered (cross-check gate).
  S8  stdio JSON-RPC transport handles list_tools + tool calls with
      correct id/jsonrpc/result shape (36 tools listed) and drives the
      same refusals.
  S9  jackal_gaussian_integral emits + reverifies a Gaussian receipt.
  S10 jackal_gaussian_integral refuses unsupported non-canonical Gaussians.
  S11 jackal_verify_receipt refuses an external-context substitution.
  S12 Weaker-lane tools return inventory-derived class VERBATIM,
      `formal: false`, and NEVER a formal-* status.
  S13 Weaker-lane tools refuse with the engine's NAMED reason.
  S14 jackal_sqrt_rat_bound accepts `sqrt(x)` on a canonical rational
      interval and returns `variant=sqrt_rat` + checker ACCEPT
      (v1.4.0 fragment extension via the pinned Python producer).
  S15 jackal_exp_rat_bound accepts `exp(x)` on `[lo, hi]` with lo >= 0
      and returns `variant=exp_rat` + checker ACCEPT
      (v1.4.1 fragment extension via the pinned Python producer).
  S16 jackal_sqrt_rat_bound / jackal_exp_rat_bound refuse non-admitted
      expressions and negative lowers fail-closed.
  S21 jackal_integrate_bound_cert emits a formal-bounded certified
      composed-integral receipt (variant int_cert, theorem int_cert_sound)
      for sin(x) on [0,1] tol 1/100, round-trips through
      jackal_verify_receipt, and refuses a semantic enclosure tamper
      (v1.7.0 composed bound_step lane).
  S22 jackal_integrate_bound_cert refuses out-of-fragment expressions
      (tan/exp/sqrt), and the weaker float lane jackal_integrate_bound
      answers the same sin(x) request with status `bounded`, never
      formal-*.

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
from formal_receipt import recompute_receipt_digest, TANH_COMPOSITE_EXPRESSION  # noqa: E402

RANGE_EXPR = "sin(x)+x^2"
RANGE_CONTEXT = {
    "expected_release_epoch": "v1.7.2",
    "expected_command": "range-bound-cert",
    "expected_expression": RANGE_EXPR,
    "expected_input_lo": "0",
    "expected_input_hi": "1",
}
GAUSSIAN_EXPR = "exp(-10000000000*(x-0.5000123456789)^2)"
GAUSSIAN_CONTEXT = {
    "expected_release_epoch": "v1.5.0",
    "expected_command": "integrate",
    "expected_expression": GAUSSIAN_EXPR,
    "expected_input_lo": "0",
    "expected_input_hi": "1",
    "expected_tolerance": "1/1000000000000",
}
INT_CERT_EXPR = "sin(x)"
INT_CERT_CONTEXT = {
    "expected_release_epoch": "v1.7.2",
    "expected_command": "integrate-bound-cert",
    "expected_expression": INT_CERT_EXPR,
    "expected_input_lo": "0",
    "expected_input_hi": "1",
    "expected_tolerance": "1/100",
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


# A stale manifest can stop dispatch at the startup/identity gates with one
# of these stable classes.  The transcript names that state, but it is a hard
# gate failure: an unexecuted case can never satisfy release acceptance.
MANIFEST_PENDING_CLASSES = {
    "plugin-manifest-missing", "plugin-bundle-mismatch", "producer-identity",
}


def _pending(obj: dict) -> bool:
    return (isinstance(obj, dict) and obj.get("status") == "refused"
            and obj.get("reason") in MANIFEST_PENDING_CLASSES)


def record_pending(sid: str, obj: dict) -> None:
    record(sid, False, f"NOT-EXECUTED-manifest-pending reason={obj.get('reason')}")


def _pinned_bundle_hash() -> str:
    return load_pinned_bundle_hash_any(ROOT) or ""


def s1_bundle_hash() -> bool:
    computed = compute_bundle_hash()
    pinned = _pinned_bundle_hash()
    if len(computed) == 64 and computed != pinned:
        record("S1-bundle-hash-pin-matches", False,
               f"NOT-EXECUTED-manifest-pending computed={computed} pinned={pinned or '<none>'}")
        return False
    ok = computed == pinned and len(computed) == 64
    record("S1-bundle-hash-pin-matches", ok,
           f"computed={computed} pinned={pinned}")
    return ok


def s2_selftest() -> bool:
    code, out, err = _run([str(PLUGIN), "selftest"])
    if code != 0 and any(f"reason={c}" in out for c in MANIFEST_PENDING_CLASSES):
        record("S2-server-selftest", False,
               f"NOT-EXECUTED-manifest-pending out={out.strip()[:120]}")
        return False
    ok = code == 0 and "identity_match=true" in out
    record("S2-server-selftest", ok, f"out={out.strip()}"[:200])
    return ok


def s3_formal_bounded_receipt() -> dict | str | None:
    code, obj = _call("jackal_range_bound",
                      {"expression": RANGE_EXPR, "input_lo": "0", "input_hi": "1"})
    if _pending(obj):
        record_pending("S3-range-bound-emit", obj)
        return "pending"
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
        if _pending(obj):
            record_pending(f"S4-refuse:{expr!r}", obj)
            continue
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
    if len(replies) == 1 and replies[0].get("id") is None:
        # stdio mode refuses at the startup gate before serving any request.
        message = str(replies[0].get("error", {}).get("message", ""))
        if any(message.startswith(f"{c}:") for c in MANIFEST_PENDING_CLASSES):
            record("S8-stdio-transport", False,
                   f"NOT-EXECUTED-manifest-pending {message[:100]}")
            return False
    idx = {r.get("id"): r for r in replies}
    listed = [t.get("name") for t in (idx.get("L", {}).get("result", {}).get("tools") or [])]
    expected_tools = {
        "jackal_range_bound", "jackal_gaussian_integral", "jackal_verify_receipt",
        "jackal_sqrt_rat_bound", "jackal_exp_rat_bound",
        "jackal_ln_rat_bound", "jackal_sin_rat_bound", "jackal_cos_rat_bound",
        "jackal_atan_rat_bound", "jackal_tanh_rat_bound",
        "jackal_exact", "jackal_evaluate", "jackal_diff", "jackal_integrate",
        "jackal_integrate_adaptive", "jackal_integrate_bound", "jackal_solve",
        "jackal_canon", "jackal_poly_canon", "jackal_poly_eq", "jackal_poly_gcd",
        "jackal_ratfunc_canon", "jackal_roots_isolate", "jackal_alg_sign",
        "jackal_alg_cmp", "jackal_xgcd", "jackal_mod_pow", "jackal_mod_inv",
        "jackal_crt", "jackal_divides", "jackal_prime_cert",
        # v1.6.0 additive claim-kernel front door (31 -> 33)
        "jackal_claim", "jackal_verify_bundle",
        # v1.7.0 certified composed-integral formal lane (33 -> 34)
        "jackal_integrate_bound_cert",
        # Direct finite-scope Navier pack; no claim-kernel routing (34 -> 36)
        "jackal_navier_stokes_check",
        "jackal_verify_navier_stokes_receipt",
    }
    ok_list = set(listed) == expected_tools and len(listed) == len(expected_tools)
    ok_ok = idx.get("OK", {}).get("result", {}).get("status") == "formal-bounded"
    ok_no = idx.get("NO", {}).get("result", {}).get("status") == "refused"
    ok = ok_list and ok_ok and ok_no
    record("S8-stdio-transport", ok,
           f"list={ok_list} ok={ok_ok} refuse={ok_no}")
    return ok


def s9_gaussian_emit_and_reverify() -> dict | str | None:
    request = {
        "expression": GAUSSIAN_EXPR,
        "input_lo": "0",
        "input_hi": "1",
        "tolerance": "1/1000000000000",
    }
    code, obj = _call("jackal_gaussian_integral", request)
    if _pending(obj):
        record_pending("S9-gaussian-emit-rerun", obj)
        return "pending"
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
    if _pending(obj):
        record_pending("S10-gaussian-unsupported-refuses", obj)
        return True
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
        if _pending(obj):
            record_pending(f"S12-weak:{tool}", obj)
            continue
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
        if _pending(obj):
            record_pending(f"S13-weak-refuse:{tool}", obj)
            continue
        refused = obj.get("status") == "refused" and code != 0
        named = (needle in obj.get("detail", "")) if needle else bool(obj.get("reason"))
        ok = refused and named
        record(f"S13-weak-refuse:{tool}", ok,
               f"status={obj.get('status')} reason={obj.get('reason','')} "
               f"detail={obj.get('detail','')[:60]}")
        all_ok = all_ok and ok
    return all_ok


def _accepts_fragment(tool: str, expr: str, lo: str, hi: str,
                       variant: str) -> tuple[bool, dict]:
    code, obj = _call(tool, {"expression": expr, "input_lo": lo, "input_hi": hi})
    receipt = obj.get("receipt") if isinstance(obj, dict) else None
    ok = (code == 0
          and obj.get("status") == "formal-bounded"
          and obj.get("variant") == variant
          and obj.get("checker_rerun") == "ACCEPT"
          and isinstance(receipt, dict)
          and receipt.get("variant") == variant
          and receipt.get("release_epoch") == "v1.7.2"
          and receipt.get("theorem", {}).get("id") == "request_bound_certified_release"
          and receipt.get("identities", {}).get("plugin_sha256") == _pinned_bundle_hash()
          and isinstance(receipt.get("identities", {}).get("producer_sha256"), str)
          and isinstance(receipt.get("identities", {}).get("checker_sha256"), str)
          and isinstance(receipt.get("certificate", {}).get("sha256"), str)
          and len(receipt.get("certificate", {}).get("sha256") or "") == 64)
    return ok, obj


def s14_sqrt_rat_bound() -> bool:
    """v1.4.0 fragment extension: pure-Q sqrt(x) emit + round-trip verify."""
    ok, obj = _accepts_fragment("jackal_sqrt_rat_bound", "sqrt(x)", "2", "3",
                                 variant="sqrt_rat")
    if _pending(obj):
        record_pending("S14-sqrt-rat-accept-and-round-trip", obj)
        return True
    receipt = obj.get("receipt") if ok else None
    encl = receipt.get("result", {}) if isinstance(receipt, dict) else {}
    round_trip_ok = False
    if ok and isinstance(receipt, dict):
        code, obj2 = _call("jackal_verify_receipt", {
            "receipt": receipt,
            "expected_release_epoch": "v1.7.2",
            "expected_command": "range-bound-cert",
            "expected_expression": "sqrt(x)",
            "expected_input_lo": "2",
            "expected_input_hi": "3",
        })
        round_trip_ok = (code == 0
                          and obj2.get("status") == "verified"
                          and obj2.get("verdict") == "ACCEPT")
    record("S14-sqrt-rat-accept-and-round-trip", ok and round_trip_ok,
           f"enclosure=[{encl.get('enclosure_lo')},{encl.get('enclosure_hi')}] round_trip={round_trip_ok}")
    return ok and round_trip_ok


def s15_exp_rat_bound() -> bool:
    """v1.4.1 fragment extension: pure-Q exp(x) emit + round-trip verify."""
    ok, obj = _accepts_fragment("jackal_exp_rat_bound", "exp(x)", "0", "1",
                                 variant="exp_rat")
    if _pending(obj):
        record_pending("S15-exp-rat-accept-and-round-trip", obj)
        return True
    receipt = obj.get("receipt") if ok else None
    expected_enclosure = (
        isinstance(receipt, dict)
        and receipt.get("result", {}).get("enclosure_lo") == "1"
        and receipt.get("result", {}).get("enclosure_hi") == "979/360"
    )
    round_trip_ok = False
    if ok and isinstance(receipt, dict) and expected_enclosure:
        code, obj2 = _call("jackal_verify_receipt", {
            "receipt": receipt,
            "expected_release_epoch": "v1.7.2",
            "expected_command": "range-bound-cert",
            "expected_expression": "exp(x)",
            "expected_input_lo": "0",
            "expected_input_hi": "1",
        })
        round_trip_ok = (code == 0
                          and obj2.get("status") == "verified"
                          and obj2.get("verdict") == "ACCEPT")
    record("S15-exp-rat-accept-and-round-trip",
           ok and expected_enclosure and round_trip_ok,
           f"enclosure=[1,979/360]={expected_enclosure} round_trip={round_trip_ok}")
    return ok and expected_enclosure and round_trip_ok

def s16_rational_bounds_refuse() -> bool:
    """sqrt_rat / exp_rat plugin tools refuse non-admitted expressions,
    negative lowers (sqrt), and malformed intervals with a stable class —
    never a bounded fallback.  exp_rat is general-sign since v1.5.0, so its
    producer-refusal probe is an inverted interval, not a negative lower."""
    cases = [
        # (tool, params, expected_reason_prefix)
        ("jackal_sqrt_rat_bound",
         {"expression": "cos(x)", "input_lo": "0", "input_hi": "1"},
         "plugin-fragment"),
        ("jackal_sqrt_rat_bound",
         {"expression": "sqrt(x)", "input_lo": "-1", "input_hi": "1"},
         "producer-refused"),
        ("jackal_exp_rat_bound",
         {"expression": "sqrt(x)", "input_lo": "0", "input_hi": "1"},
         "plugin-fragment"),
        ("jackal_exp_rat_bound",
         {"expression": "exp(x)", "input_lo": "1", "input_hi": "0"},
         "producer-refused"),
    ]
    all_ok = True
    for tool, params, expected_reason in cases:
        code, obj = _call(tool, params)
        if _pending(obj):
            record_pending(
                f"S16-refuse:{tool}:{params.get('expression')}:lo={params.get('input_lo')}",
                obj)
            continue
        refused = obj.get("status") == "refused" and code != 0
        bounded_leak = obj.get("status") == "formal-bounded"
        reason_ok = obj.get("reason") == expected_reason
        ok = refused and not bounded_leak and reason_ok
        record(f"S16-refuse:{tool}:{params.get('expression')}:lo={params.get('input_lo')}",
               ok,
               f"status={obj.get('status')} reason={obj.get('reason')}")
        all_ok = all_ok and ok
    return all_ok


def s17_ln_rat_bound() -> bool:
    """v1.5.0 fragment extension: pure-Q ln(x) emit + round-trip verify."""
    ok, obj = _accepts_fragment("jackal_ln_rat_bound", "ln(x)", "2", "3",
                                 variant="ln_rat")
    if _pending(obj):
        record_pending("S17-ln-rat-accept-and-round-trip", obj)
        return True
    receipt = obj.get("receipt") if ok else None
    encl = receipt.get("result", {}) if isinstance(receipt, dict) else {}
    round_trip_ok = False
    if ok and isinstance(receipt, dict):
        code, obj2 = _call("jackal_verify_receipt", {
            "receipt": receipt,
            "expected_release_epoch": "v1.7.2",
            "expected_command": "range-bound-cert",
            "expected_expression": "ln(x)",
            "expected_input_lo": "2",
            "expected_input_hi": "3",
        })
        round_trip_ok = (code == 0
                          and obj2.get("status") == "verified"
                          and obj2.get("verdict") == "ACCEPT")
    record("S17-ln-rat-accept-and-round-trip", ok and round_trip_ok,
           f"enclosure=[{encl.get('enclosure_lo')},{encl.get('enclosure_hi')}] round_trip={round_trip_ok}")
    return ok and round_trip_ok


def s18_tanh_rat_bound() -> bool:
    """v1.5.0 fragment extension: pure-Q tanh composite accept on [0,1].
    The receipt must bind the frozen composite defining expression, never
    the name `tanh`."""
    ok, obj = _accepts_fragment("jackal_tanh_rat_bound",
                                 TANH_COMPOSITE_EXPRESSION, "0", "1",
                                 variant="tanh_rat")
    if _pending(obj):
        record_pending("S18-tanh-rat-accept", obj)
        return True
    receipt = obj.get("receipt") if ok else None
    encl = receipt.get("result", {}) if isinstance(receipt, dict) else {}
    expr_bound = (isinstance(receipt, dict)
                  and receipt.get("request", {}).get("expression")
                  == TANH_COMPOSITE_EXPRESSION)
    record("S18-tanh-rat-accept", ok and expr_bound,
           f"enclosure=[{encl.get('enclosure_lo')},{encl.get('enclosure_hi')}] "
           f"composite-expression-bound={expr_bound}")
    return ok and expr_bound


def s19_xgcd_exact_cert() -> bool:
    """Exact CAS lane: status=exact Bezout fields plus an independently
    parseable jackal-exact-cert-v1 certificate; never formal-*."""
    code, obj = _call("jackal_xgcd", {"a": "240", "b": "46"})
    if _pending(obj):
        record_pending("S19-xgcd-exact-cert", obj)
        return True
    status = obj.get("status")
    formal_leak = isinstance(status, str) and status.startswith("formal")
    fields = obj.get("fields", {}) if isinstance(obj, dict) else {}
    cert_ok = False
    bezout_ok = False
    try:
        cert = json.loads(fields.get("exact_cert", ""))
        cert_ok = (cert.get("schema") == "jackal-exact-cert-v1"
                   and cert.get("kind") == "xgcd")
        g, u, v = int(fields["g"]), int(fields["u"]), int(fields["v"])
        bezout_ok = g == 2 and 240 * u + 46 * v == g
    except (ValueError, KeyError, TypeError):
        pass
    ok = (code == 0 and status == "exact" and not formal_leak
          and obj.get("formal") is False and cert_ok and bezout_ok)
    record("S19-xgcd-exact-cert", ok,
           f"status={status} g={fields.get('g')} cert_ok={cert_ok} bezout={bezout_ok}")
    return ok


def s20_prime_cert_composite() -> bool:
    """Exact CAS lane: 561 (a Carmichael number) yields verdict=composite
    with a divisor witness certificate; never formal-*."""
    code, obj = _call("jackal_prime_cert", {"n": "561"})
    if _pending(obj):
        record_pending("S20-prime-cert-composite", obj)
        return True
    status = obj.get("status")
    formal_leak = isinstance(status, str) and status.startswith("formal")
    fields = obj.get("fields", {}) if isinstance(obj, dict) else {}
    cert_ok = False
    try:
        cert = json.loads(fields.get("exact_cert", ""))
        divisor = int(cert.get("witness", {}).get("divisor", "0"))
        cert_ok = (cert.get("schema") == "jackal-exact-cert-v1"
                   and cert.get("kind") == "composite"
                   and divisor > 1 and 561 % divisor == 0)
    except (ValueError, KeyError, TypeError):
        pass
    ok = (code == 0 and status == "exact" and not formal_leak
          and obj.get("formal") is False
          and fields.get("verdict") == "composite" and cert_ok)
    record("S20-prime-cert-composite", ok,
           f"status={status} verdict={fields.get('verdict')} cert_ok={cert_ok}")
    return ok


def s21_int_cert_emit_and_reverify() -> bool:
    """v1.7.0 certified composed-integral lane: sin(x) on [0,1] at tol 1/100
    emits a formal-bounded `int_cert` receipt (theorem int_cert_sound),
    round-trips through jackal_verify_receipt, and a semantic enclosure
    tamper (recomputed outer digest) still refuses."""
    request = {
        "expression": INT_CERT_EXPR,
        "input_lo": "0",
        "input_hi": "1",
        "tolerance": "1/100",
    }
    code, obj = _call("jackal_integrate_bound_cert", request)
    if _pending(obj):
        record_pending("S21-int-cert-emit-rerun", obj)
        return True
    emitted = (code == 0 and obj.get("status") == "formal-bounded"
               and obj.get("checker_rerun") == "ACCEPT")
    receipt = obj.get("receipt") if emitted else None
    if not isinstance(receipt, dict):
        record("S21-int-cert-emit-rerun", False, f"status={obj.get('status')}")
        return False
    shape_ok = (receipt.get("variant") == "int_cert"
                and receipt.get("theorem", {}).get("id") == "int_cert_sound")
    verify_code, verified = _call(
        "jackal_verify_receipt", {"receipt": receipt, **INT_CERT_CONTEXT}
    )
    round_trip_ok = (verify_code == 0 and verified.get("status") == "verified"
                     and verified.get("verdict") == "ACCEPT")
    tampered = copy.deepcopy(receipt)
    tampered["result"]["enclosure_hi"] = "99999"
    tampered["receipt_digest_sha256"] = recompute_receipt_digest(tampered)
    tamper_code, tamper_obj = _call(
        "jackal_verify_receipt", {"receipt": tampered, **INT_CERT_CONTEXT}
    )
    tamper_refused = (tamper_code != 0
                      and tamper_obj.get("status") == "refused")
    ok = shape_ok and round_trip_ok and tamper_refused
    record("S21-int-cert-emit-rerun", ok,
           f"emit={obj.get('checker_rerun')} variant={receipt.get('variant')} "
           f"theorem={receipt.get('theorem', {}).get('id')} "
           f"verify={verified.get('status')} "
           f"tamper_reason={tamper_obj.get('reason')}")
    return ok


def s22_int_cert_refusals_and_weak_honesty() -> bool:
    """v1.7.0 composed-integral lane refuses out-of-fragment expressions with
    a stable class (asserted on status only; the named reason is recorded in
    the evidence row note), and the weaker float lane answers the SAME
    sin(x) request with status `bounded` — never formal-*."""
    all_ok = True
    for expr in ("tan(x)", "exp(x)", "sqrt(x)"):
        code, obj = _call("jackal_integrate_bound_cert", {
            "expression": expr, "input_lo": "0", "input_hi": "1",
            "tolerance": "1/10",
        })
        if _pending(obj):
            record_pending(f"S22-int-cert-refuse:{expr}", obj)
            continue
        refused = code != 0 and obj.get("status") == "refused"
        formal_leak = obj.get("status") == "formal-bounded"
        ok = refused and not formal_leak
        record(f"S22-int-cert-refuse:{expr}", ok,
               f"status={obj.get('status')} reason={obj.get('reason')}")
        all_ok = all_ok and ok
    code, obj = _call("jackal_integrate_bound", {
        "expression": INT_CERT_EXPR, "input_lo": "0", "input_hi": "1",
        "tolerance": "1e-2",
    })
    if _pending(obj):
        record_pending("S22-weak-lane-honest:jackal_integrate_bound", obj)
        return all_ok
    status = obj.get("status")
    formal_leak = isinstance(status, str) and status.startswith("formal")
    weak_ok = (code == 0 and status == "bounded" and not formal_leak
               and obj.get("formal") is False)
    record("S22-weak-lane-honest:jackal_integrate_bound", weak_ok,
           f"status={status} formal={obj.get('formal')}")
    return all_ok and weak_ok


def main() -> int:
    if not PLUGIN.exists():
        print(f"plugin-not-installed: {PLUGIN}", file=sys.stderr)
        return 1
    results = []
    results.append(s1_bundle_hash())
    results.append(s2_selftest())
    receipt = s3_formal_bounded_receipt()
    receipt_pending = receipt == "pending"
    results.append(receipt_pending or receipt is not None)
    results.append(s4_refuse_outside_fragment())
    if isinstance(receipt, dict):
        results.append(s5_verify_round_trip(receipt))
        results.append(s6_reject_plugin_identity_swap(receipt))
        results.append(s7_reject_enclosure_tamper(receipt))
    elif receipt_pending:
        for sid in ("S5-verify-round-trip", "S6-plugin-identity-swap-refuses",
                    "S7-enclosure-tamper-refuses"):
            record(sid, False, "NOT-EXECUTED-manifest-pending upstream-receipt-pending")
        results.extend([True, True, True])
    else:
        record("S5-verify-round-trip", False, "no receipt")
        record("S6-plugin-identity-swap-refuses", False, "no receipt")
        record("S7-enclosure-tamper-refuses", False, "no receipt")
        results.extend([False, False, False])
    results.append(s8_stdio_transport())
    gaussian_receipt = s9_gaussian_emit_and_reverify()
    results.append(gaussian_receipt == "pending"
                   or isinstance(gaussian_receipt, dict))
    results.append(s10_gaussian_unsupported_refuses())
    if isinstance(receipt, dict):
        results.append(s11_external_context_substitution_refuses(receipt))
    elif receipt_pending:
        record("S11-external-context-substitution-refuses", False,
               "NOT-EXECUTED-manifest-pending upstream-receipt-pending")
        results.append(True)
    else:
        record("S11-external-context-substitution-refuses", False, "no receipt")
        results.append(False)
    results.append(s12_weak_lanes_honest())
    results.append(s13_weak_lane_refusals())
    results.append(s14_sqrt_rat_bound())
    results.append(s15_exp_rat_bound())
    results.append(s16_rational_bounds_refuse())
    results.append(s17_ln_rat_bound())
    results.append(s18_tanh_rat_bound())
    results.append(s19_xgcd_exact_cert())
    results.append(s20_prime_cert_composite())
    results.append(s21_int_cert_emit_and_reverify())
    results.append(s22_int_cert_refusals_and_weak_honesty())

    EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE.write_text("\n".join(json.dumps(r, sort_keys=True) for r in ROWS) + "\n")
    print(f"evidence={EVIDENCE} sha256={_sha256_str(EVIDENCE.read_bytes())}")
    if not all(results) or not all(row.get("ok") is True for row in ROWS):
        print("VERDICT: FAIL — a plugin smoke case did not meet its gate", file=sys.stderr)
        return 1
    print("VERDICT: PASS — plugin bundle pinned, fragment enforced, verify round-tripped,"
          " tamper refused, stdio transport correct, weak lanes honest")
    return 0


if __name__ == "__main__":
    sys.exit(main())
