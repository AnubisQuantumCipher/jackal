# JACKAL v1.7 `bound_step` composition — research sources and architecture decisions

**Status: research-shadow. Non-authoritative. Not a release artifact.**
Date accessed for all sources: 2026-08-16 (America/New_York).
Mission: mechanize the `bound_step` acceptance-policy composition (Ledger roadmap item 4)
in non-authoritative shadow mode, against baseline v1.6.0 = 19b763e9451276e72c7511ec8ba42bf828d096f6.

Scope discipline: only material that can change this design. Each entry records the
exact proposition used, its applicability, its non-applicability/trust assumptions,
and the resulting architecture decision.

---

## S1. Mahboubi, Melquiond, Sibut-Pinote — "Formally Verified Approximations of Definite Integrals"

- **Source:** Journal of Automated Reasoning 62(2):281–300, 2019 (conference version ITP 2016,
  LNCS 9807, pp. 274–289). HAL: https://hal.science/hal-01630143 ;
  Springer: https://link.springer.com/article/10.1007/s10817-018-9463-7. Accessed 2026-08-16.
- **Proposition used:** definite-integral enclosures can be machine-checked by combining
  (a) rigorous polynomial approximation of the integrand on a subinterval,
  (b) exact integration of the polynomial part plus an interval remainder, and
  (c) **adaptive domain splitting**, where the enclosure of the whole integral is the
  interval sum of per-piece enclosures. Their tool works inside Coq by *reflection*:
  the enclosure is recomputed inside the prover by a verified interval evaluator
  (CoqInterval), not checked from an externally produced trace.
- **Applicability to JACKAL:** confirms the mathematical shape JACKAL's `bound_step`
  already implements (midpoint/Taylor form + remainder over a subinterval + dyadic
  bisection + interval addition of accepted children) is the standard mechanized
  design; the per-piece enclosure + interval-sum composition is exactly the theorem
  this mission must state for the subdivision tree.
- **Non-applicability / trust assumptions:** the reflection architecture does NOT fit
  this mission. JACKAL's objective is to bind the *shipped engine's* acceptance policy,
  and the repo's established trust design (bridge #2, `CertTypes`/`CertCheck`/`CertSound`)
  is proof-carrying: an untrusted producer emits a certificate and a small proved
  checker validates it. Reflection would move the whole quadrature into the prover and
  would certify a *different* computation than the engine's, silently widening the claim.
- **Decision:** keep the certificate/checker architecture (extend bridge #2 with a
  subdivision-tree certificate); do not adopt reflection. Mirror their composition fact
  as the shadow soundness theorem: per-leaf enclosure theorems + exact partition +
  interval addition ⇒ enclosure of the requested integral.

## S2. McConnell, Mehlhorn, Näher, Schweitzer — "Certifying algorithms"

- **Source:** Computer Science Review 5(2):119–161, 2011.
  https://www.sciencedirect.com/science/article/abs/pii/S1574013710000560 ;
  ACM: https://dl.acm.org/doi/10.1016/j.cosrev.2010.09.009. Accessed 2026-08-16.
- **Proposition used:** an algorithm should emit, with each output, a *witness* that a
  simple, independently trusted checker can verify; the checker — not the producing
  algorithm — carries the trust. Witness design goal: checking is asymptotically and
  conceptually simpler than producing.
- **Applicability to JACKAL:** the shadow producer (a `bound_step` mirror) is untrusted
  by design; every fact the soundness theorem consumes must be reconstructible by the
  checker from the artifact alone (structural tree validity, per-leaf premises via
  embedded evaluation certificates, exact-ℚ inequalities). This justifies the key
  simplification below (D3): the checker verifies *conservativity against an exact-ℚ
  ideal recomputation* rather than replaying the engine's float ops.
- **Non-applicability / trust assumptions:** the survey's checkers are trusted by
  inspection; here the checker itself is *proved* (Lean), which is strictly stronger,
  but adds the Lean toolchain to the TCB exactly as the existing bridge #2 already
  discloses (Ledger.lean residual (c)).
