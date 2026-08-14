/-
JACKAL certified integration — formula evaluability certifies
differentiability, over the SINGLE canonical `Expr` (`JackalIv/Syntax.lean`).

The engine's `bound_step` accepts the Taylor-2 / Taylor-4 midpoint forms only
after the symbolic formulas f, f', … ALL interval-evaluate over the closed
subinterval; its stated argument is "each elementary rule holds on the open
domain where its own formula is defined, so success certifies f in C^k there".
Here that becomes a theorem about the MODEL: a symbolic differentiator `D`
mirroring the engine's `deriv()`, and proofs that evaluability of the chain
e, D e, … certifies `HasDerivAt` / C¹ / C² / C⁴ — exactly the hypotheses the
Taylor midpoint enclosures (Taylor.lean) consume.

`D` ↔ engine `deriv()`, rule for rule (smooth core):
  num/const → 0, x → 1; neg, add, sub; mul → du·v + u·dv; div → quotient rule
  with `v^2` denominator; pow with a NUM-LITERAL exponent c → power rule
  `(c·b^(c-1))·db` (via `Real.hasDerivAt_rpow_const`, matching the engine's
  `ast_const_value_or_nan` constant-exponent branch); sin → cos·du,
  cos → −(sin·du), atan → du/(1+u²), sqrt → du/(2√u), ln → du/u, exp → exp·du.

Every OTHER canonical node — `mod`, the general (non-literal-exponent) `pow`,
`call1` names outside {sin,cos,atan,sqrt,exp,ln} (tan/asin/acos/cbrt/log10/
log2/abs/floor/ceil/round/trunc), every `call2` (hypot/atan2/min/max/pow) —
maps to the never-defined sentinel `Dbad`, so it is OUTSIDE `D`'s domain
(`DefinedOn (D e)` is `False` there → the C^k hypotheses are unsatisfiable,
a fail-closed refusal), never mis-differentiated.  This mirrors the engine's
`deriv()` `panic`/general-`x^y` branches, which the model deliberately leaves
as residual (as the pre-canonical `Deriv` wave did).

`DefinedOn`/`sem` are the canonical ones (Syntax.lean).  Continuity of the
derivative FORMULA (needed for the C^k ladder) is proved only for the
`Smooth` sublanguage — the closure of the smooth core under num-literal
powers — which every `D`-output inhabits (`D_smooth`) and whose inhabitation
is forced by `DefinedOn (D e)` (`definedOn_D_smooth`); the discontinuous nodes
(`floor`, general `pow`, …) are simply not `Smooth`, so the ladder never has
to claim their continuity.
-/
import JackalIv.Syntax
import JackalIv.Taylor

namespace JackalIv
namespace Deriv

open Set
open scoped ContDiff

