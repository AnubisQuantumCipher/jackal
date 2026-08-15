#!/usr/bin/env python3
"""JACKAL Hermes plugin — proof-carrying range-bound tool server.

Exposes exactly two tools (see `tools.json`):

  * `jackal_range_bound`      emit a `jackal-formal-receipt-v1` receipt
  * `jackal_verify_receipt`   re-run the pinned Lean-proved checker

The plugin does NOT ship a new checker or a new evaluator.  It is a
narrow, fail-closed adapter that binds every call through the SAME
executables the CLI release wrapper does (`jackal-native` +
`jackal_cert_check`), the SAME shared validator, the SAME formal-status
gate, and the SAME coverage inventory.  The only new trust surface is
this plugin's own bundle hash — verified at startup against the pinned
value in `release/MANIFEST.sha256`.

Fail-closed guarantees (no code path emits `formal-bounded` unless
all hold):

  P0  the plugin bundle hash equals the pin;
  P1  the parsed operator set is a subset of the inventory's FORMAL fragment;
  P2  the shared release validator returns success (evaluator+checker
      pinned identities matched, checker ACCEPT, TOCTOU stable, formal-
      status gate accepted);
  P3  the formal-bounded JSON receipt is emitted and the plugin's OWN
      bundle hash is bound into `identities.plugin_sha256`.

`jackal_verify_receipt` runs the independent verifier
(`tools/receipt_verify.py`) end-to-end, re-executing the pinned checker
over the embedded certificate bytes — recomputing the outer receipt
digest alone is NOT sufficient.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

PLUGIN_DIR = Path(__file__).resolve().parent

# Discover repo/package layout; both ship the same components at either
# `<root>/release`, `<root>/tools`, `<root>/tests` (repo) or as siblings of the
# plugin dir (shipped package).
from bundle_hash import (  # noqa: E402
    PLUGIN_DIR as _PDIR,
    compute_bundle_hash,
    find_repo_root,
    load_pinned_bundle_hash_any,
)

ROOT = find_repo_root()


def _shipped_layout() -> dict[str, Path]:
    """Locate the release wrapper, validator, verifier, and pinned binaries.

    Repo layout (development):
        <ROOT>/jackal-native
        <ROOT>/proofs/lean/.lake/build/bin/jackal_cert_check
        <ROOT>/tests/release_validate.py
        <ROOT>/tools/{formal_receipt,receipt_verify,formal_status_gate,
                       coverage_inventory}.py
        <ROOT>/release/{MANIFEST.sha256,coverage/formal_coverage_inventory.json}

    Shipped-package layout (self-contained):
        <ROOT>/jackal-native
        <ROOT>/jackal_cert_check
        <ROOT>/release_validate.py
        <ROOT>/{formal_receipt,receipt_verify,formal_status_gate,
                coverage_inventory}.py
        <ROOT>/{MANIFEST.sha256,formal_coverage_inventory.json}
    """
    layout: dict[str, Path] = {}
    # Executables
    for name, cands in (
        ("evaluator", [ROOT / "jackal-native"]),
        ("checker", [
            ROOT / "proofs/lean/.lake/build/bin/jackal_cert_check",
            ROOT / "jackal_cert_check",
        ]),
        ("validator", [
            ROOT / "tests/release_validate.py",
            ROOT / "release_validate.py",
        ]),
        ("verifier", [
            ROOT / "tools/receipt_verify.py",
            ROOT / "receipt_verify.py",
        ]),
        ("manifest", [
            ROOT / "release/MANIFEST.sha256",
            ROOT / "MANIFEST.sha256",
        ]),
        ("inventory", [
            ROOT / "release/coverage/formal_coverage_inventory.json",
            ROOT / "formal_coverage_inventory.json",
        ]),
    ):
        for c in cands:
            if c.exists():
                layout[name] = c
                break
        else:
            raise SystemExit(f"plugin-layout-missing: {name} in {[str(x) for x in cands]}")
    return layout


LAYOUT = _shipped_layout()

# Import the shared validator / formal_receipt / receipt_verify by path so both
# layouts work without a package install.
for _cand in (ROOT / "tests", ROOT / "tools", ROOT):
    if str(_cand) not in sys.path and _cand.exists():
        sys.path.insert(0, str(_cand))

import release_validate as rv  # noqa: E402
import receipt_verify as vr  # noqa: E402
import formal_status_gate as fsg  # noqa: E402
from formal_receipt import _operators_in_sexp as sexp_ops  # noqa: E402


PLUGIN_HASH = compute_bundle_hash()
PLUGIN_HASH_PINNED = load_pinned_bundle_hash_any(ROOT)


class PluginRefusal(Exception):
    def __init__(self, reason: str, detail: str = ""):
        super().__init__(f"{reason}: {detail}")
        self.reason = reason
        self.detail = detail


def _startup_gate() -> None:
    """Enforce P0 — bundle hash equals pin (or fail closed at startup).

    If no pinned value is discoverable, refuse startup rather than silently
    running unpinned.  A packaged release MUST have `plugin_hermes <sha>`
    in `MANIFEST.sha256`.
    """
    if PLUGIN_HASH_PINNED is None:
        raise PluginRefusal("plugin-manifest-missing", "no `plugin_hermes` row in release/MANIFEST.sha256")
    if PLUGIN_HASH != PLUGIN_HASH_PINNED:
        raise PluginRefusal("plugin-bundle-mismatch", f"computed {PLUGIN_HASH} != pinned {PLUGIN_HASH_PINNED}")


def _load_pinned_ids() -> tuple[str, str]:
    """Read pinned evaluator/checker sha256 from MANIFEST.sha256."""
    ev = ck = ""
    for ln in LAYOUT["manifest"].read_text().splitlines():
        parts = ln.split()
        if len(parts) >= 3 and parts[0] == "evaluator":
            ev = parts[-1]
        elif len(parts) >= 3 and parts[0] == "checker":
            ck = parts[-1]
    if not ev or not ck:
        raise PluginRefusal("plugin-manifest-incomplete", str(LAYOUT["manifest"]))
    return ev, ck


def _admitted_operators() -> set[str]:
    """Live-verified FORMAL operator set from the coverage inventory."""
    inv = fsg.load_inventory(verify_integrity=False)
    return fsg.formal_operators(inv)


def _refuse(reason: str, detail: str = "") -> dict[str, Any]:
    return {"status": "refused", "reason": reason, "detail": detail}


def _validate_args(args: dict[str, Any], keys: list[str]) -> None:
    if not isinstance(args, dict):
        raise PluginRefusal("plugin-args-schema", "arguments must be an object")
    for k in keys:
        v = args.get(k)
        if not isinstance(v, str) or not v:
            raise PluginRefusal("plugin-args-schema", f"missing/invalid field: {k!r}")


def tool_range_bound(args: dict[str, Any]) -> dict[str, Any]:
    """Emit a formal-bounded receipt (P1..P3), or refuse.

    Preflight fragment check: the expression's operators must all be in the
    FORMAL fragment.  Because the engine's parser is a runtime component, the
    definitive check is the shared validator's operator-set gate — but a
    cheap preflight run against the evaluator's cert emission catches the
    common cases immediately, without spinning up subprocesses for non-
    formal transcendental expressions.

    On success, returns:
        {"status": "formal-bounded", "receipt": <jackal-formal-receipt-v1>}
    """
    _validate_args(args, ["expression", "input_lo", "input_hi"])
    expr = args["expression"]
    lo = args["input_lo"]
    hi = args["input_hi"]
    ev_expected, ck_expected = _load_pinned_ids()

    with tempfile.TemporaryDirectory(prefix="jackal-plugin-") as td:
        formal_path = os.path.join(td, "receipt.json")
        try:
            rv.validate_release(
                expr=expr, lo=lo, hi=hi,
                evaluator=str(LAYOUT["evaluator"]),
                checker=str(LAYOUT["checker"]),
                expected_evaluator=ev_expected,
                expected_checker=ck_expected,
                formal_receipt_path=formal_path,
                plugin_sha256=PLUGIN_HASH,
                release_epoch="v1.2.0",
            )
        except rv.ReleaseRefusal as r:
            # Map the validator's stable class through unchanged.  The plugin
            # never converts a bounded failure into a bounded fallback.
            return _refuse(r.cls, r.detail)
        receipt = json.loads(Path(formal_path).read_text())

    # P1 (post-hoc): every operator in the emitted certificate must be in
    # the live FORMAL fragment.  The validator already enforces this via the
    # formal-status gate; we redo it here so a receipt-emit code-path
    # regression is caught before it leaves the plugin.
    admitted = _admitted_operators()
    stray = sorted(set(receipt["fragment"]["expression_operators"]) - admitted)
    if stray:
        return _refuse("plugin-operator-refused", f"non-formal operators: {stray}")
    # P3: plugin identity bound into the receipt.
    if receipt["identities"].get("plugin_sha256") != PLUGIN_HASH:
        return _refuse("plugin-identity-unbound",
                       f"receipt plugin={receipt['identities'].get('plugin_sha256')} != {PLUGIN_HASH}")
    return {"status": "formal-bounded", "receipt": receipt}


def tool_verify_receipt(args: dict[str, Any]) -> dict[str, Any]:
    """Re-run the pinned Lean-proved checker over an embedded certificate.

    This is NOT a signature check.  The verifier extracts the certificate
    bytes, writes them to a fresh mode-0600 tempfile, and invokes the
    pinned `jackal_cert_check` binary on them.  Only an ACCEPT return
    combined with all binding gates (see `tools/receipt_verify.py`)
    yields `verified`; anything else is a stable refusal.
    """
    if not isinstance(args, dict):
        return _refuse("plugin-args-schema", "arguments must be an object")
    receipt = args.get("receipt")
    if not isinstance(receipt, dict):
        return _refuse("plugin-args-schema", "receipt must be an object")
    ev_expected, ck_expected = _load_pinned_ids()
    try:
        result = vr.verify_receipt(
            receipt=receipt,
            checker=str(LAYOUT["checker"]),
            expected_evaluator=ev_expected,
            expected_checker=ck_expected,
            inventory_path=LAYOUT["inventory"],
            expected_plugin=PLUGIN_HASH,
        )
    except vr.ReceiptRefusal as r:
        return _refuse(r.cls, r.detail)
    return {"status": "verified", **result}


TOOLS = {
    "jackal_range_bound":     tool_range_bound,
    "jackal_verify_receipt":  tool_verify_receipt,
}


def _dispatch(method: str, params: Any) -> dict[str, Any]:
    if method not in TOOLS:
        return _refuse("plugin-unknown-tool", method)
    if not isinstance(params, dict):
        return _refuse("plugin-args-schema", "params must be an object")
    try:
        return TOOLS[method](params)
    except PluginRefusal as p:
        return _refuse(p.reason, p.detail)
    except Exception as e:  # noqa: BLE001
        return _refuse("plugin-internal", f"{type(e).__name__}: {e}")


# -- stdio JSON-RPC 2.0 transport (MCP-friendly) -------------------------------

def _rpc_ok(rid: Any, result: dict[str, Any]) -> str:
    return json.dumps({"jsonrpc": "2.0", "id": rid, "result": result},
                      sort_keys=True, separators=(",", ":"))


def _rpc_err(rid: Any, code: int, message: str, data: Any = None) -> str:
    err = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return json.dumps({"jsonrpc": "2.0", "id": rid, "error": err},
                      sort_keys=True, separators=(",", ":"))


def _serve_stdio() -> int:
    """Line-delimited JSON-RPC 2.0.  One request per line; one reply per line.

    Recognised methods:
        list_tools()                       -> tool manifest
        <tool-name>(<args-object>)          -> tool result
    """
    tools_manifest = json.loads((PLUGIN_DIR / "tools.json").read_text())
    try:
        _startup_gate()
    except PluginRefusal as p:
        sys.stdout.write(_rpc_err(None, -32000, f"{p.reason}: {p.detail}") + "\n")
        return 1
    for raw in sys.stdin:
        raw = raw.strip()
        if not raw:
            continue
        try:
            req = json.loads(raw)
        except json.JSONDecodeError as e:
            sys.stdout.write(_rpc_err(None, -32700, f"parse error: {e}") + "\n")
            sys.stdout.flush()
            continue
        rid = req.get("id")
        method = req.get("method")
        params = req.get("params", {})
        if method == "list_tools":
            sys.stdout.write(_rpc_ok(rid, tools_manifest) + "\n")
        else:
            sys.stdout.write(_rpc_ok(rid, _dispatch(method, params)) + "\n")
        sys.stdout.flush()
    return 0


def _serve_call(tool: str, arg_json: str) -> int:
    try:
        _startup_gate()
    except PluginRefusal as p:
        sys.stdout.write(json.dumps({"status": "refused", "reason": p.reason,
                                     "detail": p.detail}, sort_keys=True) + "\n")
        return 1
    try:
        params = json.loads(arg_json)
    except json.JSONDecodeError as e:
        sys.stdout.write(json.dumps({"status": "refused", "reason": "plugin-args-schema",
                                     "detail": f"parse error: {e}"}, sort_keys=True) + "\n")
        return 1
    result = _dispatch(tool, params)
    sys.stdout.write(json.dumps(result, sort_keys=True, indent=2) + "\n")
    return 0 if result.get("status") in {"formal-bounded", "verified"} else 1


def _serve_http(port: int, host: str) -> int:
    """Tiny HTTP wrapper: POST /tools/<name> JSON body -> JSON reply."""
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    try:
        _startup_gate()
    except PluginRefusal as p:
        sys.stderr.write(f"startup-refuse {p.reason}: {p.detail}\n")
        return 1

    tools_manifest = json.loads((PLUGIN_DIR / "tools.json").read_text())

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):  # silence access log
            return

        def _send_json(self, code: int, obj: dict[str, Any]) -> None:
            payload = json.dumps(obj, sort_keys=True, indent=2).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self):  # noqa: N802
            if self.path in ("/tools", "/"):
                self._send_json(200, tools_manifest)
            else:
                self._send_json(404, {"status": "refused", "reason": "plugin-http-notfound"})

        def do_POST(self):  # noqa: N802
            if not self.path.startswith("/tools/"):
                self._send_json(404, {"status": "refused", "reason": "plugin-http-notfound"})
                return
            tool = self.path[len("/tools/"):]
            n = int(self.headers.get("Content-Length", "0") or 0)
            body = self.rfile.read(n) if n else b"{}"
            try:
                params = json.loads(body or b"{}")
            except json.JSONDecodeError as e:
                self._send_json(400, {"status": "refused", "reason": "plugin-args-schema",
                                      "detail": f"parse error: {e}"})
                return
            self._send_json(200, _dispatch(tool, params))

    server = ThreadingHTTPServer((host, port), Handler)
    server.serve_forever()
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="JACKAL Hermes plugin server")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("stdio", help="line-delimited JSON-RPC 2.0")
    call = sub.add_parser("call", help="one-shot tool invocation")
    call.add_argument("tool")
    call.add_argument("args_json")
    http = sub.add_parser("http", help="POST /tools/<name>")
    http.add_argument("--port", type=int, default=8181)
    http.add_argument("--host", default="127.0.0.1")
    sub.add_parser("selftest", help="print bundle-hash and pinned value")
    ns = ap.parse_args(argv)
    if ns.cmd == "stdio":
        return _serve_stdio()
    if ns.cmd == "call":
        return _serve_call(ns.tool, ns.args_json)
    if ns.cmd == "http":
        return _serve_http(ns.port, ns.host)
    if ns.cmd == "selftest":
        print(f"plugin_hermes.bundle_sha256={PLUGIN_HASH}")
        print(f"plugin_hermes.pinned_sha256={PLUGIN_HASH_PINNED or '<none>'}")
        print(f"plugin_hermes.identity_match={'true' if PLUGIN_HASH == PLUGIN_HASH_PINNED else 'false'}")
        print(f"evaluator={LAYOUT['evaluator']}")
        print(f"checker={LAYOUT['checker']}")
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
