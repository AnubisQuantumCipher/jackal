#!/usr/bin/env python3
"""Fail-closed release gate for theorem-backed Gaussian integration."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from fractions import Fraction
from pathlib import Path
from typing import Any

from formal_receipt import (
    build_gaussian_formal_receipt,
    canonical_json_bytes,
    canonical_rat,
    gaussian_request_commitment_b64,
)
from formal_status_gate import StatusRefusal, derive_status, load_inventory


class Refusal(Exception):
    def __init__(self, cls: str, detail: str = "") -> None:
        super().__init__(f"{cls}: {detail}")
        self.cls = cls
        self.detail = detail


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_file(raw: str, executable: bool = False) -> Path:
    path = Path(raw).expanduser().resolve()
    if not path.is_file():
        raise Refusal("artifact-missing", str(path))
    if executable and not os.access(path, os.X_OK):
        raise Refusal("artifact-not-executable", str(path))
    return path


def validate_pin(value: str, name: str) -> str:
    if re.fullmatch(r"[0-9a-f]{64}", value or "") is None:
        raise Refusal("bad-identity-pin", name)
    return value


def parse_certificate(raw: bytes) -> dict[str, str]:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise Refusal("certificate-not-utf8", str(exc)) from exc
    if not text.endswith("\n") or text.endswith("\n\n"):
        raise Refusal("certificate-framing", "must end with exactly one newline")
    lines = text[:-1].split("\n")
    if len(lines) != 18 or lines[0] != "jackal-gaussian-integral-cert v1" or lines[-1] != "end":
        raise Refusal("certificate-schema", "unexpected canonical line layout")
    fields: dict[str, str] = {"schema": lines[0]}
    for line in lines[1:-1]:
        if " " not in line:
            raise Refusal("certificate-field", line)
        key, value = line.split(" ", 1)
        if key in fields or not value:
            raise Refusal("certificate-field", key)
        fields[key] = value
    required = {
        "operation", "assurance", "family", "expression", "lower", "upper",
        "tolerance", "A-token", "mu-token", "scale", "method", "core",
        "degree", "sqrt-pi-lower", "sqrt-pi-upper", "output",
    }
    if set(fields) != required | {"schema"}:
        raise Refusal("certificate-fields", str(sorted(set(fields) ^ (required | {"schema"}))))
    return fields


def release(args: argparse.Namespace) -> dict[str, Any]:
    receipt_path = Path(args.receipt).expanduser().resolve()
    if receipt_path.exists():
        receipt_path.unlink()

    producer = resolve_file(args.producer)
    checker = resolve_file(args.checker, executable=True)
    expected_producer = validate_pin(args.expected_producer, "producer")
    expected_checker = validate_pin(args.expected_checker, "checker")
    producer_pre = sha256_file(producer)
    checker_pre = sha256_file(checker)
    if producer_pre != expected_producer:
        raise Refusal("producer-identity", f"observed={producer_pre}")
    if checker_pre != expected_checker:
        raise Refusal("checker-identity", f"observed={checker_pre}")

    try:
        canonical_lo = canonical_rat(args.lower)
        canonical_hi = canonical_rat(args.upper)
        canonical_tolerance = canonical_rat(args.tolerance)
    except ValueError as exc:
        raise Refusal("request-rational", str(exc)) from exc
    if Fraction(canonical_lo) >= Fraction(canonical_hi):
        raise Refusal("request-domain", "lower must be below upper")
    if Fraction(canonical_tolerance) <= 0:
        raise Refusal("request-tolerance", "must be positive")

    produced = subprocess.run(
        [
            sys.executable,
            str(producer),
            "emit",
            "--expression",
            args.expression,
            "--lower",
            canonical_lo,
            "--upper",
            canonical_hi,
            "--tolerance",
            canonical_tolerance,
        ],
        capture_output=True,
        timeout=args.timeout,
    )
    if produced.returncode != 0:
        detail = produced.stderr.decode("utf-8", errors="replace").strip()
        raise Refusal("producer-refused", detail)
    cert_bytes = produced.stdout
    fields = parse_certificate(cert_bytes)
    expected_bindings = {
        "operation": "integrate",
        "assurance": "formal-bounded",
        "family": "gaussian-exp-square-v1",
        "expression": args.expression,
        "lower": canonical_lo,
        "upper": canonical_hi,
        "tolerance": canonical_tolerance,
        "method": "gaussian-total-minus-tails-v1",
        "core": "6",
        "degree": "96",
        "sqrt-pi-lower": "177245385090551/100000000000000",
        "sqrt-pi-upper": "22155673136319/12500000000000",
    }
    for key, expected in expected_bindings.items():
        if fields.get(key) != expected:
            raise Refusal("request-binding", f"{key}: {fields.get(key)!r} != {expected!r}")
    output_parts = fields["output"].split(" ")
    if len(output_parts) != 2:
        raise Refusal("certificate-output", fields["output"])
    try:
        output_lo = canonical_rat(output_parts[0])
        output_hi = canonical_rat(output_parts[1])
    except ValueError as exc:
        raise Refusal("certificate-output", str(exc)) from exc
    if Fraction(output_lo) > Fraction(output_hi):
        raise Refusal("certificate-output", "reversed enclosure")
    if Fraction(output_hi) - Fraction(output_lo) > Fraction(canonical_tolerance):
        raise Refusal("certificate-width", "exceeds requested tolerance")

    with tempfile.TemporaryDirectory(prefix="jackal-gaussian-check-") as directory:
        cert_path = Path(directory) / "certificate.gcert"
        cert_path.write_bytes(cert_bytes)
        cert_path.chmod(0o600)
        checked = subprocess.run(
            [str(checker), str(cert_path)], capture_output=True, timeout=args.timeout
        )
    if checked.returncode != 0 or not checked.stdout.startswith(
        b"ACCEPT theorem=gaussian_integral_check_sound family=gaussian-exp-square-v1"
    ):
        detail = checked.stderr.decode("utf-8", errors="replace").strip()
        raise Refusal("checker-rejected", detail)

    if sha256_file(producer) != producer_pre or sha256_file(checker) != checker_pre:
        raise Refusal("artifact-toctou", "producer or checker changed during release")

    try:
        status = derive_status(
            operator="gaussian-exp-square-integral-v1",
            requested="formal-bounded",
            checker_accepted=True,
            certificate_sha256=hashlib.sha256(cert_bytes).hexdigest(),
            theorem_id="gaussian_integral_check_sound",
            request_bound=True,
            inv=load_inventory(),
        )
    except StatusRefusal as exc:
        raise Refusal("formal-status-refused", f"{exc.cls}: {exc.detail}") from exc
    if status != "formal-bounded":
        raise Refusal("formal-status-mismatch", status)

    commitment = gaussian_request_commitment_b64(
        "integrate", args.expression, canonical_lo, canonical_hi, canonical_tolerance
    )
    receipt = build_gaussian_formal_receipt(
        release_epoch=args.release_epoch,
        request={
            "command": "integrate",
            "expression": args.expression,
            "input_lo": canonical_lo,
            "input_hi": canonical_hi,
            "tolerance": canonical_tolerance,
        },
        enclosure=(output_lo, output_hi),
        cert_bytes=cert_bytes,
        producer_sha256=producer_pre,
        checker_sha256=checker_pre,
        canonical_lo=canonical_lo,
        canonical_hi=canonical_hi,
        canonical_tolerance=canonical_tolerance,
        request_commitment_b64=commitment,
        plugin_sha256=args.plugin_sha256,
    )
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = receipt_path.with_name(receipt_path.name + ".tmp")
    temporary.write_bytes(canonical_json_bytes(receipt) + b"\n")
    temporary.chmod(0o600)
    os.replace(temporary, receipt_path)
    return receipt


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--expression", required=True)
    result.add_argument("--lower", required=True)
    result.add_argument("--upper", required=True)
    result.add_argument("--tolerance", required=True)
    result.add_argument("--producer", required=True)
    result.add_argument("--checker", required=True)
    result.add_argument("--expected-producer", required=True)
    result.add_argument("--expected-checker", required=True)
    result.add_argument("--receipt", required=True)
    result.add_argument("--plugin-sha256")
    result.add_argument("--release-epoch", default="v1.3.0")
    result.add_argument("--timeout", type=int, default=60)
    return result


def main() -> int:
    args = parser().parse_args()
    try:
        receipt = release(args)
    except (Refusal, subprocess.TimeoutExpired, OSError) as exc:
        try:
            Path(args.receipt).expanduser().resolve().unlink(missing_ok=True)
        except OSError:
            pass
        if isinstance(exc, Refusal):
            print(f"status=refused class={exc.cls} detail={exc.detail}", file=sys.stderr)
        else:
            print(f"status=refused class=runtime detail={exc}", file=sys.stderr)
        return 101
    result = receipt["result"]
    print(
        "status=formal-bounded "
        f"enclosure=[{result['enclosure_lo']},{result['enclosure_hi']}] "
        "theorem=gaussian_integral_check_sound "
        f"producer_sha256={receipt['identities']['producer_sha256']} "
        f"checker_sha256={receipt['identities']['checker_sha256']} "
        f"receipt={args.receipt}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
