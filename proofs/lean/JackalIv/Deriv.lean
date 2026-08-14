/-
JACKAL certified integration — formula evaluability certifies
differentiability.

This file mechanizes the C^k justification the bound lane relies on: the
engine's `bound_step` (jackal_calc.anb, section "JACKAL CERTIFIED
INTEGRATION", git 8a71540) accepts the Taylor-2 midpoint form only after the
symbolic formulas f, f', f'' ALL interval-evaluate (`ieval` success) over the
closed subinterval (lines 2643–2646), and the Taylor-4 form only after the
chain f..f'''' succeeds (2650–2654); the engine's stated argument
(lines 2564–2567) is

    "each elementary rule holds on the open domain where its own formula is
     defined, so success certifies f in C^2 there".

Here that argument becomes a theorem about the MODEL: a symbolic
differentiator `D` mirroring the engine's `deriv()` (lines 1662–1813), a
pointwise definedness predicate `DefinedOn` mirroring the `ieval` domain
guards (lines 2491–2558), and proofs that evaluability of the chain
e, D e, … certifies `HasDerivAt` / C¹ / C² / C⁴ — exactly the hypotheses
`taylor2_midpoint_enclosure` / `taylor4_midpoint_enclosure` (Taylor.lean)
consume.  `taylor2_enclosure_of_evaluable` / `taylor4_enclosure_of_evaluable`
compose the two ends.

Engine correspondence, constructor by constructor:

* `Expr` / `sem` — the smooth core of the expression AST (the subset
  `ast_smooth_ok`, engine lines 1628–1647, admits to the Taylor lanes):
  num/const literals (`lit` covers both), the variable x (`var`),
  neg/add/sub/mul/div, integer powers (`powInt`, the `iv_pow_int` lane of
  `pow`, lines 2285–2303 and 2550–2556), and the unary calls
  sqrt/exp/ln/sin/cos/atan.  NOTE: `Embed.lean` does not exist in this wave,
  so `Expr`/`sem`/`DefinedOn` are minimal local copies under the `Deriv`
  namespace, to be reconciled when the deep embedding lands.

* `D` ↔ `deriv()`, rule for rule:
    - num/const → 0, x → 1                        (engine lines 1670–1674)
    - neg, add, sub                               (1675–1683)
    - mul → du·v + u·dv   (product rule)          (1684–1692)
    - div → (du·v − u·dv)/v²  (quotient rule)     (1693–1703)
    - powInt n → (n·u^(n−1))·du  (power rule)     (1705–1716, integer c)
    - sin  → cos(u)·du                            (1759–1762)
    - cos  → −(sin(u)·du)                         (1763–1767)
    - atan → du/(1+u²)                            (1781–1785)
    - sqrt → du/(2·√u)                            (1786–1790)
    - ln   → du/u                                 (1797)
    - exp  → exp(u)·du                            (1806–1809)
  Deliberately OUT of scope this wave (`deriv()` has rules, not modeled
  here): tan, asin, acos, cbrt, log10, log2, hypot, atan2, and the
  non-integer / general-exponent power lanes (constant real c by the same
  power rule; x^y via exp(y·ln x), lines 1717–1724).  Recorded as residual
  rather than weakening any statement below.

* `DefinedOn` ↔ the pointwise shadow of the `ieval` guards: div refuses a
  denominator interval containing zero (`iv_div`, line 2261) — pointwise
  `sem e₂ x ≠ 0`; sqrt refuses lo < 0 (`iv_sqrt`, 2317) — pointwise
  `0 ≤ sem e x`; ln refuses lo ≤ 0 (`iv_ln`, 2337) — pointwise
  `0 < sem e x`; x^n for n < 0 routes through `iv_div` on the core
  (`iv_pow_int`, 2299–2301) — pointwise `sem e x ≠ 0`; exp/sin/cos/atan are
  total (2330, 2370, 2387, 2426).  `ieval` success over a subinterval
  implies these pointwise conditions at every point of it (the interval
  guards are strictly stronger, since outward pads only widen), so
  `∀ x ∈ Icc a b, DefinedOn … x` is exactly what a successful engine
  evaluation furnishes to the theorems below.

* `deriv_correct` / `deriv_correct_on` — the sqrt case is why the ENGINE
  needs the f' formula to evaluate, not just f: `DefinedOn (sqrt u)` alone
  gives only 0 ≤ u (and √ is not differentiable at u = 0), but
  `DefinedOn (D (sqrt u))` carries the guard 2·√u ≠ 0 of the emitted
  quotient du/(2·√u), which forces u > 0 — the engine's f' formula refuses
  at u = 0 through exactly that division guard.  No openness hypothesis is
  needed: Mathlib's `HasDerivAt` composition lemmas are genuinely pointwise,
  so the engine's "open domain" phrasing is subsumed.

* `taylor2_hypotheses_of_evaluable` / `taylor4_hypotheses_of_evaluable` —
  produce literally the `HasDerivAt` hypothesis tuples that
  `taylor2_midpoint_enclosure` / `taylor4_midpoint_enclosure` take,
  mirroring `bound_step`'s gating.  The engine builds the chain f1..f4 as
  `simplify_bound(deriv(...))` (lines 3008–3013); `simplify_bound`'s
  documented contract (1565–1581) is that every rule it applies is a
  structural identity on all of ℝ preserving definedness in both
  directions, so the unsimplified `D` chain modeled here evaluates iff the
  engine's simplified chain does.
-/
import JackalIv.Model
import JackalIv.Pad
import JackalIv.Taylor

namespace JackalIv
namespace Deriv

open Set
open scoped ContDiff

/-- Smooth-core expression AST — the subset of the engine grammar that
`ast_smooth_ok` admits to the Taylor lanes and this wave models.  `lit`
covers both "num" and "const" engine nodes (a named constant is just a real
literal to the semantics). -/
inductive Expr : Type
  | var    : Expr
  | lit    : ℝ → Expr
  | neg    : Expr → Expr
  | add    : Expr → Expr → Expr
  | sub    : Expr → Expr → Expr
  | mul    : Expr → Expr → Expr
  | div    : Expr → Expr → Expr
  | powInt : Expr → ℤ → Expr
  | sqrt   : Expr → Expr
  | exp    : Expr → Expr
  | log    : Expr → Expr
  | sin    : Expr → Expr
  | cos    : Expr → Expr
  | atan   : Expr → Expr

/-- Real semantics of the smooth core (the exact function the engine's
certified enclosures are ABOUT — total, with Lean's junk values exactly
where `DefinedOn` is false). -/
noncomputable def sem : Expr → ℝ → ℝ
  | .var, x => x
  | .lit c, _ => c
  | .neg e, x => -(sem e x)
  | .add e₁ e₂, x => sem e₁ x + sem e₂ x
  | .sub e₁ e₂, x => sem e₁ x - sem e₂ x
  | .mul e₁ e₂, x => sem e₁ x * sem e₂ x
  | .div e₁ e₂, x => sem e₁ x / sem e₂ x
  | .powInt e n, x => sem e x ^ n
  | .sqrt e, x => Real.sqrt (sem e x)
  | .exp e, x => Real.exp (sem e x)
  | .log e, x => Real.log (sem e x)
  | .sin e, x => Real.sin (sem e x)
  | .cos e, x => Real.cos (sem e x)
  | .atan e, x => Real.arctan (sem e x)

/-- Pointwise definedness — the shadow of the `ieval` refusal guards:
`iv_div` (zero-free denominator), `iv_sqrt` (nonnegative argument),
`iv_ln` (positive argument), `iv_pow_int` with negative exponent
(nonzero base, via its `iv_div(1, core)` lane). -/
def DefinedOn : Expr → ℝ → Prop
  | .var, _ => True
  | .lit _, _ => True
  | .neg e, x => DefinedOn e x
  | .add e₁ e₂, x => DefinedOn e₁ x ∧ DefinedOn e₂ x
  | .sub e₁ e₂, x => DefinedOn e₁ x ∧ DefinedOn e₂ x
  | .mul e₁ e₂, x => DefinedOn e₁ x ∧ DefinedOn e₂ x
  | .div e₁ e₂, x => DefinedOn e₁ x ∧ DefinedOn e₂ x ∧ sem e₂ x ≠ 0
  | .powInt e n, x => DefinedOn e x ∧ (0 ≤ n ∨ sem e x ≠ 0)
  | .sqrt e, x => DefinedOn e x ∧ 0 ≤ sem e x
  | .exp e, x => DefinedOn e x
  | .log e, x => DefinedOn e x ∧ 0 < sem e x
  | .sin e, x => DefinedOn e x
  | .cos e, x => DefinedOn e x
  | .atan e, x => DefinedOn e x

/-- The symbolic differentiator — rule for rule the engine's `deriv()`
(smooth core).  In particular the sqrt rule emits `du / (2·√u)`, whose
`DefinedOn` carries the `2·√u ≠ 0` division guard: evaluability of `D e`
refuses at `u = 0` exactly as the engine's f' formula does. -/
noncomputable def D : Expr → Expr
  | .var => .lit 1
  | .lit _ => .lit 0
  | .neg e => .neg (D e)
  | .add e₁ e₂ => .add (D e₁) (D e₂)
  | .sub e₁ e₂ => .sub (D e₁) (D e₂)
  | .mul e₁ e₂ => .add (.mul (D e₁) e₂) (.mul e₁ (D e₂))
  | .div e₁ e₂ =>
      .div (.sub (.mul (D e₁) e₂) (.mul e₁ (D e₂))) (.powInt e₂ 2)
  | .powInt e n => .mul (.mul (.lit (n : ℝ)) (.powInt e (n - 1))) (D e)
  | .sqrt e => .div (D e) (.mul (.lit 2) (.sqrt e))
  | .exp e => .mul (.exp e) (D e)
  | .log e => .div (D e) e
  | .sin e => .mul (.cos e) (D e)
  | .cos e => .neg (.mul (.sin e) (D e))
  | .atan e => .div (D e) (.add (.lit 1) (.powInt e 2))

/-! ### Small plumbing -/

private lemma hasDerivAt_congr_val {g : ℝ → ℝ} {v w x : ℝ}
    (h : HasDerivAt g v x) (hvw : v = w) : HasDerivAt g w x := hvw ▸ h

private lemma zpow_two_eq (a : ℝ) : a ^ (2 : ℤ) = a ^ (2 : ℕ) := by
  rw [zpow_two, pow_two]

/-! ### Main theorem 1 — evaluability of `e` and `D e` certifies the
derivative -/

/-- **Symbolic differentiation is correct on the evaluable domain**: at any
point where both the formula `e` and its emitted derivative formula `D e`
are defined (= where `ieval` of both succeeds, in the engine), `sem e` is
differentiable with derivative exactly `sem (D e)`.  Structural induction;
every domain side condition Mathlib needs is supplied by a `DefinedOn`
guard, which is the mechanized content of the engine comment "each
elementary rule holds on the open domain where its own formula is
defined". -/
theorem deriv_correct (e : Expr) (x : ℝ)
    (he : DefinedOn e x) (hD : DefinedOn (D e) x) :
    HasDerivAt (sem e) (sem (D e) x) x := by
  induction e with
  | var =>
      exact hasDerivAt_id x
  | lit c =>
      exact hasDerivAt_const x c
  | neg e ih =>
      simp only [DefinedOn] at he
      simp only [D, DefinedOn] at hD
      exact (ih he hD).neg
  | add e₁ e₂ ih₁ ih₂ =>
      simp only [DefinedOn] at he
      simp only [D, DefinedOn] at hD
      exact (ih₁ he.1 hD.1).add (ih₂ he.2 hD.2)
  | sub e₁ e₂ ih₁ ih₂ =>
      simp only [DefinedOn] at he
      simp only [D, DefinedOn] at hD
      exact (ih₁ he.1 hD.1).sub (ih₂ he.2 hD.2)
  | mul e₁ e₂ ih₁ ih₂ =>
      simp only [DefinedOn] at he
      simp only [D, DefinedOn] at hD
      exact (ih₁ he.1 hD.1.1).mul (ih₂ he.2 hD.2.2)
  | div e₁ e₂ ih₁ ih₂ =>
      simp only [DefinedOn] at he
      simp only [D, DefinedOn, sem] at hD
      obtain ⟨he₁, he₂, hz⟩ := he
      obtain ⟨⟨⟨hd₁, -⟩, ⟨-, hd₂⟩⟩, -, -⟩ := hD
      refine hasDerivAt_congr_val
        ((ih₁ he₁ hd₁).fun_div (ih₂ he₂ hd₂) hz) ?_
      simp only [D, sem]
      rw [zpow_two_eq]
  | powInt u n ih =>
      simp only [DefinedOn] at he
      simp only [D, DefinedOn, true_and] at hD
      obtain ⟨hu, -⟩ := he
      obtain ⟨⟨-, hcase⟩, hdu⟩ := hD
      have hcond : sem u x ≠ 0 ∨ 0 ≤ n := by
        rcases hcase with h | h
        · exact Or.inr (by omega)
        · exact Or.inl h
      exact (hasDerivAt_zpow n (sem u x) hcond).comp x (ih hu hdu)
  | sqrt u ih =>
      simp only [DefinedOn] at he
      simp only [D, DefinedOn, sem, true_and] at hD
      obtain ⟨hdu, -, hne⟩ := hD
      have hsne : Real.sqrt (sem u x) ≠ 0 := fun h => hne (by rw [h, mul_zero])
      have hupos : (0 : ℝ) < sem u x := Real.sqrt_ne_zero'.mp hsne
      exact (ih he.1 hdu).sqrt (ne_of_gt hupos)
  | exp u ih =>
      simp only [DefinedOn] at he
      simp only [D, DefinedOn] at hD
      exact (ih he hD.2).exp
  | log u ih =>
      simp only [DefinedOn] at he
      simp only [D, DefinedOn] at hD
      exact (ih he.1 hD.1).log (ne_of_gt he.2)
  | sin u ih =>
      simp only [DefinedOn] at he
      simp only [D, DefinedOn] at hD
      exact (ih he hD.2).sin
  | cos u ih =>
      simp only [DefinedOn] at he
      simp only [D, DefinedOn] at hD
      refine hasDerivAt_congr_val ((ih he hD.2).cos) ?_
      simp only [D, sem]
      exact neg_mul _ _
  | atan u ih =>
      simp only [DefinedOn] at he
      simp only [D, DefinedOn, sem, true_and] at hD
      obtain ⟨hdu, -, -⟩ := hD
      refine hasDerivAt_congr_val ((ih he hdu).arctan) ?_
      simp only [D, sem]
      rw [zpow_two_eq, one_div_mul_eq_div]

/-- Set-quantified form of `deriv_correct` (the shape `bound_step` needs
over the closed subinterval).  `U` needs no openness hypothesis: the
`HasDerivAt` chain lemmas are pointwise, so the engine's "open domain"
phrasing is subsumed by pointwise definedness. -/
theorem deriv_correct_on (e : Expr) (U : Set ℝ)
    (hdef : ∀ x ∈ U, DefinedOn e x) (hDdef : ∀ x ∈ U, DefinedOn (D e) x) :
    ∀ x ∈ U, HasDerivAt (sem e) (sem (D e) x) x :=
  fun x hx => deriv_correct e x (hdef x hx) (hDdef x hx)

/-! ### Continuity of an evaluable formula (helper for the C^k ladder) -/

/-- An evaluable formula is continuous at every point where it is defined:
each `DefinedOn` guard is exactly the side condition Mathlib's pointwise
continuity lemmas need (`ContinuousAt.div`, `continuousAt_zpow₀`,
`Real.continuousAt_log`). -/
theorem sem_continuousAt (e : Expr) (x : ℝ) (he : DefinedOn e x) :
    ContinuousAt (sem e) x := by
  induction e with
  | var => exact continuousAt_id
  | lit c => exact continuousAt_const
  | neg e ih =>
      simp only [DefinedOn] at he
      exact (ih he).neg
  | add e₁ e₂ ih₁ ih₂ =>
      simp only [DefinedOn] at he
      exact (ih₁ he.1).add (ih₂ he.2)
  | sub e₁ e₂ ih₁ ih₂ =>
      simp only [DefinedOn] at he
      exact (ih₁ he.1).sub (ih₂ he.2)
  | mul e₁ e₂ ih₁ ih₂ =>
      simp only [DefinedOn] at he
      exact (ih₁ he.1).mul (ih₂ he.2)
  | div e₁ e₂ ih₁ ih₂ =>
      simp only [DefinedOn] at he
      exact (ih₁ he.1).div (ih₂ he.2.1) he.2.2
  | powInt u n ih =>
      simp only [DefinedOn] at he
      exact (continuousAt_zpow₀ (sem u x) n he.2.symm).comp (ih he.1)
  | sqrt u ih =>
      simp only [DefinedOn] at he
      exact Real.continuous_sqrt.continuousAt.comp (ih he.1)
  | exp u ih =>
      simp only [DefinedOn] at he
      exact Real.continuous_exp.continuousAt.comp (ih he)
  | log u ih =>
      simp only [DefinedOn] at he
      exact (Real.continuousAt_log (ne_of_gt he.2)).comp (ih he.1)
  | sin u ih =>
      simp only [DefinedOn] at he
      exact Real.continuous_sin.continuousAt.comp (ih he)
  | cos u ih =>
      simp only [DefinedOn] at he
      exact Real.continuous_cos.continuousAt.comp (ih he)
  | atan u ih =>
      simp only [DefinedOn] at he
      exact Real.continuous_arctan.continuousAt.comp (ih he)

/-- Set version of `sem_continuousAt`. -/
theorem sem_continuousOn (e : Expr) (s : Set ℝ)
    (h : ∀ x ∈ s, DefinedOn e x) : ContinuousOn (sem e) s :=
  fun x hx => (sem_continuousAt e x (h x hx)).continuousWithinAt

/-! ### Main theorem 2 — the C^k ladder -/

/-- One rung of the C^k ladder: a pointwise derivative on `Icc a b` whose
formula is `C^n` there makes the function `C^(n+1)` there. -/
private lemma contDiffOn_succ_step {g dg : ℝ → ℝ} {a b : ℝ} {n : ℕ∞ω}
    (hn : n ≠ ω) (hab : a < b)
    (hd : ∀ x ∈ Icc a b, HasDerivAt g (dg x) x)
    (hdg : ContDiffOn ℝ n dg (Icc a b)) :
    ContDiffOn ℝ (n + 1) g (Icc a b) := by
  have hu : UniqueDiffOn ℝ (Icc a b) := uniqueDiffOn_Icc hab
  rw [contDiffOn_succ_iff_derivWithin hu]
  refine ⟨fun x hx => (hd x hx).differentiableAt.differentiableWithinAt,
          fun h => absurd h hn, hdg.congr ?_⟩
  intro x hx
  exact ((hd x hx).hasDerivWithinAt).derivWithin (hu x hx)

/-- **Evaluability certifies C¹** — the engine's claim, one level up:
if the formula `e` and its emitted derivative formula `D e` both evaluate
everywhere on `[a, b]`, then `sem e` is continuously differentiable on
`[a, b]`. -/
theorem c1_on_of_evaluable (e : Expr) (a b : ℝ) (hab : a < b)
    (h0 : ∀ x ∈ Icc a b, DefinedOn e x)
    (h1 : ∀ x ∈ Icc a b, DefinedOn (D e) x) :
    ContDiffOn ℝ 1 (sem e) (Icc a b) := by
  have hu : UniqueDiffOn ℝ (Icc a b) := uniqueDiffOn_Icc hab
  have hd : ∀ x ∈ Icc a b, HasDerivAt (sem e) (sem (D e) x) x :=
    deriv_correct_on e (Icc a b) h0 h1
  rw [contDiffOn_one_iff_derivWithin hu]
  refine ⟨fun x hx => (hd x hx).differentiableAt.differentiableWithinAt, ?_⟩
  refine (sem_continuousOn (D e) (Icc a b) h1).congr ?_
  intro x hx
  exact ((hd x hx).hasDerivWithinAt).derivWithin (hu x hx)

/-- **Evaluability of the chain e, e′, e″ certifies C²** — iterating
`c1_on_of_evaluable` one rung: exactly the smoothness the engine's
`smooth-taylor2` acceptance implicitly claims ("success certifies f in C^2
there", engine lines 2564–2567). -/
theorem c2_on_of_evaluable (e : Expr) (a b : ℝ) (hab : a < b)
    (h0 : ∀ x ∈ Icc a b, DefinedOn e x)
    (h1 : ∀ x ∈ Icc a b, DefinedOn (D e) x)
    (h2 : ∀ x ∈ Icc a b, DefinedOn (D (D e)) x) :
    ContDiffOn ℝ 2 (sem e) (Icc a b) := by
  have step := contDiffOn_succ_step (n := 1) (by simp) hab
    (deriv_correct_on e (Icc a b) h0 h1)
    (c1_on_of_evaluable (D e) a b hab h1 h2)
  rw [show (2 : ℕ∞ω) = 1 + 1 from one_add_one_eq_two.symm]
  exact step

/-- **Evaluability of the chain e, …, e⁗ certifies C⁴** — the smoothness
the engine's `smooth-taylor4` acceptance claims. -/
theorem c4_on_of_evaluable (e : Expr) (a b : ℝ) (hab : a < b)
    (h0 : ∀ x ∈ Icc a b, DefinedOn e x)
    (h1 : ∀ x ∈ Icc a b, DefinedOn (D e) x)
    (h2 : ∀ x ∈ Icc a b, DefinedOn (D (D e)) x)
    (h3 : ∀ x ∈ Icc a b, DefinedOn (D (D (D e))) x)
    (h4 : ∀ x ∈ Icc a b, DefinedOn (D (D (D (D e)))) x) :
    ContDiffOn ℝ 4 (sem e) (Icc a b) := by
  have hc2 : ContDiffOn ℝ 2 (sem (D (D e))) (Icc a b) :=
    c2_on_of_evaluable (D (D e)) a b hab h2 h3 h4
  have hc3 : ContDiffOn ℝ 3 (sem (D e)) (Icc a b) := by
    have step := contDiffOn_succ_step (n := 2) (by simp) hab
      (deriv_correct_on (D e) (Icc a b) h1 h2) hc2
    rw [show (3 : ℕ∞ω) = 2 + 1 from two_add_one_eq_three.symm]
    exact step
  have step := contDiffOn_succ_step (n := 3) (by simp) hab
    (deriv_correct_on e (Icc a b) h0 h1) hc3
  rw [show (4 : ℕ∞ω) = 3 + 1 from three_add_one_eq_four.symm]
  exact step

/-! ### Main theorem 3 — bridges into the Taylor midpoint enclosures -/

/-- **Taylor-2 hypothesis tuple from evaluability**: if the chain
e, D e, D² e all evaluate over `[a, b]` (= the engine's `F.ok && Fm.ok &&
F1.ok && F2.ok` gate in `bound_step`, lines 2643–2646), the two
`HasDerivAt` chains `taylor2_midpoint_enclosure` takes hold literally. -/
theorem taylor2_hypotheses_of_evaluable (e : Expr) (a b : ℝ)
    (h0 : ∀ x ∈ Icc a b, DefinedOn e x)
    (h1 : ∀ x ∈ Icc a b, DefinedOn (D e) x)
    (h2 : ∀ x ∈ Icc a b, DefinedOn (D (D e)) x) :
    (∀ x ∈ Icc a b, HasDerivAt (sem e) (sem (D e) x) x) ∧
      (∀ x ∈ Icc a b, HasDerivAt (sem (D e)) (sem (D (D e)) x) x) :=
  ⟨deriv_correct_on e (Icc a b) h0 h1,
   deriv_correct_on (D e) (Icc a b) h1 h2⟩

/-- **Taylor-4 hypothesis tuple from evaluability**: the four `HasDerivAt`
chains `taylor4_midpoint_enclosure` takes, from evaluability of
e, D e, D² e, D³ e, D⁴ e (= the engine's additional `F2m.ok && F3.ok &&
F4.ok` gate, lines 2650–2654). -/
theorem taylor4_hypotheses_of_evaluable (e : Expr) (a b : ℝ)
    (h0 : ∀ x ∈ Icc a b, DefinedOn e x)
    (h1 : ∀ x ∈ Icc a b, DefinedOn (D e) x)
    (h2 : ∀ x ∈ Icc a b, DefinedOn (D (D e)) x)
    (h3 : ∀ x ∈ Icc a b, DefinedOn (D (D (D e))) x)
    (h4 : ∀ x ∈ Icc a b, DefinedOn (D (D (D (D e)))) x) :
    (∀ x ∈ Icc a b, HasDerivAt (sem e) (sem (D e) x) x) ∧
      (∀ x ∈ Icc a b, HasDerivAt (sem (D e)) (sem (D (D e)) x) x) ∧
      (∀ x ∈ Icc a b, HasDerivAt (sem (D (D e))) (sem (D (D (D e))) x) x) ∧
      (∀ x ∈ Icc a b,
        HasDerivAt (sem (D (D (D e)))) (sem (D (D (D (D e)))) x) x) :=
  ⟨deriv_correct_on e (Icc a b) h0 h1,
   deriv_correct_on (D e) (Icc a b) h1 h2,
   deriv_correct_on (D (D e)) (Icc a b) h2 h3,
   deriv_correct_on (D (D (D e))) (Icc a b) h3 h4⟩

/-- **End-to-end Taylor-2**: evaluability of e, D e, D² e over `[a, b]`
plus interval bounds on the second-derivative FORMULA `D² e` (the engine's
`F2 = ieval(f2, a, b)`) yield the `smooth-taylor2` enclosure of
`bound_step` — `h·f(c) + h³/24·[m2, M2]` brackets `∫_a^b f`. -/
theorem taylor2_enclosure_of_evaluable (e : Expr) (a b m2 M2 : ℝ)
    (hab : a < b)
    (h0 : ∀ x ∈ Icc a b, DefinedOn e x)
    (h1 : ∀ x ∈ Icc a b, DefinedOn (D e) x)
    (h2 : ∀ x ∈ Icc a b, DefinedOn (D (D e)) x)
    (hm2 : ∀ x ∈ Icc a b, m2 ≤ sem (D (D e)) x)
    (hM2 : ∀ x ∈ Icc a b, sem (D (D e)) x ≤ M2) :
    (b - a) * sem e ((a + b) / 2) + (b - a) ^ 3 / 24 * m2
        ≤ (∫ x in a..b, sem e x) ∧
      (∫ x in a..b, sem e x)
        ≤ (b - a) * sem e ((a + b) / 2) + (b - a) ^ 3 / 24 * M2 := by
  obtain ⟨hd1, hd2⟩ := taylor2_hypotheses_of_evaluable e a b h0 h1 h2
  exact taylor2_midpoint_enclosure (sem e) (sem (D e)) (sem (D (D e)))
    a b m2 M2 hab hd1 hd2 hm2 hM2

/-- **End-to-end Taylor-4**: evaluability of the chain e … D⁴ e over
`[a, b]` plus interval bounds on the fourth-derivative FORMULA `D⁴ e` (the
engine's `F4 = ieval(f4, a, b)`) yield the `smooth-taylor4` enclosure of
`bound_step` — `h·f(c) + h³/24·f″(c) + h⁵/1920·[m4, M4]` brackets
`∫_a^b f`. -/
theorem taylor4_enclosure_of_evaluable (e : Expr) (a b m4 M4 : ℝ)
    (hab : a < b)
    (h0 : ∀ x ∈ Icc a b, DefinedOn e x)
    (h1 : ∀ x ∈ Icc a b, DefinedOn (D e) x)
    (h2 : ∀ x ∈ Icc a b, DefinedOn (D (D e)) x)
    (h3 : ∀ x ∈ Icc a b, DefinedOn (D (D (D e))) x)
    (h4 : ∀ x ∈ Icc a b, DefinedOn (D (D (D (D e)))) x)
    (hm4 : ∀ x ∈ Icc a b, m4 ≤ sem (D (D (D (D e)))) x)
    (hM4 : ∀ x ∈ Icc a b, sem (D (D (D (D e)))) x ≤ M4) :
    (b - a) * sem e ((a + b) / 2)
        + (b - a) ^ 3 / 24 * sem (D (D e)) ((a + b) / 2)
        + (b - a) ^ 5 / 1920 * m4 ≤ (∫ x in a..b, sem e x) ∧
      (∫ x in a..b, sem e x)
        ≤ (b - a) * sem e ((a + b) / 2)
          + (b - a) ^ 3 / 24 * sem (D (D e)) ((a + b) / 2)
          + (b - a) ^ 5 / 1920 * M4 := by
  obtain ⟨hd1, hd2, hd3, hd4⟩ :=
    taylor4_hypotheses_of_evaluable e a b h0 h1 h2 h3 h4
  exact taylor4_midpoint_enclosure (sem e) (sem (D e)) (sem (D (D e)))
    (sem (D (D (D e)))) (sem (D (D (D (D e))))) a b m4 M4 hab
    hd1 hd2 hd3 hd4 hm4 hM4

end Deriv
end JackalIv
