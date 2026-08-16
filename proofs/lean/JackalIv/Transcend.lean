/-
JackalIv/Transcend.lean — zero-libm exact-rational enclosures for sin, cos,
tan (as a bracket helper), and arctan (§490 fragment extension v1.5.0).

Everything here is either a computable `ℚ` endpoint function or a soundness
lemma transporting a decidable rational inequality to the real fact the
`Runs` constructors need.  The Mathlib inputs are:

* `Real.sin_bound`  : `|x| ≤ 1 → |sin x − (x − x³/6)| ≤ |x|⁵ / 100`
* `Real.cos_bound`  : `|x| ≤ 1 → |cos x − (1 − x²/2)| ≤ |x|⁴ · (5/96)`
* `Real.cos_pos_of_le_one`, `Real.abs_sin_sub_sin_le`, `Real.abs_cos_sub_cos_le`
* `Real.tan_eq_sin_div_cos`, `Real.arctan_tan`, `Real.tan_arctan`,
  `Real.arctan_mono`, `Real.arctan_lt_pi_div_two`,
  `Real.neg_pi_div_two_lt_arctan`,
  `Real.arctan_inv_of_pos`, `Real.arctan_inv_of_neg`
* `Real.pi_gt_d20` / `Real.pi_lt_d20` (20-decimal-digit rational π bounds)

No `sorry`/`admit`/axiom/`native_decide`/`@[implemented_by]`.
-/
import JackalIv.Gaussian
import Mathlib.Analysis.SpecialFunctions.Trigonometric.Bounds
import Mathlib.Analysis.SpecialFunctions.Trigonometric.Arctan
import Mathlib.Analysis.Real.Pi.Bounds

namespace JackalIv.Transcend

/-! ### Rational π bounds (from Mathlib's 20-digit theorems) -/

/-- Rational lower bound for π: `3.14159265358979323846`. -/
def piLoQ : ℚ := 314159265358979323846 / 100000000000000000000

/-- Rational upper bound for π: `3.14159265358979323847`. -/
def piHiQ : ℚ := 314159265358979323847 / 100000000000000000000

theorem piLoQ_lt_pi : ((piLoQ : ℚ) : ℝ) < Real.pi := by
  have h := Real.pi_gt_d20
  unfold piLoQ
  push_cast
  norm_num at h ⊢
  linarith

theorem pi_lt_piHiQ : Real.pi < ((piHiQ : ℚ) : ℝ) := by
  have h := Real.pi_lt_d20
  unfold piHiQ
  push_cast
  norm_num at h ⊢
  linarith

lemma three_lt_piHiQ : (3 : ℚ) < piHiQ := by unfold piHiQ; norm_num

/-! ### Point enclosures for sin/cos at a rational argument with `|m| ≤ 1` -/

/-- Rational lower endpoint for `sin m` (`|m| ≤ 1`). -/
def sinLoQ (m : ℚ) : ℚ := (m - m ^ 3 / 6) - |m| ^ 5 / 100

/-- Rational upper endpoint for `sin m` (`|m| ≤ 1`). -/
def sinHiQ (m : ℚ) : ℚ := (m - m ^ 3 / 6) + |m| ^ 5 / 100

/-- Rational lower endpoint for `cos m` (`|m| ≤ 1`). -/
def cosLoQ (m : ℚ) : ℚ := (1 - m ^ 2 / 2) - m ^ 4 * (5 / 96)

/-- Rational upper endpoint for `cos m` (`|m| ≤ 1`). -/
def cosHiQ (m : ℚ) : ℚ := (1 - m ^ 2 / 2) + m ^ 4 * (5 / 96)

lemma abs_cast_le_one {m : ℚ} (hm : |m| ≤ 1) : |((m : ℚ) : ℝ)| ≤ 1 := by
  rw [← Rat.cast_abs]
  exact_mod_cast hm

