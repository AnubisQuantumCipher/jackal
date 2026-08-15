#!/usr/bin/env python3
"""Isolated source loader for JACKAL's Python release/plugin TCB.

The shell entry points invoke this file with ``python3 -I -S -B``.  That
removes the script directory, user site, environment-controlled Python paths,
and ``.pth`` files from module discovery.  Project modules are then compiled
from the exact declared source bytes below and preloaded into ``sys.modules``;
unlisted sibling modules and stale/malicious ``.pyc`` files cannot shadow
stdlib or JACKAL runtime imports.

This is an integrity boundary, not code signing.  Its exact bytes are included
in the package checksum and Hermes runtime-bundle identity.
"""
from __future__ import annotations

import sys


if not (sys.flags.isolated and sys.flags.no_site):
    print(
        "status=refused reason=python-not-isolated "
        "detail='requires python3 -I -S -B'",
        file=sys.stderr,
    )
    raise SystemExit(126)

# These imports now resolve only against the interpreter's stdlib paths.
import types  # noqa: E402
from pathlib import Path  # noqa: E402
from typing import Any  # noqa: E402


def _load_exact(name: str, path: Path) -> types.ModuleType:
    """Compile one exact UTF-8 source file, bypassing import-path and pyc lookup."""
    if not path.is_file():
        raise RuntimeError(f"isolated-runtime-missing: {name}: {path}")
    raw = path.read_bytes()
    code = compile(raw, str(path), "exec", dont_inherit=True)
    module = types.ModuleType(name)
    module.__file__ = str(path)
    module.__package__ = ""
    module.__loader__ = None
    sys.modules[name] = module
    try:
        exec(code, module.__dict__)
    except BaseException:
        sys.modules.pop(name, None)
        raise
    return module


def _layout() -> tuple[Path, bool]:
    here = Path(__file__).resolve()
    if here.parent.name == "tools" and (here.parents[1] / "release").is_dir():
        return here.parents[1], True
    return here.parent, False


def _path(root: Path, repo: bool, repo_rel: str, package_name: str) -> Path:
    return root / (repo_rel if repo else package_name)


def _run_target(mode: str, argv: list[str]) -> int:
    root, repo = _layout()
    project_modules: list[tuple[str, Path]] = [
        ("formal_receipt", _path(root, repo, "tools/formal_receipt.py", "formal_receipt.py")),
        ("coverage_inventory", _path(root, repo, "tools/coverage_inventory.py", "coverage_inventory.py")),
        ("formal_status_gate", _path(root, repo, "tools/formal_status_gate.py", "formal_status_gate.py")),
        ("receipt_verify", _path(root, repo, "tools/receipt_verify.py", "receipt_verify.py")),
        ("release_validate", _path(root, repo, "tests/release_validate.py", "release_validate.py")),
        ("gaussian_release", _path(root, repo, "tools/gaussian_release.py", "gaussian_release.py")),
    ]
    targets: dict[str, Path] = {
        "range": project_modules[4][1],
        "gaussian": project_modules[5][1],
        "verify": project_modules[3][1],
        "plugin": root / "plugin/hermes/server.py",
    }
    target = targets.get(mode)
    if target is None:
        raise RuntimeError(f"isolated-mode-unknown: {mode}")

    if mode == "plugin":
        _load_exact("bundle_hash", root / "plugin/hermes/bundle_hash.py")
    for name, path in project_modules:
        _load_exact(name, path)

    raw = target.read_bytes()
    globals_dict: dict[str, Any] = {
        "__name__": "__main__",
        "__file__": str(target),
        "__package__": "",
        "__loader__": None,
        "__builtins__": __builtins__,
    }
    sys.argv = [str(target), *argv]
    exec(compile(raw, str(target), "exec", dont_inherit=True), globals_dict)
    return 0


def main(argv: list[str]) -> int:
    if not argv:
        print("usage: isolated_entry.py <range|gaussian|verify|plugin> [args...]", file=sys.stderr)
        return 64
    try:
        return _run_target(argv[0], argv[1:])
    except (OSError, UnicodeError, ValueError, RuntimeError) as exc:
        print(f"status=refused reason=isolated-runtime detail={exc}", file=sys.stderr)
        return 126


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
