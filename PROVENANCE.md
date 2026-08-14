# JACKAL PROVENANCE

Every link in the chain from source to shipped binary to test receipts,
either mechanically derived or measured — and anything that failed
measurement stated as failed rather than papered over.

```text
source → compiler pin → deterministic build → binary hash → gate receipts → adjudication
```

## Seal v1.0.2 — 2026-08-14 (current)

Adds implementation-correspondence bridge #1: the engine's parser and lowering
lifted onto a single canonical Lean `Expr`, with a machine-checked
correspondence theorem and a parser differential gate.

### Source
- `jackal_calc.anb` SHA-256: `6fb22d3df4f6940d4b1734ce9be13f86bd322b98a74a639310fafca3746a29bb`
- Git: the commit tagged `v1.0.2`.
- Change vs v1.0.1: two inert diagnostic commands, `parse-dump` and
  `lower-dump`, emitting the real parse tree / certified-lane lowering in
  canonical s-expression form (via a new `ast_sexp`). No existing command's
  behavior changes.

### Compiler
- pin `anubis-a733565f237d` (unchanged), SHA-256 `a733565f237df171e7cf93b9b37700a42d8713576818fd92f8cd23a8ad7a69e2`.

### Build — byte-reproducible, verified
- shipped `jackal-native` SHA-256: `f83af0793e897d07cae02e3a0fac0feab6cf079606a27180cee2da239d9fe1eb`
  (two clean builds identical).

### Gate receipts (2026-08-14, against this binary/pin, all green)

| Gate | Result |
|---|---|
| `anubis check` + native self-test | passed; 83/83 |
| Black-box acceptance suite | 200/200 (incl. Kepler-conditioning and Fresnel-certification cases) |
| Containment campaign (`bound_campaign.py 250 20260813`) | BOUND_OK=246 REFUSED=4 **0 violations**; JSONL sha256 `28e834552271105cd367225d779caa0d09f629f553b1b6466d6b684cd8bdf32f` |
| mpmath.iv differential (`iv_differential.py 300 20260813`) | OK=300 **0 violations**; median width ratio 1.000; JSONL sha256 `60fe6093bd015849609586fc374be448139ab2293a5a07109dc84a802ed89f6a` |
| **Parser correspondence gate** (`parser_differential.py`) | **78/78** (30 accepted MATCH, 9 refused BOTH_REFUSE, 3 parser-only), all case IDs unique; green against both source and the shipped binary; `--tamper` self-test PASS |
| **Parser tamper cycle** (recorded) | a semantic mutation of the runnable `Dump` mirror's power rule (base↔exponent) that still COMPILES and RUNS produced an observable `PARSE_DRIFT` + nonzero gate; restore verified by hash equality to canonical `Parser.lean` `3a219bc3…` and `Dump.lean` `3baba941…`; stale exe purged; gate green again |
| Lean mechanization (`proofs/lean`, 20 modules, ~6,200 lines) | `lake build` green; 170+ theorems, zero `sorry`; flagship theorems audited to `[propext, Classical.choice, Quot.sound]` only |

### Bridge #1 — what is proved vs gated vs open

