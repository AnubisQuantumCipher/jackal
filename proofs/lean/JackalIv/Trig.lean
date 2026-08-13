/-
JackalIv/Trig.lean — sin/cos range soundness for the JACKAL certified
interval engine.

Engine correspondence (jackal_calc.anb, section "JACKAL CERTIFIED INTERVAL
ENGINE", fns `iv_sin` (line ~2370), `iv_cos` (line ~2387), `crit_in`
(line ~2357), git 8a71540):

* `iv_sin(a)` over `[a.lo, a.hi]` with width < 2π computes
  `s1 = sin(a.lo)`, `s2 = sin(a.hi)` via libm (modeled here as
  `Approx δlib σ0 s1 (Real.sin a)` etc.), pads the hull
  `iv_out(min s1 s2, max s1 s2)` — modeled as
  `[min (padLo s1) (padLo s2), max (padHi s1) (padHi s2)]`, which equals
  `[padLo (min s1 s2), padHi (max s1 s2)]` by `padLo_min` / `padHi_max`
  below — then widens `hi := 1` if `crit_in(lo, hi, π/2, 2π)` and
  `lo := -1` if `crit_in(lo, hi, -π/2, 2π)`, and finally clamps
  `lo := max lo (-1)`, `hi := min hi 1`.

* The float test `crit_in` is slack-widened so that a REAL critical point
  inside `[a,b]` always triggers it.  That conservativity is a separately
  disclosed assumption about the float code; here it appears as the
  hypothesis "`crit_in` returned false ⇒ no critical point of that family
  lies in `Set.Icc a b`".

Theorem → engine-line map:

| theorem                          | engine behaviour modeled                     |
|----------------------------------|----------------------------------------------|
| `sin_mem_Icc`, `cos_mem_Icc`     | range facts backing the final clamp          |
| `clamp_encloses`,                | `if lo < -1 { lo = -1 }; if hi > 1 { hi = 1 }`|
|  `sin_clamp_encloses`,           |   (iv_sin lines 2382–2383,                   |
|  `cos_clamp_encloses`            |    iv_cos lines 2399–2400)                   |
| `padLo_min`, `padHi_max`         | `iv_out(min s1 s2, max s1 s2)` = endpointwise pad |
| `cos_ne_zero_of_no_crit`         | both sin `crit_in` tests false ⇒ cos ≠ 0 on [a,b] |
| `sin_ne_zero_of_no_crit`         | both cos `crit_in` tests false ⇒ sin ≠ 0 on [a,b] |
| `sin_monotoneOn_of_no_crit`      | why the endpoint hull is exact for sin       |
| `cos_monotoneOn_of_no_crit`      | why the endpoint hull is exact for cos       |
| `iv_sin_encloses_no_crit`        | iv_sin branch: neither `crit_in` fired       |
| `iv_sin_encloses_no_crit_clamped`| same branch incl. the final clamp            |
| `iv_cos_encloses_no_crit`        | iv_cos branch: neither `crit_in` fired       |
| `iv_cos_encloses_no_crit_clamped`| same branch incl. the final clamp            |
| `sin_min_endpoint_bound` etc.    | one-sided hull exactness when only the       |
|                                  | opposite extremum family may be present      |
| `iv_sin_encloses_hi_widened`     | iv_sin branch: only max-crit fired (`hi := 1`)|
| `iv_sin_encloses_lo_widened`     | iv_sin branch: only min-crit fired (`lo := -1`)|
| `iv_cos_encloses_hi_widened`     | iv_cos branch: only max-crit fired           |
| `iv_cos_encloses_lo_widened`     | iv_cos branch: only min-crit fired           |
| `iv_sin_encloses_maybe_crit`     | both fired, or width ≥ 2π: box = [-1,1]      |
| `iv_cos_encloses_maybe_crit`     | both fired, or width ≥ 2π: box = [-1,1]      |

Claims discipline: all statements are about the model in `JackalIv.Model`;
the libm quality (`Approx δlib σ0 _ _`) and the `crit_in` conservativity
are hypotheses, mirroring the engine's disclosed trust assumptions.
-/
import JackalIv.Model
import JackalIv.Pad

namespace JackalIv

open Real Set

/-! ### 1. Range facts and the final clamp (iv_sin lines 2382–2383) -/

