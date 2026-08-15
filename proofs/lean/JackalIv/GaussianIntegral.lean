/-
JackalIv/GaussianIntegral.lean — theorem-backed finite Gaussian integral
enclosure from Mathlib's full Gaussian integral, exact rational pi bounds, and
proved exponential tail bounds.  No platform libm call appears in the bound.
-/
import JackalIv.Gaussian
import Mathlib.Analysis.Real.Pi.Bounds
import Mathlib.Analysis.SpecialFunctions.Gaussian.GaussianIntegral

namespace JackalIv.Gaussian

open Set MeasureTheory Filter
open scoped Topology

/-- Compact exact rational bounds for `sqrt pi`. -/
def sqrtPiLoQ : ℚ := 177245385090551 / 100000000000000
def sqrtPiHiQ : ℚ := 22155673136319 / 12500000000000

lemma sqrtPi_enclosed :
    ((sqrtPiLoQ : ℚ) : ℝ) ≤ Real.sqrt Real.pi ∧
      Real.sqrt Real.pi ≤ ((sqrtPiHiQ : ℚ) : ℝ) := by
  constructor
  · rw [Real.le_sqrt (by norm_num [sqrtPiLoQ]) Real.pi_nonneg]
    dsimp [sqrtPiLoQ]
    norm_num
    nlinarith [Real.pi_gt_d20]
  · rw [Real.sqrt_le_iff]
    constructor
    · norm_num [sqrtPiHiQ]
    · dsimp [sqrtPiHiQ]
      norm_num
      nlinarith [Real.pi_lt_d20]

/-- Exact antiderivative evaluation of the first Gaussian moment on a tail. -/
theorem integral_Ioi_mul_gaussian (T : ℝ) :
    ∫ x in Ioi T, x * Real.exp (-x ^ 2) = Real.exp (-T ^ 2) / 2 := by
  let F : ℝ → ℝ := fun x => -(2 : ℝ)⁻¹ * Real.exp (-x ^ 2)
  have hderiv : ∀ x : ℝ, HasDerivAt F (x * Real.exp (-x ^ 2)) x := by
    intro x
    dsimp [F]
    convert (((hasDerivAt_id x).pow 2).neg.exp).const_mul (-(2 : ℝ)⁻¹) using 1
    all_goals (try simp [id])
    all_goals first | rfl | ring
  have hint : IntegrableOn (fun x : ℝ => x * Real.exp (-x ^ 2)) (Ioi T) := by
    simpa using (integrable_mul_exp_neg_mul_sq (b := 1) (by norm_num)).integrableOn
  have hlim : Tendsto F atTop (𝓝 0) := by
    dsimp [F]
    have hexp : Tendsto (fun y : ℝ => Real.exp (-y ^ 2)) atTop (𝓝 0) := by
      simpa using Real.tendsto_exp_atBot.comp
        ((tendsto_pow_atTop two_ne_zero).const_mul_atTop_of_neg
          (show (-1 : ℝ) < 0 by norm_num))
    simpa using hexp.const_mul (-(2 : ℝ)⁻¹)
  have h := integral_Ioi_of_hasDerivAt_of_tendsto'
    (fun x _ => hderiv x) hint hlim
  dsimp [F] at h
  rw [h]
  ring

/-- Classical Gaussian tail inequality, with its right-hand side later
replaced by the exact-rational exponential enclosure. -/
theorem integral_Ioi_gaussian_le (T : ℝ) (hT : 0 < T) :
    (∫ x in Ioi T, Real.exp (-x ^ 2)) ≤ Real.exp (-T ^ 2) / (2 * T) := by
  have hf : IntegrableOn (fun x : ℝ => Real.exp (-x ^ 2)) (Ioi T) := by
    simpa using (integrable_exp_neg_mul_sq (b := 1) (by norm_num)).integrableOn
  have hg : IntegrableOn (fun x : ℝ => (x / T) * Real.exp (-x ^ 2)) (Ioi T) := by
    have hwhole := (integrable_mul_exp_neg_mul_sq (b := 1) (by norm_num)).const_mul (T⁻¹)
    exact hwhole.integrableOn.congr_fun (fun x _ => by ring_nf) measurableSet_Ioi
  calc
    (∫ x in Ioi T, Real.exp (-x ^ 2))
        ≤ ∫ x in Ioi T, (x / T) * Real.exp (-x ^ 2) := by
      refine setIntegral_mono_on hf hg measurableSet_Ioi ?_
      intro x hx
      have hratio : 1 ≤ x / T := by
        rw [le_div_iff₀ hT]
        simpa using hx.le
      nlinarith [Real.exp_pos (-x ^ 2)]
    _ = T⁻¹ * ∫ x in Ioi T, x * Real.exp (-x ^ 2) := by
      rw [← integral_const_mul]
      apply setIntegral_congr_fun measurableSet_Ioi
      intro x _
      ring
    _ = Real.exp (-T ^ 2) / (2 * T) := by
      rw [integral_Ioi_mul_gaussian]
      field_simp

