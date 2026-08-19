#!/usr/bin/env python3
"""Install the one pinned JACKAL macOS arm64 runtime, fail closed."""

from __future__ import annotations

import argparse
import contextlib
import ctypes
import errno
import hashlib
import hmac
import json
import os
import platform
import re
import selectors
import signal
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
import unicodedata
import urllib.request
from pathlib import Path, PurePosixPath
from typing import Callable, Iterable, Mapping


EPOCH = "v1.7.0"
ASSET = "jackal-v1.7.0-macos-arm64.tar.gz"
URL = "https://github.com/AnubisQuantumCipher/jackal/releases/download/v1.7.0/jackal-v1.7.0-macos-arm64.tar.gz"
PACKAGE_SIZE = 118862060
PACKAGE_SHA256 = "21c7ede586f30a58772f321f7dbb36ab66213e199785489f99133710ac56096e"
EXTRACTED_SIZE = 416736385
SHA256SUMS_SHA256 = "f1f794ccd2ba331e6188840cfc089180cdcd744f23c1880f8364a81b230c1a28"
PACKAGE_DIRECTORY = "jackal-v1.7.0-macos-arm64"
MAX_ARCHIVE_MEMBERS = 8192
MAX_RUNTIME_RECORDS = MAX_ARCHIVE_MEMBERS
MAX_RUNTIME_ENTRIES = MAX_ARCHIVE_MEMBERS + 2
MAX_RUNTIME_DEPTH = 64
MAX_RUNTIME_PATH_BYTES = 4096
MAX_RUNTIME_MANIFEST_BYTES = 8 * 1024 * 1024
MAX_INSTALLED_METADATA_BYTES = 16 * 1024
DOWNLOAD_CHUNK_SIZE = 64 * 1024
NETWORK_TIMEOUT = 30.0
DOWNLOAD_TOTAL_TIMEOUT = 300.0
SELFTEST_TIMEOUT = 30.0
SELFTEST_OUTPUT_LIMIT = 64 * 1024
SNAPSHOT_BYTE_LIMIT = EXTRACTED_SIZE + 1024 * 1024
MAX_RUNTIME_FILE_BYTES = EXTRACTED_SIZE
MAX_RUNTIME_TOTAL_BYTES = SNAPSHOT_BYTE_LIMIT
RUNTIME_ENV_ALLOWLIST = ("JACKAL_HOME",)
FIXED_SYSTEM_PATH = "/usr/bin:/bin:/usr/sbin:/sbin"

_CHECKSUM_LINE = re.compile(r"([0-9a-f]{64})  \./([^\n]+)", re.ASCII)


class ProvisionError(RuntimeError):
    """A bounded, operator-facing provisioning refusal."""


class _LeaderAnchorLost(ProvisionError):
    pass


def default_runtime_target(home: Path | None = None) -> Path:
    root = Path.home() if home is None else Path(home)
    return root / "Library/Application Support/JACKAL/runtimes" / EPOCH


def default_locator_path(home: Path | None = None) -> Path:
    root = Path.home() if home is None else Path(home)
    return root / "Library/Application Support/JACKAL/codex-plugin/runtime.json"


def validate_host(system: str | None = None, machine: str | None = None) -> None:
    actual_system = platform.system() if system is None else system
    actual_machine = platform.machine() if machine is None else machine
    if actual_system != "Darwin" or actual_machine != "arm64":
        raise ProvisionError(f"unsupported host: {actual_system}/{actual_machine}; requires Darwin/arm64")