/-- `Real.sin x` always lies in `[-1, 1]` — the fact backing the clamp. -/
theorem sin_mem_Icc (x : ℝ) : Real.sin x ∈ Set.Icc (-1 : ℝ) 1 :=
  ⟨Real.neg_one_le_sin x, Real.sin_le_one x⟩

/-- `Real.cos x` always lies in `[-1, 1]`. -/
theorem cos_mem_Icc (x : ℝ) : Real.cos x ∈ Set.Icc (-1 : ℝ) 1 :=
  ⟨Real.neg_one_le_cos x, Real.cos_le_one x⟩

/-- Clamping an enclosure of a value known to lie in `[-1,1]` keeps it an
enclosure (engine: `if lo < -1 { lo = -1 }; if hi > 1 { hi = 1 }`). -/
theorem clamp_encloses {lo hi y : ℝ} (hlo : lo ≤ y) (hhi : y ≤ hi)
    (hy1 : -1 ≤ y) (hy2 : y ≤ 1) :
    max lo (-1) ≤ y ∧ y ≤ min hi 1 :=
  ⟨max_le hlo hy1, le_min hhi hy2⟩

/-- Clamp lemma specialized to sin: any enclosure of `sin x` survives the
final clamp of `iv_sin`. -/
theorem sin_clamp_encloses {lo hi x : ℝ}
    (h : lo ≤ Real.sin x ∧ Real.sin x ≤ hi) :
    max lo (-1) ≤ Real.sin x ∧ Real.sin x ≤ min hi 1 :=
  clamp_encloses h.1 h.2 (Real.neg_one_le_sin x) (Real.sin_le_one x)

/-- Clamp lemma specialized to cos: any enclosure of `cos x` survives the
final clamp of `iv_cos`. -/
theorem cos_clamp_encloses {lo hi x : ℝ}
    (h : lo ≤ Real.cos x ∧ Real.cos x ≤ hi) :
    max lo (-1) ≤ Real.cos x ∧ Real.cos x ≤ min hi 1 :=
  clamp_encloses h.1 h.2 (Real.neg_one_le_cos x) (Real.cos_le_one x)

/-! ### 2. Pad/hull bookkeeping (iv_out(min s1 s2, max s1 s2)) -/

/-- Padding the min endpoint equals the min of the padded endpoints — the
engine's `iv_out(min s1 s2, …)` lower side in either reading. -/
lemma padLo_min (s1 s2 : ℝ) : padLo (min s1 s2) = min (padLo s1) (padLo s2) :=
  padLo_mono.map_min

/-- Padding the max endpoint equals the max of the padded endpoints. -/
lemma padHi_max (s1 s2 : ℝ) : padHi (max s1 s2) = max (padHi s1) (padHi s2) :=
  padHi_mono.map_max

/-- If two libm results bracket the exact endpoint values and `y` lies in the
exact hull, then `y` lies in the padded computed hull.  This is the generic
soundness of `iv_out(min s1 s2, max s1 s2)` for any function value `y`
between the exact endpoint values. -/
lemma padded_hull_encloses {s1 s2 u v y : ℝ}
    (h1 : Approx δlib σ0 s1 u) (h2 : Approx δlib σ0 s2 v)
    (hlo : min u v ≤ y) (hhi : y ≤ max u v) :
    min (padLo s1) (padLo s2) ≤ y ∧ y ≤ max (padHi s1) (padHi s2) := by
  obtain ⟨h1lo, h1hi⟩ := libm_brackets s1 u h1
  obtain ⟨h2lo, h2hi⟩ := libm_brackets s2 v h2
  exact ⟨le_trans (min_le_min h1lo h2lo) hlo,
         le_trans hhi (max_le_max h1hi h2hi)⟩

/-- A function monotone-or-antitone on `[a,b]` stays inside the hull of its
endpoint values there. -/
lemma between_endpoints {f : ℝ → ℝ} {a b x : ℝ} (hab : a ≤ b)
    (hf : MonotoneOn f (Set.Icc a b) ∨ AntitoneOn f (Set.Icc a b))
    (hx : x ∈ Set.Icc a b) :
    min (f a) (f b) ≤ f x ∧ f x ≤ max (f a) (f b) := by
  have ha : a ∈ Set.Icc a b := Set.left_mem_Icc.mpr hab
  have hb : b ∈ Set.Icc a b := Set.right_mem_Icc.mpr hab
  rcases hf with hm | hm
  · exact ⟨(min_le_left _ _).trans (hm ha hx hx.1),
           (hm hx hb hx.2).trans (le_max_right _ _)⟩
  · exact ⟨(min_le_right _ _).trans (hm hx hb hx.2),
           (hm ha hx hx.1).trans (le_max_left _ _)⟩

