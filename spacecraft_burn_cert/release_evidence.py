#!/usr/bin/env python3
"""Install or reproduce the canonical v2 spacecraft release evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
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
MAX_STAGED_JSON_BYTES = 16 * 1024 * 1024
MAX_STAGED_WITNESS_BYTES = 64 * 1024 * 1024
MAX_JSON_NESTING_DEPTH = 128
MAX_JSON_INTEGER_DIGITS = 128


class DuplicateJsonKey(ValueError):
    pass


def reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateJsonKey(key)
        result[key] = value
    return result


def reject_nonfinite_json(value: str) -> None:
    raise ValueError(f"non-finite JSON number: {value}")


def reject_fractional_json(_value: str) -> None:
    raise ValueError("fractional JSON numbers are not admitted")


def parse_bounded_json_integer(value: str) -> int:
    digits = value[1:] if value.startswith("-") else value
    if len(digits) > MAX_JSON_INTEGER_DIGITS:
        raise ValueError("JSON integer exceeds the evidence digit limit")
    return int(value)


def contains_unicode_surrogate(value: str) -> bool:
    return any("\ud800" <= character <= "\udfff" for character in value)


def strict_json_document(raw: bytes) -> dict:
    try:
        document = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=reject_duplicate_keys,
            parse_constant=reject_nonfinite_json,
            parse_float=reject_fractional_json,
            parse_int=parse_bounded_json_integer,
        )
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
        DuplicateJsonKey,
        OverflowError,
        RecursionError,
        ValueError,
    ) as error:
        raise RuntimeError("staged JSON is invalid") from error
    pending = [(document, 0)]
    try:
        while pending:
            value, depth = pending.pop()
            if type(value) is dict:
                if depth >= MAX_JSON_NESTING_DEPTH:
                    raise ValueError("JSON nesting exceeds the evidence limit")
                if any(contains_unicode_surrogate(key) for key in value):
                    raise ValueError("JSON strings contain Unicode surrogates")
                pending.extend((child, depth + 1) for child in value.values())
            elif type(value) is list:
                if depth >= MAX_JSON_NESTING_DEPTH:
                    raise ValueError("JSON nesting exceeds the evidence limit")
                pending.extend((child, depth + 1) for child in value)
            elif type(value) is str and contains_unicode_surrogate(value):
                raise ValueError("JSON strings contain Unicode surrogates")
            elif type(value) is float:
                raise ValueError("fractional JSON numbers are not admitted")
    except ValueError as error:
        raise RuntimeError("staged JSON is invalid") from error
    if type(document) is not dict:
        raise RuntimeError("staged JSON is invalid")
    return document


def read_regular_snapshot(path: Path, maximum_bytes: int) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    descriptor: int | None = None
    try:
        descriptor = os.open(path, flags)
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_size > maximum_bytes:
            raise RuntimeError("staged input is invalid")
        payload = bytearray()
        while len(payload) <= maximum_bytes:
            block = os.read(
                descriptor, min(1024 * 1024, maximum_bytes + 1 - len(payload))
            )
            if not block:
                break
            payload.extend(block)
        after = os.fstat(descriptor)
        stable = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
        if (
            len(payload) > maximum_bytes
            or len(payload) != before.st_size
            or any(getattr(before, field) != getattr(after, field) for field in stable)
        ):
            raise RuntimeError("staged input is invalid")
        return bytes(payload)
    except OSError as error:
        raise RuntimeError("staged input is invalid") from error
    finally:
        if descriptor is not None:
            os.close(descriptor)


def read_regular_snapshot_at(
    directory_descriptor: int, name: str, maximum_bytes: int
) -> bytes:
    if Path(name).name != name or name in {"", ".", ".."}:
        raise RuntimeError("staged input is invalid")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    descriptor: int | None = None
    try:
        descriptor = os.open(name, flags, dir_fd=directory_descriptor)
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_size > maximum_bytes:
            raise RuntimeError("staged input is invalid")
        payload = bytearray()
        while len(payload) <= maximum_bytes:
            block = os.read(
                descriptor, min(1024 * 1024, maximum_bytes + 1 - len(payload))
            )
            if not block:
                break
            payload.extend(block)
        after = os.fstat(descriptor)
        stable = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
        if (
            len(payload) > maximum_bytes
            or len(payload) != before.st_size
            or any(getattr(before, field) != getattr(after, field) for field in stable)
        ):
            raise RuntimeError("staged input is invalid")
        return bytes(payload)
    except OSError as error:
        raise RuntimeError("staged input is invalid") from error
    finally:
        if descriptor is not None:
            os.close(descriptor)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_json(payload: dict) -> bytes:
    return (
        json.dumps(payload, sort_keys=True, indent=2, allow_nan=False) + "\n"
    ).encode("utf-8")


def expected_files(staging: Path, include_witness: bool = False) -> dict[str, bytes]:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        directory_descriptor = os.open(staging, flags)
    except OSError as error:
        raise RuntimeError("staging root is invalid") from error
    try:
        root_before = os.fstat(directory_descriptor)
        if not stat.S_ISDIR(root_before.st_mode):
            raise RuntimeError("staging root is invalid")
        witness_bytes = read_regular_snapshot_at(
            directory_descriptor,
            "baseline_witness_v2.cert",
            MAX_STAGED_WITNESS_BYTES,
        )
        json_files = {
            name: read_regular_snapshot_at(
                directory_descriptor, name, MAX_STAGED_JSON_BYTES
            )
            for name in JSON_NAMES
        }
        root_after = os.fstat(directory_descriptor)
        stable_root = ("st_dev", "st_ino", "st_mtime_ns", "st_ctime_ns")
        if any(
            getattr(root_before, field) != getattr(root_after, field)
            for field in stable_root
        ):
            raise RuntimeError("staging root changed during snapshot")
        try:
            live_root = os.stat(staging, follow_symlinks=False)
        except OSError as error:
            raise RuntimeError("staging root changed during snapshot") from error
        if (live_root.st_dev, live_root.st_ino) != (
            root_before.st_dev,
            root_before.st_ino,
        ):
            raise RuntimeError("staging root changed during snapshot")
    finally:
        os.close(directory_descriptor)
    documents = {name: strict_json_document(raw) for name, raw in json_files.items()}
    receipt_bytes = json_files[JSON_NAMES[0]]
    receipt = documents[JSON_NAMES[0]]
    witness = receipt.get("witness")
    if (
        type(witness) is not dict
        or type(witness.get("sha256")) is not str
        or re.fullmatch(r"[0-9a-f]{64}", witness["sha256"]) is None
        or type(witness.get("byte_size")) is not int
        or witness["byte_size"] <= 0
        or type(witness.get("branch_count")) is not int
        or witness["branch_count"] <= 0
        or type(witness.get("tube_count")) is not int
        or witness["tube_count"] <= 0
        or type(witness.get("cutoff_cell_count")) is not int
        or witness["cutoff_cell_count"] <= 0
        or type(receipt.get("formal_checker")) is not dict
    ):
        raise RuntimeError("staged receipt witness binding is invalid")
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
    files = dict(json_files)
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
    witness_destination = destination_root / "baseline_witness_v2.cert"
    files = expected_files(
        staging,
        include_witness=(
            include_witness or (check and witness_destination.exists())
        ),
    )
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
            try:
                observed = read_regular_snapshot(destination, max(1, len(expected)))
            except RuntimeError:
                observed = None
            if observed != expected:
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
