/-
JACKAL mechanization ledger — what is PROVEN, over what MODEL, and what
remains a disclosed residual. This file also serves as the axiom audit:
the `#print axioms` commands below surface the full axiom footprint of the
flagship theorems at build time (expected: only Lean/Mathlib's standard
`propext`, `Classical.choice`, `Quot.sound`).

## Proven (machine-checked, this project, zero `sorry`)

Over the model in `Model.lean` — outward pad ε=1e-15 relative + τ=1e-300
absolute; basic ops within δ0=2⁻⁵³ relative + σ0=2⁻¹⁰⁷⁵ absolute; libm calls
within δlib=2⁻⁵¹ relative + σ0 absolute:

* Pad admissibility and the two pad-beats-rounding facts (`Pad.lean`).
* Containment of iv_add / iv_sub / iv_neg / iv_mul / iv_div, including both
  denominator sign cases (`Arith.lean`).
* The generic monotone/antitone endpoint rule and its exp / sqrt / log /
  arctan / arcsin / arccos instances (`Monotone.lean`).
* The exact (pad-free) op family (`Exact.lean`): iv_abs (all three
  branches), iv_min / iv_max, the floor / ceil / round / trunc scalar
  family (including the engine's round-half-away-from-zero convention via
  `roundAway_mem`, and `isInt_fixed` for the |v| ≥ 2⁵³ saturation branch),
  plus the two libm binaries: `iv_hypot_encloses` (mig/mag corners +
  iv_out pad) and `iv_atan2_encloses` (guarded half-plane x > 0 as
  iv_atan ∘ iv_div, staged through the Arith division corners).
* sin/cos range soundness: the no-critical-point monotone hull, both
  one-sided widened branches, the both-widened branch, and clamp soundness
  (`Trig.lean`).
* Conservativity of the engine's `crit_in` float test (`CritIn.lean`):
  the 5-candidate window covers every relevant k, the slack accept-test is
  admissible, all-rejected ⇒ no true critical point in [a,b]
  (`crit_in_conservative`, with the sin / cos / tan instances discharging
  the `hcrit` hypotheses of `Trig.lean` verbatim), and the float error
  budget `error_budget_dominated` + `engine_candidate_within_slack`
  showing the engine's one-mul-one-add candidate evaluation stays three
  orders of magnitude inside the slack for the engine's parameter range
  (offsets 0, ±π/2, π; periods π and 2π).
* Power containment (`Pow.lean`): the even-power mignitude/magnitude hull
  and odd-power monotone hull behind iv_pow_int (n ≥ 1, both parity
  branches, libm-padded endpoints); the negative-power lane as
  iv_div([1,1], core) via the Arith division corners; and the
  iv_pow_general composition x^y = exp(y·ln x) from the ln/mul/exp stage
  enclosures under the engine's positive-base guard.
* The composition theorem (`Embed.lean`): a deep embedding of the smooth
  expression core of `ieval` (literals, var, neg/add/sub/mul/div, integer
  powers including the negative lane, sqrt/exp/ln/sin/cos/atan), an
  execution relation `Runs` carrying exactly the per-operator hypotheses
  proved in Arith/Monotone/Pow, and `runs_encloses` /
  `runs_encloses_image`: any completed run encloses the exact semantics at
  EVERY point of the input interval.
* Differentiability from evaluability (`Deriv.lean`): a symbolic
  differentiator `D` mirroring the engine's `deriv()` rule for rule,
  `deriv_correct_on` (D is the true derivative wherever the chain is
  defined), continuity, and the C¹/C²/C⁴ certificates
  `c1/c2/c4_on_of_evaluable` — mechanizing the engine's "ieval success on
  the derivative chain certifies smoothness" argument, composed end-to-end
  with Taylor.lean as `taylor2_enclosure_of_evaluable` /
  `taylor4_enclosure_of_evaluable`.
* The float-midpoint containment chain — one rounded add, exact halving,
  `iv_out` pad brackets the exact midpoint — and the centered power-integral
  identities behind the engine constants h³/24 and h⁵/1920 (`Midpoint.lean`).
* The Taylor-2 and Taylor-4 midpoint integral enclosures (`Taylor.lean`) —
  the theorems the `bound_step` smooth forms implement.
* Bisection-lane soundness (`Solve.lean`): the sign-change guard implies a
  root strictly inside the bracket (both sign orders), the per-step loop
  invariant, and the mean-value backward-error bound
  |x̂ − r| ≤ |f x̂| / m1 with its `residual_flatters` corollary — the sound
  FORM of the engine's 2026-08-13 first-order conditioning diagnostics.
