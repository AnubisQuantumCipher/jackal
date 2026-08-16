#!/usr/bin/env python3
"""Producer-side claim kernel for `jackal-claim-bundle-v1` (v1.6.0).

Builds canonical claim nodes and bundles: input declarations, evidence
admissions (formal receipts, exact certs, machine-int certs), derived
rule nodes with the small compositional assurance algebra (pointwise
meet + rule caps; artifact AND; residual union), the deterministic
renderer, and machine-int certificate production.

This module is the CONVENIENCE half of the certifying architecture.  The
independent verifier (`tools/claim_bundle_verify.py`) shares NO code with
it and recomputes everything; a kernel bug can produce refusable bundles
but can never make a false bundle verify.

Contract: release/claim/SPEC.md.
"""
from __future__ import annotations

import base64
import hashlib
import json
from fractions import Fraction
from pathlib import Path

SCHEMA_NODE = "jackal-claim-node-v1"
SCHEMA_BUNDLE = "jackal-claim-bundle-v1"
SCHEMA_POLICY = "jackal-claim-policy-v1"
SCHEMA_MACHINE = "jackal-machine-int-cert-v1"
RELEASE_EPOCH = "v1.6.0"

RESIDUALS = [
    "no-source-native-refinement",
    "no-replay-prevention-without-external-nonce-store",
    "no-probability-distributions-from-intervals",
    "no-real-world-input-truth",
    "no-universal-soundness-bounded-fragments-only",
    "transparency-metadata-is-not-mathematical-evidence",
]

PROV_ORDER = ["unknown", "supplied", "integrity-bound", "observed",
              "authenticated-source", "measured"]
MODEL_ORDER = ["unknown", "assumed", "calibrated", "empirically-validated"]
MODEL_IDENTITY = "not-applicable"
MATH_ORDER = ["refused", "indeterminate", "estimated", "model-based",
              "checked", "bounded", "formal-bounded", "exact"]
MATH_RANKS = {"refused": 0, "indeterminate": 1, "estimated": 2,
              "model-based": 2, "checked": 3, "bounded": 4,
              "formal-bounded": 5, "exact": 6}
IMPL_ORDER = ["unknown", "directly-trusted", "campaign-tested",
              "independently-recomputed", "checker-derived",
              "source-native-refined"]
ARTIFACT_FLAGS = ["content_addressed", "reproducible_built",
                  "authenticated", "transparency_logged"]
ARTIFACT_FALSE = {flag: False for flag in ARTIFACT_FLAGS}
ARTIFACT_CA = {**ARTIFACT_FALSE, "content_addressed": True}

MATH_CAPS = {"interval_add": "bounded", "interval_sub": "bounded",
             "interval_mul": "bounded", "interval_div": "bounded"}
PRESERVE_RULES = {"model_condition", "provenance_passthrough",
                  "artifact_attestation_attach"}
IMPL_CAP_DEFAULT = "independently-recomputed"

MACHINE_SHIFT_OPS = {"shl", "shr_logical", "shr_arith", "rotl", "rotr"}
MACHINE_UNARY = {"not", "neg", "convert"} | MACHINE_SHIFT_OPS


class KernelError(Exception):
    """Producer-side refusal (stable reason + detail)."""

    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(detail)
        self.reason = reason
        self.detail = detail


