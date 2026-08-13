/-
JACKAL certified integration — the Taylor midpoint enclosure theorems.

Engine correspondence (`jackal_calc.anb`, section "JACKAL CERTIFIED
INTEGRATION", function `bound_step`, git 8a71540):

* `taylor2_midpoint_enclosure` ↔ the `smooth-taylor2` accepted form:
    `t2 = iv_add(base, rem2)` with
    `base = iv_mul(hI, Fm)`             — h·f(midpoint)
    `rem2 = iv_div(iv_mul(h3, F2), 24)` — h³/24 · [m2, M2], F2 = f'' over [a,b].
  This theorem is the real-analysis fact that justifies the magic constant
  h³/24: for any m2 ≤ f'' ≤ M2 on [a,b] and c = (a+b)/2, h = b−a,
    h·f(c) + h³/24·m2  ≤  ∫_a^b f  ≤  h·f(c) + h³/24·M2.

* `taylor4_midpoint_enclosure` ↔ the `smooth-taylor4` accepted form:
    `t4 = iv_add(base, iv_add(mid_term, rem4))` with
    `mid_term = iv_div(iv_mul(h3, F2m), 24)`   — h³/24 · f''(midpoint)
    `rem4     = iv_div(iv_mul(h5, F4), 1920)`  — h⁵/1920 · [m4, M4],
  F4 = f'''' over [a,b]. This theorem justifies the magic constant h⁵/1920:
  for any m4 ≤ f'''' ≤ M4 on [a,b],
    h·f(c) + h³/24·f''(c) + h⁵/1920·m4 ≤ ∫_a^b f
      ≤ h·f(c) + h³/24·f''(c) + h⁵/1920·M4.

These are theorems about exact real numbers.  The engine evaluates f and
f'' over the outward-padded midpoint INTERVAL (which provably contains the
exact real midpoint c — see `Pad.lean`) and the derivative bounds over the
outward-rounded interval evaluation of the derivative expressions, so the
float side composes with these real-analysis facts through the pad lemmas.

Hypothesis form: explicit `HasDerivAt` chains on `Icc a b` — mirroring the
engine, which receives the symbolically differentiated `f1..f4` and treats
them as the true derivatives of the integrand (its stated trust assumption
for the smooth-taylor lane).

Proof route (no appeal to Mathlib's Taylor theorem, whose one-sided
`x₀ < x` form is awkward around a midpoint): the pointwise Lagrange bound
is derived from scratch by a nested "valley" argument — the defect
g(x) = f(x) − (Taylor polynomial + lower-bound remainder) has
g(c) = g'(c) = 0 and nonnegative top derivative, so each derivative level
is monotone away from c with the right sign, giving g ≥ 0 on [a,b].
The pointwise bounds are then integrated with
`intervalIntegral.integral_mono_on`; the polynomial integrals are computed
exactly (odd centered powers vanish; ∫(x−c)² = h³/12, ∫(x−c)⁴ = h⁵/80).
-/
import JackalIv.Model
import JackalIv.Pad

namespace JackalIv

open Set

/-! ### Derivative plumbing -/

private lemma hasDerivAt_congr_val {g : ℝ → ℝ} {v w x : ℝ}
    (h : HasDerivAt g v x) (hvw : v = w) : HasDerivAt g w x := hvw ▸ h

private lemma hasDerivAt_sub_c (c x : ℝ) : HasDerivAt (fun y : ℝ => y - c) 1 x :=
  (hasDerivAt_id x).sub_const c

private lemma hasDerivAt_pow2 (c x : ℝ) :
    HasDerivAt (fun y : ℝ => (y - c) ^ 2) (2 * (x - c)) x := by
  have hfun : (fun y : ℝ => (y - c) ^ 2) = fun y : ℝ => (y - c) * (y - c) := by
    funext y; ring
  rw [hfun]
  exact hasDerivAt_congr_val ((hasDerivAt_sub_c c x).mul (hasDerivAt_sub_c c x)) (by ring)

private lemma hasDerivAt_pow3 (c x : ℝ) :
    HasDerivAt (fun y : ℝ => (y - c) ^ 3) (3 * (x - c) ^ 2) x := by
  have hfun : (fun y : ℝ => (y - c) ^ 3) = fun y : ℝ => (y - c) ^ 2 * (y - c) := by
    funext y; ring
  rw [hfun]
  exact hasDerivAt_congr_val ((hasDerivAt_pow2 c x).mul (hasDerivAt_sub_c c x)) (by ring)

private lemma hasDerivAt_pow4 (c x : ℝ) :
    HasDerivAt (fun y : ℝ => (y - c) ^ 4) (4 * (x - c) ^ 3) x := by
  have hfun : (fun y : ℝ => (y - c) ^ 4) = fun y : ℝ => (y - c) ^ 3 * (y - c) := by
    funext y; ring
  rw [hfun]
  exact hasDerivAt_congr_val ((hasDerivAt_pow3 c x).mul (hasDerivAt_sub_c c x)) (by ring)

/-- Derivative of the centered linear polynomial. -/
private lemma hasDerivAt_poly1 (c k0 k1 x : ℝ) :
    HasDerivAt (fun y : ℝ => k0 + k1 * (y - c)) k1 x := by
  exact hasDerivAt_congr_val
    ((hasDerivAt_const x k0).add ((hasDerivAt_sub_c c x).const_mul k1)) (by ring)

/-- Derivative of the centered quadratic polynomial. -/
private lemma hasDerivAt_poly2 (c k0 k1 k2 x : ℝ) :
    HasDerivAt (fun y : ℝ => k0 + k1 * (y - c) + k2 * (y - c) ^ 2)
      (k1 + 2 * k2 * (x - c)) x := by
  exact hasDerivAt_congr_val
    (((hasDerivAt_const x k0).add ((hasDerivAt_sub_c c x).const_mul k1)).add
      ((hasDerivAt_pow2 c x).const_mul k2)) (by ring)

/-- Derivative of the centered cubic polynomial. -/
private lemma hasDerivAt_poly3 (c k0 k1 k2 k3 x : ℝ) :
    HasDerivAt (fun y : ℝ => k0 + k1 * (y - c) + k2 * (y - c) ^ 2 + k3 * (y - c) ^ 3)
      (k1 + 2 * k2 * (x - c) + 3 * k3 * (x - c) ^ 2) x := by
  exact hasDerivAt_congr_val
    ((((hasDerivAt_const x k0).add ((hasDerivAt_sub_c c x).const_mul k1)).add
      ((hasDerivAt_pow2 c x).const_mul k2)).add
      ((hasDerivAt_pow3 c x).const_mul k3)) (by ring)

/-- Derivative of the centered quartic polynomial. -/
private lemma hasDerivAt_poly4 (c k0 k1 k2 k3 k4 x : ℝ) :
    HasDerivAt
      (fun y : ℝ => k0 + k1 * (y - c) + k2 * (y - c) ^ 2 + k3 * (y - c) ^ 3
        + k4 * (y - c) ^ 4)
      (k1 + 2 * k2 * (x - c) + 3 * k3 * (x - c) ^ 2 + 4 * k4 * (x - c) ^ 3) x := by
  exact hasDerivAt_congr_val
    (((((hasDerivAt_const x k0).add ((hasDerivAt_sub_c c x).const_mul k1)).add
      ((hasDerivAt_pow2 c x).const_mul k2)).add
      ((hasDerivAt_pow3 c x).const_mul k3)).add
      ((hasDerivAt_pow4 c x).const_mul k4)) (by ring)

/-! ### Monotonicity from a signed derivative on a closed interval -/

private lemma monoOn_of_hasDerivAt_nonneg {g g1 : ℝ → ℝ} {lo hi : ℝ}
    (hdg : ∀ x ∈ Icc lo hi, HasDerivAt g (g1 x) x)
    (h0 : ∀ x ∈ Icc lo hi, 0 ≤ g1 x) : MonotoneOn g (Icc lo hi) := by
  apply monotoneOn_of_deriv_nonneg (convex_Icc lo hi)
  · exact fun x hx => (hdg x hx).continuousAt.continuousWithinAt
  · intro x hx
    rw [interior_Icc] at hx
    exact (hdg x (Ioo_subset_Icc_self hx)).differentiableAt.differentiableWithinAt
  · intro x hx
    rw [interior_Icc] at hx
    rw [(hdg x (Ioo_subset_Icc_self hx)).deriv]
    exact h0 x (Ioo_subset_Icc_self hx)

private lemma antiOn_of_hasDerivAt_nonpos {g g1 : ℝ → ℝ} {lo hi : ℝ}
    (hdg : ∀ x ∈ Icc lo hi, HasDerivAt g (g1 x) x)
    (h0 : ∀ x ∈ Icc lo hi, g1 x ≤ 0) : AntitoneOn g (Icc lo hi) := by
  apply antitoneOn_of_deriv_nonpos (convex_Icc lo hi)
  · exact fun x hx => (hdg x hx).continuousAt.continuousWithinAt
  · intro x hx
    rw [interior_Icc] at hx
    exact (hdg x (Ioo_subset_Icc_self hx)).differentiableAt.differentiableWithinAt
  · intro x hx
    rw [interior_Icc] at hx
    rw [(hdg x (Ioo_subset_Icc_self hx)).deriv]
    exact h0 x (Ioo_subset_Icc_self hx)

/-- A function whose derivative is ≤ 0 left of `c` and ≥ 0 right of `c`
attains its minimum over `[a,b]` at `c`. -/
private lemma valley_min {g g1 : ℝ → ℝ} {a b c : ℝ}
    (hac : a ≤ c) (hcb : c ≤ b)
    (hdg : ∀ x ∈ Icc a b, HasDerivAt g (g1 x) x)
    (hneg : ∀ x ∈ Icc a c, g1 x ≤ 0)
    (hpos : ∀ x ∈ Icc c b, 0 ≤ g1 x) :
    ∀ x ∈ Icc a b, g c ≤ g x := by
  have hsubL : Icc a c ⊆ Icc a b := Icc_subset_Icc le_rfl hcb
  have hsubR : Icc c b ⊆ Icc a b := Icc_subset_Icc hac le_rfl
  have hanti : AntitoneOn g (Icc a c) :=
    antiOn_of_hasDerivAt_nonpos (fun x hx => hdg x (hsubL hx)) hneg
  have hmono : MonotoneOn g (Icc c b) :=
    monoOn_of_hasDerivAt_nonneg (fun x hx => hdg x (hsubR hx)) hpos
  intro x hx
  rcases le_total x c with h | h
  · exact hanti ⟨hx.1, h⟩ ⟨hac, le_rfl⟩ h
  · exact hmono ⟨le_rfl, hcb⟩ ⟨h, hx.2⟩ h

/-- The nested valley step: if `g(c) = g'(c) = 0` and `g'' ≥ 0` on `[a,b]`,
then `g ≥ 0` on `[a,b]`.  Applied once for the Taylor-2 defect and twice,
in cascade, for the Taylor-4 defect. -/
private lemma nonneg_of_two_derivs {g g1 g2 : ℝ → ℝ} {a b c : ℝ}
    (hac : a ≤ c) (hcb : c ≤ b)
    (hdg : ∀ x ∈ Icc a b, HasDerivAt g (g1 x) x)
    (hdg1 : ∀ x ∈ Icc a b, HasDerivAt g1 (g2 x) x)
    (hgc : g c = 0) (hg1c : g1 c = 0)
    (hg2 : ∀ x ∈ Icc a b, 0 ≤ g2 x) :
    ∀ x ∈ Icc a b, 0 ≤ g x := by
  have hcmem : c ∈ Icc a b := ⟨hac, hcb⟩
  have hmono1 : MonotoneOn g1 (Icc a b) := monoOn_of_hasDerivAt_nonneg hdg1 hg2
  have hneg : ∀ x ∈ Icc a c, g1 x ≤ 0 := by
    intro x hx
    have hx' : x ∈ Icc a b := ⟨hx.1, le_trans hx.2 hcb⟩
    have h := hmono1 hx' hcmem hx.2
    linarith
  have hpos : ∀ x ∈ Icc c b, 0 ≤ g1 x := by
    intro x hx
    have hx' : x ∈ Icc a b := ⟨le_trans hac hx.1, hx.2⟩
    have h := hmono1 hcmem hx' hx.1
    linarith
  intro x hx
  have h := valley_min hac hcb hdg hneg hpos x hx
  linarith

/-! ### Pointwise Lagrange bounds about an interior point -/

/-- Order-2 pointwise lower bound: with `m2 ≤ f''` on `[a,b]`,
`f(c) + f'(c)(x−c) + m2/2·(x−c)² ≤ f(x)` for every `x ∈ [a,b]`. -/
private lemma taylor2_pointwise_lower (f f' f'' : ℝ → ℝ) (a b c m2 : ℝ)
    (hac : a ≤ c) (hcb : c ≤ b)
    (hd1 : ∀ x ∈ Icc a b, HasDerivAt f (f' x) x)
    (hd2 : ∀ x ∈ Icc a b, HasDerivAt f' (f'' x) x)
    (hm2 : ∀ x ∈ Icc a b, m2 ≤ f'' x) :
    ∀ x ∈ Icc a b,
      f c + f' c * (x - c) + m2 / 2 * (x - c) ^ 2 ≤ f x := by
  have hdg : ∀ y ∈ Icc a b,
      HasDerivAt (fun z => f z - (f c + f' c * (z - c) + m2 / 2 * (z - c) ^ 2))
        (f' y - (f' c + m2 * (y - c))) y := by
    intro y hy
    exact hasDerivAt_congr_val
      ((hd1 y hy).sub (hasDerivAt_poly2 c (f c) (f' c) (m2 / 2) y)) (by ring)
  have hdg1 : ∀ y ∈ Icc a b,
      HasDerivAt (fun z => f' z - (f' c + m2 * (z - c))) (f'' y - m2) y := by
    intro y hy
    exact (hd2 y hy).sub (hasDerivAt_poly1 c (f' c) m2 y)
  intro x hx
  have h := nonneg_of_two_derivs hac hcb hdg hdg1
    (show f c - (f c + f' c * (c - c) + m2 / 2 * (c - c) ^ 2) = 0 by ring)
    (show f' c - (f' c + m2 * (c - c)) = 0 by ring)
    (fun y hy => sub_nonneg.mpr (hm2 y hy)) x hx
  have h' : 0 ≤ f x - (f c + f' c * (x - c) + m2 / 2 * (x - c) ^ 2) := h
  linarith

/-- Order-2 pointwise upper bound, by applying the lower bound to `−f`. -/
private lemma taylor2_pointwise_upper (f f' f'' : ℝ → ℝ) (a b c M2 : ℝ)
    (hac : a ≤ c) (hcb : c ≤ b)
    (hd1 : ∀ x ∈ Icc a b, HasDerivAt f (f' x) x)
    (hd2 : ∀ x ∈ Icc a b, HasDerivAt f' (f'' x) x)
    (hM2 : ∀ x ∈ Icc a b, f'' x ≤ M2) :
    ∀ x ∈ Icc a b,
      f x ≤ f c + f' c * (x - c) + M2 / 2 * (x - c) ^ 2 := by
  intro x hx
  have h := taylor2_pointwise_lower (fun y => -f y) (fun y => -f' y) (fun y => -f'' y)
    a b c (-M2) hac hcb
    (fun y hy => (hd1 y hy).neg)
    (fun y hy => (hd2 y hy).neg)
    (fun y hy => neg_le_neg (hM2 y hy)) x hx
  have h' : -f c + -f' c * (x - c) + -M2 / 2 * (x - c) ^ 2 ≤ -f x := h
  linarith

/-- Order-4 pointwise lower bound: with `m4 ≤ f''''` on `[a,b]`,
`f(c) + f'(c)(x−c) + f''(c)/2·(x−c)² + f'''(c)/6·(x−c)³ + m4/24·(x−c)⁴ ≤ f(x)`. -/
private lemma taylor4_pointwise_lower (f f' f'' f''' f'''' : ℝ → ℝ) (a b c m4 : ℝ)
    (hac : a ≤ c) (hcb : c ≤ b)
    (hd1 : ∀ x ∈ Icc a b, HasDerivAt f (f' x) x)
    (hd2 : ∀ x ∈ Icc a b, HasDerivAt f' (f'' x) x)
    (hd3 : ∀ x ∈ Icc a b, HasDerivAt f'' (f''' x) x)
    (hd4 : ∀ x ∈ Icc a b, HasDerivAt f''' (f'''' x) x)
    (hm4 : ∀ x ∈ Icc a b, m4 ≤ f'''' x) :
    ∀ x ∈ Icc a b,
      f c + f' c * (x - c) + f'' c / 2 * (x - c) ^ 2 + f''' c / 6 * (x - c) ^ 3
        + m4 / 24 * (x - c) ^ 4 ≤ f x := by
  -- Inner cascade: the order-2 defect of f'' is nonnegative.
  have hdg2 : ∀ y ∈ Icc a b,
      HasDerivAt (fun z => f'' z - (f'' c + f''' c * (z - c) + m4 / 2 * (z - c) ^ 2))
        (f''' y - (f''' c + m4 * (y - c))) y := by
    intro y hy
    exact hasDerivAt_congr_val
      ((hd3 y hy).sub (hasDerivAt_poly2 c (f'' c) (f''' c) (m4 / 2) y)) (by ring)
  have hdg3 : ∀ y ∈ Icc a b,
      HasDerivAt (fun z => f''' z - (f''' c + m4 * (z - c))) (f'''' y - m4) y := by
    intro y hy
    exact (hd4 y hy).sub (hasDerivAt_poly1 c (f''' c) m4 y)
  have h2nn : ∀ y ∈ Icc a b,
      0 ≤ f'' y - (f'' c + f''' c * (y - c) + m4 / 2 * (y - c) ^ 2) := by
    exact nonneg_of_two_derivs hac hcb hdg2 hdg3
      (show f'' c - (f'' c + f''' c * (c - c) + m4 / 2 * (c - c) ^ 2) = 0 by ring)
      (show f''' c - (f''' c + m4 * (c - c)) = 0 by ring)
      (fun y hy => sub_nonneg.mpr (hm4 y hy))
  -- Outer cascade: the order-4 defect of f is nonnegative.
  have hdg : ∀ y ∈ Icc a b,
      HasDerivAt
        (fun z => f z - (f c + f' c * (z - c) + f'' c / 2 * (z - c) ^ 2
          + f''' c / 6 * (z - c) ^ 3 + m4 / 24 * (z - c) ^ 4))
        (f' y - (f' c + f'' c * (y - c) + f''' c / 2 * (y - c) ^ 2
          + m4 / 6 * (y - c) ^ 3)) y := by
    intro y hy
    exact hasDerivAt_congr_val
      ((hd1 y hy).sub
        (hasDerivAt_poly4 c (f c) (f' c) (f'' c / 2) (f''' c / 6) (m4 / 24) y)) (by ring)
  have hdg1 : ∀ y ∈ Icc a b,
      HasDerivAt
        (fun z => f' z - (f' c + f'' c * (z - c) + f''' c / 2 * (z - c) ^ 2
          + m4 / 6 * (z - c) ^ 3))
        (f'' y - (f'' c + f''' c * (y - c) + m4 / 2 * (y - c) ^ 2)) y := by
    intro y hy
    exact hasDerivAt_congr_val
      ((hd2 y hy).sub
        (hasDerivAt_poly3 c (f' c) (f'' c) (f''' c / 2) (m4 / 6) y)) (by ring)
  intro x hx
  have h := nonneg_of_two_derivs hac hcb hdg hdg1
    (show f c - (f c + f' c * (c - c) + f'' c / 2 * (c - c) ^ 2
      + f''' c / 6 * (c - c) ^ 3 + m4 / 24 * (c - c) ^ 4) = 0 by ring)
    (show f' c - (f' c + f'' c * (c - c) + f''' c / 2 * (c - c) ^ 2
      + m4 / 6 * (c - c) ^ 3) = 0 by ring)
    h2nn x hx
  have h' : 0 ≤ f x - (f c + f' c * (x - c) + f'' c / 2 * (x - c) ^ 2
      + f''' c / 6 * (x - c) ^ 3 + m4 / 24 * (x - c) ^ 4) := h
  linarith

/-- Order-4 pointwise upper bound, by applying the lower bound to `−f`. -/
private lemma taylor4_pointwise_upper (f f' f'' f''' f'''' : ℝ → ℝ) (a b c M4 : ℝ)
    (hac : a ≤ c) (hcb : c ≤ b)
    (hd1 : ∀ x ∈ Icc a b, HasDerivAt f (f' x) x)
    (hd2 : ∀ x ∈ Icc a b, HasDerivAt f' (f'' x) x)
    (hd3 : ∀ x ∈ Icc a b, HasDerivAt f'' (f''' x) x)
    (hd4 : ∀ x ∈ Icc a b, HasDerivAt f''' (f'''' x) x)
    (hM4 : ∀ x ∈ Icc a b, f'''' x ≤ M4) :
    ∀ x ∈ Icc a b,
      f x ≤ f c + f' c * (x - c) + f'' c / 2 * (x - c) ^ 2 + f''' c / 6 * (x - c) ^ 3
        + M4 / 24 * (x - c) ^ 4 := by
  intro x hx
  have h := taylor4_pointwise_lower (fun y => -f y) (fun y => -f' y) (fun y => -f'' y)
    (fun y => -f''' y) (fun y => -f'''' y) a b c (-M4) hac hcb
    (fun y hy => (hd1 y hy).neg)
    (fun y hy => (hd2 y hy).neg)
    (fun y hy => (hd3 y hy).neg)
    (fun y hy => (hd4 y hy).neg)
    (fun y hy => neg_le_neg (hM4 y hy)) x hx
  have h' : -f c + -f' c * (x - c) + -f'' c / 2 * (x - c) ^ 2 + -f''' c / 6 * (x - c) ^ 3
      + -M4 / 24 * (x - c) ^ 4 ≤ -f x := h
  linarith

/-! ### Exact integrals of centered polynomials -/

private lemma integral_const_mul_eq (a b k : ℝ) : (∫ _ in a..b, k) = (b - a) * k := by
  simp [smul_eq_mul]

private lemma integral_sub_c (a b c : ℝ) :
    (∫ x in a..b, (x - c)) = ((b - c) ^ 2 - (a - c) ^ 2) / 2 := by
  have h : (∫ x in a..b, (x - c)) = ∫ x in (a - c)..(b - c), x :=
    intervalIntegral.integral_comp_sub_right (fun x : ℝ => x) c
  rw [h, integral_id]

private lemma integral_sub_c_sq (a b c : ℝ) :
    (∫ x in a..b, (x - c) ^ 2) = ((b - c) ^ 3 - (a - c) ^ 3) / 3 := by
  have h : (∫ x in a..b, (x - c) ^ 2) = ∫ x in (a - c)..(b - c), x ^ 2 :=
    intervalIntegral.integral_comp_sub_right (fun x : ℝ => x ^ 2) c
  rw [h, integral_pow]
  norm_num

private lemma integral_sub_c_cube (a b c : ℝ) :
    (∫ x in a..b, (x - c) ^ 3) = ((b - c) ^ 4 - (a - c) ^ 4) / 4 := by
  have h : (∫ x in a..b, (x - c) ^ 3) = ∫ x in (a - c)..(b - c), x ^ 3 :=
    intervalIntegral.integral_comp_sub_right (fun x : ℝ => x ^ 3) c
  rw [h, integral_pow]
  norm_num

private lemma integral_sub_c_quart (a b c : ℝ) :
    (∫ x in a..b, (x - c) ^ 4) = ((b - c) ^ 5 - (a - c) ^ 5) / 5 := by
  have h : (∫ x in a..b, (x - c) ^ 4) = ∫ x in (a - c)..(b - c), x ^ 4 :=
    intervalIntegral.integral_comp_sub_right (fun x : ℝ => x ^ 4) c
  rw [h, integral_pow]
  norm_num

/-- Exact integral of the centered quadratic. -/
private lemma integral_centered_poly2 (a b c k0 k1 k2 : ℝ) :
    (∫ x in a..b, (k0 + k1 * (x - c) + k2 * (x - c) ^ 2))
      = (b - a) * k0 + k1 * (((b - c) ^ 2 - (a - c) ^ 2) / 2)
        + k2 * (((b - c) ^ 3 - (a - c) ^ 3) / 3) := by
  have i0 : IntervalIntegrable (fun _ : ℝ => k0) MeasureTheory.volume a b :=
    intervalIntegrable_const
  have i1 : IntervalIntegrable (fun x : ℝ => k1 * (x - c)) MeasureTheory.volume a b :=
    (Continuous.intervalIntegrable (by fun_prop) a b)
  have i2 : IntervalIntegrable (fun x : ℝ => k2 * (x - c) ^ 2) MeasureTheory.volume a b :=
    (Continuous.intervalIntegrable (by fun_prop) a b)
  have hs1 : (∫ x in a..b, (k0 + k1 * (x - c) + k2 * (x - c) ^ 2))
      = (∫ x in a..b, (k0 + k1 * (x - c))) + ∫ x in a..b, k2 * (x - c) ^ 2 :=
    intervalIntegral.integral_add (i0.add i1) i2
  have hs2 : (∫ x in a..b, (k0 + k1 * (x - c)))
      = (∫ _ in a..b, k0) + ∫ x in a..b, k1 * (x - c) :=
    intervalIntegral.integral_add i0 i1
  have hm1 : (∫ x in a..b, k1 * (x - c)) = k1 * ∫ x in a..b, (x - c) :=
    intervalIntegral.integral_const_mul k1 _
  have hm2 : (∫ x in a..b, k2 * (x - c) ^ 2) = k2 * ∫ x in a..b, (x - c) ^ 2 :=
    intervalIntegral.integral_const_mul k2 _
  rw [hs1, hs2, hm1, hm2, integral_sub_c a b c, integral_sub_c_sq a b c,
    integral_const_mul_eq a b k0]

/-- Exact integral of the centered quartic. -/
private lemma integral_centered_poly4 (a b c k0 k1 k2 k3 k4 : ℝ) :
    (∫ x in a..b, (k0 + k1 * (x - c) + k2 * (x - c) ^ 2 + k3 * (x - c) ^ 3
        + k4 * (x - c) ^ 4))
      = (b - a) * k0 + k1 * (((b - c) ^ 2 - (a - c) ^ 2) / 2)
        + k2 * (((b - c) ^ 3 - (a - c) ^ 3) / 3)
        + k3 * (((b - c) ^ 4 - (a - c) ^ 4) / 4)
        + k4 * (((b - c) ^ 5 - (a - c) ^ 5) / 5) := by
  have i0 : IntervalIntegrable (fun _ : ℝ => k0) MeasureTheory.volume a b :=
    intervalIntegrable_const
  have i1 : IntervalIntegrable (fun x : ℝ => k1 * (x - c)) MeasureTheory.volume a b :=
    (Continuous.intervalIntegrable (by fun_prop) a b)
  have i2 : IntervalIntegrable (fun x : ℝ => k2 * (x - c) ^ 2) MeasureTheory.volume a b :=
    (Continuous.intervalIntegrable (by fun_prop) a b)
  have i3 : IntervalIntegrable (fun x : ℝ => k3 * (x - c) ^ 3) MeasureTheory.volume a b :=
    (Continuous.intervalIntegrable (by fun_prop) a b)
  have i4 : IntervalIntegrable (fun x : ℝ => k4 * (x - c) ^ 4) MeasureTheory.volume a b :=
    (Continuous.intervalIntegrable (by fun_prop) a b)
  have hs1 : (∫ x in a..b, (k0 + k1 * (x - c) + k2 * (x - c) ^ 2 + k3 * (x - c) ^ 3
        + k4 * (x - c) ^ 4))
      = (∫ x in a..b, (k0 + k1 * (x - c) + k2 * (x - c) ^ 2 + k3 * (x - c) ^ 3))
        + ∫ x in a..b, k4 * (x - c) ^ 4 :=
    intervalIntegral.integral_add (((i0.add i1).add i2).add i3) i4
  have hs2 : (∫ x in a..b, (k0 + k1 * (x - c) + k2 * (x - c) ^ 2 + k3 * (x - c) ^ 3))
      = (∫ x in a..b, (k0 + k1 * (x - c) + k2 * (x - c) ^ 2))
        + ∫ x in a..b, k3 * (x - c) ^ 3 :=
    intervalIntegral.integral_add ((i0.add i1).add i2) i3
  have hm3 : (∫ x in a..b, k3 * (x - c) ^ 3) = k3 * ∫ x in a..b, (x - c) ^ 3 :=
    intervalIntegral.integral_const_mul k3 _
  have hm4 : (∫ x in a..b, k4 * (x - c) ^ 4) = k4 * ∫ x in a..b, (x - c) ^ 4 :=
    intervalIntegral.integral_const_mul k4 _
  rw [hs1, hs2, hm3, hm4, integral_sub_c_cube a b c, integral_sub_c_quart a b c,
    integral_centered_poly2 a b c k0 k1 k2]

/-! ### The engine theorems -/

/-- **Taylor-2 midpoint enclosure** — the real-analysis content of the
engine's `smooth-taylor2` accepted form in `bound_step`:
`t2 = h·f(c) + h³/24·[m2, M2]` encloses `∫_a^b f` whenever
`m2 ≤ f'' ≤ M2` on `[a,b]`, with `c = (a+b)/2` and `h = b − a`.
This justifies the engine's magic constant `24`. -/
theorem taylor2_midpoint_enclosure
    (f f' f'' : ℝ → ℝ) (a b m2 M2 : ℝ) (hab : a < b)
    (hd1 : ∀ x ∈ Icc a b, HasDerivAt f (f' x) x)
    (hd2 : ∀ x ∈ Icc a b, HasDerivAt f' (f'' x) x)
    (hm2 : ∀ x ∈ Icc a b, m2 ≤ f'' x)
    (hM2 : ∀ x ∈ Icc a b, f'' x ≤ M2) :
    (b - a) * f ((a + b) / 2) + (b - a) ^ 3 / 24 * m2 ≤ (∫ x in a..b, f x) ∧
      (∫ x in a..b, f x) ≤ (b - a) * f ((a + b) / 2) + (b - a) ^ 3 / 24 * M2 := by
  have hac : a ≤ (a + b) / 2 := by linarith
  have hcb : (a + b) / 2 ≤ b := by linarith
  have hlow := taylor2_pointwise_lower f f' f'' a b ((a + b) / 2) m2 hac hcb hd1 hd2 hm2
  have hupp := taylor2_pointwise_upper f f' f'' a b ((a + b) / 2) M2 hac hcb hd1 hd2 hM2
  have hfc : ContinuousOn f (Icc a b) :=
    fun x hx => (hd1 x hx).continuousAt.continuousWithinAt
  have hfint : IntervalIntegrable f MeasureTheory.volume a b :=
    hfc.intervalIntegrable_of_Icc hab.le
  have hPlow : IntervalIntegrable
      (fun x => f ((a + b) / 2) + f' ((a + b) / 2) * (x - (a + b) / 2)
        + m2 / 2 * (x - (a + b) / 2) ^ 2) MeasureTheory.volume a b :=
    (Continuous.intervalIntegrable (by fun_prop) a b)
  have hPupp : IntervalIntegrable
      (fun x => f ((a + b) / 2) + f' ((a + b) / 2) * (x - (a + b) / 2)
        + M2 / 2 * (x - (a + b) / 2) ^ 2) MeasureTheory.volume a b :=
    (Continuous.intervalIntegrable (by fun_prop) a b)
  have hIlow : (∫ x in a..b, (f ((a + b) / 2) + f' ((a + b) / 2) * (x - (a + b) / 2)
        + m2 / 2 * (x - (a + b) / 2) ^ 2))
      = (b - a) * f ((a + b) / 2) + (b - a) ^ 3 / 24 * m2 := by
    rw [integral_centered_poly2]
    ring
  have hIupp : (∫ x in a..b, (f ((a + b) / 2) + f' ((a + b) / 2) * (x - (a + b) / 2)
        + M2 / 2 * (x - (a + b) / 2) ^ 2))
      = (b - a) * f ((a + b) / 2) + (b - a) ^ 3 / 24 * M2 := by
    rw [integral_centered_poly2]
    ring
  constructor
  · have hle := intervalIntegral.integral_mono_on hab.le hPlow hfint hlow
    linarith [hIlow]
  · have hle := intervalIntegral.integral_mono_on hab.le hfint hPupp hupp
    linarith [hIupp]

/-- **Taylor-4 midpoint enclosure** — the real-analysis content of the
engine's `smooth-taylor4` accepted form in `bound_step`:
`t4 = h·f(c) + h³/24·f''(c) + h⁵/1920·[m4, M4]` encloses `∫_a^b f`
whenever `m4 ≤ f'''' ≤ M4` on `[a,b]`, with `c = (a+b)/2` and `h = b − a`.
This justifies the engine's magic constant `1920 = 80·24`. -/
theorem taylor4_midpoint_enclosure
    (f f' f'' f''' f'''' : ℝ → ℝ) (a b m4 M4 : ℝ) (hab : a < b)
    (hd1 : ∀ x ∈ Icc a b, HasDerivAt f (f' x) x)
    (hd2 : ∀ x ∈ Icc a b, HasDerivAt f' (f'' x) x)
    (hd3 : ∀ x ∈ Icc a b, HasDerivAt f'' (f''' x) x)
    (hd4 : ∀ x ∈ Icc a b, HasDerivAt f''' (f'''' x) x)
    (hm4 : ∀ x ∈ Icc a b, m4 ≤ f'''' x)
    (hM4 : ∀ x ∈ Icc a b, f'''' x ≤ M4) :
    (b - a) * f ((a + b) / 2) + (b - a) ^ 3 / 24 * f'' ((a + b) / 2)
        + (b - a) ^ 5 / 1920 * m4 ≤ (∫ x in a..b, f x) ∧
      (∫ x in a..b, f x) ≤ (b - a) * f ((a + b) / 2)
        + (b - a) ^ 3 / 24 * f'' ((a + b) / 2) + (b - a) ^ 5 / 1920 * M4 := by
  have hac : a ≤ (a + b) / 2 := by linarith
  have hcb : (a + b) / 2 ≤ b := by linarith
  have hlow := taylor4_pointwise_lower f f' f'' f''' f'''' a b ((a + b) / 2) m4
    hac hcb hd1 hd2 hd3 hd4 hm4
  have hupp := taylor4_pointwise_upper f f' f'' f''' f'''' a b ((a + b) / 2) M4
    hac hcb hd1 hd2 hd3 hd4 hM4
  have hfc : ContinuousOn f (Icc a b) :=
    fun x hx => (hd1 x hx).continuousAt.continuousWithinAt
  have hfint : IntervalIntegrable f MeasureTheory.volume a b :=
    hfc.intervalIntegrable_of_Icc hab.le
  have hPlow : IntervalIntegrable
      (fun x => f ((a + b) / 2) + f' ((a + b) / 2) * (x - (a + b) / 2)
        + f'' ((a + b) / 2) / 2 * (x - (a + b) / 2) ^ 2
        + f''' ((a + b) / 2) / 6 * (x - (a + b) / 2) ^ 3
        + m4 / 24 * (x - (a + b) / 2) ^ 4) MeasureTheory.volume a b :=
    (Continuous.intervalIntegrable (by fun_prop) a b)
  have hPupp : IntervalIntegrable
      (fun x => f ((a + b) / 2) + f' ((a + b) / 2) * (x - (a + b) / 2)
        + f'' ((a + b) / 2) / 2 * (x - (a + b) / 2) ^ 2
        + f''' ((a + b) / 2) / 6 * (x - (a + b) / 2) ^ 3
        + M4 / 24 * (x - (a + b) / 2) ^ 4) MeasureTheory.volume a b :=
    (Continuous.intervalIntegrable (by fun_prop) a b)
  have hIlow : (∫ x in a..b, (f ((a + b) / 2) + f' ((a + b) / 2) * (x - (a + b) / 2)
        + f'' ((a + b) / 2) / 2 * (x - (a + b) / 2) ^ 2
        + f''' ((a + b) / 2) / 6 * (x - (a + b) / 2) ^ 3
        + m4 / 24 * (x - (a + b) / 2) ^ 4))
      = (b - a) * f ((a + b) / 2) + (b - a) ^ 3 / 24 * f'' ((a + b) / 2)
        + (b - a) ^ 5 / 1920 * m4 := by
    rw [integral_centered_poly4]
    ring
  have hIupp : (∫ x in a..b, (f ((a + b) / 2) + f' ((a + b) / 2) * (x - (a + b) / 2)
        + f'' ((a + b) / 2) / 2 * (x - (a + b) / 2) ^ 2
        + f''' ((a + b) / 2) / 6 * (x - (a + b) / 2) ^ 3
        + M4 / 24 * (x - (a + b) / 2) ^ 4))
      = (b - a) * f ((a + b) / 2) + (b - a) ^ 3 / 24 * f'' ((a + b) / 2)
        + (b - a) ^ 5 / 1920 * M4 := by
    rw [integral_centered_poly4]
    ring
  constructor
  · have hle := intervalIntegral.integral_mono_on hab.le hPlow hfint hlow
    linarith [hIlow]
  · have hle := intervalIntegral.integral_mono_on hab.le hfint hPupp hupp
    linarith [hIupp]

end JackalIv