* Parser / lowering bridge (implementation-correspondence #1)
  (`Parser.lean`, `Lower.lean`, `Correspondence.lean`): the engine's front end
  lifted onto the SINGLE canonical `Syntax.Expr`, closing the gap between the
  string the user typed and the tree the interval engine bounds.
  - `Parser.parse` is a deep, fuel-structural mirror of the engine's `tokenize`
    + recursive-descent `ast_parse_*` (LEFT-assoc `+ - * / %`, RIGHT-assoc `^`
    with a unary exponent, prefix `neg`, known-function/arity enforcement,
    constant-vs-var classification), producing exactly the node shapes of
    `Syntax.Expr`.  Proven: determinism (`parse_deterministic` / `parse_congr`),
    a battery of structural REJECTION lemmas that reduce in the kernel
    (`parse_empty`, `parse_unclosed_paren`, `parse_empty_call`,
    `parse_double_plus`, `parse_malformed_number`, `parse_unknown_fn`,
    `parse_arity_mismatch`), and totality on the verified corpus
    (`parse_total_*`).  The serializer `exprToSexp` reproduces the engine's
    `ast_sexp` byte-for-byte, and the in-kernel corpus lemmas
    (`parse_dump_*`, `parse_corpus_*`) check `parseDumpString` against the
    differential corpus (column 2) exactly.
  - `Lower.lower` mirrors `simplify_bound` constructor-for-constructor: the
    bottom-up algebraic-identity rewrites (neg-neg collapse; 0+u / u+0; u−0 /
    0−u; 1·u / u·1; u/1; u^1) with NO num–num folding and the fail-closed
    literal division/modulo-by-zero refusal.  Proven: `lower_preserves_sem`
    (each rewrite is a semantic identity on the defined domain) and
    `lower_preserves_defined` (each rule only drops a provably-total subterm).
  - Composition (`Correspondence.lean`): `parse_lower_denotes` (the admitted
    source denotes `sem ast`, and lowering preserves that denotation onto the
    bounded `e`) and `parse_lower_encloses` (threading that identity through the
    interval composition theorem `runs_encloses`, so every completed `ieval`
    run encloses the exact SOURCE semantics at every point of the input
    interval).  A trusted `@[implemented_by]` mirror (`Dump.lean`) makes the
    noncomputable `parseSexp` / `lowerSexp` runnable for the differential-gate
    executable (`jackal_parse_dump`) — see the residuals for its trust boundary.
* Proof-carrying `ieval` → `Runs` bridge (implementation-correspondence #2)
  (`CertTypes.lean`, `CertCheck.lean`, `CertSound.lean`, `CertCodec.lean`): a
  canonical, versioned evaluation certificate (`Header × List Node`, exact-ℚ
  fields) and a GENUINELY COMPUTABLE checker `checkCert` (structural
  well-formedness — unique ids, below-parent child refs ⇒ acyclic, single root,
  full reachability, canonical rationals; plus the per-node exact-ℚ interval
  formula and pad verification for the 29 rational-decided `Runs` constructors and
  the structural padding for the 8 transcendental ones).  The deliverables:
  - `cert_check_sound : checkCert hdr nodes = true → exprOf nodes = some e →
    ModelTCB hdr nodes → Runs e (↑input) (↑output)` — an accepted certificate
    INDUCES a `Runs` derivation (the whole-tree induction `runs_of_check`
    reconstructing all 38 constructors);
  - `cert_encloses` / `certified_release` (the mission §189 statement): the
    released interval encloses `sem e` at every point of the input interval.
  `#print axioms` on all three = `[propext, Classical.choice, Quot.sound]` ONLY.
  The checker is compiled to the executable `jackal_cert_check` DIRECTLY from
  the proved `checkCert`/`parseCert` (NO `@[implemented_by]`, NO `native_decide`
  on the trust path — unlike bridge #1's dumper).  The named TCB is
  `ModelTCB = LibmModel ∧ ConstTCB` (the 8 transcendental libm bounds + the
  const-rounding declared-value facts — Prop hypotheses, never axioms).  The
  actual engine command `range-bound-cert` (exact-ℚ evaluator) emits the
  certificate for its real computation; the fail-closed `jackal-cert-release`
  gate releases `status=bounded` only when `jackal_cert_check` accepts.
  DESIGN-BRIEF CORRECTION (2026-08-14): the soundness proof produced a
  counterexample showing `const_rounded` is NOT rational-exact (`constValue
  "pi" = Real.pi` is irrational), forcing it into `ConstTCB` — the mechanization
  refusing an unsound classification.

## Disclosed residuals (NOT proven here)

* The platform libm actually satisfying the ≤ 2 ulp model (an assumption of
  the model itself, stated on every engine output line).
* The solve lane's printed root-error-estimate being an actual bound: the
  engine samples f′ at ONE point (central difference), not an interval
  minimum m1, so `backward_error_bound` does not certify the printed
  number — the engine correctly keeps it `status=estimated`.
* Embedding coverage gaps, fail-closed (`Embed.lean` header): the operators
  still WITHOUT a `Runs` constructor are exactly `tan`, `cbrt`, `log10`,
  `log2`, and `mod` — each is a sound refusal (`DefinedOn` = its pole/negative
  guard or `False`; the composition theorem simply has no derivation), never an
  unsound approximation. (`tan` awaits an `iv_tan` containment lemma; `cbrt`
  has no Mathlib real cube root; `log10`/`log2` are covered only by the generic
  monotone rule, not a bespoke instance; `mod` is refused by the engine
  itself.) The embedded sin/cos LIBM-LANE constructor is the universal [-1,1]
  hull (conservatively wider than the shipped branches separately proved in
  Trig.lean); since §490 (v1.5.0) the PURE-ℚ lane adds `Runs.sinRat`/`cosRat`
  (midpoint Taylor via Mathlib `sin_bound`/`cos_bound`, |midpoint| ≤ 1, plus
  Lipschitz-1 widening — arguments centered outside [-1,1] REFUSE, argument
  reduction by 2πk is future work), `Runs.logRat` (full positive domain via
  the inverse exponential bracket), `Runs.atanRat` (full rational domain via
  cap / tan-bracket / reciprocal strategies over 20-digit rational π bounds),
  and generalizes `Runs.expRat` to every rational argument (reciprocal
  identity; the v1.4.1 nonnegative conditions are the `0 ≤ q` special case).
  Precision residual of the §490 trig lane, stated honestly: the sin/cos
  point enclosures carry the FIXED-degree Mathlib remainders (`|m|⁵/100`,
  `|m|⁴·5/96`), so a tan-bracketed `atan` endpoint near |1| is certified only
  to ~5·10⁻² and sin/cos points to ~10⁻²/~5·10⁻² at |m| = 1 (much tighter for
  small |m|); degree-parametric trig partial sums are future work, and none
  of this affects soundness — only enclosure width.
* Parser / lowering residuals (implementation-correspondence #1):
  - The parser's BYTE-FOR-BYTE identity to the SHIPPED engine parser over the
    full input space is a DIFFERENTIAL GATE (`tests/parser_differential.py`
    driving the `jackal_parse_dump` executable), NOT a theorem. `Parser.lean`
    proves determinism, the structural rejection lemmas, and corpus
    reproduction (the in-kernel mirror); it does not prove full-space engine
    identity, and the differential corpus is finite.
  - The executable's runnable dump is the trusted `@[implemented_by]` mirror
    `Dump.lean` (`parseSexpImpl` / `lowerSexpImpl`): a real-free transcription
    of the same control flow, needed because `parseSexp` / `lowerSexp` are
    noncomputable (`Expr.num` carries `strToReal t : ℝ`). The `@[implemented_by]`
    attribute is trusted — part of the differential gate's TCB — and adds no
    axiom to, and changes no logical content of, any theorem (every
    `#print axioms` line above reports only `[propext, Classical.choice,
    Quot.sound]`); the noncomputable spec is independently pinned to the corpus
    by the in-kernel `Parser` lemmas.
  - `ieval → Runs` is now CLOSED for the certified `range-bound-cert` fragment
    via bridge #2: the actual evaluator emits a certificate and
    `cert_check_sound` proves an accepted certificate induces `Runs`.  The
    RESIDUALS of that bridge: (a) the certified fragment is the exact-ℚ
    operators + `sin`/`cos` (universal `[-1,1]`) + named constants; the
    true-transcendental operators (`sqrt`/`exp`/`ln`/`atan`/`asin`/`acos`/
    `hypot`/`atan2`/`tan`/`cbrt`/`log10`/`log2`/`%`) and negative integer powers
    FAIL CLOSED in the ENGINE emitter (outside this bridge, sound refusals) —
    while the UNTRUSTED PYTHON producers cover `sqrt`/`exp`/`ln`/`sin`/`cos`/
    `atan` through the pure-ℚ checker strategy ops (`sqrt_rat`/`exp_rat`/
    `ln_rat`/`sin_rat`/`cos_rat`/`atan_rat`, §487/§490) with NO libm TCB;
    (b) that
    the Anubis emitter faithfully produces the certificate for the computation
    it performed is enforced by testing (positive corpus + 24 negative controls
    + the A→B→A tamper showing a non-enclosing emitter is REJECTED), not proof;
    (c) the canonical ℚ codec and the Lean compiler/runtime that builds
    `jackal_cert_check` are in the TCB.
  - `bound_step`'s release-policy composition over `runs_encloses` + the Taylor
    bridges is now MECHANIZED for the certificate lane (`int_cert_sound`,
    `IntCertSound.lean` — subdivision-tree artifact, proved computable
    `checkIntCert`, compiled `jackal_int_cert_check`), with the same class of
    residuals as (b)-(c) above: producer faithfulness to the shipped engine's
    `bound_step` control flow is enforced by testing (31-row matrix + engine
    differential), and the `jackal-int-cert` codec + Lean runtime are in the
    TCB.  Source → native refinement (verified compilation of the Anubis
    lane) remains OPEN — see roadmap item (5).
* Differentiator coverage gaps (`Deriv.lean` header): `deriv()` rules for
  tan, asin, acos, cbrt, log10, log2, hypot, atan2 and the non-integer /
  general-exponent power lanes are not modeled by `D` (nodes outside `D`'s
  domain hit the never-defined sentinel — fail-closed, never mis-differentiated).
  `Deriv` and `Embed` now share the SINGLE canonical `Syntax.Expr` (the local
  copy was removed this wave); the continuity ladder is scoped to a `Smooth`
  sublanguage inhabited by every `D`-output, so the C^k theorems keep their
  original signatures.

* Gate sensitivity is itself tested (`tests/parser_differential.py --tamper`,
  and the recorded manual mirror-tamper): a semantic mutation of the runnable
  `Dump` mirror's power rule (base/exponent swap) that still COMPILES and RUNS
  produces an observable `PARSE_DRIFT` and a nonzero gate result, while the
  in-kernel spec lemmas stay proved — demonstrating the differential gate would
  catch a mirror that drifts from the spec, so the `@[implemented_by]` TCB is
  live, not silent.
* Float facts consumed as model-level hypotheses where the real-number
  model cannot see them: the `IsInt` saturation hypothesis of the
  floor-family (`Exact.lean` — every binary64 of magnitude ≥ 2⁵³ is an
  integer), the exactness of small-integer float arithmetic in
  `error_budget_dominated`'s `hm` (`CritIn.lean`), and the engine's
  "integer-valued f64 literal is exact" test behind `num_exact`
  (`Embed.lean`).
* The deep implementation gap: that the Anubis functions `ieval` /
  `bound_step` faithfully implement the modeled operations, and that the
  Anubis compiler and hardware faithfully execute them. Covered by testing
  (250-case containment campaign, 300-case mpmath.iv differential gate,
  200-case suite incl. the Kepler-conditioning and Fresnel-certification
  field cases), not proof.
* The exact rational / big-integer lanes are OUTSIDE this Lean scope: their
  carry-split invariants (`base_low` / `base_high`) are machine-checked
  in-language by the Anubis SMT checker, and their outputs are
  campaign-tested against Python/sympy oracles; full functional correctness
  of the bigint/rational algorithms is not mechanized here, and the interval
  proofs above imply nothing about them.

## Next mechanization wave (roadmap, cross-audited 2026-08-13)

In dependency order: (1) wire the remaining proved operators
(tan/cbrt/log10/log2) into the `Runs` induction; (2) DONE — the machine-checked
bridge from the engine's parser/lowering to the single canonical `Expr`
(`Parser.parse` + `Lower.lower` + `Correspondence.parse_lower_denotes` /
`parse_lower_encloses`, this wave), which also reconciled `Deriv.Expr` with
`Embed.Expr` onto `Syntax.Expr`; (3) DONE — the proof-carrying `ieval → Runs`
bridge (`CertTypes`/`CertCheck`/`CertSound`/`CertCodec`, `cert_check_sound`,
compiled checker `jackal_cert_check`, `range-bound-cert` emitter, fail-closed
`jackal-cert-release`): an accepted certificate for the exact-ℚ fragment
mechanically induces a `Runs` derivation, so the actual evaluator's certified
release carries a checker-verified witness; (4) DONE (v1.7) — `bound_step`'s
acceptance policy composed over `runs_encloses` + the Taylor bridges
(`IntCertTypes`/`IntCertCheck`/`IntCertSound`/`IntCertCodec`,
`int_cert_sound`, compiled checker `jackal_int_cert_check`, untrusted
producer `tools/int_cert_producer.py`, fail-closed `jackal-int-cert-release`):
an accepted `jackal-int-cert` subdivision-tree artifact mechanically induces
per-leaf `Runs` derivations plus exact-partition interval-sum composition, so
the certified integrate-bound-cert release carries a checker-verified
enclosure of the requested definite integral; (5) source-to-native
refinement (verified compilation for the Anubis lane). Until (5) exists, the
strongest honest claim is UNIVERSAL CORRECTNESS OVER THE PRECISELY ADMITTED
CERTIFIED FRAGMENT AND ITS STATED TCB — never "universal correctness"
unqualified, and never all of mathematics.

The engine's printed `implementation-tested-not-mechanized` residual remains
accurate: this project mechanizes the MODEL of the certified lane, not the
shipped implementation.

## Runtime provenance vs checker soundness (v1.0.4 release binding)

`cert_check_sound` proves ENCLOSURE — an accepted certificate implies a `Runs`
derivation under `ModelTCB`. It deliberately does NOT prove runtime
PROVENANCE: that the certificate was emitted for the exact request the caller
framed, by the exact evaluator executable, and checked by the exact checker
executable. That provenance is enforced OUTSIDE Lean by the fail-closed shared
release validator (`tests/release_validate.py`): exact request-commitment
binding, evaluator/checker executable-identity binding (pre/post-hashed,
TOCTOU), and no status escalation. This separation is the honest boundary — a
raw or forged certificate may lie about `source`/`exe`; the checker theorem is
agnostic to those fields, and the validator catches the lie. Do not read the
Lean theorems as proving request parsing, emitter faithfulness, executable
identity, or release-wrapper correctness.
-/
import JackalIv.Model
import JackalIv.Pad
import JackalIv.Arith
import JackalIv.Monotone
import JackalIv.Exact
import JackalIv.Trig
import JackalIv.CritIn
import JackalIv.Pow
import JackalIv.Embed
import JackalIv.Midpoint
import JackalIv.Taylor
import JackalIv.Deriv
import JackalIv.Solve
import JackalIv.Parser
import JackalIv.Lower
import JackalIv.Correspondence
import JackalIv.IntCertSound

namespace JackalIv

#print axioms le_padHi
#print axioms padLo_le
#print axioms iv_add_encloses
#print axioms iv_mul_encloses
#print axioms iv_div_encloses
#print axioms iv_monotone_encloses
#print axioms iv_abs_encloses
#print axioms iv_min_encloses
#print axioms iv_max_encloses
#print axioms roundAway_mem
#print axioms iv_hypot_encloses
#print axioms iv_atan2_encloses
#print axioms iv_sin_encloses_no_crit_clamped
#print axioms iv_cos_encloses_no_crit_clamped
#print axioms crit_in_conservative
#print axioms crit_in_conservative_sin
#print axioms crit_in_conservative_cos
#print axioms crit_in_conservative_tan
#print axioms error_budget_dominated
#print axioms engine_candidate_within_slack
#print axioms float_midpoint_in_padded
#print axioms taylor_constants_check
#print axioms taylor2_midpoint_enclosure
#print axioms taylor4_midpoint_enclosure
#print axioms iv_pow_int_even_encloses
#print axioms iv_pow_int_odd_encloses
#print axioms iv_pow_neg_encloses
#print axioms iv_pow_neg_encloses_zpow
#print axioms rpow_general_encloses
#print axioms runs_sound
#print axioms runs_encloses
#print axioms runs_encloses_image
#print axioms Deriv.deriv_correct_on
#print axioms Deriv.c2_on_of_evaluable
#print axioms Deriv.c4_on_of_evaluable
#print axioms Deriv.taylor2_enclosure_of_evaluable
#print axioms Deriv.taylor4_enclosure_of_evaluable
#print axioms bracket_has_root
#print axioms bisection_invariant
#print axioms backward_error_bound
#print axioms residual_flatters
-- Parser / lowering bridge (implementation-correspondence #1)
#print axioms Parser.parse_empty
#print axioms lower_preserves_sem
#print axioms lower_preserves_defined
#print axioms parse_lower_denotes
#print axioms parse_lower_encloses
-- v1.7 certified integrate-bound-cert lane (bound_step composition, roadmap #4)
#print axioms IntCert.int_cert_sound
#print axioms IntCert.range_leaf_sound
#print axioms IntCert.taylor2_leaf_sound
#print axioms IntCert.taylor4_leaf_sound
#print axioms IntCert.split_sound
#print axioms IntCert.sem_measurable
#print axioms IntCert.embedQ_DQ
#print axioms IntCert.embedQ_DQiter
#print axioms IntCert.qexprOf_embed
#print axioms IntCert.qbuild_embed

end JackalIv