def runtime_subprocess_environment(
    environ: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Bind bare ``python3`` in the sealed launcher to this probed interpreter."""
    source = os.environ if environ is None else environ
    executable = Path(sys.executable)
    if not executable.is_absolute() or "\x00" in os.fspath(executable):
        raise ProvisionError("selected Python executable is not absolute")
    interpreter_directory = executable.parent
    directory_text = os.fspath(interpreter_directory)
    if not directory_text or ":" in directory_text or "\x00" in directory_text:
        raise ProvisionError("selected Python directory is unsafe for PATH")
    bare_python = interpreter_directory / "python3"
    try:
        selected_info = executable.stat()
        bare_info = bare_python.stat()
    except OSError as error:
        raise ProvisionError("selected Python directory has no matching python3") from error
    if (
        not stat.S_ISREG(selected_info.st_mode)
        or not stat.S_ISREG(bare_info.st_mode)
        or (selected_info.st_dev, selected_info.st_ino)
        != (bare_info.st_dev, bare_info.st_ino)
        or not os.access(bare_python, os.X_OK)
    ):
        raise ProvisionError("selected Python directory has no matching python3")

    result = {"PATH": f"{directory_text}:{FIXED_SYSTEM_PATH}"}
    for name in RUNTIME_ENV_ALLOWLIST:
        if name not in source:
            continue
        value = source[name]
        if not isinstance(value, str) or "\x00" in value:
            raise ProvisionError(f"invalid allowlisted runtime environment: {name}")
        result[name] = value
    return result


def _valid_digest(digest: str) -> bool:
    return isinstance(digest, str) and re.fullmatch(r"[0-9a-f]{64}", digest, re.ASCII) is not None


@contextlib.contextmanager
def _hard_download_deadline(total_timeout: float):
    try:
        previous_timer = signal.getitimer(signal.ITIMER_REAL)
        previous_handler = signal.getsignal(signal.SIGALRM)
    except (AttributeError, OSError, ValueError) as error:
        raise ProvisionError("download deadline control is unavailable") from error
    if previous_timer != (0.0, 0.0):
        raise ProvisionError("download deadline timer is already in use")

    def deadline_expired(unused_signum, unused_frame) -> None:
        raise ProvisionError("download exceeded monotonic total deadline")

    try:
        signal.signal(signal.SIGALRM, deadline_expired)
    except (OSError, ValueError) as error:
        raise ProvisionError("download deadline control is unavailable") from error
    try:
        signal.setitimer(signal.ITIMER_REAL, total_timeout)
    except (OSError, ValueError) as error:
        try:
            signal.signal(signal.SIGALRM, previous_handler)
        except (OSError, ValueError):
            pass
        raise ProvisionError("download deadline control is unavailable") from error
    try:
        yield
    finally:
        try:
            signal.setitimer(signal.ITIMER_REAL, 0.0)
            signal.signal(signal.SIGALRM, previous_handler)
        except (OSError, ValueError) as error:
            raise ProvisionError("download deadline control is unavailable") from error


def stream_download(
    url: str,
    output: Path | str,
    *,
    expected_size: int = PACKAGE_SIZE,
    expected_sha256: str = PACKAGE_SHA256,
    opener: Callable = urllib.request.urlopen,
    chunk_size: int = DOWNLOAD_CHUNK_SIZE,
    network_timeout: float = NETWORK_TIMEOUT,
    total_timeout: float = DOWNLOAD_TOTAL_TIMEOUT,
) -> Path:
    """Stream a pinned asset with hard byte and monotonic elapsed-time ceilings."""
    destination = Path(output)
    if (
        expected_size < 0
        or chunk_size <= 0
        or network_timeout <= 0
        or total_timeout <= 0
        or not _valid_digest(expected_sha256)
    ):
        raise ProvisionError("invalid download expectation")
    deadline = time.monotonic() + total_timeout

    def require_deadline() -> None:
        if time.monotonic() >= deadline:
            raise ProvisionError("download exceeded monotonic total deadline")

    digest = hashlib.sha256()
    count = 0
    created = False
    try:
        with _hard_download_deadline(total_timeout):
            try:
                handle = destination.open("xb")
                created = True
            except OSError as error:
                raise ProvisionError("download destination already exists or is unavailable") from error
            with handle:
                require_deadline()
                with opener(url, timeout=min(network_timeout, total_timeout)) as response:
                    require_deadline()
                    declared = response.headers.get("Content-Length")
                    if declared is not None:
                        try:
                            declared_size = int(declared)
                        except (TypeError, ValueError) as error:
                            raise ProvisionError("invalid Content-Length") from error
                        if declared_size != expected_size:
                            raise ProvisionError("Content-Length does not match pinned size")
                    while True:
                        require_deadline()
                        chunk = response.read(chunk_size)
                        require_deadline()
                        if not chunk:
                            break
                        if not isinstance(chunk, bytes):
                            raise ProvisionError("download returned non-byte content")
                        count += len(chunk)
                        if count > expected_size:
                            raise ProvisionError("download exceeds pinned size")
                        digest.update(chunk)
                        handle.write(chunk)
                require_deadline()
                handle.flush()
                os.fsync(handle.fileno())
                require_deadline()
        if count != expected_size:
            raise ProvisionError("download size does not match pin")
        if not hmac.compare_digest(digest.hexdigest(), expected_sha256):
            raise ProvisionError("download SHA-256 does not match pin")
        return destination
    except Exception as error:
        if created:
            try:
                destination.unlink(missing_ok=True)
            except OSError:
                pass
        if isinstance(error, ProvisionError):
            raise
        raise ProvisionError("download failed") from error


def _register_aliases(parts: tuple[str, ...], aliases: dict[str, str], subject: str) -> None:
    canonical: list[str] = []
    original: list[str] = []
    for part in parts:
        canonical.append(unicodedata.normalize("NFD", part).casefold())
        original.append(part)
        key = "/".join(canonical)
        presented = "/".join(original)
        prior = aliases.get(key)
        if prior is not None and prior != presented:
            raise ProvisionError(f"{subject} contains a case or Unicode alias collision")
        aliases[key] = presented


def _canonical_archive_name(name: str) -> tuple[str, ...]:
    if not name or name.startswith("/") or "\\" in name or "\x00" in name:
        raise ProvisionError("archive member path is not canonical relative POSIX")
    parts = name.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise ProvisionError("archive member path has ambiguous component")
    if any(ord(character) < 32 or ord(character) == 127 for character in name):
        raise ProvisionError("archive member path has control character")
    pure = PurePosixPath(name)
    if pure.is_absolute() or tuple(pure.parts) != tuple(parts):
        raise ProvisionError("archive member path is not canonical")
    return tuple(parts)


def safe_members(
    archive: tarfile.TarFile,
    *,
    expected_extracted_size: int,
    expected_top_level: str | None = None,
    max_members: int = MAX_ARCHIVE_MEMBERS,
) -> tuple[tarfile.TarInfo, ...]:
    """Freeze and validate the complete set of manually extractable members."""
    if expected_extracted_size < 0 or max_members < 0:
        raise ProvisionError("invalid archive limits")
    members = tuple(archive.getmembers())
    if not members or len(members) > max_members:
        raise ProvisionError("archive member count exceeds limit or is empty")
    names: set[str] = set()
    aliases: dict[str, str] = {}
    top_levels: set[str] = set()
    total = 0
    top_level_directory = False
    for member in members:
        parts = _canonical_archive_name(member.name)
        _register_aliases(parts, aliases, "archive")
        if member.name in names:
            raise ProvisionError("archive contains duplicate member path")
        names.add(member.name)
        top_levels.add(parts[0])
        if not (member.isdir() or member.isreg()):
            raise ProvisionError("archive contains link or special entry")
        if member.isdir() and len(parts) == 1:
            top_level_directory = True
        if member.isreg():
            if member.size < 0:
                raise ProvisionError("archive member has negative size")
            total += member.size
            if total > expected_extracted_size:
                raise ProvisionError("archive extracted bytes exceed pinned extracted-size limit")
    if expected_top_level is not None:
        _canonical_archive_name(expected_top_level)
        if top_levels != {expected_top_level} or not top_level_directory:
            raise ProvisionError("archive must contain exactly the pinned top-level package directory")
    elif len(top_levels) != 1:
        raise ProvisionError("archive must contain exactly one top-level directory")
    if total != expected_extracted_size:
        raise ProvisionError("archive extracted bytes do not match the pinned extracted size")
    return members


def _directory_flags() -> int:
    return os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW | os.O_DIRECTORY


def _file_read_flags() -> int:
    return os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW


def _open_directory_chain(root_fd: int, components: Iterable[str], *, create: bool) -> int:
    current = os.dup(root_fd)
    try:
        for component in components:
            try:
                next_fd = os.open(component, _directory_flags(), dir_fd=current)
            except FileNotFoundError:
                if not create:
                    raise
                os.mkdir(component, 0o755, dir_fd=current)
                next_fd = os.open(component, _directory_flags(), dir_fd=current)
            os.close(current)
            current = next_fd
        return current
    except Exception:
        os.close(current)
        raise


def _extract_members(
    archive: tarfile.TarFile,
    members: Iterable[tarfile.TarInfo],
    destination: Path | str,
) -> None:
    """Extract validated members with no-follow directory-descriptor traversal."""
    root = Path(destination)
    try:
        root.mkdir(mode=0o700, parents=False, exist_ok=True)
        root_fd = os.open(root, _directory_flags())
    except OSError as error:
        raise ProvisionError("extraction root is not a safe directory") from error
    try:
        for member in members:
            parts = _canonical_archive_name(member.name)
            if member.isdir():
                directory_fd = _open_directory_chain(root_fd, parts, create=True)
                os.close(directory_fd)
                continue
            parent_fd = _open_directory_chain(root_fd, parts[:-1], create=True)
            try:
                flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
                fd = os.open(parts[-1], flags, member.mode & 0o777, dir_fd=parent_fd)
                try:
                    source = archive.extractfile(member)
                    if source is None:
                        raise ProvisionError("regular archive member has no content")
                    remaining = member.size
                    while remaining:
                        chunk = source.read(min(DOWNLOAD_CHUNK_SIZE, remaining))
                        if not chunk:
                            raise ProvisionError("archive member ended early")
                        view = memoryview(chunk)
                        while view:
                            written = os.write(fd, view)
                            if written <= 0:
                                raise ProvisionError("archive member write made no progress")
                            view = view[written:]
                        remaining -= len(chunk)
                    if source.read(1):
                        raise ProvisionError("archive member exceeds declared size")
                    os.fchmod(fd, member.mode & 0o777)
                    os.fsync(fd)
                finally:
                    os.close(fd)
            except (FileExistsError, NotADirectoryError, OSError) as error:
                if isinstance(error, ProvisionError):
                    raise
                raise ProvisionError("archive extraction encountered an unsafe path") from error
            finally:
                os.close(parent_fd)
    except ProvisionError:
        raise
    except OSError as error:
        raise ProvisionError("archive extraction encountered an unsafe path") from error
    finally:
        os.close(root_fd)


def _file_signature(info: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (
        info.st_dev,
        info.st_ino,
        info.st_mode,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )


def _read_fd(fd: int, *, byte_limit: int) -> bytes:
    if byte_limit < 0:
        raise ProvisionError("invalid file read byte limit")
    before = os.fstat(fd)
    if before.st_size > byte_limit:
        raise ProvisionError("file exceeds read byte limit")
    chunks: list[bytes] = []
    count = 0
    os.lseek(fd, 0, os.SEEK_SET)
    while True:
        chunk = os.read(fd, min(DOWNLOAD_CHUNK_SIZE, byte_limit - count + 1))
        if not chunk:
            break
        count += len(chunk)
        if count > byte_limit:
            raise ProvisionError("file exceeds read byte limit")
        chunks.append(chunk)
    after = os.fstat(fd)
    if _file_signature(before) != _file_signature(after) or count != after.st_size:
        raise ProvisionError("file changed during bounded read")
    return b"".join(chunks)


def _hash_fd(fd: int, *, byte_limit: int | None = None) -> str:
    before = os.fstat(fd)
    limit = before.st_size if byte_limit is None else byte_limit
    if limit < 0 or before.st_size > limit:
        raise ProvisionError("file exceeds hash byte limit")
    digest = hashlib.sha256()
    count = 0
    os.lseek(fd, 0, os.SEEK_SET)
    while chunk := os.read(fd, min(DOWNLOAD_CHUNK_SIZE, limit - count + 1)):
        count += len(chunk)
        if count > limit:
            raise ProvisionError("file exceeds hash byte limit")
        digest.update(chunk)
    after = os.fstat(fd)
    if _file_signature(before) != _file_signature(after) or count != after.st_size:
        raise ProvisionError("file changed during verification")
    return digest.hexdigest()


def _open_regular_at(root_fd: int, relative_path: str) -> int:
    parts = relative_path.split("/")
    parent_fd = _open_directory_chain(root_fd, parts[:-1], create=False)
    try:
        try:
            fd = os.open(parts[-1], _file_read_flags(), dir_fd=parent_fd)
        except OSError as error:
            raise ProvisionError(f"cannot safely open package file: {relative_path!r}") from error
    finally:
        os.close(parent_fd)
    if not stat.S_ISREG(os.fstat(fd).st_mode):
        os.close(fd)
        raise ProvisionError(f"package path is not a regular file: {relative_path!r}")
    return fd


def _validate_checksum_path(raw: str) -> str:
    if not raw or raw.startswith("/") or "\\" in raw:
        raise ProvisionError("checksum path is unsafe")
    parts = raw.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise ProvisionError("checksum path is not canonical")
    if any(ord(character) < 32 or ord(character) == 127 for character in raw):
        raise ProvisionError("checksum path contains control character")
    try:
        encoded_size = len(raw.encode("utf-8"))
    except UnicodeEncodeError as error:
        raise ProvisionError("checksum path is not valid UTF-8") from error
    if len(parts) > MAX_RUNTIME_DEPTH or encoded_size > MAX_RUNTIME_PATH_BYTES:
        raise ProvisionError("checksum path exceeds depth or byte limit")
    return raw


def _require_path_identity(root_fd: int, relative: str, verified_stat: os.stat_result) -> None:
    current_fd = _open_regular_at(root_fd, relative)
    try:
        current_stat = os.fstat(current_fd)
    finally:
        os.close(current_fd)
    if _file_signature(current_stat) != _file_signature(verified_stat):
        raise ProvisionError(f"package path changed during verification: {relative!r}")


def _verify_exact_inventory(root_fd: int, expected_files: set[str]) -> None:
    seen: set[str] = set()
    seen_directories: set[str] = set()
    aliases: dict[str, str] = {}
    allowed = set(expected_files) | {"SHA256SUMS"}
    allowed.add(".jackal-package.json")
    expected_directories: set[str] = set()
    for relative in expected_files:
        parts = relative.split("/")
        expected_directories.update("/".join(parts[:index]) for index in range(1, len(parts)))
    entry_count = 0
    stack: list[tuple[str, int, int]] = [("", os.dup(root_fd), 0)]
    try:
        while stack:
            prefix, directory_fd, depth = stack.pop()
            try:
                with os.scandir(directory_fd) as entries:
                    for entry in entries:
                        entry_count += 1
                        if entry_count > MAX_RUNTIME_ENTRIES:
                            raise ProvisionError("runtime inventory exceeds entry limit")
                        name = entry.name
                        if not isinstance(name, str) or name in ("", ".", "..") or "/" in name:
                            raise ProvisionError("runtime inventory contains an unsafe name")
                        relative = f"{prefix}/{name}" if prefix else name
                        try:
                            path_bytes = len(relative.encode("utf-8"))
                        except UnicodeEncodeError as error:
                            raise ProvisionError("runtime inventory name is not UTF-8") from error
                        if depth + 1 > MAX_RUNTIME_DEPTH or path_bytes > MAX_RUNTIME_PATH_BYTES:
                            raise ProvisionError("runtime inventory path exceeds depth or byte limit")
                        parts = tuple(relative.split("/"))
                        _register_aliases(parts, aliases, "runtime inventory")
                        try:
                            info = entry.stat(follow_symlinks=False)
                        except OSError as error:
                            raise ProvisionError("runtime inventory changed during traversal") from error
                        if stat.S_ISDIR(info.st_mode):
                            if relative not in expected_directories:
                                raise ProvisionError("runtime directories differ from the pinned checksum inventory")
                            try:
                                child_fd = os.open(
                                    name, _directory_flags(), dir_fd=directory_fd
                                )
                            except OSError as error:
                                raise ProvisionError("runtime directory changed during traversal") from error
                            try:
                                child_info = os.fstat(child_fd)
                            except OSError as error:
                                os.close(child_fd)
                                raise ProvisionError(
                                    "runtime directory changed during traversal"
                                ) from error
                            if (
                                child_info.st_dev,
                                child_info.st_ino,
                                child_info.st_mode,
                            ) != (info.st_dev, info.st_ino, info.st_mode):
                                os.close(child_fd)
                                raise ProvisionError("runtime directory changed during traversal")
                            seen_directories.add(relative)
                            stack.append((relative, child_fd, depth + 1))
                        elif stat.S_ISREG(info.st_mode):
                            if relative not in allowed:
                                raise ProvisionError("runtime inventory contains an unlisted file")
                            seen.add(relative)
                        else:
                            raise ProvisionError("runtime inventory contains a symlink or special entry")
            finally:
                os.close(directory_fd)
    except Exception as error:
        for unused_prefix, pending_fd, unused_depth in stack:
            try:
                os.close(pending_fd)
            except OSError:
                pass
        if isinstance(error, ProvisionError):
            raise
        if isinstance(error, OSError):
            raise ProvisionError("runtime inventory cannot be traversed safely") from error
        raise
    required = set(expected_files) | {"SHA256SUMS"}
    if ".jackal-package.json" in seen:
        required.add(".jackal-package.json")
    if seen != required:
        raise ProvisionError("runtime inventory differs from the pinned checksum inventory")
    if seen_directories != expected_directories:
        raise ProvisionError("runtime directories differ from the pinned checksum inventory")


def _runtime_directory_signatures(
    root_fd: int, expected_files: set[str]
) -> dict[str, tuple[int, int, int, int, int, int]]:
    directories = {""}
    for relative in expected_files:
        parts = relative.split("/")
        directories.update("/".join(parts[:index]) for index in range(1, len(parts)))
    signatures: dict[str, tuple[int, int, int, int, int, int]] = {}
    for relative in sorted(directories):
        directory_fd = _open_directory_chain(
            root_fd, () if not relative else relative.split("/"), create=False
        )
        try:
            signatures[relative] = _file_signature(os.fstat(directory_fd))
        finally:
            os.close(directory_fd)
    return signatures


def verify_sha256sums(
    runtime: Path | str,
    *,
    expected_manifest_sha256: str | None = None,
) -> dict[str, str]:
    """Verify every canonical `./path` SHA256SUMS row through open descriptors."""
    root = Path(runtime)
    try:
        root_fd = os.open(root, _directory_flags())
    except OSError as error:
        raise ProvisionError("runtime root is not a safe directory") from error
    try:
        manifest_fd = _open_regular_at(root_fd, "SHA256SUMS")
        try:
            raw = _read_fd(manifest_fd, byte_limit=MAX_RUNTIME_MANIFEST_BYTES)
            manifest_stat = os.fstat(manifest_fd)
        finally:
            os.close(manifest_fd)
        _require_path_identity(root_fd, "SHA256SUMS", manifest_stat)
        if not raw or not raw.endswith(b"\n"):
            raise ProvisionError("SHA256SUMS must be nonempty and newline terminated")
        if expected_manifest_sha256 is not None:
            if not _valid_digest(expected_manifest_sha256):
                raise ProvisionError("invalid expected SHA256SUMS digest")
            if not hmac.compare_digest(hashlib.sha256(raw).hexdigest(), expected_manifest_sha256):
                raise ProvisionError("SHA256SUMS does not match the wrapper-side release pin")
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as error:
            raise ProvisionError("SHA256SUMS is not UTF-8") from error
        lines = text[:-1].split("\n")
        if len(lines) > MAX_RUNTIME_RECORDS:
            raise ProvisionError("SHA256SUMS exceeds record limit")
        records: dict[str, str] = {}
        aliases: dict[str, str] = {}
        previous: str | None = None
        for number, line in enumerate(lines, start=1):
            match = _CHECKSUM_LINE.fullmatch(line)
            if match is None:
                raise ProvisionError(f"malformed SHA256SUMS line {number}")
            expected, relative = match.groups()
            relative = _validate_checksum_path(relative)
            _register_aliases(tuple(relative.split("/")), aliases, "SHA256SUMS")
            if relative in records:
                raise ProvisionError("duplicate SHA256SUMS path")
            if previous is not None and relative <= previous:
                raise ProvisionError("SHA256SUMS paths are not strictly sorted")
            previous = relative
            records[relative] = expected
        if not records:
            raise ProvisionError("SHA256SUMS is empty")
        _verify_exact_inventory(root_fd, set(records))
        directory_signatures = _runtime_directory_signatures(root_fd, set(records))
        remaining_bytes = MAX_RUNTIME_TOTAL_BYTES
        for relative, expected in records.items():
            fd = _open_regular_at(root_fd, relative)
            try:
                before = os.fstat(fd)
                limit = min(MAX_RUNTIME_FILE_BYTES, remaining_bytes)
                if before.st_size > limit:
                    raise ProvisionError(f"package file exceeds byte limit: {relative!r}")
                actual = _hash_fd(fd, byte_limit=limit)
                verified_stat = os.fstat(fd)
                if _file_signature(before) != _file_signature(verified_stat):
                    raise ProvisionError(f"package file changed after hashing: {relative!r}")
            finally:
                os.close(fd)
            remaining_bytes -= verified_stat.st_size
            _require_path_identity(root_fd, relative, verified_stat)
            if not hmac.compare_digest(actual, expected):
                raise ProvisionError(f"package checksum mismatch: {relative!r}")
        _verify_exact_inventory(root_fd, set(records))
        if _runtime_directory_signatures(root_fd, set(records)) != directory_signatures:
            raise ProvisionError("runtime directory changed during verification")
        return records
    finally:
        os.close(root_fd)


def _process_group_exists(
    process_group: int,
    kill_group: Callable,
    *,
    permission_quiescent: Callable[[], bool] | None = None,
) -> bool:
    try:
        kill_group(process_group, 0)
        return True
    except ProcessLookupError:
        return False
    except OSError as error:
        if error.errno == errno.ESRCH:
            return False
        if error.errno == errno.EPERM:
            if permission_quiescent is not None and permission_quiescent():
                return False
            raise ProvisionError(
                "permission denied inspecting selftest process group"
            ) from error
        raise ProvisionError("cannot inspect selftest process group") from error


def _cleanup_process_group(
    process_group: int,
    kill_group: Callable = os.killpg,
    *,
    quiescent_check: Callable[[], bool] | None = None,
) -> None:
    def independently_quiescent() -> bool:
        return quiescent_check is not None and quiescent_check()

    def bounded_permission_quiescence() -> bool:
        if quiescent_check is None:
            return False
        deadline = time.monotonic() + 0.2
        while True:
            if independently_quiescent():
                return True
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            time.sleep(min(0.01, remaining))

    if independently_quiescent():
        return
    try:
        kill_group(process_group, signal.SIGTERM)
    except ProcessLookupError:
        return
    except OSError as error:
        if error.errno == errno.ESRCH:
            return
        if error.errno == errno.EPERM:
            if bounded_permission_quiescence():
                return
            raise ProvisionError(
                "permission denied terminating selftest process group"
            ) from error
        raise ProvisionError("cannot terminate selftest process group") from error
    deadline = time.monotonic() + 0.2
    while time.monotonic() < deadline:
        if independently_quiescent():
            return
        if not _process_group_exists(
            process_group,
            kill_group,
            permission_quiescent=bounded_permission_quiescence,
        ):
            return
        time.sleep(0.01)
    if independently_quiescent():
        return
    try:
        kill_group(process_group, signal.SIGKILL)
    except ProcessLookupError:
        return
    except OSError as error:
        if error.errno == errno.ESRCH:
            return
        if error.errno == errno.EPERM:
            if bounded_permission_quiescence():
                return
            raise ProvisionError(
                "permission denied killing selftest process group"
            ) from error
        raise ProvisionError("cannot kill surviving selftest process group") from error


def _terminate_process_group(process: subprocess.Popen, kill_group: Callable = os.killpg) -> None:
    try:
        _cleanup_process_group(process.pid, kill_group)
    finally:
        try:
            process.wait(timeout=0.5)
        except subprocess.TimeoutExpired:
            pass


def _leader_exited_without_reaping(pid: int, waitid_func: Callable) -> bool:
    try:
        result = waitid_func(
            os.P_PID,
            pid,
            os.WEXITED | os.WNOHANG | os.WNOWAIT,
        )
    except ChildProcessError as error:
        raise _LeaderAnchorLost("selftest leader was reaped before process-group cleanup") from error
    return result is not None and getattr(result, "si_pid", pid) == pid


def _group_observation_is_quiescent(
    output: bytes | bytearray, process_group: int,
) -> bool:
    try:
        members = []
        for line in bytes(output).decode("ascii").splitlines():
            fields = line.split()
            if len(fields) != 2 or not fields[0].isdigit():
                raise ValueError
            members.append((int(fields[0]), fields[1]))
    except (TypeError, UnicodeDecodeError, ValueError) as error:
        raise ProvisionError("process-group observation output is invalid") from error
    return (
        bool(members)
        and any(pid == process_group for pid, unused_state in members)
        and all(state.startswith("Z") for unused_pid, state in members)
    )


def _exited_group_has_only_zombie_members(
    process_group: int,
    *,
    output_limit: int = 64 * 1024,
    timeout: float = 0.5,
) -> bool:
    """Affirm that the retained leader and every observed member are zombies."""
    if process_group <= 0 or output_limit < 1 or timeout <= 0:
        raise ProvisionError("invalid process-group observation bounds")
    try:
        observer = subprocess.Popen(
            ["/bin/ps", "-o", "pid=,state=", "-g", str(process_group)],
            env={"PATH": FIXED_SYSTEM_PATH},
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            close_fds=True,
        )
    except OSError as error:
        raise ProvisionError("cannot inspect completed selftest process group") from error
    if observer.stdout is None:
        observer.kill()
        observer.wait()
        raise ProvisionError("process-group observer pipe is unavailable")
    selector: selectors.BaseSelector | None = None
    output = bytearray()
    deadline = time.monotonic() + timeout
    try:
        try:
            selector = selectors.DefaultSelector()
        except OSError as error:
            raise ProvisionError("process-group observer setup failed") from error
        selector.register(observer.stdout, selectors.EVENT_READ)
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ProvisionError("process-group observation timed out")
            for key, unused in selector.select(min(remaining, 0.05)):
                allowance = output_limit - len(output) + 1
                chunk = os.read(key.fd, min(DOWNLOAD_CHUNK_SIZE, max(1, allowance)))
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                output.extend(chunk)
                if len(output) > output_limit:
                    raise ProvisionError("process-group observation exceeds output limit")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ProvisionError("process-group observation timed out")
        observer_return_code = observer.wait(timeout=remaining)
        if observer_return_code not in (0, 1):
            raise ProvisionError("process-group observation refused")
    except Exception:
        if observer.poll() is None:
            observer.terminate()
            try:
                observer.wait(timeout=0.1)
            except subprocess.TimeoutExpired:
                observer.kill()
                try:
                    observer.wait(timeout=0.1)
                except subprocess.TimeoutExpired as error:
                    raise ProvisionError(
                        "process-group observer did not exit after bounded cleanup"
                    ) from error
        raise
    finally:
        if selector is not None:
            selector.close()
        observer.stdout.close()
    if observer_return_code == 1 and not output:
        return False
    return _group_observation_is_quiescent(output, process_group)


def _cleanup_completed_process_group(
    process_group: int,
    cleanup_group: Callable,
    kill_group: Callable,
) -> None:
    def independently_quiescent() -> bool:
        try:
            return _exited_group_has_only_zombie_members(process_group)
        except ProvisionError:
            return False

    if independently_quiescent():
        return
    cleanup_group(
        process_group,
        kill_group,
        quiescent_check=independently_quiescent,
    )


def _run_selftest(
    command: list[str],
    *,
    timeout: float,
    output_limit: int,
    popen_factory: Callable | None = None,
    kill_group: Callable = os.killpg,
    waitid_func: Callable | None = None,
    cleanup_group: Callable | None = None,
) -> subprocess.CompletedProcess:
    if timeout <= 0 or output_limit < 1:
        raise ProvisionError("invalid selftest bounds")
    factory = subprocess.Popen if popen_factory is None else popen_factory
    observe_exit = os.waitid if waitid_func is None else waitid_func
    cleanup = _cleanup_process_group if cleanup_group is None else cleanup_group
    try:
        process = factory(
            command,
            env=runtime_subprocess_environment(),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
            close_fds=True,
        )
    except OSError as error:
        raise ProvisionError("runtime selftest failed to start") from error
    selector: selectors.BaseSelector | None = None
    stdout = bytearray()
    stderr = bytearray()
    streams = ((process.stdout, stdout), (process.stderr, stderr))
    try:
        try:
            selector = selectors.DefaultSelector()
        except OSError as error:
            raise ProvisionError("runtime selftest monitor setup failed") from error
        for stream, sink in streams:
            if stream is None:
                raise ProvisionError("runtime selftest pipes are unavailable")
            selector.register(stream, selectors.EVENT_READ, sink)
        deadline = time.monotonic() + timeout
        leader_exited = False
        while selector.get_map() or not leader_exited:
            if not leader_exited:
                leader_exited = _leader_exited_without_reaping(process.pid, observe_exit)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ProvisionError("runtime selftest timed out")
            for key, unused in selector.select(min(remaining, 0.05)):
                sink = key.data
                allowance = output_limit - len(stdout) - len(stderr) + 1
                chunk = os.read(key.fd, min(DOWNLOAD_CHUNK_SIZE, max(1, allowance)))
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                sink.extend(chunk)
                if len(stdout) + len(stderr) > output_limit:
                    raise ProvisionError("runtime selftest output exceeds limit")
        _cleanup_completed_process_group(process.pid, cleanup, kill_group)
        return_code = process.wait(timeout=0.5)
    except _LeaderAnchorLost:
        raise
    except Exception:
        _terminate_process_group(process, kill_group)
        raise
    finally:
        if selector is not None:
            selector.close()
        for stream, unused in streams:
            if stream is not None:
                stream.close()
    return subprocess.CompletedProcess(
        command,
        return_code,
        stdout.decode("utf-8", errors="replace"),
        stderr.decode("utf-8", errors="replace"),
    )


def validate_runtime(
    runtime: Path | str,
    *,
    timeout: float = SELFTEST_TIMEOUT,
    output_limit: int = SELFTEST_OUTPUT_LIMIT,
    expected_tree_sha256: str = SHA256SUMS_SHA256,
    selftest_runner: Callable | None = None,
) -> dict[str, str]:
    root = Path(runtime)
    records = verify_sha256sums(root, expected_manifest_sha256=expected_tree_sha256)
    required = {"MANIFEST.sha256", "plugin/hermes/jackal_hermes"}
    if not required.issubset(records):
        raise ProvisionError("runtime checksum manifest omits required package files")
    launcher = root / "plugin/hermes/jackal_hermes"
    try:
        launcher_stat = launcher.lstat()
    except OSError as error:
        raise ProvisionError("runtime launcher is missing") from error
    if not stat.S_ISREG(launcher_stat.st_mode) or launcher.is_symlink():
        raise ProvisionError("runtime launcher is not a regular file")
    if not os.access(launcher, os.X_OK):
        raise ProvisionError("runtime launcher is not executable")
    try:
        runner = _run_selftest if selftest_runner is None else selftest_runner
        result = runner(
            [str(launcher), "selftest"],
            timeout=timeout,
            output_limit=output_limit,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise ProvisionError("runtime selftest failed to execute within bounds") from error
    if result.returncode != 0:
        raise ProvisionError("runtime selftest refused")
    if "plugin_hermes.identity_match=true" not in result.stdout.splitlines():
        raise ProvisionError("runtime selftest did not confirm plugin identity")
    verify_sha256sums(root, expected_manifest_sha256=expected_tree_sha256)
    return records


class RuntimeSnapshot:
    """Own one private runtime copy until the MCP server has reaped its workers."""

    def __init__(self, owner: tempfile.TemporaryDirectory[str]) -> None:
        self._owner = owner
        self.root = Path(owner.name).resolve(strict=True)
        self._closed = False

    def close(self) -> None:
        if self._closed:
            return
        self._owner.cleanup()
        self._closed = True


def _private_directory_chain(root_fd: int, components: Iterable[str]) -> int:
    current = os.dup(root_fd)
    try:
        for component in components:
            try:
                next_fd = os.open(component, _directory_flags(), dir_fd=current)
            except FileNotFoundError:
                os.mkdir(component, 0o700, dir_fd=current)
                next_fd = os.open(component, _directory_flags(), dir_fd=current)
            os.close(current)
            current = next_fd
        return current
    except Exception:
        os.close(current)
        raise


def _copy_file_bytes(
    source_fd: int,
    destination_fd: int,
    relative: str,
    *,
    byte_limit: int = SNAPSHOT_BYTE_LIMIT,
) -> str:
    """Copy and hash one already opened file without resolving another pathname."""
    if byte_limit < 0:
        raise ProvisionError(f"runtime snapshot file exceeds byte limit: {relative!r}")
    digest = hashlib.sha256()
    count = 0
    os.lseek(source_fd, 0, os.SEEK_SET)
    while True:
        chunk = os.read(source_fd, DOWNLOAD_CHUNK_SIZE)
        if not chunk:
            break
        count += len(chunk)
        if count > min(byte_limit, SNAPSHOT_BYTE_LIMIT):
            raise ProvisionError(f"runtime snapshot file exceeds byte limit: {relative!r}")
        digest.update(chunk)
        view = memoryview(chunk)
        while view:
            written = os.write(destination_fd, view)
            if written <= 0:
                raise ProvisionError("runtime snapshot write made no progress")
            view = view[written:]
    return digest.hexdigest()


def _copy_runtime_file(
    source_root_fd: int,
    destination_root_fd: int,
    relative: str,
    expected_digest: str | None,
    *,
    byte_limit: int = SNAPSHOT_BYTE_LIMIT,
) -> int:
    source_fd = _open_regular_at(source_root_fd, relative)
    destination_parent_fd = -1
    destination_fd = -1
    try:
        before = os.fstat(source_fd)
        if byte_limit < 0 or before.st_size > min(byte_limit, MAX_RUNTIME_FILE_BYTES):
            raise ProvisionError(
                f"runtime snapshot file exceeds remaining byte limit: {relative!r}"
            )
        destination_parent_fd = _private_directory_chain(
            destination_root_fd, relative.split("/")[:-1]
        )
        try:
            destination_fd = os.open(
                relative.split("/")[-1],
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600,
                dir_fd=destination_parent_fd,
            )
        except OSError as error:
            raise ProvisionError("runtime snapshot destination is unsafe") from error
        actual = _copy_file_bytes(
            source_fd, destination_fd, relative, byte_limit=byte_limit
        )
        after = os.fstat(source_fd)
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
        ):
            raise ProvisionError(f"runtime file changed during snapshot: {relative!r}")
        _require_path_identity(source_root_fd, relative, after)
        if expected_digest is not None and not hmac.compare_digest(actual, expected_digest):
            raise ProvisionError(f"runtime snapshot checksum mismatch: {relative!r}")
        mode = 0o700 if before.st_mode & 0o111 else 0o600
        os.fchmod(destination_fd, mode)
        os.fsync(destination_fd)
        return before.st_size
    finally:
        if destination_fd >= 0:
            os.close(destination_fd)
        if destination_parent_fd >= 0:
            os.close(destination_parent_fd)
        os.close(source_fd)


def create_runtime_snapshot(
    runtime: Path | str,
    *,
    expected_tree_sha256: str = SHA256SUMS_SHA256,
    timeout: float = SELFTEST_TIMEOUT,
    output_limit: int = SELFTEST_OUTPUT_LIMIT,
    selftest_runner: Callable | None = None,
    temporary_parent: Path | str | None = None,
) -> RuntimeSnapshot:
    """Copy the pinned tree into a private owner and validate that exact copy."""
    source = Path(runtime)
    records = verify_sha256sums(
        source, expected_manifest_sha256=expected_tree_sha256
    )
    parent: Path | None = None
    if temporary_parent is not None:
        parent = Path(temporary_parent)
        try:
            parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        except OSError as error:
            raise ProvisionError("runtime snapshot parent is unavailable") from error
    try:
        owner = tempfile.TemporaryDirectory(
            prefix="jackal-codex-runtime-",
            dir=None if parent is None else os.fspath(parent),
        )
    except OSError as error:
        raise ProvisionError("cannot create private runtime snapshot") from error
    snapshot = RuntimeSnapshot(owner)
    try:
        os.chmod(snapshot.root, 0o700)
        source_root_fd = os.open(source, _directory_flags())
        destination_root_fd = os.open(snapshot.root, _directory_flags())
        try:
            total = 0
            for relative, digest in sorted(records.items()):
                total += _copy_runtime_file(
                    source_root_fd,
                    destination_root_fd,
                    relative,
                    digest,
                    byte_limit=SNAPSHOT_BYTE_LIMIT - total,
                )
                if total > SNAPSHOT_BYTE_LIMIT:
                    raise ProvisionError("runtime snapshot exceeds byte limit")
            total += _copy_runtime_file(
                source_root_fd,
                destination_root_fd,
                "SHA256SUMS",
                expected_tree_sha256,
                byte_limit=SNAPSHOT_BYTE_LIMIT - total,
            )
            total += _copy_runtime_file(
                source_root_fd,
                destination_root_fd,
                ".jackal-package.json",
                None,
                byte_limit=SNAPSHOT_BYTE_LIMIT - total,
            )
            if total > SNAPSHOT_BYTE_LIMIT:
                raise ProvisionError("runtime snapshot exceeds byte limit")
        finally:
            os.close(destination_root_fd)
            os.close(source_root_fd)
        verify_sha256sums(source, expected_manifest_sha256=expected_tree_sha256)
        validate_runtime(
            snapshot.root,
            timeout=timeout,
            output_limit=output_limit,
            expected_tree_sha256=expected_tree_sha256,
            selftest_runner=selftest_runner,
        )
        return snapshot
    except Exception as error:
        snapshot.close()
        if isinstance(error, ProvisionError):
            raise
        raise ProvisionError("runtime snapshot creation refused") from error


def _package_metadata(*, epoch: str, asset: str, size: int, digest: str) -> dict[str, object]:
    return {
        "schema": "jackal-runtime-package-v1",
        "epoch": epoch,
        "asset": asset,
        "package_size": size,
        "package_sha256": digest,
    }


def _locator_metadata(runtime: Path, *, epoch: str, size: int, digest: str) -> dict[str, object]:
    return {
        "schema": "jackal-codex-plugin-runtime-v1",
        "epoch": epoch,
        "runtime_path": str(runtime),
        "package_size": size,
        "package_sha256": digest,
    }


def _atomic_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, sort_keys=True, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _load_exact_metadata(path: Path, expected: dict[str, object]) -> None:
    parent_fd = -1
    metadata_fd = -1
    current_fd = -1

    def reject_duplicate_keys(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ProvisionError("installed runtime metadata has duplicate keys")
            result[key] = value
        return result

    try:
        parent_fd = os.open(path.parent, _directory_flags())
        parent_before = os.fstat(parent_fd)
        if not stat.S_ISDIR(parent_before.st_mode):
            raise ProvisionError("installed runtime metadata parent is not a directory")
        metadata_fd = os.open(path.name, _file_read_flags(), dir_fd=parent_fd)
        metadata_before = os.fstat(metadata_fd)
        if not stat.S_ISREG(metadata_before.st_mode):
            raise ProvisionError("installed runtime metadata is not a regular file")
        if metadata_before.st_size > MAX_INSTALLED_METADATA_BYTES:
            raise ProvisionError("installed runtime metadata exceeds byte limit")
        data = _read_fd(metadata_fd, byte_limit=MAX_INSTALLED_METADATA_BYTES)
        text = data.decode("utf-8")
        parsed = json.loads(text, object_pairs_hook=reject_duplicate_keys)
        canonical = (
            json.dumps(expected, sort_keys=True, separators=(",", ":")) + "\n"
        ).encode("utf-8")
        if data != canonical:
            raise ProvisionError("installed runtime metadata is not canonical JSON")

        current_fd = os.open(path.name, _file_read_flags(), dir_fd=parent_fd)
        current_info = os.fstat(current_fd)
        metadata_after = os.fstat(metadata_fd)
        if (
            not stat.S_ISREG(current_info.st_mode)
            or _file_signature(metadata_before) != _file_signature(metadata_after)
            or _file_signature(metadata_after) != _file_signature(current_info)
        ):
            raise ProvisionError("installed runtime metadata path changed during validation")
        parent_after = os.fstat(parent_fd)
        parent_path = os.stat(path.parent, follow_symlinks=False)
        if (
            _file_signature(parent_before) != _file_signature(parent_after)
            or _file_signature(parent_after) != _file_signature(parent_path)
        ):
            raise ProvisionError("installed runtime metadata parent changed during validation")
    except ProvisionError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, RecursionError) as error:
        raise ProvisionError("installed runtime metadata is invalid") from error
    finally:
        for fd in (current_fd, metadata_fd, parent_fd):
            if fd >= 0:
                os.close(fd)
    if parsed != expected:
        raise ProvisionError("installed runtime does not match the pinned package")


def _verify_outer_file(path: Path, expected_size: int, expected_sha256: str):
    try:
        fd = os.open(path, _file_read_flags())
    except OSError as error:
        raise ProvisionError("cannot safely open tarball") from error
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise ProvisionError("tarball is not a regular file")
        if info.st_size != expected_size:
            raise ProvisionError("tarball size does not match pin")
        actual = _hash_fd(fd, byte_limit=expected_size)
        if not hmac.compare_digest(actual, expected_sha256):
            raise ProvisionError("tarball SHA-256 does not match pin")
        os.lseek(fd, 0, os.SEEK_SET)
        return os.fdopen(fd, "rb")
    except Exception:
        os.close(fd)
        raise


def _renameatx_np_exclusive(
    source_parent_fd: int,
    source_name: str,
    target_parent_fd: int,
    target_name: str,
) -> None:
    if platform.system() != "Darwin":
        raise ProvisionError("atomic no-replace installation requires macOS renameatx_np")
    libc = ctypes.CDLL(None, use_errno=True)
    renameatx = libc.renameatx_np
    renameatx.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    renameatx.restype = ctypes.c_int
    result = renameatx(
        source_parent_fd,
        os.fsencode(source_name),
        target_parent_fd,
        os.fsencode(target_name),
        0x00000004,
    )
    if result != 0:
        error_number = ctypes.get_errno()
        if error_number == errno.EEXIST:
            raise FileExistsError(error_number, os.strerror(error_number), target_name)
        raise OSError(error_number, os.strerror(error_number), target_name)


def _install_no_replace(
    source: Path | str,
    target: Path | str,
    *,
    rename_exclusive: Callable | None = None,
) -> None:
    source_path = Path(source)
    target_path = Path(target)
    operation = _renameatx_np_exclusive if rename_exclusive is None else rename_exclusive
    source_parent_fd = -1
    target_parent_fd = -1
    try:
        source_parent_fd = os.open(source_path.parent, _directory_flags())
        target_parent_fd = os.open(target_path.parent, _directory_flags())
    except OSError as error:
        if source_parent_fd >= 0:
            os.close(source_parent_fd)
        raise ProvisionError("installation parent is not a safe directory") from error
    try:
        operation(source_parent_fd, source_path.name, target_parent_fd, target_path.name)
    finally:
        os.close(source_parent_fd)
        os.close(target_parent_fd)


def provision(
    *,
    tarball: Path | str | None = None,
    check_only: bool = False,
    runtime_target: Path | str | None = None,
    locator_path: Path | str | None = None,
    expected_size: int = PACKAGE_SIZE,
    expected_sha256: str = PACKAGE_SHA256,
    expected_extracted_size: int = EXTRACTED_SIZE,
    expected_tree_sha256: str = SHA256SUMS_SHA256,
    epoch: str = EPOCH,
    asset: str = ASSET,
    url: str = URL,
    expected_top_level: str = PACKAGE_DIRECTORY,
    opener: Callable = urllib.request.urlopen,
    network_timeout: float = NETWORK_TIMEOUT,
    download_total_timeout: float = DOWNLOAD_TOTAL_TIMEOUT,
    system: str | None = None,
    machine: str | None = None,
    selftest_timeout: float = SELFTEST_TIMEOUT,
    selftest_output_limit: int = SELFTEST_OUTPUT_LIMIT,
    selftest_runner: Callable | None = None,
    install_no_replace: Callable | None = None,
) -> Path:
    """Validate or atomically install the pinned runtime."""
    validate_host(system, machine)
    if (
        expected_size < 0
        or expected_extracted_size < 0
        or not _valid_digest(expected_sha256)
        or not _valid_digest(expected_tree_sha256)
    ):
        raise ProvisionError("invalid package expectation")
    target = default_runtime_target() if runtime_target is None else Path(runtime_target)
    locator = default_locator_path() if locator_path is None else Path(locator_path)
    expected_package = _package_metadata(
        epoch=epoch, asset=asset, size=expected_size, digest=expected_sha256
    )
    expected_locator = _locator_metadata(
        target, epoch=epoch, size=expected_size, digest=expected_sha256
    )

    if os.path.lexists(target):
        if target.is_symlink() or not target.is_dir():
            raise ProvisionError("existing runtime target is not a safe directory")
        _load_exact_metadata(target / ".jackal-package.json", expected_package)
        validate_runtime(
            target,
            timeout=selftest_timeout,
            output_limit=selftest_output_limit,
            expected_tree_sha256=expected_tree_sha256,
            selftest_runner=selftest_runner,
        )
        if not check_only:
            _atomic_json(locator, expected_locator)
        return target
    if check_only:
        raise ProvisionError("pinned runtime is not installed")

    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f".{epoch}.stage-", dir=target.parent) as temporary_directory:
        staging = Path(temporary_directory)
        package_source: Path
        if tarball is None:
            package_source = staging / asset
            stream_download(
                url, package_source,
                expected_size=expected_size,
                expected_sha256=expected_sha256,
                opener=opener,
                network_timeout=network_timeout,
                total_timeout=download_total_timeout,
            )
        else:
            package_source = Path(tarball)
            if not package_source.is_absolute():
                raise ProvisionError("offline tarball path must be absolute")
        with _verify_outer_file(package_source, expected_size, expected_sha256) as verified:
            try:
                with tarfile.open(fileobj=verified, mode="r:*") as archive:
                    members = safe_members(
                        archive,
                        expected_extracted_size=expected_extracted_size,
                        expected_top_level=expected_top_level,
                    )
                    extraction = staging / "extracted"
                    _extract_members(archive, members, extraction)
            except (tarfile.TarError, EOFError, OSError) as error:
                raise ProvisionError("tarball is not a valid safe archive") from error
        candidate = extraction / expected_top_level
        validate_runtime(
            candidate,
            timeout=selftest_timeout,
            output_limit=selftest_output_limit,
            expected_tree_sha256=expected_tree_sha256,
            selftest_runner=selftest_runner,
        )
        _atomic_json(candidate / ".jackal-package.json", expected_package)
        installer = _install_no_replace if install_no_replace is None else install_no_replace
        try:
            installer(candidate, target)
        except FileExistsError:
            if target.is_symlink() or not target.is_dir():
                raise ProvisionError("runtime install race produced an unsafe target")
            _load_exact_metadata(target / ".jackal-package.json", expected_package)
            validate_runtime(
                target,
                timeout=selftest_timeout,
                output_limit=selftest_output_limit,
                expected_tree_sha256=expected_tree_sha256,
                selftest_runner=selftest_runner,
            )
        except OSError as error:
            raise ProvisionError("atomic no-replace runtime installation failed") from error
    validate_runtime(
        target,
        timeout=selftest_timeout,
        output_limit=selftest_output_limit,
        expected_tree_sha256=expected_tree_sha256,
        selftest_runner=selftest_runner,
    )
    try:
        _atomic_json(locator, expected_locator)
    except Exception as error:
        raise ProvisionError("runtime installed but locator update failed") from error
    return target


def _bounded_detail(error: Exception) -> str:
    return (" ".join(str(error).splitlines()).strip() or "provisioning failed")[:240]


class _ArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise ProvisionError(f"invalid arguments: {message}")


def main(argv: list[str] | None = None) -> int:
    parser = _ArgumentParser(add_help=True, description="Provision the pinned JACKAL runtime")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--tarball")
    modes.add_argument("--check", action="store_true")
    try:
        arguments = parser.parse_args(sys.argv[1:] if argv is None else argv)
        offline = None
        if arguments.tarball is not None:
            offline = Path(arguments.tarball)
            if not offline.is_absolute():
                raise ProvisionError("--tarball requires an absolute path")
        runtime = provision(tarball=offline, check_only=arguments.check)
    except ProvisionError as error:
        print(f"jackal_runtime=refused detail={_bounded_detail(error)}", file=sys.stderr)
        return 1
    except Exception:
        print("jackal_runtime=refused detail=unexpected provisioning failure", file=sys.stderr)
        return 1
    print(
        f"jackal_runtime=ready epoch={EPOCH} runtime={runtime} package_sha256={PACKAGE_SHA256}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