/-- `sin m ∈ [sinLoQ m, sinHiQ m]` for rational `|m| ≤ 1`. -/
theorem sin_mem (m : ℚ) (hm : |m| ≤ 1) :
    ((sinLoQ m : ℚ) : ℝ) ≤ Real.sin ((m : ℚ) : ℝ) ∧
      Real.sin ((m : ℚ) : ℝ) ≤ ((sinHiQ m : ℚ) : ℝ) := by
  have h := Real.sin_bound (abs_cast_le_one hm)
  rw [abs_sub_le_iff] at h
  have hcast : |((m : ℚ) : ℝ)| = ((|m| : ℚ) : ℝ) := (Rat.cast_abs m).symm
  rw [hcast] at h
  unfold sinLoQ sinHiQ
  constructor
  · push_cast
    push_cast at h
    nlinarith [h.1, h.2]
  · push_cast
    push_cast at h
    nlinarith [h.1, h.2]

/-- `cos m ∈ [cosLoQ m, cosHiQ m]` for rational `|m| ≤ 1`. -/
theorem cos_mem (m : ℚ) (hm : |m| ≤ 1) :
    ((cosLoQ m : ℚ) : ℝ) ≤ Real.cos ((m : ℚ) : ℝ) ∧
      Real.cos ((m : ℚ) : ℝ) ≤ ((cosHiQ m : ℚ) : ℝ) := by
  have h := Real.cos_bound (abs_cast_le_one hm)
  rw [abs_sub_le_iff] at h
  have habs : |((m : ℚ) : ℝ)| ^ 4 = ((m : ℚ) : ℝ) ^ 4 := by
    rw [← abs_pow]
    exact abs_of_nonneg (by positivity)
  rw [habs] at h
  unfold cosLoQ cosHiQ
  constructor
  · push_cast
    nlinarith [h.1, h.2]
  · push_cast
    nlinarith [h.1, h.2]

/-- The rational cos lower endpoint is strictly positive on `|m| ≤ 1`
(indeed `cosLoQ m ≥ 1 − 1/2 − 5/96 = 43/96`). -/
theorem cosLoQ_pos (m : ℚ) (hm : |m| ≤ 1) : 0 < cosLoQ m := by
  unfold cosLoQ
  have habs := abs_le.mp hm
  have h2 : m ^ 2 ≤ 1 := by nlinarith [habs.1, habs.2]
  have h4 : m ^ 4 ≤ 1 := by nlinarith [sq_nonneg m, sq_nonneg (m ^ 2)]
  nlinarith [sq_nonneg m, sq_nonneg (m ^ 2)]

lemma cosLoQ_le_cosHiQ (m : ℚ) : cosLoQ m ≤ cosHiQ m := by
  unfold cosLoQ cosHiQ
  have h4 : (0 : ℚ) ≤ m ^ 4 := by positivity
  nlinarith

/-! ### Interval enclosures for sin/cos via midpoint Taylor + Lipschitz-1 -/

