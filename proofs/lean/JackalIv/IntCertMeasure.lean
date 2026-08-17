/-
JackalIv/IntCertMeasure.lean — public certified integrate-bound-cert lane (v1.7).

Measurability of the canonical semantics `sem e` for EVERY expression, plus
bounded-integrability and constant-bound integral estimates.

Why this is needed (mission §6.2 range-only leaves): the engine's range form
accepts any `ieval`-evaluable integrand — including the discontinuous exact
ops `floor` / `ceil` / `round` / `trunc` — so leaf integrability cannot come
from continuity.  It comes from measurability (this file, by structural
induction over `Expr`) plus boundedness (exactly the certified enclosure).

The one genuinely new analytic ingredient is measurability of the junk-
totalized real power `fun p : ℝ × ℝ => p.1 ^ p.2` (`Real.rpow`), which this
Mathlib revision does not provide directly; it is derived here from the
`rpow_def_of_pos` / `rpow_def_of_neg` / `zero_rpow` case formulas.

No `sorry`, no axiom, no `native_decide`, no `@[implemented_by]`.
-/
import JackalIv.Syntax

namespace JackalIv.IntCert

open JackalIv MeasureTheory Set

/-! ### Measurability of the junk-totalized real power -/

/-- `Real.rpow`, uncurried, is measurable.  Piecewise decomposition along
`x = 0`, `0 < x`, `x < 0` with the three defining formulas. -/
theorem measurable_rpow_pair : Measurable fun p : ℝ × ℝ => p.1 ^ p.2 := by
  have hfun : (fun p : ℝ × ℝ => p.1 ^ p.2) = fun p : ℝ × ℝ =>
      if p.1 = 0 then (if p.2 = 0 then (1 : ℝ) else 0)
      else if 0 < p.1 then Real.exp (Real.log p.1 * p.2)
      else Real.exp (Real.log p.1 * p.2) * Real.cos (p.2 * Real.pi) := by
    funext p
    rcases lt_trichotomy p.1 0 with hneg | hzero | hpos
    · rw [if_neg (ne_of_lt hneg), if_neg (not_lt.mpr hneg.le),
        Real.rpow_def_of_neg hneg]
    · rw [hzero, if_pos rfl]
      by_cases hy : p.2 = 0
      · rw [if_pos hy, hy, Real.rpow_zero]
      · rw [if_neg hy, Real.zero_rpow hy]
    · rw [if_neg (ne_of_gt hpos), if_pos hpos, Real.rpow_def_of_pos hpos]
  rw [hfun]
  have hs0 : MeasurableSet {p : ℝ × ℝ | p.1 = 0} :=
    measurable_fst (measurableSet_singleton (0 : ℝ))
  have hs2 : MeasurableSet {p : ℝ × ℝ | p.2 = 0} :=
    measurable_snd (measurableSet_singleton (0 : ℝ))
  have hspos : MeasurableSet {p : ℝ × ℝ | 0 < p.1} :=
    measurable_fst measurableSet_Ioi
  have hexp : Measurable fun p : ℝ × ℝ => Real.exp (Real.log p.1 * p.2) :=
    Real.measurable_exp.comp ((Real.measurable_log.comp measurable_fst).mul
      measurable_snd)
  refine Measurable.ite hs0 (Measurable.ite hs2 measurable_const measurable_const)
    (Measurable.ite hspos hexp (hexp.mul ?_))
  exact Real.measurable_cos.comp (measurable_snd.mul_const Real.pi)

/-! ### Measurability of the engine's rounding scalars -/

/-- `truncR` is measurable (branchwise floor/ceil casts). -/
theorem measurable_truncR : Measurable truncR := by
  unfold truncR
  refine Measurable.ite measurableSet_Ici ?_ ?_
  · exact measurable_from_top.comp measurable_id.floor
  · exact measurable_from_top.comp measurable_id.ceil

