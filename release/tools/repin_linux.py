#!/usr/bin/env python3
"""Derive a per-host JACKAL release manifest for a locally built runtime.

The committed ``release/MANIFEST.sha256`` pins the official macOS arm64 release
bytes. A source build on another host produces byte-different *compiled*
artifacts — the Anubis-built ``jackal-native`` and the three Lean-proved checker
binaries — while every producer (``.py``), identity (``.json``) and the Anubis
source (``.anb``) stay byte-identical across hosts.

This tool writes ``release/MANIFEST.<host>.sha256`` as the committed manifest
with exactly those compiled-binary rows re-hashed from live bytes and the
``compiler_pin`` row rebound to the local Anubis compiler. Every other row is
copied verbatim, so the host manifest asserts the same release identity except
for the platform-specific compiled bytes. It never mutates the macOS manifest.

Usage:
  JACKAL_ANUBIS_COMPILER_PATH=/path/to/anubis python3 release/tools/repin_linux.py --plan
  ...                                          python3 release/tools/repin_linux.py --write
"""
from __future__ import annotations

import argparse
import hashlib
import os
import platform
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MACOS_MANIFEST = ROOT / "release/MANIFEST.sha256"

# row-label -> repo-relative path of the compiled binary it pins
BINARY_ROWS = {
    "evaluator": "jackal-native",
    "checker": "proofs/lean/.lake/build/bin/jackal_cert_check",
    "gaussian-checker": "proofs/lean/.lake/build/bin/jackal_gaussian_check",
    "int-cert-checker": "proofs/lean/.lake/build/bin/jackal_int_cert_check",
}

# identity-row-label -> (base evidence filename without extension, digest-row-label)
# When a host-suffixed evidence file exists, the identity row's path+sha and the
# paired digest row are rebound to it. The macOS evidence files stay in place.
PROOF_IDENTITY_ROWS = {
    "range-proof-identity": ("range_proof_identity_v172", "range-proof-digest"),
    "gaussian-proof-identity": ("gaussian_proof_identity", "gaussian-proof-digest"),
    "int-cert-proof-identity": ("int_cert_proof_identity_v172", "int-cert-proof-digest"),
    "archival-range-proof-identity": ("range_proof_identity", "archival-range-proof-digest"),
}
EVIDENCE_DIR = "release/evidence"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def host_tag() -> str:
    system = platform.system().lower()
    machine = platform.machine().lower()
    return f"{system}-{machine}"


def compiler_path() -> Path:
    configured = os.environ.get("JACKAL_ANUBIS_COMPILER_PATH")
    if not configured:
        sys.exit("REPIN_LINUX_REFUSED detail=set JACKAL_ANUBIS_COMPILER_PATH to the anubis compiler")
    path = Path(configured)
    if path.is_symlink():
        sys.exit(f"REPIN_LINUX_REFUSED detail=compiler authority must not be a symlink: {path}")
    if not path.is_file():
        sys.exit(f"REPIN_LINUX_REFUSED detail=compiler not found: {path}")
    return path


def build_manifest() -> str:
    macos_rows = MACOS_MANIFEST.read_text(encoding="utf-8").splitlines()
    comp = compiler_path()
    comp_sha = sha256(comp)
    tag = host_tag()

    # Omarchy edition rebinds the archival v1.7.0 range checker row to the
    # natively rebuilt checker named by release/evidence/archival_range_checker.<host>.
    archival_marker = ROOT / EVIDENCE_DIR / f"archival_range_checker.{tag}"
    archival_sha = None
    if archival_marker.is_file():
        text = archival_marker.read_text().strip()
        if len(text) == 64:
            archival_sha = text

    def host_evidence(base: str) -> Path | None:
        candidate = ROOT / EVIDENCE_DIR / f"{base}.{tag}.json"
        return candidate if candidate.is_file() else None

    # Pre-scan which digest rows a host evidence file will override, so the
    # paired digest row is rewritten in place from the same file.
    digest_overrides: dict[str, str] = {}
    for id_label, (base, digest_label) in PROOF_IDENTITY_ROWS.items():
        ev = host_evidence(base)
        if ev is None:
            continue
        import json as _json
        internal = _json.loads(ev.read_text(encoding="utf-8")).get("identity_digest_sha256")
        if not isinstance(internal, str) or len(internal) != 64:
            sys.exit(f"REPIN_LINUX_REFUSED detail=host evidence lacks identity_digest_sha256: {ev}")
        digest_overrides[digest_label] = internal

    out: list[str] = []
    seen_binary: set[str] = set()
    for line in macos_rows:
        if not line or line.startswith("#"):
            out.append(line)
            continue
        label = line.split()[0]
        if label in BINARY_ROWS:
            target = ROOT / BINARY_ROWS[label]
            if not target.is_file():
                sys.exit(f"REPIN_LINUX_REFUSED detail=missing built artifact: {target}")
            name = line.split()[1]
            out.append(f"{label} {name} {sha256(target)}")
            seen_binary.add(label)
        elif label == "compiler_pin":
            out.append(f"compiler_pin anubis-{comp_sha[:12]} {comp_sha}")
        elif label in PROOF_IDENTITY_ROWS:
            base, _ = PROOF_IDENTITY_ROWS[label]
            ev = host_evidence(base)
            if ev is None:
                out.append(line)  # keep macOS evidence row verbatim
            else:
                rel = ev.relative_to(ROOT)
                out.append(f"{label} {rel} {sha256(ev)}")
        elif label in digest_overrides:
            out.append(f"{label} {digest_overrides[label]}")
        elif label == "archival-range-checker" and archival_sha is not None:
            name = line.split()[1]
            out.append(f"{label} {name} {archival_sha}")
        else:
            out.append(line)
    # Omarchy edition: append the architecture-qualified approved Z3 anchor row
    z3marker = ROOT / EVIDENCE_DIR / f"approved_z3.{tag}"
    if z3marker.is_file():
        parts = z3marker.read_text().split()
        if len(parts) >= 2 and len(parts[1]) == 64:
            out.append(f"approved-z3-{tag} jackal_z3_v4154 {parts[1]}")
    missing = set(BINARY_ROWS) - seen_binary
    if missing:
        sys.exit(f"REPIN_LINUX_REFUSED detail=manifest lacked binary rows: {sorted(missing)}")
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Derive a per-host JACKAL release manifest")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--plan", action="store_true", help="print without writing (default)")
    modes.add_argument("--check", action="store_true", help="compare with the on-disk host manifest")
    modes.add_argument("--write", action="store_true", help="write release/MANIFEST.<host>.sha256")
    args = parser.parse_args(argv)

    text = build_manifest()
    target = ROOT / f"release/MANIFEST.{host_tag()}.sha256"

    if args.write:
        tmp = target.with_suffix(target.suffix + ".tmp")
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, target)
        print(f"REPIN_LINUX_WROTE path={target.relative_to(ROOT)} sha256={hashlib.sha256(text.encode()).hexdigest()}")
    elif args.check:
        if not target.is_file():
            sys.exit(f"REPIN_LINUX_REFUSED detail=host manifest absent: {target}")
        if target.read_text(encoding="utf-8") != text:
            sys.exit(f"REPIN_LINUX_MISMATCH path={target.relative_to(ROOT)}")
        print(f"REPIN_LINUX_MATCH path={target.relative_to(ROOT)}")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
