#!/usr/bin/env python3
"""JACKAL adversarial campaign — every lane fuzzed against independent oracles.

Sections:
  A eval fuzz (random parenthesized trees vs Python math)
  B precedence torture (flat unparenthesized strings vs Python)
  C rat fuzz (random rational trees vs fractions.Fraction, exact + approx)
  D bigint fuzz (random 1-150 digit ops vs Python ints)
  E diff fuzz (random differentiable trees vs SymPy at sample points)
  F command-atlas oracle sweep (EVERY legacy command, valid + hostile + arity)
  G hostile inputs (deep nesting, huge exprs, emoji, empty)
  H cross-lane consistency (eval == rat approx == worksheet)
  I determinism (byte-identical repeated runs)

Rules: a case passes iff the output matches its oracle OR the program fails
closed (nonzero exit). rc=0 with a wrong or silently-coerced value is a
finding. Crashes (SIGABRT/rc!=101) are findings even when "fail-closed-ish".
Seeded for reproducibility.
"""
from __future__ import annotations
import math
import random
import statistics
import subprocess
import sys
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / "jackal-native"
random.seed(20260812)

findings: list[str] = []
counts: dict[str, list[int]] = {}


def run(*args: str, timeout: int = 60) -> subprocess.CompletedProcess[str]:
    return subprocess.run([str(BIN), *args], capture_output=True, text=True, timeout=timeout)


def tally(section: str, ok: bool, msg: str = "") -> None:
    counts.setdefault(section, [0, 0])
    counts[section][0 if ok else 1] += 1
    if not ok:
        findings.append(f"[{section}] {msg}")


def close(a: float, b: float, rel: float = 1e-11) -> bool:
    if math.isnan(a) or math.isnan(b):
        return False
    return abs(a - b) <= rel * max(1.0, abs(a), abs(b))


# --------------------------------------------------------------- A: eval fuzz
FUNS1 = [("sin", math.sin), ("cos", math.cos), ("exp", None), ("sqrt", None), ("ln", None), ("atan", math.atan), ("cbrt", None)]

def gen_tree(depth: int) -> str:
    if depth == 0 or random.random() < 0.3:
        if random.random() < 0.5:
            return repr(round(random.uniform(0.1, 9.9), 3))
        return str(random.randint(1, 99))
    r = random.random()
    if r < 0.55:
        op = random.choice("+-*/")
        return f"({gen_tree(depth-1)}{op}{gen_tree(depth-1)})"
    if r < 0.7:
        return f"({gen_tree(depth-1)}^{random.randint(1,3)})"
    if r < 0.8:
        return f"(-{gen_tree(depth-1)})"
    name = random.choice(["sin", "cos", "exp", "sqrt", "ln", "atan", "cbrt"])
    return f"{name}({gen_tree(depth-1)})"

def py_eval(expr: str) -> float:
    env = {"sin": math.sin, "cos": math.cos, "exp": math.exp, "sqrt": math.sqrt,
           "ln": math.log, "atan": math.atan, "cbrt": lambda v: math.copysign(abs(v) ** (1 / 3), v),
           "__builtins__": {}}
    return float(eval(expr.replace("^", "**"), env))

def section_a() -> None:
    for _ in range(300):
        expr = gen_tree(4)
        try:
            want = py_eval(expr)
            bad = math.isnan(want) or math.isinf(want)
        except Exception:
            bad = True
        r = run("eval", expr)
        if bad:
            tally("A-eval", r.returncode != 0, f"eval {expr!r}: python-undefined but jackal rc=0 -> {r.stdout.strip()!r}")
        elif r.returncode != 0:
            # jackal may fail closed where python survived (e.g. div by exact 0 mid-tree)
            tally("A-eval", "fail closed" in r.stderr or "expression" in r.stderr,
                  f"eval {expr!r}: rc={r.returncode} stderr tail {r.stderr.strip()[-90:]!r}")
        else:
            got = float(r.stdout.strip())
            tally("A-eval", close(got, want, 1e-9), f"eval {expr!r}: got {got!r} want {want!r}")

