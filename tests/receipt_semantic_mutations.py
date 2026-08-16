#!/usr/bin/env python3
"""Adversarial receipt semantics: every coordinated relabel must refuse.

Unlike one-field digest tampering, these cases recompute the outer receipt
digest and, where relevant, the request commitment and certificate source
header.  The range expression case therefore reaches the Lean
``requestMatches`` gate and demonstrates checker-side request binding.
"""
from __future__ import annotations

import argparse
import base64
import copy
import hashlib
import json
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "release" / "evidence" / "receipt_semantic_mutations.json"
INVENTORY = ROOT / "release" / "coverage" / "formal_coverage_inventory.json"
RANGE_CHECKER = ROOT / "proofs" / "lean" / ".lake" / "build" / "bin" / "jackal_cert_check"
GAUSSIAN_CHECKER = ROOT / "proofs" / "lean" / ".lake" / "build" / "bin" / "jackal_gaussian_check"
EVALUATOR = ROOT / "jackal-native"
PRODUCER = ROOT / "tools" / "gaussian_certificate.py"
SOURCE = ROOT / "jackal_calc.anb"
RANGE_PROOF_IDENTITY = ROOT / "release" / "evidence" / "range_proof_identity.json"
GAUSSIAN_PROOF_IDENTITY = ROOT / "release" / "evidence" / "gaussian_proof_identity.json"

import sys
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "tools"))

import gaussian_release as gr  # noqa: E402
import receipt_verify as vr  # noqa: E402
import release_validate as rv  # noqa: E402
from formal_receipt import (  # noqa: E402
    gaussian_request_commitment_b64,
    recompute_receipt_digest,
    request_commitment_b64,
    sha256_hex,
)

RANGE_REQUEST = {
    "command": "range-bound-cert",
    "expression": "x^2+1",
    "input_lo": "1",
    "input_hi": "2",
}
GAUSSIAN_REQUEST = {
    "command": "integrate",
    "expression": "exp(-10000000000*(x-0.5000123456789)^2)",
    "input_lo": "0",
    "input_hi": "1",
    "tolerance": "1/1000000000000",
}


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def identity_digest(path: Path) -> str:
    return json.loads(path.read_text())["identity_digest_sha256"]


def fresh_range() -> dict:
    with tempfile.TemporaryDirectory(prefix="jackal-receipt-mutation-range-") as td:
        path = Path(td) / "receipt.json"
        rv.validate_release(
            expr=RANGE_REQUEST["expression"], lo=RANGE_REQUEST["input_lo"],
            hi=RANGE_REQUEST["input_hi"], evaluator=str(EVALUATOR),
            checker=str(RANGE_CHECKER), expected_evaluator=file_sha(EVALUATOR),
            expected_checker=file_sha(RANGE_CHECKER), formal_receipt_path=str(path),
            release_epoch="v1.3.0",
        )
        return json.loads(path.read_text())


def fresh_gaussian() -> dict:
    with tempfile.TemporaryDirectory(prefix="jackal-receipt-mutation-gaussian-") as td:
        path = Path(td) / "receipt.json"
        args = argparse.Namespace(
            expression=GAUSSIAN_REQUEST["expression"],
            lower=GAUSSIAN_REQUEST["input_lo"],
            upper=GAUSSIAN_REQUEST["input_hi"],
            tolerance=GAUSSIAN_REQUEST["tolerance"],
            producer=str(PRODUCER), checker=str(GAUSSIAN_CHECKER),
            expected_producer=file_sha(PRODUCER),
            expected_checker=file_sha(GAUSSIAN_CHECKER), receipt=str(path),
            plugin_sha256=None, release_epoch="v1.3.0", timeout=60,
        )
        gr.release(args)
        return json.loads(path.read_text())


