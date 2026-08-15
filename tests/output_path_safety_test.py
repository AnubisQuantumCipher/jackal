#!/usr/bin/env python3
"""Regression gates for write-once formal-receipt output paths."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import os
import stat
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from formal_receipt import write_new_file_atomic  # noqa: E402
import gaussian_release as gr  # noqa: E402


def _load_range_validator():
    path = ROOT / "tests" / "release_validate.py"
    spec = importlib.util.spec_from_file_location("output_safety_release_validate", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load range validator")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


rv = _load_range_validator()


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="jackal-output-safety-") as raw:
        directory = Path(raw)
        sentinel = directory / "sentinel"
        sentinel.write_bytes(b"DO NOT MODIFY\n")
        sentinel_hash = digest(sentinel)

        # The common writer publishes complete 0600 bytes and refuses reuse.
        fresh = directory / "fresh.json"
        write_new_file_atomic(fresh, b'{"ok":true}\n')
        if fresh.read_bytes() != b'{"ok":true}\n':
            raise SystemExit("fresh output bytes changed")
        if stat.S_IMODE(fresh.stat().st_mode) != 0o600:
            raise SystemExit("fresh output mode is not 0600")
        try:
            write_new_file_atomic(fresh, b"overwrite")
        except FileExistsError:
            pass
        else:
            raise SystemExit("existing output was overwritten")

        # A final-component symlink is an existing output, never followed.
        linked = directory / "linked.json"
        linked.symlink_to(sentinel)
        try:
            write_new_file_atomic(linked, b"overwrite")
        except FileExistsError:
            pass
        else:
            raise SystemExit("symlink output was followed")

        # Both release lanes reject an existing/aliased destination before
        # resolving or executing untrusted artifacts.
        try:
            rv.validate_release(
                expr="x", lo="0", hi="1", evaluator="missing-evaluator",
                checker="missing-checker", expected_evaluator="0" * 64,
                expected_checker="0" * 64, formal_receipt_path=str(sentinel),
            )
        except rv.ReleaseRefusal as exc:
            if exc.cls != "receipt-output-exists":
                raise SystemExit(f"range wrong refusal: {exc.cls}") from exc
        else:
            raise SystemExit("range accepted existing output")

        gaussian_args = argparse.Namespace(
            receipt=str(sentinel), producer="missing-producer",
            checker="missing-checker", expected_producer="0" * 64,
            expected_checker="0" * 64, expression="exp(-1*(x-0)^2)",
            lower="-1", upper="1", tolerance="1/1000", timeout=1,
            release_epoch="v1.3.0", plugin_sha256=None,
        )
        try:
            gr.release(gaussian_args)
        except gr.Refusal as exc:
            if exc.cls != "receipt-output-exists":
                raise SystemExit(f"Gaussian wrong refusal: {exc.cls}") from exc
        else:
            raise SystemExit("Gaussian accepted existing output")

        if digest(sentinel) != sentinel_hash or sentinel.read_bytes() != b"DO NOT MODIFY\n":
            raise SystemExit("existing output target was modified")

    print("OUTPUT_PATH_SAFETY_PASS cases=6 mode=write-once-atomic")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
