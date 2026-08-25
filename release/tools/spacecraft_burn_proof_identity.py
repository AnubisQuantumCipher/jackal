#!/usr/bin/env python3
"""Generate or verify the spacecraft-burn Lean proof/build identity."""

from __future__ import annotations

import sys

if __name__ == "__main__" and not sys.flags.isolated:
    print(
        "refusing non-isolated startup; invoke with an absolute Python interpreter and -I -B",
        file=sys.stderr,
    )
    raise SystemExit(2)

import hashlib
import os
import pwd
from pathlib import Path
import re
import stat
import subprocess
import tempfile
import types
from typing import Any


WRAPPER_PATH = Path(__file__).resolve()
ENGINE_PATH = WRAPPER_PATH.with_name("gaussian_proof_identity.py")


def require_real_path_components(root: Path, path: Path) -> None:
    root = Path(os.path.abspath(root))
    path = Path(os.path.abspath(path))
    try:
        relative = path.relative_to(root)
    except ValueError as error:
        raise engine.GateError(f"path escaped its declared root: {path}") from error
    root_status = root.lstat()
    if root.is_symlink() or not stat.S_ISDIR(root_status.st_mode):
        raise engine.GateError(f"declared root is not a real directory: {root}")
    current = root
    for part in relative.parts[:-1]:
        current = current / part
        status = current.lstat()
        if current.is_symlink() or not stat.S_ISDIR(status.st_mode):
            raise engine.GateError(f"path traverses a non-directory or symlink: {current}")


def bounded_source_snapshot(path: Path, maximum_bytes: int = 16 * 1024 * 1024) -> bytes:
    descriptor = os.open(
        path,
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0),
    )
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_size > maximum_bytes:
            raise RuntimeError(f"generator source is not a bounded regular file: {path}")
        payload = bytearray()
        while len(payload) <= maximum_bytes:
            block = os.read(descriptor, min(1024 * 1024, maximum_bytes + 1 - len(payload)))
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
            raise RuntimeError(f"generator source changed during snapshot: {path}")
        return bytes(payload)
    finally:
        os.close(descriptor)


WRAPPER_SOURCE_BYTES = bounded_source_snapshot(WRAPPER_PATH)
ENGINE_SOURCE_BYTES = bounded_source_snapshot(ENGINE_PATH)
WRAPPER_SOURCE_SHA256 = hashlib.sha256(WRAPPER_SOURCE_BYTES).hexdigest()
ENGINE_SOURCE_SHA256 = hashlib.sha256(ENGINE_SOURCE_BYTES).hexdigest()
_ENGINE_MODULE_NAME = "jackal_spacecraft_gaussian_identity_engine"
engine = types.ModuleType(_ENGINE_MODULE_NAME)
engine.__file__ = str(ENGINE_PATH)
engine.__package__ = ""
sys.modules[_ENGINE_MODULE_NAME] = engine
exec(compile(ENGINE_SOURCE_BYTES, str(ENGINE_PATH), "exec"), engine.__dict__)


_collect_engine_source_closure = engine.collect_source_closure
_collect_engine_toolchain = engine.collect_toolchain
_run_engine_axiom_audit = engine.run_axiom_audit
_collect_engine_checker = engine.collect_checker
_engine_run = engine.run
LIVE_REPO_ROOT = engine.REPO_ROOT
LIVE_LEAN_DIR = engine.LEAN_DIR
_CLEAN_REBUILD = False
_VERIFIED_PACKAGE_TREES: list[dict[str, Any]] = []
_VERIFIED_PACKAGE_ENTRIES: dict[str, tuple[tuple[str, str, str, str], ...]] = {}
_PRIVATE_BUILD_ACTIVE = False
_PRIVATE_ELAN_HOME: Path | None = None
_PRIVATE_PROCESS_HOME: Path | None = None
_PRIVATE_PROCESS_TMP: Path | None = None
_PRIVATE_PACKAGE_OVERRIDE_BYTES: bytes | None = None
_PRIVATE_PACKAGE_OVERRIDE_PATH: Path | None = None
_PRIVATE_SANDBOX_PROFILE: str | None = None
_PRIVATE_TOOLCHAIN_ROOT: Path | None = None
_PRIVATE_TOOLCHAIN_TREE: dict[str, Any] | None = None
_PRIVATE_LOCAL_SOURCE_TREE: dict[str, Any] | None = None
_OBSERVED_TOOLCHAIN_BINARIES: dict[str, dict[str, Any]] = {}
TRUSTED_GIT = Path("/usr/bin/git")
TRUSTED_SANDBOX_EXEC = Path("/usr/bin/sandbox-exec")
PRIVATE_LAKE_BOOKKEEPING = (
    (
        Path(".lake/packages/proofwidgets/widget/package-lock.json.hash"),
        b"179e66574f04806e",
    ),
)
USER_HOME = Path(pwd.getpwuid(os.getuid()).pw_dir)
PACKAGE_CHECKOUT_POLICY = (
    "Every git dependency is pinned to a full commit; replacement refs, grafts, "
    "alternates, index hiding flags, object corruption, and tracked-byte drift are "
    "rejected. Tracked symlinks must remain lexically confined to real package paths. "
    "Identity generation admits only open-once snapshots of tracked dependency bytes "
    "into a private fresh workspace and rebuilds without live caches."
)
BUILD_ISOLATION_POLICY = (
    "Publication generation copies an explicit local Lean source closure, every pinned "
    "dependency blob, and the complete pinned Lean toolchain regular-file tree into a "
    "private mode-0700 workspace. Deterministic path overrides make Lake consume only "
    "those verified dependency snapshots. Lake is invoked with the absolute pinned "
    "lakefile, rehashing, reconfiguration, no remote cache, and the private toolchain. macOS "
    "sandbox policy denies the build subprocess writes to source and toolchain bytes "
    "while permitting dedicated .lake build/configuration directories and one exact "
    "ProofWidgets hash sidecar that --rehash recomputes but never trusts as an input. "
    "That sidecar and exact source/dependency manifests are checked around every Lake "
    "command, and the complete toolchain tree is checked before and after the build. "
    "This boundary trusts the "
    "owning macOS kernel, sandbox facility, dyld, libSystem, hardware, and the invoking "
    "Python interpreter; it is not a proof of that platform supply chain."
)
SPACECRAFT_AXIOM_DECLARATION_RE = re.compile(r"\baxioms?\b")
SPACECRAFT_IMPLEMENTED_BY_RE = re.compile(r"\bimplemented_by\b")
SPACECRAFT_MODULE_RE = re.compile(
    r"[A-Z][A-Za-z0-9_']*(?:\.[A-Z][A-Za-z0-9_']*)*"
)
PINNED_CONFIGURATION_SHA256 = {
    "proofs/lean/lakefile.toml": "48b4a93ddda8ea85bda3fe65ac2f94dc43d6629641cdaf7bead228ec26d90bfe",
    "proofs/lean/lake-manifest.json": "f521808691ba1ab175c5cdeec098a76586d345fea93370a38c2d2b73645f69d4",
    "proofs/lean/lean-toolchain": "2773c517aa90b66ea8a2c52bddddf84393157797f8341be0df45294fff7fd32e",
}


def isolated_process_environment(toolchain_bin: Path | None = None) -> dict[str, str]:
    path = "/usr/bin:/bin:/usr/sbin:/sbin"
    if toolchain_bin is not None:
        path = f"{toolchain_bin}:{path}"
    home = USER_HOME
    elan_home = USER_HOME / ".elan"
    temporary = Path("/tmp")
    if _PRIVATE_BUILD_ACTIVE:
        if (
            _PRIVATE_ELAN_HOME is None
            or _PRIVATE_PROCESS_HOME is None
            or _PRIVATE_PROCESS_TMP is None
        ):
            raise engine.GateError("private process environment is incomplete")
        home = _PRIVATE_PROCESS_HOME
        elan_home = _PRIVATE_ELAN_HOME
        temporary = _PRIVATE_PROCESS_TMP
    return {
        "ELAN_HOME": str(elan_home),
        "HOME": str(home),
        "LANG": "C",
        "LC_ALL": "C",
        "PATH": path,
        "TMPDIR": str(temporary),
        "TZ": "UTC",
    }


def pinned_toolchain_token(cwd: Path) -> str:
    token_bytes = bounded_source_snapshot(cwd / "lean-toolchain", 4096)
    try:
        token = token_bytes.decode("utf-8").strip()
    except UnicodeDecodeError as error:
        raise engine.GateError("lean-toolchain is not UTF-8") from error
    if re.fullmatch(r"leanprover/lean4:v[0-9]+(?:\.[0-9]+){2}", token) is None:
        raise engine.GateError(f"unsupported pinned Lean toolchain token: {token!r}")
    return token


