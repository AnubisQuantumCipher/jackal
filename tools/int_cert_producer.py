#!/usr/bin/env python3
"""UNTRUSTED certificate producer — JACKAL `integrate-bound-cert` lane (v1.7).

Public untrusted producer for the certified composed-integral lane, pinned in
release/MANIFEST.sha256 exactly like the seven `*_rat_producer.py` siblings.

Mirrors the shipped `bound_step` adaptive subdivision (jackal_calc.anb
fn bound_step) in exact rational arithmetic and emits a
`jackal-int-cert v1` composition artifact whose leaves embed ordinary
`jackal-eval-cert v2` evaluation certificates.  Trust lives ONLY in the
proved Lean checker (compiled `jackal_int_cert_check`, proved `parseIntCert`
+ `checkIntCert` + `int_cert_sound`); nothing this script computes is
evidence by itself, and a bare producer run is a diagnostic, not a release —
`jackal-int-cert-release` adds request-commitment and identity binding.

Engine-mirror notes (disclosed divergences, see RESEARCH_SOURCES.md D4-D6):
  * derivative chains are Lean's `Deriv.D` mirror (`DQ`), token-for-token,
    with NO `simplify_bound` interleaving (the engine simplifies between
    derivatives);
  * midpoint certificates use the EXACT rational midpoint point-interval
    [c, c] (strictly inside the engine's padded float midpoint interval;
    both satisfy the checker's containment rule);
  * leaf acceptance (width <= 9/10 * tol * h / span) is decided in exact
    rationals; the engine decides it in f64 (marginal disagreements are
    producer-side refusals, never acceptance widening);
  * subdivision midpoints are IEEE binary64 midpoints exactly like the
    engine (float (a+b)/2), so tree shapes match the engine's on the
    shared fragment;
  * budget (60000 entry-check) and depth (60) mirrors are exact.

Refusals (exit 1, stderr `REFUSE reason=<class> detail=...`):
  unsupported-expression, invalid-domain, invalid-tolerance,
  budget-exhausted, depth-exhausted, float-resolution, cannot-certify,
  tolerance-unmet.

Runnable under `python3 -O`.
"""

from __future__ import annotations

import argparse
import base64
import copy
import hashlib
import math
import sys
from fractions import Fraction

SCHEMA = "jackal-int-cert v1"
EMBEDDED_SCHEMA = "jackal-eval-cert v2"
MODEL = "jackal-iv-model-v1"
CHECKER_PIN = "jackal-iv-bound-step-v1"
STATUS = "bounded"
BUDGET = 60000
DEPTH_CAP = 60

EPS_Q = Fraction(1, 10 ** 15)
TAU_Q = Fraction(1, 10 ** 300)


class Refusal(Exception):
    def __init__(self, cls: str, detail: str) -> None:
        super().__init__(f"{cls}: {detail}")
        self.cls = cls
        self.detail = detail


# ---------------------------------------------------------------------------
# canonical rationals
# ---------------------------------------------------------------------------

def rat_str(q: Fraction) -> str:
    q = Fraction(q)
    if q.denominator == 1:
        return str(q.numerator)
    return f"{q.numerator}/{q.denominator}"


def parse_canonical_rat(text: str) -> Fraction:
    t = text.strip()
    try:
        if "/" in t:
            num, den = t.split("/", 1)
            f = Fraction(int(num), int(den))
        elif "^" in t:  # convenience for CLI like 1/10^40 handled below
            raise ValueError
        else:
            f = Fraction(int(t))
    except (ValueError, ZeroDivisionError) as exc:
        raise Refusal("invalid-tolerance", f"non-canonical rational {text!r}") from exc
    return f


def parse_cli_rat(text: str) -> Fraction:
    """CLI-side rational: canonical p/q plus the 1/10^K convenience."""
    t = text.strip()
    if "^" in t and t.startswith("1/"):
        base, exp = t[2:].split("^", 1)
        return Fraction(1, int(base) ** int(exp))
    return parse_canonical_rat(t)


