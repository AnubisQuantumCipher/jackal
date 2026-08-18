#!/usr/bin/env python3
"""Verify plugin-wrapper tamper evidence against an externally anchored aggregate.

This manifest detects changes to named wrapper bytes.  It does not authenticate
an author: trust in an aggregate must come from a source Git revision or a
marketplace snapshot that the caller independently trusts.
"""

from __future__ import annotations

import contextlib
import hashlib
import hmac
import errno
import os
import re
import stat
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


_MANIFEST_LINE = re.compile(r"([0-9a-f]{64})  ([^\n]+)", re.ASCII)
MAX_INVENTORY_ENTRIES = 4096
MAX_INVENTORY_DEPTH = 32
MAX_INVENTORY_PATH_BYTES = 4096
MAX_MANIFEST_BYTES = 512 * 1024
MAX_PLUGIN_FILE_BYTES = 2 * 1024 * 1024
MAX_PLUGIN_TOTAL_BYTES = 16 * 1024 * 1024


class ManifestError(ValueError):
    """Base class for a refused plugin identity manifest."""


class ManifestFormatError(ManifestError):
    pass


class MissingFile(ManifestError):
    pass


class SymlinkFile(ManifestError):
    pass


class NonRegularFile(ManifestError):
    pass


class DigestMismatch(ManifestError):
    pass


class AggregateMismatch(ManifestError):
    pass


class UnexpectedEntry(ManifestError):
    pass


class UsageError(ManifestError):
    pass


@dataclass(frozen=True)
class ManifestRecord:
    path: str
    digest: str


def _validate_path(path: str) -> None:
    if not path or path.startswith("/") or "\\" in path:
        raise ManifestFormatError("path must be a relative POSIX path")
    if path[:1].isspace():
        raise ManifestFormatError("path must begin immediately after the two-space delimiter")
    components = path.split("/")
    if any(component in ("", ".", "..") for component in components):
        raise ManifestFormatError("path contains a non-canonical component")
    if any(ord(character) < 32 or ord(character) == 127 for character in path):
        raise ManifestFormatError("path contains an ASCII control character")
    try:
        encoded_size = len(path.encode("utf-8"))
    except UnicodeEncodeError as error:
        raise ManifestFormatError("path is not valid UTF-8") from error
    if len(components) > MAX_INVENTORY_DEPTH or encoded_size > MAX_INVENTORY_PATH_BYTES:
        raise ManifestFormatError("path exceeds depth or byte limit")


def _display_path(path: str) -> str:
    """Render manifest-controlled path text without terminal control effects."""
    return ascii(path)


def _validate_records(records: Iterable[ManifestRecord]) -> tuple[ManifestRecord, ...]:
    checked: list[ManifestRecord] = []
    prior_path = None
    for record in records:
        if len(checked) >= MAX_INVENTORY_ENTRIES:
            raise ManifestFormatError("records exceed count limit")
        if not isinstance(record, ManifestRecord):
            raise ManifestFormatError("record is not a ManifestRecord")
        if not re.fullmatch(r"[0-9a-f]{64}", record.digest, re.ASCII):
            raise ManifestFormatError("digest is not lowercase SHA-256 hex")
        _validate_path(record.path)
        if prior_path is not None and record.path <= prior_path:
            raise ManifestFormatError("paths must be strictly sorted")
        prior_path = record.path
        checked.append(record)
    return tuple(checked)


def _parse_manifest_bytes(raw: bytes) -> tuple[ManifestRecord, ...]:
    if not raw:
        raise ManifestFormatError("manifest is empty")
    if not raw.endswith(b"\n"):
        raise ManifestFormatError("manifest must end with one newline")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ManifestFormatError("manifest is not UTF-8") from error

    lines = text[:-1].split("\n")
    if len(lines) > MAX_INVENTORY_ENTRIES:
        raise ManifestFormatError("manifest exceeds record limit")
    records = []
    for line_number, line in enumerate(lines, start=1):
        match = _MANIFEST_LINE.fullmatch(line)
        if match is None:
            raise ManifestFormatError(f"malformed manifest line {line_number}")
        digest, path = match.groups()
        _validate_path(path)
        records.append(ManifestRecord(path=path, digest=digest))
    if not records:
        raise ManifestFormatError("manifest is empty")
    return _validate_records(records)