/-! ### 3. Sign constancy and monotonicity between critical points -/

/-- A continuous function with no zero on `[a,b]` has constant sign there
(by the intermediate value theorem). -/
lemma sign_const_on_of_ne_zero {g : ℝ → ℝ} {a b : ℝ} (hg : Continuous g)
    (hab : a ≤ b) (h : ∀ x ∈ Set.Icc a b, g x ≠ 0) :
    (∀ x ∈ Set.Icc a b, 0 < g x) ∨ (∀ x ∈ Set.Icc a b, g x < 0) := by
  rcases lt_or_gt_of_ne (h a (Set.left_mem_Icc.mpr hab)) with hneg | hpos
  · right
    intro x hx
    by_contra hnot
    push Not at hnot
    have hzero : (0 : ℝ) ∈ Set.Icc (g a) (g x) := ⟨hneg.le, hnot⟩
    obtain ⟨c, hc, hgc⟩ := intermediate_value_Icc hx.1 hg.continuousOn hzero
    exact h c ⟨hc.1, hc.2.trans hx.2⟩ hgc
  · left
    intro x hx
    by_contra hnot
    push Not at hnot
    have hzero : (0 : ℝ) ∈ Set.Icc (g x) (g a) := ⟨hnot, hpos.le⟩
    obtain ⟨c, hc, hgc⟩ := intermediate_value_Icc' hx.1 hg.continuousOn hzero
    exact h c ⟨hc.1, hc.2.trans hx.2⟩ hgc

/-- Bridge from the engine's two sin `crit_in` families to zeros of cos:
if no maximizer `π/2 + 2kπ` and no minimizer `-π/2 + 2kπ` lies in `[a,b]`,
then cos has no zero in `[a,b]` (`Real.cos_eq_zero_iff`, parity split). -/
lemma cos_ne_zero_of_no_crit {a b : ℝ}
    (hcrit : ∀ k : ℤ, (π / 2 + (k : ℝ) * (2 * π)) ∉ Set.Icc a b ∧
                      (-(π / 2) + (k : ℝ) * (2 * π)) ∉ Set.Icc a b) :
    ∀ x ∈ Set.Icc a b, Real.cos x ≠ 0 := by
  intro x hx hzero
  obtain ⟨k, hk⟩ := Real.cos_eq_zero_iff.mp hzero
  rcases Int.even_or_odd k with ⟨m, hm⟩ | ⟨m, hm⟩
  · apply (hcrit m).1
    have he : π / 2 + (m : ℝ) * (2 * π) = x := by
      rw [hk, hm]; push_cast; ring
    rwa [he]
  · apply (hcrit (m + 1)).2
    have he : -(π / 2) + ((m + 1 : ℤ) : ℝ) * (2 * π) = x := by
      rw [hk, hm]; push_cast; ring
    rwa [he]

/-- Bridge from the engine's two cos `crit_in` families to zeros of sin:
if no maximizer `2kπ` and no minimizer `π + 2kπ` lies in `[a,b]`, then sin
has no zero in `[a,b]` (`Real.sin_eq_zero_iff`, parity split). -/
lemma sin_ne_zero_of_no_crit {a b : ℝ}
    (hcrit : ∀ k : ℤ, ((k : ℝ) * (2 * π)) ∉ Set.Icc a b ∧
                      (π + (k : ℝ) * (2 * π)) ∉ Set.Icc a b) :
    ∀ x ∈ Set.Icc a b, Real.sin x ≠ 0 := by
  intro x hx hzero
  obtain ⟨n, hn⟩ := Real.sin_eq_zero_iff.mp hzero
  rcases Int.even_or_odd n with ⟨m, hm⟩ | ⟨m, hm⟩
  · apply (hcrit m).1
    have he : (m : ℝ) * (2 * π) = x := by
      rw [← hn, hm]; push_cast; ring
    rwa [he]
  · apply (hcrit m).2
    have he : π + (m : ℝ) * (2 * π) = x := by
      rw [← hn, hm]; push_cast; ring
    rwa [he]

