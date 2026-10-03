#!/usr/bin/env python3
"""Build an unqualified, deterministic-layout VM fixture from explicit inputs.

This records observed identities; it does not authorize a release or replace an
operator's trusted pins. The output is never consumed by installed JACKAL.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess


def archive_entry(name: str, data: bytes, mode: int, inode: int) -> bytes:
    encoded = name.encode() + b"\0"
    fields = (inode, mode, 0, 0, 1, 0, len(data), 0, 0, 0, 0, len(encoded), 0)
    header = b"070701" + b"".join(f"{field:08x}".encode() for field in fields)
    prefix = header + encoded
    return prefix + b"\0" * (-len(prefix) % 4) + data + b"\0" * (-len(data) % 4)


def build(runtime: Path, kernel: Path, output: Path, compiler: Path) -> dict:
    output.mkdir(parents=False, exist_ok=False, mode=0o700)
    source = Path(__file__).with_name("guest_init.c").read_bytes()
    (output / "guest_init.c").write_bytes(source)
    compiled = output / "init"
    subprocess.run([str(compiler), "-std=c11", "-Wall", "-Wextra", "-Werror", "-static",
                    "-Os", "-Wl,--build-id=none", "-o", str(compiled),
                    str(output / "guest_init.c")], check=True,
                   env={"PATH": "/usr/bin", "LC_ALL": "C", "SOURCE_DATE_EPOCH": "0"})
    files = {"init": (compiled.read_bytes(), stat.S_IFREG | 0o700)}
    origins = {"init-source": hashlib.sha256(source).hexdigest()}
    inputs = {
        "checkers/range": runtime / "jackal_cert_check",
        "checkers/archival-range": runtime / "jackal_cert_check_v170",
        "checkers/integral": runtime / "jackal_int_cert_check",
        "checkers/gaussian": runtime / "jackal_gaussian_check",
    }
    for name in ("ld-linux-aarch64.so.1", "libc.so.6", "libpthread.so.0",
                 "libdl.so.2", "librt.so.1", "libm.so.6"):
        inputs["usr/lib/" + name] = Path("/usr/lib") / name
    inputs["lib/ld-linux-aarch64.so.1"] = Path("/usr/lib/ld-linux-aarch64.so.1")
    for name, path in inputs.items():
        # Only public, trusted fixture binaries are copied. No request data.
        resolved = path.resolve(strict=True)
        with resolved.open("rb") as handle:
            if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
                raise ValueError("nonregular fixture input")
            data = handle.read()
        files[name] = (data, stat.S_IFREG | 0o555)
        origins[name] = {"path": str(resolved), "sha256": hashlib.sha256(data).hexdigest()}
    for name in ("dev", "checkers", "lib", "usr", "usr/lib"):
        files[name] = (b"", stat.S_IFDIR | 0o755)
    archive = bytearray()
    for inode, (name, (data, mode)) in enumerate(sorted(files.items()), start=1):
        archive.extend(archive_entry(name, data, mode, inode))
    archive.extend(archive_entry("TRAILER!!!", b"", 0, 0))
    image = gzip.compress(bytes(archive), mtime=0)
    (output / "guest.cpio.gz").write_bytes(image)
    kernel_bytes = kernel.read_bytes()
    (output / "Image").write_bytes(kernel_bytes)
    manifest = {
        "schema": "jackal-private-guest-development-v1", "release_authorized": False,
        "host": "linux-aarch64", "inputs": origins,
        "kernel_sha256": hashlib.sha256(kernel_bytes).hexdigest(),
        "initramfs_sha256": hashlib.sha256(image).hexdigest(),
        "guest_init_sha256": hashlib.sha256(compiled.read_bytes()).hexdigest(),
        "compiler_sha256": hashlib.sha256(compiler.read_bytes()).hexdigest(),
        "non_claims": ["Not a release pin", "No independent implementation qualification",
                       "No runtime integration or supported-context acceptance claim"],
    }
    (output / "development-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--kernel", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--compiler", type=Path, default=Path("/usr/bin/gcc"))
    args = parser.parse_args()
    print(json.dumps(build(args.runtime.resolve(), args.kernel.resolve(),
                           args.output.resolve(), args.compiler.resolve()), indent=2))
