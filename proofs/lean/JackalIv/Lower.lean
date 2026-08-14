/-
JackalIv/Lower.lean — the LOWERING pass `lower : Expr → Option Expr`, a faithful
model of the engine's `simplify_bound` (jackal_calc.anb), together with its two
soundness theorems.

## Engine correspondence (`jackal_calc.anb`, fn `simplify_bound`)

`simplify_bound` is a bottom-up rewrite that performs a small fixed set of
algebraic identity simplifications.  Crucially it does NOT fold `num`–`num`
arithmetic (a deliberate soundness fix — `0 * x` is NOT folded either), and it
REFUSES a literal division/modulo by zero (the engine panics
"literal division by zero"; modeled here as `lower` returning `none`).

The rules, mirrored constructor-for-constructor below:

* `num` / `var` / `const` → unchanged.
* `neg u`: `u' = lower u`; if `u'` is `neg w` → `w` (neg-neg collapse);
  else `neg u'`.  (No folding of `neg (num …)`.)
* `call(name, args)`: lower each argument, rebuild the same call.  (No call
  simplification.)
* binary `tag l r`: `l' = lower l`, `r' = lower r`; then
  - `div`/`mod` with `r' = (num 0)` → REFUSE (`none`);
  - `add`: `l' = (num 0)` → `r'`; `r' = (num 0)` → `l'`;
  - `sub`: `r' = (num 0)` → `l'`; `l' = (num 0)` → `lower (neg r')`;
  - `mul`: `l' = (num 1)` → `r'`; `r' = (num 1)` → `l'`;
  - `div`: `r' = (num 1)` → `l'`;
  - `pow`: `r' = (num 1)` → `l'`;
  - else → `tag l' r'`.

The "is `(num v)`" tests inspect the num node's REAL value `r` (Syntax.lean's
`sem` ignores the token text), so `(num 0 "0")` and `(num 0 "0.0")` both match
`v = 0`; this is captured by `numVal?` returning the stored real.

## Theorems

* `lower_preserves_sem`   — lowering preserves the real semantics on the
  defined domain.  Every rewrite is a semantic identity: `neg (neg u) = u`;
  `0 + u = u`; `u + 0 = u`; `u - 0 = u`; `0 - u = -u`; `1 * u = u`;
  `u * 1 = u`; `u / 1 = u`; `u ^ 1 = u` (via `Real.rpow_one`).  The literal
  div/mod-by-zero cases are vacuous (`lower` returns `none`).
* `lower_preserves_defined` — lowering preserves structural definedness (each
  rule only drops a provably-total subterm).

None of the rewrite identities needs a side condition beyond `DefinedOn`: the
`u / 1 = u` and `u ^ 1 = u` identities hold unconditionally in `ℝ` (`div_one`,
`Real.rpow_one`), and the `num`-`num` non-folding means no new refusal is
introduced.  So both theorems carry exactly `DefinedOn` as their hypothesis.
-/
import JackalIv.Syntax

namespace JackalIv

open Classical

/-! ### Numeric-literal probe

`numVal? e` extracts the stored real value of a `num` node (ignoring its token
text) and is `none` on every non-`num` node.  The engine's "is `(num v)`" tests
become `numVal? e = some v` on the real value `v`. -/

/-- The stored real value of a `num` node, `none` otherwise. -/
noncomputable def numVal? : Expr → Option ℝ
  | .num r _ => some r
  | _ => none

/-- If a node probes as the literal `v`, its semantics at every point is `v`. -/
lemma sem_of_numVal {e : Expr} {v x : ℝ} (h : numVal? e = some v) : sem e x = v := by
  cases e with
  | num r t => simp only [numVal?, Option.some.injEq] at h; subst h; rfl
  | _ => simp [numVal?] at h

/-! ### The neg-collapse smart constructor -/

/-- Single neg-neg collapse on an already-lowered term:
`lowerNeg (neg w) = w`, else `neg u`. -/
def lowerNeg : Expr → Expr
  | .neg w => w
  | u => .neg u

/-- `lowerNeg` is semantically negation. -/
lemma sem_lowerNeg (e : Expr) (x : ℝ) : sem (lowerNeg e) x = -(sem e x) := by
  cases e with
  | neg w => simp only [lowerNeg, sem, neg_neg]
  | _ => rfl

