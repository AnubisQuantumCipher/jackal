#!/usr/bin/env python3
"""Isolated A->B->A gate for the closed-premise int-cert theorem."""

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
LEAN_DIR = ROOT / "proofs" / "lean"
CHECK_SOURCE = LEAN_DIR / "JackalIv" / "IntCertCheck.lean"
SOUND_SOURCE = LEAN_DIR / "JackalIv" / "IntCertSound.lean"
CONTRACT_SOURCE = LEAN_DIR / "JackalIv" / "IntCertPremiseContract.lean"
CHECKER = LEAN_DIR / ".lake" / "build" / "bin" / "jackal_int_cert_check"
EVIDENCE = ROOT / "release" / "evidence" / "int_cert_premise_aba_v172.json"

sys.path.insert(0, os.fspath(ROOT / "tests"))
sys.path.insert(0, os.fspath(ROOT / "tools"))
import range_ordering_aba_test as aba  # noqa: E402
import int_cert_producer as producer  # noqa: E402


def run_checker(checker: Path, artifact: bytes) -> subprocess.CompletedProcess:
    with tempfile.NamedTemporaryFile(suffix=".jic", delete=False) as handle:
        handle.write(artifact)
        artifact_path = Path(handle.name)
    try:
        return subprocess.run(
            [
                os.fspath(checker),
                os.fspath(artifact_path),
                "x",
                "0",
                "1",
                "2",
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=300,
            check=False,
        )
    finally:
        artifact_path.unlink(missing_ok=True)


def main() -> int:
    lake_text = shutil.which("lake")
    if lake_text is None:
        raise aba.GateFailure("lake is not available")
    lake = Path(lake_text).absolute()
    for path in (CHECK_SOURCE, SOUND_SOURCE, CONTRACT_SOURCE, CHECKER, lake):
        aba.require(path.is_file(), f"required file is missing: {path}")

    artifact = producer.emit(producer.build("x", "0", "1", "2")).encode("utf-8")
    pre = {
        "IntCertCheck.lean": aba.sha256(CHECK_SOURCE),
        "IntCertSound.lean": aba.sha256(SOUND_SOURCE),
        "IntCertPremiseContract.lean": aba.sha256(CONTRACT_SOURCE),
        "jackal_int_cert_check": aba.sha256(CHECKER, 256 * 1024 * 1024),
    }
    clean_pre = run_checker(CHECKER, artifact)
    aba.require(
        clean_pre.returncode == 0
        and clean_pre.stdout.startswith(b"ACCEPT status=bounded theorem=int_cert_sound"),
        "A/pre composed-integral control did not accept",
    )

    release_guard = (
        b"  guardE (Cert.releaseNodesOk c.nodes)\n"
        b"    \"missing-premise:embedded-cert-release-fragment\""
    )
    release_bypass = (
        b"  guardE true\n"
        b"    \"missing-premise:embedded-cert-release-fragment\""
    )
    request_guard = (
        b"  guardE (intRequestMatches rawExpr rawLo rawHi rawTol hdr tree)\n"
        b"    \"request-mismatch:raw-expression\""
    )
    request_bypass = (
        b"  guardE true\n"
        b"    \"request-mismatch:raw-expression\""
    )
    theorem_anchor = (
        b"    (hchk : checkIntCert hdr tree = .ok ())\n"
        b"    (hq : rootQExpr tree = some q) :"
    )
    theorem_mutation = (
        b"    (hchk : checkIntCert hdr tree = .ok ())\n"
        b"    (hq : rootQExpr tree = some q)\n"
        b"    (_htcb : TreeTCB tree) :"
    )

    evidence: dict[str, object] = {
        "schema": "jackal-int-cert-premise-aba-v172",
        "status": "passed",
        "isolation": "throwaway APFS clones; canonical source and executable not rebuilt",
        "canonical_pre_sha256": pre,
        "clean_artifact_sha256": hashlib.sha256(artifact).hexdigest(),
        "A_pre": {"clean_accept": True},
    }

    with tempfile.TemporaryDirectory(prefix="jackal-int-premise-aba-") as temporary:
        parent = Path(temporary)

        guard = aba.clone_lean(parent, "embedded-release-guard")
        aba.replace_exact(
            guard / "JackalIv" / "IntCertCheck.lean",
            release_guard,
            release_bypass,
        )
        guard_build = aba.bounded_build(guard, "JackalIv.IntCertSound", lake)
        guard_output = guard_build.stdout + guard_build.stderr
        aba.require(
            guard_build.returncode != 0,
            "embedded release-fragment guard mutation compiled",
        )
        aba.require(
            len(guard_output) <= aba.MAX_BUILD_OUTPUT_BYTES,
            "embedded release guard build output overflow",
        )
        evidence["B_embedded_release_guard"] = {
            "build_exit_nonzero": True,
            "proof_load_bearing": True,
        }

        request = aba.clone_lean(parent, "raw-request-guard")
        aba.replace_exact(
            request / "JackalIv" / "IntCertCheck.lean",
            request_guard,
            request_bypass,
        )
        request_build = aba.bounded_build(
            request, "JackalIv.IntCertPremiseContract", lake
        )
        request_output = request_build.stdout + request_build.stderr
        aba.require(
            request_build.returncode != 0,
            "raw request guard mutation compiled",
        )
        aba.require(
            len(request_output) <= aba.MAX_BUILD_OUTPUT_BYTES,
            "raw request guard build output overflow",
        )
        evidence["B_raw_request_guard"] = {
            "build_exit_nonzero": True,
            "public_request_bind_load_bearing": True,
        }

        theorem = aba.clone_lean(parent, "external-tree-tcb")
        aba.replace_exact(
            theorem / "JackalIv" / "IntCertSound.lean",
            theorem_anchor,
            theorem_mutation,
        )
        theorem_build = aba.bounded_build(
            theorem, "JackalIv.IntCertPremiseContract", lake
        )
        theorem_output = theorem_build.stdout + theorem_build.stderr
        aba.require(
            theorem_build.returncode != 0,
            "external TreeTCB theorem mutation satisfied the public contract",
        )
        aba.require(
            len(theorem_output) <= aba.MAX_BUILD_OUTPUT_BYTES,
            "TreeTCB contract build output overflow",
        )
        evidence["B_external_tree_tcb"] = {
            "build_exit_nonzero": True,
            "public_signature_contract_load_bearing": True,
        }

    post = {
        "IntCertCheck.lean": aba.sha256(CHECK_SOURCE),
        "IntCertSound.lean": aba.sha256(SOUND_SOURCE),
        "IntCertPremiseContract.lean": aba.sha256(CONTRACT_SOURCE),
        "jackal_int_cert_check": aba.sha256(CHECKER, 256 * 1024 * 1024),
    }
    aba.require(post == pre, "canonical A/post identity changed")
    clean_post = run_checker(CHECKER, artifact)
    aba.require(
        clean_post.returncode == 0
        and clean_post.stdout.startswith(b"ACCEPT status=bounded theorem=int_cert_sound"),
        "A/post composed-integral control did not accept",
    )
    evidence["canonical_post_sha256"] = post
    evidence["A_post"] = {"identity_restored": True, "clean_accept": True}

    EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE.write_text(
        json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        "int_cert_premise_aba=PASS "
        f"checker_sha256={pre['jackal_int_cert_check']} "
        f"evidence_sha256={hashlib.sha256(EVIDENCE.read_bytes()).hexdigest()}"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (aba.GateFailure, OSError, subprocess.SubprocessError) as error:
        print(
            f"int_cert_premise_aba=REFUSED detail={str(error)[:512]}",
            file=sys.stderr,
        )
        raise SystemExit(1) from None