def toolchain_directory_name(token: str) -> str:
    return token.replace("/", "--").replace(":", "---")


def live_pinned_toolchain_root(cwd: Path) -> Path:
    token = pinned_toolchain_token(cwd)
    return USER_HOME / ".elan" / "toolchains" / toolchain_directory_name(token)


def active_pinned_toolchain_root(cwd: Path) -> Path:
    token = pinned_toolchain_token(cwd)
    if _PRIVATE_BUILD_ACTIVE:
        if _PRIVATE_TOOLCHAIN_ROOT is None:
            raise engine.GateError("private Lean toolchain root is unavailable")
        if _PRIVATE_TOOLCHAIN_ROOT.name != toolchain_directory_name(token):
            raise engine.GateError("private Lean toolchain token/root mismatch")
        return _PRIVATE_TOOLCHAIN_ROOT
    return live_pinned_toolchain_root(cwd)


def pinned_toolchain_bin(cwd: Path) -> Path:
    return active_pinned_toolchain_root(cwd) / "bin"


def snapshot_toolchain_binaries(directory: Path) -> dict[str, dict[str, Any]]:
    observed: dict[str, dict[str, Any]] = {}
    for name in ("lake", "lean", "leanc"):
        path = directory / name
        raw = bounded_source_snapshot(path, 512 * 1024 * 1024)
        observed[name] = {
            "bytes": len(raw),
            "name": name,
            "sha256": hashlib.sha256(raw).hexdigest(),
        }
    return observed


def configured_lake_command(argv: list[str], cwd: Path, toolchain_bin: Path) -> list[str]:
    if argv == ["lake", "--version"]:
        return [str(toolchain_bin / "lake"), "--version"]
    if len(argv) < 2 or argv[1] not in {"build", "clean", "env"}:
        raise engine.GateError(f"unsupported Lake command shape: {argv!r}")
    forbidden = (
        "--dir",
        "-d",
        "--file",
        "-f",
        "--packages",
        "-K",
        "--update",
        "--try-cache",
        "--old",
    )
    if any(
        argument == option or argument.startswith(option + "=")
        for argument in argv[1:]
        for option in forbidden
    ):
        raise engine.GateError(f"caller supplied a forbidden Lake configuration option: {argv!r}")
    lakefile = cwd / "lakefile.toml"
    configured = [
        str(toolchain_bin / "lake"),
        f"--file={lakefile}",
        "--rehash",
        "--reconfigure",
        "--no-cache",
        "--keep-toolchain",
    ]
    if _PRIVATE_BUILD_ACTIVE:
        if _PRIVATE_PACKAGE_OVERRIDE_PATH is None:
            raise engine.GateError("private Lake dependency overrides are unavailable")
        configured.append(f"--packages={_PRIVATE_PACKAGE_OVERRIDE_PATH}")
    configured.extend(argv[1:])
    return configured


def run_isolated(
    command,
    *,
    cwd: Path,
    input_text: str | None = None,
    allow_stderr: bool = False,
) -> str:
    argv = list(command)
    if not argv:
        raise engine.GateError("empty proof-identity subprocess command")
    toolchain_bin: Path | None = None
    before_toolchain: dict[str, dict[str, Any]] | None = None
    if argv[0] == "lake":
        toolchain_bin = pinned_toolchain_bin(cwd)
        before_toolchain = snapshot_toolchain_binaries(toolchain_bin)
        argv = configured_lake_command(argv, cwd, toolchain_bin)
    elif argv[0] == "git":
        argv[0] = str(TRUSTED_GIT)
    if toolchain_bin is not None and _PRIVATE_BUILD_ACTIVE:
        if _PRIVATE_SANDBOX_PROFILE is None or not TRUSTED_SANDBOX_EXEC.is_file():
            raise engine.GateError("private build requires the owning macOS sandbox facility")
        validate_private_input_snapshots()
        argv = [
            str(TRUSTED_SANDBOX_EXEC),
            "-p",
            _PRIVATE_SANDBOX_PROFILE,
            *argv,
        ]
    timeout = 4 * 60 * 60 if toolchain_bin is not None else 10 * 60
    try:
        result = subprocess.run(
            argv,
            cwd=cwd,
            env=isolated_process_environment(toolchain_bin),
            input=input_text,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise engine.GateError(
            f"proof-identity command timed out: {' '.join(argv)}"
        ) from error
    if toolchain_bin is not None:
        if _PRIVATE_BUILD_ACTIVE:
            validate_private_input_snapshots()
        after_toolchain = snapshot_toolchain_binaries(toolchain_bin)
        if after_toolchain != before_toolchain:
            raise engine.GateError("Lean toolchain binaries changed during execution")
        if _OBSERVED_TOOLCHAIN_BINARIES and _OBSERVED_TOOLCHAIN_BINARIES != after_toolchain:
            raise engine.GateError("Lean toolchain binary identity drifted between commands")
        _OBSERVED_TOOLCHAIN_BINARIES.clear()
        _OBSERVED_TOOLCHAIN_BINARIES.update(after_toolchain)
    if result.returncode != 0:
        detail = (result.stdout + result.stderr).strip()
        raise engine.GateError(
            f"command failed ({result.returncode}): {' '.join(argv)}"
            + (f"\n{detail}" if detail else "")
        )
    if result.stderr.strip() and not allow_stderr:
        raise engine.GateError(
            f"command emitted unexpected stderr: {' '.join(argv)}\n"
            f"{result.stderr.strip()}"
        )
    return result.stdout.strip()


def git_bytes(checkout: Path, *arguments: str) -> bytes:
    command = [
        str(TRUSTED_GIT),
        "--no-replace-objects",
        "-c", "core.fsmonitor=false",
        "-c", "core.hooksPath=/dev/null",
        "-c", "core.untrackedCache=false",
        "-C", str(checkout),
        *arguments,
    ]
    environment = isolated_process_environment()
    environment.update({
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_NO_REPLACE_OBJECTS": "1",
    })
    try:
        completed = subprocess.run(
            command,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30 * 60,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise engine.GateError(
            f"trusted git command timed out for {checkout.name}: {' '.join(arguments)}"
        ) from error
    if completed.returncode != 0 or completed.stderr:
        detail = (completed.stdout + completed.stderr).decode("utf-8", "replace").strip()
        raise engine.GateError(
            f"trusted git command failed for {checkout.name}: {' '.join(arguments)}"
            + (f"\n{detail}" if detail else "")
        )
    return completed.stdout


def git_blob_oid(
    path: Path,
    expected_mode: str,
    maximum_bytes: int = 512 * 1024 * 1024,
) -> str:
    before = path.lstat()
    if expected_mode == "120000":
        if not stat.S_ISLNK(before.st_mode):
            raise engine.GateError(f"tracked symlink type drift: {path}")
        payload = os.fsencode(os.readlink(path))
        return hashlib.sha1(b"blob " + str(len(payload)).encode() + b"\0" + payload).hexdigest()
    if expected_mode not in {"100644", "100755"} or not stat.S_ISREG(before.st_mode):
        raise engine.GateError(f"tracked file type drift: {path}")
    if before.st_size > maximum_bytes:
        raise engine.GateError(f"tracked file exceeds the bounded read limit: {path}")
    executable = bool(before.st_mode & 0o111)
    if executable != (expected_mode == "100755"):
        raise engine.GateError(f"tracked executable-mode drift: {path}")
    descriptor = os.open(
        path,
        os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0),
    )
    try:
        opened = os.fstat(descriptor)
        if (opened.st_dev, opened.st_ino, opened.st_size) != (
            before.st_dev, before.st_ino, before.st_size
        ):
            raise engine.GateError(f"tracked file changed before hashing: {path}")
        digest = hashlib.sha1(
            b"blob " + str(opened.st_size).encode("ascii") + b"\0"
        )
        consumed = 0
        while consumed <= opened.st_size:
            block = os.read(
                descriptor,
                min(1024 * 1024, opened.st_size + 1 - consumed),
            )
            if not block:
                break
            consumed += len(block)
            digest.update(block)
        if consumed > opened.st_size:
            raise engine.GateError(f"tracked file grew while hashing: {path}")
        after = os.fstat(descriptor)
        stable = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
        if consumed != opened.st_size or any(
            getattr(opened, field) != getattr(after, field) for field in stable
        ):
            raise engine.GateError(f"tracked file changed while hashing: {path}")
        return digest.hexdigest()
    finally:
        os.close(descriptor)


def filesystem_source_entries(checkout: Path) -> set[str]:
    observed: set[str] = set()
    for current, directories, files in os.walk(checkout, topdown=True, followlinks=False):
        current_path = Path(current)
        if current_path == checkout:
            directories[:] = [name for name in directories if name not in {".git", ".lake"}]
            files = [name for name in files if name not in {".git"}]
        for name in list(directories):
            candidate = current_path / name
            if candidate.is_symlink():
                observed.add(candidate.relative_to(checkout).as_posix())
                directories.remove(name)
        for name in files:
            observed.add((current_path / name).relative_to(checkout).as_posix())
    return observed


def copy_regular_snapshot(
    source: Path,
    destination: Path,
    *,
    maximum_bytes: int = 512 * 1024 * 1024,
    expected_git_oid: str | None = None,
    executable: bool | None = None,
) -> dict[str, Any]:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    source_descriptor = os.open(source, flags)
    destination_descriptor: int | None = None
    try:
        before = os.fstat(source_descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_size > maximum_bytes:
            raise engine.GateError(f"snapshot source is not a bounded regular file: {source}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination_descriptor = os.open(
            destination,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0),
            0o755 if (executable if executable is not None else before.st_mode & 0o111) else 0o644,
        )
        git_digest = hashlib.sha1(
            b"blob " + str(before.st_size).encode("ascii") + b"\0"
        )
        content_digest = hashlib.sha256()
        copied = 0
        while copied <= before.st_size:
            block = os.read(
                source_descriptor,
                min(1024 * 1024, before.st_size + 1 - copied),
            )
            if not block:
                break
            git_digest.update(block)
            content_digest.update(block)
            view = memoryview(block)
            offset = 0
            while offset < len(view):
                written = os.write(destination_descriptor, view[offset:])
                if written <= 0:
                    raise engine.GateError(f"zero-length private snapshot write: {destination}")
                offset += written
            copied += len(block)
        if copied > before.st_size:
            raise engine.GateError(f"snapshot source grew during copy: {source}")
        after = os.fstat(source_descriptor)
        stable = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
        if copied != before.st_size or any(
            getattr(before, field) != getattr(after, field) for field in stable
        ):
            raise engine.GateError(f"snapshot source changed during copy: {source}")
        if expected_git_oid is not None and git_digest.hexdigest() != expected_git_oid:
            raise engine.GateError(f"snapshot source does not match its pinned Git blob: {source}")
        os.fsync(destination_descriptor)
        return {
            "bytes": copied,
            "mode": stat.S_IMODE(before.st_mode),
            "sha256": content_digest.hexdigest(),
        }
    except BaseException:
        try:
            destination.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    finally:
        if destination_descriptor is not None:
            os.close(destination_descriptor)
        os.close(source_descriptor)


def stable_regular_file_record(
    path: Path,
    maximum_bytes: int = 512 * 1024 * 1024,
) -> dict[str, Any]:
    descriptor = os.open(
        path,
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0),
    )
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_size > maximum_bytes:
            raise engine.GateError(f"tree member is not a bounded regular file: {path}")
        digest = hashlib.sha256()
        consumed = 0
        while consumed <= before.st_size:
            block = os.read(
                descriptor,
                min(1024 * 1024, before.st_size + 1 - consumed),
            )
            if not block:
                break
            digest.update(block)
            consumed += len(block)
        after = os.fstat(descriptor)
        stable = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
        if (
            consumed != before.st_size
            or any(getattr(before, field) != getattr(after, field) for field in stable)
        ):
            raise engine.GateError(f"tree member changed while hashing: {path}")
        return {
            "bytes": consumed,
            "mode": stat.S_IMODE(before.st_mode),
            "sha256": digest.hexdigest(),
        }
    finally:
        os.close(descriptor)


