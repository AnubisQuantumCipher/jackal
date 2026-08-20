#!/usr/bin/env python3
"""Fail-closed MCP bridge for the sealed JACKAL macOS runtime."""

from __future__ import annotations

import asyncio
from collections import deque
import contextlib
import copy
import errno
import hashlib
import hmac
import json
import math
import os
import re
import selectors
import signal
import socket
import stat
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any, Callable, Mapping, Protocol, Sequence, cast


sys.dont_write_bytecode = True


DRAFT_07 = "http://json-schema.org/draft-07/schema#"
LATEST_PROTOCOL_VERSION = "2025-11-25"
SUPPORTED_PROTOCOL_VERSIONS = frozenset(
    {LATEST_PROTOCOL_VERSION, "2025-06-18", "2025-03-26", "2024-11-05"}
)
SUPPORTED_ARGUMENT_TYPES = frozenset({"string", "object"})
EXPECTED_TOOL_COUNT = 41
TOOL_TIMEOUT_SECONDS = 3600.0
TERMINATE_GRACE_SECONDS = 0.5
LEADER_POLL_SECONDS = 0.01
MAX_REQUEST_LINE_BYTES = 1024 * 1024
MAX_CATALOG_BYTES = 2 * 1024 * 1024
MAX_WRAPPER_MODULE_BYTES = 2 * 1024 * 1024
MAX_STDOUT_BYTES = 16 * 1024 * 1024
MAX_STDERR_BYTES = 1024 * 1024
MAX_ERROR_RESPONSE_BYTES = 1024
MAX_ACTIVE_CALLS = 8
MAX_TRANSPORT_TASKS = 16
MAX_JSON_DEPTH = 64
MAX_MCP_RESPONSE_BYTES = (2 * MAX_STDOUT_BYTES) + (2 * 1024 * 1024)
MAX_RESPONSE_QUEUE_BYTES = 2 * MAX_MCP_RESPONSE_BYTES
STDIO_DRAIN_TIMEOUT = 0.5
PROCESS_GROUP_OBSERVATION_BYTES = 64 * 1024
PROCESS_GROUP_OBSERVATION_TIMEOUT = 0.5
_IDENTITY_LINE = re.compile(r"([0-9a-f]{64})  ([^\n]+)", re.ASCII)

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603
REQUEST_CANCELLED = -32800
BACKEND_TIMEOUT = -32001
BACKEND_ERROR = -32002


class AdapterError(RuntimeError):
    """Base class for bounded adapter failures."""


class CatalogError(AdapterError):
    """The runtime tool catalog is not the exact supported shape."""


class StartupError(AdapterError):
    """Production startup could not establish plugin/runtime identity."""


class ProtocolError(AdapterError):
    def __init__(self, code: int, message: str, request_id: str | int | None = None):
        super().__init__(message)
        self.code = code
        self.request_id = request_id


class BackendFailure(AdapterError):
    pass


class BackendTimedOut(BackendFailure):
    pass


class CallCancelled(BackendFailure):
    pass


class _DuplicateJSONKey(ValueError):
    pass


class _ProvisionerAPI(Protocol):
    EPOCH: str
    ASSET: str
    PACKAGE_SIZE: int
    PACKAGE_SHA256: str
    SHA256SUMS_SHA256: str
    SELFTEST_TIMEOUT: float
    SELFTEST_OUTPUT_LIMIT: int

    def validate_host(self) -> None: ...

    def default_locator_path(self) -> Path: ...

    def validate_runtime(self, runtime: Path, **kwargs: Any) -> object: ...

    def create_runtime_snapshot(self, runtime: Path, **kwargs: Any) -> object: ...

    def runtime_subprocess_environment(
        self, environ: Mapping[str, str] | None = None
    ) -> dict[str, str]: ...


@dataclass
class _CallState:
    request_id: str | int
    cancelled: asyncio.Event = field(default_factory=asyncio.Event)
    process: subprocess.Popen[bytes] | None = None
    runner: _AnchoredBackendRunner | None = None
    worker: asyncio.Task[dict[str, Any]] | None = None
    term_sent: bool = False
    kill_sent: bool = False
    anchor_lost: bool = False
    leader_status: int | None = None
    reaped: bool = False


def plugin_root_from_server(server_path: Path | str = Path(__file__)) -> Path:
    """Resolve the plugin root from either source or installed-cache layout."""
    path = Path(server_path).resolve(strict=True)
    if path.name != "server.py" or path.parent.name != "mcp":
        raise StartupError("server path is not in the canonical mcp layout")
    return path.parents[1]


def _require_exact_keys(value: dict[str, Any], required: set[str], subject: str) -> None:
    if set(value) != required:
        raise CatalogError(f"{subject} has an unsupported shape")


def _tool_definition(record: object) -> dict[str, Any]:
    if not isinstance(record, dict):
        raise CatalogError("tool record is not an object")
    _require_exact_keys(record, {"name", "description", "arguments", "returns"}, "tool record")
    name = record["name"]
    description = record["description"]
    arguments = record["arguments"]
    if not isinstance(name, str) or not name or len(name) > 128:
        raise CatalogError("tool name is invalid")
    if not isinstance(description, str) or not description or len(description) > 16_384:
        raise CatalogError(f"tool description is invalid: {name!r}")
    if not isinstance(arguments, dict):
        raise CatalogError(f"tool arguments are not an object: {name!r}")

    properties: dict[str, dict[str, str]] = {}
    required: list[str] = []
    for argument_name, argument in arguments.items():
        if (
            not isinstance(argument_name, str)
            or not argument_name
            or len(argument_name) > 128
            or not isinstance(argument, dict)
        ):
            raise CatalogError(f"invalid argument record: {name!r}")
        _require_exact_keys(argument, {"type", "required", "help"}, "argument record")
        argument_type = argument["type"]
        is_required = argument["required"]
        help_text = argument["help"]
        if argument_type not in SUPPORTED_ARGUMENT_TYPES:
            raise CatalogError(f"unsupported argument type: {name!r}.{argument_name}")
        if not isinstance(is_required, bool):
            raise CatalogError(f"argument required flag is not boolean: {name!r}.{argument_name}")
        if not isinstance(help_text, str) or not help_text or len(help_text) > 16_384:
            raise CatalogError(f"argument help is invalid: {name!r}.{argument_name}")
        properties[argument_name] = {"type": argument_type, "description": help_text}
        if is_required:
            required.append(argument_name)

    return {
        "name": name,
        "description": description,
        "inputSchema": {
            "$schema": DRAFT_07,
            "type": "object",
            "properties": properties,
            "required": required,
            "additionalProperties": False,
        },
    }


def build_tool_definitions(
    document: object, *, expected_count: int = EXPECTED_TOOL_COUNT
) -> tuple[dict[str, Any], ...]:
    """Strictly convert a JACKAL tools.json document to MCP tool definitions."""
    if not isinstance(expected_count, int) or isinstance(expected_count, bool) or expected_count < 1:
        raise CatalogError("expected tool count is invalid")
    if not isinstance(document, dict) or not isinstance(document.get("tools"), list):
        raise CatalogError("tool catalog is not an object containing a tools array")
    records = document["tools"]
    if len(records) != expected_count:
        raise CatalogError("tool catalog count does not match the wrapper-side expectation")
    definitions = tuple(_tool_definition(record) for record in records)
    names = [definition["name"] for definition in definitions]
    if len(set(names)) != len(names):
        raise CatalogError("tool catalog contains duplicate names")
    return definitions


