/-
JackalIv/ShadowQExpr.lean — SHADOW (research-shadow, NON-AUTHORITATIVE).

ℚ-valued mirror of the canonical `Syntax.Expr`, with a COMPUTABLE mirror
differentiator `DQ` of `Deriv.D` and a computable partial reconstruction
`qexprOf` from evaluation-certificate node lists (`Cert.Node`).

Purpose (v1.7 bound_step shadow mission, roadmap item 4): the composition
checker must verify — computably — that the embedded derivative-chain
certificates of a subdivision-tree leaf are certificates for EXACTLY the Lean
differentiator chain `e, D e, D (D e), …` of the root integrand.  `Deriv.D`
is noncomputable (`Expr.num` carries `ℝ`), so the checker compares `QExpr`
values under the proved bridges:

  * `embedQ_DQ    : embedQ (DQ q) = Deriv.D (embedQ q)`
  * `qexprOf_embed: qexprOf nodes = some q → Cert.exprOf nodes = some (embedQ q)`

`qexprOf` deliberately covers only the SHADOW FRAGMENT of certificate ops
(num_exact / var / neg / add / sub / mul / div / powZero / powEvenPos /
powOddPos / sin / cos / sin_rat / cos_rat); every other op yields `none`,
which the composition checker treats as a fail-closed refusal.  This is a
strict subset of `Cert.buildExpr`'s coverage, so the agreement lemma only
claims the direction the soundness proof needs.

Trust note: nothing in this file changes any public verifier or acceptance
class; no `sorry`, no axiom, no `native_decide`, no `@[implemented_by]`.
-/
import JackalIv.CertTypes
import JackalIv.Deriv

namespace JackalIv.Shadow

open JackalIv

/-! ### The ℚ-mirror expression syntax -/

/-- ℚ-valued mirror of `Syntax.Expr` (constructor for constructor).  `num`
carries the exact rational value plus the original token text, exactly as
`Expr.num` carries the real value plus the token. -/
inductive QExpr : Type
  | num (q : ℚ) (t : String)
  | var (name : String)
  | constant (name : String)
  | neg (u : QExpr)
  | add (l r : QExpr)
  | sub (l r : QExpr)
  | mul (l r : QExpr)
  | div (l r : QExpr)
  | mod (l r : QExpr)
  | pow (base exponent : QExpr)
  | call1 (name : String) (u : QExpr)
  | call2 (name : String) (u v : QExpr)
  deriving DecidableEq, Repr, Inhabited

/-- Embedding into the canonical syntax: cast every rational literal. -/
noncomputable def embedQ : QExpr → Expr
  | .num q t => .num (↑q) t
  | .var name => .var name
  | .constant name => .constant name
  | .neg u => .neg (embedQ u)
  | .add l r => .add (embedQ l) (embedQ r)
  | .sub l r => .sub (embedQ l) (embedQ r)
  | .mul l r => .mul (embedQ l) (embedQ r)
  | .div l r => .div (embedQ l) (embedQ r)
  | .mod l r => .mod (embedQ l) (embedQ r)
  | .pow b e => .pow (embedQ b) (embedQ e)
  | .call1 name u => .call1 name (embedQ u)
  | .call2 name u v => .call2 name (embedQ u) (embedQ v)

/-! ### The computable mirror differentiator -/

/-- Mirror of `Deriv.Dbad` (the never-defined sentinel `1/0`). -/
def DQbad : QExpr := .div (.num 1 "1") (.num 0 "0")

/-- COMPUTABLE mirror of `Deriv.D`, rule for rule, including the token-text
reuse of the power rule (`.num (c-1) t` keeps the ORIGINAL token `t`, exactly
as `Deriv.D` does). -/
def DQ : QExpr → QExpr
  | .num _ _ => .num 0 "0"
  | .var name => if name = "x" then .num 1 "1" else .num 0 "0"
  | .constant _ => .num 0 "0"
  | .neg u => .neg (DQ u)
  | .add l r => .add (DQ l) (DQ r)
  | .sub l r => .sub (DQ l) (DQ r)
  | .mul l r => .add (.mul (DQ l) r) (.mul l (DQ r))
  | .div l r => .div (.sub (.mul (DQ l) r) (.mul l (DQ r))) (.pow r (.num 2 "2"))
  | .mod _ _ => DQbad
  | .pow b (.num c t) => .mul (.mul (.num c t) (.pow b (.num (c - 1) t))) (DQ b)
  | .pow _ _ => DQbad
  | .call1 name u =>
      if name = "sin" then .mul (.call1 "cos" u) (DQ u)
      else if name = "cos" then .neg (.mul (.call1 "sin" u) (DQ u))
      else if name = "atan" then .div (DQ u) (.add (.num 1 "1") (.pow u (.num 2 "2")))
      else if name = "sqrt" then .div (DQ u) (.mul (.num 2 "2") (.call1 "sqrt" u))
      else if name = "exp" then .mul (.call1 "exp" u) (DQ u)
      else if name = "ln" then .div (DQ u) u
      else DQbad
  | .call2 _ _ _ => DQbad

