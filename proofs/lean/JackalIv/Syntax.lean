/-
JackalIv/Syntax.lean — the SINGLE canonical expression syntax.

This file replaces the two duplicate `Expr`/`sem`/`DefinedOn` copies that
previously lived, incompatibly, inside `Embed.lean` (namespace `JackalIv`)
and `Deriv.lean` (namespace `JackalIv.Deriv`).  Everything downstream — the
composition theorem `runs_encloses` (Embed) and the differentiator
correctness `deriv_correct_on` / the C^k ladder (Deriv) — is now stated
against this one `Expr`.

## Engine AST correspondence (`jackal_calc.anb`, fn `ieval`, fn `deriv`,
fns `ast_parse_*`).  The parser (`ast_parse_atom` … `ast_parse_expr`)
produces these node shapes, mirrored 1:1 by the constructors below:

| engine AST node                     | canonical constructor                 |
|-------------------------------------|---------------------------------------|
| `["num", value, text]`              | `num (r : ℝ) (t : String)`            |
| `["var", name]`                     | `var (name : String)`                 |
| `["const", name]`                   | `constant (name : String)`            |
| `["neg", u]`                        | `neg u`                               |
| `["add"/"sub"/"mul"/"div"/"mod", l, r]` | `add`/`sub`/`mul`/`div`/`mod l r` |
| `["pow", base, exponent]`           | `pow base exponent`                   |
| `["call", name, [u]]`   (unary)     | `call1 name u`                        |
| `["call", name, [u, v]]` (binary)   | `call2 name u v`                      |

`num` carries BOTH the real value `r` (consumed by `sem`/`DefinedOn`) and
the original token text `t` (consumed only by the later parser-correspondence
s-expr dump — `ast_sexp` serializes `(num t)`).  `sem`/`DefinedOn` ignore `t`.

The engine keeps `pow` as a genuinely BINARY node and decides at runtime
(`ieval` lines: `right.lo == right.hi && right.lo == trunc(right.lo) && …`)
whether to take the integer lane (`iv_pow_int`) or the general lane
(`iv_pow_general`).  Mirroring that, `pow` here is binary; the
integer-exponent specialization is a SEMANTIC decision made in the `Runs`
constructors (Embed.lean), never a syntactic one.  `call1`/`call2` split the
engine's single list-argument `call` node by structural arity, so induction
over `Expr` is clean (no list recursion).

## `sem` — total real semantics.
`sem` is total, junk-totalized exactly as Mathlib totalizes the partial
functions: `x / 0 = 0`; `Real.sqrt`/`Real.log`/`Real.logb` of an
out-of-domain argument is their Mathlib junk value; `pow` is `Real.rpow`
(the `ℝ ^ ℝ` instance).  `Real.rpow` agrees with the engine's integer lane
for EVERY base via `Real.rpow_intCast` / `Real.rpow_natCast`, and with the
engine's general lane (`exp(e·ln b)`, positive base) via
`Real.rpow_def_of_pos` — so both lanes' proofs (Pow.lean) port unchanged.
Unknown `call` names dispatch to the junk default `0`.

## `DefinedOn` — the structural shadow of `ieval`'s refusal guards.
Mirrors the `iv_bad` conditions of `ieval` precisely (engine `fn ieval` and
the `iv_*` helpers it calls):

* `div`/`mod`: `iv_div` refuses a denominator interval straddling zero →
  pointwise `sem r x ≠ 0`; `mod` is refused unconditionally by the engine
  (`iv_bad("'%' has no certified interval model")`) → `False`.
* `pow`: `iv_pow_int` accepts any base but needs a nonzero base under a
  negative integer exponent (its `iv_div(1, core)` lane); `iv_pow_general`
  needs a strictly positive base.  `powDom b e` = `0 < b ∨ (e is an integer
  n ∧ (n < 0 → b ≠ 0))` captures exactly the union of both accepted domains
  (= where `Real.rpow` equals the genuine value).
* `call1`: `iv_sqrt` refuses arg < 0 → `0 ≤ v`; `iv_ln`/`iv_log10`/`iv_log2`
  refuse arg ≤ 0 → `0 < v`; `iv_asin`/`iv_acos` refuse arg ∉ [-1,1] →
  `-1 ≤ v ∧ v ≤ 1`; `iv_tan` refuses an interval that may contain a pole
  (`crit_in` near π/2 + kπ) → pointwise `Real.cos v ≠ 0`; sin/cos/atan/exp/
  abs/floor/ceil/round/trunc are total.  `cbrt` and every unknown name are
  fail-closed (`False`): see "not yet embedded" below.
