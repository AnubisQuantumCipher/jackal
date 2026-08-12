#!/usr/bin/env python3
"""Black-box acceptance tests for JackalCalc's Anubis CLI."""
from __future__ import annotations

import math
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "jackal_calc.anb"
PIN = Path(os.environ.get("ANUBIS_BIN", "/Users/sicarii/anubis-lang/vm/pins/anubis-51f4a964347a"))
OUT_ROOT = Path(os.environ.get("JACKAL_TEST_OUT", "/tmp/jackal-calc-test-out"))

CASES = [
    (["add", "40", "2"], "42"),
    (["div", "22", "7"], "3.142857142857143"),
    (["sqrt", "81"], "9"),
    (["sin-deg", "30"], "0.49999999999999994"),
    (["hypot", "3", "4"], "5"),
    (["hex", "255"], "0xFF"),
    (["bin", "42"], "0b101010"),
    (["band", "240", "170"], "160"),
    (["bxor", "170", "255"], "85"),
    (["shl", "7", "3"], "56"),
    (["gcd", "462", "1071"], "21"),
    (["fact", "10"], "3628800"),
    (["stats", "2", "4", "4", "4", "5", "5", "7", "9"], "n=8 sum=40 mean=5 min=2 max=9"),
    # Mathematics and numerical analysis
    (["quadratic", "1", "-3", "2"], "roots=2,1 discriminant=1"),
    (["quadratic", "1", "2", "5"], "complex roots: real=-1 imaginary=2"),
    (["lerp", "10", "20", "0.25"], "12.5"),
    (["percent-error", "9.8", "10"], "2%"),
    (["ncr", "10", "3"], "120"),
    (["ncr", "62", "31"], "465428353255261088"),
    (["ncr", "66", "33"], "7219428434016265740"),
    (["lcm", "21", "6"], "42"),
    (["prime", "104729"], "104729 is prime"),
    # Vectors, statistics, and data science
    (["dot", "1", "2", "3", "4", "5", "6"], "32"),
    (["cross", "1", "2", "3", "4", "5", "6"], "[-3,6,-3]"),
    (["norm3", "2", "3", "6"], "7"),
    (["describe", "2", "4", "4", "4", "5", "5", "7", "9"], "n=8 mean=5 median=4.5 variance=4 sd=2 range=7"),
    (["linreg", "1", "2", "2", "4", "3", "6", "4", "8"], "y=2*x+0 r=1 r2=1"),
    # Engineering and unit-aware computation
    (["convert", "1", "km", "m"], "1000 m"),
    (["convert", "212", "F", "C"], "100 C"),
    (["convert", "1", "atm", "Pa"], "101325 Pa"),
    (["ohm", "v", "12", "4"], "voltage=12 V current=3 A resistance=4 ohm power=36 W"),
    (["parallel-r", "100", "200"], "66.66666666666667 ohm"),
    # Physics, chemistry, and Earth/space science
    (["kinetic", "2", "3"], "9 J"),
    (["photon", "500"], "energy=0.00000000000000000039728917142978563 J frequency=599584916000000 Hz"),
    (["ideal-gas", "1", "300", "0.0246172098242879"], "pressure=101325 Pa"),
    # rounded() must not corrupt beyond-2^53 magnitudes (round() saturation once
    # laundered this into garbage); expected value verified against Python
    (["ideal-gas", "1000000", "300", "0.000001"], "pressure=2494338785445972 Pa"),
    (["molarity", "0.5", "2"], "0.25 mol/L"),
    (["orbit", "6371000", "398600441800000"], "speed=7909.792402654085 m/s period=5060.837447340496 s"),
    (["projectile", "20", "45", "9.80665"], "range=40.78864851911713 m time=2.8841929963302353 s max-height=10.19716212977928 m"),
    (["self-test"], "self-test: 64/64 Anubis-native invariants pass"),
    # Exact rational engine (echoes its parsed form, per the transcription-check discipline)
    (["rat", "0.1 + 0.2"], "parsed=0.1+0.2 exact=3/10 approx=0.30000000000000004"),
    (["rat", "1/3 + 1/6"], "parsed=1/3+1/6 exact=1/2 approx=0.5"),
    # approx is the honest IEEE f64 value of pow(2/3, -2) — NOT 2.25; the exact
    # field 9/4 is the true answer, and that discrepancy is the feature.
    (["rat", "(2/3)^-2"], "parsed=(2/3)^-2 exact=9/4 approx=2.2500000000000004"),
    (["rat", "1/3 - 1/3"], "parsed=1/3-1/3 exact=0 approx=0"),
    (["rat", "-3/9"], "parsed=-3/9 exact=-1/3 approx=-0.3333333333333333"),
    (["rat", "2.5e1 * 2"], "parsed=2.5e1*2 exact=50 approx=50"),
    # Worksheet: variables persist across semicolon-separated statements
    (["worksheet", "a = 5; b = a^2; a+b"], "a = 5\nb = 25\n30"),
    (["worksheet", "r0 = 2; area = pi*r0^2"], "r0 = 2\narea = 12.566370614359172"),
    # Expression engine
    (["eval", "2+3*4"], "14"),
    (["eval", "(2+3)*4"], "20"),
    (["eval", "2^10"], "1024"),
    (["eval", "-3^2"], "-9"),
    (["eval", "2^-3"], "0.125"),
    (["eval", "sqrt(16)+cbrt(27)"], "7"),
    (["eval", "hypot(3,4)"], "5"),
    (["eval", "2*pi"], "6.283185307179586"),
    (["eval", "1.5e2/3"], "50"),
    (["eval", "min(3,2)+max(3,2)"], "5"),
    (["eval", "atan2(1,1)*4"], "3.141592653589793"),
    (["eval", "7.5%2"], "1.5"),
    # JACKAL 10x: auditable measurement, numerical lab, and advanced STEM
    (["measure-mul", "12", "0.1", "3", "0.05", "m2"], "36 ± 0.9 m2 (2.5%)"),
    (["uncertain-ohm", "12", "0.1", "3", "0.05"], "resistance=4 ± 0.1 ohm relative=2.5%"),
    (["matrix2", "1", "2", "3", "4"], "det=-2 inverse=[-2,1;1.5,-0.5]"),
    (["solve2", "2", "1", "5", "1", "-1", "1"], "x=2 y=1 residual=0"),
    (["integrate-x2", "0", "3", "100"], "integral=9 method=simpson panels=100"),
    (["derivative-x3", "2", "0.001"], "derivative=12.000000999998 truncation-probe=0.000000999998"),
    (["ph", "0.001"], "pH=3 classification=acidic"),
    (["dilute", "2", "0.5", "0.25"], "final-volume=4 L solvent-to-add=3.5 L"),
    (["relativity", "0.6"], "gamma=1.25 time-dilation=1.25 length-factor=0.8"),
    (["decibel-power", "100"], "20 dB"),
    (["blackbody", "5778"], "peak-wavelength=501.51816458982347 nm band=visible"),
    (["kinetic-sensitivity", "2", "3"], "energy=9 J elasticity[mass]=1 elasticity[speed]=2"),
]

