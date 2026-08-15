#!/usr/bin/env python3
"""JACKAL Hermes plugin — deterministic runtime-bundle identity.

The plugin's runtime identity is the SHA-256 of the deterministic,
length-framed concatenation of every file declared by
``tools.json:runtime_files``.  Logical names are hashed instead of host paths,
and each logical name has ordered repo/package path candidates.  Therefore the
repository and a faithfully assembled package have the same identity even
though their directory layouts differ.

The covered bytes include the plugin launcher and manifest, every project
Python module imported or executed by ``server.py``, and the exact formal
coverage inventory consumed at runtime.  Native evaluator/checker executables
remain independently pinned in ``MANIFEST.sha256`` and receipts; the manifest
itself cannot be part of this hash because it contains this hash's pin.

The bundle hash is:

  1. computed here (no timestamps or resolved-path bytes in the digest);
  2. compared against the pinned value in `release/MANIFEST.sha256`
     (line `plugin_hermes <SHA-256>`);
  3. threaded into every formal receipt as `identities.plugin_sha256`.

A mismatch is a fail-closed startup refusal (`plugin-bundle-mismatch`).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any


PLUGIN_DIR = Path(__file__).resolve().parent
TOOLS_JSON = PLUGIN_DIR / "tools.json"
BUNDLE_IDENTITY_SCHEMA = "jackal-hermes-runtime-bundle-v2"
_LOGICAL_NAME_RE = re.compile(r"^[A-Za-z0-9._/-]+$")


def _reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-standard JSON constant: {value}")


def _framed(name: str, data: bytes) -> bytes:
    # length-delimited: <name-utf8-len>:<name>\0<data-len>:<data>\0
    name_b = name.encode("utf-8")
    return (str(len(name_b)).encode() + b":" + name_b + b"\0"
            + str(len(data)).encode() + b":" + data + b"\0")


def _load_manifest(plugin_dir: Path) -> dict[str, Any]:
    try:
        manifest = json.loads(
            (plugin_dir / "tools.json").read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_pairs,
            parse_constant=_reject_json_constant,
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise SystemExit(f"plugin-manifest-unreadable: {exc}") from exc
    if manifest.get("schema") != "jackal-hermes-plugin-v1":
        raise SystemExit(f"plugin-manifest-schema: {manifest.get('schema')!r}")
    if manifest.get("bundle_identity_schema") != BUNDLE_IDENTITY_SCHEMA:
        raise SystemExit(
            "plugin-bundle-identity-schema: "
            f"{manifest.get('bundle_identity_schema')!r}"
        )
    return manifest


def resolve_runtime_files(plugin_dir: Path | None = None) -> dict[str, Path]:
    """Resolve logical runtime names to the first existing layout candidate.

    Paths are used only to obtain bytes; the returned physical path is never
    included in the identity.  Logical keys are validated and later sorted so
    JSON object insertion order cannot affect framing order.
    """
    d = plugin_dir or PLUGIN_DIR
    manifest = _load_manifest(d)
    declared = manifest.get("runtime_files")
    if not isinstance(declared, dict) or not declared:
        raise SystemExit("plugin-runtime-files-schema: expected nonempty object")

    resolved: dict[str, Path] = {}
    for logical_name in sorted(declared):
        candidates = declared[logical_name]
        if (not isinstance(logical_name, str)
                or not _LOGICAL_NAME_RE.fullmatch(logical_name)
                or logical_name.startswith("/")
                or ".." in Path(logical_name).parts):
            raise SystemExit(f"plugin-runtime-logical-name: {logical_name!r}")
        if (not isinstance(candidates, list) or not candidates
                or any(not isinstance(item, str) or not item for item in candidates)):
            raise SystemExit(
                f"plugin-runtime-candidates-schema: {logical_name!r}"
            )
        selected = next(
            (d / candidate for candidate in candidates
             if (d / candidate).is_file()),
            None,
        )
        if selected is None:
            raise SystemExit(
                "plugin-runtime-file-missing: "
                f"{logical_name} candidates={candidates!r}"
            )
        resolved[logical_name] = selected

    # ``bundle_files`` is retained as public plugin metadata.  Require every
    # listed plugin-local file to be represented in the stronger runtime map,
    # preventing a future launcher/adapter addition from silently retaining
    # the old, narrower identity boundary.
    bundle_files = manifest.get("bundle_files")
    if (not isinstance(bundle_files, list) or not bundle_files
            or any(not isinstance(item, str) or not item for item in bundle_files)):
        raise SystemExit("plugin-bundle-files-schema: expected nonempty string array")
    selected_local = {
        path.name for logical, path in resolved.items()
        if logical.startswith("plugin/") and path.parent.resolve() == d.resolve()
    }
    missing_local = sorted(set(bundle_files) - selected_local)
    if missing_local:
        raise SystemExit(f"plugin-runtime-local-coverage: {missing_local!r}")
    return resolved


def compute_bundle_hash(plugin_dir: Path | None = None) -> str:
    """Return the deterministic v2 identity of all declared runtime bytes."""
    runtime_files = resolve_runtime_files(plugin_dir)
    h = hashlib.sha256()
    h.update(BUNDLE_IDENTITY_SCHEMA.encode("ascii") + b"\0")
    for logical_name in sorted(runtime_files):
        h.update(_framed(logical_name, runtime_files[logical_name].read_bytes()))
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