* `call2`: `iv_atan2` refuses `x.lo ≤ 0` → pointwise `0 < v` (the x-argument);
  `iv_hypot`/`iv_min`/`iv_max` are total; `pow` (the function-call spelling)
  reuses `powDom`.

## Fail-closed coverage (Step-3 status; every `Expr` node with no `Runs`
constructor in Embed.lean is a sound refusal — the composition theorem
simply has no derivation for it).

* WIRED into `Runs` (Embed.lean): num, var, constant, neg, add, sub, mul,
  div, pow (integer lanes: 0 / even≥2 / odd≥1 / negative even / negative odd;
  general positive-base lane), sqrt, exp, ln, sin, cos, atan, asin, acos,
  abs, floor, ceil, round, trunc, hypot, min, max, atan2 (guarded x > 0).
* NOT YET EMBEDDED (fail-closed, no `Runs` constructor, `DefinedOn` = False):
  - `tan` — Trig.lean proves the sin/cos hull soundness but no `iv_tan`
    containment lemma exists yet; `DefinedOn (tan …)` = `cos v ≠ 0` records
    the pole guard for the future wiring, but there is no derivation.
  - `cbrt` — no Mathlib real cube root and no containment instance; `sem`
    returns the junk default `0` and `DefinedOn` is `False`.
  - `log10` / `log2` — only the GENERIC `iv_monotone_encloses` covers them
    (no direct instance lemma in Monotone.lean); left fail-closed rather
    than carry a bespoke monotonicity hypothesis.
  - `mod` — refused by the engine itself; `DefinedOn` = `False`.
* Differentiator (`D`, Deriv.lean) has rules only for the smooth core it
  had before (num/const/var/neg/add/sub/mul/div, the num-literal power rule,
  sqrt/exp/ln/sin/cos/atan); every other node maps to a never-defined
  sentinel, so it is outside `D`'s domain (fail-closed), never mis-differentiated.
-/
import JackalIv.Model
import JackalIv.Pad
import JackalIv.Arith
import JackalIv.Monotone
import JackalIv.Exact
import JackalIv.Pow
import JackalIv.Trig

namespace JackalIv

/-! ### The canonical expression AST -/

/-- Canonical expression syntax mirroring the engine AST 1:1 (see file header
for the node↔constructor table). -/
inductive Expr : Type
  | num (r : ℝ) (t : String)
  | var (name : String)
  | constant (name : String)
  | neg (u : Expr)
  | add (l r : Expr)
  | sub (l r : Expr)
  | mul (l r : Expr)
  | div (l r : Expr)
  | mod (l r : Expr)
  | pow (base exponent : Expr)
  | call1 (name : String) (u : Expr)
  | call2 (name : String) (u v : Expr)
  deriving Inhabited

/-! ### Named-constant values

`constant_value(name)` in the engine returns a correctly-rounded f64 of a
mathematical constant.  The model only needs a total, `x`-independent real
here; a few known names are pinned and everything else defaults to `0`. -/
noncomputable def constValue (name : String) : ℝ :=
  if name = "pi" then Real.pi
  else if name = "e" then Real.exp 1
  else if name = "tau" then 2 * Real.pi
  else 0

/-! ### Unary / binary call semantics (string-dispatched) -/

/-- Real semantics of a unary `call`.  Dispatch mirrors `ieval`'s unary
branch; `cbrt` and unknown names return the junk default `0`. -/
noncomputable def call1Sem (name : String) (v : ℝ) : ℝ :=
  if name = "sin" then Real.sin v
  else if name = "cos" then Real.cos v
  else if name = "tan" then Real.tan v
  else if name = "asin" then Real.arcsin v
  else if name = "acos" then Real.arccos v
  else if name = "atan" then Real.arctan v
  else if name = "sqrt" then Real.sqrt v
  else if name = "ln" then Real.log v
  else if name = "log10" then Real.logb 10 v
  else if name = "log2" then Real.logb 2 v
  else if name = "exp" then Real.exp v
  else if name = "abs" then |v|
  else if name = "floor" then ((⌊v⌋ : ℤ) : ℝ)
  else if name = "ceil" then ((⌈v⌉ : ℤ) : ℝ)
  else if name = "round" then roundAway v
  else if name = "trunc" then truncR v
  else 0