- PROVED (Lean, this seal): one canonical `Syntax.Expr` unifying enclosure and
  differentiation; `Parser.parse` (determinism + structural rejection lemmas)
  mirroring the recursive-descent grammar; `Lower.lower` mirroring
  `simplify_bound` with **`lower_preserves_sem`** and `lower_preserves_defined`;
  and the composition `parse_lower_denotes` (the admitted source denotes
  `sem ast`, preserved by lowering) / `parse_lower_encloses` (that denotation,
  threaded through `runs_encloses`, is enclosed at every point). ~30 operators
  wired into `Runs`.
  `#print axioms parse_lower_denotes` = `#print axioms parse_lower_encloses` =
  `[propext, Classical.choice, Quot.sound]` — the `@[implemented_by]` runnable
  mirror is a compiler directive, NOT an axiom, and is excluded from theorem
  trust (it lives only in the differential gate's TCB).
- GATED, not proved: byte-for-byte identity of the Lean parser to the SHIPPED
  engine parser (the differential gate over a finite corpus).
- OPEN, unclaimed: still-fail-closed operators tan/cbrt/log10/log2/mod; the
  actual `ieval`→`Runs` bridge; `bound_step` release-policy composition; and
  source→native refinement. The exact target claim is unchanged — universal
  correctness over the precisely admitted certified fragment and its stated TCB,
  never unqualified.

**Claim boundary (unchanged, cross-audited).** The certified fragment's
mathematical model is universally mechanized under stated assumptions, and the
front-end correspondence now ties the admitted *source string* to it; the
shipped implementation is tested, differential-gated, reproducible, and sealed
— NOT mechanically proved to refine the model. Neither half quoted without the
other.

## Seal v1.0.1 — 2026-08-13 (superseded by v1.0.2)

### Source

- `jackal_calc.anb` SHA-256: `43810ce5b8e5fe05be7c3411067b00d0aaa74b8083accdbca6e840ecfa10e2b9`
- Git: the commit tagged `v1.0.1` in this repository.
- Change vs v1.0.0: `solve` conditioning diagnostics (derivative-estimate,
  condition-amplification, first-order root-error-estimate) — field-adjudicated
  the same day on a near-parabolic Kepler equation where a 2.3e-20 residual
  accompanied a 1.3e-12 root error (amplification ~6.06e7; the printed estimate
  matched the independently measured error to two significant figures).

### Compiler

- pin: `anubis-a733565f237d` (content-addressed snapshot; anubis-lang commit `b3390c7c`)
- pin SHA-256: `a733565f237df171e7cf93b9b37700a42d8713576818fd92f8cd23a8ad7a69e2`

### Build — byte-reproducible, verified

Same recipe as v1.0.0. Two clean builds of this source: byte-identical.

- shipped `jackal-native` SHA-256: `d8dd82a23f0b5f920c2f26bab734d45b050d2219007eef573ae69313daaa7d22`

### Gate receipts (2026-08-13, all against this binary/pin, all green)

| Gate | Result |
|---|---|
| `anubis check jackal_calc.anb` | passed |
| Native self-test | 83/83 invariants |
| Black-box acceptance suite | TOTAL **200/200** — now includes the Kepler-conditioning case and the Fresnel integral (~796 oscillations) certified-enclosure case |
| Seeded containment campaign (`tests/bound_campaign.py 250 20260813`) | BOUND_OK=246 REFUSED=4 ORACLE_SKIP=0 **CONTAINMENT_VIOLATION=0 WIDTH_VIOLATION=0**; JSONL sha256 `28e834552271105cd367225d779caa0d09f629f553b1b6466d6b684cd8bdf32f` (the harness oracle may legitimately choose antiderivative vs quadrature per run, so campaign JSONLs are not byte-stable across runs; counts and verdict are the receipt) |
| Cross-implementation differential gate (`tests/iv_differential.py 300 20260813`) | OK=300 **POINT_VIOLATION=0 DISJOINT_IMPLEMENTATIONS=0**; median width ratio vs mpmath.iv = 1.000; JSONL sha256 `60fe6093bd015849609586fc374be448139ab2293a5a07109dc84a802ed89f6a` — byte-identical to the v1.0.0 runs (range-bound behavior unchanged) |
| Lean 4 mechanization (`proofs/lean`, 14 modules, ~4,000 lines) | `lake build` green (8,670 jobs); **121+ theorems, zero `sorry`**; 42 flagship theorems axiom-audited to exactly `[propext, Classical.choice, Quot.sound]`; independently cross-audited read-only the same day (fresh-snapshot rebuild: clean; `runs_encloses` axiom audit: clean) |

### What the Lean development now covers

Pad model; add/sub/neg/mul/div; integer, negative, and positive-base general
powers; exact ops (abs/min/max/floor-family/hypot/atan2); monotone rule with
exp/sqrt/log/arctan/arcsin/arccos; sin/cos hulls across all widening branches;
**float critical-point-test conservativity** on the engine's parameter range;
bisection bracket soundness and the backward-error bound behind `solve`'s new
diagnostics; float-midpoint containment; Taylor-2/4 midpoint enclosures; the
**deep-embedded composition theorem** `runs_encloses` (every modeled execution
over every interval encloses the exact semantics at every point — universal
quantifiers, no sampling); and the **evaluability-certifies-smoothness chain**
composing end-to-end into the Taylor theorems. The target claim, stated
exactly: universal correctness over the precisely admitted certified fragment
and its stated TCB — never "universal correctness" unqualified. Residuals and
the next-wave bridge roadmap (parser→Expr, ieval→Runs, bound_step composition,
source-to-native refinement) are enumerated in `proofs/lean/JackalIv/Ledger.lean`.

**Claim boundary (cross-audited 2026-08-13).** The certified fragment's
mathematical *model* is universally mechanized under its stated assumptions.
The shipped *implementation* passed the stated tests, differential and
containment gates, reproducibility checks, and this seal — it is **not**
mechanically proved to refine that model; implementation refinement is the
future work named above. Neither half of that sentence should be quoted
without the other.

## Seal v1.0.0 — 2026-08-13 (superseded by v1.0.1)

### Source

- `jackal_calc.anb` SHA-256: `b74d078db6acc7b73f81001ed823643df037e4770b6062c15de411ff571f5384`
- Git: the commit tagged `v1.0.0` in this repository.

### Compiler

- pin: `anubis-a733565f237d` (content-addressed snapshot; anubis-lang commit `b3390c7c`)
- pin SHA-256: `a733565f237df171e7cf93b9b37700a42d8713576818fd92f8cd23a8ad7a69e2`

### Build — byte-reproducible, verified

```bash
ANUBIS_BIN=$HOME/anubis-lang/vm/pins/anubis-a733565f237d \
  JACKAL_FORCE_SOURCE=1 JACKAL_OUT=./.build ./jackal self-test
cp ./.build/anubis_run ./jackal-native && chmod +x ./jackal-native
```

- shipped `jackal-native` SHA-256: `609de1035be62a5183ad6555b97402567c9e4539b41806a5b52974f6be9030ae`
- **Byte-reproducibility: verified.** Repeated clean builds of the committed
  source with this pin are fully byte-identical (same SHA-256, linker UUID
  included), across differing out-dir paths including one containing spaces.
  Anyone holding the pin can rebuild and compare. The GitHub release for
  `v1.0.0` ships this exact binary with a `SHA256SUMS` file.

### Gate receipts (2026-08-13, all against this binary/pin, all green)

| Gate | Result |
|---|---|
| `anubis check jackal_calc.anb` | passed |
| Native self-test | 83/83 invariants |
| Black-box acceptance suite (`tests/test_calculator.py`, source-built via pin) | TOTAL 198/198, includes 7 enclosure-contains-independent-oracle checks |
| Seeded containment campaign (`tests/bound_campaign.py 250 20260813`) | BOUND_OK=246 REFUSED=4 **CONTAINMENT_VIOLATION=0 WIDTH_VIOLATION=0**; JSONL sha256 `4473208f8e15715f67734fc14a322afca9c52687448f93f2357768e1d36186fa` — byte-identical to the pre-pin-swap run, a determinism receipt in itself |
| Cross-implementation differential gate (`tests/iv_differential.py 300 20260813`, vs mpmath.iv + 40-digit point sampling) | OK=300 **POINT_VIOLATION=0 DISJOINT_IMPLEMENTATIONS=0**; median width ratio vs mpmath.iv = 1.000; JSONL sha256 `60fe6093bd015849609586fc374be448139ab2293a5a07109dc84a802ed89f6a` — also byte-identical across binaries |
| Lean 4 mechanization of the interval model (`proofs/lean`, Mathlib v4.32.0) | `lake build` green; 60+ theorems, zero `sorry`; `#print axioms` on all flagship theorems (incl. `taylor2/4_midpoint_enclosure`) = `[propext, Classical.choice, Quot.sound]` only; unproven residuals enumerated in `JackalIv/Ledger.lean` |
| Adversarial multi-lens review (4 lenses, 20 agents, adversarial verify per finding) | 11 confirmed findings (2 critical soundness, 2 major honesty, 7 minor) — all fixed in commit `8a71540` with regression coverage; 2 findings refuted |

### zk-receipt binding (reconciled)

`guest_source_sha256` in `proofs/zk-receipt/risc0_metadata.json` digests the
deterministic transpiled Rust guest (`guest_source.rs`), not the `.anb`
bytes. Re-derived 2026-08-13 from the committed
`proofs/jackal_proof_guest.anb`: transpile hash identical (`2d11f1bf…`),
guest ELF byte-identical (`d363e61d…`), ImageID identical, fresh receipt
verifies with the same journal (`8`). Details in
`proofs/zk-receipt/VERIFY.md`.

## Build-determinism history (how the reproducibility claim was earned)

Earlier pins were **not** byte-reproducible: repeated builds of identical
source produced distinct binaries. The divergence was diagnosed stage by
stage on 2026-08-13:

1. Anubis → Rust transpile: byte-deterministic all along (every build of
   source `b74d078d…` emits `anubis_run.rs` with SHA-256 `3e4fde1e…`).
2. rustc → binary: layout permuted per build. Root cause: the compiler
   generated a randomized per-build Cargo package name, which cargo folds
   into the crate metadata hash, which decides symbol mangling and
   codegen-unit layout.
3. Fix (anubis-lang commit `b3390c7c`): content-derived package name
   `anubis_run_<sha256(generated .rs)[..12]>` — reproducible for identical
   source, unique across programs, and same-name collisions under the shared
   target dir became benign (same name now implies same bytes).

`tests/content_hash.py` (hashes only code/data segments, excluding Mach-O
headers and linker metadata) remains available for comparing binaries across
toolchains.

## Prior seal — 2026-08-13, superseded

- Compiler pin `anubis-51f4a964347a`
  (`51f4a964347a4a0f3ea2833331eb313315aa502c96c9d7a71fc3b20414eca027`),
  non-reproducible builds; chain bound the exact gate-tested binary
  `c37a256c38c5819e24b31c405152fb61fe06bcf4f05550dee9e5c4e8e080c2c2`
  (commits `8a71540`/`11cac9b`). All gates were green against that binary
  with the same source hash; the v1.0.0 seal reproduces those results.
- The original 1,402-case behavioral campaign (adjudicated
  `NO_UNEXPLAINED_MISMATCHES`, 2026-08-13) bound to artifact
  `211c614b46f986d826b1e3272a4190b63178d83fb389bbf1d910162420c4295b` — the
  engine as it existed *before* the certified lane. That receipt remains
  valid for that artifact.

## Non-claims

Finite campaigns do not establish universal correctness. The certified
lane's enclosures are conditional on the stated f64 rounding model
(correctly rounded basic ops; libm within 2 ulp) and on an implementation
that is campaign-tested — its mathematical *model* is machine-checked in
`proofs/lean/`, the implementation itself is not. `jackal maturity` prints
the per-command epistemic grades.

## Regenerate

```bash
shasum -a 256 jackal_calc.anb jackal-native
ANUBIS_BIN=$HOME/anubis-lang/vm/pins/anubis-a733565f237d python3 tests/test_calculator.py
python3 tests/bound_campaign.py 250 20260813
python3 tests/iv_differential.py 300 20260813
cd proofs/lean && lake exe cache get && lake build
```