def parse_manifest(manifest_path: Path | str) -> tuple[ManifestRecord, ...]:
    """Parse one strictly canonical, newline-terminated identity manifest."""
    raw = _read_regular_file_nofollow(
        manifest_path, "manifest", byte_limit=MAX_MANIFEST_BYTES
    )
    return _parse_manifest_bytes(raw)


def _open_flags(*, directory: bool = False) -> int:
    flags = os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW
    if directory:
        flags |= os.O_DIRECTORY
    return flags


def _read_regular_file_nofollow(
    path: Path | str,
    subject: str,
    *,
    byte_limit: int = MAX_PLUGIN_FILE_BYTES,
) -> bytes:
    if byte_limit < 0:
        raise ManifestFormatError(f"invalid byte limit for {subject}")
    try:
        fd = os.open(os.fspath(path), _open_flags())
    except OSError as error:
        if error.errno == errno.ELOOP:
            raise SymlinkFile(f"symlink is not permitted for {subject}") from error
        raise MissingFile(f"cannot open {subject}: {error.strerror or 'open failed'}") from error
    try:
        return _read_open_regular_file(fd, subject, byte_limit=byte_limit)
    finally:
        os.close(fd)


def _read_open_regular_file(fd: int, subject: str, *, byte_limit: int) -> bytes:
    before = os.fstat(fd)
    if not stat.S_ISREG(before.st_mode):
        raise NonRegularFile(f"{subject} is not a regular file")
    if before.st_size > byte_limit:
        raise ManifestFormatError(f"{subject} exceeds byte limit")
    chunks = []
    count = 0
    os.lseek(fd, 0, os.SEEK_SET)
    while chunk := os.read(fd, min(64 * 1024, byte_limit - count + 1)):
        count += len(chunk)
        if count > byte_limit:
            raise ManifestFormatError(f"{subject} exceeds byte limit")
        chunks.append(chunk)
    after = os.fstat(fd)
    if _stable_file_signature(before) != _stable_file_signature(after) or count != after.st_size:
        raise ManifestFormatError(f"{subject} changed during read")
    return b"".join(chunks)


def _open_plugin_file(plugin_root: Path | str, relative_path: str) -> int:
    """Open a manifest file from a no-follow plugin-root directory descriptor."""
    root_fd = _open_plugin_root(plugin_root)
    try:
        return _open_plugin_file_at(root_fd, relative_path)
    finally:
        os.close(root_fd)


def _open_plugin_root(plugin_root: Path | str) -> int:
    try:
        fd = os.open(os.fspath(plugin_root), _open_flags(directory=True))
    except OSError as error:
        if error.errno == errno.ELOOP:
            raise SymlinkFile("plugin root must not be a symlink") from error
        raise MissingFile(f"cannot open plugin root: {error.strerror or 'open failed'}") from error

    if not stat.S_ISDIR(os.fstat(fd).st_mode):
        os.close(fd)
        raise NonRegularFile("plugin root is not a directory")
    return fd


def _open_plugin_file_at(root_fd: int, relative_path: str) -> int:
    fd = -1
    try:
        fd = os.dup(root_fd)
        components = relative_path.split("/")
        for index, component in enumerate(components):
            try:
                next_fd = os.open(
                    component,
                    _open_flags(directory=index < len(components) - 1),
                    dir_fd=fd,
                )
            except OSError as error:
                if error.errno == errno.ELOOP:
                    raise SymlinkFile(f"symlink is not permitted: {_display_path(relative_path)}") from error
                raise MissingFile(
                    f"cannot open {_display_path(relative_path)}: {error.strerror or 'open failed'}"
                ) from error
            os.close(fd)
            fd = next_fd
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise NonRegularFile(f"not a regular file: {_display_path(relative_path)}")
        return fd
    except OSError as error:
        if fd >= 0:
            with contextlib.suppress(OSError):
                os.close(fd)
        raise UnexpectedEntry("plugin file cannot be opened safely") from error
    except Exception:
        if fd >= 0:
            with contextlib.suppress(OSError):
                os.close(fd)
        raise

