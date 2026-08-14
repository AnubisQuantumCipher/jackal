/-
Containment lemmas for the JACKAL interval POWER ops.

Engine correspondence (`jackal_calc.anb`, section "JACKAL CERTIFIED INTERVAL
ENGINE", git 8a71540) — each theorem here models one engine function:

* `mig` / `mag` ↔ `iv_mig` (line 2278) / `iv_mag` (line 2276):
  interval mignitude/magnitude.  Float `abs`/`min`/`max` are EXACT in
  IEEE-754, so these carry no rounding and are modeled as exact reals.
* `pow_even_mem` + `iv_pow_int_even_encloses` ↔ `iv_pow_int(a, n)`, even
  branch (lines 2293–2294): `core = iv_out(pow(iv_mig(a), m), pow(iv_mag(a), m))`.
  Each endpoint is ONE libm `pow` call, modeled as `Approx δlib σ0` against
  the exact powers `mig^n` / `mag^n`; `iv_out` is `padLo`/`padHi`.
* `pow_odd_mem` + `iv_pow_int_odd_encloses` ↔ `iv_pow_int(a, n)`, odd
  branch (lines 2295–2296): `core = iv_out(pow(a.lo, m), pow(a.hi, m))` —
  odd integer powers are monotone, so the endpoint rule is sound.
  Together the even/odd pair covers `iv_pow_int` for every n ≥ 1, exactly
  mirroring the engine's `if m % 2 == 0` split (line 2293).
* `iv_pow_neg_encloses` (+ `iv_pow_neg_encloses_zpow`) ↔ `iv_pow_int(a, n)`
  for n ≤ -1 (lines 2290, 2299–2301): the engine first computes the
  positive-power core `[cl, cu]` (the padded n ≥ 1 lane above, so
  `cl ≤ x^m ≤ cu` is exactly what `iv_pow_int_even/odd_encloses` conclude),
  then returns `iv_div(iv_exact(1.0), core)`.  `iv_exact(1.0)` is the EXACT
  point interval [1,1] (line 2210, no pad); the four division corners are
  IEEE basic ops (`Approx δ0 σ0`) guarded zero-free by `iv_div` (line 2261)
  — so the negative lane is literally `iv_div_encloses`/`div_mem_corners`
  from Arith.lean instantiated at a = [1,1], b = core.
* `rpow_general_encloses` ↔ `iv_pow_general(b, e)` (lines 2306–2313):
  guarded by `b.lo <= 0 → error` (line 2309), then
  `iv_exp(iv_mul(e, iv_ln(b)))`.  For a positive base the real power is
  `x^y = exp(y · ln x)` (`Real.rpow_def_of_pos`), so composing the three
  already-mechanized stage enclosures — iv_ln (`iv_log_encloses`), iv_mul
  (`iv_mul_encloses`), iv_exp (`iv_exp_encloses`), taken here as hypotheses
  in exactly the shape those lemmas produce — encloses `x^y` end-to-end.
-/
import JackalIv.Model
import JackalIv.Pad
import JackalIv.Arith

namespace JackalIv

/-! ### Mignitude and magnitude — model `iv_mig` / `iv_mag` (exact) -/

/-- `iv_mig` (jackal_calc.anb line 2278): the smallest absolute value
attained on `[xl, xu]` — 0 if the interval straddles zero, else
`min |xl| |xu|`.  Float `abs`/`min` are exact, so no rounding model. -/
noncomputable def mig (xl xu : ℝ) : ℝ :=
  if xl ≤ 0 ∧ 0 ≤ xu then 0 else min |xl| |xu|

/-- `iv_mag` (jackal_calc.anb line 2276): the largest absolute value
attained on `[xl, xu]`.  Float `abs`/`max` are exact. -/
noncomputable def mag (xl xu : ℝ) : ℝ := max |xl| |xu|

lemma mig_nonneg (xl xu : ℝ) : 0 ≤ mig xl xu := by
  unfold mig
  split_ifs with h
  · exact le_refl 0
  · exact le_min (abs_nonneg xl) (abs_nonneg xu)

lemma mag_nonneg (xl xu : ℝ) : 0 ≤ mag xl xu :=
  le_trans (abs_nonneg xl) (le_max_left _ _)

/-- The mignitude really is a lower bound for `|x|` across the interval:
the engine's zero-straddling test (`a.lo <= 0 && a.hi >= 0`) is exactly the
case split needed. -/
lemma mig_le_abs {xl xu x : ℝ} (hx1 : xl ≤ x) (hx2 : x ≤ xu) :
    mig xl xu ≤ |x| := by
  unfold mig
  split_ifs with h
  · exact abs_nonneg x
  · rcases not_and_or.mp h with h1 | h2
    · -- ¬ xl ≤ 0, i.e. 0 < xl: the interval is strictly positive.
      have hxl : 0 < xl := not_le.mp h1
      have hx0 : 0 < x := lt_of_lt_of_le hxl hx1
      calc min |xl| |xu| ≤ |xl| := min_le_left _ _
        _ = xl := abs_of_pos hxl
        _ ≤ x := hx1
        _ = |x| := (abs_of_pos hx0).symm
    · -- ¬ 0 ≤ xu, i.e. xu < 0: the interval is strictly negative.
      have hxu : xu < 0 := not_le.mp h2
      have hx0 : x < 0 := lt_of_le_of_lt hx2 hxu
      calc min |xl| |xu| ≤ |xu| := min_le_right _ _
        _ = -xu := abs_of_neg hxu
        _ ≤ -x := neg_le_neg hx2
        _ = |x| := (abs_of_neg hx0).symm

/-- The magnitude really is an upper bound for `|x|` across the interval. -/
lemma abs_le_mag {xl xu x : ℝ} (hx1 : xl ≤ x) (hx2 : x ≤ xu) :
    |x| ≤ mag xl xu := by
  unfold mag
  rcases le_total 0 x with hx0 | hx0
  · calc |x| = x := abs_of_nonneg hx0
      _ ≤ xu := hx2
      _ ≤ |xu| := le_abs_self xu
      _ ≤ max |xl| |xu| := le_max_right _ _
  · calc |x| = -x := abs_of_nonpos hx0
      _ ≤ -xl := neg_le_neg hx1
      _ ≤ |xl| := neg_le_abs xl
      _ ≤ max |xl| |xu| := le_max_left _ _

/-! ### Even powers — model the `m % 2 == 0` branch of `iv_pow_int` -/

/-- Corner lemma for even powers: for even n (the engine reaches this branch
only with n ≥ 2), `x^n` lies between `mig^n` and `mag^n` — the mathematical
fact behind `iv_out(pow(iv_mig(a), m), pow(iv_mag(a), m))`.  The dependency-
aware point: `x·x` over `[-1,2]` gives `[0,4]`, not the naive `[-2,4]`. -/
theorem pow_even_mem (n : ℕ) (hn : Even n) (_hn2 : 2 ≤ n) (xl xu x : ℝ)
    (hx1 : xl ≤ x) (hx2 : x ≤ xu) :
    mig xl xu ^ n ≤ x ^ n ∧ x ^ n ≤ mag xl xu ^ n := by
  have h1 : mig xl xu ≤ |x| := mig_le_abs hx1 hx2
  have h2 : |x| ≤ mag xl xu := abs_le_mag hx1 hx2
  have habs : |x| ^ n = x ^ n := hn.pow_abs x
  constructor
  · calc mig xl xu ^ n ≤ |x| ^ n := pow_le_pow_left₀ (mig_nonneg xl xu) h1 n
      _ = x ^ n := habs
  · calc x ^ n = |x| ^ n := habs.symm
      _ ≤ mag xl xu ^ n := pow_le_pow_left₀ (abs_nonneg x) h2 n

/-! ### Odd powers — model the odd branch of `iv_pow_int` -/

/-- Odd integer powers are monotone on all of ℝ (three sign cases). -/
lemma odd_pow_mono {n : ℕ} (hn : Odd n) {a b : ℝ} (hab : a ≤ b) :
    a ^ n ≤ b ^ n := by
  rcases le_total 0 a with ha | ha
  · exact pow_le_pow_left₀ ha hab n
  · rcases le_total b 0 with hb | hb
    · have h1 : (0 : ℝ) ≤ -b := neg_nonneg.mpr hb
      have h2 : -b ≤ -a := neg_le_neg hab
      have h3 : (-b) ^ n ≤ (-a) ^ n := pow_le_pow_left₀ h1 h2 n
      rw [hn.neg_pow, hn.neg_pow] at h3
      linarith
    · have h1 : a ^ n ≤ 0 := hn.pow_nonpos ha
      have h2 : (0 : ℝ) ≤ b ^ n := pow_nonneg hb n
      linarith

/-- Corner lemma for odd powers: for odd n ≥ 1, `x^n ∈ [xl^n, xu^n]` — the
fact behind `iv_out(pow(a.lo, m), pow(a.hi, m))`. -/
theorem pow_odd_mem (n : ℕ) (hn : Odd n) (xl xu x : ℝ)
    (hx1 : xl ≤ x) (hx2 : x ≤ xu) :
    xl ^ n ≤ x ^ n ∧ x ^ n ≤ xu ^ n :=
  ⟨odd_pow_mono hn hx1, odd_pow_mono hn hx2⟩

/-! ### `iv_pow_int`, n ≥ 1 — padded endpoint computations -/

/-- `iv_pow_int` even branch (n ≥ 2 even): the two libm `pow` evaluations
`fl_lo ≈ mig^n`, `fl_hi ≈ mag^n` (each `Approx δlib σ0`), padded by
`iv_out`, enclose the exact power `x^n`. -/
theorem iv_pow_int_even_encloses (n : ℕ) (hn : Even n) (hn2 : 2 ≤ n)
    (xl xu x fl_lo fl_hi : ℝ)
    (hx1 : xl ≤ x) (hx2 : x ≤ xu)
    (hlo : Approx δlib σ0 fl_lo (mig xl xu ^ n))
    (hhi : Approx δlib σ0 fl_hi (mag xl xu ^ n)) :
    padLo fl_lo ≤ x ^ n ∧ x ^ n ≤ padHi fl_hi := by
  obtain ⟨hmemLo, hmemHi⟩ := pow_even_mem n hn hn2 xl xu x hx1 hx2
  exact ⟨le_trans (libm_brackets fl_lo _ hlo).1 hmemLo,
         le_trans hmemHi (libm_brackets fl_hi _ hhi).2⟩

/-- `iv_pow_int` odd branch (n ≥ 1 odd): the two libm `pow` evaluations
`fl_lo ≈ xl^n`, `fl_hi ≈ xu^n` (each `Approx δlib σ0`), padded by `iv_out`,
enclose the exact power `x^n`. -/
theorem iv_pow_int_odd_encloses (n : ℕ) (hn : Odd n)
    (xl xu x fl_lo fl_hi : ℝ)
    (hx1 : xl ≤ x) (hx2 : x ≤ xu)
    (hlo : Approx δlib σ0 fl_lo (xl ^ n))
    (hhi : Approx δlib σ0 fl_hi (xu ^ n)) :
    padLo fl_lo ≤ x ^ n ∧ x ^ n ≤ padHi fl_hi := by
  obtain ⟨hmemLo, hmemHi⟩ := pow_odd_mem n hn xl xu x hx1 hx2
  exact ⟨le_trans (libm_brackets fl_lo _ hlo).1 hmemLo,
         le_trans hmemHi (libm_brackets fl_hi _ hhi).2⟩

/-! ### `iv_pow_int`, n ≤ -1 — `iv_div([1,1], core)` -/

/-- `iv_pow_int` negative branch: given the positive-power core enclosure
`cl ≤ x^m ≤ cu` (exactly what the n ≥ 1 lane concludes with
`cl = padLo fl_lo`, `cu = padHi fl_hi`) and the engine's zero-free guard on
the core (`iv_div` line 2261, as `0 < cl ∨ cu < 0`), the four rounded
division corners of `iv_div(iv_exact(1.0), core)` — `q̃ᵢ ≈ 1/cl, 1/cu`
(basic-op `Approx δ0 σ0`; `iv_exact(1.0)` is exact `[1,1]`) — min/max'd and
padded by `iv_out`, enclose the exact reciprocal power `1 / x^m`.
Proved by instantiating `iv_div_encloses` (hence `div_mem_corners`) at
a = [1,1], b = [cl, cu]. -/
theorem iv_pow_neg_encloses (m : ℕ) (x cl cu q1 q2 q3 q4 : ℝ)
    (hcl : cl ≤ x ^ m) (hcu : x ^ m ≤ cu)
    (hden : 0 < cl ∨ cu < 0)
    (h1 : Approx δ0 σ0 q1 (1 / cl)) (h2 : Approx δ0 σ0 q2 (1 / cu))
    (h3 : Approx δ0 σ0 q3 (1 / cl)) (h4 : Approx δ0 σ0 q4 (1 / cu)) :
    padLo (min (min q1 q2) (min q3 q4)) ≤ 1 / x ^ m ∧
    1 / x ^ m ≤ padHi (max (max q1 q2) (max q3 q4)) :=
  iv_div_encloses 1 1 cl cu 1 (x ^ m) q1 q2 q3 q4
    le_rfl le_rfl hcl hcu hden h1 h2 h3 h4

/-- The same conclusion phrased against the true integer power `x^(-m)`
(`zpow`): for x ≠ 0 this is the engine's `x^n` with n = -m; Lean's junk
value at x = 0 (`0⁻¹ = 0`) agrees with `1 / 0^m`, so no side condition is
needed. -/
theorem iv_pow_neg_encloses_zpow (m : ℕ) (x cl cu q1 q2 q3 q4 : ℝ)
    (hcl : cl ≤ x ^ m) (hcu : x ^ m ≤ cu)
    (hden : 0 < cl ∨ cu < 0)
    (h1 : Approx δ0 σ0 q1 (1 / cl)) (h2 : Approx δ0 σ0 q2 (1 / cu))
    (h3 : Approx δ0 σ0 q3 (1 / cl)) (h4 : Approx δ0 σ0 q4 (1 / cu)) :
    padLo (min (min q1 q2) (min q3 q4)) ≤ x ^ (-(m : ℤ)) ∧
    x ^ (-(m : ℤ)) ≤ padHi (max (max q1 q2) (max q3 q4)) := by
  have hzp : x ^ (-(m : ℤ)) = 1 / x ^ m := by
    rw [zpow_neg, zpow_natCast, one_div]
  rw [hzp]
  exact iv_pow_neg_encloses m x cl cu q1 q2 q3 q4 hcl hcu hden h1 h2 h3 h4

/-! ### `iv_pow_general` — exp(e · ln b) composition -/

/-- `iv_pow_general` (jackal_calc.anb lines 2306–2313): under the engine's
positive-base guard (`b.lo <= 0 → error`, so `0 < xl`), the real power is
`x^y = exp(y · ln x)` (`Real.rpow_def_of_pos`).  The three hypotheses are
the stage enclosures the engine chains — `iv_ln(b)` giving `[Ll, Lu]`
(shape of `iv_log_encloses`), `iv_mul(e, lnb)` giving `[Ml, Mu]` (shape of
`iv_mul_encloses`), `iv_exp(prod)` giving `[El, Eu]` (shape of
`iv_exp_encloses`) — and composing them encloses `x^y` for every
`x ∈ [xl, xu]`, `y ∈ [yl, yu]`. -/
theorem rpow_general_encloses (xl xu yl yu Ll Lu Ml Mu El Eu : ℝ)
    (hxl : 0 < xl)
    (hln : ∀ t, xl ≤ t → t ≤ xu → Ll ≤ Real.log t ∧ Real.log t ≤ Lu)
    (hmul : ∀ u v, yl ≤ u → u ≤ yu → Ll ≤ v → v ≤ Lu →
      Ml ≤ u * v ∧ u * v ≤ Mu)
    (hexp : ∀ t, Ml ≤ t → t ≤ Mu → El ≤ Real.exp t ∧ Real.exp t ≤ Eu)
    (x y : ℝ) (hx1 : xl ≤ x) (hx2 : x ≤ xu) (hy1 : yl ≤ y) (hy2 : y ≤ yu) :
    El ≤ x ^ y ∧ x ^ y ≤ Eu := by
  have hx0 : 0 < x := lt_of_lt_of_le hxl hx1
  have hlog := hln x hx1 hx2
  have hprod := hmul y (Real.log x) hy1 hy2 hlog.1 hlog.2
  have hE := hexp (y * Real.log x) hprod.1 hprod.2
  rw [Real.rpow_def_of_pos hx0, mul_comm (Real.log x) y]
  exact hE

end JackalIv