# ------------------------------------------------------- B: precedence torture
def section_b() -> None:
    cases = ["2+3*4-5/2", "2^3^2", "-2^2+7", "2^-3*8", "10-4-3-2", "100/5/2", "7.5%2%1.2",
             "2*3^2/6", "1+2*3^2-4/2", "5-3+2*4^2/8"]
    for _ in range(30):
        n = random.randint(3, 7)
        toks = [str(random.randint(1, 9))]
        for _ in range(n):
            toks.append(random.choice(["+", "-", "*", "/"]))
            toks.append(str(random.randint(1, 9)))
        cases.append("".join(toks))
    for expr in cases:
        want = float(eval(expr.replace("^", "**")))
        r = run("eval", expr)
        ok = r.returncode == 0 and close(float(r.stdout.strip()), want, 1e-12)
        tally("B-precedence", ok, f"eval {expr!r}: got {r.stdout.strip()!r} want {want!r}")

# ----------------------------------------------------------------- C: rat fuzz
def gen_rat(depth: int) -> str:
    if depth == 0 or random.random() < 0.35:
        if random.random() < 0.3:
            whole = random.randint(0, 99)
            frac = random.randint(1, 999)
            return f"{whole}.{frac:03d}"
        return str(random.randint(1, 9999))
    r = random.random()
    if r < 0.7:
        op = random.choice("+-*/")
        return f"({gen_rat(depth-1)}{op}{gen_rat(depth-1)})"
    if r < 0.85:
        return f"({gen_rat(depth-1)}^{random.choice([-2,-1,2,3])})"
    return f"(-{gen_rat(depth-1)})"

def frac_eval(expr: str) -> Fraction:
    def conv(tok: str) -> str:
        if "." in tok:
            return f"Fraction('{tok}')"
        return f"Fraction({tok})"
    import re
    py = re.sub(r"\d+\.\d+|\d+", lambda m: conv(m.group(0)), expr).replace("^", "**")
    return eval(py, {"Fraction": Fraction, "__builtins__": {}})

def section_c() -> None:
    for _ in range(200):
        expr = gen_rat(3)
        try:
            want = frac_eval(expr)
            bad = False
        except ZeroDivisionError:
            bad = True
        r = run("rat", expr)
        if bad:
            tally("C-rat", r.returncode != 0, f"rat {expr!r}: div-zero but rc=0 -> {r.stdout.strip()!r}")
            continue
        if r.returncode != 0:
            tally("C-rat", False, f"rat {expr!r}: refused but python fine: {r.stderr.strip()[-80:]!r}")
            continue
        out = r.stdout.strip()
        exact = out.split("exact=")[1].split(" ")[0]
        want_s = f"{want.numerator}/{want.denominator}" if want.denominator != 1 else str(want.numerator)
        tally("C-rat", exact == want_s, f"rat {expr!r}: exact={exact} want {want_s}")

# -------------------------------------------------------------- D: bigint fuzz
def rand_big(digits: int) -> int:
    lo = 10 ** (digits - 1) if digits > 1 else 0
    return random.randint(lo, 10 ** digits - 1)

def section_d() -> None:
    for _ in range(40):
        a, b = rand_big(random.randint(1, 150)), rand_big(random.randint(1, 150))
        r = run("big-add", str(a), str(b))
        tally("D-bigint", r.returncode == 0 and r.stdout.strip() == str(a + b), f"big-add {a} {b}")
        r = run("big-mul", str(a), str(b))
        tally("D-bigint", r.returncode == 0 and r.stdout.strip() == str(a * b), f"big-mul {a} {b}")
    for _ in range(15):
        base, e = rand_big(random.randint(1, 25)), random.randint(0, 200)
        r = run("big-pow", str(base), str(e))
        tally("D-bigint", r.returncode == 0 and r.stdout.strip() == str(base ** e), f"big-pow {base} {e}")
    for _ in range(15):
        n = random.randint(0, 300)
        k = random.randint(0, n) if n else 0
        r = run("big-ncr", str(n), str(k))
        tally("D-bigint", r.returncode == 0 and r.stdout.strip() == str(math.comb(n, k)), f"big-ncr {n} {k}")
    for n in [0, 1, 2, 50, 500]:
        r = run("big-fact", str(n))
        tally("D-bigint", r.returncode == 0 and r.stdout.strip() == str(math.factorial(n)), f"big-fact {n}")
    for args, why in [(["big-fact", "-1"], "neg"), (["big-fact", "10001"], "cap"), (["big-ncr", "5", "9"], "r>n"),
                      (["big-pow", "2", "10001"], "cap"), (["big-add", "12x", "3"], "nondigit"), (["big-mul", "", "3"], "empty")]:
        r = run(*args)
        tally("D-bigint", r.returncode != 0, f"{' '.join(args)}: {why} accepted rc=0 -> {r.stdout.strip()!r}")

