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
* sin/cos range soundness: the no-critical-point monotone hull, both
  one-sided widened branches, the both-widened branch, and clamp soundness
  (`Trig.lean`).
* The float-midpoint containment chain — one rounded add, exact halving,
  `iv_out` pad brackets the exact midpoint — and the centered power-integral
  identities behind the engine constants h³/24 and h⁵/1920 (`Midpoint.lean`).
* The Taylor-2 and Taylor-4 midpoint integral enclosures (`Taylor.lean`) —
  the theorems the `bound_step` smooth forms implement.

## Disclosed residuals (NOT proven here)

* The platform libm actually satisfying the ≤ 2 ulp model (an assumption of
  the model itself, stated on every engine output line).
* Conservativity of the engine's float `crit_in` test (that a real critical
  point inside [a,b] always triggers the slack-widened float test) — taken
  as a hypothesis in `Trig.lean`.
* The deep embedding: that the Anubis functions `ieval`/`bound_step`
  faithfully implement the modeled operations, and that the Anubis compiler
  and hardware faithfully execute them. Covered by testing (250-case
  containment campaign, 300-case mpmath.iv differential gate, 198-case
  suite), not proof.
* `iv_pow_int` / `iv_pow_general` / `hypot` / `atan2` / `abs` / floor-family
  containment lemmas — engine-tested; composition targets for a future pass
  (pow composes Arith + Monotone lemmas; abs/min/max are exact operations).

The engine's printed `implementation-tested-not-mechanized` residual remains
accurate: this project mechanizes the MODEL of the certified lane, not the
shipped implementation.
-/
import JackalIv.Model
import JackalIv.Pad
import JackalIv.Arith
import JackalIv.Monotone
import JackalIv.Trig
import JackalIv.Midpoint
import JackalIv.Taylor

namespace JackalIv

#print axioms le_padHi
#print axioms padLo_le
#print axioms iv_add_encloses
#print axioms iv_mul_encloses
#print axioms iv_div_encloses
#print axioms iv_monotone_encloses
#print axioms iv_sin_encloses_no_crit_clamped
#print axioms iv_cos_encloses_no_crit_clamped
#print axioms float_midpoint_in_padded
#print axioms taylor_constants_check
#print axioms taylor2_midpoint_enclosure
#print axioms taylor4_midpoint_enclosure

end JackalIv