/-- `lowerNeg` preserves definedness (both branches are defeq to `neg`'s guard). -/
lemma def_lowerNeg {e : Expr} {x : ℝ} (h : DefinedOn e x) : DefinedOn (lowerNeg e) x := by
  cases e <;> exact h

/-! ### Binary smart constructors (operating on already-lowered children) -/

/-- `add` with the identity-elimination rules. -/
noncomputable def lowerAdd (l r : Expr) : Expr :=
  if numVal? l = some 0 then r
  else if numVal? r = some 0 then l
  else .add l r

/-- `sub` with `x - 0 = x` and `0 - x = -x`. -/
noncomputable def lowerSub (l r : Expr) : Expr :=
  if numVal? r = some 0 then l
  else if numVal? l = some 0 then lowerNeg r
  else .sub l r

/-- `mul` with the unit-elimination rules. -/
noncomputable def lowerMul (l r : Expr) : Expr :=
  if numVal? l = some 1 then r
  else if numVal? r = some 1 then l
  else .mul l r

/-- `div`: literal division by zero REFUSES (`none`); `x / 1 = x`. -/
noncomputable def lowerDiv (l r : Expr) : Option Expr :=
  if numVal? r = some 0 then none
  else if numVal? r = some 1 then some l
  else some (.div l r)

/-- `mod`: literal modulo by zero REFUSES (`none`); no other simplification. -/
noncomputable def lowerMod (l r : Expr) : Option Expr :=
  if numVal? r = some 0 then none
  else some (.mod l r)

/-- `pow`: `x ^ 1 = x`. -/
noncomputable def lowerPow (b e : Expr) : Expr :=
  if numVal? e = some 1 then b
  else .pow b e

/-! #### Semantic identities of the smart constructors -/

lemma sem_lowerAdd (l r : Expr) (x : ℝ) : sem (lowerAdd l r) x = sem l x + sem r x := by
  unfold lowerAdd
  split_ifs with h1 h2
  · have hl := sem_of_numVal (x := x) h1; rw [hl, zero_add]
  · have hr := sem_of_numVal (x := x) h2; rw [hr, add_zero]
  · rfl

lemma sem_lowerSub (l r : Expr) (x : ℝ) : sem (lowerSub l r) x = sem l x - sem r x := by
  unfold lowerSub
  split_ifs with h1 h2
  · have hr := sem_of_numVal (x := x) h1; rw [hr, sub_zero]
  · have hl := sem_of_numVal (x := x) h2; rw [sem_lowerNeg, hl, zero_sub]
  · rfl

lemma sem_lowerMul (l r : Expr) (x : ℝ) : sem (lowerMul l r) x = sem l x * sem r x := by
  unfold lowerMul
  split_ifs with h1 h2
  · have hl := sem_of_numVal (x := x) h1; rw [hl, one_mul]
  · have hr := sem_of_numVal (x := x) h2; rw [hr, mul_one]
  · rfl

lemma sem_lowerDiv (l r : Expr) (x : ℝ) :
    ∀ res, lowerDiv l r = some res → sem res x = sem l x / sem r x := by
  intro res hres
  unfold lowerDiv at hres
  by_cases h1 : numVal? r = some 0
  · rw [if_pos h1] at hres; exact absurd hres (by simp)
  · rw [if_neg h1] at hres
    by_cases h2 : numVal? r = some 1
    · rw [if_pos h2, Option.some.injEq] at hres; subst res
      have hr := sem_of_numVal (x := x) h2; rw [hr, div_one]
    · rw [if_neg h2, Option.some.injEq] at hres; subst res; rfl

lemma sem_lowerPow (b e : Expr) (x : ℝ) : sem (lowerPow b e) x = (sem b x) ^ (sem e x) := by
  unfold lowerPow
  split_ifs with h1
  · have he := sem_of_numVal (x := x) h1; rw [he, Real.rpow_one]
  · rfl

/-! #### Definedness preservation of the smart constructors -/

lemma def_lowerAdd {l r : Expr} {x : ℝ} (hl : DefinedOn l x) (hr : DefinedOn r x) :
    DefinedOn (lowerAdd l r) x := by
  unfold lowerAdd
  split_ifs with h1 h2
  · exact hr
  · exact hl
  · exact ⟨hl, hr⟩

lemma def_lowerSub {l r : Expr} {x : ℝ} (hl : DefinedOn l x) (hr : DefinedOn r x) :
    DefinedOn (lowerSub l r) x := by
  unfold lowerSub
  split_ifs with h1 h2
  · exact hl
  · exact def_lowerNeg hr
  · exact ⟨hl, hr⟩

lemma def_lowerMul {l r : Expr} {x : ℝ} (hl : DefinedOn l x) (hr : DefinedOn r x) :
    DefinedOn (lowerMul l r) x := by
  unfold lowerMul
  split_ifs with h1 h2
  · exact hr
  · exact hl
  · exact ⟨hl, hr⟩

lemma def_lowerDiv {l r : Expr} {x : ℝ} (hl : DefinedOn l x) (hr : DefinedOn r x)
    (hne : sem r x ≠ 0) : ∀ res, lowerDiv l r = some res → DefinedOn res x := by
  intro res hres
  unfold lowerDiv at hres
  by_cases h1 : numVal? r = some 0
  · rw [if_pos h1] at hres; exact absurd hres (by simp)
  · rw [if_neg h1] at hres
    by_cases h2 : numVal? r = some 1
    · rw [if_pos h2, Option.some.injEq] at hres; subst res; exact hl
    · rw [if_neg h2, Option.some.injEq] at hres; subst res; exact ⟨hl, hr, hne⟩

lemma def_lowerPow {b e : Expr} {x : ℝ} (hb : DefinedOn b x) (he : DefinedOn e x)
    (hpd : powDom (sem b x) (sem e x)) : DefinedOn (lowerPow b e) x := by
  unfold lowerPow
  split_ifs with h1
  · exact hb
  · exact ⟨hb, he, hpd⟩

/-! ### The lowering pass -/

/-- `lower e` mirrors `simplify_bound` EXACTLY: a bottom-up algebraic-identity
simplifier that returns `none` iff the run hits a literal division/modulo by a
`(num 0)` (the engine's fail-closed refusal). -/
noncomputable def lower : Expr → Option Expr
  | .num r t => some (.num r t)
  | .var n => some (.var n)
  | .constant n => some (.constant n)
  | .neg u =>
      match lower u with
      | some u' => some (lowerNeg u')
      | none => none
  | .add l r =>
      match lower l, lower r with
      | some l', some r' => some (lowerAdd l' r')
      | _, _ => none
  | .sub l r =>
      match lower l, lower r with
      | some l', some r' => some (lowerSub l' r')
      | _, _ => none
  | .mul l r =>
      match lower l, lower r with
      | some l', some r' => some (lowerMul l' r')
      | _, _ => none
  | .div l r =>
      match lower l, lower r with
      | some l', some r' => lowerDiv l' r'
      | _, _ => none
  | .mod l r =>
      match lower l, lower r with
      | some l', some r' => lowerMod l' r'
      | _, _ => none
  | .pow b e =>
      match lower b, lower e with
      | some b', some e' => some (lowerPow b' e')
      | _, _ => none
  | .call1 name u =>
      match lower u with
      | some u' => some (.call1 name u')
      | none => none
  | .call2 name u v =>
      match lower u, lower v with
      | some u', some v' => some (.call2 name u' v')
      | _, _ => none

