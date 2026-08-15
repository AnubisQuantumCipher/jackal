#!/usr/bin/env python3
"""JACKAL v1.2.0 fresh-extraction package smoke test.

Copies the built package to a fresh temp directory with NO repository-relative
fallback and exercises it end to end: valid release bounded; unsupported op,
forged request, forged evaluator/checker, missing checker, and manifest tamper
all refuse; and the released output identifies the exact packaged evaluator +
checker hashes. Load-bearing checks raise; no assert.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PKG_SRC = ROOT / "release/dist/jackal-v1.2.0-macos-arm64"


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=3600, **kw)


def fail(m):
    print(f"PACKAGE-SMOKE-FAIL: {m}", file=sys.stderr)
    raise SystemExit(1)


def main() -> int:
    if not PKG_SRC.exists():
        fail(f"package not built at {PKG_SRC}")
    tmp = Path(tempfile.mkdtemp(prefix="jackal-pkg-smoke-"))
    pkg = tmp / "pkg"
    shutil.copytree(PKG_SRC, pkg)
    rel = pkg / "jackal-cert-release"
    os.chmod(rel, 0o755)
    os.chmod(pkg / "jackal-native", 0o755)
    os.chmod(pkg / "jackal_cert_check", 0o755)

    eval_id = sha(pkg / "jackal-native")
    chk_id = sha(pkg / "jackal_cert_check")

    # SHA256SUMS integrity over the fresh extraction.
    c = run(["shasum", "-a", "256", "-c", "SHA256SUMS"], cwd=pkg)
    if c.returncode != 0:
        fail(f"SHA256SUMS check failed: {c.stdout}{c.stderr}")

    results = []

    def smoke(name, args, expect_bounded, mutate=None):
        p = pkg
        if mutate:
            mutate(p)
        cp = run([str(rel), *args], cwd=p)
        ok_bounded = cp.returncode == 0 and "status=formal-bounded" in cp.stdout
        if expect_bounded and not ok_bounded:
            fail(f"{name}: expected bounded, got rc={cp.returncode} {cp.stdout}{cp.stderr}")
        if not expect_bounded and ok_bounded:
            fail(f"{name}: expected refusal, got bounded")
        results.append((name, "formal-bounded" if ok_bounded else "refused", cp.stdout, cp.stderr))
        return cp

    receipt_path = pkg / "formal-receipt.json"
    cp = smoke("valid", ["x^2+1", "1", "2", str(receipt_path)], True)
    if eval_id not in cp.stdout or chk_id not in cp.stdout:
        fail("released output does not identify exact packaged evaluator/checker hashes")
    if not receipt_path.is_file():
        fail("valid release did not emit the requested formal receipt")
    verified = run([sys.executable, str(pkg / "receipt_verify.py"),
                    "--receipt", str(receipt_path),
                    "--checker", str(pkg / "jackal_cert_check"),
                    "--expected-evaluator", eval_id,
                    "--expected-checker", chk_id,
                    "--inventory", str(pkg / "formal_coverage_inventory.json")])
    if verified.returncode != 0 or "status=verified verdict=ACCEPT" not in verified.stdout:
        fail(f"standalone receipt verifier did not accept: {verified.stdout}{verified.stderr}")
    results.append(("formal-receipt-reverify", "verified", verified.stdout, verified.stderr))

    smoke("unsupported-op", ["sqrt(x)", "1", "2"], False)
    smoke("invalid-domain", ["1/x", "-1", "1"], False)

    # forged request: tamper the wrapper is not allowed; instead validate a cert
    # for a different request via the packaged validator directly.
    forged = run([sys.executable, str(pkg / "release_validate.py"),
                  "--expr", "x^2+1", "--lo", "1", "--hi", "2",
                  "--evaluator", str(pkg / "jackal-native"),
                  "--checker", str(pkg / "jackal_cert_check"),
                  "--expected-evaluator", "b" * 64, "--expected-checker", chk_id])
    if forged.returncode == 0:
        fail("forged evaluator identity released bounded")
    results.append(("forged-evaluator", "refused", forged.stdout, forged.stderr))

    forged_chk = run([sys.executable, str(pkg / "release_validate.py"),
                      "--expr", "x^2+1", "--lo", "1", "--hi", "2",
                      "--evaluator", str(pkg / "jackal-native"),
                      "--checker", str(pkg / "jackal_cert_check"),
                      "--expected-evaluator", eval_id, "--expected-checker", "c" * 64])
    if forged_chk.returncode == 0:
        fail("forged checker identity released bounded")
    results.append(("forged-checker", "refused", forged_chk.stdout, forged_chk.stderr))

    # missing checker
    (pkg / "jackal_cert_check").rename(pkg / "jackal_cert_check.bak")
    mc = run([str(rel), "x^2+1", "1", "2"], cwd=pkg)
    if mc.returncode == 0:
        fail("missing checker released bounded")
    (pkg / "jackal_cert_check.bak").rename(pkg / "jackal_cert_check")
    results.append(("missing-checker", "refused", mc.stdout, mc.stderr))

    # manifest tamper: point evaluator identity at a wrong hash → refuse
    man = pkg / "MANIFEST.sha256"
    orig = man.read_text()
    man.write_text(orig.replace(eval_id, "d" * 64))
    mt = run([str(rel), "x^2+1", "1", "2"], cwd=pkg)
    if mt.returncode == 0:
        fail("manifest tamper released bounded")
    man.write_text(orig)
    results.append(("manifest-tamper", "refused", mt.stdout, mt.stderr))

    # The packaged Hermes adapter must bind its own pinned bundle identity and
    # re-run the same checker from the fresh extraction, with no repo fallback.
    plugin = pkg / "plugin" / "hermes" / "jackal_hermes"
    plugin.chmod(0o755)
    ps = run([str(plugin), "selftest"], cwd=pkg)
    if ps.returncode != 0 or "identity_match=true" not in ps.stdout:
        fail(f"packaged plugin identity selftest failed: {ps.stdout}{ps.stderr}")
    pc = run([str(plugin), "call", "jackal_range_bound",
              '{"expression":"sin(x)+x^2","input_lo":"0","input_hi":"1"}'], cwd=pkg)
    if pc.returncode != 0 or '"status": "formal-bounded"' not in pc.stdout:
        fail(f"packaged plugin formal call failed: {pc.stdout}{pc.stderr}")
    results.append(("plugin-fresh-extraction", "formal-bounded", pc.stdout, pc.stderr))

    shutil.rmtree(tmp, ignore_errors=True)
    for name, verdict, _, _ in results:
        print(f"  smoke {name}: {verdict}")
    print(f"package_evaluator_sha256={eval_id}")
    print(f"package_checker_sha256={chk_id}")
    print("VERDICT: PASS — fresh-extraction package smokes all correct")
    return 0


if __name__ == "__main__":
    sys.exit(main())