/-- Range soundness for `sin` over `[m−hw, m+hw]`: the rational Taylor point
enclosure at `m`, widened by the halfwidth `hw`, encloses `sin t` for every
real `t` in the interval (|sin′| ≤ 1). -/
theorem sin_range (m hw loQ hiQ : ℚ) (hm : |m| ≤ 1)
    (hlo : loQ ≤ sinLoQ m - hw) (hhi : sinHiQ m + hw ≤ hiQ) :
    ∀ t : ℝ, ((m : ℚ) : ℝ) - ((hw : ℚ) : ℝ) ≤ t → t ≤ ((m : ℚ) : ℝ) + ((hw : ℚ) : ℝ) →
      ((loQ : ℚ) : ℝ) ≤ Real.sin t ∧ Real.sin t ≤ ((hiQ : ℚ) : ℝ) := by
  intro t ht1 ht2
  have hlip := Real.abs_sin_sub_sin_le t ((m : ℚ) : ℝ)
  have habs : |t - ((m : ℚ) : ℝ)| ≤ ((hw : ℚ) : ℝ) :=
    abs_le.mpr ⟨by linarith, by linarith⟩
  have hlip' := abs_sub_le_iff.mp (le_trans hlip habs)
  have hpt := sin_mem m hm
  have hloR : ((loQ : ℚ) : ℝ) ≤ ((sinLoQ m : ℚ) : ℝ) - ((hw : ℚ) : ℝ) := by
    have h0 : ((loQ : ℚ) : ℝ) ≤ ((sinLoQ m - hw : ℚ) : ℝ) := by exact_mod_cast hlo
    push_cast at h0
    linarith
  have hhiR : ((sinHiQ m : ℚ) : ℝ) + ((hw : ℚ) : ℝ) ≤ ((hiQ : ℚ) : ℝ) := by
    have h0 : ((sinHiQ m + hw : ℚ) : ℝ) ≤ ((hiQ : ℚ) : ℝ) := by exact_mod_cast hhi
    push_cast at h0
    linarith
  constructor
  · linarith [hpt.1, hlip'.2]
  · linarith [hpt.2, hlip'.1]

/-- Range soundness for `cos` over `[m−hw, m+hw]` (|cos′| ≤ 1). -/
theorem cos_range (m hw loQ hiQ : ℚ) (hm : |m| ≤ 1)
    (hlo : loQ ≤ cosLoQ m - hw) (hhi : cosHiQ m + hw ≤ hiQ) :
    ∀ t : ℝ, ((m : ℚ) : ℝ) - ((hw : ℚ) : ℝ) ≤ t → t ≤ ((m : ℚ) : ℝ) + ((hw : ℚ) : ℝ) →
      ((loQ : ℚ) : ℝ) ≤ Real.cos t ∧ Real.cos t ≤ ((hiQ : ℚ) : ℝ) := by
  intro t ht1 ht2
  have hlip := Real.abs_cos_sub_cos_le t ((m : ℚ) : ℝ)
  have habs : |t - ((m : ℚ) : ℝ)| ≤ ((hw : ℚ) : ℝ) :=
    abs_le.mpr ⟨by linarith, by linarith⟩
  have hlip' := abs_sub_le_iff.mp (le_trans hlip habs)
  have hpt := cos_mem m hm
  have hloR : ((loQ : ℚ) : ℝ) ≤ ((cosLoQ m : ℚ) : ℝ) - ((hw : ℚ) : ℝ) := by
    have h0 : ((loQ : ℚ) : ℝ) ≤ ((cosLoQ m - hw : ℚ) : ℝ) := by exact_mod_cast hlo
    push_cast at h0
    linarith
  have hhiR : ((cosHiQ m : ℚ) : ℝ) + ((hw : ℚ) : ℝ) ≤ ((hiQ : ℚ) : ℝ) := by
    have h0 : ((cosHiQ m + hw : ℚ) : ℝ) ≤ ((hiQ : ℚ) : ℝ) := by exact_mod_cast hhi
    push_cast at h0
    linarith
  constructor
  · linarith [hpt.1, hlip'.2]
  · linarith [hpt.2, hlip'.1]

/-! ### Rational tan brackets at `|t| ≤ 1` -/

/-- Rational lower endpoint for `tan t` (`|t| ≤ 1`): sign-aware corner of the
sin/cos brackets. -/
def tanLoQ (t : ℚ) : ℚ :=
  if 0 ≤ sinLoQ t then sinLoQ t / cosHiQ t else sinLoQ t / cosLoQ t

/-- Rational upper endpoint for `tan t` (`|t| ≤ 1`). -/
def tanHiQ (t : ℚ) : ℚ :=
  if 0 ≤ sinHiQ t then sinHiQ t / cosLoQ t else sinHiQ t / cosHiQ t

/-- `tan t ∈ [tanLoQ t, tanHiQ t]` for rational `|t| ≤ 1`. -/
theorem tan_mem (t : ℚ) (ht : |t| ≤ 1) :
    ((tanLoQ t : ℚ) : ℝ) ≤ Real.tan ((t : ℚ) : ℝ) ∧
      Real.tan ((t : ℚ) : ℝ) ≤ ((tanHiQ t : ℚ) : ℝ) := by
  have hcos := cos_mem t ht
  have hsin := sin_mem t ht
  have hcosLo : (0 : ℝ) < ((cosLoQ t : ℚ) : ℝ) := by exact_mod_cast cosLoQ_pos t ht
  have hcosPos : (0 : ℝ) < Real.cos ((t : ℚ) : ℝ) := lt_of_lt_of_le hcosLo hcos.1
  have hcosHi : (0 : ℝ) < ((cosHiQ t : ℚ) : ℝ) :=
    lt_of_lt_of_le hcosLo (by exact_mod_cast cosLoQ_le_cosHiQ t)
  rw [Real.tan_eq_sin_div_cos]
  constructor
  · -- lower endpoint
    unfold tanLoQ
    by_cases hs : (0 : ℚ) ≤ sinLoQ t
    · rw [if_pos hs]
      have hsR : (0 : ℝ) ≤ ((sinLoQ t : ℚ) : ℝ) := by exact_mod_cast hs
      push_cast
      rw [div_le_div_iff₀ hcosHi hcosPos]
      nlinarith [hsin.1, hcos.2, hcosPos, hsR]
    · rw [if_neg hs]
      rw [not_le] at hs
      have hsR : ((sinLoQ t : ℚ) : ℝ) < 0 := by exact_mod_cast hs
      push_cast
      rw [div_le_div_iff₀ hcosLo hcosPos]
      nlinarith [hsin.1, hcos.1, hcosPos, hsR]
  · -- upper endpoint
    unfold tanHiQ
    by_cases hs : (0 : ℚ) ≤ sinHiQ t
    · rw [if_pos hs]
      have hsR : (0 : ℝ) ≤ ((sinHiQ t : ℚ) : ℝ) := by exact_mod_cast hs
      push_cast
      rw [div_le_div_iff₀ hcosPos hcosLo]
      nlinarith [hsin.2, hcos.1, hcosPos, hsR]
    · rw [if_neg hs]
      rw [not_le] at hs
      have hsR : ((sinHiQ t : ℚ) : ℝ) < 0 := by exact_mod_cast hs
      push_cast
      rw [div_le_div_iff₀ hcosPos hcosHi]
      nlinarith [hsin.2, hcos.2, hcosPos, hcosHi, hsR]

/-! ### tan-bracket transport to arctan -/

/-- `1 < π/2` (so `|t| ≤ 1` keeps `t` strictly inside `(−π/2, π/2)`). -/
lemma one_lt_pi_div_two : (1 : ℝ) < Real.pi / 2 := by
  have := Real.pi_gt_three
  linarith

/-- A rational `|t| ≤ 1` lies strictly inside `(−π/2, π/2)`. -/
lemma mem_arctan_dom {t : ℚ} (ht : |t| ≤ 1) :
    -(Real.pi / 2) < ((t : ℚ) : ℝ) ∧ ((t : ℚ) : ℝ) < Real.pi / 2 := by
  have h := abs_le.mp (abs_cast_le_one ht)
  have := one_lt_pi_div_two
  constructor <;> linarith [h.1, h.2]

/-- Bracket transport, lower side: if `tan t ≤ q` for `|t| ≤ 1` then
`t ≤ arctan q`. -/
theorem le_arctan_of_tan_le {t : ℚ} {q : ℝ} (ht : |t| ≤ 1)
    (h : Real.tan ((t : ℚ) : ℝ) ≤ q) : ((t : ℚ) : ℝ) ≤ Real.arctan q := by
  have hdom := mem_arctan_dom ht
  calc ((t : ℚ) : ℝ) = Real.arctan (Real.tan ((t : ℚ) : ℝ)) :=
        (Real.arctan_tan hdom.1 hdom.2).symm
    _ ≤ Real.arctan q := Real.arctan_mono h

/-- Bracket transport, upper side: if `q ≤ tan t` for `|t| ≤ 1` then
`arctan q ≤ t`. -/
theorem arctan_le_of_le_tan {t : ℚ} {q : ℝ} (ht : |t| ≤ 1)
    (h : q ≤ Real.tan ((t : ℚ) : ℝ)) : Real.arctan q ≤ ((t : ℚ) : ℝ) := by
  have hdom := mem_arctan_dom ht
  calc Real.arctan q ≤ Real.arctan (Real.tan ((t : ℚ) : ℝ)) := Real.arctan_mono h
    _ = ((t : ℚ) : ℝ) := Real.arctan_tan hdom.1 hdom.2

/-! ### The decidable arctan endpoint admissions

Each side admits four decidable strategies; each is proved sound below.

* CAP        — the endpoint clears `±piHiQ/2`, outside arctan's whole range.
* BRACKET    — the endpoint itself is a `|·| ≤ 1` tan-bracket witness.
* POS-RECIP  — reciprocal reduction `arctan q = π/2 − arctan (1/q)`, `q > 0`.
* NEG-RECIP  — reciprocal reduction `arctan q = −π/2 − arctan (1/q)`, `q < 0`.
-/

/-- Lower-endpoint admission: `lo ≤ arctan q` for every `q ≥ cLo`. -/
def atanLoOK (lo cLo : ℚ) : Bool :=
  decide (lo ≤ -(piHiQ / 2)) ||
  (decide (|lo| ≤ 1) && decide (tanHiQ lo ≤ cLo)) ||
  (decide (0 < cLo) && decide (|piLoQ / 2 - lo| ≤ 1) &&
    decide (1 / cLo ≤ tanLoQ (piLoQ / 2 - lo))) ||
  (decide (cLo < 0) && decide (|-(piHiQ / 2) - lo| ≤ 1) &&
    decide (1 / cLo ≤ tanLoQ (-(piHiQ / 2) - lo)))

/-- Upper-endpoint admission: `arctan q ≤ hi` for every `q ≤ cHi`. -/
def atanHiOK (hi cHi : ℚ) : Bool :=
  decide (piHiQ / 2 ≤ hi) ||
  (decide (|hi| ≤ 1) && decide (cHi ≤ tanLoQ hi)) ||
  (decide (0 < cHi) && decide (|piHiQ / 2 - hi| ≤ 1) &&
    decide (tanHiQ (piHiQ / 2 - hi) ≤ 1 / cHi)) ||
  (decide (cHi < 0) && decide (|-(piLoQ / 2) - hi| ≤ 1) &&
    decide (tanHiQ (-(piLoQ / 2) - hi) ≤ 1 / cHi))

/-- SOUNDNESS of `atanLoOK`: an accepted lower endpoint bounds `arctan q`
from below for every real `q ≥ cLo`. -/
theorem atanLo_sound {lo cLo : ℚ} (h : atanLoOK lo cLo = true)
    {q : ℝ} (hq : ((cLo : ℚ) : ℝ) ≤ q) : ((lo : ℚ) : ℝ) ≤ Real.arctan q := by
  unfold atanLoOK at h
  simp only [Bool.or_eq_true, Bool.and_eq_true] at h
  rcases h with ((hcap | ⟨hbr1, hbr2⟩) | ⟨⟨hp1, hp2⟩, hp3⟩) | ⟨⟨hn1, hn2⟩, hn3⟩
  · -- CAP: lo ≤ −piHiQ/2 < −π/2 < arctan q
    have hcapQ : lo ≤ -(piHiQ / 2) := of_decide_eq_true hcap
    have h1 : ((lo : ℚ) : ℝ) ≤ -(((piHiQ : ℚ) : ℝ) / 2) := by
      have h0 : ((lo : ℚ) : ℝ) ≤ ((-(piHiQ / 2) : ℚ) : ℝ) := by exact_mod_cast hcapQ
      push_cast at h0
      linarith
    have h2 := pi_lt_piHiQ
    have h3 := Real.neg_pi_div_two_lt_arctan q
    linarith
  · -- BRACKET: tan lo ≤ tanHiQ lo ≤ cLo ≤ q
    have hlo1 : |lo| ≤ 1 := of_decide_eq_true hbr1
    have hbr2Q : tanHiQ lo ≤ cLo := of_decide_eq_true hbr2
    have htan := (tan_mem lo hlo1).2
    have hle : ((tanHiQ lo : ℚ) : ℝ) ≤ ((cLo : ℚ) : ℝ) := by exact_mod_cast hbr2Q
    exact le_arctan_of_tan_le hlo1 (le_trans htan (le_trans hle hq))
  · -- POS-RECIP: q ≥ cLo > 0; arctan q = π/2 − arctan (1/q)
    have hcpos : (0 : ℚ) < cLo := of_decide_eq_true hp1
    have hdom : |piLoQ / 2 - lo| ≤ 1 := of_decide_eq_true hp2
    have hbrQ : 1 / cLo ≤ tanLoQ (piLoQ / 2 - lo) := of_decide_eq_true hp3
    have hcposR : (0 : ℝ) < ((cLo : ℚ) : ℝ) := by exact_mod_cast hcpos
    have hqpos : (0 : ℝ) < q := lt_of_lt_of_le hcposR hq
    have hinv1 : (1 : ℝ) / q ≤ 1 / ((cLo : ℚ) : ℝ) :=
      one_div_le_one_div_of_le hcposR hq
    have hinv2 : ((1 / cLo : ℚ) : ℝ) ≤ ((tanLoQ (piLoQ / 2 - lo) : ℚ) : ℝ) := by
      exact_mod_cast hbrQ
    have htan := (tan_mem (piLoQ / 2 - lo) hdom).1
    have harc : Real.arctan (1 / q) ≤ (((piLoQ / 2 - lo : ℚ)) : ℝ) := by
      apply arctan_le_of_le_tan hdom
      have heq : ((1 / cLo : ℚ) : ℝ) = 1 / ((cLo : ℚ) : ℝ) := by push_cast; ring
      rw [heq] at hinv2
      linarith
    have hid := Real.arctan_inv_of_pos hqpos
    have hinv_eq : Real.arctan q⁻¹ = Real.arctan (1 / q) := by rw [one_div]
    have hcastt : (((piLoQ / 2 - lo : ℚ)) : ℝ) =
        ((piLoQ : ℚ) : ℝ) / 2 - ((lo : ℚ) : ℝ) := by push_cast; ring
    have hpiLo := piLoQ_lt_pi
    rw [hcastt] at harc
    rw [hinv_eq] at hid
    linarith
  · -- NEG-RECIP: cLo < 0; split on the sign of q.
    have hcneg : cLo < 0 := of_decide_eq_true hn1
    have hdom : |-(piHiQ / 2) - lo| ≤ 1 := of_decide_eq_true hn2
    have hbrQ : 1 / cLo ≤ tanLoQ (-(piHiQ / 2) - lo) := of_decide_eq_true hn3
    have hcnegR : ((cLo : ℚ) : ℝ) < 0 := by exact_mod_cast hcneg
    by_cases hqsign : q < 0
    · -- q ∈ [cLo, 0): arctan q = −π/2 − arctan (1/q)
      have hinv1 : (1 : ℝ) / q ≤ 1 / ((cLo : ℚ) : ℝ) :=
        one_div_le_one_div_of_neg_of_le hqsign hq
      have hinv2 : ((1 / cLo : ℚ) : ℝ) ≤ ((tanLoQ (-(piHiQ / 2) - lo) : ℚ) : ℝ) := by
        exact_mod_cast hbrQ
      have htan := (tan_mem (-(piHiQ / 2) - lo) hdom).1
      have harc : Real.arctan (1 / q) ≤ (((-(piHiQ / 2) - lo : ℚ)) : ℝ) := by
        apply arctan_le_of_le_tan hdom
        have heq : ((1 / cLo : ℚ) : ℝ) = 1 / ((cLo : ℚ) : ℝ) := by push_cast; ring
        rw [heq] at hinv2
        linarith
      have hid := Real.arctan_inv_of_neg hqsign
      have hinv_eq : Real.arctan q⁻¹ = Real.arctan (1 / q) := by rw [one_div]
      have hcastt : (((-(piHiQ / 2) - lo : ℚ)) : ℝ) =
          -(((piHiQ : ℚ) : ℝ) / 2) - ((lo : ℚ) : ℝ) := by push_cast; ring
      have hpiHi := pi_lt_piHiQ
      rw [hcastt] at harc
      rw [hinv_eq] at hid
      linarith
    · -- q ≥ 0: arctan q ≥ 0 and the domain witness forces lo < 0.
      rw [not_lt] at hqsign
      have harctan_nn : 0 ≤ Real.arctan q := by
        have h0 := Real.arctan_mono hqsign
        simpa [Real.arctan_zero] using h0
      have hd := abs_le.mp hdom
      have hlo_neg : ((lo : ℚ) : ℝ) ≤ 0 := by
        have h1 : -1 ≤ -(piHiQ / 2) - lo := hd.1
        have h3 := three_lt_piHiQ
        have h2 : lo ≤ (0 : ℚ) := by linarith
        exact_mod_cast h2
      linarith

/-- SOUNDNESS of `atanHiOK`: an accepted upper endpoint bounds `arctan q`
from above for every real `q ≤ cHi`. -/
theorem atanHi_sound {hi cHi : ℚ} (h : atanHiOK hi cHi = true)
    {q : ℝ} (hq : q ≤ ((cHi : ℚ) : ℝ)) : Real.arctan q ≤ ((hi : ℚ) : ℝ) := by
  unfold atanHiOK at h
  simp only [Bool.or_eq_true, Bool.and_eq_true] at h
  rcases h with ((hcap | ⟨hbr1, hbr2⟩) | ⟨⟨hp1, hp2⟩, hp3⟩) | ⟨⟨hn1, hn2⟩, hn3⟩
  · -- CAP: arctan q < π/2 < piHiQ/2 ≤ hi
    have hcapQ : piHiQ / 2 ≤ hi := of_decide_eq_true hcap
    have h1 : ((piHiQ : ℚ) : ℝ) / 2 ≤ ((hi : ℚ) : ℝ) := by
      have h0 : ((piHiQ / 2 : ℚ) : ℝ) ≤ ((hi : ℚ) : ℝ) := by exact_mod_cast hcapQ
      push_cast at h0
      linarith
    have h2 := pi_lt_piHiQ
    have h3 := Real.arctan_lt_pi_div_two q
    linarith
  · -- BRACKET: q ≤ cHi ≤ tanLoQ hi ≤ tan hi
    have hhi1 : |hi| ≤ 1 := of_decide_eq_true hbr1
    have hbr2Q : cHi ≤ tanLoQ hi := of_decide_eq_true hbr2
    have htan := (tan_mem hi hhi1).1
    have hle : ((cHi : ℚ) : ℝ) ≤ ((tanLoQ hi : ℚ) : ℝ) := by exact_mod_cast hbr2Q
    exact arctan_le_of_le_tan hhi1 (le_trans hq (le_trans hle htan))
  · -- POS-RECIP: 0 < cHi; split on the sign of q.
    have hcpos : (0 : ℚ) < cHi := of_decide_eq_true hp1
    have hdom : |piHiQ / 2 - hi| ≤ 1 := of_decide_eq_true hp2
    have hbrQ : tanHiQ (piHiQ / 2 - hi) ≤ 1 / cHi := of_decide_eq_true hp3
    have hcposR : (0 : ℝ) < ((cHi : ℚ) : ℝ) := by exact_mod_cast hcpos
    have hinv2 : ((tanHiQ (piHiQ / 2 - hi) : ℚ) : ℝ) ≤ ((1 / cHi : ℚ) : ℝ) := by
      exact_mod_cast hbrQ
    have htan := (tan_mem (piHiQ / 2 - hi) hdom).2
    have hcastt : (((piHiQ / 2 - hi : ℚ)) : ℝ) =
        ((piHiQ : ℚ) : ℝ) / 2 - ((hi : ℚ) : ℝ) := by push_cast; ring
    have hpiHi := pi_lt_piHiQ
    by_cases hqsign : 0 < q
    · -- 0 < q ≤ cHi: tan t ≤ 1/cHi ≤ 1/q ⇒ t ≤ arctan (1/q)
      have hinv1 : 1 / ((cHi : ℚ) : ℝ) ≤ 1 / q :=
        one_div_le_one_div_of_le hqsign hq
      have harc : (((piHiQ / 2 - hi : ℚ)) : ℝ) ≤ Real.arctan (1 / q) := by
        apply le_arctan_of_tan_le hdom
        have heq : ((1 / cHi : ℚ) : ℝ) = 1 / ((cHi : ℚ) : ℝ) := by push_cast; ring
        rw [heq] at hinv2
        linarith
      have hid := Real.arctan_inv_of_pos hqsign
      have hinv_eq : Real.arctan q⁻¹ = Real.arctan (1 / q) := by rw [one_div]
      rw [hcastt] at harc
      rw [hinv_eq] at hid
      linarith
    · -- q ≤ 0: arctan q ≤ 0 and the domain witness forces hi > 0.
      rw [not_lt] at hqsign
      have harctan_np : Real.arctan q ≤ 0 := by
        have h0 := Real.arctan_mono hqsign
        simpa [Real.arctan_zero] using h0
      have hd := abs_le.mp hdom
      have hhi_nn : (0 : ℝ) ≤ ((hi : ℚ) : ℝ) := by
        have h1 : piHiQ / 2 - hi ≤ 1 := hd.2
        have h3 := three_lt_piHiQ
        have h2 : (0 : ℚ) ≤ hi := by linarith
        exact_mod_cast h2
      linarith
  · -- NEG-RECIP: q ≤ cHi < 0: arctan q = −π/2 − arctan (1/q)
    have hcneg : cHi < 0 := of_decide_eq_true hn1
    have hdom : |-(piLoQ / 2) - hi| ≤ 1 := of_decide_eq_true hn2
    have hbrQ : tanHiQ (-(piLoQ / 2) - hi) ≤ 1 / cHi := of_decide_eq_true hn3
    have hcnegR : ((cHi : ℚ) : ℝ) < 0 := by exact_mod_cast hcneg
    have hqneg : q < 0 := lt_of_le_of_lt hq hcnegR
    have hinv1 : 1 / ((cHi : ℚ) : ℝ) ≤ 1 / q :=
      one_div_le_one_div_of_neg_of_le hcnegR hq
    have hinv2 : ((tanHiQ (-(piLoQ / 2) - hi) : ℚ) : ℝ) ≤ ((1 / cHi : ℚ) : ℝ) := by
      exact_mod_cast hbrQ
    have htan := (tan_mem (-(piLoQ / 2) - hi) hdom).2
    have harc : (((-(piLoQ / 2) - hi : ℚ)) : ℝ) ≤ Real.arctan (1 / q) := by
      apply le_arctan_of_tan_le hdom
      have heq : ((1 / cHi : ℚ) : ℝ) = 1 / ((cHi : ℚ) : ℝ) := by push_cast; ring
      rw [heq] at hinv2
      linarith
    have hid := Real.arctan_inv_of_neg hqneg
    have hcastt : (((-(piLoQ / 2) - hi : ℚ)) : ℝ) =
        -(((piLoQ : ℚ) : ℝ) / 2) - ((hi : ℚ) : ℝ) := by push_cast; ring
    have hpiLo := piLoQ_lt_pi
    have hinv_eq : Real.arctan q⁻¹ = Real.arctan (1 / q) := by rw [one_div]
    rw [hcastt] at harc
    rw [hinv_eq] at hid
    linarith

end JackalIv.Transcend