/-- `roundAway` is measurable (branchwise shifted floor/ceil casts). -/
theorem measurable_roundAway : Measurable roundAway := by
  unfold roundAway
  refine Measurable.ite measurableSet_Ici ?_ ?_
  · exact measurable_from_top.comp (measurable_id.add_const (1 / 2 : ℝ)).floor
  · exact measurable_from_top.comp (measurable_id.sub_const (1 / 2 : ℝ)).ceil

/-! ### Measurability of the string-dispatched call semantics -/

/-- Every unary call semantics is measurable in its argument. -/
theorem measurable_call1Sem (name : String) : Measurable (call1Sem name) := by
  by_cases h1 : name = "sin"
  · have : (call1Sem name) = Real.sin := by
      funext v; simp [call1Sem, h1]
    rw [this]; exact Real.measurable_sin
  by_cases h2 : name = "cos"
  · have : (call1Sem name) = Real.cos := by
      funext v; simp [call1Sem, h2]
    rw [this]; exact Real.measurable_cos
  by_cases h3 : name = "tan"
  · have : (call1Sem name) = fun v => Real.sin v / Real.cos v := by
      funext v; simp [call1Sem, h1, h2, h3, Real.tan_eq_sin_div_cos]
    rw [this]; exact Real.measurable_sin.div Real.measurable_cos
  by_cases h4 : name = "asin"
  · have : (call1Sem name) = Real.arcsin := by
      funext v; simp [call1Sem, h4]
    rw [this]; exact Real.continuous_arcsin.measurable
  by_cases h5 : name = "acos"
  · have : (call1Sem name) = Real.arccos := by
      funext v; simp [call1Sem, h5]
    rw [this]; exact Real.continuous_arccos.measurable
  by_cases h6 : name = "atan"
  · have : (call1Sem name) = Real.arctan := by
      funext v; simp [call1Sem, h6]
    rw [this]; exact Real.measurable_arctan
  by_cases h7 : name = "sqrt"
  · have : (call1Sem name) = Real.sqrt := by
      funext v; simp [call1Sem, h7]
    rw [this]; exact Real.continuous_sqrt.measurable
  by_cases h8 : name = "ln"
  · have : (call1Sem name) = Real.log := by
      funext v; simp [call1Sem, h8]
    rw [this]; exact Real.measurable_log
  by_cases h9 : name = "log10"
  · have : (call1Sem name) = fun v => Real.log v / Real.log 10 := by
      funext v; simp [call1Sem, h1, h2, h3, h4, h5, h6, h7, h8, h9, Real.logb]
    rw [this]; exact Real.measurable_log.div_const _
  by_cases h10 : name = "log2"
  · have : (call1Sem name) = fun v => Real.log v / Real.log 2 := by
      funext v
      simp [call1Sem, h1, h2, h3, h4, h5, h6, h7, h8, h9, h10, Real.logb]
    rw [this]; exact Real.measurable_log.div_const _
  by_cases h11 : name = "exp"
  · have : (call1Sem name) = Real.exp := by
      funext v; simp [call1Sem, h11]
    rw [this]; exact Real.measurable_exp
  by_cases h12 : name = "abs"
  · have : (call1Sem name) = fun v : ℝ => |v| := by
      funext v
      simp [call1Sem, h1, h2, h3, h4, h5, h6, h7, h8, h9, h10, h11, h12]
    rw [this]; exact measurable_id.abs
  by_cases h13 : name = "floor"
  · have : (call1Sem name) = fun v : ℝ => ((⌊v⌋ : ℤ) : ℝ) := by
      funext v
      simp [call1Sem, h1, h2, h3, h4, h5, h6, h7, h8, h9, h10, h11, h12, h13]
    rw [this]; exact measurable_from_top.comp measurable_id.floor
  by_cases h14 : name = "ceil"
  · have : (call1Sem name) = fun v : ℝ => ((⌈v⌉ : ℤ) : ℝ) := by
      funext v
      simp [call1Sem, h1, h2, h3, h4, h5, h6, h7, h8, h9, h10, h11, h12, h13,
        h14]
    rw [this]; exact measurable_from_top.comp measurable_id.ceil
  by_cases h15 : name = "round"
  · have : (call1Sem name) = roundAway := by
      funext v
      simp [call1Sem, h1, h2, h3, h4, h5, h6, h7, h8, h9, h10, h11, h12, h13,
        h14, h15]
    rw [this]; exact measurable_roundAway
  by_cases h16 : name = "trunc"
  · have : (call1Sem name) = truncR := by
      funext v
      simp [call1Sem, h1, h2, h3, h4, h5, h6, h7, h8, h9, h10, h11, h12, h13,
        h14, h15, h16]
    rw [this]; exact measurable_truncR
  · have : (call1Sem name) = fun _ : ℝ => (0 : ℝ) := by
      funext v
      simp [call1Sem, h1, h2, h3, h4, h5, h6, h7, h8, h9, h10, h11, h12, h13,
        h14, h15, h16]
    rw [this]; exact measurable_const

