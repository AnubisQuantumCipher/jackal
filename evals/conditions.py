"""Five tool-condition runners for the JACKAL evaluation harness.

Each runner accepts (Problem, ModelFn) and returns an Observation.

    ModelFn signature:
        def model_fn(prompt: str, system: str | None = None,
                     max_tokens: int = 256) -> ModelReply
        where ModelReply is a dataclass with .text, .tokens_in, .tokens_out,
        .latency_ms, .stub (bool).

Conditions:
    1. model_only              — single-shot; no tools
    2. model_dc                — model may emit <DC>...</DC>, harness runs `dc`
    3. model_python            — model may emit <PYTHON>...</PYTHON>, sandboxed
    4. model_jackal            — model may emit <JACKAL>subcmd args</JACKAL>
    5. model_jackal_verified   — model_jackal + auto-run of jackal_verify_receipt
                                  for any range/gaussian tool result

In OBSERVED-STUB mode (no live model) the "model" is a deterministic stub
that always requests the appropriate tool for the category; the tool call
itself is real. Rows produced this way are flagged in metrics.observed_stub.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from evals.metrics import Observation


REPO_ROOT = Path(__file__).resolve().parent.parent
JACKAL_BIN = str(REPO_ROOT / "jackal-native")
HERMES_BIN = str(REPO_ROOT / "plugin" / "hermes" / "jackal_hermes")


@dataclass
class ModelReply:
    text: str
    tokens_in: int = 0
    tokens_out: int = 0
    latency_ms: int = 0
    stub: bool = False


# --------------------------------------------------------------------------- #
# Tool tag extraction                                                          #
# --------------------------------------------------------------------------- #
_RE_DC = re.compile(r"<DC>\s*(.*?)\s*</DC>", re.DOTALL)
_RE_PY = re.compile(r"<PYTHON>\s*(.*?)\s*</PYTHON>", re.DOTALL)
_RE_JK = re.compile(r"<JACKAL>\s*(.*?)\s*</JACKAL>", re.DOTALL)
_RE_JK_RANGE = re.compile(
    r"<JACKAL_RANGE\s+expr=\"(.*?)\"\s+lo=\"(.*?)\"\s+hi=\"(.*?)\"\s*/?>", re.DOTALL
)
_RE_ANSWER = re.compile(r"<ANSWER>\s*(.*?)\s*</ANSWER>", re.DOTALL)


def _extract_answer(text: str) -> str:
    """Pick an answer out of a model reply.

    Priority:
        1. LAST <ANSWER>...</ANSWER> block (models self-correct; the last one wins)
        2. last non-empty line
    """
    matches = _RE_ANSWER.findall(text)
    if matches:
        return matches[-1].strip()
    for line in reversed(text.strip().splitlines()):
        s = line.strip()
        if s and not s.startswith("<"):
            return s
    return text.strip()


def _guess_status(text: str, tool_used: list[str], verified: bool | None) -> str:
    lower = text.lower()
    if any(w in lower for w in ("refuse", "undefined", "cannot", "not defined", "no such")):
        if "refused" in lower or lower.strip() == "refused":
            return "refused"
    if verified is True:
        return "formal-bounded"
    if any(t.startswith("jackal:range") or t.startswith("jackal:gauss") for t in tool_used):
        return "bounded"
    if "jackal:big-add" in tool_used or "jackal:big-mul" in tool_used or "jackal:rat" in tool_used or "jackal:eval-exact" in tool_used or "python" in tool_used or "dc" in tool_used:
        return "exact"
    if any(t.startswith("jackal:") for t in tool_used):
        return "estimated"
    if "exact" in lower or "certified" in lower:
        return "exact"
    return "estimated"


# --------------------------------------------------------------------------- #
# Real tool executors                                                          #
# --------------------------------------------------------------------------- #
def run_dc(expr: str, timeout: float = 5.0) -> tuple[str, str | None]:
    """Return (stdout, err). expr should end with a `p` (print) or we add one."""
    if "p" not in expr:
        expr = expr.strip() + " p"
    try:
        r = subprocess.run(
            ["dc"], input=expr.encode(), capture_output=True, timeout=timeout
        )
        return r.stdout.decode(errors="replace").strip(), None if r.returncode == 0 else r.stderr.decode(errors="replace")[:200]
    except Exception as e:  # noqa: BLE001
        return "", f"dc-error: {e}"


def run_python(code: str, timeout: float = 5.0) -> tuple[str, str | None]:
    """Run a snippet through `python3 -I` with no network/env, capturing stdout."""
    try:
        r = subprocess.run(
            ["python3", "-I", "-S", "-B", "-c", code],
            capture_output=True, timeout=timeout,
            env={"PATH": "/usr/bin:/bin"},
        )
        out = r.stdout.decode(errors="replace").strip()
        err = None if r.returncode == 0 else r.stderr.decode(errors="replace")[:300]
        return out, err
    except subprocess.TimeoutExpired:
        return "", "python-timeout"
    except Exception as e:  # noqa: BLE001
        return "", f"python-error: {e}"


def run_jackal(argv: list[str], timeout: float = 10.0) -> tuple[str, str | None]:
    try:
        r = subprocess.run(
            [JACKAL_BIN, *argv], capture_output=True, timeout=timeout
        )
        out = r.stdout.decode(errors="replace").strip()
        err = None if r.returncode == 0 else r.stderr.decode(errors="replace")[:300]
        return out, err
    except Exception as e:  # noqa: BLE001
        return "", f"jackal-error: {e}"


def run_hermes(tool: str, args: dict, timeout: float = 15.0) -> tuple[dict, str | None]:
    try:
        r = subprocess.run(
            [HERMES_BIN, "call", tool, json.dumps(args)],
            capture_output=True, timeout=timeout,
        )
        out = r.stdout.decode(errors="replace")
        try:
            data = json.loads(out) if out.strip() else {}
        except json.JSONDecodeError:
            data = {"raw": out}
        err = None if r.returncode == 0 else r.stderr.decode(errors="replace")[:300]
        return data, err
    except Exception as e:  # noqa: BLE001
        return {}, f"hermes-error: {e}"


# --------------------------------------------------------------------------- #
# Prompt scaffolds per condition                                               #
# --------------------------------------------------------------------------- #
SYS_ONLY = (
    "You are a careful calculator. Reply concisely. If the answer is undefined, "
    "reply exactly the word 'refused'. Wrap your final answer in <ANSWER>...</ANSWER>."
)

SYS_DC = (
    "You are a calculator that may call the Unix `dc` utility (reverse-Polish arbitrary-precision). "
    "If you would benefit from `dc`, emit ONE block like:\n"
    "  <DC>10 3 * p</DC>\n"
    "The harness will run it and inject the stdout as <DC_OUT>...</DC_OUT>. "
    "You will then produce a final answer wrapped in <ANSWER>...</ANSWER>. "
    "If undefined, reply <ANSWER>refused</ANSWER>."
)

SYS_PY = (
    "You are a calculator that may call Python via <PYTHON>...</PYTHON>. "
    "The block runs in a sandboxed `python3 -I -S`. Only stdout is captured; "
    "you MUST end your Python with a print of the answer. Then wrap the final "
    "answer in <ANSWER>...</ANSWER>. Undefined -> <ANSWER>refused</ANSWER>."
)

SYS_JK = (
    "You are a calculator with access to JACKAL, a claim-aware STEM engine (./jackal-native). "
    "Available subcommands include: big-add A B, big-mul A B, big-pow A B, rat 'EXPR', "
    "eval 'EXPR', integrate 'EXPR' A B N, derivative 'EXPR' X H, add A B, mul A B, "
    "sqrt A, pow A B. "
    "If a subcommand would help, emit ONE block like:\n"
    "  <JACKAL>big-add 1234567890 987654321</JACKAL>\n"
    "The harness runs it and injects the stdout as <JACKAL_OUT>...</JACKAL_OUT>. "
    "Then wrap final answer in <ANSWER>...</ANSWER>. Undefined -> <ANSWER>refused</ANSWER>."
)

SYS_JK_V = (
    SYS_JK
    + "\nAdditionally, for enclosure claims you MAY emit a formal-range request:\n"
    "  <JACKAL_RANGE expr=\"x^2\" lo=\"0\" hi=\"1\"/>\n"
    "The harness runs jackal_range_bound AND jackal_verify_receipt, and injects a JSON "
    "summary as <JACKAL_VERIFY>...</JACKAL_VERIFY>. Only claim 'exact' or 'certified' "
    "if the verifier returned status=verified."
)


# --------------------------------------------------------------------------- #
# STUB model — used when no live model is available                            #
# --------------------------------------------------------------------------- #
def _stub_reply(problem, condition: str) -> ModelReply:
    """Deterministic tool-request generator so we can still exercise the tool
    call side of the harness honestly when the API isn't available."""
    cat = problem.category
    md = problem.metadata

    if condition == "model_only":
        # no live model -> emit an explicit refusal so it's obvious in the report
        return ModelReply(text="<ANSWER>skipped-no-api-key</ANSWER>", stub=True)

    if condition == "model_dc":
        if cat == "arith":
            op = md.get("op")
            # rebuild expression from prompt
            m = re.search(r"Compute exactly:\s*(.*?)\.", problem.prompt)
            expr_txt = m.group(1) if m else ""
            if op == "add":
                a, b = re.findall(r"\d+", expr_txt)
                return ModelReply(text=f"<DC>{a} {b} + p</DC>\n<ANSWER>@dc</ANSWER>", stub=True)
            if op == "mul":
                a, b = re.findall(r"\d+", expr_txt)
                return ModelReply(text=f"<DC>{a} {b} * p</DC>\n<ANSWER>@dc</ANSWER>", stub=True)
            if op == "pow":
                base, exp = re.findall(r"\d+", expr_txt)
                return ModelReply(text=f"<DC>{base} {exp} ^ p</DC>\n<ANSWER>@dc</ANSWER>", stub=True)
        if cat == "root":
            k = md["square"]
            return ModelReply(text=f"<DC>{k} v p</DC>\n<ANSWER>@dc</ANSWER>", stub=True)
        # dc is too weak for fractions/refusals; produce a plausible fallback
        return ModelReply(text="<ANSWER>skipped-tool-not-applicable</ANSWER>", stub=True)

    if condition == "model_python":
        return ModelReply(text=_python_stub_for(problem), stub=True)

    if condition == "model_jackal":
        return ModelReply(text=_jackal_stub_for(problem), stub=True)

    if condition == "model_jackal_verified":
        return ModelReply(text=_jackal_verified_stub_for(problem), stub=True)

    return ModelReply(text="<ANSWER>skipped</ANSWER>", stub=True)


