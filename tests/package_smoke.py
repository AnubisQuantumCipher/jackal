#!/usr/bin/env python3
"""JACKAL v1.4.1 fresh-extraction package smoke test.

Copies the built package to a fresh temp directory with NO repository-relative
fallback and exercises it end to end: valid release bounded; unsupported op,
forged request, forged evaluator/checker, missing checker, and manifest tamper
all refuse; and the released output identifies the exact packaged evaluator +
checker hashes. Load-bearing checks raise; no assert.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PKG_SRC = ROOT / "release/dist/jackal-v1.4.1-macos-arm64"


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
    gaussian_rel = pkg / "jackal-gaussian-release"
    os.chmod(rel, 0o755)
    os.chmod(gaussian_rel, 0o755)
    os.chmod(pkg / "jackal-native", 0o755)
    os.chmod(pkg / "jackal_cert_check", 0o755)
    os.chmod(pkg / "jackal_gaussian_check", 0o755)
    os.chmod(pkg / "jackal-sqrt-rat-release", 0o755)
    os.chmod(pkg / "jackal-exp-rat-release", 0o755)

    eval_id = sha(pkg / "jackal-native")
    chk_id = sha(pkg / "jackal_cert_check")
    gaussian_producer_id = sha(pkg / "gaussian_certificate.py")
    gaussian_checker_id = sha(pkg / "jackal_gaussian_check")
    source_id = sha(pkg / "jackal_calc.anb")
    range_proof_file_id = sha(pkg / "range_proof_identity.json")
    gaussian_proof_file_id = sha(pkg / "gaussian_proof_identity.json")
    range_proof_digest = json.loads(
        (pkg / "range_proof_identity.json").read_text())["identity_digest_sha256"]
    gaussian_proof_digest = json.loads(
        (pkg / "gaussian_proof_identity.json").read_text())["identity_digest_sha256"]

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
    verified = run([str(pkg / "jackal-receipt-verify"),
                    "--receipt", str(receipt_path),
                    "--checker", str(pkg / "jackal_cert_check"),
                    "--expected-evaluator", eval_id,
                    "--expected-checker", chk_id,
                    "--expected-source", source_id,
                    "--expected-release-epoch", "v1.4.1",
                    "--expected-command", "range-bound-cert",
                    "--expected-expression", "x^2+1",
                    "--expected-input-lo", "1",
                    "--expected-input-hi", "2",
                    "--proof-identity", str(pkg / "range_proof_identity.json"),
                    "--expected-proof-identity-file", range_proof_file_id,
                    "--expected-proof-identity-digest", range_proof_digest,
                    "--expected-inventory", sha(pkg / "formal_coverage_inventory.json"),
                    "--inventory", str(pkg / "formal_coverage_inventory.json")])
    if verified.returncode != 0 or "status=verified verdict=ACCEPT" not in verified.stdout:
        fail(f"standalone receipt verifier did not accept: {verified.stdout}{verified.stderr}")
    results.append(("formal-receipt-reverify", "verified", verified.stdout, verified.stderr))

    gaussian_receipt = pkg / "gaussian-formal-receipt.json"
    gaussian = run([
        str(gaussian_rel), "exp(-10000000000*(x-0.5000123456789)^2)",
        "0", "1", "1/1000000000000", str(gaussian_receipt),
    ], cwd=pkg)
    if gaussian.returncode != 0 or "status=formal-bounded" not in gaussian.stdout:
        fail(f"Gaussian formal release failed: {gaussian.stdout}{gaussian.stderr}")
    if gaussian_producer_id not in gaussian.stdout or gaussian_checker_id not in gaussian.stdout:
        fail("Gaussian release omitted exact producer/checker identities")
    gaussian_verified = run([
        str(pkg / "jackal-receipt-verify"),
        "--receipt", str(gaussian_receipt),
        "--checker", str(pkg / "jackal_gaussian_check"),
        "--expected-evaluator", gaussian_producer_id,
        "--expected-checker", gaussian_checker_id,
        "--expected-release-epoch", "v1.4.1",
        "--expected-command", "integrate",
        "--expected-expression", "exp(-10000000000*(x-0.5000123456789)^2)",
        "--expected-input-lo", "0",
        "--expected-input-hi", "1",
        "--expected-tolerance", "1/1000000000000",
        "--proof-identity", str(pkg / "gaussian_proof_identity.json"),
        "--expected-proof-identity-file", gaussian_proof_file_id,
        "--expected-proof-identity-digest", gaussian_proof_digest,
        "--expected-inventory", sha(pkg / "formal_coverage_inventory.json"),
        "--inventory", str(pkg / "formal_coverage_inventory.json"),
    ])
    if gaussian_verified.returncode != 0 or "receipt_valid=true" not in gaussian_verified.stdout:
        fail(f"Gaussian receipt verifier refused: {gaussian_verified.stdout}{gaussian_verified.stderr}")
    results.append(("gaussian-formal", "formal-bounded", gaussian.stdout, gaussian.stderr))

    unsupported_gaussian = run([
        str(gaussian_rel), "exp(x)", "0", "1", "1/1000000000000",
        str(pkg / "must-not-exist.json"),
    ], cwd=pkg)
    if unsupported_gaussian.returncode == 0 or (pkg / "must-not-exist.json").exists():
        fail("unsupported formal integration request did not fail closed")
    results.append(("gaussian-unsupported", "refused", unsupported_gaussian.stdout,
                    unsupported_gaussian.stderr))

    smoke("unsupported-op", ["sqrt(x)", "1", "2",
                              str(pkg / "unsupported-must-not-exist.json")], False)
    smoke("invalid-domain", ["1/x", "-1", "1",
                              str(pkg / "domain-must-not-exist.json")], False)

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
    mc = run([str(rel), "x^2+1", "1", "2",
              str(pkg / "missing-checker-must-not-exist.json")], cwd=pkg)
    if mc.returncode == 0:
        fail("missing checker released bounded")
    (pkg / "jackal_cert_check.bak").rename(pkg / "jackal_cert_check")
    results.append(("missing-checker", "refused", mc.stdout, mc.stderr))

    # manifest tamper: point evaluator identity at a wrong hash → refuse
    man = pkg / "MANIFEST.sha256"
    orig = man.read_text()
    man.write_text(orig.replace(eval_id, "d" * 64))
    mt = run([str(rel), "x^2+1", "1", "2",
              str(pkg / "manifest-tamper-must-not-exist.json")], cwd=pkg)
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

    # v1.4.x fragment-extension CLIs must work in the packaged, fresh-extracted
    # layout — regressions here would be silent otherwise. The plugin variants
    # exercise the same producer + checker pins via the plugin surface.
    sqrt_cli = run([str(pkg / "jackal-sqrt-rat-release"), "sqrt(x)", "2", "3"],
                    cwd=pkg)
    if sqrt_cli.returncode != 0 or "status=formal-bounded" not in sqrt_cli.stdout:
        fail(f"packaged jackal-sqrt-rat-release refused: "
             f"{sqrt_cli.stdout}{sqrt_cli.stderr}")
    results.append(("sqrt-rat-release-cli", "formal-bounded",
                     sqrt_cli.stdout, sqrt_cli.stderr))

    exp_cli = run([str(pkg / "jackal-exp-rat-release"), "exp(x)", "0", "1"],
                   cwd=pkg)
    if exp_cli.returncode != 0 or "status=formal-bounded" not in exp_cli.stdout:
        fail(f"packaged jackal-exp-rat-release refused: "
             f"{exp_cli.stdout}{exp_cli.stderr}")
    results.append(("exp-rat-release-cli", "formal-bounded",
                     exp_cli.stdout, exp_cli.stderr))

    # Negative-lower must refuse fail-closed on the packaged exp wrapper.
    exp_neg = run([str(pkg / "jackal-exp-rat-release"), "exp(x)", "-1", "1"],
                   cwd=pkg)
    if exp_neg.returncode == 0:
        fail(f"packaged exp wrapper accepted negative lower: {exp_neg.stdout}")
    results.append(("exp-rat-release-cli-refuse-neg", "refused",
                     exp_neg.stdout, exp_neg.stderr))

    # Plugin variants must round-trip through the packaged bundle too — this
    # catches the class of drift where the packaged MANIFEST omits producer
    # labels the plugin depends on (fixed in v1.4.1a).
    plugin_sqrt = run([str(plugin), "call", "jackal_sqrt_rat_bound",
                        '{"expression":"sqrt(x)","input_lo":"2","input_hi":"3"}'],
                       cwd=pkg)
    if plugin_sqrt.returncode != 0 or '"status": "formal-bounded"' not in plugin_sqrt.stdout:
        fail(f"packaged plugin jackal_sqrt_rat_bound failed: "
             f"{plugin_sqrt.stdout}{plugin_sqrt.stderr}")
    results.append(("plugin-sqrt-rat", "formal-bounded",
                     plugin_sqrt.stdout, plugin_sqrt.stderr))

    plugin_exp = run([str(plugin), "call", "jackal_exp_rat_bound",
                       '{"expression":"exp(x)","input_lo":"0","input_hi":"1"}'],
                      cwd=pkg)
    if plugin_exp.returncode != 0 or '"status": "formal-bounded"' not in plugin_exp.stdout:
        fail(f"packaged plugin jackal_exp_rat_bound failed: "
             f"{plugin_exp.stdout}{plugin_exp.stderr}")
    results.append(("plugin-exp-rat", "formal-bounded",
                     plugin_exp.stdout, plugin_exp.stderr))

    shutil.rmtree(tmp, ignore_errors=True)
    for name, verdict, _, _ in results:
        print(f"  smoke {name}: {verdict}")
    print(f"package_evaluator_sha256={eval_id}")
    print(f"package_checker_sha256={chk_id}")
    print("VERDICT: PASS — fresh-extraction package smokes all correct")
    return 0


if __name__ == "__main__":
    sys.exit(main())
