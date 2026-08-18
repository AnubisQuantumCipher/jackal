#!/usr/bin/env python3
"""Fail-closed JACKAL v1.7.2 aggregate gate driver for Apple Silicon macOS.

This is a current-release runner, not a textual extension of an older runner.
The v1.7.2 proof closure and checker bytes are exercised as the live authority.
The historical range checker is used only by the separately labelled v1.5
receipt-replay gate. The v1.7.0 int checker is never replay authority: its
exact digest is retained solely as a negative fixture proving current policy
refuses that request-unbound receipt class.

Every normal run starts with dependency/toolchain and manifest-identity
preflights. A zero-exit child that reports a skip, an unexecuted row, or a
manifest-pending result is red. The complete run ends by checking the manifest
again so a gate cannot leave the seal inconsistent.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
from pathlib import Path, PurePosixPath
from typing import NoReturn


ROOT = Path(__file__).resolve().parents[2]
DRIVER = Path(__file__).resolve()
PACKAGE_NAME = "jackal-v1.7.2-macos-arm64"
PACKAGE_DIR = ROOT / "release/dist" / PACKAGE_NAME
PACKAGE_TARBALL = ROOT / "release/dist" / f"{PACKAGE_NAME}.tar.gz"
COMPILER = Path("/Users/sicarii/anubis-lang/vm/pins/anubis-a733565f237d")
COMPILER_SHA256 = (
    "a733565f237df171e7cf93b9b37700a42d8713576818fd92f8cd23a8ad7a69e2"
)
V170_RANGE_CHECKER_SHA256 = (
    "05c3518b836f239712f897c483a2ddadad9f544e0887b1b7bb1424a27289de8a"
)
V170_COVERAGE_INVENTORY_SHA256 = (
    "18ff7b1d428dbc6f807fd4de27751ba415b33ef0b356088d7fa316ed74bb0ba6"
)
REVOKED_V170_INT_CHECKER_SHA256 = (
    "c858e3bfc0ff2809a808170caabbf090077cb54996e76f065dbcd26ffb067d49"
)


class GateRefusal(RuntimeError):
    """A stable fail-closed internal-gate refusal."""


def py(
    test: str, timeout: int, *, optimized: bool = False
) -> tuple[list[str], int]:
    command = [sys.executable]
    if optimized:
        command.append("-O")
    command.append(test)
    return command, timeout


PREFLIGHT_GATES: list[tuple[str, list[str], int]] = [
    (
        "dependency-toolchain-preflight",
        [sys.executable, os.fspath(DRIVER), "--internal-preflight"],
        60,
    ),
    (
        "manifest-v172-preflight",
        [sys.executable, "release/tools/repin_v172.py", "--check"],
        120,
    ),
    (
        "lake-build-current",
        [
            "lake",
            "build",
            "JackalIv",
            "jackal_cert_check",
            "jackal_gaussian_check",
            "jackal_int_cert_check",
            "jackal_parse_dump",
            "JackalIv.CertRequestOrderingContract",
            "JackalIv.IntCertPremiseContract",
        ],
        3600,
    ),
    (
        "proof-identity-v2-range",
        [sys.executable, "release/tools/range_proof_identity.py", "check", "--lane", "range"],
        1800,
    ),
    (
        "proof-identity-v2-int-cert",
        [sys.executable, "release/tools/range_proof_identity.py", "check", "--lane", "int-cert"],
        1800,
    ),
    (
        "proof-identity-gaussian-preserved",
        [sys.executable, "release/tools/gaussian_proof_identity.py", "check", "--lane", "gaussian"],
        600,
    ),
]


CURRENT_GATES: list[tuple[str, list[str], int]] = [
    ("range-ordering-contract", *py("tests/range_ordering_contract_test.py", 300)),
    (
        "range-ordering-contract-optimized",
        *py("tests/range_ordering_contract_test.py", 300, optimized=True),
    ),
    ("range-ordering-aba", *py("tests/range_ordering_aba_test.py", 3600)),
    (
        "range-ordering-aba-optimized",
        *py("tests/range_ordering_aba_test.py", 3600, optimized=True),
    ),
    (
        "int-premise-contract",
        ["lake", "env", "lean", "JackalIv/IntCertPremiseContract.lean"],
        1800,
    ),
    ("int-premise-aba", *py("tests/int_cert_premise_aba_v172_test.py", 3600)),
    (
        "int-premise-aba-optimized",
        *py("tests/int_cert_premise_aba_v172_test.py", 3600, optimized=True),
    ),
    (
        "int-request-binding-v172",
        *py("tests/int_cert_request_binding_v172_test.py", 600),
    ),
    (
        "int-request-binding-v172-optimized",
        *py("tests/int_cert_request_binding_v172_test.py", 600, optimized=True),
    ),
    (
        "proof-identity-v172-contract",
        *py("tests/proof_identity_v172_contract_test.py", 1800),
    ),
    (
        "proof-identity-v172-contract-optimized",
        *py("tests/proof_identity_v172_contract_test.py", 1800, optimized=True),
    ),
    ("proof-compat-v172", *py("tests/proof_compatibility_v172_test.py", 300)),
    (
        "proof-compat-v172-optimized",
        *py("tests/proof_compatibility_v172_test.py", 300, optimized=True),
    ),
    ("gate-driver-v172-contract", *py("tests/gate_driver_v172_contract_test.py", 300)),
    (
        "gate-driver-v172-contract-optimized",
        *py("tests/gate_driver_v172_contract_test.py", 300, optimized=True),
    ),
    (
        "release-wiring-v172-contract",
        *py("tests/release_wiring_v172_contract_test.py", 300),
    ),
    (
        "release-wiring-v172-contract-optimized",
        *py("tests/release_wiring_v172_contract_test.py", 300, optimized=True),
    ),
    # Current computation and range-certificate regressions retained from the
    # earlier suite only where their runtime contracts are valid at v1.7.2.
    ("engine-self-test", ["./jackal", "self-test"], 600),
    ("positive-corpus", *py("tests/cert_positive_corpus.py", 1800)),
    ("negative-controls", *py("tests/cert_controls.py", 1800)),
    ("aba-mutations", *py("tests/cert_aba_mutations.py", 1800)),
    ("mutations-11", *py("tests/cert_mutations_11.py", 3600)),
    ("formal-status-gate", *py("tests/formal_status_gate_test.py", 600)),
    ("sqrt-rat-release", *py("tests/formal_sqrt_rat_release_test.py", 900)),
    ("exp-rat-release", *py("tests/formal_exp_rat_release_test.py", 900)),
    ("ln-rat-release", *py("tests/formal_ln_rat_release_test.py", 900)),
    ("sin-rat-release", *py("tests/formal_sin_rat_release_test.py", 900)),
    ("cos-rat-release", *py("tests/formal_cos_rat_release_test.py", 900)),
    ("atan-rat-release", *py("tests/formal_atan_rat_release_test.py", 900)),
    ("tanh-rat-release", *py("tests/formal_tanh_rat_release_test.py", 900)),
    (
        "rational-receipt-output-v172",
        *py("tests/rational_receipt_output_v172_test.py", 3600),
    ),
    (
        "rational-receipt-output-v172-optimized",
        *py("tests/rational_receipt_output_v172_test.py", 3600, optimized=True),
    ),
    ("gaussian-emitter", *py("tests/formal_gaussian_emitter_test.py", 900)),
    ("gaussian-checker", *py("tests/formal_gaussian_checker_test.py", 900)),
    ("gaussian-mutations", *py("tests/formal_gaussian_mutations.py", 1800)),
    ("gaussian-receipt", *py("tests/formal_gaussian_receipt_test.py", 1800)),
    ("receipt-semantic-mutations", *py("tests/receipt_semantic_mutations.py", 3600)),
    ("plugin-smoke", *py("tests/plugin_smoke.py", 3600)),
    ("output-path-safety", *py("tests/output_path_safety_test.py", 600)),
    # These gates are deliberately named here as current migrations. If any
    # still emits an old-epoch skip or manifest-pending result, the driver is
    # red rather than silently treating that row as coverage.
    ("fail-closed-sweep", *py("tests/fail_closed_sweep.py", 3600)),
    ("seal-audit", *py("tests/seal_audit_v150.py", 1800)),
    ("seal-audit-receipts", *py("tests/seal_audit_receipts_v150.py", 900)),
    ("exact-verify", *py("tests/exact_verify_test.py", 900)),
    ("branch-discontinuity", *py("tests/branch_discontinuity_test.py", 900)),
    ("evidence-verify", *py("release/verify_evidence.py", 1800)),
    ("compat-floor", [sys.executable, "tools/compat_floor.py", "--check"], 600),
    ("evidence-determinism", *py("tests/evidence_determinism_test.py", 1800)),
    ("claim-router-output-v172", *py("tests/claim_router_output_v172_test.py", 300)),
    (
        "claim-router-output-v172-optimized",
        *py("tests/claim_router_output_v172_test.py", 300, optimized=True),
    ),
    ("claim-hostile", *py("tests/claim_hostile_test.py", 1800)),
    ("claim-dogfood", *py("tests/claim_dogfood_test.py", 1800)),
    ("claim-aba", *py("tests/claim_aba_test.py", 3600)),
    ("int-cert-matrix", *py("tests/int_cert_matrix_test.py", 1800)),
    ("int-cert-aba", *py("tests/int_cert_aba_test.py", 3600)),
    ("int-cert-differential", *py("tests/int_cert_differential.py", 1800)),
    ("int-cert-release", *py("tests/int_cert_release_test.py", 1800)),
]


PACKAGE_GATES: list[tuple[str, list[str], int]] = [
    ("package-v172-contract", *py("tests/package_contract_v172_test.py", 180)),
    ("package-v172-build", ["/bin/sh", "release/build_package_v172.sh", "--build"], 1800),
    (
        "package-v172-fresh-extract-parity",
        [sys.executable, os.fspath(DRIVER), "--internal-package-fresh-extract"],
        1800,
    ),
]


ARCHIVAL_GATES: list[tuple[str, list[str], int]] = [
    (
        "archival-range-replay-v150",
        [sys.executable, os.fspath(DRIVER), "--internal-archival-range-replay"],
        1800,
    ),
    (
        "archival-int-cert-revocation-v170",
        [sys.executable, os.fspath(DRIVER), "--internal-archival-int-revocation"],
        1800,
    ),
]


FINAL_GATES: list[tuple[str, list[str], int]] = [
    ("manifest-v172-final", [sys.executable, "release/tools/repin_v172.py", "--check"], 120)
]

GATES = PREFLIGHT_GATES + CURRENT_GATES + PACKAGE_GATES + ARCHIVAL_GATES + FINAL_GATES
LEAN_CWD_GATES = {"lake-build-current", "int-premise-contract"}
MANDATORY_SELECTION_GATES = {"dependency-toolchain-preflight", "manifest-v172-preflight"}


_SKIP_PATTERNS = (
    re.compile(r"(?im)^\s*(?:SKIP|SKIPPED)(?:\b|[-_:])"),
    re.compile(r"(?i)NOT-EXECUTED"),
    re.compile(r"(?i)manifest-pending"),
    re.compile(r'(?i)["\']verdict["\']\s*:\s*["\']ORACLE_SKIP["\']'),
    re.compile(r"(?i)\b(?:ORACLE_SKIP|IV_CROSSCHECK_SKIPPED)=(?!0\b)[0-9]+"),
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def require_regular(path: Path, label: str) -> None:
    try:
        mode = path.lstat().st_mode
    except OSError as exc:
        raise GateRefusal(f"{label}-missing:{path}:{exc}") from exc
    if not stat.S_ISREG(mode) or path.is_symlink():
        raise GateRefusal(f"{label}-not-regular:{path}")


def require_digest(path: Path, expected: str, label: str) -> None:
    require_regular(path, label)
    observed = sha256(path)
    if observed != expected:
        raise GateRefusal(
            f"{label}-identity:observed={observed}:expected={expected}:path={path}"
        )


def skip_markers(output: str) -> list[str]:
    """Return fail-closed skip markers while allowing explicit zero counts."""

    markers: list[str] = []
    for line in output.splitlines():
        if any(pattern.search(line) for pattern in _SKIP_PATTERNS):
            markers.append(line.strip()[:240])
    return markers


def internal_preflight() -> None:
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        raise GateRefusal(
            "unsupported-host:"
            f"system={platform.system()}:machine={platform.machine()}:"
            "expected=Darwin/arm64"
        )
    if sys.version_info < (3, 11):
        raise GateRefusal(f"python-too-old:{platform.python_version()}")
    for tool in ("lake", "git"):
        if shutil.which(tool) is None:
            raise GateRefusal(f"dependency-missing:{tool}")
    for tool in (Path("/usr/bin/shasum"), Path("/usr/bin/uname"), Path("/bin/sh")):
        require_regular(tool, "dependency")
    require_digest(COMPILER, COMPILER_SHA256, "compiler-authority")
    for relative in (
        "release/MANIFEST.sha256",
        "release/tools/repin_v172.py",
        "release/build_package_v172.sh",
        "release/evidence/range_proof_identity_v172.json",
        "release/evidence/int_cert_proof_identity_v172.json",
        "release/evidence/range_proof_identity.json",
        "release/evidence/int_cert_proof_identity.json",
        "release/compat/v172_floor.json",
        "release/evidence/range_ordering_aba_v172.json",
        "release/evidence/int_cert_premise_aba_v172.json",
    ):
        require_regular(ROOT / relative, "required-input")
    # Historical verification never trusts an ambient "old enough" binary.
    # The range checker is replay authority; the int checker is retained only
    # as an exact known-bad negative fixture for the revocation regression.
    runtime = archival_runtime()
    require_digest(
        runtime / "jackal_cert_check",
        V170_RANGE_CHECKER_SHA256,
        "archival-range-dependency",
    )
    require_digest(
        runtime / "jackal_int_cert_check",
        REVOKED_V170_INT_CHECKER_SHA256,
        "revoked-int-negative-fixture",
    )
    require_digest(
        runtime / "formal_coverage_inventory.json",
        V170_COVERAGE_INVENTORY_SHA256,
        "archival-range-inventory-dependency",
    )
    print(
        "PREFLIGHT_V172_PASS platform=macos-arm64 "
        f"python={platform.python_version()} compiler_sha256={COMPILER_SHA256} "
        f"archival_range_checker_sha256={V170_RANGE_CHECKER_SHA256} "
        f"archival_range_inventory_sha256={V170_COVERAGE_INVENTORY_SHA256} "
        f"revoked_int_negative_fixture_sha256={REVOKED_V170_INT_CHECKER_SHA256}"
    )


def tree_inventory(root: Path) -> dict[str, tuple[int, int, str]]:
    inventory: dict[str, tuple[int, int, str]] = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        mode = path.lstat().st_mode
        if stat.S_ISDIR(mode):
            continue
        if not stat.S_ISREG(mode) or path.is_symlink():
            raise GateRefusal(f"package-tree-nonregular:{relative}")
        inventory[relative] = (stat.S_IMODE(mode), path.stat().st_size, sha256(path))
    return inventory


def safe_extract_package(archive: Path, destination: Path) -> Path:
    require_regular(archive, "package-tarball")
    seen: set[str] = set()
    total = 0
    with tarfile.open(archive, "r:gz") as bundle:
        members = bundle.getmembers()
        if not members or len(members) > 4096:
            raise GateRefusal(f"package-member-count:{len(members)}")
        for member in members:
            pure = PurePosixPath(member.name)
            if (
                pure.is_absolute()
                or not pure.parts
                or pure.parts[0] != PACKAGE_NAME
                or any(part in ("", ".", "..") for part in pure.parts)
                or member.name in seen
            ):
                raise GateRefusal(f"package-member-path:{member.name}")
            seen.add(member.name)
            if not (member.isdir() or member.isfile()):
                raise GateRefusal(f"package-member-type:{member.name}")
            total += member.size
            if total > 2 * 1024 * 1024 * 1024:
                raise GateRefusal("package-expanded-size")

        for member in members:
            target = destination.joinpath(*PurePosixPath(member.name).parts)
            if member.isdir():
                target.mkdir(mode=member.mode & 0o777, parents=True, exist_ok=True)
                continue
            target.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
            source = bundle.extractfile(member)
            if source is None:
                raise GateRefusal(f"package-member-read:{member.name}")
            with target.open("xb") as output:
                shutil.copyfileobj(source, output, length=1024 * 1024)
                output.flush()
                os.fsync(output.fileno())
            if target.stat().st_size != member.size:
                raise GateRefusal(f"package-member-size:{member.name}")
            target.chmod(member.mode & 0o777)
    extracted = destination / PACKAGE_NAME
    if not extracted.is_dir() or extracted.is_symlink():
        raise GateRefusal("package-top-level")
    return extracted


def run_checked(command: list[str], *, cwd: Path, timeout: int = 1800) -> str:
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            env=dict(os.environ),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise GateRefusal(f"child-timeout:{timeout}:command={command!r}") from exc
    combined = (completed.stdout or "") + "\n" + (completed.stderr or "")
    if completed.returncode != 0:
        raise GateRefusal(
            f"child-exit:{completed.returncode}:command={command!r}:tail={combined[-1000:]!r}"
        )
    markers = skip_markers(combined)
    if markers:
        raise GateRefusal(f"child-skip:{markers!r}:command={command!r}")
    return combined


def internal_package_fresh_extract() -> None:
    require_regular(PACKAGE_TARBALL, "package-tarball")
    if not PACKAGE_DIR.is_dir() or PACKAGE_DIR.is_symlink():
        raise GateRefusal(f"package-directory:{PACKAGE_DIR}")
    source_inventory = tree_inventory(PACKAGE_DIR)
    with tempfile.TemporaryDirectory(prefix="jackal-v172-package-parity-") as raw:
        extracted = safe_extract_package(PACKAGE_TARBALL, Path(raw))
        extracted_inventory = tree_inventory(extracted)
        if extracted_inventory != source_inventory:
            source_names = set(source_inventory)
            extracted_names = set(extracted_inventory)
            raise GateRefusal(
                "package-tree-parity:"
                f"missing={sorted(source_names - extracted_names)[:5]}:"
                f"extra={sorted(extracted_names - source_names)[:5]}"
            )
        run_checked(["/usr/bin/shasum", "-a", "256", "-c", "SHA256SUMS"], cwd=extracted)
        manifest = (extracted / "MANIFEST.sha256").read_text(encoding="utf-8")
        required_rows = (
            "version v1.7.2",
            f"archival_range_checker jackal_cert_check_v170 {V170_RANGE_CHECKER_SHA256}",
            "archival_range_coverage_inventory "
            "evidence/formal_coverage_inventory_v170.json "
            f"{V170_COVERAGE_INVENTORY_SHA256}",
        )
        for row in required_rows:
            if row not in manifest.splitlines():
                raise GateRefusal(f"package-manifest-row:{row}")
        # Preflight already binds the on-disk runtime tuple; the fresh
        # extract additionally binds the tuple the package itself ships,
        # by exact byte digest, independent of any manifest string. A
        # cross-mixed archival tuple in the package cannot pass both.
        require_digest(
            extracted / "jackal_cert_check_v170",
            V170_RANGE_CHECKER_SHA256,
            "package-archival-range-checker",
        )
        require_digest(
            extracted / "evidence/formal_coverage_inventory_v170.json",
            V170_COVERAGE_INVENTORY_SHA256,
            "package-archival-range-inventory",
        )
        current_inventory_sha = sha256(
            extracted / "formal_coverage_inventory.json"
        )
        if current_inventory_sha == V170_COVERAGE_INVENTORY_SHA256:
            raise GateRefusal(
                "package-current-archival-inventory-collision"
            )
        if any(
            line.startswith("archival_int_cert_checker ")
            for line in manifest.splitlines()
        ):
            raise GateRefusal("package-revoked-int-checker-manifest-row")
        revoked_checker = extracted / "jackal_int_cert_check_v170"
        if revoked_checker.exists() or revoked_checker.is_symlink():
            raise GateRefusal("package-revoked-int-checker-present")
        compatibility = json.loads(
            (extracted / "evidence/compat_v172_floor.json").read_text(
                encoding="utf-8"
            )
        )
        try:
            revoked_policy = compatibility["lanes"]["int_cert"]["archival_v1"]
        except (KeyError, TypeError) as exc:
            raise GateRefusal("package-int-revocation-policy-missing") from exc
        if (
            revoked_policy.get("mode") != "revoked-refuse"
            or revoked_policy.get("allowed_release_epochs") != []
            or "raw request expression" not in str(revoked_policy.get("reason", ""))
        ):
            raise GateRefusal("package-int-revocation-policy")

        range_receipt = extracted / ".gate-range-receipt.json"
        range_output = run_checked(
            [
                os.fspath(extracted / "jackal-cert-release"),
                "x^2+1",
                "1",
                "2",
                os.fspath(range_receipt),
            ],
            cwd=extracted,
        )
        if "status=formal-bounded" not in range_output:
            raise GateRefusal("package-range-smoke-status")
        range_doc = json.loads(range_receipt.read_text(encoding="utf-8"))
        if range_doc.get("release_epoch") != "v1.7.2":
            raise GateRefusal("package-range-smoke-epoch")

        int_receipt = extracted / ".gate-int-receipt.json"
        int_output = run_checked(
            [
                os.fspath(extracted / "jackal-int-cert-release"),
                "x^2",
                "0",
                "1",
                "1/1000",
                os.fspath(int_receipt),
            ],
            cwd=extracted,
        )
        if "status=formal-bounded" not in int_output:
            raise GateRefusal("package-int-smoke-status")
        int_doc = json.loads(int_receipt.read_text(encoding="utf-8"))
        if int_doc.get("release_epoch") != "v1.7.2":
            raise GateRefusal("package-int-smoke-epoch")

        claim_request = extracted / ".gate-int-claim-request.json"
        claim_bundle = extracted / ".gate-int-claim-bundle.json"
        claim_root = extracted / ".gate-int-claim-root.json"
        request_doc = {
            "schema": "jackal-claim-request-v1",
            "emitted_at_unix": "1786752000",
            "steps": [{"id": "i", "op": "integrate_cert",
                       "expression": "0", "lo": "0", "hi": "1",
                       "tolerance": "2"}],
            "root": "i",
        }
        claim_request.write_text(
            json.dumps(request_doc, sort_keys=True), encoding="utf-8")
        run_checked(
            [os.fspath(extracted / "jackal-claim"), "--request",
             os.fspath(claim_request), "--emit-bundle",
             os.fspath(claim_bundle)], cwd=extracted)
        bundle_doc = json.loads(claim_bundle.read_text(encoding="utf-8"))
        by_id = {node["id"]: node for node in bundle_doc["nodes"]}
        root_node = by_id[bundle_doc["root"]]
        manifest_rows = {
            line.split()[0]: line.split()[-1]
            for line in manifest.splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        }
        if (
            root_node.get("proposition", {}).get("arg", {}).get("fn")
            != "formal.integral"
            or root_node.get("checker", {}).get("sha256")
            != manifest_rows.get("int_cert_checker")
        ):
            raise GateRefusal("package-int-claim-context")
        claim_root.write_text(
            json.dumps(root_node["proposition"], sort_keys=True),
            encoding="utf-8")
        policy_sha = hashlib.sha256(
            json.dumps(bundle_doc["policy"], sort_keys=True,
                       separators=(",", ":"), ensure_ascii=False).encode()
        ).hexdigest()
        claim_output = run_checked(
            [os.fspath(extracted / "jackal-claim-verify"),
             "--bundle", os.fspath(claim_bundle),
             "--expected-release-epoch", "v1.6.0",
             "--expected-policy-sha256", policy_sha,
             "--expected-root-proposition", os.fspath(claim_root),
             "--verification-time-unix", "1786752000"],
            cwd=extracted)
        if "claim-verify=verified" not in claim_output:
            raise GateRefusal("package-int-claim-replay")
        plugin_output = run_checked(
            [os.fspath(extracted / "plugin/hermes/jackal_hermes"), "selftest"],
            cwd=extracted,
        )
        if "plugin_hermes.identity_match=true" not in plugin_output:
            raise GateRefusal("package-hermes-selftest-identity")
    print(
        "PACKAGE_V172_FRESH_EXTRACT_PASS "
        f"files={len(source_inventory)} tarball_sha256={sha256(PACKAGE_TARBALL)}"
    )


def archival_runtime() -> Path:
    configured = os.environ.get("JACKAL_V170_RUNTIME")
    candidate = (
        Path(configured).expanduser()
        if configured
        else Path.home() / "Library/Application Support/JACKAL/runtimes/v1.7.0"
    )
    if not candidate.is_dir() or candidate.is_symlink():
        raise GateRefusal(f"archival-runtime-missing:{candidate}")
    return candidate.resolve()


def archival_verifier_accepts(output: str) -> bool:
    required = {
        "status=verified verdict=ACCEPT",
        "receipt_valid=true",
        "checker_verdict=ACCEPT",
    }
    return required <= {line.strip() for line in output.splitlines()}


def int_revocation_refused(returncode: int, output: str) -> bool:
    text = output.lower()
    return (
        returncode == 1
        and "status=refused" in text
        and "reason=proof-compatibility" in text
        and any(token in text for token in ("unsupported lane/schema/release tuple", "revoked"))
    )


def verify_archival_receipt(
    verifier: Path,
    inventory: Path,
    cwd: Path,
    receipt: Path,
    checker: Path,
    expected_checker: str,
    proof_identity: Path,
) -> None:
    document = json.loads(receipt.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise GateRefusal("archival-receipt-root")
    variant = document.get("variant")
    expected_epoch = "v1.5.0"
    if variant != "range":
        raise GateRefusal(f"archival-receipt-variant:{variant!r}")
    if document.get("release_epoch") != expected_epoch:
        raise GateRefusal(f"archival-receipt-epoch:{variant}")
    identities = document.get("identities")
    request = document.get("request")
    fragment = document.get("fragment")
    proof = document.get("proof_identity")
    if not all(isinstance(item, dict) for item in (identities, request, fragment, proof)):
        raise GateRefusal(f"archival-receipt-structure:{variant}")
    if identities.get("checker_sha256") != expected_checker:
        raise GateRefusal(f"archival-receipt-checker:{variant}")
    require_digest(checker, expected_checker, f"archival-{variant}-checker")
    require_regular(proof_identity, f"archival-{variant}-proof")
    if proof.get("file_sha256") != sha256(proof_identity):
        raise GateRefusal(f"archival-receipt-proof-file:{variant}")

    command = [
        os.fspath(verifier),
        "--receipt",
        os.fspath(receipt),
        "--checker",
        os.fspath(checker),
        "--expected-evaluator",
        str(identities.get("evaluator_sha256")),
        "--expected-checker",
        expected_checker,
        "--expected-release-epoch",
        expected_epoch,
        "--expected-command",
        str(request.get("command")),
        "--expected-expression",
        str(request.get("expression")),
        "--expected-input-lo",
        str(request.get("input_lo")),
        "--expected-input-hi",
        str(request.get("input_hi")),
        "--inventory",
        os.fspath(inventory),
        "--expected-inventory",
        str(fragment.get("coverage_inventory_sha256")),
        "--proof-identity",
        os.fspath(proof_identity),
        "--expected-proof-identity-file",
        str(proof.get("file_sha256")),
        "--expected-proof-identity-digest",
        str(proof.get("identity_digest_sha256")),
    ]
    source = identities.get("source_anb_sha256")
    command.extend(["--expected-source", str(source)])
    output = run_checked(command, cwd=cwd)
    if not archival_verifier_accepts(output):
        raise GateRefusal(f"archival-receipt-verdict:{variant}")


def internal_archival_range_replay() -> None:
    runtime = archival_runtime()
    packaged_range = PACKAGE_DIR / "jackal_cert_check_v170"
    packaged_inventory = PACKAGE_DIR / "evidence/formal_coverage_inventory_v170.json"
    require_digest(packaged_range, V170_RANGE_CHECKER_SHA256, "archival-range-checker")
    require_digest(
        packaged_inventory,
        V170_COVERAGE_INVENTORY_SHA256,
        "archival-range-coverage-inventory",
    )
    require_digest(
        runtime / "jackal_cert_check",
        V170_RANGE_CHECKER_SHA256,
        "archival-runtime-range-checker",
    )
    for name in (
        "SHA256SUMS",
        "jackal-cert-release",
        "jackal-receipt-verify",
        "formal_coverage_inventory.json",
        "range_proof_identity.json",
    ):
        require_regular(runtime / name, "archival-runtime-input")
    run_checked(["/usr/bin/shasum", "-a", "256", "-c", "SHA256SUMS"], cwd=runtime)

    with tempfile.TemporaryDirectory(prefix="jackal-v150-archival-range-replay-") as raw:
        temporary = Path(raw)
        range_receipt = temporary / "range.json"
        range_output = run_checked(
            [
                os.fspath(runtime / "jackal-cert-release"),
                "x^2+1",
                "1",
                "2",
                os.fspath(range_receipt),
            ],
            cwd=runtime,
        )
        if "status=formal-bounded" not in range_output:
            raise GateRefusal("archival-range-producer-status")
        verify_archival_receipt(
            PACKAGE_DIR / "jackal-receipt-verify",
            PACKAGE_DIR / "evidence/formal_coverage_inventory_v170.json",
            PACKAGE_DIR,
            range_receipt,
            packaged_range,
            V170_RANGE_CHECKER_SHA256,
            PACKAGE_DIR / "evidence/range_proof_identity_v1.json",
        )
    print(
        "ARCHIVAL_RANGE_REPLAY_V150_PASS "
        f"range_checker_sha256={V170_RANGE_CHECKER_SHA256}"
    )


def internal_archival_int_revocation() -> None:
    runtime = archival_runtime()
    require_digest(
        runtime / "jackal_int_cert_check",
        REVOKED_V170_INT_CHECKER_SHA256,
        "revoked-int-checker-reference",
    )
    for path in (
        runtime / "SHA256SUMS",
        runtime / "jackal-int-cert-release",
        PACKAGE_DIR / "jackal-receipt-verify",
        PACKAGE_DIR / "formal_coverage_inventory.json",
        PACKAGE_DIR / "evidence/int_cert_proof_identity_v1.json",
    ):
        require_regular(path, "int-revocation-input")
    run_checked(["/usr/bin/shasum", "-a", "256", "-c", "SHA256SUMS"], cwd=runtime)
    with tempfile.TemporaryDirectory(prefix="jackal-v170-int-revocation-") as raw:
        receipt = Path(raw) / "historical-int.json"
        old_output = run_checked(
            [
                os.fspath(runtime / "jackal-int-cert-release"),
                "x^2",
                "0",
                "1",
                "1/1000",
                os.fspath(receipt),
            ],
            cwd=runtime,
        )
        if "status=formal-bounded" not in old_output:
            raise GateRefusal("int-revocation-historical-fixture")
        document = json.loads(receipt.read_text(encoding="utf-8"))
        identities = document.get("identities", {})
        request = document.get("request", {})
        fragment = document.get("fragment", {})
        proof = document.get("proof_identity", {})
        if (
            document.get("variant") != "int_cert"
            or document.get("release_epoch") != "v1.7.0"
            or identities.get("checker_sha256")
            != REVOKED_V170_INT_CHECKER_SHA256
        ):
            raise GateRefusal("int-revocation-historical-context")
        command = [
            os.fspath(PACKAGE_DIR / "jackal-receipt-verify"),
            "--receipt",
            os.fspath(receipt),
            "--checker",
            os.fspath(runtime / "jackal_int_cert_check"),
            "--expected-evaluator",
            str(identities.get("evaluator_sha256")),
            "--expected-checker",
            REVOKED_V170_INT_CHECKER_SHA256,
            "--expected-release-epoch",
            "v1.7.0",
            "--expected-command",
            str(request.get("command")),
            "--expected-expression",
            str(request.get("expression")),
            "--expected-input-lo",
            str(request.get("input_lo")),
            "--expected-input-hi",
            str(request.get("input_hi")),
            "--expected-tolerance",
            str(request.get("tolerance")),
            "--inventory",
            os.fspath(PACKAGE_DIR / "formal_coverage_inventory.json"),
            "--expected-inventory",
            str(fragment.get("coverage_inventory_sha256")),
            "--proof-identity",
            os.fspath(PACKAGE_DIR / "evidence/int_cert_proof_identity_v1.json"),
            "--expected-proof-identity-file",
            str(proof.get("file_sha256")),
            "--expected-proof-identity-digest",
            str(proof.get("identity_digest_sha256")),
        ]
        completed = subprocess.run(
            command,
            cwd=PACKAGE_DIR,
            env=dict(os.environ),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=300,
            check=False,
        )
        output = (completed.stdout or "") + "\n" + (completed.stderr or "")
        if not int_revocation_refused(completed.returncode, output):
            raise GateRefusal(
                "int-revocation-not-enforced:"
                f"returncode={completed.returncode}:tail={output[-1000:]!r}"
            )
    print(
        "ARCHIVAL_INT_CERT_REVOCATION_V170_PASS "
        f"known_bad_checker_sha256={REVOKED_V170_INT_CHECKER_SHA256}"
    )


def internal(action: str) -> int:
    try:
        if action == "--internal-preflight":
            internal_preflight()
        elif action == "--internal-package-fresh-extract":
            internal_package_fresh_extract()
        elif action == "--internal-archival-range-replay":
            internal_archival_range_replay()
        elif action == "--internal-archival-int-revocation":
            internal_archival_int_revocation()
        else:
            raise GateRefusal(f"unknown-internal-action:{action}")
    except (GateRefusal, OSError, ValueError, json.JSONDecodeError, tarfile.TarError) as exc:
        print(f"INTERNAL_V172_REFUSED reason={exc}", file=sys.stderr)
        return 1
    return 0


def tail_text(completed: subprocess.CompletedProcess[str] | None) -> str:
    if completed is None:
        return "timeout"
    lines = [
        line
        for line in ((completed.stdout or "") + "\n" + (completed.stderr or "")).splitlines()
        if line.strip()
    ]
    return lines[-1][:150] if lines else ""


def refuse_unknown(unknown: list[str]) -> NoReturn:
    print(f"GATES: REFUSED unknown={','.join(unknown)}", file=sys.stderr)
    raise SystemExit(2)


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if len(arguments) == 1 and arguments[0].startswith("--internal-"):
        return internal(arguments[0])
    if arguments == ["--list"]:
        for name, command, timeout in GATES:
            print(f"{name}\ttimeout={timeout}\t{' '.join(command)}")
        return 0

    selected = set(arguments)
    known = {name for name, _command, _timeout in GATES}
    unknown = sorted(selected - known)
    if unknown:
        refuse_unknown(unknown)
    if selected:
        selected.update(MANDATORY_SELECTION_GATES)

    results: list[tuple[str, str, float]] = []
    for name, command, timeout in GATES:
        if selected and name not in selected:
            continue
        cwd = ROOT / "proofs/lean" if name in LEAN_CWD_GATES else ROOT
        started = time.time()
        try:
            completed = subprocess.run(
                command,
                cwd=cwd,
                env=dict(os.environ),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=timeout,
                check=False,
            )
            markers = skip_markers((completed.stdout or "") + "\n" + (completed.stderr or ""))
            passed = completed.returncode == 0 and not markers
        except subprocess.TimeoutExpired:
            completed = None
            markers = []
            passed = False
        elapsed = time.time() - started
        status = "PASS" if passed else "FAIL"
        results.append((name, status, elapsed))
        print(f"{status} {name} ({elapsed:.0f}s) :: {tail_text(completed)}")
        if not passed:
            if markers:
                print(f"---- refused skip markers: {markers!r} ----")
            if completed is not None:
                print("---- stdout tail ----")
                sys.stdout.write((completed.stdout or "")[-3000:] + "\n")
                print("---- stderr tail ----")
                sys.stdout.write((completed.stderr or "")[-3000:] + "\n")
            print(f"GATES: FAIL at {name}")
            return 1
    print(f"GATES: PASS ({len(results)} gates)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
