/-
Containment lemmas for the JACKAL interval ARITHMETIC ops.

Engine correspondence (`jackal_calc.anb`, section "JACKAL CERTIFIED INTERVAL
ENGINE", git 8a71540) — each theorem here models one engine function:

* `iv_add_encloses`  ↔ `iv_add(a, b) = iv_out(a.lo + b.lo, a.hi + b.hi)`.
  Each endpoint is ONE IEEE-754 basic op, modeled as `Approx δ0 σ0`; `iv_out`
  is `padLo`/`padHi`.
* `iv_sub_encloses`  ↔ `iv_sub(a, b) = iv_out(a.lo - b.hi, a.hi - b.lo)`.
  Same one-basic-op-per-endpoint model.
* `iv_neg_encloses`  ↔ `iv_neg(a) = { lo := -a.hi, hi := -a.lo }`.
  IEEE-754 negation is EXACT, so the engine applies no pad; neither do we.
* `mul_mem_corners` + `iv_mul_encloses` ↔ `iv_mul(a, b)`:
  four rounded corner products p1..p4 (each `Approx δ0 σ0` against its exact
  corner), exact float `min`/`max` of the four, then `iv_out` on min and max.
* `div_mem_corners` + `iv_div_encloses` ↔ `iv_div(a, b)`:
  same shape with quotients q1..q4, guarded by the engine check
  `b.lo <= 0 && b.hi >= 0 → error`, i.e. the hypothesis `0 < yl ∨ yu < 0`.

The float `min`/`max` in `iv_mul`/`iv_div` are exact (no rounding), which is
why the pad is applied only once, to the selected extremes — mirrored here by
`padLo (min …)` / `padHi (max …)`.
-/
import JackalIv.Model
import JackalIv.Pad

namespace JackalIv

/-! ### Addition — models `iv_add` -/

/-- `iv_add`: endpoints `fl_lo ≈ xl + yl`, `fl_hi ≈ xu + yu` (one basic op
each), padded by `iv_out`, enclose the exact sum `x + y`. -/
theorem iv_add_encloses (xl xu yl yu x y fl_lo fl_hi : ℝ)
    (hx1 : xl ≤ x) (hx2 : x ≤ xu) (hy1 : yl ≤ y) (hy2 : y ≤ yu)
    (hlo : Approx δ0 σ0 fl_lo (xl + yl))
    (hhi : Approx δ0 σ0 fl_hi (xu + yu)) :
    padLo fl_lo ≤ x + y ∧ x + y ≤ padHi fl_hi := by
  have hLo := (basic_brackets fl_lo (xl + yl) hlo).1
  have hHi := (basic_brackets fl_hi (xu + yu) hhi).2
  constructor
  · linarith
  · linarith

/-! ### Subtraction — models `iv_sub` -/

/-- `iv_sub`: endpoints `fl_lo ≈ xl − yu`, `fl_hi ≈ xu − yl` (one basic op
each), padded by `iv_out`, enclose the exact difference `x − y`. -/
theorem iv_sub_encloses (xl xu yl yu x y fl_lo fl_hi : ℝ)
    (hx1 : xl ≤ x) (hx2 : x ≤ xu) (hy1 : yl ≤ y) (hy2 : y ≤ yu)
    (hlo : Approx δ0 σ0 fl_lo (xl - yu))
    (hhi : Approx δ0 σ0 fl_hi (xu - yl)) :
    padLo fl_lo ≤ x - y ∧ x - y ≤ padHi fl_hi := by
  have hLo := (basic_brackets fl_lo (xl - yu) hlo).1
  have hHi := (basic_brackets fl_hi (xu - yl) hhi).2
  constructor
  · linarith
  · linarith

/-! ### Negation — models `iv_neg` (exact, no pad) -/

/-- `iv_neg`: IEEE-754 negation is exact, so `[-xu, -xl]` encloses `-x`
with no pad — exactly what the engine returns. -/
theorem iv_neg_encloses (xl xu x : ℝ) (hx1 : xl ≤ x) (hx2 : x ≤ xu) :
    -xu ≤ -x ∧ -x ≤ -xl :=
  ⟨neg_le_neg hx2, neg_le_neg hx1⟩

/-! ### Multiplication — models `iv_mul` -/

/-- Linearity in the left factor: for `t ∈ [a, b]`, `t * y` is at most the
larger of the endpoint products. -/
private lemma mul_le_max_endpoints (a b y t : ℝ) (h1 : a ≤ t) (h2 : t ≤ b) :
    t * y ≤ max (a * y) (b * y) := by
  rcases le_total 0 y with hy | hy
  · exact le_max_of_le_right (mul_le_mul_of_nonneg_right h2 hy)
  · exact le_max_of_le_left (mul_le_mul_of_nonpos_right h1 hy)

/-- Linearity in the left factor: for `t ∈ [a, b]`, `t * y` is at least the
smaller of the endpoint products. -/
private lemma min_endpoints_le_mul (a b y t : ℝ) (h1 : a ≤ t) (h2 : t ≤ b) :
    min (a * y) (b * y) ≤ t * y := by
  rcases le_total 0 y with hy | hy
  · exact min_le_of_left_le (mul_le_mul_of_nonneg_right h1 hy)
  · exact min_le_of_right_le (mul_le_mul_of_nonpos_right h2 hy)

/-- Corner lemma for `iv_mul`: the exact product `x * y` lies between the min
and max of the four exact corner products — the mathematical fact behind the
engine taking `min/max` of `p1..p4`. -/
theorem mul_mem_corners (xl xu yl yu x y : ℝ)
    (hx1 : xl ≤ x) (hx2 : x ≤ xu) (hy1 : yl ≤ y) (hy2 : y ≤ yu) :
    min (min (xl * yl) (xl * yu)) (min (xu * yl) (xu * yu)) ≤ x * y ∧
    x * y ≤ max (max (xl * yl) (xl * yu)) (max (xu * yl) (xu * yu)) := by
  constructor
  · -- lower bound
    have hstep : min (xl * y) (xu * y) ≤ x * y :=
      min_endpoints_le_mul xl xu y x hx1 hx2
    have hxl : min (xl * yl) (xl * yu) ≤ xl * y := by
      have := min_endpoints_le_mul yl yu xl y hy1 hy2
      simpa [mul_comm] using this
    have hxu : min (xu * yl) (xu * yu) ≤ xu * y := by
      have := min_endpoints_le_mul yl yu xu y hy1 hy2
      simpa [mul_comm] using this
    exact le_trans (min_le_min hxl hxu) hstep
  · -- upper bound
    have hstep : x * y ≤ max (xl * y) (xu * y) :=
      mul_le_max_endpoints xl xu y x hx1 hx2
    have hxl : xl * y ≤ max (xl * yl) (xl * yu) := by
      have := mul_le_max_endpoints yl yu xl y hy1 hy2
      simpa [mul_comm] using this
    have hxu : xu * y ≤ max (xu * yl) (xu * yu) := by
      have := mul_le_max_endpoints yl yu xu y hy1 hy2
      simpa [mul_comm] using this
    exact le_trans hstep (max_le_max hxl hxu)

/-- The padded min of four rounded values sits below the min of their exact
counterparts: `padLo` of the float `min` is a lower bound for every exact
corner. Models the `iv_out(min(min(p1,p2),min(p3,p4)), …)` lower side. -/
private lemma padLo_min4_le (p1 p2 p3 p4 e1 e2 e3 e4 : ℝ)
    (h1 : Approx δ0 σ0 p1 e1) (h2 : Approx δ0 σ0 p2 e2)
    (h3 : Approx δ0 σ0 p3 e3) (h4 : Approx δ0 σ0 p4 e4) :
    padLo (min (min p1 p2) (min p3 p4)) ≤ min (min e1 e2) (min e3 e4) := by
  have k1 : padLo (min (min p1 p2) (min p3 p4)) ≤ e1 :=
    le_trans (padLo_mono (le_trans (min_le_left _ _) (min_le_left _ _)))
      (basic_brackets p1 e1 h1).1
  have k2 : padLo (min (min p1 p2) (min p3 p4)) ≤ e2 :=
    le_trans (padLo_mono (le_trans (min_le_left _ _) (min_le_right _ _)))
      (basic_brackets p2 e2 h2).1
  have k3 : padLo (min (min p1 p2) (min p3 p4)) ≤ e3 :=
    le_trans (padLo_mono (le_trans (min_le_right _ _) (min_le_left _ _)))
      (basic_brackets p3 e3 h3).1
  have k4 : padLo (min (min p1 p2) (min p3 p4)) ≤ e4 :=
    le_trans (padLo_mono (le_trans (min_le_right _ _) (min_le_right _ _)))
      (basic_brackets p4 e4 h4).1
  exact le_min (le_min k1 k2) (le_min k3 k4)

/-- Dual of `padLo_min4_le` for the upper side: `padHi` of the float `max`
dominates every exact corner. -/
private lemma le_padHi_max4 (p1 p2 p3 p4 e1 e2 e3 e4 : ℝ)
    (h1 : Approx δ0 σ0 p1 e1) (h2 : Approx δ0 σ0 p2 e2)
    (h3 : Approx δ0 σ0 p3 e3) (h4 : Approx δ0 σ0 p4 e4) :
    max (max e1 e2) (max e3 e4) ≤ padHi (max (max p1 p2) (max p3 p4)) := by
  have k1 : e1 ≤ padHi (max (max p1 p2) (max p3 p4)) :=
    le_trans (basic_brackets p1 e1 h1).2
      (padHi_mono (le_trans (le_max_left _ _) (le_max_left _ _)))
  have k2 : e2 ≤ padHi (max (max p1 p2) (max p3 p4)) :=
    le_trans (basic_brackets p2 e2 h2).2
      (padHi_mono (le_trans (le_max_right _ _) (le_max_left _ _)))
  have k3 : e3 ≤ padHi (max (max p1 p2) (max p3 p4)) :=
    le_trans (basic_brackets p3 e3 h3).2
      (padHi_mono (le_trans (le_max_left _ _) (le_max_right _ _)))
  have k4 : e4 ≤ padHi (max (max p1 p2) (max p3 p4)) :=
    le_trans (basic_brackets p4 e4 h4).2
      (padHi_mono (le_trans (le_max_right _ _) (le_max_right _ _)))
  exact max_le (max_le k1 k2) (max_le k3 k4)

/-- `iv_mul`: the four rounded corner products `p̃1 ≈ xl*yl`, `p̃2 ≈ xl*yu`,
`p̃3 ≈ xu*yl`, `p̃4 ≈ xu*yu`, min/max'd exactly and padded by `iv_out`,
enclose the exact product `x * y`. -/
theorem iv_mul_encloses (xl xu yl yu x y p1 p2 p3 p4 : ℝ)
    (hx1 : xl ≤ x) (hx2 : x ≤ xu) (hy1 : yl ≤ y) (hy2 : y ≤ yu)
    (h1 : Approx δ0 σ0 p1 (xl * yl)) (h2 : Approx δ0 σ0 p2 (xl * yu))
    (h3 : Approx δ0 σ0 p3 (xu * yl)) (h4 : Approx δ0 σ0 p4 (xu * yu)) :
    padLo (min (min p1 p2) (min p3 p4)) ≤ x * y ∧
    x * y ≤ padHi (max (max p1 p2) (max p3 p4)) := by
  obtain ⟨hcornerLo, hcornerHi⟩ := mul_mem_corners xl xu yl yu x y hx1 hx2 hy1 hy2
  exact ⟨le_trans (padLo_min4_le p1 p2 p3 p4 _ _ _ _ h1 h2 h3 h4) hcornerLo,
         le_trans hcornerHi (le_padHi_max4 p1 p2 p3 p4 _ _ _ _ h1 h2 h3 h4)⟩

/-! ### Division — models `iv_div` -/

/-- Corner lemma for `iv_div`: when the denominator interval excludes zero
(the engine's `b.lo <= 0 && b.hi >= 0` guard, as `0 < yl ∨ yu < 0`), the
exact quotient `x / y` lies between the min and max of the four exact corner
quotients. -/
theorem div_mem_corners (xl xu yl yu x y : ℝ)
    (hx1 : xl ≤ x) (hx2 : x ≤ xu) (hy1 : yl ≤ y) (hy2 : y ≤ yu)
    (hden : 0 < yl ∨ yu < 0) :
    min (min (xl / yl) (xl / yu)) (min (xu / yl) (xu / yu)) ≤ x / y ∧
    x / y ≤ max (max (xl / yl) (xl / yu)) (max (xu / yl) (xu / yu)) := by
  -- In both sign cases, 1/· is antitone across [yl, yu], so 1/y ∈ [1/yu, 1/yl].
  have hinv : 1 / yu ≤ 1 / y ∧ 1 / y ≤ 1 / yl := by
    rcases hden with hyl | hyu
    · have hy0 : (0 : ℝ) < y := lt_of_lt_of_le hyl hy1
      exact ⟨one_div_le_one_div_of_le hy0 hy2, one_div_le_one_div_of_le hyl hy1⟩
    · have hy0 : y < 0 := lt_of_le_of_lt hy2 hyu
      exact ⟨one_div_le_one_div_of_neg_of_le hyu hy2,
             one_div_le_one_div_of_neg_of_le hy0 hy1⟩
  obtain ⟨hcornerLo, hcornerHi⟩ :=
    mul_mem_corners xl xu (1 / yu) (1 / yl) x (1 / y) hx1 hx2 hinv.1 hinv.2
  constructor
  · have hLo : min (min (xl / yu) (xl / yl)) (min (xu / yu) (xu / yl)) ≤ x / y := by
      have h := hcornerLo
      simp only [mul_one_div] at h
      exact h
    calc min (min (xl / yl) (xl / yu)) (min (xu / yl) (xu / yu))
        = min (min (xl / yu) (xl / yl)) (min (xu / yu) (xu / yl)) := by
          rw [min_comm (xl / yl) (xl / yu), min_comm (xu / yl) (xu / yu)]
      _ ≤ x / y := hLo
  · have hHi : x / y ≤ max (max (xl / yu) (xl / yl)) (max (xu / yu) (xu / yl)) := by
      have h := hcornerHi
      simp only [mul_one_div] at h
      exact h
    calc x / y
        ≤ max (max (xl / yu) (xl / yl)) (max (xu / yu) (xu / yl)) := hHi
      _ = max (max (xl / yl) (xl / yu)) (max (xu / yl) (xu / yu)) := by
          rw [max_comm (xl / yu) (xl / yl), max_comm (xu / yu) (xu / yl)]

/-- `iv_div`: with the zero-free-denominator guard, the four rounded corner
quotients `q̃1 ≈ xl/yl`, `q̃2 ≈ xl/yu`, `q̃3 ≈ xu/yl`, `q̃4 ≈ xu/yu`,
min/max'd exactly and padded by `iv_out`, enclose the exact quotient `x / y`. -/
theorem iv_div_encloses (xl xu yl yu x y q1 q2 q3 q4 : ℝ)
    (hx1 : xl ≤ x) (hx2 : x ≤ xu) (hy1 : yl ≤ y) (hy2 : y ≤ yu)
    (hden : 0 < yl ∨ yu < 0)
    (h1 : Approx δ0 σ0 q1 (xl / yl)) (h2 : Approx δ0 σ0 q2 (xl / yu))
    (h3 : Approx δ0 σ0 q3 (xu / yl)) (h4 : Approx δ0 σ0 q4 (xu / yu)) :
    padLo (min (min q1 q2) (min q3 q4)) ≤ x / y ∧
    x / y ≤ padHi (max (max q1 q2) (max q3 q4)) := by
  obtain ⟨hcornerLo, hcornerHi⟩ :=
    div_mem_corners xl xu yl yu x y hx1 hx2 hy1 hy2 hden
  exact ⟨le_trans (padLo_min4_le q1 q2 q3 q4 _ _ _ _ h1 h2 h3 h4) hcornerLo,
         le_trans hcornerHi (le_padHi_max4 q1 q2 q3 q4 _ _ _ _ h1 h2 h3 h4)⟩

end JackalIv
