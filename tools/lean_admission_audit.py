#!/usr/bin/env python3
"""Generate and verify JACKAL's repository-wide Lean admission audit.

The audit is deliberately narrow.  It inventories every Git-tracked Lean
source, rejects local proof/admission bypasses, replays the exact ``#print
axioms`` surface named by the current release proof identities, and binds the
checker bytes those identities name.  It does not authenticate the builder or
prove source-to-native refinement.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
from typing import Any, Iterable


DEFAULT_ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_REL = Path("release/evidence/lean_admission_audit_v173.json")
GENERATOR_REL = Path("tools/lean_admission_audit.py")
LEAN_DIR_REL = Path("proofs/lean")
ALLOWED_AXIOMS = ("propext", "Classical.choice", "Quot.sound")
MAX_SOURCE_BYTES = 16 * 1024 * 1024
MAX_EVIDENCE_BYTES = 16 * 1024 * 1024

IDENTITY_CONFIGS = (
    (
        "range",
        Path("release/evidence/range_proof_identity_v172.json"),
        "jackal-range-proof-identity-v2",
    ),
    (
        "gaussian",
        Path("release/evidence/gaussian_proof_identity.json"),
        "jackal-gaussian-proof-identity-v1",
    ),
    (
        "int-cert",
        Path("release/evidence/int_cert_proof_identity_v172.json"),
        "jackal-int-cert-proof-identity-v2",
    ),
)

ALLOWED_LOCAL_CONSTRUCTS = {
    "proofs/lean/JackalIv/Correspondence.lean": {
        "implemented_by": (
            "@[implemented_by Dump.parseSexpImpl]",
            "@[implemented_by Dump.lowerSexpImpl]",
        )
    }
}

CONSTRUCT_PATTERNS = {
    "admit": re.compile(r"\badmit\b"),
    "axiom_declaration": re.compile(
        r"(?m)^\s*(?:@\[[^\n]*\]\s*)*"
        r"(?:(?:private|protected|noncomputable|local)\s+)*axioms?\s+"
    ),
    "extern": re.compile(r"\bextern\b"),
    "implemented_by": re.compile(r"@\[\s*implemented_by\b"),
    "native_decide": re.compile(r"\bnative_decide\b"),
    "partial": re.compile(r"\bpartial\b"),
    "sorry": re.compile(r"\bsorry\b"),
    "unsafe": re.compile(r"\bunsafe\b"),
}

AXIOM_LINE_RE = re.compile(r"^'([^']+)' depends on axioms: \[(.*)\]$")


class AuditError(RuntimeError):
    """A repository-wide Lean trust-surface invariant failed."""


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")


def pretty_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_regular(path: Path, maximum: int) -> bytes:
    try:
        before = path.lstat()
    except OSError as exc:
        raise AuditError(f"cannot stat required file: {path}") from exc
    if not stat.S_ISREG(before.st_mode) or stat.S_ISLNK(before.st_mode):
        raise AuditError(f"required path is not a regular non-symlink file: {path}")
    if before.st_size > maximum:
        raise AuditError(f"required file exceeds byte bound: {path}")
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        opened = os.fstat(descriptor)
        if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
            raise AuditError(f"file identity changed before read: {path}")
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(descriptor, min(1024 * 1024, maximum + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > maximum:
                raise AuditError(f"required file exceeds byte bound: {path}")
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    current = path.lstat()
    identity = lambda item: (  # noqa: E731
        item.st_dev,
        item.st_ino,
        item.st_mode,
        item.st_size,
        item.st_mtime_ns,
        item.st_ctime_ns,
    )
    if identity(opened) != identity(after) or identity(after) != identity(current):
        raise AuditError(f"file changed while being read: {path}")
    return b"".join(chunks)


def strict_json(path: Path) -> dict[str, Any]:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        document: dict[str, Any] = {}
        for key, value in pairs:
            if key in document:
                raise AuditError(f"duplicate JSON key in {path}: {key}")
            document[key] = value
        return document

    try:
        value = json.loads(
            read_regular(path, MAX_EVIDENCE_BYTES).decode("utf-8"),
            object_pairs_hook=reject_duplicates,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AuditError(f"cannot parse JSON evidence {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise AuditError(f"JSON evidence is not an object: {path}")
    return value


def _character_literal_end(source: str, start: int) -> int | None:
    """Return the end of a Lean character literal, or None for identifier primes."""

    if source[start] != "'" or start + 2 >= len(source):
        return None
    cursor = start + 1
    character = source[cursor]
    if character in "\r\n'":
        return None
    if character != "\\":
        cursor += 1
    else:
        cursor += 1
        if cursor >= len(source):
            return None
        escape = source[cursor]
        if escape == "u" and cursor + 1 < len(source) and source[cursor + 1] == "{":
            close = source.find("}", cursor + 2)
            if close < 0:
                return None
            digits = source[cursor + 2 : close]
            if not 1 <= len(digits) <= 6 or any(
                digit not in "0123456789abcdefABCDEF" for digit in digits
            ):
                return None
            cursor = close + 1
        elif escape in {"u", "U", "x"}:
            width = {"u": 4, "U": 8, "x": 2}[escape]
            digits = source[cursor + 1 : cursor + 1 + width]
            if len(digits) != width or any(
                digit not in "0123456789abcdefABCDEF" for digit in digits
            ):
                return None
            cursor += 1 + width
        else:
            cursor += 1
    if cursor < len(source) and source[cursor] == "'":
        return cursor + 1
    return None


def code_without_comments_or_strings(source: str) -> str:
    """Blank Lean comments, strings, and character literals while preserving lines."""

    output: list[str] = []
    index = 0
    block_depth = 0
    in_string = False
    while index < len(source):
        char = source[index]
        pair = source[index : index + 2]
        if block_depth:
            if pair == "/-":
                output.extend("  ")
                block_depth += 1
                index += 2
            elif pair == "-/":
                output.extend("  ")
                block_depth -= 1
                index += 2
            else:
                output.append("\n" if char == "\n" else " ")
                index += 1
            continue
        if in_string:
            if char == "\\" and index + 1 < len(source):
                output.extend("  ")
                index += 2
            elif char == '"':
                output.append(" ")
                in_string = False
                index += 1
            else:
                output.append("\n" if char == "\n" else " ")
                index += 1
            continue
        character_literal_end = _character_literal_end(source, index)
        if character_literal_end is not None:
            output.extend(
                "\n" if value == "\n" else " "
                for value in source[index:character_literal_end]
            )
            index = character_literal_end
        elif pair == "/-":
            output.extend("  ")
            block_depth = 1
            index += 2
        elif pair == "--":
            while index < len(source) and source[index] != "\n":
                output.append(" ")
                index += 1
        elif char == '"':
            output.append(" ")
            in_string = True
            index += 1
        else:
            output.append(char)
            index += 1
    if block_depth:
        raise AuditError("unterminated block comment in Lean source")
    if in_string:
        raise AuditError("unterminated string in Lean source")
    return "".join(output)


def tracked_lean_paths(root: Path) -> list[str]:
    completed = subprocess.run(
        ["git", "-C", str(root), "ls-files", "--", LEAN_DIR_REL.as_posix()],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if completed.returncode == 0:
        paths = sorted(
            line for line in completed.stdout.splitlines() if line.endswith(".lean")
        )
    else:
        lean_dir = root / LEAN_DIR_REL
        paths = sorted(
            path.relative_to(root).as_posix()
            for path in lean_dir.rglob("*.lean")
            if path.is_file() and not path.is_symlink()
        )
    if not paths:
        raise AuditError(f"no Lean sources found below {LEAN_DIR_REL}")
    if len(paths) != len(set(paths)):
        raise AuditError("duplicate Lean source path in inventory")
    return paths


def finding_record(
    *, construct: str, relative: str, source: str, code: str, offset: int
) -> dict[str, Any]:
    line = code.count("\n", 0, offset) + 1
    source_lines = source.splitlines()
    return {
        "construct": construct,
        "line": line,
        "path": relative,
        "source_line": source_lines[line - 1].strip(),
    }


def scan_sources(
    root: Path, relative_paths: Iterable[str] | None = None
) -> dict[str, Any]:
    root = root.resolve()
    paths = sorted(relative_paths if relative_paths is not None else tracked_lean_paths(root))
    records: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []
    noncomputable_occurrences = 0
    for relative in paths:
        path = root / relative
        try:
            path.resolve().relative_to(root)
        except ValueError as exc:
            raise AuditError(f"Lean source escapes audit root: {relative}") from exc
        raw = read_regular(path, MAX_SOURCE_BYTES)
        try:
            source = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise AuditError(f"Lean source is not UTF-8: {relative}") from exc
        code = code_without_comments_or_strings(source)
        noncomputable_occurrences += len(re.findall(r"\bnoncomputable\b", code))
        for construct, pattern in CONSTRUCT_PATTERNS.items():
            for match in pattern.finditer(code):
                findings.append(
                    finding_record(
                        construct=construct,
                        relative=relative,
                        source=source,
                        code=code,
                        offset=match.start(),
                    )
                )
        records.append(
            {
                "bytes": len(raw),
                "path": relative,
                "sha256": sha256_bytes(raw),
            }
        )

    findings.sort(key=lambda row: (row["path"], row["line"], row["construct"]))
    selected_paths = set(paths)
    expected_allowed = [
        {
            "construct": construct,
            "path": relative,
            "source_line": source_line,
        }
        for relative, constructs in sorted(ALLOWED_LOCAL_CONSTRUCTS.items())
        if relative in selected_paths
        for construct, source_lines in sorted(constructs.items())
        for source_line in source_lines
    ]
    observed_allowed_without_lines = [
        {
            "construct": row["construct"],
            "path": row["path"],
            "source_line": row["source_line"],
        }
        for row in findings
        if row["construct"] == "implemented_by"
    ]
    if observed_allowed_without_lines != expected_allowed:
        raise AuditError(
            "forbidden or missing implemented_by construct: "
            f"expected={expected_allowed!r} actual={observed_allowed_without_lines!r}"
        )
    forbidden = [row for row in findings if row["construct"] != "implemented_by"]
    if forbidden:
        raise AuditError(f"forbidden Lean construct findings: {forbidden!r}")
    allowed = [
        {**row, "classification": "dump-only trusted runtime mirror"}
        for row in findings
        if row["construct"] == "implemented_by"
    ]
    allowed.sort(key=lambda row: (row["path"], row["line"], row["construct"]))
    payload = {
        "files": records,
        "construct_policy": {
            "allowed_exact_source_lines": expected_allowed,
            "allowed_findings": allowed,
            "forbidden_by_default": sorted(CONSTRUCT_PATTERNS),
            "forbidden_findings": forbidden,
            "noncomputable_classification": (
                "Lean noncomputable declarations are counted but are not logical "
                "admissions or executable-code substitutions."
            ),
            "noncomputable_occurrences": noncomputable_occurrences,
            "scan_scope": "comments and string bodies removed; executable Lean tokens scanned",
        },
        "file_count": len(records),
    }
    payload["aggregate_sha256"] = sha256_bytes(canonical_bytes(payload))
    return payload


def run_checked(
    command: list[str], *, cwd: Path, input_text: str | None = None
) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment.update({"LANG": "C", "LC_ALL": "C"})
    completed = subprocess.run(
        command,
        cwd=cwd,
        env=environment,
        input=input_text,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=180,
        check=False,
    )
    if completed.returncode != 0:
        detail = (completed.stdout + completed.stderr).strip()
        raise AuditError(
            f"command failed ({completed.returncode}): {' '.join(command)}"
            + (f"\n{detail}" if detail else "")
        )
    if completed.stderr.strip():
        raise AuditError(
            f"command emitted unexpected stderr: {' '.join(command)}\n"
            f"{completed.stderr.strip()}"
        )
    return completed


def collect_identity_bindings(
    root: Path,
) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    bindings: list[dict[str, Any]] = []
    theorem_axioms: dict[str, list[str]] = {}
    root_modules: set[str] = set()
    for lane, relative, expected_schema in IDENTITY_CONFIGS:
        path = root / relative
        raw = read_regular(path, MAX_EVIDENCE_BYTES)
        identity = strict_json(path)
        if identity.get("schema") != expected_schema:
            raise AuditError(
                f"proof identity schema mismatch for {lane}: {identity.get('schema')!r}"
            )
        proof = identity.get("proof")
        closure = identity.get("source_closure")
        checker = identity.get("checker")
        if not isinstance(proof, dict) or not isinstance(closure, dict) or not isinstance(checker, dict):
            raise AuditError(f"proof identity missing proof/source/checker object: {relative}")
        theorem_rows = proof.get("theorems")
        modules = closure.get("root_modules")
        if not isinstance(theorem_rows, list) or not isinstance(modules, list):
            raise AuditError(f"proof identity has malformed theorem/module list: {relative}")
        lane_theorems: list[str] = []
        for row in theorem_rows:
            if not isinstance(row, dict):
                raise AuditError(f"malformed theorem row in {relative}")
            theorem = row.get("theorem")
            axioms = row.get("axioms")
            if not isinstance(theorem, str) or not theorem:
                raise AuditError(f"malformed theorem name in {relative}")
            if axioms != list(ALLOWED_AXIOMS):
                raise AuditError(
                    f"identity theorem axiom policy mismatch for {theorem}: {axioms!r}"
                )
            prior = theorem_axioms.setdefault(theorem, list(axioms))
            if prior != axioms:
                raise AuditError(f"conflicting theorem axiom declarations for {theorem}")
            lane_theorems.append(theorem)
        for module in modules:
            if not isinstance(module, str) or not module:
                raise AuditError(f"malformed root module in {relative}")
            root_modules.add(module)
        checker_path_value = checker.get("path")
        if not isinstance(checker_path_value, str) or not checker_path_value:
            raise AuditError(f"proof identity has malformed checker path: {relative}")
        checker_path = root / checker_path_value
        checker_raw = read_regular(checker_path, 512 * 1024 * 1024)
        checker_digest = sha256_bytes(checker_raw)
        if checker.get("sha256") != checker_digest or checker.get("bytes") != len(checker_raw):
            raise AuditError(f"checker bytes do not match proof identity for lane {lane}")
        identity_digest = identity.get("identity_digest_sha256")
        if not isinstance(identity_digest, str) or re.fullmatch(r"[0-9a-f]{64}", identity_digest) is None:
            raise AuditError(f"malformed semantic identity digest for lane {lane}")
        identity_body = {
            key: value for key, value in identity.items() if key != "identity_digest_sha256"
        }
        calculated_identity_digest = sha256_bytes(canonical_bytes(identity_body))
        if identity_digest != calculated_identity_digest:
            raise AuditError(
                f"proof identity self-digest mismatch for lane {lane}: "
                f"recorded={identity_digest} actual={calculated_identity_digest}"
            )
        bindings.append(
            {
                "checker_bytes": len(checker_raw),
                "checker_path": checker_path_value,
                "checker_sha256": checker_digest,
                "identity_bytes": len(raw),
                "identity_checker_bytes": checker["bytes"],
                "identity_checker_sha256": checker["sha256"],
                "identity_digest_sha256": identity_digest,
                "identity_path": relative.as_posix(),
                "identity_schema": expected_schema,
                "identity_sha256": sha256_bytes(raw),
                "lane": lane,
                "root_modules": sorted(modules),
                "theorems": lane_theorems,
            }
        )
    return bindings, sorted(theorem_axioms), sorted(root_modules)


def run_theorem_axiom_audit(
    root: Path,
    theorem_names: list[str],
    root_modules: list[str],
    identity_bindings: list[dict[str, Any]],
) -> dict[str, Any]:
    observed: dict[str, tuple[list[str], str]] = {}
    invocations: list[dict[str, Any]] = []
    for binding in identity_bindings:
        modules = binding["root_modules"]
        lane_theorems = binding["theorems"]
        program = "\n".join(
            [f"import {module}" for module in modules]
            + [f"#print axioms {theorem}" for theorem in lane_theorems]
        ) + "\n"
        completed = run_checked(
            ["lake", "env", "lean", "/dev/stdin"],
            cwd=root / LEAN_DIR_REL,
            input_text=program,
        )
        raw_output = completed.stdout
        invocation_theorems: list[str] = []
        for line in raw_output.splitlines():
            match = AXIOM_LINE_RE.fullmatch(line)
            if match is None:
                raise AuditError(f"unexpected #print axioms output: {line!r}")
            theorem, raw_axioms = match.groups()
            axioms = (
                [] if not raw_axioms else [item.strip() for item in raw_axioms.split(",")]
            )
            current = (axioms, line)
            if theorem in observed and observed[theorem] != current:
                raise AuditError(f"conflicting #print axioms result: {theorem}")
            observed[theorem] = current
            invocation_theorems.append(theorem)
        if invocation_theorems != lane_theorems:
            raise AuditError(
                f"#print axioms output order/set mismatch for lane {binding['lane']}"
            )
        invocations.append(
            {
                "input_program_sha256": sha256_bytes(program.encode("utf-8")),
                "lane": binding["lane"],
                "output_sha256": sha256_bytes(raw_output.encode("utf-8")),
                "root_modules": modules,
                "theorem_count": len(lane_theorems),
            }
        )
    if set(observed) != set(theorem_names):
        raise AuditError(
            "#print axioms theorem set mismatch: "
            f"missing={sorted(set(theorem_names) - set(observed))} "
            f"extra={sorted(set(observed) - set(theorem_names))}"
        )
    rows: list[dict[str, Any]] = []
    for theorem in theorem_names:
        axioms, line = observed[theorem]
        if axioms != list(ALLOWED_AXIOMS):
            raise AuditError(f"unexpected axiom surface for {theorem}: {axioms!r}")
        rows.append({"axioms": axioms, "raw_output": line, "theorem": theorem})
    return {
        "allowed_exactly": list(ALLOWED_AXIOMS),
        "command": "lake env lean /dev/stdin",
        "invocations": invocations,
        "root_modules": root_modules,
        "theorem_count": len(rows),
        "theorems": rows,
    }


def collect_compatibility_snapshots(root: Path) -> dict[str, Any]:
    relative = Path("release/compat/v172_floor.json")
    path = root / relative
    raw = read_regular(path, MAX_EVIDENCE_BYTES)
    floor = strict_json(path)
    if floor.get("schema") != "jackal-proof-compatibility-floor-v1":
        raise AuditError("unexpected proof compatibility-floor schema")
    lanes = floor.get("lanes")
    if not isinstance(lanes, dict):
        raise AuditError("proof compatibility floor has no lanes object")
    snapshots: list[dict[str, Any]] = []
    for lane, policies in sorted(lanes.items()):
        if not isinstance(policies, dict):
            raise AuditError(f"malformed compatibility policy for {lane}")
        for epoch_class, policy in sorted(policies.items()):
            if not isinstance(policy, dict):
                raise AuditError(f"malformed compatibility snapshot for {lane}/{epoch_class}")
            identity_relative = policy.get("identity_file")
            expected_digest = policy.get("identity_file_sha256")
            if not isinstance(identity_relative, str) or not isinstance(expected_digest, str):
                raise AuditError(f"compatibility snapshot lacks identity binding: {lane}/{epoch_class}")
            identity_raw = read_regular(root / identity_relative, MAX_EVIDENCE_BYTES)
            actual_digest = sha256_bytes(identity_raw)
            if actual_digest != expected_digest:
                raise AuditError(
                    f"compatibility identity drift for {lane}/{epoch_class}: "
                    f"expected={expected_digest} actual={actual_digest}"
                )
            snapshots.append(
                {
                    "allowed_release_epochs": policy.get("allowed_release_epochs"),
                    "epoch_class": epoch_class,
                    "identity_path": identity_relative,
                    "identity_schema": policy.get("schema"),
                    "identity_sha256": actual_digest,
                    "lane": lane,
                    "mode": policy.get("mode", "current"),
                    "reason": policy.get("reason"),
                }
            )
    return {
        "classification": (
            "Compatibility snapshots constrain replay or refusal policy; they are "
            "evidence inputs, not Lean logical admissions."
        ),
        "current_release_epoch": floor.get("current_release_epoch"),
        "floor_bytes": len(raw),
        "floor_path": relative.as_posix(),
        "floor_sha256": sha256_bytes(raw),
        "reversed_interval_policy": floor.get("reversed_interval_policy"),
        "snapshots": snapshots,
        "unsupported_policy": floor.get("unsupported_policy"),
    }


def collect_toolchain(root: Path) -> dict[str, Any]:
    lean_dir = root / LEAN_DIR_REL
    configuration_files: list[dict[str, Any]] = []
    configuration_bytes: dict[str, bytes] = {}
    for relative in (
        Path("proofs/lean/lakefile.toml"),
        Path("proofs/lean/lake-manifest.json"),
        Path("proofs/lean/lean-toolchain"),
    ):
        raw = read_regular(root / relative, MAX_EVIDENCE_BYTES)
        configuration_bytes[relative.as_posix()] = raw
        configuration_files.append(
            {"bytes": len(raw), "path": relative.as_posix(), "sha256": sha256_bytes(raw)}
        )
    manifest = strict_json(root / "proofs/lean/lake-manifest.json")
    packages = manifest.get("packages")
    if not isinstance(packages, list):
        raise AuditError("lake manifest has no package list")
    mathlib = [row for row in packages if isinstance(row, dict) and row.get("name") == "mathlib"]
    if len(mathlib) != 1 or not isinstance(mathlib[0].get("rev"), str):
        raise AuditError("lake manifest does not pin exactly one mathlib revision")
    version = run_checked(["lake", "env", "lean", "--version"], cwd=lean_dir).stdout.strip()
    executable_text = run_checked(["lake", "env", "which", "lean"], cwd=lean_dir).stdout.strip()
    executable = Path(executable_text)
    executable_raw = read_regular(executable, 512 * 1024 * 1024)
    try:
        toolchain_token = configuration_bytes[
            "proofs/lean/lean-toolchain"
        ].decode("utf-8").strip()
    except UnicodeDecodeError as exc:
        raise AuditError("lean-toolchain is not UTF-8") from exc
    return {
        "configuration_files": configuration_files,
        "lean": {
            "executable_bytes": len(executable_raw),
            "executable_sha256": sha256_bytes(executable_raw),
            "version_output": version,
        },
        "lean_toolchain": toolchain_token,
        "mathlib_revision": mathlib[0]["rev"],
    }


def build_audit(root: Path) -> dict[str, Any]:
    root = root.resolve()
    inventory = scan_sources(root)
    bindings, theorem_names, root_modules = collect_identity_bindings(root)
    theorem_audit = run_theorem_axiom_audit(
        root, theorem_names, root_modules, bindings
    )
    compatibility = collect_compatibility_snapshots(root)
    generator_raw = read_regular(root / GENERATOR_REL, MAX_EVIDENCE_BYTES)
    document: dict[str, Any] = {
        "audit_result": {
            "logical_admission_count": 0,
            "repository_axiom_declaration_count": 0,
            "status": "pass",
            "unexpected_construct_count": 0,
        },
        "generator": {
            "bytes": len(generator_raw),
            "path": GENERATOR_REL.as_posix(),
            "sha256": sha256_bytes(generator_raw),
        },
        "release_bindings": {
            "compatibility_snapshot_inputs": compatibility,
            "current_proof_identities": bindings,
            "lane_identifier_mapping": {
                "classification": (
                    "Compatibility-floor lane keys and proof-checker lane ids are "
                    "separate namespaces; this map is their explicit relationship."
                ),
                "compatibility_floor_to_proof_checker": {
                    "int_cert": "int-cert",
                    "range": "range",
                    "rational_variants": "range",
                },
                "proof_checker_without_compatibility_floor": ["gaussian"],
            },
            "release_state": "v1.7.3-candidate",
        },
        "residual_nonclaims": [
            "This audit is not a cryptographic signature or builder authentication.",
            "Lean kernel, compiler, mathlib, operating system, hardware, and supply chain remain trusted dependencies.",
            "The audit does not prove Lean source-to-native checker refinement.",
            "Runtime request parsing, provenance validation, and release-policy enforcement remain outside the named theorem statements except where a checker premise explicitly binds them.",
            "Compatibility snapshots state replay/refusal policy and do not turn historical artifacts into current proofs.",
        ],
        "schema": "jackal-lean-admission-audit-v1",
        "source_inventory": inventory,
        "theorem_axiom_audit": theorem_audit,
        "toolchain": collect_toolchain(root),
        "trust_surface": {
            "allowed_local_runtime_substitutions": inventory["construct_policy"]["allowed_findings"],
            "lean_standard_axioms": list(ALLOWED_AXIOMS),
            "logical_admissions": [],
            "repository_axiom_declarations": [],
            "runtime_substitution_boundary": (
                "The two implemented_by attributes are confined to dump-only parser/lowering "
                "mirrors; current checker acceptance uses neither definition."
            ),
        },
    }
    document["audit_digest_sha256"] = sha256_bytes(canonical_bytes(document))
    return document


def render_audit(root: Path) -> bytes:
    return pretty_bytes(build_audit(root))


def write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".lean-audit.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def check_committed(root: Path) -> None:
    path = root / ARTIFACT_REL
    expected = render_audit(root)
    actual = read_regular(path, MAX_EVIDENCE_BYTES)
    if actual != expected:
        raise AuditError(f"generated audit differs from committed artifact: {ARTIFACT_REL}")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="verify the committed artifact")
    mode.add_argument("--write", action="store_true", help="atomically replace the artifact")
    mode.add_argument(
        "--source-check",
        action="store_true",
        help="platform-neutral tracked-source policy check without release binaries",
    )
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    root = args.root.resolve()
    if args.source_check:
        inventory = scan_sources(root)
        print(
            "LEAN_SOURCE_ADMISSION_PASS "
            f"files={inventory['file_count']} admissions=0"
        )
        return 0
    if args.write:
        write_atomic(root / ARTIFACT_REL, render_audit(root))
    else:
        check_committed(root)
    document = strict_json(root / ARTIFACT_REL)
    print(
        "LEAN_ADMISSION_AUDIT_PASS "
        f"files={document['source_inventory']['file_count']} "
        f"theorems={document['theorem_axiom_audit']['theorem_count']} "
        f"admissions={document['audit_result']['logical_admission_count']}"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (AuditError, OSError, subprocess.SubprocessError) as error:
        print(f"LEAN_ADMISSION_AUDIT_REFUSED detail={str(error)[:1000]}", file=sys.stderr)
        raise SystemExit(1) from None
