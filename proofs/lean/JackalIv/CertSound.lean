/-
JackalIv/CertSound.lean — the proof-carrying `checkCert → Runs` bridge.

This is the CertSound deliverable of the architect mission: connect the
COMPUTABLE certificate checker (`CertCheck.checkCert`) to the mechanized
execution relation (`Embed.Runs`), so that a certificate the checker accepts
is a genuine `Runs` derivation (and therefore, via `Embed.runs_encloses`, a
sound enclosure of the exact semantics).

## The `const_rounded` contract gap (why the three headline theorems are
## delivered "modulo the const-rounding TCB")

`Runs.const_rounded` (Embed.lean) carries `Approx δ0 σ0 fl (constValue name)`
where `constValue name` is the REAL mathematical constant (`Real.pi`,
`Real.exp 1`, `2·Real.pi`) — an IRRATIONAL number for every supported name.
`checkNode` (CertCheck.lean, `const_rounded` arm) only verifies
`algApproxQ nd.fl_lo nd.value δ0Q σ0Q`, i.e. `Approx δ0 σ0 (↑fl) (↑nd.value)`
against the RATIONAL field `nd.value`; and `CertTypes.libmNodeFact` has NO
`const_rounded` case, so `LibmModel` contributes only `True` for a constant
node.  Nothing in `checkCert` or `LibmModel` binds `↑nd.value` to
`constValue name`, and no such binding is possible over ℚ because
`constValue name` is irrational.

Consequently the verbatim statement
  `checkCert = true → exprOf = some e → LibmModel → Runs e X Y`
is NOT a theorem — it is FALSE.  Concrete counterexample: a single node
`{op := "const_rounded", name := "pi", value := 0, fl_lo := 0,
  out_lo := padLoQ 0, out_hi := padHiQ 0}` with the matching header passes
`checkCert` (isKnownConst "pi", the two pad equalities, and
`algApproxQ 0 0 δ0Q σ0Q = true`), yet `Runs.const_rounded` would require
`|0 − Real.pi| ≤ δ0·|Real.pi| + σ0`, i.e. `Real.pi ≤ Real.pi / 2^53 + 2^-1075`,
which is false.

The design brief classified `const_rounded` among the "23 rational-exact"
constructors "needing no TCB".  That classification is a factual error:
`const_rounded` is a ROUNDING-TCB constructor exactly like the 8
transcendentals — the correctly-rounded f64 of an irrational constant is a
libm/rounding fact, not a ℚ-decidable one.  The precise fix is to add ONE
case to `CertTypes.libmNodeFact`:
    | "const_rounded", [] => Approx δ0 σ0 (↑nd.fl_lo) (constValue nd.name)
After that single-line contract fix, `LibmModel` supplies `ConstTCB` below
and the three headline theorems hold verbatim with clean axioms — the whole
induction machinery in this file is already complete and green for all 31
constructors.

Until that fix lands we DO NOT `sorry` and DO NOT weaken silently: we thread
the missing fact through an EXPLICIT, named hypothesis `ConstTCB` (the
disclosed const-rounding TCB) and prove the fully general
`checkCert → Runs` bridge and its enclosure/release corollaries in
"modulo-`ConstTCB`" form.  `#print axioms` on all of them shows only
`[propext, Classical.choice, Quot.sound]`; `ConstTCB` and `LibmModel` are
Prop hypotheses, never Lean axioms.

No `sorry`/`admit`/axiom/`native_decide`/`unsafe`/`@[implemented_by]`.
-/
import JackalIv.CertCheck
import JackalIv.Embed

namespace JackalIv.Cert

open JackalIv

/-! ### ℚ→ℝ reflection for the checker constants and exact helpers -/

@[simp] lemma cast_δ0Q : ((δ0Q : ℚ) : ℝ) = δ0 := by unfold δ0Q δ0; push_cast; ring
@[simp] lemma cast_δlibQ : ((δlibQ : ℚ) : ℝ) = δlib := by unfold δlibQ δlib; push_cast; ring

set_option exponentiation.threshold 1200 in
@[simp] lemma cast_σ0Q : ((σ0Q : ℚ) : ℝ) = σ0 := by unfold σ0Q σ0; push_cast; ring

/-- REFLECTION: the checker's rational mignitude casts to the model's `mig`. -/
@[simp] lemma cast_migQ (l u : ℚ) : ((migQ l u : ℚ) : ℝ) = mig (↑l) (↑u) := by
  unfold migQ mig
  split_ifs with h1 h2 h2
  · exact Rat.cast_zero
  · exact absurd ⟨by exact_mod_cast h1.1, by exact_mod_cast h1.2⟩ h2
  · exact absurd ⟨by exact_mod_cast h2.1, by exact_mod_cast h2.2⟩ h1
  · push_cast; rfl

/-- REFLECTION: the checker's rational magnitude casts to the model's `mag`. -/
@[simp] lemma cast_magQ (l u : ℚ) : ((magQ l u : ℚ) : ℝ) = mag (↑l) (↑u) := by
  unfold magQ mag; rw [Rat.cast_max, Rat.cast_abs, Rat.cast_abs]

