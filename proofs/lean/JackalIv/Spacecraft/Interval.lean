/- Executable dyadic interval arithmetic and its containment boundary. -/
import Mathlib.Data.Rat.Floor
import Mathlib.Data.Int.Sqrt
import Mathlib.Analysis.Real.Sqrt
import JackalIv.Arith
import JackalIv.Spacecraft.Types

namespace JackalIv.Spacecraft

def scale (bits : Nat) : Int := (2 ^ bits : Nat)

theorem scale_pos (bits : Nat) : (0 : Int) < scale bits := by
  simp [scale]

theorem scale_real_pos (bits : Nat) : (0 : ℝ) < (scale bits : ℝ) := by
  exact_mod_cast scale_pos bits

noncomputable def lower (bits : Nat) (a : DInterval) : ℝ :=
  (a.lo : ℝ) / (scale bits : ℝ)

noncomputable def upper (bits : Nat) (a : DInterval) : ℝ :=
  (a.hi : ℝ) / (scale bits : ℝ)

def Mem (bits : Nat) (x : ℝ) (a : DInterval) : Prop :=
  lower bits a ≤ x ∧ x ≤ upper bits a

def Valid (a : DInterval) : Prop := a.lo ≤ a.hi

def add (a b : DInterval) : DInterval := ⟨a.lo + b.lo, a.hi + b.hi⟩
def neg (a : DInterval) : DInterval := ⟨-b.hi, -b.lo⟩
  where b := a
def sub (a b : DInterval) : DInterval := add a (neg b)

private def min4 (a b c d : Int) : Int := min (min a b) (min c d)
private def max4 (a b c d : Int) : Int := max (max a b) (max c d)

def floorDiv (n d : Int) : Int := ⌊(n : ℚ) / (d : ℚ)⌋
def ceilDiv (n d : Int) : Int := ⌈(n : ℚ) / (d : ℚ)⌉

def pointRat (bits : Nat) (q : ℚ) : DInterval :=
  ⟨⌊q * (scale bits : ℚ)⌋, ⌈q * (scale bits : ℚ)⌉⟩

def mul (bits : Nat) (a b : DInterval) : DInterval :=
  let p0 := a.lo * b.lo
  let p1 := a.lo * b.hi
  let p2 := a.hi * b.lo
  let p3 := a.hi * b.hi
  ⟨floorDiv (min4 p0 p1 p2 p3) (scale bits),
   ceilDiv (max4 p0 p1 p2 p3) (scale bits)⟩

def divUnchecked (bits : Nat) (a b : DInterval) : DInterval :=
  let s := scale bits
  let q0lo := floorDiv (a.lo * s) b.lo
  let q1lo := floorDiv (a.lo * s) b.hi
  let q2lo := floorDiv (a.hi * s) b.lo
  let q3lo := floorDiv (a.hi * s) b.hi
  let q0hi := ceilDiv (a.lo * s) b.lo
  let q1hi := ceilDiv (a.lo * s) b.hi
  let q2hi := ceilDiv (a.hi * s) b.lo
  let q3hi := ceilDiv (a.hi * s) b.hi
  ⟨min4 q0lo q1lo q2lo q3lo, max4 q0hi q1hi q2hi q3hi⟩

def div (bits : Nat) (a b : DInterval) : Except String DInterval :=
  if b.lo ≤ 0 ∧ 0 ≤ b.hi then .error "division-by-zero-interval"
  else .ok (divUnchecked bits a b)

def square (bits : Nat) (a : DInterval) : DInterval :=
  if a.lo ≤ 0 ∧ 0 ≤ a.hi then
    ⟨0, ceilDiv (max (a.lo * a.lo) (a.hi * a.hi)) (scale bits)⟩
  else
    ⟨floorDiv (min (a.lo * a.lo) (a.hi * a.hi)) (scale bits),
     ceilDiv (max (a.lo * a.lo) (a.hi * a.hi)) (scale bits)⟩