def _hash_open_file(fd: int, *, byte_limit: int) -> tuple[str, int]:
    """Hash a pre-opened descriptor, preserving the object verified by traversal."""
    if byte_limit < 0:
        raise UnexpectedEntry("invalid plugin file byte limit")
    before = os.fstat(fd)
    if before.st_size > byte_limit:
        raise UnexpectedEntry("plugin file exceeds byte limit")
    digest = hashlib.sha256()
    count = 0
    os.lseek(fd, 0, os.SEEK_SET)
    while chunk := os.read(fd, min(64 * 1024, byte_limit - count + 1)):
        count += len(chunk)
        if count > byte_limit:
            raise UnexpectedEntry("plugin file exceeds byte limit")
        digest.update(chunk)
    after = os.fstat(fd)
    if (
        before.st_dev,
        before.st_ino,
        before.st_mode,
        before.st_size,
        before.st_mtime_ns,
        before.st_ctime_ns,
    ) != (
        after.st_dev,
        after.st_ino,
        after.st_mode,
        after.st_size,
        after.st_mtime_ns,
        after.st_ctime_ns,
    ) or count != after.st_size:
        raise UnexpectedEntry("plugin file changed during hashing")
    return digest.hexdigest(), count


def _expected_directories(records: Iterable[ManifestRecord]) -> set[str]:
    directories: set[str] = set()
    for record in records:
        components = record.path.split("/")
        directories.update(
            "/".join(components[:index])
            for index in range(1, len(components))
        )
    return directories


def _verify_exact_inventory_at(
    root_fd: int, records: Iterable[ManifestRecord]
) -> None:
    checked = tuple(records)
    expected_files = {record.path for record in checked} | {"PLUGIN_IDENTITY.sha256"}
    expected_directories = _expected_directories(checked)
    seen_files: set[str] = set()
    seen_directories: set[str] = set()
    entry_count = 0
    stack: list[tuple[str, int, int]] = []
    try:
        stack.append(("", os.dup(root_fd), 0))
        while stack:
            prefix, directory_fd, depth = stack.pop()
            try:
                with os.scandir(directory_fd) as entries:
                    for entry in entries:
                        entry_count += 1
                        if entry_count > MAX_INVENTORY_ENTRIES:
                            raise UnexpectedEntry("plugin inventory exceeds entry limit")
                        name = entry.name
                        if not isinstance(name, str) or name in ("", ".", "..") or "/" in name:
                            raise UnexpectedEntry("plugin inventory contains an unsafe name")
                        relative = f"{prefix}/{name}" if prefix else name
                        if (
                            depth + 1 > MAX_INVENTORY_DEPTH
                            or len(os.fsencode(relative)) > MAX_INVENTORY_PATH_BYTES
                        ):
                            raise UnexpectedEntry("plugin inventory path exceeds limit")
                        try:
                            info = entry.stat(follow_symlinks=False)
                        except OSError as error:
                            raise UnexpectedEntry("plugin inventory changed during traversal") from error
                        if stat.S_ISDIR(info.st_mode):
                            if relative not in expected_directories:
                                raise UnexpectedEntry(
                                    f"unexpected plugin directory: {_display_path(relative)}"
                                )
                            try:
                                child_fd = os.open(
                                    name, _open_flags(directory=True), dir_fd=directory_fd
                                )
                            except OSError as error:
                                raise UnexpectedEntry(
                                    "plugin directory changed during traversal"
                                ) from error
                            try:
                                child_info = os.fstat(child_fd)
                            except OSError as error:
                                os.close(child_fd)
                                raise UnexpectedEntry(
                                    "plugin directory changed during traversal"
                                ) from error
                            if (
                                child_info.st_dev,
                                child_info.st_ino,
                                child_info.st_mode,
                            ) != (info.st_dev, info.st_ino, info.st_mode):
                                os.close(child_fd)
                                raise UnexpectedEntry(
                                    "plugin directory changed during traversal"
                                )
                            seen_directories.add(relative)
                            stack.append((relative, child_fd, depth + 1))
                        elif stat.S_ISREG(info.st_mode):
                            if relative not in expected_files:
                                raise UnexpectedEntry(
                                    f"unexpected plugin file: {_display_path(relative)}"
                                )
                            seen_files.add(relative)
                        else:
                            raise UnexpectedEntry(
                                f"plugin inventory contains a link or special entry: {_display_path(relative)}"
                            )
            finally:
                os.close(directory_fd)
        if seen_files != expected_files:
            missing = sorted(expected_files - seen_files)
            if missing:
                raise MissingFile(
                    f"missing plugin file: {_display_path(missing[0])}"
                )
            raise UnexpectedEntry("plugin inventory differs from identity manifest")
        if seen_directories != expected_directories:
            missing = sorted(expected_directories - seen_directories)
            if missing:
                raise MissingFile(
                    f"missing plugin directory: {_display_path(missing[0])}"
                )
            raise UnexpectedEntry("plugin inventory differs from identity manifest")
    except OSError as error:
        for unused_prefix, pending_fd, unused_depth in stack:
            with contextlib.suppress(OSError):
                os.close(pending_fd)
        raise UnexpectedEntry("plugin inventory cannot be traversed safely") from error
    except Exception:
        for unused_prefix, pending_fd, unused_depth in stack:
            with contextlib.suppress(OSError):
                os.close(pending_fd)
        raise