def regular_tree_record(
    root: Path,
    *,
    definition: str,
    excluded_root_directories: frozenset[str] = frozenset(),
    maximum_entries: int = 100_000,
    maximum_total_bytes: int = 8 * 1024 * 1024 * 1024,
) -> dict[str, Any]:
    root = Path(os.path.abspath(root))
    root_status = root.lstat()
    if root.is_symlink() or not stat.S_ISDIR(root_status.st_mode):
        raise engine.GateError(f"tree root is not a real directory: {root}")
    aggregate = hashlib.sha256(b"jackal-regular-tree-v1\0")
    directory_count = 0
    file_count = 0
    total_bytes = 0
    for current, directories, files in os.walk(root, topdown=True, followlinks=False):
        current_path = Path(current)
        directories.sort()
        files.sort()
        if current_path == root:
            directories[:] = [
                name for name in directories if name not in excluded_root_directories
            ]
        for name in directories:
            path = current_path / name
            status = path.lstat()
            if path.is_symlink() or not stat.S_ISDIR(status.st_mode):
                raise engine.GateError(f"tree directory is not a real directory: {path}")
            relative = path.relative_to(root).as_posix()
            aggregate.update(
                b"D\0"
                + relative.encode("utf-8")
                + b"\0"
                + f"{stat.S_IMODE(status.st_mode):04o}".encode("ascii")
                + b"\n"
            )
            directory_count += 1
            if file_count + directory_count > maximum_entries:
                raise engine.GateError(f"tree exceeds the entry bound: {root}")
        for name in files:
            path = current_path / name
            if path.is_symlink():
                raise engine.GateError(f"tree symlinks are forbidden: {path}")
            record = stable_regular_file_record(path)
            if record["mode"] not in {0o644, 0o755}:
                raise engine.GateError(f"unsupported tree member mode: {path}")
            relative = path.relative_to(root).as_posix()
            aggregate.update(
                b"F\0"
                + relative.encode("utf-8")
                + b"\0"
                + f"{record['mode']:04o}".encode("ascii")
                + b"\0"
                + str(record["bytes"]).encode("ascii")
                + b"\0"
                + record["sha256"].encode("ascii")
                + b"\n"
            )
            file_count += 1
            total_bytes += record["bytes"]
            if file_count + directory_count > maximum_entries:
                raise engine.GateError(f"tree exceeds the entry bound: {root}")
            if total_bytes > maximum_total_bytes:
                raise engine.GateError(f"tree exceeds the byte bound: {root}")
    return {
        "aggregate_sha256": aggregate.hexdigest(),
        "definition": definition,
        "directory_count": directory_count,
        "entry_count": directory_count + file_count,
        "file_count": file_count,
        "total_bytes": total_bytes,
    }


def complete_toolchain_tree_record(root: Path, token: str) -> dict[str, Any]:
    return {
        **regular_tree_record(
            root,
            definition=(
                "SHA-256 aggregate over every relative directory path/mode and regular "
                "file path/mode/size/SHA-256 in the private Lean toolchain snapshot; "
                "symlinks and special files are forbidden."
            ),
        ),
        "directory_name": toolchain_directory_name(token),
        "lean_toolchain": token,
    }


def snapshot_complete_toolchain(source: Path, destination: Path, token: str) -> dict[str, Any]:
    source = Path(os.path.abspath(source))
    if source.name != toolchain_directory_name(token):
        raise engine.GateError("live Lean toolchain directory does not match the pinned token")
    source_status = source.lstat()
    if source.is_symlink() or not stat.S_ISDIR(source_status.st_mode):
        raise engine.GateError(f"live Lean toolchain is not a real directory: {source}")
    destination.mkdir(mode=0o700, parents=True, exist_ok=False)
    for current, directories, files in os.walk(source, topdown=True, followlinks=False):
        current_path = Path(current)
        destination_current = destination / current_path.relative_to(source)
        directories.sort()
        files.sort()
        for name in directories:
            child = current_path / name
            require_real_path_components(source, child / ".component-check")
            status = child.lstat()
            if child.is_symlink() or not stat.S_ISDIR(status.st_mode):
                raise engine.GateError(f"toolchain directory is not a real directory: {child}")
            target = destination_current / name
            target.mkdir(mode=stat.S_IMODE(status.st_mode), exist_ok=False)
            os.chmod(target, stat.S_IMODE(status.st_mode))
        for name in files:
            child = current_path / name
            require_real_path_components(source, child)
            if child.is_symlink():
                raise engine.GateError(f"toolchain symlinks are forbidden: {child}")
            copied = copy_regular_snapshot(child, destination_current / name)
            if copied["mode"] not in {0o644, 0o755}:
                raise engine.GateError(f"unsupported toolchain member mode: {child}")
    private_record = complete_toolchain_tree_record(destination, token)
    live_record = complete_toolchain_tree_record(source, token)
    if private_record != live_record:
        raise engine.GateError("live Lean toolchain changed during its private snapshot")
    return private_record