def _python_stub_for(problem) -> str:
    cat = problem.category
    md = problem.metadata
    if cat == "arith":
        m = re.search(r"Compute exactly:\s*(.*?)\.", problem.prompt)
        expr = m.group(1)
        pyexpr = expr.replace("^", "**")
        return f"<PYTHON>print({pyexpr})</PYTHON>\n<ANSWER>@py</ANSWER>"
    if cat == "frac":
        # extract numbers
        nums = re.findall(r"-?\d+", problem.prompt)
        n1, d1, n2, d2 = nums[:4]
        op = md["op"]
        return (
            f"<PYTHON>from fractions import Fraction as F\n"
            f"r = F({n1},{d1}) {op} F({n2},{d2})\n"
            f"print(f'{{r.numerator}}/{{r.denominator}}')</PYTHON>\n<ANSWER>@py</ANSWER>"
        )
    if cat == "int":
        k, a, b = md["k"], md["a"], md["b"]
        return (
            f"<PYTHON>from fractions import Fraction as F\n"
            f"k,a,b = {k},{a},{b}\n"
            f"r = F(b)**(k+1)/(k+1) - F(a)**(k+1)/(k+1)\n"
            f"print(f'{{r.numerator}}/{{r.denominator}}' if r.denominator!=1 else r.numerator)</PYTHON>\n<ANSWER>@py</ANSWER>"
        )
    if cat == "diff":
        k, p = md["k"], md["p"]
        return f"<PYTHON>k,p = {k},{p}\nprint(k*(p**(k-1)))</PYTHON>\n<ANSWER>@py</ANSWER>"
    if cat == "sing":
        return "<ANSWER>refused</ANSWER>"
    if cat == "thr":
        nums = re.findall(r"-?\d+", problem.prompt)
        a_num, a_den, b_num, b_den = nums[:4]
        return (
            f"<PYTHON>from fractions import Fraction as F\n"
            f"print('yes' if F({a_num},{a_den})>F({b_num},{b_den}) else 'no')</PYTHON>\n<ANSWER>@py</ANSWER>"
        )
    if cat == "dec":
        a_int, b_int = md["a_int"], md["b_int"]
        return (
            f"<PYTHON>from fractions import Fraction as F\n"
            f"r = F({a_int},10)+F({b_int},10)\nprint(f'{{r.numerator}}/{{r.denominator}}')</PYTHON>\n<ANSWER>@py</ANSWER>"
        )
    if cat == "ref":
        return "<ANSWER>refused</ANSWER>"
    if cat == "unit":
        src, dst, qty = md["src"], md["dst"], md["qty"]
        from evals.corpus import UNIT_TABLE
        factor = next(f for s, d, f, _ in UNIT_TABLE if s == src and d == dst)
        return (
            f"<PYTHON>from fractions import Fraction as F\n"
            f"r = F({qty})*F({factor.numerator},{factor.denominator})\n"
            f"print(f'{{r.numerator}}/{{r.denominator}}' if r.denominator!=1 else r.numerator)</PYTHON>\n<ANSWER>@py</ANSWER>"
        )
    if cat == "root":
        k = md["square"]
        return f"<PYTHON>import math\nprint(int(math.isqrt({k})))</PYTHON>\n<ANSWER>@py</ANSWER>"
    return "<ANSWER>skipped</ANSWER>"


