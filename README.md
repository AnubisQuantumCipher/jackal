# JACKAL CALC — MATHEMATICAL EVIDENCE KERNEL

JACKAL is a deterministic, offline **mathematical evidence kernel** — an epistemic claim
compiler for Hermes and machine consumers that is also a full STEM calculator. Its one
unusual property: **every answer tells you what kind of answer it is** — `exact`, `bounded`
(a conditional interval enclosure), `formal-bounded` (a proved-checker-accepted enclosure),
`checked`, `estimated`, or `model-based` — and what it would take to trust it. When JACKAL
cannot stand behind a number, it refuses with a named reason instead of printing something
plausible.

**New here? Start with [GETTING-STARTED.md](GETTING-STARTED.md)** — install (released binary
for Apple Silicon macOS, or build from source with an Anubis compiler), first commands, and
how to read the trust labels. License: [MIT](LICENSE).

JACKAL is written in **Anubis Safe mode**. It does not try to win by adding another wall of
buttons. It treats a serious calculation as a bounded scientific claim: value, units,
uncertainty, method, assumptions, sensitivity, residual, non-claims, and a reproducible
fingerprint where applicable.

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
- **A five-tier assurance ladder for numerical integration** —
  `integrate` prints a Richardson *estimate* tagged `assurance=estimate-not-bound(grid-limited)`
  (heuristic; a feature narrower than the grid can evade both grids — verified: a width~0.0007
  Gaussian peak on a 100-panel grid underestimated its own error ~256×);
  `integrate-adaptive` prints a *local estimate with refusal semantics* (it refuses rather than
  print unearned confidence, but agreement is still not a bound);
  `integrate-bound` prints a **conditional enclosure** under the stated f64/libm model;
  `jackal-gaussian-release` adds a distinct **zero-libm formal enclosure** for checker-accepted
  canonical `exp(-A*(x-mu)^2)` requests and refuses every unsupported formal request without
  downgrade (see "Formal Gaussian integration" below); and `jackal-int-cert-release` (v1.7.0)
  emits a **Lean-checked composed enclosure** over the certified fragment — the compiled proved
  checker re-checks the entire subdivision tree (theorem `int_cert_sound`) while `integrate-bound`
  itself stays conditional/`bounded`. Bisection ships residuals; symbolic derivatives ship their own
  numeric verification line. Only the `rat`/`big-*` lanes are exact.
- **Machine-readable epistemic classes** — metadata-bearing lanes print `status=` as the first
  field: `exact` (rat), `bounded` (integrate-bound), `formal-bounded` (proved range/Gaussian
  release wrappers, and the certified composed-integral lane `integrate-bound-cert` via
  `jackal-int-cert-release` — proved composed enclosure, theorem `int_cert_sound`), `checked` (diff),
  `estimated` (integrate, integrate-adaptive, derivative, solve, integrate-x2, derivative-x3),
  `model-based` (claim-card). `jackal maturity` prints the full graded command inventory —
  every lane's class, oracle, evidence, and known residual — so strong evidence in one lane
  cannot silently inflate trust in another.
- **Echoed parse** — `rat` echoes `parsed=`, `diff` echoes `d/dx[input]`: the dominant failure
  at the model-tool boundary is transcription, not computation, and the echo lets the caller
  confirm the engine evaluated the expression it intended.
- **Fail-closed typed errors** — no silent NaN, no wraparound, no clamping; every domain
  violation is a named refusal on stderr with nonzero exit.

## Run

```bash
git clone https://github.com/AnubisQuantumCipher/jackal-calc.git
cd jackal-calc
./jackal help
./jackal self-test
```

The `./jackal` launcher prefers a prebuilt native artifact (`jackal-native`) and otherwise
runs the Anubis source through a compiler it resolves in this order:

1. `$ANUBIS_BIN` — an explicit path you set;
2. the pinned compiler at `$HOME/anubis-lang/vm/pins/anubis-a733565f237d`, if present;
3. an `anubis` executable on your `PATH`.

If none is found it prints exactly how to fix it and exits non-zero — it never fails silently or
misleadingly. `jackal-native` is **not** committed (it is a build artifact; its SHA-256 is
sealed in [`PROVENANCE.md`](PROVENANCE.md)); obtain it from the public GitHub release
(Apple Silicon macOS), verify the release checksums and pinned identities, or build from
source (see below and [GETTING-STARTED.md](GETTING-STARTED.md)).

**Formal-release paths (v1.5.0).** `jackal-cert-release "<expr in x>" <lo> <hi> [formal-receipt.json]`
emits `status=formal-bounded` **only** when the shared
release validator (`tests/release_validate.py`)
confirms the whole bound chain: the exact request commitment, the exact `jackal-native`
evaluator identity, the pinned executables, and the proved checker's `ACCEPT`, TOCTOU stability,
and no status escalation.  Any break refuses with a stable class, never a bounded fallback.
The bundled `plugin/hermes` adapter exposes the same release and verification
path.  See NON-CLAIMS.txt for the exact scope.  Formal-status *soundness* (an
accepted certificate implies a true enclosure) is Lean-proved; runtime
*provenance* (request/evaluator identity) is validator-enforced, not theorem-proved. See
[`PROVENANCE.md`](PROVENANCE.md) "Seal v1.5.0" for the receipts and preserved predecessor scars.