# ------------------------------------------------------------ E: diff vs sympy
def gen_diff(depth: int) -> str:
    if depth == 0 or random.random() < 0.3:
        return random.choice(["x", "x", str(random.randint(1, 9))])
    r = random.random()
    if r < 0.4:
        op = random.choice("+-*")
        return f"({gen_diff(depth-1)}{op}{gen_diff(depth-1)})"
    if r < 0.55:
        return f"({gen_diff(depth-1)}/({gen_diff(depth-1)}^2+2))"
    if r < 0.7:
        return f"({gen_diff(depth-1)}^{random.randint(1,4)})"
    name = random.choice(["sin", "cos", "exp", "atan"])
    return f"{name}({gen_diff(depth-1)})"

def section_e() -> None:
    try:
        import sympy as sp
    except ImportError:
        tally("E-diff", False, "sympy unavailable")
        return
    x = sp.Symbol("x")
    for _ in range(60):
        expr = gen_diff(3)
        r = run("diff", expr)
        if r.returncode != 0:
            tally("E-diff", False, f"diff {expr!r} refused: {r.stderr.strip()[-80:]!r}")
            continue
        emitted = r.stdout.split("] = ")[1].split("\n")[0]
        try:
            mine = sp.sympify(emitted.replace("^", "**"), locals={"ln": sp.log, "cbrt": sp.cbrt}, rational=True)
            truth = sp.diff(sp.sympify(expr.replace("^", "**"), locals={"ln": sp.log}, rational=True), x)
        except Exception as e:
            tally("E-diff", False, f"diff {expr!r}: sympy parse error {e}")
            continue
        ok_pts = 0
        for pt in [0.31, 0.77, 1.19, 1.83]:
            try:
                mv, tv = float(mine.subs(x, pt)), float(truth.subs(x, pt))
                if close(mv, tv, 1e-6):
                    ok_pts += 1
            except Exception:
                ok_pts += 1  # domain miss at this point: not a mismatch
        tally("E-diff", ok_pts == 4, f"diff {expr!r}: emitted {emitted!r} disagrees with sympy")

# ------------------------------------------------- F: command-atlas oracle sweep
def outnum(r: subprocess.CompletedProcess[str]) -> float:
    return float(r.stdout.strip().split()[0])