def _jackal_stub_for(problem) -> str:
    cat = problem.category
    md = problem.metadata
    if cat == "arith":
        op = md["op"]
        m = re.search(r"Compute exactly:\s*(.*?)\.", problem.prompt)
        expr = m.group(1)
        nums = re.findall(r"\d+", expr)
        if op == "add":
            return f"<JACKAL>big-add {nums[0]} {nums[1]}</JACKAL>\n<ANSWER>@jk</ANSWER>"
        if op == "mul":
            return f"<JACKAL>big-mul {nums[0]} {nums[1]}</JACKAL>\n<ANSWER>@jk</ANSWER>"
        if op == "pow":
            return f"<JACKAL>big-pow {nums[0]} {nums[1]}</JACKAL>\n<ANSWER>@jk</ANSWER>"
    if cat == "frac":
        nums = re.findall(r"-?\d+", problem.prompt)
        n1, d1, n2, d2 = nums[:4]
        op = md["op"]
        return f"<JACKAL>rat ({n1}/{d1}){op}({n2}/{d2})</JACKAL>\n<ANSWER>@jk-rat</ANSWER>"
    if cat == "int":
        k, a, b = md["k"], md["a"], md["b"]
        # jackal integrate is estimated only — will disagree with exact truth for k>=3 sometimes
        return f"<JACKAL>integrate x^{k} {a} {b} 200</JACKAL>\n<ANSWER>@jk-int</ANSWER>"
    if cat == "diff":
        k, p = md["k"], md["p"]
        return f"<JACKAL>derivative x^{k} {p} 0.001</JACKAL>\n<ANSWER>@jk-diff</ANSWER>"
    if cat == "sing":
        return "<ANSWER>refused</ANSWER>"
    if cat == "thr":
        # jackal-native has no direct threshold cmd; use rat to subtract and check sign
        nums = re.findall(r"-?\d+", problem.prompt)
        a_num, a_den, b_num, b_den = nums[:4]
        return f"<JACKAL>rat ({a_num}/{a_den})-({b_num}/{b_den})</JACKAL>\n<ANSWER>@jk-thr</ANSWER>"
    if cat == "dec":
        a_int, b_int = md["a_int"], md["b_int"]
        return f"<JACKAL>rat 0.{a_int}+0.{b_int}</JACKAL>\n<ANSWER>@jk-rat</ANSWER>"
    if cat == "ref":
        return "<ANSWER>refused</ANSWER>"
    if cat == "unit":
        from evals.corpus import UNIT_TABLE
        src, dst, qty = md["src"], md["dst"], md["qty"]
        factor = next(f for s, d, f, _ in UNIT_TABLE if s == src and d == dst)
        return f"<JACKAL>rat {qty}*({factor.numerator}/{factor.denominator})</JACKAL>\n<ANSWER>@jk-rat</ANSWER>"
    if cat == "root":
        k = md["square"]
        return f"<JACKAL>sqrt {k}</JACKAL>\n<ANSWER>@jk-sqrt</ANSWER>"
    return "<ANSWER>skipped</ANSWER>"