CONTAINS_CASES = [
    (["claim-card", "projectile", "20", "45", "9.80665"], [
        "JACKAL CLAIM CARD v1",
        "model=ideal-projectile",
        "assumptions=same elevation; vacuum; constant gravity; point mass",
        "observed.range=40.78864851911713 m",
        "sensitivity.speed=2 sensitivity.gravity=-1",
        "non-claims=no drag; no wind; no terrain; no uncertainty inferred",
        "canonical=jackal-claim-v1|ideal-projectile|speed=20.0|angle-deg=45.0|gravity=9.80665|",
        "fingerprint.sha256=",
    ]),
    (["integrate", "x^2", "0", "3", "100"], [
        "integral=9 ",
        "method=simpson panels=100",
        "richardson-error-estimate=",
    ]),
    (["integrate", "sin(x)", "0", "3.141592653589793", "200"], [
        "integral=2.000000000",
        "method=simpson panels=200",
        "richardson-error-estimate=",
    ]),
    (["derivative", "x^3", "2", "0.001"], [
        "derivative=12.0000002",
        "method=central-difference step=0.0005",
        "richardson-probe=",
    ]),
    (["solve", "x^2-2", "1", "2"], [
        "root=1.414213562373095",
        "method=bisection",
        "residual=",
    ]),
    # Richardson-extrapolated verification must pass stiff-but-correct rules that
    # the bare fixed-step check refused (rule proven sympy-equal)
    (["diff", "cos(exp((x^3)))", ], [
        "d/dx[cos(exp((x^3)))] = -(sin(exp(x^3))*(exp(x^3)*(3*x^2)))",
        "verified=numeric points=5",
    ]),
    (["diff", "x/x"], [
        "d/dx[x/x] = 0",
        "domain-caveat=",
        "verified=numeric",
    ]),
    (["integrate", "x^3-2*x", "0", "2", "100"], [
        "assurance=estimate-not-bound(grid-limited)",
    ]),
    # The narrow-Gaussian that beat fixed-grid Simpson by 256x must now resolve
    # (truth: sqrt(pi)/1000 = 0.0017724538509055...)
    (["integrate-adaptive", "exp(0-1000000*(x-0.1225)^2)", "0", "1", "1e-9"], [
        "integral=0.00177245385",
        "method=adaptive-simpson",
        "assurance=refuses-when-unconverged",
    ]),
    # Oscillatory case (exact symbolic truth 0.009998741052161843; a field probe's
    # reference once claimed -0.0049958 — the probe was wrong, the engine right)
    (["integrate-adaptive", "sin(100*x)*exp(-x)", "0", "10", "1e-10"], [
        "integral=0.00999874105",
        "method=adaptive-simpson",
    ]),
    (["integrate-adaptive", "x^2", "0", "3", "1e-12"], [
        "integral=9 ",
        "achieved-error-estimate=0 ",
    ]),
    # Symbolic differentiation: every derivative self-verifies numerically
    (["diff", "x^2"], ["d/dx[x^2] = 2*x", "verified=numeric"]),
    (["diff", "x^2*sin(x)"], ["2*x*sin(x)+x^2*cos(x)", "verified=numeric"]),
    (["diff", "x^x"], ["x^x*(ln(x)+1)", "verified=numeric"]),
    (["diff", "sqrt(x)"], ["1/(2*sqrt(x))", "verified=numeric"]),
    (["diff", "5"], ["d/dx[5] = 0", "verified=numeric points=5"]),
]

