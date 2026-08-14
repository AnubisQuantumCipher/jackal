/-
JACKAL certified interval lane — EXACT (pad-free) interval ops and the two
remaining libm binary ops.

Engine correspondence (`jackal_calc.anb`, section "JACKAL CERTIFIED INTERVAL
ENGINE", git 8a71540) — each theorem here models one engine function:

* `iv_abs_encloses` (+ three branch lemmas) ↔ `iv_abs(a)` (line 2269):
    a.lo >= 0  →  return a                                  (nonneg branch)
    a.hi <= 0  →  return { lo := -a.hi, hi := -a.lo }        (nonpos branch)
    otherwise  →  return { lo := 0, hi := max(-a.lo, a.hi) } (mixed branch)
  IEEE-754 negation, `max`, and `abs` are EXACT float ops, so the engine
  applies no pad; neither do we.  `absLo`/`absHi` transcribe the three-case
  branch structure verbatim.

* `iv_min_encloses` ↔ `iv_min(a, b)` (line 2464):
    { lo := min(a.lo, b.lo), hi := min(a.hi, b.hi) } — float min is exact.
* `iv_max_encloses` ↔ `iv_max(a, b)` (line 2470): dual; float max is exact.

* `floor_mem` / `ceil_mem` / `round_mem` / `roundAway_mem` / `trunc_mem`
  ↔ the scalar rounding family `iv_floor_scalar` (line 2431) /
  `iv_ceil_scalar` (2436) / `iv_round_scalar` (2441) / `iv_trunc_scalar`
  (2446), applied endpoint-wise by the evaluator (lines 2537–2540):
    { lo := iv_*_scalar(a.lo), hi := iv_*_scalar(a.hi) }.
  Each scalar op is exact (the result is an integer-valued f64 and the
  `0.0 +` conversion is exact), so there is no pad; soundness is exactly
  MONOTONICITY of floor / ceil / round / trunc, mechanized here.

  MODEL HYPOTHESES for this family:
  - Saturation branch: for |v| >= 2^53 = 9007199254740992 each scalar op
    returns v itself.  That is sound because every binary64 of magnitude
    >= 2^53 is an integer — a FLOAT fact outside this real-number model.
    We record it as the hypothesis `IsInt v`: `isInt_fixed` shows every
    member of the family fixes such a v, so the saturated return coincides
    with the unsaturated formula and the `*_mem` monotone bounds apply.
  - Tie convention: Mathlib's `round` is round-half-UP (`⌊x + 1/2⌋`); the
    C `round` the engine calls rounds half AWAY FROM ZERO.  They differ
    only at negative half-integers.  `round_mem` covers Mathlib's
    convention; `roundAway_mem` covers the engine's actual convention via
    `roundAway`, defined to match C `round` exactly on the reals.

* `mig` / `mag` ↔ `iv_mig` (line 2278) / `iv_mag` (line 2276): defined in
  `JackalIv/Pow.lean` (shared with the `iv_pow_int` even branch) and
  imported here — mignitude (least absolute value over the interval; 0 if
  it straddles zero) and magnitude (greatest absolute value), computed by
  exact float abs/min/max in the engine — no rounding, no pad.

* `hypot_mem` + `iv_hypot_encloses` ↔ `iv_hypot(a, b)` (line 2451):
    iv_out(hypot(mig(a), mig(b)), hypot(mag(a), mag(b))).
  The two `hypot` calls are libm (`Approx δlib σ0` against the exact
  `sqrt (·² + ·²)` of the exact mig/mag values), padded by `iv_out`.

* `atan2R` + `iv_atan2_encloses_staged` + `iv_atan2_encloses`
  ↔ `iv_atan2(y, x)` (line 2457):
    guard `x.lo <= 0` → error; else `iv_atan(iv_div(y, x))`.
  On the guarded half-plane x > 0 the libm atan2 specification is
  atan2(y, x) = atan(y / x); we DEFINE `atan2R y x := Real.arctan (y / x)`
  for exactly that half-plane (the definition is stated only there — the
  engine refuses everything else) and prove the engine's two-stage
  composition encloses it: rounded corner quotients + `iv_out` pad
  (stage 1, `iv_div`), then libm arctan at the padded endpoints + `iv_out`
  pad (stage 2, `iv_atan`).  The staged variant takes the division-stage
  enclosure as a hypothesis (the shape of the Pow general lemma); the full
  variant composes `iv_div_encloses` and `iv_atan_encloses`.
-/
import JackalIv.Model
import JackalIv.Pad
import JackalIv.Arith
import JackalIv.Monotone
import JackalIv.Pow

namespace JackalIv

/-! ### Absolute value — models `iv_abs` (exact, no pad) -/

/-- Lower endpoint of the engine's three-case `iv_abs` (line 2269). -/
noncomputable def absLo (l u : ℝ) : ℝ :=
  if 0 ≤ l then l else if u ≤ 0 then -u else 0

/-- Upper endpoint of the engine's three-case `iv_abs` (line 2269). -/
noncomputable def absHi (l u : ℝ) : ℝ :=
  if 0 ≤ l then u else if u ≤ 0 then -l else max (-l) u

/-- `iv_abs`, nonneg branch (`a.lo >= 0` → return `a` unchanged). -/
theorem iv_abs_encloses_nonneg (l u x : ℝ) (hl : 0 ≤ l)
    (h1 : l ≤ x) (h2 : x ≤ u) : l ≤ |x| ∧ |x| ≤ u := by
  rw [abs_of_nonneg (le_trans hl h1)]
  exact ⟨h1, h2⟩

/-- `iv_abs`, nonpos branch (`a.hi <= 0` → `[-a.hi, -a.lo]`). -/
theorem iv_abs_encloses_nonpos (l u x : ℝ) (hu : u ≤ 0)
    (h1 : l ≤ x) (h2 : x ≤ u) : -u ≤ |x| ∧ |x| ≤ -l := by
  rw [abs_of_nonpos (le_trans h2 hu)]
  exact ⟨neg_le_neg h2, neg_le_neg h1⟩

/-- `iv_abs`, mixed branch (`[0, max(-a.lo, a.hi)]`); holds unconditionally,
so in particular on the engine's residual case `a.lo < 0 < a.hi`. -/
theorem iv_abs_encloses_mixed (l u x : ℝ) (h1 : l ≤ x) (h2 : x ≤ u) :
    0 ≤ |x| ∧ |x| ≤ max (-l) u := by
  refine ⟨abs_nonneg x, ?_⟩
  rcases le_total 0 x with hx | hx
  · rw [abs_of_nonneg hx]
    exact le_max_of_le_right h2
  · rw [abs_of_nonpos hx]
    exact le_max_of_le_left (neg_le_neg h1)

/-- `iv_abs`: `x ∈ [l, u]` → `|x| ∈ [absLo l u, absHi l u]`, the engine's
three-case interval — exact, no pad. -/
theorem iv_abs_encloses (l u x : ℝ) (h1 : l ≤ x) (h2 : x ≤ u) :
    absLo l u ≤ |x| ∧ |x| ≤ absHi l u := by
  unfold absLo absHi
  by_cases hl : 0 ≤ l
  · simp only [if_pos hl]
    exact iv_abs_encloses_nonneg l u x hl h1 h2
  · by_cases hu : u ≤ 0
    · simp only [if_neg hl, if_pos hu]
      exact iv_abs_encloses_nonpos l u x hu h1 h2
    · simp only [if_neg hl, if_neg hu]
      exact iv_abs_encloses_mixed l u x h1 h2

/-! ### Min / Max — model `iv_min` / `iv_max` (exact, no pad) -/

/-- `iv_min` (line 2464): float `min` is exact, so
`[min xl yl, min xu yu]` encloses `min x y` with no pad. -/
theorem iv_min_encloses (xl xu yl yu x y : ℝ)
    (hx1 : xl ≤ x) (hx2 : x ≤ xu) (hy1 : yl ≤ y) (hy2 : y ≤ yu) :
    min xl yl ≤ min x y ∧ min x y ≤ min xu yu :=
  ⟨min_le_min hx1 hy1, min_le_min hx2 hy2⟩

/-- `iv_max` (line 2470): float `max` is exact, so
`[max xl yl, max xu yu]` encloses `max x y` with no pad. -/
theorem iv_max_encloses (xl xu yl yu x y : ℝ)
    (hx1 : xl ≤ x) (hx2 : x ≤ xu) (hy1 : yl ≤ y) (hy2 : y ≤ yu) :
    max xl yl ≤ max x y ∧ max x y ≤ max xu yu :=
  ⟨max_le_max hx1 hy1, max_le_max hx2 hy2⟩

/-! ### Floor family — models `iv_floor_scalar` / `iv_ceil_scalar` /
`iv_round_scalar` / `iv_trunc_scalar`, applied endpoint-wise -/

/-- `v` is an integer-valued real.  MODEL HYPOTHESIS recording the float
fact that every binary64 with `|v| ≥ 2^53` is an integer; the engine's
saturation branch (`return v`) is covered by `isInt_fixed` below. -/
def IsInt (v : ℝ) : Prop := ∃ n : ℤ, (n : ℝ) = v

/-- Truncation toward zero, as computed by C `trunc` (engine
`iv_trunc_scalar`, line 2446). -/
noncomputable def truncR (x : ℝ) : ℝ :=
  if 0 ≤ x then (⌊x⌋ : ℝ) else (⌈x⌉ : ℝ)

/-- Rounding half AWAY FROM ZERO, as computed by C `round` (engine
`iv_round_scalar`, line 2441). -/
noncomputable def roundAway (x : ℝ) : ℝ :=
  if 0 ≤ x then (⌊x + 1 / 2⌋ : ℝ) else (⌈x - 1 / 2⌉ : ℝ)

/-- `iv_floor_scalar` endpoint-wise: `x ∈ [l, u]` →
`⌊x⌋ ∈ [⌊l⌋, ⌊u⌋]` (monotonicity of floor; exact, no pad). -/
theorem floor_mem (l u x : ℝ) (h1 : l ≤ x) (h2 : x ≤ u) :
    ((⌊l⌋ : ℤ) : ℝ) ≤ ((⌊x⌋ : ℤ) : ℝ) ∧ ((⌊x⌋ : ℤ) : ℝ) ≤ ((⌊u⌋ : ℤ) : ℝ) :=
  ⟨by exact_mod_cast Int.floor_mono h1, by exact_mod_cast Int.floor_mono h2⟩

/-- `iv_ceil_scalar` endpoint-wise: `x ∈ [l, u]` →
`⌈x⌉ ∈ [⌈l⌉, ⌈u⌉]` (monotonicity of ceil; exact, no pad). -/
theorem ceil_mem (l u x : ℝ) (h1 : l ≤ x) (h2 : x ≤ u) :
    ((⌈l⌉ : ℤ) : ℝ) ≤ ((⌈x⌉ : ℤ) : ℝ) ∧ ((⌈x⌉ : ℤ) : ℝ) ≤ ((⌈u⌉ : ℤ) : ℝ) :=
  ⟨by exact_mod_cast Int.ceil_mono h1, by exact_mod_cast Int.ceil_mono h2⟩

/-- Mathlib's `round` (half-up, `⌊x + 1/2⌋`) is monotone. -/
lemma round_monotone : Monotone (fun t : ℝ => round t) := by
  intro a b hab
  simp only [round_eq]
  exact Int.floor_mono (by linarith)

/-- `iv_round_scalar` endpoint-wise, Mathlib tie convention (half-up):
`x ∈ [l, u]` → `round x ∈ [round l, round u]`.  See the header for the
half-integer tie discrepancy with C `round`; `roundAway_mem` is the
engine-faithful statement. -/
theorem round_mem (l u x : ℝ) (h1 : l ≤ x) (h2 : x ≤ u) :
    ((round l : ℤ) : ℝ) ≤ ((round x : ℤ) : ℝ) ∧
    ((round x : ℤ) : ℝ) ≤ ((round u : ℤ) : ℝ) :=
  ⟨by exact_mod_cast round_monotone h1, by exact_mod_cast round_monotone h2⟩

/-- `truncR` (truncation toward zero) is monotone. -/
lemma truncR_mono : Monotone truncR := by
  intro a b hab
  unfold truncR
  by_cases ha : 0 ≤ a
  · have hb : 0 ≤ b := le_trans ha hab
    rw [if_pos ha, if_pos hb]
    exact_mod_cast Int.floor_mono hab
  · by_cases hb : 0 ≤ b
    · rw [if_neg ha, if_pos hb]
      have ha' : a < 0 := not_le.mp ha
      have h1 : (⌈a⌉ : ℤ) ≤ 0 := Int.ceil_le.mpr (by push_cast; linarith)
      have h2 : (0 : ℤ) ≤ ⌊b⌋ := Int.le_floor.mpr (by push_cast; linarith)
      have h1' : ((⌈a⌉ : ℤ) : ℝ) ≤ 0 := by exact_mod_cast h1
      have h2' : (0 : ℝ) ≤ ((⌊b⌋ : ℤ) : ℝ) := by exact_mod_cast h2
      linarith
    · rw [if_neg ha, if_neg hb]
      exact_mod_cast Int.ceil_mono hab

/-- `iv_trunc_scalar` endpoint-wise: `x ∈ [l, u]` →
`truncR x ∈ [truncR l, truncR u]` (exact, no pad). -/
theorem trunc_mem (l u x : ℝ) (h1 : l ≤ x) (h2 : x ≤ u) :
    truncR l ≤ truncR x ∧ truncR x ≤ truncR u :=
  ⟨truncR_mono h1, truncR_mono h2⟩

/-- `roundAway` (rounding half away from zero, the C `round` semantics) is
monotone. -/
lemma roundAway_mono : Monotone roundAway := by
  intro a b hab
  unfold roundAway
  by_cases ha : 0 ≤ a
  · have hb : 0 ≤ b := le_trans ha hab
    rw [if_pos ha, if_pos hb]
    have hab' : a + 1 / 2 ≤ b + 1 / 2 := by linarith
    exact_mod_cast Int.floor_mono hab'
  · by_cases hb : 0 ≤ b
    · rw [if_neg ha, if_pos hb]
      have ha' : a < 0 := not_le.mp ha
      have h1 : (⌈a - 1 / 2⌉ : ℤ) ≤ 0 := Int.ceil_le.mpr (by push_cast; linarith)
      have h2 : (0 : ℤ) ≤ ⌊b + 1 / 2⌋ := Int.le_floor.mpr (by push_cast; linarith)
      have h1' : ((⌈a - 1 / 2⌉ : ℤ) : ℝ) ≤ 0 := by exact_mod_cast h1
      have h2' : (0 : ℝ) ≤ ((⌊b + 1 / 2⌋ : ℤ) : ℝ) := by exact_mod_cast h2
      linarith
    · rw [if_neg ha, if_neg hb]
      have hab' : a - 1 / 2 ≤ b - 1 / 2 := by linarith
      exact_mod_cast Int.ceil_mono hab'

/-- `iv_round_scalar` endpoint-wise, ENGINE tie convention (C `round`,
half away from zero): `x ∈ [l, u]` → `roundAway x ∈ [roundAway l,
roundAway u]` (exact, no pad). -/
theorem roundAway_mem (l u x : ℝ) (h1 : l ≤ x) (h2 : x ≤ u) :
    roundAway l ≤ roundAway x ∧ roundAway x ≤ roundAway u :=
  ⟨roundAway_mono h1, roundAway_mono h2⟩

/-- Saturation-branch soundness: an integer-valued `v` is a fixed point of
floor, ceil, round (both tie conventions), and trunc.  Under the `IsInt`
model hypothesis (every binary64 with `|v| ≥ 2^53` is an integer), the
engine's `return v` saturation branch therefore coincides with the
unsaturated formula, and the `*_mem` monotone bounds above still apply. -/
theorem isInt_fixed (v : ℝ) (hv : IsInt v) :
    ((⌊v⌋ : ℤ) : ℝ) = v ∧ ((⌈v⌉ : ℤ) : ℝ) = v ∧
    ((round v : ℤ) : ℝ) = v ∧ truncR v = v ∧ roundAway v = v := by
  obtain ⟨n, rfl⟩ := hv
  have hhalf : ⌊(1 : ℝ) / 2⌋ = 0 :=
    Int.floor_eq_zero_iff.mpr (Set.mem_Ico.mpr ⟨by norm_num, by norm_num⟩)
  have hnhalf : ⌈-((1 : ℝ) / 2)⌉ = 0 := by
    rw [Int.ceil_neg, hhalf, neg_zero]
  refine ⟨by simp, by simp, by simp, ?_, ?_⟩
  · unfold truncR
    split_ifs <;> simp
  · unfold roundAway
    split_ifs with h
    · rw [Int.floor_intCast_add, hhalf]
      simp
    · rw [sub_eq_add_neg, Int.ceil_intCast_add, hnhalf]
      simp

/-! ### Hypot — models `iv_hypot`

`mig` / `mag` and their bracketing lemmas (`mig_nonneg`, `mig_le_abs`,
`abs_le_mag`) come from `JackalIv/Pow.lean`, which models the same engine
helpers `iv_mig` (line 2278) / `iv_mag` (line 2276). -/

private lemma sq_le_sq_of_nonneg {a b : ℝ} (ha : 0 ≤ a) (hab : a ≤ b) :
    a ^ 2 ≤ b ^ 2 := by
  have h := mul_self_le_mul_self ha hab
  calc a ^ 2 = a * a := by ring
    _ ≤ b * b := h
    _ = b ^ 2 := by ring

/-- Corner lemma for `iv_hypot`: the exact `sqrt (x² + y²)` lies between the
hypot of the mignitudes and the hypot of the magnitudes — the mathematical
fact behind the engine's `iv_out(hypot(mig,mig), hypot(mag,mag))`. -/
theorem hypot_mem (xl xu yl yu x y : ℝ)
    (hx1 : xl ≤ x) (hx2 : x ≤ xu) (hy1 : yl ≤ y) (hy2 : y ≤ yu) :
    Real.sqrt (mig xl xu ^ 2 + mig yl yu ^ 2) ≤ Real.sqrt (x ^ 2 + y ^ 2) ∧
    Real.sqrt (x ^ 2 + y ^ 2) ≤ Real.sqrt (mag xl xu ^ 2 + mag yl yu ^ 2) := by
  have hxlo : mig xl xu ^ 2 ≤ x ^ 2 := by
    have h := sq_le_sq_of_nonneg (mig_nonneg xl xu) (mig_le_abs hx1 hx2)
    calc mig xl xu ^ 2 ≤ |x| ^ 2 := h
      _ = x ^ 2 := sq_abs x
  have hylo : mig yl yu ^ 2 ≤ y ^ 2 := by
    have h := sq_le_sq_of_nonneg (mig_nonneg yl yu) (mig_le_abs hy1 hy2)
    calc mig yl yu ^ 2 ≤ |y| ^ 2 := h
      _ = y ^ 2 := sq_abs y
  have hxhi : x ^ 2 ≤ mag xl xu ^ 2 := by
    have h := sq_le_sq_of_nonneg (abs_nonneg x) (abs_le_mag hx1 hx2)
    calc x ^ 2 = |x| ^ 2 := (sq_abs x).symm
      _ ≤ mag xl xu ^ 2 := h
  have hyhi : y ^ 2 ≤ mag yl yu ^ 2 := by
    have h := sq_le_sq_of_nonneg (abs_nonneg y) (abs_le_mag hy1 hy2)
    calc y ^ 2 = |y| ^ 2 := (sq_abs y).symm
      _ ≤ mag yl yu ^ 2 := h
  exact ⟨Real.sqrt_le_sqrt (by linarith), Real.sqrt_le_sqrt (by linarith)⟩

/-- `iv_hypot` (line 2451): the two libm `hypot` evaluations at the exact
mig/mag arguments (mig/mag are computed by exact float ops), padded by
`iv_out`, enclose the exact `sqrt (x² + y²)`. -/
theorem iv_hypot_encloses (xl xu yl yu x y fl_lo fl_hi : ℝ)
    (hx1 : xl ≤ x) (hx2 : x ≤ xu) (hy1 : yl ≤ y) (hy2 : y ≤ yu)
    (hlo : Approx δlib σ0 fl_lo (Real.sqrt (mig xl xu ^ 2 + mig yl yu ^ 2)))
    (hhi : Approx δlib σ0 fl_hi (Real.sqrt (mag xl xu ^ 2 + mag yl yu ^ 2))) :
    padLo fl_lo ≤ Real.sqrt (x ^ 2 + y ^ 2) ∧
    Real.sqrt (x ^ 2 + y ^ 2) ≤ padHi fl_hi := by
  obtain ⟨hm1, hm2⟩ := hypot_mem xl xu yl yu x y hx1 hx2 hy1 hy2
  exact ⟨le_trans (libm_brackets _ _ hlo).1 hm1,
         le_trans hm2 (libm_brackets _ _ hhi).2⟩

/-! ### Atan2 (positive-x half-plane) — models `iv_atan2` -/

/-- The exact function the certified `iv_atan2` lane encloses.  On the
engine-guarded half-plane `x > 0` (the ONLY region the engine accepts —
line 2460 refuses `x.lo <= 0`), libm `atan2(y, x)` is specified as
`atan (y / x)`; this definition is stated for exactly that half-plane. -/
noncomputable def atan2R (y x : ℝ) : ℝ := Real.arctan (y / x)

/-- Staged form of `iv_atan2` (shape of the Pow general lemma): given the
division-stage enclosure `y/x ∈ [dlo, dhi]` and the libm arctan evaluations
at those endpoints, the final padded bracket encloses `atan2R y x`. -/
theorem iv_atan2_encloses_staged (y x dlo dhi fl_lo fl_hi : ℝ)
    (hd1 : dlo ≤ y / x) (hd2 : y / x ≤ dhi)
    (ha : Approx δlib σ0 fl_lo (Real.arctan dlo))
    (hb : Approx δlib σ0 fl_hi (Real.arctan dhi)) :
    padLo fl_lo ≤ atan2R y x ∧ atan2R y x ≤ padHi fl_hi := by
  unfold atan2R
  exact iv_atan_encloses dlo dhi (y / x) fl_lo fl_hi
    (Set.mem_Icc.mpr ⟨hd1, hd2⟩) (le_trans hd1 hd2) ha hb

/-- `iv_atan2` (line 2457), full composition `iv_atan(iv_div(y, x))` under
the engine guard `x.lo > 0`: rounded corner quotients `q̃ᵢ` + `iv_out` pad
(stage 1, `iv_div`), then libm arctan at the padded division endpoints +
`iv_out` pad (stage 2, `iv_atan`), enclose `atan2R y x = atan (y / x)`. -/
theorem iv_atan2_encloses (yl yu xl xu y x q1 q2 q3 q4 fl_lo fl_hi : ℝ)
    (hy1 : yl ≤ y) (hy2 : y ≤ yu) (hx1 : xl ≤ x) (hx2 : x ≤ xu)
    (hxpos : 0 < xl)
    (h1 : Approx δ0 σ0 q1 (yl / xl)) (h2 : Approx δ0 σ0 q2 (yl / xu))
    (h3 : Approx δ0 σ0 q3 (yu / xl)) (h4 : Approx δ0 σ0 q4 (yu / xu))
    (ha : Approx δlib σ0 fl_lo
      (Real.arctan (padLo (min (min q1 q2) (min q3 q4)))))
    (hb : Approx δlib σ0 fl_hi
      (Real.arctan (padHi (max (max q1 q2) (max q3 q4))))) :
    padLo fl_lo ≤ atan2R y x ∧ atan2R y x ≤ padHi fl_hi := by
  obtain ⟨hdl, hdh⟩ := iv_div_encloses yl yu xl xu y x q1 q2 q3 q4
    hy1 hy2 hx1 hx2 (Or.inl hxpos) h1 h2 h3 h4
  exact iv_atan2_encloses_staged y x _ _ fl_lo fl_hi hdl hdh ha hb

end JackalIv