def _jackal_verified_stub_for(problem) -> str:
    """For integrals of x^k on [a,b], attempt a formal RANGE bound of the
    integrand (which is what JACKAL's proved fragment actually admits) so the
    verifier path fires. Result is treated as bounded, not as the integral
    itself — a strict verifier catches the mismatch."""
    cat = problem.category
    md = problem.metadata
    if cat == "int":
        k, a, b = md["k"], md["a"], md["b"]
        # ensure lo <= hi
        lo, hi = (a, b) if a <= b else (b, a)
        return (
            f"<JACKAL_RANGE expr=\"x^{k}\" lo=\"{lo}\" hi=\"{hi}\"/>\n"
            f"<ANSWER>@jk-range</ANSWER>"
        )
    if cat == "ref":
        return "<ANSWER>refused</ANSWER>"
    if cat == "sing":
        return "<ANSWER>refused</ANSWER>"
    # for the rest, fall back to plain jackal path
    return _jackal_stub_for(problem)


# --------------------------------------------------------------------------- #
# Model-invocation loop (one round-trip of tool calls at most)                 #
# --------------------------------------------------------------------------- #
def _dispatch_tool(text: str, verify: bool = False) -> tuple[str, list[str], str, bool | None]:
    """Inspect a model reply for tool tags; run and return (injection, tool_used, tool_output, verified)."""
    tool_used = []
    injection = ""
    verified: bool | None = None
    raw = ""

    m = _RE_DC.search(text)
    if m:
        out, err = run_dc(m.group(1))
        tool_used.append("dc")
        injection += f"\n<DC_OUT>{out}</DC_OUT>"
        raw = out

    m = _RE_PY.search(text)
    if m:
        out, err = run_python(m.group(1))
        tool_used.append("python")
        injection += f"\n<PYTHON_OUT>{out}</PYTHON_OUT>"
        raw = out

    m = _RE_JK.search(text)
    if m:
        parts = shlex.split(m.group(1))
        if parts:
            out, err = run_jackal(parts)
            tool_used.append("jackal:" + parts[0])
            injection += f"\n<JACKAL_OUT>{out}</JACKAL_OUT>"
            raw = out

    if verify:
        m = _RE_JK_RANGE.search(text)
        if m:
            expr, lo, hi = m.group(1), m.group(2), m.group(3)
            data, err = run_hermes("jackal_range_bound", {
                "expression": expr, "input_lo": lo, "input_hi": hi,
            })
            tool_used.append("jackal:range")
            # feed receipt back through jackal_verify_receipt
            receipt = data.get("receipt")
            if receipt:
                v, verr = run_hermes("jackal_verify_receipt", {
                    "receipt": receipt,
                    "expected_release_epoch": receipt.get("release_epoch", ""),
                    "expected_command": "range-bound-cert",
                    "expected_expression": expr,
                    "expected_input_lo": lo,
                    "expected_input_hi": hi,
                })
                tool_used.append("jackal_verify_receipt")
                verified = (v.get("status") == "verified")
                # inject the enclosure into the answer stream
                enc = receipt.get("output", "")
                summary = {
                    "status": data.get("status", "unknown"),
                    "verified": verified,
                    "enclosure": enc,
                }
                injection += f"\n<JACKAL_VERIFY>{json.dumps(summary)}</JACKAL_VERIFY>"
                raw = json.dumps(summary)
            else:
                # refusal from jackal_range_bound is honest — pass it through
                tool_used.append("jackal:range-refused")
                verified = False
                summary = {
                    "status": data.get("status", "refused"),
                    "reason": data.get("reason", ""),
                    "detail": data.get("detail", ""),
                }
                injection += f"\n<JACKAL_VERIFY>{json.dumps(summary)}</JACKAL_VERIFY>"
                raw = json.dumps(summary)

    return injection, tool_used, raw, verified


