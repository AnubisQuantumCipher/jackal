#!/usr/bin/env python3
"""Derive the additive JACKAL v1.7.3 release-manifest plan from live bytes.

The default and ``--plan`` modes print the complete proposed manifest without
mutating ``release/MANIFEST.sha256``.  ``--check`` compares the proposal with
that file.  ``--write`` atomically replaces the manifest only when an operator
explicitly selects that mode.
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "release/MANIFEST.sha256"
COMPILER_PATH_ENV = "JACKAL_ANUBIS_COMPILER_PATH"
_CONFIGURED_COMPILER_PATH = os.environ.get(COMPILER_PATH_ENV)
COMPILER_PATH = (
    Path(_CONFIGURED_COMPILER_PATH) if _CONFIGURED_COMPILER_PATH else None
)
COMPILER_SHA256 = (
    "a733565f237df171e7cf93b9b37700a42d8713576818fd92f8cd23a8ad7a69e2"
)
V170_ARCHIVE_SHA256 = (
    "21c7ede586f30a58772f321f7dbb36ab66213e199785489f99133710ac56096e"
)
V170_RANGE_CHECKER_SHA256 = (
    "05c3518b836f239712f897c483a2ddadad9f544e0887b1b7bb1424a27289de8a"
)
V170_COVERAGE_INVENTORY_SHA256 = (
    "18ff7b1d428dbc6f807fd4de27751ba415b33ef0b356088d7fa316ed74bb0ba6"
)
V170_INT_CHECKER_SHA256 = (
    "c858e3bfc0ff2809a808170caabbf090077cb54996e76f065dbcd26ffb067d49"
)
V170_PLUGIN_HERMES_SHA256 = (
    "d141c909e8f5f03e268a2112f291e6bd79fafff906522eb7ca9accc247a3274b"
)
MAX_IDENTITY_BYTES = 512 * 1024 * 1024

HEADER = (
    "# JACKAL v1.7.3 pinned release identities (v1.7.2 proof/claim/domain lanes + "
    "inventory-safe Anubis program evidence)"
)

FILE_ROWS = [
    ("evaluator", "jackal-native"),
    ("checker", "proofs/lean/.lake/build/bin/jackal_cert_check"),
    ("gaussian-producer", "tools/gaussian_certificate.py"),
    ("gaussian-checker", "proofs/lean/.lake/build/bin/jackal_gaussian_check"),
    ("range-proof-identity", "release/evidence/range_proof_identity_v172.json"),
    ("archival-range-proof-identity", "release/evidence/range_proof_identity.json"),
    ("gaussian-proof-identity", "release/evidence/gaussian_proof_identity.json"),
    (
        "lean-admission-audit",
        "release/evidence/lean_admission_audit_v173.json",
    ),
    ("int-cert-producer", "tools/int_cert_producer.py"),
    ("int-cert-checker", "proofs/lean/.lake/build/bin/jackal_int_cert_check"),
    (
        "int-cert-proof-identity",
        "release/evidence/int_cert_proof_identity_v172.json",
    ),
    (
        "revoked-int-cert-proof-identity-reference",
        "release/evidence/int_cert_proof_identity.json",
    ),
    ("compatibility-floor", "release/compat/v172_floor.json"),
    ("program-compatibility-floor", "release/compat/v173_floor.json"),
    ("range-ordering-aba", "release/evidence/range_ordering_aba_v172.json"),
    (
        "int-cert-premise-aba",
        "release/evidence/int_cert_premise_aba_v172.json",
    ),
    ("coverage-inventory", "release/coverage/formal_coverage_inventory.json"),
    ("build-environment", "release/evidence/build_environment_v170.json"),
    ("source", "jackal_calc.anb"),
    ("sqrt_rat_producer", "tools/sqrt_rat_producer.py"),
    ("exp_rat_producer", "tools/exp_rat_producer.py"),
    ("ln_rat_producer", "tools/ln_rat_producer.py"),
    ("sin_rat_producer", "tools/sin_rat_producer.py"),
    ("atan_rat_producer", "tools/atan_rat_producer.py"),
    ("tanh_rat_producer", "tools/tanh_rat_producer.py"),
    ("exact_verifier", "tools/exact_verify.py"),
    ("claim_kernel", "tools/claim_kernel.py"),
    ("claim_router", "tools/claim_router.py"),
    ("claim_verifier", "tools/claim_bundle_verify.py"),
    ("domain_pack_registry", "domain_packs/registry_v1.json"),
    ("domain_pack_verifier", "tools/domain_pack_verify.py"),
    ("domain_pack_test_exists_checker", "tools/test_exists_verify.py"),
    ("domain_pack_decision_checker", "tools/decision_verify.py"),
    ("anubis_program_verifier", "tools/anubis_program_verify.py"),
    ("anubis_program_policy", "release/program/inventory_safe_v1.json"),
    ("claim_inference_registry", "release/claim/inference_registry_v1.json"),
    ("claim_unit_registry", "release/claim/unit_registry_v1.json"),
]

DISPLAY = {
    "checker": "jackal_cert_check",
    "gaussian-checker": "jackal_gaussian_check",
    "int-cert-checker": "jackal_int_cert_check",
}

ORDER = [
    "#",
    "evaluator",
    "checker",
    "archival-v170-archive-source",
    "archival-range-checker",
    "archival-range-coverage-inventory",
    "archival-plugin-hermes",
    "gaussian-producer",
    "gaussian-checker",
    "range-proof-identity",
    "range-proof-digest",
    "archival-range-proof-identity",
    "archival-range-proof-digest",
    "gaussian-proof-identity",
    "gaussian-proof-digest",
    "lean-admission-audit",
    "lean-admission-audit-digest",
    "int-cert-producer",
    "int-cert-checker",
    "int-cert-proof-identity",
    "int-cert-proof-digest",
    "revoked-int-cert-proof-identity-reference",
    "compatibility-floor",
    "program-compatibility-floor",
    "range-ordering-aba",
    "int-cert-premise-aba",
    "coverage-inventory",
    "build-environment",
    "source",
    "compiler_pin",
    "plugin_hermes",
    "sqrt_rat_producer",
    "exp_rat_producer",
    "ln_rat_producer",
    "sin_rat_producer",
    "atan_rat_producer",
    "tanh_rat_producer",
    "exact_verifier",
    "claim_kernel",
    "claim_router",
    "claim_verifier",
    "domain_pack_registry",
    "domain_pack_verifier",
    "domain_pack_test_exists_checker",
    "domain_pack_decision_checker",
    "anubis_program_verifier",
    "anubis_program_policy",
    "claim_inference_registry",
    "claim_unit_registry",
]


class PlanRefusal(RuntimeError):
    """Fail-closed manifest-plan refusal."""


def read_regular(path: Path, maximum: int = MAX_IDENTITY_BYTES) -> bytes:
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or before.st_size > maximum:
        raise PlanRefusal(f"not a bounded regular file: {path}")
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        opened = os.fstat(descriptor)
        if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
            raise PlanRefusal(f"path identity changed before read: {path}")
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(descriptor, min(1024 * 1024, maximum + 1 - total))
            if not chunk:
                break
            total += len(chunk)
            if total > maximum:
                raise PlanRefusal(f"file exceeds byte bound: {path}")
            chunks.append(chunk)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    current = path.lstat()
    identity = lambda value: (  # noqa: E731
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )
    if identity(opened) != identity(after) or identity(after) != identity(current):
        raise PlanRefusal(f"file changed while reading: {path}")
    return b"".join(chunks)


def sha256(path: Path) -> str:
    return hashlib.sha256(read_regular(path)).hexdigest()


def identity_digest(path: Path, raw: bytes) -> str:
    value = decode_json(path, raw)
    digest = value.get("identity_digest_sha256")
    if not isinstance(digest, str) or len(digest) != 64:
        raise PlanRefusal(f"identity digest missing or malformed: {path}")
    return digest


def audit_digest(path: Path, raw: bytes) -> str:
    value = decode_json(path, raw)
    digest = value.get("audit_digest_sha256")
    if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
        raise PlanRefusal(f"audit digest missing or malformed: {path}")
    body = {key: item for key, item in value.items() if key != "audit_digest_sha256"}
    computed = hashlib.sha256(
        json.dumps(
            body, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
    ).hexdigest()
    require_equal(digest, computed, "Lean admission audit self-digest")
    return digest


def decode_json(path: Path, raw: bytes) -> dict[str, object]:
    value = json.loads(raw.decode("utf-8"))
    if not isinstance(value, dict):
        raise PlanRefusal(f"JSON record is not an object: {path}")
    return value


def read_json(path: Path) -> dict[str, object]:
    return decode_json(path, read_regular(path))


def nested(value: dict[str, object], *keys: str) -> object:
    current: object = value
    for key in keys:
        if not isinstance(current, dict) or key not in current:
            raise PlanRefusal(f"missing JSON binding: {'.'.join(keys)}")
        current = current[key]
    return current


def require_equal(observed: object, expected: object, label: str) -> None:
    if observed != expected:
        raise PlanRefusal(
            f"binding mismatch {label}: observed={observed!r} "
            f"expected={expected!r}"
        )


def validate_v172_contract() -> dict[str, str]:
    range_checker = ROOT / "proofs/lean/.lake/build/bin/jackal_cert_check"
    int_checker = ROOT / "proofs/lean/.lake/build/bin/jackal_int_cert_check"
    range_identity_path = ROOT / "release/evidence/range_proof_identity_v172.json"
    int_identity_path = ROOT / "release/evidence/int_cert_proof_identity_v172.json"
    archival_range_identity_path = ROOT / "release/evidence/range_proof_identity.json"
    archival_int_identity_path = ROOT / "release/evidence/int_cert_proof_identity.json"
    compatibility_path = ROOT / "release/compat/v172_floor.json"
    range_aba_path = ROOT / "release/evidence/range_ordering_aba_v172.json"
    int_aba_path = ROOT / "release/evidence/int_cert_premise_aba_v172.json"

    range_checker_digest = sha256(range_checker)
    int_checker_digest = sha256(int_checker)
    range_identity_digest = sha256(range_identity_path)
    int_identity_digest = sha256(int_identity_path)
    range_identity = read_json(range_identity_path)
    int_identity = read_json(int_identity_path)
    archival_range_identity = read_json(archival_range_identity_path)
    archival_int_identity = read_json(archival_int_identity_path)
    compatibility = read_json(compatibility_path)
    range_aba = read_json(range_aba_path)
    int_aba = read_json(int_aba_path)

    require_equal(
        range_identity.get("schema"),
        "jackal-range-proof-identity-v2",
        "range identity schema",
    )
    require_equal(
        int_identity.get("schema"),
        "jackal-int-cert-proof-identity-v2",
        "int-cert identity schema",
    )
    require_equal(
        nested(range_identity, "checker", "sha256"),
        range_checker_digest,
        "range identity checker",
    )
    require_equal(
        nested(range_identity, "build_attestation", "checker", "sha256"),
        range_checker_digest,
        "range build attestation checker",
    )
    require_equal(
        nested(int_identity, "checker", "sha256"),
        int_checker_digest,
        "int-cert identity checker",
    )
    require_equal(
        nested(int_identity, "build_attestation", "checker", "sha256"),
        int_checker_digest,
        "int-cert build attestation checker",
    )
    require_equal(
        nested(archival_range_identity, "checker", "sha256"),
        V170_RANGE_CHECKER_SHA256,
        "archival range checker",
    )
    require_equal(
        nested(archival_int_identity, "checker", "sha256"),
        V170_INT_CHECKER_SHA256,
        "archival int-cert checker",
    )
    require_equal(
        nested(range_identity, "fragment", "premises_not_discharged_by_checker"),
        [],
        "range closed premises",
    )
    require_equal(
        nested(int_identity, "fragment", "premises_not_discharged_by_checker"),
        [],
        "int-cert closed premises",
    )

    require_equal(
        compatibility.get("current_release_epoch"),
        "v1.7.2",
        "compatibility epoch",
    )
    require_equal(
        compatibility.get("reversed_interval_policy"),
        "revoked-refuse",
        "reversed interval policy",
    )
    require_equal(
        compatibility.get("unsupported_policy"),
        "refuse",
        "unsupported policy",
    )
    for lane, expected_path, expected_schema, expected_file_digest in (
        (
            "range",
            "release/evidence/range_proof_identity_v172.json",
            "jackal-range-proof-identity-v2",
            range_identity_digest,
        ),
        (
            "int_cert",
            "release/evidence/int_cert_proof_identity_v172.json",
            "jackal-int-cert-proof-identity-v2",
            int_identity_digest,
        ),
    ):
        require_equal(
            nested(compatibility, "lanes", lane, "current", "identity_file"),
            expected_path,
            f"{lane} compatibility identity path",
        )
        require_equal(
            nested(
                compatibility,
                "lanes",
                lane,
                "current",
                "identity_file_sha256",
            ),
            expected_file_digest,
            f"{lane} compatibility identity bytes",
        )
        require_equal(
            nested(compatibility, "lanes", lane, "current", "schema"),
            expected_schema,
            f"{lane} compatibility schema",
        )
        require_equal(
            nested(
                compatibility,
                "lanes",
                lane,
                "current",
                "allowed_release_epochs",
            ),
            ["v1.7.2"],
            f"{lane} compatibility epochs",
        )

    for lane, epoch, checker_file, checker_digest in (
        (
            "range",
            "v1.5.0",
            "jackal_cert_check_v170",
            V170_RANGE_CHECKER_SHA256,
        ),
        (
            "rational_variants",
            "v1.5.0",
            "jackal_cert_check_v170",
            V170_RANGE_CHECKER_SHA256,
        ),
    ):
        require_equal(
            nested(
                compatibility,
                "lanes",
                lane,
                "archival_v1",
                "allowed_release_epochs",
            ),
            [epoch],
            f"{lane} archival epoch",
        )
        require_equal(
            nested(compatibility, "lanes", lane, "archival_v1", "checker_file"),
            checker_file,
            f"{lane} archival checker path",
        )
        require_equal(
            nested(compatibility, "lanes", lane, "archival_v1", "checker_sha256"),
            checker_digest,
            f"{lane} archival checker bytes",
        )

    revoked_int = nested(compatibility, "lanes", "int_cert", "archival_v1")
    require_equal(revoked_int.get("allowed_release_epochs"), [],
                  "int-cert archival epochs revoked")
    require_equal(revoked_int.get("mode"), "revoked-refuse",
                  "int-cert archival mode")
    if "does not bind the raw request" not in str(revoked_int.get("reason", "")):
        raise PlanRefusal("int-cert archival revocation reason missing")
    require_equal(revoked_int.get("checker_sha256"),
                  V170_INT_CHECKER_SHA256,
                  "int-cert historical checker bytes")

    require_equal(range_aba.get("status"), "passed", "range ABA status")
    require_equal(int_aba.get("status"), "passed", "int-cert ABA status")
    for phase in ("canonical_pre_sha256", "canonical_post_sha256"):
        require_equal(
            nested(range_aba, phase, "jackal_cert_check"),
            range_checker_digest,
            f"range ABA {phase}",
        )
        require_equal(
            nested(int_aba, phase, "jackal_int_cert_check"),
            int_checker_digest,
            f"int-cert ABA {phase}",
        )

    return {
        "release_epoch": "v1.7.2",
        "range_checker_sha256": range_checker_digest,
        "int_cert_checker_sha256": int_checker_digest,
        "range_identity_file_sha256": range_identity_digest,
        "int_cert_identity_file_sha256": int_identity_digest,
        "range_aba_status": str(range_aba["status"]),
        "int_cert_aba_status": str(int_aba["status"]),
    }


def validate_compiler(compiler_path: Path | None = COMPILER_PATH) -> str:
    if compiler_path is None:
        raise PlanRefusal(
            f"compiler-path-unset: set {COMPILER_PATH_ENV} or pass --compiler-path"
        )
    if compiler_path.is_symlink():
        raise PlanRefusal(f"compiler authority must not be a symlink: {compiler_path}")
    observed = sha256(compiler_path)
    if observed != COMPILER_SHA256:
        raise PlanRefusal(
            f"compiler authority drift: path={compiler_path} observed={observed} "
            f"expected={COMPILER_SHA256}"
        )
    return observed


def validate_unified_contract() -> None:
    catalog = read_json(ROOT / "plugin/hermes/tools.json")
    names = [
        row.get("name")
        for row in catalog.get("tools", [])
        if isinstance(row, dict)
    ]
    require_equal(catalog.get("version"), "v1.7.3", "plugin release epoch")
    require_equal(len(names), 41, "plugin tool count")
    require_equal(len(set(names)), 41, "plugin tool uniqueness")
    full = read_json(ROOT / "plugin/hermes/profiles/full.json")
    require_equal(full.get("tools"), names, "full profile catalog parity")

    compatibility = read_json(ROOT / "release/compat/v173_floor.json")
    require_equal(compatibility.get("release_epoch"), "v1.7.3", "compat epoch")
    require_equal(compatibility.get("tool_count"), 41, "compat tool count")
    require_equal(
        compatibility.get("program_profile"),
        "inventory-safe-v1",
        "compat program profile",
    )
    require_equal(
        compatibility.get("independent_policy_construct_totality"),
        False,
        "compat construct-totality boundary",
    )

    policy = read_json(ROOT / "release/program/inventory_safe_v1.json")
    policy_digest = policy.get("policy_digest_sha256")
    policy_body = {
        key: value
        for key, value in policy.items()
        if key != "policy_digest_sha256"
    }
    computed_policy_digest = hashlib.sha256(
        json.dumps(
            policy_body,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()
    require_equal(policy_digest, computed_policy_digest, "program policy digest")
    require_equal(
        compatibility.get("program_policy_sha256"),
        policy_digest,
        "compat program policy",
    )

    profile_check = subprocess.run(
        [sys.executable, "-I", "-S", "-B", "tools/profile_verify.py"],
        cwd=ROOT,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=30,
        check=False,
    )
    if profile_check.returncode != 0:
        raise PlanRefusal(
            f"profile verification refused: "
            f"{(profile_check.stderr or profile_check.stdout)[:512]}"
        )

    pack_check = subprocess.run(
        [
            sys.executable,
            "-I",
            "-S",
            "-B",
            "tools/domain_pack_verify.py",
            "--root",
            str(ROOT),
        ],
        cwd=ROOT,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=120,
        check=False,
    )
    if pack_check.returncode != 0:
        raise PlanRefusal(
            f"domain-pack verification refused: "
            f"{(pack_check.stderr or pack_check.stdout)[:512]}"
        )
    try:
        pack_report = json.loads(pack_check.stdout)
    except json.JSONDecodeError as error:
        raise PlanRefusal(f"domain-pack verifier output malformed: {error}") from None
    require_equal(pack_report.get("status"), "accepted", "domain-pack status")

    lean_audit_check = subprocess.run(
        [
            sys.executable,
            "-I",
            "-S",
            "-B",
            "tools/lean_admission_audit.py",
            "--check",
            "--root",
            str(ROOT),
        ],
        cwd=ROOT,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=180,
        check=False,
    )
    if lean_audit_check.returncode != 0:
        raise PlanRefusal(
            "Lean admission audit refused: "
            f"{(lean_audit_check.stderr or lean_audit_check.stdout)[:512]}"
        )


def plugin_bundle_digest() -> str:
    completed = subprocess.run(
        [
            sys.executable,
            "-I",
            "-S",
            "-B",
            "plugin/hermes/bundle_hash.py",
            "print",
        ],
        cwd=ROOT,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=30,
        check=False,
    )
    if completed.returncode != 0:
        raise PlanRefusal(f"plugin bundle hash refused: {completed.stderr[:512]}")
    digest = completed.stdout.strip()
    if len(digest) != 64:
        raise PlanRefusal("plugin bundle hash is malformed")
    return digest


def build_rows(compiler_path: Path | None = COMPILER_PATH) -> list[str]:
    validate_compiler(compiler_path)
    validate_unified_contract()
    contract = validate_v172_contract()
    rows = [HEADER]
    for label, relative in FILE_ROWS:
        path = ROOT / relative
        raw = read_regular(path)
        observed = hashlib.sha256(raw).hexdigest()
        if label == "checker":
            require_equal(
                observed, contract["range_checker_sha256"], "range checker TOCTOU"
            )
        elif label == "int-cert-checker":
            require_equal(
                observed,
                contract["int_cert_checker_sha256"],
                "int-cert checker TOCTOU",
            )
        elif label == "range-proof-identity":
            require_equal(
                observed,
                contract["range_identity_file_sha256"],
                "range identity TOCTOU",
            )
        elif label == "int-cert-proof-identity":
            require_equal(
                observed,
                contract["int_cert_identity_file_sha256"],
                "int-cert identity TOCTOU",
            )
        rows.append(f"{label} {DISPLAY.get(label, relative)} {observed}")
        if label in {
            "range-proof-identity",
            "archival-range-proof-identity",
            "gaussian-proof-identity",
            "int-cert-proof-identity",
        }:
            rows.append(
                f"{label.rsplit('-', 1)[0]}-digest {identity_digest(path, raw)}"
            )
        elif label == "lean-admission-audit":
            rows.append(
                f"lean-admission-audit-digest {audit_digest(path, raw)}"
            )
    rows.extend(
        [
            f"archival-v170-archive-source github-release-v1.7.0 {V170_ARCHIVE_SHA256}",
            f"archival-range-checker jackal_cert_check_v170 {V170_RANGE_CHECKER_SHA256}",
            "archival-range-coverage-inventory "
            f"formal_coverage_inventory_v170.json {V170_COVERAGE_INVENTORY_SHA256}",
            f"archival-plugin-hermes v1.7.0-plugin {V170_PLUGIN_HERMES_SHA256}",
        ]
    )
    rows.append(f"compiler_pin anubis-a733565f237d {COMPILER_SHA256}")
    rows.append(f"plugin_hermes {plugin_bundle_digest()}")
    keyed = {
        row.split()[0] if not row.startswith("#") else "#": row for row in rows
    }
    missing = [label for label in ORDER if label not in keyed]
    extras = sorted(set(keyed) - set(ORDER))
    if missing or extras:
        raise PlanRefusal(f"manifest row mismatch missing={missing} extras={extras}")
    return [keyed[label] for label in ORDER]


def manifest_text(compiler_path: Path | None = COMPILER_PATH) -> str:
    return "\n".join(build_rows(compiler_path)) + "\n"


def write_atomic(path: Path, data: str) -> None:
    destination_mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o644
    descriptor, temporary = tempfile.mkstemp(prefix=".MANIFEST.v173.", dir=path.parent)
    try:
        os.fchmod(descriptor, destination_mode)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--plan", action="store_true", help="print without writing")
    modes.add_argument("--check", action="store_true", help="compare with manifest")
    modes.add_argument("--write", action="store_true", help="explicitly replace manifest")
    parser.add_argument(
        "--compiler-path",
        default=_CONFIGURED_COMPILER_PATH,
        required=_CONFIGURED_COMPILER_PATH is None,
        help=(
            "path to the exact compiler authority; may also be set with "
            f"{COMPILER_PATH_ENV}"
        ),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    proposed = manifest_text(Path(args.compiler_path))
    if args.check:
        current = MANIFEST.read_text(encoding="utf-8")
        if current != proposed:
            sys.stdout.writelines(
                difflib.unified_diff(
                    current.splitlines(keepends=True),
                    proposed.splitlines(keepends=True),
                    fromfile="release/MANIFEST.sha256",
                    tofile="v1.7.3-plan",
                )
            )
            print("REPIN_V173_CHECK_FAIL")
            return 1
        print(f"REPIN_V173_CHECK_PASS rows={len(proposed.splitlines())}")
        return 0
    if args.write:
        write_atomic(MANIFEST, proposed)
        print(f"REPIN_V173_WRITTEN rows={len(proposed.splitlines())} manifest={MANIFEST}")
        return 0
    sys.stdout.write(proposed)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, PlanRefusal, ValueError, subprocess.SubprocessError) as error:
        print(f"REPIN_V173_REFUSED detail={str(error)[:512]}", file=sys.stderr)
        raise SystemExit(1) from None