/-- Real semantics of a binary `call`.  `atan2 u v = arctan (u / v)` on the
positive-`v` half-plane (the engine's guarded lane); `pow` reuses `Real.rpow`. -/
noncomputable def call2Sem (name : String) (u v : ℝ) : ℝ :=
  if name = "hypot" then Real.sqrt (u ^ 2 + v ^ 2)
  else if name = "atan2" then Real.arctan (u / v)
  else if name = "min" then min u v
  else if name = "max" then max u v
  else if name = "pow" then u ^ v
  else 0

/-- Total real semantics of a canonical expression (junk-totalized; see
header).  `pow` is `Real.rpow` (the `ℝ ^ ℝ` instance). -/
noncomputable def sem : Expr → ℝ → ℝ
  | .num r _, _ => r
  | .var name, x => if name = "x" then x else 0
  | .constant name, _ => constValue name
  | .neg u, x => -(sem u x)
  | .add l r, x => sem l x + sem r x
  | .sub l r, x => sem l x - sem r x
  | .mul l r, x => sem l x * sem r x
  | .div l r, x => sem l x / sem r x
  | .mod l r, x => sem l x - sem r x * ((⌊sem l x / sem r x⌋ : ℤ) : ℝ)
  | .pow b e, x => (sem b x) ^ (sem e x)
  | .call1 name u, x => call1Sem name (sem u x)
  | .call2 name u v, x => call2Sem name (sem u x) (sem v x)

/-! ### Definedness guards -/

/-- `pow` domain guard: strictly positive base (general lane), or an integer
exponent `n` with the negative-power nonzero-base guard (integer lane).  This
is exactly the set where `Real.rpow b e` is the genuine mathematical value. -/
def powDom (b e : ℝ) : Prop :=
  0 < b ∨ ∃ n : ℤ, e = (n : ℝ) ∧ (n < 0 → b ≠ 0)

/-- Domain guard for a unary `call` — the pointwise shadow of `ieval`'s
unary refusal branches. -/
def call1Dom (name : String) (v : ℝ) : Prop :=
  if name = "sqrt" then 0 ≤ v
  else if name = "ln" then 0 < v
  else if name = "log10" then 0 < v
  else if name = "log2" then 0 < v
  else if name = "asin" then -1 ≤ v ∧ v ≤ 1
  else if name = "acos" then -1 ≤ v ∧ v ≤ 1
  else if name = "tan" then Real.cos v ≠ 0
  else if name = "sin" then True
  else if name = "cos" then True
  else if name = "atan" then True
  else if name = "exp" then True
  else if name = "abs" then True
  else if name = "floor" then True
  else if name = "ceil" then True
  else if name = "round" then True
  else if name = "trunc" then True
  else False

/-- Domain guard for a binary `call`. -/
def call2Dom (name : String) (u v : ℝ) : Prop :=
  if name = "atan2" then 0 < v
  else if name = "hypot" then True
  else if name = "min" then True
  else if name = "max" then True
  else if name = "pow" then powDom u v
  else False

/-- Structural definedness at a point — the pointwise shadow of `ieval`'s
`iv_bad` guards (see header). -/
def DefinedOn : Expr → ℝ → Prop
  | .num _ _, _ => True
  | .var name, _ => name = "x"
  | .constant _, _ => True
  | .neg u, x => DefinedOn u x
  | .add l r, x => DefinedOn l x ∧ DefinedOn r x
  | .sub l r, x => DefinedOn l x ∧ DefinedOn r x
  | .mul l r, x => DefinedOn l x ∧ DefinedOn r x
  | .div l r, x => DefinedOn l x ∧ DefinedOn r x ∧ sem r x ≠ 0
  | .mod _ _, _ => False
  | .pow b e, x => DefinedOn b x ∧ DefinedOn e x ∧ powDom (sem b x) (sem e x)
  | .call1 name u, x => DefinedOn u x ∧ call1Dom name (sem u x)
  | .call2 name u v, x => DefinedOn u x ∧ DefinedOn v x ∧ call2Dom name (sem u x) (sem v x)

/-! ### Reduction lemmas for the string-dispatched call semantics -/

@[simp] lemma call1Sem_sin (v : ℝ) : call1Sem "sin" v = Real.sin v := by
  simp [call1Sem]
@[simp] lemma call1Sem_cos (v : ℝ) : call1Sem "cos" v = Real.cos v := by
  simp [call1Sem]
@[simp] lemma call1Sem_asin (v : ℝ) : call1Sem "asin" v = Real.arcsin v := by
  simp [call1Sem]
@[simp] lemma call1Sem_acos (v : ℝ) : call1Sem "acos" v = Real.arccos v := by
  simp [call1Sem]
@[simp] lemma call1Sem_atan (v : ℝ) : call1Sem "atan" v = Real.arctan v := by
  simp [call1Sem]
@[simp] lemma call1Sem_sqrt (v : ℝ) : call1Sem "sqrt" v = Real.sqrt v := by
  simp [call1Sem]
@[simp] lemma call1Sem_ln (v : ℝ) : call1Sem "ln" v = Real.log v := by
  simp [call1Sem]
@[simp] lemma call1Sem_exp (v : ℝ) : call1Sem "exp" v = Real.exp v := by
  simp [call1Sem]
@[simp] lemma call1Sem_abs (v : ℝ) : call1Sem "abs" v = |v| := by
  simp [call1Sem]
@[simp] lemma call1Sem_floor (v : ℝ) : call1Sem "floor" v = ((⌊v⌋ : ℤ) : ℝ) := by
  simp [call1Sem]
@[simp] lemma call1Sem_ceil (v : ℝ) : call1Sem "ceil" v = ((⌈v⌉ : ℤ) : ℝ) := by
  simp [call1Sem]
@[simp] lemma call1Sem_round (v : ℝ) : call1Sem "round" v = roundAway v := by
  simp [call1Sem]
@[simp] lemma call1Sem_trunc (v : ℝ) : call1Sem "trunc" v = truncR v := by
  simp [call1Sem]

@[simp] lemma call2Sem_hypot (u v : ℝ) :
    call2Sem "hypot" u v = Real.sqrt (u ^ 2 + v ^ 2) := by simp [call2Sem]
@[simp] lemma call2Sem_atan2 (u v : ℝ) :
    call2Sem "atan2" u v = Real.arctan (u / v) := by simp [call2Sem]
@[simp] lemma call2Sem_min (u v : ℝ) : call2Sem "min" u v = min u v := by
  simp [call2Sem]
@[simp] lemma call2Sem_max (u v : ℝ) : call2Sem "max" u v = max u v := by
  simp [call2Sem]

@[simp] lemma call1Dom_sqrt (v : ℝ) : call1Dom "sqrt" v = (0 ≤ v) := by
  simp [call1Dom]
@[simp] lemma call1Dom_ln (v : ℝ) : call1Dom "ln" v = (0 < v) := by
  simp [call1Dom]
@[simp] lemma call1Dom_asin (v : ℝ) : call1Dom "asin" v = (-1 ≤ v ∧ v ≤ 1) := by
  simp [call1Dom]
@[simp] lemma call1Dom_acos (v : ℝ) : call1Dom "acos" v = (-1 ≤ v ∧ v ≤ 1) := by
  simp [call1Dom]
@[simp] lemma call1Dom_abs (v : ℝ) : call1Dom "abs" v = True := by
  simp [call1Dom]
@[simp] lemma call1Dom_floor (v : ℝ) : call1Dom "floor" v = True := by
  simp [call1Dom]
@[simp] lemma call1Dom_ceil (v : ℝ) : call1Dom "ceil" v = True := by
  simp [call1Dom]
@[simp] lemma call1Dom_round (v : ℝ) : call1Dom "round" v = True := by
  simp [call1Dom]
@[simp] lemma call1Dom_trunc (v : ℝ) : call1Dom "trunc" v = True := by
  simp [call1Dom]
@[simp] lemma call1Dom_sin (v : ℝ) : call1Dom "sin" v = True := by
  simp [call1Dom]
@[simp] lemma call1Dom_cos (v : ℝ) : call1Dom "cos" v = True := by
  simp [call1Dom]
@[simp] lemma call1Dom_atan (v : ℝ) : call1Dom "atan" v = True := by
  simp [call1Dom]
@[simp] lemma call1Dom_exp (v : ℝ) : call1Dom "exp" v = True := by
  simp [call1Dom]

@[simp] lemma call2Dom_atan2 (u v : ℝ) : call2Dom "atan2" u v = (0 < v) := by
  simp [call2Dom]
@[simp] lemma call2Dom_hypot (u v : ℝ) : call2Dom "hypot" u v = True := by
  simp [call2Dom]
@[simp] lemma call2Dom_min (u v : ℝ) : call2Dom "min" u v = True := by
  simp [call2Dom]
@[simp] lemma call2Dom_max (u v : ℝ) : call2Dom "max" u v = True := by
  simp [call2Dom]

/-! ### `pow`-node semantics: `Real.rpow` specialized to literal exponents -/

/-- `pow` node unfolds to `Real.rpow`. -/
lemma sem_pow (b e : Expr) (x : ℝ) : sem (.pow b e) x = (sem b x) ^ (sem e x) := rfl

/-- A `num (↑n) _` exponent collapses `pow` to the `n`-th monoid power (for
EVERY base, via `Real.rpow_natCast`) — the engine's positive integer lane. -/
lemma sem_pow_nat (b : Expr) (n : ℕ) (t : String) (x : ℝ) :
    sem (.pow b (.num ((n : ℕ) : ℝ) t)) x = (sem b x) ^ n := by
  simp only [sem]
  exact Real.rpow_natCast (sem b x) n

/-- A `neg (num (↑m) _)` exponent collapses `pow` to the integer power
`-(m : ℤ)` (for EVERY base, via `Real.rpow_intCast`) — the engine's negative
integer lane. -/
lemma sem_pow_neg_nat (b : Expr) (m : ℕ) (t : String) (x : ℝ) :
    sem (.pow b (.neg (.num ((m : ℕ) : ℝ) t))) x = (sem b x) ^ (-(m : ℤ)) := by
  simp only [sem]
  rw [show (-(((m : ℕ) : ℝ))) = (((-(m : ℤ)) : ℤ) : ℝ) by push_cast; ring,
    Real.rpow_intCast]

/-- A literal `2` exponent collapses `pow` to the square (used by the
symbolic differentiator's emitted denominators `v²`, `1 + u²`). -/
lemma sem_pow_ofNat_two (e : Expr) (t : String) (x : ℝ) :
    sem (.pow e (.num 2 t)) x = (sem e x) ^ 2 := by
  simp only [sem]
  rw [show (2 : ℝ) = ((2 : ℕ) : ℝ) by norm_num, Real.rpow_natCast]

/-! ### `powDom` / `DefinedOn` helpers for the integer power lanes -/

/-- A nonnegative integer literal exponent satisfies the pow guard for any
base (integer lane, nonnegative exponent — no base condition). -/
lemma powDom_natCast (b : ℝ) (n : ℕ) : powDom b (((n : ℕ) : ℝ)) :=
  Or.inr ⟨(n : ℤ), by push_cast; ring, fun h => absurd h (not_lt.mpr (Int.natCast_nonneg n))⟩

/-- A negative integer literal exponent satisfies the pow guard exactly when
the base is nonzero (integer lane, negative exponent). -/
lemma powDom_negNat {b : ℝ} {m : ℕ} (hb : b ≠ 0) : powDom b (-(((m : ℕ) : ℝ))) :=
  Or.inr ⟨-(m : ℤ), by push_cast; ring, fun _ => hb⟩

/-- `DefinedOn` of a positive integer power node (exponent `num (↑n) _`). -/
lemma definedOn_pow_nat {b : Expr} {n : ℕ} {t : String} {x : ℝ}
    (hb : DefinedOn b x) : DefinedOn (.pow b (.num ((n : ℕ) : ℝ) t)) x :=
  ⟨hb, trivial, powDom_natCast (sem b x) n⟩

/-- `DefinedOn` of a negative integer power node (exponent `neg (num (↑m) _)`),
which additionally needs a nonzero base. -/
lemma definedOn_pow_neg_nat {b : Expr} {m : ℕ} {t : String} {x : ℝ}
    (hb : DefinedOn b x) (hbne : sem b x ≠ 0) :
    DefinedOn (.pow b (.neg (.num ((m : ℕ) : ℝ) t))) x :=
  ⟨hb, trivial, powDom_negNat hbne⟩

end JackalIv
