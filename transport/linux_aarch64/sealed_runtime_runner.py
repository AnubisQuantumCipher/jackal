#!/usr/bin/env python3
"""Development-only private replay through an unchanged complete runtime.

This does not authorize, install, or expose a production transport. It accepts
only the retained-receipt/bundle verification methods, preserving their params.
"""
from __future__ import annotations

from contextlib import ExitStack
import hashlib
import json
import os
import selectors
from pathlib import Path
import struct
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
from development_runner import BrokerRefusal, _no_core, _read_exact, _snapshot, _write_all


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise BrokerRefusal("request-json-duplicate")
        result[key] = value
    return result


def _expect_eof(stream, deadline):
    with selectors.DefaultSelector() as selector:
        selector.register(stream, selectors.EVENT_READ)
        remaining = deadline - time.monotonic()
        if remaining <= 0 or not selector.select(remaining):
            raise BrokerRefusal("guest-shutdown-timeout")
        if os.read(stream.fileno(), 1):
            raise BrokerRefusal("guest-unexpected-tail")


def replay(image: Path, request: bytes, timeout: float = 3600) -> subprocess.CompletedProcess:
    # Development ceiling only; accepted-interface qualification is still open.
    if not isinstance(request, bytes) or not request or len(request) > 1 << 30:
        raise BrokerRefusal("request-budget")
    try:
        document = json.loads(request, object_pairs_hook=_pairs,
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonstandard constant")))
    except (ValueError, UnicodeError, RecursionError):
        raise BrokerRefusal("request-json") from None
    if (not isinstance(document, dict) or set(document) != {"jsonrpc", "id", "method", "params"}
            or document.get("jsonrpc") != "2.0"
            or not isinstance(document.get("method"), str)
            or document.get("method") not in {"jackal_verify_receipt", "jackal_verify_bundle"}
            or not isinstance(document.get("params"), dict)):
        raise BrokerRefusal("request-method")
    # Normalize framing only. JSON values and caller expectations are unchanged.
    try:
        request = (json.dumps(document, separators=(",", ":"), allow_nan=False) + "\n").encode()
    except (ValueError, UnicodeError, RecursionError):
        raise BrokerRefusal("request-json") from None
    if not request or len(request) > 1 << 30:
        raise BrokerRefusal("request-budget")
    manifest = json.loads((image / "development-manifest.json").read_bytes())
    if (manifest.get("schema") != "jackal-sealed-runtime-guest-development-v1"
            or manifest.get("release_authorized") is not False):
        raise BrokerRefusal("not-development-fixture")
    with ExitStack() as descriptors:
        snapshots = []
        for name, key in (("Image", "kernel_sha256"), ("guest.cpio.gz", "initramfs_sha256"),
                          ("runtime.ext4", "runtime_image_sha256")):
            data = (image / name).read_bytes()
            if hashlib.sha256(data).hexdigest() != manifest[key]:
                raise BrokerRefusal("fixture-drift")
            fd = _snapshot(data)
            descriptors.callback(os.close, fd)
            snapshots.append(fd)
        command = ["/usr/bin/qemu-system-aarch64", "-no-user-config", "-nodefaults",
            "-machine", "virt-11.1,accel=kvm,gic-version=3,dump-guest-core=off",
            "-cpu", "host", "-smp", "1", "-m", "2048",
            "-display", "none", "-monitor", "none", "-nic", "none",
            "-chardev", "stdio,id=private,signal=off,mux=off", "-serial", "chardev:private",
            "-no-reboot", "-kernel", f"/proc/self/fd/{snapshots[0]}",
            "-initrd", f"/proc/self/fd/{snapshots[1]}",
            "-drive", f"file=/proc/self/fd/{snapshots[2]},format=raw,if=none,id=runtime,readonly=on",
            "-device", "virtio-blk-pci,drive=runtime,disable-legacy=on,vectors=0",
            "-append", "rdinit=/init console=null quiet loglevel=0 panic=-1"]
        deadline = time.monotonic() + timeout
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, bufsize=0, start_new_session=True, pass_fds=snapshots,
            preexec_fn=_no_core, env={"PATH": "/usr/bin", "LC_ALL": "C"})
    try:
        if _read_exact(process.stdout, 8, deadline) != b"JKRRDY1\n":
            raise BrokerRefusal("guest-start-protocol")
        _write_all(process.stdin, b"JKRREQ1\n" + struct.pack(">Q", len(request)) + request, deadline)
        if _read_exact(process.stdout, 8, deadline) != b"JKRRES1\n":
            raise BrokerRefusal("guest-response-protocol")
        code, out_length, err_length = struct.unpack(">qQQ", _read_exact(process.stdout, 24, deadline))
        if out_length > 1 << 30 or err_length > 1 << 30 or out_length + err_length > 1 << 30:
            raise BrokerRefusal("guest-output-budget")
        output = _read_exact(process.stdout, out_length, deadline)
        errors = _read_exact(process.stdout, err_length, deadline)
        _write_all(process.stdin, b"JKRACK1\n", deadline)
        if _read_exact(process.stdout, 8, deadline) != b"JKREND1\n":
            raise BrokerRefusal("guest-completion-protocol")
        process.stdin.close()
        _expect_eof(process.stdout, deadline)
        process.wait(timeout=max(0, deadline - time.monotonic()))
        if process.returncode != 0:
            raise BrokerRefusal("guest-shutdown")
        return subprocess.CompletedProcess(command, code, output, errors)
    except subprocess.TimeoutExpired:
        raise BrokerRefusal("guest-timeout") from None
    finally:
        for stream in (process.stdin, process.stdout):
            if stream is not None:
                stream.close()
        if process.poll() is None:
            process.kill()
        # No cleanup path collects an untrusted output tail. Dedicated-process
        # supervision and retained ownership on termination failure remain open.
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            raise BrokerRefusal("guest-termination-pending") from None