def pad_q(v: Fraction) -> Fraction:
    return EPS_Q * abs(v) + TAU_Q


def pad_lo(v: Fraction) -> Fraction:
    return v - pad_q(v)


def pad_hi(v: Fraction) -> Fraction:
    return v + pad_q(v)


def f64(v: Fraction) -> Fraction:
    """Correctly-rounded binary64 of an exact rational, as an exact rational."""
    f = float(v)  # CPython: correctly rounded true division of big ints
    if not math.isfinite(f):
        raise Refusal("cannot-certify", "non-finite value in interval arithmetic")
    return Fraction(f)


# ---------------------------------------------------------------------------
# expression parser (engine grammar, certified fragment)
# ---------------------------------------------------------------------------

FUNCS = ("sin", "cos")


def tokenize(src: str) -> list[str]:
    toks: list[str] = []
    i = 0
    while i < len(src):
        c = src[i]
        if c.isspace():
            i += 1
            continue
        if c.isdigit():
            j = i
            while j < len(src) and (src[j].isdigit() or src[j] == "."):
                j += 1
            toks.append(src[i:j])
            i = j
            continue
        if c.isalpha():
            j = i
            while j < len(src) and src[j].isalnum():
                j += 1
            toks.append(src[i:j])
            i = j
            continue
        if c in "+-*/^()%,":
            toks.append(c)
            i += 1
            continue
        raise Refusal("unsupported-expression", f"bad character {c!r}")
    return toks


class Parser:
    def __init__(self, toks: list[str]) -> None:
        self.toks = toks
        self.i = 0

    def peek(self) -> str | None:
        return self.toks[self.i] if self.i < len(self.toks) else None

    def next(self) -> str:
        t = self.peek()
        if t is None:
            raise Refusal("unsupported-expression", "unexpected end of input")
        self.i += 1
        return t

    def parse(self):
        e = self.expr()
        if self.peek() is not None:
            raise Refusal("unsupported-expression", f"trailing tokens at {self.peek()!r}")
        return e

    def expr(self):
        e = self.term()
        while self.peek() in ("+", "-"):
            op = self.next()
            r = self.term()
            e = ("add" if op == "+" else "sub", e, r)
        return e

    def term(self):
        e = self.unary()
        while self.peek() in ("*", "/", "%"):
            op = self.next()
            if op == "%":
                raise Refusal("unsupported-expression", "'%' outside certified fragment")
            r = self.unary()
            e = ("mul" if op == "*" else "div", e, r)
        return e

    def unary(self):
        if self.peek() == "-":
            self.next()
            return ("neg", self.unary())
        if self.peek() == "+":
            self.next()
            return self.unary()
        return self.power()

    def power(self):
        base = self.atom()
        if self.peek() == "^":
            self.next()
            exp = self.unary()  # right-assoc, unary exponent
            return ("pow", base, exp)
        return base

    def atom(self):
        t = self.next()
        if t == "(":
            e = self.expr()
            if self.next() != ")":
                raise Refusal("unsupported-expression", "unclosed parenthesis")
            return e
        if t.isdigit():
            if "." in t:
                raise Refusal("unsupported-expression",
                              f"non-integer literal {t!r} outside certified fragment")
            return ("num", Fraction(int(t)), t)
        if t and t[0].isdigit():
            if "." in t:
                raise Refusal("unsupported-expression",
                              f"non-integer literal {t!r} outside certified fragment")
            return ("num", Fraction(int(t)), t)
        if t == "x":
            return ("var", "x")
        if t in FUNCS or t in ("abs", "floor", "ceil", "round", "trunc"):
            if self.next() != "(":
                raise Refusal("unsupported-expression", f"{t} needs parentheses")
            u = self.expr()
            if self.next() != ")":
                raise Refusal("unsupported-expression", "unclosed call")
            return ("call1", t, u)
        raise Refusal("unsupported-expression", f"unsupported token {t!r}")


# ---------------------------------------------------------------------------
# Lean-D mirror (token reuse, exactly Deriv.D / IntCert.DQ)
# ---------------------------------------------------------------------------