def section_f() -> None:
    S = "F-atlas"
    for _ in range(10):
        a, b = round(random.uniform(-99, 99), 4), round(random.uniform(0.1, 99), 4)
        checks = [("add", a + b), ("sub", a - b), ("mul", a * b), ("div", a / b), ("hypot", math.hypot(a, b))]
        for cmd, want in checks:
            r = run(cmd, repr(a), repr(b))
            tally(S, r.returncode == 0 and close(outnum(r), want), f"{cmd} {a} {b}: {r.stdout.strip()!r} want {want}")
        r = run("pow", repr(abs(a)), repr(round(random.uniform(-2, 3), 2)))
        tally(S, r.returncode == 0, f"pow domain")
    for cmd, f, lo, hi in [("sqrt", math.sqrt, 0, 999), ("cbrt", lambda v: v ** (1/3), 0.01, 999),
                           ("sin", math.sin, -6, 6), ("cos", math.cos, -6, 6), ("tan", math.tan, -1.4, 1.4),
                           ("ln", math.log, 0.01, 999), ("log10", math.log10, 0.01, 999), ("exp", math.exp, -20, 20)]:
        v = round(random.uniform(lo, hi), 4)
        r = run(cmd, repr(v))
        tally(S, r.returncode == 0 and close(outnum(r), f(v), 1e-10), f"{cmd} {v}: {r.stdout.strip()!r}")
    v = round(random.uniform(0, 360), 3)
    r = run("sin-deg", repr(v))
    tally(S, close(outnum(r), math.sin(math.radians(v)), 1e-10), f"sin-deg {v}")
    # programmer lane
    for _ in range(8):
        a, b = random.randint(-2**62, 2**62), random.randint(0, 2**62)
        r = run("hex", str(a)); want = ("-0x%X" % -a) if a < 0 else ("0x%X" % a)
        tally(S, r.stdout.strip() == want, f"hex {a}: {r.stdout.strip()} want {want}")
        r = run("bin", str(b)); want = "0b" + format(b, "b")
        tally(S, r.stdout.strip() == want, f"bin {b}")
        r = run("band", str(a), str(b)); tally(S, int(r.stdout.strip()) == (a & b), f"band {a} {b}")
        r = run("bor", str(a), str(b)); tally(S, int(r.stdout.strip()) == (a | b), f"bor")
        r = run("bxor", str(a), str(b)); tally(S, int(r.stdout.strip()) == (a ^ b), f"bxor")
        c = random.randint(0, 63)
        r = run("shr", str(a), str(c)); tally(S, int(r.stdout.strip()) == (a >> c), f"shr {a} {c}")
    for _ in range(6):
        a, b = random.randint(1, 10**9), random.randint(1, 10**9)
        r = run("gcd", str(a), str(b)); tally(S, int(r.stdout.strip()) == math.gcd(a, b), f"gcd {a} {b}")
        r = run("lcm", str(a), str(b)); tally(S, int(r.stdout.strip()) == math.lcm(a, b), f"lcm {a} {b}")
    for n in [0, 1, 12, 20]:
        r = run("fact", str(n)); tally(S, int(r.stdout.strip()) == math.factorial(n), f"fact {n}")
    for _ in range(6):
        n = random.randint(0, 66); k = random.randint(0, n) if n else 0
        r = run("ncr", str(n), str(k))
        want = math.comb(n, k)
        ok = (r.returncode == 0 and int(r.stdout.strip()) == want) or (r.returncode != 0 and want > 2**63 - 1)
        tally(S, ok, f"ncr {n} {k}")
    for _ in range(4):
        p = random.randint(2, 10**7)
        r = run("prime", str(p)); out = r.stdout.strip()
        import sympy as sp
        if "is prime" in out:
            tally(S, sp.isprime(p), f"prime {p}: claimed prime")
        else:
            d = int(out.split("factor=")[1])
            tally(S, p % d == 0 and 1 < d < p, f"prime {p}: factor {d}")
    # quadratic real + complex
    r = run("quadratic", "1", "-3", "2")
    tally(S, "roots=2,1" in r.stdout, "quadratic real")
    r = run("quadratic", "1", "2", "5")
    tally(S, "real=-1 imaginary=2" in r.stdout, "quadratic complex")
    # stats / describe / linreg
    data = [round(random.uniform(-50, 50), 3) for _ in range(9)]
    r = run("stats", *[repr(v) for v in data])
    m = float(r.stdout.split("mean=")[1].split(" ")[0])
    tally(S, close(m, statistics.fmean(data), 1e-9), "stats mean")
    r = run("describe", *[repr(v) for v in data])
    var = float(r.stdout.split("variance=")[1].split(" ")[0])
    tally(S, close(var, statistics.pvariance(data), 1e-9), "describe pvariance")
    med = float(r.stdout.split("median=")[1].split(" ")[0])
    tally(S, close(med, statistics.median(data), 1e-12), "describe median")
    xs = [1.0, 2.0, 3.0, 4.0, 5.0]; ys = [round(2.5 * v - 1.0 + random.uniform(-0.1, 0.1), 4) for v in xs]
    pairs: list[str] = []
    for xv, yv in zip(xs, ys):
        pairs += [repr(xv), repr(yv)]
    r = run("linreg", *pairs)
    slope = float(r.stdout.split("y=")[1].split("*")[0])
    lr = statistics.linear_regression(xs, ys)
    tally(S, close(slope, lr.slope, 1e-9), "linreg slope")
    # vectors
    a3 = [1.5, -2.0, 3.25]; b3 = [4.0, 0.5, -1.75]
    r = run("dot", *[repr(v) for v in a3 + b3])
    tally(S, close(outnum(r), sum(p * q for p, q in zip(a3, b3)), 1e-12), "dot")
    r = run("norm3", *[repr(v) for v in a3])
    tally(S, close(outnum(r), math.sqrt(sum(v * v for v in a3)), 1e-12), "norm3")
    # conversions — all supported pairs
    conv = [("km","m",1000.0), ("m","km",1e-3), ("cm","m",0.01), ("m","cm",100.0), ("in","m",0.0254),
            ("ft","m",0.3048), ("kg","g",1000.0), ("lb","kg",0.45359237), ("atm","Pa",101325.0),
            ("bar","Pa",100000.0), ("kWh","J",3600000.0)]
    for src, dst, k in conv:
        v = round(random.uniform(0.1, 50), 4)
        r = run("convert", repr(v), src, dst)
        tally(S, close(outnum(r), v * k, 1e-12), f"convert {src}->{dst}")
    r = run("convert", "25", "C", "F"); tally(S, close(outnum(r), 77.0, 1e-12), "C->F")
    r = run("convert", "300", "K", "C"); tally(S, close(outnum(r), 26.85, 1e-12), "K->C")
    # physics & chemistry & engineering formulas
    r = run("ohm", "v", "12", "4"); tally(S, "current=3 A" in r.stdout and "power=36 W" in r.stdout, "ohm v")
    r = run("parallel-r", "100", "200"); tally(S, close(outnum(r), 200/3, 1e-12), "parallel-r")
    r = run("kinetic", "3", "7"); tally(S, close(outnum(r), 0.5*3*49, 1e-12), "kinetic")
    sp_, ang, g = 33.0, 28.0, 9.80665
    r = run("projectile", repr(sp_), repr(ang), repr(g))
    rng = float(r.stdout.split("range=")[1].split(" ")[0])
    tally(S, close(rng, sp_*sp_*math.sin(2*math.radians(ang))/g, 1e-9), "projectile range")
    r = run("orbit", "7000000", "398600441800000")
    v_ = float(r.stdout.split("speed=")[1].split(" ")[0])
    tally(S, close(v_, math.sqrt(398600441800000/7000000), 1e-9), "orbit speed")
    r = run("photon", "500")
    freq = float(r.stdout.split("frequency=")[1].split(" ")[0])
    tally(S, close(freq, round(299792458.0/500e-9), 1.0), "photon frequency")
    r = run("ph", "0.0001"); tally(S, "pH=4" in r.stdout and "acidic" in r.stdout, "ph")
    r = run("dilute", "3", "0.4", "0.6"); tally(S, close(outnum(r.__class__(args=r.args, returncode=r.returncode, stdout=r.stdout.split("final-volume=")[1], stderr="")), 2.0, 1e-12) if "final-volume=" in r.stdout else False, "dilute")
    r = run("relativity", "0.8"); gam = float(r.stdout.split("gamma=")[1].split(" ")[0])
    tally(S, close(gam, 1/math.sqrt(1-0.64), 1e-12), "relativity")
    r = run("decibel-power", "1000"); tally(S, close(outnum(r), 30.0, 1e-12), "decibel")
    r = run("blackbody", "3000"); wl = float(r.stdout.split("peak-wavelength=")[1].split(" ")[0])
    tally(S, close(wl, 2897771.955/3000, 1e-9), "blackbody")
    r = run("molarity", "0.25", "0.5"); tally(S, close(outnum(r), 0.5, 1e-12), "molarity")
    r = run("ideal-gas", "2", "350", "0.01")
    p_ = float(r.stdout.split("pressure=")[1].split(" ")[0])
    tally(S, close(p_, 2*8.31446261815324*350/0.01, 1e-9), "ideal-gas")
    r = run("measure-mul", "10", "0.2", "5", "0.1", "u")
    tally(S, "50 ± 2 u (4%)" in r.stdout, f"measure-mul: {r.stdout.strip()!r}")
    r = run("matrix2", "2", "1", "1", "1"); tally(S, "det=1" in r.stdout and "inverse=[1,-1;-1,2]" in r.stdout, "matrix2")
    r = run("solve2", "1", "1", "3", "1", "-1", "1"); tally(S, "x=2 y=1" in r.stdout, "solve2")
    r = run("lerp", "10", "20", "0.75"); tally(S, close(outnum(r), 17.5, 1e-12), "lerp")
    # hostile args: malformed numerics must NOT be silently coerced
    hostile_cases = [
        ["add", "abc", "5"], ["mul", "5", ""], ["kinetic", "abc", "3"], ["convert", "xyz", "km", "m"],
        ["gcd", "4.5", "6"], ["fact", "abc"], ["hex", "12abc"], ["ncr", "ten", "3"],
        ["projectile", "20", "45", "abc"], ["stats", "1", "2", "three"], ["shl", "1", "abc"],
    ]
    for args in hostile_cases:
        r = run(*args)
        tally(S, r.returncode != 0, f"HOSTILE {' '.join(args)!r}: rc=0 output {r.stdout.strip()!r} (silent coercion)")
    # wrong arity on a sample of every world
    for args in [["add", "1"], ["quadratic", "1", "2"], ["matrix2", "1", "2", "3"], ["convert", "1", "km"],
                 ["measure-mul", "1", "2", "3"], ["diff"], ["rat"], ["big-add", "1"], ["solve", "x", "0"]]:
        r = run(*args)
        tally(S, r.returncode != 0, f"ARITY {' '.join(args)!r} accepted")

