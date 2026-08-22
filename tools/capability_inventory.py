#!/usr/bin/env python3
"""Generate and verify JACKAL's canonical exported-capability inventory.

The executable catalog remains ``plugin/hermes/tools.json``.  This tool binds
that ordered roster to profile membership, semantic integration bytes,
release-manifest checker identities, proof-identity bytes, status vocabulary,
and explicit admission/refusal summaries. Package-delivery pins are verified by
``tools/capability_drift_gate.py`` instead: the package contains this inventory,
so binding the package-pinning provisioner here would create an unsealable
content-hash cycle. It computes no mathematical result and changes no verifier
accept condition.

Usage:
  python3 tools/capability_inventory.py --write [--root PATH]
  python3 tools/capability_inventory.py --check [--root PATH]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any

CATALOG_PATH = Path("plugin/hermes/tools.json")
PROFILE_DIR = Path("plugin/hermes/profiles")
MANIFEST_PATH = Path("release/MANIFEST.sha256")
ARTIFACT_PATH = Path("release/capability_inventory_v1.json")
PROFILE_IDS = ("core", "formal", "full")
EXPECTED_VERSION = "v1.7.3"
EXPECTED_TOOL_COUNT = 41
RELEASE_STATE = "v1.7.3-candidate"
CONTAINING_REF = {
    "kind": "candidate-commit",
    "value": "d25bcd9818e0d106f337798f80527ae611cc3acc",
}

ALLOWED_STATUSES = frozenset(
    {
        "ok",
        "exact",
        "structural-exact",
        "formal-bounded",
        "bounded",
        "checked",
        "estimated",
        "model-based",
        "verified",
        "verified-program-evidence",
        "verified-program-receipt",
        "indeterminate",
        "refused",
    }
)

INPUT_PATHS = (
    Path("tools/capability_inventory.py"),
    CATALOG_PATH,
    PROFILE_DIR / "core.json",
    PROFILE_DIR / "formal.json",
    PROFILE_DIR / "full.json",
    Path("plugin/hermes/server.py"),
    Path("plugins/jackel/.codex-plugin/plugin.json"),
    Path("plugins/jackel/mcp/server.py"),
    MANIFEST_PATH,
    Path("release/evidence/anubis_program_dogfood_v1.json"),
    Path("release/evidence/range_proof_identity_v172.json"),
    Path("release/evidence/gaussian_proof_identity.json"),
    Path("release/evidence/int_cert_proof_identity_v172.json"),
)

DEPENDENCY_GROUPS: dict[str, frozenset[str]] = {
    "lean-range": frozenset(
        {
            "jackal_range_bound",
            "jackal_sqrt_rat_bound",
            "jackal_exp_rat_bound",
            "jackal_ln_rat_bound",
            "jackal_sin_rat_bound",
            "jackal_cos_rat_bound",
            "jackal_atan_rat_bound",
            "jackal_tanh_rat_bound",
        }
    ),
    "lean-gaussian": frozenset({"jackal_gaussian_integral"}),
    "lean-int-cert": frozenset({"jackal_integrate_bound_cert"}),
    "lean-receipt-registry": frozenset({"jackal_verify_receipt"}),
    "exact-cert-verifier": frozenset(
        {
            "jackal_poly_canon",
            "jackal_poly_eq",
            "jackal_poly_gcd",
            "jackal_ratfunc_canon",
            "jackal_roots_isolate",
            "jackal_xgcd",
            "jackal_mod_pow",
            "jackal_mod_inv",
            "jackal_crt",
            "jackal_prime_cert",
        }
    ),
    "structural-checker": frozenset(
        {"jackal_test_exists", "jackal_claim_cites_test"}
    ),
    "decision-checker": frozenset(
        {"jackal_decision_rank", "jackal_decision_rank_v2"}
    ),
    "claim-router": frozenset({"jackal_claim"}),
    "claim-verifier": frozenset({"jackal_verify_bundle"}),
    "program-verifier": frozenset(
        {
            "jackal_anubis_check_program",
            "jackal_anubis_verify_program",
            "jackal_anubis_verify_program_receipt",
        }
    ),
    "runtime-only": frozenset(
        {
            "jackal_exact",
            "jackal_evaluate",
            "jackal_diff",
            "jackal_integrate",
            "jackal_integrate_adaptive",
            "jackal_integrate_bound",
            "jackal_solve",
            "jackal_canon",
            "jackal_alg_sign",
            "jackal_alg_cmp",
            "jackal_divides",
        }
    ),
}

DEPENDENCY_LABELS: dict[str, tuple[str, ...]] = {
    "lean-range": (
        "evaluator",
        "checker",
        "range-proof-identity",
        "range-proof-digest",
        "coverage-inventory",
    ),
    "lean-gaussian": (
        "evaluator",
        "gaussian-checker",
        "gaussian-proof-identity",
        "gaussian-proof-digest",
    ),
    "lean-int-cert": (
        "evaluator",
        "int-cert-checker",
        "int-cert-proof-identity",
        "int-cert-proof-digest",
    ),
    "lean-receipt-registry": (
        "checker",
        "range-proof-identity",
        "range-proof-digest",
        "archival-range-checker",
        "archival-range-coverage-inventory",
        "archival-range-proof-identity",
        "archival-range-proof-digest",
        "gaussian-checker",
        "gaussian-proof-identity",
        "gaussian-proof-digest",
        "int-cert-checker",
        "int-cert-proof-identity",
        "int-cert-proof-digest",
    ),
    "exact-cert-verifier": ("evaluator", "exact_verifier"),
    "structural-checker": (
        "domain_pack_registry",
        "domain_pack_verifier",
        "domain_pack_test_exists_checker",
    ),
    "decision-checker": (
        "domain_pack_registry",
        "domain_pack_verifier",
        "domain_pack_decision_checker",
        "claim_unit_registry",
    ),
    "claim-router": (
        "claim_kernel",
        "claim_router",
        "evaluator",
        "checker",
        "range-proof-identity",
        "range-proof-digest",
        "archival-range-checker",
        "archival-range-coverage-inventory",
        "archival-range-proof-identity",
        "archival-range-proof-digest",
        "gaussian-checker",
        "gaussian-proof-identity",
        "gaussian-proof-digest",
        "int-cert-checker",
        "int-cert-proof-identity",
        "int-cert-proof-digest",
        "exact_verifier",
        "claim_inference_registry",
        "claim_unit_registry",
    ),
    "claim-verifier": (
        "claim_verifier",
        "checker",
        "range-proof-identity",
        "range-proof-digest",
        "archival-range-checker",
        "archival-range-coverage-inventory",
        "archival-range-proof-identity",
        "archival-range-proof-digest",
        "gaussian-checker",
        "gaussian-proof-identity",
        "gaussian-proof-digest",
        "int-cert-checker",
        "int-cert-proof-identity",
        "int-cert-proof-digest",
        "exact_verifier",
        "claim_inference_registry",
        "claim_unit_registry",
    ),
    "program-verifier": (
        "anubis_program_verifier",
        "anubis_program_policy",
        "program-compatibility-floor",
        "compiler_pin",
    ),
    "runtime-only": ("evaluator",),
}

REFUSAL_BOUNDARIES = {
    "lean-range": (
        "Only the catalog-declared expression and canonical-rational interval "
        "fragment is admitted. Unsupported syntax, invalid intervals, missing or "
        "mismatched pins, producer/checker rejection, or identity drift refuses; "
        "there is no weaker-lane fallback."
    ),
    "lean-gaussian": (
        "Only the exact catalog-declared Gaussian form and canonical rational "
        "bounds/tolerance are admitted. Any other form, failed enclosure, checker "
        "rejection, or pin/identity mismatch refuses without downgrade."
    ),
    "lean-int-cert": (
        "Only the request-bound v1.7.2 composed-integral fragment and canonical "
        "bounds/tolerance are admitted. Request-unbound v1.7.0 evidence, unsupported "
        "syntax, failed subdivision, checker rejection, or identity mismatch refuses "
        "without using the weaker float lane."
    ),
    "lean-receipt-registry": (
        "Only closed-registry range/rational, Gaussian, and current request-bound "
        "int-cert receipts matching independent caller expectations are replayed. "
        "Unknown epochs/variants, copied rather than caller-pinned expectations, "
        "revoked int-cert evidence, or checker/pin mismatch refuses."
    ),
    "exact-cert-verifier": (
        "Only the catalog-declared exact fragment and budgets are admitted. Invalid "
        "grammar, side conditions, limits, certificate mismatch, or independent "
        "verifier rejection refuses; exact is not relabeled formal."
    ),
    "structural-checker": (
        "Only byte-exact source/citation structure described by the schema is "
        "accepted after independent file-byte recomputation. Path traversal, malformed "
        "symbols/hashes, missing text/declarations, or checker mismatch refuses; the "
        "result never asserts test execution or correctness."
    ),
    "decision-checker": (
        "Only 2..6 schema-valid options under a caller-declared admissible numeric "
        "criterion are ranked. Invalid shape/sense/unit, value-judgment criteria, "
        "zero top margin, or checker mismatch refuses; caller values are not treated "
        "as measurements or confidence intervals."
    ),
    "claim-router": (
        "Only jackal-claim-request-v1 and its closed step vocabulary are compiled. "
        "Policy, identity, schema, route, or assurance failures refuse; fallback is "
        "off by default and any caller-enabled fallback remains explicit in the route "
        "trace rather than silently changing assurance."
    ),
    "claim-verifier": (
        "Only canonical bundles matching separately caller-pinned epoch, policy, "
        "root proposition, time, and nonce are replayed. Semantic, graph, freshness, "
        "evidence, checker, or pin ambiguity returns refused or indeterminate exactly "
        "as declared; it is never converted to success."
    ),
    "program-verifier": (
        "Only caller-pinned Safe-source anubis.program-evidence.v3 under "
        "inventory-safe-v1 is admitted. Any source/compiler/artifact/policy mismatch, "
        "roster or proof-path discrepancy, replay failure, symlink/path violation, or "
        "unsupported profile refuses. Artifacts are never executed, and success does "
        "not establish construct totality, source-to-VC, SMT-to-CNF, source-native "
        "refinement, runtime behavior, or universal soundness."
    ),
    "runtime-only": (
        "Only the catalog-declared engine command, grammar, side conditions, and "
        "budgets are admitted. Parse/domain/validation/non-convergence failures and "
        "unsupported fragments return refused; no other lane is substituted and the "
        "returned status is not promoted."
    ),
}

CLAIM_MATHEMATICAL_ASSURANCE = [
    "estimated",
    "model-based",
    "checked",
    "bounded",
    "formal-bounded",
    "exact",
]

HEX64 = re.compile(r"[0-9a-f]{64}\Z")
TOOL_NAME = re.compile(r"jackal_[a-z0-9_]+\Z")
MAX_JSON_BYTES = 8 * 1024 * 1024


class InventoryError(RuntimeError):
    """Fail-closed inventory refusal with a stable reason name."""

    def __init__(self, reason: str, detail: str):
        self.reason = reason
        self.detail = detail
        super().__init__(f"reason={reason} detail={detail}")


def refuse(reason: str, detail: str) -> None:
    raise InventoryError(reason, detail)


def canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    if not path.is_file():
        refuse("missing-input", f"required regular file is absent: {path}")
    return _sha256_bytes(path.read_bytes())


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        refuse("missing-input", f"required JSON file is absent: {path}")
    raw = path.read_bytes()
    if len(raw) > MAX_JSON_BYTES:
        refuse("oversize-input", f"JSON input exceeds {MAX_JSON_BYTES} bytes: {path}")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        refuse("invalid-json", f"{path}: {error}")
    if not isinstance(value, dict):
        refuse("invalid-json", f"top level is not an object: {path}")
    return value


def _load_manifest(path: Path) -> dict[str, dict[str, str | None]]:
    if not path.is_file():
        refuse("missing-input", f"release manifest is absent: {path}")
    entries: dict[str, dict[str, str | None]] = {}
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        fields = line.split()
        if len(fields) not in {2, 3}:
            refuse("manifest-shape", f"{path}:{line_number}: expected 2 or 3 fields")
        label = fields[0]
        if label in entries:
            refuse("manifest-duplicate", f"duplicate label {label!r}")
        digest = fields[-1]
        if HEX64.fullmatch(digest) is None:
            refuse("manifest-digest", f"label {label!r} has invalid SHA-256")
        entries[label] = {
            "label": label,
            "locator": fields[1] if len(fields) == 3 else None,
            "sha256": digest,
        }
    return entries


def _verify_proof_identity_inputs(
    root: Path, manifest: dict[str, dict[str, str | None]]
) -> None:
    bindings = {
        "range-proof-identity": Path(
            "release/evidence/range_proof_identity_v172.json"
        ),
        "gaussian-proof-identity": Path(
            "release/evidence/gaussian_proof_identity.json"
        ),
        "int-cert-proof-identity": Path(
            "release/evidence/int_cert_proof_identity_v172.json"
        ),
    }
    for label, relative in bindings.items():
        entry = manifest.get(label)
        if entry is None:
            refuse("missing-checker-identity", f"manifest label {label!r} is absent")
        if entry["locator"] != relative.as_posix():
            refuse(
                "checker-identity-path",
                f"{label!r} points to {entry['locator']!r}, expected {relative.as_posix()!r}",
            )
        actual = _sha256_file(root / relative)
        if entry["sha256"] != actual:
            refuse(
                "checker-identity-digest",
                f"{label!r} manifest={entry['sha256']} actual={actual}",
            )
        _load_json(root / relative)


def _load_catalog(root: Path) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
    document = _load_json(root / CATALOG_PATH)
    if document.get("version") != EXPECTED_VERSION:
        refuse(
            "catalog-version",
            f"expected {EXPECTED_VERSION!r}, found {document.get('version')!r}",
        )
    tools = document.get("tools")
    if not isinstance(tools, list):
        refuse("catalog-shape", "tools is not an array")
    names: list[str] = []
    for index, row in enumerate(tools):
        if not isinstance(row, dict):
            refuse("catalog-shape", f"tools[{index}] is not an object")
        name = row.get("name")
        if not isinstance(name, str) or TOOL_NAME.fullmatch(name) is None:
            refuse("catalog-tool-name", f"tools[{index}] has invalid name {name!r}")
        names.append(name)
    duplicates = sorted({name for name in names if names.count(name) > 1})
    if duplicates:
        refuse("duplicate-tool", f"duplicate catalog names: {duplicates}")
    if len(names) != EXPECTED_TOOL_COUNT:
        refuse("tool-count", f"expected {EXPECTED_TOOL_COUNT}, found {len(names)}")
    return document, tools, names


def _load_profiles(root: Path, catalog_names: list[str]) -> dict[str, list[str]]:
    catalog_set = set(catalog_names)
    profiles: dict[str, list[str]] = {}
    for profile_id in PROFILE_IDS:
        path = root / PROFILE_DIR / f"{profile_id}.json"
        document = _load_json(path)
        if document.get("profile_id") != profile_id:
            refuse("profile-id", f"{path} does not declare {profile_id!r}")
        declared = document.get("tools")
        if not isinstance(declared, list) or not all(
            isinstance(name, str) for name in declared
        ):
            refuse("profile-shape", f"{profile_id}.tools is not a string array")
        if len(declared) != len(set(declared)):
            refuse("profile-duplicate", f"{profile_id} contains duplicate tools")
        unknown = sorted(set(declared) - catalog_set)
        if unknown:
            refuse("profile-unknown-tool", f"{profile_id} has unknown tools {unknown}")
        expected_order = [name for name in catalog_names if name in set(declared)]
        if declared != expected_order:
            refuse("profile-order", f"{profile_id} is not in catalog order")
        digest = document.get("profile_digest_sha256")
        payload = {
            key: value
            for key, value in document.items()
            if key != "profile_digest_sha256"
        }
        expected_digest = _sha256_bytes(canonical_bytes(payload))
        if digest != expected_digest:
            refuse(
                "profile-digest",
                f"{profile_id} digest={digest!r} expected={expected_digest}",
            )
        profiles[profile_id] = declared
    if not set(profiles["core"]) <= set(profiles["formal"]):
        refuse("profile-nesting", "core is not a subset of formal")
    if not set(profiles["formal"]) <= set(profiles["full"]):
        refuse("profile-nesting", "formal is not a subset of full")
    if profiles["full"] != catalog_names:
        refuse("full-profile-mismatch", "full profile is not the exact catalog roster")
    return profiles


def _dependency_family(name: str) -> str:
    matches = [family for family, members in DEPENDENCY_GROUPS.items() if name in members]
    if not matches:
        refuse("unmapped-tool", f"no capability facts are bound for {name!r}")
    if len(matches) != 1:
        refuse("dependency-family-conflict", f"{name!r} belongs to {matches}")
    return matches[0]


def _status_classes(row: dict[str, Any]) -> list[str]:
    name = row["name"]
    returns = row.get("returns")
    if not isinstance(returns, dict):
        refuse("catalog-shape", f"{name}.returns is not an object")
    declaration = returns.get("status")
    if not isinstance(declaration, str):
        refuse("catalog-shape", f"{name}.returns.status is not a string")
    statuses = declaration.split(" | ")
    if not statuses or " | ".join(statuses) != declaration or any(not item for item in statuses):
        refuse("status-shape", f"{name} status declaration is not exact ' | ' tokens")
    if len(statuses) != len(set(statuses)):
        refuse("status-shape", f"{name} repeats a status token")
    unknown = sorted(set(statuses) - ALLOWED_STATUSES)
    if unknown:
        refuse("status-vocabulary", f"{name} uses unknown statuses {unknown}")
    if "refused" not in statuses:
        refuse("status-refusal-missing", f"{name} does not declare refused")
    return statuses


def _assurance_classes(name: str, statuses: list[str]) -> list[str]:
    if name in {"jackal_claim", "jackal_verify_bundle"}:
        return list(CLAIM_MATHEMATICAL_ASSURANCE)
    if name == "jackal_verify_receipt":
        return ["formal-bounded"]
    values = [value for value in statuses if value not in {"refused", "indeterminate", "ok"}]
    if not values:
        refuse("assurance-mapping", f"{name} has no positive assurance class")
    return values


def _supported_fragment(row: dict[str, Any]) -> str:
    name = row["name"]
    description = row.get("description")
    arguments = row.get("arguments")
    if not isinstance(description, str) or not description.strip():
        refuse("catalog-shape", f"{name}.description is empty")
    if not isinstance(arguments, dict) or not arguments:
        refuse("catalog-shape", f"{name}.arguments is not a non-empty object")
    clauses: list[str] = []
    for argument, definition in arguments.items():
        if not isinstance(argument, str) or not isinstance(definition, dict):
            refuse("catalog-shape", f"{name}.arguments has an invalid entry")
        help_text = definition.get("help")
        if not isinstance(help_text, str) or not help_text.strip():
            refuse("catalog-shape", f"{name}.{argument}.help is empty")
        clauses.append(f"{argument}: {help_text.strip()}")
    return f"{description.strip()} Inputs: {'; '.join(clauses)}"


def _dependency_record(
    family: str, manifest: dict[str, dict[str, str | None]]
) -> dict[str, Any]:
    labels = DEPENDENCY_LABELS[family]
    missing = [label for label in labels if label not in manifest]
    if missing:
        refuse(
            "missing-checker-identity",
            f"dependency family {family!r} lacks manifest labels {missing}",
        )
    return {
        "family": family,
        "identities": [dict(manifest[label]) for label in labels],
    }


def build_inventory(root: Path | str) -> dict[str, Any]:
    root_path = Path(root).resolve()
    _catalog, tools, catalog_names = _load_catalog(root_path)
    profiles = _load_profiles(root_path, catalog_names)
    manifest = _load_manifest(root_path / MANIFEST_PATH)
    _verify_proof_identity_inputs(root_path, manifest)

    required_labels = {
        label for labels in DEPENDENCY_LABELS.values() for label in labels
    }
    missing_labels = sorted(required_labels - set(manifest))
    if missing_labels:
        refuse(
            "missing-checker-identity",
            f"required release-manifest labels are absent: {missing_labels}",
        )

    input_digests = []
    for relative in INPUT_PATHS:
        input_digests.append(
            {"path": relative.as_posix(), "sha256": _sha256_file(root_path / relative)}
        )

    records: list[dict[str, Any]] = []
    for row in tools:
        name = row["name"]
        family = _dependency_family(name)
        statuses = _status_classes(row)
        returns = row["returns"]
        records.append(
            {
                "name": name,
                "schema_sha256": _sha256_bytes(canonical_bytes(row)),
                "exposure": {"kernel": True, "hermes": True, "codex": True},
                "status_classes": statuses,
                "assurance_classes": _assurance_classes(name, statuses),
                "consequence_ceiling": returns.get("consequence_ceiling"),
                "dependency": _dependency_record(family, manifest),
                "supported_fragment": _supported_fragment(row),
                "refusal_boundary": REFUSAL_BOUNDARIES[family],
                "profiles": [
                    profile_id
                    for profile_id in PROFILE_IDS
                    if name in profiles[profile_id]
                ],
                "release_state": RELEASE_STATE,
                "containing_ref": dict(CONTAINING_REF),
            }
        )

    unique = len({row["name"] for row in records})
    if len(records) != EXPECTED_TOOL_COUNT or unique != EXPECTED_TOOL_COUNT:
        refuse(
            "tool-count",
            f"expected tools={EXPECTED_TOOL_COUNT} unique={EXPECTED_TOOL_COUNT}, "
            f"found tools={len(records)} unique={unique}",
        )
    return {
        "schema": "jackal-capability-inventory-v1",
        "catalog": {
            "path": CATALOG_PATH.as_posix(),
            "version": EXPECTED_VERSION,
            "sha256": _sha256_file(root_path / CATALOG_PATH),
        },
        "release": {
            "state": RELEASE_STATE,
            "version": EXPECTED_VERSION,
            "containing_ref": dict(CONTAINING_REF),
            "statement": (
                "Candidate identity only; this document does not assert that an "
                "annotated v1.7.3 tag or public release exists."
            ),
        },
        "tool_count": len(records),
        "unique_tool_count": unique,
        "status_vocabulary": sorted(ALLOWED_STATUSES),
        "inputs": input_digests,
        "tools": records,
    }


def render_inventory(root: Path | str) -> bytes:
    return canonical_bytes(build_inventory(root)) + b"\n"


def check_committed(root: Path | str) -> None:
    root_path = Path(root).resolve()
    path = root_path / ARTIFACT_PATH
    if not path.is_file():
        refuse("artifact-missing", f"committed inventory is absent: {path}")
    expected = render_inventory(root_path)
    actual = path.read_bytes()
    if actual != expected:
        refuse(
            "artifact-drift",
            f"{ARTIFACT_PATH} actual={_sha256_bytes(actual)} "
            f"generated={_sha256_bytes(expected)}",
        )


def _write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o644)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--write", action="store_true", help="write generated bytes")
    action.add_argument("--check", action="store_true", help="verify committed bytes")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args(argv)
    try:
        if args.write:
            _write_atomic(args.root.resolve() / ARTIFACT_PATH, render_inventory(args.root))
        else:
            check_committed(args.root)
        document = build_inventory(args.root)
    except InventoryError as error:
        print(
            f"CAPABILITY_INVENTORY_REFUSED reason={error.reason} detail={error.detail}",
            file=sys.stderr,
        )
        return 1
    print(
        "CAPABILITY_INVENTORY_PASS "
        f"tools={document['tool_count']} unique={document['unique_tool_count']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