DBAD = ("div", ("num", Fraction(1), "1"), ("num", Fraction(0), "0"))


def dq(e):
    tag = e[0]
    if tag == "num":
        return ("num", Fraction(0), "0")
    if tag == "var":
        return ("num", Fraction(1), "1") if e[1] == "x" else ("num", Fraction(0), "0")
    if tag == "neg":
        return ("neg", dq(e[1]))
    if tag == "add":
        return ("add", dq(e[1]), dq(e[2]))
    if tag == "sub":
        return ("sub", dq(e[1]), dq(e[2]))
    if tag == "mul":
        l, r = e[1], e[2]
        return ("add", ("mul", dq(l), r), ("mul", l, dq(r)))
    if tag == "div":
        l, r = e[1], e[2]
        return ("div", ("sub", ("mul", dq(l), r), ("mul", l, dq(r))),
                ("pow", r, ("num", Fraction(2), "2")))
    if tag == "pow" and e[2][0] == "num":
        b, (_, c, t) = e[1], e[2]
        return ("mul", ("mul", ("num", c, t), ("pow", b, ("num", c - 1, t))), dq(b))
    if tag == "call1":
        name, u = e[1], e[2]
        if name == "sin":
            return ("mul", ("call1", "cos", u), dq(u))
        if name == "cos":
            return ("neg", ("mul", ("call1", "sin", u), dq(u)))
        return DBAD
    return DBAD


def smooth_ok(e) -> bool:
    """Certified-fragment mirror of the engine's ast_smooth_ok: every node has a
    D rule (the D-chain never hits DBAD)."""
    tag = e[0]
    if tag in ("num", "var"):
        return True
    if tag == "neg":
        return smooth_ok(e[1])
    if tag in ("add", "sub", "mul", "div"):
        return smooth_ok(e[1]) and smooth_ok(e[2])
    if tag == "pow":
        return e[2][0] == "num" and smooth_ok(e[1])
    if tag == "call1":
        return e[1] in ("sin", "cos") and smooth_ok(e[2])
    return False


def ast_size(e) -> int:
    tag = e[0]
    if tag in ("num", "var"):
        return 1
    if tag == "neg":
        return 1 + ast_size(e[1])
    if tag == "call1":
        return 1 + ast_size(e[2])
    return 1 + ast_size(e[1]) + ast_size(e[2])


def sexp(e) -> str:
    tag = e[0]
    if tag == "num":
        return f"(num {e[2]})"
    if tag == "var":
        return f"(var {e[1]})"
    if tag == "neg":
        return f"(neg {sexp(e[1])})"
    if tag in ("add", "sub", "mul", "div"):
        return f"({tag} {sexp(e[1])} {sexp(e[2])})"
    if tag == "pow":
        return f"(pow {sexp(e[1])} {sexp(e[2])})"
    if tag == "call1":
        return f"(call {e[1]} {sexp(e[2])})"
    raise Refusal("unsupported-expression", f"sexp of {tag}")


# ---------------------------------------------------------------------------
# exact-ℚ ieval mirror emitting jackal-eval-cert v2 nodes
# ---------------------------------------------------------------------------

def sin_lo_q(m: Fraction) -> Fraction:
    return (m - m ** 3 / 6) - abs(m) ** 5 / 100


def sin_hi_q(m: Fraction) -> Fraction:
    return (m - m ** 3 / 6) + abs(m) ** 5 / 100


def cos_lo_q(m: Fraction) -> Fraction:
    return (1 - m ** 2 / 2) - m ** 4 * Fraction(5, 96)


def cos_hi_q(m: Fraction) -> Fraction:
    return (1 - m ** 2 / 2) + m ** 4 * Fraction(5, 96)


