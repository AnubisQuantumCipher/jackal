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
    load_proof_identity_binding,
    require_fresh_output,
    write_new_file_atomic,
)
from formal_status_gate import INVENTORY, StatusRefusal, derive_status, load_inventory
import receipt_verify as vr


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
    try:
        receipt_path = require_fresh_output(args.receipt)
    except FileExistsError as exc:
        raise Refusal("receipt-output-exists", str(exc)) from exc
    except OSError as exc:
        raise Refusal("receipt-output-path", str(exc)) from exc

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
    expected_accept = (
        b"ACCEPT theorem=gaussian_integral_check_sound "
        b"family=gaussian-exp-square-v1\n"
    )
    if checked.returncode != 0 or checked.stdout != expected_accept or checked.stderr:
        detail = checked.stderr.decode("utf-8", errors="replace").strip()
        if not detail:
            detail = checked.stdout.decode("utf-8", errors="replace").strip()
        raise Refusal("checker-rejected", detail)

    if sha256_file(producer) != producer_pre or sha256_file(checker) != checker_pre:
        raise Refusal("artifact-toctou", "producer or checker changed during release")

    try:
        inventory = load_inventory()
        status = derive_status(
            operator="gaussian-exp-square-integral-v1",
            requested="formal-bounded",
            checker_accepted=True,
            certificate_sha256=hashlib.sha256(cert_bytes).hexdigest(),
            theorem_id="gaussian_integral_check_sound",
            request_bound=True,
            inv=inventory,
        )
    except StatusRefusal as exc:
        raise Refusal("formal-status-refused", f"{exc.cls}: {exc.detail}") from exc
    if status != "formal-bounded":
        raise Refusal("formal-status-mismatch", status)

    commitment = gaussian_request_commitment_b64(
        "integrate", args.expression, canonical_lo, canonical_hi, canonical_tolerance
    )
    here = Path(__file__).resolve().parent
    proof_candidates = [
        here.parent / "release" / "evidence" / "gaussian_proof_identity.json",
        here / "gaussian_proof_identity.json",
    ]
    proof_path = next((candidate for candidate in proof_candidates
                       if candidate.is_file()), None)
    if proof_path is None:
        raise Refusal("proof-identity", "Gaussian proof identity missing")
    try:
        proof_identity = load_proof_identity_binding(proof_path)
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise Refusal("proof-identity", str(exc)) from exc
    if proof_identity["checker_sha256"] != checker_pre:
        raise Refusal("proof-checker-identity", "Gaussian proof/checker mismatch")
    if proof_identity["soundness_theorem"] != \
            "JackalIv.GaussianCert.gaussian_integral_check_sound":
        raise Refusal("proof-theorem-identity", proof_identity["soundness_theorem"])
    receipt = build_gaussian_formal_receipt(
        release_epoch=args.release_epoch,
        request={
            "command": "integrate",
            "expression": args.expression,
            "input_lo": args.lower,
            "input_hi": args.upper,
            "tolerance": args.tolerance,
        },
        enclosure=(output_lo, output_hi),
        cert_bytes=cert_bytes,
        producer_sha256=producer_pre,
        checker_sha256=checker_pre,
        canonical_lo=canonical_lo,
        canonical_hi=canonical_hi,
        canonical_tolerance=canonical_tolerance,
        request_commitment_b64=commitment,
        coverage_inventory_sha256=sha256_file(INVENTORY),
        proof_identity=proof_identity,
        plugin_sha256=args.plugin_sha256,
    )
    try:
        write_new_file_atomic(receipt_path, canonical_json_bytes(receipt) + b"\n")
    except FileExistsError as exc:
        raise Refusal("receipt-output-exists", str(exc)) from exc
    except OSError as exc:
        raise Refusal("receipt-output-create", str(exc)) from exc
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
    result.add_argument("--inventory", required=True)
    result.add_argument("--expected-inventory", required=True)
    result.add_argument("--proof-identity", required=True)
    result.add_argument("--expected-proof-identity-file", required=True)
    result.add_argument("--expected-proof-identity-digest", required=True)
    result.add_argument("--plugin-sha256")
    result.add_argument("--release-epoch", default="v1.3.0")
    result.add_argument("--timeout", type=int, default=60)
    return result


def main() -> int:
    if not (sys.flags.isolated and sys.flags.no_site):
        print(
            "status=refused class=python-not-isolated "
            "detail=invoke-jackal-gaussian-release",
            file=sys.stderr,
        )
        return 126
    args = parser().parse_args()
    created_receipt: tuple[Path, os.stat_result] | None = None
    try:
        receipt = release(args)
        created_path = Path(os.path.abspath(os.path.expanduser(args.receipt)))
        created_receipt = (created_path, os.lstat(created_path))
        rerun = vr.verify_receipt(
            receipt=receipt,
            checker=args.checker,
            expected_evaluator=args.expected_producer,
            expected_checker=args.expected_checker,
            inventory_path=Path(args.inventory),
            expected_inventory_sha256=args.expected_inventory,
            proof_identity_path=Path(args.proof_identity),
            expected_proof_identity_file=args.expected_proof_identity_file,
            expected_proof_identity_digest=args.expected_proof_identity_digest,
            expected_plugin=args.plugin_sha256,
            expected_release_epoch=args.release_epoch,
            expected_request={
                "command": "integrate",
                "expression": args.expression,
                "input_lo": args.lower,
                "input_hi": args.upper,
                "tolerance": args.tolerance,
            },
        )
        if rerun.get("verdict") != "ACCEPT":
            raise Refusal("receipt-reverify", str(rerun.get("verdict")))
    except (Refusal, vr.ReceiptRefusal, subprocess.TimeoutExpired, OSError) as exc:
        if created_receipt is not None:
            created_path, identity = created_receipt
            try:
                observed = os.lstat(created_path)
                if (observed.st_dev, observed.st_ino) == \
                        (identity.st_dev, identity.st_ino):
                    os.unlink(created_path)
            except FileNotFoundError:
                pass
        if isinstance(exc, Refusal):
            print(f"status=refused class={exc.cls} detail={exc.detail}", file=sys.stderr)
        elif isinstance(exc, vr.ReceiptRefusal):
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
        "receipt_reverified=true "
        f"receipt={args.receipt}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
