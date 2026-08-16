#!/usr/bin/env python3
"""One-shot v1.5.0 re-pin driver (repo maintenance tool, NOT a trust surface).

Order matters:
  1. install the freshly built engine binary as jackal-native;
  2. regenerate the coverage inventory (reads Embed.lean + engine source);
  3. regenerate BOTH proof identities (Lean source closure changed);
  4. compute the plugin bundle hash (server.py/tools.json changed);
  5. rewrite release/MANIFEST.sha256 with every pin, including the five new
     labels (ln_rat_producer, sin_rat_producer, atan_rat_producer,
     tanh_rat_producer, exact_verifier).

Every hash is recomputed from the bytes on disk at run time; nothing is
hand-typed.  The script prints each pin as it lands.  Idempotent.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENGINE_BUILD = Path("/tmp/jackal-final-build/anubis_run")


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    print(f"$ {' '.join(cmd)}")
    return subprocess.run(cmd, check=True, cwd=ROOT, **kw)


def main() -> int:
    # 1. engine binary
    if ENGINE_BUILD.exists():
        native = ROOT / "jackal-native"
        if not native.exists() or sha(native) != sha(ENGINE_BUILD):
            shutil.copy2(ENGINE_BUILD, native)
            native.chmod(0o755)
            print(f"installed jackal-native <- {ENGINE_BUILD}")
    else:
        print(f"NOTE: {ENGINE_BUILD} missing; keeping existing jackal-native")

    # 2. coverage inventory
    run([sys.executable, "tools/coverage_inventory.py"])

    # 3. proof identities (range + gaussian)
    for lane in ("range", "gaussian"):
        run([sys.executable, "release/tools/gaussian_proof_identity.py",
             "generate", "--lane", lane])

    # 4. plugin bundle hash
    bundle = run([sys.executable, "plugin/hermes/bundle_hash.py", "print"],
                 capture_output=True, text=True).stdout.strip().split()[-1]
    print(f"plugin bundle {bundle}")

    # 5. manifest
    def digest_of(path: str) -> str:
        return sha(ROOT / path)

    range_pi = json.loads((ROOT / "release/evidence/range_proof_identity.json").read_text())
    gauss_pi = json.loads((ROOT / "release/evidence/gaussian_proof_identity.json").read_text())
    lines = [
        "# JACKAL v1.6.0 pinned release identities (range schema v2 + Gaussian schema v1"
        " + sqrt_rat/exp_rat/ln_rat/sin_rat/cos_rat/atan_rat/tanh_rat variants"
        " + exact CAS lane verifier + claim kernel)",
        f"evaluator jackal-native {digest_of('jackal-native')}",
        f"checker jackal_cert_check {digest_of('proofs/lean/.lake/build/bin/jackal_cert_check')}",
        f"gaussian-producer tools/gaussian_certificate.py {digest_of('tools/gaussian_certificate.py')}",
        f"gaussian-checker jackal_gaussian_check {digest_of('proofs/lean/.lake/build/bin/jackal_gaussian_check')}",
        f"range-proof-identity release/evidence/range_proof_identity.json {digest_of('release/evidence/range_proof_identity.json')}",
        f"range-proof-digest {range_pi['identity_digest_sha256']}",
        f"gaussian-proof-identity release/evidence/gaussian_proof_identity.json {digest_of('release/evidence/gaussian_proof_identity.json')}",
        f"gaussian-proof-digest {gauss_pi['identity_digest_sha256']}",
        f"coverage-inventory release/coverage/formal_coverage_inventory.json {digest_of('release/coverage/formal_coverage_inventory.json')}",
        f"source jackal_calc.anb {digest_of('jackal_calc.anb')}",
        f"compiler_pin anubis-a733565f237d {digest_of_home_pin()}",
        f"plugin_hermes {bundle}",
        f"sqrt_rat_producer tools/sqrt_rat_producer.py {digest_of('tools/sqrt_rat_producer.py')}",
        f"exp_rat_producer tools/exp_rat_producer.py {digest_of('tools/exp_rat_producer.py')}",
        f"ln_rat_producer tools/ln_rat_producer.py {digest_of('tools/ln_rat_producer.py')}",
        f"sin_rat_producer tools/sin_rat_producer.py {digest_of('tools/sin_rat_producer.py')}",
        f"atan_rat_producer tools/atan_rat_producer.py {digest_of('tools/atan_rat_producer.py')}",
        f"tanh_rat_producer tools/tanh_rat_producer.py {digest_of('tools/tanh_rat_producer.py')}",
        f"exact_verifier tools/exact_verify.py {digest_of('tools/exact_verify.py')}",
        f"claim_kernel tools/claim_kernel.py {digest_of('tools/claim_kernel.py')}",
        f"claim_router tools/claim_router.py {digest_of('tools/claim_router.py')}",
        f"claim_verifier tools/claim_bundle_verify.py {digest_of('tools/claim_bundle_verify.py')}",
        f"claim_inference_registry release/claim/inference_registry_v1.json {digest_of('release/claim/inference_registry_v1.json')}",
        f"claim_unit_registry release/claim/unit_registry_v1.json {digest_of('release/claim/unit_registry_v1.json')}",
    ]
    manifest = ROOT / "release/MANIFEST.sha256"
    manifest.write_text("\n".join(lines) + "\n")
    print(manifest.read_text())
    return 0


def digest_of_home_pin() -> str:
    pin = Path.home() / "anubis-lang/vm/pins/anubis-a733565f237d"
    return hashlib.sha256(pin.read_bytes()).hexdigest()


if __name__ == "__main__":
    sys.exit(main())