class CertRun:
    """One exact-ℚ evaluation of an expression over [xlo, xhi], recorded as
    v2 certificate nodes (children strictly below parents)."""

    def __init__(self, xlo: Fraction, xhi: Fraction) -> None:
        self.xlo = xlo
        self.xhi = xhi
        self.lines: list[str] = []
        self.next_id = 0

    def emit(self, op: str, children: list[int], out: tuple[Fraction, Fraction],
             extras: str = "") -> tuple[int, Fraction, Fraction]:
        nid = self.next_id
        self.next_id += 1
        ch = ",".join(str(c) for c in children)
        line = (f"node {nid} {op} children[{ch}] "
                f"out[{rat_str(out[0])},{rat_str(out[1])}]")
        if extras:
            line += " " + extras
        self.lines.append(line)
        return nid, out[0], out[1]

    def eval(self, e) -> tuple[int, Fraction, Fraction]:
        tag = e[0]
        if tag == "num":
            _, v, t = e
            if v.denominator != 1:
                raise Refusal("unsupported-expression",
                              f"non-integer literal value {v}")
            return self.emit("num_exact", [], (v, v),
                             f"val {rat_str(v)} name {t}")
        if tag == "var":
            return self.emit("var", [], (self.xlo, self.xhi), "name x")
        if tag == "neg":
            c, l, u = self.eval(e[1])
            return self.emit("neg", [c], (-u, -l))
        if tag in ("add", "sub"):
            c0, l1, u1 = self.eval(e[1])
            c1, l2, u2 = self.eval(e[2])
            if tag == "add":
                flo, fhi = f64(l1 + l2), f64(u1 + u2)
            else:
                flo, fhi = f64(l1 - u2), f64(u1 - l2)
            return self.emit(tag, [c0, c1], (pad_lo(flo), pad_hi(fhi)),
                             f"f[{rat_str(flo)},{rat_str(fhi)}]")
        if tag == "mul":
            c0, l1, u1 = self.eval(e[1])
            c1, l2, u2 = self.eval(e[2])
            ps = [f64(l1 * l2), f64(l1 * u2), f64(u1 * l2), f64(u1 * u2)]
            return self.emit("mul", [c0, c1],
                             (pad_lo(min(ps)), pad_hi(max(ps))),
                             "p[" + ",".join(rat_str(p) for p in ps) + "]")
        if tag == "div":
            c0, l1, u1 = self.eval(e[1])
            c1, l2, u2 = self.eval(e[2])
            if l2 > 0:
                den = 1
            elif u2 < 0:
                den = -1
            else:
                raise Refusal("cannot-certify",
                              "denominator interval contains zero")
            ps = [f64(l1 / l2), f64(l1 / u2), f64(u1 / l2), f64(u1 / u2)]
            return self.emit("div", [c0, c1],
                             (pad_lo(min(ps)), pad_hi(max(ps))),
                             "p[" + ",".join(rat_str(p) for p in ps) + "]"
                             + f" den {den}")
        if tag == "pow":
            if e[2][0] != "num" or e[2][1].denominator != 1:
                raise Refusal("unsupported-expression", "non-integer exponent")
            n = e[2][1].numerator
            name = e[2][2]
            if n < 0 or n > 4096:
                raise Refusal("unsupported-expression",
                              f"exponent {n} outside certified fragment")
            c0, l, u = self.eval(e[1])
            if n == 0:
                return self.emit("powZero", [c0], (Fraction(1), Fraction(1)),
                                 f"n 0 name {name}")
            if n % 2 == 0:
                mig = Fraction(0) if (l <= 0 <= u) else min(abs(l), abs(u))
                mag = max(abs(l), abs(u))
                flo, fhi = f64(mig ** n), f64(mag ** n)
                return self.emit("powEvenPos", [c0],
                                 (pad_lo(flo), pad_hi(fhi)),
                                 f"f[{rat_str(flo)},{rat_str(fhi)}]"
                                 f" n {n} name {name}")
            flo, fhi = f64(l ** n), f64(u ** n)
            return self.emit("powOddPos", [c0], (pad_lo(flo), pad_hi(fhi)),
                             f"f[{rat_str(flo)},{rat_str(fhi)}] n {n} name {name}")
        if tag == "call1":
            name, u = e[1], e[2]
            if name == "abs":
                c0, l, uu = self.eval(u)
                if l >= 0:
                    out = (l, uu)
                elif uu <= 0:
                    out = (-uu, -l)
                else:
                    out = (Fraction(0), max(-l, uu))
                return self.emit("abs", [c0], out)
            if name in ("sin", "cos"):
                c0, l, uu = self.eval(u)
                m = (l + uu) / 2
                hw = (uu - l) / 2
                if abs(m) <= 1:
                    if name == "sin":
                        out = (sin_lo_q(m) - hw, sin_hi_q(m) + hw)
                    else:
                        out = (cos_lo_q(m) - hw, cos_hi_q(m) + hw)
                    return self.emit(f"{name}_rat", [c0], out)
                return self.emit(name, [c0], (Fraction(-1), Fraction(1)))
            raise Refusal("unsupported-expression",
                          f"call {name!r} outside certified fragment")
        raise Refusal("unsupported-expression", f"node {tag!r}")


