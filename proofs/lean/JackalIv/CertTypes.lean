/-
JackalIv/CertTypes.lean — the STRUCTURED certificate schema (schema v1) plus the
ℚ→ℝ reflection bridge that every downstream soundness step reduces to.

This is the shared contract described in `CERT_DESIGN.md`.  A certificate is a
`Header × List Node`, a FLAT node list (not a tree) so the determinism controls
(dup id, missing/unreachable node, cycle, reordered children) are expressible
and checkable.  All numeric fields are `ℚ` (canonical rationals) — the string
codec is a later phase; here we work with `Rat` directly.

This file provides, and PROVES, the ℚ→ℝ reflection lemmas:
  * `cast_padLo` / `cast_padHi` : the checker's rational pad casts to the model's
    real pad (`padLo`/`padHi` of `Model.lean`).
  * `algApproxQ` (a decidable `Bool`) + `cast_algApprox` : a `true` rational
    algebraic-approximation decision yields the model's `Approx` fact over ℝ.
  * `cast_min4` / `cast_max4` and the combined `cast_padLo_min4` /
    `cast_padHi_max4` for the four-corner mul/div/atan2/powNeg lanes.

It also defines the total, fail-closed `exprOf` reconstruction of the canonical
`Syntax.Expr` from the node tree, and `LibmModel` — the NAMED TCB: a `Prop`
hypothesis carrying exactly the transcendental (sqrt/exp/ln/atan/asin/acos/hypot/
powGeneral) `Approx`/stage facts the `Runs` constructors need.  `LibmModel` is a
hypothesis, NEVER a Lean axiom; the 23 rational-exact constructors need no TCB.

No `sorry`/`admit`/axiom/`native_decide`/`@[implemented_by]` on any trust path.
-/
import JackalIv.Syntax

namespace JackalIv.Cert

open JackalIv

/-! ### The certificate header -/

/-- Certificate header (all fields mandatory).  `input_lo/hi`, `output_lo/hi`
are canonical rationals; the string fields are opaque commitments/identity
checked at the release layer (§CERT_DESIGN). -/
structure Header where
  schema_version      : Nat
  model_const_version : String
  expr_commitment     : String
  source_commitment   : String
  input_lo            : ℚ
  input_hi            : ℚ
  root_id             : Nat
  output_lo           : ℚ
  output_hi           : ℚ
  exe_identity        : String
  status_class        : String
  deriving DecidableEq, Repr, Inhabited

/-! ### A certificate node

A single flat structure with op-specific `ℚ` fields (defaulting to `0`), tagged
by the `op` string.  Kept flat so `DecidableEq` derives cleanly and the checker
can switch on `op`.  Fields, by op family:

