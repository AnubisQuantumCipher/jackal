# JACKAL CALC — CLAIM-AWARE STEM ENGINE

JACKAL is a deterministic, offline STEM engine written in **Anubis Safe mode**. It does not try
to win by adding another wall of buttons. It treats a serious calculation as a bounded scientific
claim: value, units, uncertainty, method, assumptions, sensitivity, residual, non-claims, and a
reproducible fingerprint where applicable.

Every product model, formula, validation rule, unit policy, algorithm, formatter, command route,
claim-card generator and executable invariant is in `jackal_calc.anb`. Python is only an external
black-box launcher used to compare observed stdout.

## Research basis

See [`RESEARCH.md`](RESEARCH.md) for the primary-source comparison against TI-Nspire CX II CAS,
Qalculate!, Soulver and SpeedCrunch. JACKAL does **not** claim parity with a general CAS,
arbitrary-precision-float engine, or interactive graphing system. Its differentiated implemented
surface is claim-aware and measurement-aware computation.

## Why a calculator, in the age of frontier AI

Language models are demonstrably unreliable at the arithmetic layer. OpenAI's own GSM8K
repository states that "our models frequently fail to accurately perform calculations" and
mitigated it by training models to call a calculator ([GSM8K README](https://github.com/openai/grade-school-math);
[Cobbe et al. 2021](https://arxiv.org/abs/2110.14168)). The failure is structural, not
incidental: transformers solve multi-digit arithmetic by pattern-matching rather than
systematic computation ([Dziri et al. 2023](https://arxiv.org/abs/2305.18654)). The winning
paradigm is delegation — offloading computation to a deterministic runtime beat chain-of-thought
by 15 absolute points on GSM8K ([PAL, Gao et al. 2022](https://arxiv.org/abs/2211.10435));
models can teach themselves to call calculator APIs ([Toolformer, Schick et al. 2023](https://arxiv.org/abs/2302.04761));
and structured tool use is now a first-class production interface
([Anthropic tool-use docs](https://platform.claude.com/docs/en/docs/agents-and-tools/tool-use/overview)).

So the calculator an AI needs is not more buttons. It is the properties JACKAL implements:

- **Determinism** — identical input, byte-identical output; claim cards carry SHA-256 fingerprints.
- **Exactness flags** — `rat` and `big-*` results are exact; `approx=` is labeled IEEE f64;
  the single most common downstream error is a model treating a truncated decimal as exact.
- **Labeled error estimates** — integration and differentiation ship Richardson estimates
  tagged `assurance=estimate-not-bound(grid-limited)`: they are heuristic, and a feature narrower
  than the grid can evade both grids and produce a confident wrong answer (verified: a
  width~0.0007 Gaussian peak on a 100-panel grid underestimated its own error ~256×). Bisection
  ships residuals; symbolic derivatives ship their own numeric verification line. Only the
  `rat`/`big-*` lanes are exact.
- **Echoed parse** — `rat` echoes `parsed=`, `diff` echoes `d/dx[input]`: the dominant failure
  at the model-tool boundary is transcription, not computation, and the echo lets the caller
  confirm the engine evaluated the expression it intended.
- **Fail-closed typed errors** — no silent NaN, no wraparound, no clamping; every domain
  violation is a named refusal on stderr with nonzero exit.

## Run

```bash
cd /Users/sicarii/Desktop/jackal-calc
./jackal help
./jackal self-test
```

`./jackal` prefers the checked native ARM64 artifact `jackal-native`; set
`JACKAL_FORCE_SOURCE=1` to execute through the pinned Anubis runner during development.

## The unusual part: calculation claim cards

```bash
./jackal claim-card projectile 20 45 9.80665
```

The Anubis program emits:

- canonical model identity;
- typed inputs and units;
- explicit assumptions;
- observed outputs;
- dimensionless sensitivity elasticities;
- explicit non-claims;
- SHA-256 fingerprint of canonical model inputs and results.

This does not magically prove the physical model. It makes the model boundary inspectable and the
exact calculation reproducible.

## Expression engine

JACKAL evaluates arbitrary arithmetic expressions with an explicit, documented grammar —
tokenizer, recursive-descent parser, and evaluator all written in Anubis:

```bash
./jackal eval "2+3*sin(pi/6)^2"
./jackal integrate "sin(x)" 0 3.141592653589793 200   # general Simpson + Richardson error estimate
./jackal derivative "x^3" 2 0.001                     # central difference + Richardson probe
./jackal solve "x^2-2" 1 2                            # bisection + residual, requires a sign change
```

Grammar: `+ - * / %`, `^` (power, right-associative), unary minus (binds looser than `^`,
so `-3^2 = -9`, the calculator convention), parentheses, function calls, and comma-separated
arguments. Functions: `sin cos tan asin acos atan sqrt cbrt ln log10 log2 exp abs floor ceil
round trunc` (one argument) and `hypot pow atan2 min max` (two). Constants: `pi e tau c g0 h
na kb r`. The variable `x` is bound only inside `integrate`/`derivative`/`solve`.

## Symbolic differentiation — that verifies itself

`diff` parses the expression to an AST, differentiates symbolically, simplifies conservatively,
and then **refuses to print a derivative that fails its own numeric check**: the result is
compared against a central difference (h = 1e-5, the optimal cube-root-of-epsilon scale for
f64) at sample points, skipping points outside the domain.

```bash
./jackal diff "x^2*sin(x)"
# d/dx[x^2*sin(x)] = 2*x*sin(x)+x^2*cos(x)
# verified=numeric points=5 max-rel-dev=0.00000000008517730964996417 tolerance=0.0001

./jackal diff "x^x"
# d/dx[x^x] = x^x*(ln(x)+1)
```

Rules cover `+ - * / ^` (constant and general exponents via ln), `sin cos tan asin acos atan
sqrt cbrt ln log10 log2 exp hypot atan2`. Non-differentiable functions (`abs floor ceil round
trunc min max`, `%`) fail closed rather than guess. In the black-box suite, every printed
derivative is additionally cross-checked against sympy as an independent symbolic oracle.

## Exact rational arithmetic

`rat` evaluates in exact big-rational arithmetic (big-integer numerator/denominator,
gcd-reduced canonical form, sign flag, den > 0). Decimal literals become exact rationals —
which makes float error *visible*:

```bash
./jackal rat "0.1 + 0.2"
# parsed=0.1+0.2 exact=3/10 approx=0.30000000000000004

./jackal rat "123456789123456789/987654321987654321 + 1/3"
# parsed=... exact=150891632/329218107 approx=0.4583333321942708
```

The `exact=` field is the truth; `approx=` is the same expression through IEEE f64, printed so
the discrepancy is inspectable. Supports `+ - * /`, `^` with integer exponents (negative
allowed), parentheses, and decimals/scientific notation. Everything else fails closed.

## A calculation with a zero-knowledge receipt

JACKAL's integer core has been run inside the RISC0 zkVM through Anubis's proving backend.
[`proofs/jackal_proof_guest.anb`](proofs/jackal_proof_guest.anb) re-executes the gcd,
exact-binomial, primality and lcm invariants inside the guest and commits how many held; the
resulting receipt ([`proofs/zk-receipt/`](proofs/zk-receipt/VERIFY.md)) binds the output
(journal = 8, all invariants) to the exact program (ImageID derived from the guest ELF).
Anyone can re-verify with `anubis verify-receipt` — no trust in this host or author required.
Flipping a single byte of the receipt makes verification fail; that negative control was
performed and recorded. No mainstream calculator ships a cryptographic proof that its
arithmetic core does what it claims.

## Worksheet mode

Semicolon-separated statements with persistent variables, Soulver-style:

```bash
./jackal worksheet "a = 5; b = a^2; a+b"
# a = 5
# b = 25
# 30
```

Assignments print `name = value`; bare expressions print their value; reserved names
(constants, functions) cannot be shadowed and fail closed.

## Exact integer engine

Arbitrary-precision nonnegative integer arithmetic implemented in Anubis as base-1e9 limb
lists — every result exact, never rounded:

```bash
./jackal big-fact 1000        # all 2568 digits, exact
./jackal big-ncr 1000 500
./jackal big-pow 2 512
./jackal big-mul 123456789012345678901234567890 987654321098765432109876543210
./jackal big-add 999999999999999999999999 1
```

Compute budgets fail closed: `big-fact`/`big-ncr` accept n <= 10000, `big-pow` exponents
<= 10000 on bases <= 1000 digits. The legacy `fact`/`ncr` stay on the documented i64
register model; the `big-` lane is the exact model.

## Command atlas

| World | Commands |
|---|---|
| Trust and metrology | `claim-card self-test measure-mul uncertain-ohm kinetic-sensitivity` |
| Expression engine | `eval integrate derivative solve` |
| Symbolic | `diff` (self-verifying d/dx) |
| Exact rationals | `rat` (canonical p/q + labeled f64 approx) |
| Worksheet | `worksheet` (persistent variables across `;`) |
| Exact integers | `big-add big-mul big-pow big-fact big-ncr` |
| Numerical laboratory | `matrix2 solve2 integrate-x2 derivative-x3` |
| Mathematics | `quadratic lerp percent-error ncr gcd lcm fact prime` |
| Vector algebra | `dot cross norm3` |
| Data science | `stats describe linreg` |
| Unit laboratory | `convert` for length, mass, temperature, pressure and energy |
| Electrical engineering | `ohm parallel-r uncertain-ohm` |
| Mechanics and space | `kinetic projectile orbit relativity` |
| Physics and chemistry | `ph dilute photon blackbody ideal-gas molarity decibel-power` |
| Programmer | `hex bin band bor bxor shl shr` |
| Scientific core | `add sub mul div pow sqrt cbrt sin cos tan sin-deg hypot ln log10 exp` |

## Examples

```bash
# Measurements and propagated worst-case relative uncertainty
./jackal measure-mul 12 0.1 3 0.05 m2
./jackal uncertain-ohm 12 0.1 3 0.05

# Linear algebra with residual reporting
./jackal matrix2 1 2 3 4
./jackal solve2 2 1 5 1 -1 1

# Numerical methods with method metadata/error probes
./jackal integrate-x2 0 3 100
./jackal derivative-x3 2 0.001

# Chemistry and physics
./jackal ph 0.001
./jackal dilute 2 0.5 0.25
./jackal relativity 0.6
./jackal blackbody 5778

# Sensitivity: K = 1/2 m v²
./jackal kinetic-sensitivity 2 3
```

## Verification

```bash
ANUBIS=/Users/sicarii/anubis-lang/vm/pins/anubis-51f4a964347a
$ANUBIS check jackal_calc.anb --out /tmp/jackal-check
./jackal self-test
ANUBIS_BIN=$ANUBIS python3 tests/test_calculator.py
```

## Honest boundaries

- Numeric calculations use Anubis's current IEEE-754 floating-point runtime, not arbitrary precision.
- `ncr` computes exactly every binomial coefficient representable in i64 (gcd-reduced multiply)
  and fails closed at the i64 boundary rather than wrapping; `C(66,33)` is the largest central case.
- `shl`/`shr` use the i64 two's-complement register model; shift counts outside 0..63 fail closed.
- `div` by zero fails closed rather than printing IEEE infinity.
- The claim card prints its canonical preimage (`canonical=`), so the SHA-256 fingerprint is
  recomputable with any external tool; Anubis interpolates floats in default form (e.g. `20.0`).
- Domain violations abort through the Anubis runtime's panic channel: nonzero exit with the reason
  on stderr, wrapped in a runtime trace. Fail-closed, not pretty-printed.
- Every CLI number enters through strict ingestion (`strict_float`/`strict_int` over the
  language's `parse_*_opt`): malformed text (`abc`, `12abc`, `4.5` where an integer is required)
  and non-finite literals (`nan`, `inf`) are refused at the boundary instead of being leniently
  coerced to 0 — closing an entire silent-wrong-value class (`add abc 5` once printed `5`).
- The `diff` release gate verifies against Richardson-extrapolated central differences
  (h and h/2, combined to cancel the h² term), so stiff-but-correct derivatives such as
  `cos(exp(x^3))` pass while a mutation-tested wrong rule (sin for cos) is still refused.
- The adversarial campaign (`python3 tests/campaign.py`, seeded) fuzzes every lane against
  Python/SymPy/Fraction oracles — ~990 cases across eval/precedence/rat/bigint/diff/atlas/
  hostile/cross-lane/determinism — and must report zero findings.
- Measurement multiplication/division uses conservative first-order addition of relative absolute
  uncertainties; it does not infer distributions, covariance or confidence levels.
- The expression engine is numeric, not symbolic: no CAS, no simplification. Expression
  arithmetic is IEEE-754 f64; only the `big-` integer lane is arbitrary precision. Numbers
  require a leading digit (`0.5`, not `.5`). Expression division/modulo by zero and non-finite
  results (NaN/inf) fail closed — deliberately stricter than the underlying language's
  documented IEEE leniency.
- The exact integer lane covers nonnegative integers on its command surface; internally it also
  implements comparison, subtraction, binary GCD, and schoolbook base-10 long division
  (correctness-first, compute-budget capped) to power the rational engine. Expected test values
  are generated at test time by Python and sympy — independent oracles.
- The simplifier is conservative and adopts documented conventions: `u^0 -> 1` and `0^0 -> 1`
  follow the C/IEEE pow() library convention (not a mathematical identity); `u/u -> 1`,
  `u-u -> 0`, `0*u -> 0` hold wherever `u` is defined (measure-zero caveats at singularities).
  The numeric self-verification still checks every printed derivative.
- `diff` differentiates with respect to `x`; other free variables are treated as constants and
  bound to 1.5 during the numeric verification pass. Symbolic simplification is minimal — no
  trig identities, no factoring, no collection.
- `rat` exponents are capped at 10000 (compute budget); non-rational operations (functions,
  constants, `%`) fail closed rather than approximate.
- Worksheet state lives for one invocation; there is no persistent session file.
- Richardson values are error *estimates* from grid refinement, not proven bounds — both grids
  can miss structure narrower than the panel width, so agreement is necessary but not sufficient.
  Fixed-grid `integrate` says so (`assurance=estimate-not-bound(grid-limited)`). For integrands
  with localized or fine structure, use `integrate-adaptive "expr" a b tol`: recursive adaptive
  Simpson over a 32-interval seed that subdivides until each region meets its local tolerance and
  **refuses** (budget, depth, or f64-resolution exhaustion) rather than print unearned confidence.
  The narrow-Gaussian case that beat the fixed grid by 256× resolves to 12 significant figures
  under the adaptive lane. The estimate is still local, not a proven bound: structure below
  seed/f64 resolution can evade even adaptivity. Bisection requires a bracketing sign change and
  reports its residual; it correctly refuses even-multiplicity roots.
- A calibration note from adversarial field testing: on `sin(100*x)*exp(-x)` over [0,10], a
  probe's independent reference claimed the sign was wrong — exact symbolic integration proved
  the *reference* wrong and JACKAL right, with the printed Richardson estimate (2.1865e-7)
  matching the true error (2.1857e-7) to 0.04%. Trust claims here are tested in both directions.
- All numeric output routes through a finite gate: NaN/inf reaching any printer is a fail-closed
  panic, and claim cards additionally refuse non-finite inputs at admission — a fingerprint
  authenticates bytes, it is not an accept verdict.
- `diff` prints a `domain-caveat=` line whenever simplification applied a where-defined
  convention (u/u, u−u, u^0, 0·u), because the emitted derivative does not carry the original
  expression's domain restrictions.
- The legacy `integrate-x2`/`derivative-x3` commands are kept for compatibility; `integrate`,
  `derivative`, and `solve` accept arbitrary expressions in `x`.
- `describe` reports population variance and standard deviation.
- Orbital output assumes an ideal circular two-body orbit.
- Projectile output assumes equal launch/landing elevation, vacuum, constant gravity and a point mass.
- Claim-card hashes bind canonical bytes; they do not prove that the physical assumptions match reality.
- Targeted checker/runtime evidence is not a universal Anubis soundness or calculator-correctness claim.