def eval_interval(e, xlo: Fraction, xhi: Fraction) -> tuple[Fraction, Fraction]:
    """Interval-only evaluation (same arithmetic as CertRun, no emission)."""
    run = CertRun(xlo, xhi)
    _, lo, hi = run.eval(e)
    return lo, hi


def emit_eval_cert(e, xlo: Fraction, xhi: Fraction) -> dict:
    """Full embedded certificate for one evaluation."""
    run = CertRun(xlo, xhi)
    root, lo, hi = run.eval(e)
    header = [
        f"{EMBEDDED_SCHEMA}",
        f"model {MODEL}",
        "exe ",
        f"status {STATUS}",
        f"expr {sexp(e)}",
        "source ",
        f"input {rat_str(xlo)} {rat_str(xhi)}",
        f"root {root}",
        f"output {rat_str(lo)} {rat_str(hi)}",
    ]
    text = "\n".join(header + run.lines + ["end"]) + "\n"
    return {"text": text, "lo": lo, "hi": hi, "input_lo": xlo, "input_hi": xhi}


# ---------------------------------------------------------------------------
# bound_step mirror
# ---------------------------------------------------------------------------

class BoundCtx:
    def __init__(self, chain, degree: int, span: Fraction, tol: Fraction) -> None:
        self.chain = chain          # [f, f1, f2, f3, f4]
        self.degree = degree
        self.span = span
        self.tol = tol
        self.nodes_counter = 0
        self.tree: list[dict] = []
        self.next_id = 0

    def fresh_id(self) -> int:
        i = self.next_id
        self.next_id += 1
        return i


def try_eval(e, a: Fraction, b: Fraction):
    try:
        return eval_interval(e, a, b)
    except Refusal as r:
        return r


