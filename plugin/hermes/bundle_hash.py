#!/usr/bin/env python3
"""JACKAL Hermes plugin — deterministic bundle-hash computation.

The plugin's runtime identity is the SHA-256 of the deterministic
concatenation of every shipped plugin file in the order declared by
`tools.json` (`bundle_files`), each framed with its length prefix.

The bundle hash is:

  1. computed here (no ambient state, no timestamps, no path leaks);
  2. compared against the pinned value in `release/MANIFEST.sha256`
     (line `plugin_hermes <SHA-256>`);
  3. threaded into every formal receipt as `identities.plugin_sha256`.

A mismatch is a fail-closed startup refusal (`plugin-bundle-mismatch`).
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path


PLUGIN_DIR = Path(__file__).resolve().parent
TOOLS_JSON = PLUGIN_DIR / "tools.json"


def _framed(name: str, data: bytes) -> bytes:
    # length-delimited: <name-utf8-len>:<name>\0<data-len>:<data>\0
    name_b = name.encode("utf-8")
    return (str(len(name_b)).encode() + b":" + name_b + b"\0"
            + str(len(data)).encode() + b":" + data + b"\0")


def compute_bundle_hash(plugin_dir: Path | None = None) -> str:
    """Deterministic SHA-256 of the shipped plugin bundle (files in
    `tools.json:bundle_files` order, framed with lengths)."""
    d = plugin_dir or PLUGIN_DIR
    manifest = json.loads((d / "tools.json").read_text())
    if manifest.get("schema") != "jackal-hermes-plugin-v1":
        raise SystemExit(f"plugin-manifest-schema: {manifest.get('schema')!r}")
    h = hashlib.sha256()
    h.update(b"jackal-hermes-bundle-v1\0")
    for name in manifest["bundle_files"]:
        p = d / name
        if not p.exists():
            raise SystemExit(f"plugin-bundle-file-missing: {name}")
        h.update(_framed(name, p.read_bytes()))
    return h.hexdigest()


def load_pinned_bundle_hash(root: Path) -> str | None:
    """Read `plugin_hermes <hash>` from `release/MANIFEST.sha256`, if present."""
    m = root / "release" / "MANIFEST.sha256"
    if not m.exists():
        return None
    for ln in m.read_text().splitlines():
        ln = ln.strip()
        if ln.startswith("plugin_hermes "):
            parts = ln.split()
            if len(parts) >= 2:
                return parts[-1]
    return None


def find_repo_root(start: Path | None = None) -> Path:
    """Walk upward from `start` (or PLUGIN_DIR) looking for `release/MANIFEST.sha256`.

    Falls back to the plugin dir itself (shipped-package layout, where
    MANIFEST.sha256 is a sibling of the plugin subtree).
    """
    p = (start or PLUGIN_DIR).resolve()
    for step in [p, *p.parents]:
        if (step / "release" / "MANIFEST.sha256").exists():
            return step
        if (step / "MANIFEST.sha256").exists() and step != p:
            return step
    return PLUGIN_DIR


def load_pinned_bundle_hash_any(root: Path | None = None) -> str | None:
    """Look up the plugin bundle hash in either the repo MANIFEST or the
    shipped-package MANIFEST sibling (both use the same `plugin_hermes` key)."""
    r = root or find_repo_root()
    for candidate in (r / "release" / "MANIFEST.sha256", r / "MANIFEST.sha256"):
        if candidate.exists():
            for ln in candidate.read_text().splitlines():
                ln = ln.strip()
                if ln.startswith("plugin_hermes "):
                    parts = ln.split()
                    if len(parts) >= 2:
                        return parts[-1]
    return None


if __name__ == "__main__":
    action = sys.argv[1] if len(sys.argv) > 1 else "print"
    computed = compute_bundle_hash()
    if action == "print":
        print(computed)
        sys.exit(0)
    if action == "verify":
        pinned = load_pinned_bundle_hash_any()
        if pinned is None:
            print("no pinned plugin_hermes hash", file=sys.stderr)
            sys.exit(2)
        if pinned != computed:
            print(f"plugin-bundle-mismatch: computed {computed} != pinned {pinned}",
                  file=sys.stderr)
            sys.exit(1)
        print(f"plugin-bundle-verified {computed}")
        sys.exit(0)
    print(f"usage: {os.path.basename(sys.argv[0])} [print|verify]", file=sys.stderr)
    sys.exit(2)