**The zero-libm transcendental fragment (v1.5.0).** Seven standalone release
wrappers emit pure-ℚ, Lean-checker-verified enclosures with **no libm on the
proof-decision path**; every producer is untrusted and every claim is
re-validated by the compiled proved checker `jackal_cert_check`:

| Wrapper | Admits | Domain | Strategy (all exact ℚ) |
|---|---|---|---|
| `jackal-sqrt-rat-release "sqrt(x)" lo hi` | `sqrt(x)` | `lo ≥ 0` | Newton square bracket (v1.4.0) |
| `jackal-exp-rat-release "exp(x)" lo hi` | `exp(x)` | all rationals (general-sign since v1.5.0) | Taylor partial + certified remainder; exact reciprocal for negatives |
| `jackal-ln-rat-release "ln(x)" lo hi` | `ln(x)` | `lo > 0` | inverse exponential bracket (`exp(out_lo) ≤ lo`, `hi ≤ exp(out_hi)`, decided in ℚ) |
| `jackal-sin-rat-release "sin(x)" lo hi` | `sin(x)` | midpoint within `[-1,1]` | Mathlib `sin_bound` midpoint Taylor + Lipschitz-1 widening |
| `jackal-cos-rat-release "cos(x)" lo hi` | `cos(x)` | midpoint within `[-1,1]` | Mathlib `cos_bound` midpoint Taylor + Lipschitz-1 widening |
| `jackal-atan-rat-release "atan(x)" lo hi` | `atan(x)` | all rationals | cap / tan-bracket / reciprocal strategies over 20-digit rational π bounds |
| `jackal-tanh-rat-release "1-2/(exp(2*x)+1)" lo hi` | the tanh-defining composite | `|x| ≤ 20` | 8-node zero-libm certificate DAG; constant-numerator division stays tight at any width |

`tanh` is not an engine grammar token: the wrapper admits the explicit
composite expression `1-2/(exp(2*x)+1)` (mathematically equal to `tanh(x)`),
the receipt binds that expression string, and the tanh reading is a
documented identity — never a checker claim.  Requests spelled `tanh(x)`
fail closed at parse in every lane.  Every unsupported expression refuses
without downgrade.  Documented enclosure-width residuals (soundness is never
affected): sin/cos point enclosures carry the fixed-degree Mathlib remainders
(`|m|⁵/100`, `|m|⁴·5/96`), and tan-bracketed `atan` endpoints near `|x| = 1`
are certified to ~5·10⁻²; ln/exp/sqrt/tanh brackets are tight (~10⁻⁹ or
better at defaults).  Arguments outside a fragment's stated domain refuse
with a named reason — sin/cos beyond `|midpoint| ≤ 1` (2πk argument
reduction is future work), ln at `lo ≤ 0`, tanh beyond `|x| ≤ 20`.
The separate `jackal-gaussian-release "exp(-A*(x-mu)^2)" <lo> <hi> <tolerance> <formal-receipt.json>`
path admits only canonical nonnegative rational tokens, a checker-verified positive rational
`scale` with `scale^2=A`, and a transformed interval containing `[-6,6]`. Its untrusted producer
emits exact-rational witness bytes; `jackal_gaussian_check` parses and recomputes them. The Lean
theorem `gaussian_integral_check_sound` proves that checker acceptance binds the source tokens and
encloses the requested real integral. It uses Mathlib's Gaussian-integral and pi-bound theorems,
a proved `exp(-36)` tail bound, and no platform `exp`/libm result. Unsupported formal integration
requests refuse with no fallback to `integrate-bound`.

