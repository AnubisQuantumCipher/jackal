# Getting started with JACKAL

JACKAL is a command-line STEM calculator with one unusual property: **every
answer tells you what kind of answer it is.** Exact results say `exact`.
Floating-point estimates say `estimated` and print their own error estimate.
Certified interval bounds say `bounded` and print an enclosure the true value
provably cannot escape. Model-based physics answers say `model-based` and list
their assumptions. And when JACKAL cannot stand behind a number, it refuses —
loudly, with a named reason — instead of printing something plausible.

This guide takes you from install to reading your first certified result.

## 1. Install

### Option A — download the release binary (Apple Silicon macOS)

Grab `jackal-native` from the [latest GitHub release](../../releases/latest),
verify its checksum against the one published in
[`PROVENANCE.md`](PROVENANCE.md), and drop it next to the launcher:

```bash
git clone https://github.com/AnubisQuantumCipher/jackal-calc.git
cd jackal-calc
# download jackal-native from the Releases page into this directory, then:
shasum -a 256 jackal-native        # compare against PROVENANCE.md
chmod +x jackal-native
./jackal self-test
```

You should see:

```text
self-test: 83/83 Anubis-native invariants pass
```

### Option B — build from source

The entire engine is one file of [Anubis](https://github.com/AnubisQuantumCipher)
source, `jackal_calc.anb`. Building it requires the Anubis compiler, which is
not yet publicly distributed — if you have access to a pinned `anubis` binary:

```bash
export ANUBIS_BIN=/path/to/anubis
./jackal self-test                 # compiles, then runs
```

Builds are **byte-reproducible**: two clean builds of the same source with the
same pinned compiler produce bit-identical binaries (see `PROVENANCE.md` for
the verified chain). Everyone else: use Option A — the released binary's
hash is sealed in `PROVENANCE.md`, and the source it was built from is right
here in the repo.

## 2. First calculations

```bash
./jackal eval "2+3*sin(pi/6)^2"        # expression engine (IEEE f64)
./jackal rat "0.1 + 0.2"               # exact rational arithmetic
./jackal big-fact 100                  # exact arbitrary-precision integers
./jackal diff "x^2*sin(x)"             # symbolic derivative, checked before release
./jackal solve "x^2-2" 1 2             # bisection: residual + conditioning + root-error estimate
./jackal quadratic 1 -3 2              # and ~40 more commands: ./jackal help
```

A few outputs worth pausing on:

```text
$ ./jackal rat "0.1 + 0.2"
status=exact parsed=0.1+0.2 exact=3/10 approx=0.30000000000000004
```

`exact=3/10` is the truth; `approx=` is what IEEE floating point makes of the
same expression, printed so the difference is *visible*. The `parsed=` echo
exists because the most common failure at any calculator boundary is
transcription, not computation — confirm JACKAL evaluated what you meant.

```text
$ ./jackal diff "x^2*sin(x)"
d/dx[x^2*sin(x)] = 2*x*sin(x)+x^2*cos(x)
status=checked check=numeric points=9 max-rel-dev=0.00000000005999646518118516 tolerance=0.0001 assurance=numeric-sample-check(not-proof-of-identity)
```

JACKAL refuses to print a derivative that fails its own numeric verification.
The `assurance=` field tells you exactly how far that verification goes: a
sampled check, not a proof of symbolic identity.

## 3. The assurance ladder — three ways to integrate

This is JACKAL's core idea in one example.

**Tier 1 — fast estimate** (`integrate`): Simpson's rule plus a Richardson
error estimate. Superbly calibrated in testing — and still an *estimate*, and
it says so:

```bash
./jackal integrate "sin(x)" 0 3.141592653589793 200
# status=estimated integral=2.000000000000001 ... assurance=estimate-not-bound(grid-limited) ...
```

**Tier 2 — estimate with refusal semantics** (`integrate-adaptive`): adaptive
subdivision that *refuses* (nonzero exit, named reason) rather than print
unearned confidence when it cannot converge.

**Tier 3 — a certified bound** (`integrate-bound`): outward-rounded interval
arithmetic. The printed enclosure provably contains the true integral, under
a rounding model stated on the output line itself:

```bash
./jackal integrate-bound "exp(0-1000000*(x-0.1225)^2)" 0 1 1e-9
# status=bounded integral-enclosure=[0.0017724538498025575,0.0017724538524225815] ...
```

That integrand is a Gaussian spike ~0.0007 wide. A fixed sampling grid can
step right over it and confidently report almost-zero — this exact failure
was demonstrated against Tier 1 in adversarial testing. Tier 3 is immune by
construction: interval arithmetic evaluates the function over *ranges*, and a
range containing a spike contains the spike. The trade-off is honest cost:
certification is the slowest lane, and for non-smooth integrands it may
refuse tight tolerances entirely.

There is also `range-bound`, the same certified machinery for the *range* of
a function over an interval:

```bash
./jackal range-bound "sin(x)" 0 6.4
# status=bounded range-enclosure=[-1.000000000000001,1.000000000000001] ...
```

## 4. Reading `status=` and `assurance=`

Every metadata-bearing answer leads with its epistemic class:

| `status=` | Meaning | Where |
|---|---|---|
| `exact` | True by exact arithmetic; not an approximation | `rat` (and the `big-*` lanes, implicitly) |
| `bounded` | A certified enclosure under a stated f64 rounding model | `integrate-bound`, `range-bound` |
| `checked` | Numerically verified before release; not a proof | `diff` |
| `estimated` | A numerical method with a disclosed, heuristic error estimate | `integrate`, `integrate-adaptive`, `derivative`, `solve`, legacy lanes |
| `model-based` | A physics/chemistry formula; correct only if its assumptions fit | `claim-card` (and the physics commands, implicitly) |

The `assurance=` field carries the residual: what the number still depends
on. For the certified lane that is
`certified-bound(outward-rounded-f64;libm<=2ulp-model;implementation-tested-not-mechanized)`
— meaning: correctly-rounded IEEE basic ops, a ≤2-ulp math-library
assumption, and an implementation validated by adversarial campaigns (plus a
machine-checked Lean model of the mathematics — see
[`proofs/lean/`](proofs/lean/)) rather than end-to-end proof.

Run `./jackal maturity` to see every command graded: its class, its
independent oracle, the evidence behind it, and its known residual. The last
line of that output is JACKAL's whole philosophy:

```text
non-claim=universal-correctness; finite campaigns cannot establish it
```

## 5. Refusal is an answer

Invalid input, domain violations, exhausted certification budgets, and
non-finite intermediate values all **fail closed**: nonzero exit, named
reason on stderr. Some examples to try:

```bash
./jackal div 1 0                       # division by zero has no finite result
./jackal eval "sqrt(0-1)"              # NaN → refused
./jackal integrate-bound "1/x" 0 1 1e-6   # cannot certify across a pole → refused
./jackal parallel-r -50 100            # negative resistance → outside the ideal-passive model
./jackal big-fact 10001                # compute budget → refused
```

A note on presentation: refusals surface through the Anubis runtime's panic
channel, so you'll see a runtime trace around the message. That is the
fail-closed mechanism, not a crash — the named reason on stderr is the
answer.

## 6. Claim cards — answers you can hand to someone else

```bash
./jackal claim-card projectile 20 45 9.80665
```

This prints a complete, reproducible claim: model identity, typed inputs,
explicit assumptions, results, sensitivity elasticities, explicit
*non-claims*, the canonical preimage, and a SHA-256 fingerprint over it. Two
runs produce byte-identical cards; anyone can recompute the fingerprint with
any SHA-256 tool. The card makes the model boundary inspectable — it does
not, and does not claim to, prove the physics assumptions fit your situation.

## 7. Worksheets and the expression grammar

```bash
./jackal worksheet "a = 5; b = a^2; a+b"
```

Grammar: `+ - * / %`, `^` (right-associative; unary minus binds looser, so
`-3^2 = -9`, the calculator convention), parentheses, function calls.
Functions: `sin cos tan asin acos atan sqrt cbrt ln log10 log2 exp abs floor
ceil round trunc` (one argument), `hypot pow atan2 min max` (two).
Constants: `pi e tau c g0 h na kb r`. The variable `x` is bound only inside
`integrate*`, `derivative`, `solve`, and `range-bound`. Numbers need a
leading digit (`0.5`, not `.5`).

## 8. Verifying more than you have to

Everything JACKAL claims about itself is re-derivable:

```bash
./jackal self-test                          # 83 in-binary invariants
python3 tests/test_calculator.py            # ~200-case black-box suite (needs sympy, mpmath)
python3 tests/bound_campaign.py 250 20260813    # certified-lane containment campaign
python3 tests/iv_differential.py 300 20260813   # cross-check vs mpmath.iv interval arithmetic
```

The chain from source to binary to test receipts is sealed in
[`PROVENANCE.md`](PROVENANCE.md). The machine-checked model of the certified
lane lives in [`proofs/lean/`](proofs/lean/) (Lean 4 + Mathlib; build with
`cd proofs/lean && lake exe cache get && lake build`). A RISC0 zero-knowledge
receipt for the integer core lives in
[`proofs/zk-receipt/`](proofs/zk-receipt/VERIFY.md).

## 9. Where to go next

- [`README.md`](README.md) — the full command atlas and the design rationale.
- [`RESEARCH.md`](RESEARCH.md) — how JACKAL positions against TI-Nspire,
  Qalculate!, Soulver, and SpeedCrunch, and why a *claim-aware* calculator is
  the one worth building in the AI era.
- `./jackal help` — every command; `./jackal maturity` — every command's
  trust grade.

If a number matters, check its `status=`. If it really matters, use a lane
whose class is `exact` or `bounded` — or read the refusal as the honest
answer it is.
