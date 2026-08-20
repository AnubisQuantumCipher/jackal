#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERIFIER = ROOT / "tools/anubis_program_verify.py"
POLICY_PATH = ROOT / "release/program/inventory_safe_v1.json"
VERIFY_TIME = "1787097600"
APPROVED_CHECK_COMPILER_SHA256 = (
    "0d6a8f89355eb9ec5971749daf943567c204ed9f2d3001edbd46599f4540d7d6"
)
APPROVED_Z3_SHA256 = (
    "ae6c8df33db9c9ae9a80b6044e77cd66529a141d8b25f0620f1e89b409594f48"
)
REQUIRED_STAGES = [
    "parse",
    "typecheck",
    "monomorphization",
    "policy-effects",
    "policy-capability",
    "policy-information-flow",
    "policy-declassification",
    "symbolic",
    "solver",
    "source-binding",
    "artifact-binding",
    "evidence-closure",
]
REQUIRED_CONSUMERS = [
    "effects",
    "capability",
    "information-flow",
    "declassification",
    "mode",
    "contracts",
]
PRODUCER_RESIDUALS = [
    "no-source-to-vc-proof",
    "no-smt-to-cnf-proof",
    "no-source-native-refinement",
    "no-universal-language-soundness",
    "policy-semantics-producer-attested",
    "runtime-not-observed",
    "derived-confinement-is-not-os-enforcement",
]
RECEIPT_RESIDUALS = [
    *PRODUCER_RESIDUALS,
    "policy-construct-totality-not-established",
]
POLICY_BODY = {
    "schema": "jackal-anubis-program-policy-v1",
    "profile": "inventory-safe-v1",
    "mode": "safe",
    "source_leaves": 1,
    "minimum_obligations": 1,
    "proof_kinds": ["rup_refutation"],
    "required_stages": REQUIRED_STAGES,
    "required_consumers": REQUIRED_CONSUMERS,
    "approved_check_compiler_sha256": APPROVED_CHECK_COMPILER_SHA256,
    "approved_z3_sha256": APPROVED_Z3_SHA256,
    "runtime_execution": False,
    "policy_inventory_authority": "producer-attested-function-roster",
    "independent_policy_construct_totality": False,
    "receipt_residual_non_claims": RECEIPT_RESIDUALS,
}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def compact(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


POLICY_SHA256 = sha(compact(POLICY_BODY))


def dump(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def reseal(evidence: Path) -> None:
    rows = []
    for path in sorted(evidence.rglob("*")):
        if path.is_file() and path.name != "MANIFEST.sha256":
            relative = path.relative_to(evidence).as_posix()
            rows.append(f"{sha(path.read_bytes())}  {relative}\n")
    (evidence / "MANIFEST.sha256").write_text("".join(rows), encoding="ascii")


def _summary_hashes(evidence: Path) -> dict[str, str]:
    return {
        "build_log_hash": sha((evidence / "build.log").read_bytes()),
        "environment_hash": sha((evidence / "environment.json").read_bytes()),
        "source_tree_hash": sha((evidence / "source-tree.json").read_bytes()),
        "sarif_hash": sha((evidence / "checks.sarif").read_bytes()),
        "bounty_report_hash": sha((evidence / "bounty-report.md").read_bytes()),
    }


def make_v3_fixture(root: Path) -> tuple[Path, Path, str, str, Path]:
    root.mkdir(parents=True, exist_ok=True)
    source = root / "main.anb"
    source.write_text(
        "fn id(x: i64) -> i64 ensures(result == x) { return x; }\n"
        "fn main() { assert(id(7) == 7); }\n",
        encoding="utf-8",
    )
    marker = root / "ARTIFACT_EXECUTED"
    evidence = root / "evidence"
    proof_dir = evidence / "analysis" / "proofs"
    proof_dir.mkdir(parents=True)
    (evidence / "source.anubis").write_bytes(source.read_bytes())
    artifact = evidence / "artifact"
    artifact.write_text(
        f"#!/bin/sh\nprintf executed > {marker}\n", encoding="utf-8"
    )
    artifact.chmod(0o755)

    function = {
        "effects": [],
        "mode": "safe",
        "module": None,
        "name": "id",
        "params": [],
        "span": [0, 60],
        "symbols": [],
    }
    function_id = sha(compact(function))
    hir = {"functions": [function], "imports": [], "modules": []}
    mir: list[object] = []
    taint: list[object] = []
    mono: list[object] = []
    smt = "(set-logic QF_BV)\n(assert false)\n(check-sat)\n(get-model)\n"
    obligation_name = "ensures:id"
    solver = [
        {
            "detail": "proved",
            "model": None,
            "name": obligation_name,
            "smt": smt,
            "status": "PASS",
        }
    ]
    dump(evidence / "hir.json", hir)
    dump(evidence / "mir.json", mir)
    dump(evidence / "taint-traces.json", taint)
    dump(evidence / "mono_specializations.json", mono)
    dump(evidence / "solver.json", solver)
    (proof_dir / "obligation_0000.smt2").write_text(smt, encoding="utf-8")
    (proof_dir / "obligation_0000.cnf").write_text(
        "p cnf 1 2\n1 0\n-1 0\n", encoding="ascii"
    )
    (proof_dir / "obligation_0000.drat").write_text("0\n", encoding="ascii")
    proof_row = {
        "obligation": obligation_name,
        "status": "PASS",
        "proof": "rup_refutation",
        "smt": "analysis/proofs/obligation_0000.smt2",
        "cnf_dimacs": "analysis/proofs/obligation_0000.cnf",
        "proof_drat": "analysis/proofs/obligation_0000.drat",
        "num_vars": 1,
        "num_clauses": 2,
        "steps": 1,
        "checker": "test-rup-checker",
        "checker_version": "1",
        "replay": "test-rup-replay",
    }
    dump(
        evidence / "analysis/proofs.json",
        {"note": "test", "obligations": [proof_row]},
    )

    stable_obligation = {
        "name": obligation_name,
        "smt_sha256": sha((proof_dir / "obligation_0000.smt2").read_bytes()),
        "cnf_sha256": sha((proof_dir / "obligation_0000.cnf").read_bytes()),
        "proof_sha256": sha((proof_dir / "obligation_0000.drat").read_bytes()),
    }
    obligation_id = sha(compact(stable_obligation))
    compiler_sha = "a" * 64
    artifact_sha = sha(artifact.read_bytes())
    consumers = []
    for consumer_id in ("effects", "capability", "information-flow"):
        consumers.append(
            {
                "id": consumer_id,
                "status": "PASS",
                "authority": "anubis-typecheck-producer-attested",
                "subjects": [function_id],
            }
        )
    consumers.append(
        {
            "id": "declassification",
            "status": "PASS",
            "authority": "anubis-source-walker-producer-attested",
            "subjects": {"count": 0},
        }
    )
    consumers.append(
        {
            "id": "mode",
            "status": "PASS",
            "authority": "anubis-typecheck-producer-attested",
            "subjects": [function_id],
        }
    )
    consumers.append(
        {
            "id": "contracts",
            "status": "PASS",
            "authority": "anubis-typecheck-producer-attested",
            "subjects": {"solver_obligation_count": 1},
        }
    )
    program = {
        "schema": "anubis.program-evidence.v3",
        "version": 3,
        "mode": "safe",
        "source": {
            "path": "source.anubis",
            "sha256": sha(source.read_bytes()),
            "merkle": sha(source.read_bytes()),
            "bytes": len(source.read_bytes()),
        },
        "compiler": {
            "tool": "anubis 0.1.0",
            "path_basename": "anubis",
            "sha256": compiler_sha,
        },
        "artifacts": {
            "hir": {
                "path": "hir.json",
                "sha256": sha((evidence / "hir.json").read_bytes()),
                "bytes": (evidence / "hir.json").stat().st_size,
            },
            "mir": {
                "path": "mir.json",
                "sha256": sha((evidence / "mir.json").read_bytes()),
                "bytes": (evidence / "mir.json").stat().st_size,
            },
            "taint": {
                "path": "taint-traces.json",
                "sha256": sha((evidence / "taint-traces.json").read_bytes()),
                "bytes": (evidence / "taint-traces.json").stat().st_size,
            },
            "solver": {
                "path": "solver.json",
                "sha256": sha((evidence / "solver.json").read_bytes()),
                "bytes": (evidence / "solver.json").stat().st_size,
            },
            "monomorphization": {
                "path": "mono_specializations.json",
                "sha256": sha((evidence / "mono_specializations.json").read_bytes()),
                "bytes": (evidence / "mono_specializations.json").stat().st_size,
            },
            "native": {"path": "artifact", "sha256": artifact_sha},
        },
        "stages": [
            {"id": value, "status": "PASS", "authority": "test"}
            for value in REQUIRED_STAGES
        ],
        "solver_inventory": {
            "count": 1,
            "obligations": [
                {
                    "id": obligation_id,
                    "name": obligation_name,
                    "status": "PASS",
                    "proof_kind": "rup_refutation",
                    "smt_path": proof_row["smt"],
                    "smt_sha256": stable_obligation["smt_sha256"],
                    "cnf_path": proof_row["cnf_dimacs"],
                    "cnf_sha256": stable_obligation["cnf_sha256"],
                    "proof_path": proof_row["proof_drat"],
                    "proof_sha256": stable_obligation["proof_sha256"],
                    "num_vars": 1,
                    "num_clauses": 2,
                    "steps": 1,
                    "checker": "test-rup-checker",
                    "checker_version": "1",
                }
            ],
        },
        "policy_inventory": {
            "functions": [
                {
                    "id": function_id,
                    "name": "id",
                    "module": None,
                    "mode": "safe",
                    "effects": [],
                    "param_count": 0,
                    "symbol_count": 0,
                }
            ],
            "consumers": consumers,
            "capabilities_present_count": 0,
            "taint_trace_count": 0,
            "monomorphization_count": 0,
            "mir_function_count": 0,
        },
        "residual_non_claims": PRODUCER_RESIDUALS,
    }
    dump(evidence / "program-evidence.json", program)
    (evidence / "build.log").write_text("synthetic build log\n", encoding="utf-8")
    (evidence / "bounty-report.md").write_text("# Synthetic report\n", encoding="utf-8")
    (evidence / "validate.sh").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    (evidence / "program.entitlements").write_text("<plist/>\n", encoding="utf-8")
    (evidence / "analysis/solver.smt2").write_text(smt, encoding="utf-8")
    dump(
        evidence / "analysis/solver_replay.json",
        {"replay_valid": True, "status": "counterexample_replayed"},
    )
    dump(evidence / "checks.sarif", {"runs": [], "version": "2.1.0"})
    dump(evidence / "confinement_manifest.json", {"capabilities_present": []})
    dump(evidence / "declassify_audit.json", {"declassifications": []})
    dump(evidence / "entitlement_profile.json", {"entitlements": []})
    dump(evidence / "environment.json", {"anubis": "0.1.0"})
    dump(evidence / "source-tree.json", [])
    dump(evidence / "summaries.json", {"functions": []})

    summary_hashes = _summary_hashes(evidence)
    source_hash = sha(source.read_bytes())
    build_log_hash = summary_hashes["build_log_hash"]
    check_details = {
        "source_hash": source_hash,
        "build_log_hash": build_log_hash,
        "artifact_hash": artifact_sha,
    }
    checks = [
        {
            "name": value,
            "status": "PASS",
            "detail": check_details.get(value, "test"),
        }
        for value in (
            "parse",
            "typecheck",
            "monomorphization",
            "symbolic",
            "solver",
            "source_hash",
            "build_log_hash",
            "artifact",
            "artifact_hash",
        )
    ]
    manifest_summary = sha(
        f"{source_hash}:{build_log_hash}:{summary_hashes['source_tree_hash']}:PASS".encode()
    )
    evidence_summary = {
        "timestamp": "test",
        "tool": "anubis 0.1.0",
        "mode": "safe",
        "source_hash": source_hash,
        "build_log_hash": build_log_hash,
        "artifact_hash": artifact_sha,
        "lane": "safe",
        **summary_hashes,
        "manifest_sha256": manifest_summary,
        "checks": checks,
        "verdict": "PASS",
        "security": {"mode": "safe", "note": "test"},
    }
    dump(evidence / "evidence.json", evidence_summary)
    dump(evidence / "manifest.json", evidence_summary)
    dump(
        evidence / "pca.json",
        {
            "pca_version": 2,
            "source_sha256": source_hash,
            "mode": "safe",
            "tier": "checked",
            "rejection": None,
            "parse_ok": True,
            "typecheck_ok": True,
            "solver_obligations": 1,
            "solver_all_discharged": True,
            "solver_backend": "z3",
            "zk_present": False,
            "zk_image_id": None,
            "zk_receipt_sha256": None,
            "zk_journal_sha256": None,
            "verdict": "PASS",
            "tool": "anubis 0.1.0",
        },
    )
    reseal(evidence)
    return source, evidence, compiler_sha, artifact_sha, marker


def run_verify(
    source: Path,
    evidence: Path,
    compiler_sha: str,
    artifact_sha: str | None = None,
    *,
    profile: str = "inventory-safe-v1",
    expected_source_sha256: str | None = None,
    expected_policy_sha256: str = POLICY_SHA256,
) -> subprocess.CompletedProcess[str]:
    command = [
        sys.executable,
        "-I",
        "-S",
        "-B",
        str(VERIFIER),
        "verify",
        "--source",
        str(source),
        "--evidence-dir",
        str(evidence),
        "--expected-source-sha256",
        expected_source_sha256 or sha(source.read_bytes()),
        "--expected-compiler-sha256",
        compiler_sha,
        "--expected-policy-sha256",
        expected_policy_sha256,
        "--verification-time-unix",
        VERIFY_TIME,
        "--profile",
        profile,
        "--nonce",
        "test-nonce",
    ]
    if artifact_sha is not None:
        command += ["--expected-artifact-sha256", artifact_sha]
    return subprocess.run(
        command, capture_output=True, text=True, cwd=ROOT, timeout=30
    )


class AnubisProgramVerifierTest(unittest.TestCase):
    def test_surface_uses_honestly_weaker_inventory_profile(self) -> None:
        self.assertTrue(VERIFIER.is_file(), VERIFIER)
        self.assertTrue(POLICY_PATH.is_file(), POLICY_PATH)
        policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
        self.assertEqual(policy["profile"], "inventory-safe-v1")
        self.assertIs(policy["independent_policy_construct_totality"], False)
        self.assertEqual(policy["policy_digest_sha256"], POLICY_SHA256)
        self.assertEqual(
            {key: value for key, value in policy.items() if key != "policy_digest_sha256"},
            POLICY_BODY,
        )

    def test_pca_v2_refuses_as_insufficient_for_program_evidence_status(self) -> None:
        with tempfile.TemporaryDirectory(prefix="jackal-program-v2-") as td:
            root = Path(td)
            source = root / "main.anb"
            source.write_text("fn main() { assert(true); }\n", encoding="utf-8")
            evidence = root / "evidence"
            evidence.mkdir()
            (evidence / "source.anubis").write_bytes(source.read_bytes())
            dump(evidence / "pca.json", {"pca_version": 2, "verdict": "PASS"})
            reseal(evidence)
            result = run_verify(source, evidence, "0" * 64)
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn("reason=unsupported-program-evidence-version", result.stdout)

    def test_v3_inventory_profile_verifies_replays_and_never_executes_artifact(self) -> None:
        with tempfile.TemporaryDirectory(prefix="jackal-program-v3-") as td:
            source, evidence, compiler_sha, artifact_sha, marker = make_v3_fixture(
                Path(td)
            )
            receipt = Path(td) / "receipt.json"
            command = [
                sys.executable,
                "-I",
                "-S",
                "-B",
                str(VERIFIER),
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
                "test-nonce",
                "--emit-receipt",
                str(receipt),
            ]
            emitted = subprocess.run(
                command, capture_output=True, text=True, cwd=ROOT, timeout=30
            )
            self.assertEqual(emitted.returncode, 0, emitted.stdout + emitted.stderr)
            self.assertFalse(marker.exists(), "compiled artifact was executed")
            document = json.loads(receipt.read_text(encoding="utf-8"))
            self.assertEqual(document["status"], "verified-program-evidence")
            self.assertEqual(document["profile"], "inventory-safe-v1")
            self.assertEqual(document["proof_replay"]["verified"], 1)
            self.assertEqual(
                document["assurance"]["policy_construct_totality"],
                "not-established",
            )
            self.assertEqual(document["assurance"]["smt_to_cnf"], "open")
            self.assertEqual(document["assurance"]["source_to_vc"], "open")
            self.assertEqual(document["assurance"]["runtime"], "not-observed")
            self.assertEqual(document["residual_non_claims"], RECEIPT_RESIDUALS)

            replay = subprocess.run(
                [
                    sys.executable,
                    "-I",
                    "-S",
                    "-B",
                    str(VERIFIER),
                    "verify-receipt",
                    "--receipt",
                    str(receipt),
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
                    "test-nonce",
                ],
                capture_output=True,
                text=True,
                cwd=ROOT,
                timeout=30,
            )
            self.assertEqual(replay.returncode, 0, replay.stdout + replay.stderr)
            self.assertIn("status=verified-program-receipt", replay.stdout)
            self.assertFalse(marker.exists(), "receipt replay executed artifact")

    def test_plugin_program_success_statuses_exit_zero(self) -> None:
        with tempfile.TemporaryDirectory(prefix="jackal-program-plugin-") as td:
            source, evidence, compiler_sha, artifact_sha, marker = make_v3_fixture(
                Path(td)
            )
            arguments = {
                "source_path": str(source),
                "evidence_dir": str(evidence),
                "expected_source_sha256": sha(source.read_bytes()),
                "expected_compiler_sha256": compiler_sha,
                "expected_artifact_sha256": artifact_sha,
                "expected_policy_sha256": POLICY_SHA256,
                "verification_time_unix": VERIFY_TIME,
                "profile": "inventory-safe-v1",
                "nonce": "plugin-exit",
            }
            launcher = ROOT / "plugin/hermes/jackal_hermes"
            verified = subprocess.run(
                [
                    str(launcher),
                    "call",
                    "jackal_anubis_verify_program",
                    json.dumps(arguments),
                ],
                capture_output=True,
                text=True,
                cwd=ROOT,
                timeout=30,
            )
            self.assertEqual(
                verified.returncode, 0, verified.stdout + verified.stderr
            )
            document = json.loads(verified.stdout)
            self.assertEqual(document["status"], "verified-program-evidence")
            replay = subprocess.run(
                [
                    str(launcher),
                    "call",
                    "jackal_anubis_verify_program_receipt",
                    json.dumps({**arguments, "receipt": document["receipt"]}),
                ],
                capture_output=True,
                text=True,
                cwd=ROOT,
                timeout=30,
            )
            self.assertEqual(replay.returncode, 0, replay.stdout + replay.stderr)
            self.assertEqual(
                json.loads(replay.stdout)["status"], "verified-program-receipt"
            )
            self.assertFalse(marker.exists(), "plugin executed compiled artifact")

    def test_each_caller_identity_pin_mismatch_refuses(self) -> None:
        with tempfile.TemporaryDirectory(prefix="jackal-program-pins-") as td:
            source, evidence, compiler_sha, artifact_sha, _ = make_v3_fixture(
                Path(td)
            )
            cases = {
                "source-pin-mismatch": {
                    "compiler_sha": compiler_sha,
                    "artifact_sha": artifact_sha,
                    "expected_source_sha256": "f" * 64,
                },
                "compiler-pin-mismatch": {
                    "compiler_sha": "f" * 64,
                    "artifact_sha": artifact_sha,
                },
                "artifact-pin-mismatch": {
                    "compiler_sha": compiler_sha,
                    "artifact_sha": "f" * 64,
                },
                "policy-pin-mismatch": {
                    "compiler_sha": compiler_sha,
                    "artifact_sha": artifact_sha,
                    "expected_policy_sha256": "f" * 64,
                },
            }
            for reason, values in cases.items():
                with self.subTest(reason=reason):
                    result = run_verify(source, evidence, **values)
                    self.assertEqual(
                        result.returncode, 1, result.stdout + result.stderr
                    )
                    self.assertIn(f"reason={reason}", result.stdout)

    def test_contracted_safe_profile_is_not_silently_inherited(self) -> None:
        with tempfile.TemporaryDirectory(prefix="jackal-program-profile-") as td:
            source, evidence, compiler_sha, artifact_sha, _ = make_v3_fixture(Path(td))
            result = run_verify(
                source,
                evidence,
                compiler_sha,
                artifact_sha,
                profile="contracted-safe-v1",
            )
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn("reason=profile-unsupported", result.stdout)

    def test_program_inventory_without_producer_summaries_refuses(self) -> None:
        with tempfile.TemporaryDirectory(prefix="jackal-program-producerless-") as td:
            source, evidence, compiler_sha, artifact_sha, _ = make_v3_fixture(Path(td))
            (evidence / "evidence.json").unlink()
            (evidence / "pca.json").unlink()
            reseal(evidence)
            result = run_verify(source, evidence, compiler_sha, artifact_sha)
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn("reason=bundle-file-roster", result.stdout)

    def test_summary_hash_laundering_refuses_after_consistent_reseal(self) -> None:
        with tempfile.TemporaryDirectory(prefix="jackal-program-summary-") as td:
            source, evidence, compiler_sha, artifact_sha, _ = make_v3_fixture(Path(td))
            summary_path = evidence / "evidence.json"
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            summary["build_log_hash"] = "0" * 64
            dump(summary_path, summary)
            dump(evidence / "manifest.json", summary)
            reseal(evidence)
            result = run_verify(source, evidence, compiler_sha, artifact_sha)
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn("reason=producer-evidence-mismatch", result.stdout)


if __name__ == "__main__":
    unittest.main()