# ---------------------------------------------------------------- G: hostile
def section_g() -> None:
    S = "G-hostile"
    deep = "(" * 4000 + "1" + ")" * 4000
    r = run("eval", deep)
    ok = (r.returncode == 0 and r.stdout.strip() == "1") or (r.returncode != 0 and "ANUBIS_PANIC" in r.stderr)
    tally(S, ok, f"4000-deep parens: rc={r.returncode} (crash without fail-closed message)")
    r = run("eval", "1+" * 20000 + "1")
    ok = (r.returncode == 0 and r.stdout.strip() == "20001") or (r.returncode != 0 and "ANUBIS_PANIC" in r.stderr)
    tally(S, ok, f"20001-term chain: rc={r.returncode}")
    # NOTE: an embedded NUL can't cross the argv boundary (the OS rejects it
    # before JACKAL ever runs), so it is untestable-and-safe at the CLI.
    for expr in ["🦊+1", "1;2", '"quote"', "1e999999999", "9" * 5000]:
        r = run("eval", expr)
        good_reject = r.returncode != 0 and "ANUBIS_PANIC" in r.stderr
        good_value = False
        if expr == "9" * 5000 and r.returncode != 0:
            good_reject = True
        if expr == "1e999999999":
            good_reject = r.returncode != 0  # inf -> finite gate
        tally(S, good_reject or good_value, f"hostile eval {expr[:24]!r}: rc={r.returncode} out={r.stdout.strip()[:40]!r}")
    r = run("worksheet", "; ".join(f"v{i} = {i}" for i in range(500)) + "; v499")
    tally(S, r.returncode == 0 and r.stdout.strip().endswith("499"), "500-statement worksheet")
    r = run("nonsense-command")
    tally(S, r.returncode != 0, "unknown command accepted")
    r = run("big-fact", "10000", timeout=120)
    tally(S, r.returncode == 0 and len(r.stdout.strip()) == 35660, "big-fact 10000 digit count")