/-- The finite symmetric core differs from the full Gaussian integral by at
most the two proved tails. -/
theorem gaussian_core_enclosure (T : ℝ) (hT : 0 < T) :
    Real.sqrt Real.pi - Real.exp (-T ^ 2) / T
        ≤ (∫ x in (-T)..T, Real.exp (-x ^ 2)) ∧
      (∫ x in (-T)..T, Real.exp (-x ^ 2)) ≤ Real.sqrt Real.pi := by
  let f : ℝ → ℝ := fun x => Real.exp (-x ^ 2)
  have hf : Integrable f := by
    simpa [f] using integrable_exp_neg_mul_sq (b := 1) (by norm_num)
  have hnonneg : ∀ x, 0 ≤ f x := fun x => (Real.exp_pos _).le
  have hfull : (∫ x : ℝ, f x) = Real.sqrt Real.pi := by
    simpa [f] using integral_gaussian 1
  have hleft : (∫ x in Iic (-T), f x) = ∫ x in Ioi T, f x := by
    rw [← integral_comp_neg_Ioi T f]
    apply setIntegral_congr_fun measurableSet_Ioi
    intro x _
    simp [f]
  have hcomp : (∫ x in (Ioc (-T) T)ᶜ, f x) =
      (∫ x in Iic (-T), f x) + ∫ x in Ioi T, f x := by
    rw [compl_Ioc]
    exact setIntegral_union (Iic_disjoint_Ioi (by linarith)) measurableSet_Ioi
      hf.integrableOn hf.integrableOn
  have hsplit := integral_add_compl (s := Ioc (-T) T) measurableSet_Ioc hf
  have htail := integral_Ioi_gaussian_le T hT
  have hcentral : (∫ x in (-T)..T, f x) = ∫ x in Ioc (-T) T, f x := by
    exact intervalIntegral.integral_of_le (by linarith)
  constructor
  · rw [hcentral]
    rw [hcomp, hleft] at hsplit
    rw [hfull] at hsplit
    change (∫ x in Ioi T, f x) ≤ Real.exp (-T ^ 2) / (2 * T) at htail
    have htwo : 2 * (Real.exp (-T ^ 2) / (2 * T)) = Real.exp (-T ^ 2) / T := by
      field_simp
    nlinarith [htail]
  · rw [hcentral]
    calc
      (∫ x in Ioc (-T) T, f x) ≤ ∫ x : ℝ, f x :=
        setIntegral_le_integral hf (ae_of_all _ hnonneg)
      _ = Real.sqrt Real.pi := hfull

/-! ## Fixed checker core and arbitrary containing intervals -/

def checkerCoreQ : ℚ := 6
def checkerDegree : Nat := 96
def checkerCoreLoQ : ℚ :=
  sqrtPiLoQ - expNegHiQ (checkerCoreQ ^ 2) checkerDegree / checkerCoreQ
def checkerCoreHiQ : ℚ := sqrtPiHiQ

theorem checker_core_enclosed :
    ((checkerCoreLoQ : ℚ) : ℝ)
        ≤ (∫ x in (-6 : ℝ)..6, Real.exp (-x ^ 2)) ∧
      (∫ x in (-6 : ℝ)..6, Real.exp (-x ^ 2))
        ≤ ((checkerCoreHiQ : ℚ) : ℝ) := by
  have hcore := gaussian_core_enclosure 6 (by norm_num)
  norm_num at hcore
  have hcoreLo : Real.sqrt Real.pi - Real.exp (-36) / 6 ≤
      (∫ x in (-6 : ℝ)..6, Real.exp (-x ^ 2)) := by
    linarith [hcore.1]
  have hexp := (expNegQ_encloses (36 : ℚ) checkerDegree
    (by norm_num) (by norm_num [checkerDegree]) (by norm_num [checkerDegree])).2
  obtain ⟨hsqrtLo, hsqrtHi⟩ := sqrtPi_enclosed
  constructor
  · change (((sqrtPiLoQ - expNegHiQ (checkerCoreQ ^ 2) checkerDegree /
      checkerCoreQ : ℚ) : ℚ) : ℝ) ≤ _
    simp only [Rat.cast_sub, Rat.cast_div, Rat.cast_ofNat, checkerCoreQ]
    have htail : Real.exp (-(36 : ℝ)) / 6 ≤
        ((expNegHiQ (36 : ℚ) checkerDegree : ℚ) : ℝ) / 6 := by
      exact div_le_div_of_nonneg_right (by simpa using hexp) (by norm_num)
    exact (sub_le_sub hsqrtLo htail).trans hcoreLo
  · exact hcore.2.trans hsqrtHi

