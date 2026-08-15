/-
JackalIv/Gaussian.lean — zero-libm exact-rational foundations for the
proof-carrying Gaussian integration fragment.

No executable acceptance condition is defined here.  This module supplies the
mathematical facts later consumed by the independent certificate checker.
-/
import JackalIv.Taylor
import Mathlib.Analysis.Complex.Exponential

namespace JackalIv.Gaussian

open scoped BigOperators
open Finset

/-- The first `n` terms of the exponential series, over any field. -/
def expPartial {K : Type*} [Field K] [CharZero K] (z : K) (n : Nat) : K :=
  ∑ k ∈ range n, z ^ k / (k.factorial : K)

/-- The pure-rational remainder used by the admitted checker fragment. -/
def expRemainder {K : Type*} [Field K] [CharZero K] (z : K) (n : Nat) : K :=
  2 * z ^ n / (n.factorial : K)

lemma real_exp_remainder_bound (z : ℝ) (n : Nat)
    (hz : 0 ≤ z) (hn : z / (n + 1 : ℝ) ≤ 1 / 2) :
    |Real.exp z - expPartial z n| ≤ expRemainder z n := by
  have h := Complex.exp_bound' (x := (z : ℂ)) (n := n) (by
    simpa [abs_of_nonneg hz] using hn)
  have h' : ‖Real.exp z - ∑ k ∈ range n, z ^ k / k.factorial‖ ≤
      ‖z‖ ^ n / n.factorial * 2 := by
    exact_mod_cast h
  simpa [expPartial, expRemainder, Real.norm_eq_abs, abs_of_nonneg hz,
    div_eq_mul_inv, mul_comm, mul_left_comm, mul_assoc] using h'

lemma real_exp_between (z : ℝ) (n : Nat)
    (hz : 0 ≤ z) (hn : z / (n + 1 : ℝ) ≤ 1 / 2) :
    expPartial z n ≤ Real.exp z ∧
      Real.exp z ≤ expPartial z n + expRemainder z n := by
  constructor
  · exact Real.sum_le_exp_of_nonneg hz n
  · have h := real_exp_remainder_bound z n hz hn
    rw [abs_le] at h
    linarith

lemma one_le_expPartial (z : ℝ) (n : Nat) (hz : 0 ≤ z) (hn : 0 < n) :
    1 ≤ expPartial z n := by
  unfold expPartial
  have hzero : 0 ∈ range n := by simpa using hn
  calc
    1 = z ^ 0 / ((0 : Nat).factorial : ℝ) := by norm_num
    _ ≤ ∑ k ∈ range n, z ^ k / (k.factorial : ℝ) := by
      exact single_le_sum (f := fun k => z ^ k / (k.factorial : ℝ))
        (fun k _ => by positivity) hzero

/-- Exact-rational lower endpoint for `exp(-z)`. -/
def expNegLoQ (z : ℚ) (n : Nat) : ℚ :=
  1 / (expPartial z n + expRemainder z n)

/-- Exact-rational upper endpoint for `exp(-z)`. -/
def expNegHiQ (z : ℚ) (n : Nat) : ℚ :=
  1 / expPartial z n

lemma cast_expPartial (z : ℚ) (n : Nat) :
    ((expPartial z n : ℚ) : ℝ) = expPartial (z : ℝ) n := by
  simp [expPartial]

lemma cast_expRemainder (z : ℚ) (n : Nat) :
    ((expRemainder z n : ℚ) : ℝ) = expRemainder (z : ℝ) n := by
  simp [expRemainder]

/-- The exact-rational endpoints computed by the checker enclose `exp(-z)`.
No platform transcendental evaluation appears in either endpoint. -/
theorem expNegQ_encloses (z : ℚ) (n : Nat)
    (hz : 0 ≤ z) (hnpos : 0 < n)
    (hdegree : (z : ℝ) / (n + 1 : ℝ) ≤ 1 / 2) :
    ((expNegLoQ z n : ℚ) : ℝ) ≤ Real.exp (-(z : ℝ)) ∧
      Real.exp (-(z : ℝ)) ≤ ((expNegHiQ z n : ℚ) : ℝ) := by
  have hzR : 0 ≤ (z : ℝ) := by exact_mod_cast hz
  obtain ⟨hlo, hhi⟩ := real_exp_between (z : ℝ) n hzR hdegree
  have hs : 0 < expPartial (z : ℝ) n :=
    lt_of_lt_of_le zero_lt_one (one_le_expPartial (z : ℝ) n hzR hnpos)
  have her : 0 < Real.exp (z : ℝ) := Real.exp_pos _
  have hsr : 0 < expPartial (z : ℝ) n + expRemainder (z : ℝ) n :=
    lt_of_lt_of_le her hhi
  constructor
  · rw [Real.exp_neg]
    change ((1 / (expPartial z n + expRemainder z n) : ℚ) : ℝ) ≤
      (Real.exp (z : ℝ))⁻¹
    simp only [Rat.cast_div, Rat.cast_one, Rat.cast_add, cast_expPartial,
      cast_expRemainder]
    simpa [one_div] using one_div_le_one_div_of_le her hhi
  · rw [Real.exp_neg]
    change (Real.exp (z : ℝ))⁻¹ ≤ ((1 / expPartial z n : ℚ) : ℝ)
    simp only [Rat.cast_div, Rat.cast_one, cast_expPartial]
    simpa [one_div] using one_div_le_one_div_of_le hs hlo

end JackalIv.Gaussian
