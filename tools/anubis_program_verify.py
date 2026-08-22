#!/usr/bin/env python3
"""Fail-closed verifier for Anubis whole-program evidence packages.

This verifier is dependency-free and intentionally does not execute program artifacts.
It binds caller-pinned source/compiler/artifact identities, closes the evidence manifest,
reconciles Anubis program-evidence v3 inventories, and independently replays the admitted
RUP proof fragment. Source-to-VC and source-to-native refinement remain explicit residuals.
"""
from __future__ import annotations

import sys

if not (sys.flags.isolated and sys.flags.no_site):
    print('status=refused reason=python-not-isolated detail="requires python3 -I -S -B"')
    raise SystemExit(126)

import argparse
import hashlib
import json
import os
import re
import subprocess
import tempfile
import time
from pathlib import Path, PurePosixPath
from typing import Any, Callable

MAX_FILES = 512
MAX_TOTAL_BYTES = 64 * 1024 * 1024
MAX_JSON_BYTES = 8 * 1024 * 1024
MAX_PROOF_STEPS = 200_000
MAX_CLAUSES = 2_000_000
MAX_LITERALS = 20_000_000
RUP_REPLAY_TIMEOUT_SECONDS = 30.0
HEX64 = re.compile(r"^[0-9a-f]{64}$")
MANIFEST_ROW = re.compile(r"^([0-9a-f]{64})  ([A-Za-z0-9._/-]+)$")
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
PROGRAM_KEYS = {
    "schema",
    "version",
    "mode",
    "source",
    "compiler",
    "artifacts",
    "stages",
    "solver_inventory",
    "policy_inventory",
    "residual_non_claims",
}
ALLOWED_PROGRAM_FILES = {
    "MANIFEST.sha256",
    "analysis/proofs.json",
    "analysis/solver.smt2",
    "analysis/solver_replay.json",
    "artifact",
    "bounty-report.md",
    "build.log",
    "checks.sarif",
    "confinement_manifest.json",
    "declassify_audit.json",
    "dep_closure.json",
    "entitlement_profile.json",
    "environment.json",
    "evidence.json",
    "hir.json",
    "manifest.json",
    "mir.json",
    "mono_specializations.json",
    "pca.json",
    "program-evidence.json",
    "program.entitlements",
    "solver.json",
    "source-merkle-leaves.json",
    "source-tree.json",
    "source.anubis",
    "summaries.json",
    "taint-traces.json",
    "validate.sh",
}
REQUIRED_PROGRAM_FILES = ALLOWED_PROGRAM_FILES - {
    "dep_closure.json",
    "source-merkle-leaves.json",
}
PROOF_FILE = re.compile(r"^analysis/proofs/obligation_[0-9]{4}\.(cnf|drat|smt2)$")
Z3_UNSAT_MODEL_ERROR = re.compile(
    r'^\(error "line [1-9][0-9]* column [1-9][0-9]*: model is not available"\)$'
)
SUPPORTED_PROFILE = "inventory-safe-v1"
APPROVED_CHECK_COMPILER_SHA256 = (
    "0d6a8f89355eb9ec5971749daf943567c204ed9f2d3001edbd46599f4540d7d6"
)
APPROVED_Z3_PATH = Path("/opt/homebrew/bin/z3")
APPROVED_Z3_SHA256 = "ae6c8df33db9c9ae9a80b6044e77cd66529a141d8b25f0620f1e89b409594f48"
PROGRAM_POLICY_CANDIDATES = (
    Path(__file__).resolve().parents[1]
    / "release/program/inventory_safe_v1.json",
    Path(__file__).resolve().parents[1] / "program/inventory_safe_v1.json",
)
PROGRAM_POLICY_BODY = {
    "schema": "jackal-anubis-program-policy-v1",
    "profile": SUPPORTED_PROFILE,
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
PROGRAM_POLICY_SHA256 = hashlib.sha256(
    json.dumps(
        PROGRAM_POLICY_BODY,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
).hexdigest()


class Refusal(Exception):
    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(detail)
        self.reason = reason
        self.detail = detail


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha_file(path: Path) -> str:
    return sha(path.read_bytes())


def canonical(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            raise Refusal("duplicate-key", key)
        out[key] = value
    return out


def reject_float(token: str) -> None:
    raise Refusal("float-forbidden", token)


def load_json(path: Path) -> Any:
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise Refusal("input-read", f"{path.name}: {exc}") from None
    if len(data) > MAX_JSON_BYTES:
        raise Refusal("json-budget", path.name)
    try:
        return json.loads(
            data.decode("utf-8"),
            object_pairs_hook=reject_duplicates,
            parse_float=reject_float,
            parse_constant=reject_float,
        )
    except Refusal:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise Refusal("json-invalid", f"{path.name}: {exc}") from None


def require_keys(value: Any, expected: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise Refusal("schema", f"{label} must be an object")
    actual = set(value)
    if actual != expected:
        raise Refusal(
            "unknown-field",
            f"{label}: missing={sorted(expected - actual)} extra={sorted(actual - expected)}",
        )
    return value


def require_hex(value: Any, label: str) -> str:
    if not isinstance(value, str) or not HEX64.fullmatch(value):
        raise Refusal("hash-token", label)
    return value


def load_program_policy() -> tuple[dict[str, Any], str, str]:
    present = [
        path
        for path in PROGRAM_POLICY_CANDIDATES
        if path.exists() or path.is_symlink()
    ]
    if len(present) != 1:
        raise Refusal(
            "policy-layout",
            f"expected one policy file, found {[str(path) for path in present]}",
        )
    path = present[0]
    if path.is_symlink() or not path.is_file():
        raise Refusal("policy-layout", "policy must be a regular non-symlink file")
    document = require_keys(
        load_json(path),
        set(PROGRAM_POLICY_BODY) | {"policy_digest_sha256"},
        "program policy",
    )
    digest = require_hex(document["policy_digest_sha256"], "policy digest")
    body = {
        key: value
        for key, value in document.items()
        if key != "policy_digest_sha256"
    }
    if digest != sha(canonical(body)):
        raise Refusal("policy-digest-mismatch")
    if digest != PROGRAM_POLICY_SHA256 or body != PROGRAM_POLICY_BODY:
        raise Refusal("policy-unsupported", digest)
    return body, digest, sha_file(path)


def safe_relative(token: str) -> str:
    if "\\" in token or token.startswith("/"):
        raise Refusal("path-unsafe", token)
    path = PurePosixPath(token)
    if not token or any(part in {"", ".", ".."} for part in path.parts):
        raise Refusal("path-unsafe", token)
    normalized = path.as_posix()
    if normalized != token:
        raise Refusal("path-noncanonical", token)
    return token


def regular_tree(root: Path) -> dict[str, Path]:
    try:
        root = root.resolve(strict=True)
    except OSError as exc:
        raise Refusal("input-path", str(exc)) from None
    if not root.is_dir() or root.is_symlink():
        raise Refusal("input-path", "evidence root must be a real directory")
    files: dict[str, Path] = {}
    total = 0
    def walk_error(exc: OSError) -> None:
        raise Refusal("tree-walk-error", str(exc))

    for current, dirs, names in os.walk(
        root, followlinks=False, onerror=walk_error
    ):
        current_path = Path(current)
        depth = len(current_path.relative_to(root).parts)
        if depth > 8:
            raise Refusal("path-depth", str(current_path))
        for directory in dirs:
            child = current_path / directory
            if child.is_symlink():
                raise Refusal("symlink-forbidden", child.relative_to(root).as_posix())
        for name in names:
            child = current_path / name
            rel = safe_relative(child.relative_to(root).as_posix())
            if child.is_symlink() or not child.is_file():
                raise Refusal("nonregular-file", rel)
            if rel in files:
                raise Refusal("path-duplicate", rel)
            files[rel] = child
            total += child.stat().st_size
            if len(files) > MAX_FILES or total > MAX_TOTAL_BYTES:
                raise Refusal("bundle-budget", f"files={len(files)} bytes={total}")
    return files


def verify_manifest(root: Path, files: dict[str, Path]) -> tuple[dict[str, str], str]:
    manifest = files.get("MANIFEST.sha256")
    if manifest is None:
        raise Refusal("manifest-missing")
    try:
        raw = manifest.read_bytes()
        text = raw.decode("ascii")
    except (OSError, UnicodeDecodeError) as exc:
        raise Refusal("manifest-invalid", str(exc)) from None
    rows: dict[str, str] = {}
    casefold: set[str] = set()
    for line in text.splitlines():
        match = MANIFEST_ROW.fullmatch(line)
        if match is None:
            raise Refusal("manifest-invalid", line[:120])
        digest, raw_path = match.groups()
        path = safe_relative(raw_path)
        folded = path.casefold()
        if path in rows or folded in casefold:
            raise Refusal("manifest-duplicate", path)
        rows[path] = digest
        casefold.add(folded)
    actual = set(files) - {"MANIFEST.sha256"}
    if set(rows) != actual:
        raise Refusal(
            "manifest-closure",
            f"missing={sorted(actual - set(rows))} extra={sorted(set(rows) - actual)}",
        )
    for path, digest in rows.items():
        if sha_file(files[path]) != digest:
            raise Refusal("manifest-hash-mismatch", path)
    return rows, sha(raw)


def verify_file_roster(files: dict[str, Path]) -> None:
    unknown = sorted(
        path
        for path in files
        if path not in ALLOWED_PROGRAM_FILES and not PROOF_FILE.fullmatch(path)
    )
    if unknown:
        raise Refusal("bundle-file-roster", str(unknown))
    missing = sorted(REQUIRED_PROGRAM_FILES - set(files))
    if missing:
        raise Refusal("bundle-file-roster", f"missing={missing}")


def freeze_evidence_tree(
    source_root: Path, files: dict[str, Path], manifest_rows: dict[str, str]
) -> tuple[tempfile.TemporaryDirectory[str], Path, dict[str, Path], str]:
    holder = tempfile.TemporaryDirectory(prefix="jackal-program-snapshot-")
    snapshot = Path(holder.name) / "evidence"
    snapshot.mkdir()
    for relative, source in sorted(files.items()):
        data = source.read_bytes()
        if relative != "MANIFEST.sha256" and sha(data) != manifest_rows[relative]:
            holder.cleanup()
            raise Refusal("snapshot-drift", relative)
        destination = snapshot / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("xb") as handle:
            handle.write(data)
    frozen_files = regular_tree(snapshot)
    verify_file_roster(frozen_files)
    _, frozen_manifest_sha = verify_manifest(snapshot, frozen_files)
    return holder, snapshot, frozen_files, frozen_manifest_sha


def _check_proof_deadline(
    deadline: float, clock: Callable[[], float]
) -> None:
    if clock() > deadline:
        raise Refusal("proof-budget", "RUP replay deadline exceeded")


def read_dimacs(
    path: Path,
    *,
    deadline: float | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> tuple[list[tuple[int, ...]], int]:
    clauses: list[tuple[int, ...]] = []
    declared_vars = None
    declared_clauses = None
    literal_count = 0
    text = path.read_text(encoding="ascii")
    if deadline is not None:
        _check_proof_deadline(deadline, clock)
    for raw in text.splitlines():
        if deadline is not None:
            _check_proof_deadline(deadline, clock)
        line = raw.strip()
        if not line or line.startswith("c"):
            continue
        if line.startswith("p "):
            parts = line.split()
            if (
                declared_vars is not None
                or clauses
                or len(parts) != 4
                or parts[:2] != ["p", "cnf"]
            ):
                raise Refusal("cnf-invalid", path.name)
            try:
                declared_vars = int(parts[2])
                declared_clauses = int(parts[3])
            except ValueError:
                raise Refusal("cnf-invalid", path.name) from None
            continue
        try:
            values = [int(value) for value in line.split()]
        except ValueError:
            raise Refusal("cnf-invalid", path.name) from None
        if not values or values[-1] != 0 or 0 in values[:-1]:
            raise Refusal("cnf-invalid", path.name)
        clause = tuple(values[:-1])
        if len(set(clause)) != len(clause) or any(-value in clause for value in clause):
            raise Refusal("cnf-invalid", "duplicate/tautological clause")
        if declared_vars is not None and any(abs(value) > declared_vars for value in clause):
            raise Refusal("cnf-invalid", "literal exceeds declared variable count")
        clauses.append(clause)
        literal_count += len(clause)
        if len(clauses) > MAX_CLAUSES or literal_count > MAX_LITERALS:
            raise Refusal("proof-budget", path.name)
    if declared_vars is None or declared_clauses != len(clauses):
        raise Refusal("cnf-invalid", "header count mismatch")
    return clauses, declared_vars


def unit_conflict(
    clauses: list[tuple[int, ...]],
    assumptions: list[int],
    *,
    deadline: float,
    clock: Callable[[], float],
) -> bool:
    assignments: dict[int, bool] = {}
    for literal in assumptions:
        _check_proof_deadline(deadline, clock)
        variable = abs(literal)
        value = literal > 0
        prior = assignments.get(variable)
        if prior is not None:
            if prior != value:
                return True
        else:
            assignments[variable] = value

    while True:
        changed = False
        for clause in clauses:
            _check_proof_deadline(deadline, clock)
            satisfied = False
            unassigned: list[int] = []
            for index, item in enumerate(clause):
                if index % 1024 == 0:
                    _check_proof_deadline(deadline, clock)
                assigned = assignments.get(abs(item))
                if assigned is None:
                    unassigned.append(item)
                elif assigned == (item > 0):
                    satisfied = True
                    break
            if satisfied:
                continue
            if not unassigned:
                return True
            if len(unassigned) == 1:
                candidate = unassigned[0]
                variable = abs(candidate)
                desired = candidate > 0
                existing = assignments.get(variable)
                if existing is not None:
                    if existing != desired:
                        return True
                else:
                    assignments[variable] = desired
                    changed = True
        if not changed:
            return False


def verify_rup(
    cnf_path: Path,
    proof_path: Path,
    *,
    timeout_seconds: float = RUP_REPLAY_TIMEOUT_SECONDS,
    clock: Callable[[], float] = time.monotonic,
) -> tuple[int, int, int]:
    if timeout_seconds <= 0:
        raise Refusal("proof-budget", "RUP replay deadline is not positive")
    deadline = clock() + timeout_seconds
    clauses, variables = read_dimacs(
        cnf_path, deadline=deadline, clock=clock
    )
    original_clause_count = len(clauses)
    steps = 0
    saw_empty = False
    proof_text = proof_path.read_text(encoding="ascii")
    _check_proof_deadline(deadline, clock)
    for raw in proof_text.splitlines():
        _check_proof_deadline(deadline, clock)
        line = raw.strip()
        if not line or line.startswith("c"):
            continue
        if line.startswith("d "):
            raise Refusal("proof-feature-unsupported", "deletion/RAT not admitted")
        try:
            values = [int(value) for value in line.split()]
        except ValueError:
            raise Refusal("proof-invalid", proof_path.name) from None
        if not values or values[-1] != 0 or 0 in values[:-1]:
            raise Refusal("proof-invalid", proof_path.name)
        clause = tuple(values[:-1])
        if len(set(clause)) != len(clause) or any(-value in clause for value in clause):
            raise Refusal("proof-invalid", "duplicate/tautological proof clause")
        if not unit_conflict(
            clauses,
            [-value for value in clause],
            deadline=deadline,
            clock=clock,
        ):
            raise Refusal("rup-replay-failed", f"{proof_path.name} step {steps}")
        clauses.append(clause)
        steps += 1
        if not clause:
            saw_empty = True
        if steps > MAX_PROOF_STEPS:
            raise Refusal("proof-budget", proof_path.name)
        if saw_empty:
            continue
    if not saw_empty:
        raise Refusal("proof-no-empty-clause", proof_path.name)
    return steps, variables, original_clause_count


def verify_smt_unsat(path: Path) -> None:
    try:
        z3_path = APPROVED_Z3_PATH.resolve(strict=True)
    except OSError:
        raise Refusal("z3-unavailable") from None
    if not z3_path.is_file():
        raise Refusal("z3-unavailable")
    before = sha_file(z3_path)
    if before != APPROVED_Z3_SHA256:
        raise Refusal("z3-identity-mismatch")
    try:
        completed = subprocess.run(
            [str(z3_path), "-smt2", str(path)],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise Refusal("z3-replay-failed", str(exc)) from None
    if sha_file(z3_path) != before:
        raise Refusal("z3-toctou")
    lines = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
    clean_unsat = completed.returncode == 0 and lines == ["unsat"] and not completed.stderr
    anubis_unsat_with_model_query = (
        completed.returncode == 1
        and len(lines) == 2
        and lines[0] == "unsat"
        and Z3_UNSAT_MODEL_ERROR.fullmatch(lines[1]) is not None
        and not completed.stderr
    )
    if not (clean_unsat or anubis_unsat_with_model_query):
        raise Refusal("smt-not-unsat", (completed.stdout + completed.stderr)[:200])


def verify_artifacts(root: Path, program: dict[str, Any]) -> dict[str, Any]:
    artifacts = require_keys(
        program["artifacts"],
        {"hir", "mir", "taint", "solver", "monomorphization", "native"},
        "artifacts",
    )
    loaded: dict[str, Any] = {}
    for label in ("hir", "mir", "taint", "solver", "monomorphization"):
        row = require_keys(artifacts[label], {"path", "sha256", "bytes"}, label)
        relative = safe_relative(row["path"])
        path = root / relative
        if not path.is_file():
            raise Refusal("artifact-missing", relative)
        if sha_file(path) != require_hex(row["sha256"], f"{label}.sha256"):
            raise Refusal("artifact-hash-mismatch", label)
        if path.stat().st_size != row["bytes"]:
            raise Refusal("artifact-size-mismatch", label)
        loaded[label] = load_json(path)
    native = require_keys(artifacts["native"], {"path", "sha256"}, "native")
    if native["path"] != "artifact":
        raise Refusal("artifact-path", "inventory-safe-v1 requires artifact")
    native_path = root / "artifact"
    native_sha256 = require_hex(native["sha256"], "native.sha256")
    if not native_path.is_file() or sha_file(native_path) != native_sha256:
        raise Refusal("artifact-hash-mismatch", "native")
    return loaded


def verify_stages(program: dict[str, Any]) -> None:
    stages = program["stages"]
    if not isinstance(stages, list):
        raise Refusal("stage-schema")
    seen: list[str] = []
    for row in stages:
        item = require_keys(row, {"id", "status", "authority"}, "stage")
        if item["id"] in seen:
            raise Refusal("stage-duplicate", item["id"])
        seen.append(item["id"])
        if item["status"] != "PASS":
            raise Refusal("stage-not-pass", f"{item['id']}={item['status']}")
    if seen != REQUIRED_STAGES:
        raise Refusal("stage-roster", f"got={seen}")


def function_inventory_from_hir(hir: Any) -> tuple[list[dict[str, Any]], list[str]]:
    if (
        not isinstance(hir, dict)
        or set(hir) != {"functions", "imports", "modules"}
        or not isinstance(hir["functions"], list)
        or not isinstance(hir["imports"], list)
        or not isinstance(hir["modules"], list)
    ):
        raise Refusal("hir-schema")
    rows = []
    ids = []
    for function in hir["functions"]:
        if not isinstance(function, dict):
            raise Refusal("hir-schema", "function")
        identifier = sha(canonical(function))
        row = {
            "id": identifier,
            "name": function.get("name", ""),
            "module": function.get("module"),
            "mode": function.get("mode", ""),
            "effects": function.get("effects", []),
            "param_count": len(function.get("params", [])),
            "symbol_count": len(function.get("symbols", [])),
        }
        rows.append(row)
        ids.append(identifier)
    if len(ids) != len(set(ids)):
        raise Refusal("function-duplicate")
    return rows, ids


def verify_policy(
    root: Path, program: dict[str, Any], loaded: dict[str, Any]
) -> tuple[int, int]:
    policy = require_keys(
        program["policy_inventory"],
        {
            "functions",
            "consumers",
            "capabilities_present_count",
            "taint_trace_count",
            "monomorphization_count",
            "mir_function_count",
        },
        "policy_inventory",
    )
    expected_functions, function_ids = function_inventory_from_hir(loaded["hir"])
    if policy["functions"] != expected_functions:
        raise Refusal("policy-function-mismatch")
    if any(row["mode"] != "safe" for row in expected_functions):
        raise Refusal("policy-function-mode")
    consumers = policy["consumers"]
    if not isinstance(consumers, list):
        raise Refusal("policy-consumer-schema")
    roster = [row.get("id") for row in consumers if isinstance(row, dict)]
    if roster != REQUIRED_CONSUMERS:
        raise Refusal("policy-consumer-roster", str(roster))
    for row in consumers:
        item = require_keys(row, {"id", "status", "authority", "subjects"}, "consumer")
        if item["status"] != "PASS":
            raise Refusal("policy-consumer-not-pass", item["id"])
        if item["id"] in {"effects", "capability", "information-flow", "mode"}:
            if item["subjects"] != function_ids:
                raise Refusal("policy-subject-mismatch", item["id"])
    declassifications = 0
    if (root / "declassify_audit.json").is_file():
        audit = load_json(root / "declassify_audit.json")
        if not isinstance(audit, dict) or not isinstance(audit.get("declassifications"), list):
            raise Refusal("policy-artifact-schema", "declassification")
        declassifications = len(audit["declassifications"])
    declass_row = next(row for row in consumers if row["id"] == "declassification")
    if declass_row["subjects"] != {"count": declassifications}:
        raise Refusal("policy-count-mismatch", "declassification")
    capabilities = 0
    if (root / "confinement_manifest.json").is_file():
        confinement = load_json(root / "confinement_manifest.json")
        if not isinstance(confinement, dict) or not isinstance(
            confinement.get("capabilities_present"), list
        ):
            raise Refusal("policy-artifact-schema", "capability")
        capabilities = len(confinement["capabilities_present"])
    if policy["capabilities_present_count"] != capabilities:
        raise Refusal("policy-count-mismatch", "capability")
    if policy["taint_trace_count"] != len(loaded["taint"]):
        raise Refusal("policy-count-mismatch", "taint")
    if policy["monomorphization_count"] != len(loaded["monomorphization"]):
        raise Refusal("policy-count-mismatch", "monomorphization")
    if policy["mir_function_count"] != len(loaded["mir"]):
        raise Refusal("policy-count-mismatch", "mir")
    return len(expected_functions), len(consumers)


def verify_solver(root: Path, program: dict[str, Any], solver: Any) -> tuple[int, int]:
    inventory = require_keys(program["solver_inventory"], {"count", "obligations"}, "solver_inventory")
    obligations = inventory["obligations"]
    if not isinstance(obligations, list) or not isinstance(solver, list):
        raise Refusal("solver-schema")
    if inventory["count"] != len(obligations) or len(obligations) != len(solver):
        raise Refusal("solver-count-mismatch")
    if not obligations:
        raise Refusal("zero-obligations", f"{SUPPORTED_PROFILE} requires at least one")
    proof_index = load_json(root / "analysis/proofs.json")
    if not isinstance(proof_index, dict) or set(proof_index) != {"note", "obligations"}:
        raise Refusal("proof-index-schema")
    proof_rows = proof_index["obligations"]
    if not isinstance(proof_rows, list) or len(proof_rows) != len(obligations):
        raise Refusal("proof-count-mismatch")
    verified = 0
    total_steps = 0
    ids: set[str] = set()
    used_paths: set[str] = set()
    used_proof_tuples: set[tuple[str, str, str]] = set()
    for index, obligation in enumerate(obligations):
        row = require_keys(
            obligation,
            {
                "id",
                "name",
                "status",
                "proof_kind",
                "smt_path",
                "smt_sha256",
                "cnf_path",
                "cnf_sha256",
                "proof_path",
                "proof_sha256",
                "num_vars",
                "num_clauses",
                "steps",
                "checker",
                "checker_version",
            },
            "obligation",
        )
        proof = proof_rows[index]
        solver_row = solver[index]
        require_keys(
            proof,
            {
                "obligation",
                "status",
                "proof",
                "smt",
                "cnf_dimacs",
                "proof_drat",
                "num_vars",
                "num_clauses",
                "steps",
                "checker",
                "checker_version",
                "replay",
            },
            "proof index row",
        )
        require_keys(solver_row, {"detail", "model", "name", "smt", "status"}, "solver row")
        if row["name"] != proof.get("obligation") or row["name"] != solver_row.get("name"):
            raise Refusal("obligation-name-mismatch", str(index))
        if row["status"] != "PASS" or proof.get("status") != "PASS" or solver_row.get("status") != "PASS":
            raise Refusal("obligation-not-pass", row["name"])
        if row["proof_kind"] != "rup_refutation" or proof.get("proof") != "rup_refutation":
            raise Refusal("proof-feature-unsupported", row["name"])
        for label, program_path, program_hash, proof_key in (
            ("smt", row["smt_path"], row["smt_sha256"], "smt"),
            ("cnf", row["cnf_path"], row["cnf_sha256"], "cnf_dimacs"),
            ("proof", row["proof_path"], row["proof_sha256"], "proof_drat"),
        ):
            if program_path != proof.get(proof_key):
                raise Refusal("proof-path-mismatch", label)
            relative = safe_relative(program_path)
            if relative in used_paths:
                raise Refusal("proof-path-reuse", relative)
            used_paths.add(relative)
            actual = sha_file(root / relative)
            if actual != require_hex(program_hash, f"{label}.sha256"):
                raise Refusal("proof-hash-mismatch", label)
        stable = {
            "name": row["name"],
            "smt_sha256": row["smt_sha256"],
            "cnf_sha256": row["cnf_sha256"],
            "proof_sha256": row["proof_sha256"],
        }
        expected_id = sha(canonical(stable))
        if row["id"] != expected_id or row["id"] in ids:
            raise Refusal("obligation-id-mismatch", row["name"])
        ids.add(row["id"])
        if (root / row["smt_path"]).read_text(encoding="utf-8") != solver_row["smt"]:
            raise Refusal("solver-smt-mismatch", row["name"])
        proof_tuple = (row["smt_sha256"], row["cnf_sha256"], row["proof_sha256"])
        if proof_tuple in used_proof_tuples:
            raise Refusal("proof-reuse", row["name"])
        used_proof_tuples.add(proof_tuple)
        verify_smt_unsat(root / row["smt_path"])
        steps, variables, clauses = verify_rup(
            root / row["cnf_path"], root / row["proof_path"]
        )
        if (
            row["num_vars"] != variables
            or proof["num_vars"] != variables
            or row["num_clauses"] != clauses
            or proof["num_clauses"] != clauses
            or row["steps"] != steps
            or proof["steps"] != steps
            or row["checker"] != proof["checker"]
            or row["checker_version"] != proof["checker_version"]
        ):
            raise Refusal("proof-counter-mismatch", row["name"])
        total_steps += steps
        verified += 1
    contracts = next(row for row in program["policy_inventory"]["consumers"] if row["id"] == "contracts")
    if contracts["subjects"] != {"solver_obligation_count": verified}:
        raise Refusal("policy-count-mismatch", "contracts")
    return verified, total_steps


def verify_producer_evidence(
    root: Path,
    program: dict[str, Any],
    expected_source: str,
    expected_artifact: str,
    proof_count: int,
) -> None:
    evidence_path = root / "evidence.json"
    pca_path = root / "pca.json"
    if not evidence_path.is_file() or not pca_path.is_file():
        raise Refusal("producer-evidence-missing")
    evidence = require_keys(
        load_json(evidence_path),
        {
            "timestamp",
            "tool",
            "mode",
            "source_hash",
            "build_log_hash",
            "artifact_hash",
            "lane",
            "environment_hash",
            "source_tree_hash",
            "sarif_hash",
            "bounty_report_hash",
            "manifest_sha256",
            "checks",
            "verdict",
            "security",
        },
        "evidence.json",
    )
    security = evidence["security"]
    if (
        evidence["mode"] != "safe"
        or evidence["lane"] not in {None, "safe"}
        or evidence["verdict"] != "PASS"
        or evidence["tool"] != program["compiler"]["tool"]
        or evidence["source_hash"] != program["source"]["merkle"]
        or evidence["artifact_hash"] != expected_artifact
        or not isinstance(security, dict)
        or security.get("mode") != "safe"
    ):
        raise Refusal("producer-evidence-mismatch", "manifest summary")
    summary_files = {
        "build_log_hash": "build.log",
        "environment_hash": "environment.json",
        "source_tree_hash": "source-tree.json",
        "sarif_hash": "checks.sarif",
        "bounty_report_hash": "bounty-report.md",
    }
    for field, relative in summary_files.items():
        if evidence[field] != sha_file(root / relative):
            raise Refusal("producer-evidence-mismatch", field)
    expected_manifest_summary = sha(
        (
            f"{evidence['source_hash']}:{evidence['build_log_hash']}:"
            f"{evidence['source_tree_hash']}:PASS"
        ).encode("utf-8")
    )
    if evidence["manifest_sha256"] != expected_manifest_summary:
        raise Refusal("producer-evidence-mismatch", "manifest_sha256")
    if (root / "manifest.json").read_bytes() != evidence_path.read_bytes():
        raise Refusal("producer-evidence-mismatch", "manifest/evidence divergence")
    checks = evidence["checks"]
    if not isinstance(checks, list):
        raise Refusal("producer-evidence-schema", "checks")
    seen: set[str] = set()
    details: dict[str, Any] = {}
    required = {
        "parse",
        "typecheck",
        "monomorphization",
        "symbolic",
        "solver",
        "source_hash",
        "build_log_hash",
        "artifact",
        "artifact_hash",
    }
    for row in checks:
        item = require_keys(row, {"name", "status", "detail"}, "evidence check")
        if item["name"] in seen:
            raise Refusal("producer-evidence-mismatch", "duplicate check")
        seen.add(item["name"])
        if item["status"] != "PASS":
            raise Refusal("producer-evidence-mismatch", f"{item['name']} not PASS")
        details[item["name"]] = item["detail"]
    expected_details = {
        "source_hash": evidence["source_hash"],
        "build_log_hash": evidence["build_log_hash"],
        "artifact_hash": expected_artifact,
    }
    for name, expected_detail in expected_details.items():
        if details.get(name) != expected_detail:
            raise Refusal("producer-evidence-mismatch", f"{name} detail")
    if not required <= seen:
        raise Refusal("producer-evidence-mismatch", f"missing checks {sorted(required - seen)}")

    pca = require_keys(
        load_json(pca_path),
        {
            "pca_version",
            "source_sha256",
            "mode",
            "tier",
            "rejection",
            "parse_ok",
            "typecheck_ok",
            "solver_obligations",
            "solver_all_discharged",
            "solver_backend",
            "zk_present",
            "zk_image_id",
            "zk_receipt_sha256",
            "zk_journal_sha256",
            "verdict",
            "tool",
        },
        "pca.json",
    )
    if (
        pca["pca_version"] != 2
        or pca["source_sha256"] != expected_source
        or pca["mode"] != "safe"
        or pca["tier"] != "checked"
        or pca["rejection"] is not None
        or pca["parse_ok"] is not True
        or pca["typecheck_ok"] is not True
        or pca["solver_obligations"] != proof_count
        or pca["solver_all_discharged"] is not True
        or pca["verdict"] != "PASS"
        or pca["tool"] != program["compiler"]["tool"]
    ):
        raise Refusal("producer-evidence-mismatch", "PCA summary")


def build_receipt(args: argparse.Namespace) -> dict[str, Any]:
    source_path = Path(args.source)
    if source_path.is_symlink() or not source_path.is_file():
        raise Refusal("input-path", "source must be a regular non-symlink file")
    source = source_path.read_bytes()
    expected_source = require_hex(args.expected_source_sha256, "expected-source")
    if sha(source) != expected_source:
        raise Refusal("source-pin-mismatch")
    expected_compiler = require_hex(args.expected_compiler_sha256, "expected-compiler")
    expected_policy = require_hex(args.expected_policy_sha256, "expected-policy")
    policy_body, policy_digest, policy_file_sha256 = load_program_policy()
    if expected_policy != policy_digest:
        raise Refusal("policy-pin-mismatch")
    if (
        not isinstance(args.verification_time_unix, str)
        or not args.verification_time_unix.isdigit()
    ):
        raise Refusal("verification-time-invalid")
    if args.profile != SUPPORTED_PROFILE:
        raise Refusal("profile-unsupported", args.profile)

    provided_root = Path(args.evidence_dir)
    if provided_root.is_symlink():
        raise Refusal("input-path", "evidence root symlink")
    original_root = provided_root.resolve(strict=True)
    original_files = regular_tree(original_root)
    if "program-evidence.json" not in original_files:
        raise Refusal(
            "unsupported-program-evidence-version",
            "anubis.program-evidence.v3 is required; PCA v2 is partial",
        )
    manifest_rows, original_manifest_sha = verify_manifest(original_root, original_files)
    verify_file_roster(original_files)
    snapshot_holder, root, files, manifest_sha = freeze_evidence_tree(
        original_root, original_files, manifest_rows
    )
    try:
        if manifest_sha != original_manifest_sha:
            raise Refusal("snapshot-drift", "manifest")
        program_path = files.get("program-evidence.json")
        if program_path is None:
            raise Refusal(
                "unsupported-program-evidence-version",
                "anubis.program-evidence.v3 is required; PCA v2 is partial",
            )
        program = require_keys(load_json(program_path), PROGRAM_KEYS, "program-evidence")
        if program["schema"] != "anubis.program-evidence.v3" or program["version"] != 3:
            raise Refusal("unsupported-program-evidence-version")
        if program["mode"] != "safe":
            raise Refusal("mode-unsupported", str(program["mode"]))
        source_row = require_keys(program["source"], {"path", "sha256", "merkle", "bytes"}, "source")
        sealed_source = root / safe_relative(source_row["path"])
        if sealed_source.read_bytes() != source:
            raise Refusal("source-byte-mismatch")
        if source_row["sha256"] != expected_source or source_row["bytes"] != len(source):
            raise Refusal("source-inventory-mismatch")
        if source_row["merkle"] != expected_source:
            raise Refusal(
                "multi-source-unsupported",
                f"{SUPPORTED_PROFILE} requires one exact source leaf",
            )
        compiler = require_keys(program["compiler"], {"tool", "path_basename", "sha256"}, "compiler")
        if compiler["sha256"] != expected_compiler:
            raise Refusal("compiler-pin-mismatch")

        verify_stages(program)
        loaded = verify_artifacts(root, program)
        native = program["artifacts"]["native"]
        expected_artifact = args.expected_artifact_sha256
        if expected_artifact is None:
            raise Refusal("artifact-pin-required", SUPPORTED_PROFILE)
        expected_artifact = require_hex(expected_artifact, "expected-artifact")
        if native["sha256"] != expected_artifact:
            raise Refusal("artifact-pin-mismatch")
        function_count, consumer_count = verify_policy(root, program, loaded)
        proof_count, proof_steps = verify_solver(root, program, loaded["solver"])
        verify_producer_evidence(root, program, expected_source, expected_artifact, proof_count)
        producer_residuals = program["residual_non_claims"]
        if producer_residuals != PRODUCER_RESIDUALS:
            raise Refusal("residual-roster", str(producer_residuals))

        receipt: dict[str, Any] = {
            "schema": "jackal-anubis-program-receipt-v1",
            "status": "verified-program-evidence",
            "profile": args.profile,
            "source": {"sha256": expected_source, "bytes": len(source)},
            "compiler": {
                "sha256": expected_compiler,
                "tool": compiler["tool"],
                "path_basename": compiler["path_basename"],
            },
            "artifact": {"sha256": expected_artifact},
            "evidence_manifest_sha256": manifest_sha,
            "program_evidence_sha256": sha_file(program_path),
            "stage_count": len(REQUIRED_STAGES),
            "policy": {
                "profile": policy_body["profile"],
                "policy_digest_sha256": policy_digest,
                "policy_file_sha256": policy_file_sha256,
                "inventory_authority": policy_body["policy_inventory_authority"],
                "independent_construct_totality": policy_body[
                    "independent_policy_construct_totality"
                ],
                "function_count": function_count,
                "consumer_count": consumer_count,
            },
            "proof_replay": {
                "kind": "approved-z3-plus-independent-rup",
                "verified": proof_count,
                "smt_verified": proof_count,
                "steps": proof_steps,
            },
            "assurance": {
                "source_binding": "verified",
                "evidence_closure": "verified",
                "proof_replay": "independently-recomputed",
                "smt_replay": "approved-z3-unsat",
                "smt_to_cnf": "open",
                "policy_semantics": "producer-attested-inventory-checked",
                "policy_construct_totality": "not-established",
                "source_to_vc": "open",
                "source_native_refinement": "open",
                "runtime": "not-observed",
            },
            "residual_non_claims": RECEIPT_RESIDUALS,
            "nonce": args.nonce,
            "policy_sha256": expected_policy,
            "verification_time_unix": args.verification_time_unix,
        }
        receipt["receipt_digest_sha256"] = sha(canonical(receipt))
        post_files = regular_tree(original_root)
        verify_file_roster(post_files)
        _, post_manifest_sha = verify_manifest(original_root, post_files)
        if post_manifest_sha != original_manifest_sha:
            raise Refusal("snapshot-drift", "source evidence changed during verification")
        return receipt
    finally:
        snapshot_holder.cleanup()


def write_new(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8") as handle:
            json.dump(document, handle, indent=2, ensure_ascii=False, sort_keys=True)
            handle.write("\n")
    except FileExistsError:
        raise Refusal("output-exists", str(path)) from None


def verify(args: argparse.Namespace) -> dict[str, Any]:
    receipt = build_receipt(args)
    if args.emit_receipt:
        write_new(Path(args.emit_receipt), receipt)
    return receipt


def verify_receipt(args: argparse.Namespace) -> dict[str, Any]:
    supplied = load_json(Path(args.receipt))
    if not isinstance(supplied, dict) or "receipt_digest_sha256" not in supplied:
        raise Refusal("receipt-schema")
    without_digest = {
        key: value for key, value in supplied.items() if key != "receipt_digest_sha256"
    }
    if supplied["receipt_digest_sha256"] != sha(canonical(without_digest)):
        raise Refusal("receipt-digest-mismatch")
    replay_args = argparse.Namespace(**vars(args))
    replay_args.emit_receipt = None
    expected = build_receipt(replay_args)
    if supplied != expected:
        raise Refusal("receipt-semantic-mismatch")
    if args.emit_receipt:
        write_new(Path(args.emit_receipt), expected)
    return expected


def check_program(args: argparse.Namespace) -> dict[str, Any]:
    source = Path(args.source)
    compiler = Path(args.anubis_bin)
    if source.is_symlink() or not source.is_file():
        raise Refusal("input-path", "source")
    if compiler.is_symlink() or not compiler.is_file():
        raise Refusal("input-path", "anubis-bin")
    expected_source = require_hex(args.expected_source_sha256, "expected-source")
    expected_compiler = require_hex(args.expected_compiler_sha256, "expected-compiler")
    expected_policy = require_hex(args.expected_policy_sha256, "expected-policy")
    if expected_policy != PROGRAM_POLICY_SHA256:
        raise Refusal("policy-pin-mismatch")
    if not isinstance(args.verification_time_unix, str) or not args.verification_time_unix.isdigit():
        raise Refusal("verification-time-invalid")
    if sha_file(source) != expected_source:
        raise Refusal("source-pin-mismatch")
    if sha_file(compiler) != expected_compiler:
        raise Refusal("compiler-pin-mismatch")
    if expected_compiler != APPROVED_CHECK_COMPILER_SHA256:
        raise Refusal("compiler-not-approved", expected_compiler)
    out_root = Path(args.out_root)
    if out_root.exists() or out_root.is_symlink():
        raise Refusal("output-exists", str(out_root))
    out_root.parent.mkdir(parents=True, exist_ok=True)
    command = [
        str(compiler),
        "build",
        str(source),
        "--out",
        str(out_root),
        "--evidence",
    ]
    try:
        completed = subprocess.run(command, capture_output=True, timeout=900)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise Refusal("producer-failed", str(exc)) from None
    if sha_file(compiler) != expected_compiler:
        raise Refusal("compiler-toctou")
    if completed.returncode != 0:
        detail = (completed.stdout + completed.stderr).decode("utf-8", "replace")[-2000:]
        raise Refusal("producer-rejected", detail)
    evidence_dirs = sorted(
        path
        for path in out_root.iterdir()
        if path.is_dir() and path.name.startswith("evidence-")
    )
    if len(evidence_dirs) != 1:
        raise Refusal("producer-output", f"evidence_dirs={len(evidence_dirs)}")
    artifact = evidence_dirs[0] / "artifact"
    if not artifact.is_file():
        raise Refusal("producer-output", "missing sealed artifact")
    replay_args = argparse.Namespace(
        source=str(source),
        evidence_dir=str(evidence_dirs[0]),
        expected_source_sha256=expected_source,
        expected_compiler_sha256=expected_compiler,
        expected_artifact_sha256=sha_file(artifact),
        expected_policy_sha256=args.expected_policy_sha256,
        verification_time_unix=args.verification_time_unix,
        profile=args.profile,
        nonce=args.nonce,
        emit_receipt=args.emit_receipt,
    )
    return verify(replay_args)


def add_verify_arguments(command: argparse.ArgumentParser) -> None:
    command.add_argument("--source", required=True)
    command.add_argument("--evidence-dir", required=True)
    command.add_argument("--expected-source-sha256", required=True)
    command.add_argument("--expected-compiler-sha256", required=True)
    command.add_argument("--expected-artifact-sha256")
    command.add_argument("--expected-policy-sha256", required=True)
    command.add_argument("--verification-time-unix", required=True)
    command.add_argument("--profile", required=True)
    command.add_argument("--nonce", required=True)
    command.add_argument("--emit-receipt")


def parser() -> argparse.ArgumentParser:
    top = argparse.ArgumentParser()
    sub = top.add_subparsers(dest="command", required=True)
    verify_parser = sub.add_parser("verify")
    add_verify_arguments(verify_parser)
    receipt_parser = sub.add_parser("verify-receipt")
    receipt_parser.add_argument("--receipt", required=True)
    add_verify_arguments(receipt_parser)
    check_parser = sub.add_parser("check")
    check_parser.add_argument("--source", required=True)
    check_parser.add_argument("--anubis-bin", required=True)
    check_parser.add_argument("--expected-source-sha256", required=True)
    check_parser.add_argument("--expected-compiler-sha256", required=True)
    check_parser.add_argument("--expected-policy-sha256", required=True)
    check_parser.add_argument("--verification-time-unix", required=True)
    check_parser.add_argument("--profile", required=True)
    check_parser.add_argument("--nonce", required=True)
    check_parser.add_argument("--out-root", required=True)
    check_parser.add_argument("--emit-receipt", required=True)
    return top


def main() -> int:
    args = parser().parse_args()
    try:
        if args.command == "verify":
            result = verify(args)
            status = "verified-program-evidence"
        elif args.command == "verify-receipt":
            result = verify_receipt(args)
            status = "verified-program-receipt"
        else:
            result = check_program(args)
            status = "verified-program-evidence"
    except Refusal as exc:
        detail = exc.detail.replace('"', "'")
        print(f'status=refused reason={exc.reason} detail="{detail}"')
        return 1
    except (OSError, UnicodeError, ValueError, TypeError, KeyError) as exc:
        detail = str(exc).replace('"', "'")[:300]
        print(f'status=refused reason=verifier-internal detail="{detail}"')
        return 1
    print("status=" + status)
    print("receipt_digest_sha256=" + result["receipt_digest_sha256"])
    print("proofs_verified=" + str(result["proof_replay"]["verified"]))
    print("source_sha256=" + result["source"]["sha256"])
    print("artifact_sha256=" + result["artifact"]["sha256"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
