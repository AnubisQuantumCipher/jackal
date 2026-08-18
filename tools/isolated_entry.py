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
        ("int_cert_release", _path(root, repo, "tools/int_cert_release.py", "int_cert_release.py")),
    ]
    targets: dict[str, Path] = {
        "range": project_modules[4][1],
        "gaussian": project_modules[5][1],
        "verify": project_modules[3][1],
        "int-cert": project_modules[6][1],
        "plugin": root / "plugin/hermes/server.py",
    }
    if mode == "emit-variant-receipt":
        # Preload the formal_receipt module and dispatch inline (no external
        # script needed).  The wrappers pass all required paths as flags.
        for name, path in project_modules:
            _load_exact(name, path)
        return _emit_variant_receipt(argv)
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


def _emit_variant_receipt(argv: list[str]) -> int:
    """Emit a canonical jackal-formal-receipt-v1 for a rational-fragment cert.

    Flags (all required):
      --variant sqrt_rat|exp_rat|ln_rat|sin_rat|cos_rat|atan_rat|tanh_rat
      --expression <expr>
      --lower <lo>          --upper <hi>
      --cert <cert.txt>     (bytes already accepted by the checker)
      --producer <path>     --checker <path>
      --proof-identity <range_proof_identity.json>
      --inventory <formal_coverage_inventory.json>
      --release-epoch <label>
      --output <receipt.json>
    """
    import argparse
    import hashlib
    ap = argparse.ArgumentParser(prog="emit-variant-receipt")
    # Admission mirrors formal_receipt.RATIONAL_VARIANTS (the builder's own
    # fail-closed lock) instead of a hardcoded pair — audit finding
    # 2026-08-16: the v1.4.2-era pair silently excluded the five v1.5.0
    # variants from the packaged receipt path.
    import formal_receipt as _fr_variants
    ap.add_argument("--variant", required=True,
                    choices=tuple(sorted(_fr_variants.RATIONAL_VARIANTS)))
    ap.add_argument("--expression", required=True)
    ap.add_argument("--lower", required=True)
    ap.add_argument("--upper", required=True)
    ap.add_argument("--cert", required=True)
    ap.add_argument("--producer", required=True)
    ap.add_argument("--checker", required=True)
    ap.add_argument("--proof-identity", required=True, dest="proof_identity")
    ap.add_argument("--inventory", required=True)
    ap.add_argument("--release-epoch", required=True, dest="release_epoch")
    ap.add_argument("--output", required=True)
    ns = ap.parse_args(argv)
    import formal_receipt as fr
    destination = fr.require_fresh_output(ns.output)
    cert_bytes = Path(ns.cert).read_bytes()
    prod_sha = hashlib.sha256(Path(ns.producer).read_bytes()).hexdigest()
    chk_sha = hashlib.sha256(Path(ns.checker).read_bytes()).hexdigest()
    inv_bytes = Path(ns.inventory).read_bytes()
    proof = fr.load_proof_identity_binding(Path(ns.proof_identity))
    hdr = fr._parse_cert_header(cert_bytes)
    encl_lo, encl_hi = hdr.get("output", "").split(" ", 1)
    receipt = fr.build_variant_formal_receipt(
        variant=ns.variant, release_epoch=ns.release_epoch,
        request={"command": "range-bound-cert", "expression": ns.expression,
                 "input_lo": ns.lower, "input_hi": ns.upper},
        enclosure=(encl_lo, encl_hi),
        cert_bytes=cert_bytes,
        producer_sha256=prod_sha, checker_sha256=chk_sha,
        canonical_lo=fr.canonical_rat(ns.lower),
        canonical_hi=fr.canonical_rat(ns.upper),
        request_commitment_b64=fr.request_commitment_b64(
            "range-bound-cert", ns.expression, ns.lower, ns.upper),
        coverage_inventory_sha256=hashlib.sha256(inv_bytes).hexdigest(),
        proof_identity=proof,
        plugin_sha256=None,
    )
    fr.write_new_file_atomic(
        destination, fr.dump_receipt(receipt).encode("utf-8"))
    return 0


def main(argv: list[str]) -> int:
    if not argv:
        print("usage: isolated_entry.py <range|gaussian|int-cert|verify|plugin|emit-variant-receipt> [args...]", file=sys.stderr)
        return 64
    try:
        return _run_target(argv[0], argv[1:])
    except (OSError, UnicodeError, ValueError, RuntimeError) as exc:
        print(f"status=refused reason=isolated-runtime detail={exc}", file=sys.stderr)
        return 126


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