/-- If cos has no zero on `[a,b]`, then sin is monotone or antitone on
`[a,b]` — the reason `iv_sin`'s endpoint hull is exact on the no-crit
branch.  (Sign constancy of cos by IVT, then the derivative test with
`Real.deriv_sin`.) -/
theorem sin_monotoneOn_of_no_crit {a b : ℝ} (hab : a ≤ b)
    (hcos : ∀ x ∈ Set.Icc a b, Real.cos x ≠ 0) :
    MonotoneOn Real.sin (Set.Icc a b) ∨ AntitoneOn Real.sin (Set.Icc a b) := by
  rcases sign_const_on_of_ne_zero Real.continuous_cos hab hcos with hpos | hneg
  · left
    refine (strictMonoOn_of_deriv_pos (convex_Icc a b)
      Real.continuous_sin.continuousOn ?_).monotoneOn
    intro x hx
    rw [Real.deriv_sin]
    exact hpos x (interior_subset hx)
  · right
    refine (strictAntiOn_of_deriv_neg (convex_Icc a b)
      Real.continuous_sin.continuousOn ?_).antitoneOn
    intro x hx
    rw [Real.deriv_sin]
    exact hneg x (interior_subset hx)

/-- If sin has no zero on `[a,b]`, then cos is monotone or antitone on
`[a,b]` (derivative of cos is `-sin`, `Real.deriv_cos`). -/
theorem cos_monotoneOn_of_no_crit {a b : ℝ} (hab : a ≤ b)
    (hsin : ∀ x ∈ Set.Icc a b, Real.sin x ≠ 0) :
    MonotoneOn Real.cos (Set.Icc a b) ∨ AntitoneOn Real.cos (Set.Icc a b) := by
  rcases sign_const_on_of_ne_zero Real.continuous_sin hab hsin with hpos | hneg
  · right
    refine (strictAntiOn_of_deriv_neg (convex_Icc a b)
      Real.continuous_cos.continuousOn ?_).antitoneOn
    intro x hx
    rw [Real.deriv_cos]
    have := hpos x (interior_subset hx)
    linarith
  · left
    refine (strictMonoOn_of_deriv_pos (convex_Icc a b)
      Real.continuous_cos.continuousOn ?_).monotoneOn
    intro x hx
    rw [Real.deriv_cos]
    have := hneg x (interior_subset hx)
    linarith

/-! ### 4. iv_sin / iv_cos: the no-crit branch -/

/-- `iv_sin`, branch where neither `crit_in` test fired (conservativity of
`crit_in` means no real critical point of sin lies in `[a,b]`): the padded
endpoint hull `[min (padLo s1) (padLo s2), max (padHi s1) (padHi s2)]`
(equivalently `[padLo (min s1 s2), padHi (max s1 s2)]` — engine's literal
`iv_out(min s1 s2, max s1 s2)` — by `padLo_min` / `padHi_max`) encloses
`sin x` for every `x ∈ [a,b]`. -/
theorem iv_sin_encloses_no_crit {a b s1 s2 x : ℝ} (hab : a ≤ b)
    (hcrit : ∀ k : ℤ, (π / 2 + (k : ℝ) * (2 * π)) ∉ Set.Icc a b ∧
                      (-(π / 2) + (k : ℝ) * (2 * π)) ∉ Set.Icc a b)
    (hs1 : Approx δlib σ0 s1 (Real.sin a))
    (hs2 : Approx δlib σ0 s2 (Real.sin b))
    (hx : x ∈ Set.Icc a b) :
    min (padLo s1) (padLo s2) ≤ Real.sin x ∧
      Real.sin x ≤ max (padHi s1) (padHi s2) := by
  have hmono := sin_monotoneOn_of_no_crit hab (cos_ne_zero_of_no_crit hcrit)
  have hbet := between_endpoints hab hmono hx
  exact padded_hull_encloses hs1 hs2 hbet.1 hbet.2