- **Decision:** the shadow artifact is a witness for the checker, never evidence by
  itself; every acceptance-relevant premise is either checked, a named TCB hypothesis
  (`ModelTCB` per embedded certificate), or a fail-closed refusal.

## S3. Irving — `girving/interval`: conservative floating-point interval arithmetic in Lean 4

- **Source:** https://github.com/girving/interval (README; repo active, Lean 4).
  Accessed 2026-08-16.
- **Proposition used:** Lean 4's built-in `Float` is *untrusted* (opaque primitives),
  so verified interval work in Lean either implements its own verified software floats
  (their choice: 64+64-bit `Floating` + `Approx A ℝ` typeclass) or avoids trusting
  float execution entirely.
- **Applicability to JACKAL:** confirms the existing JACKAL checker design choice —
  all checker arithmetic over exact `ℚ` (`Rat`), never Lean `Float` — and rules out
  "just replay the engine's f64 ops in the Lean checker" for the shadow tree: the
  checker cannot trust any float computation it performs itself.
- **Non-applicability / trust assumptions:** their verified-float stack is a heavier
  dependency than this mission needs; JACKAL's model already brackets engine floats via
  the `Approx δ σ` rounding model + outward pads, checked against exact ℚ. No new
  dependency is admitted (toolchain pins are frozen: lakefile.toml / lake-manifest.json /
  lean-toolchain are sha256-pinned in release/evidence/range_proof_identity.json:33-45).
- **Decision:** shadow checker computes only in `ℚ`/`Nat`/`Int`/`String`/`Bool`
  (same discipline as `CertCheck.lean`); engine float values enter only as exact
  dyadic rationals recorded in the artifact.

## S4. IEEE 754 / exact float-to-rational representability (model boundary)

- **Source:** IEEE Std 754-2019 (binary64 interchange format: every finite value is
  ±m·2^e with m < 2^53, hence a dyadic rational); locally instantiated by the repo's
  own model: `proofs/lean/JackalIv/Model.lean:33-43` (δ0 = 2⁻⁵³ correctly-rounded
  basic ops, δlib = 2⁻⁵¹ libm, σ0 = 2⁻¹⁰⁷⁵ subnormal floor, as `Approx` bounds) and
  `CertTypes.lean:294-339` (rational pads + `algApproxQ` reflection). Producer-side
  instantiation: CPython `float` is IEEE binary64; `Fraction(float)` is exact and
  `float(Fraction)` is correctly rounded (CPython language guarantee, mirrored by the
  six existing `tools/*_rat_producer.py`).
- **Proposition used:** every finite f64 is *exactly* a rational, so request endpoints,
  tolerance, subdivision midpoints, and all engine interval endpoints can be bound into
  the artifact exactly, with no pretense that f64 execution is exact real arithmetic:
  rounding enters only through the already-mechanized `Approx`/pad model of the
  embedded evaluation certificates.
- **Applicability:** answers the §6.1 question "can endpoints and tolerance be
  represented exactly enough for a proof-carrying checker": yes — as ℚ, exactly.
- **Non-applicability / trust assumptions:** the *decimal text* → f64 parse the engine
  performs on the command line stays upstream of the artifact (same boundary as the
  existing `Header.input_lo/hi` vs `source_commitment` split); the artifact binds the
  parsed dyadic values.
- **Decision:** all artifact numerics are canonical ℚ (existing `parseRatCanon`
  discipline, CertCodec.lean:225-247). The float midpoint `m = fl((a+b)/2)` is bound
  NOT via the rounding model but by the strictly stronger exact check
  `m_lo ≤ (a+b)/2 ≤ m_hi` on the midpoint evaluation's input interval (see D5).

## S5. Local prior art (pinned tree, strongest evidence): bridge #2 and the Taylor/Deriv/Midpoint stack