/-- The never-defined sentinel: `1 / 0`, whose `DefinedOn` is `False`
(denominator literally zero).  `D` returns it for every node outside its
smooth-core rule set, so that node is fail-closed (outside `D`'s domain). -/
def Dbad : Expr := .div (.num 1 "1") (.num 0 "0")

/-- `Dbad` is never defined anywhere — the mechanized meaning of "the engine's
`deriv()` refuses (panics) here, so no derivative formula evaluates". -/
lemma dbad_undefined (x : ℝ) : ¬ DefinedOn Dbad x := by
  simp [Dbad, DefinedOn, sem]

/-- The symbolic differentiator — rule for rule the engine's `deriv()` smooth
core; every other node is `Dbad` (outside `D`'s domain). -/
noncomputable def D : Expr → Expr
  | .num _ _ => .num 0 "0"
  | .var name => if name = "x" then .num 1 "1" else .num 0 "0"
  | .constant _ => .num 0 "0"
  | .neg u => .neg (D u)
  | .add l r => .add (D l) (D r)
  | .sub l r => .sub (D l) (D r)
  | .mul l r => .add (.mul (D l) r) (.mul l (D r))
  | .div l r => .div (.sub (.mul (D l) r) (.mul l (D r))) (.pow r (.num 2 "2"))
  | .mod _ _ => Dbad
  | .pow b (.num c t) => .mul (.mul (.num c t) (.pow b (.num (c - 1) t))) (D b)
  | .pow _ _ => Dbad
  | .call1 name u =>
      if name = "sin" then .mul (.call1 "cos" u) (D u)
      else if name = "cos" then .neg (.mul (.call1 "sin" u) (D u))
      else if name = "atan" then .div (D u) (.add (.num 1 "1") (.pow u (.num 2 "2")))
      else if name = "sqrt" then .div (D u) (.mul (.num 2 "2") (.call1 "sqrt" u))
      else if name = "exp" then .mul (.call1 "exp" u) (D u)
      else if name = "ln" then .div (D u) u
      else Dbad
  | .call2 _ _ _ => Dbad

/-! ### The `Smooth` sublanguage (closure of the smooth core under
num-literal powers) — the fragment `D` ranges over and over which the
derivative formula is continuous. -/

/-- A formula is `Smooth` when it is built from the differentiable core with
num-literal exponents only.  Every `D`-output is `Smooth` (`D_smooth`), and
`DefinedOn (D e)` forces `Smooth e` (`definedOn_D_smooth`). -/
def Smooth : Expr → Prop
  | .num _ _ => True
  | .var _ => True
  | .constant _ => True
  | .neg u => Smooth u
  | .add l r => Smooth l ∧ Smooth r
  | .sub l r => Smooth l ∧ Smooth r
  | .mul l r => Smooth l ∧ Smooth r
  | .div l r => Smooth l ∧ Smooth r
  | .mod _ _ => False
  | .pow b (.num _ _) => Smooth b
  | .pow _ _ => False
  | .call1 name u =>
      (name = "sin" ∨ name = "cos" ∨ name = "atan" ∨ name = "sqrt" ∨
        name = "exp" ∨ name = "ln") ∧ Smooth u
  | .call2 _ _ _ => False

/-! ### Small plumbing -/

private lemma hasDerivAt_congr_val {g : ℝ → ℝ} {v w x : ℝ}
    (h : HasDerivAt g v x) (hvw : v = w) : HasDerivAt g w x := hvw ▸ h

/-- The `rpow_const` differentiability side condition `b ≠ 0 ∨ 1 ≤ c`, read
off the pow guard `powDom b (c - 1)` (= evaluability of the emitted
derivative's `b^(c-1)` factor). -/
private lemma rpow_const_cond {b c : ℝ} (h : powDom b (c - 1)) : b ≠ 0 ∨ 1 ≤ c := by
  rcases h with hpos | ⟨n, hn, hg⟩
  · exact Or.inl (ne_of_gt hpos)
  · rcases lt_or_ge n 0 with hlt | hge
    · exact Or.inl (hg hlt)
    · right
      have hnn : (0 : ℝ) ≤ (n : ℝ) := by exact_mod_cast hge
      linarith [hn]

/-! ### Main theorem 1 — evaluability of `e` and `D e` certifies the
derivative -/

/-- **Symbolic differentiation is correct on the evaluable domain**: at any
point where both `e` and its emitted derivative formula `D e` are defined
(= where `ieval` of both succeeds, in the engine), `sem e` is differentiable
with derivative exactly `sem (D e)`.  Every domain side condition Mathlib
needs is supplied by a `DefinedOn` guard. -/
theorem deriv_correct (e : Expr) (x : ℝ)
    (he : DefinedOn e x) (hD : DefinedOn (D e) x) :
    HasDerivAt (sem e) (sem (D e) x) x := by
  induction e with
  | num c t =>
      have hfun : sem (.num c t) = fun _ : ℝ => c := rfl
      have hval : sem (D (.num c t)) x = 0 := by simp [D, sem]
      rw [hfun, hval]; exact hasDerivAt_const x c
  | var name =>
      simp only [DefinedOn] at he
      subst he
      have hfun : sem (.var "x") = fun y : ℝ => y := by funext y; simp [sem]
      have hval : sem (D (.var "x")) x = 1 := by simp [D, sem]
      rw [hfun, hval]; exact hasDerivAt_id x
  | constant name =>
      have hfun : sem (.constant name) = fun _ : ℝ => constValue name := rfl
      have hval : sem (D (.constant name)) x = 0 := by simp [D, sem]
      rw [hfun, hval]; exact hasDerivAt_const x _
  | neg u ih =>
      simp only [DefinedOn] at he
      simp only [D, DefinedOn] at hD
      have hfun : sem (.neg u) = fun y : ℝ => -(sem u y) := by funext y; simp [sem]
      have hval : sem (D (.neg u)) x = -(sem (D u) x) := by simp [D, sem]
      rw [hfun, hval]; exact (ih he hD).neg
  | add e₁ e₂ ih₁ ih₂ =>
      simp only [DefinedOn] at he
      simp only [D, DefinedOn] at hD
      have hfun : sem (.add e₁ e₂) = fun y : ℝ => sem e₁ y + sem e₂ y := by funext y; simp [sem]
      have hval : sem (D (.add e₁ e₂)) x = sem (D e₁) x + sem (D e₂) x := by simp [D, sem]
      rw [hfun, hval]; exact (ih₁ he.1 hD.1).add (ih₂ he.2 hD.2)
  | sub e₁ e₂ ih₁ ih₂ =>
      simp only [DefinedOn] at he
      simp only [D, DefinedOn] at hD
      have hfun : sem (.sub e₁ e₂) = fun y : ℝ => sem e₁ y - sem e₂ y := by funext y; simp [sem]
      have hval : sem (D (.sub e₁ e₂)) x = sem (D e₁) x - sem (D e₂) x := by simp [D, sem]
      rw [hfun, hval]; exact (ih₁ he.1 hD.1).sub (ih₂ he.2 hD.2)
  | mul e₁ e₂ ih₁ ih₂ =>
      simp only [DefinedOn] at he
      simp only [D, DefinedOn] at hD
      obtain ⟨⟨hd₁, -⟩, -, hd₂⟩ := hD
      have hfun : sem (.mul e₁ e₂) = fun y : ℝ => sem e₁ y * sem e₂ y := by funext y; simp [sem]
      have hval : sem (D (.mul e₁ e₂)) x
          = sem (D e₁) x * sem e₂ x + sem e₁ x * sem (D e₂) x := by simp [D, sem]
      rw [hfun, hval]; exact (ih₁ he.1 hd₁).mul (ih₂ he.2 hd₂)
  | div e₁ e₂ ih₁ ih₂ =>
      simp only [DefinedOn] at he
      obtain ⟨he₁, he₂, hz⟩ := he
      simp only [D, DefinedOn, sem] at hD
      obtain ⟨⟨⟨hd₁, -⟩, -, hd₂⟩, -, -⟩ := hD
      have hfun : sem (.div e₁ e₂) = fun y : ℝ => sem e₁ y / sem e₂ y := by funext y; simp [sem]
      have hval : sem (D (.div e₁ e₂)) x
          = (sem (D e₁) x * sem e₂ x - sem e₁ x * sem (D e₂) x) / sem e₂ x ^ 2 := by
        show sem (.sub (.mul (D e₁) e₂) (.mul e₁ (D e₂))) x
            / sem (.pow e₂ (.num 2 "2")) x = _
        rw [sem_pow_ofNat_two]; simp [sem]
      rw [hfun, hval]; exact (ih₁ he₁ hd₁).div (ih₂ he₂ hd₂) hz
  | mod e₁ e₂ ih₁ ih₂ =>
      exact absurd hD (dbad_undefined x)
  | pow b e ihb ihe =>
      clear ihe
      cases e with
      | num c t =>
          simp only [D, DefinedOn, sem] at hD
          obtain ⟨⟨-, hbdef, -, hpd⟩, hDb⟩ := hD
          have hb := ihb hbdef hDb
          have hcond : sem b x ≠ 0 ∨ 1 ≤ c := rpow_const_cond hpd
          have key := (Real.hasDerivAt_rpow_const hcond).comp x hb
          have hfun : sem (.pow b (.num c t)) = fun y : ℝ => sem b y ^ c := by
            funext y; simp [sem]
          have hval : sem (D (.pow b (.num c t))) x
              = c * sem b x ^ (c - 1) * sem (D b) x := by simp [D, sem]
          rw [hfun, hval]; exact key
      | var n => exact absurd hD (dbad_undefined x)
      | constant n => exact absurd hD (dbad_undefined x)
      | neg u => exact absurd hD (dbad_undefined x)
      | add l r => exact absurd hD (dbad_undefined x)
      | sub l r => exact absurd hD (dbad_undefined x)
      | mul l r => exact absurd hD (dbad_undefined x)
      | div l r => exact absurd hD (dbad_undefined x)
      | mod l r => exact absurd hD (dbad_undefined x)
      | pow bb ee => exact absurd hD (dbad_undefined x)
      | call1 nm u => exact absurd hD (dbad_undefined x)
      | call2 nm u v => exact absurd hD (dbad_undefined x)
  | call1 name u ihu =>
      by_cases h1 : name = "sin"
      · subst h1
        simp only [DefinedOn] at he
        simp only [D, if_pos, DefinedOn] at hD
        have hu := ihu he.1 hD.2
        have hval : sem (D (.call1 "sin" u)) x = Real.cos (sem u x) * sem (D u) x := by
          simp [D, sem]
        have hfun : sem (.call1 "sin" u) = fun y : ℝ => Real.sin (sem u y) := by
          funext y; simp [sem]
        rw [hfun, hval]; exact hu.sin
      · by_cases h2 : name = "cos"
        · subst h2
          simp only [DefinedOn] at he
          simp only [D, if_neg h1, if_pos, DefinedOn] at hD
          have hu := ihu he.1 hD.2
          have hval : sem (D (.call1 "cos" u)) x = -(Real.sin (sem u x) * sem (D u) x) := by
            simp [D, sem]
          have hfun : sem (.call1 "cos" u) = fun y : ℝ => Real.cos (sem u y) := by
            funext y; simp [sem]
          rw [hfun, hval]
          have key := hu.cos
          rwa [neg_mul] at key
        · by_cases h3 : name = "atan"
          · subst h3
            simp only [DefinedOn] at he
            simp only [D, if_neg h1, if_neg h2, if_pos, DefinedOn] at hD
            have hu := ihu he.1 hD.1
            have hval : sem (D (.call1 "atan" u)) x
                = sem (D u) x / (1 + sem u x ^ 2) := by
              show sem (D u) x / sem (.add (.num 1 "1") (.pow u (.num 2 "2"))) x = _
              rw [show sem (.add (.num 1 "1") (.pow u (.num 2 "2"))) x
                  = sem (.num 1 "1") x + sem (.pow u (.num 2 "2")) x from rfl,
                sem_pow_ofNat_two]
              simp [sem]
            have hfun : sem (.call1 "atan" u) = fun y : ℝ => Real.arctan (sem u y) := by
              funext y; simp [sem]
            rw [hfun, hval]
            have key := hu.arctan
            rw [one_div, mul_comm] at key
            rw [div_eq_mul_inv]; exact key
          · by_cases h4 : name = "sqrt"
            · subst h4
              simp only [DefinedOn] at he
              simp only [D, if_neg h1, if_neg h2, if_neg h3, if_pos, DefinedOn, sem,
                call1Sem_sqrt] at hD
              obtain ⟨hdu, -, hne⟩ := hD
              have hsne : Real.sqrt (sem u x) ≠ 0 := fun h => hne (by rw [h, mul_zero])
              have hupos : (0 : ℝ) < sem u x := Real.sqrt_ne_zero'.mp hsne
              have hu := ihu he.1 hdu
              have hval : sem (D (.call1 "sqrt" u)) x
                  = sem (D u) x / (2 * Real.sqrt (sem u x)) := by simp [D, sem]
              have hfun : sem (.call1 "sqrt" u) = fun y : ℝ => Real.sqrt (sem u y) := by
                funext y; simp [sem]
              rw [hfun, hval]; exact hu.sqrt (ne_of_gt hupos)
            · by_cases h5 : name = "exp"
              · subst h5
                simp only [DefinedOn] at he
                simp only [D, if_neg h1, if_neg h2, if_neg h3, if_neg h4, if_pos, DefinedOn] at hD
                have hu := ihu he.1 hD.2
                have hval : sem (D (.call1 "exp" u)) x = Real.exp (sem u x) * sem (D u) x := by
                  simp [D, sem]
                have hfun : sem (.call1 "exp" u) = fun y : ℝ => Real.exp (sem u y) := by
                  funext y; simp [sem]
                rw [hfun, hval]; exact hu.exp
              · by_cases h6 : name = "ln"
                · subst h6
                  simp only [DefinedOn] at he
                  obtain ⟨heu, hpos⟩ := he
                  simp only [call1Dom_ln] at hpos
                  simp only [D, if_neg h1, if_neg h2, if_neg h3, if_neg h4, if_neg h5,
                    if_pos, DefinedOn] at hD
                  have hu := ihu heu hD.1
                  have hval : sem (D (.call1 "ln" u)) x = sem (D u) x / sem u x := by
                    simp [D, sem]
                  have hfun : sem (.call1 "ln" u) = fun y : ℝ => Real.log (sem u y) := by
                    funext y; simp [sem]
                  rw [hfun, hval]
                  have key := (hu.log (ne_of_gt hpos))
                  simpa [div_eq_mul_inv] using key
                · exfalso
                  have hbad : D (.call1 name u) = Dbad := by
                    simp only [D, if_neg h1, if_neg h2, if_neg h3, if_neg h4, if_neg h5, if_neg h6]
                  rw [hbad] at hD
                  exact dbad_undefined x hD
  | call2 name u v ihu ihv =>
      exact absurd hD (dbad_undefined x)

/-- Set-quantified form of `deriv_correct` (the shape `bound_step` needs over
the closed subinterval).  Pointwise — the engine's "open domain" phrasing is
subsumed. -/
theorem deriv_correct_on (e : Expr) (U : Set ℝ)
    (hdef : ∀ x ∈ U, DefinedOn e x) (hDdef : ∀ x ∈ U, DefinedOn (D e) x) :
    ∀ x ∈ U, HasDerivAt (sem e) (sem (D e) x) x :=
  fun x hx => deriv_correct e x (hdef x hx) (hDdef x hx)

/-! ### `Smooth` bookkeeping for the continuity ladder -/

/-- Every `D`-output lies in the `Smooth` sublanguage. -/
theorem D_smooth (e : Expr) (hs : Smooth e) : Smooth (D e) := by
  induction e with
  | num c t => simp [D, Smooth]
  | var name => by_cases h : name = "x" <;> simp [D, Smooth, h]
  | constant name => simp [D, Smooth]
  | neg u ih => exact ih hs
  | add l r ih₁ ih₂ => exact ⟨ih₁ hs.1, ih₂ hs.2⟩
  | sub l r ih₁ ih₂ => exact ⟨ih₁ hs.1, ih₂ hs.2⟩
  | mul l r ih₁ ih₂ => exact ⟨⟨ih₁ hs.1, hs.2⟩, hs.1, ih₂ hs.2⟩
  | div l r ih₁ ih₂ => exact ⟨⟨⟨ih₁ hs.1, hs.2⟩, hs.1, ih₂ hs.2⟩, hs.2⟩
  | mod l r ih₁ ih₂ => exact hs.elim
  | pow b e ihb ihe =>
      cases e with
      | num c t => exact ⟨⟨trivial, hs⟩, ihb hs⟩
      | _ => exact hs.elim
  | call1 name u ihu =>
      obtain ⟨hname, hsu⟩ := hs
      have hDu : Smooth (D u) := ihu hsu
      rcases hname with h | h | h | h | h | h <;> subst h
      · exact ⟨⟨by simp, hsu⟩, hDu⟩
      · exact ⟨⟨by simp, hsu⟩, hDu⟩
      · exact ⟨hDu, trivial, hsu⟩
      · exact ⟨hDu, trivial, by simp, hsu⟩
      · exact ⟨⟨by simp, hsu⟩, hDu⟩
      · exact ⟨hDu, hsu⟩
  | call2 name u v ihu ihv => exact hs.elim

/-- Evaluability of a derivative formula forces its argument to be `Smooth`
(the non-`Smooth` nodes all differentiate to the never-defined `Dbad`). -/
theorem definedOn_D_smooth (e : Expr) (x : ℝ) (hD : DefinedOn (D e) x) : Smooth e := by
  induction e with
  | num c t => trivial
  | var name => trivial
  | constant name => trivial
  | neg u ih => exact ih (by simpa [D, DefinedOn] using hD)
  | add l r ih₁ ih₂ =>
      simp only [D, DefinedOn] at hD
      exact ⟨ih₁ hD.1, ih₂ hD.2⟩
  | sub l r ih₁ ih₂ =>
      simp only [D, DefinedOn] at hD
      exact ⟨ih₁ hD.1, ih₂ hD.2⟩
  | mul l r ih₁ ih₂ =>
      simp only [D, DefinedOn] at hD
      exact ⟨ih₁ hD.1.1, ih₂ hD.2.2⟩
  | div l r ih₁ ih₂ =>
      simp only [D, DefinedOn] at hD
      exact ⟨ih₁ hD.1.1.1, ih₂ hD.1.2.2⟩
  | mod l r ih₁ ih₂ => exact absurd hD (dbad_undefined x)
  | pow b e ihb ihe =>
      cases e with
      | num c t =>
          simp only [D, DefinedOn] at hD
          exact ihb hD.2
      | var n => exact absurd hD (dbad_undefined x)
      | constant n => exact absurd hD (dbad_undefined x)
      | neg u => exact absurd hD (dbad_undefined x)
      | add l r => exact absurd hD (dbad_undefined x)
      | sub l r => exact absurd hD (dbad_undefined x)
      | mul l r => exact absurd hD (dbad_undefined x)
      | div l r => exact absurd hD (dbad_undefined x)
      | mod l r => exact absurd hD (dbad_undefined x)
      | pow bb ee => exact absurd hD (dbad_undefined x)
      | call1 nm u => exact absurd hD (dbad_undefined x)
      | call2 nm u v => exact absurd hD (dbad_undefined x)
  | call1 name u ihu =>
      by_cases h1 : name = "sin"
      · subst h1; refine ⟨by tauto, ihu ?_⟩; simpa [D, DefinedOn] using hD.2
      · by_cases h2 : name = "cos"
        · subst h2; refine ⟨by tauto, ihu ?_⟩
          simp only [D, if_neg h1, if_pos, DefinedOn] at hD; exact hD.2
        · by_cases h3 : name = "atan"
          · subst h3; refine ⟨by tauto, ihu ?_⟩
            simp only [D, if_neg h1, if_neg h2, if_pos, DefinedOn] at hD; exact hD.1
          · by_cases h4 : name = "sqrt"
            · subst h4; refine ⟨by tauto, ihu ?_⟩
              simp only [D, if_neg h1, if_neg h2, if_neg h3, if_pos, DefinedOn] at hD; exact hD.1
            · by_cases h5 : name = "exp"
              · subst h5; refine ⟨by tauto, ihu ?_⟩
                simp only [D, if_neg h1, if_neg h2, if_neg h3, if_neg h4, if_pos, DefinedOn] at hD
                exact hD.2
              · by_cases h6 : name = "ln"
                · subst h6; refine ⟨by tauto, ihu ?_⟩
                  simp only [D, if_neg h1, if_neg h2, if_neg h3, if_neg h4, if_neg h5, if_pos,
                    DefinedOn] at hD
                  exact hD.1
                · exfalso
                  have hbad : D (.call1 name u) = Dbad := by
                    simp only [D, if_neg h1, if_neg h2, if_neg h3, if_neg h4, if_neg h5, if_neg h6]
                  rw [hbad] at hD; exact dbad_undefined x hD
  | call2 name u v ihu ihv => exact absurd hD (dbad_undefined x)

/-! ### Continuity of an evaluable `Smooth` formula -/

/-- A `Smooth`, evaluable formula is continuous at every point where it is
defined.  Only the smooth-core cases arise (the discontinuous nodes are not
`Smooth`), so each `DefinedOn` guard is exactly the side condition Mathlib's
pointwise continuity lemmas need. -/
theorem sem_continuousAt (e : Expr) (x : ℝ) (hs : Smooth e) (he : DefinedOn e x) :
    ContinuousAt (sem e) x := by
  induction e with
  | num c t => simpa [sem] using continuousAt_const
  | var name =>
      simp only [DefinedOn] at he; subst he
      have hfun : sem (.var "x") = fun y : ℝ => y := by funext y; simp [sem]
      rw [hfun]; exact continuousAt_id
  | constant name =>
      have hfun : sem (.constant name) = fun _ : ℝ => constValue name := rfl
      rw [hfun]; exact continuousAt_const
  | neg u ih =>
      simp only [DefinedOn] at he
      have hfun : sem (.neg u) = fun y : ℝ => -(sem u y) := by funext y; simp [sem]
      rw [hfun]; exact (ih hs he).neg
  | add e₁ e₂ ih₁ ih₂ =>
      simp only [DefinedOn] at he
      have hfun : sem (.add e₁ e₂) = fun y : ℝ => sem e₁ y + sem e₂ y := by funext y; simp [sem]
      rw [hfun]; exact (ih₁ hs.1 he.1).add (ih₂ hs.2 he.2)
  | sub e₁ e₂ ih₁ ih₂ =>
      simp only [DefinedOn] at he
      have hfun : sem (.sub e₁ e₂) = fun y : ℝ => sem e₁ y - sem e₂ y := by funext y; simp [sem]
      rw [hfun]; exact (ih₁ hs.1 he.1).sub (ih₂ hs.2 he.2)
  | mul e₁ e₂ ih₁ ih₂ =>
      simp only [DefinedOn] at he
      have hfun : sem (.mul e₁ e₂) = fun y : ℝ => sem e₁ y * sem e₂ y := by funext y; simp [sem]
      rw [hfun]; exact (ih₁ hs.1 he.1).mul (ih₂ hs.2 he.2)
  | div e₁ e₂ ih₁ ih₂ =>
      simp only [DefinedOn] at he
      have hfun : sem (.div e₁ e₂) = fun y : ℝ => sem e₁ y / sem e₂ y := by funext y; simp [sem]
      rw [hfun]; exact (ih₁ hs.1 he.1).div (ih₂ hs.2 he.2.1) he.2.2
  | mod e₁ e₂ ih₁ ih₂ => exact hs.elim
  | pow b e ihb ihe =>
      cases e with
      | num c t =>
          simp only [DefinedOn, sem] at he
          obtain ⟨hbdef, -, hpd⟩ := he
          have hbc := ihb hs hbdef
          have hcond : sem b x ≠ 0 ∨ 0 ≤ c := by
            rcases hpd with hpos | ⟨n, hn, hg⟩
            · exact Or.inl (ne_of_gt hpos)
            · rcases lt_or_ge n 0 with hlt | hge
              · exact Or.inl (hg hlt)
              · right
                have hnn : (0 : ℝ) ≤ (n : ℝ) := by exact_mod_cast hge
                linarith [hn]
          have key := (Real.continuousAt_rpow_const (sem b x) c hcond).comp hbc
          have hfun : sem (.pow b (.num c t)) = fun y : ℝ => sem b y ^ c := by
            funext y; simp [sem]
          rw [hfun]; exact key
      | _ => exact hs.elim
  | call1 name u ihu =>
      obtain ⟨hname, hsu⟩ := hs
      simp only [DefinedOn] at he
      have hcu := ihu hsu he.1
      rcases hname with h | h | h | h | h | h <;> subst h
      · have hfun : sem (.call1 "sin" u) = fun y : ℝ => Real.sin (sem u y) := by
          funext y; simp [sem]
        rw [hfun]; exact Real.continuous_sin.continuousAt.comp hcu
      · have hfun : sem (.call1 "cos" u) = fun y : ℝ => Real.cos (sem u y) := by
          funext y; simp [sem]
        rw [hfun]; exact Real.continuous_cos.continuousAt.comp hcu
      · have hfun : sem (.call1 "atan" u) = fun y : ℝ => Real.arctan (sem u y) := by
          funext y; simp [sem]
        rw [hfun]; exact Real.continuous_arctan.continuousAt.comp hcu
      · have hfun : sem (.call1 "sqrt" u) = fun y : ℝ => Real.sqrt (sem u y) := by
          funext y; simp [sem]
        rw [hfun]; exact Real.continuous_sqrt.continuousAt.comp hcu
      · have hfun : sem (.call1 "exp" u) = fun y : ℝ => Real.exp (sem u y) := by
          funext y; simp [sem]
        rw [hfun]; exact Real.continuous_exp.continuousAt.comp hcu
      · have hpos : 0 < sem u x := by simpa only [call1Dom_ln] using he.2
        have hfun : sem (.call1 "ln" u) = fun y : ℝ => Real.log (sem u y) := by
          funext y; simp [sem]
        rw [hfun]; exact (Real.continuousAt_log (ne_of_gt hpos)).comp hcu
  | call2 name u v ihu ihv => exact hs.elim

/-- Set version of `sem_continuousAt` for a `Smooth` formula. -/
theorem sem_continuousOn (e : Expr) (s : Set ℝ) (hs : Smooth e)
    (h : ∀ x ∈ s, DefinedOn e x) : ContinuousOn (sem e) s :=
  fun x hx => (sem_continuousAt e x hs (h x hx)).continuousWithinAt

/-! ### Main theorem 2 — the C^k ladder -/

/-- One rung of the C^k ladder. -/
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

/-- **Evaluability certifies C¹**: if `e` and `D e` both evaluate everywhere
on `[a, b]`, then `sem e` is continuously differentiable there.  Continuity of
the derivative `sem (D e)` comes from `sem_continuousOn` on the `Smooth`
sublanguage, whose membership is forced by evaluability of `D e`. -/
theorem c1_on_of_evaluable (e : Expr) (a b : ℝ) (hab : a < b)
    (h0 : ∀ x ∈ Icc a b, DefinedOn e x)
    (h1 : ∀ x ∈ Icc a b, DefinedOn (D e) x) :
    ContDiffOn ℝ 1 (sem e) (Icc a b) := by
  have hu : UniqueDiffOn ℝ (Icc a b) := uniqueDiffOn_Icc hab
  have hd : ∀ x ∈ Icc a b, HasDerivAt (sem e) (sem (D e) x) x :=
    deriv_correct_on e (Icc a b) h0 h1
  have hsmooth_e : Smooth e :=
    definedOn_D_smooth e a (h1 a (left_mem_Icc.mpr hab.le))
  have hsmooth_De : Smooth (D e) := D_smooth e hsmooth_e
  rw [contDiffOn_one_iff_derivWithin hu]
  refine ⟨fun x hx => (hd x hx).differentiableAt.differentiableWithinAt, ?_⟩
  refine (sem_continuousOn (D e) (Icc a b) hsmooth_De h1).congr ?_
  intro x hx
  exact ((hd x hx).hasDerivWithinAt).derivWithin (hu x hx)

/-- **Evaluability of the chain e, e′, e″ certifies C²**. -/
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

/-- **Evaluability of the chain e, …, e⁗ certifies C⁴**. -/
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

/-- **Taylor-2 hypothesis tuple from evaluability**. -/
theorem taylor2_hypotheses_of_evaluable (e : Expr) (a b : ℝ)
    (h0 : ∀ x ∈ Icc a b, DefinedOn e x)
    (h1 : ∀ x ∈ Icc a b, DefinedOn (D e) x)
    (h2 : ∀ x ∈ Icc a b, DefinedOn (D (D e)) x) :
    (∀ x ∈ Icc a b, HasDerivAt (sem e) (sem (D e) x) x) ∧
      (∀ x ∈ Icc a b, HasDerivAt (sem (D e)) (sem (D (D e)) x) x) :=
  ⟨deriv_correct_on e (Icc a b) h0 h1,
   deriv_correct_on (D e) (Icc a b) h1 h2⟩

/-- **Taylor-4 hypothesis tuple from evaluability**. -/
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

/-- **End-to-end Taylor-2**. -/
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

/-- **End-to-end Taylor-4**. -/
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