def _verify_exact_inventory(
    plugin_root: Path | str, records: Iterable[ManifestRecord]
) -> None:
    root_fd = _open_plugin_root(plugin_root)
    try:
        _verify_exact_inventory_at(root_fd, records)
    finally:
        os.close(root_fd)


def _stable_file_signature(info: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (
        info.st_dev,
        info.st_ino,
        info.st_mode,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )


def _require_plugin_path_identity(
    root_fd: int, relative_path: str, expected: os.stat_result
) -> None:
    current_fd = _open_plugin_file_at(root_fd, relative_path)
    try:
        current = os.fstat(current_fd)
    finally:
        os.close(current_fd)
    if _stable_file_signature(current) != _stable_file_signature(expected):
        raise UnexpectedEntry(
            f"plugin path changed after hashing: {_display_path(relative_path)}"
        )


def _require_supplied_manifest_bytes(
    manifest_path: Path | str,
    anchored_bytes: bytes,
    anchored_stat: os.stat_result,
) -> None:
    try:
        fd = os.open(os.fspath(manifest_path), _open_flags())
    except OSError as error:
        raise MissingFile("cannot safely open supplied manifest path") from error
    try:
        current = os.fstat(fd)
        if _stable_file_signature(current) == _stable_file_signature(anchored_stat):
            return
        supplied_bytes = _read_open_regular_file(
            fd, "supplied manifest", byte_limit=MAX_MANIFEST_BYTES
        )
    finally:
        os.close(fd)
    if supplied_bytes != anchored_bytes:
        raise UnexpectedEntry("supplied manifest bytes differ from the anchored plugin manifest")


def _open_plugin_directory_at(root_fd: int, relative_path: str) -> int:
    fd = -1
    try:
        fd = os.dup(root_fd)
        if relative_path:
            for component in relative_path.split("/"):
                next_fd = os.open(
                    component, _open_flags(directory=True), dir_fd=fd
                )
                os.close(fd)
                fd = next_fd
        if not stat.S_ISDIR(os.fstat(fd).st_mode):
            raise NonRegularFile("plugin inventory directory is not a directory")
        return fd
    except OSError as error:
        if fd >= 0:
            with contextlib.suppress(OSError):
                os.close(fd)
        raise UnexpectedEntry(
            "plugin inventory directory cannot be opened safely"
        ) from error
    except Exception:
        if fd >= 0:
            with contextlib.suppress(OSError):
                os.close(fd)
        raise


def _directory_signatures(
    root_fd: int, records: Iterable[ManifestRecord]
) -> dict[str, tuple[int, int, int, int, int, int]]:
    signatures: dict[str, tuple[int, int, int, int, int, int]] = {}
    for relative in [""] + sorted(_expected_directories(records)):
        directory_fd = _open_plugin_directory_at(root_fd, relative)
        try:
            signatures[relative] = _stable_file_signature(os.fstat(directory_fd))
        finally:
            os.close(directory_fd)
    return signatures


def verify_manifest(plugin_root: Path | str, manifest_path: Path | str) -> tuple[ManifestRecord, ...]:
    """Verify every named regular file and return canonical manifest records."""
    root_fd = _open_plugin_root(plugin_root)
    try:
        manifest_fd = _open_plugin_file_at(root_fd, "PLUGIN_IDENTITY.sha256")
        try:
            manifest_before = os.fstat(manifest_fd)
            manifest_raw = _read_open_regular_file(
                manifest_fd, "manifest", byte_limit=MAX_MANIFEST_BYTES
            )
        finally:
            os.close(manifest_fd)
        _require_supplied_manifest_bytes(
            manifest_path, manifest_raw, manifest_before
        )
        _require_plugin_path_identity(
            root_fd, "PLUGIN_IDENTITY.sha256", manifest_before
        )
        records = _parse_manifest_bytes(manifest_raw)
        _verify_exact_inventory_at(root_fd, records)
        directory_signatures = _directory_signatures(root_fd, records)
        remaining_bytes = MAX_PLUGIN_TOTAL_BYTES
        for record in records:
            fd = _open_plugin_file_at(root_fd, record.path)
            try:
                before = os.fstat(fd)
                actual, size = _hash_open_file(
                    fd, byte_limit=min(MAX_PLUGIN_FILE_BYTES, remaining_bytes)
                )
                after = os.fstat(fd)
                if (
                    _stable_file_signature(before) != _stable_file_signature(after)
                    or size != after.st_size
                ):
                    raise UnexpectedEntry(
                        f"plugin file changed after hashing: {_display_path(record.path)}"
                    )
                _require_plugin_path_identity(root_fd, record.path, after)
            finally:
                os.close(fd)
            remaining_bytes -= size
            if not hmac.compare_digest(actual, record.digest):
                raise DigestMismatch(f"digest mismatch: {_display_path(record.path)}")
        _verify_exact_inventory_at(root_fd, records)
        if _directory_signatures(root_fd, records) != directory_signatures:
            raise UnexpectedEntry("plugin inventory directory changed during verification")
        return records
    finally:
        os.close(root_fd)


def aggregate_digest(records: Iterable[ManifestRecord]) -> str:
    """Hash exact UTF-8 canonical manifest lines, including their final newline."""
    verified_records = _validate_records(records)
    canonical = "".join(
        f"{record.digest}  {record.path}\n" for record in verified_records
    ).encode("utf-8")
    if len(canonical) > MAX_MANIFEST_BYTES:
        raise ManifestFormatError("canonical records exceed manifest byte limit")
    return hashlib.sha256(canonical).hexdigest()


def require_expected_aggregate(records: Iterable[ManifestRecord], expected_hex: str) -> str:
    """Require a caller-pinned aggregate from an independently trusted anchor."""
    if not isinstance(expected_hex, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_hex, re.ASCII):
        raise ManifestFormatError("expected aggregate is not lowercase SHA-256 hex")
    actual = aggregate_digest(records)
    if not hmac.compare_digest(actual, expected_hex):
        raise AggregateMismatch("caller-pinned aggregate does not match")
    return actual


def _bounded_detail(error: Exception) -> str:
    detail = " ".join(str(error).splitlines()).strip() or "verification failed"
    return detail[:240]


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    try:
        if arguments:
            raise UsageError("no arguments are accepted")
        plugin_root = Path(__file__).resolve().parents[1]
        records = verify_manifest(plugin_root, plugin_root / "PLUGIN_IDENTITY.sha256")
        digest = aggregate_digest(records)
    except ManifestError as error:
        print(
            f"plugin_identity=refused reason={type(error).__name__} detail={_bounded_detail(error)}",
            file=sys.stderr,
        )
        return 1
    except Exception:
        print(
            "plugin_identity=refused reason=internal-error detail=unexpected verification failure",
            file=sys.stderr,
        )
        return 1
    print(f"plugin_identity=verified files={len(records)} aggregate_sha256={digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