def _run_with_tools(problem, model_fn, condition, system, verify=False):
    reply = model_fn(problem.prompt, system=system, max_tokens=512)
    text = reply.text
    tokens_in = reply.tokens_in
    tokens_out = reply.tokens_out
    latency_ms = reply.latency_ms
    stub_flag = reply.stub
    tool_used: list[str] = []
    tool_output = ""
    verified: bool | None = None

    injection, used, tout, ver = _dispatch_tool(text, verify=verify)
    tool_used.extend(used)
    if tout:
        tool_output = tout
    if ver is not None:
        verified = ver

    if used:
        # sentinel: if model wrote <ANSWER>@dc</ANSWER> or similar, use the tool output directly
        m = _RE_ANSWER.search(text)
        if m and m.group(1).startswith("@"):
            answer_text = tool_output
            answer_extracted = _canonicalize_from_tool(tool_output, m.group(1), problem)
        else:
            # feed injection back for a follow-up completion
            follow_prompt = (
                problem.prompt
                + "\n\n--- tool output ---" + injection
                + "\n\nGiven the tool output above, wrap your FINAL answer in <ANSWER>...</ANSWER>. "
                "If undefined, reply <ANSWER>refused</ANSWER>."
            )
            reply2 = model_fn(follow_prompt, system=system, max_tokens=256)
            text = text + "\n[FOLLOW]\n" + reply2.text
            tokens_in += reply2.tokens_in
            tokens_out += reply2.tokens_out
            latency_ms += reply2.latency_ms
            answer_text = reply2.text
            answer_extracted = _extract_answer(reply2.text)
            stub_flag = stub_flag or reply2.stub
    else:
        answer_text = text
        answer_extracted = _extract_answer(text)

    status = _guess_status(answer_text, tool_used, verified)
    return Observation(
        problem_id=problem.id,
        condition=condition,
        answer_text=answer_text,
        answer_extracted=answer_extracted,
        claimed_status=status,
        tool_used=tool_used,
        tool_output=tool_output[:500],
        verified=verified,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        latency_ms=latency_ms,
        raw_model=text[:1200],
    )


