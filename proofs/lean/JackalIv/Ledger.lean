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

## Disclosed residuals (NOT proven here)

* The platform libm actually satisfying the ≤ 2 ulp model (an assumption of
  the model itself, stated on every engine output line).
* The solve lane's printed root-error-estimate being an actual bound: the
  engine samples f′ at ONE point (central difference), not an interval
  minimum m1, so `backward_error_bound` does not certify the printed
  number — the engine correctly keeps it `status=estimated`.
* Embedding coverage gaps, fail-closed (`Embed.lean` header): tan / asin /
  acos / cbrt / log10 / log2 / hypot / atan2 / abs / min / max /
  floor-family / iv_pow_general have per-op lemmas (Monotone / Exact /
  Pow) but NO `Runs` constructor yet — wiring them into the induction is
  future work, not a soundness gap. The embedded sin/cos constructor is
  the universal [-1,1] hull (conservatively wider than the shipped
  branches separately proved in Trig.lean).
* Differentiator coverage gaps (`Deriv.lean` header): `deriv()` rules for
  tan, asin, acos, cbrt, log10, log2, hypot, atan2 and the non-integer /
  general-exponent power lanes are not modeled; `Deriv.Expr` is a minimal
  local copy of the smooth core, to be reconciled with `Embed.Expr` in a
  future pass.
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

In dependency order: (1) wire the remaining proved operators into the `Runs`
induction and reconcile `Deriv.Expr` with `Embed.Expr`; (2) a machine-checked
bridge from the engine's parser/lowering to `Expr`; (3) a bridge showing the
actual `ieval` execution induces a `Runs` derivation; (4) compose
`bound_step`'s acceptance policy over `runs_encloses` + the Taylor bridges;
(5) source-to-native refinement (verified compilation for the Anubis lane).
Until (2)–(5) exist, the strongest honest claim is UNIVERSAL CORRECTNESS OVER
THE PRECISELY ADMITTED CERTIFIED FRAGMENT AND ITS STATED TCB — never
"universal correctness" unqualified, and never all of mathematics.

The engine's printed `implementation-tested-not-mechanized` residual remains
accurate: this project mechanizes the MODEL of the certified lane, not the
shipped implementation.
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

end JackalIv
