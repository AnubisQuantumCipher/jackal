/-
JackalIv/ShadowCertSound.lean — SHADOW (research-shadow, NON-AUTHORITATIVE).

Soundness of the v1.7 `bound_step` composition checker: an artifact the
checker accepts encloses the exact integral of the (embedded) integrand over
the requested interval, under the named `TreeTCB` (= `Cert.ModelTCB` per
embedded evaluation certificate).

  int_cert_sound :
    checkIntCert hdr tree = .ok () → rootQExpr tree = some q → TreeTCB tree →
      IntervalIntegrable (sem (embedQ q)) volume ↑hdr.req_lo ↑hdr.req_hi
      ∧ ↑hdr.out_lo ≤ ∫ x in ↑hdr.req_lo..↑hdr.req_hi, sem (embedQ q) x
      ∧ (∫ x in ↑hdr.req_lo..↑hdr.req_hi, sem (embedQ q) x) ≤ ↑hdr.out_hi

Proof architecture (mission §6.3), reusing the existing stack verbatim:

  * leaf premises  — `Cert.cert_check_sound` (bridge #2) turns each accepted
    embedded certificate into a `Runs` derivation; `runs_encloses` yields
    `DefinedOn` + pointwise enclosure.
  * range leaves   — measurable + bounded ⇒ integrable, constant-bound
    integral estimate (`ShadowMeasure`).
  * taylor leaves  — `Deriv.taylor2/4_enclosure_of_evaluable` with the exact
    real midpoint bound obtained by instantiating the midpoint certificate's
    `runs_encloses` at `(a+b)/2` (checked to lie inside its input interval).
  * splits         — `intervalIntegral.integral_add_adjacent_intervals` +
    `IntervalIntegrable.trans`, with the checker's exact partition equalities.
  * glue           — strong induction on the node id (children ids are
    checked strictly below their parent's id).

The theorem consumes only the checker's decided facts, transported ℚ → ℝ by
casts; no float reasoning appears (design decision D3/D5, RESEARCH_SOURCES).

No `sorry`, no axiom, no `native_decide`, no `@[implemented_by]`.
-/
import JackalIv.ShadowCertCheck
import JackalIv.ShadowMeasure

namespace JackalIv.Shadow

open JackalIv MeasureTheory Set

/-! ### Small transport helpers -/

/-- Membership from a successful `findTree`. -/
theorem mem_of_findTree {tree : List TreeNode} {id : Nat} {t : TreeNode}
    (h : findTree tree id = some t) : t ∈ tree :=
  List.mem_of_find?_eq_some h

/-- The found node carries the looked-up id. -/
theorem id_of_findTree {tree : List TreeNode} {id : Nat} {t : TreeNode}
    (h : findTree tree id = some t) : t.id = id := by
  have := List.find?_some h
  simpa using this

/-- Iterated-mirror rewriting at the depths the leaf lemmas need. -/
theorem embedQ_DQ1 (q : QExpr) : embedQ (DQiter 1 q) = Deriv.D (embedQ q) := by
  simp [DQiter, embedQ_DQ]

theorem embedQ_DQ2 (q : QExpr) :
    embedQ (DQiter 2 q) = Deriv.D (Deriv.D (embedQ q)) := by
  simp [DQiter, embedQ_DQ]

theorem embedQ_DQ3 (q : QExpr) :
    embedQ (DQiter 3 q) = Deriv.D (Deriv.D (Deriv.D (embedQ q))) := by
  simp [DQiter, embedQ_DQ]

theorem embedQ_DQ4 (q : QExpr) :
    embedQ (DQiter 4 q) = Deriv.D (Deriv.D (Deriv.D (Deriv.D (embedQ q)))) := by
  simp [DQiter, embedQ_DQ]

/-- `DQiter 0` is the identity. -/
theorem embedQ_DQ0 (q : QExpr) : embedQ (DQiter 0 q) = embedQ q := rfl

/-! ### The node-level invariant -/

/-- The per-node enclosure invariant the induction carries. -/
def NodeInv (f : ℝ → ℝ) (t : TreeNode) : Prop :=
  IntervalIntegrable f volume ↑t.a ↑t.b ∧
  (↑t.lo ≤ ∫ x in (↑t.a : ℝ)..↑t.b, f x) ∧
  ((∫ x in (↑t.a : ℝ)..↑t.b, f x) ≤ ↑t.hi)

/-! ### Leaf lemmas (real-number level) -/

/-- Range-only accepted leaf: the claimed interval is conservative w.r.t.
`(b−a)·[F.lo, F.hi]`, and the enclosure comes from `runs_encloses` +
measurable-bounded integrability. -/
theorem range_leaf_sound {e : Expr} {a b flo fhi lo hi : ℝ}
    (hab : a < b) (hrun : Runs e (a, b) (flo, fhi))
    (hlo : lo ≤ (b - a) * flo) (hhi : (b - a) * fhi ≤ hi) :
    IntervalIntegrable (sem e) volume a b ∧
    (lo ≤ ∫ x in a..b, sem e x) ∧ ((∫ x in a..b, sem e x) ≤ hi) := by
  have henc : ∀ x ∈ Icc a b, flo ≤ sem e x ∧ sem e x ≤ fhi := by
    intro x hx
    have h := runs_encloses hrun hab.le x hx
    exact ⟨h.2.1, h.2.2⟩
  obtain ⟨hint, h1, h2⟩ :=
    integral_bounds_of_encloses (sem_measurable e) hab.le henc
  exact ⟨hint, le_trans hlo h1, le_trans h2 hhi⟩

/-- Smooth-taylor2 accepted leaf, including the engine's range∩taylor
intersection: the claim must only be conservative w.r.t. the tighter of the
range ideal and the Taylor-2 ideal. -/
theorem taylor2_leaf_sound {e : Expr}
    {a b flo fhi f1lo f1hi f2lo f2hi fmlo fmhi mlo mhi lo hi : ℝ}
    (hab : a < b)
    (hF : Runs e (a, b) (flo, fhi))
    (hF1 : Runs (Deriv.D e) (a, b) (f1lo, f1hi))
    (hF2 : Runs (Deriv.D (Deriv.D e)) (a, b) (f2lo, f2hi))
    (hFm : Runs e (mlo, mhi) (fmlo, fmhi))
    (hmlo : mlo ≤ (a + b) / 2) (hmhi : (a + b) / 2 ≤ mhi)
    (hlo : lo ≤ max ((b - a) * flo) ((b - a) * fmlo + (b - a) ^ 3 / 24 * f2lo))
    (hhi : min ((b - a) * fhi) ((b - a) * fmhi + (b - a) ^ 3 / 24 * f2hi) ≤ hi) :
    IntervalIntegrable (sem e) volume a b ∧
    (lo ≤ ∫ x in a..b, sem e x) ∧ ((∫ x in a..b, sem e x) ≤ hi) := by
  -- range part (also provides integrability)
  have hencF : ∀ x ∈ Icc a b, flo ≤ sem e x ∧ sem e x ≤ fhi := by
    intro x hx
    have h := runs_encloses hF hab.le x hx
    exact ⟨h.2.1, h.2.2⟩
  obtain ⟨hint, hr1, hr2⟩ :=
    integral_bounds_of_encloses (sem_measurable e) hab.le hencF
  -- evaluability premises for the Taylor bridge
  have h0 : ∀ x ∈ Icc a b, DefinedOn e x :=
    fun x hx => (runs_encloses hF hab.le x hx).1
  have h1 : ∀ x ∈ Icc a b, DefinedOn (Deriv.D e) x :=
    fun x hx => (runs_encloses hF1 hab.le x hx).1
  have h2 : ∀ x ∈ Icc a b, DefinedOn (Deriv.D (Deriv.D e)) x :=
    fun x hx => (runs_encloses hF2 hab.le x hx).1
  have hm2 : ∀ x ∈ Icc a b, f2lo ≤ sem (Deriv.D (Deriv.D e)) x :=
    fun x hx => (runs_encloses hF2 hab.le x hx).2.1
  have hM2 : ∀ x ∈ Icc a b, sem (Deriv.D (Deriv.D e)) x ≤ f2hi :=
    fun x hx => (runs_encloses hF2 hab.le x hx).2.2
  obtain ⟨ht1, ht2⟩ := Deriv.taylor2_enclosure_of_evaluable e a b f2lo f2hi
    hab h0 h1 h2 hm2 hM2
  -- the exact midpoint value is bounded by the midpoint certificate
  have hmm : mlo ≤ mhi := le_trans hmlo hmhi
  have hc := runs_encloses hFm hmm ((a + b) / 2) ⟨hmlo, hmhi⟩
  have hcl : fmlo ≤ sem e ((a + b) / 2) := hc.2.1
  have hcu : sem e ((a + b) / 2) ≤ fmhi := hc.2.2
  have hba : (0 : ℝ) ≤ b - a := by linarith
  have hml : (b - a) * fmlo ≤ (b - a) * sem e ((a + b) / 2) :=
    mul_le_mul_of_nonneg_left hcl hba
  have hmu : (b - a) * sem e ((a + b) / 2) ≤ (b - a) * fmhi :=
    mul_le_mul_of_nonneg_left hcu hba
  refine ⟨hint, ?_, ?_⟩
  · have htl : (b - a) * fmlo + (b - a) ^ 3 / 24 * f2lo
        ≤ ∫ x in a..b, sem e x := by linarith
    exact le_trans hlo (max_le hr1 htl)
  · have hth : (∫ x in a..b, sem e x)
        ≤ (b - a) * fmhi + (b - a) ^ 3 / 24 * f2hi := by linarith
    exact le_trans (le_min hr2 hth) hhi

/-- Smooth-taylor4 accepted leaf, including the engine's range∩taylor
intersection. -/
theorem taylor4_leaf_sound {e : Expr}
    {a b flo fhi f1lo f1hi f2lo f2hi f3lo f3hi f4lo f4hi
      fmlo fmhi f2mlo f2mhi mlo mhi m2lo m2hi lo hi : ℝ}
    (hab : a < b)
    (hF : Runs e (a, b) (flo, fhi))
    (hF1 : Runs (Deriv.D e) (a, b) (f1lo, f1hi))
    (hF2 : Runs (Deriv.D (Deriv.D e)) (a, b) (f2lo, f2hi))
    (hF3 : Runs (Deriv.D (Deriv.D (Deriv.D e))) (a, b) (f3lo, f3hi))
    (hF4 : Runs (Deriv.D (Deriv.D (Deriv.D (Deriv.D e)))) (a, b) (f4lo, f4hi))
    (hFm : Runs e (mlo, mhi) (fmlo, fmhi))
    (hF2m : Runs (Deriv.D (Deriv.D e)) (m2lo, m2hi) (f2mlo, f2mhi))
    (hmlo : mlo ≤ (a + b) / 2) (hmhi : (a + b) / 2 ≤ mhi)
    (hm2lo : m2lo ≤ (a + b) / 2) (hm2hi : (a + b) / 2 ≤ m2hi)
    (hlo : lo ≤ max ((b - a) * flo)
      ((b - a) * fmlo + (b - a) ^ 3 / 24 * f2mlo + (b - a) ^ 5 / 1920 * f4lo))
    (hhi : min ((b - a) * fhi)
      ((b - a) * fmhi + (b - a) ^ 3 / 24 * f2mhi + (b - a) ^ 5 / 1920 * f4hi)
      ≤ hi) :
    IntervalIntegrable (sem e) volume a b ∧
    (lo ≤ ∫ x in a..b, sem e x) ∧ ((∫ x in a..b, sem e x) ≤ hi) := by
  have hencF : ∀ x ∈ Icc a b, flo ≤ sem e x ∧ sem e x ≤ fhi := by
    intro x hx
    have h := runs_encloses hF hab.le x hx
    exact ⟨h.2.1, h.2.2⟩
  obtain ⟨hint, hr1, hr2⟩ :=
    integral_bounds_of_encloses (sem_measurable e) hab.le hencF
  have h0 : ∀ x ∈ Icc a b, DefinedOn e x :=
    fun x hx => (runs_encloses hF hab.le x hx).1
  have h1 : ∀ x ∈ Icc a b, DefinedOn (Deriv.D e) x :=
    fun x hx => (runs_encloses hF1 hab.le x hx).1
  have h2 : ∀ x ∈ Icc a b, DefinedOn (Deriv.D (Deriv.D e)) x :=
    fun x hx => (runs_encloses hF2 hab.le x hx).1
  have h3 : ∀ x ∈ Icc a b, DefinedOn (Deriv.D (Deriv.D (Deriv.D e))) x :=
    fun x hx => (runs_encloses hF3 hab.le x hx).1
  have h4 : ∀ x ∈ Icc a b,
      DefinedOn (Deriv.D (Deriv.D (Deriv.D (Deriv.D e)))) x :=
    fun x hx => (runs_encloses hF4 hab.le x hx).1
  have hm4 : ∀ x ∈ Icc a b,
      f4lo ≤ sem (Deriv.D (Deriv.D (Deriv.D (Deriv.D e)))) x :=
    fun x hx => (runs_encloses hF4 hab.le x hx).2.1
  have hM4 : ∀ x ∈ Icc a b,
      sem (Deriv.D (Deriv.D (Deriv.D (Deriv.D e)))) x ≤ f4hi :=
    fun x hx => (runs_encloses hF4 hab.le x hx).2.2
  obtain ⟨ht1, ht2⟩ := Deriv.taylor4_enclosure_of_evaluable e a b f4lo f4hi
    hab h0 h1 h2 h3 h4 hm4 hM4
  -- exact midpoint values bounded by the two midpoint certificates
  have hmm : mlo ≤ mhi := le_trans hmlo hmhi
  have hc := runs_encloses hFm hmm ((a + b) / 2) ⟨hmlo, hmhi⟩
  have hm2m : m2lo ≤ m2hi := le_trans hm2lo hm2hi
  have hc2 := runs_encloses hF2m hm2m ((a + b) / 2) ⟨hm2lo, hm2hi⟩
  have hba : (0 : ℝ) ≤ b - a := by linarith
  have hba3 : (0 : ℝ) ≤ (b - a) ^ 3 / 24 := by positivity
  have hml : (b - a) * fmlo ≤ (b - a) * sem e ((a + b) / 2) :=
    mul_le_mul_of_nonneg_left hc.2.1 hba
  have hmu : (b - a) * sem e ((a + b) / 2) ≤ (b - a) * fmhi :=
    mul_le_mul_of_nonneg_left hc.2.2 hba
  have h2ml : (b - a) ^ 3 / 24 * f2mlo
      ≤ (b - a) ^ 3 / 24 * sem (Deriv.D (Deriv.D e)) ((a + b) / 2) :=
    mul_le_mul_of_nonneg_left hc2.2.1 hba3
  have h2mu : (b - a) ^ 3 / 24 * sem (Deriv.D (Deriv.D e)) ((a + b) / 2)
      ≤ (b - a) ^ 3 / 24 * f2mhi :=
    mul_le_mul_of_nonneg_left hc2.2.2 hba3
  refine ⟨hint, ?_, ?_⟩
  · have htl : (b - a) * fmlo + (b - a) ^ 3 / 24 * f2mlo
        + (b - a) ^ 5 / 1920 * f4lo ≤ ∫ x in a..b, sem e x := by linarith
    exact le_trans hlo (max_le hr1 htl)
  · have hth : (∫ x in a..b, sem e x) ≤ (b - a) * fmhi
        + (b - a) ^ 3 / 24 * f2mhi + (b - a) ^ 5 / 1920 * f4hi := by linarith
    exact le_trans (le_min hr2 hth) hhi

/-- Split node: adjacent-interval additivity + parent-sum conservativity. -/
theorem split_sound {f : ℝ → ℝ} {a m b llo lhi rlo rhi lo hi : ℝ}
    (hL : IntervalIntegrable f volume a m ∧
      (llo ≤ ∫ x in a..m, f x) ∧ ((∫ x in a..m, f x) ≤ lhi))
    (hR : IntervalIntegrable f volume m b ∧
      (rlo ≤ ∫ x in m..b, f x) ∧ ((∫ x in m..b, f x) ≤ rhi))
    (hlo : lo ≤ llo + rlo) (hhi : lhi + rhi ≤ hi) :
    IntervalIntegrable f volume a b ∧
    (lo ≤ ∫ x in a..b, f x) ∧ ((∫ x in a..b, f x) ≤ hi) := by
  have hint := hL.1.trans hR.1
  have hadd := intervalIntegral.integral_add_adjacent_intervals hL.1 hR.1
  refine ⟨hint, ?_, ?_⟩
  · have := hL.2.1; have := hR.2.1; linarith
  · have := hL.2.2; have := hR.2.2; linarith

/-! ### ℚ → ℝ transports for checker-decided facts -/

private theorem castQ_le {p r : ℚ} (h : p ≤ r) : (↑p : ℝ) ≤ ↑r :=
  Rat.cast_le.mpr h

private theorem castQ_lt {p r : ℚ} (h : p < r) : (↑p : ℝ) < ↑r :=
  Rat.cast_lt.mpr h

/-- Cast the ℚ midpoint bound to the real exact midpoint. -/
private theorem cast_mid_le {m a b : ℚ} (h : m ≤ (a + b) / 2) :
    (↑m : ℝ) ≤ ((↑a : ℝ) + ↑b) / 2 := by
  have := castQ_le h
  push_cast at this
  linarith

private theorem cast_le_mid {m a b : ℚ} (h : (a + b) / 2 ≤ m) :
    ((↑a : ℝ) + ↑b) / 2 ≤ (↑m : ℝ) := by
  have := castQ_le h
  push_cast at this
  linarith
/-! ### Checker-fact extraction helpers -/

/-- A supported leaf kind is one of the three shipped modes. -/
private theorem isLeafKind_cases {k : String} (h : isLeafKind k = true) :
    k = "range" ∨ k = "taylor2" ∨ k = "taylor4" := by
  unfold isLeafKind at h
  simp only [Bool.or_eq_true, beq_iff_eq] at h
  tauto

/-- Everything `checkEmbedded` decides, extracted. -/
private theorem checkEmbedded_ok {hdr : IntHeader} {q : QExpr} {t : TreeNode}
    {spec : Nat × Bool} {c : EvalCert}
    (h : checkEmbedded hdr q t spec c = .ok ()) :
    Cert.checkCert c.hdr c.nodes = true ∧
    qexprOf c.nodes = some (DQiter spec.1 q) ∧
    (spec.2 = true → c.hdr.input_lo = t.a ∧ c.hdr.input_hi = t.b) ∧
    (spec.2 = false → c.hdr.input_lo ≤ (t.a + t.b) / 2 ∧
      (t.a + t.b) / 2 ≤ c.hdr.input_hi) := by
  unfold checkEmbedded at h
  obtain ⟨h1, h⟩ := bind_guard_ok h
  obtain ⟨h2, h⟩ := bind_guard_ok h
  obtain ⟨_h3, h⟩ := bind_guard_ok h
  refine ⟨h1, beq_iff_eq.mp h2, ?_, ?_⟩
  · intro hs
    rw [if_pos hs] at h
    have hc := guard_ok h
    simp only [Bool.and_eq_true] at hc
    exact ⟨beq_iff_eq.mp hc.1, beq_iff_eq.mp hc.2⟩
  · intro hs
    rw [if_neg (by simp [hs])] at h
    have hc := guard_ok h
    simp only [Bool.and_eq_true] at hc
    exact ⟨of_decide_eq_true hc.1, of_decide_eq_true hc.2⟩

/-- Shape + ideal facts of an accepted `range` leaf. -/
private theorem ideal_range_shape {t : TreeNode} (hk : t.kind = "range")
    (h : checkLeafIdeal t = .ok ()) :
    ∃ cF, t.certs = [cF] ∧
      t.lo ≤ (t.b - t.a) * cF.hdr.output_lo ∧
      (t.b - t.a) * cF.hdr.output_hi ≤ t.hi := by
  unfold checkLeafIdeal at h
  simp only [hk] at h
  rw [if_pos (show (("range" == "range") = true) by decide)] at h
  cases hcs : t.certs with
  | nil => rw [hcs] at h; simp at h
  | cons cF rest =>
    cases rest with
    | cons _ _ => rw [hcs] at h; simp at h
    | nil =>
      rw [hcs] at h
      simp only [] at h
      obtain ⟨hlo, h⟩ := bind_guard_ok h
      have hhi := guard_ok h
      exact ⟨cF, rfl, of_decide_eq_true hlo, of_decide_eq_true hhi⟩

/-- Shape + ideal facts of an accepted `taylor2` leaf. -/
private theorem ideal_taylor2_shape {t : TreeNode} (hk : t.kind = "taylor2")
    (h : checkLeafIdeal t = .ok ()) :
    ∃ cF cF1 cF2 cFm, t.certs = [cF, cF1, cF2, cFm] ∧
      t.lo ≤ max ((t.b - t.a) * cF.hdr.output_lo)
        ((t.b - t.a) * cFm.hdr.output_lo
          + (t.b - t.a) ^ 3 / 24 * cF2.hdr.output_lo) ∧
      min ((t.b - t.a) * cF.hdr.output_hi)
        ((t.b - t.a) * cFm.hdr.output_hi
          + (t.b - t.a) ^ 3 / 24 * cF2.hdr.output_hi) ≤ t.hi := by
  unfold checkLeafIdeal at h
  simp only [hk] at h
  rw [if_neg (show ¬(("taylor2" == "range") = true) by decide),
    if_pos (show (("taylor2" == "taylor2") = true) by decide)] at h
  cases hcs : t.certs with
  | nil => rw [hcs] at h; simp at h
  | cons cF r1 =>
    cases r1 with
    | nil => rw [hcs] at h; simp at h
    | cons cF1 r2 =>
      cases r2 with
      | nil => rw [hcs] at h; simp at h
      | cons cF2 r3 =>
        cases r3 with
        | nil => rw [hcs] at h; simp at h
        | cons cFm r4 =>
          cases r4 with
          | cons _ _ => rw [hcs] at h; simp at h
          | nil =>
            rw [hcs] at h
            simp only [] at h
            obtain ⟨hlo, h⟩ := bind_guard_ok h
            have hhi := guard_ok h
            exact ⟨cF, cF1, cF2, cFm, rfl,
              of_decide_eq_true hlo, of_decide_eq_true hhi⟩

/-- Shape + ideal facts of an accepted `taylor4` leaf. -/
private theorem ideal_taylor4_shape {t : TreeNode} (hk : t.kind = "taylor4")
    (h : checkLeafIdeal t = .ok ()) :
    ∃ cF cF1 cF2 cF3 cF4 cFm cF2m,
      t.certs = [cF, cF1, cF2, cF3, cF4, cFm, cF2m] ∧
      t.lo ≤ max ((t.b - t.a) * cF.hdr.output_lo)
        ((t.b - t.a) * cFm.hdr.output_lo
          + (t.b - t.a) ^ 3 / 24 * cF2m.hdr.output_lo
          + (t.b - t.a) ^ 5 / 1920 * cF4.hdr.output_lo) ∧
      min ((t.b - t.a) * cF.hdr.output_hi)
        ((t.b - t.a) * cFm.hdr.output_hi
          + (t.b - t.a) ^ 3 / 24 * cF2m.hdr.output_hi
          + (t.b - t.a) ^ 5 / 1920 * cF4.hdr.output_hi) ≤ t.hi := by
  unfold checkLeafIdeal at h
  simp only [hk] at h
  rw [if_neg (show ¬(("taylor4" == "range") = true) by decide),
    if_neg (show ¬(("taylor4" == "taylor2") = true) by decide),
    if_pos (show (("taylor4" == "taylor4") = true) by decide)] at h
  cases hcs : t.certs with
  | nil => rw [hcs] at h; simp at h
  | cons cF r1 =>
    cases r1 with
    | nil => rw [hcs] at h; simp at h
    | cons cF1 r2 =>
      cases r2 with
      | nil => rw [hcs] at h; simp at h
      | cons cF2 r3 =>
        cases r3 with
        | nil => rw [hcs] at h; simp at h
        | cons cF3 r4 =>
          cases r4 with
          | nil => rw [hcs] at h; simp at h
          | cons cF4 r5 =>
            cases r5 with
            | nil => rw [hcs] at h; simp at h
            | cons cFm r6 =>
              cases r6 with
              | nil => rw [hcs] at h; simp at h
              | cons cF2m r7 =>
                cases r7 with
                | cons _ _ => rw [hcs] at h; simp at h
                | nil =>
                  rw [hcs] at h
                  simp only [] at h
                  obtain ⟨hlo, h⟩ := bind_guard_ok h
                  have hhi := guard_ok h
                  exact ⟨cF, cF1, cF2, cF3, cF4, cFm, cF2m, rfl,
                    of_decide_eq_true hlo, of_decide_eq_true hhi⟩

/-- One step of `checkLeafCerts` extraction. -/
private theorem leafCerts_cons {hdr : IntHeader} {q : QExpr} {t : TreeNode}
    {spec : Nat × Bool} {specs : List (Nat × Bool)} {c : EvalCert}
    {cs : List EvalCert}
    (h : checkLeafCerts hdr q t (spec :: specs) (c :: cs) = .ok ()) :
    checkEmbedded hdr q t spec c = .ok () ∧
    checkLeafCerts hdr q t specs cs = .ok () := by
  unfold checkLeafCerts at h
  obtain ⟨⟨⟩, h1, h2⟩ := except_bind_ok h
  exact ⟨h1, h2⟩

/-- Build the `Runs` fact of one embedded certificate at chain depth `k`. -/
private theorem runs_of_embedded {hdr : IntHeader} {q : QExpr} {t : TreeNode}
    {k : Nat} {full : Bool} {c : EvalCert}
    (hEmb : checkEmbedded hdr q t (k, full) c = .ok ())
    (hTCB : Cert.ModelTCB c.hdr c.nodes) :
    Runs (embedQ (DQiter k q)) (↑c.hdr.input_lo, ↑c.hdr.input_hi)
      (↑c.hdr.output_lo, ↑c.hdr.output_hi) := by
  obtain ⟨hchk, hqx, _, _⟩ := checkEmbedded_ok hEmb
  exact Cert.cert_check_sound hchk (qexprOf_embed _ _ hqx) hTCB

/-! ### The composition soundness theorem -/

set_option maxHeartbeats 1600000 in
/-- **`bound_step` composition soundness (SHADOW)** — an artifact accepted by
`checkIntCert` yields a genuine enclosure of the exact integral of the
reconstructed integrand over the requested interval, under the named
`TreeTCB`.  This mechanizes roadmap item (4)'s composition in
non-authoritative shadow mode: every leaf premise flows through the existing
`cert_check_sound` / `runs_encloses` / Taylor bridges, and subdivision
composes by exact partition + interval addition. -/
theorem int_cert_sound (hdr : IntHeader) (tree : List TreeNode) (q : QExpr)
    (hchk : checkIntCert hdr tree = .ok ())
    (hq : rootQExpr tree = some q)
    (htcb : TreeTCB tree) :
    IntervalIntegrable (sem (embedQ q)) volume ↑hdr.req_lo ↑hdr.req_hi ∧
    ((↑hdr.out_lo : ℝ) ≤
      ∫ x in (↑hdr.req_lo : ℝ)..↑hdr.req_hi, sem (embedQ q) x) ∧
    ((∫ x in (↑hdr.req_lo : ℝ)..↑hdr.req_hi, sem (embedQ q) x)
      ≤ (↑hdr.out_hi : ℝ)) := by
  unfold checkIntCert at hchk
  obtain ⟨⟨⟩, _hHdr, hchk⟩ := except_bind_ok hchk
  obtain ⟨⟨⟩, _hStruct, hchk⟩ := except_bind_ok hchk
  cases hroot : findTree tree hdr.root_id with
  | none => rw [hroot] at hchk; simp at hchk
  | some root =>
    rw [hroot] at hchk
    simp only [] at hchk
    obtain ⟨hdomB, hchk⟩ := bind_guard_ok hchk
    rw [hq] at hchk
    simp only [] at hchk
    obtain ⟨⟨⟩, hAllE, hchk⟩ := except_bind_ok hchk
    obtain ⟨hrelB, hchk⟩ := bind_guard_ok hchk
    have _htolB := guard_ok hchk
    have hall := allE_ok hAllE
    -- the per-node invariant, by induction on an id bound
    have main : ∀ n id, id < n → ∀ t, findTree tree id = some t →
        NodeInv (sem (embedQ q)) t := by
      intro n
      induction n with
      | zero => intro id hid; omega
      | succ n ihn =>
        intro id hid t hfind
        have hmem : t ∈ tree := mem_of_findTree hfind
        have htid : t.id = id := id_of_findTree hfind
        have hnode := hall t hmem
        unfold checkTreeNode at hnode
        obtain ⟨habB, hnode⟩ := bind_guard_ok hnode
        obtain ⟨_hlohiB, hnode⟩ := bind_guard_ok hnode
        have habQ : t.a < t.b := of_decide_eq_true habB
        have habR : (↑t.a : ℝ) < ↑t.b := castQ_lt habQ
        by_cases hk : (t.kind == "split") = true
        · -- split node
          rw [if_pos hk] at hnode
          obtain ⟨_hce, hnode⟩ := bind_guard_ok hnode
          cases hch : t.children with
          | nil => rw [hch] at hnode; simp at hnode
          | cons lid rest =>
            cases rest with
            | nil => rw [hch] at hnode; simp at hnode
            | cons rid rest2 =>
              cases rest2 with
              | cons _ _ => rw [hch] at hnode; simp at hnode
              | nil =>
                rw [hch] at hnode
                simp only [] at hnode
                obtain ⟨hidsB, hnode⟩ := bind_guard_ok hnode
                simp only [Bool.and_eq_true] at hidsB
                have hlidQ : lid < t.id := of_decide_eq_true hidsB.1
                have hridQ : rid < t.id := of_decide_eq_true hidsB.2
                cases hfl : findTree tree lid with
                | none => rw [hfl] at hnode; simp at hnode
                | some l =>
                  cases hfr : findTree tree rid with
                  | none => rw [hfl, hfr] at hnode; simp at hnode
                  | some r =>
                    rw [hfl, hfr] at hnode
                    simp only [] at hnode
                    obtain ⟨hlaB, hnode⟩ := bind_guard_ok hnode
                    obtain ⟨hmidB, hnode⟩ := bind_guard_ok hnode
                    obtain ⟨hrbB, hnode⟩ := bind_guard_ok hnode
                    obtain ⟨hsloB, hnode⟩ := bind_guard_ok hnode
                    have hshiB := guard_ok hnode
                    have hla : l.a = t.a := beq_iff_eq.mp hlaB
                    have hmid : l.b = r.a := beq_iff_eq.mp hmidB
                    have hrb : r.b = t.b := beq_iff_eq.mp hrbB
                    have hslo : t.lo ≤ l.lo + r.lo := of_decide_eq_true hsloB
                    have hshi : l.hi + r.hi ≤ t.hi := of_decide_eq_true hshiB
                    have hIl := ihn lid (by omega) l hfl
                    have hIr := ihn rid (by omega) r hfr
                    unfold NodeInv at hIl hIr ⊢
                    rw [hla, hmid] at hIl
                    rw [hrb] at hIr
                    have hsloR : (↑t.lo : ℝ) ≤ ↑l.lo + ↑r.lo := by
                      have := castQ_le hslo; push_cast at this; linarith
                    have hshiR : (↑l.hi : ℝ) + ↑r.hi ≤ ↑t.hi := by
                      have := castQ_le hshi; push_cast at this; linarith
                    exact split_sound hIl hIr hsloR hshiR
        · -- leaf node
          rw [if_neg hk] at hnode
          obtain ⟨hleafk, hnode⟩ := bind_guard_ok hnode
          obtain ⟨_hdeg, hnode⟩ := bind_guard_ok hnode
          obtain ⟨_hchE, hnode⟩ := bind_guard_ok hnode
          obtain ⟨⟨⟩, hCerts, hnode⟩ := except_bind_ok hnode
          obtain ⟨⟨⟩, hIdeal, _hPolicy⟩ := except_bind_ok hnode
          unfold NodeInv
          rcases isLeafKind_cases hleafk with hkind | hkind | hkind
          · -- range leaf
            obtain ⟨cF, hcs, hloQ, hhiQ⟩ := ideal_range_shape hkind hIdeal
            rw [hkind, hcs] at hCerts
            rw [show roleSpecs "range" = [(0, true)] from by decide] at hCerts
            obtain ⟨hEmbF, _⟩ := leafCerts_cons hCerts
            have hTCBF := htcb.cert hmem (show cF ∈ t.certs by rw [hcs]; simp)
            have hrunF := runs_of_embedded hEmbF hTCBF
            rw [embedQ_DQ0] at hrunF
            obtain ⟨_, _, hfull, _⟩ := checkEmbedded_ok hEmbF
            obtain ⟨hin1, hin2⟩ := hfull rfl
            rw [hin1, hin2] at hrunF
            have hloR : (↑t.lo : ℝ)
                ≤ ((↑t.b : ℝ) - ↑t.a) * ↑cF.hdr.output_lo := by
              have := castQ_le hloQ; push_cast at this; linarith
            have hhiR : ((↑t.b : ℝ) - ↑t.a) * ↑cF.hdr.output_hi
                ≤ ↑t.hi := by
              have := castQ_le hhiQ; push_cast at this; linarith
            exact range_leaf_sound habR hrunF hloR hhiR
          · -- taylor2 leaf
            obtain ⟨cF, cF1, cF2, cFm, hcs, hloQ, hhiQ⟩ :=
              ideal_taylor2_shape hkind hIdeal
            rw [hkind, hcs] at hCerts
            rw [show roleSpecs "taylor2"
                = [(0, true), (1, true), (2, true), (0, false)]
              from by decide] at hCerts
            obtain ⟨hEmbF, hCerts⟩ := leafCerts_cons hCerts
            obtain ⟨hEmbF1, hCerts⟩ := leafCerts_cons hCerts
            obtain ⟨hEmbF2, hCerts⟩ := leafCerts_cons hCerts
            obtain ⟨hEmbFm, _⟩ := leafCerts_cons hCerts
            have hTCBF := htcb.cert hmem (show cF ∈ t.certs by rw [hcs]; simp)
            have hTCBF1 := htcb.cert hmem (show cF1 ∈ t.certs by rw [hcs]; simp)
            have hTCBF2 := htcb.cert hmem (show cF2 ∈ t.certs by rw [hcs]; simp)
            have hTCBFm := htcb.cert hmem (show cFm ∈ t.certs by rw [hcs]; simp)
            have hrunF := runs_of_embedded hEmbF hTCBF
            have hrunF1 := runs_of_embedded hEmbF1 hTCBF1
            have hrunF2 := runs_of_embedded hEmbF2 hTCBF2
            have hrunFm := runs_of_embedded hEmbFm hTCBFm
            rw [embedQ_DQ0] at hrunF hrunFm
            rw [embedQ_DQ1] at hrunF1
            rw [embedQ_DQ2] at hrunF2
            obtain ⟨_, _, hfullF, _⟩ := checkEmbedded_ok hEmbF
            obtain ⟨hinF1, hinF2⟩ := hfullF rfl
            rw [hinF1, hinF2] at hrunF
            obtain ⟨_, _, hfullF1, _⟩ := checkEmbedded_ok hEmbF1
            obtain ⟨hin11, hin12⟩ := hfullF1 rfl
            rw [hin11, hin12] at hrunF1
            obtain ⟨_, _, hfullF2, _⟩ := checkEmbedded_ok hEmbF2
            obtain ⟨hin21, hin22⟩ := hfullF2 rfl
            rw [hin21, hin22] at hrunF2
            obtain ⟨_, _, _, hmidFm⟩ := checkEmbedded_ok hEmbFm
            obtain ⟨hmlo, hmhi⟩ := hmidFm rfl
            have hloR : (↑t.lo : ℝ) ≤
                max (((↑t.b : ℝ) - ↑t.a) * ↑cF.hdr.output_lo)
                  (((↑t.b : ℝ) - ↑t.a) * ↑cFm.hdr.output_lo
                    + ((↑t.b : ℝ) - ↑t.a) ^ 3 / 24 * ↑cF2.hdr.output_lo) := by
              have := castQ_le hloQ; push_cast at this; linarith
            have hhiR :
                min (((↑t.b : ℝ) - ↑t.a) * ↑cF.hdr.output_hi)
                  (((↑t.b : ℝ) - ↑t.a) * ↑cFm.hdr.output_hi
                    + ((↑t.b : ℝ) - ↑t.a) ^ 3 / 24 * ↑cF2.hdr.output_hi)
                  ≤ (↑t.hi : ℝ) := by
              have := castQ_le hhiQ; push_cast at this; linarith
            exact taylor2_leaf_sound habR hrunF hrunF1 hrunF2 hrunFm
              (cast_mid_le hmlo) (cast_le_mid hmhi) hloR hhiR
          · -- taylor4 leaf
            obtain ⟨cF, cF1, cF2, cF3, cF4, cFm, cF2m, hcs, hloQ, hhiQ⟩ :=
              ideal_taylor4_shape hkind hIdeal
            rw [hkind, hcs] at hCerts
            rw [show roleSpecs "taylor4"
                = [(0, true), (1, true), (2, true), (3, true), (4, true),
                   (0, false), (2, false)] from by decide] at hCerts
            obtain ⟨hEmbF, hCerts⟩ := leafCerts_cons hCerts
            obtain ⟨hEmbF1, hCerts⟩ := leafCerts_cons hCerts
            obtain ⟨hEmbF2, hCerts⟩ := leafCerts_cons hCerts
            obtain ⟨hEmbF3, hCerts⟩ := leafCerts_cons hCerts
            obtain ⟨hEmbF4, hCerts⟩ := leafCerts_cons hCerts
            obtain ⟨hEmbFm, hCerts⟩ := leafCerts_cons hCerts
            obtain ⟨hEmbF2m, _⟩ := leafCerts_cons hCerts
            have hTCBF := htcb.cert hmem (show cF ∈ t.certs by rw [hcs]; simp)
            have hTCBF1 := htcb.cert hmem (show cF1 ∈ t.certs by rw [hcs]; simp)
            have hTCBF2 := htcb.cert hmem (show cF2 ∈ t.certs by rw [hcs]; simp)
            have hTCBF3 := htcb.cert hmem (show cF3 ∈ t.certs by rw [hcs]; simp)
            have hTCBF4 := htcb.cert hmem (show cF4 ∈ t.certs by rw [hcs]; simp)
            have hTCBFm := htcb.cert hmem (show cFm ∈ t.certs by rw [hcs]; simp)
            have hTCBF2m := htcb.cert hmem (show cF2m ∈ t.certs by rw [hcs]; simp)
            have hrunF := runs_of_embedded hEmbF hTCBF
            have hrunF1 := runs_of_embedded hEmbF1 hTCBF1
            have hrunF2 := runs_of_embedded hEmbF2 hTCBF2
            have hrunF3 := runs_of_embedded hEmbF3 hTCBF3
            have hrunF4 := runs_of_embedded hEmbF4 hTCBF4
            have hrunFm := runs_of_embedded hEmbFm hTCBFm
            have hrunF2m := runs_of_embedded hEmbF2m hTCBF2m
            rw [embedQ_DQ0] at hrunF hrunFm
            rw [embedQ_DQ1] at hrunF1
            rw [embedQ_DQ2] at hrunF2 hrunF2m
            rw [embedQ_DQ3] at hrunF3
            rw [embedQ_DQ4] at hrunF4
            obtain ⟨_, _, hfullF, _⟩ := checkEmbedded_ok hEmbF
            obtain ⟨hinF1, hinF2⟩ := hfullF rfl
            rw [hinF1, hinF2] at hrunF
            obtain ⟨_, _, hfullF1, _⟩ := checkEmbedded_ok hEmbF1
            obtain ⟨hin11, hin12⟩ := hfullF1 rfl
            rw [hin11, hin12] at hrunF1
            obtain ⟨_, _, hfullF2, _⟩ := checkEmbedded_ok hEmbF2
            obtain ⟨hin21, hin22⟩ := hfullF2 rfl
            rw [hin21, hin22] at hrunF2
            obtain ⟨_, _, hfullF3, _⟩ := checkEmbedded_ok hEmbF3
            obtain ⟨hin31, hin32⟩ := hfullF3 rfl
            rw [hin31, hin32] at hrunF3
            obtain ⟨_, _, hfullF4, _⟩ := checkEmbedded_ok hEmbF4
            obtain ⟨hin41, hin42⟩ := hfullF4 rfl
            rw [hin41, hin42] at hrunF4
            obtain ⟨_, _, _, hmidFm⟩ := checkEmbedded_ok hEmbFm
            obtain ⟨hmlo, hmhi⟩ := hmidFm rfl
            obtain ⟨_, _, _, hmidF2m⟩ := checkEmbedded_ok hEmbF2m
            obtain ⟨hm2lo, hm2hi⟩ := hmidF2m rfl
            have hloR : (↑t.lo : ℝ) ≤
                max (((↑t.b : ℝ) - ↑t.a) * ↑cF.hdr.output_lo)
                  (((↑t.b : ℝ) - ↑t.a) * ↑cFm.hdr.output_lo
                    + ((↑t.b : ℝ) - ↑t.a) ^ 3 / 24 * ↑cF2m.hdr.output_lo
                    + ((↑t.b : ℝ) - ↑t.a) ^ 5 / 1920 * ↑cF4.hdr.output_lo) := by
              have := castQ_le hloQ; push_cast at this; linarith
            have hhiR :
                min (((↑t.b : ℝ) - ↑t.a) * ↑cF.hdr.output_hi)
                  (((↑t.b : ℝ) - ↑t.a) * ↑cFm.hdr.output_hi
                    + ((↑t.b : ℝ) - ↑t.a) ^ 3 / 24 * ↑cF2m.hdr.output_hi
                    + ((↑t.b : ℝ) - ↑t.a) ^ 5 / 1920 * ↑cF4.hdr.output_hi)
                  ≤ (↑t.hi : ℝ) := by
              have := castQ_le hhiQ; push_cast at this; linarith
            exact taylor4_leaf_sound habR hrunF hrunF1 hrunF2 hrunF3 hrunF4
              hrunFm hrunF2m (cast_mid_le hmlo) (cast_le_mid hmhi)
              (cast_mid_le hm2lo) (cast_le_mid hm2hi) hloR hhiR
    -- root instantiation and released-interval transport
    have hrootInv := main (hdr.root_id + 1) hdr.root_id (by omega) root hroot
    unfold NodeInv at hrootInv
    simp only [Bool.and_eq_true] at hdomB hrelB
    have hra : root.a = hdr.req_lo := beq_iff_eq.mp hdomB.1
    have hrbq : root.b = hdr.req_hi := beq_iff_eq.mp hdomB.2
    rw [hra, hrbq] at hrootInv
    have hrel1 : (↑hdr.out_lo : ℝ) ≤ ↑root.lo :=
      castQ_le (of_decide_eq_true hrelB.1)
    have hrel2 : (↑root.hi : ℝ) ≤ ↑hdr.out_hi :=
      castQ_le (of_decide_eq_true hrelB.2)
    exact ⟨hrootInv.1, le_trans hrel1 hrootInv.2.1,
      le_trans hrootInv.2.2 hrel2⟩

/-! ### Axiom audit — the shadow flagship theorems -/

#print axioms int_cert_sound
#print axioms range_leaf_sound
#print axioms taylor2_leaf_sound
#print axioms taylor4_leaf_sound
#print axioms split_sound
#print axioms sem_measurable
#print axioms embedQ_DQ
#print axioms qexprOf_embed

end JackalIv.Shadow
