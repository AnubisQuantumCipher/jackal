#!/opt/homebrew/bin/python3
"""Install or reproduce the canonical v2 spacecraft release evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Sequence


ROOT = Path(__file__).resolve().parent
EVIDENCE = ROOT / "evidence"
JSON_NAMES = (
    "baseline_receipt_v2.json",
    "independent_verification_v2.json",
    "instrument_validation_v2.json",
    "mutation_aba_v2.json",
)
MANIFEST = "baseline_witness_v2.manifest.json"
SUMS = "SHA256SUMS"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_json(payload: dict) -> bytes:
    return (json.dumps(payload, sort_keys=True, indent=2) + "\n").encode("utf-8")


def expected_files(staging: Path) -> dict[str, bytes]:
    witness_path = staging / "baseline_witness_v2.cert"
    receipt_path = staging / "baseline_receipt_v2.json"
    witness_bytes = witness_path.read_bytes()
    receipt_bytes = receipt_path.read_bytes()
    receipt = json.loads(receipt_bytes)
    witness = receipt["witness"]
    actual_digest = sha256(witness_bytes)
    if actual_digest != witness["sha256"] or len(witness_bytes) != witness["byte_size"]:
        raise RuntimeError("staged witness does not match receipt")
    manifest = {
        "schema": "spacecraft-finite-burn-witness-manifest-v2",
        "release_asset": "baseline_witness_v2.cert",
        "sha256": actual_digest,
        "byte_size": len(witness_bytes),
        "branch_count": witness["branch_count"],
        "tube_count": witness["tube_count"],
        "cutoff_cell_count": witness["cutoff_cell_count"],
        "receipt_sha256": sha256(receipt_bytes),
        "formal_checker": receipt["formal_checker"],
    }
    files = {name: (staging / name).read_bytes() for name in JSON_NAMES}
    files[MANIFEST] = canonical_json(manifest)
    sum_names = (*JSON_NAMES, MANIFEST)
    files[SUMS] = "".join(f"{sha256(files[name])}  {name}\n" for name in sum_names).encode("ascii")
    return files


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    with temporary.open("xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def install_or_check(staging: Path, check: bool) -> None:
    files = expected_files(staging.resolve())
    mismatches = []
    for name, expected in files.items():
        destination = EVIDENCE / name
        if check:
            if not destination.is_file() or destination.read_bytes() != expected:
                mismatches.append(name)
        else:
            atomic_write(destination, expected)
    if mismatches:
        raise RuntimeError("evidence reproduction mismatch: " + ", ".join(mismatches))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--staging-dir", type=Path, required=True)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    install_or_check(args.staging_dir, args.check)
    print("SPACECRAFT_EVIDENCE_REPRODUCED" if args.check else "SPACECRAFT_EVIDENCE_INSTALLED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
