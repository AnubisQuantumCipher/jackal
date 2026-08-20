#!/usr/bin/env python3
"""v1.7.3 unified package parity and fresh-extraction gate.

1. Builds the current v1.7.3 package twice into independent destinations from
   one frozen repository state and requires byte-identical tarballs.
2. Fresh-extracts one tarball and verifies complete SHA256SUMS.
3. Exercises every self-contained calculator/claim tool plus all four
   domain-pack tools and all three Anubis program-evidence plugin routes.
4. Proves three-way claim parity across repository CLI, package CLI, and
   packaged plugin, then proves a tampered bundle refuses.
5. Refuses before building when the canonical instrument is pointed at a
   superseded builder or catalog.

Run: python3 tests/claim_package_parity_test.py
"""
from __future__ import annotations

import hashlib
import filecmp
import json
import subprocess
import os
import sys
import tempfile
from pathlib import Path

try:
    from tests.anubis_program_verifier_test import (
        POLICY_SHA256,
        VERIFY_TIME,
        make_v3_fixture,
        sha,
    )
except ModuleNotFoundError:
    from anubis_program_verifier_test import (
        POLICY_SHA256,
        VERIFY_TIME,
        make_v3_fixture,
        sha,
    )

ROOT = Path(__file__).resolve().parents[1]
BUILDER = ROOT / "release/build_package_v173.sh"
PKG_NAME = "jackal-v1.7.3-macos-arm64"
TARBALL: Path | None = None
BUILD_HOLDER: tempfile.TemporaryDirectory[str] | None = None

ROWS: list[dict] = []


def record(rid: str, ok: bool, expect: str, observed: str) -> None:
    ROWS.append({"id": rid, "ok": bool(ok), "expect": expect,
                 "observed": observed[:200]})
    print(f"{'PASS' if ok else 'FAIL'} {rid}"
          + ("" if ok else f" — expected {expect}, got {observed[:140]}"))