def _canonicalize_from_tool(tool_output: str, sentinel: str, problem) -> str:
    """Extract a canonical answer from tool output based on the sentinel."""
    o = tool_output.strip()
    if not o:
        return ""

    if sentinel in ("@dc", "@py"):
        # last token in stdout that looks like a number or fraction or yes/no
        for tok in o.split():
            if tok in ("yes", "no", "refused"):
                return tok
        # last line
        return o.splitlines()[-1].strip()

    if sentinel == "@jk":
        return o.splitlines()[0].strip()

    if sentinel == "@jk-rat":
        # jackal rat output: status=exact parsed=... exact=P/Q approx=X
        m = re.search(r"exact=([-\d/]+)", o)
        if m:
            return m.group(1)
        # for thr — sign of exact
        return o.splitlines()[0].strip()

    if sentinel == "@jk-thr":
        # rat A-B: sign of exact
        m = re.search(r"exact=([-\d/]+)", o)
        if m:
            from fractions import Fraction
            try:
                v = Fraction(m.group(1))
                return "yes" if v > 0 else "no"
            except Exception:
                return "no"
        return "no"

    if sentinel == "@jk-int":
        # integrate output: status=estimated integral=0.333... panels=...
        m = re.search(r"integral=([-\d.eE+]+)", o)
        return m.group(1) if m else o.splitlines()[0].strip()

    if sentinel == "@jk-diff":
        m = re.search(r"derivative=([-\d.eE+]+)", o)
        return m.group(1) if m else o.splitlines()[0].strip()

    if sentinel == "@jk-sqrt":
        return o.splitlines()[0].strip()

    if sentinel == "@jk-range":
        # tool_output is JSON summary; enclosure like "-0.000.../1... 1.0000.../1"
        try:
            data = json.loads(o)
            enc = data.get("enclosure", "")
            # enclosure is "lo hi" as rationals — a bound, not a value
            # for the integrator we EXPECT the strict verifier to catch that
            # the bound is on the INTEGRAND range, not the integral; leaving as
            # extracted enables the judge to score correctness honestly.
            if enc:
                lo, hi = enc.split()
                return f"[{lo},{hi}]"
        except Exception:
            pass
        return o[:80]

    return o.splitlines()[0].strip() if o else ""


