#!/usr/bin/env python3
"""Generate and verify JACKAL's Gaussian and range proof/build identities.

The record is deliberately an unsigned, deterministic binding.  It identifies
the local Lean source closure, dependency locks, theorem/axiom surface, and one
platform checker build.  It is not a signature, an authentication mechanism,
or a proof that the Lean compiler preserved the source semantics.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, Iterable


REPO_ROOT = Path(__file__).resolve().parents[2]
LEAN_DIR = REPO_ROOT / "proofs" / "lean"
ALLOWED_AXIOMS = ("propext", "Classical.choice", "Quot.sound")


@dataclass(frozen=True)
class LaneConfig:
    schema: str
    identity_name: str
    checker_path: str
    checker_target: str
    root_modules: tuple[str, ...]
    fragment: dict[str, Any]
    theorems: tuple[str, ...]
    allowed_local_constructs: dict[str, dict[str, tuple[str, ...]]]


LANES = {
    "gaussian": LaneConfig(
        schema="jackal-gaussian-proof-identity-v1",
        identity_name="gaussian_proof_identity.json",
        checker_path="proofs/lean/.lake/build/bin/jackal_gaussian_check",
        checker_target="jackal_gaussian_check",
        root_modules=("JackalIv.GaussianCertMain",),
        fragment={
            "assurance": "formal-bounded",
            "certificate_magic": "jackal-gaussian-integral-cert v1",
            "checker_boolean_definition": "JackalIv.GaussianCert.checkCert",
            "checker_entrypoint_definition": "runGaussianCert",
            "checker_executable": "jackal_gaussian_check",
            "family": "gaussian-exp-square-v1",
            "lane": "gaussian",
            "parser_definition": "JackalIv.GaussianCert.parseCert",
            "runtime_alternate_implementation_boundary": "none in local source closure",
            "soundness_theorem": "JackalIv.GaussianCert.gaussian_integral_check_sound",
            "theorem_premises": ["checkCert c = true (runtime checked)"],
            "premises_not_discharged_by_checker": [],
        },
        theorems=(
            "JackalIv.GaussianCert.gaussian_integral_check_sound",
            "JackalIv.Gaussian.scaled_gaussian_enclosed",
            "JackalIv.Gaussian.checker_core_enclosed",
            "JackalIv.Gaussian.expNegQ_encloses",
            "JackalIv.Gaussian.sqrtPi_enclosed",
            "JackalIv.GaussianCert.checkCert_iff",
        ),
        allowed_local_constructs={},
    ),
    "range": LaneConfig(
        schema="jackal-range-proof-identity-v1",
        identity_name="range_proof_identity.json",
        checker_path="proofs/lean/.lake/build/bin/jackal_cert_check",
        checker_target="jackal_cert_check",
        root_modules=("JackalIv.CertCheckMain",),
        fragment={
            "assurance": "formal-bounded",
            "certificate_magic": "jackal-eval-cert v2",
            "checker_boolean_definition": "JackalIv.Cert.checkCert",
            "checker_entrypoint_definition": "runRequestBound",
            "checker_executable": "jackal_cert_check",
            "family": "range-request-bound-v1",
            "lane": "range",
            "parser_definition": "JackalIv.Cert.parseCert",
            "request_matcher_definition": "JackalIv.Cert.requestMatches",
            "runtime_alternate_implementation_boundary": (
                "request acceptance uses no implemented_by definition; two exact dump-only "
                "implemented_by attributes elsewhere in the imported closure are pinned"
            ),
            "soundness_theorem": "JackalIv.Cert.request_bound_certified_release",
            "theorem_premises": [
                "requestMatches command rawExpr rawLo rawHi hdr nodes = true (runtime checked)",
                "checkCert hdr nodes = true (runtime checked)",
                "ModelTCB hdr nodes",
                "((hdr.input_lo : ℚ) : ℝ) ≤ ((hdr.input_hi : ℚ) : ℝ)",
            ],
            "premises_not_discharged_by_checker": [
                "ModelTCB hdr nodes = LibmModel hdr nodes ∧ ConstTCB nodes",
                "input interval ordering ((input_lo : ℚ) : ℝ) ≤ (input_hi : ℚ) : ℝ",
            ],
        },
        theorems=(
            "JackalIv.Cert.request_bound_certified_release",
            "JackalIv.Cert.requestMatches_true",
            "JackalIv.Cert.lowerRaw_toExpr",
            "JackalIv.Cert.rawExprOf_toExpr",
            "JackalIv.Cert.cert_check_sound",
            "JackalIv.parse_lower_encloses",
        ),
        allowed_local_constructs={
            "proofs/lean/JackalIv/Correspondence.lean": {
                "implemented_by": (
                    "@[implemented_by Dump.parseSexpImpl]",
                    "@[implemented_by Dump.lowerSexpImpl]",
                )
            }
        },
    ),
}


def configure_lane(name: str) -> None:
    config = LANES[name]
    global SCHEMA, DEFAULT_IDENTITY, CHECKER_REL, CHECKER_TARGET
    global ROOT_MODULES, FRAGMENT, THEOREMS, ALLOWED_LOCAL_CONSTRUCTS
    SCHEMA = config.schema
    DEFAULT_IDENTITY = REPO_ROOT / "release" / "evidence" / config.identity_name
    CHECKER_REL = Path(config.checker_path)
    CHECKER_TARGET = config.checker_target
    ROOT_MODULES = config.root_modules
    FRAGMENT = config.fragment
    THEOREMS = config.theorems
    ALLOWED_LOCAL_CONSTRUCTS = config.allowed_local_constructs


configure_lane("gaussian")

FORBIDDEN_LOCAL_CONSTRUCTS = {
    "admit": re.compile(r"\badmit\b"),
    "axiom_declaration": re.compile(
        r"(?m)^\s*(?:@\[[^\n]*\]\s*)*(?:private\s+)?axioms?\s+"
    ),
    "extern": re.compile(r"\bextern\b"),
    "implemented_by": re.compile(r"@\[\s*implemented_by\b"),
    "native_decide": re.compile(r"\bnative_decide\b"),
    "partial": re.compile(r"\bpartial\b"),
    "sorry": re.compile(r"\bsorry\b"),
    "unsafe": re.compile(r"\bunsafe\b"),
}

MODULE_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_']*(?:\.[A-Za-z_][A-Za-z0-9_']*)*")
LEAN_VERSION_RE = re.compile(
    r"^Lean \(version ([^,]+), ([^,]+), commit ([0-9a-f]{40}), ([^)]+)\)$"
)
AXIOM_LINE_RE = re.compile(r"^'([^']+)' depends on axioms: \[(.*)\]$")


class GateError(RuntimeError):
    """A proof identity invariant failed."""


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


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def repo_relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
    except ValueError as exc:
        raise GateError(f"path escapes repository: {path}") from exc


def run(
    command: Iterable[str],
    *,
    cwd: Path,
    input_text: str | None = None,
    allow_stderr: bool = False,
) -> str:
    env = os.environ.copy()
    env.update({"LANG": "C", "LC_ALL": "C"})
    argv = list(command)
    result = subprocess.run(
        argv,
        cwd=cwd,
        env=env,
        input=input_text,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        detail = (result.stdout + result.stderr).strip()
        raise GateError(
            f"command failed ({result.returncode}): {' '.join(argv)}"
            + (f"\n{detail}" if detail else "")
        )
    if result.stderr.strip() and not allow_stderr:
        raise GateError(
            f"command emitted unexpected stderr: {' '.join(argv)}\n{result.stderr.strip()}"
        )
    return result.stdout.strip()


def code_without_comments_or_strings(source: str) -> str:
    """Replace Lean comments and string bodies with spaces, retaining newlines."""

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

        if pair == "/-":
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
        raise GateError("unterminated block comment while scanning Lean source")
    if in_string:
        raise GateError("unterminated string while scanning Lean source")
    return "".join(output)


def module_path(module: str) -> Path:
    return LEAN_DIR / (module.replace(".", "/") + ".lean")


def parse_imports(path: Path, code: str) -> list[str]:
    imports: list[str] = []
    for line_number, line in enumerate(code.splitlines(), start=1):
        match = re.match(r"^\s*import\s+(.+?)\s*$", line)
        if match is None:
            continue
        tokens = match.group(1).split()
        if not tokens or any(MODULE_RE.fullmatch(token) is None for token in tokens):
            raise GateError(f"unsupported import syntax at {repo_relative(path)}:{line_number}")
        imports.extend(tokens)
    return imports


def collect_source_closure() -> dict[str, Any]:
    pending = list(ROOT_MODULES)
    seen_modules: set[str] = set()
    records: list[dict[str, Any]] = []
    external_imports: set[str] = set()
    observed_allowed_constructs: list[dict[str, Any]] = []

    while pending:
        module = pending.pop()
        if module in seen_modules:
            continue
        path = module_path(module)
        if not path.is_file():
            raise GateError(f"missing local root/import module: {module} ({path})")
        seen_modules.add(module)

        raw = path.read_bytes()
        try:
            source = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise GateError(f"Lean source is not UTF-8: {repo_relative(path)}") from exc
        code = code_without_comments_or_strings(source)
        imports = parse_imports(path, code)
        relative_path = repo_relative(path)
        source_lines = source.splitlines()
        allowed_for_path = ALLOWED_LOCAL_CONSTRUCTS.get(relative_path, {})
        for name, pattern in FORBIDDEN_LOCAL_CONSTRUCTS.items():
            matched_lines = [
                source_lines[code.count("\n", 0, match.start())].strip()
                for match in pattern.finditer(code)
            ]
            expected_lines = list(allowed_for_path.get(name, ()))
            if matched_lines != expected_lines:
                raise GateError(
                    f"local Lean construct policy mismatch in {relative_path} for {name}: "
                    f"expected={expected_lines} actual={matched_lines}"
                )
            if matched_lines:
                observed_allowed_constructs.append(
                    {
                        "construct": name,
                        "path": relative_path,
                        "source_lines": matched_lines,
                    }
                )

        for imported in imports:
            imported_path = module_path(imported)
            if imported_path.is_file():
                pending.append(imported)
            else:
                external_imports.add(imported)

        records.append(
            {
                "bytes": len(raw),
                "imports": imports,
                "module": module,
                "path": relative_path,
                "sha256": sha256_bytes(raw),
            }
        )

    records.sort(key=lambda item: item["path"])
    expected_allowed_constructs = [
        {"construct": construct, "path": path, "source_lines": list(lines)}
        for path, constructs in sorted(ALLOWED_LOCAL_CONSTRUCTS.items())
        for construct, lines in sorted(constructs.items())
    ]
    observed_allowed_constructs.sort(key=lambda item: (item["path"], item["construct"]))
    if observed_allowed_constructs != expected_allowed_constructs:
        raise GateError(
            "allowed local Lean construct set is outside the selected source closure: "
            f"expected={expected_allowed_constructs} actual={observed_allowed_constructs}"
        )
    closure_payload = {
        "external_imports": sorted(external_imports),
        "files": records,
        "root_modules": list(ROOT_MODULES),
    }
    return {
        **closure_payload,
        "aggregate_sha256": sha256_bytes(canonical_bytes(closure_payload)),
        "definition": (
            "Every repository-local transitive Lean import reachable from root_modules; "
            "external imports are bound through lake-manifest.json and named here."
        ),
        "local_construct_policy": {
            "allowed_exact_source_lines": observed_allowed_constructs,
            "forbidden_by_default": sorted(FORBIDDEN_LOCAL_CONSTRUCTS),
        },
    }


def strict_json_load(path: Path) -> Any:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise GateError(f"duplicate JSON key in {repo_relative(path)}: {key}")
            result[key] = value
        return result

    try:
        return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=reject_duplicates)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GateError(f"cannot parse identity JSON {path}: {exc}") from exc


def normalized_packages(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    packages = manifest.get("packages")
    if not isinstance(packages, list):
        raise GateError("lake-manifest.json has no packages array")
    normalized: list[dict[str, Any]] = []
    for package in packages:
        if not isinstance(package, dict):
            raise GateError("lake-manifest.json contains a non-object package")
        for key in ("name", "type", "rev"):
            if not isinstance(package.get(key), str) or not package[key]:
                raise GateError(f"lake package is missing a pinned {key}: {package!r}")
        revision = package["rev"]
        if package["type"] == "git" and re.fullmatch(r"[0-9a-f]{40}", revision) is None:
            raise GateError(f"git package {package['name']} is not pinned to a full commit")
        normalized.append(
            {
                "config_file": package.get("configFile"),
                "inherited": package.get("inherited"),
                "input_revision": package.get("inputRev"),
                "manifest_file": package.get("manifestFile"),
                "name": package["name"],
                "revision": revision,
                "scope": package.get("scope"),
                "subdirectory": package.get("subDir"),
                "type": package["type"],
                "url": package.get("url"),
            }
        )
    normalized.sort(key=lambda item: item["name"])
    return normalized


def validate_package_checkouts(packages: list[dict[str, Any]]) -> None:
    for package in packages:
        if package["type"] != "git":
            continue
        checkout = LEAN_DIR / ".lake" / "packages" / package["name"]
        if not checkout.is_dir():
            raise GateError(
                f"missing locked package checkout {package['name']}; run lake build first"
            )
        actual = run(["git", "rev-parse", "HEAD"], cwd=checkout)
        if actual != package["revision"]:
            raise GateError(
                f"package checkout mismatch for {package['name']}: "
                f"manifest={package['revision']} checkout={actual}"
            )
        dirty = run(
            ["git", "status", "--porcelain", "--untracked-files=all"], cwd=checkout
        )
        if dirty:
            raise GateError(
                f"package checkout is dirty for {package['name']}; commit pins do not "
                "identify modified or untracked dependency bytes"
            )


def collect_toolchain() -> tuple[dict[str, Any], dict[str, Any]]:
    toolchain_path = LEAN_DIR / "lean-toolchain"
    manifest_path = LEAN_DIR / "lake-manifest.json"
    lakefile_path = LEAN_DIR / "lakefile.toml"
    for path in (toolchain_path, manifest_path, lakefile_path):
        if not path.is_file():
            raise GateError(f"missing Lean configuration file: {repo_relative(path)}")

    toolchain_raw = toolchain_path.read_bytes()
    try:
        toolchain_name = toolchain_raw.decode("utf-8").strip()
    except UnicodeDecodeError as exc:
        raise GateError("lean-toolchain is not UTF-8") from exc
    if not toolchain_name or b"\x00" in toolchain_raw:
        raise GateError("invalid lean-toolchain token")

    manifest = strict_json_load(manifest_path)
    if not isinstance(manifest, dict):
        raise GateError("lake-manifest.json root is not an object")
    packages = normalized_packages(manifest)
    validate_package_checkouts(packages)

    mathlib = [package for package in packages if package["name"] == "mathlib"]
    if len(mathlib) != 1:
        raise GateError("lake-manifest.json must contain exactly one mathlib package")

    lean_version_output = run(["lake", "env", "lean", "--version"], cwd=LEAN_DIR)
    version_match = LEAN_VERSION_RE.fullmatch(lean_version_output)
    if version_match is None:
        raise GateError(f"unrecognized Lean version output: {lean_version_output!r}")
    lean_version, lean_target, lean_commit, lean_build = version_match.groups()
    release_match = re.fullmatch(r"leanprover/lean4:v(.+)", toolchain_name)
    if release_match is not None and release_match.group(1) != lean_version:
        raise GateError(
            f"Lean version {lean_version} does not match toolchain token {toolchain_name}"
        )

    lake_version = run(["lake", "--version"], cwd=LEAN_DIR)
    lean_executable = Path(run(["lake", "env", "which", "lean"], cwd=LEAN_DIR)).resolve()
    if not lean_executable.is_file():
        raise GateError(f"Lean executable does not exist: {lean_executable}")
    toolchain = {
        "configuration_files": [
            {
                "path": repo_relative(lakefile_path),
                "sha256": sha256_file(lakefile_path),
            },
            {
                "path": repo_relative(manifest_path),
                "sha256": sha256_file(manifest_path),
            },
            {
                "path": repo_relative(toolchain_path),
                "sha256": sha256_bytes(toolchain_raw),
            },
        ],
        "lake_version": lake_version,
        "lean": {
            "build": lean_build,
            "commit": lean_commit,
            "version": lean_version,
        },
        "lean_toolchain": toolchain_name,
        "manifest_packages": packages,
        "mathlib_commit": mathlib[0]["revision"],
        "package_checkout_policy": (
            "Every git package checkout is clean and its HEAD equals its full "
            "lake-manifest revision during generation and verification."
        ),
    }
    observed = {
        "build": lean_build,
        "commit": lean_commit,
        "target": lean_target,
        "version": lean_version,
        "executable_bytes": lean_executable.stat().st_size,
        "executable_sha256": sha256_file(lean_executable),
    }
    return toolchain, observed


def run_axiom_audit() -> list[dict[str, Any]]:
    program = "\n".join(
        ["import " + " ".join(ROOT_MODULES)]
        + [f"#print axioms {theorem}" for theorem in THEOREMS]
    ) + "\n"
    output = run(
        ["lake", "env", "lean", "/dev/stdin"],
        cwd=LEAN_DIR,
        input_text=program,
    )
    observed: dict[str, list[str]] = {}
    for line in output.splitlines():
        match = AXIOM_LINE_RE.fullmatch(line)
        if match is None:
            raise GateError(f"unexpected #print axioms output: {line!r}")
        theorem, raw_axioms = match.groups()
        if theorem in observed:
            raise GateError(f"duplicate #print axioms output for {theorem}")
        axioms = [] if not raw_axioms else [part.strip() for part in raw_axioms.split(",")]
        observed[theorem] = axioms

    if set(observed) != set(THEOREMS):
        missing = sorted(set(THEOREMS) - set(observed))
        extra = sorted(set(observed) - set(THEOREMS))
        raise GateError(f"axiom theorem set mismatch: missing={missing} extra={extra}")
    for theorem in THEOREMS:
        if set(observed[theorem]) != set(ALLOWED_AXIOMS):
            raise GateError(
                f"unexpected axioms for {theorem}: {observed[theorem]} "
                f"(allowed exactly {list(ALLOWED_AXIOMS)})"
            )
    return [
        {"axioms": list(ALLOWED_AXIOMS), "theorem": theorem} for theorem in THEOREMS
    ]


def collect_proof_sections() -> dict[str, Any]:
    source_closure = collect_source_closure()
    toolchain, observed_compiler = collect_toolchain()
    theorem_axioms = run_axiom_audit()
    return {
        "generator": {
            "path": repo_relative(Path(__file__)),
            "sha256": sha256_file(Path(__file__)),
        },
        "fragment": FRAGMENT,
        "proof": {
            "axiom_audit_command": "lake env lean /dev/stdin with checked-in #print axioms set",
            "axiom_policy": {
                "allowed_exactly": list(ALLOWED_AXIOMS),
                "forbidden": ["sorryAx", "any additional axiom"],
            },
            "theorems": theorem_axioms,
        },
        "source_closure": source_closure,
        "toolchain": toolchain,
        "_observed_compiler": observed_compiler,
    }


def collect_checker(
    source_closure: dict[str, Any],
    toolchain: dict[str, Any],
    observed_compiler: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    checker_path = REPO_ROOT / CHECKER_REL
    if not checker_path.is_file():
        raise GateError(
            f"missing checker binary {repo_relative(checker_path)}; "
            f"run: cd proofs/lean && lake build {CHECKER_TARGET}"
        )
    checker = {
        "bytes": checker_path.stat().st_size,
        "path": CHECKER_REL.as_posix(),
        "sha256": sha256_file(checker_path),
        "target": CHECKER_TARGET,
    }
    attestation_body = {
        "build_command": ["lake", "build", CHECKER_TARGET],
        "checker": checker,
        "compiler_observed_for_build_platform": observed_compiler,
        "inputs": {
            "lean_commit": toolchain["lean"]["commit"],
            "mathlib_commit": toolchain["mathlib_commit"],
            "source_closure_sha256": source_closure["aggregate_sha256"],
            "toolchain_configuration": toolchain["configuration_files"],
        },
        "kind": "unsigned-local-build-binding-v1",
        "working_directory": "proofs/lean",
    }
    attestation_payload = {
        **attestation_body,
        "authentication": {
            "authenticated": False,
            "scheme": "none",
            "statement": (
                "This deterministic record binds observed checker bytes to named inputs. "
                "It is not a signature and does not authenticate the builder or artifact."
            ),
        },
        "claim_boundary": (
            "This is reproducibility/build-provenance evidence, not a proof of compiler, "
            "linker, operating-system, hardware, or supply-chain correctness."
        ),
    }
    attestation = {
        **attestation_payload,
        "attestation_digest_sha256": sha256_bytes(canonical_bytes(attestation_payload)),
    }
    return checker, attestation


def build_record() -> dict[str, Any]:
    sections = collect_proof_sections()
    observed_compiler = sections.pop("_observed_compiler")
    checker, attestation = collect_checker(
        sections["source_closure"], sections["toolchain"], observed_compiler
    )
    body = {
        "schema": SCHEMA,
        **sections,
        "checker": checker,
        "build_attestation": attestation,
    }
    return {
        **body,
        "identity_digest_sha256": sha256_bytes(canonical_bytes(body)),
    }


def verify_identity_envelope(path: Path, record: Any) -> dict[str, Any]:
    if not isinstance(record, dict):
        raise GateError("identity JSON root is not an object")
    if record.get("schema") != SCHEMA:
        raise GateError(f"unexpected identity schema: {record.get('schema')!r}")
    expected_keys = {
        "build_attestation",
        "checker",
        "fragment",
        "generator",
        "identity_digest_sha256",
        "proof",
        "schema",
        "source_closure",
        "toolchain",
    }
    if set(record) != expected_keys:
        raise GateError(
            f"identity top-level keys mismatch: expected={sorted(expected_keys)} "
            f"actual={sorted(record)}"
        )
    digest = record.get("identity_digest_sha256")
    if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
        raise GateError("identity_digest_sha256 is not a lowercase SHA-256")
    body = {key: value for key, value in record.items() if key != "identity_digest_sha256"}
    actual_digest = sha256_bytes(canonical_bytes(body))
    if digest != actual_digest:
        raise GateError(
            f"identity self-digest mismatch: recorded={digest} actual={actual_digest}"
        )
    raw = path.read_bytes()
    if raw != pretty_bytes(record):
        raise GateError("identity JSON is not in canonical checked-in formatting")
    return record


def first_difference(expected: Any, actual: Any, path: str = "$") -> str | None:
    if type(expected) is not type(actual):
        return f"{path}: type {type(expected).__name__} != {type(actual).__name__}"
    if isinstance(expected, dict):
        if set(expected) != set(actual):
            return f"{path}: keys {sorted(expected)} != {sorted(actual)}"
        for key in sorted(expected):
            difference = first_difference(expected[key], actual[key], f"{path}.{key}")
            if difference is not None:
                return difference
        return None
    if isinstance(expected, list):
        if len(expected) != len(actual):
            return f"{path}: list length {len(expected)} != {len(actual)}"
        for index, (left, right) in enumerate(zip(expected, actual)):
            difference = first_difference(left, right, f"{path}[{index}]")
            if difference is not None:
                return difference
        return None
    if expected != actual:
        return f"{path}: {expected!r} != {actual!r}"
    return None


def build_checker() -> None:
    run(["lake", "build", CHECKER_TARGET], cwd=LEAN_DIR, allow_stderr=True)


def command_generate(args: argparse.Namespace) -> None:
    configure_lane(args.lane)
    build_checker()
    record = build_record()
    output = Path(args.output).resolve() if args.output else DEFAULT_IDENTITY
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(pretty_bytes(record))
    print(
        f"GENERATED {repo_relative(output) if output.is_relative_to(REPO_ROOT) else output} "
        f"identity_sha256={record['identity_digest_sha256']} "
        f"checker_sha256={record['checker']['sha256']}"
    )


def command_check(args: argparse.Namespace) -> None:
    configure_lane(args.lane)
    build_checker()
    identity_path = Path(args.identity).resolve() if args.identity else DEFAULT_IDENTITY
    expected = verify_identity_envelope(identity_path, strict_json_load(identity_path))

    live_sections = collect_proof_sections()
    observed_compiler = live_sections.pop("_observed_compiler")
    for section in ("fragment", "generator", "proof", "source_closure", "toolchain"):
        difference = first_difference(expected[section], live_sections[section], f"$.{section}")
        if difference is not None:
            raise GateError(f"proof identity drift: {difference}")

    if args.proof_only:
        print(
            f"PASS {FRAGMENT['lane']} proof identity/axiom gate; "
            "checker byte/build binding intentionally not verified (--proof-only)"
        )
        return

    checker, attestation = collect_checker(
        live_sections["source_closure"], live_sections["toolchain"], observed_compiler
    )
    for section, actual in (("checker", checker), ("build_attestation", attestation)):
        difference = first_difference(expected[section], actual, f"$.{section}")
        if difference is not None:
            raise GateError(f"checker/build identity drift: {difference}")
    print(
        f"PASS {FRAGMENT['lane']} proof identity, axiom audit, and checker build binding "
        f"identity_sha256={expected['identity_digest_sha256']} "
        f"checker_sha256={expected['checker']['sha256']}"
    )


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    subcommands = result.add_subparsers(dest="command", required=True)

    generate = subcommands.add_parser("generate", help="write a deterministic identity record")
    generate.add_argument("--lane", choices=sorted(LANES), default="gaussian")
    generate.add_argument("--output")
    generate.set_defaults(handler=command_generate)

    check = subcommands.add_parser("check", help="verify a committed identity record")
    check.add_argument("--lane", choices=sorted(LANES), default="gaussian")
    check.add_argument("--identity")
    check.add_argument(
        "--proof-only",
        action="store_true",
        help="verify sources, locks, toolchain, and axioms but not platform checker bytes",
    )
    check.set_defaults(handler=command_check)
    return result


def main() -> int:
    args = parser().parse_args()
    try:
        args.handler(args)
    except GateError as exc:
        print(f"FAIL {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
