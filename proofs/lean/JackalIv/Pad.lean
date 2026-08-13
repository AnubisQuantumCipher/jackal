/-
The pad-beats-rounding core: if a computed value approximates an exact real
within an admissible error model, the outward-padded value brackets the exact
real. Every containment lemma in this development reduces to these two facts.

Engine correspondence: `iv_out` in jackal_calc.anb pads each computed
endpoint by `pad v = ε|v| + τ` outward; these lemmas are exactly the claim
that this pad strictly dominates the rounding error of the operation that
produced the endpoint, for every admissible (δ, σ).
-/
import JackalIv.Model

namespace JackalIv

/-- Reverse triangle consequence: `|fl| ≥ |r| − (δ|r| + σ)`. -/
lemma abs_fl_ge (δ σ fl r : ℝ) (h : Approx δ σ fl r) :
    |r| - (δ * |r| + σ) ≤ |fl| := by
  have h1 : |r| - |fl| ≤ |fl - r| := by
    have := abs_sub_abs_le_abs_sub r fl
    simpa [abs_sub_comm] using this
  have h2 := h
  unfold Approx at h2
  linarith

/-- Padding up beats admissible rounding: the exact value sits below `padHi fl`. -/
theorem le_padHi (δ σ fl r : ℝ)
    (_hδ : 0 ≤ δ) (_hσ : 0 ≤ σ)
    (hδa : δ * (1 + ε) ≤ ε) (hσa : σ * (1 + ε) ≤ τ)
    (h : Approx δ σ fl r) : r ≤ padHi fl := by
  have habs : |fl - r| ≤ δ * |r| + σ := h
  have hfl_lower : r - (δ * |r| + σ) ≤ fl := by
    have := abs_le.mp habs
    linarith [this.1]
  have hfl_abs : |r| - (δ * |r| + σ) ≤ |fl| := abs_fl_ge δ σ fl r h
  have hεabs : ε * (|r| - (δ * |r| + σ)) ≤ ε * |fl| :=
    mul_le_mul_of_nonneg_left hfl_abs (le_of_lt ε_pos)
  have hr_abs : (0:ℝ) ≤ |r| := abs_nonneg r
  have hterm1 : 0 ≤ (ε - δ * (1 + ε)) * |r| := by
    apply mul_nonneg _ hr_abs
    linarith
  have hterm2 : 0 ≤ τ - σ * (1 + ε) := by linarith
  unfold padHi pad
  nlinarith [hεabs, hfl_lower, hterm1, hterm2]

/-- Padding down beats admissible rounding: the exact value sits above `padLo fl`. -/
theorem padLo_le (δ σ fl r : ℝ)
    (_hδ : 0 ≤ δ) (_hσ : 0 ≤ σ)
    (hδa : δ * (1 + ε) ≤ ε) (hσa : σ * (1 + ε) ≤ τ)
    (h : Approx δ σ fl r) : padLo fl ≤ r := by
  have habs : |fl - r| ≤ δ * |r| + σ := h
  have hfl_upper : fl ≤ r + (δ * |r| + σ) := by
    have := abs_le.mp habs
    linarith [this.2]
  have hfl_abs : |r| - (δ * |r| + σ) ≤ |fl| := abs_fl_ge δ σ fl r h
  have hεabs : ε * (|r| - (δ * |r| + σ)) ≤ ε * |fl| :=
    mul_le_mul_of_nonneg_left hfl_abs (le_of_lt ε_pos)
  have hr_abs : (0:ℝ) ≤ |r| := abs_nonneg r
  have hterm1 : 0 ≤ (ε - δ * (1 + ε)) * |r| := by
    apply mul_nonneg _ hr_abs
    linarith
  have hterm2 : 0 ≤ τ - σ * (1 + ε) := by linarith
  unfold padLo pad
  nlinarith [hεabs, hfl_upper, hterm1, hterm2]

/-- `padLo` is monotone (the pad slope never exceeds 1 since ε < 1). -/
lemma padLo_mono : Monotone padLo := by
  intro a b hab
  have h3 : ε * (|b| - |a|) ≤ ε * (b - a) := by
    apply mul_le_mul_of_nonneg_left _ ε_pos.le
    calc |b| - |a| ≤ |b - a| := abs_sub_abs_le_abs_sub b a
      _ = b - a := abs_of_nonneg (by linarith)
  have h4 : ε * (b - a) ≤ 1 * (b - a) :=
    mul_le_mul_of_nonneg_right ε_lt_one.le (by linarith)
  unfold padLo pad
  nlinarith [h3, h4]

/-- `padHi` is monotone. -/
lemma padHi_mono : Monotone padHi := by
  intro a b hab
  have h3 : ε * (|a| - |b|) ≤ ε * (b - a) := by
    apply mul_le_mul_of_nonneg_left _ ε_pos.le
    calc |a| - |b| ≤ |a - b| := abs_sub_abs_le_abs_sub a b
      _ = |b - a| := abs_sub_comm a b
      _ = b - a := abs_of_nonneg (by linarith)
  have h4 : ε * (b - a) ≤ 1 * (b - a) :=
    mul_le_mul_of_nonneg_right ε_lt_one.le (by linarith)
  unfold padHi pad
  nlinarith [h3, h4]

/-- Padding an exactly-computed endpoint still brackets it from below. -/
theorem padLo_le_of_exact (v : ℝ) : padLo v ≤ v := by
  unfold padLo pad
  nlinarith [abs_nonneg v, ε_pos.le, τ_pos.le]

/-- Padding an exactly-computed endpoint still brackets it from above. -/
theorem le_padHi_of_exact (v : ℝ) : v ≤ padHi v := by
  unfold padHi pad
  nlinarith [abs_nonneg v, ε_pos.le, τ_pos.le]

/-- The basic-op instantiation (δ0, σ0) brackets. -/
theorem basic_brackets (fl r : ℝ) (h : Approx δ0 σ0 fl r) :
    padLo fl ≤ r ∧ r ≤ padHi fl :=
  ⟨padLo_le δ0 σ0 fl r δ0_pos.le σ0_pos.le δ0_admissible σ0_admissible h,
   le_padHi δ0 σ0 fl r δ0_pos.le σ0_pos.le δ0_admissible σ0_admissible h⟩

/-- The libm instantiation (δlib, σ0) brackets. -/
theorem libm_brackets (fl r : ℝ) (h : Approx δlib σ0 fl r) :
    padLo fl ≤ r ∧ r ≤ padHi fl :=
  ⟨padLo_le δlib σ0 fl r δlib_pos.le σ0_pos.le δlib_admissible σ0_admissible h,
   le_padHi δlib σ0 fl r δlib_pos.le σ0_pos.le δlib_admissible σ0_admissible h⟩

end JackalIv
