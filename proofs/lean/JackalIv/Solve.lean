/-
Soundness lemmas for the JACKAL bisection SOLVE lane and its conditioning
diagnostics.

Engine correspondence (`jackal_calc.anb`, `main()` op == "solve",
lines 3073–3124, including the 2026-08-13 first-order backward-error
diagnostics block at lines 3097–3121):

* `bracket_has_root` ↔ the sign-change guard (lines 3079–3085): `solve`
  panics unless `f(lo)` and `f(hi)` have strictly opposite signs
  (`(flo > 0 && fhi > 0) || (flo < 0 && fhi < 0) → panic`, and the exact-zero
  endpoint cases return early), so the surviving path has `f(lo)·f(hi) < 0`.
  For a function continuous on `[lo, hi]` that guard guarantees a REAL root
  strictly inside `(lo, hi)` — the intermediate value theorem, both sign
  orders.
* `bisection_invariant` ↔ the loop body (lines 3086–3094): each step
  replaces one endpoint by the midpoint, always keeping the sign change
  (`if (fmid > 0) == (flo > 0) { lo = mid; flo = fmid } else { hi = mid;
  fhi = fmid }`). The invariant every step preserves is the same
  root-existence fact restated on the current subinterval
  `[l', u'] ⊆ [lo, hi]`.