def sha_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def canon(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode()


REQUEST = {
    "schema": "jackal-claim-request-v1",
    "emitted_at_unix": "1786752000",
    "steps": [
        {"id": "p", "op": "exact", "command": "mod-pow",
         "args": ["3", "100", "7"]},
        {"id": "t", "op": "threshold", "arg": "p", "cmp": "lt",
         "threshold": "7"},
    ],
    "root": "t",
}

GAUSSIAN_EXPR = "exp(-10000000000*(x-0.5000123456789)^2)"

PLUGIN_CASES: list[tuple[str, dict, set[str]]] = [
    ("jackal_range_bound", {"expression": "cos(x)", "input_lo": "0",
                            "input_hi": "1"}, {"formal-bounded"}),
    ("jackal_gaussian_integral",
     {"expression": GAUSSIAN_EXPR, "input_lo": "0", "input_hi": "1",
      "tolerance": "1/1000000000000"}, {"formal-bounded"}),
    ("jackal_integrate_bound_cert",
     {"expression": "sin(x)", "input_lo": "0", "input_hi": "1",
      "tolerance": "1/100"}, {"formal-bounded"}),
    ("jackal_sqrt_rat_bound", {"expression": "sqrt(x)", "input_lo": "2",
                               "input_hi": "3"}, {"formal-bounded"}),
    ("jackal_exp_rat_bound", {"expression": "exp(x)", "input_lo": "0",
                              "input_hi": "1"}, {"formal-bounded"}),
    ("jackal_ln_rat_bound", {"expression": "ln(x)", "input_lo": "2",
                             "input_hi": "3"}, {"formal-bounded"}),
    ("jackal_sin_rat_bound", {"expression": "sin(x)", "input_lo": "0",
                              "input_hi": "1"}, {"formal-bounded"}),
    ("jackal_cos_rat_bound", {"expression": "cos(x)", "input_lo": "0",
                              "input_hi": "1"}, {"formal-bounded"}),
    ("jackal_atan_rat_bound", {"expression": "atan(x)", "input_lo": "0",
                               "input_hi": "1"}, {"formal-bounded"}),
    ("jackal_tanh_rat_bound", {"expression": "1-2/(exp(2*x)+1)",
                               "input_lo": "0", "input_hi": "1"},
     {"formal-bounded"}),
    ("jackal_exact", {"expression": "1/3+1/6"}, {"exact"}),
    ("jackal_evaluate", {"expression": "2+2*10"},
     {"exact", "checked", "estimated", "bounded", "model-based"}),
    ("jackal_diff", {"expression": "x^3"},
     {"exact", "checked", "estimated"}),
    ("jackal_integrate", {"expression": "x^2", "input_lo": "0",
                          "input_hi": "1", "panels": "128"},
     {"estimated"}),
    ("jackal_integrate_adaptive", {"expression": "x^2", "input_lo": "0",
                                   "input_hi": "1",
                                   "tolerance": "0.000001"},
     {"estimated"}),
    ("jackal_integrate_bound", {"expression": "x^2", "input_lo": "0",
                                "input_hi": "1", "tolerance": "0.01"},
     {"bounded"}),
    ("jackal_solve", {"expression": "x^2-2", "input_lo": "1",
                      "input_hi": "2"}, {"estimated", "checked"}),
    ("jackal_canon", {"expression": "2+3*sin(pi/6)^2"}, {"exact"}),
    ("jackal_poly_canon", {"expression": "(x+1)*(x-1)"}, {"exact"}),
    ("jackal_poly_eq", {"lhs": "(x+1)^2", "rhs": "x^2+2*x+1"},
     {"exact"}),
    ("jackal_poly_gcd", {"lhs": "x^2-1", "rhs": "x^2+2*x+1"}, {"exact"}),
    ("jackal_ratfunc_canon", {"expression": "(x^2-1)/(x+1)"}, {"exact"}),
    ("jackal_roots_isolate", {"expression": "x^2-2"}, {"exact"}),
    ("jackal_alg_sign", {"expression": "x^2-2", "point": "1"},
     {"exact"}),
    ("jackal_alg_cmp", {"p": "x^2-2", "a1": "1", "b1": "2",
                        "q": "x^2-3", "a2": "1", "b2": "2"}, {"exact"}),
    ("jackal_xgcd", {"a": "240", "b": "46"}, {"exact"}),
    ("jackal_mod_pow", {"base": "3", "exp": "100", "mod": "7"},
     {"exact"}),
    ("jackal_mod_inv", {"a": "3", "m": "7"}, {"exact"}),
    ("jackal_crt", {"args": "2 3 3 5 2 7"}, {"exact"}),
    ("jackal_divides", {"a": "12", "b": "3"}, {"exact"}),
    ("jackal_prime_cert", {"n": "104729"}, {"exact"}),
]


def instrument_current() -> tuple[bool, str]:
    if BUILDER.name != "build_package_v173.sh" or not BUILDER.is_file():
        return False, "superseded-builder"
    catalog = json.loads((ROOT / "plugin/hermes/tools.json").read_text())
    names = [row.get("name") for row in catalog.get("tools", [])]
    if catalog.get("version") != "v1.7.3" or len(names) != 41:
        return False, "stale-catalog"
    full = json.loads((ROOT / "plugin/hermes/profiles/full.json").read_text())
    if full.get("tools") != names:
        return False, "profile-catalog-divergence"
    return True, "current"


def build_twice() -> bool:
    global BUILD_HOLDER, TARBALL
    BUILD_HOLDER = tempfile.TemporaryDirectory(prefix="jackal-parity-builds-")
    build_root = Path(BUILD_HOLDER.name)
    tarballs: list[Path] = []
    hashes: list[str] = []
    for attempt in (1, 2):
        destination = build_root / f"attempt-{attempt}"
        destination.mkdir()
        environment = os.environ.copy()
        environment["JACKAL_DIST"] = str(destination)
        proc = subprocess.run(
            [str(BUILDER), "--build"],
            capture_output=True,
            text=True,
            timeout=1800,
            cwd=ROOT,
            env=environment,
        )
        if proc.returncode != 0:
            record(
                f"pkg-build-{attempt}",
                False,
                "exit 0",
                (proc.stderr or proc.stdout)[-160:],
            )
            return False
        tarball = destination / f"{PKG_NAME}.tar.gz"
        ok = tarball.is_file() and "PACKAGE_V173_BUILD_PASS" in proc.stdout
        record(
            f"pkg-build-{attempt}",
            ok,
            "current builder emits v1.7.3 tarball",
            (proc.stdout or proc.stderr)[-160:].replace("\n", " "),
        )
        if not ok:
            return False
        tarballs.append(tarball)
        hashes.append(sha_file(tarball))
    identical = (
        hashes[0] == hashes[1]
        and tarballs[0].stat().st_size == tarballs[1].stat().st_size
        and filecmp.cmp(tarballs[0], tarballs[1], shallow=False)
    )
    record(
        "pkg-double-build-identical",
        identical,
        "byte-identical tarball",
        f"{hashes[0]} vs {hashes[1]}",
    )
    TARBALL = tarballs[0]
    return identical


def plugin_call(pkg: Path, tool: str, arguments: dict) -> dict:
    proc = subprocess.run(
        [sys.executable, "-I", "-S", "-B",
         str(pkg / "isolated_entry.py"), "plugin", "call", tool,
         json.dumps(arguments)],
        capture_output=True, text=True, timeout=900, cwd=pkg)
    out = proc.stdout or ""
    start = out.find("{")
    if start < 0:
        return {"status": "no-json", "detail": (out + (proc.stderr or ""))[-160:]}
    try:
        return json.loads(out[start:])
    except json.JSONDecodeError:
        return {"status": "bad-json", "detail": out[start:start + 160]}


def cli_route(cli: Path, workdir: Path, tag: str) -> dict | None:
    req = workdir / f"req-{tag}.json"
    bundle = workdir / f"bundle-{tag}.json"
    req.write_text(json.dumps(REQUEST, sort_keys=True))
    proc = subprocess.run([str(cli), "--request", str(req),
                           "--emit-bundle", str(bundle)],
                          capture_output=True, text=True, timeout=900)
    if proc.returncode != 0:
        return None
    return json.loads(bundle.read_text())


def main() -> int:
    current, reason = instrument_current()
    record(
        "pkg-instrument-current",
        current,
        "v1.7.3 builder, 41-tool catalog, matching full profile",
        reason,
    )
    if not current:
        return finish()
    if not build_twice():
        return finish()
    assert TARBALL is not None

    with tempfile.TemporaryDirectory(prefix="jackal-claim-pkg-") as td:
        work = Path(td)
        subprocess.run(["tar", "-xzf", str(TARBALL), "-C", str(work)],
                       check=True, timeout=300)
        pkg = work / PKG_NAME
        record("pkg-fresh-extract", pkg.is_dir(), "extracted",
               str(sorted(p.name for p in work.iterdir()))[:120])

        sums = subprocess.run(["shasum", "-a", "256", "-c", "SHA256SUMS"],
                              capture_output=True, text=True, cwd=pkg,
                              timeout=300)
        record("pkg-sha256sums", sums.returncode == 0
               and "FAILED" not in (sums.stdout or ""),
               "all files verify", (sums.stdout or "")[-80:])

        # --- preserved calculator and claim plugin tools ----------------
        for tool, arguments, allowed in PLUGIN_CASES:
            doc = plugin_call(pkg, tool, arguments)
            record(f"pkg-tool-{tool}", doc.get("status") in allowed,
                   f"status in {sorted(allowed)}",
                   f"status={doc.get('status')} "
                   f"reason={doc.get('reason', '')}")

        # --- domain-pack tools: two structural and two decision lanes ----
        structural_path = pkg / "tools/anubis_program_verify.py"
        structural_relative = structural_path.relative_to(pkg).as_posix()
        structural_lines = structural_path.read_text(encoding="utf-8").splitlines()
        declaration_lines = [
            index
            for index, line in enumerate(structural_lines, 1)
            if line.startswith("def build_receipt(")
        ]
        structural_common = {
            "file_path": structural_relative,
            "file_sha256": sha_file(structural_path),
            "symbol": "build_receipt",
            "declaration_line": str(declaration_lines[0]),
            "declaration_count": str(len(declaration_lines)),
        }
        domain_cases = [
            ("jackal_test_exists", structural_common, "structural-exact"),
            (
                "jackal_claim_cites_test",
                {
                    "doc_path": "README.txt",
                    "doc_sha256": sha_file(pkg / "README.txt"),
                    "claim_text": "First run: shasum -a 256 -c SHA256SUMS",
                    "test_path": structural_relative,
                    "test_sha256": sha_file(structural_path),
                    "symbol": "build_receipt",
                },
                "structural-exact",
            ),
            (
                "jackal_decision_rank",
                {
                    "decision_id": "package_v173",
                    "criterion": "latency_ms",
                    "sense": "min",
                    "options": "alpha 120 beta 90",
                },
                "exact",
            ),
            (
                "jackal_decision_rank_v2",
                {
                    "decision_id": "package_v173_unit",
                    "criterion": "latency_ms",
                    "unit": "ms",
                    "sense": "min",
                    "options": "alpha 120 beta 90",
                },
                "exact",
            ),
        ]
        for tool, arguments, expected_status in domain_cases:
            document = plugin_call(pkg, tool, arguments)
            record(
                f"pkg-tool-{tool}",
                document.get("status") == expected_status,
                expected_status,
                f"status={document.get('status')} "
                f"reason={document.get('reason', '')}",
            )

        # --- all three Anubis program-evidence routes -------------------
        source, evidence, compiler_sha, artifact_sha, marker = make_v3_fixture(
            work / "program-fixture"
        )
        program_arguments = {
            "source_path": str(source),
            "evidence_dir": str(evidence),
            "expected_source_sha256": sha(source.read_bytes()),
            "expected_compiler_sha256": compiler_sha,
            "expected_artifact_sha256": artifact_sha,
            "expected_policy_sha256": POLICY_SHA256,
            "verification_time_unix": VERIFY_TIME,
            "profile": "inventory-safe-v1",
            "nonce": "package-parity",
        }
        program_verify = plugin_call(
            pkg, "jackal_anubis_verify_program", program_arguments
        )
        record(
            "pkg-tool-jackal_anubis_verify_program",
            program_verify.get("status") == "verified-program-evidence"
            and not marker.exists(),
            "verified-program-evidence without artifact execution",
            f"status={program_verify.get('status')} "
            f"reason={program_verify.get('reason', '')}",
        )
        program_receipt = program_verify.get("receipt")
        if isinstance(program_receipt, dict):
            replay_arguments = {
                **program_arguments,
                "receipt": program_receipt,
            }
            program_replay = plugin_call(
                pkg,
                "jackal_anubis_verify_program_receipt",
                replay_arguments,
            )
            record(
                "pkg-tool-jackal_anubis_verify_program_receipt",
                program_replay.get("status") == "verified-program-receipt"
                and not marker.exists(),
                "verified-program-receipt without artifact execution",
                f"status={program_replay.get('status')} "
                f"reason={program_replay.get('reason', '')}",
            )
        else:
            record(
                "pkg-tool-jackal_anubis_verify_program_receipt",
                False,
                "program receipt available",
                "verify returned no receipt",
            )

        echo_path = Path("/bin/echo")
        check_refusal = plugin_call(
            pkg,
            "jackal_anubis_check_program",
            {
                "source_path": str(source),
                "anubis_bin": str(echo_path),
                "expected_source_sha256": sha(source.read_bytes()),
                "expected_compiler_sha256": sha(echo_path.read_bytes()),
                "expected_policy_sha256": POLICY_SHA256,
                "verification_time_unix": VERIFY_TIME,
                "profile": "inventory-safe-v1",
                "nonce": "package-check-refusal",
                "out_root": str(work / "program-check-output"),
            },
        )
        record(
            "pkg-tool-jackal_anubis_check_program",
            check_refusal.get("status") == "refused"
            and check_refusal.get("reason") == "compiler-not-approved",
            "reachable named compiler-not-approved refusal",
            f"status={check_refusal.get('status')} "
            f"reason={check_refusal.get('reason', '')}",
        )

        direct_receipt = work / "package-program-receipt.json"
        direct_program = subprocess.run(
            [
                str(pkg / "jackal-anubis-program"),
                "verify",
                "--source",
                str(source),
                "--evidence-dir",
                str(evidence),
                "--expected-source-sha256",
                sha(source.read_bytes()),
                "--expected-compiler-sha256",
                compiler_sha,
                "--expected-artifact-sha256",
                artifact_sha,
                "--expected-policy-sha256",
                POLICY_SHA256,
                "--verification-time-unix",
                VERIFY_TIME,
                "--profile",
                "inventory-safe-v1",
                "--nonce",
                "package-parity-direct",
                "--emit-receipt",
                str(direct_receipt),
            ],
            capture_output=True,
            text=True,
            cwd=pkg,
            timeout=120,
        )
        record(
            "pkg-wrapper-jackal-anubis-program",
            direct_program.returncode == 0
            and "status=verified-program-evidence" in direct_program.stdout
            and direct_receipt.is_file()
            and not marker.exists(),
            "verified-program-evidence without artifact execution",
            (direct_program.stdout or direct_program.stderr)[:120].replace(
                "\n", " "
            ),
        )

        # verify_receipt round trip through the packaged plugin
        rb = plugin_call(pkg, "jackal_range_bound",
                         {"expression": "cos(x)", "input_lo": "0",
                          "input_hi": "1"})
        receipt = rb.get("receipt")
        if receipt:
            ver = plugin_call(pkg, "jackal_verify_receipt", {
                "receipt": receipt,
                "expected_release_epoch": "v1.7.2",
                "expected_command": "range-bound-cert",
                "expected_expression": "cos(x)",
                "expected_input_lo": "0",
                "expected_input_hi": "1"})
            record("pkg-tool-jackal_verify_receipt",
                   ver.get("status") == "verified", "verified",
                   f"status={ver.get('status')} reason={ver.get('reason', '')}")
        else:
            record("pkg-tool-jackal_verify_receipt", False,
                   "receipt available", "range_bound returned no receipt")

        # --- shell wrappers (10 release wrappers + 2 claim) ----------
        wrapper_cases = [
            ("jackal-int-cert-release",
             ["sin(x)", "0", "1", "1/100", "int-cert-parity-receipt.json"]),
            ("jackal-sqrt-rat-release", ["sqrt(x)", "2", "3"]),
            ("jackal-exp-rat-release", ["exp(x)", "0", "1"]),
            ("jackal-ln-rat-release", ["ln(x)", "2", "3"]),
            ("jackal-sin-rat-release", ["sin(x)", "0", "1"]),
            ("jackal-cos-rat-release", ["cos(x)", "0", "1"]),
            ("jackal-atan-rat-release", ["atan(x)", "0", "1"]),
            ("jackal-tanh-rat-release", ["1-2/(exp(2*x)+1)", "0", "1"]),
        ]
        for wrapper, argv in wrapper_cases:
            proc = subprocess.run([str(pkg / wrapper), *argv],
                                  capture_output=True, text=True,
                                  timeout=900, cwd=pkg)
            ok = proc.returncode == 0 and \
                "status=formal-bounded" in (proc.stdout or "")
            record(f"pkg-wrapper-{wrapper}", ok, "formal-bounded",
                   (proc.stdout or proc.stderr)[:80].replace("\n", " "))

        receipt_path = work / "wrapped-receipt.json"
        proc = subprocess.run(
            [str(pkg / "jackal-cert-release"), "x^2+1", "1", "2",
             str(receipt_path)],
            capture_output=True, text=True, timeout=900, cwd=pkg)
        record("pkg-wrapper-jackal-cert-release",
               proc.returncode == 0 and receipt_path.exists(),
               "receipt emitted",
               (proc.stdout or proc.stderr)[:80].replace("\n", " "))

        greceipt = work / "gaussian-receipt.json"
        proc = subprocess.run(
            [str(pkg / "jackal-gaussian-release"), GAUSSIAN_EXPR, "0",
             "1", "1/1000000000000", str(greceipt)],
            capture_output=True, text=True, timeout=900, cwd=pkg)
        record("pkg-wrapper-jackal-gaussian-release",
               proc.returncode == 0 and greceipt.exists(),
               "receipt emitted",
               (proc.stdout or proc.stderr)[:80].replace("\n", " "))

        if receipt_path.exists():
            manifest = (pkg / "MANIFEST.sha256").read_text()
            rows = {line.split()[0]: line.split()[-1]
                    for line in manifest.splitlines()
                    if line.strip() and not line.startswith("#")}
            proc = subprocess.run(
                [str(pkg / "jackal-receipt-verify"),
                 "--receipt", str(receipt_path),
                 "--checker", str(pkg / "jackal_cert_check"),
                 "--expected-evaluator", rows["evaluator"],
                 "--expected-checker", rows["checker"],
                 "--expected-source", rows["source"],
                 "--expected-release-epoch", "v1.7.2",
                 "--expected-command", "range-bound-cert",
                 "--expected-expression", "x^2+1",
                 "--expected-input-lo", "1", "--expected-input-hi", "2",
                 "--inventory", str(pkg / "formal_coverage_inventory.json"),
                 "--expected-inventory", rows["coverage_inventory"],
                 "--proof-identity", str(pkg / "range_proof_identity.json"),
                 "--expected-proof-identity-file",
                 rows["range_proof_identity"],
                 "--expected-proof-identity-digest",
                 rows["range_proof_digest"]],
                capture_output=True, text=True, timeout=900, cwd=pkg)
            record("pkg-wrapper-jackal-receipt-verify",
                   proc.returncode == 0
                   and "status=verified verdict=ACCEPT"
                   in (proc.stdout or ""),
                   "verified ACCEPT",
                   (proc.stdout or proc.stderr)[:80].replace("\n", " "))
        else:
            record("pkg-wrapper-jackal-receipt-verify", False,
                   "receipt available", "cert-release emitted nothing")

        # --- three-way parity: repo CLI, package CLI, plugin ---------
        repo_bundle = cli_route(ROOT / "jackal-claim", work, "repo")
        pkg_bundle = cli_route(pkg / "jackal-claim", work, "pkg")
        plugin_doc = plugin_call(pkg, "jackal_claim",
                                 {"request": REQUEST})
        plugin_bundle = plugin_doc.get("bundle") or {}
        triples = {
            "repo": (repo_bundle or {}).get("bundle_digest_sha256", ""),
            "pkg": (pkg_bundle or {}).get("bundle_digest_sha256", ""),
            "plugin": plugin_bundle.get("bundle_digest_sha256", ""),
        }
        ok = len(set(triples.values())) == 1 and all(triples.values())
        record("pkg-three-way-parity", ok,
               "identical bundle digest across repo/pkg/plugin",
               json.dumps({k: v[:16] for k, v in triples.items()}))

        if ok:
            root_node = next(n for n in pkg_bundle["nodes"]
                             if n["id"] == pkg_bundle["root"])
            prop_path = work / "prop.json"
            prop_path.write_text(json.dumps(root_node["proposition"],
                                            sort_keys=True))
            policy_sha = hashlib.sha256(
                canon(pkg_bundle["policy"])).hexdigest()
            bundle_path = work / "bundle-pkg.json"
            proc = subprocess.run(
                [str(pkg / "jackal-claim-verify"),
                 "--bundle", str(bundle_path),
                 "--expected-release-epoch", "v1.6.0",
                 "--expected-root-proposition", str(prop_path),
                 "--expected-policy-sha256", policy_sha,
                 "--verification-time-unix", "1786752000"],
                capture_output=True, text=True, timeout=900, cwd=pkg)
            record("pkg-claim-verify-verified",
                   proc.returncode == 0
                   and "claim-verify=verified" in (proc.stdout or ""),
                   "claim-verify=verified",
                   (proc.stdout or proc.stderr)[:100].replace("\n", " "))

            tampered = json.loads(bundle_path.read_text())
            tampered["nodes"][0]["proposition"]["set"]["hi"] = "5"
            tpath = work / "bundle-tampered.json"
            tpath.write_text(json.dumps(tampered, indent=1,
                                        sort_keys=True))
            proc = subprocess.run(
                [str(pkg / "jackal-claim-verify"),
                 "--bundle", str(tpath),
                 "--expected-release-epoch", "v1.6.0",
                 "--expected-root-proposition", str(prop_path),
                 "--expected-policy-sha256", policy_sha,
                 "--verification-time-unix", "1786752000"],
                capture_output=True, text=True, timeout=900, cwd=pkg)
            record("pkg-claim-verify-tamper-refuses",
                   proc.returncode != 0
                   and "reason=node-id-mismatch" in (proc.stdout or ""),
                   "refused/node-id-mismatch",
                   (proc.stdout or proc.stderr)[:100].replace("\n", " "))
        else:
            record("pkg-claim-verify-verified", False, "parity first",
                   "skipped")
            record("pkg-claim-verify-tamper-refuses", False,
                   "parity first", "skipped")

    return finish()


def finish() -> int:
    failures = [r for r in ROWS if not r["ok"]]
    print(f"CLAIM_PACKAGE_PARITY_{'PASS' if not failures else 'FAIL'} "
          f"rows={len(ROWS)} failures={len(failures)}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