/-- Iterated mirror differentiator. -/
def DQiter : Nat → QExpr → QExpr
  | 0, q => q
  | k + 1, q => DQ (DQiter k q)

/-! ### Bridge 1: `embedQ` commutes with differentiation -/

@[simp] lemma embedQ_DQbad : embedQ DQbad = Deriv.Dbad := by
  simp [DQbad, Deriv.Dbad, embedQ]

/-- The computable mirror differentiator commutes with the embedding: the
embedded `DQ`-image IS the Lean differentiator's output, as an `Expr`
equality (values AND token texts). -/
theorem embedQ_DQ (q : QExpr) : embedQ (DQ q) = Deriv.D (embedQ q) := by
  induction q with
  | num c t => simp [DQ, embedQ, Deriv.D]
  | var name =>
      by_cases h : name = "x" <;> simp [DQ, embedQ, Deriv.D, h]
  | constant name => simp [DQ, embedQ, Deriv.D]
  | neg u ih => simp [DQ, embedQ, Deriv.D, ih]
  | add l r ihl ihr => simp [DQ, embedQ, Deriv.D, ihl, ihr]
  | sub l r ihl ihr => simp [DQ, embedQ, Deriv.D, ihl, ihr]
  | mul l r ihl ihr => simp [DQ, embedQ, Deriv.D, ihl, ihr]
  | div l r ihl ihr => simp [DQ, embedQ, Deriv.D, ihl, ihr]
  | mod l r _ _ => simp [DQ, embedQ, Deriv.D]
  | pow b e ihb ihe =>
      cases e with
      | num c t =>
          simp [DQ, embedQ, Deriv.D, ihb, Rat.cast_sub, Rat.cast_one]
      | var n => simp [DQ, embedQ, Deriv.D]
      | constant n => simp [DQ, embedQ, Deriv.D]
      | neg u => simp [DQ, embedQ, Deriv.D]
      | add l r => simp [DQ, embedQ, Deriv.D]
      | sub l r => simp [DQ, embedQ, Deriv.D]
      | mul l r => simp [DQ, embedQ, Deriv.D]
      | div l r => simp [DQ, embedQ, Deriv.D]
      | mod l r => simp [DQ, embedQ, Deriv.D]
      | pow bb ee => simp [DQ, embedQ, Deriv.D]
      | call1 nm u => simp [DQ, embedQ, Deriv.D]
      | call2 nm u v => simp [DQ, embedQ, Deriv.D]
  | call1 name u ihu =>
      by_cases h1 : name = "sin"
      · simp [DQ, embedQ, Deriv.D, h1, ihu]
      · by_cases h2 : name = "cos"
        · simp [DQ, embedQ, Deriv.D, h2, ihu]
        · by_cases h3 : name = "atan"
          · simp [DQ, embedQ, Deriv.D, h3, ihu]
          · by_cases h4 : name = "sqrt"
            · simp [DQ, embedQ, Deriv.D, h4, ihu]
            · by_cases h5 : name = "exp"
              · simp [DQ, embedQ, Deriv.D, h5, ihu]
              · by_cases h6 : name = "ln"
                · simp [DQ, embedQ, Deriv.D, h6, ihu]
                · simp [DQ, embedQ, Deriv.D, h1, h2, h3, h4, h5, h6]
  | call2 name u v _ _ => simp [DQ, embedQ, Deriv.D]

