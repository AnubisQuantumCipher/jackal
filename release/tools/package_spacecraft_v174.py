#!/usr/bin/env python3
"""Build deterministic JACKAL v1.7.4 spacecraft certificate release assets."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import os
import re
import tarfile
from pathlib import Path
from typing import Sequence


ROOT = Path(__file__).resolve().parents[2]
VERSION = "v1.7.4"
ARCHIVE_NAME = "jackal-spacecraft-burn-v1.7.4-verifier-macos-arm64.tar.gz"
WITNESS_NAME = "baseline_witness_v2.cert"
RECEIPT_NAME = "baseline_receipt_v2.json"
PROOF_NAME = "spacecraft_burn_proof_identity_v1.json"
REVIEW_NAME = "spacecraft_burn_independent_review_v1.md"
CHECKER = ROOT / "proofs/lean/.lake/build/bin/jackal_spacecraft_burn_check"
IDENTITY = ROOT / "release/evidence" / PROOF_NAME
REVIEW = ROOT / "release/evidence" / REVIEW_NAME
EVIDENCE = ROOT / "spacecraft_burn_cert/evidence"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def atomic_write(path: Path, data: bytes, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    try:
        if os.write(descriptor, data) != len(data):
            raise RuntimeError("short release-asset write")
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    os.replace(temporary, path)


def deterministic_tar_gz(entries: dict[str, tuple[bytes, int]]) -> bytes:
    buffer = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=buffer, mtime=0) as compressed:
        with tarfile.open(fileobj=compressed, mode="w", format=tarfile.PAX_FORMAT) as archive:
            for name in sorted(entries):
                data, mode = entries[name]
                info = tarfile.TarInfo(name)
                info.size = len(data)
                info.mode = mode
                info.mtime = 0
                info.uid = info.gid = 0
                info.uname = info.gname = "root"
                archive.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def source_closure(identity: dict) -> list[Path]:
    rows = identity.get("source_closure", {}).get("files")
    if not isinstance(rows, list):
        raise RuntimeError("proof identity lacks source closure")
    result = []
    for row in rows:
        path = row.get("path") if isinstance(row, dict) else None
        if not isinstance(path, str) or path.startswith("/") or ".." in Path(path).parts:
            raise RuntimeError("proof identity contains invalid source path")
        result.append(ROOT / path)
    return result


def verification_text(commit: str, receipt_sha: str, witness_sha: str,
                      proof_file_sha: str, proof_internal_sha: str) -> bytes:
    text = f"""# JACKAL {VERSION} spacecraft certificate verification

Tag `{VERSION}` must resolve to merge commit `{commit}`.

Public verdict: CERTIFIED SAFE under the stated finite-burn ODE model, supplied input bounds, and machine-checked interval-certificate assumptions.

Pinned identities:

- receipt SHA-256: `{receipt_sha}`
- witness SHA-256: `{witness_sha}`
- proof identity file SHA-256: `{proof_file_sha}`
- proof identity internal digest: `{proof_internal_sha}`
- request digest: `03bcad618ad60114007c74a384eb8c9432e3755b817e74bd5bdc9bd1ba6df3e7`
- model: `jackal-spacecraft-finite-burn-ode-v2`
- epoch: `{VERSION}`
- nonce: `spacecraft-burn-v2-publication-20260824`

First run `shasum -a 256 -c SHA256SUMS`. Extract `{ARCHIVE_NAME}`, then invoke the bundled checker and outer verifier with the caller-pinned values above. The checker must emit one `ACCEPT theorem=spacecraft_burn_certified_safe status=formal-bounded` line, and the outer verifier must return `status: ACCEPT` with no reasons.