def verify_range(receipt: dict, request: dict[str, str] | None = None,
                 epoch: str = "v1.3.0", *,
                 inventory_sha: str | None = None,
                 proof_file_sha: str | None = None,
                 proof_digest: str | None = None,
                 evaluator_sha: str | None = None) -> dict:
    return vr.verify_receipt(
        receipt=receipt, checker=str(RANGE_CHECKER),
        expected_evaluator=evaluator_sha or file_sha(EVALUATOR),
        expected_checker=file_sha(RANGE_CHECKER),
        expected_source=file_sha(SOURCE), inventory_path=INVENTORY,
        expected_inventory_sha256=inventory_sha or file_sha(INVENTORY),
        proof_identity_path=RANGE_PROOF_IDENTITY,
        expected_proof_identity_file=proof_file_sha or file_sha(RANGE_PROOF_IDENTITY),
        expected_proof_identity_digest=proof_digest or identity_digest(RANGE_PROOF_IDENTITY),
        expected_release_epoch=epoch, expected_request=request or RANGE_REQUEST,
    )


def verify_gaussian(receipt: dict, request: dict[str, str] | None = None,
                    epoch: str = "v1.3.0", *,
                    inventory_sha: str | None = None,
                    proof_file_sha: str | None = None,
                    proof_digest: str | None = None) -> dict:
    return vr.verify_receipt(
        receipt=receipt, checker=str(GAUSSIAN_CHECKER),
        expected_evaluator=file_sha(PRODUCER),
        expected_checker=file_sha(GAUSSIAN_CHECKER),
        inventory_path=INVENTORY, proof_identity_path=GAUSSIAN_PROOF_IDENTITY,
        expected_inventory_sha256=inventory_sha or file_sha(INVENTORY),
        expected_proof_identity_file=proof_file_sha or file_sha(GAUSSIAN_PROOF_IDENTITY),
        expected_proof_identity_digest=proof_digest or identity_digest(GAUSSIAN_PROOF_IDENTITY),
        expected_release_epoch=epoch,
        expected_request=request or GAUSSIAN_REQUEST,
    )


SQRT_RAT_REQUEST = {
    "command": "range-bound-cert",
    "expression": "sqrt(x)",
    "input_lo": "2",
    "input_hi": "3",
}
EXP_RAT_REQUEST = {
    "command": "range-bound-cert",
    "expression": "exp(x)",
    "input_lo": "0",
    "input_hi": "1",
}
SQRT_RAT_PRODUCER = ROOT / "tools" / "sqrt_rat_producer.py"
EXP_RAT_PRODUCER = ROOT / "tools" / "exp_rat_producer.py"
LN_RAT_REQUEST = {
    "command": "range-bound-cert",
    "expression": "ln(x)",
    "input_lo": "2",
    "input_hi": "3",
}
SIN_RAT_REQUEST = {
    "command": "range-bound-cert",
    "expression": "sin(x)",
    "input_lo": "-1/2",
    "input_hi": "1/2",
}
COS_RAT_REQUEST = {
    "command": "range-bound-cert",
    "expression": "cos(x)",
    "input_lo": "0",
    "input_hi": "1/2",
}
ATAN_RAT_REQUEST = {
    "command": "range-bound-cert",
    "expression": "atan(x)",
    "input_lo": "1",
    "input_hi": "2",
}
TANH_RAT_REQUEST = {
    "command": "range-bound-cert",
    "expression": "1-2/(exp(2*x)+1)",
    "input_lo": "0",
    "input_hi": "1",
}
LN_RAT_PRODUCER = ROOT / "tools" / "ln_rat_producer.py"
SIN_RAT_PRODUCER = ROOT / "tools" / "sin_rat_producer.py"
ATAN_RAT_PRODUCER = ROOT / "tools" / "atan_rat_producer.py"
TANH_RAT_PRODUCER = ROOT / "tools" / "tanh_rat_producer.py"