**Formal receipt + Hermes plugin.** When the optional fourth path is supplied,
the wrapper emits a canonical `jackal-formal-receipt-v1` JSON receipt with
the certificate **embedded** (base64) and every field a downstream reverifier
needs: exact canonical request (including integration tolerance), exact enclosure,
producer/evaluator/checker/plugin identities, matching theorem id (`cert_check_sound` or
`gaussian_integral_check_sound`), Lean kernel axiom list, admitted
operator set, coverage-row ids, assumptions, non-claims, and an outer
`receipt_digest_sha256`. The independent verifier `tools/receipt_verify.py`
re-hydrates the embedded certificate and **re-runs the matching pinned Lean-proved
checker on this machine** — recomputing the outer digest alone is not
sufficient. The Hermes/MCP-style plugin (`plugin/hermes/jackal_hermes`) threads every
call through the same shared validator, the same formal-status gate, the same
pinned executables, and additionally bind the plugin's OWN bundle hash into the
receipt via `identities.plugin_sha256`. The Hermes plugin exposes thirty-four
tools — eleven formal (`jackal_range_bound`, `jackal_gaussian_integral`,
`jackal_integrate_bound_cert`,
`jackal_sqrt_rat_bound`, `jackal_exp_rat_bound`, `jackal_ln_rat_bound`,
`jackal_sin_rat_bound`, `jackal_cos_rat_bound`, `jackal_atan_rat_bound`,
`jackal_tanh_rat_bound`, `jackal_verify_receipt`), twenty-one weaker-lane
adapters (the seven numeric lanes `jackal_exact`, `jackal_evaluate`,
`jackal_diff`, `jackal_integrate`, `jackal_integrate_adaptive`,
`jackal_integrate_bound`, `jackal_solve`, and fourteen exact-CAS lanes from
`jackal_canon` through `jackal_prime_cert`) that thread through the pinned
evaluator with identity checks and return the engine's honest inventory-derived
epistemic class (`exact`/`checked`/`estimated`/`bounded`/`model-based`) with
`formal: false` — status inflation is structurally impossible — plus the two
v1.6.0 claim-kernel front doors (`jackal_claim`, `jackal_verify_bundle`; see
"The claim-bundle evidence kernel" below).

The eleven-category A→B→A mutation harness (`tests/cert_mutations_11.py`)
plus the receipt-semantic mutation harness (`tests/receipt_semantic_mutations.py`,
42/42 including the two §487 audit locks for U+2028 parser-differential
injection and `const_rounded` release-fragment admission, and the §490
v1.5.0 variant locks incl. the ln_rat→ln TCB-op smuggle) prove that every
trust-boundary gate — request/AST/enclosure/certificate/limits/formal-status/
checker/evaluator/outer-digest/stale-success/plugin-bundle — is load-bearing:
the mutation harness disables one governing gate (still-compiling), the poison
is admitted only under that disablement, and the exact pre-mutation bytes are
restored hash-verified before A(post). See `release/evidence/` for the durable
transcripts (`positive_corpus.jsonl`, `negative_controls.jsonl`,
`plugin_smoke.jsonl`, `mutations_11.json`, `receipt_semantic_mutations.json`,
`fail_closed_sweep.jsonl`, `gaussian_formal_v150.json` (v1.3.0 record preserved), and `aba_mutations.json`).

## Build from source