/-- REFLECTION: the checker's rational `absLoQ` casts to the model's `absLo`. -/
@[simp] lemma cast_absLoQ (l u : ℚ) : ((absLoQ l u : ℚ) : ℝ) = absLo (↑l) (↑u) := by
  unfold absLoQ absLo
  by_cases h1 : (0:ℚ) ≤ l
  · have h1' : (0:ℝ) ≤ (↑l:ℝ) := by exact_mod_cast h1
    rw [if_pos h1, if_pos h1']
  · have h1' : ¬ (0:ℝ) ≤ (↑l:ℝ) := by exact_mod_cast h1
    rw [if_neg h1, if_neg h1']
    by_cases h2 : u ≤ (0:ℚ)
    · have h2' : (↑u:ℝ) ≤ 0 := by exact_mod_cast h2
      rw [if_pos h2, if_pos h2']; push_cast; ring
    · have h2' : ¬ (↑u:ℝ) ≤ 0 := by exact_mod_cast h2
      rw [if_neg h2, if_neg h2']; simp

/-- REFLECTION: the checker's rational `absHiQ` casts to the model's `absHi`. -/
@[simp] lemma cast_absHiQ (l u : ℚ) : ((absHiQ l u : ℚ) : ℝ) = absHi (↑l) (↑u) := by
  unfold absHiQ absHi
  by_cases h1 : (0:ℚ) ≤ l
  · have h1' : (0:ℝ) ≤ (↑l:ℝ) := by exact_mod_cast h1
    rw [if_pos h1, if_pos h1']
  · have h1' : ¬ (0:ℝ) ≤ (↑l:ℝ) := by exact_mod_cast h1
    rw [if_neg h1, if_neg h1']
    by_cases h2 : u ≤ (0:ℚ)
    · have h2' : (↑u:ℝ) ≤ 0 := by exact_mod_cast h2
      rw [if_pos h2, if_pos h2']; push_cast; ring
    · have h2' : ¬ (↑u:ℝ) ≤ 0 := by exact_mod_cast h2
      rw [if_neg h2, if_neg h2']; push_cast; rfl

/-- REFLECTION: the checker's rational truncation casts to the model's `truncR`. -/
@[simp] lemma cast_truncRQ (x : ℚ) : ((truncRQ x : ℚ) : ℝ) = truncR (↑x) := by
  unfold truncRQ truncR
  by_cases h : (0:ℚ) ≤ x
  · have h' : (0:ℝ) ≤ (↑x:ℝ) := by exact_mod_cast h
    rw [if_pos h, if_pos h']; push_cast; rw [Rat.floor_cast]
  · have h' : ¬ (0:ℝ) ≤ (↑x:ℝ) := by exact_mod_cast h
    rw [if_neg h, if_neg h']; push_cast; rw [Rat.ceil_cast]

/-- REFLECTION: the checker's rational round-away casts to the model's `roundAway`. -/
@[simp] lemma cast_roundAwayQ (x : ℚ) : ((roundAwayQ x : ℚ) : ℝ) = roundAway (↑x) := by
  unfold roundAwayQ roundAway
  by_cases h : (0:ℚ) ≤ x
  · have h' : (0:ℝ) ≤ (↑x:ℝ) := by exact_mod_cast h
    rw [if_pos h, if_pos h']
    rw [show ((↑x:ℝ) + 1/2) = ((↑(x + 1/2):ℝ)) by push_cast; ring, Rat.floor_cast]
    push_cast; ring
  · have h' : ¬ (0:ℝ) ≤ (↑x:ℝ) := by exact_mod_cast h
    rw [if_neg h, if_neg h']
    rw [show ((↑x:ℝ) - 1/2) = ((↑(x - 1/2):ℝ)) by push_cast; ring, Rat.ceil_cast]
    push_cast; ring

/-- REFLECTION: a rational integer floor casts to the model's real floor. -/
@[simp] lemma cast_floorQ (l : ℚ) : ((((⌊l⌋ : ℤ) : ℚ)) : ℝ) = ((⌊(↑l:ℝ)⌋ : ℤ) : ℝ) := by
  push_cast; rw [Rat.floor_cast]

/-- REFLECTION: a rational integer ceil casts to the model's real ceil. -/
@[simp] lemma cast_ceilQ (l : ℚ) : ((((⌈l⌉ : ℤ) : ℚ)) : ℝ) = ((⌈(↑l:ℝ)⌉ : ℤ) : ℝ) := by
  push_cast; rw [Rat.ceil_cast]

/-! ### Boolean → Prop bridges for the checker's decidable atoms -/

/-- A `true` rational equality decision is a rational equality. -/
lemma eqQ_eq {a b : ℚ} (h : eqQ a b = true) : a = b := of_decide_eq_true h

/-- A `true` `algApproxQ` at the basic-op bounds yields the model's `Approx δ0 σ0`. -/
lemma approx0 {fl r : ℚ} (h : algApproxQ fl r δ0Q σ0Q = true) :
    Approx δ0 σ0 (↑fl) (↑r) := by
  have := cast_algApprox h; rwa [cast_δ0Q, cast_σ0Q] at this

/-- A `true` `algApproxQ` at the libm bounds yields the model's `Approx δlib σ0`. -/
lemma approxLib {fl r : ℚ} (h : algApproxQ fl r δlibQ σ0Q = true) :
    Approx δlib σ0 (↑fl) (↑r) := by
  have := cast_algApprox h; rwa [cast_δlibQ, cast_σ0Q] at this

/-! ### Node-lookup bridges -/

/-- Recover the found node and its recorded interval from a `childOut` hit. -/
lemma childOut_findNode {nodes : List Node} {id : Nat} {l u : ℚ}
    (h : childOut nodes id = some (l, u)) :
    ∃ nd, findNode nodes id = some nd ∧ nd.out_lo = l ∧ nd.out_hi = u := by
  unfold childOut at h
  cases hfn : findNode nodes id with
  | none => rw [hfn] at h; simp at h
  | some nd =>
      rw [hfn] at h
      simp only [Option.map_some, Option.some.injEq, Prod.mk.injEq] at h
      exact ⟨nd, rfl, h.1, h.2⟩

/-- Membership from a `findNode` hit. -/
lemma mem_of_findNode {nodes : List Node} {id : Nat} {nd : Node}
    (h : findNode nodes id = some nd) : nd ∈ nodes := by
  unfold findNode at h; exact List.mem_of_find?_eq_some h

/-- Deconstruct a two-child `some/some` build match. -/
lemma bind2_eq_some {α β γ : Type*} {o1 : Option α} {o2 : Option β}
    {g : α → β → γ} {e : γ}
    (h : (match o1, o2 with | some a, some b => some (g a b) | _, _ => none) = some e) :
    ∃ a b, o1 = some a ∧ o2 = some b ∧ g a b = e := by
  cases o1 with
  | none => simp only [] at h; exact absurd h (by simp)
  | some a => cases o2 with
    | none => simp only [] at h; exact absurd h (by simp)
    | some b => exact ⟨a, b, rfl, rfl, by simpa only [Option.some.injEq] using h⟩

/-- The out-interval recorded at a found node, as a `childOut` value. -/
lemma childOut_of_findNode {nodes : List Node} {id : Nat} {nd : Node}
    (h : findNode nodes id = some nd) :
    childOut nodes id = some (nd.out_lo, nd.out_hi) := by
  unfold childOut; rw [h]; rfl

/-- A successful `buildExpr` implies the corresponding node exists. -/
lemma buildExpr_some_findNode {nodes : List Node} {fuel id : Nat} {e : Expr}
    (h : buildExpr fuel nodes id = some e) : ∃ nd, findNode nodes id = some nd := by
  cases fuel with
  | zero => simp [buildExpr] at h
  | succ f =>
    simp only [buildExpr] at h
    cases hfn : findNode nodes id with
    | none => simp [hfn] at h
    | some m => exact ⟨m, rfl⟩

/-- The checker's denominator-sign guard yields the zero-free disjunction (ℚ). -/
lemma denSignOk_or {s : Int} {l u : ℚ} (h : denSignOk s l u = true) : 0 < l ∨ u < 0 := by
  unfold denSignOk at h
  split at h
  · exact Or.inl (of_decide_eq_true h)
  · split at h
    · exact Or.inr (of_decide_eq_true h)
    · exact absurd h (by simp)

/-! ### The disclosed const-rounding TCB

`ConstTCB` is the const-node rounding fact MISSING from `CertTypes.libmNodeFact`
(see the file header): the correctly-rounded f64 of an irrational named constant
approximates the real constant.  It is a disclosed TCB hypothesis, exactly like
the eight transcendental facts in `LibmModel`; the one-line fix that folds it
INTO `libmNodeFact` makes the headline theorems hold verbatim. -/
def ConstTCB (nodes : List Node) : Prop :=
  ∀ nd ∈ nodes, nd.op = "const_rounded" →
    Approx δ0 σ0 (↑nd.fl_lo) (constValue nd.name)

/-! ### The core induction: `checkNode`-accepted nodes are `Runs` derivations

For every reconstructed subexpression `e` rooted at node `id` (with recorded
interval `nd.out`), a run exists producing exactly `(↑nd.out_lo, ↑nd.out_hi)`.
The induction is on `buildExpr`'s fuel; each child recurses at the predecessor
fuel, so the induction hypothesis applies verbatim.  Every one of the 38
`Runs` constructors is reconstructed; `const_rounded`'s missing rounding fact
is supplied by the disclosed `ConstTCB`. -/
set_option maxHeartbeats 3200000
theorem runs_of_check (hdr : Header) (nodes : List Node)
    (hall : ∀ nd ∈ nodes, checkNode hdr nodes nd = true)
    (hlibm : LibmModel hdr nodes) (hconst : ConstTCB nodes) :
    ∀ (fuel id : Nat) (nd : Node) (e : Expr),
      findNode nodes id = some nd → buildExpr fuel nodes id = some e →
      Runs e (↑hdr.input_lo, ↑hdr.input_hi) (↑nd.out_lo, ↑nd.out_hi) := by
  intro fuel
  induction fuel with
  | zero => intro id nd e _ hb; exact absurd hb (by simp [buildExpr])
  | succ fuel ih =>
    intro id nd e hfind hb
    have hmem : nd ∈ nodes := mem_of_findNode hfind
    have hcheck : checkNode hdr nodes nd = true := hall nd hmem
    have hlf : libmNodeFact nodes nd := hlibm nd hmem
    simp only [buildExpr, hfind] at hb
    unfold checkNode at hcheck
    split at hcheck
    all_goals (try (exact absurd hcheck (by decide)))
    · -- num_exact
      have hop : nd.op = "num_exact" := by assumption
      simp only [*] at hb
      simp only [Option.some.injEq] at hb
      subst hb
      simp only [Bool.and_eq_true] at hcheck
      obtain ⟨h1, h2⟩ := hcheck
      rw [show (↑nd.out_lo:ℝ) = ↑nd.value by rw [eqQ_eq h1],
          show (↑nd.out_hi:ℝ) = ↑nd.value by rw [eqQ_eq h2]]
      exact Runs.num_exact
    · -- num_rounded
      have hop : nd.op = "num_rounded" := by assumption
      simp only [*] at hb
      simp only [Option.some.injEq] at hb
      subst hb
      simp only [Bool.and_eq_true] at hcheck
      obtain ⟨⟨hlo, hhi⟩, ha⟩ := hcheck
      have hA : Approx δ0 σ0 (↑nd.fl_lo) (↑nd.value) := approx0 ha
      rw [show (↑nd.out_lo:ℝ) = padLo ↑nd.fl_lo by rw [eqQ_eq hlo]; simp,
          show (↑nd.out_hi:ℝ) = padHi ↑nd.fl_lo by rw [eqQ_eq hhi]; simp]
      exact Runs.num_rounded hA
    · -- const_rounded  (uses the disclosed ConstTCB)
      have hop : nd.op = "const_rounded" := by assumption
      simp only [*] at hb
      simp only [Option.some.injEq] at hb
      subst hb
      simp only [Bool.and_eq_true] at hcheck
      obtain ⟨⟨⟨_, hlo⟩, hhi⟩, _⟩ := hcheck
      have hA : Approx δ0 σ0 (↑nd.fl_lo) (constValue nd.name) := hconst nd hmem hop
      rw [show (↑nd.out_lo:ℝ) = padLo ↑nd.fl_lo by rw [eqQ_eq hlo]; simp,
          show (↑nd.out_hi:ℝ) = padHi ↑nd.fl_lo by rw [eqQ_eq hhi]; simp]
      exact Runs.const_rounded hA
    · -- var
      have hop : nd.op = "var" := by assumption
      simp only [*] at hb
      simp only [Option.some.injEq] at hb
      subst hb
      simp only [Bool.and_eq_true] at hcheck
      obtain ⟨⟨hname, hlo⟩, hhi⟩ := hcheck
      have hn : nd.name = "x" := by simpa using hname
      rw [hn, show (↑nd.out_lo:ℝ) = ↑hdr.input_lo by rw [eqQ_eq hlo],
          show (↑nd.out_hi:ℝ) = ↑hdr.input_hi by rw [eqQ_eq hhi]]
      exact Runs.var
    · -- neg
      have hop : nd.op = "neg" := by assumption
      simp only [*] at hb
      rw [Option.map_eq_some_iff] at hb
      obtain ⟨a, hba, rfl⟩ := hb
      obtain ⟨ndc0, hf0⟩ := buildExpr_some_findNode hba
      simp only [childOut_of_findNode hf0, Bool.and_eq_true] at hcheck
      obtain ⟨hlo, hhi⟩ := hcheck
      have hr := ih _ ndc0 a hf0 hba
      rw [show (↑nd.out_lo:ℝ) = -↑ndc0.out_hi by rw [eqQ_eq hlo]; push_cast; ring,
          show (↑nd.out_hi:ℝ) = -↑ndc0.out_lo by rw [eqQ_eq hhi]; push_cast; ring]
      exact Runs.neg hr
    · -- add
      have hop : nd.op = "add" := by assumption
      simp only [*] at hb
      split at hb
      all_goals (try (simp only [reduceCtorEq] at hb))
      rename_i a b hba hbb
      simp only [Option.some.injEq] at hb; subst hb
      obtain ⟨ndc0, hf0⟩ := buildExpr_some_findNode hba
      obtain ⟨ndc1, hf1⟩ := buildExpr_some_findNode hbb
      simp only [childOut_of_findNode hf0, childOut_of_findNode hf1, Bool.and_eq_true] at hcheck
      obtain ⟨⟨⟨hlo, hhi⟩, ha1⟩, ha2⟩ := hcheck
      have hr1 := ih _ ndc0 a hf0 hba
      have hr2 := ih _ ndc1 b hf1 hbb
      have hA1 : Approx δ0 σ0 (↑nd.fl_lo) ((↑ndc0.out_lo:ℝ) + ↑ndc1.out_lo) := by
        rw [← Rat.cast_add]; exact approx0 ha1
      have hA2 : Approx δ0 σ0 (↑nd.fl_hi) ((↑ndc0.out_hi:ℝ) + ↑ndc1.out_hi) := by
        rw [← Rat.cast_add]; exact approx0 ha2
      rw [show (↑nd.out_lo:ℝ) = padLo ↑nd.fl_lo by rw [eqQ_eq hlo]; simp,
          show (↑nd.out_hi:ℝ) = padHi ↑nd.fl_hi by rw [eqQ_eq hhi]; simp]
      exact Runs.add hr1 hr2 hA1 hA2
    · -- sub
      have hop : nd.op = "sub" := by assumption
      simp only [*] at hb
      split at hb
      all_goals (try (simp only [reduceCtorEq] at hb))
      rename_i a b hba hbb
      simp only [Option.some.injEq] at hb; subst hb
      obtain ⟨ndc0, hf0⟩ := buildExpr_some_findNode hba
      obtain ⟨ndc1, hf1⟩ := buildExpr_some_findNode hbb
      simp only [childOut_of_findNode hf0, childOut_of_findNode hf1, Bool.and_eq_true] at hcheck
      obtain ⟨⟨⟨hlo, hhi⟩, ha1⟩, ha2⟩ := hcheck
      have hr1 := ih _ ndc0 a hf0 hba
      have hr2 := ih _ ndc1 b hf1 hbb
      have hA1 : Approx δ0 σ0 (↑nd.fl_lo) ((↑ndc0.out_lo:ℝ) - ↑ndc1.out_hi) := by
        rw [← Rat.cast_sub]; exact approx0 ha1
      have hA2 : Approx δ0 σ0 (↑nd.fl_hi) ((↑ndc0.out_hi:ℝ) - ↑ndc1.out_lo) := by
        rw [← Rat.cast_sub]; exact approx0 ha2
      rw [show (↑nd.out_lo:ℝ) = padLo ↑nd.fl_lo by rw [eqQ_eq hlo]; simp,
          show (↑nd.out_hi:ℝ) = padHi ↑nd.fl_hi by rw [eqQ_eq hhi]; simp]
      exact Runs.sub hr1 hr2 hA1 hA2
    · -- mul
      have hop : nd.op = "mul" := by assumption
      simp only [*] at hb
      split at hb
      all_goals (try (simp only [reduceCtorEq] at hb))
      rename_i a b hba hbb
      simp only [Option.some.injEq] at hb; subst hb
      obtain ⟨ndc0, hf0⟩ := buildExpr_some_findNode hba
      obtain ⟨ndc1, hf1⟩ := buildExpr_some_findNode hbb
      simp only [childOut_of_findNode hf0, childOut_of_findNode hf1, Bool.and_eq_true] at hcheck
      obtain ⟨⟨⟨⟨⟨hlo, hhi⟩, h1⟩, h2⟩, h3⟩, h4⟩ := hcheck
      have hr1 := ih _ ndc0 a hf0 hba
      have hr2 := ih _ ndc1 b hf1 hbb
      have hA1 : Approx δ0 σ0 (↑nd.p1) ((↑ndc0.out_lo:ℝ) * ↑ndc1.out_lo) := by
        rw [← Rat.cast_mul]; exact approx0 h1
      have hA2 : Approx δ0 σ0 (↑nd.p2) ((↑ndc0.out_lo:ℝ) * ↑ndc1.out_hi) := by
        rw [← Rat.cast_mul]; exact approx0 h2
      have hA3 : Approx δ0 σ0 (↑nd.p3) ((↑ndc0.out_hi:ℝ) * ↑ndc1.out_lo) := by
        rw [← Rat.cast_mul]; exact approx0 h3
      have hA4 : Approx δ0 σ0 (↑nd.p4) ((↑ndc0.out_hi:ℝ) * ↑ndc1.out_hi) := by
        rw [← Rat.cast_mul]; exact approx0 h4
      rw [show (↑nd.out_lo:ℝ) = padLo (min (min ↑nd.p1 ↑nd.p2) (min ↑nd.p3 ↑nd.p4))
            by rw [eqQ_eq hlo]; exact cast_padLo_min4 nd.p1 nd.p2 nd.p3 nd.p4,
          show (↑nd.out_hi:ℝ) = padHi (max (max ↑nd.p1 ↑nd.p2) (max ↑nd.p3 ↑nd.p4))
            by rw [eqQ_eq hhi]; exact cast_padHi_max4 nd.p1 nd.p2 nd.p3 nd.p4]
      exact Runs.mul hr1 hr2 hA1 hA2 hA3 hA4
    · -- div
      have hop : nd.op = "div" := by assumption
      simp only [*] at hb
      split at hb
      all_goals (try (simp only [reduceCtorEq] at hb))
      rename_i a b hba hbb
      simp only [Option.some.injEq] at hb; subst hb
      obtain ⟨ndc0, hf0⟩ := buildExpr_some_findNode hba
      obtain ⟨ndc1, hf1⟩ := buildExpr_some_findNode hbb
      simp only [childOut_of_findNode hf0, childOut_of_findNode hf1, Bool.and_eq_true] at hcheck
      obtain ⟨⟨⟨⟨⟨⟨hds, hlo⟩, hhi⟩, h1⟩, h2⟩, h3⟩, h4⟩ := hcheck
      have hr1 := ih _ ndc0 a hf0 hba
      have hr2 := ih _ ndc1 b hf1 hbb
      have hden : (0:ℝ) < ↑ndc1.out_lo ∨ (↑ndc1.out_hi:ℝ) < 0 :=
        (denSignOk_or hds).imp (fun h => by exact_mod_cast h) (fun h => by exact_mod_cast h)
      have hA1 : Approx δ0 σ0 (↑nd.p1) ((↑ndc0.out_lo:ℝ) / ↑ndc1.out_lo) := by
        rw [← Rat.cast_div]; exact approx0 h1
      have hA2 : Approx δ0 σ0 (↑nd.p2) ((↑ndc0.out_lo:ℝ) / ↑ndc1.out_hi) := by
        rw [← Rat.cast_div]; exact approx0 h2
      have hA3 : Approx δ0 σ0 (↑nd.p3) ((↑ndc0.out_hi:ℝ) / ↑ndc1.out_lo) := by
        rw [← Rat.cast_div]; exact approx0 h3
      have hA4 : Approx δ0 σ0 (↑nd.p4) ((↑ndc0.out_hi:ℝ) / ↑ndc1.out_hi) := by
        rw [← Rat.cast_div]; exact approx0 h4
      rw [show (↑nd.out_lo:ℝ) = padLo (min (min ↑nd.p1 ↑nd.p2) (min ↑nd.p3 ↑nd.p4))
            by rw [eqQ_eq hlo]; exact cast_padLo_min4 nd.p1 nd.p2 nd.p3 nd.p4,
          show (↑nd.out_hi:ℝ) = padHi (max (max ↑nd.p1 ↑nd.p2) (max ↑nd.p3 ↑nd.p4))
            by rw [eqQ_eq hhi]; exact cast_padHi_max4 nd.p1 nd.p2 nd.p3 nd.p4]
      exact Runs.div hr1 hr2 hden hA1 hA2 hA3 hA4
    · -- powZero
      have hop : nd.op = "powZero" := by assumption
      simp only [*] at hb
      rw [Option.map_eq_some_iff] at hb
      obtain ⟨a, hba, rfl⟩ := hb
      obtain ⟨ndc0, hf0⟩ := buildExpr_some_findNode hba
      simp only [childOut_of_findNode hf0, Bool.and_eq_true] at hcheck
      obtain ⟨⟨hn0, hlo⟩, hhi⟩ := hcheck
      have hne : nd.n = 0 := by simpa using hn0
      have hr := ih _ ndc0 a hf0 hba
      rw [hne, show (↑nd.out_lo:ℝ) = 1 by rw [eqQ_eq hlo]; norm_num,
          show (↑nd.out_hi:ℝ) = 1 by rw [eqQ_eq hhi]; norm_num]
      exact Runs.powZero hr
    · -- powEvenPos
      have hop : nd.op = "powEvenPos" := by assumption
      simp only [*] at hb
      rw [Option.map_eq_some_iff] at hb
      obtain ⟨a, hba, rfl⟩ := hb
      obtain ⟨ndc0, hf0⟩ := buildExpr_some_findNode hba
      simp only [childOut_of_findNode hf0, Bool.and_eq_true] at hcheck
      obtain ⟨⟨⟨⟨⟨hmod, hdec⟩, hlo⟩, hhi⟩, h5⟩, h6⟩ := hcheck
      have hr := ih _ ndc0 a hf0 hba
      have hEven : Even nd.n := Nat.even_iff.mpr (by simpa using hmod)
      have hn2 : 2 ≤ nd.n := of_decide_eq_true hdec
      have hA1 : Approx δlib σ0 (↑nd.fl_lo) (mig (↑ndc0.out_lo) (↑ndc0.out_hi) ^ nd.n) := by
        have := approxLib h5; rwa [Rat.cast_pow, cast_migQ] at this
      have hA2 : Approx δlib σ0 (↑nd.fl_hi) (mag (↑ndc0.out_lo) (↑ndc0.out_hi) ^ nd.n) := by
        have := approxLib h6; rwa [Rat.cast_pow, cast_magQ] at this
      rw [show (↑nd.out_lo:ℝ) = padLo ↑nd.fl_lo by rw [eqQ_eq hlo]; simp,
          show (↑nd.out_hi:ℝ) = padHi ↑nd.fl_hi by rw [eqQ_eq hhi]; simp]
      exact Runs.powEvenPos nd.n hEven hn2 hr hA1 hA2
    · -- powOddPos
      have hop : nd.op = "powOddPos" := by assumption
      simp only [*] at hb
      rw [Option.map_eq_some_iff] at hb
      obtain ⟨a, hba, rfl⟩ := hb
      obtain ⟨ndc0, hf0⟩ := buildExpr_some_findNode hba
      simp only [childOut_of_findNode hf0, Bool.and_eq_true] at hcheck
      obtain ⟨⟨⟨⟨hmod, hlo⟩, hhi⟩, h4⟩, h5⟩ := hcheck
      have hr := ih _ ndc0 a hf0 hba
      have hOdd : Odd nd.n := Nat.odd_iff.mpr (by simpa using hmod)
      have hA1 : Approx δlib σ0 (↑nd.fl_lo) ((↑ndc0.out_lo:ℝ) ^ nd.n) := by
        have := approxLib h4; rwa [Rat.cast_pow] at this
      have hA2 : Approx δlib σ0 (↑nd.fl_hi) ((↑ndc0.out_hi:ℝ) ^ nd.n) := by
        have := approxLib h5; rwa [Rat.cast_pow] at this
      rw [show (↑nd.out_lo:ℝ) = padLo ↑nd.fl_lo by rw [eqQ_eq hlo]; simp,
          show (↑nd.out_hi:ℝ) = padHi ↑nd.fl_hi by rw [eqQ_eq hhi]; simp]
      exact Runs.powOddPos nd.n hOdd hr hA1 hA2
    · -- powNegEven
      have hop : nd.op = "powNegEven" := by assumption
      simp only [*] at hb
      rw [Option.map_eq_some_iff] at hb
      obtain ⟨a, hba, rfl⟩ := hb
      obtain ⟨ndc0, hf0⟩ := buildExpr_some_findNode hba
      simp only [childOut_of_findNode hf0, Bool.and_eq_true] at hcheck
      obtain ⟨⟨⟨⟨⟨⟨⟨⟨⟨⟨hmod, hdec⟩, hc3⟩, hc4⟩, hds⟩, hlo⟩, hhi⟩, hp1⟩, hp2⟩, hp3⟩, hp4⟩ := hcheck
      have hr := ih _ ndc0 a hf0 hba
      have hEven : Even nd.n := Nat.even_iff.mpr (by simpa using hmod)
      have hn2 : 2 ≤ nd.n := of_decide_eq_true hdec
      have hclo : Approx δlib σ0 (↑nd.fl_lo) (mig (↑ndc0.out_lo) (↑ndc0.out_hi) ^ nd.n) := by
        have := approxLib hc3; rwa [Rat.cast_pow, cast_migQ] at this
      have hchi : Approx δlib σ0 (↑nd.fl_hi) (mag (↑ndc0.out_lo) (↑ndc0.out_hi) ^ nd.n) := by
        have := approxLib hc4; rwa [Rat.cast_pow, cast_magQ] at this
      have hden : (0:ℝ) < padLo ↑nd.fl_lo ∨ padHi ↑nd.fl_hi < 0 := by
        rcases denSignOk_or hds with h | h
        · left; rw [← cast_padLo]; exact_mod_cast h
        · right; rw [← cast_padHi]; exact_mod_cast h
      have hq1 : Approx δ0 σ0 (↑nd.p1) (1 / padLo ↑nd.fl_lo) := by
        have := approx0 hp1; rwa [Rat.cast_div, Rat.cast_one, cast_padLo] at this
      have hq2 : Approx δ0 σ0 (↑nd.p2) (1 / padHi ↑nd.fl_hi) := by
        have := approx0 hp2; rwa [Rat.cast_div, Rat.cast_one, cast_padHi] at this
      have hq3 : Approx δ0 σ0 (↑nd.p3) (1 / padLo ↑nd.fl_lo) := by
        have := approx0 hp3; rwa [Rat.cast_div, Rat.cast_one, cast_padLo] at this
      have hq4 : Approx δ0 σ0 (↑nd.p4) (1 / padHi ↑nd.fl_hi) := by
        have := approx0 hp4; rwa [Rat.cast_div, Rat.cast_one, cast_padHi] at this
      rw [show (↑nd.out_lo:ℝ) = padLo (min (min ↑nd.p1 ↑nd.p2) (min ↑nd.p3 ↑nd.p4))
            by rw [eqQ_eq hlo]; exact cast_padLo_min4 nd.p1 nd.p2 nd.p3 nd.p4,
          show (↑nd.out_hi:ℝ) = padHi (max (max ↑nd.p1 ↑nd.p2) (max ↑nd.p3 ↑nd.p4))
            by rw [eqQ_eq hhi]; exact cast_padHi_max4 nd.p1 nd.p2 nd.p3 nd.p4]
      exact Runs.powNegEven nd.n hEven hn2 hr hclo hchi hden hq1 hq2 hq3 hq4
    · -- powNegOdd
      have hop : nd.op = "powNegOdd" := by assumption
      simp only [*] at hb
      rw [Option.map_eq_some_iff] at hb
      obtain ⟨a, hba, rfl⟩ := hb
      obtain ⟨ndc0, hf0⟩ := buildExpr_some_findNode hba
      simp only [childOut_of_findNode hf0, Bool.and_eq_true] at hcheck
      obtain ⟨⟨⟨⟨⟨⟨⟨⟨⟨hmod, hc2⟩, hc3⟩, hds⟩, hlo⟩, hhi⟩, hp1⟩, hp2⟩, hp3⟩, hp4⟩ := hcheck
      have hr := ih _ ndc0 a hf0 hba
      have hOdd : Odd nd.n := Nat.odd_iff.mpr (by simpa using hmod)
      have hclo : Approx δlib σ0 (↑nd.fl_lo) ((↑ndc0.out_lo:ℝ) ^ nd.n) := by
        have := approxLib hc2; rwa [Rat.cast_pow] at this
      have hchi : Approx δlib σ0 (↑nd.fl_hi) ((↑ndc0.out_hi:ℝ) ^ nd.n) := by
        have := approxLib hc3; rwa [Rat.cast_pow] at this
      have hden : (0:ℝ) < padLo ↑nd.fl_lo ∨ padHi ↑nd.fl_hi < 0 := by
        rcases denSignOk_or hds with h | h
        · left; rw [← cast_padLo]; exact_mod_cast h
        · right; rw [← cast_padHi]; exact_mod_cast h
      have hq1 : Approx δ0 σ0 (↑nd.p1) (1 / padLo ↑nd.fl_lo) := by
        have := approx0 hp1; rwa [Rat.cast_div, Rat.cast_one, cast_padLo] at this
      have hq2 : Approx δ0 σ0 (↑nd.p2) (1 / padHi ↑nd.fl_hi) := by
        have := approx0 hp2; rwa [Rat.cast_div, Rat.cast_one, cast_padHi] at this
      have hq3 : Approx δ0 σ0 (↑nd.p3) (1 / padLo ↑nd.fl_lo) := by
        have := approx0 hp3; rwa [Rat.cast_div, Rat.cast_one, cast_padLo] at this
      have hq4 : Approx δ0 σ0 (↑nd.p4) (1 / padHi ↑nd.fl_hi) := by
        have := approx0 hp4; rwa [Rat.cast_div, Rat.cast_one, cast_padHi] at this
      rw [show (↑nd.out_lo:ℝ) = padLo (min (min ↑nd.p1 ↑nd.p2) (min ↑nd.p3 ↑nd.p4))
            by rw [eqQ_eq hlo]; exact cast_padLo_min4 nd.p1 nd.p2 nd.p3 nd.p4,
          show (↑nd.out_hi:ℝ) = padHi (max (max ↑nd.p1 ↑nd.p2) (max ↑nd.p3 ↑nd.p4))
            by rw [eqQ_eq hhi]; exact cast_padHi_max4 nd.p1 nd.p2 nd.p3 nd.p4]
      exact Runs.powNegOdd nd.n hOdd hr hclo hchi hden hq1 hq2 hq3 hq4
    · -- sin
      have hop : nd.op = "sin" := by assumption
      simp only [*] at hb
      simp at hb
      obtain ⟨_, a, hba, rfl⟩ := hb
      obtain ⟨ndc0, hf0⟩ := buildExpr_some_findNode hba
      simp only [childOut_of_findNode hf0, Bool.and_eq_true] at hcheck
      obtain ⟨hlo, hhi⟩ := hcheck
      have hr := ih _ ndc0 a hf0 hba
      rw [show (↑nd.out_lo:ℝ) = -1 by rw [eqQ_eq hlo]; norm_num,
          show (↑nd.out_hi:ℝ) = 1 by rw [eqQ_eq hhi]; norm_num]
      exact Runs.sin hr
    · -- cos
      have hop : nd.op = "cos" := by assumption
      simp only [*] at hb
      simp at hb
      obtain ⟨_, a, hba, rfl⟩ := hb
      obtain ⟨ndc0, hf0⟩ := buildExpr_some_findNode hba
      simp only [childOut_of_findNode hf0, Bool.and_eq_true] at hcheck
      obtain ⟨hlo, hhi⟩ := hcheck
      have hr := ih _ ndc0 a hf0 hba
      rw [show (↑nd.out_lo:ℝ) = -1 by rw [eqQ_eq hlo]; norm_num,
          show (↑nd.out_hi:ℝ) = 1 by rw [eqQ_eq hhi]; norm_num]
      exact Runs.cos hr
    · -- abs
      have hop : nd.op = "abs" := by assumption
      simp only [*] at hb
      simp at hb
      obtain ⟨_, a, hba, rfl⟩ := hb
      obtain ⟨ndc0, hf0⟩ := buildExpr_some_findNode hba
      simp only [childOut_of_findNode hf0, Bool.and_eq_true] at hcheck
      obtain ⟨hlo, hhi⟩ := hcheck
      have hr := ih _ ndc0 a hf0 hba
      rw [show (↑nd.out_lo:ℝ) = absLo ↑ndc0.out_lo ↑ndc0.out_hi by rw [eqQ_eq hlo]; simp,
          show (↑nd.out_hi:ℝ) = absHi ↑ndc0.out_lo ↑ndc0.out_hi by rw [eqQ_eq hhi]; simp]
      exact Runs.abs hr
    · -- floor
      have hop : nd.op = "floor" := by assumption
      simp only [*] at hb
      simp at hb
      obtain ⟨_, a, hba, rfl⟩ := hb
      obtain ⟨ndc0, hf0⟩ := buildExpr_some_findNode hba
      simp only [childOut_of_findNode hf0, Bool.and_eq_true] at hcheck
      obtain ⟨hlo, hhi⟩ := hcheck
      have hr := ih _ ndc0 a hf0 hba
      rw [show (↑nd.out_lo:ℝ) = ((⌊(↑ndc0.out_lo:ℝ)⌋ : ℤ) : ℝ) by rw [eqQ_eq hlo]; simp,
          show (↑nd.out_hi:ℝ) = ((⌊(↑ndc0.out_hi:ℝ)⌋ : ℤ) : ℝ) by rw [eqQ_eq hhi]; simp]
      exact Runs.floor hr
    · -- ceil
      have hop : nd.op = "ceil" := by assumption
      simp only [*] at hb
      simp at hb
      obtain ⟨_, a, hba, rfl⟩ := hb
      obtain ⟨ndc0, hf0⟩ := buildExpr_some_findNode hba
      simp only [childOut_of_findNode hf0, Bool.and_eq_true] at hcheck
      obtain ⟨hlo, hhi⟩ := hcheck
      have hr := ih _ ndc0 a hf0 hba
      rw [show (↑nd.out_lo:ℝ) = ((⌈(↑ndc0.out_lo:ℝ)⌉ : ℤ) : ℝ) by rw [eqQ_eq hlo]; simp,
          show (↑nd.out_hi:ℝ) = ((⌈(↑ndc0.out_hi:ℝ)⌉ : ℤ) : ℝ) by rw [eqQ_eq hhi]; simp]
      exact Runs.ceil hr
    · -- round
      have hop : nd.op = "round" := by assumption
      simp only [*] at hb
      simp at hb
      obtain ⟨_, a, hba, rfl⟩ := hb
      obtain ⟨ndc0, hf0⟩ := buildExpr_some_findNode hba
      simp only [childOut_of_findNode hf0, Bool.and_eq_true] at hcheck
      obtain ⟨hlo, hhi⟩ := hcheck
      have hr := ih _ ndc0 a hf0 hba
      rw [show (↑nd.out_lo:ℝ) = roundAway ↑ndc0.out_lo by rw [eqQ_eq hlo]; simp,
          show (↑nd.out_hi:ℝ) = roundAway ↑ndc0.out_hi by rw [eqQ_eq hhi]; simp]
      exact Runs.round hr
    · -- trunc
      have hop : nd.op = "trunc" := by assumption
      simp only [*] at hb
      simp at hb
      obtain ⟨_, a, hba, rfl⟩ := hb
      obtain ⟨ndc0, hf0⟩ := buildExpr_some_findNode hba
      simp only [childOut_of_findNode hf0, Bool.and_eq_true] at hcheck
      obtain ⟨hlo, hhi⟩ := hcheck
      have hr := ih _ ndc0 a hf0 hba
      rw [show (↑nd.out_lo:ℝ) = truncR ↑ndc0.out_lo by rw [eqQ_eq hlo]; simp,
          show (↑nd.out_hi:ℝ) = truncR ↑ndc0.out_hi by rw [eqQ_eq hhi]; simp]
      exact Runs.trunc hr
    · -- min
      have hop : nd.op = "min" := by assumption
      simp only [*] at hb
      simp at hb
      obtain ⟨_, _, hb⟩ := hb
      split at hb
      all_goals (try (simp only [reduceCtorEq] at hb))
      rename_i a b hba hbb
      simp only [Option.some.injEq] at hb; subst hb
      obtain ⟨ndc0, hf0⟩ := buildExpr_some_findNode hba
      obtain ⟨ndc1, hf1⟩ := buildExpr_some_findNode hbb
      simp only [childOut_of_findNode hf0, childOut_of_findNode hf1, Bool.and_eq_true] at hcheck
      obtain ⟨hlo, hhi⟩ := hcheck
      have hr1 := ih _ ndc0 a hf0 hba
      have hr2 := ih _ ndc1 b hf1 hbb
      rw [show (↑nd.out_lo:ℝ) = min ↑ndc0.out_lo ↑ndc1.out_lo by rw [eqQ_eq hlo]; simp,
          show (↑nd.out_hi:ℝ) = min ↑ndc0.out_hi ↑ndc1.out_hi by rw [eqQ_eq hhi]; simp]
      exact Runs.min hr1 hr2
    · -- max
      have hop : nd.op = "max" := by assumption
      simp only [*] at hb
      simp at hb
      obtain ⟨_, _, hb⟩ := hb
      split at hb
      all_goals (try (simp only [reduceCtorEq] at hb))
      rename_i a b hba hbb
      simp only [Option.some.injEq] at hb; subst hb
      obtain ⟨ndc0, hf0⟩ := buildExpr_some_findNode hba
      obtain ⟨ndc1, hf1⟩ := buildExpr_some_findNode hbb
      simp only [childOut_of_findNode hf0, childOut_of_findNode hf1, Bool.and_eq_true] at hcheck
      obtain ⟨hlo, hhi⟩ := hcheck
      have hr1 := ih _ ndc0 a hf0 hba
      have hr2 := ih _ ndc1 b hf1 hbb
      rw [show (↑nd.out_lo:ℝ) = max ↑ndc0.out_lo ↑ndc1.out_lo by rw [eqQ_eq hlo]; simp,
          show (↑nd.out_hi:ℝ) = max ↑ndc0.out_hi ↑ndc1.out_hi by rw [eqQ_eq hhi]; simp]
      exact Runs.max hr1 hr2
    · -- sqrt
      have hop : nd.op = "sqrt" := by assumption
      simp only [*] at hb
      simp at hb
      obtain ⟨_, a, hba, rfl⟩ := hb
      obtain ⟨ndc0, hf0⟩ := buildExpr_some_findNode hba
      simp only [libmNodeFact, *] at hlf
      simp [childOut_of_findNode hf0] at hlf
      obtain ⟨hAlo, hAhi⟩ := hlf
      simp only [childOut_of_findNode hf0, Bool.and_eq_true] at hcheck
      obtain ⟨⟨hg, hlo⟩, hhi⟩ := hcheck
      have hr := ih _ ndc0 a hf0 hba
      have hguard : (0:ℝ) ≤ ↑ndc0.out_lo := by exact_mod_cast (of_decide_eq_true hg)
      rw [show (↑nd.out_lo:ℝ) = max (padLo ↑nd.fl_lo) 0 by rw [eqQ_eq hlo]; simp,
          show (↑nd.out_hi:ℝ) = padHi ↑nd.fl_hi by rw [eqQ_eq hhi]; simp]
      exact Runs.sqrt hr hguard hAlo hAhi
    · -- exp
      have hop : nd.op = "exp" := by assumption
      simp only [*] at hb
      simp at hb
      obtain ⟨_, a, hba, rfl⟩ := hb
      obtain ⟨ndc0, hf0⟩ := buildExpr_some_findNode hba
      simp only [libmNodeFact, *] at hlf
      simp [childOut_of_findNode hf0] at hlf
      obtain ⟨hAlo, hAhi⟩ := hlf
      simp only [childOut_of_findNode hf0, Bool.and_eq_true] at hcheck
      obtain ⟨hlo, hhi⟩ := hcheck
      have hr := ih _ ndc0 a hf0 hba
      rw [show (↑nd.out_lo:ℝ) = padLo ↑nd.fl_lo by rw [eqQ_eq hlo]; simp,
          show (↑nd.out_hi:ℝ) = padHi ↑nd.fl_hi by rw [eqQ_eq hhi]; simp]
      exact Runs.exp hr hAlo hAhi
    · -- ln
      have hop : nd.op = "ln" := by assumption
      simp only [*] at hb
      simp at hb
      obtain ⟨_, a, hba, rfl⟩ := hb
      obtain ⟨ndc0, hf0⟩ := buildExpr_some_findNode hba
      simp only [libmNodeFact, *] at hlf
      simp [childOut_of_findNode hf0] at hlf
      obtain ⟨hAlo, hAhi⟩ := hlf
      simp only [childOut_of_findNode hf0, Bool.and_eq_true] at hcheck
      obtain ⟨⟨hg, hlo⟩, hhi⟩ := hcheck
      have hr := ih _ ndc0 a hf0 hba
      have hguard : (0:ℝ) < ↑ndc0.out_lo := by exact_mod_cast (of_decide_eq_true hg)
      rw [show (↑nd.out_lo:ℝ) = padLo ↑nd.fl_lo by rw [eqQ_eq hlo]; simp,
          show (↑nd.out_hi:ℝ) = padHi ↑nd.fl_hi by rw [eqQ_eq hhi]; simp]
      exact Runs.log hr hguard hAlo hAhi
    · -- atan
      have hop : nd.op = "atan" := by assumption
      simp only [*] at hb
      simp at hb
      obtain ⟨_, a, hba, rfl⟩ := hb
      obtain ⟨ndc0, hf0⟩ := buildExpr_some_findNode hba
      simp only [libmNodeFact, *] at hlf
      simp [childOut_of_findNode hf0] at hlf
      obtain ⟨hAlo, hAhi⟩ := hlf
      simp only [childOut_of_findNode hf0, Bool.and_eq_true] at hcheck
      obtain ⟨hlo, hhi⟩ := hcheck
      have hr := ih _ ndc0 a hf0 hba
      rw [show (↑nd.out_lo:ℝ) = padLo ↑nd.fl_lo by rw [eqQ_eq hlo]; simp,
          show (↑nd.out_hi:ℝ) = padHi ↑nd.fl_hi by rw [eqQ_eq hhi]; simp]
      exact Runs.atan hr hAlo hAhi
    · -- asin
      have hop : nd.op = "asin" := by assumption
      simp only [*] at hb
      simp at hb
      obtain ⟨_, a, hba, rfl⟩ := hb
      obtain ⟨ndc0, hf0⟩ := buildExpr_some_findNode hba
      simp only [libmNodeFact, *] at hlf
      simp [childOut_of_findNode hf0] at hlf
      obtain ⟨hAlo, hAhi⟩ := hlf
      simp only [childOut_of_findNode hf0, Bool.and_eq_true] at hcheck
      obtain ⟨⟨hg, hlo⟩, hhi⟩ := hcheck
      have hr := ih _ ndc0 a hf0 hba
      have hdom : (-1:ℝ) ≤ ↑ndc0.out_lo ∧ (↑ndc0.out_hi:ℝ) ≤ 1 := by
        obtain ⟨h1, h2⟩ := of_decide_eq_true hg
        exact ⟨by exact_mod_cast h1, by exact_mod_cast h2⟩
      rw [show (↑nd.out_lo:ℝ) = padLo ↑nd.fl_lo by rw [eqQ_eq hlo]; simp,
          show (↑nd.out_hi:ℝ) = padHi ↑nd.fl_hi by rw [eqQ_eq hhi]; simp]
      exact Runs.asin hr hdom hAlo hAhi
    · -- acos
      have hop : nd.op = "acos" := by assumption
      simp only [*] at hb
      simp at hb
      obtain ⟨_, a, hba, rfl⟩ := hb
      obtain ⟨ndc0, hf0⟩ := buildExpr_some_findNode hba
      simp only [libmNodeFact, *] at hlf
      simp [childOut_of_findNode hf0] at hlf
      obtain ⟨hAlo, hAhi⟩ := hlf
      simp only [childOut_of_findNode hf0, Bool.and_eq_true] at hcheck
      obtain ⟨⟨hg, hlo⟩, hhi⟩ := hcheck
      have hr := ih _ ndc0 a hf0 hba
      have hdom : (-1:ℝ) ≤ ↑ndc0.out_lo ∧ (↑ndc0.out_hi:ℝ) ≤ 1 := by
        obtain ⟨h1, h2⟩ := of_decide_eq_true hg
        exact ⟨by exact_mod_cast h1, by exact_mod_cast h2⟩
      rw [show (↑nd.out_lo:ℝ) = padLo ↑nd.fl_hi by rw [eqQ_eq hlo]; simp,
          show (↑nd.out_hi:ℝ) = padHi ↑nd.fl_lo by rw [eqQ_eq hhi]; simp]
      exact Runs.acos hr hdom hAlo hAhi
    · -- hypot
      have hop : nd.op = "hypot" := by assumption
      simp only [*] at hb
      simp at hb
      obtain ⟨_, _, hb⟩ := hb
      split at hb
      all_goals (try (simp only [reduceCtorEq] at hb))
      rename_i a b hba hbb
      simp only [Option.some.injEq] at hb; subst hb
      obtain ⟨ndc0, hf0⟩ := buildExpr_some_findNode hba
      obtain ⟨ndc1, hf1⟩ := buildExpr_some_findNode hbb
      simp only [libmNodeFact, *] at hlf
      simp [childOut_of_findNode hf0, childOut_of_findNode hf1] at hlf
      obtain ⟨hAlo, hAhi⟩ := hlf
      simp only [childOut_of_findNode hf0, childOut_of_findNode hf1, Bool.and_eq_true] at hcheck
      obtain ⟨hlo, hhi⟩ := hcheck
      have hr1 := ih _ ndc0 a hf0 hba
      have hr2 := ih _ ndc1 b hf1 hbb
      rw [show (↑nd.out_lo:ℝ) = padLo ↑nd.fl_lo by rw [eqQ_eq hlo]; simp,
          show (↑nd.out_hi:ℝ) = padHi ↑nd.fl_hi by rw [eqQ_eq hhi]; simp]
      exact Runs.hypot hr1 hr2 hAlo hAhi
    · -- powGeneral
      have hop : nd.op = "powGeneral" := by assumption
      simp only [*] at hb
      split at hb
      all_goals (try (simp only [reduceCtorEq] at hb))
      rename_i a b hba hbb
      simp only [Option.some.injEq] at hb; subst hb
      obtain ⟨ndc0, hf0⟩ := buildExpr_some_findNode hba
      obtain ⟨ndc1, hf1⟩ := buildExpr_some_findNode hbb
      simp only [libmNodeFact, *] at hlf
      simp [childOut_of_findNode hf0, childOut_of_findNode hf1] at hlf
      obtain ⟨hln, hmul, hexpst⟩ := hlf
      simp only [childOut_of_findNode hf0, childOut_of_findNode hf1, Bool.and_eq_true] at hcheck
      obtain ⟨⟨hg, hlo⟩, hhi⟩ := hcheck
      have hxl : (0:ℝ) < ↑ndc0.out_lo := by exact_mod_cast (of_decide_eq_true hg)
      have hr1 := ih _ ndc0 a hf0 hba
      have hr2 := ih _ ndc1 b hf1 hbb
      rw [show (↑nd.out_lo:ℝ) = ↑nd.El by rw [eqQ_eq hlo],
          show (↑nd.out_hi:ℝ) = ↑nd.Eu by rw [eqQ_eq hhi]]
      exact Runs.powGeneral hr1 hr2 hxl hln hmul hexpst
    · -- sqrt_rat  (pure ℚ; no libm TCB, §487-fragment extension).
      have hop : nd.op = "sqrt_rat" := by assumption
      simp only [*] at hb
      rw [Option.map_eq_some_iff] at hb
      obtain ⟨a, hba, rfl⟩ := hb
      obtain ⟨ndc0, hf0⟩ := buildExpr_some_findNode hba
      simp only [childOut_of_findNode hf0, Bool.and_eq_true] at hcheck
      obtain ⟨⟨⟨hlnn, hunn⟩, hlb⟩, hub⟩ := hcheck
      have hr := ih _ ndc0 a hf0 hba
      have hlnnQ : (0 : ℚ) ≤ nd.out_lo := of_decide_eq_true hlnn
      have hunnQ : (0 : ℚ) ≤ nd.out_hi := of_decide_eq_true hunn
      have hlbQ : nd.out_lo ^ 2 ≤ ndc0.out_lo := of_decide_eq_true hlb
      have hubQ : ndc0.out_hi ≤ nd.out_hi ^ 2 := of_decide_eq_true hub
      have hlbR : ((nd.out_lo : ℚ) : ℝ) ^ 2 ≤ ((ndc0.out_lo : ℚ) : ℝ) := by
        exact_mod_cast hlbQ
      have hubR : ((ndc0.out_hi : ℚ) : ℝ) ≤ ((nd.out_hi : ℚ) : ℝ) ^ 2 := by
        exact_mod_cast hubQ
      exact Runs.sqrtRat hr hlnnQ hunnQ hlbR hubR
    · -- exp_rat  (pure ℚ; no libm TCB; GENERAL-SIGN §490 v1.5.0).
      have hop : nd.op = "exp_rat" := by assumption
      simp only [*] at hb
      rw [Option.map_eq_some_iff] at hb
      obtain ⟨a, hba, rfl⟩ := hb
      obtain ⟨ndc0, hf0⟩ := buildExpr_some_findNode hba
      simp only [childOut_of_findNode hf0, Bool.and_eq_true] at hcheck
      obtain ⟨⟨⟨⟨_hMono, hdegLo⟩, hdegHi⟩, hLB⟩, hUB⟩ := hcheck
      have hr := ih _ ndc0 a hf0 hba
      have hLBQ : nd.out_lo ≤ Gaussian.expLBQ ndc0.out_lo nd.n :=
        of_decide_eq_true hLB
      have hUBQ : Gaussian.expUBQ ndc0.out_hi nd.n ≤ nd.out_hi :=
        of_decide_eq_true hUB
      have hbLo := Gaussian.exp_between_general ndc0.out_lo nd.n hdegLo
      have hbHi := Gaussian.exp_between_general ndc0.out_hi nd.n hdegHi
      have hloR : ((nd.out_lo : ℚ) : ℝ) ≤ Real.exp ((ndc0.out_lo : ℚ) : ℝ) :=
        le_trans (by exact_mod_cast hLBQ) hbLo.1
      have hhiR : Real.exp ((ndc0.out_hi : ℚ) : ℝ) ≤ ((nd.out_hi : ℚ) : ℝ) :=
        le_trans hbHi.2 (by exact_mod_cast hUBQ)
      exact Runs.expRat hr hloR hhiR
    · -- ln_rat  (pure ℚ; no libm TCB; §490 v1.5.0).
      have hop : nd.op = "ln_rat" := by assumption
      simp only [*] at hb
      rw [Option.map_eq_some_iff] at hb
      obtain ⟨a, hba, rfl⟩ := hb
      obtain ⟨ndc0, hf0⟩ := buildExpr_some_findNode hba
      simp only [childOut_of_findNode hf0, Bool.and_eq_true] at hcheck
      obtain ⟨⟨⟨⟨⟨hPos, _hMono⟩, hdegLo⟩, hdegHi⟩, hUBc⟩, hLBc⟩ := hcheck
      have hr := ih _ ndc0 a hf0 hba
      have hPosQ : (0 : ℚ) < ndc0.out_lo := of_decide_eq_true hPos
      have hUBQ : Gaussian.expUBQ nd.out_lo nd.n ≤ ndc0.out_lo :=
        of_decide_eq_true hUBc
      have hLBQ : ndc0.out_hi ≤ Gaussian.expLBQ nd.out_hi nd.n :=
        of_decide_eq_true hLBc
      have hbLo := Gaussian.exp_between_general nd.out_lo nd.n hdegLo
      have hbHi := Gaussian.exp_between_general nd.out_hi nd.n hdegHi
      have hguard : (0 : ℝ) < ((ndc0.out_lo : ℚ) : ℝ) := by exact_mod_cast hPosQ
      have hlo : Real.exp ((nd.out_lo : ℚ) : ℝ) ≤ ((ndc0.out_lo : ℚ) : ℝ) :=
        le_trans hbLo.2 (by exact_mod_cast hUBQ)
      have hhi : ((ndc0.out_hi : ℚ) : ℝ) ≤ Real.exp ((nd.out_hi : ℚ) : ℝ) :=
        le_trans (by exact_mod_cast hLBQ) hbHi.1
      exact Runs.logRat hr hguard hlo hhi
    · -- sin_rat  (pure ℚ; no libm TCB; §490 v1.5.0).
      have hop : nd.op = "sin_rat" := by assumption
      simp only [*] at hb
      rw [Option.map_eq_some_iff] at hb
      obtain ⟨a, hba, rfl⟩ := hb
      obtain ⟨ndc0, hf0⟩ := buildExpr_some_findNode hba
      simp only [childOut_of_findNode hf0, Bool.and_eq_true] at hcheck
      obtain ⟨⟨⟨_hMono, hm⟩, hlo⟩, hhi⟩ := hcheck
      have hr := ih _ ndc0 a hf0 hba
      have hmQ : |(ndc0.out_lo + ndc0.out_hi) / 2| ≤ 1 := of_decide_eq_true hm
      have hloQ : nd.out_lo ≤
          Transcend.sinLoQ ((ndc0.out_lo + ndc0.out_hi) / 2) -
            (ndc0.out_hi - ndc0.out_lo) / 2 := of_decide_eq_true hlo
      have hhiQ : Transcend.sinHiQ ((ndc0.out_lo + ndc0.out_hi) / 2) +
            (ndc0.out_hi - ndc0.out_lo) / 2 ≤ nd.out_hi := of_decide_eq_true hhi
      have henc := Transcend.sin_range _ _ _ _ hmQ hloQ hhiQ
      refine Runs.sinRat hr ?_
      intro t ht1 ht2
      apply henc t
      · have hcast : ((((ndc0.out_lo + ndc0.out_hi) / 2 : ℚ)) : ℝ) -
            (((ndc0.out_hi - ndc0.out_lo) / 2 : ℚ) : ℝ) = ((ndc0.out_lo : ℚ) : ℝ) := by
          push_cast; ring
        rw [hcast]; exact ht1
      · have hcast : ((((ndc0.out_lo + ndc0.out_hi) / 2 : ℚ)) : ℝ) +
            (((ndc0.out_hi - ndc0.out_lo) / 2 : ℚ) : ℝ) = ((ndc0.out_hi : ℚ) : ℝ) := by
          push_cast; ring
        rw [hcast]; exact ht2
    · -- cos_rat  (pure ℚ; no libm TCB; §490 v1.5.0).
      have hop : nd.op = "cos_rat" := by assumption
      simp only [*] at hb
      rw [Option.map_eq_some_iff] at hb
      obtain ⟨a, hba, rfl⟩ := hb
      obtain ⟨ndc0, hf0⟩ := buildExpr_some_findNode hba
      simp only [childOut_of_findNode hf0, Bool.and_eq_true] at hcheck
      obtain ⟨⟨⟨_hMono, hm⟩, hlo⟩, hhi⟩ := hcheck
      have hr := ih _ ndc0 a hf0 hba
      have hmQ : |(ndc0.out_lo + ndc0.out_hi) / 2| ≤ 1 := of_decide_eq_true hm
      have hloQ : nd.out_lo ≤
          Transcend.cosLoQ ((ndc0.out_lo + ndc0.out_hi) / 2) -
            (ndc0.out_hi - ndc0.out_lo) / 2 := of_decide_eq_true hlo
      have hhiQ : Transcend.cosHiQ ((ndc0.out_lo + ndc0.out_hi) / 2) +
            (ndc0.out_hi - ndc0.out_lo) / 2 ≤ nd.out_hi := of_decide_eq_true hhi
      have henc := Transcend.cos_range _ _ _ _ hmQ hloQ hhiQ
      refine Runs.cosRat hr ?_
      intro t ht1 ht2
      apply henc t
      · have hcast : ((((ndc0.out_lo + ndc0.out_hi) / 2 : ℚ)) : ℝ) -
            (((ndc0.out_hi - ndc0.out_lo) / 2 : ℚ) : ℝ) = ((ndc0.out_lo : ℚ) : ℝ) := by
          push_cast; ring
        rw [hcast]; exact ht1
      · have hcast : ((((ndc0.out_lo + ndc0.out_hi) / 2 : ℚ)) : ℝ) +
            (((ndc0.out_hi - ndc0.out_lo) / 2 : ℚ) : ℝ) = ((ndc0.out_hi : ℚ) : ℝ) := by
          push_cast; ring
        rw [hcast]; exact ht2
    · -- atan_rat  (pure ℚ; no libm TCB; §490 v1.5.0).
      have hop : nd.op = "atan_rat" := by assumption
      simp only [*] at hb
      rw [Option.map_eq_some_iff] at hb
      obtain ⟨a, hba, rfl⟩ := hb
      obtain ⟨ndc0, hf0⟩ := buildExpr_some_findNode hba
      simp only [childOut_of_findNode hf0, Bool.and_eq_true] at hcheck
      obtain ⟨⟨_hMono, hloOK⟩, hhiOK⟩ := hcheck
      have hr := ih _ ndc0 a hf0 hba
      refine Runs.atanRat hr ?_
      intro t ht1 ht2
      exact ⟨Transcend.atanLo_sound hloOK ht1, Transcend.atanHi_sound hhiOK ht2⟩

/-! ### Structural extraction and the headline theorems

`structuralOk_facts` reads off the root binding the checker enforces: the
maximal-id root equals `hdr.root_id`, it is a real node, and the header's
released interval equals that root's recorded interval.  The three headline
theorems then compose `runs_of_check` with `Embed.runs_encloses`.

These are the §CERT_DESIGN deliverables in the honest "modulo-`ConstTCB`"
form forced by the `const_rounded` contract gap (file header): each carries
the disclosed const-rounding TCB `ConstTCB` as an explicit hypothesis.  Once
`CertTypes.libmNodeFact` gains its `const_rounded` case, `ConstTCB` follows
from `LibmModel` and the primes drop, verbatim, with the same proofs. -/

/-- The root facts the structural pass guarantees. -/
lemma structuralOk_facts {hdr : Header} {nodes : List Node}
    (h : structuralOk hdr nodes = true) :
    ∃ root, rootId nodes = some hdr.root_id ∧ findNode nodes hdr.root_id = some root ∧
      hdr.output_lo = root.out_lo ∧ hdr.output_hi = root.out_hi := by
  unfold structuralOk at h
  simp only [Bool.and_eq_true] at h
  obtain ⟨⟨⟨⟨⟨⟨⟨⟨⟨_, _⟩, _⟩, _⟩, _⟩, hroot⟩, _⟩, _⟩, hout⟩, _⟩ := h
  split at hroot
  · rename_i r hrid
    have hr : r = hdr.root_id := of_decide_eq_true hroot
    subst hr
    split at hout
    · rename_i root hfr
      simp only [Bool.and_eq_true] at hout
      exact ⟨root, hrid, hfr, eqQ_eq hout.1, eqQ_eq hout.2⟩
    · exact absurd hout (by simp)
  · exact absurd hroot (by simp)

/-- CENTRAL (modulo the disclosed `ConstTCB`): a certificate the checker
accepts, whose reconstructed expression is `e`, is a genuine `Runs`
derivation producing exactly the header's released interval. -/
theorem cert_check_sound' {hdr : Header} {nodes : List Node} {e : Expr}
    (hchk : checkCert hdr nodes = true) (hex : exprOf nodes = some e)
    (hlibm : LibmModel hdr nodes) (hconst : ConstTCB nodes) :
    Runs e (↑hdr.input_lo, ↑hdr.input_hi) (↑hdr.output_lo, ↑hdr.output_hi) := by
  unfold checkCert at hchk
  simp only [Bool.and_eq_true] at hchk
  obtain ⟨⟨hstruct, hallb⟩, _hsexp⟩ := hchk
  have hall : ∀ nd ∈ nodes, checkNode hdr nodes nd = true :=
    fun nd hmem => (List.all_eq_true.mp hallb) nd hmem
  obtain ⟨root, hrid, hfr, hol, hoh⟩ := structuralOk_facts hstruct
  unfold exprOf at hex
  simp only [hrid] at hex
  have hruns := runs_of_check hdr nodes hall hlibm hconst
    (nodes.length + 1) hdr.root_id root e hfr hex
  rw [hol, hoh]; exact hruns

/-- COMPOSE (modulo `ConstTCB`): the accepted certificate's reconstructed
expression is defined on the whole input interval and its exact semantics is
enclosed by the released interval at every point. -/
theorem cert_encloses' {hdr : Header} {nodes : List Node} {e : Expr}
    (hchk : checkCert hdr nodes = true) (hex : exprOf nodes = some e)
    (hlibm : LibmModel hdr nodes) (hconst : ConstTCB nodes)
    (hab : (↑hdr.input_lo : ℝ) ≤ ↑hdr.input_hi) :
    ∀ x ∈ Set.Icc (↑hdr.input_lo : ℝ) (↑hdr.input_hi),
      DefinedOn e x ∧ sem e x ∈ Set.Icc (↑hdr.output_lo : ℝ) (↑hdr.output_hi) :=
  runs_encloses (cert_check_sound' hchk hex hlibm hconst) hab

/-- CERTIFIED RELEASE (§189, modulo `ConstTCB`): for a `"bounded"` cert the
checker accepts, the released interval `[output_lo, output_hi]` encloses the
exact semantics of `e` on the input interval `[input_lo, input_hi]`. -/
theorem certified_release' {hdr : Header} {nodes : List Node} {e : Expr}
    (hchk : checkCert hdr nodes = true) (hex : exprOf nodes = some e)
    (hlibm : LibmModel hdr nodes) (hconst : ConstTCB nodes)
    (_hstatus : hdr.status_class = "bounded")
    (hab : (↑hdr.input_lo : ℝ) ≤ ↑hdr.input_hi) :
    ∀ x ∈ Set.Icc (↑hdr.input_lo : ℝ) (↑hdr.input_hi),
      sem e x ∈ Set.Icc (↑hdr.output_lo : ℝ) (↑hdr.output_hi) :=
  fun x hx => (cert_encloses' hchk hex hlibm hconst hab x hx).2

/-! ### The single named model TCB

`ModelTCB` is the ONE named trusted-computing-base hypothesis of the release
theorems: the eight transcendental libm bounds (`LibmModel`) together with the
const-rounding declared-value facts (`ConstTCB` — π/e/τ stored as a
correctly-rounded f64, irrational hence not ℚ-decidable).  Both are `Prop`
hypotheses, never Lean axioms; `#print axioms` on the theorems below shows only
`[propext, Classical.choice, Quot.sound]`. -/
def ModelTCB (hdr : Header) (nodes : List Node) : Prop :=
  LibmModel hdr nodes ∧ ConstTCB nodes

/-- CENTRAL (verbatim §CERT_DESIGN): a certificate the checker accepts, whose
reconstructed expression is `e`, is a genuine `Runs` derivation producing
exactly the header's released interval — under only the named `ModelTCB`. -/
theorem cert_check_sound {hdr : Header} {nodes : List Node} {e : Expr}
    (hchk : checkCert hdr nodes = true) (hex : exprOf nodes = some e)
    (htcb : ModelTCB hdr nodes) :
    Runs e (↑hdr.input_lo, ↑hdr.input_hi) (↑hdr.output_lo, ↑hdr.output_hi) :=
  cert_check_sound' hchk hex htcb.1 htcb.2

/-- COMPOSE (verbatim): the accepted certificate's reconstructed expression is
defined on the whole input interval and its exact semantics is enclosed by the
released interval at every point. -/
theorem cert_encloses {hdr : Header} {nodes : List Node} {e : Expr}
    (hchk : checkCert hdr nodes = true) (hex : exprOf nodes = some e)
    (htcb : ModelTCB hdr nodes)
    (hab : (↑hdr.input_lo : ℝ) ≤ ↑hdr.input_hi) :
    ∀ x ∈ Set.Icc (↑hdr.input_lo : ℝ) (↑hdr.input_hi),
      DefinedOn e x ∧ sem e x ∈ Set.Icc (↑hdr.output_lo : ℝ) (↑hdr.output_hi) :=
  cert_encloses' hchk hex htcb.1 htcb.2 hab

/-- CERTIFIED RELEASE (§189, verbatim): for a `"bounded"` cert the checker
accepts, the released interval `[output_lo, output_hi]` encloses the exact
semantics of `e` on the input interval — under only the named `ModelTCB`. -/
theorem certified_release {hdr : Header} {nodes : List Node} {e : Expr}
    (hchk : checkCert hdr nodes = true) (hex : exprOf nodes = some e)
    (htcb : ModelTCB hdr nodes)
    (hstatus : hdr.status_class = "bounded")
    (hab : (↑hdr.input_lo : ℝ) ≤ ↑hdr.input_hi) :
    ∀ x ∈ Set.Icc (↑hdr.input_lo : ℝ) (↑hdr.input_hi),
      sem e x ∈ Set.Icc (↑hdr.output_lo : ℝ) (↑hdr.output_hi) :=
  certified_release' hchk hex htcb.1 htcb.2 hstatus hab

/-! ### Axiom audit — only the three foundational axioms; `ModelTCB` (=
`LibmModel ∧ ConstTCB`) is a Prop hypothesis, never a Lean axiom. -/

#print axioms cert_check_sound
#print axioms cert_encloses
#print axioms certified_release

end JackalIv.Cert