def bound_step_mirror(ctx: BoundCtx, a: Fraction, b: Fraction, depth: int) -> dict:
    """Returns the tree node dict for [a, b]; raises Refusal mirroring the
    engine's fail-closed panics."""
    if ctx.nodes_counter > BUDGET:
        raise Refusal("budget-exhausted",
                      "subdivision budget (60000 subintervals) exhausted")
    f = ctx.chain[0]
    F = try_eval(f, a, b)
    if depth > DEPTH_CAP:
        if isinstance(F, Refusal):
            raise Refusal("cannot-certify",
                          f"{F.detail} persists after 60 subdivision levels")
        raise Refusal("depth-exhausted",
                      "subdivision depth (60) exhausted before certifying")
    h = b - a
    local_tol = Fraction(9, 10) * ctx.tol * h / ctx.span
    kind = None
    lo = hi = None
    if not isinstance(F, Refusal):
        flo, fhi = F
        lo, hi = h * flo, h * fhi        # range ideal
        kind = "range"
        if ctx.degree >= 2:
            c = (a + b) / 2
            Fm = try_eval(f, c, c)
            F1 = try_eval(ctx.chain[1], a, b)
            F2 = try_eval(ctx.chain[2], a, b)
            if not any(isinstance(v, Refusal) for v in (Fm, F1, F2)):
                tried4 = False
                if ctx.degree >= 4:
                    F2m = try_eval(ctx.chain[2], c, c)
                    F3 = try_eval(ctx.chain[3], a, b)
                    F4 = try_eval(ctx.chain[4], a, b)
                    if not any(isinstance(v, Refusal) for v in (F2m, F3, F4)):
                        t4lo = h * Fm[0] + h ** 3 / 24 * F2m[0] \
                            + h ** 5 / 1920 * F4[0]
                        t4hi = h * Fm[1] + h ** 3 / 24 * F2m[1] \
                            + h ** 5 / 1920 * F4[1]
                        lo, hi = max(lo, t4lo), min(hi, t4hi)
                        kind = "taylor4"
                        tried4 = True
                if not tried4:
                    t2lo = h * Fm[0] + h ** 3 / 24 * F2[0]
                    t2hi = h * Fm[1] + h ** 3 / 24 * F2[1]
                    lo, hi = max(lo, t2lo), min(hi, t2hi)
                    kind = "taylor2"
        if hi - lo <= local_tol:
            ctx.nodes_counter += 1
            # certificates are emitted in a second pass only after the whole
            # walk and the final width check succeed (refusal paths stay fast)
            node = {"id": ctx.fresh_id(), "kind": kind, "a": a, "b": b,
                    "lo": lo, "hi": hi, "children": [], "certs": []}
            ctx.tree.append(node)
            return node
    # subdivide at the engine's float midpoint
    mid_f = (float(a) + float(b)) / 2.0
    mid = Fraction(mid_f)
    if mid <= a or mid >= b:
        if isinstance(F, Refusal):
            raise Refusal("cannot-certify",
                          f"{F.detail} persists at float64 resolution")
        raise Refusal("float-resolution",
                      "cannot subdivide below float64 resolution")
    ctx.nodes_counter += 1
    left = bound_step_mirror(ctx, a, mid, depth + 1)
    right = bound_step_mirror(ctx, mid, b, depth + 1)
    node = {"id": ctx.fresh_id(), "kind": "split", "a": a, "b": b,
            "lo": left["lo"] + right["lo"], "hi": left["hi"] + right["hi"],
            "children": [left["id"], right["id"]], "certs": []}
    ctx.tree.append(node)
    return node


def build_leaf_certs(ctx: BoundCtx, kind: str, a: Fraction, b: Fraction) -> list[dict]:
    f, f1, f2, f3, f4 = ctx.chain
    c = (a + b) / 2
    if kind == "range":
        roles = [("f", f, a, b)]
    elif kind == "taylor2":
        roles = [("f", f, a, b), ("f1", f1, a, b), ("f2", f2, a, b),
                 ("fm", f, c, c)]
    elif kind == "taylor4":
        roles = [("f", f, a, b), ("f1", f1, a, b), ("f2", f2, a, b),
                 ("f3", f3, a, b), ("f4", f4, a, b), ("fm", f, c, c),
                 ("f2m", f2, c, c)]
    else:
        raise Refusal("cannot-certify", f"internal: bad kind {kind}")
    out = []
    for role, expr, xlo, xhi in roles:
        cert = emit_eval_cert(expr, xlo, xhi)
        cert["role"] = role
        out.append(cert)
    return out


# ---------------------------------------------------------------------------
# artifact assembly
# ---------------------------------------------------------------------------

def request_commitment_b64(expr: str, lo: str, hi: str, tol: str) -> str:
    """Injective request commitment, scheme `jackal-req-v3-int-cert`.

    Byte-length framing identical to the gaussian scheme in
    tools/formal_receipt.py; the release binder and receipt verifier
    recompute this exact construction over the CANONICAL rationals.
    """
    def framed(part: str) -> bytes:
        raw = part.encode("utf-8")
        return str(len(raw)).encode() + b":" + raw
    framing = (b"jackal-req-v3-int-cert\x00" + framed("integrate-bound-cert")
               + b"|" + framed(expr) + b"|" + framed(lo) + b"|" + framed(hi)
               + b"|" + framed(tol))
    return base64.b64encode(
        hashlib.sha256(framing).hexdigest().encode("ascii")).decode("ascii")


