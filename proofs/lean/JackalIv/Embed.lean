/-
JackalIv/Embed.lean — the COMPOSITION theorem: a deep embedding of the
smooth expression core of `ieval`, an execution relation carrying exactly
the per-operator hypotheses already proved sound in Arith/Monotone/Pow, and
the whole-expression guarantee that any completed run encloses the exact
semantics at every point of the input interval.

Engine correspondence (`jackal_calc.anb`, section "JACKAL CERTIFIED INTERVAL
ENGINE", fn `ieval` line 2491, git 8a71540).  Constructor → engine map:

| Runs constructor  | engine branch (line)                | containment lemma used     |
|-------------------|-------------------------------------|----------------------------|
| `num_exact`       | `iv_from_literal` integer branch    | exact, no pad              |
|                   |   → `iv_exact` (2481–2483, 2210)    |                            |
| `num_rounded`     | `iv_from_literal` rounded branch    | `basic_brackets`           |
|                   |   → `iv_out(v, v)` (2484)           |                            |
| `var`             | `ieval` tag "var" (2495–2498)       | exact, no pad              |
| `neg`             | `iv_neg` (2500–2503, 2243)          | `iv_neg_encloses` shape    |
| `add`             | `iv_add` (2545, 2231)               | `iv_add_encloses`          |
| `sub`             | `iv_sub` (2546, 2237)               | `iv_sub_encloses`          |
| `mul`             | `iv_mul` (2547, 2248)               | `iv_mul_encloses`          |
| `div`             | `iv_div` (2548, 2258; zero-free     | `iv_div_encloses`          |
|                   |   guard line 2261)                  |                            |
| `powZero`         | `iv_pow_int`, n = 0 (2287)          | `zpow_zero`, exact         |
| `powEvenPos`      | `iv_pow_int`, even n ≥ 2 (2293–94)  | `iv_pow_int_even_encloses` |
| `powOddPos`       | `iv_pow_int`, odd n ≥ 1 (2295–96)   | `iv_pow_int_odd_encloses`  |
| `powNegEven`      | `iv_pow_int`, n ≤ -1, even core     | even lemma +               |
|                   |   (2290, 2299–2301)                 |   `iv_pow_neg_encloses_zpow`|
| `powNegOdd`       | `iv_pow_int`, n ≤ -1, odd core      | odd lemma +                |
|                   |   (2290, 2299–2301)                 |   `iv_pow_neg_encloses_zpow`|
| `sqrt`            | `iv_sqrt` (2529, 2315; guard 2317,  | `iv_sqrt_encloses`         |
|                   |   final `lo := max(lo,0)` 2320–21)  |                            |
| `exp`             | `iv_exp` (2534, 2330)               | `iv_exp_encloses`          |
| `log`             | `iv_ln` (2531, 2335; guard 2337)    | `iv_log_encloses`          |
| `sin`             | `iv_sin` (2523, 2370) — see below   | `sin_mem_Icc` ([-1,1])     |
| `cos`             | `iv_cos` (2524, 2387) — see below   | `cos_mem_Icc` ([-1,1])     |
| `atan`            | `iv_atan` (2528, 2426)              | `iv_atan_encloses`         |

HONEST OMISSIONS (fail-closed: an operator absent here simply has no `Runs`
constructor — no unsound approximation is smuggled in):

* `tan` / `asin` / `acos` / `cbrt` / `log10` / `log2` / `hypot` / `atan2` /
  `abs` / `min` / `max` / floor-family / `iv_pow_general` are NOT embedded.
  Their per-op containment lemmas live in Monotone.lean / Exact.lean /
  Pow.lean; wiring them into this induction is future work, not a soundness
  gap.  `mod` is refused by the engine itself (line 2549).
* `sin` / `cos` use the SIMPLEST sound constructor: the universal `[-1, 1]`
  enclosure (every `iv_sin`/`iv_cos` branch returns a sub-box of `[-1, 1]`
  after the final clamp, lines 2382–83 / 2399–2400, so this models a
  conservative widening of every engine branch).  The engine's tighter
  padded endpoint hulls and one-sided widenings are separately proved in
  Trig.lean; a model run through this relation may therefore be WIDER than
  the shipped box at sin/cos nodes (and may refuse a division the engine
  accepts) — conservative in the sound direction.
* `num_exact` models the engine's float-level "integer-valued f64 in exact
  range" test simply as: the literal IS the intended real (no pad).  The
  float fact backing that test is part of the disclosed model residual
  (Ledger.lean).

`DefinedOn` is the structural definedness predicate the composition theorem
additionally delivers: division denominators nonzero at `x`, `log` arguments
strictly positive, `sqrt` arguments nonnegative, and (beyond the task's
minimum, for zpow honesty) nonzero base under a negative integer power.
`sem` is total via Mathlib's junk values (`Real.log`/`Real.sqrt`/`zpow`);
`DefinedOn` is exactly what upgrades the junk-totalized reading to the
real-mathematics reading on the engine-accepted domain.
-/
import JackalIv.Model
import JackalIv.Pad
import JackalIv.Arith
import JackalIv.Monotone
import JackalIv.Pow

namespace JackalIv

/-! ### The deep-embedded smooth expression core of `ieval` -/

/-- Expression AST: the smooth core of the engine grammar (`ieval`,
jackal_calc.anb line 2491).  `num` covers both the "num" and "const" tags
(both route through `iv_from_literal`, line 2493–2494). -/
inductive Expr : Type
  | num (r : ℝ)
  | var
  | neg (e : Expr)
  | add (e₁ e₂ : Expr)
  | sub (e₁ e₂ : Expr)
  | mul (e₁ e₂ : Expr)
  | div (e₁ e₂ : Expr)
  | powInt (e : Expr) (n : ℤ)
  | sqrt (e : Expr)
  | exp (e : Expr)
  | log (e : Expr)
  | sin (e : Expr)
  | cos (e : Expr)
  | atan (e : Expr)

/-- Total semantics over ℝ, junk-totalized exactly as Mathlib totalizes the
partial functions: `x / 0 = 0`, `Real.sqrt` of a negative is `0`,
`Real.log` of a nonpositive is `0`, `0 ^ (negative : ℤ) = 0`.
`DefinedOn` (below) carves out the domain where these junk values are
never consulted. -/
noncomputable def sem : Expr → ℝ → ℝ
  | .num r, _ => r
  | .var, x => x
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

/-- Structural definedness at a point: every division denominator is
nonzero, every `log` argument is strictly positive, every `sqrt` argument
is nonnegative, and every negative integer power has a nonzero base.
This is what the engine's domain guards purchase. -/
def DefinedOn : Expr → ℝ → Prop
  | .num _, _ => True
  | .var, _ => True
  | .neg e, x => DefinedOn e x
  | .add e₁ e₂, x => DefinedOn e₁ x ∧ DefinedOn e₂ x
  | .sub e₁ e₂, x => DefinedOn e₁ x ∧ DefinedOn e₂ x
  | .mul e₁ e₂, x => DefinedOn e₁ x ∧ DefinedOn e₂ x
  | .div e₁ e₂, x => DefinedOn e₁ x ∧ DefinedOn e₂ x ∧ sem e₂ x ≠ 0
  | .powInt e n, x => DefinedOn e x ∧ (n < 0 → sem e x ≠ 0)
  | .sqrt e, x => DefinedOn e x ∧ 0 ≤ sem e x
  | .exp e, x => DefinedOn e x
  | .log e, x => DefinedOn e x ∧ 0 < sem e x
  | .sin e, x => DefinedOn e x
  | .cos e, x => DefinedOn e x
  | .atan e, x => DefinedOn e x

/-! ### The execution relation

`Runs e (a, b) (lo, hi)` reads: on input interval `[a, b]`, a run of the
modeled `ieval` on `e` completed (no refusal) and produced the box
`[lo, hi]`.  Each constructor carries EXACTLY the hypotheses of that
operator's containment lemma: the `Approx` side conditions on the computed
float endpoints, and the domain guards on which the engine refuses. -/
inductive Runs : Expr → ℝ × ℝ → ℝ × ℝ → Prop
  /-- `iv_from_literal` integer-exact branch (line 2481) → `iv_exact` (2210):
  the literal is the intended real, no pad. -/
  | num_exact {r a b : ℝ} : Runs (.num r) (a, b) (r, r)
  /-- `iv_from_literal` rounded branch (line 2484): the stored f64 `fl` is
  the correct rounding of the intended real `r` (≤ 0.5 ulp, `Approx δ0 σ0`),
  and `iv_out(fl, fl)` pads it. -/
  | num_rounded {r a b fl : ℝ} (h : Approx δ0 σ0 fl r) :
      Runs (.num r) (a, b) (padLo fl, padHi fl)
  /-- `ieval` tag "var" (line 2497): the input box itself, exact. -/
  | var {a b : ℝ} : Runs .var (a, b) (a, b)
  /-- `iv_neg` (line 2243): IEEE negation is exact, endpoints swap, no pad. -/
  | neg {e : Expr} {a b l u : ℝ} (hr : Runs e (a, b) (l, u)) :
      Runs (.neg e) (a, b) (-u, -l)
  /-- `iv_add` (line 2231): one basic op per endpoint, `iv_out` pad. -/
  | add {e₁ e₂ : Expr} {a b l₁ u₁ l₂ u₂ fl_lo fl_hi : ℝ}
      (hr₁ : Runs e₁ (a, b) (l₁, u₁)) (hr₂ : Runs e₂ (a, b) (l₂, u₂))
      (hlo : Approx δ0 σ0 fl_lo (l₁ + l₂)) (hhi : Approx δ0 σ0 fl_hi (u₁ + u₂)) :
      Runs (.add e₁ e₂) (a, b) (padLo fl_lo, padHi fl_hi)
  /-- `iv_sub` (line 2237): endpoints `lo₁ − hi₂` / `hi₁ − lo₂`, padded. -/
  | sub {e₁ e₂ : Expr} {a b l₁ u₁ l₂ u₂ fl_lo fl_hi : ℝ}
      (hr₁ : Runs e₁ (a, b) (l₁, u₁)) (hr₂ : Runs e₂ (a, b) (l₂, u₂))
      (hlo : Approx δ0 σ0 fl_lo (l₁ - u₂)) (hhi : Approx δ0 σ0 fl_hi (u₁ - l₂)) :
      Runs (.sub e₁ e₂) (a, b) (padLo fl_lo, padHi fl_hi)
  /-- `iv_mul` (line 2248): four rounded corner products, exact float
  min/max, `iv_out` pad on the selected extremes. -/
  | mul {e₁ e₂ : Expr} {a b l₁ u₁ l₂ u₂ p1 p2 p3 p4 : ℝ}
      (hr₁ : Runs e₁ (a, b) (l₁, u₁)) (hr₂ : Runs e₂ (a, b) (l₂, u₂))
      (h1 : Approx δ0 σ0 p1 (l₁ * l₂)) (h2 : Approx δ0 σ0 p2 (l₁ * u₂))
      (h3 : Approx δ0 σ0 p3 (u₁ * l₂)) (h4 : Approx δ0 σ0 p4 (u₁ * u₂)) :
      Runs (.mul e₁ e₂) (a, b)
        (padLo (min (min p1 p2) (min p3 p4)), padHi (max (max p1 p2) (max p3 p4)))
  /-- `iv_div` (line 2258): the zero-free-denominator guard (line 2261,
  `b.lo <= 0 && b.hi >= 0 → refuse`, i.e. `0 < l₂ ∨ u₂ < 0`), four rounded
  corner quotients, exact min/max, `iv_out` pad. -/
  | div {e₁ e₂ : Expr} {a b l₁ u₁ l₂ u₂ q1 q2 q3 q4 : ℝ}
      (hr₁ : Runs e₁ (a, b) (l₁, u₁)) (hr₂ : Runs e₂ (a, b) (l₂, u₂))
      (hden : 0 < l₂ ∨ u₂ < 0)
      (h1 : Approx δ0 σ0 q1 (l₁ / l₂)) (h2 : Approx δ0 σ0 q2 (l₁ / u₂))
      (h3 : Approx δ0 σ0 q3 (u₁ / l₂)) (h4 : Approx δ0 σ0 q4 (u₁ / u₂)) :
      Runs (.div e₁ e₂) (a, b)
        (padLo (min (min q1 q2) (min q3 q4)), padHi (max (max q1 q2) (max q3 q4)))
  /-- `iv_pow_int`, n = 0 (line 2287): `iv_exact(1.0)`, no pad. -/
  | powZero {e : Expr} {a b l u : ℝ} (hr : Runs e (a, b) (l, u)) :
      Runs (.powInt e 0) (a, b) (1, 1)
  /-- `iv_pow_int`, even n ≥ 2 (lines 2293–2294): libm `pow` at the exact
  mignitude/magnitude of the child box, `iv_out` pad. -/
  | powEvenPos (n : ℕ) (hn : Even n) (hn2 : 2 ≤ n) {e : Expr} {a b l u fl_lo fl_hi : ℝ}
      (hr : Runs e (a, b) (l, u))
      (hlo : Approx δlib σ0 fl_lo (mig l u ^ n))
      (hhi : Approx δlib σ0 fl_hi (mag l u ^ n)) :
      Runs (.powInt e (n : ℤ)) (a, b) (padLo fl_lo, padHi fl_hi)
  /-- `iv_pow_int`, odd n ≥ 1 (lines 2295–2296): libm `pow` at the child
  endpoints (odd powers are monotone), `iv_out` pad. -/
  | powOddPos (n : ℕ) (hn : Odd n) {e : Expr} {a b l u fl_lo fl_hi : ℝ}
      (hr : Runs e (a, b) (l, u))
      (hlo : Approx δlib σ0 fl_lo (l ^ n)) (hhi : Approx δlib σ0 fl_hi (u ^ n)) :
      Runs (.powInt e (n : ℤ)) (a, b) (padLo fl_lo, padHi fl_hi)
  /-- `iv_pow_int`, n ≤ -1 with even core (lines 2290, 2299–2301): the even
  positive-power core `[padLo fl_lo, padHi fl_hi]`, then
  `iv_div(iv_exact(1.0), core)` — zero-free guard on the core, four rounded
  reciprocal corners (`1/cl`, `1/cu` each twice, since the numerator box is
  the exact point `[1,1]`), `iv_out` pad. -/
  | powNegEven (m : ℕ) (hm : Even m) (hm2 : 2 ≤ m) {e : Expr} {a b l u fl_lo fl_hi q1 q2 q3 q4 : ℝ}
      (hr : Runs e (a, b) (l, u))
      (hclo : Approx δlib σ0 fl_lo (mig l u ^ m))
      (hchi : Approx δlib σ0 fl_hi (mag l u ^ m))
      (hden : 0 < padLo fl_lo ∨ padHi fl_hi < 0)
      (h1 : Approx δ0 σ0 q1 (1 / padLo fl_lo)) (h2 : Approx δ0 σ0 q2 (1 / padHi fl_hi))
      (h3 : Approx δ0 σ0 q3 (1 / padLo fl_lo)) (h4 : Approx δ0 σ0 q4 (1 / padHi fl_hi)) :
      Runs (.powInt e (-(m : ℤ))) (a, b)
        (padLo (min (min q1 q2) (min q3 q4)), padHi (max (max q1 q2) (max q3 q4)))
  /-- `iv_pow_int`, n ≤ -1 with odd core (lines 2290, 2299–2301): as
  `powNegEven` but the core is the odd endpoint lane. -/
  | powNegOdd (m : ℕ) (hm : Odd m) {e : Expr} {a b l u fl_lo fl_hi q1 q2 q3 q4 : ℝ}
      (hr : Runs e (a, b) (l, u))
      (hclo : Approx δlib σ0 fl_lo (l ^ m)) (hchi : Approx δlib σ0 fl_hi (u ^ m))
      (hden : 0 < padLo fl_lo ∨ padHi fl_hi < 0)
      (h1 : Approx δ0 σ0 q1 (1 / padLo fl_lo)) (h2 : Approx δ0 σ0 q2 (1 / padHi fl_hi))
      (h3 : Approx δ0 σ0 q3 (1 / padLo fl_lo)) (h4 : Approx δ0 σ0 q4 (1 / padHi fl_hi)) :
      Runs (.powInt e (-(m : ℤ))) (a, b)
        (padLo (min (min q1 q2) (min q3 q4)), padHi (max (max q1 q2) (max q3 q4)))
  /-- `iv_sqrt` (line 2315): guard `a.lo < 0 → refuse` (line 2317, so
  `0 ≤ l`), libm sqrt at the endpoints, `iv_out` pad, then the final
  `lo := max(lo, 0)` clamp (lines 2320–2321). -/
  | sqrt {e : Expr} {a b l u fl_lo fl_hi : ℝ}
      (hr : Runs e (a, b) (l, u)) (hguard : 0 ≤ l)
      (hlo : Approx δlib σ0 fl_lo (Real.sqrt l))
      (hhi : Approx δlib σ0 fl_hi (Real.sqrt u)) :
      Runs (.sqrt e) (a, b) (max (padLo fl_lo) 0, padHi fl_hi)
  /-- `iv_exp` (line 2330): libm exp at the endpoints (monotone), padded. -/
  | exp {e : Expr} {a b l u fl_lo fl_hi : ℝ}
      (hr : Runs e (a, b) (l, u))
      (hlo : Approx δlib σ0 fl_lo (Real.exp l))
      (hhi : Approx δlib σ0 fl_hi (Real.exp u)) :
      Runs (.exp e) (a, b) (padLo fl_lo, padHi fl_hi)
  /-- `iv_ln` (line 2335): guard `a.lo <= 0 → refuse` (line 2337, so
  `0 < l`), libm ln at the endpoints (monotone), padded. -/
  | log {e : Expr} {a b l u fl_lo fl_hi : ℝ}
      (hr : Runs e (a, b) (l, u)) (hguard : 0 < l)
      (hlo : Approx δlib σ0 fl_lo (Real.log l))
      (hhi : Approx δlib σ0 fl_hi (Real.log u)) :
      Runs (.log e) (a, b) (padLo fl_lo, padHi fl_hi)
  /-- `iv_sin` (line 2370), modeled by its universal fallback: every branch
  returns a sub-box of `[-1, 1]` after the final clamp (lines 2382–2383),
  so `[-1, 1]` is a sound (conservative) model of every branch.  The
  engine's tighter hulls are separately proved in Trig.lean. -/
  | sin {e : Expr} {a b l u : ℝ} (hr : Runs e (a, b) (l, u)) :
      Runs (.sin e) (a, b) (-1, 1)
  /-- `iv_cos` (line 2387), same universal fallback (clamp lines 2399–2400);
  tighter hulls in Trig.lean. -/
  | cos {e : Expr} {a b l u : ℝ} (hr : Runs e (a, b) (l, u)) :
      Runs (.cos e) (a, b) (-1, 1)
  /-- `iv_atan` (line 2426): libm atan at the endpoints (monotone), padded. -/
  | atan {e : Expr} {a b l u fl_lo fl_hi : ℝ}
      (hr : Runs e (a, b) (l, u))
      (hlo : Approx δlib σ0 fl_lo (Real.arctan l))
      (hhi : Approx δlib σ0 fl_hi (Real.arctan u)) :
      Runs (.atan e) (a, b) (padLo fl_lo, padHi fl_hi)

/-! ### The composition theorem -/

/-- Pair-projection form of the composition theorem (the induction motive;
`runs_encloses` below is the clean statement).  Any completed run on a
nonempty input interval delivers, at every point of the interval, both
structural definedness and containment of the exact value in the output
box. -/
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
  | var =>
    intro _ x hx
    exact ⟨trivial, hx⟩
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
    refine ⟨⟨hd, fun hcon => absurd hcon (lt_irrefl 0)⟩, ?_⟩
    simp only [sem, zpow_zero, Set.mem_Icc]
    exact ⟨le_rfl, le_rfl⟩
  | powEvenPos n hn hn2 hr hlo hhi ih =>
    intro hab x hx
    obtain ⟨hd, hm⟩ := ih hab x hx
    have h := iv_pow_int_even_encloses n hn hn2 _ _ _ _ _ hm.1 hm.2 hlo hhi
    refine ⟨⟨hd, fun hcon => absurd hcon (not_lt.mpr (Int.natCast_nonneg n))⟩, ?_⟩
    simp only [sem, zpow_natCast, Set.mem_Icc]
    exact ⟨h.1, h.2⟩
  | powOddPos n hn hr hlo hhi ih =>
    intro hab x hx
    obtain ⟨hd, hm⟩ := ih hab x hx
    have h := iv_pow_int_odd_encloses n hn _ _ _ _ _ hm.1 hm.2 hlo hhi
    refine ⟨⟨hd, fun hcon => absurd hcon (not_lt.mpr (Int.natCast_nonneg n))⟩, ?_⟩
    simp only [sem, zpow_natCast, Set.mem_Icc]
    exact ⟨h.1, h.2⟩
  | powNegEven m hm hm2 hr hclo hchi hden h1 h2 h3 h4 ih =>
    intro hab x hx
    obtain ⟨hd, hmem⟩ := ih hab x hx
    have hcore := iv_pow_int_even_encloses m hm hm2 _ _ _ _ _ hmem.1 hmem.2 hclo hchi
    have hzp := iv_pow_neg_encloses_zpow m _ _ _ _ _ _ _ hcore.1 hcore.2 hden h1 h2 h3 h4
    refine ⟨⟨hd, fun _ => ?_⟩, ?_⟩
    · intro h0
      have hm0 : m ≠ 0 := by omega
      have hc1 := hcore.1
      have hc2 := hcore.2
      rw [h0, zero_pow hm0] at hc1 hc2
      rcases hden with hpos | hneg
      · linarith
      · linarith
    · simp only [sem, Set.mem_Icc]
      exact ⟨hzp.1, hzp.2⟩
  | powNegOdd m hm hr hclo hchi hden h1 h2 h3 h4 ih =>
    intro hab x hx
    obtain ⟨hd, hmem⟩ := ih hab x hx
    have hcore := iv_pow_int_odd_encloses m hm _ _ _ _ _ hmem.1 hmem.2 hclo hchi
    have hzp := iv_pow_neg_encloses_zpow m _ _ _ _ _ _ _ hcore.1 hcore.2 hden h1 h2 h3 h4
    refine ⟨⟨hd, fun _ => ?_⟩, ?_⟩
    · intro h0
      have hm0 : m ≠ 0 := by rcases hm with ⟨k, hk⟩; omega
      have hc1 := hcore.1
      have hc2 := hcore.2
      rw [h0, zero_pow hm0] at hc1 hc2
      rcases hden with hpos | hneg
      · linarith
      · linarith
    · simp only [sem, Set.mem_Icc]
      exact ⟨hzp.1, hzp.2⟩
  | sqrt hr hguard hlo hhi ih =>
    intro hab x hx
    obtain ⟨hd, hm⟩ := ih hab x hx
    have h := iv_sqrt_encloses _ _ _ _ _ hm (le_trans hm.1 hm.2) hlo hhi
    refine ⟨⟨hd, le_trans hguard hm.1⟩, ?_⟩
    simp only [sem, Set.mem_Icc]
    exact ⟨max_le h.1 (Real.sqrt_nonneg _), h.2⟩
  | exp hr hlo hhi ih =>
    intro hab x hx
    obtain ⟨hd, hm⟩ := ih hab x hx
    have h := iv_exp_encloses _ _ _ _ _ hm (le_trans hm.1 hm.2) hlo hhi
    refine ⟨hd, ?_⟩
    simp only [sem, Set.mem_Icc]
    exact ⟨h.1, h.2⟩
  | log hr hguard hlo hhi ih =>
    intro hab x hx
    obtain ⟨hd, hm⟩ := ih hab x hx
    have h := iv_log_encloses _ _ _ _ _ hguard hm (le_trans hm.1 hm.2) hlo hhi
    refine ⟨⟨hd, lt_of_lt_of_le hguard hm.1⟩, ?_⟩
    simp only [sem, Set.mem_Icc]
    exact ⟨h.1, h.2⟩
  | sin hr ih =>
    intro hab x hx
    obtain ⟨hd, _⟩ := ih hab x hx
    refine ⟨hd, ?_⟩
    simp only [sem, Set.mem_Icc]
    exact ⟨Real.neg_one_le_sin _, Real.sin_le_one _⟩
  | cos hr ih =>
    intro hab x hx
    obtain ⟨hd, _⟩ := ih hab x hx
    refine ⟨hd, ?_⟩
    simp only [sem, Set.mem_Icc]
    exact ⟨Real.neg_one_le_cos _, Real.cos_le_one _⟩
  | atan hr hlo hhi ih =>
    intro hab x hx
    obtain ⟨hd, hm⟩ := ih hab x hx
    have h := iv_atan_encloses _ _ _ _ _ hm (le_trans hm.1 hm.2) hlo hhi
    refine ⟨hd, ?_⟩
    simp only [sem, Set.mem_Icc]
    exact ⟨h.1, h.2⟩

/-- MAIN THEOREM (composition): a completed run of the modeled `ieval` on
`e` over a nonempty input interval `[a, b]` producing the box `[lo, hi]`
guarantees, for EVERY `x ∈ [a, b]`, that the expression is structurally
defined at `x` (division denominators nonzero, log arguments positive,
sqrt arguments nonnegative, negative-power bases nonzero) and that the
exact value `sem e x` lies in `[lo, hi]`.  This is the per-op lemmas of
Arith/Monotone/Pow composed through the whole expression tree — the
soundness statement for the engine's `ieval` under the rounding model. -/
theorem runs_encloses {e : Expr} {a b lo hi : ℝ}
    (hrun : Runs e (a, b) (lo, hi)) (hab : a ≤ b) :
    ∀ x ∈ Set.Icc a b, DefinedOn e x ∧ sem e x ∈ Set.Icc lo hi :=
  runs_sound hrun hab

/-- The same guarantee phrased through the model's `Encloses` predicate:
the output box encloses the exact image of the input interval. -/
theorem runs_encloses_image {e : Expr} {a b lo hi : ℝ}
    (hrun : Runs e (a, b) (lo, hi)) (hab : a ≤ b) :
    Encloses ⟨lo, hi⟩ (sem e '' Set.Icc a b) := by
  rintro y ⟨x, hx, rfl⟩
  have h := (runs_encloses hrun hab x hx).2
  exact ⟨h.1, h.2⟩

#print axioms runs_encloses

end JackalIv