/-! ### Soundness: lowering preserves the real semantics -/

/-- KEY THEOREM.  On the defined domain, lowering preserves the exact real
semantics: whenever `lower e = some res`, `sem res x = sem e x`. -/
theorem lower_preserves_sem (e : Expr) :
    ∀ (x : ℝ), DefinedOn e x → ∀ res, lower e = some res → sem res x = sem e x := by
  induction e with
  | num r t =>
    intro x _ res hres
    simp only [lower, Option.some.injEq] at hres; subst hres; rfl
  | var n =>
    intro x _ res hres
    simp only [lower, Option.some.injEq] at hres; subst hres; rfl
  | constant n =>
    intro x _ res hres
    simp only [lower, Option.some.injEq] at hres; subst hres; rfl
  | neg u ih =>
    intro x hdef res hres
    have hdu : DefinedOn u x := hdef
    cases hlu : lower u with
    | none => simp [lower, hlu] at hres
    | some u' =>
      simp only [lower, hlu, Option.some.injEq] at hres
      subst hres
      rw [sem_lowerNeg, ih x hdu u' hlu]
      rfl
  | add l r ihl ihr =>
    intro x hdef res hres
    obtain ⟨hdl, hdr⟩ := hdef
    cases hll : lower l with
    | none => simp [lower, hll] at hres
    | some l' =>
      cases hrr : lower r with
      | none => simp [lower, hll, hrr] at hres
      | some r' =>
        simp only [lower, hll, hrr, Option.some.injEq] at hres
        subst hres
        rw [sem_lowerAdd, ihl x hdl l' hll, ihr x hdr r' hrr]
        rfl
  | sub l r ihl ihr =>
    intro x hdef res hres
    obtain ⟨hdl, hdr⟩ := hdef
    cases hll : lower l with
    | none => simp [lower, hll] at hres
    | some l' =>
      cases hrr : lower r with
      | none => simp [lower, hll, hrr] at hres
      | some r' =>
        simp only [lower, hll, hrr, Option.some.injEq] at hres
        subst hres
        rw [sem_lowerSub, ihl x hdl l' hll, ihr x hdr r' hrr]
        rfl
  | mul l r ihl ihr =>
    intro x hdef res hres
    obtain ⟨hdl, hdr⟩ := hdef
    cases hll : lower l with
    | none => simp [lower, hll] at hres
    | some l' =>
      cases hrr : lower r with
      | none => simp [lower, hll, hrr] at hres
      | some r' =>
        simp only [lower, hll, hrr, Option.some.injEq] at hres
        subst hres
        rw [sem_lowerMul, ihl x hdl l' hll, ihr x hdr r' hrr]
        rfl
  | div l r ihl ihr =>
    intro x hdef res hres
    obtain ⟨hdl, hdr, hne⟩ := hdef
    cases hll : lower l with
    | none => simp [lower, hll] at hres
    | some l' =>
      cases hrr : lower r with
      | none => simp [lower, hll, hrr] at hres
      | some r' =>
        simp only [lower, hll, hrr] at hres
        have hsem := sem_lowerDiv l' r' x res hres
        rw [hsem, ihl x hdl l' hll, ihr x hdr r' hrr]
        rfl
  | mod l r ihl ihr =>
    intro x hdef res hres
    exact hdef.elim
  | pow b e ihb ihe =>
    intro x hdef res hres
    obtain ⟨hdb, hde, hpd⟩ := hdef
    cases hlb : lower b with
    | none => simp [lower, hlb] at hres
    | some b' =>
      cases hle : lower e with
      | none => simp [lower, hlb, hle] at hres
      | some e2 =>
        simp only [lower, hlb, hle, Option.some.injEq] at hres
        subst hres
        rw [sem_lowerPow, ihb x hdb b' hlb, ihe x hde e2 hle]
        rfl
  | call1 name u ih =>
    intro x hdef res hres
    obtain ⟨hdu, hcd⟩ := hdef
    cases hlu : lower u with
    | none => simp [lower, hlu] at hres
    | some u' =>
      simp only [lower, hlu, Option.some.injEq] at hres
      subst hres
      simp only [sem]
      rw [ih x hdu u' hlu]
  | call2 name u v ihu ihv =>
    intro x hdef res hres
    obtain ⟨hdu, hdv, hcd⟩ := hdef
    cases hlu : lower u with
    | none => simp [lower, hlu] at hres
    | some u' =>
      cases hlv : lower v with
      | none => simp [lower, hlu, hlv] at hres
      | some v' =>
        simp only [lower, hlu, hlv, Option.some.injEq] at hres
        subst hres
        simp only [sem]
        rw [ihu x hdu u' hlu, ihv x hdv v' hlv]

/-! ### Soundness: lowering preserves definedness -/

/-- Lowering preserves structural definedness: whenever `lower e = some res`,
`DefinedOn res x` holds wherever `DefinedOn e x` did. -/
theorem lower_preserves_defined (e : Expr) :
    ∀ (x : ℝ), DefinedOn e x → ∀ res, lower e = some res → DefinedOn res x := by
  induction e with
  | num r t =>
    intro x _ res hres
    simp only [lower, Option.some.injEq] at hres; subst hres; trivial
  | var n =>
    intro x hdef res hres
    simp only [lower, Option.some.injEq] at hres; subst hres; exact hdef
  | constant n =>
    intro x _ res hres
    simp only [lower, Option.some.injEq] at hres; subst hres; trivial
  | neg u ih =>
    intro x hdef res hres
    have hdu : DefinedOn u x := hdef
    cases hlu : lower u with
    | none => simp [lower, hlu] at hres
    | some u' =>
      simp only [lower, hlu, Option.some.injEq] at hres
      subst hres
      exact def_lowerNeg (ih x hdu u' hlu)
  | add l r ihl ihr =>
    intro x hdef res hres
    obtain ⟨hdl, hdr⟩ := hdef
    cases hll : lower l with
    | none => simp [lower, hll] at hres
    | some l' =>
      cases hrr : lower r with
      | none => simp [lower, hll, hrr] at hres
      | some r' =>
        simp only [lower, hll, hrr, Option.some.injEq] at hres
        subst hres
        exact def_lowerAdd (ihl x hdl l' hll) (ihr x hdr r' hrr)
  | sub l r ihl ihr =>
    intro x hdef res hres
    obtain ⟨hdl, hdr⟩ := hdef
    cases hll : lower l with
    | none => simp [lower, hll] at hres
    | some l' =>
      cases hrr : lower r with
      | none => simp [lower, hll, hrr] at hres
      | some r' =>
        simp only [lower, hll, hrr, Option.some.injEq] at hres
        subst hres
        exact def_lowerSub (ihl x hdl l' hll) (ihr x hdr r' hrr)
  | mul l r ihl ihr =>
    intro x hdef res hres
    obtain ⟨hdl, hdr⟩ := hdef
    cases hll : lower l with
    | none => simp [lower, hll] at hres
    | some l' =>
      cases hrr : lower r with
      | none => simp [lower, hll, hrr] at hres
      | some r' =>
        simp only [lower, hll, hrr, Option.some.injEq] at hres
        subst hres
        exact def_lowerMul (ihl x hdl l' hll) (ihr x hdr r' hrr)
  | div l r ihl ihr =>
    intro x hdef res hres
    obtain ⟨hdl, hdr, hne⟩ := hdef
    cases hll : lower l with
    | none => simp [lower, hll] at hres
    | some l' =>
      cases hrr : lower r with
      | none => simp [lower, hll, hrr] at hres
      | some r' =>
        simp only [lower, hll, hrr] at hres
        have hsr : sem r' x = sem r x := lower_preserves_sem r x hdr r' hrr
        have hne' : sem r' x ≠ 0 := by rw [hsr]; exact hne
        exact def_lowerDiv (ihl x hdl l' hll) (ihr x hdr r' hrr) hne' res hres
  | mod l r ihl ihr =>
    intro x hdef res hres
    exact hdef.elim
  | pow b e ihb ihe =>
    intro x hdef res hres
    obtain ⟨hdb, hde, hpd⟩ := hdef
    cases hlb : lower b with
    | none => simp [lower, hlb] at hres
    | some b' =>
      cases hle : lower e with
      | none => simp [lower, hlb, hle] at hres
      | some e2 =>
        simp only [lower, hlb, hle, Option.some.injEq] at hres
        subst hres
        have hsb : sem b' x = sem b x := lower_preserves_sem b x hdb b' hlb
        have hse : sem e2 x = sem e x := lower_preserves_sem e x hde e2 hle
        have hpd' : powDom (sem b' x) (sem e2 x) := by rw [hsb, hse]; exact hpd
        exact def_lowerPow (ihb x hdb b' hlb) (ihe x hde e2 hle) hpd'
  | call1 name u ih =>
    intro x hdef res hres
    obtain ⟨hdu, hcd⟩ := hdef
    cases hlu : lower u with
    | none => simp [lower, hlu] at hres
    | some u' =>
      simp only [lower, hlu, Option.some.injEq] at hres
      subst hres
      have hsu : sem u' x = sem u x := lower_preserves_sem u x hdu u' hlu
      refine ⟨ih x hdu u' hlu, ?_⟩
      rw [hsu]; exact hcd
  | call2 name u v ihu ihv =>
    intro x hdef res hres
    obtain ⟨hdu, hdv, hcd⟩ := hdef
    cases hlu : lower u with
    | none => simp [lower, hlu] at hres
    | some u' =>
      cases hlv : lower v with
      | none => simp [lower, hlu, hlv] at hres
      | some v' =>
        simp only [lower, hlu, hlv, Option.some.injEq] at hres
        subst hres
        have hsu : sem u' x = sem u x := lower_preserves_sem u x hdu u' hlu
        have hsv : sem v' x = sem v x := lower_preserves_sem v x hdv v' hlv
        refine ⟨ihu x hdu u' hlu, ihv x hdv v' hlv, ?_⟩
        rw [hsu, hsv]; exact hcd

#print axioms lower_preserves_sem
#print axioms lower_preserves_defined

end JackalIv