def snapshot_symlink(
    source: Path,
    destination: Path,
    expected_git_oid: str,
    package_root: Path,
) -> None:
    source = Path(os.path.abspath(source))
    package_root = Path(os.path.abspath(package_root))
    require_real_path_components(package_root, source)
    before = source.lstat()
    if not stat.S_ISLNK(before.st_mode):
        raise engine.GateError(f"tracked symlink type drift: {source}")
    target = os.readlink(source)
    after = source.lstat()
    stable = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
    if any(getattr(before, field) != getattr(after, field) for field in stable):
        raise engine.GateError(f"tracked symlink changed during snapshot: {source}")
    payload = os.fsencode(target)
    observed = hashlib.sha1(
        b"blob " + str(len(payload)).encode("ascii") + b"\0" + payload
    ).hexdigest()
    if observed != expected_git_oid:
        raise engine.GateError(f"tracked symlink byte drift: {source}")
    target_path = Path(target)
    if target_path.is_absolute():
        raise engine.GateError(f"tracked symlink escapes package: {source}")
    lexical_target = Path(os.path.normpath(str(source.parent / target_path)))
    try:
        lexical_target.relative_to(package_root)
    except ValueError as error:
        raise engine.GateError(f"tracked symlink escapes package: {source}") from error
    try:
        require_real_path_components(package_root, lexical_target)
    except OSError as error:
        raise engine.GateError(
            f"tracked symlink target traverses an invalid component: {source}"
        ) from error
    if lexical_target.is_symlink():
        raise engine.GateError(f"tracked symlink target is another symlink: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    os.symlink(target, destination)


def snapshot_local_lean_workspace(
    source: Path,
    destination: Path,
    relative_paths: set[Path],
) -> dict[str, Any]:
    destination.mkdir(parents=True, exist_ok=False)
    for relative in sorted(relative_paths, key=lambda item: item.as_posix()):
        if relative.is_absolute() or ".." in relative.parts or relative.parts[0] == ".lake":
            raise engine.GateError(f"unsafe private local source path: {relative}")
        child = source / relative
        require_real_path_components(source, child)
        if child.is_symlink():
            raise engine.GateError(f"local Lean source file is a symlink: {child}")
        copy_regular_snapshot(
            child,
            destination / relative,
            maximum_bytes=64 * 1024 * 1024,
        )
    return regular_tree_record(
        destination,
        definition=(
            "Exact private regular-file tree containing only the admitted transitive local "
            "Lean source closure and the three pinned Lake configuration files; .lake build "
            "outputs are excluded."
        ),
        excluded_root_directories=frozenset({".lake"}),
        maximum_total_bytes=1024 * 1024 * 1024,
    )


def snapshot_dependency_workspaces(
    live_lean: Path,
    private_lean: Path,
    packages: list[dict[str, Any]],
) -> None:
    validate_spacecraft_package_checkouts(packages)
    package_root = private_lean / ".lake" / "packages"
    package_root.mkdir(parents=True, exist_ok=True)
    for package in packages:
        if package["type"] != "git":
            raise engine.GateError(f"unsupported non-git Lake dependency: {package['name']}")
        name = package["name"]
        source = live_lean / ".lake" / "packages" / name
        destination = package_root / name
        destination.mkdir(parents=True, exist_ok=False)
        entries = _VERIFIED_PACKAGE_ENTRIES.get(name)
        if entries is None:
            raise engine.GateError(f"missing verified dependency tree: {name}")
        for mode, object_type, object_id, relative in entries:
            source_path = source / relative
            destination_path = destination / relative
            require_real_path_components(source, source_path)
            if mode == "160000" and object_type == "commit":
                destination_path.mkdir(parents=True, exist_ok=True)
            elif mode == "120000" and object_type == "blob":
                snapshot_symlink(source_path, destination_path, object_id, source)
            elif mode in {"100644", "100755"} and object_type == "blob":
                copy_regular_snapshot(
                    source_path,
                    destination_path,
                    expected_git_oid=object_id,
                    executable=mode == "100755",
                )
            else:
                raise engine.GateError(f"unsupported dependency tree entry: {name}/{relative}")
        validate_private_package_layout(private_lean, package)


def validate_private_package_snapshots(packages: list[dict[str, Any]]) -> None:
    expected_names = [package["name"] for package in packages if package["type"] == "git"]
    if expected_names != [record["name"] for record in _VERIFIED_PACKAGE_TREES]:
        raise engine.GateError("private dependency set does not match verified live snapshots")
    for package in packages:
        if package["type"] != "git":
            raise engine.GateError(f"unsupported non-git Lake dependency: {package['name']}")
        if next(
            record for record in _VERIFIED_PACKAGE_TREES if record["name"] == package["name"]
        )["revision"] != package["revision"]:
            raise engine.GateError(f"private dependency revision mismatch: {package['name']}")
        root = engine.LEAN_DIR / ".lake" / "packages" / package["name"]
        validate_private_package_layout(engine.LEAN_DIR, package)
        for mode, object_type, object_id, relative in _VERIFIED_PACKAGE_ENTRIES[package["name"]]:
            path = root / relative
            if mode == "160000" and object_type == "commit":
                if path.is_symlink() or not path.is_dir() or any(os.scandir(path)):
                    raise engine.GateError(f"private gitlink drift: {path}")
            elif object_type == "blob" and git_blob_oid(path, mode) != object_id:
                raise engine.GateError(f"private dependency byte drift: {path}")


def private_lake_bookkeeping_record() -> dict[str, Any]:
    return {
        "definition": (
            "Exact non-source Lake hash sidecars required to replay pinned dependency "
            "targets under --rehash; each is recomputed, never trusted as an input, and "
            "validated after every Lake command."
        ),
        "files": [
            {
                "bytes": len(payload),
                "path": path.as_posix(),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
            for path, payload in PRIVATE_LAKE_BOOKKEEPING
        ],
    }


def validate_private_lake_bookkeeping(
    private_lean: Path,
    *,
    require_complete: bool,
) -> None:
    for relative, expected in PRIVATE_LAKE_BOOKKEEPING:
        path = private_lean / relative
        if not os.path.lexists(path):
            if require_complete:
                raise engine.GateError(f"private Lake bookkeeping is missing: {path}")
            continue
        try:
            observed = bounded_source_snapshot(path, 1024)
        except (OSError, RuntimeError) as error:
            raise engine.GateError(
                f"private Lake bookkeeping is not a bounded regular file: {path}"
            ) from error
        if observed != expected:
            raise engine.GateError(f"private Lake bookkeeping drift: {path}")


def validate_private_input_snapshots() -> None:
    if not _PRIVATE_BUILD_ACTIVE:
        return
    if _PRIVATE_LOCAL_SOURCE_TREE is None:
        raise engine.GateError("private local source manifest is unavailable")
    if _PRIVATE_PACKAGE_OVERRIDE_PATH is None or _PRIVATE_PACKAGE_OVERRIDE_BYTES is None:
        raise engine.GateError("private dependency override snapshot is unavailable")
    if (
        bounded_source_snapshot(_PRIVATE_PACKAGE_OVERRIDE_PATH, 1024 * 1024)
        != _PRIVATE_PACKAGE_OVERRIDE_BYTES
    ):
        raise engine.GateError("private dependency override bytes drifted")
    current_local = regular_tree_record(
        engine.LEAN_DIR,
        definition=_PRIVATE_LOCAL_SOURCE_TREE["definition"],
        excluded_root_directories=frozenset({".lake"}),
        maximum_total_bytes=1024 * 1024 * 1024,
    )
    if current_local != _PRIVATE_LOCAL_SOURCE_TREE:
        raise engine.GateError("private local Lean source/configuration bytes drifted")
    validate_private_package_snapshots(locked_packages())
    validate_private_lake_bookkeeping(engine.LEAN_DIR, require_complete=False)


def sandbox_string(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def private_build_sandbox_profile(
    private_lean: Path,
    private_toolchain: Path,
    packages: list[dict[str, Any]],
) -> str:
    if _PRIVATE_PROCESS_HOME is None or _PRIVATE_PROCESS_TMP is None:
        raise engine.GateError("private sandbox process directories are unavailable")
    writable_directories = [
        _PRIVATE_PROCESS_HOME,
        _PRIVATE_PROCESS_TMP,
        private_lean / ".lake" / "build",
        private_lean / ".lake" / "config",
    ]
    for package in packages:
        writable_directories.append(
            private_lean / private_package_relative_directory(package) / ".lake"
        )
    for directory in writable_directories:
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    rules = [
        "(version 1)",
        "(deny default)",
        "(allow process*)",
        "(allow file-read*)",
        "(allow sysctl-read)",
        "(allow mach-lookup)",
        "(allow ipc-posix-shm)",
        "(allow signal)",
        f"(allow file-write* (literal {sandbox_string('/dev/null')}))",
    ]
    rules.extend(
        f"(allow file-write* (subpath {sandbox_string(str(path))}))"
        for path in writable_directories
    )
    rules.extend(
        f"(allow file-write* (literal {sandbox_string(str(private_lean / relative))}))"
        for relative, _payload in PRIVATE_LAKE_BOOKKEEPING
    )
    profile = "\n".join(rules) + "\n"
    if str(private_lean) not in profile or str(private_toolchain) in profile:
        raise engine.GateError("private sandbox profile construction failed closed")
    return profile


def verify_git_dependency_checkout(checkout: Path, revision: str) -> dict[str, Any]:
    global _VERIFIED_PACKAGE_ENTRIES
    checkout = Path(os.path.abspath(checkout))
    packages_root = (engine.LEAN_DIR / ".lake" / "packages").resolve()
    if (
        checkout.is_symlink()
        or not checkout.is_dir()
        or checkout.resolve().parent != packages_root
    ):
        raise engine.GateError(f"invalid dependency checkout path: {checkout}")
    git_directory = checkout / ".git"
    if not git_directory.is_dir() or git_directory.is_symlink():
        raise engine.GateError(f"dependency .git directory is not private: {checkout.name}")
    if git_bytes(checkout, "rev-parse", "--show-object-format").strip() != b"sha1":
        raise engine.GateError(f"unsupported dependency object format: {checkout.name}")
    actual = git_bytes(checkout, "rev-parse", "--verify", "HEAD^{commit}").decode().strip()
    if actual != revision:
        raise engine.GateError(
            f"package checkout mismatch for {checkout.name}: manifest={revision} checkout={actual}"
        )
    if git_bytes(checkout, "for-each-ref", "--format=%(refname)", "refs/replace").strip():
        raise engine.GateError(f"dependency replacement refs are forbidden: {checkout.name}")
    for relative in ("info/grafts", "objects/info/alternates"):
        if (git_directory / relative).exists() or (git_directory / relative).is_symlink():
            raise engine.GateError(f"dependency {relative} is forbidden: {checkout.name}")
    index_rows = git_bytes(checkout, "ls-files", "-v", "-z").split(b"\0")
    if any(row and not row.startswith(b"H ") for row in index_rows):
        raise engine.GateError(f"dependency index hiding/state flags are forbidden: {checkout.name}")
    git_bytes(
        checkout,
        "fsck", "--full", "--strict", "--no-reflogs", "--no-dangling", "--no-progress",
        revision,
    )
    raw_tree = git_bytes(checkout, "ls-tree", "-r", "-z", "--full-tree", revision)
    tracked_paths: set[str] = set()
    aggregate = hashlib.sha256()
    entry_count = 0
    verified_entries: list[tuple[str, str, str, str]] = []
    for record in raw_tree.split(b"\0"):
        if not record:
            continue
        try:
            metadata, raw_path = record.split(b"\t", 1)
            mode, object_type, object_id = metadata.split(b" ", 2)
        except ValueError as error:
            raise engine.GateError(f"malformed dependency tree: {checkout.name}") from error
        path_text = os.fsdecode(raw_path)
        path = Path(path_text)
        if path.is_absolute() or ".." in path.parts or path.parts[0] in {".git", ".lake"}:
            raise engine.GateError(f"unsafe dependency tree path: {checkout.name}")
        full_path = checkout / path
        require_real_path_components(checkout, full_path)
        mode_text = mode.decode("ascii")
        if mode_text == "160000" and object_type == b"commit":
            if full_path.is_symlink() or (
                full_path.exists()
                and (not full_path.is_dir() or any(os.scandir(full_path)))
            ):
                raise engine.GateError(
                    f"materialized unbound dependency gitlink is forbidden: {full_path}"
                )
            aggregate.update(record + b"\0")
            verified_entries.append(
                (mode_text, object_type.decode("ascii"), object_id.decode("ascii"), path.as_posix())
            )
            entry_count += 1
            continue
        if object_type != b"blob":
            raise engine.GateError(f"unsupported dependency tree entry: {full_path}")
        observed_oid = git_blob_oid(full_path, mode_text)
        if observed_oid.encode("ascii") != object_id:
            raise engine.GateError(f"tracked dependency byte drift: {full_path}")
        tracked_paths.add(path.as_posix())
        aggregate.update(record + b"\0")
        verified_entries.append(
            (mode_text, object_type.decode("ascii"), object_id.decode("ascii"), path.as_posix())
        )
        entry_count += 1
    if git_bytes(checkout, "rev-parse", "--verify", "HEAD^{commit}").decode().strip() != revision:
        raise engine.GateError(f"dependency HEAD changed during verification: {checkout.name}")
    git_bytes(
        checkout,
        "fsck", "--full", "--strict", "--no-reflogs", "--no-dangling", "--no-progress",
        revision,
    )
    tree = git_bytes(checkout, "rev-parse", "--verify", f"{revision}^{{tree}}").decode().strip()
    _VERIFIED_PACKAGE_ENTRIES[checkout.name] = tuple(verified_entries)
    return {
        "entry_count": entry_count,
        "name": checkout.name,
        "revision": revision,
        "tree_sha1": tree,
        "verified_worktree_sha256": aggregate.hexdigest(),
    }


def validate_spacecraft_package_checkouts(packages: list[dict[str, Any]]) -> None:
    global _VERIFIED_PACKAGE_TREES
    if _PRIVATE_BUILD_ACTIVE:
        validate_private_package_snapshots(packages)
        return
    _VERIFIED_PACKAGE_ENTRIES.clear()
    records = []
    for package in packages:
        if package["type"] != "git":
            continue
        records.append(
            verify_git_dependency_checkout(
                engine.LEAN_DIR / ".lake" / "packages" / package["name"],
                package["revision"],
            )
        )
    _VERIFIED_PACKAGE_TREES = records


def locked_packages() -> list[dict[str, Any]]:
    manifest = engine.strict_json_load(engine.LEAN_DIR / "lake-manifest.json")
    if not isinstance(manifest, dict):
        raise engine.GateError("lake-manifest.json root is not an object")
    return engine.normalized_packages(manifest)


def private_package_relative_directory(package: dict[str, Any]) -> Path:
    if package["type"] != "git":
        raise engine.GateError(f"unsupported non-git Lake dependency: {package['name']}")
    if not isinstance(package["name"], str):
        raise engine.GateError("Lake dependency name is not text")
    name_path = Path(package["name"])
    if (
        name_path.is_absolute()
        or len(name_path.parts) != 1
        or package["name"] in {"", ".", ".."}
    ):
        raise engine.GateError(f"unsafe Lake dependency name: {package['name']!r}")
    relative_directory = Path(".lake/packages") / name_path
    subdirectory = package["subdirectory"]
    if subdirectory is not None:
        if not isinstance(subdirectory, str):
            raise engine.GateError(
                f"Lake dependency subdirectory is not text: {package['name']}"
            )
        subdirectory_path = Path(subdirectory)
        if subdirectory_path.is_absolute() or ".." in subdirectory_path.parts:
            raise engine.GateError(
                f"unsafe Lake dependency subdirectory: {package['name']}"
            )
        relative_directory /= subdirectory_path
    return relative_directory


def validate_private_package_layout(
    private_lean: Path,
    package: dict[str, Any],
) -> None:
    package_root = private_lean / ".lake" / "packages" / package["name"]
    workspace = private_lean / private_package_relative_directory(package)
    try:
        require_real_path_components(package_root, workspace / ".component-check")
    except OSError as error:
        raise engine.GateError(
            f"private package path traverses a non-directory or symlink: {package['name']}"
        ) from error
    if workspace.is_symlink() or not workspace.is_dir():
        raise engine.GateError(
            f"private package workspace is not a real directory: {package['name']}"
    )
    for key in ("config_file", "manifest_file"):
        configured = package[key]
        if not isinstance(configured, str) or not configured:
            raise engine.GateError(
                f"unsafe Lake dependency {key}: {package['name']}"
            )
        relative = Path(configured)
        if relative.is_absolute() or ".." in relative.parts:
            raise engine.GateError(
                f"unsafe Lake dependency {key}: {package['name']}"
            )
        path = workspace / relative
        try:
            require_real_path_components(workspace, path)
        except OSError as error:
            raise engine.GateError(
                f"private package {key} traverses an invalid component: {package['name']}"
            ) from error
        if path.is_symlink():
            raise engine.GateError(
                f"private package {key} is a symlink: {package['name']}"
            )


def private_package_override_bytes(packages: list[dict[str, Any]]) -> bytes:
    names = [package.get("name") for package in packages]
    if len(names) != len(set(names)):
        raise engine.GateError("Lake manifest dependency names are not unique")
    entries = []
    for package in packages:
        relative_directory = private_package_relative_directory(package)
        for key in ("config_file", "manifest_file"):
            configured_path = package[key]
            if (
                not isinstance(configured_path, str)
                or not configured_path
                or Path(configured_path).is_absolute()
                or ".." in Path(configured_path).parts
            ):
                raise engine.GateError(
                    f"unsafe Lake dependency {key}: {package['name']}"
                )
        if not isinstance(package["inherited"], bool):
            raise engine.GateError(f"invalid Lake inheritance flag: {package['name']}")
        if package["scope"] is not None and not isinstance(package["scope"], str):
            raise engine.GateError(f"invalid Lake dependency scope: {package['name']}")
        entries.append({
            "configFile": package["config_file"],
            "dir": relative_directory.as_posix(),
            "inherited": package["inherited"],
            "manifestFile": package["manifest_file"],
            "name": package["name"],
            "scope": package["scope"] or "",
            "type": "path",
        })
    return engine.pretty_bytes({"packages": entries, "version": "1.2.0"})


def private_package_override_record(packages: list[dict[str, Any]]) -> dict[str, Any]:
    payload = private_package_override_bytes(packages)
    return {
        "definition": (
            "Deterministic Lake path overrides that force every manifest-pinned Git "
            "dependency to load only from its already verified private tracked-blob snapshot."
        ),
        "package_count": len(packages),
        "package_names": [package["name"] for package in packages],
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def build_spacecraft_checker() -> None:
    packages = locked_packages()
    validate_spacecraft_package_checkouts(packages)
    if _CLEAN_REBUILD:
        engine.run(["lake", "clean"], cwd=engine.LEAN_DIR, allow_stderr=True)
        validate_spacecraft_package_checkouts(packages)
    engine.run(
        ["lake", "build", engine.CHECKER_TARGET],
        cwd=engine.LEAN_DIR,
        allow_stderr=True,
    )
    if _PRIVATE_BUILD_ACTIVE:
        validate_private_lake_bookkeeping(
            engine.LEAN_DIR,
            require_complete=True,
        )
    validate_spacecraft_package_checkouts(packages)


def validate_pinned_configuration_payloads(payloads: dict[str, bytes]) -> None:
    if set(payloads) != set(PINNED_CONFIGURATION_SHA256):
        raise engine.GateError("spacecraft proof configuration set mismatch")
    for path, expected in PINNED_CONFIGURATION_SHA256.items():
        if engine.sha256_bytes(payloads[path]) != expected:
            raise engine.GateError(
                f"spacecraft proof configuration drift: {path}"
            )


def validate_pinned_configurations() -> None:
    payloads = {
        path: bounded_source_snapshot(engine.REPO_ROOT / path, 16 * 1024 * 1024)
        for path in PINNED_CONFIGURATION_SHA256
    }
    validate_pinned_configuration_payloads(payloads)


def parse_spacecraft_imports(path: Path, code: str) -> list[str]:
    imports: list[str] = []
    for line_number, line in enumerate(code.splitlines(), start=1):
        contains_import = re.search(r"\bimport\b", line) is not None
        match = re.fullmatch(r"\s*import\s+(.+?)\s*", line)
        if not contains_import:
            continue
        if match is None:
            raise engine.GateError(
                f"unsupported import syntax at {engine.repo_relative(path)}:{line_number}"
            )
        tokens = match.group(1).split()
        if not tokens or any(
            SPACECRAFT_MODULE_RE.fullmatch(token) is None for token in tokens
        ):
            raise engine.GateError(
                f"unsupported import syntax at {engine.repo_relative(path)}:{line_number}"
            )
        imports.extend(tokens)
    return imports


def collect_engine_semantic_sections() -> dict[str, Any]:
    source_closure = _collect_engine_source_closure()
    toolchain, observed_compiler = _collect_engine_toolchain()
    theorem_axioms = _run_engine_axiom_audit()
    return {
        "fragment": engine.FRAGMENT,
        "proof": {
            "axiom_audit_command": (
                "lake env lean /dev/stdin with checked-in #print axioms set"
            ),
            "axiom_policy": {
                "allowed_exactly": list(engine.ALLOWED_AXIOMS),
                "forbidden": ["sorryAx", "any additional axiom"],
            },
            "theorems": theorem_axioms,
        },
        "source_closure": source_closure,
        "toolchain": toolchain,
        "_observed_compiler": observed_compiler,
    }


def collect_spacecraft_proof_sections():
    sections = collect_engine_semantic_sections()
    validate_spacecraft_package_checkouts(locked_packages())
    sections["toolchain"]["package_checkout_policy"] = PACKAGE_CHECKOUT_POLICY
    sections["toolchain"]["verified_package_trees"] = list(
        _VERIFIED_PACKAGE_TREES
    )
    files = [
        {
            "path": "release/tools/spacecraft_burn_proof_identity.py",
            "sha256": WRAPPER_SOURCE_SHA256,
        },
        {
            "path": "release/tools/gaussian_proof_identity.py",
            "sha256": ENGINE_SOURCE_SHA256,
        },
    ]
    sections["generator"] = {
        "definition": (
            "Complete repository-local Python generator source closure used to construct "
            "and verify this identity. The interpreter and standard library remain in the "
            "explicit build-platform trusted base."
        ),
        "files": files,
    }
    return sections


def trusted_platform_launcher(role: str, path: Path) -> dict[str, Any]:
    path = Path(os.path.abspath(path))
    before = path.lstat()
    symlink_target: str | None = None
    if stat.S_ISLNK(before.st_mode):
        symlink_target = os.readlink(path)
        after = path.lstat()
        stable = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
        if any(getattr(before, field) != getattr(after, field) for field in stable):
            raise engine.GateError(f"platform launcher symlink changed: {path}")
    resolved = path.resolve(strict=True)
    record = stable_regular_file_record(resolved)
    return {
        "bytes": record["bytes"],
        "invocation_path": str(path),
        "invocation_symlink_target": symlink_target,
        "resolved_path": str(resolved),
        "role": role,
        "sha256": record["sha256"],
    }


def collect_spacecraft_checker(
    source_closure: dict[str, Any],
    toolchain: dict[str, Any],
    observed_compiler: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    checker, base_attestation = _collect_engine_checker(
        source_closure,
        toolchain,
        observed_compiler,
    )
    if set(_OBSERVED_TOOLCHAIN_BINARIES) != {"lake", "lean", "leanc"}:
        raise engine.GateError("Lean launcher identity was not observed during the build")
    observed_lean = _OBSERVED_TOOLCHAIN_BINARIES["lean"]
    if (
        observed_lean["bytes"] != observed_compiler["executable_bytes"]
        or observed_lean["sha256"] != observed_compiler["executable_sha256"]
    ):
        raise engine.GateError("observed Lean executable is not the recorded launcher byte")
    token = pinned_toolchain_token(engine.LEAN_DIR)
    if _PRIVATE_BUILD_ACTIVE:
        if _PRIVATE_TOOLCHAIN_TREE is None:
            raise engine.GateError("complete private Lean toolchain identity is unavailable")
        toolchain_tree = _PRIVATE_TOOLCHAIN_TREE
    else:
        toolchain_tree = complete_toolchain_tree_record(
            active_pinned_toolchain_root(engine.LEAN_DIR),
            token,
        )
    attestation_body = {
        key: value
        for key, value in base_attestation.items()
        if key != "attestation_digest_sha256"
    }
    attestation_body["build_environment"] = {
        "dependency_path_overrides": private_package_override_record(locked_packages()),
        "isolation_policy": BUILD_ISOLATION_POLICY,
        "lake_generated_bookkeeping": private_lake_bookkeeping_record(),
        "lean_launcher_binaries": [
            _OBSERVED_TOOLCHAIN_BINARIES[name] for name in ("lake", "lean", "leanc")
        ],
        "lean_toolchain_tree": toolchain_tree,
        "trusted_platform_launchers": [
            trusted_platform_launcher("python-launcher", Path("/usr/bin/python3")),
            trusted_platform_launcher("python-interpreter", Path(sys.executable)),
            trusted_platform_launcher("git-client", TRUSTED_GIT),
            trusted_platform_launcher("sandbox-launcher", TRUSTED_SANDBOX_EXEC),
        ],
    }
    attestation_body["claim_boundary"] = (
        "This binds the complete private Lean toolchain regular-file tree, admitted source "
        "and dependency bytes, observed checker bytes, and named platform launchers. It is "
        "reproducibility/build-provenance evidence, not a proof of Python, Git, macOS, "
        "sandbox-exec, dyld, libSystem, the kernel, hardware, or supply-chain correctness."
    )
    return checker, {
        **attestation_body,
        "attestation_digest_sha256": engine.sha256_bytes(
            engine.canonical_bytes(attestation_body)
        ),
    }


SPACECRAFT_LANE = engine.LaneConfig(
    schema="jackal-spacecraft-burn-proof-identity-v1",
    identity_name="spacecraft_burn_proof_identity_v1.json",
    checker_path="proofs/lean/.lake/build/bin/jackal_spacecraft_burn_check",
    checker_target="jackal_spacecraft_burn_check",
    root_modules=("JackalIv.Spacecraft.CertMain",),
    fragment={
        "assurance": "formal-bounded",
        "certificate_magic": "jackal-spacecraft-burn-cert v2",
        "checker_boolean_definition": "JackalIv.Spacecraft.checkBurnCert",
        "checker_entrypoint_definition": "main (Spacecraft.CertMain)",
        "checker_executable": "jackal_spacecraft_burn_check",
        "checker_root_module": "JackalIv.Spacecraft.CertMain",
        "checker_build_cache_policy": (
            "identity generation builds only open-once snapshots of local and pinned "
            "dependency source bytes in a private fresh workspace without live caches"
        ),
        "family": "spacecraft-finite-burn-model-conditional-v2",
        "lane": "spacecraft-burn",
        "model_id": "jackal-spacecraft-finite-burn-ode-v2",
        "parser_definition": "JackalIv.Spacecraft.parseBurnWitness",
        "release_epoch": "v1.7.5",
        "request_digest": "03bcad618ad60114007c74a384eb8c9432e3755b817e74bd5bdc9bd1ba6df3e7",
        "runtime_alternate_implementation_boundary": (
            "none in the local source closure; no native_decide or implemented_by"
        ),
        "soundness_theorem": "JackalIv.Spacecraft.spacecraft_burn_certified_safe",
        "theorem_premises": [
            "checkBurnCert raw requestDigest modelId epoch = .ok accepted (runtime checked)"
        ],
        "premises_not_discharged_by_checker": [],
    },
    theorems=(
        "JackalIv.Spacecraft.spacecraft_burn_certified_safe",
        "JackalIv.Spacecraft.spacecraft_burn_universal_safe",
        "JackalIv.Spacecraft.spacecraft_burn_certificate_sound",
        "JackalIv.Spacecraft.checkBurnWitness_sound",
        "JackalIv.Spacecraft.checkBurnWitness_universal_sound",
        "JackalIv.Spacecraft.checkBurnWitness_margin_bound",
        "JackalIv.Spacecraft.checkBranchesCert_sound",
        "JackalIv.Spacecraft.checkBranchesCert_universal_sound",
        "JackalIv.Spacecraft.checkBranchesCert_margin_bound",
        "JackalIv.Spacecraft.checkBranchCert_sound",
        "JackalIv.Spacecraft.checkBranchCert_universal_sound",
        "JackalIv.Spacecraft.checkBranchCert_margin_bound",
        "JackalIv.Spacecraft.checkOrbitSteps_sound",
        "JackalIv.Spacecraft.checkOrbitSteps_margin_bound",
        "JackalIv.Spacecraft.checked_chain_state_safe",
        "JackalIv.Spacecraft.checked_chain_state_margin_bound",
        "JackalIv.Spacecraft.chain_state_at_exists",
        "JackalIv.Spacecraft.checked_steps_nonvacuous",
        "JackalIv.Spacecraft.checked_steps_compose",
        "JackalIv.Spacecraft.exists_classicalSolution_of_checkStep",
        "JackalIv.Spacecraft.orbitPostprocess_sound",
        "JackalIv.Spacecraft.orbitalEccentricityFormula_eq_vector",
        "JackalIv.Spacecraft.intersection_sound",
        "JackalIv.Spacecraft.supplied_inputs_covered",
        "JackalIv.Spacecraft.supplied_cutoff_time_covered",
        "JackalIv.Spacecraft.checkCutoffCoverage_sound",
        "JackalIv.Spacecraft.fieldEnclosed",
        "JackalIv.Spacecraft.burnField_contDiffOn_of_domain",
        "JackalIv.Spacecraft.burnField_locallyLipschitzOn_of_domain",
    ),
    allowed_local_constructs={},
)


def write_payload_atomic(
    path: Path,
    payload: bytes,
    mode: int,
    *,
    allow_replace: bool,
) -> None:
    path = Path(os.path.abspath(path))
    try:
        resolved_parent = path.parent.resolve(strict=True)
    except OSError as error:
        raise engine.GateError(f"output parent must already exist: {path.parent}") from error
    if resolved_parent != path.parent:
        raise engine.GateError(f"output parent path must not traverse symlinks: {path.parent}")
    parent_descriptor = os.open(
        path.parent,
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0),
    )
    descriptor: int | None = None
    temporary_name: str | None = None
    try:
        try:
            existing = os.stat(path.name, dir_fd=parent_descriptor, follow_symlinks=False)
        except FileNotFoundError:
            existing = None
        if existing is not None:
            if not allow_replace:
                raise engine.GateError(f"output path already exists: {path}")
            if not stat.S_ISREG(existing.st_mode):
                raise engine.GateError(f"replaceable output is not a regular file: {path}")
        for attempt in range(128):
            candidate = f".{path.name}.tmp-{os.getpid()}-{attempt}"
            try:
                descriptor = os.open(
                    candidate,
                    os.O_WRONLY
                    | os.O_CREAT
                    | os.O_EXCL
                    | getattr(os, "O_CLOEXEC", 0),
                    mode,
                    dir_fd=parent_descriptor,
                )
            except FileExistsError:
                continue
            temporary_name = candidate
            break
        if descriptor is None or temporary_name is None:
            raise engine.GateError(f"could not reserve an exclusive output name: {path}")
        view = memoryview(payload)
        offset = 0
        while offset < len(view):
            written = os.write(descriptor, view[offset:])
            if written <= 0:
                raise engine.GateError(f"zero-length identity output write: {path}")
            offset += written
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = None
        os.rename(
            temporary_name,
            path.name,
            src_dir_fd=parent_descriptor,
            dst_dir_fd=parent_descriptor,
        )
        temporary_name = None
        os.fsync(parent_descriptor)
    except BaseException:
        if descriptor is not None:
            os.close(descriptor)
        if temporary_name is not None:
            try:
                os.unlink(temporary_name, dir_fd=parent_descriptor)
            except OSError:
                pass
        raise
    finally:
        os.close(parent_descriptor)


def ensure_repo_output_parent(path: Path) -> None:
    path = Path(os.path.abspath(path))
    root = LIVE_REPO_ROOT.resolve(strict=True)
    try:
        relative_parent = path.parent.relative_to(root)
    except ValueError as error:
        raise engine.GateError(f"fixed build output escaped the repository: {path}") from error
    current = root
    for part in relative_parent.parts:
        candidate = current / part
        try:
            status = candidate.lstat()
        except FileNotFoundError:
            candidate.mkdir(mode=0o755)
            status = candidate.lstat()
        if candidate.is_symlink() or not stat.S_ISDIR(status.st_mode):
            raise engine.GateError(f"fixed build output parent is unsafe: {candidate}")
        current = candidate


def validate_identity_output_path(path: Path, default_identity: Path) -> tuple[Path, bool]:
    path = Path(os.path.abspath(path))
    default_identity = Path(os.path.abspath(default_identity))
    try:
        inside_repository = path.is_relative_to(LIVE_REPO_ROOT.resolve(strict=True))
    except OSError as error:
        raise engine.GateError("live repository root is unavailable") from error
    if inside_repository and path != default_identity:
        raise engine.GateError(
            "a proof identity written inside the repository must use the canonical evidence path"
        )
    if path != default_identity and (path.exists() or path.is_symlink()):
        raise engine.GateError(f"explicit identity output must be new: {path}")
    return path, path == default_identity


def command_generate_private(args) -> None:
    global _CLEAN_REBUILD, _PRIVATE_BUILD_ACTIVE
    global _PRIVATE_ELAN_HOME, _PRIVATE_LOCAL_SOURCE_TREE
    global _PRIVATE_PACKAGE_OVERRIDE_BYTES, _PRIVATE_PACKAGE_OVERRIDE_PATH
    global _PRIVATE_PROCESS_HOME, _PRIVATE_PROCESS_TMP, _PRIVATE_SANDBOX_PROFILE
    global _PRIVATE_TOOLCHAIN_ROOT, _PRIVATE_TOOLCHAIN_TREE
    engine.configure_lane(args.lane)
    live_default_identity = engine.DEFAULT_IDENTITY
    requested_output = (
        Path(os.path.abspath(args.output)) if args.output else live_default_identity
    )
    output, replace_identity = validate_identity_output_path(
        requested_output,
        live_default_identity,
    )
    packages = locked_packages()
    live_source_closure = engine.collect_source_closure()
    lean_prefix = Path("proofs/lean")
    local_paths = {
        Path(item["path"]).relative_to(lean_prefix)
        for item in live_source_closure["files"]
    }
    local_paths.update(
        Path(path).relative_to(lean_prefix) for path in PINNED_CONFIGURATION_SHA256
    )
    token = pinned_toolchain_token(LIVE_LEAN_DIR)
    live_toolchain = live_pinned_toolchain_root(LIVE_LEAN_DIR)
    _OBSERVED_TOOLCHAIN_BINARIES.clear()
    with tempfile.TemporaryDirectory(prefix="jackal-spacecraft-proof-build-") as directory:
        private_session = Path(directory).resolve(strict=True)
        os.chmod(private_session, 0o700)
        private_root = private_session / "repo"
        private_lean = private_root / "proofs" / "lean"
        private_elan = private_session / "private-elan"
        private_toolchain_parent = private_elan / "toolchains"
        private_toolchain_parent.mkdir(mode=0o700, parents=True)
        private_toolchain = private_toolchain_parent / toolchain_directory_name(token)
        private_home = private_session / "process-home"
        private_tmp = private_session / "process-tmp"
        private_inputs = private_session / "build-inputs"
        private_home.mkdir(mode=0o700)
        private_tmp.mkdir(mode=0o700)
        private_inputs.mkdir(mode=0o700)
        package_override_bytes = private_package_override_bytes(packages)
        package_override_path = private_inputs / "lake-package-overrides.json"
        write_payload_atomic(
            package_override_path,
            package_override_bytes,
            0o600,
            allow_replace=False,
        )
        private_local_record = snapshot_local_lean_workspace(
            LIVE_LEAN_DIR,
            private_lean,
            local_paths,
        )
        snapshot_dependency_workspaces(LIVE_LEAN_DIR, private_lean, packages)
        private_toolchain_record = snapshot_complete_toolchain(
            live_toolchain,
            private_toolchain,
            token,
        )
        previous_root, previous_lean = engine.REPO_ROOT, engine.LEAN_DIR
        previous_private, previous_clean = _PRIVATE_BUILD_ACTIVE, _CLEAN_REBUILD
        previous_elan, previous_home, previous_tmp = (
            _PRIVATE_ELAN_HOME,
            _PRIVATE_PROCESS_HOME,
            _PRIVATE_PROCESS_TMP,
        )
        previous_profile = _PRIVATE_SANDBOX_PROFILE
        previous_override_bytes = _PRIVATE_PACKAGE_OVERRIDE_BYTES
        previous_override_path = _PRIVATE_PACKAGE_OVERRIDE_PATH
        previous_toolchain_root = _PRIVATE_TOOLCHAIN_ROOT
        previous_toolchain_tree = _PRIVATE_TOOLCHAIN_TREE
        previous_local_tree = _PRIVATE_LOCAL_SOURCE_TREE
        try:
            engine.REPO_ROOT = private_root
            engine.LEAN_DIR = private_lean
            _PRIVATE_ELAN_HOME = private_elan
            _PRIVATE_PROCESS_HOME = private_home
            _PRIVATE_PROCESS_TMP = private_tmp
            _PRIVATE_PACKAGE_OVERRIDE_BYTES = package_override_bytes
            _PRIVATE_PACKAGE_OVERRIDE_PATH = package_override_path
            _PRIVATE_TOOLCHAIN_ROOT = private_toolchain
            _PRIVATE_TOOLCHAIN_TREE = private_toolchain_record
            _PRIVATE_LOCAL_SOURCE_TREE = private_local_record
            _PRIVATE_BUILD_ACTIVE = True
            _CLEAN_REBUILD = True
            _PRIVATE_SANDBOX_PROFILE = private_build_sandbox_profile(
                private_lean,
                private_toolchain,
                packages,
            )
            validate_pinned_configurations()
            validate_private_input_snapshots()
            build_spacecraft_checker()
            record = engine.build_record()
            validate_private_input_snapshots()
            private_checker = private_root / engine.CHECKER_REL
            checker_bytes = bounded_source_snapshot(
                private_checker, 512 * 1024 * 1024
            )
            if hashlib.sha256(checker_bytes).hexdigest() != record["checker"]["sha256"]:
                raise engine.GateError("private checker changed after identity construction")
            if complete_toolchain_tree_record(private_toolchain, token) != private_toolchain_record:
                raise engine.GateError("private Lean toolchain changed during the build")
        finally:
            engine.REPO_ROOT, engine.LEAN_DIR = previous_root, previous_lean
            _PRIVATE_BUILD_ACTIVE, _CLEAN_REBUILD = previous_private, previous_clean
            _PRIVATE_ELAN_HOME, _PRIVATE_PROCESS_HOME, _PRIVATE_PROCESS_TMP = (
                previous_elan,
                previous_home,
                previous_tmp,
            )
            _PRIVATE_SANDBOX_PROFILE = previous_profile
            _PRIVATE_PACKAGE_OVERRIDE_BYTES = previous_override_bytes
            _PRIVATE_PACKAGE_OVERRIDE_PATH = previous_override_path
            _PRIVATE_TOOLCHAIN_ROOT = previous_toolchain_root
            _PRIVATE_TOOLCHAIN_TREE = previous_toolchain_tree
            _PRIVATE_LOCAL_SOURCE_TREE = previous_local_tree

    if bounded_source_snapshot(WRAPPER_PATH) != WRAPPER_SOURCE_BYTES:
        raise engine.GateError("spacecraft proof-identity wrapper changed during generation")
    if bounded_source_snapshot(ENGINE_PATH) != ENGINE_SOURCE_BYTES:
        raise engine.GateError("delegated proof-identity engine changed during generation")
    checker_output = LIVE_REPO_ROOT / engine.CHECKER_REL
    ensure_repo_output_parent(checker_output)
    write_payload_atomic(checker_output, checker_bytes, 0o755, allow_replace=True)
    write_payload_atomic(
        output,
        engine.pretty_bytes(record),
        0o644,
        allow_replace=replace_identity,
    )
    shown = (
        output.relative_to(LIVE_REPO_ROOT).as_posix()
        if output.is_relative_to(LIVE_REPO_ROOT)
        else str(output)
    )
    print(
        f"GENERATED {shown} identity_sha256={record['identity_digest_sha256']} "
        f"checker_sha256={record['checker']['sha256']} private_fresh_build=true"
    )


def main() -> int:
    global _CLEAN_REBUILD
    engine.LANES["spacecraft-burn"] = SPACECRAFT_LANE
    engine.__file__ = str(Path(__file__).resolve())
    engine.collect_proof_sections = collect_spacecraft_proof_sections
    engine.collect_checker = collect_spacecraft_checker
    engine.parse_imports = parse_spacecraft_imports
    engine.run = run_isolated
    engine.build_checker = build_spacecraft_checker
    engine.command_generate = command_generate_private
    engine.validate_package_checkouts = validate_spacecraft_package_checkouts
    engine.FORBIDDEN_LOCAL_CONSTRUCTS = {
        **engine.FORBIDDEN_LOCAL_CONSTRUCTS,
        "axiom_declaration": SPACECRAFT_AXIOM_DECLARATION_RE,
        "implemented_by": SPACECRAFT_IMPLEMENTED_BY_RE,
    }
    validate_pinned_configurations()
    if len(sys.argv) < 2 or sys.argv[1] not in {"generate", "check"}:
        print("usage: spacecraft_burn_proof_identity.py {generate|check} [options]", file=sys.stderr)
        return 2
    _CLEAN_REBUILD = sys.argv[1] == "generate"
    if any(argument == "--lane" or argument.startswith("--lane=") for argument in sys.argv[2:]):
        print("--lane is fixed to spacecraft-burn by this wrapper", file=sys.stderr)
        return 2
    sys.argv[2:2] = ["--lane", "spacecraft-burn"]
    return engine.main()


if __name__ == "__main__":
    raise SystemExit(main())