# --------------------------------------------------------------- canonical
def canonical_bytes(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def sha_hex(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def rat_token(fr: Fraction) -> str:
    return str(fr.numerator) if fr.denominator == 1 else \
        f"{fr.numerator}/{fr.denominator}"


def node_id(node: dict) -> str:
    return sha_hex(canonical_bytes(
        {k: v for k, v in node.items() if k != "id"}))


def with_id(node: dict) -> dict:
    node["id"] = node_id(node)
    return node


# ------------------------------------------------------------ unit registry
class Units:
    def __init__(self, registry_path: Path) -> None:
        doc = json.loads(registry_path.read_text())
        self.raw_sha = sha_hex(registry_path.read_bytes())
        self.units = {}
        for uid, row in doc["units"].items():
            self.units[uid] = {
                "dim": tuple(row["dim"]),
                "scale": Fraction(row["scale"]),
                "offset": Fraction(row["offset"]) if "offset" in row
                else None,
                "kind": row["kind"],
            }
        self.aliases = dict(doc.get("aliases", {}))

    def canonicalize(self, uid: str) -> str:
        """Alias resolution — INPUT canonicalization only."""
        if uid in self.units:
            return uid
        if uid in self.aliases:
            return self.aliases[uid]
        raise KernelError("unit-unknown", uid)

    def row(self, uid: str) -> dict:
        if uid not in self.units:
            raise KernelError("unit-unknown", uid)
        return self.units[uid]


# ----------------------------------------------------------- axis algebra
def _meet(values: list[str], order: list[str],
          ranks: dict | None = None) -> str:
    if ranks is None:
        return min(values, key=order.index)
    return min(values, key=lambda v: (ranks[v], order.index(v)))


def _meet_model(values: list[str]) -> str:
    real = [v for v in values if v != MODEL_IDENTITY]
    return _meet(real, MODEL_ORDER) if real else MODEL_IDENTITY


def computed_axes(rule_id: str, parents: list[dict]) -> dict:
    math = _meet([p["assurance"]["mathematical"] for p in parents],
                 MATH_ORDER, MATH_RANKS)
    cap = MATH_CAPS.get(rule_id)
    if cap is not None and MATH_RANKS[cap] < MATH_RANKS[math]:
        math = cap
    impl = _meet([p["assurance"]["implementation"] for p in parents],
                 IMPL_ORDER)
    if rule_id not in PRESERVE_RULES and \
            IMPL_ORDER.index(IMPL_CAP_DEFAULT) < IMPL_ORDER.index(impl):
        impl = IMPL_CAP_DEFAULT
    return {
        "input_provenance": _meet(
            [p["assurance"]["input_provenance"] for p in parents],
            PROV_ORDER),
        "model_validity": _meet_model(
            [p["assurance"]["model_validity"] for p in parents]),
        "mathematical": math,
        "implementation": impl,
        "artifact": {flag: all(p["assurance"]["artifact"][flag]
                               for p in parents)
                     for flag in ARTIFACT_FLAGS},
    }


def merged_env(parents: list[dict]) -> dict:
    vars_: dict = {}
    for p in parents:
        vars_.update(p["env"]["vars"])
    return {"vars": vars_}


def merged_assumptions(parents: list[dict],
                       extra: list[str] | None = None) -> list[str]:
    out: list[str] = []
    for p in parents:
        for a in p["assumptions"]:
            if a not in out:
                out.append(a)
    for a in (extra or []):
        if a not in out:
            out.append(a)
    return out


def merged_residuals(parents: list[dict]) -> list[str]:
    out = list(RESIDUALS)
    for p in parents:
        for r in p["residual_non_claims"]:
            if r not in out:
                out.append(r)
    return out


# ------------------------------------------------------------ freshness
def freshness_block(*, environment_epoch: str, emitted_at_unix: str,
                    source_version: str = RELEASE_EPOCH,
                    max_age_seconds: int | None = None,
                    expires_at_unix: str | None = None,
                    nonce: str | None = None) -> dict:
    return {
        "source_version": source_version,
        "emitted_at_unix": emitted_at_unix,
        "max_age_seconds": max_age_seconds,
        "expires_at_unix": expires_at_unix,
        "nonce": nonce,
        "environment_epoch": environment_epoch,
    }


# --------------------------------------------------------------- builders
def _base_node(*, proposition, freshness: dict, env=None, assumptions=None,
               evidence=None, producer=None, checker=None, parents=None,
               rule=None, assurance=None, residuals=None, decision=None,
               display_text: str = "") -> dict:
    node = {
        "schema": SCHEMA_NODE,
        "proposition": proposition,
        "env": env or {"vars": {}},
        "assumptions": assumptions or [],
        "evidence": evidence or {"kind": "none"},
        "producer": producer,
        "checker": checker,
        "release_epoch": RELEASE_EPOCH,
        "parents": parents or [],
        "rule": rule,
        "assurance": assurance,
        "freshness": freshness,
        "residual_non_claims": residuals or list(RESIDUALS),
        "decision": decision,
        "display": {"text": display_text},
    }
    return with_id(node)


def build_input_node(*, name: str, lo: str, hi: str, freshness: dict,
                     unit: str | None = None, source_id: str | None = None,
                     provenance: str = "supplied",
                     mathematical: str = "checked",
                     model_validity: str = MODEL_IDENTITY,
                     source_description: str | None = None,
                     display_text: str = "") -> dict:
    if provenance not in ("unknown", "supplied", "integrity-bound"):
        raise KernelError("provenance-upgrade",
                          f"v1 inputs may not declare {provenance!r}")
    if MATH_RANKS.get(mathematical, 99) > MATH_RANKS["checked"]:
        raise KernelError("assurance-launder",
                          "input mathematical class caps at checked")
    prop = {"t": "in", "arg": {"t": "var", "name": name},
            "set": {"t": "interval", "lo": lo, "hi": hi}}
    if unit is not None:
        prop["unit"] = unit
    params = {"source_description":
              source_description or f"supplied-input-{name}",
              "declared_provenance": provenance}
    if source_id is not None:
        params["source_id"] = source_id
    return _base_node(
        proposition=prop,
        env={"vars": {name: {"t": "interval", "lo": lo, "hi": hi}}},
        rule={"id": "input_declare", "params": params},
        assurance={"input_provenance": provenance,
                   "model_validity": model_validity,
                   "mathematical": mathematical,
                   "implementation": "directly-trusted",
                   "artifact": dict(ARTIFACT_FALSE)},
        freshness=freshness,
        display_text=display_text)


def build_receipt_node(*, receipt: dict, receipt_bytes: bytes,
                       checker_sha256: str, freshness: dict,
                       display_text: str = "") -> dict:
    req = receipt["request"]
    variant = receipt.get("variant", "range")
    domain = {"t": "interval", "lo": req["canonical_lo"],
              "hi": req["canonical_hi"]}
    enclosure = {"t": "interval",
                 "lo": receipt["result"]["enclosure_lo"],
                 "hi": receipt["result"]["enclosure_hi"]}
    if variant == "gaussian":
        arg = {"t": "app", "fn": "formal.gaussian_integral",
               "args": [{"t": "str", "v": req["expression"]}, domain,
                        {"t": "rat", "v": req["canonical_tolerance"]}]}
        expected_request = {"command": req["command"],
                            "expression": req["expression"],
                            "input_lo": req["input_lo"],
                            "input_hi": req["input_hi"],
                            "tolerance": req["tolerance"]}
    else:
        arg = {"t": "app", "fn": "formal.range",
               "args": [{"t": "str", "v": req["expression"]}, domain]}
        expected_request = {"command": req["command"],
                            "expression": req["expression"],
                            "input_lo": req["input_lo"],
                            "input_hi": req["input_hi"]}
    prop = {"t": "in", "arg": arg, "set": enclosure}
    return _base_node(
        proposition=prop,
        assumptions=[f"receipt:{a}" for a in receipt["assumptions"]],
        evidence={"kind": "formal-receipt",
                  "payload_b64": base64.b64encode(receipt_bytes).decode(),
                  "sha256": sha_hex(receipt_bytes)},
        producer={"name": f"{variant}-producer",
                  "sha256": receipt["identities"]["evaluator_sha256"]},
        checker={"name": "jackal_cert_check" if variant != "gaussian"
                 else "jackal_gaussian_check",
                 "sha256": checker_sha256},
        rule={"id": "evidence_admit",
              "params": {"evidence_kind": "formal-receipt",
                         "expected_request": expected_request,
                         "expected_release_epoch":
                             receipt["release_epoch"],
                         "expected_identities": {
                             "evaluator_sha256":
                                 receipt["identities"]["evaluator_sha256"],
                             "checker_sha256": checker_sha256}}},
        assurance={"input_provenance": "supplied",
                   "model_validity": "assumed",
                   "mathematical": "formal-bounded",
                   "implementation": "checker-derived",
                   "artifact": dict(ARTIFACT_CA)},
        freshness=freshness,
        display_text=display_text)


def build_exact_node(*, cert: dict, freshness: dict,
                     display_text: str = "") -> dict:
    raw = canonical_bytes(cert)
    kind = cert["kind"]
    claim = cert["claim"]

    def num(tok: str) -> dict:
        return {"t": "rat", "v": tok}

    def point(fn: str, args: list[dict], value: str) -> dict:
        return {"t": "in", "arg": {"t": "app", "fn": fn, "args": args},
                "set": {"t": "interval", "lo": value, "hi": value}}

    if kind == "xgcd":
        prop = point("gcd", [num(claim["a"]), num(claim["b"])], claim["g"])
    elif kind == "mod-inv":
        prop = point("mod_inv", [num(claim["a"]), num(claim["m"])],
                     claim["inv"])
    elif kind == "mod-pow":
        prop = point("mod_pow", [num(claim["base"]), num(claim["exp"]),
                                 num(claim["mod"])], claim["r"])
    elif kind == "crt":
        args: list[dict] = []
        for residue in claim["residues"]:
            args.append(num(residue["r"]))
            args.append(num(residue["m"]))
        prop = point("crt_solve", args, claim["x"])
    elif kind == "prime":
        prop = {"t": "pred", "name": "prime", "args": [num(claim["n"])]}
    elif kind == "composite":
        prop = {"t": "pred", "name": "composite",
                "args": [num(claim["n"])]}
    else:
        prop = {"t": "pred", "name": f"exact:{kind}",
                "args": [{"t": "str",
                          "v": canonical_bytes(claim).decode("utf-8")}]}
    return _base_node(
        proposition=prop,
        evidence={"kind": "exact-cert",
                  "payload_b64": base64.b64encode(raw).decode(),
                  "sha256": sha_hex(raw)},
        rule={"id": "evidence_admit",
              "params": {"evidence_kind": "exact-cert"}},
        assurance={"input_provenance": "supplied",
                   "model_validity": MODEL_IDENTITY,
                   "mathematical": "exact",
                   "implementation": "independently-recomputed",
                   "artifact": dict(ARTIFACT_CA)},
        freshness=freshness,
        display_text=display_text)


# ---------------------------------------------------------- machine certs
def machine_range(width: int, signed: bool) -> tuple[int, int]:
    if signed:
        return -(1 << (width - 1)), (1 << (width - 1)) - 1
    return 0, (1 << width) - 1


def _to_bits(v: int, w: int) -> int:
    return v % (1 << w)


def _from_bits(b: int, w: int, signed: bool) -> int:
    if signed and b >= (1 << (w - 1)):
        return b - (1 << w)
    return b


def build_machine_cert(*, op: str, width: int, signed: bool, mode: str,
                       operands: list[int],
                       shift: int | None = None) -> dict:
    if width not in (8, 16, 32, 64):
        raise KernelError("machine-cert-invalid", f"width {width}")
    if mode not in ("wrap", "checked"):
        raise KernelError("machine-cert-invalid", f"mode {mode}")
    want_n = 1 if op in MACHINE_UNARY else 2
    if len(operands) != want_n:
        raise KernelError("machine-cert-invalid", "operand count")
    lo_r, hi_r = machine_range(width, signed)
    if op != "convert":
        for v in operands:
            if not (lo_r <= v <= hi_r):
                raise KernelError("machine-width", str(v))
    if op in MACHINE_SHIFT_OPS:
        if shift is None or not (0 <= shift < width):
            raise KernelError("machine-shift-range", str(shift))
    elif shift is not None:
        raise KernelError("machine-cert-invalid", "shift forbidden")
    w = width
    if op in ("add", "sub", "mul"):
        a, b = operands
        math = {"add": a + b, "sub": a - b, "mul": a * b}[op]
    elif op == "neg":
        math = -operands[0]
    elif op in ("and", "or", "xor"):
        a, b = (_to_bits(operands[0], w), _to_bits(operands[1], w))
        math = _from_bits({"and": a & b, "or": a | b,
                           "xor": a ^ b}[op], w, signed)
    elif op == "not":
        math = _from_bits(_to_bits(operands[0], w) ^ ((1 << w) - 1), w,
                          signed)
    elif op == "shl":
        math = operands[0] * (1 << shift)
    elif op == "shr_logical":
        math = _from_bits(_to_bits(operands[0], w) >> shift, w, signed)
    elif op == "shr_arith":
        math = operands[0] >> shift
    elif op in ("rotl", "rotr"):
        bits = _to_bits(operands[0], w)
        s = shift % w
        if s:
            if op == "rotl":
                bits = ((bits << s) | (bits >> (w - s))) & ((1 << w) - 1)
            else:
                bits = ((bits >> s) | (bits << (w - s))) & ((1 << w) - 1)
        math = _from_bits(bits, w, signed)
    elif op == "convert":
        math = operands[0]
    elif op in ("eq", "lt", "le", "gt", "ge"):
        a, b = operands
        math = int({"eq": a == b, "lt": a < b, "le": a <= b,
                    "gt": a > b, "ge": a >= b}[op])
    else:
        raise KernelError("machine-cert-invalid", f"op {op!r}")
    machine = _from_bits(_to_bits(math, w), w, signed)
    if op in ("eq", "lt", "le", "gt", "ge"):
        machine = math
    return {
        "schema": SCHEMA_MACHINE,
        "width": width,
        "signed": signed,
        "op": op,
        "mode": mode,
        "operands": [str(v) for v in operands],
        "shift": str(shift) if shift is not None else None,
        "math_result": str(math),
        "machine_result": str(machine),
        "overflow": math != machine,
        "semantics": "two-complement-v1",
    }


def machine_fn(cert: dict) -> str:
    return (f"m.{cert['op']}.w{cert['width']}."
            f"{'s' if cert['signed'] else 'u'}.{cert['mode']}")


def machine_eq_prop(cert: dict) -> dict:
    w, s = cert["width"], cert["signed"]
    if cert["op"] == "convert":
        args: list[dict] = [{"t": "rat", "v": v} for v in cert["operands"]]
    else:
        args = [{"t": "bitvec", "width": w, "signed": s, "v": v}
                for v in cert["operands"]]
    if cert["shift"] is not None:
        args.append({"t": "rat", "v": cert["shift"]})
    return {"t": "eq",
            "lhs": {"t": "app", "fn": machine_fn(cert), "args": args},
            "rhs": {"t": "bitvec", "width": w, "signed": s,
                    "v": cert["machine_result"]}}


def machine_overflow_prop(cert: dict) -> dict:
    w, s = cert["width"], cert["signed"]
    if cert["op"] == "convert":
        args: list[dict] = [{"t": "rat", "v": v} for v in cert["operands"]]
    else:
        args = [{"t": "bitvec", "width": w, "signed": s, "v": v}
                for v in cert["operands"]]
    return {"t": "pred",
            "name": (f"m.overflow.{cert['op']}.w{w}."
                     f"{'s' if s else 'u'}.checked"),
            "args": args}


def build_machine_node(*, cert: dict, freshness: dict,
                       display_text: str = "") -> dict:
    raw = canonical_bytes(cert)
    checked_overflow = cert["mode"] == "checked" and cert["overflow"]
    prop = machine_overflow_prop(cert) if checked_overflow \
        else machine_eq_prop(cert)
    return _base_node(
        proposition=prop,
        evidence={"kind": "machine-int-cert",
                  "payload_b64": base64.b64encode(raw).decode(),
                  "sha256": sha_hex(raw)},
        rule={"id": "evidence_admit",
              "params": {"evidence_kind": "machine-int-cert"}},
        assurance={"input_provenance": "supplied",
                   "model_validity": MODEL_IDENTITY,
                   "mathematical": "exact",
                   "implementation": "independently-recomputed",
                   "artifact": dict(ARTIFACT_CA)},
        freshness=freshness,
        display_text=display_text)


# ------------------------------------------------------------ derived nodes
def _derived(rule_id: str, parents: list[dict], proposition: dict,
             params: dict, freshness: dict, *,
             decision: dict | None = None,
             extra_assumptions: list[str] | None = None,
             axes_override: dict | None = None,
             display_text: str = "") -> dict:
    axes = axes_override or computed_axes(rule_id, parents)
    return _base_node(
        proposition=proposition,
        env=merged_env(parents),
        assumptions=merged_assumptions(parents, extra_assumptions),
        parents=[p["id"] for p in parents],
        rule={"id": rule_id, "params": params},
        assurance=axes,
        residuals=merged_residuals(parents),
        freshness=freshness,
        decision=decision,
        display_text=display_text)


def hull(op: str, a: tuple, b: tuple) -> tuple:
    lo1, hi1 = a
    lo2, hi2 = b
    if op == "add":
        return lo1 + lo2, hi1 + hi2
    if op == "sub":
        return lo1 - hi2, hi1 - lo2
    if op == "mul":
        prods = [lo1 * lo2, lo1 * hi2, hi1 * lo2, hi1 * hi2]
        return min(prods), max(prods)
    if op == "div":
        recips = [1 / lo2, 1 / hi2]
        prods = [lo1 * r for r in recips] + [hi1 * r for r in recips]
        return min(prods), max(prods)
    raise KernelError("rule-unknown", op)


def _interval_of(prop: dict) -> tuple:
    return (Fraction(prop["set"]["lo"]), Fraction(prop["set"]["hi"]))


def build_interval_node(op: str, p1: dict, p2: dict, units: Units,
                        freshness: dict) -> dict:
    prop1, prop2 = p1["proposition"], p2["proposition"]
    if prop1.get("t") != "in" or prop2.get("t") != "in":
        raise KernelError("rule-invalid", "parents must be enclosures")
    u1, u2 = prop1.get("unit"), prop2.get("unit")
    row1 = units.row(u1) if u1 else None
    row2 = units.row(u2) if u2 else None
    for uid, row in ((u1, row1), (u2, row2)):
        if row is not None and row["kind"] == "affine":
            raise KernelError("unit-affine-forbidden", uid or "")
    i1, i2 = _interval_of(prop1), _interval_of(prop2)
    if op in ("add", "sub"):
        if u1 != u2:
            raise KernelError("unit-dim-mismatch", f"{u1!r} vs {u2!r}")
        result_unit, result_row = u1, row1
        j1, j2 = i1, i2
    else:
        if op == "div" and i2[0] <= 0 <= i2[1]:
            raise KernelError("interval-div-zero", "denominator")
        def zerodim(row):
            return row is not None and all(e == 0 for e in row["dim"])
        if u1 is None and u2 is None:
            result_unit, result_row = None, None
            j1, j2 = i1, i2
        elif row1 is not None and zerodim(row2):
            result_unit, result_row = u1, row1
            j1 = i1
            j2 = (i2[0] * row2["scale"], i2[1] * row2["scale"])
        elif zerodim(row1) and row2 is not None:
            result_unit, result_row = u2, row2
            j1 = (i1[0] * row1["scale"], i1[1] * row1["scale"])
            j2 = i2
        elif row1 is not None and row2 is None:
            result_unit, result_row = u1, row1
            j1, j2 = i1, i2
        elif row1 is None and row2 is not None:
            result_unit, result_row = u2, row2
            j1, j2 = i1, i2
        else:
            result_unit, result_row = None, None
            j1 = (i1[0] * row1["scale"], i1[1] * row1["scale"])
            j2 = (i2[0] * row2["scale"], i2[1] * row2["scale"])
        if op == "div" and j2[0] <= 0 <= j2[1]:
            raise KernelError("interval-div-zero", "denominator")
    h = hull(op, j1, j2)
    if result_row is not None and op in ("mul", "div"):
        h = (h[0] / result_row["scale"], h[1] / result_row["scale"])
    prop = {"t": "in",
            "arg": {"t": op, "lhs": prop1["arg"], "rhs": prop2["arg"]},
            "set": {"t": "interval", "lo": rat_token(h[0]),
                    "hi": rat_token(h[1])}}
    if result_unit is not None:
        prop["unit"] = result_unit
    return _derived(f"interval_{op}", [p1, p2], prop, {}, freshness)


def build_and_node(parents: list[dict], freshness: dict) -> dict:
    prop = {"t": "and", "args": [p["proposition"] for p in parents]}
    return _derived("and_intro", parents, prop, {}, freshness)


def build_threshold_node(parent: dict, op: str, threshold: str,
                         freshness: dict) -> dict:
    prop_parent = parent["proposition"]
    if prop_parent.get("t") != "in":
        raise KernelError("rule-invalid", "threshold parent must enclose")
    if "unit" in prop_parent:
        raise KernelError("rule-invalid",
                          "threshold requires a unitless enclosure")
    lo, hi = _interval_of(prop_parent)
    t = Fraction(threshold)
    established = {"lt": hi < t, "le": hi <= t,
                   "gt": lo > t, "ge": lo >= t}[op]
    if not established:
        raise KernelError("threshold-not-established",
                          f"[{rat_token(lo)},{rat_token(hi)}] vs "
                          f"{op} {threshold}")
    prop = {"t": op, "lhs": prop_parent["arg"],
            "rhs": {"t": "rat", "v": threshold}}
    return _derived("threshold_from_enclosure", [parent], prop,
                    {"op": op, "threshold": threshold}, freshness)


def build_decision_node(thr: dict, encl: dict, *, decision_id: str,
                        action: str, consequence_class: str,
                        freshness: dict) -> dict:
    cmp_prop = thr["proposition"]
    op = cmp_prop["t"]
    t = Fraction(cmp_prop["rhs"]["v"])
    lo, hi = _interval_of(encl["proposition"])
    margin = (t - hi) if op in ("lt", "le") else (lo - t)
    prop = {"t": "pred", "name": "threshold_robust",
            "args": [cmp_prop["lhs"], {"t": "str", "v": op},
                     cmp_prop["rhs"]]}
    decision = {"decision_id": decision_id, "action": action,
                "comparison": op, "threshold": cmp_prop["rhs"]["v"],
                "margin": rat_token(margin),
                "consequence_class": consequence_class}
    return _derived("robust_decision", [thr], prop,
                    {"decision_id": decision_id, "action": action,
                     "consequence_class": consequence_class},
                    freshness, decision=decision)


def build_convert_node(parent: dict, target_unit: str, units: Units,
                       freshness: dict) -> dict:
    prop_parent = parent["proposition"]
    if prop_parent.get("t") != "in" or "unit" not in prop_parent:
        raise KernelError("rule-invalid", "convert parent must be united")
    src_uid = prop_parent["unit"]
    src, dst = units.row(src_uid), units.row(target_unit)
    if src["dim"] != dst["dim"]:
        raise KernelError("unit-dim-mismatch",
                          f"{src_uid} -> {target_unit}")
    lo, hi = _interval_of(prop_parent)
    affine = src["kind"] == "affine" or dst["kind"] == "affine"
    rule_id = "unit_convert_affine" if affine else "unit_convert_linear"
    if affine and lo != hi:
        raise KernelError("unit-affine-forbidden", "point values only")
    src_off = src["offset"] or Fraction(0)
    dst_off = dst["offset"] or Fraction(0)
    si_lo = lo * src["scale"] + src_off
    si_hi = hi * src["scale"] + src_off
    want_lo = (si_lo - dst_off) / dst["scale"]
    want_hi = (si_hi - dst_off) / dst["scale"]
    prop = {"t": "in", "arg": prop_parent["arg"],
            "set": {"t": "interval", "lo": rat_token(want_lo),
                    "hi": rat_token(want_hi)},
            "unit": target_unit}
    return _derived(rule_id, [parent], prop,
                    {"target_unit": target_unit}, freshness)


def build_model_condition_node(parent: dict, added: list[str],
                               freshness: dict) -> dict:
    node = _derived("model_condition", [parent], parent["proposition"],
                    {"added_assumptions": added}, freshness,
                    extra_assumptions=added,
                    axes_override=dict(parent["assurance"]))
    parent_model = parent["assurance"]["model_validity"]
    node["assurance"] = dict(parent["assurance"])
    node["assurance"]["artifact"] = dict(
        parent["assurance"]["artifact"])
    node["assurance"]["model_validity"] = (
        "assumed" if parent_model == MODEL_IDENTITY else parent_model)
    return with_id(node)


def build_passthrough_node(parent: dict, freshness: dict) -> dict:
    return _derived("provenance_passthrough", [parent],
                    parent["proposition"], {}, freshness,
                    axes_override=dict(parent["assurance"]))


def build_attach_node(parent: dict, attestations: list[dict],
                      flags: dict, freshness: dict) -> dict:
    axes = dict(parent["assurance"])
    art = dict(parent["assurance"]["artifact"])
    art.update(flags)
    axes["artifact"] = art
    return _derived("artifact_attestation_attach", [parent],
                    parent["proposition"],
                    {"attestations": attestations}, freshness,
                    axes_override=axes)


# ------------------------------------------------------------------ policy
def default_policy(**over) -> dict:
    pol = {
        "schema": SCHEMA_POLICY,
        "policy_id": "jackal-default-v1",
        "accept": {
            "input_provenance": ["supplied", "integrity-bound"],
            "model_validity": ["not-applicable", "assumed"],
            "mathematical": ["checked", "bounded", "formal-bounded",
                             "exact"],
            "implementation": ["directly-trusted", "campaign-tested",
                               "independently-recomputed",
                               "checker-derived"],
            "artifact_required_flags": {},
        },
        "require": {
            "max_nodes": 128,
            "max_depth": 32,
            "require_nonce": False,
            "max_age_seconds": None,
            "decision_margin_min": None,
            "max_enclosure_width": None,
            "forbid_rules": [],
        },
        "allow_fallback": False,
    }
    pol.update(over)
    return pol


def policy_sha256(policy: dict) -> str:
    return sha_hex(canonical_bytes(policy))


# ---------------------------------------------------------------- renderer
MATH_WORDING = {
    "exact": "Exact over the admitted integer/rational semantics",
    "formal-bounded": ("Formally enclosed under the named checker and "
                       "model assumptions"),
    "bounded": "Bounded enclosure composed via registered interval rules",
    "checked": "Checked result",
    "estimated": "Estimate without certified bound",
    "model-based": "Model-based result",
    "indeterminate": "Indeterminate",
    "refused": "Refused",
}
IMPL_WORDING = {
    "unknown": "implementation status unknown",
    "directly-trusted": "directly trusted implementation",
    "campaign-tested": "campaign-tested implementation",
    "independently-recomputed": "independently recomputed",
    "checker-derived": "implementation checker-derived",
    "source-native-refined": "source-native refined",
}
MODEL_WORDING = {
    "not-applicable": "no physical model involved",
    "unknown": "model validity unknown",
    "assumed": "conditional on the stated model assumptions",
    "calibrated": "calibrated model",
    "empirically-validated": "empirically validated model",
}


def render(root: dict) -> dict:
    a = root["assurance"]
    fresh = root["freshness"]
    parts = [
        MATH_WORDING[a["mathematical"]],
        IMPL_WORDING[a["implementation"]],
        f"input provenance {a['input_provenance']}",
        MODEL_WORDING[a["model_validity"]],
    ]
    token_parts = ["render-v1", a["mathematical"], a["input_provenance"],
                   a["model_validity"], a["implementation"]]
    if root["decision"] is not None:
        d = root["decision"]
        parts.append(
            f"decision {d['decision_id']} ({d['consequence_class']}) "
            f"robust with certified margin {d['margin']}")
        token_parts.append("decision")
    if fresh["nonce"] is not None:
        parts.append("nonce-bound")
        token_parts.append("nonce")
    if fresh["max_age_seconds"] is not None \
            or fresh["expires_at_unix"] is not None:
        parts.append("age-checked")
        token_parts.append("aged")
    if root["assumptions"]:
        parts.append("assumptions(" + str(len(root["assumptions"])) + "): "
                     + "; ".join(root["assumptions"]))
    parts.append("non-claims: " + "; ".join(root["residual_non_claims"]))
    return {"token": "/".join(token_parts),
            "permitted_text": ". ".join(parts) + "."}


# ------------------------------------------------------------------ bundle
def build_bundle(*, nodes: list[dict], root_id: str, policy: dict,
                 evaluator_sha256: str, source_anb_sha256: str,
                 inference_registry_sha256: str,
                 unit_registry_sha256: str,
                 rendering: dict | None = None) -> dict:
    by_id = {n["id"]: n for n in nodes}
    if root_id not in by_id:
        raise KernelError("root-missing", root_id[:16])
    bundle = {
        "schema": SCHEMA_BUNDLE,
        "release_epoch": RELEASE_EPOCH,
        "engine_identity": {"evaluator_sha256": evaluator_sha256,
                            "source_anb_sha256": source_anb_sha256},
        "registries": {
            "inference_registry_sha256": inference_registry_sha256,
            "unit_registry_sha256": unit_registry_sha256},
        "policy": policy,
        "nodes": nodes,
        "root": root_id,
        "rendering": rendering if rendering is not None
        else render(by_id[root_id]),
    }
    bundle["bundle_digest_sha256"] = sha_hex(canonical_bytes(
        {k: v for k, v in bundle.items() if k != "bundle_digest_sha256"}))
    return bundle


def dump_bundle(bundle: dict) -> str:
    return json.dumps(bundle, indent=1, sort_keys=True) + "\n"
