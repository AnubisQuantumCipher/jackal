#!/usr/bin/env python3
"""Install or reproduce the canonical v2 spacecraft release evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import tempfile
from pathlib import Path
from typing import Iterable, Sequence


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
ALLOWED_EXTRA = {"legacy-v1"}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_json(payload: dict) -> bytes:
    return (json.dumps(payload, sort_keys=True, indent=2) + "\n").encode("utf-8")


def expected_files(staging: Path, include_witness: bool = False) -> dict[str, bytes]:
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
    if include_witness:
        files["baseline_witness_v2.cert"] = witness_bytes
    sum_names = (*JSON_NAMES, MANIFEST)
    files[SUMS] = "".join(f"{sha256(files[name])}  {name}\n" for name in sum_names).encode("ascii")
    return files


def _lexical_absolute(path: Path | str) -> Path:
    return Path(os.path.abspath(os.fspath(path)))


def _resolved_parent_leaf(path: Path | str) -> Path:
    lexical = _lexical_absolute(path)
    if not lexical.name:
        raise RuntimeError("evidence output path has no filename")
    return lexical.parent.resolve(strict=False) / lexical.name


def prepare_output_path(
    path: Path | str, input_paths: Iterable[Path | str]
) -> Path:
    lexical = _lexical_absolute(path)
    resolved_parent = _resolved_parent_leaf(lexical)
    output_candidates = tuple(dict.fromkeys((lexical, resolved_parent)))
    output_identities: set[tuple[int, int]] = set()
    for candidate in output_candidates:
        try:
            metadata = os.lstat(candidate)
        except FileNotFoundError:
            continue
        except OSError as error:
            raise RuntimeError("evidence output path cannot be inspected") from error
        if stat.S_ISLNK(metadata.st_mode):
            raise RuntimeError("evidence output path must not be a symlink")
        if not stat.S_ISREG(metadata.st_mode):
            raise RuntimeError("evidence output path must be absent or regular")
        output_identities.add((metadata.st_dev, metadata.st_ino))

    for input_path in input_paths:
        input_lexical = _lexical_absolute(input_path)
        input_resolved_parent = _resolved_parent_leaf(input_lexical)
        if lexical == input_lexical or resolved_parent == input_resolved_parent:
            raise RuntimeError("evidence output must not alias a staged input path")
        for candidate in dict.fromkeys((input_lexical, input_resolved_parent)):
            try:
                metadata = os.stat(candidate)
            except FileNotFoundError:
                continue
            except OSError as error:
                raise RuntimeError("staged evidence input cannot be inspected") from error
            if (metadata.st_dev, metadata.st_ino) in output_identities:
                raise RuntimeError("evidence output must not share a staged input inode")
    return resolved_parent


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(
        path,
        os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_CLOEXEC", 0),
    )
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def atomic_write(
    path: Path | str,
    data: bytes,
    input_paths: Iterable[Path | str] = (),
) -> Path:
    inputs = tuple(input_paths)
    target = prepare_output_path(path, inputs)
    target.parent.mkdir(parents=True, exist_ok=True)
    target = prepare_output_path(target, inputs)
    descriptor: int | None = None
    temporary: Path | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{target.name}.tmp-", dir=target.parent
        )
        temporary = Path(temporary_name)
        os.fchmod(descriptor, 0o644)
        view = memoryview(data)
        offset = 0
        while offset < len(view):
            written = os.write(descriptor, view[offset:])
            if written <= 0:
                raise RuntimeError("zero-length evidence output write")
            offset += written
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = None
        os.replace(temporary, target)
        temporary = None
        _fsync_directory(target.parent)
        return target
    except BaseException:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
        raise


def install_or_check(
    staging: Path,
    check: bool,
    evidence_dir: Path | None = None,
    include_witness: bool = False,
) -> None:
    staging = _lexical_absolute(staging)
    destination_root = _lexical_absolute(EVIDENCE if evidence_dir is None else evidence_dir)
    if os.path.lexists(destination_root):
        metadata = os.lstat(destination_root)
        if stat.S_ISLNK(metadata.st_mode):
            raise RuntimeError("evidence output directory must not be a symlink")
        if not stat.S_ISDIR(metadata.st_mode):
            raise RuntimeError("evidence output root is not a directory")
    files = expected_files(staging, include_witness=include_witness)
    witness_destination = destination_root / "baseline_witness_v2.cert"
    if check and not include_witness and witness_destination.exists():
        files["baseline_witness_v2.cert"] = (staging / "baseline_witness_v2.cert").read_bytes()
    input_paths = tuple(staging / name for name in (
        "baseline_witness_v2.cert", *JSON_NAMES
    ))
    destinations = {
        name: prepare_output_path(destination_root / name, input_paths)
        for name in files
    }
    mismatches = []
    for name, expected in files.items():
        destination = destinations[name]
        if check:
            if not destination.is_file() or destination.read_bytes() != expected:
                mismatches.append(name)
        else:
            atomic_write(destination, expected, input_paths)
    if check and destination_root.is_dir():
        allowed = set(files) | ALLOWED_EXTRA
        for entry in sorted(destination_root.iterdir()):
            if entry.name not in allowed:
                mismatches.append(f"unexpected:{entry.name}")
    if mismatches:
        raise RuntimeError("evidence reproduction mismatch: " + ", ".join(mismatches))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--staging-dir", type=Path, required=True)
    parser.add_argument("--evidence-dir", type=Path)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--include-witness", action="store_true")
    args = parser.parse_args(argv)
    install_or_check(
        args.staging_dir, args.check, args.evidence_dir, args.include_witness
    )
    print("SPACECRAFT_EVIDENCE_REPRODUCED" if args.check else "SPACECRAFT_EVIDENCE_INSTALLED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