/-- Iterated form of the commuting bridge. -/
theorem embedQ_DQiter (k : Nat) (q : QExpr) :
    embedQ (DQiter k q) = Deriv.D^[k] (embedQ q) := by
  induction k with
  | zero => simp [DQiter]
  | succ n ih =>
      simp [DQiter, Function.iterate_succ_apply', embedQ_DQ, ih]

/-! ### Bridge 2: partial ℚ-reconstruction from certificate nodes -/

/-- ℚ-mirror of `Cert.buildExpr`, restricted to the SHADOW FRAGMENT ops.
Any node op outside the fragment yields `none` (fail closed). -/
def qbuildExpr : Nat → List Cert.Node → Nat → Option QExpr
  | 0, _, _ => none
  | fuel + 1, nodes, id =>
    match Cert.findNode nodes id with
    | none => none
    | some nd =>
      match nd.op, nd.children with
      | "num_exact", [] => some (.num nd.value nd.name)
      | "var", [] => some (.var nd.name)
      | "neg", [c0] => (qbuildExpr fuel nodes c0).map (.neg ·)
      | "powZero", [c0] =>
          (qbuildExpr fuel nodes c0).map (fun e => .pow e (.num (↑nd.n) nd.name))
      | "powEvenPos", [c0] =>
          (qbuildExpr fuel nodes c0).map (fun e => .pow e (.num (↑nd.n) nd.name))
      | "powOddPos", [c0] =>
          (qbuildExpr fuel nodes c0).map (fun e => .pow e (.num (↑nd.n) nd.name))
      | "sin_rat", [c0] => (qbuildExpr fuel nodes c0).map (.call1 "sin" ·)
      | "cos_rat", [c0] => (qbuildExpr fuel nodes c0).map (.call1 "cos" ·)
      | "sin", [c0] => (qbuildExpr fuel nodes c0).map (.call1 "sin" ·)
      | "cos", [c0] => (qbuildExpr fuel nodes c0).map (.call1 "cos" ·)
      | "add", [c0, c1] =>
          match qbuildExpr fuel nodes c0, qbuildExpr fuel nodes c1 with
          | some a, some b => some (.add a b) | _, _ => none
      | "sub", [c0, c1] =>
          match qbuildExpr fuel nodes c0, qbuildExpr fuel nodes c1 with
          | some a, some b => some (.sub a b) | _, _ => none
      | "mul", [c0, c1] =>
          match qbuildExpr fuel nodes c0, qbuildExpr fuel nodes c1 with
          | some a, some b => some (.mul a b) | _, _ => none
      | "div", [c0, c1] =>
          match qbuildExpr fuel nodes c0, qbuildExpr fuel nodes c1 with
          | some a, some b => some (.div a b) | _, _ => none
      | _, _ => none

/-- ℚ-mirror of `Cert.exprOf` on the shadow fragment. -/
def qexprOf (nodes : List Cert.Node) : Option QExpr :=
  match Cert.rootId nodes with
  | none => none
  | some rid => qbuildExpr (nodes.length + 1) nodes rid

/-- Agreement with `Cert.buildExpr`, in the one direction soundness needs:
a successful ℚ-reconstruction embeds to the canonical reconstruction. -/
theorem qbuild_embed (fuel : Nat) (nodes : List Cert.Node) (id : Nat)
    (q : QExpr) (hq : qbuildExpr fuel nodes id = some q) :
    Cert.buildExpr fuel nodes id = some (embedQ q) := by
  induction fuel generalizing id q with
  | zero => simp [qbuildExpr] at hq
  | succ fuel ih =>
      cases hfind : Cert.findNode nodes id with
      | none => simp [qbuildExpr, hfind] at hq
      | some nd =>
          simp only [qbuildExpr, hfind] at hq
          simp only [Cert.buildExpr, hfind]
          -- Split on the shadow-fragment op arms of the ℚ-mirror.
          split at hq
          all_goals (try (simp only [reduceCtorEq] at hq))
          -- num_exact
          · have hop : nd.op = "num_exact" := by assumption
            have hch : nd.children = [] := by assumption
            simp only [Option.some.injEq] at hq
            subst hq
            simp [hop, hch, embedQ]
          -- var
          · have hop : nd.op = "var" := by assumption
            have hch : nd.children = [] := by assumption
            simp only [Option.some.injEq] at hq
            subst hq
            simp [hop, hch, embedQ]
          -- neg
          · rename_i c0 hop heq
            have _check : nd.op = "neg" := hop
            simp only [Option.map_eq_some_iff] at hq
            obtain ⟨u, hu, rfl⟩ := hq
            simp [hop, heq, ih c0 u hu, embedQ]
          -- powZero
          · rename_i c0 hop heq
            have _check : nd.op = "powZero" := hop
            simp only [Option.map_eq_some_iff] at hq
            obtain ⟨u, hu, rfl⟩ := hq
            simp [hop, heq, ih c0 u hu, embedQ]
          -- powEvenPos
          · rename_i c0 hop heq
            have _check : nd.op = "powEvenPos" := hop
            simp only [Option.map_eq_some_iff] at hq
            obtain ⟨u, hu, rfl⟩ := hq
            simp [hop, heq, ih c0 u hu, embedQ]
          -- powOddPos
          · rename_i c0 hop heq
            have _check : nd.op = "powOddPos" := hop
            simp only [Option.map_eq_some_iff] at hq
            obtain ⟨u, hu, rfl⟩ := hq
            simp [hop, heq, ih c0 u hu, embedQ]
          -- sin_rat
          · rename_i c0 hop heq
            have _check : nd.op = "sin_rat" := hop
            simp only [Option.map_eq_some_iff] at hq
            obtain ⟨u, hu, rfl⟩ := hq
            simp [hop, heq, ih c0 u hu, embedQ]
          -- cos_rat
          · rename_i c0 hop heq
            have _check : nd.op = "cos_rat" := hop
            simp only [Option.map_eq_some_iff] at hq
            obtain ⟨u, hu, rfl⟩ := hq
            simp [hop, heq, ih c0 u hu, embedQ]
          -- sin
          · rename_i c0 hop heq
            have _check : nd.op = "sin" := hop
            simp only [Option.map_eq_some_iff] at hq
            obtain ⟨u, hu, rfl⟩ := hq
            simp [hop, heq, ih c0 u hu, embedQ, Cert.call1Names]
          -- cos
          · rename_i c0 hop heq
            have _check : nd.op = "cos" := hop
            simp only [Option.map_eq_some_iff] at hq
            obtain ⟨u, hu, rfl⟩ := hq
            simp [hop, heq, ih c0 u hu, embedQ, Cert.call1Names]
          -- add
          · rename_i c0 c1 hop heq
            have _check : nd.op = "add" := hop
            split at hq
            all_goals (try (simp only [reduceCtorEq] at hq))
            rename_i a b ha hb
            simp only [Option.some.injEq] at hq
            subst hq
            simp [hop, heq, ih c0 a ha, ih c1 b hb, embedQ]
          -- sub
          · rename_i c0 c1 hop heq
            have _check : nd.op = "sub" := hop
            split at hq
            all_goals (try (simp only [reduceCtorEq] at hq))
            rename_i a b ha hb
            simp only [Option.some.injEq] at hq
            subst hq
            simp [hop, heq, ih c0 a ha, ih c1 b hb, embedQ]
          -- mul
          · rename_i c0 c1 hop heq
            have _check : nd.op = "mul" := hop
            split at hq
            all_goals (try (simp only [reduceCtorEq] at hq))
            rename_i a b ha hb
            simp only [Option.some.injEq] at hq
            subst hq
            simp [hop, heq, ih c0 a ha, ih c1 b hb, embedQ]
          -- div
          · rename_i c0 c1 hop heq
            have _check : nd.op = "div" := hop
            split at hq
            all_goals (try (simp only [reduceCtorEq] at hq))
            rename_i a b ha hb
            simp only [Option.some.injEq] at hq
            subst hq
            simp [hop, heq, ih c0 a ha, ih c1 b hb, embedQ]

/-- Agreement at the root: a successful `qexprOf` embeds to `Cert.exprOf`. -/
theorem qexprOf_embed (nodes : List Cert.Node) (q : QExpr)
    (hq : qexprOf nodes = some q) :
    Cert.exprOf nodes = some (embedQ q) := by
  unfold qexprOf at hq
  unfold Cert.exprOf
  cases hrid : Cert.rootId nodes with
  | none => rw [hrid] at hq; exact absurd hq (by simp)
  | some rid =>
      rw [hrid] at hq
      exact qbuild_embed _ nodes rid q hq

end JackalIv.Shadow