/-- Same branch of `iv_sin`, composed with the final clamp: the box the
engine actually returns encloses `sin x`. -/
theorem iv_sin_encloses_no_crit_clamped {a b s1 s2 x : ℝ} (hab : a ≤ b)
    (hcrit : ∀ k : ℤ, (π / 2 + (k : ℝ) * (2 * π)) ∉ Set.Icc a b ∧
                      (-(π / 2) + (k : ℝ) * (2 * π)) ∉ Set.Icc a b)
    (hs1 : Approx δlib σ0 s1 (Real.sin a))
    (hs2 : Approx δlib σ0 s2 (Real.sin b))
    (hx : x ∈ Set.Icc a b) :
    max (min (padLo s1) (padLo s2)) (-1) ≤ Real.sin x ∧
      Real.sin x ≤ min (max (padHi s1) (padHi s2)) 1 :=
  sin_clamp_encloses (iv_sin_encloses_no_crit hab hcrit hs1 hs2 hx)

/-- `iv_cos`, branch where neither `crit_in` test fired: the padded endpoint
hull encloses `cos x` for every `x ∈ [a,b]`. -/
theorem iv_cos_encloses_no_crit {a b s1 s2 x : ℝ} (hab : a ≤ b)
    (hcrit : ∀ k : ℤ, ((k : ℝ) * (2 * π)) ∉ Set.Icc a b ∧
                      (π + (k : ℝ) * (2 * π)) ∉ Set.Icc a b)
    (hs1 : Approx δlib σ0 s1 (Real.cos a))
    (hs2 : Approx δlib σ0 s2 (Real.cos b))
    (hx : x ∈ Set.Icc a b) :
    min (padLo s1) (padLo s2) ≤ Real.cos x ∧
      Real.cos x ≤ max (padHi s1) (padHi s2) := by
  have hmono := cos_monotoneOn_of_no_crit hab (sin_ne_zero_of_no_crit hcrit)
  have hbet := between_endpoints hab hmono hx
  exact padded_hull_encloses hs1 hs2 hbet.1 hbet.2

/-- Same branch of `iv_cos`, composed with the final clamp. -/
theorem iv_cos_encloses_no_crit_clamped {a b s1 s2 x : ℝ} (hab : a ≤ b)
    (hcrit : ∀ k : ℤ, ((k : ℝ) * (2 * π)) ∉ Set.Icc a b ∧
                      (π + (k : ℝ) * (2 * π)) ∉ Set.Icc a b)
    (hs1 : Approx δlib σ0 s1 (Real.cos a))
    (hs2 : Approx δlib σ0 s2 (Real.cos b))
    (hx : x ∈ Set.Icc a b) :
    max (min (padLo s1) (padLo s2)) (-1) ≤ Real.cos x ∧
      Real.cos x ≤ min (max (padHi s1) (padHi s2)) 1 :=
  cos_clamp_encloses (iv_cos_encloses_no_crit hab hcrit hs1 hs2 hx)

/-! ### 5. One-sided hull exactness (mixed crit branches)

When only ONE `crit_in` test fires, the engine widens that side to ±1 but
keeps the padded endpoint hull on the other side.  Soundness of the kept
side needs only the absence of the OPPOSITE extremum family: the min (resp.
max) of sin over `[a,b]` is attained at an endpoint or at an interior
critical point, and the only interior critical points available are of the
harmless (opposite) kind. -/

/-- If no minimizer `-π/2 + 2kπ` of sin lies in `[a,b]`, then sin is bounded
below on `[a,b]` by the min of its endpoint values. -/
lemma sin_min_endpoint_bound {a b x : ℝ} (hab : a ≤ b)
    (hmin : ∀ k : ℤ, (-(π / 2) + (k : ℝ) * (2 * π)) ∉ Set.Icc a b)
    (hx : x ∈ Set.Icc a b) :
    min (Real.sin a) (Real.sin b) ≤ Real.sin x := by
  obtain ⟨c, hc, hcmin⟩ := isCompact_Icc.exists_isMinOn
    (Set.nonempty_Icc.mpr hab) Real.continuous_sin.continuousOn
  have hcx : Real.sin c ≤ Real.sin x := isMinOn_iff.mp hcmin x hx
  rcases eq_or_lt_of_le hc.1 with hac | hac
  · exact (min_le_left _ _).trans (by rw [hac]; exact hcx)
  rcases eq_or_lt_of_le hc.2 with hcb | hcb
  · exact (min_le_right _ _).trans (by rw [← hcb]; exact hcx)
  -- interior minimum ⇒ cos c = 0
  have hloc : IsLocalMin Real.sin c := hcmin.isLocalMin (Icc_mem_nhds hac hcb)
  have hcos : Real.cos c = 0 := by
    have h0 := hloc.deriv_eq_zero
    rwa [Real.deriv_sin] at h0
  obtain ⟨k, hk⟩ := Real.cos_eq_zero_iff.mp hcos
  rcases Int.even_or_odd k with ⟨m, hm⟩ | ⟨m, hm⟩
  · -- maximizer form: sin c = 1, so everything is ≥ the endpoint min anyway
    have hsc : Real.sin c = 1 :=
      Real.sin_eq_one_iff.mpr ⟨m, by rw [hk, hm]; push_cast; ring⟩
    calc min (Real.sin a) (Real.sin b) ≤ Real.sin a := min_le_left _ _
      _ ≤ 1 := Real.sin_le_one a
      _ = Real.sin c := hsc.symm
      _ ≤ Real.sin x := hcx
  · -- minimizer form: excluded by hypothesis
    exfalso
    apply hmin (m + 1)
    have he : -(π / 2) + ((m + 1 : ℤ) : ℝ) * (2 * π) = c := by
      rw [hk, hm]; push_cast; ring
    rwa [he]

