#!/usr/bin/env python3
"""End-to-end dogfood bundles for the v1.6.0 claim kernel (mission §15).

Ten mixed claim graphs, each compiled through the REAL router (repo CLI
path), each independently replayed through `tools/claim_bundle_verify.py`
under caller pins, each negative twin refused for the intended semantic
reason:

   1. exact + threshold  -> robust comparison over exact CAS parents;
   2. formal + supplied  -> ln_rat enclosure decision, provenance stays
      `supplied`;
   3. model-based physics -> exact subcalculation under an explicitly
      assumed model; root stays model-conditional;
   4. units              -> compatible exact conversion + arithmetic;
      incompatible twin refuses;
   5. uncertainty        -> repeated dependency propagates outward;
      false-independence narrowing refuses;
   6. machine integer    -> checked-overflow vs wrap produce distinct
      bound claims;
   7. legacy receipt     -> a v1.5 receipt embedded as a parent verifies
      without migration;
   8. laundering         -> valid parents + stronger child refuses;
   9. freshness/replay   -> expected nonce accepts; wrong/stale twin
      refuses;
  10. repo/plugin parity -> CLI router and Hermes plugin return the same
      canonical root hash and verdict for the same request (package
      parity is proven separately by claim_package_parity_test.py).

Writes deterministic durable evidence (pinned emitted_at, no volatile
content) to release/evidence/claim_dogfood_v160.json.

Run: python3 tests/claim_dogfood_test.py
"""
from __future__ import annotations

import base64
import copy
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import claim_kernel as ck   # noqa: E402
import formal_receipt as fr  # noqa: E402

ROUTER = ROOT / "tools/claim_router.py"
VERIFIER = ROOT / "tools/claim_bundle_verify.py"
INF_REG = ROOT / "release/claim/inference_registry_v1.json"
UNIT_REG = ROOT / "release/claim/unit_registry_v1.json"
CHECKER = ROOT / "proofs/lean/.lake/build/bin/jackal_cert_check"
INVENTORY = ROOT / "release/coverage/formal_coverage_inventory.json"
PROOF_ID = ROOT / "release/evidence/range_proof_identity.json"
EVIDENCE_OUT = ROOT / "release/evidence/claim_dogfood_v160.json"

EPOCH = "v1.6.0"
EMITTED = "1786752000"
VTIME = "1786752000"

ROWS: list[dict] = []
BUNDLES: dict[str, str] = {}