def backend_result(value: object) -> dict[str, Any]:
    """Wrap one backend JSON object without changing its assurance semantics."""
    if not isinstance(value, dict):
        raise BackendFailure("backend result is not a JSON object")
    try:
        text = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as error:
        raise BackendFailure("backend result is not strict JSON") from error
    return {
        "content": [{"type": "text", "text": text}],
        "structuredContent": copy.deepcopy(value),
    }


def _object_pairs(pairs: Sequence[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise _DuplicateJSONKey("duplicate JSON object key")
        value[key] = item
    return value


def _reject_json_constant(unused: str) -> None:
    raise ValueError("non-finite JSON number")


def _strict_json_loads(text: str) -> Any:
    try:
        value = json.loads(
            text,
            object_pairs_hook=_object_pairs,
            parse_constant=_reject_json_constant,
        )
    except RecursionError as error:
        raise ValueError("JSON nesting exceeds limit") from error
    stack: list[tuple[object, int]] = [(value, 1)]
    while stack:
        item, depth = stack.pop()
        if isinstance(item, dict):
            if depth > MAX_JSON_DEPTH:
                raise ValueError("JSON nesting exceeds limit")
            stack.extend((child, depth + 1) for child in item.values())
        elif isinstance(item, list):
            if depth > MAX_JSON_DEPTH:
                raise ValueError("JSON nesting exceeds limit")
            stack.extend((child, depth + 1) for child in item)
    return value


def _group_observation_is_quiescent(output: bytes | bytearray, process_group: int) -> bool:
    try:
        members = []
        for line in bytes(output).decode("ascii").splitlines():
            fields = line.split()
            if len(fields) != 2 or not fields[0].isdigit():
                raise ValueError
            members.append((int(fields[0]), fields[1]))
    except (TypeError, UnicodeDecodeError, ValueError) as error:
        raise BackendFailure("backend process-group observation output is invalid") from error
    return (
        bool(members)
        and any(pid == process_group for pid, unused_state in members)
        and all(state.startswith("Z") for unused_pid, state in members)
    )


def _exited_group_has_only_zombie_members(process_group: int) -> bool:
    """Affirm a completed group has its leader and only zombie members."""
    try:
        observer = subprocess.Popen(
            ["/bin/ps", "-o", "pid=,state=", "-g", str(process_group)],
            env={"PATH": "/usr/bin:/bin:/usr/sbin:/sbin"},
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            close_fds=True,
        )
    except OSError as error:
        raise BackendFailure("cannot inspect completed backend process group") from error
    if observer.stdout is None:
        observer.kill()
        observer.wait()
        raise BackendFailure("backend process-group observer pipe is unavailable")
    selector: selectors.BaseSelector | None = None
    output = bytearray()
    deadline = time.monotonic() + PROCESS_GROUP_OBSERVATION_TIMEOUT
    try:
        try:
            selector = selectors.DefaultSelector()
        except OSError as error:
            raise BackendFailure("backend process-group observer setup failed") from error
        selector.register(observer.stdout, selectors.EVENT_READ)
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise BackendFailure("backend process-group observation timed out")
            for key, unused in selector.select(min(remaining, 0.05)):
                allowance = PROCESS_GROUP_OBSERVATION_BYTES - len(output) + 1
                chunk = os.read(key.fd, min(64 * 1024, max(1, allowance)))
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                output.extend(chunk)
                if len(output) > PROCESS_GROUP_OBSERVATION_BYTES:
                    raise BackendFailure(
                        "backend process-group observation exceeds output limit"
                    )
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise BackendFailure("backend process-group observation timed out")
        observer_return_code = observer.wait(timeout=remaining)
        if observer_return_code not in (0, 1):
            raise BackendFailure("backend process-group observation refused")
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
                    raise BackendFailure(
                        "backend process-group observer did not exit after bounded cleanup"
                    ) from error
        raise
    finally:
        if selector is not None:
            selector.close()
        observer.stdout.close()
    if observer_return_code == 1 and not output:
        return False
    return _group_observation_is_quiescent(output, process_group)


class _AnchoredBackendRunner:
    """Own one backend group without reaping its leader before cleanup."""

    def __init__(
        self,
        *,
        state: _CallState,
        command: Sequence[str],
        cwd: Path | str,
        environment: Mapping[str, str],
        timeout: float,
        stdout_limit: int,
        stderr_limit: int,
        terminate_grace: float,
        leader_poll_interval: float,
    ) -> None:
        if (
            not command
            or not isinstance(environment, Mapping)
            or "PATH" not in environment
            or timeout <= 0
            or stdout_limit < 1
            or stderr_limit < 1
            or terminate_grace <= 0
            or leader_poll_interval <= 0
        ):
            raise ValueError("invalid anchored backend bounds")
        self.state = state
        self.command = tuple(command)
        self.cwd = Path(cwd)
        self.environment = dict(environment)
        if any(
            not isinstance(key, str)
            or not isinstance(value, str)
            or "\x00" in key
            or "\x00" in value
            for key, value in self.environment.items()
        ):
            raise ValueError("invalid anchored backend environment")
        self.timeout = float(timeout)
        self.stdout_limit = int(stdout_limit)
        self.stderr_limit = int(stderr_limit)
        self.terminate_grace = float(terminate_grace)
        self.leader_poll_interval = float(leader_poll_interval)
        self._cancelled = threading.Event()
        self._wake_lock = threading.Lock()
        self._wake_writer: socket.socket | None = None

    def cancel(self) -> None:
        """Wake the runner and request cleanup; the caller never signals."""
        self._cancelled.set()
        with self._wake_lock:
            writer = self._wake_writer
        if writer is not None:
            with contextlib.suppress(OSError):
                writer.send(b"\0")

    def _peek_leader_anchor(self, process: subprocess.Popen[bytes]) -> int | None:
        state = self.state
        if state.reaped or state.anchor_lost:
            raise BackendFailure("backend leader anchor is unavailable")
        if state.leader_status is not None:
            return state.leader_status
        try:
            waitid = getattr(os, "waitid", None)
            if waitid is None:
                raise OSError("waitid is unavailable")
            result = waitid(
                os.P_PID,
                process.pid,
                os.WEXITED | os.WNOHANG | os.WNOWAIT,
            )
        except ChildProcessError as error:
            state.anchor_lost = True
            raise BackendFailure("backend leader was reaped before group cleanup") from error
        except OSError as error:
            raise BackendFailure("cannot inspect backend leader anchor") from error
        if result is None:
            return None
        if result.si_pid != process.pid:
            state.anchor_lost = True
            raise BackendFailure("backend leader observation is inconsistent")
        if result.si_code == os.CLD_EXITED:
            status = result.si_status
        elif result.si_code in (os.CLD_KILLED, os.CLD_DUMPED):
            status = -result.si_status
        else:
            raise BackendFailure("backend leader has an unsupported wait status")
        state.leader_status = status
        return status

    def _signal_group(self, process: subprocess.Popen[bytes], requested_signal: int) -> bool:
        self._peek_leader_anchor(process)
        if self.state.leader_status is not None:
            try:
                if _exited_group_has_only_zombie_members(process.pid):
                    return False
            except BackendFailure:
                # Observation is an optimization for the zombie-only case. A
                # failed observer must never prevent an otherwise permitted
                # group signal; EPERM from that signal remains a named failure.
                pass
        try:
            os.killpg(process.pid, requested_signal)
            return True
        except ProcessLookupError:
            return False
        except OSError as error:
            if error.errno == errno.ESRCH:
                return False
            if error.errno == errno.EPERM:
                if self._permission_failure_is_quiescent(process):
                    return False
                raise BackendFailure(
                    "permission denied signalling backend process group"
                ) from error
            raise BackendFailure("cannot signal backend process group") from error

    def _group_exists(self, process: subprocess.Popen[bytes]) -> bool:
        return self._signal_group(process, 0)

    def _permission_failure_is_quiescent(
        self, process: subprocess.Popen[bytes]
    ) -> bool:
        """Require a retained exited leader and an all-zombie group snapshot."""
        deadline = time.monotonic() + self.terminate_grace
        while True:
            try:
                status = self._peek_leader_anchor(process)
            except BackendFailure:
                return False
            if status is not None:
                try:
                    if _exited_group_has_only_zombie_members(process.pid):
                        return True
                except BackendFailure:
                    return False
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            time.sleep(min(0.01, remaining))

    def _begin_termination(self, process: subprocess.Popen[bytes]) -> None:
        state = self.state
        if state.reaped or state.anchor_lost or state.term_sent:
            return
        state.term_sent = self._signal_group(process, signal.SIGTERM)

    def _terminate_and_reap(self, process: subprocess.Popen[bytes]) -> int:
        """Signal while the WNOWAIT anchor is retained, then reap exactly once."""
        state = self.state
        if state.reaped:
            if state.leader_status is None:
                raise BackendFailure("reaped backend has no exit status")
            return state.leader_status
        if state.anchor_lost:
            raise BackendFailure("backend leader anchor is unavailable")

        self._begin_termination(process)
        if state.term_sent:
            deadline = time.monotonic() + self.terminate_grace
            while self._group_exists(process):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    state.kill_sent = self._signal_group(process, signal.SIGKILL)
                    break
                time.sleep(min(self.leader_poll_interval, remaining))

        leader_deadline = time.monotonic() + max(1.0, self.terminate_grace * 4)
        status = self._peek_leader_anchor(process)
        while status is None:
            if time.monotonic() >= leader_deadline:
                raise BackendFailure("backend leader did not exit within cleanup bounds")
            time.sleep(self.leader_poll_interval)
            status = self._peek_leader_anchor(process)

        if state.kill_sent:
            group_deadline = time.monotonic() + max(1.0, self.terminate_grace * 4)
            while self._group_exists(process):
                if time.monotonic() >= group_deadline:
                    raise BackendFailure("backend process group survived SIGKILL")
                time.sleep(self.leader_poll_interval)

        try:
            reaped_status = process.wait()
        except (ChildProcessError, OSError) as error:
            state.anchor_lost = True
            raise BackendFailure("backend leader anchor was lost during final reap") from error
        if reaped_status != status:
            state.anchor_lost = True
            raise BackendFailure("backend reap status changed after WNOWAIT observation")
        state.reaped = True
        return status

    @staticmethod
    def _drain_wakeup(reader: socket.socket) -> None:
        while True:
            try:
                if not reader.recv(4096):
                    return
            except BlockingIOError:
                return

    @staticmethod
    def _close_selector_file(selector: selectors.BaseSelector, file_object: Any) -> None:
        with contextlib.suppress(Exception):
            selector.unregister(file_object)

    def _read_ready(
        self,
        selector: selectors.BaseSelector,
        buffers: dict[str, bytearray],
        open_streams: set[str],
        wake_reader: socket.socket,
        timeout: float,
    ) -> None:
        try:
            events = selector.select(max(0.0, timeout))
        except OSError as error:
            raise BackendFailure("cannot read backend pipes") from error
        for key, unused_mask in events:
            stream, limit = cast(tuple[str, int], key.data)
            if stream == "wake":
                self._drain_wakeup(wake_reader)
                continue
            try:
                chunk = os.read(key.fd, min(64 * 1024, limit - len(buffers[stream]) + 1))
            except BlockingIOError:
                continue
            except OSError as error:
                raise BackendFailure("cannot read backend stream") from error
            if not chunk:
                self._close_selector_file(selector, key.fileobj)
                open_streams.discard(stream)
                continue
            buffers[stream].extend(chunk)
            if len(buffers[stream]) > limit:
                raise BackendFailure("backend stream exceeded byte limit")

    def _drain_to_eof(
        self,
        selector: selectors.BaseSelector,
        buffers: dict[str, bytearray],
        open_streams: set[str],
        wake_reader: socket.socket,
    ) -> None:
        deadline = time.monotonic() + max(1.0, self.terminate_grace * 4)
        while open_streams:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise BackendFailure("backend pipes did not close within bounds")
            self._read_ready(
                selector,
                buffers,
                open_streams,
                wake_reader,
                min(self.leader_poll_interval, remaining),
            )

    @staticmethod
    def _parse_backend_output(raw: bytes) -> dict[str, Any]:
        try:
            value = _strict_json_loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
            raise BackendFailure("backend stdout is not one strict JSON value") from error
        if not isinstance(value, dict):
            raise BackendFailure("backend stdout is not a JSON object")
        return value

    def run(self) -> dict[str, Any]:
        """Run, bound, terminate, and reap one process group in one worker thread."""
        try:
            process = subprocess.Popen(
                list(self.command),
                cwd=str(self.cwd),
                env=self.environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,
                close_fds=True,
                bufsize=0,
            )
        except (OSError, ValueError) as error:
            raise BackendFailure("backend failed to start") from error

        self.state.process = process
        selector: selectors.BaseSelector | None = None
        wake_reader: socket.socket | None = None
        wake_writer: socket.socket | None = None
        buffers = {"stdout": bytearray(), "stderr": bytearray()}
        open_streams = {"stdout", "stderr"}
        cleanup_done = False
        try:
            try:
                selector = selectors.DefaultSelector()
                wake_reader, wake_writer = socket.socketpair()
                wake_reader.setblocking(False)
                wake_writer.setblocking(False)
            except (OSError, ValueError) as error:
                raise BackendFailure("backend monitor setup failed") from error
            if process.stdout is None or process.stderr is None:
                raise BackendFailure("backend pipes unavailable")
            os.set_blocking(process.stdout.fileno(), False)
            os.set_blocking(process.stderr.fileno(), False)
            selector.register(wake_reader, selectors.EVENT_READ, ("wake", 0))
            selector.register(
                process.stdout, selectors.EVENT_READ, ("stdout", self.stdout_limit)
            )
            selector.register(
                process.stderr, selectors.EVENT_READ, ("stderr", self.stderr_limit)
            )
            with self._wake_lock:
                self._wake_writer = wake_writer
            if self._cancelled.is_set():
                with contextlib.suppress(OSError):
                    wake_writer.send(b"\0")

            deadline = time.monotonic() + self.timeout
            outcome: BackendFailure | None = None
            leader_status: int | None = None
            while outcome is None and leader_status is None:
                if self._cancelled.is_set():
                    outcome = CallCancelled("request cancelled")
                    break
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    outcome = BackendTimedOut("backend timed out")
                    break
                try:
                    leader_status = self._peek_leader_anchor(process)
                    if leader_status is None:
                        self._read_ready(
                            selector,
                            buffers,
                            open_streams,
                            wake_reader,
                            min(self.leader_poll_interval, remaining),
                        )
                except BackendFailure as error:
                    outcome = error

            status = self._terminate_and_reap(process)
            cleanup_done = True
            if outcome is None and self._cancelled.is_set():
                outcome = CallCancelled("request cancelled during backend cleanup")
            if outcome is not None:
                raise outcome

            self._drain_to_eof(selector, buffers, open_streams, wake_reader)
            if self._cancelled.is_set():
                raise CallCancelled("request cancelled before backend result delivery")
            value = self._parse_backend_output(bytes(buffers["stdout"]))
            if self._cancelled.is_set():
                raise CallCancelled("request cancelled before backend result delivery")
            if status == 0:
                return value
            if status == 1 and value.get("status") in {"ok", "refused", "indeterminate"}:
                return value
            raise BackendFailure("backend returned a non-domain failure")
        finally:
            try:
                if not cleanup_done and not self.state.reaped and not self.state.anchor_lost:
                    self._terminate_and_reap(process)
            finally:
                if wake_writer is not None:
                    with self._wake_lock:
                        if self._wake_writer is wake_writer:
                            self._wake_writer = None
                for file_object in (process.stdout, process.stderr):
                    if file_object is not None:
                        if selector is not None:
                            self._close_selector_file(selector, file_object)
                        with contextlib.suppress(OSError):
                            file_object.close()
                if selector is not None:
                    if wake_reader is not None:
                        self._close_selector_file(selector, wake_reader)
                    selector.close()
                if wake_reader is not None:
                    wake_reader.close()
                if wake_writer is not None:
                    wake_writer.close()
                self.state.process = None


def _read_regular_nofollow(path: Path | str, *, limit: int, subject: str) -> bytes:
    if limit < 1:
        raise StartupError("invalid file read limit")
    flags = os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW
    try:
        descriptor = os.open(os.fspath(path), flags)
    except OSError as error:
        raise StartupError(f"cannot safely open {subject}") from error
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_size > limit:
            raise StartupError(f"{subject} is not a bounded regular file")
        chunks: list[bytes] = []
        count = 0
        while True:
            chunk = os.read(descriptor, min(64 * 1024, limit - count + 1))
            if not chunk:
                break
            count += len(chunk)
            if count > limit:
                raise StartupError(f"{subject} exceeds its byte limit")
            chunks.append(chunk)
        after = os.fstat(descriptor)
        stable = (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
        ) == (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        )
        if not stable:
            raise StartupError(f"{subject} changed while being read")
        try:
            current = os.stat(path, follow_symlinks=False)
        except OSError as error:
            raise StartupError(f"{subject} path changed while being read") from error
        if (
            current.st_dev,
            current.st_ino,
            current.st_mode,
        ) != (
            after.st_dev,
            after.st_ino,
            after.st_mode,
        ):
            raise StartupError(f"{subject} path changed while being read")
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _read_canonical_json(path: Path | str, *, limit: int, subject: str) -> dict[str, Any]:
    raw = _read_regular_nofollow(path, limit=limit, subject=subject)
    if not raw.endswith(b"\n") or raw.endswith(b"\n\n"):
        raise StartupError(f"{subject} is not canonical newline-terminated JSON")
    try:
        text = raw.decode("utf-8")
        parsed = _strict_json_loads(text)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise StartupError(f"{subject} is not strict JSON") from error
    if not isinstance(parsed, dict):
        raise StartupError(f"{subject} is not a JSON object")
    canonical = json.dumps(parsed, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
    if canonical.encode("utf-8") != raw:
        raise StartupError(f"{subject} is not canonical JSON")
    return parsed


def _canonical_absolute_directory(raw_path: object, *, subject: str) -> Path:
    if not isinstance(raw_path, str) or not raw_path or "\x00" in raw_path:
        raise StartupError(f"{subject} is not a path string")
    path = Path(raw_path)
    if not path.is_absolute():
        raise StartupError(f"{subject} must be absolute")
    try:
        resolved = path.resolve(strict=True)
        info = path.lstat()
    except OSError as error:
        raise StartupError(f"{subject} does not exist") from error
    if resolved != path or not stat.S_ISDIR(info.st_mode):
        raise StartupError(f"{subject} must be a canonical non-symlink directory")
    return path


def resolve_runtime_path(
    *,
    environ: Mapping[str, str] | None = None,
    locator_path: Path | str | None = None,
    provisioner: _ProvisionerAPI,
) -> Path:
    """Resolve only a canonical absolute JACKAL_HOME or the pinned locator."""
    environment = os.environ if environ is None else environ
    selected = environment.get("JACKAL_HOME")
    if selected is not None:
        return _canonical_absolute_directory(selected, subject="JACKAL_HOME")

    locator = Path(provisioner.default_locator_path()) if locator_path is None else Path(locator_path)
    document = _read_canonical_json(locator, limit=16 * 1024, subject="runtime locator")
    expected_keys = {"schema", "epoch", "runtime_path", "package_size", "package_sha256"}
    if set(document) != expected_keys:
        raise StartupError("runtime locator has an unsupported shape")
    if (
        document["schema"] != "jackal-codex-plugin-runtime-v1"
        or document["epoch"] != provisioner.EPOCH
        or document["package_size"] != provisioner.PACKAGE_SIZE
        or document["package_sha256"] != provisioner.PACKAGE_SHA256
    ):
        raise StartupError("runtime locator does not match wrapper-side release pins")
    return _canonical_absolute_directory(document["runtime_path"], subject="located runtime")


def _verify_package_metadata(runtime: Path, provisioner: _ProvisionerAPI) -> None:
    document = _read_canonical_json(
        runtime / ".jackal-package.json",
        limit=16 * 1024,
        subject="runtime package metadata",
    )
    expected = {
        "schema": "jackal-runtime-package-v1",
        "epoch": provisioner.EPOCH,
        "asset": provisioner.ASSET,
        "package_size": provisioner.PACKAGE_SIZE,
        "package_sha256": provisioner.PACKAGE_SHA256,
    }
    if document != expected:
        raise StartupError("runtime package metadata does not match wrapper-side release pins")


def _load_catalog(path: Path) -> dict[str, Any]:
    raw = _read_regular_nofollow(path, limit=MAX_CATALOG_BYTES, subject="runtime tools.json")
    try:
        parsed = _strict_json_loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise StartupError("runtime tools.json is not strict JSON") from error
    if not isinstance(parsed, dict):
        raise StartupError("runtime tools.json is not a JSON object")
    return parsed


def _execute_module_bytes(source: bytes, path: Path | str, module_name: str) -> ModuleType:
    code = compile(source, os.fspath(path), "exec", dont_inherit=True)
    module = ModuleType(module_name)
    module.__file__ = os.fspath(path)
    module.__package__ = module_name.rpartition(".")[0]
    module.__loader__ = None
    module.__dict__["__cached__"] = None
    previous = sys.modules.get(module_name)
    sys.modules[module_name] = module
    try:
        exec(code, module.__dict__)
    except Exception:
        if previous is None:
            sys.modules.pop(module_name, None)
        else:
            sys.modules[module_name] = previous
        raise
    return module


def _read_plugin_module_once(
    plugin_root: Path | str, relative_path: str, *, limit: int
) -> tuple[bytes, str]:
    components = relative_path.split("/")
    if (
        not relative_path
        or relative_path.startswith("/")
        or "\\" in relative_path
        or any(component in ("", ".", "..") for component in components)
    ):
        raise StartupError("wrapper module path is invalid")
    directory_flags = os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW | os.O_DIRECTORY
    file_flags = os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW
    try:
        descriptor = os.open(os.fspath(plugin_root), directory_flags)
    except OSError as error:
        raise StartupError("cannot safely open plugin root") from error
    try:
        for component in components[:-1]:
            try:
                next_descriptor = os.open(component, directory_flags, dir_fd=descriptor)
            except OSError as error:
                raise StartupError("cannot safely open wrapper module directory") from error
            os.close(descriptor)
            descriptor = next_descriptor
        try:
            file_descriptor = os.open(components[-1], file_flags, dir_fd=descriptor)
        except OSError as error:
            raise StartupError("cannot safely open wrapper module") from error
    finally:
        os.close(descriptor)
    try:
        before = os.fstat(file_descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_size > limit:
            raise StartupError("wrapper module is not a bounded regular file")
        digest = hashlib.sha256()
        chunks: list[bytes] = []
        count = 0
        while True:
            chunk = os.read(file_descriptor, min(64 * 1024, limit - count + 1))
            if not chunk:
                break
            count += len(chunk)
            if count > limit:
                raise StartupError("wrapper module exceeds its byte limit")
            digest.update(chunk)
            chunks.append(chunk)
        after = os.fstat(file_descriptor)
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
            raise StartupError("wrapper module changed while being read")
        return b"".join(chunks), digest.hexdigest()
    finally:
        os.close(file_descriptor)


def _record_digest(records: object, relative_path: str) -> str:
    if isinstance(records, Mapping):
        expected = records.get(relative_path)
    else:
        expected = None
        try:
            for record in cast(Sequence[object], records):
                if getattr(record, "path", None) == relative_path:
                    expected = getattr(record, "digest", None)
                    break
        except TypeError as error:
            raise StartupError("wrapper inventory is invalid") from error
    if not isinstance(expected, str) or re.fullmatch(r"[0-9a-f]{64}", expected) is None:
        raise StartupError("wrapper inventory omits the required module")
    return expected


def _load_verified_module(
    plugin_root: Path | str,
    relative_path: str,
    module_name: str,
    records: object,
) -> ModuleType:
    expected = _record_digest(records, relative_path)
    source, actual = _read_plugin_module_once(
        plugin_root, relative_path, limit=MAX_WRAPPER_MODULE_BYTES
    )
    if not hmac.compare_digest(actual, expected):
        raise StartupError("wrapper module digest does not match inventory")
    try:
        return _execute_module_bytes(
            source, Path(plugin_root) / relative_path, module_name
        )
    except StartupError:
        raise
    except Exception as error:
        raise StartupError("wrapper module failed to load") from error


def _read_identity_inventory(plugin_root: Path | str) -> dict[str, str]:
    raw = _read_regular_nofollow(
        Path(plugin_root) / "PLUGIN_IDENTITY.sha256",
        limit=MAX_WRAPPER_MODULE_BYTES,
        subject="plugin identity manifest",
    )
    if not raw or not raw.endswith(b"\n"):
        raise StartupError("plugin identity manifest is not canonical")
    try:
        lines = raw[:-1].decode("utf-8").split("\n")
    except UnicodeDecodeError as error:
        raise StartupError("plugin identity manifest is not UTF-8") from error
    inventory: dict[str, str] = {}
    previous: str | None = None
    for line in lines:
        match = _IDENTITY_LINE.fullmatch(line)
        if match is None:
            raise StartupError("plugin identity manifest line is malformed")
        digest, relative = match.groups()
        components = relative.split("/")
        if (
            relative.startswith("/")
            or "\\" in relative
            or any(component in ("", ".", "..") for component in components)
            or any(ord(character) < 32 or ord(character) == 127 for character in relative)
            or previous is not None and relative <= previous
        ):
            raise StartupError("plugin identity manifest path is invalid")
        inventory[relative] = digest
        previous = relative
    if not inventory:
        raise StartupError("plugin identity manifest is empty")
    return inventory


def _inventory_from_records(records: object) -> dict[str, str]:
    inventory: dict[str, str] = {}
    try:
        for record in cast(Sequence[object], records):
            path = getattr(record, "path", None)
            digest = getattr(record, "digest", None)
            if (
                not isinstance(path, str)
                or not isinstance(digest, str)
                or re.fullmatch(r"[0-9a-f]{64}", digest) is None
                or path in inventory
            ):
                raise StartupError("verified wrapper inventory is invalid")
            inventory[path] = digest
    except TypeError as error:
        raise StartupError("verified wrapper inventory is invalid") from error
    return inventory


def _load_module(path: Path, module_name: str) -> ModuleType:
    try:
        source = _read_regular_nofollow(
            path,
            limit=MAX_WRAPPER_MODULE_BYTES,
            subject="wrapper module source",
        )
        return _execute_module_bytes(source, path, module_name)
    except StartupError:
        raise
    except Exception as error:
        raise StartupError("wrapper module failed to load") from error


def _error_response(
    request_id: str | int | None, code: int, message: str
) -> dict[str, Any]:
    response: dict[str, Any] = {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": code, "message": message[:240]},
    }
    if len(json.dumps(response, ensure_ascii=True, separators=(",", ":"))) > MAX_ERROR_RESPONSE_BYTES:
        response["error"]["message"] = "bounded adapter error"
    return response


def _success_response(request_id: str | int, result: object) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _valid_request_id(value: object) -> bool:
    return isinstance(value, str) or (isinstance(value, int) and not isinstance(value, bool))


def _validate_meta(params: dict[str, Any]) -> None:
    if "_meta" in params and not isinstance(params["_meta"], dict):
        raise ProtocolError(INVALID_PARAMS, "_meta must be an object")


def _is_strict_json(value: object) -> bool:
    if value is None or isinstance(value, (str, bool)):
        return True
    if isinstance(value, int):
        return not isinstance(value, bool)
    if isinstance(value, float):
        return math.isfinite(value)
    if isinstance(value, list):
        return all(_is_strict_json(item) for item in value)
    if isinstance(value, dict):
        return all(
            isinstance(key, str) and _is_strict_json(item)
            for key, item in value.items()
        )
    return False


def _validate_arguments(arguments: object) -> dict[str, Any]:
    if not isinstance(arguments, dict):
        raise ProtocolError(INVALID_PARAMS, "tool arguments must be an object")
    if not _is_strict_json(arguments):
        raise ProtocolError(INVALID_PARAMS, "tool arguments are not strict JSON")
    return arguments


class MCPServer:
    """One MCP server instance with serialized, cancellable JACKAL calls."""

    def __init__(
        self,
        *,
        runtime_root: Path | str,
        launcher: Path | str,
        tool_definitions: Sequence[dict[str, Any]],
        runtime_environment: Mapping[str, str],
        max_active_calls: int = MAX_ACTIVE_CALLS,
        tool_timeout: float = TOOL_TIMEOUT_SECONDS,
        stdout_limit: int = MAX_STDOUT_BYTES,
        stderr_limit: int = MAX_STDERR_BYTES,
        terminate_grace: float = TERMINATE_GRACE_SECONDS,
        leader_poll_interval: float = LEADER_POLL_SECONDS,
        runtime_owner: object | None = None,
    ) -> None:
        if (
            tool_timeout <= 0
            or not isinstance(runtime_environment, Mapping)
            or "PATH" not in runtime_environment
            or isinstance(max_active_calls, bool)
            or not isinstance(max_active_calls, int)
            or max_active_calls < 1
            or stdout_limit < 1
            or stderr_limit < 1
            or terminate_grace <= 0
            or leader_poll_interval <= 0
        ):
            raise ValueError("invalid MCP process bounds")
        self.runtime_root = Path(runtime_root)
        self.launcher = Path(launcher)
        self.tool_definitions = tuple(copy.deepcopy(tuple(tool_definitions)))
        self.runtime_environment = dict(runtime_environment)
        if any(
            not isinstance(key, str)
            or not isinstance(value, str)
            or "\x00" in key
            or "\x00" in value
            for key, value in self.runtime_environment.items()
        ):
            raise ValueError("invalid MCP runtime environment")
        self._tools = {definition["name"]: definition for definition in self.tool_definitions}
        if len(self._tools) != len(self.tool_definitions):
            raise ValueError("duplicate MCP tool definitions")
        self.tool_timeout = float(tool_timeout)
        self.max_active_calls = max_active_calls
        self.stdout_limit = int(stdout_limit)
        self.stderr_limit = int(stderr_limit)
        self.terminate_grace = float(terminate_grace)
        self.leader_poll_interval = float(leader_poll_interval)
        self._backend_lock = asyncio.Lock()
        self._active: dict[str | int, _CallState] = {}
        self._closed = False
        self._runtime_owner = runtime_owner

    async def handle_line(self, line: bytes) -> dict[str, Any] | None:
        if not isinstance(line, bytes):
            return _error_response(None, INVALID_REQUEST, "request line must be bytes")
        if len(line) > MAX_REQUEST_LINE_BYTES:
            return _error_response(None, INVALID_REQUEST, "request line exceeds byte limit")
        if not line.endswith(b"\n") or line.count(b"\n") != 1:
            return _error_response(None, INVALID_REQUEST, "request record must end in one LF")
        try:
            text = line.decode("utf-8")
            message = _strict_json_loads(text)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError, RecursionError):
            return _error_response(None, PARSE_ERROR, "invalid JSON")
        return await self.handle_message(message)

    async def handle_message(self, message: object) -> dict[str, Any] | None:
        request_id: str | int | None = None
        is_notification = False
        try:
            if not isinstance(message, dict):
                raise ProtocolError(INVALID_REQUEST, "request must be a JSON object")
            is_notification = "id" not in message
            if not is_notification and _valid_request_id(message.get("id")):
                request_id = message["id"]
            allowed = {"jsonrpc", "id", "method", "params"}
            if any(key not in allowed for key in message):
                raise ProtocolError(INVALID_REQUEST, "request contains unknown top-level fields")
            if message.get("jsonrpc") != "2.0" or not isinstance(message.get("method"), str):
                raise ProtocolError(INVALID_REQUEST, "invalid JSON-RPC request")
            if not is_notification:
                if not _valid_request_id(message["id"]):
                    raise ProtocolError(INVALID_REQUEST, "request id must be a string or integer")
                request_id = message["id"]
            params = message.get("params", {})
            if not isinstance(params, dict):
                raise ProtocolError(INVALID_PARAMS, "params must be an object", request_id)
            result = await self._dispatch(
                method=message["method"],
                params=params,
                request_id=request_id,
                is_notification=is_notification,
            )
            if is_notification:
                return None
            assert request_id is not None
            return _success_response(request_id, result)
        except ProtocolError as error:
            if is_notification:
                return None
            error_id = request_id if error.request_id is None else error.request_id
            return _error_response(error_id, error.code, str(error))
        except CallCancelled:
            if is_notification:
                return None
            return _error_response(request_id, REQUEST_CANCELLED, "request cancelled")
        except BackendTimedOut:
            return _error_response(request_id, BACKEND_TIMEOUT, "JACKAL backend timed out")
        except BackendFailure:
            return _error_response(request_id, BACKEND_ERROR, "JACKAL backend failed closed")
        except Exception:
            if is_notification:
                return None
            return _error_response(request_id, INTERNAL_ERROR, "unexpected adapter failure")

    async def _dispatch(
        self,
        *,
        method: str,
        params: dict[str, Any],
        request_id: str | int | None,
        is_notification: bool,
    ) -> object:
        if method == "notifications/cancelled":
            if not is_notification:
                raise ProtocolError(INVALID_REQUEST, "cancellation must be a notification", request_id)
            allowed = {"requestId", "reason", "_meta"}
            if set(params) - allowed or "requestId" not in params:
                raise ProtocolError(INVALID_PARAMS, "invalid cancellation params")
            _validate_meta(params)
            target = params["requestId"]
            if not _valid_request_id(target):
                raise ProtocolError(INVALID_PARAMS, "invalid cancellation request id")
            if "reason" in params and not isinstance(params["reason"], str):
                raise ProtocolError(INVALID_PARAMS, "invalid cancellation reason")
            self._cancel_request(target)
            return {}

        if method == "notifications/initialized":
            if set(params) - {"_meta"}:
                raise ProtocolError(INVALID_PARAMS, "invalid initialized notification params")
            _validate_meta(params)
            return {}
        if is_notification:
            return {}
        if method == "initialize":
            _validate_meta(params)
            protocol = params.get("protocolVersion")
            if not isinstance(protocol, str):
                raise ProtocolError(INVALID_PARAMS, "initialize requires protocolVersion", request_id)
            capabilities = params.get("capabilities")
            client_info = params.get("clientInfo")
            if not isinstance(capabilities, dict) or not isinstance(client_info, dict):
                raise ProtocolError(INVALID_PARAMS, "initialize requires client capabilities and info", request_id)
            negotiated = protocol if protocol in SUPPORTED_PROTOCOL_VERSIONS else LATEST_PROTOCOL_VERSION
            return {
                "protocolVersion": negotiated,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "jackel-codex", "version": "0.1.0"},
                "instructions": (
                    "Preserve JACKAL status and evidence class exactly. "
                    "Unsupported strong claims refuse; never silently downgrade."
                ),
            }
        if method == "ping":
            if set(params) - {"_meta"}:
                raise ProtocolError(INVALID_PARAMS, "invalid ping params", request_id)
            _validate_meta(params)
            return {}
        if method == "tools/list":
            if set(params) - {"cursor", "_meta"}:
                raise ProtocolError(INVALID_PARAMS, "invalid tools/list params", request_id)
            _validate_meta(params)
            if "cursor" in params and not isinstance(params["cursor"], str):
                raise ProtocolError(INVALID_PARAMS, "tools/list cursor must be a string", request_id)
            return {"tools": list(copy.deepcopy(self.tool_definitions))}
        if method == "tools/call":
            if set(params) - {"name", "arguments", "_meta"} or not {
                "name", "arguments"
            }.issubset(params):
                raise ProtocolError(INVALID_PARAMS, "tools/call requires name and arguments", request_id)
            _validate_meta(params)
            name = params["name"]
            if not isinstance(name, str) or name not in self._tools:
                raise ProtocolError(INVALID_PARAMS, "unknown tool name", request_id)
            arguments = _validate_arguments(params["arguments"])
            assert request_id is not None
            return await self._handle_tool_call(request_id, name, arguments)
        raise ProtocolError(METHOD_NOT_FOUND, "method not found", request_id)

    async def _handle_tool_call(
        self, request_id: str | int, name: str, arguments: dict[str, Any]
    ) -> dict[str, Any]:
        if self._closed:
            raise BackendFailure("server is closed")
        if request_id in self._active:
            raise ProtocolError(INVALID_REQUEST, "duplicate active request id", request_id)
        if len(self._active) >= self.max_active_calls:
            return backend_result({"status": "refused", "reason": "plugin-busy"})
        state = _CallState(request_id=request_id)
        self._active[request_id] = state
        try:
            value = await self._invoke_serialized(state, name, arguments)
            return backend_result(value)
        finally:
            if self._active.get(request_id) is state:
                del self._active[request_id]

    async def _acquire_backend(self, state: _CallState) -> None:
        if state.cancelled.is_set():
            raise CallCancelled("request was cancelled while queued")
        acquire = asyncio.create_task(self._backend_lock.acquire())
        cancelled = asyncio.create_task(state.cancelled.wait())
        try:
            done, unused_pending = await asyncio.wait(
                {acquire, cancelled}, return_when=asyncio.FIRST_COMPLETED
            )
            if cancelled in done and cancelled.result():
                if acquire.done() and not acquire.cancelled() and acquire.exception() is None:
                    if acquire.result():
                        self._backend_lock.release()
                else:
                    acquire.cancel()
                raise CallCancelled("request was cancelled while queued")
            await acquire
        finally:
            cancelled.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await cancelled
            if not acquire.done():
                acquire.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await acquire

    async def _invoke_serialized(
        self, state: _CallState, name: str, arguments: dict[str, Any]
    ) -> dict[str, Any]:
        await self._acquire_backend(state)
        try:
            if state.cancelled.is_set():
                raise CallCancelled("request was cancelled before launch")
            return await self._invoke_backend(state, name, arguments)
        finally:
            self._backend_lock.release()

    async def _invoke_backend(
        self, state: _CallState, name: str, arguments: dict[str, Any]
    ) -> dict[str, Any]:
        compact_arguments = json.dumps(
            arguments,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        runner = _AnchoredBackendRunner(
            state=state,
            command=(str(self.launcher), "call", name, compact_arguments),
            cwd=self.runtime_root,
            environment=self.runtime_environment,
            timeout=self.tool_timeout,
            stdout_limit=self.stdout_limit,
            stderr_limit=self.stderr_limit,
            terminate_grace=self.terminate_grace,
            leader_poll_interval=self.leader_poll_interval,
        )
        state.runner = runner
        worker = asyncio.create_task(asyncio.to_thread(runner.run))
        state.worker = worker
        try:
            return await asyncio.shield(worker)
        except asyncio.CancelledError:
            state.cancelled.set()
            runner.cancel()
            while not worker.done():
                try:
                    await asyncio.shield(worker)
                except asyncio.CancelledError:
                    continue
                except Exception:
                    break
            raise
        finally:
            state.worker = None
            state.runner = None

    def _cancel_request(self, request_id: str | int) -> None:
        state = self._active.get(request_id)
        if state is None:
            return
        state.cancelled.set()
        if state.runner is not None:
            state.runner.cancel()

    async def close(self) -> None:
        self._closed = True
        states = tuple(self._active.values())
        for state in states:
            state.cancelled.set()
            if state.runner is not None:
                state.runner.cancel()
        workers = tuple(state.worker for state in states if state.worker is not None)
        if workers:
            completion = asyncio.gather(
                *(asyncio.shield(worker) for worker in workers),
                return_exceptions=True,
            )
            try:
                await asyncio.wait_for(
                    completion,
                    timeout=max(2.0, self.terminate_grace * 8),
                )
            except asyncio.TimeoutError as error:
                raise BackendFailure("backend cleanup did not finish within bounds") from error
        deadline = asyncio.get_running_loop().time() + 1.0
        while self._active and asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(0)
        owner = self._runtime_owner
        if owner is not None:
            close = getattr(owner, "close", None)
            if not callable(close):
                raise BackendFailure("runtime snapshot owner is invalid")
            try:
                close()
            except Exception as error:
                raise BackendFailure("runtime snapshot cleanup failed") from error
            self._runtime_owner = None


def build_production_server(
    *,
    plugin_root: Path | str | None = None,
    environ: Mapping[str, str] | None = None,
    locator_path: Path | str | None = None,
    provisioner: _ProvisionerAPI | None = None,
    identity_verifier: Callable[[Path, Path], object] | None = None,
    runtime_validator: Callable[..., object] | None = None,
) -> MCPServer:
    """Verify plugin + pinned runtime, then construct the production server."""
    root = plugin_root_from_server() if plugin_root is None else Path(plugin_root)
    if not root.is_absolute():
        raise StartupError("plugin root must be absolute")
    inventory: dict[str, str] | None = None
    if identity_verifier is None:
        inventory = _read_identity_inventory(root)
        verifier_module = _load_verified_module(
            root,
            "scripts/verify_plugin.py",
            "jackel_codex_verify_plugin",
            inventory,
        )
        identity_verifier = verifier_module.verify_manifest
    try:
        verified_records = identity_verifier(root, root / "PLUGIN_IDENTITY.sha256")
    except Exception as error:
        raise StartupError("plugin identity verification refused") from error
    if inventory is not None and _inventory_from_records(verified_records) != inventory:
        raise StartupError("plugin identity records changed during verification")
    if provisioner is None:
        if inventory is None:
            inventory = _inventory_from_records(verified_records)
        provisioner = cast(
            _ProvisionerAPI,
            _load_verified_module(
                root,
                "scripts/provision_runtime.py",
                "jackel_codex_provision_runtime",
                inventory,
            ),
        )
    try:
        provisioner.validate_host()
    except Exception as error:
        raise StartupError("unsupported production host") from error

    runtime = resolve_runtime_path(
        environ=environ,
        locator_path=locator_path,
        provisioner=provisioner,
    )
    _verify_package_metadata(runtime, provisioner)
    validator = provisioner.validate_runtime if runtime_validator is None else runtime_validator
    try:
        validator(
            runtime,
            timeout=provisioner.SELFTEST_TIMEOUT,
            output_limit=provisioner.SELFTEST_OUTPUT_LIMIT,
            expected_tree_sha256=provisioner.SHA256SUMS_SHA256,
        )
    except Exception as error:
        raise StartupError("pinned runtime validation refused") from error

    snapshot_owner: object | None = None
    try:
        snapshot_owner = provisioner.create_runtime_snapshot(
            runtime,
            timeout=provisioner.SELFTEST_TIMEOUT,
            output_limit=provisioner.SELFTEST_OUTPUT_LIMIT,
            expected_tree_sha256=provisioner.SHA256SUMS_SHA256,
        )
        snapshot_value = getattr(snapshot_owner, "root", None)
        snapshot = _canonical_absolute_directory(
            os.fspath(snapshot_value) if isinstance(snapshot_value, (Path, str)) else None,
            subject="private runtime snapshot",
        )
        snapshot_info = snapshot.lstat()
        if snapshot == runtime or snapshot_info.st_mode & 0o077:
            raise StartupError("runtime snapshot is not private and independent")
        _verify_package_metadata(snapshot, provisioner)
        catalog = _load_catalog(snapshot / "plugin/hermes/tools.json")
        definitions = build_tool_definitions(catalog, expected_count=EXPECTED_TOOL_COUNT)
        launcher = snapshot / "plugin/hermes/jackal_hermes"
        try:
            launcher_info = launcher.lstat()
        except OSError as error:
            raise StartupError("runtime launcher is missing") from error
        if (
            not stat.S_ISREG(launcher_info.st_mode)
            or launcher.is_symlink()
            or not os.access(launcher, os.X_OK)
        ):
            raise StartupError("runtime launcher is not a safe executable")
        try:
            runtime_environment = provisioner.runtime_subprocess_environment(environ)
        except Exception as error:
            raise StartupError("runtime subprocess environment refused") from error
        return MCPServer(
            runtime_root=snapshot,
            launcher=launcher,
            tool_definitions=definitions,
            runtime_environment=runtime_environment,
            tool_timeout=TOOL_TIMEOUT_SECONDS,
            runtime_owner=snapshot_owner,
        )
    except Exception as error:
        cleanup_error: Exception | None = None
        if snapshot_owner is not None:
            close = getattr(snapshot_owner, "close", None)
            if callable(close):
                try:
                    close()
                except Exception as failure:
                    cleanup_error = failure
        if cleanup_error is not None:
            raise StartupError(
                "private runtime snapshot cleanup failed after startup refusal"
            ) from cleanup_error
        if isinstance(error, StartupError):
            raise
        raise StartupError("private runtime snapshot creation refused") from error


class _ResponseQueueClosed(AdapterError):
    pass


class _ResponseQueueFull(AdapterError):
    pass


class _BoundedResponseQueue:
    def __init__(self, max_bytes: int = MAX_RESPONSE_QUEUE_BYTES) -> None:
        if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes < 1:
            raise ValueError("invalid response queue byte bound")
        self.max_bytes = max_bytes
        self._bytes = 0
        self._items: deque[bytes] = deque()
        self._closed = False
        self._condition = asyncio.Condition()

    async def put(self, payload: bytes) -> None:
        if not isinstance(payload, bytes) or not payload or len(payload) > self.max_bytes:
            raise BackendFailure("encoded MCP response exceeds queue byte limit")
        async with self._condition:
            if self._closed:
                raise _ResponseQueueClosed("response queue is closed")
            if self._bytes + len(payload) > self.max_bytes:
                raise _ResponseQueueFull("response queue capacity is exhausted")
            self._items.append(payload)
            self._bytes += len(payload)
            self._condition.notify_all()

    async def get(self) -> bytes | None:
        async with self._condition:
            while not self._items and not self._closed:
                await self._condition.wait()
            if not self._items:
                return None
            payload = self._items.popleft()
            self._bytes -= len(payload)
            self._condition.notify_all()
            return payload

    async def close(self) -> None:
        async with self._condition:
            self._closed = True
            self._condition.notify_all()


class _AsyncWritePipeProtocol(asyncio.Protocol):
    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        on_connection_lost: Callable[[], None],
    ) -> None:
        self._loop = loop
        self._on_connection_lost = on_connection_lost
        self._paused = False
        self._lost: BaseException | None = None
        self._drain_waiter: asyncio.Future[None] | None = None

    def pause_writing(self) -> None:
        self._paused = True

    def resume_writing(self) -> None:
        self._paused = False
        waiter = self._drain_waiter
        if waiter is not None and not waiter.done():
            waiter.set_result(None)

    def connection_lost(self, exc: Exception | None) -> None:
        self._lost = exc if exc is not None else BrokenPipeError("stdout pipe closed")
        waiter = self._drain_waiter
        if waiter is not None and not waiter.done():
            waiter.set_exception(self._lost)
        self._on_connection_lost()

    async def drain(self) -> None:
        if self._lost is not None:
            raise self._lost
        if not self._paused:
            return
        waiter = self._loop.create_future()
        self._drain_waiter = waiter
        try:
            await waiter
        finally:
            if self._drain_waiter is waiter:
                self._drain_waiter = None


def _encode_transport_response(response: dict[str, Any]) -> bytes:
    request_id = response.get("id") if _valid_request_id(response.get("id")) else None
    try:
        encoded = (
            json.dumps(
                response,
                ensure_ascii=False,
                allow_nan=False,
                sort_keys=False,
                separators=(",", ":"),
            ).encode("utf-8")
            + b"\n"
        )
        if len(encoded) > MAX_MCP_RESPONSE_BYTES:
            raise ValueError("encoded response exceeds limit")
        return encoded
    except (TypeError, ValueError, RecursionError):
        fallback = _error_response(
            request_id, INTERNAL_ERROR, "response serialization failed closed"
        )
        return json.dumps(fallback, separators=(",", ":")).encode("utf-8") + b"\n"


async def _wait_for_transport_capacity(
    tasks: set[asyncio.Task[None]], *, max_tasks: int = MAX_TRANSPORT_TASKS
) -> None:
    if isinstance(max_tasks, bool) or not isinstance(max_tasks, int) or max_tasks < 1:
        raise ValueError("invalid transport task bound")
    while len(tasks) >= max_tasks:
        done, unused_pending = await asyncio.wait(
            tuple(tasks), return_when=asyncio.FIRST_COMPLETED
        )
        tasks.difference_update(done)
        await asyncio.gather(*done, return_exceptions=True)


async def _serve_stdio(server: MCPServer) -> None:
    loop = asyncio.get_running_loop()
    reader = asyncio.StreamReader(limit=MAX_REQUEST_LINE_BYTES + 1)
    protocol = asyncio.StreamReaderProtocol(reader)
    response_queue = _BoundedResponseQueue()
    tasks: set[asyncio.Task[None]] = set()
    read_transport: asyncio.ReadTransport | None = None
    write_transport: asyncio.WriteTransport | None = None
    writer_task: asyncio.Task[None] | None = None
    transport_stop_task: asyncio.Task[None] | None = None
    shutting_down = False

    async def stop_transport() -> None:
        await response_queue.close()
        if read_transport is not None:
            read_transport.close()
        if write_transport is not None:
            write_transport.abort()

    def schedule_transport_stop() -> None:
        nonlocal transport_stop_task
        if shutting_down:
            return
        if transport_stop_task is None or transport_stop_task.done():
            transport_stop_task = asyncio.create_task(stop_transport())

    async def drain_responses(write_protocol: _AsyncWritePipeProtocol) -> None:
        assert write_transport is not None
        try:
            while True:
                encoded = await response_queue.get()
                if encoded is None:
                    return
                write_transport.write(encoded)
                await write_protocol.drain()
        except asyncio.CancelledError:
            raise
        except Exception:
            await stop_transport()

    async def process(line: bytes) -> None:
        try:
            response = await server.handle_line(line)
        except asyncio.CancelledError:
            raise
        except Exception:
            response = _error_response(None, INTERNAL_ERROR, "unexpected handler failure")
        if response is None:
            return
        try:
            await response_queue.put(_encode_transport_response(response))
        except _ResponseQueueClosed:
            return
        except _ResponseQueueFull:
            await stop_transport()

    try:
        raw_read_transport, unused_read_protocol = await loop.connect_read_pipe(
            lambda: protocol, sys.stdin.buffer
        )
        read_transport = cast(asyncio.ReadTransport, raw_read_transport)
        raw_transport, write_protocol = await loop.connect_write_pipe(
            lambda: _AsyncWritePipeProtocol(loop, schedule_transport_stop),
            sys.stdout.buffer,
        )
        write_transport = cast(asyncio.WriteTransport, raw_transport)
        write_transport.set_write_buffer_limits(
            high=MAX_MCP_RESPONSE_BYTES, low=max(1, MAX_MCP_RESPONSE_BYTES // 2)
        )
        writer_task = asyncio.create_task(drain_responses(write_protocol))
        while True:
            try:
                line = await reader.readline()
            except ValueError:
                response = _error_response(None, INVALID_REQUEST, "request line exceeds byte limit")
                try:
                    await response_queue.put(_encode_transport_response(response))
                except _ResponseQueueClosed:
                    pass
                except _ResponseQueueFull:
                    await stop_transport()
                break
            if not line:
                break
            await _wait_for_transport_capacity(tasks)
            task = asyncio.create_task(process(line))
            tasks.add(task)
            # Preserve wire order through each handler's first suspension so a
            # following cancellation cannot overtake registration of its call.
            await asyncio.sleep(0)
    finally:
        shutting_down = True
        try:
            # EOF means the client can no longer receive a call response.
            # Cancel/reap active process groups before awaiting handler exit.
            await server.close()
        finally:
            if tasks:
                done, pending = await asyncio.wait(tasks, timeout=STDIO_DRAIN_TIMEOUT)
                if pending:
                    await response_queue.close()
                    for task in pending:
                        task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
            await response_queue.close()
            if writer_task is not None:
                done, unused_pending = await asyncio.wait(
                    {writer_task}, timeout=STDIO_DRAIN_TIMEOUT
                )
                if not done:
                    writer_task.cancel()
                    if write_transport is not None:
                        write_transport.abort()
                await asyncio.gather(writer_task, return_exceptions=True)
            if write_transport is not None:
                write_transport.close()
            if read_transport is not None:
                read_transport.close()
            if transport_stop_task is not None:
                await asyncio.gather(transport_stop_task, return_exceptions=True)


def _bounded_detail(error: Exception) -> str:
    return (" ".join(str(error).splitlines()).strip() or "startup failed")[:240]


def main() -> int:
    try:
        server = build_production_server()
        asyncio.run(_serve_stdio(server))
    except (AdapterError, OSError, RuntimeError) as error:
        print(f"jackel_mcp=refused detail={_bounded_detail(error)}", file=sys.stderr)
        return 1
    except Exception:
        print("jackel_mcp=refused detail=unexpected startup failure", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
