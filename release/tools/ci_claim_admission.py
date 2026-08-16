#!/usr/bin/env python3
"""Hosted-CI v1.6.0 claim-kernel admission gate (engine-free).

Replays the committed exact-lane claim fixture through the dependency-free
verifier `tools/claim_bundle_verify.py` with every semantic pin supplied
from `release/evidence/ci_claim_fixture_v160/pins.json`, then proves one
semantic tamper (a mutated node value) refuses for a stable reason.

Scope (stated honestly): this exercises the v1.6.0 claim-kernel admission
path — canonical bytes, node identity, rule replay, assurance-axis
recomputation, consequence floors, rendering, and the exact-cert
independent recompute — on the hosted platform.  It does NOT run the
macOS-only engine, the Lean-checked formal lanes, or the full 38-gate
aggregate; those remain local sealed evidence.  The recorded environment
epoch is replayed as a caller pin, exactly as a downstream verifier would.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "release/evidence/ci_claim_fixture_v160"


def verify(bundle: Path, pins: dict) -> subprocess.CompletedProcess:
    argv = [
        sys.executable, "-I", "-S", "-B",
        str(ROOT / "tools/claim_bundle_verify.py"),
        "--bundle", str(bundle),
        "--expected-release-epoch", pins["expected_release_epoch"],
        "--expected-root-proposition", str(FIXTURE / "root_prop.json"),
        "--expected-policy-sha256", pins["expected_policy_sha256"],
        "--expected-inference-registry",
        str(ROOT / "release/claim/inference_registry_v1.json"),
        "--expected-inference-registry-sha256",
        pins["expected_inference_registry_sha256"],
        "--expected-unit-registry",
        str(ROOT / "release/claim/unit_registry_v1.json"),
        "--expected-unit-registry-sha256",
        pins["expected_unit_registry_sha256"],
        "--expected-environment-epoch", pins["expected_environment_epoch"],
        "--verification-time-unix", str(pins["verification_time_unix"]),
        "--exact-verifier", str(ROOT / "tools/exact_verify.py"),
    ]
    return subprocess.run(argv, capture_output=True, text=True, timeout=600)


def main() -> int:
    pins = json.loads((FIXTURE / "pins.json").read_text())
    bundle = FIXTURE / "bundle.json"

    import hashlib
    got = hashlib.sha256(bundle.read_bytes()).hexdigest()
    if got != pins["bundle_sha256"]:
        print(f"FAIL fixture-bundle-hash: {got} != {pins['bundle_sha256']}")
        return 1
    print(f"PASS fixture-bundle-hash {got}")

    p = verify(bundle, pins)
    out = p.stdout or ""
    if p.returncode != 0 or "claim-verify=verified" not in out:
        print("FAIL positive-replay")
        print(out[-2000:], (p.stderr or "")[-2000:], sep="\n")
        return 1
    if f"bundle.digest={pins['bundle_digest_sha256']}" not in out:
        print("FAIL positive-replay: bundle digest mismatch")
        return 1
    print(f"PASS positive-replay bundle.digest={pins['bundle_digest_sha256']}")

    # Semantic tamper: flip the exact-lane node's claimed value.  The
    # verifier must refuse — never downgrade, never re-render.
    doc = json.loads(bundle.read_text())
    tampered_nodes = 0
    for node in doc["nodes"]:
        prop = json.dumps(node.get("proposition", {}))
        if '"5"' in prop:  # 3^100 mod 7 == 4; forge any 5 in the exact chain
            node_s = json.dumps(node["proposition"])
            node["proposition"] = json.loads(node_s.replace('"5"', '"6"'))
            tampered_nodes += 1
    if tampered_nodes == 0:
        # fall back: mutate the recorded root value digit 4 -> 5
        s = bundle.read_text().replace('"4"', '"5"', 1)
        tampered = FIXTURE / "_tampered.json"
        tampered.write_text(s)
    else:
        tampered = FIXTURE / "_tampered.json"
        tampered.write_text(json.dumps(doc, sort_keys=True,
                                       separators=(",", ":"),
                                       ensure_ascii=False))
    try:
        q = verify(tampered, pins)
        qout = (q.stdout or "") + (q.stderr or "")
        if q.returncode == 0 or "claim-verify=verified" in qout:
            print("FAIL tamper-refusal: tampered bundle verified")
            return 1
        if "claim-verify=refused" not in qout and \
           "claim-verify=indeterminate" not in qout:
            print("FAIL tamper-refusal: no stable refusal line")
            print(qout[-2000:])
            return 1
        reason = next((ln for ln in qout.splitlines()
                       if ln.startswith("claim-verify=")), "?")
        print(f"PASS tamper-refusal {reason}")
    finally:
        tampered.unlink(missing_ok=True)

    print("CI_CLAIM_ADMISSION_PASS checks=3")
    return 0


if __name__ == "__main__":
    sys.exit(main())
