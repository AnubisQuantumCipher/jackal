#!/usr/bin/env python3
"""Build an explicitly unqualified companion around an unchanged runtime archive.

The caller supplies the archive pin independently. Platform hashes emitted here
are observations, not release authorization. No installed runtime is modified.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import tarfile

from build_development_guest import archive_entry


def build(archive: Path, expected: str, kernel: Path, output: Path,
          interpreter: Path, stdlib: Path) -> dict:
    interpreter = interpreter.resolve(strict=True)
    stdlib = stdlib.resolve(strict=True)
    tool_environment = {"PATH": "/usr/bin", "LC_ALL": "C"}
    observed_stdlib = subprocess.check_output([str(interpreter), "-I", "-S", "-c",
        "import sysconfig; print(sysconfig.get_path('stdlib'))"],
        text=True, env=tool_environment).strip()
    if Path(observed_stdlib).resolve(strict=True) != stdlib:
        raise ValueError("explicit interpreter and stdlib do not match")
    stdlib_guest = "usr/lib/" + stdlib.name
    archive_bytes = archive.read_bytes()
    if hashlib.sha256(archive_bytes).hexdigest() != expected:
        raise ValueError("runtime archive differs from caller pin")
    output.mkdir(exist_ok=False, mode=0o700)
    stage = output / "platform-root"
    stage.mkdir(mode=0o755)
    platform = {}
    runtime = {}

    def put(relative: str, data: bytes, executable: bool, origin: str, record: dict) -> None:
        name = PurePosixPath(relative)
        if name.is_absolute() or not name.parts or any(p in {".", ".."} for p in name.parts):
            raise ValueError("invalid guest member path")
        path = stage / str(name)
        mode = 0o555 if executable else 0o444
        if path.exists():
            if not path.is_file() or path.read_bytes() != data or stat.S_IMODE(path.stat().st_mode) != mode:
                raise ValueError("conflicting platform inputs")
            return
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
        path.write_bytes(data)
        path.chmod(0o555 if executable else 0o444)
        os.utime(path, (0, 0))
        record[str(name)] = {"sha256": hashlib.sha256(data).hexdigest(),
                             "bytes": len(data), "origin": origin, "mode": mode}

    with tarfile.open(fileobj=io.BytesIO(archive_bytes), mode="r:gz") as package:
        seen = set()
        root_name = None
        for member in package:
            name = PurePosixPath(member.name)
            canonical = name.as_posix()
            if (name.is_absolute() or not name.parts or ".." in name.parts
                    or canonical != member.name.rstrip("/") or canonical in seen):
                raise ValueError("invalid or duplicate runtime archive member")
            seen.add(canonical)
            if root_name is None:
                root_name = name.parts[0]
            if name.parts[0] != root_name:
                raise ValueError("multiple package roots")
            if member.isdir():
                directory = stage / "runtime" / Path(*name.parts[1:])
                directory.mkdir(parents=True, exist_ok=True)
                continue
            if not member.isfile() or len(name.parts) < 2:
                raise ValueError("unsupported runtime archive member")
            stream = package.extractfile(member)
            if stream is None:
                raise ValueError("missing runtime archive member")
            put("runtime/" + "/".join(name.parts[1:]), stream.read(),
                bool(member.mode & 0o111), member.name, runtime)

    # The unchanged Linux package resolves its archival platform markers via
    # the source-layout sibling directory. Materialize only the exact context
    # already pinned by its packaged compatibility floor, outside runtime/.
    # This is new companion layout metadata, never a rewrite of old manifests.
    floor_path = stage / "runtime/evidence/compat_v172_floor.json"
    floor = json.loads(floor_path.read_bytes())
    archival = floor["lanes"]["range"]["archival_v1"]
    proof_path = stage / "runtime/evidence/range_proof_identity_v1.json"
    checker_path = stage / "runtime/jackal_cert_check_v170"
    proof_bytes = proof_path.read_bytes()
    checker_digest = hashlib.sha256(checker_path.read_bytes()).hexdigest()
    if (archival["mode"] != "replay-only" or archival["allowed_release_epochs"] != ["v1.5.0"]
            or archival["checker_file"] != "jackal_cert_check_v170"
            or hashlib.sha256(proof_bytes).hexdigest() != archival["identity_file_sha256"]
            or checker_digest != archival["checker_sha256"]
            or json.loads(proof_bytes)["checker"]["sha256"] != checker_digest):
        raise ValueError("packaged archival context does not match its own pinned floor")
    put("release/evidence/range_proof_identity.linux-aarch64.json", proof_bytes, False,
        "runtime/evidence/range_proof_identity_v1.json", platform)
    put("release/evidence/archival_range_checker.linux-aarch64", (checker_digest + "\n").encode(),
        False, "runtime/evidence/compat_v172_floor.json:lanes.range.archival_v1", platform)

    put("usr/bin/python3", interpreter.read_bytes(), True, str(interpreter), platform)
    # GUI bindings are outside this headless verifier platform. Their optional
    # Tcl/Tk dependencies are not installed on the source host either.
    excluded_stdlib = []
    for path in sorted(stdlib.rglob("*")):
        relative = path.relative_to(stdlib)
        if any(p in {"site-packages", "__pycache__"} for p in relative.parts) or path.suffix == ".pyc":
            continue
        if "tkinter" in relative.parts or path.name.startswith("_tkinter."):
            if path.is_file():
                excluded_stdlib.append(relative.as_posix())
            continue
        if path.is_file():
            put(stdlib_guest + "/" + relative.as_posix(), path.read_bytes(),
                bool(path.stat().st_mode & 0o111), str(path.resolve()), platform)

    # Resolve every declared ELF dependency from trusted system library paths.
    # This is a development closure; runtime-loaded non-ELF resources still need
    # explicit release qualification. No supplied executable is run to resolve it.
    def is_elf(path: Path) -> bool:
        if not path.is_file():
            return False
        with path.open("rb") as stream:
            return stream.read(4) == b"\x7fELF"

    queue = [p for p in stage.rglob("*") if is_elf(p)]
    inspected = set()
    while queue:
        path = queue.pop()
        if path in inspected:
            continue
        inspected.add(path)
        dynamic = subprocess.check_output(["/usr/bin/readelf", "-d", str(path)], text=True, env=tool_environment)
        headers = subprocess.check_output(["/usr/bin/readelf", "-l", str(path)], text=True, env=tool_environment)
        search_rules = re.findall(r"\((?:RPATH|RUNPATH)\).*?\[([^\]]*)\]", dynamic)
        if any(rule != "/usr/lib" for rule in search_rules):
            raise ValueError("ELF search rules need explicit platform qualification: " + str(path))
        elf_header = subprocess.check_output(["/usr/bin/readelf", "-h", str(path)],
            text=True, env=tool_environment)
        if not re.search(r"Machine:\s+AArch64\s*$", elf_header, re.MULTILINE):
            raise ValueError("platform ELF architecture mismatch")
        needed = re.findall(r"\(NEEDED\).*?\[([^\]]+)\]", dynamic)
        interpreters = re.findall(r"Requesting program interpreter: ([^\]]+)\]", headers)
        for requested in [*needed, *interpreters]:
            if requested.startswith("/"):
                guest_name = requested.lstrip("/")
                source = Path(requested).resolve(strict=True)
            else:
                if "/" in requested:
                    raise ValueError("unsupported ELF dependency path")
                guest_name = "usr/lib/" + requested
                source = (Path("/usr/lib") / requested).resolve(strict=True)
            destination = stage / guest_name
            already_present = destination.exists()
            put(guest_name, source.read_bytes(), True, str(source), platform)
            if not already_present:
                queue.append(destination)
    for name in ("tmp", "dev", "proc"):
        (stage / name).mkdir(exist_ok=True, mode=0o755)

    # Normalize independently of caller umask; the host output stays private.
    directories = {}
    for directory in [stage, *(p for p in stage.rglob("*") if p.is_dir())]:
        directory.chmod(0o755)
        directories[str(directory.relative_to(stage))] = 0o755

    guest_source = Path(__file__).with_name("sealed_runtime_guest.c").read_bytes()
    (output / "guest_init.c").write_bytes(guest_source)
    subprocess.run(["/usr/bin/gcc", "-std=c11", "-Wall", "-Wextra", "-Werror", "-static",
                    "-Os", "-Wl,--build-id=none", "-o", str(output / "init"),
                    str(output / "guest_init.c")], check=True)
    init_bytes = (output / "init").read_bytes()
    cpio = archive_entry("init", init_bytes, stat.S_IFREG | 0o700, 1)
    for i, name in enumerate(("dev", "sealed"), start=2):
        cpio += archive_entry(name, b"", stat.S_IFDIR | 0o755, i)
    cpio += archive_entry("TRAILER!!!", b"", 0, 0)
    initramfs = gzip.compress(cpio, mtime=0)
    (output / "guest.cpio.gz").write_bytes(initramfs)
    kernel_bytes = kernel.read_bytes()
    (output / "Image").write_bytes(kernel_bytes)
    size = sum(p.stat().st_size for p in stage.rglob("*") if p.is_file())
    disk_size = ((size + (128 << 20) + 4095) // 4096) * 4096
    disk = output / "runtime.ext4"
    with disk.open("xb") as stream:
        stream.truncate(disk_size)
    subprocess.run(["/usr/bin/mke2fs", "-q", "-t", "ext4", "-F", "-b", "4096",
                    "-O", "^has_journal", "-E", "lazy_itable_init=0",
                    "-d", str(stage), str(disk)], check=True)
    with disk.open("rb") as stream:
        disk_digest = hashlib.file_digest(stream, "sha256").hexdigest()
    manifest = {"schema": "jackal-sealed-runtime-guest-development-v1",
                "release_authorized": False, "runtime_archive_sha256": expected,
                "runtime_files": runtime, "platform_files": platform, "directories": directories,
                "guest_source_sha256": hashlib.sha256(guest_source).hexdigest(),
                "kernel_sha256": hashlib.sha256(kernel_bytes).hexdigest(),
                "initramfs_sha256": hashlib.sha256(initramfs).hexdigest(),
                "runtime_image_sha256": disk_digest,
                "excluded_stdlib": excluded_stdlib,
                "non_claims": ["Development closure, not operator authorization",
                               "No production integration or complete compatibility qualification"]}
    (output / "development-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return {key: value for key, value in manifest.items() if key not in {"runtime_files", "platform_files"}}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--kernel", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--python", type=Path, required=True)
    parser.add_argument("--stdlib", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.archive.resolve(), args.expected_sha256,
                           args.kernel.resolve(), args.output.resolve(), args.python, args.stdlib), indent=2))