def ceilSqrtInt (n : Int) : Int :=
  let root := Int.sqrt n
  if root * root < n then root + 1 else root

def sqrtUnchecked (bits : Nat) (a : DInterval) : DInterval :=
  ⟨Int.sqrt (a.lo * scale bits), ceilSqrtInt (a.hi * scale bits)⟩

def sqrt (bits : Nat) (a : DInterval) : Except String DInterval :=
  if a.lo < 0 then .error "sqrt-negative-interval"
  else .ok (sqrtUnchecked bits a)

def hull (a b : DInterval) : DInterval := ⟨min a.lo b.lo, max a.hi b.hi⟩

def intersection (a b : DInterval) : Option DInterval :=
  let low := max a.lo b.lo
  let high := min a.hi b.hi
  if low ≤ high then some ⟨low, high⟩ else none

theorem add_sound {bits : Nat} {a b : DInterval} {x y : ℝ}
    (hx : Mem bits x a) (hy : Mem bits y b) : Mem bits (x + y) (add a b) := by
  rcases hx with ⟨hx0, hx1⟩
  rcases hy with ⟨hy0, hy1⟩
  constructor <;> simp only [lower, upper, add] at *
  · rw [Int.cast_add, add_div]
    exact add_le_add hx0 hy0
  · rw [Int.cast_add, add_div]
    exact add_le_add hx1 hy1

theorem neg_sound {bits : Nat} {a : DInterval} {x : ℝ}
    (hx : Mem bits x a) : Mem bits (-x) (neg a) := by
  rcases hx with ⟨hx0, hx1⟩
  constructor <;> simp only [lower, upper, neg, Int.cast_neg, neg_div] at *
  · exact neg_le_neg hx1
  · exact neg_le_neg hx0

theorem sub_sound {bits : Nat} {a b : DInterval} {x y : ℝ}
    (hx : Mem bits x a) (hy : Mem bits y b) : Mem bits (x - y) (sub a b) := by
  simpa [sub, sub_eq_add_neg] using add_sound hx (neg_sound hy)

private theorem floor_scaled_le (bits : Nat) (n : Int) :
    ((floorDiv n (scale bits) : Int) : ℝ) / (scale bits : ℝ) ≤
      ((n : ℝ) / (scale bits : ℝ)) / (scale bits : ℝ) := by
  have hq : ((floorDiv n (scale bits) : Int) : ℚ) ≤
      (n : ℚ) / (scale bits : ℚ) := by
    exact Int.floor_le _
  have hr : ((floorDiv n (scale bits) : Int) : ℝ) ≤
      (n : ℝ) / (scale bits : ℝ) := by exact_mod_cast hq
  exact div_le_div_of_nonneg_right hr (scale_real_pos bits).le

private theorem le_ceil_scaled (bits : Nat) (n : Int) :
    ((n : ℝ) / (scale bits : ℝ)) / (scale bits : ℝ) ≤
      ((ceilDiv n (scale bits) : Int) : ℝ) / (scale bits : ℝ) := by
  have hq : (n : ℚ) / (scale bits : ℚ) ≤
      ((ceilDiv n (scale bits) : Int) : ℚ) := by
    exact Int.le_ceil _
  have hr : (n : ℝ) / (scale bits : ℝ) ≤
      ((ceilDiv n (scale bits) : Int) : ℝ) := by exact_mod_cast hq
  exact div_le_div_of_nonneg_right hr (scale_real_pos bits).le

