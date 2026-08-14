/-
JackalIv/Embed.lean — the COMPOSITION theorem: an execution relation over the
SINGLE canonical `Expr` (`JackalIv/Syntax.lean`) carrying exactly the
per-operator hypotheses already proved sound in Arith/Monotone/Exact/Pow, and
the whole-expression guarantee `runs_encloses`: any completed run of the
modeled `ieval` encloses the exact semantics at every point of the input
interval.

Engine correspondence (`jackal_calc.anb`, section "JACKAL CERTIFIED INTERVAL
ENGINE", fn `ieval` and the `iv_*` helpers it calls).  `Runs` constructor →
engine branch → containment lemma:

| `Runs` constructor | engine branch (`iv_*`)              | containment lemma          |
|--------------------|-------------------------------------|----------------------------|
| `num_exact`        | `iv_from_literal` integer-exact     | exact, no pad              |
| `num_rounded`      | `iv_from_literal` rounded branch    | `basic_brackets`           |
| `const_rounded`    | `iv_from_literal(constant_value(_))`| `basic_brackets`           |
| `var`              | `ieval` tag "var" (x bound)         | exact, no pad              |
| `neg`              | `iv_neg` (exact)                    | `iv_neg` shape             |
| `add`/`sub`/`mul`  | `iv_add`/`iv_sub`/`iv_mul`          | `iv_*_encloses`            |
| `div`              | `iv_div` (zero-free guard)          | `iv_div_encloses`          |
| `powZero`          | `iv_pow_int`, n = 0                 | `pow_zero`, exact          |
| `powEvenPos`       | `iv_pow_int`, even n ≥ 2            | `iv_pow_int_even_encloses` |
| `powOddPos`        | `iv_pow_int`, odd n ≥ 1             | `iv_pow_int_odd_encloses`  |
| `powNegEven/Odd`   | `iv_pow_int`, n ≤ -1 (÷ core)       | `iv_pow_neg_encloses_zpow` |
| `powGeneral`       | `iv_pow_general` (base > 0)         | `rpow_general_encloses`    |
| `sqrt`             | `iv_sqrt` (guard lo ≥ 0, clamp)     | `iv_sqrt_encloses`         |
| `exp`              | `iv_exp`                            | `iv_exp_encloses`          |
| `log`  (name "ln") | `iv_ln` (guard lo > 0)              | `iv_log_encloses`          |
| `sin`/`cos`        | `iv_sin`/`iv_cos` (universal ±1)    | `sin/cos_mem_Icc`          |
| `atan`             | `iv_atan`                           | `iv_atan_encloses`         |
| `asin`             | `iv_asin` (guard [-1,1])            | `iv_asin_encloses`         |
| `acos`             | `iv_acos` (swap, guard [-1,1])      | `iv_acos_encloses`         |
| `abs`              | `iv_abs` (three-case, exact)        | `iv_abs_encloses`          |
| `floor/ceil/round/trunc` | endpoint-wise scalar family   | `floor/ceil/roundAway/trunc_mem` |
| `min`/`max`        | `iv_min`/`iv_max` (exact)           | `iv_min/max_encloses`      |
| `hypot`            | `iv_hypot` (mig/mag, libm)          | `iv_hypot_encloses`        |
| `atan2`            | `iv_atan2` (guard x > 0)            | `iv_atan2_encloses`        |

FAIL-CLOSED (Syntax.lean header "not yet embedded"): `tan`, `cbrt`,
`log10`, `log2`, `mod`, and every unknown `call` name have NO `Runs`
constructor — the composition theorem simply has no derivation for them, an
honest refusal, never an unsound approximation.  `sin`/`cos` use the
universal `[-1,1]` enclosure (a conservative widening of every `iv_sin`/
`iv_cos` branch; Trig.lean proves the tighter hulls separately).
-/
import JackalIv.Syntax

namespace JackalIv

/-! ### The execution relation over the canonical `Expr`

`Runs e (a, b) (lo, hi)` reads: on input interval `[a, b]`, a run of the
modeled `ieval` on `e` completed (no refusal) and produced the box
`[lo, hi]`.  Each constructor carries EXACTLY the hypotheses of that
operator's containment lemma. -/
inductive Runs : Expr → ℝ × ℝ → ℝ × ℝ → Prop
  /-- `iv_from_literal` integer-exact branch: the literal is the intended
  real, no pad.  `t` is the parser token text, ignored by the model. -/
  | num_exact {r a b : ℝ} {t : String} : Runs (.num r t) (a, b) (r, r)
  /-- `iv_from_literal` rounded branch: `iv_out(fl, fl)` pads a ≤ 0.5-ulp
  rounding of the intended real. -/
  | num_rounded {r a b fl : ℝ} {t : String} (h : Approx δ0 σ0 fl r) :
      Runs (.num r t) (a, b) (padLo fl, padHi fl)
  /-- `iv_from_literal(constant_value(name))`: a named constant is a rounded
  literal of its intended real value. -/
  | const_rounded {a b fl : ℝ} {name : String}
      (h : Approx δ0 σ0 fl (constValue name)) :
      Runs (.constant name) (a, b) (padLo fl, padHi fl)
  /-- `ieval` tag "var": the bound variable `x` returns the input box, exact. -/
  | var {a b : ℝ} : Runs (.var "x") (a, b) (a, b)
  /-- `iv_neg`: IEEE negation is exact, endpoints swap, no pad. -/
  | neg {e : Expr} {a b l u : ℝ} (hr : Runs e (a, b) (l, u)) :
      Runs (.neg e) (a, b) (-u, -l)
  /-- `iv_add`: one basic op per endpoint, `iv_out` pad. -/
  | add {e₁ e₂ : Expr} {a b l₁ u₁ l₂ u₂ fl_lo fl_hi : ℝ}
      (hr₁ : Runs e₁ (a, b) (l₁, u₁)) (hr₂ : Runs e₂ (a, b) (l₂, u₂))
      (hlo : Approx δ0 σ0 fl_lo (l₁ + l₂)) (hhi : Approx δ0 σ0 fl_hi (u₁ + u₂)) :
      Runs (.add e₁ e₂) (a, b) (padLo fl_lo, padHi fl_hi)
  /-- `iv_sub`: endpoints `lo₁ − hi₂` / `hi₁ − lo₂`, padded. -/
  | sub {e₁ e₂ : Expr} {a b l₁ u₁ l₂ u₂ fl_lo fl_hi : ℝ}
      (hr₁ : Runs e₁ (a, b) (l₁, u₁)) (hr₂ : Runs e₂ (a, b) (l₂, u₂))
      (hlo : Approx δ0 σ0 fl_lo (l₁ - u₂)) (hhi : Approx δ0 σ0 fl_hi (u₁ - l₂)) :
      Runs (.sub e₁ e₂) (a, b) (padLo fl_lo, padHi fl_hi)
  /-- `iv_mul`: four rounded corner products, exact float min/max, `iv_out`. -/
  | mul {e₁ e₂ : Expr} {a b l₁ u₁ l₂ u₂ p1 p2 p3 p4 : ℝ}
      (hr₁ : Runs e₁ (a, b) (l₁, u₁)) (hr₂ : Runs e₂ (a, b) (l₂, u₂))
      (h1 : Approx δ0 σ0 p1 (l₁ * l₂)) (h2 : Approx δ0 σ0 p2 (l₁ * u₂))
      (h3 : Approx δ0 σ0 p3 (u₁ * l₂)) (h4 : Approx δ0 σ0 p4 (u₁ * u₂)) :
      Runs (.mul e₁ e₂) (a, b)
        (padLo (min (min p1 p2) (min p3 p4)), padHi (max (max p1 p2) (max p3 p4)))
  /-- `iv_div`: zero-free-denominator guard (`0 < l₂ ∨ u₂ < 0`), four rounded
  corner quotients, exact min/max, `iv_out`. -/
  | div {e₁ e₂ : Expr} {a b l₁ u₁ l₂ u₂ q1 q2 q3 q4 : ℝ}
      (hr₁ : Runs e₁ (a, b) (l₁, u₁)) (hr₂ : Runs e₂ (a, b) (l₂, u₂))
      (hden : 0 < l₂ ∨ u₂ < 0)
      (h1 : Approx δ0 σ0 q1 (l₁ / l₂)) (h2 : Approx δ0 σ0 q2 (l₁ / u₂))
      (h3 : Approx δ0 σ0 q3 (u₁ / l₂)) (h4 : Approx δ0 σ0 q4 (u₁ / u₂)) :
      Runs (.div e₁ e₂) (a, b)
        (padLo (min (min q1 q2) (min q3 q4)), padHi (max (max q1 q2) (max q3 q4)))
  /-- `iv_pow_int`, n = 0: `iv_exact(1.0)`, no pad. -/
  | powZero {e : Expr} {a b l u : ℝ} {t : String} (hr : Runs e (a, b) (l, u)) :
      Runs (.pow e (.num ((0 : ℕ) : ℝ) t)) (a, b) (1, 1)
  /-- `iv_pow_int`, even n ≥ 2: libm `pow` at mignitude/magnitude, `iv_out`. -/
  | powEvenPos (n : ℕ) (hn : Even n) (hn2 : 2 ≤ n) {e : Expr}
      {a b l u fl_lo fl_hi : ℝ} {t : String}
      (hr : Runs e (a, b) (l, u))
      (hlo : Approx δlib σ0 fl_lo (mig l u ^ n))
      (hhi : Approx δlib σ0 fl_hi (mag l u ^ n)) :
      Runs (.pow e (.num ((n : ℕ) : ℝ) t)) (a, b) (padLo fl_lo, padHi fl_hi)
  /-- `iv_pow_int`, odd n ≥ 1: libm `pow` at the child endpoints, `iv_out`. -/
  | powOddPos (n : ℕ) (hn : Odd n) {e : Expr} {a b l u fl_lo fl_hi : ℝ}
      {t : String}
      (hr : Runs e (a, b) (l, u))
      (hlo : Approx δlib σ0 fl_lo (l ^ n)) (hhi : Approx δlib σ0 fl_hi (u ^ n)) :
      Runs (.pow e (.num ((n : ℕ) : ℝ) t)) (a, b) (padLo fl_lo, padHi fl_hi)
  /-- `iv_pow_int`, n ≤ -1 with even core: even positive core then
  `iv_div(iv_exact(1.0), core)`.  Exponent is the parser's `neg (num m)`. -/
  | powNegEven (m : ℕ) (hm : Even m) (hm2 : 2 ≤ m) {e : Expr}
      {a b l u fl_lo fl_hi q1 q2 q3 q4 : ℝ} {t : String}
      (hr : Runs e (a, b) (l, u))
      (hclo : Approx δlib σ0 fl_lo (mig l u ^ m))
      (hchi : Approx δlib σ0 fl_hi (mag l u ^ m))
      (hden : 0 < padLo fl_lo ∨ padHi fl_hi < 0)
      (h1 : Approx δ0 σ0 q1 (1 / padLo fl_lo)) (h2 : Approx δ0 σ0 q2 (1 / padHi fl_hi))
      (h3 : Approx δ0 σ0 q3 (1 / padLo fl_lo)) (h4 : Approx δ0 σ0 q4 (1 / padHi fl_hi)) :
      Runs (.pow e (.neg (.num ((m : ℕ) : ℝ) t))) (a, b)
        (padLo (min (min q1 q2) (min q3 q4)), padHi (max (max q1 q2) (max q3 q4)))
  /-- `iv_pow_int`, n ≤ -1 with odd core: as `powNegEven` but odd core lane. -/
  | powNegOdd (m : ℕ) (hm : Odd m) {e : Expr}
      {a b l u fl_lo fl_hi q1 q2 q3 q4 : ℝ} {t : String}
      (hr : Runs e (a, b) (l, u))
      (hclo : Approx δlib σ0 fl_lo (l ^ m)) (hchi : Approx δlib σ0 fl_hi (u ^ m))
      (hden : 0 < padLo fl_lo ∨ padHi fl_hi < 0)
      (h1 : Approx δ0 σ0 q1 (1 / padLo fl_lo)) (h2 : Approx δ0 σ0 q2 (1 / padHi fl_hi))
      (h3 : Approx δ0 σ0 q3 (1 / padLo fl_lo)) (h4 : Approx δ0 σ0 q4 (1 / padHi fl_hi)) :
      Runs (.pow e (.neg (.num ((m : ℕ) : ℝ) t))) (a, b)
        (padLo (min (min q1 q2) (min q3 q4)), padHi (max (max q1 q2) (max q3 q4)))
  /-- `iv_pow_general` (base > 0): `iv_exp(iv_mul(e, iv_ln(b)))`.  The three
  hypotheses are the stage enclosures `rpow_general_encloses` composes. -/
  | powGeneral {base exp : Expr} {a b xl xu yl yu Ll Lu Ml Mu El Eu : ℝ}
      (hbase : Runs base (a, b) (xl, xu)) (hexp : Runs exp (a, b) (yl, yu))
      (hxl : 0 < xl)
      (hln : ∀ t, xl ≤ t → t ≤ xu → Ll ≤ Real.log t ∧ Real.log t ≤ Lu)
      (hmul : ∀ u v, yl ≤ u → u ≤ yu → Ll ≤ v → v ≤ Lu → Ml ≤ u * v ∧ u * v ≤ Mu)
      (hexpst : ∀ t, Ml ≤ t → t ≤ Mu → El ≤ Real.exp t ∧ Real.exp t ≤ Eu) :
      Runs (.pow base exp) (a, b) (El, Eu)
  /-- `iv_sqrt`: guard `0 ≤ l`, libm sqrt at endpoints, `iv_out`, then the
  final `lo := max(lo, 0)` clamp. -/
  | sqrt {e : Expr} {a b l u fl_lo fl_hi : ℝ}
      (hr : Runs e (a, b) (l, u)) (hguard : 0 ≤ l)
      (hlo : Approx δlib σ0 fl_lo (Real.sqrt l))
      (hhi : Approx δlib σ0 fl_hi (Real.sqrt u)) :
      Runs (.call1 "sqrt" e) (a, b) (max (padLo fl_lo) 0, padHi fl_hi)
  /-- `iv_exp`: libm exp at the endpoints (monotone), padded. -/
  | exp {e : Expr} {a b l u fl_lo fl_hi : ℝ}
      (hr : Runs e (a, b) (l, u))
      (hlo : Approx δlib σ0 fl_lo (Real.exp l))
      (hhi : Approx δlib σ0 fl_hi (Real.exp u)) :
      Runs (.call1 "exp" e) (a, b) (padLo fl_lo, padHi fl_hi)
  /-- `iv_ln` (engine name "ln"): guard `0 < l`, libm ln, padded. -/
  | log {e : Expr} {a b l u fl_lo fl_hi : ℝ}
      (hr : Runs e (a, b) (l, u)) (hguard : 0 < l)
      (hlo : Approx δlib σ0 fl_lo (Real.log l))
      (hhi : Approx δlib σ0 fl_hi (Real.log u)) :
      Runs (.call1 "ln" e) (a, b) (padLo fl_lo, padHi fl_hi)
  /-- `iv_sin`, universal `[-1, 1]` enclosure (sound for every branch). -/
  | sin {e : Expr} {a b l u : ℝ} (hr : Runs e (a, b) (l, u)) :
      Runs (.call1 "sin" e) (a, b) (-1, 1)
  /-- `iv_cos`, universal `[-1, 1]` enclosure. -/
  | cos {e : Expr} {a b l u : ℝ} (hr : Runs e (a, b) (l, u)) :
      Runs (.call1 "cos" e) (a, b) (-1, 1)
  /-- `iv_atan`: libm atan at the endpoints (monotone), padded. -/
  | atan {e : Expr} {a b l u fl_lo fl_hi : ℝ}
      (hr : Runs e (a, b) (l, u))
      (hlo : Approx δlib σ0 fl_lo (Real.arctan l))
      (hhi : Approx δlib σ0 fl_hi (Real.arctan u)) :
      Runs (.call1 "atan" e) (a, b) (padLo fl_lo, padHi fl_hi)
  /-- `iv_asin`: guard `[-1, 1]`, libm asin (monotone), padded. -/
  | asin {e : Expr} {a b l u fl_lo fl_hi : ℝ}
      (hr : Runs e (a, b) (l, u)) (hdom : -1 ≤ l ∧ u ≤ 1)
      (hlo : Approx δlib σ0 fl_lo (Real.arcsin l))
      (hhi : Approx δlib σ0 fl_hi (Real.arcsin u)) :
      Runs (.call1 "asin" e) (a, b) (padLo fl_lo, padHi fl_hi)
  /-- `iv_acos`: guard `[-1, 1]`, libm acos (antitone → swapped endpoints),
  padded — `iv_out(acos(a.hi), acos(a.lo))`. -/
  | acos {e : Expr} {a b l u fl_lo fl_hi : ℝ}
      (hr : Runs e (a, b) (l, u)) (hdom : -1 ≤ l ∧ u ≤ 1)
      (hlo : Approx δlib σ0 fl_lo (Real.arccos l))
      (hhi : Approx δlib σ0 fl_hi (Real.arccos u)) :
      Runs (.call1 "acos" e) (a, b) (padLo fl_hi, padHi fl_lo)
  /-- `iv_abs`: three-case exact interval, no pad. -/
  | abs {e : Expr} {a b l u : ℝ} (hr : Runs e (a, b) (l, u)) :
      Runs (.call1 "abs" e) (a, b) (absLo l u, absHi l u)
  /-- `iv_floor_scalar` endpoint-wise: `[⌊l⌋, ⌊u⌋]`, exact, no pad. -/
  | floor {e : Expr} {a b l u : ℝ} (hr : Runs e (a, b) (l, u)) :
      Runs (.call1 "floor" e) (a, b) (((⌊l⌋ : ℤ) : ℝ), ((⌊u⌋ : ℤ) : ℝ))
  /-- `iv_ceil_scalar` endpoint-wise: `[⌈l⌉, ⌈u⌉]`, exact, no pad. -/
  | ceil {e : Expr} {a b l u : ℝ} (hr : Runs e (a, b) (l, u)) :
      Runs (.call1 "ceil" e) (a, b) (((⌈l⌉ : ℤ) : ℝ), ((⌈u⌉ : ℤ) : ℝ))
  /-- `iv_round_scalar` endpoint-wise (C round, half away from zero):
  `[roundAway l, roundAway u]`, exact, no pad. -/
  | round {e : Expr} {a b l u : ℝ} (hr : Runs e (a, b) (l, u)) :
      Runs (.call1 "round" e) (a, b) (roundAway l, roundAway u)
  /-- `iv_trunc_scalar` endpoint-wise: `[truncR l, truncR u]`, exact, no pad. -/
  | trunc {e : Expr} {a b l u : ℝ} (hr : Runs e (a, b) (l, u)) :
      Runs (.call1 "trunc" e) (a, b) (truncR l, truncR u)
  /-- `iv_min`: float min is exact, no pad. -/
  | min {e₁ e₂ : Expr} {a b l₁ u₁ l₂ u₂ : ℝ}
      (hr₁ : Runs e₁ (a, b) (l₁, u₁)) (hr₂ : Runs e₂ (a, b) (l₂, u₂)) :
      Runs (.call2 "min" e₁ e₂) (a, b) (min l₁ l₂, min u₁ u₂)
  /-- `iv_max`: float max is exact, no pad. -/
  | max {e₁ e₂ : Expr} {a b l₁ u₁ l₂ u₂ : ℝ}
      (hr₁ : Runs e₁ (a, b) (l₁, u₁)) (hr₂ : Runs e₂ (a, b) (l₂, u₂)) :
      Runs (.call2 "max" e₁ e₂) (a, b) (max l₁ l₂, max u₁ u₂)
  /-- `iv_hypot`: libm hypot at the exact mig/mag arguments, padded. -/
  | hypot {e₁ e₂ : Expr} {a b l₁ u₁ l₂ u₂ fl_lo fl_hi : ℝ}
      (hr₁ : Runs e₁ (a, b) (l₁, u₁)) (hr₂ : Runs e₂ (a, b) (l₂, u₂))
      (hlo : Approx δlib σ0 fl_lo (Real.sqrt (mig l₁ u₁ ^ 2 + mig l₂ u₂ ^ 2)))
      (hhi : Approx δlib σ0 fl_hi (Real.sqrt (mag l₁ u₁ ^ 2 + mag l₂ u₂ ^ 2))) :
      Runs (.call2 "hypot" e₁ e₂) (a, b) (padLo fl_lo, padHi fl_hi)
  /-- `iv_atan2` (guard x > 0): `iv_atan(iv_div(y, x))` — the first argument is
  y (`e₁`), the second is x (`e₂`).  Two-stage rounded division + libm atan. -/
  | atan2 {e₁ e₂ : Expr} {a b l₁ u₁ l₂ u₂ q1 q2 q3 q4 fl_lo fl_hi : ℝ}
      (hr₁ : Runs e₁ (a, b) (l₁, u₁)) (hr₂ : Runs e₂ (a, b) (l₂, u₂))
      (hxpos : 0 < l₂)
      (h1 : Approx δ0 σ0 q1 (l₁ / l₂)) (h2 : Approx δ0 σ0 q2 (l₁ / u₂))
      (h3 : Approx δ0 σ0 q3 (u₁ / l₂)) (h4 : Approx δ0 σ0 q4 (u₁ / u₂))
      (ha : Approx δlib σ0 fl_lo (Real.arctan (padLo (min (min q1 q2) (min q3 q4)))))
      (hb : Approx δlib σ0 fl_hi (Real.arctan (padHi (max (max q1 q2) (max q3 q4))))) :
      Runs (.call2 "atan2" e₁ e₂) (a, b) (padLo fl_lo, padHi fl_hi)

/-! ### The composition theorem -/

/-- Pair-projection form of the composition theorem (the induction motive).
Any completed run on a nonempty input interval delivers, at every point of
the interval, both structural definedness and containment of the exact
semantics in the output box. -/
theorem runs_sound {e : Expr} {p q : ℝ × ℝ} (hrun : Runs e p q) :
    p.1 ≤ p.2 → ∀ x ∈ Set.Icc p.1 p.2, DefinedOn e x ∧ sem e x ∈ Set.Icc q.1 q.2 := by
  induction hrun with
  | num_exact =>
    intro _ x _
    refine ⟨trivial, ?_⟩
    simp only [sem, Set.mem_Icc]
    exact ⟨le_rfl, le_rfl⟩
  | num_rounded h =>
    intro _ x _
    refine ⟨trivial, ?_⟩
    have hbr := basic_brackets _ _ h
    simp only [sem, Set.mem_Icc]
    exact ⟨hbr.1, hbr.2⟩
  | const_rounded h =>
    intro _ x _
    refine ⟨trivial, ?_⟩
    have hbr := basic_brackets _ _ h
    simp only [sem, Set.mem_Icc]
    exact ⟨hbr.1, hbr.2⟩
  | var =>
    intro _ x hx
    refine ⟨by simp [DefinedOn], ?_⟩
    have hv : sem (.var "x") x = x := by simp [sem]
    rw [hv]; exact hx
  | neg hr ih =>
    intro hab x hx
    obtain ⟨hd, hm⟩ := ih hab x hx
    refine ⟨hd, ?_⟩
    simp only [sem, Set.mem_Icc]
    exact ⟨neg_le_neg hm.2, neg_le_neg hm.1⟩
  | add hr₁ hr₂ hlo hhi ih₁ ih₂ =>
    intro hab x hx
    obtain ⟨hd₁, hm₁⟩ := ih₁ hab x hx
    obtain ⟨hd₂, hm₂⟩ := ih₂ hab x hx
    have h := iv_add_encloses _ _ _ _ _ _ _ _ hm₁.1 hm₁.2 hm₂.1 hm₂.2 hlo hhi
    refine ⟨⟨hd₁, hd₂⟩, ?_⟩
    simp only [sem, Set.mem_Icc]
    exact ⟨h.1, h.2⟩
  | sub hr₁ hr₂ hlo hhi ih₁ ih₂ =>
    intro hab x hx
    obtain ⟨hd₁, hm₁⟩ := ih₁ hab x hx
    obtain ⟨hd₂, hm₂⟩ := ih₂ hab x hx
    have h := iv_sub_encloses _ _ _ _ _ _ _ _ hm₁.1 hm₁.2 hm₂.1 hm₂.2 hlo hhi
    refine ⟨⟨hd₁, hd₂⟩, ?_⟩
    simp only [sem, Set.mem_Icc]
    exact ⟨h.1, h.2⟩
  | mul hr₁ hr₂ h1 h2 h3 h4 ih₁ ih₂ =>
    intro hab x hx
    obtain ⟨hd₁, hm₁⟩ := ih₁ hab x hx
    obtain ⟨hd₂, hm₂⟩ := ih₂ hab x hx
    have h := iv_mul_encloses _ _ _ _ _ _ _ _ _ _ hm₁.1 hm₁.2 hm₂.1 hm₂.2 h1 h2 h3 h4
    refine ⟨⟨hd₁, hd₂⟩, ?_⟩
    simp only [sem, Set.mem_Icc]
    exact ⟨h.1, h.2⟩
  | div hr₁ hr₂ hden h1 h2 h3 h4 ih₁ ih₂ =>
    intro hab x hx
    obtain ⟨hd₁, hm₁⟩ := ih₁ hab x hx
    obtain ⟨hd₂, hm₂⟩ := ih₂ hab x hx
    have h := iv_div_encloses _ _ _ _ _ _ _ _ _ _ hm₁.1 hm₁.2 hm₂.1 hm₂.2 hden h1 h2 h3 h4
    refine ⟨⟨hd₁, hd₂, ?_⟩, ?_⟩
    · rcases hden with hpos | hneg
      · exact ne_of_gt (lt_of_lt_of_le hpos hm₂.1)
      · exact ne_of_lt (lt_of_le_of_lt hm₂.2 hneg)
    · simp only [sem, Set.mem_Icc]
      exact ⟨h.1, h.2⟩
  | powZero hr ih =>
    intro hab x hx
    obtain ⟨hd, _⟩ := ih hab x hx
    refine ⟨definedOn_pow_nat hd, ?_⟩
    rw [sem_pow_nat]
    simp only [pow_zero, Set.mem_Icc]
    exact ⟨le_rfl, le_rfl⟩
  | powEvenPos n hn hn2 hr hlo hhi ih =>
    intro hab x hx
    obtain ⟨hd, hm⟩ := ih hab x hx
    have h := iv_pow_int_even_encloses n hn hn2 _ _ _ _ _ hm.1 hm.2 hlo hhi
    refine ⟨definedOn_pow_nat hd, ?_⟩
    rw [sem_pow_nat]
    simp only [Set.mem_Icc]
    exact ⟨h.1, h.2⟩
  | powOddPos n hn hr hlo hhi ih =>
    intro hab x hx
    obtain ⟨hd, hm⟩ := ih hab x hx
    have h := iv_pow_int_odd_encloses n hn _ _ _ _ _ hm.1 hm.2 hlo hhi
    refine ⟨definedOn_pow_nat hd, ?_⟩
    rw [sem_pow_nat]
    simp only [Set.mem_Icc]
    exact ⟨h.1, h.2⟩
  | powNegEven m hm hm2 hr hclo hchi hden h1 h2 h3 h4 ih =>
    intro hab x hx
    obtain ⟨hd, hmem⟩ := ih hab x hx
    have hcore := iv_pow_int_even_encloses m hm hm2 _ _ _ _ _ hmem.1 hmem.2 hclo hchi
    have hzp := iv_pow_neg_encloses_zpow m _ _ _ _ _ _ _ hcore.1 hcore.2 hden h1 h2 h3 h4
    refine ⟨⟨hd, trivial, Or.inr ⟨-(m : ℤ), by simp only [sem]; push_cast; ring,
        fun _ h0 => ?_⟩⟩, ?_⟩
    · have hm0 : m ≠ 0 := by omega
      rw [h0, zero_pow hm0] at hcore
      rcases hden with hpos | hneg
      · linarith [hcore.1, hcore.2]
      · linarith [hcore.1, hcore.2]
    · rw [sem_pow_neg_nat]
      simp only [Set.mem_Icc]
      exact ⟨hzp.1, hzp.2⟩
  | powNegOdd m hm hr hclo hchi hden h1 h2 h3 h4 ih =>
    intro hab x hx
    obtain ⟨hd, hmem⟩ := ih hab x hx
    have hcore := iv_pow_int_odd_encloses m hm _ _ _ _ _ hmem.1 hmem.2 hclo hchi
    have hzp := iv_pow_neg_encloses_zpow m _ _ _ _ _ _ _ hcore.1 hcore.2 hden h1 h2 h3 h4
    refine ⟨⟨hd, trivial, Or.inr ⟨-(m : ℤ), by simp only [sem]; push_cast; ring,
        fun _ h0 => ?_⟩⟩, ?_⟩
    · have hm0 : m ≠ 0 := by rcases hm with ⟨k, hk⟩; omega
      rw [h0, zero_pow hm0] at hcore
      rcases hden with hpos | hneg
      · linarith [hcore.1, hcore.2]
      · linarith [hcore.1, hcore.2]
    · rw [sem_pow_neg_nat]
      simp only [Set.mem_Icc]
      exact ⟨hzp.1, hzp.2⟩
  | powGeneral hbase hexp hxl hln hmul hexpst ihb ihe =>
    intro hab x hx
    obtain ⟨hdb, hmb⟩ := ihb hab x hx
    obtain ⟨hde, hme⟩ := ihe hab x hx
    have h := rpow_general_encloses _ _ _ _ _ _ _ _ _ _ hxl hln hmul hexpst
      _ _ hmb.1 hmb.2 hme.1 hme.2
    refine ⟨⟨hdb, hde, Or.inl (lt_of_lt_of_le hxl hmb.1)⟩, ?_⟩
    simp only [sem, Set.mem_Icc]
    exact ⟨h.1, h.2⟩
  | sqrt hr hguard hlo hhi ih =>
    intro hab x hx
    obtain ⟨hd, hm⟩ := ih hab x hx
    have h := iv_sqrt_encloses _ _ _ _ _ hm (le_trans hm.1 hm.2) hlo hhi
    refine ⟨⟨hd, ?_⟩, ?_⟩
    · simp only [call1Dom_sqrt]; exact le_trans hguard hm.1
    · simp only [sem, call1Sem_sqrt, Set.mem_Icc]
      exact ⟨max_le h.1 (Real.sqrt_nonneg _), h.2⟩
  | exp hr hlo hhi ih =>
    intro hab x hx
    obtain ⟨hd, hm⟩ := ih hab x hx
    have h := iv_exp_encloses _ _ _ _ _ hm (le_trans hm.1 hm.2) hlo hhi
    refine ⟨⟨hd, by simp [call1Dom]⟩, ?_⟩
    simp only [sem, call1Sem_exp, Set.mem_Icc]
    exact ⟨h.1, h.2⟩
  | log hr hguard hlo hhi ih =>
    intro hab x hx
    obtain ⟨hd, hm⟩ := ih hab x hx
    have h := iv_log_encloses _ _ _ _ _ hguard hm (le_trans hm.1 hm.2) hlo hhi
    refine ⟨⟨hd, ?_⟩, ?_⟩
    · simp only [call1Dom_ln]; exact lt_of_lt_of_le hguard hm.1
    · simp only [sem, call1Sem_ln, Set.mem_Icc]
      exact ⟨h.1, h.2⟩
  | sin hr ih =>
    intro hab x hx
    obtain ⟨hd, _⟩ := ih hab x hx
    refine ⟨⟨hd, by simp [call1Dom]⟩, ?_⟩
    simp only [sem, call1Sem_sin, Set.mem_Icc]
    exact ⟨Real.neg_one_le_sin _, Real.sin_le_one _⟩
  | cos hr ih =>
    intro hab x hx
    obtain ⟨hd, _⟩ := ih hab x hx
    refine ⟨⟨hd, by simp [call1Dom]⟩, ?_⟩
    simp only [sem, call1Sem_cos, Set.mem_Icc]
    exact ⟨Real.neg_one_le_cos _, Real.cos_le_one _⟩
  | atan hr hlo hhi ih =>
    intro hab x hx
    obtain ⟨hd, hm⟩ := ih hab x hx
    have h := iv_atan_encloses _ _ _ _ _ hm (le_trans hm.1 hm.2) hlo hhi
    refine ⟨⟨hd, by simp [call1Dom]⟩, ?_⟩
    simp only [sem, call1Sem_atan, Set.mem_Icc]
    exact ⟨h.1, h.2⟩
  | asin hr hdom hlo hhi ih =>
    intro hab x hx
    obtain ⟨hd, hm⟩ := ih hab x hx
    have h := iv_asin_encloses _ _ _ _ _ hdom hm (le_trans hm.1 hm.2) hlo hhi
    refine ⟨⟨hd, ?_⟩, ?_⟩
    · simp only [call1Dom_asin]
      exact ⟨le_trans hdom.1 hm.1, le_trans hm.2 hdom.2⟩
    · simp only [sem, call1Sem_asin, Set.mem_Icc]
      exact ⟨h.1, h.2⟩
  | acos hr hdom hlo hhi ih =>
    intro hab x hx
    obtain ⟨hd, hm⟩ := ih hab x hx
    have h := iv_acos_encloses _ _ _ _ _ hdom hm (le_trans hm.1 hm.2) hlo hhi
    refine ⟨⟨hd, ?_⟩, ?_⟩
    · simp only [call1Dom_acos]
      exact ⟨le_trans hdom.1 hm.1, le_trans hm.2 hdom.2⟩
    · simp only [sem, call1Sem_acos, Set.mem_Icc]
      exact ⟨h.1, h.2⟩
  | abs hr ih =>
    intro hab x hx
    obtain ⟨hd, hm⟩ := ih hab x hx
    have h := iv_abs_encloses _ _ _ hm.1 hm.2
    refine ⟨⟨hd, by simp [call1Dom]⟩, ?_⟩
    simp only [sem, call1Sem_abs, Set.mem_Icc]
    exact ⟨h.1, h.2⟩
  | floor hr ih =>
    intro hab x hx
    obtain ⟨hd, hm⟩ := ih hab x hx
    have h := floor_mem _ _ _ hm.1 hm.2
    refine ⟨⟨hd, by simp [call1Dom]⟩, ?_⟩
    simp only [sem, call1Sem_floor, Set.mem_Icc]
    exact ⟨h.1, h.2⟩
  | ceil hr ih =>
    intro hab x hx
    obtain ⟨hd, hm⟩ := ih hab x hx
    have h := ceil_mem _ _ _ hm.1 hm.2
    refine ⟨⟨hd, by simp [call1Dom]⟩, ?_⟩
    simp only [sem, call1Sem_ceil, Set.mem_Icc]
    exact ⟨h.1, h.2⟩
  | round hr ih =>
    intro hab x hx
    obtain ⟨hd, hm⟩ := ih hab x hx
    have h := roundAway_mem _ _ _ hm.1 hm.2
    refine ⟨⟨hd, by simp [call1Dom]⟩, ?_⟩
    simp only [sem, call1Sem_round, Set.mem_Icc]
    exact ⟨h.1, h.2⟩
  | trunc hr ih =>
    intro hab x hx
    obtain ⟨hd, hm⟩ := ih hab x hx
    have h := trunc_mem _ _ _ hm.1 hm.2
    refine ⟨⟨hd, by simp [call1Dom]⟩, ?_⟩
    simp only [sem, call1Sem_trunc, Set.mem_Icc]
    exact ⟨h.1, h.2⟩
  | min hr₁ hr₂ ih₁ ih₂ =>
    intro hab x hx
    obtain ⟨hd₁, hm₁⟩ := ih₁ hab x hx
    obtain ⟨hd₂, hm₂⟩ := ih₂ hab x hx
    have h := iv_min_encloses _ _ _ _ _ _ hm₁.1 hm₁.2 hm₂.1 hm₂.2
    refine ⟨⟨hd₁, hd₂, by simp [call2Dom]⟩, ?_⟩
    simp only [sem, call2Sem_min, Set.mem_Icc]
    exact ⟨h.1, h.2⟩
  | max hr₁ hr₂ ih₁ ih₂ =>
    intro hab x hx
    obtain ⟨hd₁, hm₁⟩ := ih₁ hab x hx
    obtain ⟨hd₂, hm₂⟩ := ih₂ hab x hx
    have h := iv_max_encloses _ _ _ _ _ _ hm₁.1 hm₁.2 hm₂.1 hm₂.2
    refine ⟨⟨hd₁, hd₂, by simp [call2Dom]⟩, ?_⟩
    simp only [sem, call2Sem_max, Set.mem_Icc]
    exact ⟨h.1, h.2⟩
  | hypot hr₁ hr₂ hlo hhi ih₁ ih₂ =>
    intro hab x hx
    obtain ⟨hd₁, hm₁⟩ := ih₁ hab x hx
    obtain ⟨hd₂, hm₂⟩ := ih₂ hab x hx
    have h := iv_hypot_encloses _ _ _ _ _ _ _ _ hm₁.1 hm₁.2 hm₂.1 hm₂.2 hlo hhi
    refine ⟨⟨hd₁, hd₂, by simp [call2Dom]⟩, ?_⟩
    simp only [sem, call2Sem_hypot, Set.mem_Icc]
    exact ⟨h.1, h.2⟩
  | atan2 hr₁ hr₂ hxpos h1 h2 h3 h4 ha hb ih₁ ih₂ =>
    intro hab x hx
    obtain ⟨hd₁, hm₁⟩ := ih₁ hab x hx
    obtain ⟨hd₂, hm₂⟩ := ih₂ hab x hx
    have h := iv_atan2_encloses _ _ _ _ _ _ _ _ _ _ _ _
      hm₁.1 hm₁.2 hm₂.1 hm₂.2 hxpos h1 h2 h3 h4 ha hb
    refine ⟨⟨hd₁, hd₂, ?_⟩, ?_⟩
    · simp only [call2Dom_atan2]; exact lt_of_lt_of_le hxpos hm₂.1
    · simp only [sem, call2Sem_atan2, Set.mem_Icc, atan2R] at h ⊢
      exact ⟨h.1, h.2⟩

/-- MAIN THEOREM (composition): a completed run of the modeled `ieval` on `e`
over a nonempty input interval `[a, b]` producing the box `[lo, hi]`
guarantees, for EVERY `x ∈ [a, b]`, structural definedness at `x` and that
the exact value `sem e x` lies in `[lo, hi]`.  This is the per-op lemmas of
Arith/Monotone/Exact/Pow composed through the whole expression tree — the
soundness statement for the engine's `ieval` under the rounding model. -/
theorem runs_encloses {e : Expr} {a b lo hi : ℝ}
    (hrun : Runs e (a, b) (lo, hi)) (hab : a ≤ b) :
    ∀ x ∈ Set.Icc a b, DefinedOn e x ∧ sem e x ∈ Set.Icc lo hi :=
  runs_sound hrun hab

/-- The same guarantee phrased through the model's `Encloses` predicate. -/
theorem runs_encloses_image {e : Expr} {a b lo hi : ℝ}
    (hrun : Runs e (a, b) (lo, hi)) (hab : a ≤ b) :
    Encloses ⟨lo, hi⟩ (sem e '' Set.Icc a b) := by
  rintro y ⟨x, hx, rfl⟩
  have h := (runs_encloses hrun hab x hx).2
  exact ⟨h.1, h.2⟩

#print axioms runs_encloses

end JackalIv