def build(expr_src: str, lo_text: str, hi_text: str, tol_text: str,
          degree_cap: int | None = None) -> dict:
    """Run the mirror; return the artifact as a manipulable dict (untrusted
    producer API used by the test harness for surgical poisons)."""
    a = parse_cli_rat(lo_text)
    b = parse_cli_rat(hi_text)
    tol = parse_cli_rat(tol_text)
    if tol <= 0:
        raise Refusal("invalid-tolerance", "tolerance must be positive")
    if a >= b:
        raise Refusal("invalid-domain", "requires lo < hi")
    ast = Parser(tokenize(expr_src)).parse()
    # engine degree policy mirror (ast_smooth_ok + size caps), plus the
    # explicit test knob --degree-cap (documented producer-side heuristic)
    degree = 0
    chain = [ast, DBAD, DBAD, DBAD, DBAD]
    if smooth_ok(ast):
        d1 = dq(ast)
        d2 = dq(d1)
        chain = [ast, d1, d2, DBAD, DBAD]
        if ast_size(d2) <= 20000:
            degree = 2
            d3 = dq(d2)
            d4 = dq(d3)
            chain = [ast, d1, d2, d3, d4]
            if ast_size(d4) <= 20000:
                degree = 4
    if degree_cap is not None:
        degree = min(degree, degree_cap)
    ctx = BoundCtx(chain, degree, b - a, tol)
    root = bound_step_mirror(ctx, a, b, 0)
    out_lo, out_hi = pad_lo(root["lo"]), pad_hi(root["hi"])
    if out_hi - out_lo > tol:
        raise Refusal("tolerance-unmet",
                      f"achieved width {float(out_hi - out_lo)} exceeds "
                      f"tolerance {float(tol)} after accumulation padding")
    for node in ctx.tree:
        if node["kind"] != "split":
            node["certs"] = build_leaf_certs(ctx, node["kind"],
                                             node["a"], node["b"])
    return {
        "_expr_src": expr_src,
        "schema": SCHEMA,
        "model": MODEL,
        "checker": CHECKER_PIN,
        "producer": producer_sha256(),
        "status": STATUS,
        "expr_sexp": sexp(ast),
        "source": request_commitment_b64(expr_src, lo_text, hi_text, tol_text),
        "req_lo": a, "req_hi": b, "tol": tol,
        "degree": degree,
        "root": root["id"],
        "out_lo": out_lo, "out_hi": out_hi,
        "tree": sorted(ctx.tree, key=lambda t: t["id"]),
    }


def emit(art: dict) -> str:
    """Serialize an artifact dict — NO validation (untrusted emitter)."""
    lines = [
        art["schema"],
        f"model {art['model']}",
        f"checker {art['checker']}",
        f"producer {art['producer']}",
        f"status {art['status']}",
        f"expr {art['expr_sexp']}",
        f"source {art['source']}",
        f"request {rat_str(art['req_lo'])} {rat_str(art['req_hi'])} "
        f"{rat_str(art['tol'])}",
        f"degree {art['degree']}",
        f"root {art['root']}",
        f"output {rat_str(art['out_lo'])} {rat_str(art['out_hi'])}",
    ]
    for t in art["tree"]:
        ch = ",".join(str(c) for c in t["children"])
        lines.append(
            f"tree {t['id']} {t['kind']} dom[{rat_str(t['a'])},{rat_str(t['b'])}]"
            f" out[{rat_str(t['lo'])},{rat_str(t['hi'])}] children[{ch}]")
    for t in art["tree"]:
        for cert in t["certs"]:
            block = cert["text"].rstrip("\n").split("\n")
            lines.append(f"cert {t['id']} {cert['role']} lines {len(block)}")
            lines.extend(block)
    lines.append("end")
    return "\n".join(lines) + "\n"


def producer_sha256() -> str:
    try:
        with open(__file__, "rb") as fh:
            return hashlib.sha256(fh.read()).hexdigest()
    except OSError:
        return ""