theorem pointRat_sound (bits : Nat) (q : ℚ) :
    Mem bits ((q : ℚ) : ℝ) (pointRat bits q) := by
  constructor
  · have hq : ((⌊q * (scale bits : ℚ)⌋ : Int) : ℚ) ≤
        q * (scale bits : ℚ) := Int.floor_le _
    have hr : ((⌊q * (scale bits : ℚ)⌋ : Int) : ℝ) ≤
        ((q : ℚ) : ℝ) * (scale bits : ℝ) := by exact_mod_cast hq
    simpa [Mem, lower, pointRat, (scale_real_pos bits).ne'] using
      (div_le_iff₀ (scale_real_pos bits)).2 hr
  · have hq : q * (scale bits : ℚ) ≤
        ((⌈q * (scale bits : ℚ)⌉ : Int) : ℚ) := Int.le_ceil _
    have hr : ((q : ℚ) : ℝ) * (scale bits : ℝ) ≤
        ((⌈q * (scale bits : ℚ)⌉ : Int) : ℝ) := by exact_mod_cast hq
    simpa [Mem, upper, pointRat, (scale_real_pos bits).ne'] using
      (le_div_iff₀ (scale_real_pos bits)).2 hr

private theorem floor_ratio_scaled_le (bits : Nat) (a b : Int) (hb : b ≠ 0) :
    ((floorDiv (a * scale bits) b : Int) : ℝ) / (scale bits : ℝ) ≤
      ((a : ℝ) / (scale bits : ℝ)) /
        ((b : ℝ) / (scale bits : ℝ)) := by
  have hq : ((floorDiv (a * scale bits) b : Int) : ℚ) ≤
      ((a * scale bits : Int) : ℚ) / (b : ℚ) := Int.floor_le _
  have hr : ((floorDiv (a * scale bits) b : Int) : ℝ) ≤
      ((a * scale bits : Int) : ℝ) / (b : ℝ) := by exact_mod_cast hq
  have hbr : (b : ℝ) ≠ 0 := by exact_mod_cast hb
  have hs : (scale bits : ℝ) ≠ 0 := (scale_real_pos bits).ne'
  calc
    _ ≤ (((a * scale bits : Int) : ℝ) / (b : ℝ)) /
        (scale bits : ℝ) := div_le_div_of_nonneg_right hr (scale_real_pos bits).le
    _ = _ := by push_cast; field_simp

private theorem le_ceil_ratio_scaled (bits : Nat) (a b : Int) (hb : b ≠ 0) :
    ((a : ℝ) / (scale bits : ℝ)) /
        ((b : ℝ) / (scale bits : ℝ)) ≤
      ((ceilDiv (a * scale bits) b : Int) : ℝ) / (scale bits : ℝ) := by
  have hq : ((a * scale bits : Int) : ℚ) / (b : ℚ) ≤
      ((ceilDiv (a * scale bits) b : Int) : ℚ) := Int.le_ceil _
  have hr : ((a * scale bits : Int) : ℝ) / (b : ℝ) ≤
      ((ceilDiv (a * scale bits) b : Int) : ℝ) := by exact_mod_cast hq
  have hbr : (b : ℝ) ≠ 0 := by exact_mod_cast hb
  have hs : (scale bits : ℝ) ≠ 0 := (scale_real_pos bits).ne'
  calc
    _ = (((a * scale bits : Int) : ℝ) / (b : ℝ)) /
        (scale bits : ℝ) := by push_cast; field_simp
    _ ≤ _ := div_le_div_of_nonneg_right hr (scale_real_pos bits).le

private theorem min4_scaled (bits : Nat) (a b c d : Int) :
    (((min4 (a*b) (a*d) (c*b) (c*d) : Int) : ℝ) /
        (scale bits : ℝ)) / (scale bits : ℝ) =
      min (min ((a:ℝ)/(scale bits:ℝ) * ((b:ℝ)/(scale bits:ℝ)))
               ((a:ℝ)/(scale bits:ℝ) * ((d:ℝ)/(scale bits:ℝ))))
          (min ((c:ℝ)/(scale bits:ℝ) * ((b:ℝ)/(scale bits:ℝ)))
               ((c:ℝ)/(scale bits:ℝ) * ((d:ℝ)/(scale bits:ℝ)))) := by
  simp only [min4, Int.cast_min, Int.cast_mul]
  let s : ℝ := (scale bits : ℝ)
  have hs : s ≠ 0 := (scale_real_pos bits).ne'
  have hs2 : 0 ≤ s * s := mul_nonneg (scale_real_pos bits).le (scale_real_pos bits).le
  change (min (min ((a:ℝ)*(b:ℝ)) ((a:ℝ)*(d:ℝ)))
      (min ((c:ℝ)*(b:ℝ)) ((c:ℝ)*(d:ℝ))) / s) / s =
    min (min (((a:ℝ)/s) * ((b:ℝ)/s)) (((a:ℝ)/s) * ((d:ℝ)/s)))
      (min (((c:ℝ)/s) * ((b:ℝ)/s)) (((c:ℝ)/s) * ((d:ℝ)/s)))
  rw [show ∀ x : ℝ, (x / s) / s = x / (s*s) by intro x; field_simp]
  simp_rw [show ∀ x y : ℝ, (x / s) * (y / s) = (x*y) / (s*s) by
    intro x y; field_simp]
  rw [min_div_div_right hs2, min_div_div_right hs2, min_div_div_right hs2]

private theorem max4_scaled (bits : Nat) (a b c d : Int) :
    (((max4 (a*b) (a*d) (c*b) (c*d) : Int) : ℝ) /
        (scale bits : ℝ)) / (scale bits : ℝ) =
      max (max ((a:ℝ)/(scale bits:ℝ) * ((b:ℝ)/(scale bits:ℝ)))
               ((a:ℝ)/(scale bits:ℝ) * ((d:ℝ)/(scale bits:ℝ))))
          (max ((c:ℝ)/(scale bits:ℝ) * ((b:ℝ)/(scale bits:ℝ)))
               ((c:ℝ)/(scale bits:ℝ) * ((d:ℝ)/(scale bits:ℝ)))) := by
  simp only [max4, Int.cast_max, Int.cast_mul]
  let s : ℝ := (scale bits : ℝ)
  have hs : s ≠ 0 := (scale_real_pos bits).ne'
  have hs2 : 0 ≤ s * s := mul_nonneg (scale_real_pos bits).le (scale_real_pos bits).le
  change (max (max ((a:ℝ)*(b:ℝ)) ((a:ℝ)*(d:ℝ)))
      (max ((c:ℝ)*(b:ℝ)) ((c:ℝ)*(d:ℝ))) / s) / s =
    max (max (((a:ℝ)/s) * ((b:ℝ)/s)) (((a:ℝ)/s) * ((d:ℝ)/s)))
      (max (((c:ℝ)/s) * ((b:ℝ)/s)) (((c:ℝ)/s) * ((d:ℝ)/s)))
  rw [show ∀ x : ℝ, (x / s) / s = x / (s*s) by intro x; field_simp]
  simp_rw [show ∀ x y : ℝ, (x / s) * (y / s) = (x*y) / (s*s) by
    intro x y; field_simp]
  rw [max_div_div_right hs2, max_div_div_right hs2, max_div_div_right hs2]

private theorem min2_square_scaled (bits : Nat) (a b : Int) :
    (((min (a*a) (b*b) : Int) : ℝ) / (scale bits : ℝ)) /
        (scale bits : ℝ) =
      min (((a:ℝ)/(scale bits:ℝ)) ^ 2)
          (((b:ℝ)/(scale bits:ℝ)) ^ 2) := by
  simp only [Int.cast_min, Int.cast_mul]
  let s : ℝ := (scale bits : ℝ)
  have hs : s ≠ 0 := (scale_real_pos bits).ne'
  have hs2 : 0 ≤ s * s := mul_nonneg (scale_real_pos bits).le (scale_real_pos bits).le
  change (min ((a:ℝ)*(a:ℝ)) ((b:ℝ)*(b:ℝ)) / s) / s =
    min (((a:ℝ)/s)^2) (((b:ℝ)/s)^2)
  rw [show ∀ x : ℝ, (x / s) / s = x / (s*s) by intro x; field_simp]
  simp_rw [show ∀ x : ℝ, (x / s)^2 = (x*x)/(s*s) by
    intro x; field_simp]
  rw [min_div_div_right hs2]

private theorem max2_square_scaled (bits : Nat) (a b : Int) :
    (((max (a*a) (b*b) : Int) : ℝ) / (scale bits : ℝ)) /
        (scale bits : ℝ) =
      max (((a:ℝ)/(scale bits:ℝ)) ^ 2)
          (((b:ℝ)/(scale bits:ℝ)) ^ 2) := by
  simp only [Int.cast_max, Int.cast_mul]
  let s : ℝ := (scale bits : ℝ)
  have hs : s ≠ 0 := (scale_real_pos bits).ne'
  have hs2 : 0 ≤ s * s := mul_nonneg (scale_real_pos bits).le (scale_real_pos bits).le
  change (max ((a:ℝ)*(a:ℝ)) ((b:ℝ)*(b:ℝ)) / s) / s =
    max (((a:ℝ)/s)^2) (((b:ℝ)/s)^2)
  rw [show ∀ x : ℝ, (x / s) / s = x / (s*s) by intro x; field_simp]
  simp_rw [show ∀ x : ℝ, (x / s)^2 = (x*x)/(s*s) by
    intro x; field_simp]
  rw [max_div_div_right hs2]

private theorem int_sqrt_sq_le {n : Int} (hn : 0 ≤ n) :
    Int.sqrt n * Int.sqrt n ≤ n := by
  have hncast : (n.toNat : Int) = n := Int.toNat_of_nonneg hn
  rw [Int.sqrt, ← hncast]
  exact_mod_cast Nat.sqrt_le n.toNat

private theorem int_lt_succ_sqrt_sq {n : Int} (hn : 0 ≤ n) :
    n < (Int.sqrt n + 1) * (Int.sqrt n + 1) := by
  have hncast : (n.toNat : Int) = n := Int.toNat_of_nonneg hn
  rw [Int.sqrt, ← hncast]
  exact_mod_cast Nat.lt_succ_sqrt n.toNat

private theorem le_ceilSqrtInt_sq {n : Int} (hn : 0 ≤ n) :
    n ≤ ceilSqrtInt n * ceilSqrtInt n := by
  rw [ceilSqrtInt]
  split
  · exact (int_lt_succ_sqrt_sq hn).le
  · omega

private theorem ceilSqrtInt_nonneg (n : Int) : 0 ≤ ceilSqrtInt n := by
  rw [ceilSqrtInt]
  split <;> have := Int.sqrt_nonneg n <;> omega

theorem mul_sound {bits : Nat} {a b : DInterval} {x y : ℝ}
    (hx : Mem bits x a) (hy : Mem bits y b) : Mem bits (x * y) (mul bits a b) := by
  obtain ⟨hlo, hhi⟩ := JackalIv.mul_mem_corners
    (lower bits a) (upper bits a) (lower bits b) (upper bits b) x y
    hx.1 hx.2 hy.1 hy.2
  constructor
  · exact (floor_scaled_le bits _).trans ((min4_scaled bits a.lo b.lo a.hi b.hi).symm ▸ hlo)
  · exact hhi.trans ((max4_scaled bits a.lo b.lo a.hi b.hi) ▸ le_ceil_scaled bits _)

theorem div_sound {bits : Nat} {a b : DInterval} {x y : ℝ}
    (hx : Mem bits x a) (hy : Mem bits y b)
    (hden : 0 < lower bits b ∨ upper bits b < 0) :
    Mem bits (x / y) (divUnchecked bits a b) := by
  have hblo : b.lo ≠ 0 := by
    intro hz
    rcases hden with h | h
    · simp [lower, hz] at h
    · have hbad : lower bits b < 0 := hy.1.trans_lt (hy.2.trans_lt h)
      simp [lower, hz] at hbad
  have hbhi : b.hi ≠ 0 := by
    intro hz
    rcases hden with h | h
    · have hbad : 0 < upper bits b := h.trans_le (hy.1.trans hy.2)
      simp [upper, hz] at hbad
    · simp [upper, hz] at h
  obtain ⟨hlo, hhi⟩ := JackalIv.div_mem_corners
    (lower bits a) (upper bits a) (lower bits b) (upper bits b) x y
    hx.1 hx.2 hy.1 hy.2 hden
  let s := scale bits
  let q0lo := floorDiv (a.lo * s) b.lo
  let q1lo := floorDiv (a.lo * s) b.hi
  let q2lo := floorDiv (a.hi * s) b.lo
  let q3lo := floorDiv (a.hi * s) b.hi
  let q0hi := ceilDiv (a.lo * s) b.lo
  let q1hi := ceilDiv (a.lo * s) b.hi
  let q2hi := ceilDiv (a.hi * s) b.lo
  let q3hi := ceilDiv (a.hi * s) b.hi
  constructor
  · apply le_trans ?_ hlo
    apply le_min
    · apply le_min
      · exact (div_le_div_of_nonneg_right
          (Int.cast_le.2 (le_trans (min_le_left _ _) (min_le_left _ _)))
          (scale_real_pos bits).le).trans (floor_ratio_scaled_le bits _ _ hblo)
      · exact (div_le_div_of_nonneg_right
          (Int.cast_le.2 (le_trans (min_le_left _ _) (min_le_right _ _)))
          (scale_real_pos bits).le).trans (floor_ratio_scaled_le bits _ _ hbhi)
    · apply le_min
      · exact (div_le_div_of_nonneg_right
          (Int.cast_le.2 (le_trans (min_le_right _ _) (min_le_left _ _)))
          (scale_real_pos bits).le).trans (floor_ratio_scaled_le bits _ _ hblo)
      · exact (div_le_div_of_nonneg_right
          (Int.cast_le.2 (le_trans (min_le_right _ _) (min_le_right _ _)))
          (scale_real_pos bits).le).trans (floor_ratio_scaled_le bits _ _ hbhi)
  · apply le_trans hhi
    apply max_le
    · apply max_le
      · exact (le_ceil_ratio_scaled bits _ _ hblo).trans
          (div_le_div_of_nonneg_right
            (Int.cast_le.2 (le_trans (le_max_left _ _) (le_max_left _ _)))
            (scale_real_pos bits).le)
      · exact (le_ceil_ratio_scaled bits _ _ hbhi).trans
          (div_le_div_of_nonneg_right
            (Int.cast_le.2 (le_trans (le_max_right _ _) (le_max_left _ _)))
            (scale_real_pos bits).le)
    · apply max_le
      · exact (le_ceil_ratio_scaled bits _ _ hblo).trans
          (div_le_div_of_nonneg_right
            (Int.cast_le.2 (le_trans (le_max_left _ _) (le_max_right _ _)))
            (scale_real_pos bits).le)
      · exact (le_ceil_ratio_scaled bits _ _ hbhi).trans
          (div_le_div_of_nonneg_right
            (Int.cast_le.2 (le_trans (le_max_right _ _) (le_max_right _ _)))
            (scale_real_pos bits).le)

theorem square_sound {bits : Nat} {a : DInterval} {x : ℝ}
    (hx : Mem bits x a) : Mem bits (x ^ 2) (square bits a) := by
  have hupper : x ^ 2 ≤ max ((lower bits a) ^ 2) ((upper bits a) ^ 2) := by
    rcases le_total x 0 with hxneg | hxpos
    · apply le_max_of_le_left
      have h1 : 0 ≤ x - lower bits a := sub_nonneg.mpr hx.1
      have h2 : 0 ≤ -x - lower bits a := by linarith
      nlinarith [mul_nonneg h1 h2]
    · apply le_max_of_le_right
      have h1 : 0 ≤ upper bits a - x := sub_nonneg.mpr hx.2
      have h2 : 0 ≤ upper bits a + x := by linarith
      nlinarith [mul_nonneg h1 h2]
  by_cases hz : a.lo ≤ 0 ∧ 0 ≤ a.hi
  · rw [square, if_pos hz]
    constructor
    · simp [lower]
      positivity
    · exact hupper.trans
        ((max2_square_scaled bits a.lo a.hi).symm ▸ le_ceil_scaled bits _)
  · rw [square, if_neg hz]
    constructor
    · apply (floor_scaled_le bits _).trans
      rw [min2_square_scaled]
      by_cases hlo : a.lo ≤ 0
      · have hhi : a.hi < 0 := by omega
        apply min_le_iff.mpr
        right
        have hxneg : x ≤ upper bits a := hx.2
        have huNeg : upper bits a < 0 := by
          exact div_neg_of_neg_of_pos (by exact_mod_cast hhi) (scale_real_pos bits)
        have h3 : 0 ≤ upper bits a - x := by linarith
        have h4 : 0 ≤ -x - upper bits a := by linarith
        have hp : 0 ≤ (upper bits a - x) * (-x - upper bits a) :=
          mul_nonneg h3 h4
        simp only [upper] at hp ⊢
        nlinarith
      · have hloPos : 0 < a.lo := by omega
        apply min_le_iff.mpr
        left
        have hlPos : 0 < lower bits a :=
          div_pos (by exact_mod_cast hloPos) (scale_real_pos bits)
        have h1 : 0 ≤ x - lower bits a := sub_nonneg.mpr hx.1
        have h2 : 0 ≤ x + lower bits a := by linarith
        have hp : 0 ≤ (x - lower bits a) * (x + lower bits a) :=
          mul_nonneg h1 h2
        simp only [lower] at hp ⊢
        nlinarith
    · exact hupper.trans
        ((max2_square_scaled bits a.lo a.hi).symm ▸ le_ceil_scaled bits _)

theorem sqrt_sound {bits : Nat} {a : DInterval} {x : ℝ}
    (hlo : 0 ≤ a.lo) (hx0 : 0 ≤ x) (hx : Mem bits x a) :
    Mem bits (Real.sqrt x)
      ⟨Int.sqrt (a.lo * scale bits), ceilSqrtInt (a.hi * scale bits)⟩ := by
  have hs : (0 : ℝ) < (scale bits : ℝ) := scale_real_pos bits
  have hs0 : (0 : Int) < scale bits := scale_pos bits
  have hvalidReal : lower bits a ≤ upper bits a := hx.1.trans hx.2
  have hvalid : a.lo ≤ a.hi := by
    have hc : (a.lo : ℝ) ≤ (a.hi : ℝ) := by
      exact (div_le_div_iff_of_pos_right hs).mp hvalidReal
    exact_mod_cast hc
  have hhi : 0 ≤ a.hi := hlo.trans hvalid
  have hnlo : 0 ≤ a.lo * scale bits := mul_nonneg hlo hs0.le
  have hnhi : 0 ≤ a.hi * scale bits := mul_nonneg hhi hs0.le
  constructor
  · change ((Int.sqrt (a.lo * scale bits) : Int) : ℝ) /
        (scale bits : ℝ) ≤ Real.sqrt x
    apply (Real.le_sqrt
      (div_nonneg (by exact_mod_cast Int.sqrt_nonneg (a.lo * scale bits)) hs.le)
      hx0).2
    have hi := int_sqrt_sq_le hnlo
    have hir0 : ((Int.sqrt (a.lo * scale bits) : Int) : ℝ) *
        ((Int.sqrt (a.lo * scale bits) : Int) : ℝ) ≤
        (a.lo : ℝ) * (scale bits : ℝ) := by exact_mod_cast hi
    have hir : ((Int.sqrt (a.lo * scale bits) : Int) : ℝ) ^ 2 ≤
        (a.lo : ℝ) * (scale bits : ℝ) := by simpa [pow_two] using hir0
    calc
      (((Int.sqrt (a.lo * scale bits) : Int) : ℝ) /
          (scale bits : ℝ)) ^ 2
          = (((Int.sqrt (a.lo * scale bits) : Int) : ℝ) ^ 2) /
              ((scale bits : ℝ) ^ 2) := by rw [div_pow]
      _ ≤ ((a.lo : ℝ) * (scale bits : ℝ)) /
              ((scale bits : ℝ) ^ 2) :=
          div_le_div_of_nonneg_right hir (sq_nonneg _)
      _ = lower bits a := by simp [lower]; field_simp
      _ ≤ x := hx.1
  · change Real.sqrt x ≤ ((ceilSqrtInt (a.hi * scale bits) : Int) : ℝ) /
        (scale bits : ℝ)
    apply Real.sqrt_le_iff.mpr
    constructor
    · exact div_nonneg (by
          exact_mod_cast ceilSqrtInt_nonneg (a.hi * scale bits)) hs.le
    · have hi := le_ceilSqrtInt_sq hnhi
      have hir0 : (a.hi : ℝ) * (scale bits : ℝ) ≤
          ((ceilSqrtInt (a.hi * scale bits) : Int) : ℝ) *
          ((ceilSqrtInt (a.hi * scale bits) : Int) : ℝ) := by exact_mod_cast hi
      have hir : (a.hi : ℝ) * (scale bits : ℝ) ≤
          ((ceilSqrtInt (a.hi * scale bits) : Int) : ℝ) ^ 2 := by
        simpa [pow_two] using hir0
      apply hx.2.trans
      calc
        upper bits a = ((a.hi : ℝ) * (scale bits : ℝ)) /
            ((scale bits : ℝ) ^ 2) := by simp [upper]; field_simp
        _ ≤ (((ceilSqrtInt (a.hi * scale bits) : Int) : ℝ) ^ 2) /
            ((scale bits : ℝ) ^ 2) := div_le_div_of_nonneg_right hir (sq_nonneg _)
        _ = (((ceilSqrtInt (a.hi * scale bits) : Int) : ℝ) /
            (scale bits : ℝ)) ^ 2 := by rw [div_pow]

theorem lower_pos_of_lo_pos {bits : Nat} {a : DInterval} (h : 0 < a.lo) :
    0 < lower bits a :=
  div_pos (by exact_mod_cast h) (scale_real_pos bits)
theorem hull_sound_left {bits : Nat} {a b : DInterval} {x : ℝ}
    (hx : Mem bits x a) : Mem bits x (hull a b) := by
  constructor
  · exact (div_le_div_of_nonneg_right (Int.cast_le.2 (min_le_left _ _)) (scale_real_pos bits).le).trans hx.1
  · exact hx.2.trans (div_le_div_of_nonneg_right (Int.cast_le.2 (le_max_left _ _)) (scale_real_pos bits).le)

theorem hull_sound_right {bits : Nat} {a b : DInterval} {x : ℝ}
    (hx : Mem bits x b) : Mem bits x (hull a b) := by
  constructor
  · exact (div_le_div_of_nonneg_right (Int.cast_le.2 (min_le_right _ _)) (scale_real_pos bits).le).trans hx.1
  · exact hx.2.trans (div_le_div_of_nonneg_right (Int.cast_le.2 (le_max_right _ _)) (scale_real_pos bits).le)

theorem intersection_sound {bits : Nat} {a b c : DInterval} {x : ℝ}
    (hc : intersection a b = some c) (ha : Mem bits x a) (hb : Mem bits x b) :
    Mem bits x c := by
  simp only [intersection] at hc
  split at hc
  · cases hc
    constructor
    · change ((max a.lo b.lo : Int) : ℝ) / (scale bits : ℝ) ≤ x
      rw [Int.cast_max, ← max_div_div_right (scale_real_pos bits).le]
      exact max_le ha.1 hb.1
    · change x ≤ ((min a.hi b.hi : Int) : ℝ) / (scale bits : ℝ)
      rw [Int.cast_min, ← min_div_div_right (scale_real_pos bits).le]
      exact le_min ha.2 hb.2
  · contradiction

end JackalIv.Spacecraft