/-- If no maximizer `π/2 + 2kπ` of sin lies in `[a,b]`, then sin is bounded
above on `[a,b]` by the max of its endpoint values. -/
lemma sin_max_endpoint_bound {a b x : ℝ} (hab : a ≤ b)
    (hmax : ∀ k : ℤ, (π / 2 + (k : ℝ) * (2 * π)) ∉ Set.Icc a b)
    (hx : x ∈ Set.Icc a b) :
    Real.sin x ≤ max (Real.sin a) (Real.sin b) := by
  obtain ⟨c, hc, hcmax⟩ := isCompact_Icc.exists_isMaxOn
    (Set.nonempty_Icc.mpr hab) Real.continuous_sin.continuousOn
  have hcx : Real.sin x ≤ Real.sin c := isMaxOn_iff.mp hcmax x hx
  rcases eq_or_lt_of_le hc.1 with hac | hac
  · exact le_trans (by rw [hac]; exact hcx) (le_max_left _ _)
  rcases eq_or_lt_of_le hc.2 with hcb | hcb
  · exact le_trans (by rw [hcb] at hcx; exact hcx) (le_max_right _ _)
  have hloc : IsLocalMax Real.sin c := hcmax.isLocalMax (Icc_mem_nhds hac hcb)
  have hcos : Real.cos c = 0 := by
    have h0 := hloc.deriv_eq_zero
    rwa [Real.deriv_sin] at h0
  obtain ⟨k, hk⟩ := Real.cos_eq_zero_iff.mp hcos
  rcases Int.even_or_odd k with ⟨m, hm⟩ | ⟨m, hm⟩
  · -- maximizer form: excluded by hypothesis
    exfalso
    apply hmax m
    have he : π / 2 + (m : ℝ) * (2 * π) = c := by
      rw [hk, hm]; push_cast; ring
    rwa [he]
  · -- minimizer form: sin c = -1, so everything is ≤ the endpoint max anyway
    have hsc : Real.sin c = -1 :=
      Real.sin_eq_neg_one_iff.mpr ⟨m + 1, by rw [hk, hm]; push_cast; ring⟩
    calc Real.sin x ≤ Real.sin c := hcx
      _ = -1 := hsc
      _ ≤ Real.sin a := Real.neg_one_le_sin a
      _ ≤ max (Real.sin a) (Real.sin b) := le_max_left _ _

