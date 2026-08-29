#!/usr/bin/env python3
"""Fail-closed release gate for the certified composed-integral lane.

`integrate-bound-cert` (v1.7, bound_step composition): runs the identity-pinned
UNTRUSTED producer (tools/int_cert_producer.py), demands ACCEPT from the pinned
proved checker (jackal_int_cert_check, theorem `int_cert_sound`), binds the
exact caller request via the `jackal-req-v3-int-cert` commitment, enforces
TOCTOU identity stability, emits a canonical `jackal-formal-receipt-v1`
(variant `int_cert`), and independently re-verifies the receipt before
reporting success.  No status escalation: `formal-bounded` is derived only
through tools/formal_status_gate.py against the digest-bound coverage
inventory.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import os
import re
import subprocess
import sys
import tempfile
from fractions import Fraction
from pathlib import Path
from typing import Any

if "formal_receipt" not in sys.modules:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
from formal_receipt import (  # noqa: E402
    build_int_cert_formal_receipt,
    canonical_json_bytes,
    canonical_rat,
    int_cert_request_commitment_b64,
    load_proof_identity_binding,
    CURRENT_PROOF_RELEASE_EPOCH,
    require_fresh_output,
    write_new_file_atomic,
)
from formal_status_gate import INVENTORY, StatusRefusal, derive_status, load_inventory  # noqa: E402
import receipt_verify as vr  # noqa: E402

ACCEPT_PREFIX = (
    b"ACCEPT status=bounded theorem=int_cert_sound "
    b"checker=jackal-iv-bound-step-v1 output "
)


class Refusal(Exception):
    def __init__(self, cls: str, detail: str = "") -> None:
        super().__init__(f"{cls}: {detail}")
        self.cls = cls
        self.detail = detail


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
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


def parse_artifact_header(raw: bytes) -> dict[str, str]:
    """Header rows of a jackal-int-cert artifact, up to the first tree line."""
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise Refusal("artifact-not-utf8", str(exc)) from exc
    fields: dict[str, str] = {}
    for line in text.split("\n"):
        if not line:
            continue
        if line.startswith("tree ") or line.startswith("cert ") or line == "end":
            break
        if line == "jackal-int-cert v1":
            if "schema" in fields:
                raise Refusal("artifact-header-duplicate", "schema")
            fields["schema"] = line
            continue
        parts = line.split(" ", 1)
        if len(parts) == 2:
            if parts[0] in fields:
                raise Refusal("artifact-header-duplicate", parts[0])
            fields[parts[0]] = parts[1]
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
    fields = parse_artifact_header(cert_bytes)
    commitment = int_cert_request_commitment_b64(
        "integrate-bound-cert", args.expression, canonical_lo, canonical_hi,
        canonical_tolerance,
    )
    expected_bindings = {
        "schema": "jackal-int-cert v1",
        "model": "jackal-iv-model-v1",
        "checker": "jackal-iv-bound-step-v1",
        "producer": producer_pre,
        "status": "bounded",
        "source": commitment,
        "request": f"{canonical_lo} {canonical_hi} {canonical_tolerance}",
    }
    for key, expected in expected_bindings.items():
        if fields.get(key) != expected:
            raise Refusal("request-binding", f"{key}: {fields.get(key)!r} != {expected!r}")
    output_parts = (fields.get("output") or "").split(" ")
    if len(output_parts) != 2:
        raise Refusal("certificate-output", str(fields.get("output")))
    try:
        output_lo = canonical_rat(output_parts[0])
        output_hi = canonical_rat(output_parts[1])
    except ValueError as exc:
        raise Refusal("certificate-output", str(exc)) from exc
    if output_lo != output_parts[0] or output_hi != output_parts[1]:
        raise Refusal("certificate-output", "noncanonical enclosure")
    if Fraction(output_lo) > Fraction(output_hi):
        raise Refusal("certificate-output", "reversed enclosure")
    if Fraction(output_hi) - Fraction(output_lo) > Fraction(canonical_tolerance):
        raise Refusal("certificate-width", "exceeds requested tolerance")

    with tempfile.TemporaryDirectory(prefix="jackal-int-cert-check-") as directory:
        cert_path = Path(directory) / "artifact.jic"
        cert_path.write_bytes(cert_bytes)
        cert_path.chmod(0o600)
        checked = subprocess.run(
            [
                str(checker),
                str(cert_path),
                args.expression,
                canonical_lo,
                canonical_hi,
                canonical_tolerance,
            ],
            capture_output=True,
            timeout=args.timeout,
        )
    stdout_bytes = checked.stdout or b""
    if checked.returncode != 0 or not stdout_bytes.startswith(ACCEPT_PREFIX) \
            or not stdout_bytes.endswith(b"\n") or checked.stderr:
        detail = checked.stderr.decode("utf-8", errors="replace").strip()
        if not detail:
            detail = stdout_bytes.decode("utf-8", errors="replace").strip()[:200]
        raise Refusal("checker-rejected", detail)
    tail = stdout_bytes[len(ACCEPT_PREFIX):-1]
    try:
        echo_lo_b, echo_hi_b = tail.split(b" ", 1)
        if b" " in echo_hi_b:
            raise ValueError("extra tokens after checker output_hi")
        echo_lo = echo_lo_b.decode("ascii")
        echo_hi = echo_hi_b.decode("ascii")
    except (ValueError, UnicodeDecodeError) as exc:
        raise Refusal("checker-accept-malformed", str(exc)) from exc
    if canonical_rat(echo_lo) != output_lo or canonical_rat(echo_hi) != output_hi:
        raise Refusal(
            "checker-echo-divergence",
            f"checker {echo_lo} {echo_hi} != artifact {output_lo} {output_hi}",
        )

    if sha256_file(producer) != producer_pre or sha256_file(checker) != checker_pre:
        raise Refusal("artifact-toctou", "producer or checker changed during release")

    try:
        inventory = load_inventory()
        status = derive_status(
            operator="jackal_integrate_bound_cert",
            requested="formal-bounded",
            checker_accepted=True,
            certificate_sha256=hashlib.sha256(cert_bytes).hexdigest(),
            theorem_id="int_cert_sound",
            request_bound=True,
            inv=inventory,
        )
    except StatusRefusal as exc:
        raise Refusal("formal-status-refused", f"{exc.cls}: {exc.detail}") from exc
    if status != "formal-bounded":
        raise Refusal("formal-status-mismatch", status)

    here = Path(__file__).resolve().parent
    proof_name = (
        "int_cert_proof_identity_v172.json"
        if args.release_epoch == CURRENT_PROOF_RELEASE_EPOCH
        else "int_cert_proof_identity.json"
    )
    _host_tag = f"{platform.system().lower()}-{platform.machine().lower()}"
    _host_proof_name = proof_name[:-5] + f".{_host_tag}.json"
    proof_candidates = [
        here.parent / "release" / "evidence" / _host_proof_name,
        here.parent / "release" / "evidence" / proof_name,
        here / proof_name,
    ]
    if args.release_epoch == CURRENT_PROOF_RELEASE_EPOCH:
        proof_candidates.append(here / "int_cert_proof_identity.json")
    proof_path = next((candidate for candidate in proof_candidates
                       if candidate.is_file()), None)
    if proof_path is None:
        raise Refusal("proof-identity", "int-cert proof identity missing")
    try:
        proof_identity = load_proof_identity_binding(proof_path)
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise Refusal("proof-identity", str(exc)) from exc
    if proof_identity["checker_sha256"] != checker_pre:
        raise Refusal("proof-checker-identity", "int-cert proof/checker mismatch")
    if proof_identity["soundness_theorem"] != \
            "JackalIv.IntCert.int_cert_sound":
        raise Refusal("proof-theorem-identity", proof_identity["soundness_theorem"])
    receipt = build_int_cert_formal_receipt(
        release_epoch=args.release_epoch,
        request={
            "command": "integrate-bound-cert",
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
    result.add_argument("--release-epoch", default=CURRENT_PROOF_RELEASE_EPOCH)
    result.add_argument("--timeout", type=int, default=300)
    return result


def main() -> int:
    if not (sys.flags.isolated and sys.flags.no_site):
        print(
            "status=refused class=python-not-isolated "
            "detail=invoke-jackal-int-cert-release",
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
                "command": "integrate-bound-cert",
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
        "theorem=int_cert_sound "
        f"producer_sha256={receipt['identities']['producer_sha256']} "
        f"checker_sha256={receipt['identities']['checker_sha256']} "
        "receipt_reverified=true "
        f"receipt={args.receipt}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