theorem containing_interval_enclosed (L U : ℝ)
    (hL : L ≤ -6) (hU : 6 ≤ U) :
    ((checkerCoreLoQ : ℚ) : ℝ)
        ≤ (∫ x in L..U, Real.exp (-x ^ 2)) ∧
      (∫ x in L..U, Real.exp (-x ^ 2))
        ≤ ((checkerCoreHiQ : ℚ) : ℝ) := by
  have hint : IntervalIntegrable (fun x : ℝ => Real.exp (-x ^ 2)) volume L U :=
    Continuous.intervalIntegrable (by fun_prop) L U
  have hnonneg : 0 ≤ᵐ[volume.restrict (Ioc L U)]
      (fun x : ℝ => Real.exp (-x ^ 2)) := ae_of_all _ fun x => (Real.exp_pos _).le
  have hmono : (∫ x in (-6 : ℝ)..6, Real.exp (-x ^ 2)) ≤
      ∫ x in L..U, Real.exp (-x ^ 2) :=
    intervalIntegral.integral_mono_interval hL (by norm_num) hU hnonneg hint
  have hwhole : Integrable (fun x : ℝ => Real.exp (-x ^ 2)) := by
    simpa using integrable_exp_neg_mul_sq (b := 1) (by norm_num)
  constructor
  · exact checker_core_enclosed.1.trans hmono
  · change (∫ x in L..U, Real.exp (-x ^ 2)) ≤ ((sqrtPiHiQ : ℚ) : ℝ)
    rw [intervalIntegral.integral_of_le (hL.trans (by linarith))]
    calc
      (∫ x in Ioc L U, Real.exp (-x ^ 2))
          ≤ ∫ x : ℝ, Real.exp (-x ^ 2) :=
        setIntegral_le_integral hwhole (ae_of_all _ fun x => (Real.exp_pos _).le)
      _ = Real.sqrt Real.pi := by simpa using integral_gaussian 1
      _ ≤ ((sqrtPiHiQ : ℚ) : ℝ) := sqrtPi_enclosed.2

/-- Change variables through the checker-validated positive rational scale.
This is the semantic theorem consumed by the certificate soundness proof. -/
theorem scaled_gaussian_enclosed (s μ a b : ℝ) (hs : 0 < s)
    (hL : s * (a - μ) ≤ -6) (hU : 6 ≤ s * (b - μ)) :
    ((checkerCoreLoQ : ℚ) : ℝ) / s
        ≤ (∫ x in a..b, Real.exp (-(s ^ 2) * (x - μ) ^ 2)) ∧
      (∫ x in a..b, Real.exp (-(s ^ 2) * (x - μ) ^ 2))
        ≤ ((checkerCoreHiQ : ℚ) : ℝ) / s := by
  let g : ℝ → ℝ := fun t => Real.exp (-t ^ 2)
  have hchange :
      (∫ x in a..b, Real.exp (-(s ^ 2) * (x - μ) ^ 2)) =
        s⁻¹ * ∫ t in s * a - s * μ..s * b - s * μ, g t := by
    calc
      (∫ x in a..b, Real.exp (-(s ^ 2) * (x - μ) ^ 2))
          = ∫ x in a..b, g (s * x + (-s * μ)) := by
            apply intervalIntegral.integral_congr
            intro x _
            dsimp [g]
            congr 1
            ring
      _ = s⁻¹ * ∫ t in s * a + (-s * μ)..s * b + (-s * μ), g t := by
            simpa [smul_eq_mul] using
              (intervalIntegral.integral_comp_mul_add (f := g) (a := a) (b := b)
                (c := s) (d := -s * μ) hs.ne')
      _ = s⁻¹ * ∫ t in s * a - s * μ..s * b - s * μ, g t := by ring_nf
  have hcontained := containing_interval_enclosed (s * a - s * μ) (s * b - s * μ)
    (by linarith [hL]) (by linarith [hU])
  have hsInv : 0 ≤ s⁻¹ := (inv_pos.2 hs).le
  constructor
  · rw [hchange]
    have := mul_le_mul_of_nonneg_left hcontained.1 hsInv
    simpa [g, div_eq_mul_inv, mul_comm] using this
  · rw [hchange]
    have := mul_le_mul_of_nonneg_left hcontained.2 hsInv
    simpa [g, div_eq_mul_inv, mul_comm] using this

end JackalIv.Gaussian