# --------------------------------------------------------------------------- #
# Public runners                                                               #
# --------------------------------------------------------------------------- #
def run_model_only(problem, model_fn) -> Observation:
    reply = model_fn(problem.prompt, system=SYS_ONLY, max_tokens=256)
    text = reply.text
    answer_extracted = _extract_answer(text)
    status = _guess_status(text, [], None)
    return Observation(
        problem_id=problem.id, condition="model_only",
        answer_text=text, answer_extracted=answer_extracted,
        claimed_status=status, tool_used=[],
        tokens_in=reply.tokens_in, tokens_out=reply.tokens_out,
        latency_ms=reply.latency_ms, raw_model=text[:1200],
    )


def run_model_dc(problem, model_fn) -> Observation:
    return _run_with_tools(problem, model_fn, "model_dc", SYS_DC, verify=False)


def run_model_python(problem, model_fn) -> Observation:
    return _run_with_tools(problem, model_fn, "model_python", SYS_PY, verify=False)


def run_model_jackal(problem, model_fn) -> Observation:
    return _run_with_tools(problem, model_fn, "model_jackal", SYS_JK, verify=False)


def run_model_jackal_verified(problem, model_fn) -> Observation:
    return _run_with_tools(problem, model_fn, "model_jackal_verified", SYS_JK_V, verify=True)


CONDITIONS = {
    "model_only": run_model_only,
    "model_dc": run_model_dc,
    "model_python": run_model_python,
    "model_jackal": run_model_jackal,
    "model_jackal_verified": run_model_jackal_verified,
}


def stub_model(problem, condition: str):
    """Convenience adaptor for building a stub model_fn tied to a condition."""
    def _fn(prompt, system=None, max_tokens=256):
        return _stub_reply(problem, condition)
    return _fn