# Symbolic oracle: sympy independently differentiates each input; JACKAL's
# printed derivative must agree with sympy's numerically at sample points.
SYMPY_DIFF_CASES = [
    "x^2*sin(x)",
    "x/(1+x^2)",
    "exp(x)*ln(x)",
    "x^x",
    "atan(x)*x",
    "cbrt(x)+sqrt(x)",
    "atan2(x,2)",
    "hypot(x,3)",
    "log10(x)*x",
    "tan(x)/x",
]

# Exact-rational oracle: sympy evaluates each expression exactly; JACKAL's
# exact= field must match sympy's canonical rational string.
RAT_ORACLE_CASES = [
    "123456789123456789/987654321987654321 + 1/3",
    "355/113 - 22/7",
    "(1/7 + 1/11 + 1/13)^3",
    "0.1 + 0.2 + 0.3",
    "999999999999999999999/1000000000000000000000 + 1/1000000000000000000000",
]

# Exact-integer engine: expected values computed HERE by Python's arbitrary
# precision at runtime — an independent oracle, not author-transcribed constants.
ORACLE_CASES = [
    (["big-fact", "100"], str(math.factorial(100))),
    (["big-fact", "1000"], str(math.factorial(1000))),
    (["big-ncr", "100", "50"], str(math.comb(100, 50))),
    (["big-ncr", "1000", "500"], str(math.comb(1000, 500))),
    (["big-pow", "2", "512"], str(2**512)),
    (["big-pow", "123456789", "100"], str(123456789**100)),
    (["big-add", "999999999999999999999999", "1"], str(10**24)),
    (["big-mul", "123456789012345678901234567890", "987654321098765432109876543210"],
     str(123456789012345678901234567890 * 987654321098765432109876543210)),
]