- **Source (all at v1.6.0 = 19b763e):**
  - `proofs/lean/JackalIv/CertSound.lean:985-1011` — `cert_check_sound` / `cert_encloses`:
    an accepted evaluation certificate induces `Runs`, hence pointwise enclosure, under
    the named `ModelTCB` (Prop hypothesis, never an axiom).
  - `proofs/lean/JackalIv/Embed.lean:616-625` — `runs_encloses`: a completed run gives
    `DefinedOn e x ∧ sem e x ∈ [lo, hi]` for every x in the input interval.
  - `proofs/lean/JackalIv/Deriv.lean:588-624` — `taylor2/4_enclosure_of_evaluable`:
    evaluability of the D-chain supplies the C²/C⁴ premises and yields the midpoint
    Taylor enclosures with exact real midpoint values.
  - `proofs/lean/JackalIv/Taylor.lean:415-514` — the h³/24 and h⁵/1920 midpoint forms.
  - `proofs/lean/JackalIv/Midpoint.lean:76-91` — `float_midpoint_in_padded` /
    `midpoint_enclosure_transfer`: why the engine's padded float midpoint interval
    contains the exact midpoint (emitter-compatibility justification for D5).
  - `jackal_calc.anb:2975-3068` — the shipped `bound_step` control flow (acceptance,
    fallback, budget/depth/resolution refusals, `iv_add` composition, intersect).
  - Verified locally: `lake build JackalIv jackal_cert_check jackal_gaussian_check
    jackal_parse_dump` = exit 0 on this worktree (2026-08-16), all flagship
    `#print axioms` = `[propext, Classical.choice, Quot.sound]`.
- **Proposition used:** every leaf premise of the composition theorem is *already
  mechanized*; the missing object is exactly the tree-shaped certificate + checker +
  composition induction (Ledger.lean:243-245 roadmap item 4).
- **Decision:** reuse, never restate: leaf soundness = `cert_check_sound` ∘
  `runs_encloses` (range), plus `taylor2/4_enclosure_of_evaluable` (smooth forms);
  composition = strong induction over the flat id-ordered tree (the same
  child-id-strictly-below-parent discipline as `structuralOk`/`runs_of_check`).

## S6. Mathlib API at the pinned revision (81a5d257c8e410db227a6665ed08f64fea08e997)

- **Source:** local checkout `proofs/lean/.lake/packages/mathlib` at the exact
  lake-manifest revision (verified by `git rev-parse HEAD` on 2026-08-16); the
  integration/measurability lemmas the composition proof consumes:
  - `MeasureTheory/Integral/IntervalIntegral/Basic.lean:1094` —
    `integral_add_adjacent_intervals` (adjacent-interval additivity).
  - `MeasureTheory/Integral/IntervalIntegral/Basic.lean:208` — `IntervalIntegrable.trans`.
  - `intervalIntegral.integral_mono_on` (already consumed by `Taylor.lean:450,511`).
  - `MeasureTheory/Function/L1Space/Integrable.lean:100` — `Integrable.mono'`
    (bounded + a.e. measurable ⇒ integrable, for the range-leaf integrability).
  - `MeasureTheory/Measure/Typeclasses/Finite.lean:642` — `measure_Ioc_lt_top`.
  - `MeasureTheory/Group/Arithmetic.lean:269` — `Measurable.div`.
  - `MeasureTheory/Constructions/BorelSpace/Order.lean:789` — `Monotone.measurable`
    (floor/ceil/round/trunc lanes).
  - `MeasureTheory/Function/Floor.lean:27` — `Int.measurable_floor`.
  - `Analysis/SpecialFunctions/Trigonometric/Inverse.lean:93,377` —
    `continuous_arcsin` / `continuous_arccos`.
  - **Gap found:** no stock measurability lemma for real `rpow` at this revision
    (`Measurable.rpow` absent under `Analysis/SpecialFunctions/Pow/`). Available
    instead: `Real.rpow_def_of_pos` (`Pow/Real.lean:51`), `rpow_def_of_neg` (`:95`),
    `zero_rpow` (`:128`).
- **Proposition used:** integrability of a *range-only* accepted integrand cannot come
  from continuity (floor/ceil/round/trunc integrands are accepted by the engine's range
  form and are discontinuous) — it must come from measurability + boundedness, where
  boundedness is exactly the certified enclosure.
- **Decision:** prove `sem_measurable : ∀ e, Measurable (sem e)` by structural
  induction (a new shadow lemma), including a local piecewise derivation of rpow
  measurability from `rpow_def_of_pos/neg` + `zero_rpow`; then range-leaf
  integrability = `Integrable.mono'` against the constant bound, and tree-level
  integrability composes upward with `IntervalIntegrable.trans` while values compose
  with `integral_add_adjacent_intervals`.