/-- If no minimizer `π + 2kπ` of cos lies in `[a,b]`, then cos is bounded
below on `[a,b]` by the min of its endpoint values. -/
lemma cos_min_endpoint_bound {a b x : ℝ} (hab : a ≤ b)
    (hmin : ∀ k : ℤ, (π + (k : ℝ) * (2 * π)) ∉ Set.Icc a b)
    (hx : x ∈ Set.Icc a b) :
    min (Real.cos a) (Real.cos b) ≤ Real.cos x := by
  obtain ⟨c, hc, hcmin⟩ := isCompact_Icc.exists_isMinOn
    (Set.nonempty_Icc.mpr hab) Real.continuous_cos.continuousOn
  have hcx : Real.cos c ≤ Real.cos x := isMinOn_iff.mp hcmin x hx
  rcases eq_or_lt_of_le hc.1 with hac | hac
  · exact (min_le_left _ _).trans (by rw [hac]; exact hcx)
  rcases eq_or_lt_of_le hc.2 with hcb | hcb
  · exact (min_le_right _ _).trans (by rw [← hcb]; exact hcx)
  have hloc : IsLocalMin Real.cos c := hcmin.isLocalMin (Icc_mem_nhds hac hcb)
  have hsin : Real.sin c = 0 := by
    have h0 := hloc.deriv_eq_zero
    rw [Real.deriv_cos] at h0
    linarith
  obtain ⟨n, hn⟩ := Real.sin_eq_zero_iff.mp hsin
  rcases Int.even_or_odd n with ⟨m, hm⟩ | ⟨m, hm⟩
  · -- maximizer form: cos c = 1
    have hsc : Real.cos c = 1 :=
      (Real.cos_eq_one_iff c).mpr ⟨m, by rw [← hn, hm]; push_cast; ring⟩
    calc min (Real.cos a) (Real.cos b) ≤ Real.cos a := min_le_left _ _
      _ ≤ 1 := Real.cos_le_one a
      _ = Real.cos c := hsc.symm
      _ ≤ Real.cos x := hcx
  · -- minimizer form: excluded by hypothesis
    exfalso
    apply hmin m
    have he : π + (m : ℝ) * (2 * π) = c := by
      rw [← hn, hm]; push_cast; ring
    rwa [he]

/-- If no maximizer `2kπ` of cos lies in `[a,b]`, then cos is bounded above
on `[a,b]` by the max of its endpoint values. -/
lemma cos_max_endpoint_bound {a b x : ℝ} (hab : a ≤ b)
    (hmax : ∀ k : ℤ, ((k : ℝ) * (2 * π)) ∉ Set.Icc a b)
    (hx : x ∈ Set.Icc a b) :
    Real.cos x ≤ max (Real.cos a) (Real.cos b) := by
  obtain ⟨c, hc, hcmax⟩ := isCompact_Icc.exists_isMaxOn
    (Set.nonempty_Icc.mpr hab) Real.continuous_cos.continuousOn
  have hcx : Real.cos x ≤ Real.cos c := isMaxOn_iff.mp hcmax x hx
  rcases eq_or_lt_of_le hc.1 with hac | hac
  · exact le_trans (by rw [hac]; exact hcx) (le_max_left _ _)
  rcases eq_or_lt_of_le hc.2 with hcb | hcb
  · exact le_trans (by rw [hcb] at hcx; exact hcx) (le_max_right _ _)
  have hloc : IsLocalMax Real.cos c := hcmax.isLocalMax (Icc_mem_nhds hac hcb)
  have hsin : Real.sin c = 0 := by
    have h0 := hloc.deriv_eq_zero
    rw [Real.deriv_cos] at h0
    linarith
  obtain ⟨n, hn⟩ := Real.sin_eq_zero_iff.mp hsin
  rcases Int.even_or_odd n with ⟨m, hm⟩ | ⟨m, hm⟩
  · -- maximizer form: excluded by hypothesis
    exfalso
    apply hmax m
    have he : (m : ℝ) * (2 * π) = c := by
      rw [← hn, hm]; push_cast; ring
    rwa [he]
  · -- minimizer form: cos c = -1
    have hsc : Real.cos c = -1 :=
      Real.cos_eq_neg_one_iff.mpr ⟨m, by rw [← hn, hm]; push_cast; ring⟩
    calc Real.cos x ≤ Real.cos c := hcx
      _ = -1 := hsc
      _ ≤ Real.cos a := Real.neg_one_le_cos a
      _ ≤ max (Real.cos a) (Real.cos b) := le_max_left _ _

/-! ### 6. iv_sin / iv_cos: the widened branches -/

/-- `iv_sin`, branch where only the max-crit test fired (`hi := 1`): the
kept lower side is the padded hull minimum (sound because no minimizer lies
in `[a,b]` — the `crit_in` conservativity hypothesis for the min family),
and the widened upper side is `1`. -/
theorem iv_sin_encloses_hi_widened {a b s1 s2 x : ℝ} (hab : a ≤ b)
    (hmin : ∀ k : ℤ, (-(π / 2) + (k : ℝ) * (2 * π)) ∉ Set.Icc a b)
    (hs1 : Approx δlib σ0 s1 (Real.sin a))
    (hs2 : Approx δlib σ0 s2 (Real.sin b))
    (hx : x ∈ Set.Icc a b) :
    min (padLo s1) (padLo s2) ≤ Real.sin x ∧ Real.sin x ≤ 1 := by
  refine ⟨?_, Real.sin_le_one x⟩
  have h1 := (libm_brackets s1 _ hs1).1
  have h2 := (libm_brackets s2 _ hs2).1
  exact le_trans (min_le_min h1 h2) (sin_min_endpoint_bound hab hmin hx)

