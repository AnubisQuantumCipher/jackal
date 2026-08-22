#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from pathlib import Path

from anubis_program_verifier_test import make_v3_fixture, reseal, run_verify

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "release/evidence/anubis_program_hostile_v1.json"
ROWS: list[dict] = []


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def dump(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def record(name: str, ok: bool, observed: str) -> None:
    ROWS.append({"id": name, "ok": ok, "observed": observed[:300]})
    print(f"{'PASS' if ok else 'FAIL'} {name} {observed[:160]}")


def reason(result) -> str:
    text = result.stdout + result.stderr
    marker = "reason="
    return text.split(marker, 1)[1].split()[0] if marker in text else text[:80]


def run_case(name: str, mutate, expected: str) -> None:
    with tempfile.TemporaryDirectory(prefix=f"jackal-program-{name}-") as td:
        source, pristine, compiler_sha, artifact_sha, _marker = make_v3_fixture(
            Path(td) / "a"
        )
        clean = run_verify(source, pristine, compiler_sha, artifact_sha)
        poisoned = Path(td) / "b"
        shutil.copytree(pristine, poisoned, symlinks=True)
        mutate(source, poisoned, compiler_sha, artifact_sha)
        bad = run_verify(source, poisoned, compiler_sha, artifact_sha)
        shutil.rmtree(poisoned)
        shutil.copytree(pristine, poisoned, symlinks=True)
        restored = run_verify(source, poisoned, compiler_sha, artifact_sha)
        observed = reason(bad)
        record(
            name,
            clean.returncode == 0
            and bad.returncode == 1
            and observed == expected
            and restored.returncode == 0,
            f"bad={observed} A2={restored.returncode}",
        )


def main() -> int:
    def refresh_solver_artifact(evidence: Path, program: dict) -> None:
        solver_path = evidence / "solver.json"
        program["artifacts"]["solver"]["sha256"] = sha(solver_path.read_bytes())
        program["artifacts"]["solver"]["bytes"] = solver_path.stat().st_size

    def refresh_obligation_id(row: dict) -> None:
        stable = {
            "name": row["name"],
            "smt_sha256": row["smt_sha256"],
            "cnf_sha256": row["cnf_sha256"],
            "proof_sha256": row["proof_sha256"],
        }
        row["id"] = sha(
            json.dumps(stable, sort_keys=True, separators=(",", ":")).encode()
        )

    def stage_partial(_source, evidence, _compiler, _artifact):
        path = evidence / "program-evidence.json"
        value = json.loads(path.read_text())
        value["stages"][5]["status"] = "PARTIAL"
        dump(path, value)
        reseal(evidence)

    def consumer_omitted(_source, evidence, _compiler, _artifact):
        path = evidence / "program-evidence.json"
        value = json.loads(path.read_text())
        value["policy_inventory"]["consumers"].pop(1)
        dump(path, value)
        reseal(evidence)

    def rup_lie(_source, evidence, _compiler, _artifact):
        cnf = evidence / "analysis/proofs/obligation_0000.cnf"
        cnf.write_text("p cnf 1 1\n1 0\n")
        program_path = evidence / "program-evidence.json"
        program = json.loads(program_path.read_text())
        row = program["solver_inventory"]["obligations"][0]
        row["cnf_sha256"] = sha(cnf.read_bytes())
        stable = {
            "name": row["name"],
            "smt_sha256": row["smt_sha256"],
            "cnf_sha256": row["cnf_sha256"],
            "proof_sha256": row["proof_sha256"],
        }
        row["id"] = sha(json.dumps(stable, sort_keys=True, separators=(",", ":")).encode())
        dump(program_path, program)
        reseal(evidence)

    def extra_file(_source, evidence, _compiler, _artifact):
        (evidence / "green-looking-extra.json").write_text("{}\n")
        reseal(evidence)

    def zero_obligations(_source, evidence, _compiler, _artifact):
        dump(evidence / "solver.json", [])
        dump(evidence / "analysis/proofs.json", {"note": "forged empty", "obligations": []})
        program_path = evidence / "program-evidence.json"
        program = json.loads(program_path.read_text())
        program["artifacts"]["solver"]["sha256"] = sha((evidence / "solver.json").read_bytes())
        program["artifacts"]["solver"]["bytes"] = (evidence / "solver.json").stat().st_size
        program["solver_inventory"] = {"count": 0, "obligations": []}
        for consumer in program["policy_inventory"]["consumers"]:
            if consumer["id"] == "contracts":
                consumer["subjects"] = {"solver_obligation_count": 0}
        dump(program_path, program)
        for path in (evidence / "analysis/proofs").iterdir():
            path.unlink()
        reseal(evidence)

    def symlink_hir(_source, evidence, _compiler, _artifact):
        hir = evidence / "hir.json"
        copy = evidence.parent / "outside-hir.json"
        copy.write_bytes(hir.read_bytes())
        hir.unlink()
        hir.symlink_to(copy)
        reseal(evidence)

    def producer_verdict_launder(_source, evidence, _compiler, _artifact):
        path = evidence / "evidence.json"
        value = json.loads(path.read_text())
        value["verdict"] = "FAIL"
        dump(path, value)
        reseal(evidence)

    def solver_smt_decouple(_source, evidence, _compiler, _artifact):
        solver_path = evidence / "solver.json"
        solver = json.loads(solver_path.read_text())
        solver[0]["smt"] += "(assert true)\n"
        dump(solver_path, solver)
        program_path = evidence / "program-evidence.json"
        program = json.loads(program_path.read_text())
        refresh_solver_artifact(evidence, program)
        dump(program_path, program)
        reseal(evidence)

    def proof_path_reuse(_source, evidence, _compiler, _artifact):
        solver_path = evidence / "solver.json"
        solver = json.loads(solver_path.read_text())
        second_solver = dict(solver[0])
        second_solver["name"] = "ensures:id-duplicate-proof"
        solver.append(second_solver)
        dump(solver_path, solver)

        proof_index_path = evidence / "analysis/proofs.json"
        proof_index = json.loads(proof_index_path.read_text())
        second_proof = dict(proof_index["obligations"][0])
        second_proof["obligation"] = second_solver["name"]
        proof_index["obligations"].append(second_proof)
        dump(proof_index_path, proof_index)

        program_path = evidence / "program-evidence.json"
        program = json.loads(program_path.read_text())
        second_row = dict(program["solver_inventory"]["obligations"][0])
        second_row["name"] = second_solver["name"]
        refresh_obligation_id(second_row)
        program["solver_inventory"]["obligations"].append(second_row)
        program["solver_inventory"]["count"] = 2
        for consumer in program["policy_inventory"]["consumers"]:
            if consumer["id"] == "contracts":
                consumer["subjects"] = {"solver_obligation_count": 2}
        refresh_solver_artifact(evidence, program)
        dump(program_path, program)
        reseal(evidence)

    def proof_tuple_reuse(_source, evidence, _compiler, _artifact):
        proof_dir = evidence / "analysis/proofs"
        for suffix in ("smt2", "cnf", "drat"):
            shutil.copy2(
                proof_dir / f"obligation_0000.{suffix}",
                proof_dir / f"obligation_0001.{suffix}",
            )
        solver_path = evidence / "solver.json"
        solver = json.loads(solver_path.read_text())
        second_solver = dict(solver[0])
        second_solver["name"] = "ensures:id-duplicate-bytes"
        solver.append(second_solver)
        dump(solver_path, solver)

        proof_index_path = evidence / "analysis/proofs.json"
        proof_index = json.loads(proof_index_path.read_text())
        second_proof = dict(proof_index["obligations"][0])
        second_proof["obligation"] = second_solver["name"]
        second_proof["smt"] = "analysis/proofs/obligation_0001.smt2"
        second_proof["cnf_dimacs"] = "analysis/proofs/obligation_0001.cnf"
        second_proof["proof_drat"] = "analysis/proofs/obligation_0001.drat"
        proof_index["obligations"].append(second_proof)
        dump(proof_index_path, proof_index)

        program_path = evidence / "program-evidence.json"
        program = json.loads(program_path.read_text())
        second_row = dict(program["solver_inventory"]["obligations"][0])
        second_row["name"] = second_solver["name"]
        second_row["smt_path"] = second_proof["smt"]
        second_row["cnf_path"] = second_proof["cnf_dimacs"]
        second_row["proof_path"] = second_proof["proof_drat"]
        refresh_obligation_id(second_row)
        program["solver_inventory"]["obligations"].append(second_row)
        program["solver_inventory"]["count"] = 2
        for consumer in program["policy_inventory"]["consumers"]:
            if consumer["id"] == "contracts":
                consumer["subjects"] = {"solver_obligation_count": 2}
        refresh_solver_artifact(evidence, program)
        dump(program_path, program)
        reseal(evidence)

    def manifest_missing(_source, evidence, _compiler, _artifact):
        (evidence / "MANIFEST.sha256").unlink()

    def missing_canonical_file(_source, evidence, _compiler, _artifact):
        (evidence / "checks.sarif").unlink()
        reseal(evidence)

    def multi_source_launder(_source, evidence, _compiler, _artifact):
        path = evidence / "program-evidence.json"
        value = json.loads(path.read_text())
        value["source"]["merkle"] = "f" * 64
        dump(path, value)
        reseal(evidence)

    def z3_trailing_error(_source, evidence, _compiler, _artifact):
        smt_path = evidence / "analysis/proofs/obligation_0000.smt2"
        smt_path.write_text(smt_path.read_text() + "(bad-command)\n")
        solver_path = evidence / "solver.json"
        solver = json.loads(solver_path.read_text())
        solver[0]["smt"] = smt_path.read_text()
        dump(solver_path, solver)
        program_path = evidence / "program-evidence.json"
        program = json.loads(program_path.read_text())
        row = program["solver_inventory"]["obligations"][0]
        row["smt_sha256"] = sha(smt_path.read_bytes())
        refresh_obligation_id(row)
        refresh_solver_artifact(evidence, program)
        dump(program_path, program)
        reseal(evidence)

    run_case("stage-partial", stage_partial, "stage-not-pass")
    run_case("consumer-omitted", consumer_omitted, "policy-consumer-roster")
    run_case("consistent-rup-lie", rup_lie, "rup-replay-failed")
    run_case("manifested-extra-file", extra_file, "bundle-file-roster")
    run_case("zero-obligation-launder", zero_obligations, "zero-obligations")
    run_case("symlink-hir", symlink_hir, "nonregular-file")
    run_case("producer-verdict-launder", producer_verdict_launder,
             "producer-evidence-mismatch")
    run_case("solver-smt-decouple", solver_smt_decouple, "solver-smt-mismatch")
    run_case("proof-path-reuse", proof_path_reuse, "proof-path-reuse")
    run_case("proof-tuple-reuse", proof_tuple_reuse, "proof-reuse")
    run_case("manifest-missing", manifest_missing, "manifest-missing")
    run_case("missing-canonical-file", missing_canonical_file, "bundle-file-roster")
    run_case("multi-source-launder", multi_source_launder,
             "multi-source-unsupported")
    run_case("z3-trailing-error", z3_trailing_error, "smt-not-unsat")

    with tempfile.TemporaryDirectory(prefix="jackal-program-root-symlink-") as td:
        root = Path(td)
        source, pristine, compiler_sha, artifact_sha, _marker = make_v3_fixture(
            root / "a"
        )
        link = root / "evidence-link"
        link.symlink_to(pristine, target_is_directory=True)
        clean = run_verify(source, pristine, compiler_sha, artifact_sha)
        bad = run_verify(source, link, compiler_sha, artifact_sha)
        restored = run_verify(source, pristine, compiler_sha, artifact_sha)
        observed = reason(bad)
        record(
            "root-symlink",
            clean.returncode == 0
            and bad.returncode == 1
            and observed == "input-path"
            and restored.returncode == 0,
            f"bad={observed} A2={restored.returncode}",
        )

    document = {
        "schema": "jackal-anubis-program-hostile-v1",
        "rows": ROWS,
        "passed": sum(1 for row in ROWS if row["ok"]),
        "failed": sum(1 for row in ROWS if not row["ok"]),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    dump(OUT, document)
    print(f"evidence={OUT} sha256={sha(OUT.read_bytes())}")
    if document["failed"]:
        print("ANUBIS_PROGRAM_HOSTILE_FAIL")
        return 1
    print(f"ANUBIS_PROGRAM_HOSTILE_PASS rows={len(ROWS)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