* every node: `out_lo, out_hi` (the node's IBox).
* `num_exact`/`num_rounded`: `value` (the intended real `r`), `name` (token);
  `num_rounded` also `fl_lo` (= the rounded float `fl`).
* `const_rounded`: `name` (constant name), `fl_lo` (= `fl`).
* `var`: `name` (= `"x"`).
* `add`/`sub`: `fl_lo, fl_hi`.
* `mul`/`div`/`atan2`: `p1..p4` (rounded corners); `div`/`atan2` also `den_sign`.
* `powZero`/`powEvenPos`/`powOddPos`: `n` (exponent), `name` (exponent token),
  `fl_lo, fl_hi`.
* `powNegEven`/`powNegOdd`: `n` (exponent magnitude), `name` (token), `fl_lo,
  fl_hi` (core), `p1..p4`, `den_sign`.
* `powGeneral`: two children (base, exp) + stage bounds `Ll,Lu,Ml,Mu,El,Eu`.
* `sqrt`/`exp`/`ln`/`atan`/`asin`/`acos`/`hypot`: `fl_lo, fl_hi`.
* `sin`/`cos`/`neg`/`abs`/`floor`/`ceil`/`round`/`trunc`/`min`/`max`: exact,
  no float fields. -/
structure Node where
  id       : Nat
  op       : String
  children : List Nat
  out_lo   : ℚ
  out_hi   : ℚ
  name     : String := ""
  value    : ℚ := 0
  fl_lo    : ℚ := 0
  fl_hi    : ℚ := 0
  p1       : ℚ := 0
  p2       : ℚ := 0
  p3       : ℚ := 0
  p4       : ℚ := 0
  den_sign : Int := 0
  n        : Nat := 0
  Ll       : ℚ := 0
  Lu       : ℚ := 0
  Ml       : ℚ := 0
  Mu       : ℚ := 0
  El       : ℚ := 0
  Eu       : ℚ := 0
  deriving DecidableEq, Repr, Inhabited

/-! ### Node lookup helpers -/

/-- Find the (first) node with the given id. -/
def findNode (nodes : List Node) (id : Nat) : Option Node :=
  nodes.find? (fun nd => nd.id == id)

/-- The out-interval (`out_lo`, `out_hi`) recorded at node `id`, if present. -/
def childOut (nodes : List Node) (id : Nat) : Option (ℚ × ℚ) :=
  (findNode nodes id).map (fun nd => (nd.out_lo, nd.out_hi))

/-- The root id: the maximum node id (under the well-formedness invariant
`child id < parent id` the root is the unique maximal node).  `none` if empty. -/
def rootId (nodes : List Node) : Option Nat :=
  match nodes with
  | []          => none
  | nd :: rest  => some (rest.foldl (fun acc m => max acc m.id) nd.id)

/-! ### Expression reconstruction (`exprOf`)

Total and fail-closed: any structural mismatch (missing node, wrong arity,
unsupported op) yields `none`.  Structurally decreasing on the `fuel` argument;
`fuel = nodes.length + 1` bounds the depth because every child id is strictly
below its parent id, so every root-to-leaf path visits distinct nodes. -/

/-- Unary call names that map to `Expr.call1 name ·`. -/
def call1Names : List String :=
  ["sqrt", "exp", "ln", "sin", "cos", "atan", "asin", "acos",
   "abs", "floor", "ceil", "round", "trunc"]

/-- Binary call names that map to `Expr.call2 name · ·`. -/
def call2Names : List String :=
  ["min", "max", "hypot", "atan2"]

/-- Build the `Expr` rooted at node `id`, with `fuel` recursion budget. -/
def buildExpr : Nat → List Node → Nat → Option Expr
  | 0, _, _ => none
  | fuel + 1, nodes, id =>
    match findNode nodes id with
    | none => none
    | some nd =>
      match nd.op, nd.children with
      -- leaves
      | "num_exact",    []  => some (.num (↑nd.value) nd.name)
      | "num_rounded",  []  => some (.num (↑nd.value) nd.name)
      | "const_rounded",[]  => some (.constant nd.name)
      | "var",          []  => some (.var nd.name)
      -- unary structural
      | "neg", [c0] => (buildExpr fuel nodes c0).map (.neg ·)
      -- integer power lanes: single child (base), exponent synthesized from `n`
      | "powZero",    [c0] => (buildExpr fuel nodes c0).map (fun e => .pow e (.num (↑nd.n) nd.name))
      | "powEvenPos", [c0] => (buildExpr fuel nodes c0).map (fun e => .pow e (.num (↑nd.n) nd.name))
      | "powOddPos",  [c0] => (buildExpr fuel nodes c0).map (fun e => .pow e (.num (↑nd.n) nd.name))
      | "powNegEven", [c0] => (buildExpr fuel nodes c0).map (fun e => .pow e (.neg (.num (↑nd.n) nd.name)))
      | "powNegOdd",  [c0] => (buildExpr fuel nodes c0).map (fun e => .pow e (.neg (.num (↑nd.n) nd.name)))
      -- sqrt_rat is a CHECKER-STRATEGY variant of sqrt (pure-ℚ, no libm TCB):
      -- the underlying expression is still `sqrt(x)`; the alternate op name only
      -- tells the checker which arm to use.
      | "sqrt_rat", [c0] => (buildExpr fuel nodes c0).map (.call1 "sqrt" ·)
      -- exp_rat is a CHECKER-STRATEGY variant of exp (pure-ℚ, no libm TCB):
      -- the underlying expression is still `exp(x)`; the alternate op name only
      -- tells the checker which arm to use.
      | "exp_rat", [c0] => (buildExpr fuel nodes c0).map (.call1 "exp" ·)
      -- binary structural
      | "add", [c0, c1] =>
          match buildExpr fuel nodes c0, buildExpr fuel nodes c1 with
          | some a, some b => some (.add a b) | _, _ => none
      | "sub", [c0, c1] =>
          match buildExpr fuel nodes c0, buildExpr fuel nodes c1 with
          | some a, some b => some (.sub a b) | _, _ => none
      | "mul", [c0, c1] =>
          match buildExpr fuel nodes c0, buildExpr fuel nodes c1 with
          | some a, some b => some (.mul a b) | _, _ => none
      | "div", [c0, c1] =>
          match buildExpr fuel nodes c0, buildExpr fuel nodes c1 with
          | some a, some b => some (.div a b) | _, _ => none
      | "powGeneral", [c0, c1] =>
          match buildExpr fuel nodes c0, buildExpr fuel nodes c1 with
          | some b, some ex => some (.pow b ex) | _, _ => none
      -- unary / binary string-named calls, and fail-closed default
      | op, ch =>
          if op ∈ call1Names then
            match ch with
            | [c0] => (buildExpr fuel nodes c0).map (.call1 op ·)
            | _    => none
          else if op ∈ call2Names then
            match ch with
            | [c0, c1] =>
                match buildExpr fuel nodes c0, buildExpr fuel nodes c1 with
                | some a, some b => some (.call2 op a b) | _, _ => none
            | _ => none
          else none

/-- Reconstruct the canonical `Expr` from the node list, rooted at the maximal
id.  Total; `none` on any structural failure (fail-closed). -/
def exprOf (nodes : List Node) : Option Expr :=
  match rootId nodes with
  | none     => none
  | some rid => buildExpr (nodes.length + 1) nodes rid

/-! ### The named libm TCB (`LibmModel`)

For each transcendental node, the exact `Approx`/stage facts its `Runs`
constructor requires, stated over ℝ against the recorded rational floats and the
children's recorded rational out-intervals.  Non-transcendental nodes (and any
malformed transcendental node whose children can't be resolved) contribute
`True`.  `LibmModel` is a HYPOTHESIS — the disclosed libm/rounding TCB — never a
Lean axiom.  The `Header` argument is carried for schema symmetry. -/

/-- The libm/stage obligation contributed by a single node.  (The
`const_rounded` declared-value fact — π/e/τ stored as a correctly-rounded f64,
irrational, hence not ℚ-decidable — lives in the companion `ConstTCB`, and both
are conjoined into the single named `ModelTCB` consumed by the soundness
theorems.) -/
def libmNodeFact (nodes : List Node) (nd : Node) : Prop :=
  match nd.op, nd.children with
  | "sqrt", [c0] =>
      match childOut nodes c0 with
      | some (l, u) =>
          Approx δlib σ0 (↑nd.fl_lo) (Real.sqrt (↑l)) ∧
          Approx δlib σ0 (↑nd.fl_hi) (Real.sqrt (↑u))
      | none => True
  | "exp", [c0] =>
      match childOut nodes c0 with
      | some (l, u) =>
          Approx δlib σ0 (↑nd.fl_lo) (Real.exp (↑l)) ∧
          Approx δlib σ0 (↑nd.fl_hi) (Real.exp (↑u))
      | none => True
  | "ln", [c0] =>
      match childOut nodes c0 with
      | some (l, u) =>
          Approx δlib σ0 (↑nd.fl_lo) (Real.log (↑l)) ∧
          Approx δlib σ0 (↑nd.fl_hi) (Real.log (↑u))
      | none => True
  | "atan", [c0] =>
      match childOut nodes c0 with
      | some (l, u) =>
          Approx δlib σ0 (↑nd.fl_lo) (Real.arctan (↑l)) ∧
          Approx δlib σ0 (↑nd.fl_hi) (Real.arctan (↑u))
      | none => True
  | "asin", [c0] =>
      match childOut nodes c0 with
      | some (l, u) =>
          Approx δlib σ0 (↑nd.fl_lo) (Real.arcsin (↑l)) ∧
          Approx δlib σ0 (↑nd.fl_hi) (Real.arcsin (↑u))
      | none => True
  | "acos", [c0] =>
      match childOut nodes c0 with
      | some (l, u) =>
          Approx δlib σ0 (↑nd.fl_lo) (Real.arccos (↑l)) ∧
          Approx δlib σ0 (↑nd.fl_hi) (Real.arccos (↑u))
      | none => True
  | "hypot", [c0, c1] =>
      match childOut nodes c0, childOut nodes c1 with
      | some (l₁, u₁), some (l₂, u₂) =>
          Approx δlib σ0 (↑nd.fl_lo)
            (Real.sqrt (mig (↑l₁) (↑u₁) ^ 2 + mig (↑l₂) (↑u₂) ^ 2)) ∧
          Approx δlib σ0 (↑nd.fl_hi)
            (Real.sqrt (mag (↑l₁) (↑u₁) ^ 2 + mag (↑l₂) (↑u₂) ^ 2))
      | _, _ => True
  | "powGeneral", [c0, c1] =>
      match childOut nodes c0, childOut nodes c1 with
      | some (xl, xu), some (yl, yu) =>
          (∀ t : ℝ, (↑xl) ≤ t → t ≤ (↑xu) →
              (↑nd.Ll) ≤ Real.log t ∧ Real.log t ≤ (↑nd.Lu)) ∧
          (∀ u v : ℝ, (↑yl) ≤ u → u ≤ (↑yu) → (↑nd.Ll) ≤ v → v ≤ (↑nd.Lu) →
              (↑nd.Ml) ≤ u * v ∧ u * v ≤ (↑nd.Mu)) ∧
          (∀ t : ℝ, (↑nd.Ml) ≤ t → t ≤ (↑nd.Mu) →
              (↑nd.El) ≤ Real.exp t ∧ Real.exp t ≤ (↑nd.Eu))
      | _, _ => True
  | _, _ => True

/-- The named libm/rounding TCB: the conjunction, over every node, of that
node's `libmNodeFact`.  A `Prop` hypothesis consumed by the soundness theorem;
never a Lean axiom. -/
def LibmModel (_hdr : Header) (nodes : List Node) : Prop :=
  ∀ nd ∈ nodes, libmNodeFact nodes nd

/-- Project the libm fact for a specific node out of `LibmModel`. -/
theorem LibmModel.fact {hdr : Header} {nodes : List Node} {nd : Node}
    (h : LibmModel hdr nodes) (hmem : nd ∈ nodes) : libmNodeFact nodes nd :=
  h nd hmem

/-! ### The ℚ→ℝ reflection bridge

The checker computes pads and approximation decisions over `ℚ`; these lemmas
transport those computations to the model's `ℝ` `padLo`/`padHi`/`Approx`. -/

/-- Rational relative pad (matches `Model.ε = 1/10^15`). -/
def εQ : ℚ := 1 / 10 ^ 15

/-- Rational absolute pad (matches `Model.τ = 1/10^300`). -/
def τQ : ℚ := 1 / 10 ^ 300

/-- Rational pad magnitude at `v` (matches `Model.pad`). -/
def padQ (v : ℚ) : ℚ := εQ * |v| + τQ

/-- Rational lower pad (matches `Model.padLo`). -/
def padLoQ (v : ℚ) : ℚ := v - padQ v

/-- Rational upper pad (matches `Model.padHi`). -/
def padHiQ (v : ℚ) : ℚ := v + padQ v

@[simp] lemma cast_εQ : ((εQ : ℚ) : ℝ) = ε := by
  unfold εQ ε; push_cast; ring

set_option exponentiation.threshold 400 in
@[simp] lemma cast_τQ : ((τQ : ℚ) : ℝ) = τ := by
  unfold τQ τ; push_cast; ring

/-- The rational pad casts to the model's real pad. -/
@[simp] lemma cast_padQ (v : ℚ) : ((padQ v : ℚ) : ℝ) = pad (↑v) := by
  unfold padQ pad
  rw [Rat.cast_add, Rat.cast_mul, Rat.cast_abs, cast_εQ, cast_τQ]

/-- REFLECTION: the checker's `padLoQ` casts to the model's `padLo`. -/
@[simp] lemma cast_padLo (v : ℚ) : ((padLoQ v : ℚ) : ℝ) = padLo (↑v) := by
  unfold padLoQ padLo
  rw [Rat.cast_sub, cast_padQ]

/-- REFLECTION: the checker's `padHiQ` casts to the model's `padHi`. -/
@[simp] lemma cast_padHi (v : ℚ) : ((padHiQ v : ℚ) : ℝ) = padHi (↑v) := by
  unfold padHiQ padHi
  rw [Rat.cast_add, cast_padQ]

/-- Decidable rational algebraic-approximation check: `|fl − r| ≤ δ·|r| + σ`. -/
def algApproxQ (fl r δ σ : ℚ) : Bool := decide (|fl - r| ≤ δ * |r| + σ)

/-- REFLECTION: a `true` rational approximation decision yields the model's
`Approx` fact over ℝ. -/
theorem cast_algApprox {fl r δ σ : ℚ} (h : algApproxQ fl r δ σ = true) :
    Approx (↑δ) (↑σ) (↑fl) (↑r) := by
  have hq : |fl - r| ≤ δ * |r| + σ := of_decide_eq_true h
  unfold Approx
  exact_mod_cast hq

/-- The four-corner rational min casts componentwise (mul/div/atan2/powNeg lo). -/
@[simp] lemma cast_min4 (a b c d : ℚ) :
    ((min (min a b) (min c d) : ℚ) : ℝ) = min (min (↑a) (↑b)) (min (↑c) (↑d)) := by
  simp only [Rat.cast_min]

/-- The four-corner rational max casts componentwise (mul/div/atan2/powNeg hi). -/
@[simp] lemma cast_max4 (a b c d : ℚ) :
    ((max (max a b) (max c d) : ℚ) : ℝ) = max (max (↑a) (↑b)) (max (↑c) (↑d)) := by
  simp only [Rat.cast_max]

/-- Combined: the padded four-corner min casts to the model's `padLo` of the
real four-corner min (the mul/div/atan2/powNeg lower endpoint). -/
lemma cast_padLo_min4 (a b c d : ℚ) :
    ((padLoQ (min (min a b) (min c d)) : ℚ) : ℝ)
      = padLo (min (min (↑a) (↑b)) (min (↑c) (↑d))) := by
  rw [cast_padLo, cast_min4]

/-- Combined: the padded four-corner max casts to the model's `padHi` of the
real four-corner max (the mul/div/atan2/powNeg upper endpoint). -/
lemma cast_padHi_max4 (a b c d : ℚ) :
    ((padHiQ (max (max a b) (max c d)) : ℚ) : ℝ)
      = padHi (max (max (↑a) (↑b)) (max (↑c) (↑d))) := by
  rw [cast_padHi, cast_max4]

/-! ### Convenience ℚ→ℝ cast simp lemmas (min/max/abs/neg)

Re-exported so downstream reflection `simp` sets can normalize freely. -/

@[simp] lemma cast_min' (a b : ℚ) : ((min a b : ℚ) : ℝ) = min (↑a) (↑b) := Rat.cast_min a b
@[simp] lemma cast_max' (a b : ℚ) : ((max a b : ℚ) : ℝ) = max (↑a) (↑b) := Rat.cast_max a b
@[simp] lemma cast_abs' (a : ℚ) : ((|a| : ℚ) : ℝ) = |(↑a : ℝ)| := Rat.cast_abs a
@[simp] lemma cast_neg' (a : ℚ) : ((-a : ℚ) : ℝ) = -(↑a : ℝ) := Rat.cast_neg a

end JackalIv.Cert
