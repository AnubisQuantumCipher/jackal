#!/usr/bin/env python3
"""Deterministic policy router for JACKAL claim requests (v1.6.0).

Compiles a `jackal-claim-request-v1` into a `jackal-claim-bundle-v1` by
routing through the existing JACKAL lanes under deterministic constrained
selection:

  1. every policy predicate must be satisfiable by the selected lane;
  2. exact/formal lanes are preferred over weaker ones (stable
     ROUTE_ORDER below);
  3. trusted components are minimized (fewest subprocess hops that
     satisfy 1);
  4. unresolved assumptions/non-claims are minimized (formal variants
     before the general range lane);
  5. enclosure width is minimized only among lanes that already satisfy
     the above;
  6. runtime cost is considered last;
  7. ties break by the documented stable lane order.

The router emits a route trace naming candidates, refusal reasons, and
the selected lane.  It never silently downgrades: `allow_fallback`
defaults to false, and in v1 no sound weaker lane exists for enclosure
requests, so fallback requests refuse explicitly instead of downgrading.

Request schema (`jackal-claim-request-v1`):

  {
    "schema": "jackal-claim-request-v1",
    "policy": {...jackal-claim-policy-v1... | omitted for default},
    "nonce": "..." | null,
    "emitted_at_unix": "<int token>"        (omitted -> wall clock),
    "max_age_seconds": int | null,
    "expires_at_unix": "<int token>" | null,
    "steps": [ {"id": "...", "op": ...}, ... ],
    "root": "<step id>"
  }

Step ops:
  input            name, lo, hi, [unit], [source_id], [provenance],
                   [mathematical]
  exact            command (engine exact-cert command), args[]
  enclose          expression, lo, hi  (deterministic formal lane choice)
  gaussian         expression, lo, hi, tolerance
  machine          mop, width, signed, mode, operands[], [shift]
  interval_add/sub/mul/div   lhs, rhs (step ids)
  threshold        arg, cmp (lt|le|gt|ge), threshold
  decision         arg (threshold step), decision_id, action,
                   consequence_class
  convert          arg, target_unit
  and              args[] (step ids)
  model            arg, assumptions[]
  passthrough      arg
  attach           arg, attestations[], flags{}

Run: python3 -I -S -B tools/claim_router.py claim --request <file|-> \
     [--emit-bundle <path>]
"""
from __future__ import annotations

import sys

if not (sys.flags.isolated and sys.flags.no_site):
    sys.stderr.write(
        "status=refused reason=python-not-isolated "
        "detail=\"requires python3 -I -S -B\"\n")
    sys.exit(126)

import argparse            # noqa: E402
import hashlib             # noqa: E402
import json                # noqa: E402
import subprocess          # noqa: E402
import time                # noqa: E402
from pathlib import Path   # noqa: E402

HERE = Path(__file__).resolve().parent


def _layout() -> dict:
    """Repo layout (tools/ + siblings) or package-flat layout."""
    if HERE.name == "tools" and (HERE.parent / "release").is_dir():
        root = HERE.parent
        return {
            "root": root,
            "engine": root / "jackal-native",
            "manifest": root / "release/MANIFEST.sha256",
            "checker": root / "proofs/lean/.lake/build/bin/"
                              "jackal_cert_check",
            "gaussian_checker": root / "proofs/lean/.lake/build/bin/"
                                       "jackal_gaussian_check",
            "inventory": root / "release/coverage/"
                                "formal_coverage_inventory.json",
            "proof_identity": root / "release/evidence/"
                                     "range_proof_identity.json",
            "gaussian_proof_identity": root / "release/evidence/"
                                              "gaussian_proof_identity.json",
            "inference_registry": root / "release/claim/"
                                         "inference_registry_v1.json",
            "unit_registry": root / "release/claim/unit_registry_v1.json",
            "producers": root / "tools",
            "source_anb": root / "jackal_calc.anb",
        }
    root = HERE
    return {
        "root": root,
        "engine": root / "jackal-native",
        "manifest": root / "MANIFEST.sha256",
        "checker": root / "jackal_cert_check",
        "gaussian_checker": root / "jackal_gaussian_check",
        "inventory": root / "formal_coverage_inventory.json",
        "proof_identity": root / "range_proof_identity.json",
        "gaussian_proof_identity": root / "gaussian_proof_identity.json",
        "inference_registry": root / "inference_registry_v1.json",
        "unit_registry": root / "unit_registry_v1.json",
        "producers": root,
        "source_anb": root / "jackal_calc.anb",
    }


