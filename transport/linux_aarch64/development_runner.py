#!/usr/bin/env python3
"""Exercise a local VM fixture. Deliberately not a production verifier adapter.

The development manifest only detects fixture drift; it is not an independent
operator authorization. No installed runtime imports this module.
"""
from __future__ import annotations

import hashlib
import fcntl
import json
import os
from pathlib import Path
import resource
import selectors
import struct
import subprocess
import time


class BrokerRefusal(Exception):
    pass


def _no_core() -> None:
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


def _read_exact(stream, amount: int, deadline: float) -> bytes:
    result = bytearray()
    with selectors.DefaultSelector() as selector:
        selector.register(stream, selectors.EVENT_READ)
        while len(result) < amount:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not selector.select(remaining):
                raise BrokerRefusal("guest-timeout")
            chunk = os.read(stream.fileno(), min(65536, amount - len(result)))
            if not chunk:
                raise BrokerRefusal("guest-truncated")
            result.extend(chunk)
    return bytes(result)


def _write_all(stream, data: bytes, deadline: float) -> None:
    remaining_data = memoryview(data)
    os.set_blocking(stream.fileno(), False)
    with selectors.DefaultSelector() as selector:
        selector.register(stream, selectors.EVENT_WRITE)
        while remaining_data:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not selector.select(remaining):
                raise BrokerRefusal("guest-timeout")
            try:
                written = os.write(stream.fileno(), remaining_data)
            except BlockingIOError:
                continue
            if written <= 0:
                raise BrokerRefusal("guest-input-closed")
            remaining_data = remaining_data[written:]


def _snapshot(data: bytes) -> int:
    fd = os.memfd_create("jackal-public-boot", os.MFD_ALLOW_SEALING | os.MFD_CLOEXEC)
    try:
        with os.fdopen(os.dup(fd), "wb") as stream:
            stream.write(data)
        os.lseek(fd, 0, os.SEEK_SET)
        fcntl.fcntl(fd, fcntl.F_ADD_SEALS, fcntl.F_SEAL_WRITE | fcntl.F_SEAL_GROW |
                    fcntl.F_SEAL_SHRINK | fcntl.F_SEAL_SEAL)
        return fd
    except BaseException:
        os.close(fd)
        raise


def call_guest(image: Path, selected: int, certificate: bytes, arguments: list[str],
               timeout: float = 3600) -> subprocess.CompletedProcess:
    if type(selected) is not int or selected not in range(4):
        raise BrokerRefusal("checker-selection")
    if not certificate or len(certificate) > 8 << 20 or len(arguments) > 16:
        raise BrokerRefusal("request-budget")
    fields = []
    for arg in arguments:
        raw = arg.encode("utf-8")
        if len(raw) >= 131072 or b"\0" in raw:
            raise BrokerRefusal("argument-budget")
        fields.append(struct.pack(">Q", len(raw)) + raw)
    request = b"JCKREQ1\n" + struct.pack(">QQQ", selected, len(arguments), len(certificate))
    request += b"".join(fields) + certificate
    manifest = json.loads((image / "development-manifest.json").read_bytes())
    if manifest.get("release_authorized") is not False:
        raise BrokerRefusal("not-development-fixture")
    snapshots = []
    for name, key in (("Image", "kernel_sha256"), ("guest.cpio.gz", "initramfs_sha256")):
        data = (image / name).read_bytes()
        if hashlib.sha256(data).hexdigest() != manifest[key]:
            for fd in snapshots:
                os.close(fd)
            raise BrokerRefusal("fixture-drift")
        snapshots.append(_snapshot(data))
    command = ["/usr/bin/qemu-system-aarch64", "-no-user-config", "-nodefaults",
               "-machine", "virt-11.1,accel=kvm,gic-version=3,dump-guest-core=off",
               "-cpu", "host", "-smp", "1", "-m", "2048",
               "-display", "none", "-monitor", "none", "-nic", "none",
               "-chardev", "stdio,id=private,signal=off,mux=off",
               "-serial", "chardev:private", "-no-reboot",
               "-kernel", f"/proc/self/fd/{snapshots[0]}", "-initrd", f"/proc/self/fd/{snapshots[1]}",
               "-append", "rdinit=/init console=null quiet loglevel=0 panic=-1"]
    deadline = time.monotonic() + timeout
    try:
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, bufsize=0, start_new_session=True,
                               pass_fds=snapshots, preexec_fn=_no_core,
                               env={"PATH": "/usr/bin", "LC_ALL": "C"})
    finally:
        for fd in snapshots:
            os.close(fd)
    try:
        if _read_exact(process.stdout, 8, deadline) != b"JCKRDY1\n":
            raise BrokerRefusal("guest-start-protocol")
        _write_all(process.stdin, request, deadline)
        if _read_exact(process.stdout, 8, deadline) != b"JCKRES1\n":
            raise BrokerRefusal("guest-response-protocol")
        code, out_length, err_length = struct.unpack(">qQQ", _read_exact(process.stdout, 24, deadline))
        output = _read_exact(process.stdout, out_length, deadline)
        errors = _read_exact(process.stdout, err_length, deadline)
        _write_all(process.stdin, b"JCKACK1\n", deadline)
        if _read_exact(process.stdout, 8, deadline) != b"JCKEND1\n":
            raise BrokerRefusal("guest-completion-protocol")
        extra, _diagnostic = process.communicate(timeout=max(0, deadline - time.monotonic()))
        if process.returncode != 0 or extra:
            raise BrokerRefusal("guest-shutdown")
        return subprocess.CompletedProcess(command, code, output, errors)
    except subprocess.TimeoutExpired:
        raise BrokerRefusal("guest-timeout") from None
    finally:
        if process.poll() is None:
            process.kill()
        process.communicate()
        for stream in (process.stdin, process.stdout, process.stderr):
            if stream is not None:
                stream.close()