def sha_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def canon(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode()


ENV_EPOCH = sha_file(ROOT / "jackal-native")
INF_SHA = sha_file(INF_REG)
UNIT_SHA = sha_file(UNIT_REG)
CHECKER_SHA = sha_file(CHECKER)
INVENTORY_SHA = sha_file(INVENTORY)
PROOF_ID_SHA = sha_file(PROOF_ID)
PROOF_ID_DIGEST = json.loads(PROOF_ID.read_text())["identity_digest_sha256"]


def record(rid: str, ok: bool, expect: str, observed: str) -> None:
    ROWS.append({"id": rid, "ok": bool(ok), "expect": expect,
                 "observed": observed[:200]})
    print(f"{'PASS' if ok else 'FAIL'} {rid}"
          + ("" if ok else f" — expected {expect}, got {observed[:120]}"))


def route(request: dict) -> tuple[dict | None, str]:
    with tempfile.TemporaryDirectory(prefix="jackal-dogfood-") as td:
        req_path = Path(td) / "request.json"
        bundle_path = Path(td) / "bundle.json"
        req_path.write_text(json.dumps(request, sort_keys=True))
        proc = subprocess.run(
            [sys.executable, "-I", "-S", "-B", str(ROUTER), "claim",
             "--request", str(req_path), "--emit-bundle",
             str(bundle_path)],
            capture_output=True, text=True, timeout=900, cwd=ROOT)
        if proc.returncode != 0:
            return None, (proc.stdout or proc.stderr).strip()[:300]
        return json.loads(bundle_path.read_text()), proc.stdout


def verify(bundle: dict, *, root_prop=None, nonce: str | None = None,
           vtime: str = VTIME, with_legacy: bool = True,
           ) -> tuple[str, str, str]:
    with tempfile.TemporaryDirectory(prefix="jackal-dogfood-") as td:
        bundle_path = Path(td) / "bundle.json"
        prop_path = Path(td) / "root_prop.json"
        bundle_path.write_text(json.dumps(bundle, indent=1,
                                          sort_keys=True))
        if root_prop is None:
            by_id = {n["id"]: n for n in bundle["nodes"]}
            root_prop = by_id[bundle["root"]]["proposition"]
        prop_path.write_text(json.dumps(root_prop, sort_keys=True))
        argv = [sys.executable, "-I", "-S", "-B", str(VERIFIER),
                "--bundle", str(bundle_path),
                "--expected-release-epoch", EPOCH,
                "--expected-policy-sha256",
                hashlib.sha256(canon(bundle["policy"])).hexdigest(),
                "--expected-root-proposition", str(prop_path),
                "--expected-inference-registry", str(INF_REG),
                "--expected-inference-registry-sha256", INF_SHA,
                "--expected-unit-registry", str(UNIT_REG),
                "--expected-unit-registry-sha256", UNIT_SHA,
                "--expected-environment-epoch", ENV_EPOCH,
                "--verification-time-unix", vtime]
        if nonce is not None:
            argv += ["--expected-nonce", nonce]
        if with_legacy:
            argv += ["--receipt-verifier", str(ROOT / "tools/receipt_verify.py"),
                     "--exact-verifier", str(ROOT / "tools/exact_verify.py"),
                     "--checker", str(CHECKER),
                     "--expected-checker", CHECKER_SHA,
                     "--expected-evaluator", ENV_EPOCH,
                     "--inventory", str(INVENTORY),
                     "--expected-inventory", INVENTORY_SHA,
                     "--proof-identity", str(PROOF_ID),
                     "--expected-proof-identity-file", PROOF_ID_SHA,
                     "--expected-proof-identity-digest", PROOF_ID_DIGEST]
            for producer in ("sqrt_rat_producer.py", "exp_rat_producer.py",
                             "ln_rat_producer.py", "sin_rat_producer.py",
                             "atan_rat_producer.py",
                             "tanh_rat_producer.py"):
                path = ROOT / "tools" / producer
                if path.exists():
                    argv += ["--trusted-producer", sha_file(path)]
        proc = subprocess.run(argv, capture_output=True, text=True,
                              timeout=3600, cwd=ROOT)
        out = (proc.stdout or "") + (proc.stderr or "")
        verdict, reason = "", ""
        for line in out.splitlines():
            if line.startswith("claim-verify="):
                verdict = line.split("=", 2)[1].split()[0]
                if "reason=" in line:
                    reason = line.split("reason=", 1)[1].split()[0]
                break
        return verdict, reason, out


def request_of(steps: list[dict], root: str, **over) -> dict:
    req = {"schema": "jackal-claim-request-v1",
           "emitted_at_unix": EMITTED, "steps": steps, "root": root}
    req.update(over)
    return req


def keep(rid: str, bundle: dict | None) -> None:
    if bundle is not None:
        BUNDLES[rid] = bundle["bundle_digest_sha256"]


# ------------------------------------------------------------- dogfoods
def dog1_exact_threshold() -> None:
    bundle, detail = route(request_of([
        {"id": "p", "op": "exact", "command": "mod-pow",
         "args": ["3", "100", "7"]},
        {"id": "g", "op": "exact", "command": "xgcd",
         "args": ["240", "46"]},
        {"id": "s", "op": "interval_add", "lhs": "p", "rhs": "g"},
        {"id": "t", "op": "threshold", "arg": "s", "cmp": "lt",
         "threshold": "7"},
        {"id": "d", "op": "decision", "arg": "t", "decision_id": "dog1",
         "action": "accept-sum-bound",
         "consequence_class": "decision-boundary"},
    ], "d"))
    if bundle is None:
        record("dog1-exact-threshold", False, "routed", detail)
        return
    verdict, reason, out = verify(bundle)
    ok = verdict == "verified" and "mathematical=bounded" in out \
        and "margin=1" in out
    record("dog1-exact-threshold", ok, "verified bounded margin=1",
           f"{verdict}/{reason}")
    keep("dog1", bundle)


def dog2_formal_supplied() -> None:
    bundle, detail = route(request_of([
        {"id": "e", "op": "enclose", "expression": "ln(x)",
         "lo": "2", "hi": "3"},
        {"id": "t", "op": "threshold", "arg": "e", "cmp": "lt",
         "threshold": "2"},
        {"id": "d", "op": "decision", "arg": "t", "decision_id": "dog2",
         "action": "accept-ln-bound",
         "consequence_class": "decision-boundary"},
    ], "d"))
    if bundle is None:
        record("dog2-formal-supplied", False, "routed", detail)
        return
    verdict, reason, out = verify(bundle)
    ok = (verdict == "verified"
          and "input_provenance=supplied" in out
          and "mathematical=formal-bounded" in out
          and "model_validity=assumed" in out)
    record("dog2-formal-supplied", ok,
           "verified formal-bounded supplied", f"{verdict}/{reason}")
    keep("dog2", bundle)


def dog3_model_physics() -> None:
    bundle, detail = route(request_of([
        {"id": "d", "op": "input", "name": "dist", "lo": "10",
         "hi": "12"},
        {"id": "t", "op": "input", "name": "dur", "lo": "2", "hi": "2"},
        {"id": "v", "op": "interval_div", "lhs": "d", "rhs": "t"},
        {"id": "m", "op": "model", "arg": "v",
         "assumptions": ["model:constant-velocity-kinematics",
                         "model:frictionless"]},
    ], "m", policy=ck.default_policy(policy_id="dog3-model")))
    if bundle is None:
        record("dog3-model-physics", False, "routed", detail)
        return
    verdict, reason, out = verify(bundle, with_legacy=False)
    ok = (verdict == "verified"
          and "model_validity=assumed" in out
          and "conditional on the stated model assumptions" in out)
    record("dog3-model-physics", ok, "verified model-conditional",
           f"{verdict}/{reason}")
    keep("dog3", bundle)


def dog4_units() -> None:
    bundle, detail = route(request_of([
        {"id": "a", "op": "input", "name": "len_a", "lo": "10",
         "hi": "12", "unit": "meter"},
        {"id": "b", "op": "input", "name": "len_b", "lo": "1", "hi": "2",
         "unit": "m"},
        {"id": "s", "op": "interval_add", "lhs": "a", "rhs": "b"},
        {"id": "c", "op": "convert", "arg": "s", "target_unit": "cm"},
    ], "c"))
    if bundle is None:
        record("dog4-units", False, "routed", detail)
        return
    verdict, reason, out = verify(bundle, with_legacy=False)
    by_id = {n["id"]: n for n in bundle["nodes"]}
    root_prop = by_id[bundle["root"]]["proposition"]
    ok = (verdict == "verified" and root_prop.get("unit") == "cm"
          and root_prop["set"] == {"t": "interval", "lo": "1100",
                                   "hi": "1400"})
    record("dog4-units", ok, "verified cm [1100,1400]",
           f"{verdict}/{reason} set={root_prop.get('set')}")
    keep("dog4", bundle)

    _, detail2 = route(request_of([
        {"id": "a", "op": "input", "name": "len_a", "lo": "10",
         "hi": "12", "unit": "m"},
        {"id": "t", "op": "input", "name": "dur", "lo": "1", "hi": "2",
         "unit": "s"},
        {"id": "bad", "op": "interval_add", "lhs": "a", "rhs": "t"},
    ], "bad"))
    ok2 = "unit-dim-mismatch" in detail2
    record("dog4-units-twin-refuses", ok2, "unit-dim-mismatch", detail2)


def dog5_uncertainty() -> None:
    bundle, detail = route(request_of([
        {"id": "x1", "op": "input", "name": "x1", "lo": "0", "hi": "1",
         "source_id": "sensor-a"},
        {"id": "x2", "op": "input", "name": "x2", "lo": "0", "hi": "1",
         "source_id": "sensor-a"},
        {"id": "d", "op": "interval_sub", "lhs": "x1", "rhs": "x2"},
    ], "d"))
    if bundle is None:
        record("dog5-uncertainty", False, "routed", detail)
        return
    by_id = {n["id"]: n for n in bundle["nodes"]}
    root_prop = by_id[bundle["root"]]["proposition"]
    verdict, reason, _ = verify(bundle, with_legacy=False)
    ok = (verdict == "verified"
          and root_prop["set"] == {"t": "interval", "lo": "-1", "hi": "1"})
    record("dog5-uncertainty-outward", ok, "verified [-1,1]",
           f"{verdict}/{reason} set={root_prop.get('set')}")
    keep("dog5", bundle)

    forged = copy.deepcopy(bundle)
    by_id = {n["id"]: n for n in forged["nodes"]}
    root = by_id[forged["root"]]
    root["proposition"]["set"] = {"t": "interval", "lo": "0", "hi": "0"}
    root["id"] = hashlib.sha256(canon(
        {k: v for k, v in root.items() if k != "id"})).hexdigest()
    forged["root"] = root["id"]
    forged["rendering"] = None
    forged["bundle_digest_sha256"] = hashlib.sha256(canon(
        {k: v for k, v in forged.items()
         if k != "bundle_digest_sha256"})).hexdigest()
    verdict, reason, _ = verify(forged, root_prop=root["proposition"],
                                with_legacy=False)
    ok = verdict == "refused" and reason == "rule-invalid"
    record("dog5-false-independence-refuses", ok, "refused/rule-invalid",
           f"{verdict}/{reason}")


def dog6_machine() -> None:
    wrap_bundle, detail = route(request_of([
        {"id": "w", "op": "machine", "mop": "add", "width": 8,
         "signed": False, "mode": "wrap", "operands": ["200", "100"]},
    ], "w"))
    checked_bundle, detail2 = route(request_of([
        {"id": "c", "op": "machine", "mop": "add", "width": 8,
         "signed": False, "mode": "checked", "operands": ["200", "100"]},
    ], "c"))
    if wrap_bundle is None or checked_bundle is None:
        record("dog6-machine", False, "routed", f"{detail} {detail2}")
        return
    v1, r1, _ = verify(wrap_bundle, with_legacy=False)
    v2, r2, _ = verify(checked_bundle, with_legacy=False)
    wp = {n["id"]: n for n in wrap_bundle["nodes"]}[
        wrap_bundle["root"]]["proposition"]
    cp = {n["id"]: n for n in checked_bundle["nodes"]}[
        checked_bundle["root"]]["proposition"]
    ok = (v1 == "verified" and v2 == "verified"
          and wp["t"] == "eq" and cp["t"] == "pred"
          and wp["rhs"]["v"] == "44"
          and cp["name"].startswith("m.overflow.add.w8.u"))
    record("dog6-machine-wrap-vs-checked", ok,
           "distinct eq-44 vs overflow-pred claims",
           f"{v1}/{r1} {v2}/{r2} wrap={wp['t']} checked={cp['t']}")
    keep("dog6-wrap", wrap_bundle)
    keep("dog6-checked", checked_bundle)


def dog7_legacy_receipt() -> None:
    producer = ROOT / "tools/ln_rat_producer.py"
    proc = subprocess.run(
        [sys.executable, "-I", "-S", "-B", str(producer), "emit",
         "--expression=ln(x)", "--lower=2", "--upper=3"],
        capture_output=True, cwd=ROOT, timeout=300)
    if proc.returncode != 0:
        record("dog7-legacy-receipt", False, "producer", "refused")
        return
    cert = proc.stdout
    hdr = fr._parse_cert_header(cert)
    lo, hi = hdr["output"].split(" ", 1)
    req = {"command": "range-bound-cert", "expression": "ln(x)",
           "input_lo": "2", "input_hi": "3"}
    receipt = fr.build_variant_formal_receipt(
        variant="ln_rat", release_epoch="v1.5.0", request=req,
        enclosure=(lo, hi), cert_bytes=cert,
        producer_sha256=sha_file(producer), checker_sha256=CHECKER_SHA,
        canonical_lo="2", canonical_hi="3",
        request_commitment_b64=fr.request_commitment_b64(
            "range-bound-cert", "ln(x)", "2", "3"),
        coverage_inventory_sha256=INVENTORY_SHA,
        proof_identity=fr.load_proof_identity_binding(PROOF_ID),
        plugin_sha256=None, emitted_at_unix=int(EMITTED))
    receipt_bytes = fr.dump_receipt(receipt).encode()
    fresh = ck.freshness_block(environment_epoch=ENV_EPOCH,
                               emitted_at_unix=EMITTED)
    node = ck.build_receipt_node(receipt=receipt,
                                 receipt_bytes=receipt_bytes,
                                 checker_sha256=CHECKER_SHA,
                                 freshness=fresh)
    bundle = ck.build_bundle(
        nodes=[node], root_id=node["id"], policy=ck.default_policy(),
        evaluator_sha256=ENV_EPOCH,
        source_anb_sha256=sha_file(ROOT / "jackal_calc.anb"),
        inference_registry_sha256=INF_SHA, unit_registry_sha256=UNIT_SHA)
    verdict, reason, out = verify(bundle)
    ok = (verdict == "verified" and "mathematical=formal-bounded" in out
          and receipt["release_epoch"] == "v1.5.0")
    record("dog7-legacy-receipt", ok,
           "v1.5.0 receipt verified unmigrated", f"{verdict}/{reason}")
    keep("dog7", bundle)


def dog8_laundering() -> None:
    bundle, detail = route(request_of([
        {"id": "a", "op": "input", "name": "a", "lo": "1", "hi": "2"},
        {"id": "b", "op": "input", "name": "b", "lo": "3", "hi": "4"},
        {"id": "j", "op": "and", "args": ["a", "b"]},
    ], "j"))
    if bundle is None:
        record("dog8-laundering", False, "routed", detail)
        return
    forged = copy.deepcopy(bundle)
    by_id = {n["id"]: n for n in forged["nodes"]}
    root = by_id[forged["root"]]
    root["assurance"]["mathematical"] = "exact"
    root["id"] = hashlib.sha256(canon(
        {k: v for k, v in root.items() if k != "id"})).hexdigest()
    forged["root"] = root["id"]
    forged["rendering"] = None
    forged["bundle_digest_sha256"] = hashlib.sha256(canon(
        {k: v for k, v in forged.items()
         if k != "bundle_digest_sha256"})).hexdigest()
    verdict, reason, _ = verify(forged, root_prop=root["proposition"],
                                with_legacy=False)
    ok = verdict == "refused" and reason == "assurance-launder"
    record("dog8-laundering-refuses", ok, "refused/assurance-launder",
           f"{verdict}/{reason}")
    v2, r2, _ = verify(bundle, with_legacy=False)
    record("dog8-honest-twin-verifies", v2 == "verified", "verified",
           f"{v2}/{r2}")
    keep("dog8", bundle)


def dog9_freshness() -> None:
    bundle, detail = route(request_of([
        {"id": "a", "op": "input", "name": "a", "lo": "1", "hi": "2"},
    ], "a", nonce="dogfood-nonce-9", max_age_seconds=3600))
    if bundle is None:
        record("dog9-freshness", False, "routed", detail)
        return
    v1, r1, _ = verify(bundle, nonce="dogfood-nonce-9",
                       with_legacy=False)
    record("dog9-nonce-accepts", v1 == "verified", "verified",
           f"{v1}/{r1}")
    v2, r2, _ = verify(bundle, nonce="wrong-nonce", with_legacy=False)
    record("dog9-wrong-nonce-refuses",
           v2 == "refused" and r2 == "nonce-mismatch",
           "refused/nonce-mismatch", f"{v2}/{r2}")
    v3, r3, _ = verify(bundle, nonce="dogfood-nonce-9",
                       vtime=str(int(EMITTED) + 7200), with_legacy=False)
    record("dog9-stale-refuses",
           v3 == "refused" and r3 == "freshness-stale",
           "refused/freshness-stale", f"{v3}/{r3}")
    keep("dog9", bundle)


def dog10_repo_plugin_parity() -> None:
    request = request_of([
        {"id": "p", "op": "exact", "command": "mod-pow",
         "args": ["3", "100", "7"]},
        {"id": "t", "op": "threshold", "arg": "p", "cmp": "lt",
         "threshold": "7"},
    ], "t")
    bundle, detail = route(request)
    if bundle is None:
        record("dog10-parity", False, "routed", detail)
        return
    proc = subprocess.run(
        [sys.executable, "-I", "-S", "-B",
         str(ROOT / "tools/isolated_entry.py"), "plugin", "call",
         "jackal_claim", json.dumps({"request": request})],
        capture_output=True, text=True, timeout=900, cwd=ROOT)
    out = proc.stdout or ""
    start = out.find("{")
    plugin_doc = json.loads(out[start:]) if start >= 0 else {}
    plugin_bundle = plugin_doc.get("bundle") or {}
    ok = (plugin_doc.get("status") == "ok"
          and plugin_bundle.get("root") == bundle["root"]
          and plugin_bundle.get("bundle_digest_sha256")
          == bundle["bundle_digest_sha256"])
    record("dog10-repo-plugin-parity", ok,
           "identical root and bundle digest",
           f"cli={bundle['bundle_digest_sha256'][:16]} "
           f"plugin={plugin_bundle.get('bundle_digest_sha256', '')[:16]}")
    if ok:
        v, r, _ = verify(bundle)
        record("dog10-parity-verifies", v == "verified", "verified",
               f"{v}/{r}")
    keep("dog10", bundle)


def main() -> int:
    dog1_exact_threshold()
    dog2_formal_supplied()
    dog3_model_physics()
    dog4_units()
    dog5_uncertainty()
    dog6_machine()
    dog7_legacy_receipt()
    dog8_laundering()
    dog9_freshness()
    dog10_repo_plugin_parity()
    failures = [r for r in ROWS if not r["ok"]]
    doc = {
        "schema": "jackal-claim-dogfood-v1",
        "release_epoch": EPOCH,
        "engine": ENV_EPOCH,
        "verifier": sha_file(VERIFIER),
        "router": sha_file(ROUTER),
        "bundle_digests": dict(sorted(BUNDLES.items())),
        "rows": ROWS,
        "verdict": "PASS" if not failures else "FAIL",
    }
    EVIDENCE_OUT.write_text(json.dumps(doc, indent=2, sort_keys=True)
                            + "\n")
    print(f"evidence={EVIDENCE_OUT}")
    print(f"CLAIM_DOGFOOD_{'PASS' if not failures else 'FAIL'} "
          f"rows={len(ROWS)} failures={len(failures)}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