# ---------------------------------------------------------------------------
# harness helpers (poison surgery on the artifact dict)
# ---------------------------------------------------------------------------

def clone(art: dict) -> dict:
    return copy.deepcopy(art)


def leaf(art: dict) -> dict:
    for t in art["tree"]:
        if t["kind"] != "split":
            return t
    raise KeyError("no leaf")


def first_split(art: dict) -> dict:
    for t in art["tree"]:
        if t["kind"] == "split":
            return t
    raise KeyError("no split")


def poison_partition(art: dict, mode: str) -> dict:
    """Shrink/grow the LEFT child's domain and regenerate its certificates and
    claim so the child is internally consistent and only the partition breaks.
    mode='gap': left.b moves left; mode='overlap': left.b moves right."""
    p = clone(art)
    sp = first_split(p)
    lid = sp["children"][0]
    lnode = next(t for t in p["tree"] if t["id"] == lid)
    if lnode["kind"] == "split":
        raise KeyError("left child is not a leaf; pick a deeper artifact")
    a, b = lnode["a"], lnode["b"]
    shift = (b - a) / 4
    new_b = b - shift if mode == "gap" else b + shift
    _rebuild_leaf(p, lnode, a, new_b)
    return p


def poison_orphan(art: dict) -> dict:
    """Append a well-formed but unreachable extra leaf node."""
    p = clone(art)
    template = leaf(p)
    orphan = copy.deepcopy(template)
    orphan["id"] = max(t["id"] for t in p["tree"]) + 1
    # keep the header root pointing at the ORIGINAL root: orphan is unreachable
    p["tree"].append(orphan)
    return p


def _rebuild_leaf(art: dict, node: dict, a: Fraction, b: Fraction) -> None:
    """Recompute a leaf node in place for domain [a, b] (internally
    consistent: certs, claim, kind preserved when possible)."""
    expr_src = art.get("_expr_src")
    if expr_src is None:
        raise KeyError("artifact was not built by build(); missing _expr_src")
    ast = Parser(tokenize(expr_src)).parse()
    d1 = dq(ast); d2 = dq(d1); d3 = dq(d2); d4 = dq(d3)
    chain = [ast, d1, d2, d3, d4]
    ctx = BoundCtx(chain, art["degree"], art["req_hi"] - art["req_lo"],
                   art["tol"])
    kind = node["kind"]
    h = b - a
    F = eval_interval(ast, a, b)
    lo, hi = h * F[0], h * F[1]
    if kind in ("taylor2", "taylor4"):
        c = (a + b) / 2
        Fm = eval_interval(ast, c, c)
        if kind == "taylor2":
            F2 = eval_interval(d2, a, b)
            lo = max(lo, h * Fm[0] + h ** 3 / 24 * F2[0])
            hi = min(hi, h * Fm[1] + h ** 3 / 24 * F2[1])
        else:
            F2m = eval_interval(d2, c, c)
            F4 = eval_interval(d4, a, b)
            lo = max(lo, h * Fm[0] + h ** 3 / 24 * F2m[0]
                     + h ** 5 / 1920 * F4[0])
            hi = min(hi, h * Fm[1] + h ** 3 / 24 * F2m[1]
                     + h ** 5 / 1920 * F4[1])
    node["a"], node["b"] = a, b
    node["lo"], node["hi"] = lo, hi
    node["certs"] = build_leaf_certs(ctx, kind, a, b)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="int_cert_producer",
                                 description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    em = sub.add_parser("emit")
    em.add_argument("--expression", required=True)
    em.add_argument("--lower", required=True)
    em.add_argument("--upper", required=True)
    em.add_argument("--tolerance", required=True)
    em.add_argument("--degree-cap", type=int, default=None)
    em.add_argument("--out", default=None)
    args = ap.parse_args(argv)
    try:
        art = build(args.expression, args.lower, args.upper, args.tolerance,
                    degree_cap=args.degree_cap)
        text = emit(art)
    except Refusal as r:
        print(f"REFUSE reason={r.cls} detail={r.detail}", file=sys.stderr)
        return 1
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text)
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