LAYOUT = _layout()
sys.path.insert(0, str(HERE))

import claim_kernel as ck          # noqa: E402
import formal_receipt as fr        # noqa: E402

VARIANT_EXPRESSIONS = {
    "sqrt(x)": "sqrt_rat",
    "exp(x)": "exp_rat",
    "ln(x)": "ln_rat",
    "sin(x)": "sin_rat",
    "cos(x)": "cos_rat",
    "atan(x)": "atan_rat",
    fr.TANH_COMPOSITE_EXPRESSION.replace(" ", ""): "tanh_rat",
}
VARIANT_PRODUCER = {
    "sqrt_rat": "sqrt_rat_producer.py",
    "exp_rat": "exp_rat_producer.py",
    "ln_rat": "ln_rat_producer.py",
    "sin_rat": "sin_rat_producer.py",
    "cos_rat": "sin_rat_producer.py",
    "atan_rat": "atan_rat_producer.py",
    "tanh_rat": "tanh_rat_producer.py",
}
# Documented stable lane order for enclosure requests (rule 7):
ROUTE_ORDER = ["sqrt_rat", "exp_rat", "ln_rat", "sin_rat", "cos_rat",
               "atan_rat", "tanh_rat"]


def _admitted_expr_of(variant: str) -> str:
    for expr, v in VARIANT_EXPRESSIONS.items():
        if v == variant:
            return expr
    return variant

EXACT_COMMANDS = {
    "xgcd": 2, "mod-inv": 2, "mod-pow": 3, "crt": -1, "prime-cert": 1,
    "poly-canon": 1, "poly-eq": 2, "poly-gcd": 2, "ratfunc-canon": 1,
    "roots-isolate": 1, "divides": 2,
}

RELEASE_EPOCH_RECEIPTS = "v1.5.0"


class RouteRefusal(Exception):
    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(detail)
        self.reason = reason
        self.detail = detail


def sha_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _manifest_rows() -> dict[str, str]:
    rows: dict[str, str] = {}
    for line in LAYOUT["manifest"].read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        rows[parts[0]] = parts[-1]
    return rows