def _fresh_variant(*, variant: str, request: dict[str, str], producer: Path,
                   epoch: str = "v1.4.2",
                   extra_args: list[str] | None = None) -> dict:
    import subprocess
    from formal_receipt import (
        build_variant_formal_receipt, canonical_rat,
        request_commitment_b64 as _rcb,
        _parse_cert_header, load_proof_identity_binding,
    )
    with tempfile.TemporaryDirectory(prefix=f"jackal-receipt-mutation-{variant}-") as td:
        cert_path = Path(td) / f"{variant}.cert"
        proc = subprocess.run(
            [sys.executable, "-I", "-S", "-B", str(producer), "emit",
             *(extra_args or []),
             "--expression", request["expression"],
             "--lower", request["input_lo"], "--upper", request["input_hi"]],
            capture_output=True, check=True, timeout=120,
        )
        cert_path.write_bytes(proc.stdout)
        cert_bytes = cert_path.read_bytes()
    hdr = _parse_cert_header(cert_bytes)
    encl_lo, encl_hi = hdr.get("output", "").split(" ", 1)
    inv_bytes = INVENTORY.read_bytes()
    return build_variant_formal_receipt(
        variant=variant,
        release_epoch=epoch,
        request=request,
        enclosure=(encl_lo, encl_hi),
        cert_bytes=cert_bytes,
        producer_sha256=file_sha(producer),
        checker_sha256=file_sha(RANGE_CHECKER),
        canonical_lo=canonical_rat(request["input_lo"]),
        canonical_hi=canonical_rat(request["input_hi"]),
        request_commitment_b64=_rcb(request["command"], request["expression"],
                                     request["input_lo"], request["input_hi"]),
        coverage_inventory_sha256=hashlib.sha256(inv_bytes).hexdigest(),
        proof_identity=load_proof_identity_binding(RANGE_PROOF_IDENTITY),
        plugin_sha256=None,
    )


def fresh_sqrt_rat() -> dict:
    return _fresh_variant(variant="sqrt_rat", request=SQRT_RAT_REQUEST,
                           producer=SQRT_RAT_PRODUCER)


def fresh_exp_rat() -> dict:
    return _fresh_variant(variant="exp_rat", request=EXP_RAT_REQUEST,
                           producer=EXP_RAT_PRODUCER)


def fresh_ln_rat() -> dict:
    return _fresh_variant(variant="ln_rat", request=LN_RAT_REQUEST,
                          producer=LN_RAT_PRODUCER, epoch="v1.5.0")


def fresh_sin_rat() -> dict:
    return _fresh_variant(variant="sin_rat", request=SIN_RAT_REQUEST,
                          producer=SIN_RAT_PRODUCER, epoch="v1.5.0",
                          extra_args=["--op", "sin"])


def fresh_cos_rat() -> dict:
    return _fresh_variant(variant="cos_rat", request=COS_RAT_REQUEST,
                          producer=SIN_RAT_PRODUCER, epoch="v1.5.0",
                          extra_args=["--op", "cos"])


def fresh_atan_rat() -> dict:
    return _fresh_variant(variant="atan_rat", request=ATAN_RAT_REQUEST,
                          producer=ATAN_RAT_PRODUCER, epoch="v1.5.0")


def fresh_tanh_rat() -> dict:
    return _fresh_variant(variant="tanh_rat", request=TANH_RAT_REQUEST,
                          producer=TANH_RAT_PRODUCER, epoch="v1.5.0")


def verify_variant(receipt: dict, *, variant: str, request: dict,
                   producer: Path, epoch: str = "v1.4.2",
                   inventory_sha: str | None = None,
                   proof_file_sha: str | None = None,
                   proof_digest: str | None = None,
                   producer_sha: str | None = None) -> dict:
    return vr.verify_receipt(
        receipt=receipt, checker=str(RANGE_CHECKER),
        expected_evaluator=producer_sha or file_sha(producer),
        expected_checker=file_sha(RANGE_CHECKER),
        expected_source=None, inventory_path=INVENTORY,
        expected_inventory_sha256=inventory_sha or file_sha(INVENTORY),
        proof_identity_path=RANGE_PROOF_IDENTITY,
        expected_proof_identity_file=proof_file_sha or file_sha(RANGE_PROOF_IDENTITY),
        expected_proof_identity_digest=proof_digest or identity_digest(RANGE_PROOF_IDENTITY),
        expected_release_epoch=epoch, expected_request=request,
    )