# Adversarial cases: each MUST fail closed (nonzero exit) with the named reason on stderr.
FAIL_CASES = [
    (["ncr", "67", "33"], "nCr overflow"),
    (["ncr", "68", "34"], "nCr overflow"),
    (["shl", "1", "64"], "shift count must be within 0..63"),
    (["shr", "1", "-1"], "shift count must be within 0..63"),
    (["div", "1", "0"], "division by zero has no finite result"),
    (["fact", "21"], "overflows i64"),
    (["fact", "-1"], "undefined for negative"),
    (["convert", "1", "kg", "m"], "dimension-mismatched conversion"),
    (["matrix2", "1", "2", "2", "4"], "singular matrix has no inverse"),
    (["relativity", "1"], "relativity beta requires"),
    (["ph", "-1"], "hydrogen concentration must be positive"),
    (["quadratic", "0", "1", "2"], "coefficient a must be nonzero"),
    # Expression engine must fail closed on malformed or non-finite input
    (["eval", "2++2"], "expression error"),
    (["eval", "(2+3"], "expected ')'"),
    (["eval", "sin()"], "expects 1 argument"),
    (["eval", "bogus(2)"], "unknown function"),
    (["eval", "x+1"], "variable x is only bound"),
    (["eval", "1/0"], "division by zero"),
    (["eval", "7%0"], "modulo by zero"),
    (["eval", "sqrt(0-1)"], "NaN"),
    (["eval", "10^400"], "non-finite"),
    (["eval", "1.2.3"], "unsupported character"),
    (["eval", ""], "empty expression"),
    (["solve", "x^2+1", "0", "1"], "sign change"),
    (["integrate", "x", "0", "1", "7"], "even panel count"),
    # Non-finite admission. A "nan"/"inf" literal is refused at INGESTION by
    # strict_float ("not a finite number"), before any downstream gate. A finite
    # input that PRODUCES inf mid-computation (1/0, x/0) is caught downstream
    # ("non-finite value"). Both fail closed; the messages differ by where.
    (["add", "nan", "1"], "not a finite number"),
    (["molarity", "1", "0"], "non-finite value"),
    (["kinetic", "nan", "3"], "not a finite number"),
    (["claim-card", "projectile", "nan", "45", "9.8"], "not a finite number"),
    # rounded() once laundered inf into plausible finite garbage (9223372.036854776%)
    (["percent-error", "5", "0"], "non-finite value"),
    # Strict ingestion: the language's lenient parse_float/parse_int coerced
    # garbage to 0 (add abc 5 -> 5; fact abc -> 1; hex 12abc -> 0x0). Every CLI
    # number now enters via strict_float/strict_int and refuses.
    (["add", "abc", "5"], "not a valid number"),
    (["fact", "abc"], "not a valid integer"),
    (["hex", "12abc"], "not a valid integer"),
    (["gcd", "4.5", "6"], "not a valid integer"),
    (["stats", "1", "2", "three"], "not a valid number"),
    (["convert", "xyz", "km", "m"], "not a valid number"),
    (["add", "inf", "1"], "not a finite number"),
    # The simplifier must not fold literal-undefined forms (0/0 once returned 0
    # while eval/rat correctly refused — the three lanes must agree)
    (["diff", "0/0"], "literal division by zero"),
    (["diff", "(0/0)*x"], "literal division by zero"),
    (["diff", "ln(0)"], "literal division by zero"),
    # Adaptive integration must REFUSE rather than print unearned confidence
    (["integrate-adaptive", "cos(1/(x+0.000001))", "0", "1", "1e-12"], "below resolvable scale"),
    (["integrate-adaptive", "1/x", "0", "1", "1e-9"], "division by zero"),
    (["integrate-adaptive", "x", "0", "1", "0"], "tolerance must be positive"),
    # Exact-integer engine and worksheet must fail closed
    (["big-fact", "10001"], "compute budget"),
    (["big-fact", "-1"], "big-fact requires 0 <= n <= 10000"),
    (["big-ncr", "5", "9"], "nCr requires 0 <= r <= n"),
    (["big-pow", "2", "10001"], "capped at 10000"),
    (["big-mul", "12x", "3"], "decimal digits only"),
    (["worksheet", "pi = 3"], "reserved name"),
    (["worksheet", "zz + 1"], "unknown identifier"),
    (["worksheet", ""], "no statements"),
    (["worksheet", "a = 1/0"], "division by zero"),
    # Symbolic and exact-rational engines must fail closed
    (["diff", "abs(x)"], "not differentiable"),
    (["diff", "floor(x)"], "not differentiable"),
    (["diff", "x % 2"], "discontinuous"),
    (["diff", "min(x,1)"], "not differentiable"),
    (["diff", "bogus(x)"], "unknown function"),
    (["rat", "1/0"], "exact division by zero"),
    (["rat", "1/(2/2-1)"], "exact division by zero"),
    (["rat", "sin(1)"], "exact mode supports"),
    (["rat", "pi"], "exact mode supports"),
    (["rat", "2^0.5"], "integer exponent"),
]