JACKAL is written in the [Anubis](https://github.com/AnubisQuantumCipher) language, so building or
running it from a clean checkout requires the Anubis compiler. There is no way around this: the
engine *is* Anubis source.

**1. Get an Anubis compiler.** Use the pinned build the committed engine was verified against
(`anubis-a733565f237d`; SHA-256 in `PROVENANCE.md`), or any Anubis toolchain that accepts
`anubis run <file> --out <dir> -- <args>`. The Anubis compiler is not yet publicly
distributed — without one, use the released `jackal-native` binary instead; the engine source
it was built from is this repo's `jackal_calc.anb`, and the build chain is sealed in
`PROVENANCE.md`.

**2. Point JACKAL at it** — either put `anubis` on your `PATH`, place the pin at
`$HOME/anubis-lang/vm/pins/anubis-a733565f237d`, or set `ANUBIS_BIN` explicitly:

```bash
export ANUBIS_BIN=/path/to/anubis
./jackal self-test          # first run compiles the engine, then runs it
./jackal eval "sqrt(2)*exp(sin(pi/7))"
```

**3. (Optional) produce a standalone native binary.** The first source run compiles a native
executable under the Anubis out-dir; copy it to `jackal-native` so later invocations skip the
compiler entirely:

```bash
ANUBIS_BIN=/path/to/anubis JACKAL_FORCE_SOURCE=1 JACKAL_OUT=./.build ./jackal self-test
cp ./.build/anubis_run ./jackal-native && chmod +x ./jackal-native
./jackal self-test          # now uses the native artifact, no Anubis needed
```

**Reproducibility — verified, byte for byte.** With the pinned compiler
`anubis-a733565f237d`, clean builds of the committed source are **fully byte-identical** —
same SHA-256 every time, linker UUID included (verified across repeated builds and differing
out-dir paths, including one containing spaces). Anyone holding the pin can rebuild
`jackal-native` and compare hashes against [`PROVENANCE.md`](PROVENANCE.md). The
nondeterminism in earlier pins (a randomized per-build package name feeding the crate-metadata
hash) was root-caused and fixed upstream on 2026-08-13; the diagnosis trail, including the
byte-deterministic transpile stage and `tests/content_hash.py` for segment-level comparison,
is preserved in `PROVENANCE.md`. `JACKAL_FORCE_SOURCE=1` always bypasses any prebuilt binary
and runs through the compiler; `JACKAL_OUT` overrides the scratch out-dir (default:
`$TMPDIR/jackal-calc-run`).

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
./jackal integrate-bound "sin(x)" 0 3.141592653589793 1e-9   # certified interval enclosure
./jackal-int-cert-release "sin(x)" 0 1 1/100 receipt.json   # Lean-checked composed integral enclosure (theorem int_cert_sound)
./jackal derivative "x^3" 2 0.001                     # central difference + Richardson probe
./jackal solve "x^2-2" 1 2         # bisection + residual + first-order root-error estimate
```

Grammar: `+ - * / %`, `^` (power, right-associative), unary minus (binds looser than `^`,
so `-3^2 = -9`, the calculator convention), parentheses, function calls, and comma-separated
arguments. Functions: `sin cos tan asin acos atan sqrt cbrt ln log10 log2 exp abs floor ceil
round trunc` (one argument) and `hypot pow atan2 min max` (two). Constants: `pi e tau c g0 h
na kb r`. The variable `x` is bound only inside `integrate`/`derivative`/`solve`.

## Certified enclosures — the tier above estimates

The 2026-08-13 adversarial campaign (1,402 cases against a frozen artifact) proved the
distinction that now defines this engine: JACKAL's Richardson estimates were *superbly
calibrated* (median actual-error/estimate ratio 0.99981 across 120 independently solved
oscillatory integrals) — and still not *bounds*, because a fixed grid cannot certify what it
never sampled. `integrate-bound` closes that gap with mathematics instead of sampling:

```bash
./jackal integrate-bound "exp(0-1000000*(x-0.1225)^2)" 0 1 1e-9
# status=bounded integral-enclosure=[0.0017724538498025575,0.0017724538524225815] ...
# — the same narrow off-grid Gaussian that silently beat fixed-grid Simpson by 256×
#   now carries a certified enclosure containing the true sqrt(pi)/1000·erf-term value

./jackal range-bound "sin(x)" 0 6.4
# status=bounded range-enclosure=[-1.000000000000001,1.000000000000001]
# assurance=certified-superset-of-range(outward-rounded-f64;libm<=2ulp-model;implementation-tested-not-mechanized)
```

How it works, and exactly what it claims:

- Every expression is evaluated in **outward-rounded interval arithmetic** over the AST:
  each operation's result interval is padded outward by 1e-15 relative + 1e-300 absolute
  (~4.5 ulp) — strictly more than the worst-case rounding of the operation that produced it.
  `sin`/`cos` ranges detect interior extrema with slack-widened critical-point tests (doubt
  can only *widen* the enclosure) and clamp to [-1,1]; `tan` refuses any interval that may
  contain a pole; division refuses any denominator interval containing zero.
- The integrator adaptively bisects; each accepted subinterval contributes a proven piece via
  the sharpest valid form: **Taylor-4 midpoint** `h·F(m) + h³/24·F″(m) + h⁵/1920·F⁗([a,b])`
  when the symbolic chain f…f⁗ interval-evaluates over the closed subinterval (which
  certifies C⁴ there — the derivative formulas come from the same `deriv()` that powers
  `diff`, simplified by a *sound* simplifier that never applies a where-defined convention),
  degrading to Taylor-2, then to the always-valid pure range form `h·F([a,b])`. All
  successful forms are enclosures, so they are intersected.
- Refusal is the answer whenever certification fails: budget (60000 subintervals), depth
  (60 levels), f64 resolution, domain hazards (`1/x` through zero, `ln` touching 0, `tan`
  poles), unknown identifiers, or a final width above the requested tolerance. The refusal
  names the reason.
- The residual trust assumptions are stated, not hidden: IEEE-754 correctly-rounded basic
  ops; math-library calls within 2 ulp (including argument reduction); and the
  implementation itself is *tested, not mechanized* — a seeded containment campaign
  (`tests/bound_campaign.py`) checks every printed enclosure against an independent
  symbolic-antiderivative oracle, and a differential gate (`tests/iv_differential.py`)
  checks every range enclosure against 40-digit point sampling and mpmath's independent
  interval arithmetic. The only fatal verdict in either is a bound that excludes the truth.
- **The model is machine-checked — universally quantified, conditionally stated.**
  [`proofs/lean/`](proofs/lean/) is a Lean 4 + Mathlib development (20 modules, ~6,200
  lines, 170+ theorems, zero `sorry`, flagship theorems axiom-audited to Lean's standard
  three) proving,
  over the stated rounding model: the pad-beats-rounding core; containment of every
  arithmetic interval op (add/sub/neg/mul/div, integer and negative powers, general powers
  on positive bases); the monotone-endpoint rule with exp/sqrt/log/arctan/arcsin/arccos
  instances; the exact ops (abs/min/max/floor-family/hypot/atan2); sin/cos range soundness
  across all widening branches; **conservativity of the float critical-point test** on the
  engine's parameter range (a maybe can only widen, never miss); bisection bracket soundness
  and the backward-error bound behind `solve`'s conditioning diagnostics; the float-midpoint
  containment chain; the Taylor-2/Taylor-4 midpoint enclosures (`h³/24` and `h⁵/1920` are
  theorems, not constants); a **deep-embedded composition theorem** (`runs_encloses`: *every*
  execution of the modeled evaluator core over *every* interval yields a true enclosure —
  all-quantifiers, no sampling, now with ~30 operators wired in); the
  **evaluability-certifies-smoothness chain**; and — implementation-correspondence bridge #1 —
  a **mechanized parser and lowerer** on one canonical syntax: `parse` mirrors the engine's
  recursive-descent grammar (determinism + structural rejection lemmas), `lower` mirrors the
  certified-lane simplifier with a proved **`lower_preserves_sem`** (lowering never changes the
  real semantics on the defined domain), and `parse_lower_denotes` / `parse_lower_encloses`
  compose them so the admitted *source string* — not just an abstract tree — is what the
  theorem covers.  Implementation-correspondence bridge #2: the engine's `range-bound-cert`
  command performs exact-rational interval evaluation and emits a canonical **evaluation
  certificate**; the compiled Lean checker `jackal_cert_check` — built *directly from the
  proved `checkCert`*, no `@[implemented_by]` on the trust path — verifies it, and the theorem
  `cert_check_sound` proves that acceptance mechanically **induces a `Runs` derivation**, hence
  a true enclosure under the named `ModelTCB`. The fail-closed `jackal-cert-release` gate emits
  `status=bounded` only when the checker accepts, so *an error in the actual evaluator causes
  refusal, never an unsupported certified release* — verified by a positive corpus, 30 negative
  controls (each failing for its intended semantic reason, `tests/cert_controls.py`), and an
  A→B→A tamper where a deliberately non-enclosing emitter is rejected then restored by hash
  (`tests/cert_tamper.sh`). The certified release fragment is the exact-ℚ operators +
  `sin`/`cos` + the six pure-ℚ checker strategies — **`sqrt`** (v1.4.0, `sqrt_rat`: Newton
  square bracket), **`exp`** (v1.4.1, `exp_rat`; general-sign since v1.5.0 §490 via the exact
  reciprocal identity), **`ln`** (v1.5.0, `ln_rat`: inverse exponential bracket), tight
  **`sin`/`cos`** (v1.5.0, `sin_rat`/`cos_rat`: Mathlib midpoint Taylor + Lipschitz-1,
  |midpoint| ≤ 1), and **`atan`** (v1.5.0, `atan_rat`: cap / tan-bracket / reciprocal over
  20-digit rational π bounds) — all with **NO libm TCB**; the remaining true-transcendentals
  (`tan`/`cbrt`/`asin`/`acos`/`log10`/`log2`/…) AND named constants (`pi`/`e`/`tau`) fail
  closed (const excluded 2026-08-15, §487-const audit — their value is bound only by the
  undischarged `ConstTCB` premise, not ℚ-decidable). What is *not* proven is enumerated in
  [`proofs/lean/JackalIv/Ledger.lean`](proofs/lean/JackalIv/Ledger.lean): libm meeting its
  2-ulp model; the still-fail-closed operators; the bigint/rational lanes (checked in-language by
  the Anubis SMT checker, outside this Lean scope); that the Anubis emitter faithfully produces
  its certificate (tested, not proven); `bound_step` release composition — now **mechanized for
  the certificate lane** (v1.7.0: theorem `int_cert_sound`, re-checked by the compiled
  `jackal_int_cert_check` on every `jackal-int-cert-release` receipt); and the one remaining
  bridge, source→native refinement, which remains **open and unclaimed**. The engine's
  printed `implementation-tested-not-mechanized` residual therefore stays, accurately: the
  *model* is proven for all inputs, `range-bound-cert` results carry a proof-checked witness, and
  the broader *implementation* is campaign-tested and differential-gated against the model.

`integrate-bound` is deliberately the slowest lane — certification costs evaluations. For a
fast heuristic with refusal semantics use `integrate-adaptive`; for raw speed use `integrate`
and treat the estimate as an estimate.

## Symbolic differentiation — numerically checked before release

`diff` parses the expression to an AST, differentiates symbolically, simplifies conservatively,
and then **refuses to print a derivative that fails its own numeric check**: the result is
compared against a central difference (h = 1e-5, the optimal cube-root-of-epsilon scale for
f64) at sample points, skipping points outside the domain. Sampled agreement is a check, not a
proof of identity — the output says so (`assurance=numeric-sample-check(not-proof-of-identity)`).

```bash
./jackal diff "x^2*sin(x)"
# d/dx[x^2*sin(x)] = 2*x*sin(x)+x^2*cos(x)
# status=checked check=numeric points=9 max-rel-dev=0.00000000005999646518118516 tolerance=0.0001 assurance=numeric-sample-check(not-proof-of-identity)

./jackal diff "x^x"
# d/dx[x^x] = x^x*(ln(x)+1)
```

The verifier validates its own instrument before it is allowed to veto: a sample point where
the h and h/2 central differences disagree beyond 1% of scale is a *broken probe*, not
evidence against the derivative — it is skipped and disclosed
(`skipped-unstable-probe=N`). The skip criterion never reads the symbolic candidate, so it
cannot launder a wrong rule through; wrong rules are still refused at every point where the
probe converges, and fewer than 3 usable points refuses outright. (Field-adjudicated
2026-08-13: a nested-tan composition was refused by the old verifier solely because
pole-adjacent probes diverged — `tan(tan(x))` now releases, and is sympy-cross-checked in the
suite.)

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
# status=exact parsed=0.1+0.2 exact=3/10 approx=0.30000000000000004

./jackal rat "123456789123456789/987654321987654321 + 1/3"
# status=exact parsed=... exact=150891632/329218107 approx=0.4583333321942708
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

## Exact algebra and number theory — certificate-bearing lanes

The v1.5.0 exact CAS lane turns the bigint/rational core into a small
certifiable computer-algebra surface.  Every command computes EXACTLY
(big-rational / big-integer arithmetic, never floats), prints `status=exact`,
and — where a compact witness exists — emits a final
`exact-cert={...}` line: a canonical `jackal-exact-cert-v1` JSON certificate
that the small, stdlib-only, independent verifier
`tools/exact_verify.py` re-checks **by full recomputation** (its own parser,
its own polynomial arithmetic, its own Sturm chains — it never trusts the
engine):

```bash
./jackal poly-eq "(x+1)^2" "x^2+2*x+1"     # status=exact equal=true  + cert
./jackal poly-eq "x^2-1" "(x-1)^2"          # equal=false — counterexample-proof coefficients in the cert
./jackal ratfunc-canon "(x^2-1)/(x-1)"      # num=1,1 den=1 side-condition=denominator-nonzero
./jackal roots-isolate "(x^2-2)*(x-3)"      # 3 disjoint rational isolating intervals + Sturm-checkable cert
./jackal alg-cmp "x^2-2" 1 3/2 "x^2-3" 3/2 2   # order=less — sqrt(2) < sqrt(3), decided exactly
./jackal xgcd 240 -46                        # g=2 u=-9 v=-47 + Bezout certificate
./jackal prime-cert 1000003                  # verdict=prime + recursive Pratt certificate
./jackal prime-cert 561                      # verdict=composite divisor=3 (Carmichael numbers cannot pass)
./jackal mod-inv 3 7 && ./jackal crt 2 3 3 5 2 7
./jackal canon "2+3*sin(pi/6)^2"             # canonical s-expression + SHA-256

# independent replay of any emitted certificate:
./jackal xgcd 240 -46 | sed -n 's/^exact-cert=//p' | python3 -I -S -B tools/exact_verify.py -
# exact-verify=ACCEPT kind=xgcd cert_sha256=... method=independent-recompute
```

Semantics and honest labels: `exact` here means exact integer/rational
computation with an independently re-checkable certificate — it is NOT a
Lean-mechanized claim (those are the `formal-*` lanes), and the verifier's
ACCEPT line says `method=independent-recompute`.  Polynomial identity over
ℚ[x] is DECIDED (canonical-form comparison, degree ≤ 64); rational-function
canonicalization records the `denominator-nonzero` side condition because
`(x²-1)/(x-1) = x+1` only where the original denominator is nonzero;
`roots-isolate` reports distinct real roots (multiplicities are not
claimed); `prime-cert` refuses beyond its factoring budget (trial division +
Pollard rho, `n ≤ 10^60`) instead of downgrading — a Pratt certificate or a
divisor, never a probabilistic verdict labeled exact.  General symbolic
simplification and equality outside these fragments remain refused, exactly
as before.

## v1.7.0: certified bound_step composition (additive)

v1.7.0 mechanizes the composed-integral bridge for a dedicated
certificate lane: `./jackal-int-cert-release "<expr>" <lo> <hi> <tol>
<receipt.json>` (plugin tool `jackal_integrate_bound_cert`).  The
producer (`tools/int_cert_producer.py`) is **untrusted**: it mirrors the
engine's adaptive subdivision in exact rational arithmetic and emits a
`jackal-int-cert v1` certificate.  The trust anchor is the independently
compiled Lean-proved checker `jackal_int_cert_check` (checker pin
`jackal-iv-bound-step-v1`), which re-checks the whole subdivision-tree
certificate and accepts only under theorem `int_cert_sound`; the
resulting `jackal-formal-receipt-v1` receipt (variant `int_cert`) is
`status=formal-bounded`.  Certified fragment:
`num`/`var`/`neg`/`add`/`sub`/`mul`/`div`/`pow` (exponent 0..4096)/
`sin`/`cos`/`abs` in `x` — everything else refuses, never downgrades.
The weaker float lane (`integrate-bound` / `jackal_integrate_bound`,
`status=bounded`, conditional on the stated f64/libm rounding model) is
unchanged and never inherits the formal status.  Residual non-claims:
producer fidelity is tested, not proved (an unfaithful producer can only
cause refusal, because the checker recomputes everything), and
source→native refinement remains OPEN.

## The claim-bundle evidence kernel (v1.6.0, additive)

v1.6.0 turns the engine and its lanes into a typed claim compiler: every
consequential quantitative conclusion either carries a canonical,
independently replayable evidence graph that preserves every weaker
class and assumption, or refuses.

```bash
# Compile a structured claim request into a content-addressed bundle:
./jackal-claim --request request.json --emit-bundle bundle.json
# Independently replay it against caller-pinned expectations:
./jackal-claim-verify --bundle bundle.json \
  --expected-release-epoch v1.6.0 \
  --expected-root-proposition root_prop.json \
  --expected-policy-sha256 <hex> \
  --verification-time-unix "$(date +%s)"
```

The kernel is deliberately small and closed:

- **Canonical bytes are load-bearing.**  One canonical JSON function
  (RFC 8785-compatible on the admitted value space; no floats, NFC-only
  strings, duplicate keys refused); node identity = SHA-256 of canonical
  node bytes; bundles bind nodes, root, policy, registries, and engine
  identity into one digest.
- **Provenance is a graph, not a badge.**  Fifteen registered inference
  rules (`release/claim/inference_registry_v1.json`) — evidence
  admission, conjunction, typed substitution, exact-rational interval
  arithmetic (division only off zero), linear/affine unit conversion,
  threshold derivation, robust decisions, model conditioning, provenance
  passthrough, attestation attach.  Anything else refuses; this is not a
  theorem prover.
- **Assurance is multidimensional and non-launderable.**  Four ordered
  axes (input provenance, model validity, mathematical class,
  implementation) propagate by pointwise meet with rule caps; artifact
  flags AND; residual non-claims union and never disappear.  A declared
  vector that diverges from the recomputed one refuses.  A signature can
  only ever affect artifact provenance.  Exact math over an assumed
  model stays `model_validity=assumed`; formal math over supplied input
  stays `input_provenance=supplied`.
- **Decisions carry structured consequence classes** (`informational`,
  `advisory`, `decision-boundary`, `safety-critical`) with
  kernel-mandated minimum axis floors and exact certified margins —
  `safety-critical` over a merely assumed physical model refuses.
- **Legacy lanes ride unmodified.**  `jackal-formal-receipt-v1` receipts
  and `jackal-exact-cert-v1` certificates enter graphs only through
  adapters that re-run the EXISTING independent verifiers
  (`receipt_verify.py` + pinned Lean checker, `exact_verify.py`); a
  bounded machine-integer fragment (`jackal-machine-int-cert-v1`: w8-w64,
  signed/unsigned, wrap/checked two's-complement) is fully recomputed by
  the claim verifier with the engine's exact bitwise commands as drift
  alarms.
- **The verifier trusts nothing.**  `tools/claim_bundle_verify.py` is
  dependency-free, runs under `python3 -I -S -B`, requires caller-pinned
  epoch/root-proposition/policy/registries/time/nonce, recomputes every
  hash, rule, axis, floor, and the deterministic rendering, and returns
  `verified`, `refused`, or `indeterminate` with one of 70 stable reason
  classes — never a bare VERIFIED badge.
- **Interval-composed enclosures cap at `mathematical=bounded`**: hull
  arithmetic is recomputed by the Python verifier, not the Lean checker;
  formal parents keep `formal-bounded` in their own nodes.  The graph
  never flattens.  The v1.7.0 certified composed-integral lane is the
  exception ONLY as direct receipt evidence — `int_cert` receipts enter
  the graph at `formal-bounded` through the receipt adapter — while the
  claim kernel's own hull arithmetic still caps at `bounded`.

Hermes exposes the kernel as two additive tools — `jackal_claim` and
`jackal_verify_bundle` — alongside the 31 unchanged v1.5.0 tools (33 at
the v1.6.0 seal; the v1.7.0 `jackal_integrate_bound_cert` brings the
inventory to thirty-four).  Hostile controls
(108-row matrix: serialization, graph identity, laundering, units,
consequence floors, freshness/replay, machine arithmetic, legacy
compatibility, rendering), A→B→A tamper gates over the seven claim trust
layers, ten end-to-end dogfood graphs, and a fresh-extraction three-way
parity gate ship in `release/evidence/claim_*_v160.json`.

## Command atlas

| World | Commands |
|---|---|
| Trust and metrology | `claim-card self-test maturity measure-mul uncertain-ohm kinetic-sensitivity` |
| Expression engine | `eval integrate integrate-adaptive derivative solve` |
| Certified enclosures | `integrate-bound range-bound` (proven interval bounds, refuse-on-doubt) |
| Proof-carrying | `range-bound-cert` plus release wrappers `jackal-cert-release`, `jackal-gaussian-release`, `jackal-int-cert-release` (composed integral enclosure, theorem `int_cert_sound`), and the seven zero-libm fragment wrappers `jackal-{sqrt,exp,ln,sin,cos,atan,tanh}-rat-release` (matching Lean checker required) |
| Provenance | `parse-dump lower-dump` (canonical s-expr of the parse/lowering — drives the Lean parser-correspondence gate) |
| Symbolic | `diff` (self-verifying d/dx) |
| Exact rationals | `rat` (canonical p/q + labeled f64 approx) |
| Exact algebra (certificate-bearing) | `canon poly-canon poly-eq poly-gcd ratfunc-canon roots-isolate alg-sign alg-cmp` |
| Number theory (certificate-bearing) | `xgcd mod-pow mod-inv crt divides prime-cert` |
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
ANUBIS=$HOME/anubis-lang/vm/pins/anubis-a733565f237d
$ANUBIS check jackal_calc.anb --out /tmp/jackal-check
./jackal self-test
ANUBIS_BIN=$ANUBIS python3 tests/test_calculator.py
python3 tests/bound_campaign.py 250 20260813   # seeded containment gate for integrate-bound
```

The containment campaign is the permanent release gate for the certified lane: seeded
generation, an independent symbolic-antiderivative oracle at 60 digits, immutable JSONL rows
with a printed SHA-256, refusals counted rather than hidden — and a hard failure if any
printed enclosure ever excludes the independently computed truth. See
[`PROVENANCE.md`](PROVENANCE.md) for the sealed source → compiler → binary chain.

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
- The `eval`/`worksheet` expression engine is numeric, not symbolic: no general CAS,
  no general simplification.  The v1.5.0 exact-algebra lane is a deliberately small
  CERTIFIABLE fragment on top of it — polynomial/rational-function canonicalization and
  decidable identity over ℚ[x] (degree ≤ 64), Sturm root isolation, and the number-theory
  kernel — each claim carried by a `jackal-exact-cert-v1` certificate an independent
  verifier recomputes.  Everything outside those fragments (trig identities, factoring,
  general symbolic equality) refuses, exactly as before.  Expression
  arithmetic in `eval` is IEEE-754 f64; the `big-` integer, `rat`, and exact-algebra
  lanes are arbitrary precision. Numbers
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
  reports its residual; it correctly refuses even-multiplicity roots. Because a tiny residual
  FLATTERS an ill-conditioned root (|x−r| ≈ |f(x)|/|f′(r)|), `solve` also reports a
  `derivative-estimate`, the `condition-amplification` 1/|f′(r)|, and a first-order
  `root-error-estimate` — field-adjudicated 2026-08-13 on a near-parabolic Kepler equation where
  a 2.3e-20 residual accompanied a 1.3e-12 root error (amplification ≈6.06×10⁷; the printed
  estimate matched the independently measured error to two significant figures). The estimate
  uses a point sample of f′, so it remains `estimate-not-bound(first-order)`; the sound form it
  instantiates (m ≤ |f′| on the bracket ⇒ |x−r| ≤ |f(x)|/m) is mechanized in `proofs/lean`.
- `integrate-bound` is the only lane whose output is a mathematical *bound*, and its claim is
  conditional exactly on: (a) IEEE-754 correctly-rounded `+ - * /`; (b) math-library functions
  within 2 ulp including argument reduction; (c) the outward-padding constants exceeding both;
  (d) the correctness of this implementation, which is campaign-tested
  (`tests/bound_campaign.py`), **not mechanized** — there is no machine-checked proof of the
  interval code itself. `0^0 = 1` follows the same documented pow() convention as the
  simplifier. Non-smooth integrands (`abs`, `floor`, `min`, …) get the pure range form, whose
  certified width converges only linearly — practical tolerances there are ~1e-4 on unit
  spans, and the budget refusal names that honestly.
- The `status=` epistemic classes (`exact`, `bounded`, `checked`, `estimated`, `model-based`)
  are printed on metadata-bearing lanes only; bare-number lanes (`eval`, `big-*`,
  single-command arithmetic) keep their historical byte-stable output and are graded in
  `jackal maturity` instead. Refusals exit nonzero with a named reason on stderr through the
  Anubis runtime's panic channel — fail-closed by construction; the runtime trace wrapping is
  cosmetic, not a crash. A future typed-refusal surface (distinct exit codes per epistemic
  state) would require a clean-exit primitive in the language.
- `parallel-r` documents its physical-domain policy: ideal passive elements. A zero-ohm branch
  is a legal ideal short (equivalent resistance exactly `0 ohm`, field-adjudicated
  2026-08-13); negative resistance implies an active element and is refused rather than
  silently reinterpreted.
- The `diff` verifier's probe self-convergence gate (skip a sample point when the h and h/2
  central differences disagree >1% of scale) validates the instrument before the number; the
  criterion is independent of the symbolic candidate, so it cannot mask a wrong rule.
- Memory is bounded by design constants, not by hoping the host is big: the certified lane's
  work is capped at 60000 subintervals with recursion depth ≤ 60 and derivative-formula size
  ≤ 20000 nodes (oversize formulas degrade to a lower Taylor form — a cost decision, never a
  soundness one), so the engine's footprint stays in transient tens-of-megabytes territory on
  any host. The test harness applies the same discipline to its *oracles*: each independent
  truth computation runs in a disposable subprocess with a hard RSS cap (3 GB) and timeout,
  because a symbolic-integration oracle that eats the machine is a harness bug, not evidence.
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