def redigest(receipt: dict) -> dict:
    receipt["receipt_digest_sha256"] = recompute_receipt_digest(receipt)
    return receipt


def rebind_range_source(receipt: dict, request: dict[str, str]) -> dict:
    commitment = request_commitment_b64(
        request["command"], request["expression"],
        request["input_lo"], request["input_hi"],
    )
    old = receipt["request"]["request_commitment_b64"]
    raw = base64.b64decode(receipt["certificate"]["bytes_b64"], validate=True)
    before = f"source {old}\n".encode()
    after = f"source {commitment}\n".encode()
    if raw.count(before) != 1:
        raise RuntimeError("certificate source header was not uniquely replaceable")
    raw = raw.replace(before, after)
    receipt["certificate"]["bytes_b64"] = base64.b64encode(raw).decode()
    receipt["certificate"]["sha256"] = sha256_hex(raw)
    receipt["request"]["request_commitment_b64"] = commitment
    return receipt


def replace_range_node_op(receipt: dict, old: bytes, new: bytes) -> dict:
    result = copy.deepcopy(receipt)
    raw = base64.b64decode(result["certificate"]["bytes_b64"], validate=True)
    before = b" " + old + b" "
    after = b" " + new + b" "
    if raw.count(before) != 1:
        raise RuntimeError(f"certificate node op {old!r} was not uniquely replaceable")
    raw = raw.replace(before, after)
    result["certificate"]["bytes_b64"] = base64.b64encode(raw).decode()
    result["certificate"]["sha256"] = sha256_hex(raw)
    return redigest(result)