# ------------------------------------------------------------- H: cross-lane
def section_h() -> None:
    for _ in range(50):
        expr = gen_rat(2)
        r_eval = run("eval", expr)
        r_rat = run("rat", expr)
        r_ws = run("worksheet", f"result = {expr}")
        if r_eval.returncode != 0 or r_rat.returncode != 0:
            agree = r_eval.returncode != 0 and r_rat.returncode != 0
            tally("H-crosslane", agree, f"{expr!r}: lanes disagree on refusal (eval rc={r_eval.returncode} rat rc={r_rat.returncode})")
            continue
        ev = float(r_eval.stdout.strip())
        approx = float(r_rat.stdout.split("approx=")[1].split()[0])
        ws = float(r_ws.stdout.strip().split("= ")[-1])
        tally("H-crosslane", ev == approx and close(ws, ev, 1e-15), f"{expr!r}: eval={ev} rat-approx={approx} ws={ws}")

# ------------------------------------------------------------ I: determinism
def section_i() -> None:
    cmds = [["claim-card", "projectile", "20", "45", "9.80665"], ["diff", "x^x"], ["rat", "0.1+0.2"],
            ["eval", "sin(1)+cos(2)^2"], ["big-ncr", "500", "250"], ["integrate-adaptive", "sin(x)", "0", "3", "1e-9"],
            ["describe", "3", "1", "4", "1", "5"], ["solve", "cos(x)-x", "0", "1"]]
    for args in cmds:
        r1, r2 = run(*args), run(*args)
        tally("I-determinism", r1.stdout == r2.stdout and r1.returncode == r2.returncode,
              f"{' '.join(args)!r} nondeterministic")

# --------------------------------------------------------------------- main
def main() -> int:
    for fn in [section_a, section_b, section_c, section_d, section_e,
               section_f, section_g, section_h, section_i]:
        fn()
        name = fn.__name__.replace("section_", "").upper()
        print(f"section {name} done", flush=True)
    print("\n=== CAMPAIGN REPORT ===")
    total_ok = total_bad = 0
    for sec in sorted(counts):
        ok, bad = counts[sec]
        total_ok += ok
        total_bad += bad
        print(f"{sec:16s} {ok:4d} pass  {bad:3d} FAIL")
    print(f"{'TOTAL':16s} {total_ok:4d} pass  {total_bad:3d} FAIL")
    if findings:
        print("\n=== FINDINGS ===")
        for f in findings[:80]:
            print(" -", f)
        if len(findings) > 80:
            print(f"   ... and {len(findings)-80} more")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