---

# Resulting architecture decisions (D1–D10)

- **D1 — Certificate, not reflection** (from S1, S2, S5): a proof-carrying
  *composition artifact* for one complete accepted `integrate-bound` subdivision tree;
  untrusted producer, proved computable checker, soundness theorem from checker
  acceptance. Non-authoritative: new status class string `research-shadow`, new magic
  `jackal-int-cert shadow-v1`, new checker identity pin
  `jackal-iv-bound-step-shadow-v1`; no public tool, no release lane, no plugin change.
- **D2 — Reuse bridge #2 verbatim for leaves** (S5): each leaf embeds ordinary
  `jackal-eval-cert v2` certificates (parsed by the *existing proved* `Cert.parseCert`,
  checked by the *existing proved* `Cert.checkCert`); leaf facts enter the composition
  proof only through `cert_check_sound` + `runs_encloses`. Roles per accepted mode:
  range-only ⇒ {F}; smooth-taylor2 ⇒ {F, F1, F2, Fm}; smooth-taylor4 ⇒
  {F, F1, F2, F3, F4, Fm, F2m} — F1/F3 are consumed *only* as evaluability witnesses
  (`DefinedOn` of the D-chain), mirroring the engine's "evaluate and require ok,
  discard the interval" smoothness certificate.
- **D3 — Exact-ℚ ideal conservativity, not float replay** (S2, S3): the checker
  verifies each claimed node interval is conservative w.r.t. the exact-rational ideal
  recomputation: range ideal `(b−a)·[F.lo, F.hi]`; taylor2 ideal
  `(b−a)·[Fm] + (b−a)³/24·[F2]`; taylor4 ideal
  `(b−a)·[Fm] + (b−a)³/24·[F2m] + (b−a)⁵/1920·[F4]`; intersected forms verified against
  `max` of lower ideals / `min` of upper ideals (the engine's
  `iv_intersect_enclosures`); parent sums against `[l.lo+r.lo, l.hi+r.hi]`. Engine
  outputs pass because every engine float op is outward-padded around the exact value
  (Pad/Arith theorems), i.e. engine intervals ⊇ exact ideals. Soundness needs only the
  one-sided claimed ⊇ ideal direction — no float modeling inside the tree checker.
- **D4 — Derivative-chain binding via a computable ℚ-mirror differentiator** (S5):
  `Deriv.D` is noncomputable (`Expr` carries ℝ). The checker binds F1..F4/F2m to the
  *Lean* D-chain by reconstructing each embedded certificate's expression as a ℚ-valued
  mirror `QExpr` (computable `qexprOfNodes`, structural `DecidableEq`) and comparing
  against the computable mirror differentiator `DQ` iterated on the root integrand.
  Proved bridges: `embedQ (DQ q) = D (embedQ q)` and
  `qexprOfNodes nodes = some q → exprOf nodes = some (embedQ q)`, so checker equalities
  transport to exactly the `D`-chain hypotheses `taylor2/4_enclosure_of_evaluable`
  need. Consequence (disclosed): the certified derivative chain is Lean's `D` (pure
  `deriv()` mirror, *no* `simplify_bound` interleaving); the engine's shipped chain
  `simplify_bound ∘ deriv` may evaluate more often/tighter. Producer-vs-engine tree
  fidelity is a differential-testing residual, exactly like bridge #2's emitter
  faithfulness residual (Ledger.lean:186-191(b)).
- **D5 — Exact midpoint containment instead of rounding-model midpoint** (S4, S5):
  the midpoint evaluations (Fm, F2m) are bound by the exact-ℚ check
  `cert.input_lo ≤ (a+b)/2 ≤ cert.input_hi`. Soundness instantiates `runs_encloses`
  at the exact real midpoint. `Midpoint.lean`'s `float_midpoint_in_padded` is the
  *emitter-compatibility* justification (the engine's `iv_out(m,m)` provably passes
  this check under the model); the checker itself never reasons about rounding here.
  This is strictly fail-closed: a forged midpoint interval that excludes the exact
  midpoint refuses.
