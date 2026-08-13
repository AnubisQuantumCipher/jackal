/-
JACKAL certified interval lane — the mechanized MODEL.

These definitions mirror, constant for constant, the interval engine in
`jackal_calc.anb` (sections "JACKAL CERTIFIED INTERVAL ENGINE" and "JACKAL
CERTIFIED INTEGRATION", git 8a71540):

* `pad`, `padLo`, `padHi` — the outward pad applied by `iv_out`:
  1e-15 relative + 1e-300 absolute.
* `Approx δ σ fl r` — the floating-point model: a computed value `fl`
  approximates the exact real `r` with relative error ≤ δ and absolute error
  ≤ σ.  The engine's stated trust assumptions instantiate this with:
    - `δ0 = 2⁻⁵³`  (IEEE-754 correctly rounded basic ops, ≤ 0.5 ulp),
    - `δlib = 2⁻⁵¹` (math-library calls within 2 ulp, incl. argument
      reduction — an ASSUMPTION of the platform libm, not a theorem),
    - `σ0 = 2⁻¹⁰⁷⁵` (subnormal absolute rounding floor).
* `IBox`/`Encloses` — an interval and what it means for it to enclose a set.

Claims discipline: every theorem in this development is about THIS model.
The gap between the model and the shipped binary (the Anubis compiler, the
platform libm, the hardware) is a disclosed residual — see `Ledger.lean`.
-/
import Mathlib

namespace JackalIv

/-- Relative outward pad applied by `iv_out` (engine constant `1e-15`). -/
noncomputable def ε : ℝ := 1 / 10 ^ 15

/-- Absolute outward pad applied by `iv_out` (engine constant `1e-300`). -/
noncomputable def τ : ℝ := 1 / 10 ^ 300

/-- Basic-op relative rounding bound: correctly rounded, ≤ 0.5 ulp. -/
noncomputable def δ0 : ℝ := 1 / 2 ^ 53

/-- Math-library relative error bound: the stated ≤ 2 ulp model. -/
noncomputable def δlib : ℝ := 1 / 2 ^ 51

/-- Absolute (subnormal-regime) rounding bound. -/
noncomputable def σ0 : ℝ := 1 / 2 ^ 1075

/-- `fl` approximates `r` with relative error ≤ `δ` and absolute error ≤ `σ`. -/
def Approx (δ σ fl r : ℝ) : Prop := |fl - r| ≤ δ * |r| + σ

/-- The outward pad magnitude at value `v`. -/
noncomputable def pad (v : ℝ) : ℝ := ε * |v| + τ

/-- Lower endpoint after outward padding (`iv_out` lower side). -/
noncomputable def padLo (v : ℝ) : ℝ := v - pad v

/-- Upper endpoint after outward padding (`iv_out` upper side). -/
noncomputable def padHi (v : ℝ) : ℝ := v + pad v

/-- A closed real interval, as printed by the engine. -/
structure IBox where
  lo : ℝ
  hi : ℝ

/-- `I` encloses the set `S`. -/
def Encloses (I : IBox) (S : Set ℝ) : Prop := ∀ x ∈ S, I.lo ≤ x ∧ x ≤ I.hi

lemma ε_pos : (0 : ℝ) < ε := by unfold ε; positivity
lemma ε_lt_one : ε < 1 := by unfold ε; norm_num
lemma τ_pos : (0 : ℝ) < τ := by unfold τ; positivity
lemma δ0_pos : (0 : ℝ) < δ0 := by unfold δ0; positivity
lemma δlib_pos : (0 : ℝ) < δlib := by unfold δlib; positivity
lemma σ0_pos : (0 : ℝ) < σ0 := by unfold σ0; positivity

/-- The basic-op bound satisfies the pad-admissibility condition δ(1+ε) ≤ ε. -/
lemma δ0_admissible : δ0 * (1 + ε) ≤ ε := by
  unfold δ0 ε; norm_num

/-- The libm bound satisfies the pad-admissibility condition δ(1+ε) ≤ ε. -/
lemma δlib_admissible : δlib * (1 + ε) ≤ ε := by
  unfold δlib ε; norm_num

set_option exponentiation.threshold 1200 in
/-- The subnormal bound satisfies the pad-admissibility condition σ(1+ε) ≤ τ. -/
lemma σ0_admissible : σ0 * (1 + ε) ≤ τ := by
  unfold σ0 τ ε
  have h1 : (1 : ℝ) + 1 / 10 ^ 15 ≤ 2 := by norm_num
  have h2 : (1 : ℝ) / 2 ^ 1075 * 2 ≤ 1 / 10 ^ 300 := by
    rw [div_mul_eq_mul_div, mul_comm]
    rw [div_le_div_iff₀ (by positivity) (by positivity)]
    norm_num
  have h3 : (0 : ℝ) < 1 / 2 ^ 1075 := by positivity
  nlinarith [h1, h2, h3]

end JackalIv