This theorem is conditional on the encoded ODE model and supplied bounds. It does not establish physical-model adequacy, input truth, omitted perturbations, actuator behavior, or source-to-native compiler correctness.
"""
    return text.encode("utf-8")


def build(staging: Path, output: Path, commit: str) -> dict[str, str]:
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise RuntimeError("merge commit must be 40 lowercase hex characters")
    output.mkdir(parents=True, exist_ok=False)
    receipt_bytes = (staging / RECEIPT_NAME).read_bytes()
    witness_bytes = (staging / WITNESS_NAME).read_bytes()
    receipt = json.loads(receipt_bytes)
    identity_bytes = IDENTITY.read_bytes()
    identity = json.loads(identity_bytes)
    binding = receipt["formal_checker"]
    if sha256(witness_bytes) != receipt["witness"]["sha256"]:
        raise RuntimeError("witness digest does not match receipt")
    if sha256(CHECKER.read_bytes()) != binding["checker_sha256"]:
        raise RuntimeError("checker digest does not match receipt")
    if sha256(identity_bytes) != binding["proof_identity_file_sha256"]:
        raise RuntimeError("proof identity file digest does not match receipt")
    if identity["identity_digest_sha256"] != binding["proof_identity_digest_sha256"]:
        raise RuntimeError("proof identity internal digest does not match receipt")

    prefix = f"jackal-spacecraft-burn-{VERSION}-verifier-macos-arm64"
    entries: dict[str, tuple[bytes, int]] = {
        f"{prefix}/bin/jackal_spacecraft_burn_check": (CHECKER.read_bytes(), 0o755),
        f"{prefix}/verifier/verify_receipt.py": ((ROOT / "spacecraft_burn_cert/verify_receipt.py").read_bytes(), 0o644),
        f"{prefix}/verifier/witness_codec.py": ((ROOT / "spacecraft_burn_cert/witness_codec.py").read_bytes(), 0o644),
        f"{prefix}/evidence/{PROOF_NAME}": (identity_bytes, 0o644),
        f"{prefix}/request_v2.json": ((ROOT / "spacecraft_burn_cert/request_v2.json").read_bytes(), 0o644),
        f"{prefix}/proofs/lean-toolchain": ((ROOT / "proofs/lean/lean-toolchain").read_bytes(), 0o644),
        f"{prefix}/proofs/lakefile.toml": ((ROOT / "proofs/lean/lakefile.toml").read_bytes(), 0o644),
    }
    for path in source_closure(identity):
        relative = path.relative_to(ROOT / "proofs/lean")
        entries[f"{prefix}/proofs/{relative.as_posix()}"] = (path.read_bytes(), 0o644)
    archive_bytes = deterministic_tar_gz(entries)

    assets = {
        WITNESS_NAME: witness_bytes,
        RECEIPT_NAME: receipt_bytes,
        PROOF_NAME: identity_bytes,
        "independent_verification_v2.json": (staging / "independent_verification_v2.json").read_bytes(),
        "instrument_validation_v2.json": (staging / "instrument_validation_v2.json").read_bytes(),
        "mutation_aba_v2.json": (staging / "mutation_aba_v2.json").read_bytes(),
        REVIEW_NAME: REVIEW.read_bytes(),
        "request_v2.json": (ROOT / "spacecraft_burn_cert/request_v2.json").read_bytes(),
        ARCHIVE_NAME: archive_bytes,
    }
    assets["VERIFICATION.md"] = verification_text(
        commit, sha256(receipt_bytes), sha256(witness_bytes), sha256(identity_bytes),
        identity["identity_digest_sha256"],
    )
    for name, data in assets.items():
        atomic_write(output / name, data)
    sums = "".join(f"{sha256(assets[name])}  {name}\n" for name in sorted(assets)).encode("ascii")
    atomic_write(output / "SHA256SUMS", sums)
    return {name: sha256(data) for name, data in assets.items()} | {"SHA256SUMS": sha256(sums)}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--staging-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--merge-commit", required=True)
    args = parser.parse_args(argv)
    result = build(args.staging_dir.resolve(), args.output_dir.resolve(), args.merge_commit)
    print(f"SPACECRAFT_V174_ASSETS_BUILT files={len(result)} output={args.output_dir.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
