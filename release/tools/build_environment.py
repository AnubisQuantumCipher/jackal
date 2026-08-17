#!/usr/bin/env python3
"""Record the effective build environment behind the pinned v1.7.0 binaries.

Mission v1.7.1 (A→B→A hardening): exact reconstruction of the pinned checker
executables needs more than the Lean toolchain files already hashed inside the
proof identities — it needs the host SDK, linker, and compiler that Lean's
native pipeline invoked.  This script RECORDS those identities from the live
machine into `release/evidence/build_environment_v170.json`, together with
the binary hashes they produced.  The file is byte-pinned in
`release/MANIFEST.sha256` (row `build-environment`).

This is a reconstruction RECORD, not a live gate: comparing the running
machine's SDK against the pin would turn every OS patch into a false gate
failure.  `--check` therefore verifies only internal consistency — that the
recorded binary hashes still match the pinned binaries on disk — never
environment equality.
"""
from __future__ import annotations

import hashlib
import json
import platform
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "release/evidence/build_environment_v170.json"

BINARIES = {
    "jackal-native": ROOT / "jackal-native",
    "jackal_cert_check": ROOT / "proofs/lean/.lake/build/bin/jackal_cert_check",
    "jackal_gaussian_check": ROOT / "proofs/lean/.lake/build/bin/jackal_gaussian_check",
    "jackal_int_cert_check": ROOT / "proofs/lean/.lake/build/bin/jackal_int_cert_check",
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def cmd(*argv: str) -> str:
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=60)
        out = (proc.stdout or "") + (proc.stderr or "")
        return out.strip()
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"UNAVAILABLE: {exc}"


def record() -> dict:
    manifest_rows = {}
    for line in (ROOT / "release/MANIFEST.sha256").read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            parts = line.split()
            manifest_rows[parts[0]] = parts[-1]
    lean_dir = ROOT / "proofs/lean"
    doc = {
        "schema": "jackal-build-environment-v1",
        "release_epoch": "v1.7.0",
        "recorded_for": "exact reconstruction of the pinned checker executables",
        "host": {
            "macos_product_version": cmd("sw_vers", "-productVersion"),
            "macos_build_version": cmd("sw_vers", "-buildVersion"),
            "arch": platform.machine(),
            "kernel": cmd("uname", "-r"),
        },
        "toolchain": {
            "xcode_select_path": cmd("xcode-select", "-p"),
            "sdk_version": cmd("xcrun", "--show-sdk-version"),
            "sdk_build_version": cmd("xcrun", "--show-sdk-build-version"),
            "sdk_path": cmd("xcrun", "--show-sdk-path"),
            "clang_version": cmd("clang", "--version").splitlines()[0]
                if not cmd("clang", "--version").startswith("UNAVAILABLE")
                else cmd("clang", "--version"),
            "ld_version": cmd("ld", "-v").splitlines()[0]
                if not cmd("ld", "-v").startswith("UNAVAILABLE")
                else cmd("ld", "-v"),
            "elan_version": cmd("elan", "--version"),
            "lake_version": cmd("lake", "--version"),
            "lean_toolchain_file": (lean_dir / "lean-toolchain").read_text().strip(),
            "lean_toolchain_file_sha256": sha(lean_dir / "lean-toolchain"),
            "lakefile_sha256": sha(lean_dir / "lakefile.toml"),
            "lake_manifest_sha256": sha(lean_dir / "lake-manifest.json"),
            "anubis_compiler_pin": manifest_rows.get("compiler_pin", ""),
        },
        "produced_binaries": {
            name: {"sha256": sha(path), "bytes": path.stat().st_size}
            for name, path in BINARIES.items()
        },
        "non_claims": [
            "a record for reconstruction, not proof that no other environment reproduces the same bytes",
            "environment equality is NOT gated: OS/SDK patches do not invalidate the sealed binaries, whose identities are byte-pinned independently",
        ],
    }
    return doc


def main() -> int:
    if "--check" in sys.argv[1:]:
        if not OUT.exists():
            print("BUILD_ENV_FAIL record missing")
            return 1
        doc = json.loads(OUT.read_text())
        errors = []
        for name, entry in doc["produced_binaries"].items():
            path = BINARIES[name]
            if not path.is_file():
                errors.append(f"binary-missing: {name}")
                continue
            got = sha(path)
            if got != entry["sha256"]:
                errors.append(f"binary-drift: {name}: recorded {entry['sha256'][:16]} != live {got[:16]}")
        for err in errors:
            print(f"FAIL {err}")
        print(f"BUILD_ENV_{'PASS' if not errors else 'FAIL'} "
              f"binaries={len(doc['produced_binaries'])} errors={len(errors)}")
        return 1 if errors else 0
    doc = record()
    OUT.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n")
    print(f"BUILD_ENV_WRITTEN {OUT}")
    for name, entry in doc["produced_binaries"].items():
        print(f"  {name} {entry['sha256'][:16]}… {entry['bytes']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
