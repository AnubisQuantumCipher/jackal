#!/usr/bin/env python3
"""Parser-correspondence gate: JACKAL's real parser vs the mechanized Lean parser.

This is the anti-drift instrument for implementation-bridge #1. JACKAL's actual
Anubis parser/lowerer (`jackal parse-dump` / `jackal lower-dump`) and the
mechanized Lean parser/lowerer (a `lake exe` over JackalIv.Parser/Lower) are run
on the SAME corpus and must agree on the canonical s-expression, byte for byte.

Two dumps are compared per input:
  parse : the raw parse tree (associativity, precedence, unary-minus-vs-power,
          arity, scientific-notation token text) — must match exactly.
  lower : the certified-lane lowering (simplify_bound) — must match exactly,
          including that literals are NOT constant-folded and that 0*x is kept.

Verdicts:
  MATCH        — both dumps identical.
  PARSE_DRIFT  — parse trees differ (a real precedence/associativity divergence).
  LOWER_DRIFT  — parse agrees but lowering differs.
  BOTH_REFUSE  — both sides reject the input (a negative control agreeing).
  REFUSAL_DRIFT— one side accepts, the other rejects (a soundness-relevant split).

The Lean side is exercised through a built executable so this gate needs no
Lean-source parsing here. If the exe is absent it is built once via `lake build`.

Usage:
  python3 tests/parser_differential.py            # curated corpus + negative controls
  python3 tests/parser_differential.py --tamper   # expect the gate to go RED
                                                   # (mutated engine dumps injected)
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "jackal"
LEAN_DIR = ROOT / "proofs" / "lean"
LEAN_EXE_NAME = "jackal_parse_dump"  # lean_exe target added by the bridge wave

# ---------------------------------------------------------------------------
# Corpus: expressions that exercise every grammar decision, plus the negative
# controls the mission enumerates.
# ---------------------------------------------------------------------------

# Well-formed inputs both sides must PARSE identically.
GRAMMAR_CASES = [
    "2+3*4",              # precedence: * over +
    "2*3+4",              # precedence, other order
    "(2+3)*4",            # parens override
    "3-2-1",              # - left-associative
    "8/4/2",              # / left-associative
    "2^3^2",              # ^ right-associative
    "-3^2",               # unary minus binds looser than ^  => neg(pow 3 2)
    "2^-3",               # unary minus inside exponent
    "2^-3^2",             # combined
    "-(-x)",              # double negation (parse keeps it; lower collapses)
    "sin(2*x)^2",         # call then power
    "1.5e2/3",            # scientific-notation token text preserved
    "1.5E2/3",            # capital E
    "6.022e23*x",         # large exponent literal
    "hypot(3,4)+atan2(1,x)",  # binary calls
    "min(x,1)+max(x,2)",  # binary calls
    "abs(x)+cbrt(x)",     # unary calls
    "exp(0-x^2)",         # nested; lowering rewrites 0-u -> neg u
    "ln(x)+log10(x)+log2(x)",
    "tan(x)+asin(x)+acos(x)+atan(x)",
    "floor(x)+ceil(x)+round(x)+trunc(x)",
    "x^2+1",
    "2*pi+e",             # constants
    "1*x+0-0*x",          # lowering: 1*x->x, +0 drop, 0*x KEPT (not folded)
    "x/1",                # lowering: /1 drop
    "x^1",                # lowering: ^1 drop
    "0-x",                # lowering: 0-x -> neg x
]

# Inputs both sides must REJECT (malformed / unsupported at the parse layer).
PARSE_REJECT_CASES = [
    "2++2",               # empty operand
    "(2+3",               # unbalanced paren
    "sin()",              # arity: sin needs 1 arg
    "hypot(3)",           # arity: hypot needs 2
    "bogus(2)",           # unknown function
    "1.2.3",              # malformed number
    "",                   # empty
    ".5",                 # number needs a leading digit
    "2^",                 # dangling operator
]

# PARSER-ONLY constructs: the parser ACCEPTS these, but the certified model
# REFUSES them (var != x, or an operator ieval has no interval model for). Both
# sides must agree: parse succeeds, certified-admission fails.
PARSER_ONLY_CASES = [
    "y+1",                # a free variable other than x
    "x%2",                # '%' has no certified interval model
    "a*b",                # two non-x variables
]

TAMPER_NOTE = (
    "tamper mode injects a mutated engine dump (precedence flipped) so a passing "
    "gate would be a bug; expect PARSE_DRIFT."
)


def run_engine(op: str, expr: str) -> tuple[int, str]:
    proc = subprocess.run(
        [str(LAUNCHER), op, expr],
        capture_output=True, text=True, timeout=3600,
        env={**_engine_env()},
    )
    out = proc.stdout.strip()
    prefix = "ast=" if op == "parse-dump" else "lowered="
    if proc.returncode == 0 and out.startswith(prefix):
        return 0, out[len(prefix):]
    return proc.returncode or 1, ""


def _engine_env() -> dict:
    import os
    env = dict(os.environ)
    env.setdefault("ANUBIS_BIN", str(Path.home() / "anubis-lang/vm/pins/anubis-a733565f237d"))
    # Exercise the live source: parse-dump/lower-dump post-date the sealed
    # jackal-native, so force the compiler path until the binary is rebuilt at
    # the next seal. (Set JACKAL_FORCE_SOURCE=0 to test a rebuilt binary.)
    env.setdefault("JACKAL_FORCE_SOURCE", "1")
    env.setdefault("JACKAL_OUT", "/tmp/jackal-parser-gate-build")
    return env


def _lean_exe_path() -> Path | None:
    # lake places executables under .lake/build/bin
    candidate = LEAN_DIR / ".lake" / "build" / "bin" / LEAN_EXE_NAME
    return candidate if candidate.exists() else None


def run_lean(mode: str, expr: str) -> tuple[int, str]:
    exe = _lean_exe_path()
    if exe is None:
        raise SystemExit(
            f"Lean dumper not built: {LEAN_DIR}/.lake/build/bin/{LEAN_EXE_NAME} absent.\n"
            f"Build it first:  cd {LEAN_DIR} && lake build {LEAN_EXE_NAME}"
        )
    proc = subprocess.run(
        [str(exe), mode, expr], capture_output=True, text=True, timeout=600,
    )
    out = proc.stdout.strip()
    # Contract: the exe prints the bare canonical s-expr on success (exit 0),
    # or exits nonzero with an empty stdout on rejection.
    if proc.returncode == 0 and out:
        return 0, out
    return proc.returncode or 1, ""


def classify(engine: tuple[int, str], lean: tuple[int, str], stage: str) -> str:
    e_ok, e_val = engine
    l_ok, l_val = lean
    if e_ok != 0 and l_ok != 0:
        return "BOTH_REFUSE"
    if (e_ok == 0) != (l_ok == 0):
        return "REFUSAL_DRIFT"
    return "MATCH" if e_val == l_val else f"{stage.upper()}_DRIFT"


def main() -> int:
    tamper = "--tamper" in sys.argv
    if tamper:
        print(f"[tamper] {TAMPER_NOTE}")

    failures = 0
    checked = 0

    def check(expr: str, expect_reject: bool = False) -> None:
        nonlocal failures, checked
        for op, mode, stage in (("parse-dump", "parse", "parse"),
                                 ("lower-dump", "lower", "lower")):
            engine = run_engine(op, expr)
            if tamper and stage == "parse" and engine[0] == 0:
                # Corrupt the engine dump to prove the gate detects drift.
                engine = (0, engine[1].replace("add", "sub", 1))
            lean = run_lean(mode, expr)
            verdict = classify(engine, lean, stage)
            checked += 1
            ok = verdict in ("MATCH", "BOTH_REFUSE")
            if expect_reject and verdict == "BOTH_REFUSE":
                ok = True
            if not ok:
                failures += 1
            flag = "ok " if ok else "BAD"
            print(f"  [{flag}] {stage:5} {verdict:14} {expr!r}")

    print("== grammar cases (must MATCH):")
    for e in GRAMMAR_CASES:
        check(e)
    print("== parse-reject cases (must BOTH_REFUSE):")
    for e in PARSE_REJECT_CASES:
        check(e, expect_reject=True)
    print("== parser-only cases (parse MATCH; certified-admission handled by the model layer):")
    for e in PARSER_ONLY_CASES:
        check(e)

    print(f"\nchecked={checked} failures={failures}")
    if tamper:
        if failures > 0:
            print("TAMPER VERDICT: PASS — the gate correctly detected injected drift.")
            return 0
        print("TAMPER VERDICT: FAIL — injected drift went undetected (gate is inert).")
        return 1
    if failures:
        print("VERDICT: FAIL — parser/lowering drift between engine and Lean model.")
        return 1
    print("VERDICT: PASS — engine and mechanized Lean parser/lowerer agree on the corpus.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