/-- Every binary call semantics is measurable in its argument pair. -/
theorem measurable_call2Sem (name : String) :
    Measurable fun p : ℝ × ℝ => call2Sem name p.1 p.2 := by
  by_cases h1 : name = "hypot"
  · have : (fun p : ℝ × ℝ => call2Sem name p.1 p.2)
        = fun p : ℝ × ℝ => Real.sqrt (p.1 ^ 2 + p.2 ^ 2) := by
      funext p; simp [call2Sem, h1]
    rw [this]
    exact Real.continuous_sqrt.measurable.comp
      ((measurable_fst.pow_const 2).add (measurable_snd.pow_const 2))
  by_cases h2 : name = "atan2"
  · have : (fun p : ℝ × ℝ => call2Sem name p.1 p.2)
        = fun p : ℝ × ℝ => Real.arctan (p.1 / p.2) := by
      funext p; simp [call2Sem, h1, h2]
    rw [this]; exact Real.measurable_arctan.comp (measurable_fst.div measurable_snd)
  by_cases h3 : name = "min"
  · have : (fun p : ℝ × ℝ => call2Sem name p.1 p.2)
        = fun p : ℝ × ℝ => min p.1 p.2 := by
      funext p; simp [call2Sem, h1, h2, h3]
    rw [this]; exact measurable_fst.min measurable_snd
  by_cases h4 : name = "max"
  · have : (fun p : ℝ × ℝ => call2Sem name p.1 p.2)
        = fun p : ℝ × ℝ => max p.1 p.2 := by
      funext p; simp [call2Sem, h1, h2, h3, h4]
    rw [this]; exact measurable_fst.max measurable_snd
  by_cases h5 : name = "pow"
  · have : (fun p : ℝ × ℝ => call2Sem name p.1 p.2)
        = fun p : ℝ × ℝ => p.1 ^ p.2 := by
      funext p; simp [call2Sem, h1, h2, h3, h4, h5]
    rw [this]; exact measurable_rpow_pair
  · have : (fun p : ℝ × ℝ => call2Sem name p.1 p.2)
        = fun _ : ℝ × ℝ => (0 : ℝ) := by
      funext p; simp [call2Sem, h1, h2, h3, h4, h5]
    rw [this]; exact measurable_const

/-! ### Measurability of the canonical semantics -/