- **D6 — Policy binding is explicit and exact-ℚ** (mission §1, §6.1): the artifact
  binds request (expr sexp + structural QExpr agreement across every leaf F/Fm
  certificate), endpoints, tolerance, tree-wide `taylor_degree`, complete tree shape,
  child ordering (partition equalities `l.a = p.a ∧ l.b = r.a ∧ r.b = p.b` make silent
  swaps/gaps/overlaps impossible), per-leaf mode, budget (total nodes ≤ 60001,
  mirroring the engine's entry-check semantics), depth ≤ 60, per-leaf local tolerance
  `width ≤ (9/10)·tol·(b−a)/span` evaluated in exact ℚ, released interval = header
  `output` with `out_lo ≤ root.lo ∧ root.hi ≤ out_hi` (the engine's final outward pad)
  and final width `out_hi − out_lo ≤ tol`. Disclosed boundary: the engine evaluates the
  local-tolerance policy in f64; the shadow policy check is its exact-ℚ rendition, so
  marginal float-vs-exact acceptance differences are producer-side refusals (fail
  closed), never acceptance widening. Mode-*selection* (which form the engine tried
  first, incl. degree fallback on chain failure) is heuristic and not certifiable from
  an acceptance artifact (absence of evidence); the artifact certifies that every
  *claimed* mode's premises hold and that claimed modes never exceed the bound
  `taylor_degree`.
- **D7 — Trust boundary separation** (mission §6.5): (i) mathematical model theorems —
  Lean, axiom-clean; (ii) checker acceptance over the artifact — proved computable
  checker; (iii) artifact ↔ shipped emitter correspondence — differential testing
  residual (the shadow producer is a mirror, and `integrate-bound` output is cross-
  checked for overlap/containment, never byte-bound); (iv) source ↔ native — untouched,
  remains OPEN (roadmap item 5); (v) platform/libm — `ModelTCB` hypotheses per embedded
  certificate (vacuously dischargeable for pure-ℚ fragments); (vi) artifact identity —
  sha256 of artifact bytes recorded in evidence, digests are identity not
  authentication; (vii) real-world truth of the request — out of scope, bound only as
  commitments.
- **D8 — Fail-closed reason classes at two layers** (mission §6.4): checker-layer
  stable reason strings (malformed artifact/schema, noncanonical value, invalid or
  reversed interval, malformed tree: dup/missing/cycle-by-forward-ref/orphan/root,
  child partition mismatch, request/tolerance/epoch mismatch, unsupported leaf mode,
  missing premise / embedded-cert rejection / wrong chain expression / wrong interval,
  forged enclosure, forged parent sum, stale checker/proof identity, budget exhausted,
  depth exhausted, tolerance unmet, policy violation); producer-layer refusals mirror
  the engine's own fail-closed panics (budget/depth/f64-resolution/tolerance/
  uncertifiable integrand) and are exercised by the harness as refusal tests.
  Infrastructure absence (missing toolchain, missing embedded cert file) is reported
  as indeterminate harness failure, never as a mathematical refusal.
- **D9 — Isolation of the shadow surface** (mission §3, §7): new Lean modules under
  `proofs/lean/JackalIv/Shadow*.lean` reachable only from the (unpinned, unpackaged)
  aggregator `JackalIv.lean`; no lakefile/lean-toolchain/lake-manifest edits (all three
  sha256-pinned in range/gaussian proof identities); no new `lean_exe`; the shadow
  driver runs via `lake env lean --run`; no MANIFEST.sha256, coverage-inventory,
  compat-floor, gate-driver, receipt, claim, or plugin edits; evidence lives under
  `research/v170-bound-step-shadow/`. The six public surfaces stating "bound_step …
  remains OPEN" stay byte-identical.
- **D10 — Measurability lemma as the one new analytic prerequisite** (S6):
  `sem_measurable` by structural induction with a local rpow-measurability derivation;
  this is the only analytic fact the existing stack does not already provide, needed
  because range-only leaves admit discontinuous (but bounded, measurable) integrands.
