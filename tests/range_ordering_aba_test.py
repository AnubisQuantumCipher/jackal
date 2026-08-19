#!/usr/bin/env python3
"""Isolated A->B->A mutation gate for the range ACCEPT contract.

Every B-state is compiled in a throwaway APFS clone of ``proofs/lean``.  The
canonical source and checker are read-only inputs to this test and must retain
their exact pre-run identities.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LEAN_DIR = ROOT / "proofs" / "lean"
REQUEST_SOURCE = LEAN_DIR / "JackalIv" / "CertRequest.lean"
MAIN_SOURCE = LEAN_DIR / "JackalIv" / "CertCheckMain.lean"
CHECKER = LEAN_DIR / ".lake" / "build" / "bin" / "jackal_cert_check"
EVIDENCE = ROOT / "release" / "evidence" / "range_ordering_aba_v172.json"
MAX_READ_BYTES = 8 * 1024 * 1024
MAX_BUILD_OUTPUT_BYTES = 2 * 1024 * 1024

sys.path.insert(0, os.fspath(ROOT / "tests"))
import range_ordering_contract_test as contract  # noqa: E402


class GateFailure(RuntimeError):
    """Deterministic fail-closed gate refusal."""


def read_regular(path: Path, maximum: int = MAX_READ_BYTES) -> bytes:
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or before.st_size > maximum:
        raise GateFailure(f"not a bounded regular file: {path}")
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        opened = os.fstat(descriptor)
        if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
            raise GateFailure(f"path identity changed before read: {path}")
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(descriptor, min(65_536, maximum + 1 - total))
            if not chunk:
                break
            total += len(chunk)
            if total > maximum:
                raise GateFailure(f"file exceeds byte bound: {path}")
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
        raise GateFailure(f"file changed while reading: {path}")
    return b"".join(chunks)


def sha256(path: Path, maximum: int = MAX_READ_BYTES) -> str:
    return hashlib.sha256(read_regular(path, maximum)).hexdigest()


def replace_exact(source: Path, old: bytes, new: bytes) -> None:
    original = read_regular(source)
    if original.count(old) != 1:
        raise GateFailure(f"mutation anchor count is not one: {source}")
    source.write_bytes(original.replace(old, new, 1))


def minimal_environment(lake: Path) -> dict[str, str]:
    return {
        "HOME": os.fspath(Path.home()),
        "PATH": f"{lake.parent}:/usr/bin:/bin:/usr/sbin:/sbin",
        "LC_ALL": "C",
    }


def bounded_build(sandbox: Path, target: str, lake: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [os.fspath(lake), "build", target],
        cwd=sandbox,
        env=minimal_environment(lake),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=1200,
        check=False,
    )


def clone_lean(parent: Path, name: str) -> Path:
    destination = parent / name
    completed = subprocess.run(
        ["/bin/cp", "-cR", os.fspath(LEAN_DIR), os.fspath(destination)],
        env={"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "LC_ALL": "C"},
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=600,
        check=False,
    )
    if completed.returncode != 0 or not destination.is_dir():
        raise GateFailure(
            "APFS clone failed: "
            + completed.stderr[:512].decode("utf-8", errors="replace")
        )
    return destination


def require(condition: bool, detail: str) -> None:
    if not condition:
        raise GateFailure(detail)


def main() -> int:
    lake_text = shutil.which("lake")
    if lake_text is None:
        raise GateFailure("lake is not available")
    lake = Path(lake_text).absolute()
    for path in (REQUEST_SOURCE, MAIN_SOURCE, CHECKER, lake):
        require(path.is_file(), f"required file is missing: {path}")

    producer = contract.INSTALLED_RUNTIME / "jackal-native"
    clean = contract.clean_certificate(producer)
    poison = contract.coherent_reversal(clean)
    pre = {
        "CertRequest.lean": sha256(REQUEST_SOURCE),
        "CertCheckMain.lean": sha256(MAIN_SOURCE),
        "jackal_cert_check": sha256(CHECKER, contract.MAX_ARTIFACT_BYTES),
    }

    clean_result = contract.run_checker(CHECKER, clean, "1", "2")
    poison_result = contract.run_checker(CHECKER, poison, "2", "1")
    require(clean_result.returncode == 0, "A/pre clean control did not accept")
    require(
        clean_result.stdout
        == b"ACCEPT request-bound theorem=request_bound_certified_release "
        b"command=range-bound-cert output 1 2\n",
        "A/pre ACCEPT token drifted",
    )
    require(poison_result.returncode != 0, "A/pre coherent reversal accepted")
    require(b"interval-order" in poison_result.stderr, "A/pre wrong refusal class")

    runtime_anchor = (
        b"if requestMatches command rawExpr rawLo rawHi hdr nodes then .ok hdr"
    )
    ordering_anchor = (
        b"def releaseIntervalsOrdered (hdr : Header) : Bool :=\n"
        b"  decide (hdr.input_lo <= hdr.input_hi) &&\n"
        b"  decide (hdr.output_lo <= hdr.output_hi)"
    )
    # Lean source contains the Unicode relation token, so derive this anchor
    # from the exact canonical bytes rather than relying on locale conversion.
    ordering_anchor = (
        "def releaseIntervalsOrdered (hdr : Header) : Bool :=\n"
        "  decide (hdr.input_lo ≤ hdr.input_hi) &&\n"
        "  decide (hdr.output_lo ≤ hdr.output_hi)"
    ).encode("utf-8")
    ordering_mutation = (
        "def releaseIntervalsOrdered (_hdr : Header) : Bool := true"
    ).encode("utf-8")
    tcb_anchor = b"  | _                 => false"
    tcb_mutation = b"  | \"sqrt\"          => true\n  | _                 => false"

    evidence: dict[str, object] = {
        "schema": "jackal-range-ordering-aba-v172",
        "status": "passed",
        "isolation": "throwaway APFS clones; canonical source and executable not rebuilt",
        "canonical_pre_sha256": pre,
        "clean_certificate_sha256": hashlib.sha256(clean).hexdigest(),
        "coherent_reversal_sha256": hashlib.sha256(poison).hexdigest(),
        "A_pre": {
            "clean_accept": True,
            "poison_refused": True,
            "reason_class": "interval-order",
        },
    }

    with tempfile.TemporaryDirectory(prefix="jackal-range-aba-") as temporary:
        parent = Path(temporary)

        runtime = clone_lean(parent, "runtime-bypass")
        replace_exact(
            runtime / "JackalIv" / "CertCheckMain.lean",
            runtime_anchor,
            b"if true then .ok hdr",
        )
        runtime_build = bounded_build(runtime, "jackal_cert_check", lake)
        require(runtime_build.returncode == 0, "runtime bypass did not compile")
        runtime_result = contract.run_checker(
            runtime / ".lake" / "build" / "bin" / "jackal_cert_check",
            poison,
            "2",
            "1",
        )
        require(
            runtime_result.returncode == 0
            and b"ACCEPT request-bound" in runtime_result.stdout,
            "runtime bypass did not admit coherent reversal",
        )
        evidence["B_runtime_bypass"] = {
            "build_exit": 0,
            "poison_admitted": True,
        }

        ordering = clone_lean(parent, "ordering-proof")
        replace_exact(
            ordering / "JackalIv" / "CertRequest.lean",
            ordering_anchor,
            ordering_mutation,
        )
        ordering_build = bounded_build(ordering, "JackalIv.CertRequest", lake)
        ordering_output = ordering_build.stdout + ordering_build.stderr
        require(ordering_build.returncode != 0, "ordering proof mutation compiled")
        require(len(ordering_output) <= MAX_BUILD_OUTPUT_BYTES, "ordering build output overflow")
        evidence["B_ordering_proof"] = {
            "build_exit_nonzero": True,
            "proof_load_bearing": True,
        }

        tcb = clone_lean(parent, "model-tcb-proof")
        replace_exact(
            tcb / "JackalIv" / "CertRequest.lean",
            tcb_anchor,
            tcb_mutation,
        )
        tcb_build = bounded_build(tcb, "JackalIv.CertRequest", lake)
        tcb_output = tcb_build.stdout + tcb_build.stderr
        require(tcb_build.returncode != 0, "modeled-constructor mutation compiled")
        require(len(tcb_output) <= MAX_BUILD_OUTPUT_BYTES, "TCB build output overflow")
        evidence["B_model_tcb"] = {
            "build_exit_nonzero": True,
            "allowlist_expansion_breaks_proof": True,
        }

    post = {
        "CertRequest.lean": sha256(REQUEST_SOURCE),
        "CertCheckMain.lean": sha256(MAIN_SOURCE),
        "jackal_cert_check": sha256(CHECKER, contract.MAX_ARTIFACT_BYTES),
    }
    require(post == pre, "canonical A/post identity changed")
    final_poison = contract.run_checker(CHECKER, poison, "2", "1")
    require(final_poison.returncode != 0, "A/post coherent reversal accepted")
    evidence["canonical_post_sha256"] = post
    evidence["A_post"] = {"identity_restored": True, "poison_refused": True}

    EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE.write_text(
        json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        "range_ordering_aba=PASS "
        f"checker_sha256={pre['jackal_cert_check']} "
        f"evidence_sha256={hashlib.sha256(EVIDENCE.read_bytes()).hexdigest()}"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (GateFailure, OSError, subprocess.SubprocessError) as error:
        print(f"range_ordering_aba=REFUSED detail={str(error)[:512]}", file=sys.stderr)
        raise SystemExit(1) from None