/-- **`sem e` is measurable for every canonical expression** — by structural
induction; the junk-totalized semantics is built from measurable pieces at
every constructor. -/
theorem sem_measurable (e : Expr) : Measurable (sem e) := by
  induction e with
  | num r t => exact measurable_const
  | var name =>
      by_cases h : name = "x"
      · have : sem (.var name) = fun x : ℝ => x := by funext x; simp [sem, h]
        rw [this]; exact measurable_id
      · have : sem (.var name) = fun _ : ℝ => (0 : ℝ) := by
          funext x; simp [sem, h]
        rw [this]; exact measurable_const
  | constant name => exact measurable_const
  | neg u ihu =>
      have : sem (.neg u) = fun x => -(sem u x) := by funext x; simp only [sem]
      rw [this]; exact ihu.neg
  | add l r ihl ihr =>
      have : sem (.add l r) = fun x => sem l x + sem r x := by
        funext x; simp only [sem]
      rw [this]; exact ihl.add ihr
  | sub l r ihl ihr =>
      have : sem (.sub l r) = fun x => sem l x - sem r x := by
        funext x; simp only [sem]
      rw [this]; exact ihl.sub ihr
  | mul l r ihl ihr =>
      have : sem (.mul l r) = fun x => sem l x * sem r x := by
        funext x; simp only [sem]
      rw [this]; exact ihl.mul ihr
  | div l r ihl ihr =>
      have : sem (.div l r) = fun x => sem l x / sem r x := by
        funext x; simp only [sem]
      rw [this]; exact ihl.div ihr
  | mod l r ihl ihr =>
      have : sem (.mod l r)
          = fun x => sem l x - sem r x * ((⌊sem l x / sem r x⌋ : ℤ) : ℝ) := by
        funext x; simp only [sem]
      rw [this]
      exact ihl.sub (ihr.mul (measurable_from_top.comp (ihl.div ihr).floor))
  | pow b e ihb ihe =>
      have : sem (.pow b e) = fun x => (sem b x) ^ (sem e x) := by
        funext x; simp only [sem]
      rw [this]
      exact measurable_rpow_pair.comp (ihb.prodMk ihe)
  | call1 name u ihu =>
      have : sem (.call1 name u) = fun x => call1Sem name (sem u x) := by
        funext x; simp only [sem]
      rw [this]; exact (measurable_call1Sem name).comp ihu
  | call2 name u v ihu ihv =>
      have : sem (.call2 name u v)
          = (fun p : ℝ × ℝ => call2Sem name p.1 p.2)
              ∘ (fun x => (sem u x, sem v x)) := by
        funext x; simp only [sem, Function.comp]
      rw [this]; exact (measurable_call2Sem name).comp (ihu.prodMk ihv)

/-! ### Bounded integrability and constant-bound integral estimates -/

/-- A measurable function bounded on `[a, b]` is interval-integrable there. -/
theorem intervalIntegrable_of_bounds {f : ℝ → ℝ} {a b lo hi : ℝ}
    (hm : Measurable f) (hab : a ≤ b)
    (henc : ∀ x ∈ Set.Icc a b, lo ≤ f x ∧ f x ≤ hi) :
    IntervalIntegrable f volume a b := by
  rw [intervalIntegrable_iff_integrableOn_Ioc_of_le hab]
  refine Integrable.mono' (g := fun _ => max |lo| |hi|)
    (integrableOn_const (hs := measure_Ioc_lt_top.ne))
    hm.aestronglyMeasurable.restrict ?_
  rw [ae_restrict_iff' measurableSet_Ioc]
  refine ae_of_all _ (fun x hx => ?_)
  have hx' := henc x (Set.Ioc_subset_Icc_self hx)
  rw [Real.norm_eq_abs]
  exact abs_le_max_abs_abs hx'.1 hx'.2

/-- The range-form estimate: an enclosure `[lo, hi]` of `f` over `[a, b]`
bounds the integral by `(b−a)·lo` and `(b−a)·hi`, with integrability. -/
theorem integral_bounds_of_encloses {f : ℝ → ℝ} {a b lo hi : ℝ}
    (hm : Measurable f) (hab : a ≤ b)
    (henc : ∀ x ∈ Set.Icc a b, lo ≤ f x ∧ f x ≤ hi) :
    IntervalIntegrable f volume a b ∧
    (b - a) * lo ≤ (∫ x in a..b, f x) ∧ (∫ x in a..b, f x) ≤ (b - a) * hi := by
  have hint := intervalIntegrable_of_bounds hm hab henc
  refine ⟨hint, ?_, ?_⟩
  · have h := intervalIntegral.integral_mono_on (μ := volume) hab
      intervalIntegrable_const hint (fun x hx => (henc x hx).1)
    simpa [intervalIntegral.integral_const, smul_eq_mul] using h
  · have h := intervalIntegral.integral_mono_on (μ := volume) hab
      hint intervalIntegrable_const (fun x hx => (henc x hx).2)
    simpa [intervalIntegral.integral_const, smul_eq_mul] using h

end JackalIv.IntCert