/-- `iv_sin`, branch where only the min-crit test fired (`lo := -1`): the
widened lower side is `-1`, and the kept upper side is the padded hull
maximum (sound because no maximizer lies in `[a,b]`). -/
theorem iv_sin_encloses_lo_widened {a b s1 s2 x : ℝ} (hab : a ≤ b)
    (hmax : ∀ k : ℤ, (π / 2 + (k : ℝ) * (2 * π)) ∉ Set.Icc a b)
    (hs1 : Approx δlib σ0 s1 (Real.sin a))
    (hs2 : Approx δlib σ0 s2 (Real.sin b))
    (hx : x ∈ Set.Icc a b) :
    (-1 : ℝ) ≤ Real.sin x ∧ Real.sin x ≤ max (padHi s1) (padHi s2) := by
  refine ⟨Real.neg_one_le_sin x, ?_⟩
  have h1 := (libm_brackets s1 _ hs1).2
  have h2 := (libm_brackets s2 _ hs2).2
  exact le_trans (sin_max_endpoint_bound hab hmax hx) (max_le_max h1 h2)

/-- `iv_cos`, branch where only the max-crit test fired (`hi := 1`). -/
theorem iv_cos_encloses_hi_widened {a b s1 s2 x : ℝ} (hab : a ≤ b)
    (hmin : ∀ k : ℤ, (π + (k : ℝ) * (2 * π)) ∉ Set.Icc a b)
    (hs1 : Approx δlib σ0 s1 (Real.cos a))
    (hs2 : Approx δlib σ0 s2 (Real.cos b))
    (hx : x ∈ Set.Icc a b) :
    min (padLo s1) (padLo s2) ≤ Real.cos x ∧ Real.cos x ≤ 1 := by
  refine ⟨?_, Real.cos_le_one x⟩
  have h1 := (libm_brackets s1 _ hs1).1
  have h2 := (libm_brackets s2 _ hs2).1
  exact le_trans (min_le_min h1 h2) (cos_min_endpoint_bound hab hmin hx)

/-- `iv_cos`, branch where only the min-crit test fired (`lo := -1`). -/
theorem iv_cos_encloses_lo_widened {a b s1 s2 x : ℝ} (hab : a ≤ b)
    (hmax : ∀ k : ℤ, ((k : ℝ) * (2 * π)) ∉ Set.Icc a b)
    (hs1 : Approx δlib σ0 s1 (Real.cos a))
    (hs2 : Approx δlib σ0 s2 (Real.cos b))
    (hx : x ∈ Set.Icc a b) :
    (-1 : ℝ) ≤ Real.cos x ∧ Real.cos x ≤ max (padHi s1) (padHi s2) := by
  refine ⟨Real.neg_one_le_cos x, ?_⟩
  have h1 := (libm_brackets s1 _ hs1).2
  have h2 := (libm_brackets s2 _ hs2).2
  exact le_trans (cos_max_endpoint_bound hab hmax hx) (max_le_max h1 h2)

/-- `iv_sin`, branch where both `crit_in` tests fired — and also the early
width-≥-2π branch: the returned box `[-1, 1]` always encloses `sin x`. -/
theorem iv_sin_encloses_maybe_crit {a b x : ℝ} (_hx : x ∈ Set.Icc a b) :
    (-1 : ℝ) ≤ Real.sin x ∧ Real.sin x ≤ 1 :=
  ⟨Real.neg_one_le_sin x, Real.sin_le_one x⟩

/-- `iv_cos`, branch where both `crit_in` tests fired — and also the early
width-≥-2π branch: the returned box `[-1, 1]` always encloses `cos x`. -/
theorem iv_cos_encloses_maybe_crit {a b x : ℝ} (_hx : x ∈ Set.Icc a b) :
    (-1 : ℝ) ≤ Real.cos x ∧ Real.cos x ≤ 1 :=
  ⟨Real.neg_one_le_cos x, Real.cos_le_one x⟩

end JackalIv