def run(args: list[str]) -> subprocess.CompletedProcess[str]:
    out = OUT_ROOT / (args[0] + "-" + str(len(args)))
    return subprocess.run(
        [str(PIN), "run", str(APP), "--out", str(out), "--", *args],
        text=True,
        capture_output=True,
        timeout=30,
    )


def main() -> int:
    if not PIN.is_file():
        print(f"FAIL instrument missing: {PIN}")
        return 2
    if not APP.is_file():
        print(f"FAIL implementation missing: {APP}")
        return 1

    failures = 0
    for args, expected in CASES + ORACLE_CASES:
        result = run(args)
        actual = result.stdout.strip()
        ok = result.returncode == 0 and actual == expected
        print(f"{'PASS' if ok else 'FAIL'} {' '.join(args)} => {actual!r}")
        if not ok:
            failures += 1
            if result.stderr:
                print(result.stderr.strip(), file=sys.stderr)
    for args, needles in CONTAINS_CASES:
        result = run(args)
        actual = result.stdout.strip()
        missing = [needle for needle in needles if needle not in actual]
        ok = result.returncode == 0 and not missing
        print(f"{'PASS' if ok else 'FAIL'} {' '.join(args)} contains {len(needles) - len(missing)}/{len(needles)}")
        if not ok:
            failures += 1
            print(f"missing={missing!r}", file=sys.stderr)
            if result.stderr:
                print(result.stderr.strip(), file=sys.stderr)
    for args, needle in FAIL_CASES:
        result = run(args)
        ok = result.returncode != 0 and needle in result.stderr
        print(f"{'PASS' if ok else 'FAIL'} {' '.join(args)} fails closed ({needle!r})")
        if not ok:
            failures += 1
            print(f"rc={result.returncode} stderr={result.stderr.strip()!r}", file=sys.stderr)

    import sympy
    x = sympy.Symbol("x")
    ns = {
        "x": x, "ln": sympy.log,
        "log10": lambda u: sympy.log(u, 10), "log2": lambda u: sympy.log(u, 2),
        "cbrt": sympy.cbrt, "hypot": lambda a, b: sympy.sqrt(a**2 + b**2),
        "atan2": sympy.atan2, "exp": sympy.exp, "sin": sympy.sin, "cos": sympy.cos,
        "tan": sympy.tan, "asin": sympy.asin, "acos": sympy.acos, "atan": sympy.atan,
        "sqrt": sympy.sqrt,
    }
    for source in SYMPY_DIFF_CASES:
        result = run(["diff", source])
        ok = result.returncode == 0
        detail = ""
        if ok:
            line = result.stdout.strip().split("\n")[0]
            jackal_text = line.split(" = ", 1)[1]
            expected_diff = sympy.diff(sympy.sympify(source.replace("^", "**"), locals=ns), x)
            got = sympy.sympify(jackal_text.replace("^", "**"), locals=ns)
            delta = got - expected_diff
            for point in (0.31, 0.77, 1.42):
                magnitude = abs(complex(delta.evalf(subs={x: point})))
                if not (magnitude < 1e-8):
                    ok = False
                    detail = f" delta({point})={magnitude}"
        print(f"{'PASS' if ok else 'FAIL'} diff {source} == sympy{detail}")
        if not ok:
            failures += 1
    for source in RAT_ORACLE_CASES:
        result = run(["rat", source])
        ok = result.returncode == 0
        detail = ""
        if ok:
            fields = [f for f in result.stdout.strip().split() if f.startswith("exact=")]
            exact = fields[0][6:] if fields else "?"
            # NOTE: no nsimplify here — it approximates to nearby "nice" rationals
            # (it once turned the true 150891632/329218107 into 11/24) and would
            # corrupt the oracle. sympify(rational=True) alone is exact.
            expected = sympy.sympify(source.replace("^", "**"), rational=True)
            ok = exact == str(expected)
            detail = f" got={exact} want={expected}"
        print(f"{'PASS' if ok else 'FAIL'} rat {source} == sympy{'' if ok else detail}")
        if not ok:
            failures += 1
    total = (len(CASES) + len(ORACLE_CASES) + len(CONTAINS_CASES) + len(FAIL_CASES)
             + len(SYMPY_DIFF_CASES) + len(RAT_ORACLE_CASES))
    print(f"TOTAL {total - failures}/{total}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