* `backward_error_bound` ↔ the diagnostics block (lines 3097–3121): with a
  root `r`, an estimate `x̂`, and `m1 ≤ |f′|` throughout an interval
  containing both, the mean value theorem gives `|x̂ − r| ≤ |f(x̂)| / m1`.
  The engine's printed `root-error-estimate = residual ×
  condition-amplification` with `amplification = 1/|f′(root-estimate)|`
  (lines 3114–3116) is the first-order instantiation of this bound.
* `residual_flatters` ↔ the engine comment at lines 3097–3101, made
  precise: `|f(x̂)| ≥ m1·|x̂ − r|` — a residual can understate the root
  error by exactly the factor `min |f′|`, so the printed
  condition-amplification `1/|f′(root-estimate)|` is the first-order
  reciprocal of that factor.

Claims discipline: the ENGINE samples `f′` at ONE point (central difference
with step `h = √ε_mach · max(1, |root|)`, lines 3105–3108) — a point
ESTIMATE of the derivative, not an interval minimum `m1` — so its printed
root-error-estimate correctly stays `status=estimated` /
`assurance=estimate-not-bound(first-order)`. The lemmas here are the sound
FORM that diagnostic instantiates (field adjudication, Kepler case
2026-08-13: residual 2.3e-20, condition-amplification 6.06e7, true root
error 1.3e-12). As everywhere in this development, `f` is the exact real
function; the gap to the engine's floating-point evaluation of the
expression is a disclosed residual — see `Ledger.lean`.
-/
import JackalIv.Model

namespace JackalIv

/-! ### Root existence — models the sign-change guard (lines 3079–3085) -/

/-- `bracket_has_root`: if `f` is continuous on `[lo, hi]` and
`f lo * f hi < 0` (the engine's surviving non-panic path), then a root lies
strictly inside `(lo, hi)`. Both sign orders. -/
theorem bracket_has_root (f : ℝ → ℝ) (lo hi : ℝ) (hlt : lo < hi)
    (hcont : ContinuousOn f (Set.Icc lo hi))
    (hsign : f lo * f hi < 0) :
    ∃ r ∈ Set.Ioo lo hi, f r = 0 := by
  rcases mul_neg_iff.mp hsign with ⟨hflo_pos, hfhi_neg⟩ | ⟨hflo_neg, hfhi_pos⟩
  · -- f lo > 0 > f hi: downward crossing
    have h0 : (0 : ℝ) ∈ Set.Ioo (f hi) (f lo) := ⟨hfhi_neg, hflo_pos⟩
    obtain ⟨r, hr, hfr⟩ := intermediate_value_Ioo' hlt.le hcont h0
    exact ⟨r, hr, hfr⟩
  · -- f lo < 0 < f hi: upward crossing
    have h0 : (0 : ℝ) ∈ Set.Ioo (f lo) (f hi) := ⟨hflo_neg, hfhi_pos⟩
    obtain ⟨r, hr, hfr⟩ := intermediate_value_Ioo hlt.le hcont h0
    exact ⟨r, hr, hfr⟩

/-! ### The bisection loop invariant (lines 3086–3094) -/

/-- `bisection_invariant`: the fact each bisection step preserves. If the
current bracket `[l', u']` sits inside the original `[lo, hi]` (where `f`
is continuous) and still carries the sign change, a root lies strictly
inside `(l', u')`. This is `bracket_has_root` restated on the subinterval
the loop maintains. -/
theorem bisection_invariant (f : ℝ → ℝ) (lo hi l' u' : ℝ) (hlt : l' < u')
    (hsub : Set.Icc l' u' ⊆ Set.Icc lo hi)
    (hcont : ContinuousOn f (Set.Icc lo hi))
    (hsign : f l' * f u' < 0) :
    ∃ r ∈ Set.Ioo l' u', f r = 0 :=
  bracket_has_root f l' u' hlt (hcont.mono hsub) hsign

/-! ### First-order backward error (diagnostics block, lines 3097–3121) -/

/-- Core mean-value estimate shared by `backward_error_bound` and
`residual_flatters`: with a derivative floor `m1` on `[a, b]` and a root
`r`, the residual at `x̂` dominates `m1 · |x̂ − r|`. -/
private lemma m1_mul_dist_le_abs (f : ℝ → ℝ) (a b xhat r m1 : ℝ)
    (hx : xhat ∈ Set.Icc a b) (hr : r ∈ Set.Icc a b)
    (hdiff : DifferentiableOn ℝ f (Set.Icc a b))
    (hroot : f r = 0)
    (hlow : ∀ ξ ∈ Set.Icc a b, m1 ≤ |deriv f ξ|) :
    m1 * |xhat - r| ≤ |f xhat| := by
  rcases lt_trichotomy xhat r with hlt | heq | hgt
  · -- x̂ < r: mean value on [x̂, r]
    have hsubIcc : Set.Icc xhat r ⊆ Set.Icc a b := Set.Icc_subset_Icc hx.1 hr.2
    have hsubIoo : Set.Ioo xhat r ⊆ Set.Icc a b :=
      Set.Ioo_subset_Icc_self.trans hsubIcc
    have hcont : ContinuousOn f (Set.Icc xhat r) :=
      hdiff.continuousOn.mono hsubIcc
    have hdio : DifferentiableOn ℝ f (Set.Ioo xhat r) := hdiff.mono hsubIoo
    obtain ⟨c, hc, hslope⟩ := exists_deriv_eq_slope f hlt hcont hdio
    have hm := hlow c (hsubIoo hc)
    rw [hslope, hroot, zero_sub] at hm
    -- hm : m1 ≤ |(-f x̂) / (r - x̂)|
    have hpos : (0 : ℝ) < r - xhat := sub_pos.mpr hlt
    rw [abs_div, abs_neg, abs_of_pos hpos] at hm
    have hprod := (le_div_iff₀ hpos).mp hm
    -- hprod : m1 * (r - x̂) ≤ |f x̂|
    have habs : |xhat - r| = r - xhat := by
      rw [abs_sub_comm]; exact abs_of_pos hpos
    rw [habs]; exact hprod
  · -- x̂ = r: both sides collapse (|f x̂| = 0 too, but 0 ≤ |·| suffices)
    subst heq
    rw [sub_self, abs_zero, mul_zero]
    exact abs_nonneg _
  · -- r < x̂: mean value on [r, x̂]
    have hsubIcc : Set.Icc r xhat ⊆ Set.Icc a b := Set.Icc_subset_Icc hr.1 hx.2
    have hsubIoo : Set.Ioo r xhat ⊆ Set.Icc a b :=
      Set.Ioo_subset_Icc_self.trans hsubIcc
    have hcont : ContinuousOn f (Set.Icc r xhat) :=
      hdiff.continuousOn.mono hsubIcc
    have hdio : DifferentiableOn ℝ f (Set.Ioo r xhat) := hdiff.mono hsubIoo
    obtain ⟨c, hc, hslope⟩ := exists_deriv_eq_slope f hgt hcont hdio
    have hm := hlow c (hsubIoo hc)
    rw [hslope, hroot, sub_zero] at hm
    -- hm : m1 ≤ |f x̂ / (x̂ - r)|
    have hpos : (0 : ℝ) < xhat - r := sub_pos.mpr hgt
    rw [abs_div, abs_of_pos hpos] at hm
    have hprod := (le_div_iff₀ hpos).mp hm
    -- hprod : m1 * (x̂ - r) ≤ |f x̂|
    have habs : |xhat - r| = xhat - r := abs_of_pos hpos
    rw [habs]; exact hprod

/-- `backward_error_bound`: the sound form of the engine's first-order
root-error diagnostic. If `f` is differentiable on `[a, b]` containing both
the estimate `x̂` and a root `r` (`f r = 0`), and `0 < m1 ≤ |f′|` throughout
`[a, b]`, then `|x̂ − r| ≤ |f x̂| / m1`. The engine's printed
`root-error-estimate = residual / |f′(root-estimate)|` is this bound with
the interval minimum `m1` replaced by a one-point derivative sample — hence
`status=estimated`, not a bound. -/
theorem backward_error_bound (f : ℝ → ℝ) (a b xhat r m1 : ℝ)
    (hx : xhat ∈ Set.Icc a b) (hr : r ∈ Set.Icc a b)
    (hdiff : DifferentiableOn ℝ f (Set.Icc a b))
    (hroot : f r = 0) (hm1 : 0 < m1)
    (hlow : ∀ ξ ∈ Set.Icc a b, m1 ≤ |deriv f ξ|) :
    |xhat - r| ≤ |f xhat| / m1 := by
  have hcore := m1_mul_dist_le_abs f a b xhat r m1 hx hr hdiff hroot hlow
  rw [le_div_iff₀ hm1, mul_comm]
  exact hcore

/-- `residual_flatters`: the field finding made precise. Under the
hypotheses of `backward_error_bound`, `|f x̂| ≥ m1 · |x̂ − r|` — a residual
can be smaller than the root error by exactly the factor `min |f′|`; the
engine's printed condition-amplification `1/|f′(root-estimate)|` is the
first-order reciprocal of that factor (Kepler case 2026-08-13: residual
2.3e-20 flattered a true root error of 1.3e-12 by amplification 6.06e7). -/
theorem residual_flatters (f : ℝ → ℝ) (a b xhat r m1 : ℝ)
    (hx : xhat ∈ Set.Icc a b) (hr : r ∈ Set.Icc a b)
    (hdiff : DifferentiableOn ℝ f (Set.Icc a b))
    (hroot : f r = 0) (hm1 : 0 < m1)
    (hlow : ∀ ξ ∈ Set.Icc a b, m1 ≤ |deriv f ξ|) :
    m1 * |xhat - r| ≤ |f xhat| := by
  have h := backward_error_bound f a b xhat r m1 hx hr hdiff hroot hm1 hlow
  have h2 := (le_div_iff₀ hm1).mp h
  -- h2 : |x̂ - r| * m1 ≤ |f x̂|
  rw [mul_comm]
  exact h2

end JackalIv