def _pinned_run(binary: Path, pin: str | None, argv: list[str],
                inp: bytes | None = None, timeout: int = 600,
                ) -> subprocess.CompletedProcess:
    """Run a binary with pre/post TOCTOU hash pinning."""
    if not binary.exists():
        raise RouteRefusal("lane-unavailable", f"missing {binary.name}")
    pre = sha_file(binary)
    if pin is not None and pre != pin:
        raise RouteRefusal("lane-identity", f"{binary.name} != pin")
    try:
        proc = subprocess.run([str(binary), *argv], capture_output=True,
                              input=inp, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RouteRefusal("lane-failed", str(exc)) from None
    if sha_file(binary) != pre:
        raise RouteRefusal("lane-identity", f"{binary.name} toctou")
    return proc


def _isolated_py(script: Path, argv: list[str], timeout: int = 600,
                 ) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            [sys.executable, "-I", "-S", "-B", str(script), *argv],
            capture_output=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RouteRefusal("lane-failed", str(exc)) from None


class Router:
    def __init__(self, request: dict) -> None:
        self.request = request
        self.rows = _manifest_rows()
        self.engine_sha = self.rows.get("evaluator")
        self.units = ck.Units(LAYOUT["unit_registry"])
        self.trace: list[dict] = []
        self.nodes: dict[str, dict] = {}
        self.order: list[dict] = []
        emitted = request.get("emitted_at_unix")
        self.emitted = str(emitted) if emitted is not None \
            else str(int(time.time()))
        self.env_epoch = sha_file(LAYOUT["engine"]) \
            if LAYOUT["engine"].exists() else (self.engine_sha or "")

    # ---------------------------------------------------------- helpers
    def fresh(self, *, nonce_ok: bool = False) -> dict:
        req = self.request
        return ck.freshness_block(
            environment_epoch=self.env_epoch,
            emitted_at_unix=self.emitted,
            max_age_seconds=req.get("max_age_seconds"),
            expires_at_unix=req.get("expires_at_unix"),
            nonce=req.get("nonce") if nonce_ok else req.get("nonce"))

    def log(self, step_id: str, op: str, candidates: list[dict],
            selected: str | None) -> None:
        self.trace.append({"step": step_id, "op": op,
                           "candidates": candidates,
                           "selected": selected})

    def ref(self, step_id) -> dict:
        if step_id not in self.nodes:
            raise RouteRefusal("request-schema",
                               f"unknown step reference {step_id!r}")
        return self.nodes[step_id]

    def add(self, step_id: str, node: dict) -> None:
        if step_id in self.nodes:
            raise RouteRefusal("request-schema",
                               f"duplicate step id {step_id!r}")
        self.nodes[step_id] = node
        self.order.append(node)

    # ------------------------------------------------------------ lanes
    def run_engine_exact(self, command: str, args: list[str]) -> dict:
        proc = _pinned_run(LAYOUT["engine"], self.engine_sha,
                           [command, *args])
        if proc.returncode != 0:
            raise RouteRefusal(
                "lane-refused",
                (proc.stderr or proc.stdout).decode(
                    errors="replace").strip()[:200])
        for line in proc.stdout.decode(errors="replace").splitlines():
            if line.startswith("exact-cert="):
                return json.loads(line[len("exact-cert="):])
        raise RouteRefusal("lane-refused",
                           f"{command}: no exact-cert emitted")

    def run_variant_producer(self, variant: str, expression: str,
                             lo: str, hi: str) -> tuple[bytes, str]:
        producer = LAYOUT["producers"] / VARIANT_PRODUCER[variant]
        if not producer.exists():
            raise RouteRefusal("lane-unavailable", producer.name)
        argv = ["emit", f"--expression={expression}",
                f"--lower={lo}", f"--upper={hi}"]
        proc = _isolated_py(producer, argv)
        if proc.returncode != 0:
            raise RouteRefusal(
                "lane-refused",
                (proc.stderr or proc.stdout).decode(
                    errors="replace").strip()[:200])
        return proc.stdout, sha_file(producer)

    def check_cert(self, cert: bytes, expression: str, lo: str,
                   hi: str) -> None:
        checker_pin = self.rows.get("checker")
        proc = _pinned_run(LAYOUT["checker"], checker_pin,
                           ["/dev/stdin", "range-bound-cert", expression,
                            lo, hi], inp=cert, timeout=3600)
        if proc.returncode != 0:
            raise RouteRefusal(
                "checker-rejected",
                (proc.stdout or proc.stderr).decode(
                    errors="replace").strip()[:200])

    def build_variant_receipt(self, variant: str, expression: str,
                              lo: str, hi: str, cert: bytes,
                              producer_sha: str) -> dict:
        req = {"command": "range-bound-cert", "expression": expression,
               "input_lo": lo, "input_hi": hi}
        hdr = fr._parse_cert_header(cert)
        enc_lo, enc_hi = hdr["output"].split(" ", 1)
        canonical_lo = ck.rat_token(__import__("fractions").Fraction(lo))
        canonical_hi = ck.rat_token(__import__("fractions").Fraction(hi))
        return fr.build_variant_formal_receipt(
            variant=variant, release_epoch=RELEASE_EPOCH_RECEIPTS,
            request=req, enclosure=(enc_lo, enc_hi), cert_bytes=cert,
            producer_sha256=producer_sha,
            checker_sha256=sha_file(LAYOUT["checker"]),
            canonical_lo=canonical_lo, canonical_hi=canonical_hi,
            request_commitment_b64=fr.request_commitment_b64(
                req["command"], expression, canonical_lo, canonical_hi),
            coverage_inventory_sha256=sha_file(LAYOUT["inventory"]),
            proof_identity=fr.load_proof_identity_binding(
                LAYOUT["proof_identity"]),
            plugin_sha256=None,
            emitted_at_unix=int(self.emitted))

    def machine_drift_alarm(self, cert: dict) -> None:
        """Cross-check bitwise/shift ops against the Anubis engine's
        exact commands (drift alarm, not the soundness root)."""
        if not LAYOUT["engine"].exists():
            return
        op = cert["op"]
        table = {"and": "band", "or": "bor", "xor": "bxor",
                 "shl": "shl", "shr_logical": "shr"}
        if op not in table or cert["signed"]:
            return
        args = list(cert["operands"])
        if cert["shift"] is not None:
            args.append(cert["shift"])
        proc = _pinned_run(LAYOUT["engine"], self.engine_sha,
                           [table[op], *args])
        if proc.returncode != 0:
            return
        out = proc.stdout.decode(errors="replace").strip().splitlines()
        got = out[-1].strip() if out else ""
        want = cert["math_result"] if op == "shl" \
            else cert["machine_result"]
        if got != want:
            raise RouteRefusal(
                "machine-engine-drift",
                f"{table[op]} {args}: engine {got!r} != cert {want!r}")

    # ------------------------------------------------------------ steps
    def compile(self) -> dict:
        request = self.request
        if request.get("schema") != "jackal-claim-request-v1":
            raise RouteRefusal("request-schema", "schema")
        steps = request.get("steps")
        if not isinstance(steps, list) or not steps:
            raise RouteRefusal("request-schema", "steps")
        if len(steps) > 128:
            raise RouteRefusal("request-budget", "steps > 128")
        policy = request.get("policy") or ck.default_policy()
        for step in steps:
            if not isinstance(step, dict) or "id" not in step \
                    or "op" not in step:
                raise RouteRefusal("request-schema", "step shape")
            self.compile_step(step, policy)
        root_ref = request.get("root")
        if root_ref not in self.nodes:
            raise RouteRefusal("request-schema", f"root {root_ref!r}")
        root = self.nodes[root_ref]
        bundle = ck.build_bundle(
            nodes=self.order, root_id=root["id"], policy=policy,
            evaluator_sha256=self.env_epoch,
            source_anb_sha256=self.rows.get(
                "source", sha_file(LAYOUT["source_anb"])
                if LAYOUT["source_anb"].exists() else "0" * 64),
            inference_registry_sha256=sha_file(
                LAYOUT["inference_registry"]),
            unit_registry_sha256=self.units.raw_sha)
        # pre-flight policy check: refuse at claim time, never downgrade
        self.policy_precheck(policy, root)
        return bundle

    def policy_precheck(self, policy: dict, root: dict) -> None:
        a = root["assurance"]
        accept = policy["accept"]
        for axis in ("input_provenance", "model_validity", "mathematical",
                     "implementation"):
            if a[axis] not in accept[axis]:
                if policy.get("allow_fallback"):
                    raise RouteRefusal(
                        "fallback-unavailable",
                        f"policy rejects root {axis}={a[axis]} and no "
                        "sound weaker lane exists in v1")
                raise RouteRefusal(
                    "policy-unsatisfied",
                    f"root {axis}={a[axis]} not in accepted "
                    f"{accept[axis]}; fallback disabled")

    def compile_step(self, step: dict, policy: dict) -> None:
        sid = step["id"]
        op = step["op"]
        fresh = self.fresh()
        try:
            if op == "input":
                node = ck.build_input_node(
                    name=step["name"], lo=step["lo"], hi=step["hi"],
                    unit=(self.units.canonicalize(step["unit"])
                          if step.get("unit") else None),
                    source_id=step.get("source_id"),
                    provenance=step.get("provenance", "supplied"),
                    mathematical=step.get("mathematical", "checked"),
                    freshness=fresh)
                self.log(sid, op, [{"lane": "input-declare",
                                    "status": "selected"}],
                         "input-declare")
            elif op == "exact":
                command = step["command"]
                if command not in EXACT_COMMANDS:
                    raise RouteRefusal("request-schema",
                                       f"exact command {command!r}")
                cert = self.run_engine_exact(command, list(step["args"]))
                node = ck.build_exact_node(cert=cert, freshness=fresh)
                self.log(sid, op, [{"lane": "engine-exact-cert",
                                    "status": "selected"}],
                         "engine-exact-cert")
            elif op == "enclose":
                node = self.step_enclose(sid, step, policy, fresh)
            elif op == "gaussian":
                node = self.step_gaussian(sid, step, fresh)
            elif op == "machine":
                cert = ck.build_machine_cert(
                    op=step["mop"], width=step["width"],
                    signed=step["signed"], mode=step["mode"],
                    operands=[int(v) for v in step["operands"]],
                    shift=int(step["shift"])
                    if step.get("shift") is not None else None)
                self.machine_drift_alarm(cert)
                node = ck.build_machine_node(cert=cert, freshness=fresh)
                self.log(sid, op, [{"lane": "machine-kernel",
                                    "status": "selected"}],
                         "machine-kernel")
            elif op in ("interval_add", "interval_sub", "interval_mul",
                        "interval_div"):
                node = ck.build_interval_node(
                    op.split("_", 1)[1], self.ref(step["lhs"]),
                    self.ref(step["rhs"]), self.units, fresh)
                self.log(sid, op, [{"lane": "interval-kernel",
                                    "status": "selected"}],
                         "interval-kernel")
            elif op == "threshold":
                node = ck.build_threshold_node(
                    self.ref(step["arg"]), step["cmp"],
                    step["threshold"], fresh)
                self.log(sid, op, [{"lane": "threshold-kernel",
                                    "status": "selected"}],
                         "threshold-kernel")
            elif op == "decision":
                thr = self.ref(step["arg"])
                encl = self.nodes_by_id(thr["parents"][0])
                node = ck.build_decision_node(
                    thr, encl, decision_id=step["decision_id"],
                    action=step["action"],
                    consequence_class=step["consequence_class"],
                    freshness=fresh)
                self.log(sid, op, [{"lane": "decision-kernel",
                                    "status": "selected"}],
                         "decision-kernel")
            elif op == "convert":
                node = ck.build_convert_node(
                    self.ref(step["arg"]),
                    self.units.canonicalize(step["target_unit"]),
                    self.units, fresh)
                self.log(sid, op, [{"lane": "unit-kernel",
                                    "status": "selected"}], "unit-kernel")
            elif op == "and":
                node = ck.build_and_node(
                    [self.ref(r) for r in step["args"]], fresh)
                self.log(sid, op, [{"lane": "and-kernel",
                                    "status": "selected"}], "and-kernel")
            elif op == "model":
                node = ck.build_model_condition_node(
                    self.ref(step["arg"]), list(step["assumptions"]),
                    fresh)
                self.log(sid, op, [{"lane": "model-kernel",
                                    "status": "selected"}], "model-kernel")
            elif op == "passthrough":
                node = ck.build_passthrough_node(self.ref(step["arg"]),
                                                 fresh)
                self.log(sid, op, [{"lane": "passthrough-kernel",
                                    "status": "selected"}],
                         "passthrough-kernel")
            elif op == "attach":
                node = ck.build_attach_node(
                    self.ref(step["arg"]),
                    list(step.get("attestations", [])),
                    dict(step.get("flags", {})), fresh)
                self.log(sid, op, [{"lane": "attach-kernel",
                                    "status": "selected"}],
                         "attach-kernel")
            else:
                raise RouteRefusal("rule-unknown",
                                   f"step op {op!r} is outside the "
                                   "registered v1 set")
        except ck.KernelError as exc:
            raise RouteRefusal(exc.reason, exc.detail) from None
        except KeyError as exc:
            raise RouteRefusal("request-schema",
                               f"step {sid!r} missing {exc}") from None
        self.add(sid, node)

    def nodes_by_id(self, node_id: str) -> dict:
        for node in self.order:
            if node["id"] == node_id:
                return node
        raise RouteRefusal("request-schema", "dangling parent")

    def step_enclose(self, sid: str, step: dict, policy: dict,
                     fresh: dict) -> dict:
        """Deterministic formal-lane selection for an enclosure request.

        v1 lane roster: the seven certified pure-Q variant producers, in
        the documented ROUTE_ORDER.  Expressions outside the variant
        fragments refuse with a full candidate trace — the general
        `range` emitter and every weaker lane remain first-class through
        their existing dedicated tools; the router never downgrades.
        """
        expression = step["expression"]
        lo, hi = step["lo"], step["hi"]
        from fractions import Fraction
        canonical_lo = ck.rat_token(Fraction(lo))
        canonical_hi = ck.rat_token(Fraction(hi))
        stripped = expression.replace(" ", "")
        variant = VARIANT_EXPRESSIONS.get(stripped)
        candidates: list[dict] = []
        node = None
        if variant is None:
            for lane in ROUTE_ORDER:
                candidates.append(
                    {"lane": lane, "status": "refused",
                     "reason": "lane-fragment",
                     "detail": f"admits only "
                               f"{_admitted_expr_of(lane)}"})
        else:
            try:
                cert, producer_sha = self.run_variant_producer(
                    variant, expression, lo, hi)
                self.check_cert(cert, expression, canonical_lo,
                                canonical_hi)
                receipt = self.build_variant_receipt(
                    variant, expression, lo, hi, cert, producer_sha)
                receipt_bytes = fr.dump_receipt(receipt).encode()
                node = ck.build_receipt_node(
                    receipt=receipt, receipt_bytes=receipt_bytes,
                    checker_sha256=sha_file(LAYOUT["checker"]),
                    freshness=fresh)
                candidates.append({"lane": variant,
                                   "status": "selected"})
            except RouteRefusal as exc:
                candidates.append({"lane": variant, "status": "refused",
                                   "reason": exc.reason,
                                   "detail": exc.detail[:120]})
        self.log(sid, "enclose", candidates,
                 variant if node is not None else None)
        if node is None:
            if policy.get("allow_fallback"):
                raise RouteRefusal(
                    "fallback-unavailable",
                    "no formal lane admitted the expression and no sound "
                    "weaker enclosure lane exists in v1")
            raise RouteRefusal(
                "lane-refused",
                f"no formal lane admitted {expression!r}; "
                "fallback disabled")
        return node

    def step_gaussian(self, sid: str, step: dict, fresh: dict) -> dict:
        producer = LAYOUT["producers"] / "gaussian_certificate.py"
        if not producer.exists():
            raise RouteRefusal("lane-unavailable", producer.name)
        expression = step["expression"]
        lo, hi, tol = step["lo"], step["hi"], step["tolerance"]
        proc = _isolated_py(producer, ["emit", "--expression", expression,
                                       "--lower", lo, "--upper", hi,
                                       "--tolerance", tol])
        if proc.returncode != 0:
            self.log(sid, "gaussian",
                     [{"lane": "gaussian", "status": "refused",
                       "reason": "lane-refused"}], None)
            raise RouteRefusal(
                "lane-refused",
                (proc.stderr or proc.stdout).decode(
                    errors="replace").strip()[:200])
        cert = proc.stdout
        checker = LAYOUT["gaussian_checker"]
        gproc = _pinned_run(checker, self.rows.get("gaussian-checker"),
                            ["/dev/stdin"], inp=cert, timeout=3600)
        if gproc.returncode != 0 or \
                b"gaussian_integral_check_sound" not in gproc.stdout:
            raise RouteRefusal("checker-rejected", "gaussian checker")
        from fractions import Fraction
        output = next(line for line in cert.decode().splitlines()
                      if line.startswith("output ")).split()
        receipt = fr.build_gaussian_formal_receipt(
            release_epoch=RELEASE_EPOCH_RECEIPTS,
            request={"command": "gaussian-exp-square-integral",
                     "expression": expression, "input_lo": lo,
                     "input_hi": hi, "tolerance": tol},
            enclosure=(output[1], output[2]), cert_bytes=cert,
            producer_sha256=sha_file(producer),
            checker_sha256=sha_file(checker),
            canonical_lo=ck.rat_token(Fraction(lo)),
            canonical_hi=ck.rat_token(Fraction(hi)),
            canonical_tolerance=ck.rat_token(Fraction(tol)),
            request_commitment_b64=fr.gaussian_request_commitment_b64(
                "gaussian-exp-square-integral", expression,
                ck.rat_token(Fraction(lo)), ck.rat_token(Fraction(hi)),
                ck.rat_token(Fraction(tol))),
            coverage_inventory_sha256=sha_file(LAYOUT["inventory"]),
            proof_identity=fr.load_proof_identity_binding(
                LAYOUT["gaussian_proof_identity"]),
            plugin_sha256=None,
            emitted_at_unix=int(self.emitted))
        receipt_bytes = fr.dump_receipt(receipt).encode()
        node = ck.build_receipt_node(
            receipt=receipt, receipt_bytes=receipt_bytes,
            checker_sha256=sha_file(checker), freshness=fresh)
        self.log(sid, "gaussian",
                 [{"lane": "gaussian", "status": "selected"}], "gaussian")
        return node


def compile_request(request: dict) -> dict:
    """Returns {status, root, bundle_digest_sha256, rendering,
    route_trace, bundle} or raises RouteRefusal."""
    router = Router(request)
    bundle = router.compile()
    return {
        "status": "ok",
        "root": bundle["root"],
        "bundle_digest_sha256": bundle["bundle_digest_sha256"],
        "rendering": bundle["rendering"],
        "route_trace": router.trace,
        "bundle": bundle,
    }


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="claim_router.py")
    sub = parser.add_subparsers(dest="mode", required=True)
    claim = sub.add_parser("claim")
    claim.add_argument("--request", required=True)
    claim.add_argument("--emit-bundle")
    args = parser.parse_args(argv)
    raw = sys.stdin.buffer.read() if args.request == "-" \
        else Path(args.request).read_bytes()
    try:
        request = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"status=refused reason=request-schema detail=\"{exc}\"")
        return 1
    try:
        result = compile_request(request)
    except RouteRefusal as exc:
        print(f"status=refused reason={exc.reason} "
              f"detail=\"{exc.detail[:200]}\"")
        trace = getattr(exc, "trace", None)
        if trace:
            print("route_trace=" + json.dumps(trace, sort_keys=True))
        return 1
    if args.emit_bundle:
        Path(args.emit_bundle).write_text(
            ck.dump_bundle(result["bundle"]))
    print("status=ok")
    print(f"root={result['root']}")
    print(f"bundle_digest_sha256={result['bundle_digest_sha256']}")
    print(f"rendering.token={result['rendering']['token']}")
    print("permitted_text=" + result["rendering"]["permitted_text"])
    print("route_trace=" + json.dumps(result["route_trace"],
                                      sort_keys=True))
    if not args.emit_bundle:
        print("bundle=" + json.dumps(result["bundle"], sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