def main() -> int:
    range_receipt = fresh_range()
    gaussian_receipt = fresh_gaussian()
    if verify_range(range_receipt).get("verdict") != "ACCEPT":
        raise RuntimeError("baseline range receipt did not verify")
    if verify_gaussian(gaussian_receipt).get("verdict") != "ACCEPT":
        raise RuntimeError("baseline Gaussian receipt did not verify")
    sqrt_receipt = fresh_sqrt_rat()
    exp_receipt = fresh_exp_rat()
    if verify_variant(sqrt_receipt, variant="sqrt_rat", request=SQRT_RAT_REQUEST,
                      producer=SQRT_RAT_PRODUCER).get("verdict") != "ACCEPT":
        raise RuntimeError("baseline sqrt_rat receipt did not verify")
    if verify_variant(exp_receipt, variant="exp_rat", request=EXP_RAT_REQUEST,
                      producer=EXP_RAT_PRODUCER).get("verdict") != "ACCEPT":
        raise RuntimeError("baseline exp_rat receipt did not verify")
    ln_receipt = fresh_ln_rat()
    sin_receipt = fresh_sin_rat()
    cos_receipt = fresh_cos_rat()
    atan_receipt = fresh_atan_rat()
    tanh_receipt = fresh_tanh_rat()
    for _name, _rcpt, _req, _prod in [
        ("ln_rat", ln_receipt, LN_RAT_REQUEST, LN_RAT_PRODUCER),
        ("sin_rat", sin_receipt, SIN_RAT_REQUEST, SIN_RAT_PRODUCER),
        ("cos_rat", cos_receipt, COS_RAT_REQUEST, SIN_RAT_PRODUCER),
        ("atan_rat", atan_receipt, ATAN_RAT_REQUEST, ATAN_RAT_PRODUCER),
        ("tanh_rat", tanh_receipt, TANH_RAT_REQUEST, TANH_RAT_PRODUCER),
    ]:
        if verify_variant(_rcpt, variant=_name, request=_req, producer=_prod,
                          epoch="v1.5.0").get("verdict") != "ACCEPT":
            raise RuntimeError(f"baseline {_name} receipt did not verify")

    cases: list[tuple[str, callable, str]] = []

    def add(name: str, run, expected: str) -> None:
        cases.append((name, run, expected))

    def mutate(base: dict, path: tuple[str, ...], value) -> dict:
        result = copy.deepcopy(base)
        target = result
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = value
        return redigest(result)

    add("forged-release-epoch",
        lambda: verify_gaussian(mutate(gaussian_receipt, ("release_epoch",), "forged")),
        "release-epoch")
    add("assumptions-removed",
        lambda: verify_gaussian(mutate(gaussian_receipt, ("assumptions",), [])),
        "receipt-assumptions")
    add("non-claims-replaced",
        lambda: verify_gaussian(mutate(
            gaussian_receipt, ("non_claims",), ["UNRESTRICTED UNIVERSAL CORRECTNESS"])),
        "receipt-non-claims")
    add("checker-policy-forged",
        lambda: verify_gaussian(mutate(
            gaussian_receipt, ("checker",),
            {"verdict": "REJECT", "reverify_required": False})),
        "receipt-checker-policy")
    add("cert-status-forged",
        lambda: verify_gaussian(mutate(
            gaussian_receipt, ("result", "cert_status"), "estimated")),
        "result-cert-status")
    add("duplicated-producer-identity-forged",
        lambda: verify_gaussian(mutate(
            gaussian_receipt, ("identities", "producer_sha256"), "0" * 64)),
        "producer-identity")
    add("coverage-identity-forged",
        lambda: verify_gaussian(mutate(
            gaussian_receipt, ("fragment", "coverage_inventory_sha256"), "0" * 64)),
        "coverage-inventory-identity")
    add("proof-identity-forged",
        lambda: verify_gaussian(mutate(
            gaussian_receipt, ("proof_identity", "identity_digest_sha256"),
            "0" * 64)),
        "proof-identity-mismatch")
    add("wrong-external-inventory-pin",
        lambda: verify_gaussian(gaussian_receipt, inventory_sha="0" * 64),
        "coverage-inventory-expected")
    add("wrong-external-proof-file-pin",
        lambda: verify_gaussian(gaussian_receipt, proof_file_sha="0" * 64),
        "proof-identity-file")
    add("wrong-external-proof-digest-pin",
        lambda: verify_gaussian(gaussian_receipt, proof_digest="0" * 64),
        "proof-identity-digest")
    add("range-source-identity-forged",
        lambda: verify_range(mutate(
            range_receipt, ("identities", "source_anb_sha256"), "0" * 64)),
        "source-identity")
    evaluator_relabel = copy.deepcopy(range_receipt)
    evaluator_relabel["identities"]["evaluator_sha256"] = "a" * 64
    redigest(evaluator_relabel)
    add("coordinated-range-evaluator-relabel",
        lambda: verify_range(evaluator_relabel, evaluator_sha="a" * 64),
        "evaluator-vs-certificate")
    negative_power_node = replace_range_node_op(
        range_receipt, b"powEvenPos", b"powNegEven"
    )
    add("range-policy-negative-power-node",
        lambda: verify_range(negative_power_node),
        "node-op-outside-release-fragment")
    add("stale-expected-epoch",
        lambda: verify_gaussian(gaussian_receipt, epoch="v1.2.0"),
        "release-epoch")
    add("boolean-timestamp",
        lambda: verify_gaussian(mutate(
            gaussian_receipt, ("emitted_at_unix",), True)),
        "receipt-emitted-at")
    gaussian_lo = gaussian_receipt["result"]["enclosure_lo"]
    if "/" in gaussian_lo:
        gaussian_lo_num, gaussian_lo_den = gaussian_lo.split("/", 1)
        gaussian_lo_noncanonical = f"{int(gaussian_lo_num) * 2}/{int(gaussian_lo_den) * 2}"
    else:
        gaussian_lo_noncanonical = f"{int(gaussian_lo)}/1"
    add("noncanonical-result-token",
        lambda: verify_gaussian(mutate(
            gaussian_receipt, ("result", "enclosure_lo"),
            gaussian_lo_noncanonical)),
        "result-enclosure-canonical")
    add("extra-top-level-field",
        lambda: verify_gaussian(mutate(
            gaussian_receipt, ("unexpected",), "forged")),
        "receipt-fields")
    stale_request = dict(GAUSSIAN_REQUEST)
    stale_request["expression"] = "exp(-4*x^2)"
    add("whole-receipt-substitution",
        lambda: verify_gaussian(gaussian_receipt, request=stale_request),
        "expected-request-mismatch")

    expression_request = dict(RANGE_REQUEST)
    expression_request["expression"] = "0"
    expression_relabel = copy.deepcopy(range_receipt)
    expression_relabel["request"]["expression"] = "0"
    rebind_range_source(expression_relabel, expression_request)
    redigest(expression_relabel)
    add("coordinated-range-expression-relabel",
        lambda: verify_range(expression_relabel, request=expression_request),
        "checker-rejected-on-rerun")

    limit_request = dict(RANGE_REQUEST)
    limit_request["input_lo"] = "100"
    limit_request["input_hi"] = "200"
    limit_relabel = copy.deepcopy(range_receipt)
    limit_relabel["request"].update({
        "input_lo": "100", "input_hi": "200",
        "canonical_lo": "100", "canonical_hi": "200",
    })
    rebind_range_source(limit_relabel, limit_request)
    redigest(limit_relabel)
    add("coordinated-range-limit-relabel",
        lambda: verify_range(limit_relabel, request=limit_request),
        "request-vs-range-cert")

    operation_request = dict(RANGE_REQUEST)
    operation_request["command"] = "integrate"
    operation_relabel = copy.deepcopy(range_receipt)
    operation_relabel["request"]["command"] = "integrate"
    rebind_range_source(operation_relabel, operation_request)
    redigest(operation_relabel)
    add("coordinated-operation-relabel",
        lambda: verify_range(operation_relabel, request=operation_request),
        "request-command")

    # ---- v1.4.2 variant round-trip mutation locks --------------------------
    # Every sqrt_rat / exp_rat variant receipt must refuse under the same
    # tamper classes as range / gaussian, plus variant-specific gates.
    add("sqrt-rat-wrong-variant-tag",
        lambda: verify_variant(mutate(sqrt_receipt, ("variant",), "range"),
                                variant="sqrt_rat", request=SQRT_RAT_REQUEST,
                                producer=SQRT_RAT_PRODUCER),
        "receipt-assumptions")
    add("exp-rat-wrong-variant-tag",
        lambda: verify_variant(mutate(exp_receipt, ("variant",), "gaussian"),
                                variant="exp_rat", request=EXP_RAT_REQUEST,
                                producer=EXP_RAT_PRODUCER),
        "variant-cert-schema")
    add("sqrt-rat-producer-identity-forged",
        lambda: verify_variant(mutate(sqrt_receipt, ("identities", "producer_sha256"), "0" * 64),
                                variant="sqrt_rat", request=SQRT_RAT_REQUEST,
                                producer=SQRT_RAT_PRODUCER),
        "producer-identity")
    add("exp-rat-producer-identity-forged",
        lambda: verify_variant(mutate(exp_receipt, ("identities", "producer_sha256"), "0" * 64),
                                variant="exp_rat", request=EXP_RAT_REQUEST,
                                producer=EXP_RAT_PRODUCER),
        "producer-identity")
    add("sqrt-rat-source-anb-forged-nonnull",
        lambda: verify_variant(mutate(sqrt_receipt, ("identities", "source_anb_sha256"), "0" * 64),
                                variant="sqrt_rat", request=SQRT_RAT_REQUEST,
                                producer=SQRT_RAT_PRODUCER),
        "variant-source-identity")
    add("exp-rat-fragment-admitted-forged",
        lambda: verify_variant(mutate(exp_receipt, ("fragment", "admitted_operators"),
                                       ["exp", "sqrt", "var"]),
                                variant="exp_rat", request=EXP_RAT_REQUEST,
                                producer=EXP_RAT_PRODUCER),
        "fragment-admitted")
    add("sqrt-rat-coverage-row-forged",
        lambda: verify_variant(mutate(sqrt_receipt, ("fragment", "coverage_row_ids"),
                                       ["jackal_range_bound"]),
                                variant="sqrt_rat", request=SQRT_RAT_REQUEST,
                                producer=SQRT_RAT_PRODUCER),
        "coverage-row-set")
    add("sqrt-rat-request-command-relabel",
        lambda: verify_variant(mutate(sqrt_receipt, ("request", "command"), "integrate"),
                                variant="sqrt_rat", request={**SQRT_RAT_REQUEST, "command": "integrate"},
                                producer=SQRT_RAT_PRODUCER),
        "request-command"),
    add("exp-rat-non-claims-forged",
        lambda: verify_variant(mutate(exp_receipt, ("non_claims",), ["UNIVERSAL exp"]),
                                variant="exp_rat", request=EXP_RAT_REQUEST,
                                producer=EXP_RAT_PRODUCER),
        "receipt-non-claims")

    # ---- §487 audit regression locks (2026-08-15) --------------------------
    # AUDIT-CRITICAL lock: U+2028 (LINE SEPARATOR) injected into the
    # unconstrained `exe` header line.  Python's str.splitlines() breaks on
    # U+2028 where Lean's `splitOn '\n'` does NOT — the original exploit made
    # the Python re-parse report an interval the checker never attested.  The
    # hardened parser refuses ANY Lean/Python line-boundary divergence byte.
    u2028_receipt = copy.deepcopy(range_receipt)
    u2028_raw = base64.b64decode(u2028_receipt["certificate"]["bytes_b64"], validate=True)
    exe_line = f"exe {range_receipt['identities']['evaluator_sha256']}\n".encode()
    if u2028_raw.count(exe_line) != 1:
        raise RuntimeError("exe header line was not uniquely replaceable for U+2028 lock")
    u2028_raw = u2028_raw.replace(
        exe_line,
        f"exe {range_receipt['identities']['evaluator_sha256']}\u2028injected\n".encode(),
    )
    u2028_receipt["certificate"]["bytes_b64"] = base64.b64encode(u2028_raw).decode()
    u2028_receipt["certificate"]["sha256"] = sha256_hex(u2028_raw)
    redigest(u2028_receipt)
    add("audit-lock-u2028-line-boundary-injection",
        lambda: verify_range(u2028_receipt),
        "cert-illegal-line-boundary")

    # AUDIT-HIGH lock: a `const_rounded` node (value bound only by the
    # undischarged ConstTCB premise — the pi/value=0 exploit shape) must be
    # refused from the release fragment at the node-op mirror, exactly as the
    # Lean `releaseNodeOp` and `requestRejects_const_rounded_node` refuse it.
    const_node = replace_range_node_op(
        range_receipt, b"powEvenPos", b"const_rounded"
    )
    add("audit-lock-const-rounded-node-refused",
        lambda: verify_range(const_node),
        "node-op-outside-release-fragment")

    # ---- v1.5.0 §490 variant round-trip mutation locks ---------------------
    add("ln-rat-wrong-variant-tag",
        lambda: verify_variant(mutate(ln_receipt, ("variant",), "exp_rat"),
                               variant="ln_rat", request=LN_RAT_REQUEST,
                               producer=LN_RAT_PRODUCER, epoch="v1.5.0"),
        "receipt-assumptions")
    add("cos-rat-variant-swap-to-sin",
        lambda: verify_variant(mutate(cos_receipt, ("variant",), "sin_rat"),
                               variant="cos_rat", request=COS_RAT_REQUEST,
                               producer=SIN_RAT_PRODUCER, epoch="v1.5.0"),
        "receipt-assumptions")
    add("ln-rat-source-anb-forged-nonnull",
        lambda: verify_variant(mutate(ln_receipt, ("identities", "source_anb_sha256"), "0" * 64),
                               variant="ln_rat", request=LN_RAT_REQUEST,
                               producer=LN_RAT_PRODUCER, epoch="v1.5.0"),
        "variant-source-identity")
    add("tanh-rat-producer-identity-forged",
        lambda: verify_variant(mutate(tanh_receipt, ("identities", "producer_sha256"), "0" * 64),
                               variant="tanh_rat", request=TANH_RAT_REQUEST,
                               producer=TANH_RAT_PRODUCER, epoch="v1.5.0"),
        "producer-identity")
    add("tanh-rat-admitted-forged",
        lambda: verify_variant(mutate(tanh_receipt, ("fragment", "admitted_operators"),
                                      ["exp", "var"]),
                               variant="tanh_rat", request=TANH_RAT_REQUEST,
                               producer=TANH_RAT_PRODUCER, epoch="v1.5.0"),
        "fragment-admitted")
    add("atan-rat-coverage-row-forged",
        lambda: verify_variant(mutate(atan_receipt, ("fragment", "coverage_row_ids"),
                                      ["jackal_range_bound"]),
                               variant="atan_rat", request=ATAN_RAT_REQUEST,
                               producer=ATAN_RAT_PRODUCER, epoch="v1.5.0"),
        "coverage-row-set")
    add("sin-rat-non-claims-forged",
        lambda: verify_variant(mutate(sin_receipt, ("non_claims",),
                                      ["UNIVERSAL sin correctness"]),
                               variant="sin_rat", request=SIN_RAT_REQUEST,
                               producer=SIN_RAT_PRODUCER, epoch="v1.5.0"),
        "receipt-non-claims")
    # TCB-op smuggling lock: relabel the pure-ℚ `ln_rat` node to the
    # libm-TCB `ln` op.  The release-fragment node mirror must refuse —
    # exactly as the Lean `releaseNodeOp` wildcard refuses `ln`.
    ln_tcb_node = replace_range_node_op(ln_receipt, b"ln_rat", b"ln")
    add("ln-rat-tcb-op-smuggle",
        lambda: verify_variant(ln_tcb_node,
                               variant="ln_rat", request=LN_RAT_REQUEST,
                               producer=LN_RAT_PRODUCER, epoch="v1.5.0"),
        "node-op-outside-release-fragment")
    # Stale-epoch lock for the new cycle.
    add("ln-rat-stale-expected-epoch",
        lambda: verify_variant(ln_receipt, variant="ln_rat",
                               request=LN_RAT_REQUEST,
                               producer=LN_RAT_PRODUCER, epoch="v1.4.2"),
        "release-epoch")

    rows = []
    failures = 0
    for name, run, expected in cases:
        try:
            run()
        except vr.ReceiptRefusal as refusal:
            ok = refusal.cls == expected
            observed = refusal.cls
        else:
            ok = False
            observed = "ACCEPT"
        failures += not ok
        rows.append({"id": name, "expected": expected, "observed": observed, "ok": ok})
        print(f"{'PASS' if ok else 'FAIL'} {name}: {observed}")

    document = {
        "schema": "jackal-receipt-semantic-mutations-v1",
        "baseline_range": "ACCEPT",
        "baseline_gaussian": "ACCEPT",
        "mutations": rows,
    }
    EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")
    print(f"evidence={EVIDENCE} sha256={file_sha(EVIDENCE)}")
    print(f"VERDICT: {'PASS' if failures == 0 else 'FAIL'} — "
          f"{len(rows) - failures}/{len(rows)} coordinated mutations refused")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
