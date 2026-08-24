/- Executable Picard step decisions and their interval-algebra boundary. -/
import Mathlib.Analysis.ODE.PicardLindelof
import JackalIv.Spacecraft.VectorField

namespace JackalIv.Spacecraft

open scoped NNReal

def subsetIv (inner outer : DInterval) : Bool :=
  outer.lo ≤ inner.lo ∧ inner.hi ≤ outer.hi

def strictInsideIv (inner outer : DInterval) : Bool :=
  outer.lo < inner.lo ∧ inner.hi < outer.hi

def subsetBox (inner outer : Box) : Bool :=
  ∀ i, subsetIv (inner i) (outer i)

def strictInsideBox (inner outer : Box) : Bool :=
  ∀ i, strictInsideIv (inner i) (outer i)

def addBox (left right : Box) : Box := fun i => add (left i) (right i)

def scaleBox (bits : Nat) (scalar : DInterval) (box : Box) : Box :=
  fun i => mul bits scalar (box i)

def hullBox (left right : Box) : Box := fun i => hull (left i) (right i)

structure BoxValues where
  x0 : DInterval
  x1 : DInterval
  x2 : DInterval
  x3 : DInterval
  x4 : DInterval

/-- A strict capture boundary.  Keeping this helper opaque to the code
generator prevents endpoint expressions from being floated back into the
returned `Fin 5 → DInterval` closure. -/
@[noinline] def captureBox (box : Box) : BoxValues :=
  ⟨box 0, box 1, box 2, box 3, box 4⟩

def BoxValues.toBox (values : BoxValues) : Box := ![
  values.x0, values.x1, values.x2, values.x3, values.x4]

/-- Force all five coordinates now.  This is extensionally identical to the
input box, but prevents a long checked trajectory from retaining a chain of
lazy endpoint closures whose evaluation cost would grow quadratically. -/
def materializeBox (box : Box) : Box := (captureBox box).toBox

theorem captureBox_toBox_eq (box : Box) : (captureBox box).toBox = box := by
  funext i
  fin_cases i <;> rfl

theorem materializeBox_eq (box : Box) : materializeBox box = box :=
  captureBox_toBox_eq box

def openTubeSet (bits : Nat) (box : Box) : Set State :=
  Set.univ.pi fun i => Set.Ioo (lower bits (box i)) (upper bits (box i))

theorem tubeSet_isClosed (bits : Nat) (box : Box) : IsClosed (tubeSet bits box) := by
  exact isClosed_set_pi fun _ _ => isClosed_Icc

theorem openTubeSet_isOpen (bits : Nat) (box : Box) : IsOpen (openTubeSet bits box) := by
  exact isOpen_set_pi Set.finite_univ fun _ _ => isOpen_Ioo

theorem openTubeSet_subset_tubeSet (bits : Nat) (box : Box) :
    openTubeSet bits box ⊆ tubeSet bits box := by
  intro state hs i hi
  exact (hs i hi).imp le_of_lt le_of_lt

def timeIv (bits : Nat) (h : ℚ) : DInterval :=
  ⟨0, (pointRat bits h).hi⟩

def picardMap (bits : Nat) (h : ℚ) (initial tube : Box)
    (thrust : DInterval) : Except String Box := do
  let field ← burnFieldIv bits tube thrust
  pure (hullBox initial (addBox initial (scaleBox bits (timeIv bits h) field)))

def endpointBox (bits : Nat) (h : ℚ) (initial tube : Box)
    (thrust : DInterval) : Except String Box := do
  let field ← burnFieldIv bits tube thrust
  let values := captureBox
    (addBox initial (scaleBox bits (pointRat bits h) field))
  pure values.toBox

def existenceBox (bits : Nat) (initial : Box) : Box := fun i =>
  ⟨(initial i).lo - 4 * scale bits, (initial i).lo + 4 * scale bits⟩

noncomputable def existenceCenter (bits : Nat) (initial : Box) : State :=
  fun i => lower bits (initial i)

def initialRadiusAccepts (bits : Nat) (initial : Box) : Bool :=
  ∀ i, (initial i).hi - (initial i).lo ≤ 2 * scale bits

def fieldNormAccepts (bits : Nat) (field : Box) : Bool :=
  ∀ i, -12 * scale bits ≤ (field i).lo ∧ (field i).hi ≤ 12 * scale bits

/-- A conservative, independently checked Picard--Lindelöf ball.  It uses a
sup-norm ball of radius four about the lower corner of the initial box, admits
all initial points within radius two, and bounds the field norm by twelve. -/
def existenceGuard (bits : Nat) (h : ℚ) (initial : Box)
    (thrust : DInterval) : Except String Unit :=
  match burnFieldIv bits (existenceBox bits initial) thrust with
  | .error error => .error error
  | .ok field =>
      if !initialRadiusAccepts bits initial then .error "existence-initial-radius"
      else if !fieldNormAccepts bits field then .error "existence-field-norm"
      else if 12 * h > 2 then .error "existence-time-radius"
      else .ok ()

def checkStepCore (bits : Nat) (h : ℚ) (initial tube : Box)
    (thrust : DInterval) : Except String Box := do
  let mapped ← picardMap bits h initial tube thrust
  if strictInsideBox mapped tube then
    endpointBox bits h initial tube thrust
  else .error "picard-strict-interior"

def checkStep (bits : Nat) (h : ℚ) (initial tube : Box)
    (thrust : DInterval) : Except String Box :=
  if h ≤ 0 then .error "step-size" else do
    existenceGuard bits h initial thrust
    checkStepCore bits h initial tube thrust

theorem checkStep_positive {bits : Nat} {h : ℚ} {initial tube endpoint : Box}
    {thrustIv : DInterval}
    (hcheck : checkStep bits h initial tube thrustIv = .ok endpoint) :
    (0 : ℝ) < (h : ℝ) := by
  have hq : 0 < h := by
    by_contra hn
    have hle : h ≤ 0 := le_of_not_gt hn
    simp [checkStep, hle] at hcheck
  exact_mod_cast hq

theorem checkStep_guard {bits : Nat} {h : ℚ} {initial tube endpoint : Box}
    {thrustIv : DInterval}
    (hcheck : checkStep bits h initial tube thrustIv = .ok endpoint) :
    existenceGuard bits h initial thrustIv = .ok () := by
  have hh : ¬h ≤ 0 := not_le_of_gt (by
    have := checkStep_positive hcheck
    exact_mod_cast this)
  simp only [checkStep, if_neg hh] at hcheck
  generalize hg : existenceGuard bits h initial thrustIv = result at hcheck
  cases result with
  | error error =>
    change (Except.error error >>= fun _ =>
      checkStepCore bits h initial tube thrustIv) = .ok endpoint at hcheck
    contradiction
  | ok value =>
    cases value
    rfl

theorem checkStep_core {bits : Nat} {h : ℚ} {initial tube endpoint : Box}
    {thrustIv : DInterval}
    (hcheck : checkStep bits h initial tube thrustIv = .ok endpoint) :
    checkStepCore bits h initial tube thrustIv = .ok endpoint := by
  have hh : ¬h ≤ 0 := not_le_of_gt (by
    have := checkStep_positive hcheck
    exact_mod_cast this)
  have hg := checkStep_guard hcheck
  simp only [checkStep, if_neg hh] at hcheck
  rw [hg] at hcheck
  exact hcheck

theorem existenceGuard_data {bits : Nat} {h : ℚ} {initial : Box}
    {thrustIv : DInterval}
    (hguard : existenceGuard bits h initial thrustIv = .ok ()) :
    ∃ field,
      burnFieldIv bits (existenceBox bits initial) thrustIv = .ok field ∧
      initialRadiusAccepts bits initial = true ∧
      fieldNormAccepts bits field = true ∧ 12 * h ≤ 2 := by
  generalize hfield : burnFieldIv bits (existenceBox bits initial) thrustIv = result
  simp only [existenceGuard, hfield] at hguard
  cases result with
  | error error => contradiction
  | ok field =>
    by_cases hr : initialRadiusAccepts bits initial = true
    · by_cases hf : fieldNormAccepts bits field = true
      · have htime : ¬12 * h > 2 := by
          intro hbad
          simp [hr, hf, hbad] at hguard
        exact ⟨field, rfl, hr, hf, le_of_not_gt htime⟩
      · have hff : fieldNormAccepts bits field = false :=
          Bool.eq_false_of_not_eq_true hf
        simp [hr, hff] at hguard
    · have hrf : initialRadiusAccepts bits initial = false :=
        Bool.eq_false_of_not_eq_true hr
      simp [hrf] at hguard

theorem closedBall_existenceCenter_subset {bits : Nat} {initial : Box} :
    Metric.closedBall (existenceCenter bits initial) 4 ⊆
      tubeSet bits (existenceBox bits initial) := by
  intro state hs
  rw [Metric.mem_closedBall, dist_eq_norm] at hs
  have hall : ∀ i, ‖(state - existenceCenter bits initial) i‖ ≤ (4 : ℝ) :=
    (pi_norm_le_iff_of_nonneg (by norm_num)).mp hs
  rw [mem_tubeSet_iff]
  intro i
  have hi := hall i
  simp only [Pi.sub_apply, Real.norm_eq_abs, abs_le] at hi
  change -4 ≤ state i - lower bits (initial i) ∧
    state i - lower bits (initial i) ≤ 4 at hi
  simpa [Mem, existenceBox, lower, upper, sub_div, add_div, add_comm,
    (scale_real_pos bits).ne'] using hi

theorem initial_mem_existenceBall {bits : Nat} {initial : Box}
    {initialState : State}
    (hradius : initialRadiusAccepts bits initial = true)
    (hi : ∀ i, Mem bits (initialState i) (initial i)) :
    initialState ∈ Metric.closedBall (existenceCenter bits initial) 2 := by
  rw [Metric.mem_closedBall, dist_eq_norm, pi_norm_le_iff_of_nonneg (by norm_num)]
  have hw : ∀ i, (initial i).hi - (initial i).lo ≤ 2 * scale bits :=
    of_decide_eq_true hradius
  intro i
  rw [Real.norm_eq_abs, abs_le]
  have hlo := (hi i).1
  have hupp := (hi i).2
  have hwidth :
      ((initial i).hi : ℝ) / (scale bits : ℝ) -
        ((initial i).lo : ℝ) / (scale bits : ℝ) ≤ 2 := by
    have hw' : ((initial i).hi : ℝ) - ((initial i).lo : ℝ) ≤
        2 * (scale bits : ℝ) := by exact_mod_cast hw i
    calc
      ((initial i).hi : ℝ) / (scale bits : ℝ) -
          ((initial i).lo : ℝ) / (scale bits : ℝ) =
          (((initial i).hi : ℝ) - ((initial i).lo : ℝ)) /
            (scale bits : ℝ) := (sub_div _ _ _).symm
      _ ≤ 2 := (div_le_iff₀ (scale_real_pos bits)).2 (by linarith)
  simp only [existenceCenter, Pi.sub_apply]
  constructor
  · linarith
  · exact (sub_le_sub_right hupp _).trans hwidth

theorem burnField_norm_le_of_existenceGuard {bits : Nat} {initial : Box}
    {thrustIv : DInterval} {field : Box} {thrust : ℝ} {state : State}
    (hfield : burnFieldIv bits (existenceBox bits initial) thrustIv = .ok field)
    (hbound : fieldNormAccepts bits field = true)
    (ht : Mem bits thrust thrustIv)
    (hs : state ∈ Metric.closedBall (existenceCenter bits initial) 4) :
    ‖burnField thrust state‖ ≤ 12 := by
  have hdout := burnFieldIv_ok_iff.mp hfield
  have hfeq := hdout.2
  subst field
  have hd := hdout.1
  have hmem := fieldEnclosed hd
    (mem_tubeSet_iff.mp (closedBall_existenceCenter_subset hs)) ht
  have hb : ∀ i,
      -12 * scale bits ≤
        (burnFieldIvCore bits (existenceBox bits initial) thrustIv i).lo ∧
      (burnFieldIvCore bits (existenceBox bits initial) thrustIv i).hi ≤
        12 * scale bits := of_decide_eq_true hbound
  rw [pi_norm_le_iff_of_nonneg (by norm_num)]
  intro i
  rw [Real.norm_eq_abs, abs_le]
  have hlo : (-12 : ℝ) ≤ lower bits
      (burnFieldIvCore bits (existenceBox bits initial) thrustIv i) := by
    apply (le_div_iff₀ (scale_real_pos bits)).2
    have := hb i |>.1
    exact_mod_cast this
  have hupp : upper bits
      (burnFieldIvCore bits (existenceBox bits initial) thrustIv i) ≤ (12 : ℝ) := by
    apply (div_le_iff₀ (scale_real_pos bits)).2
    have := hb i |>.2
    exact_mod_cast this
  exact ⟨hlo.trans (hmem i).1, (hmem i).2.trans hupp⟩

def checkBranchSteps (bits : Nat) (h : ℚ) (branch : Nat)
    (thrust : DInterval) : Box → Nat → List StepWitness → Except String Box
  | current, _, [] => pure current
  | current, expected, step :: tail => do
      if step.branch ≠ branch ∨ step.step ≠ expected then throw "step-order"
      let endpoint ← checkStep bits h current step.tube thrust
      checkBranchSteps bits h branch thrust endpoint (expected + 1) tail

theorem subsetIv_sound {bits : Nat} {inner outer : DInterval} {x : ℝ}
    (hsub : subsetIv inner outer = true) (hx : Mem bits x inner) :
    Mem bits x outer := by
  have hsub' : outer.lo ≤ inner.lo ∧ inner.hi ≤ outer.hi := by
    exact of_decide_eq_true hsub
  constructor
  · exact (div_le_div_of_nonneg_right (by exact_mod_cast hsub'.1)
      (scale_real_pos bits).le).trans hx.1
  · exact hx.2.trans (div_le_div_of_nonneg_right (by exact_mod_cast hsub'.2)
      (scale_real_pos bits).le)

theorem strictInsideIv_subset {inner outer : DInterval}
    (h : strictInsideIv inner outer = true) : subsetIv inner outer = true := by
  apply decide_eq_true
  have h' : outer.lo < inner.lo ∧ inner.hi < outer.hi := of_decide_eq_true h
  exact ⟨h'.1.le, h'.2.le⟩

theorem strictInsideBox_subset {inner outer : Box}
    (h : strictInsideBox inner outer = true) : subsetBox inner outer = true := by
  simp only [strictInsideBox, subsetBox, decide_eq_true_eq] at *
  intro i
  exact strictInsideIv_subset (h i)

theorem mem_openTubeSet_of_strictInside {bits : Nat} {inner outer : Box}
    {state : State} (hstrict : strictInsideBox inner outer = true)
    (hmem : ∀ i, Mem bits (state i) (inner i)) :
    state ∈ openTubeSet bits outer := by
  have hall : ∀ i, strictInsideIv (inner i) (outer i) = true :=
    of_decide_eq_true hstrict
  intro i _
  have hi : (outer i).lo < (inner i).lo ∧ (inner i).hi < (outer i).hi :=
    of_decide_eq_true (hall i)
  constructor
  · exact (div_lt_div_of_pos_right (by exact_mod_cast hi.1)
      (scale_real_pos bits)).trans_le (hmem i).1
  · exact (hmem i).2.trans_lt (div_lt_div_of_pos_right
      (by exact_mod_cast hi.2) (scale_real_pos bits))

theorem addBox_sound {bits : Nat} {left right : Box} {x y : State}
    (hx : ∀ i, Mem bits (x i) (left i))
    (hy : ∀ i, Mem bits (y i) (right i)) :
    ∀ i, Mem bits ((x + y) i) ((addBox left right) i) := by
  intro i
  simpa [addBox] using add_sound (hx i) (hy i)

theorem scaleBox_sound {bits : Nat} {scalar : DInterval} {box : Box}
    {a : ℝ} {x : State} (ha : Mem bits a scalar)
    (hx : ∀ i, Mem bits (x i) (box i)) :
    ∀ i, Mem bits ((a • x) i) ((scaleBox bits scalar box) i) := by
  intro i
  simpa [scaleBox] using mul_sound ha (hx i)

theorem hullBox_sound_left {bits : Nat} {left right : Box} {x : State}
    (hx : ∀ i, Mem bits (x i) (left i)) :
    ∀ i, Mem bits (x i) ((hullBox left right) i) := by
  intro i
  exact hull_sound_left (hx i)

theorem hullBox_sound_right {bits : Nat} {left right : Box} {x : State}
    (hx : ∀ i, Mem bits (x i) (right i)) :
    ∀ i, Mem bits (x i) ((hullBox left right) i) := by
  intro i
  exact hull_sound_right (hx i)

theorem point_step_sound (bits : Nat) (h : ℚ) :
    Mem bits ((h : ℚ) : ℝ) (pointRat bits h) :=
  pointRat_sound bits h

theorem timeIv_sound {bits : Nat} {h : ℚ} {t : ℝ}
    (ht0 : 0 ≤ t) (hth : t ≤ (h : ℝ)) : Mem bits t (timeIv bits h) := by
  constructor
  · simpa [lower, timeIv] using ht0
  · exact hth.trans (by
      simpa [upper, timeIv, pointRat] using (pointRat_sound bits h).2)

theorem picardMap_sound {bits : Nat} {h : ℚ} {initial tube : Box}
    {thrustIv : DInterval} {mapped : Box}
    {initialState state : State} {thrust t : ℝ}
    (hmap : picardMap bits h initial tube thrustIv = .ok mapped)
    (hi : ∀ i, Mem bits (initialState i) (initial i))
    (hs : ∀ i, Mem bits (state i) (tube i))
    (ht : Mem bits thrust thrustIv) (ht0 : 0 ≤ t) (hth : t ≤ (h : ℝ)) :
    ∀ i, Mem bits
      ((initialState + t • burnField thrust state) i) (mapped i) := by
  generalize hfield : burnFieldIv bits tube thrustIv = result at hmap
  cases result with
  | error error => simp [picardMap, hfield] at hmap
  | ok field =>
  have hdout := burnFieldIv_ok_iff.mp hfield
  have hfeq := hdout.2
  subst field
  simp [picardMap, hfield] at hmap
  cases hmap
  have hf := fieldEnclosed hdout.1 hs ht
  have hscaled := scaleBox_sound (timeIv_sound ht0 hth) hf
  exact hullBox_sound_right (addBox_sound hi hscaled)

theorem intervalIntegral_mem_mul {bits : Nat} {time field : DInterval}
    {t : ℝ} {g : ℝ → ℝ}
    (ht : Mem bits t time) (ht0 : 0 ≤ t)
    (hgint : IntervalIntegrable g
      (MeasureTheory.volume : MeasureTheory.Measure ℝ) 0 t)
    (hg : ∀ s ∈ Set.Icc (0 : ℝ) t, Mem bits (g s) field) :
    Mem bits (∫ s in (0 : ℝ)..t, g s
      ∂(MeasureTheory.volume : MeasureTheory.Measure ℝ))
      (mul bits time field) := by
  letI : MeasureTheory.IsLocallyFiniteMeasure
      (MeasureTheory.volume : MeasureTheory.Measure ℝ) := Real.locallyFinite_volume
  have hzero := hg 0 ⟨le_rfl, ht0⟩
  have hvalid : lower bits field ≤ upper bits field := hzero.1.trans hzero.2
  have hlow : Mem bits (lower bits field) field := ⟨le_rfl, hvalid⟩
  have hupp : Mem bits (upper bits field) field := ⟨hvalid, le_rfl⟩
  have hloMul := mul_sound ht hlow
  have huppMul := mul_sound ht hupp
  have hloInt : IntervalIntegrable (fun _ : ℝ => lower bits field)
      (MeasureTheory.volume : MeasureTheory.Measure ℝ) 0 t :=
    continuous_const.intervalIntegrable 0 t
  have huppInt : IntervalIntegrable (fun _ : ℝ => upper bits field)
      (MeasureTheory.volume : MeasureTheory.Measure ℝ) 0 t :=
    continuous_const.intervalIntegrable 0 t
  constructor
  · apply hloMul.1.trans
    have hmono := intervalIntegral.integral_mono_on
      (μ := (MeasureTheory.volume : MeasureTheory.Measure ℝ)) ht0
      hloInt hgint (fun s hs => (hg s hs).1)
    calc
      t * lower bits field = ∫ _ in (0 : ℝ)..t, lower bits field
          ∂(MeasureTheory.volume : MeasureTheory.Measure ℝ) := by
        simp [intervalIntegral.integral_const]
      _ ≤ ∫ s in (0 : ℝ)..t, g s
          ∂(MeasureTheory.volume : MeasureTheory.Measure ℝ) := hmono
  · apply le_trans ?_ huppMul.2
    have hmono := intervalIntegral.integral_mono_on
      (μ := (MeasureTheory.volume : MeasureTheory.Measure ℝ)) ht0
      hgint huppInt (fun s hs => (hg s hs).2)
    calc
      (∫ s in (0 : ℝ)..t, g s
          ∂(MeasureTheory.volume : MeasureTheory.Measure ℝ)) ≤
          ∫ _ in (0 : ℝ)..t, upper bits field
            ∂(MeasureTheory.volume : MeasureTheory.Measure ℝ) := hmono
      _ = t * upper bits field := by simp [intervalIntegral.integral_const]

structure IsClassicalSolution (h : ℚ) (thrust : ℝ)
    (initial : State) (trajectory : ℝ → State) : Prop where
  initial_eq : trajectory 0 = initial
  hasDeriv : ∀ t ∈ Set.Icc (0 : ℝ) (h : ℝ),
    HasDerivWithinAt trajectory (burnField thrust (trajectory t))
      (Set.Icc (0 : ℝ) (h : ℝ)) t

/-- An accepted step has an actual classical solution for every represented
initial state and thrust.  This closes the non-vacuity boundary independently
of the narrower asymmetric enclosure tube. -/
theorem exists_classicalSolution_of_checkStep {bits : Nat} {h : ℚ}
    {initial tube endpoint : Box} {thrustIv : DInterval}
    {initialState : State} {thrust : ℝ}
    (hcheck : checkStep bits h initial tube thrustIv = .ok endpoint)
    (hi : ∀ i, Mem bits (initialState i) (initial i))
    (ht : Mem bits thrust thrustIv) :
    ∃ trajectory : ℝ → State,
      IsClassicalSolution h thrust initialState trajectory := by
  have hh := checkStep_positive hcheck
  obtain ⟨field, hfield, hradius, hbound, htime⟩ :=
    existenceGuard_data (checkStep_guard hcheck)
  have hd := (burnFieldIv_ok_iff.mp hfield).1
  have hlocal := (burnField_locallyLipschitzOn_of_domain thrust hd).mono
    (closedBall_existenceCenter_subset (bits := bits) (initial := initial))
  obtain ⟨K, hK⟩ :=
    LocallyLipschitzOn.exists_lipschitzOnWith_of_compact
      (isCompact_closedBall (existenceCenter bits initial) 4) hlocal
  let t0 : Set.Icc (0 : ℝ) (h : ℝ) := ⟨0, le_rfl, hh.le⟩
  have hnorm : ∀ state ∈ Metric.closedBall (existenceCenter bits initial) 4,
      ‖burnField thrust state‖ ≤ (12 : ℝ≥0) := by
    intro state hs
    exact burnField_norm_le_of_existenceGuard hfield hbound ht hs
  have hmul : (12 : ℝ≥0) *
      max (((h : ℝ) - (t0 : ℝ))) (((t0 : ℝ) - 0)) ≤
        (4 : ℝ≥0) - (2 : ℝ≥0) := by
    change (12 : ℝ) * max ((h : ℝ) - 0) (0 - 0) ≤ 4 - 2
    rw [max_eq_left]
    · norm_num at htime ⊢
      exact_mod_cast htime
    · simpa using hh.le
  have hpl : IsPicardLindelof (fun _ : ℝ => burnField thrust)
      (tmin := (0 : ℝ)) (tmax := (h : ℝ)) t0
      (existenceCenter bits initial) 4 2 12 K :=
    IsPicardLindelof.of_time_independent hnorm hK hmul
  have hinit : initialState ∈
      Metric.closedBall (existenceCenter bits initial) (2 : ℝ≥0) :=
    initial_mem_existenceBall hradius hi
  obtain ⟨trajectory, hzero, hderiv⟩ :=
    hpl.exists_eq_forall_mem_Icc_hasDerivWithinAt hinit
  exact ⟨trajectory, ⟨hzero, hderiv⟩⟩

theorem classicalSolution_picard_eq {h : ℚ} {thrust : ℝ}
    {initial : State} {trajectory : ℝ → State}
    (hsol : IsClassicalSolution h thrust initial trajectory)
    {t : ℝ} (ht : t ∈ Set.Icc (0 : ℝ) (h : ℝ))
    {bits : Nat} {tube : Box} (hd : FieldDomain bits tube)
    (hmem : ∀ s ∈ Set.Icc (0 : ℝ) t, trajectory s ∈ tubeSet bits tube) :
    ODE.picard (fun _ => burnField thrust) 0 initial trajectory t = trajectory t := by
  have hsub : Set.uIcc (0 : ℝ) t ⊆ Set.Icc (0 : ℝ) (h : ℝ) := by
    rw [Set.uIcc_of_le ht.1]
    exact Set.Icc_subset_Icc_right ht.2
  have hderiv : ∀ s ∈ Set.uIcc (0 : ℝ) t,
      HasDerivWithinAt trajectory (burnField thrust (trajectory s))
        (Set.uIcc (0 : ℝ) t) s := by
    intro s hs
    exact (hsol.hasDeriv s (hsub hs)).mono hsub
  have hcont : ContinuousOn
      (Function.uncurry (fun _ : ℝ => burnField thrust))
      ((Set.uIcc (0 : ℝ) t) ×ˢ tubeSet bits tube) := by
    have hf := burnField_contDiffOn_of_domain thrust hd
    exact hf.continuousOn.comp (by fun_prop) (by
      intro z hz
      exact hz.2)
  rw [← hsol.initial_eq]
  apply ODE.picard_eq_of_hasDerivAt hcont hderiv
  intro s hs
  apply hmem s
  rwa [Set.uIcc_of_le ht.1] at hs

theorem picard_tube_encloses_of_mapsTo {bits : Nat} {h : ℚ}
    {initial tube mapped : Box} {thrustIv : DInterval}
    {initialState : State} {thrust : ℝ} {trajectory : ℝ → State}
    (hmap : picardMap bits h initial tube thrustIv = .ok mapped)
    (hi : ∀ i, Mem bits (initialState i) (initial i))
    (ht : Mem bits thrust thrustIv)
    (hsol : IsClassicalSolution h thrust initialState trajectory)
    {t : ℝ} (htime : t ∈ Set.Icc (0 : ℝ) (h : ℝ))
    (hmem : ∀ s ∈ Set.Icc (0 : ℝ) t, trajectory s ∈ tubeSet bits tube) :
    ∀ i, Mem bits (trajectory t i) (mapped i) := by
  generalize hfield : burnFieldIv bits tube thrustIv = result at hmap
  cases result with
  | error error => simp [picardMap, hfield] at hmap
  | ok field =>
  have hdout := burnFieldIv_ok_iff.mp hfield
  have hfeq := hdout.2
  subst field
  simp [picardMap, hfield] at hmap
  cases hmap
  have hsub : Set.Icc (0 : ℝ) t ⊆ Set.Icc (0 : ℝ) (h : ℝ) :=
    Set.Icc_subset_Icc_right htime.2
  have hderiv : ∀ s ∈ Set.Icc (0 : ℝ) t,
      HasDerivWithinAt trajectory (burnField thrust (trajectory s))
        (Set.Icc (0 : ℝ) t) s := by
    intro s hs
    exact (hsol.hasDeriv s (hsub hs)).mono hsub
  have htraj : ContinuousOn trajectory (Set.Icc (0 : ℝ) t) :=
    HasDerivWithinAt.continuousOn hderiv
  have hfieldCont : ContinuousOn (burnField thrust ∘ trajectory)
      (Set.Icc (0 : ℝ) t) := by
    apply (burnField_contDiffOn_of_domain thrust hdout.1).continuousOn.comp htraj
    intro s hs
    exact hmem s hs
  change ContinuousOn (fun s => burnField thrust (trajectory s))
    (Set.Icc (0 : ℝ) t) at hfieldCont
  have hfmem : ∀ s ∈ Set.Icc (0 : ℝ) t,
      ∀ i, Mem bits (burnField thrust (trajectory s) i)
        ((burnFieldIvCore bits tube thrustIv) i) := by
    intro s hs
    exact fieldEnclosed hdout.1 ((mem_tubeSet_iff.mp (hmem s hs))) ht
  have hintegral : ∀ i, Mem bits
      (∫ s in (0 : ℝ)..t, burnField thrust (trajectory s) i)
      ((scaleBox bits (timeIv bits h)
        (burnFieldIvCore bits tube thrustIv)) i) := by
    intro i
    apply intervalIntegral_mem_mul (timeIv_sound htime.1 htime.2) htime.1
    · apply ContinuousOn.intervalIntegrable
      rw [Set.uIcc_of_le htime.1]
      exact (continuous_apply i).continuousOn.comp hfieldCont (fun _ _ => Set.mem_univ _)
    · intro s hs
      exact hfmem s hs i
  have hsum := addBox_sound hi hintegral
  have hpicard := classicalSolution_picard_eq hsol htime hdout.1 hmem
  intro i
  rw [← hpicard]
  have hvecInt : IntervalIntegrable (fun s => burnField thrust (trajectory s))
      (MeasureTheory.volume : MeasureTheory.Measure ℝ) 0 t :=
    ContinuousOn.intervalIntegrable (by
      rw [Set.uIcc_of_le htime.1]
      exact hfieldCont)
  have hproj : (∫ s in (0 : ℝ)..t, burnField thrust (trajectory s)) i =
      ∫ s in (0 : ℝ)..t, burnField thrust (trajectory s) i := by
    exact (((ContinuousLinearMap.proj i : State →L[ℝ] ℝ)).intervalIntegral_comp_comm
      hvecInt).symm
  simp only [ODE.picard_apply, Pi.add_apply]
  rw [hproj]
  exact hullBox_sound_right hsum i

theorem picard_tube_encloses_core {bits : Nat} {h : ℚ}
    {initial tube mapped : Box} {thrustIv : DInterval}
    {initialState : State} {thrust : ℝ} {trajectory : ℝ → State}
    (hmap : picardMap bits h initial tube thrustIv = .ok mapped)
    (hstrict : strictInsideBox mapped tube = true)
    (hi : ∀ i, Mem bits (initialState i) (initial i))
    (ht : Mem bits thrust thrustIv)
    (hsol : IsClassicalSolution h thrust initialState trajectory) :
    ∀ t ∈ Set.Icc (0 : ℝ) (h : ℝ), trajectory t ∈ tubeSet bits tube := by
  have htraj : ContinuousOn trajectory (Set.Icc (0 : ℝ) (h : ℝ)) :=
    HasDerivWithinAt.continuousOn hsol.hasDeriv
  let safeTimes : Set ℝ := trajectory ⁻¹' tubeSet bits tube
  have hclosed : IsClosed (safeTimes ∩ Set.Icc (0 : ℝ) (h : ℝ)) := by
    have hr : Continuous (Set.restrict (Set.Icc (0 : ℝ) (h : ℝ)) trajectory) :=
      continuousOn_iff_continuous_restrict.mp htraj
    have hp : IsClosed
        ((Set.restrict (Set.Icc (0 : ℝ) (h : ℝ)) trajectory) ⁻¹'
          tubeSet bits tube) := (tubeSet_isClosed bits tube).preimage hr
    have himage := isClosed_Icc.isClosedEmbedding_subtypeVal.isClosed_iff_image_isClosed.mp hp
    convert himage using 1 <;> ext x <;> simp [safeTimes, Set.restrict]
  have hzeroMapped : ∀ i, Mem bits (initialState i) (mapped i) := by
    generalize hfield : burnFieldIv bits tube thrustIv = result at hmap
    cases result with
    | error error => simp [picardMap, hfield] at hmap
    | ok field =>
      simp [picardMap, hfield] at hmap
      cases hmap
      exact hullBox_sound_left hi
  have hzeroOpen : initialState ∈ openTubeSet bits tube :=
    mem_openTubeSet_of_strictInside hstrict hzeroMapped
  have hzero : 0 ∈ safeTimes := by
    change trajectory 0 ∈ tubeSet bits tube
    rw [hsol.initial_eq]
    exact openTubeSet_subset_tubeSet bits tube hzeroOpen
  apply hclosed.Icc_subset_of_forall_mem_nhdsGT_of_Icc_subset hzero
  intro x hx hprefix
  have hxmapped : ∀ i, Mem bits (trajectory x i) (mapped i) := by
    apply picard_tube_encloses_of_mapsTo hmap hi ht hsol ⟨hx.1, hx.2.le⟩
    intro s hs
    exact hprefix hs
  have hxopen : trajectory x ∈ openTubeSet bits tube :=
    mem_openTubeSet_of_strictInside hstrict hxmapped
  have hpre : trajectory ⁻¹' openTubeSet bits tube ∈
      nhdsWithin x (Set.Icc (0 : ℝ) (h : ℝ)) :=
    (htraj x ⟨hx.1, hx.2.le⟩).preimage_mem_nhdsWithin
      ((openTubeSet_isOpen bits tube).mem_nhds hxopen)
  have hpreGT : trajectory ⁻¹' openTubeSet bits tube ∈
      nhdsWithin x (Set.Ioi x) := by
    rw [← nhdsWithin_Ioc_eq_nhdsGT hx.2]
    have hsubset : Set.Ioc x (h : ℝ) ⊆ Set.Icc (0 : ℝ) (h : ℝ) := by
      intro y hy
      exact ⟨hx.1.trans hy.1.le, hy.2⟩
    exact (nhdsWithin_mono x hsubset) hpre
  exact Filter.mem_of_superset hpreGT fun _ hy =>
    openTubeSet_subset_tubeSet bits tube hy

theorem picard_tube_encloses {bits : Nat} {h : ℚ}
    {initial tube endpoint : Box} {thrustIv : DInterval}
    {initialState : State} {thrust : ℝ} {trajectory : ℝ → State}
    (hcheck : checkStep bits h initial tube thrustIv = .ok endpoint)
    (hi : ∀ i, Mem bits (initialState i) (initial i))
    (ht : Mem bits thrust thrustIv)
    (hsol : IsClassicalSolution h thrust initialState trajectory) :
    ∀ t ∈ Set.Icc (0 : ℝ) (h : ℝ), trajectory t ∈ tubeSet bits tube := by
  have hcore := checkStep_core hcheck
  generalize hmap : picardMap bits h initial tube thrustIv = result at hcore
  simp only [checkStepCore, hmap] at hcore
  cases result with
  | error error =>
    change Except.error error = Except.ok endpoint at hcore
    contradiction
  | ok mapped =>
    change (if strictInsideBox mapped tube then
      endpointBox bits h initial tube thrustIv
      else Except.error "picard-strict-interior") = Except.ok endpoint at hcore
    by_cases hstrict : strictInsideBox mapped tube = true
    · exact picard_tube_encloses_core hmap hstrict hi ht hsol
    · have hsfalse : strictInsideBox mapped tube = false :=
        Bool.eq_false_of_not_eq_true hstrict
      simp [hsfalse] at hcore

theorem endpointBox_sound {bits : Nat} {h : ℚ} {initial tube : Box}
    {thrustIv : DInterval} {endpoint : Box}
    {initialState state : State} {thrust : ℝ}
    (hendpoint : endpointBox bits h initial tube thrustIv = .ok endpoint)
    (hi : ∀ i, Mem bits (initialState i) (initial i))
    (hs : ∀ i, Mem bits (state i) (tube i))
    (ht : Mem bits thrust thrustIv) :
    ∀ i, Mem bits
      ((initialState + (h : ℝ) • burnField thrust state) i)
      (endpoint i) := by
  generalize hfield : burnFieldIv bits tube thrustIv = result at hendpoint
  cases result with
  | error error => simp [endpointBox, hfield] at hendpoint
  | ok field =>
  have hdout := burnFieldIv_ok_iff.mp hfield
  have hfeq := hdout.2
  subst field
  simp [endpointBox, hfield] at hendpoint
  cases hendpoint
  have hd := hdout.1
  have hf := fieldEnclosed hd hs ht
  have hscaled := scaleBox_sound (pointRat_sound bits h) hf
  have hsum := addBox_sound hi hscaled
  simpa only [captureBox_toBox_eq] using hsum

theorem checkStep_endpoint {bits : Nat} {h : ℚ} {initial tube endpoint : Box}
    {thrustIv : DInterval}
    (hcheck : checkStep bits h initial tube thrustIv = .ok endpoint) :
    endpointBox bits h initial tube thrustIv = .ok endpoint := by
  have hcore := checkStep_core hcheck
  generalize hmap : picardMap bits h initial tube thrustIv = result at hcore
  simp only [checkStepCore, hmap] at hcore
  cases result with
  | error error =>
    change Except.error error = Except.ok endpoint at hcore
    contradiction
  | ok mapped =>
    change (if strictInsideBox mapped tube then
      endpointBox bits h initial tube thrustIv
      else Except.error "picard-strict-interior") = Except.ok endpoint at hcore
    by_cases hs : strictInsideBox mapped tube = true
    · simpa [hs] using hcore
    · have hsfalse := Bool.eq_false_of_not_eq_true hs
      simp [hsfalse] at hcore

theorem picard_endpoint_encloses {bits : Nat} {h : ℚ}
    {initial tube endpoint : Box} {thrustIv : DInterval}
    {initialState : State} {thrust : ℝ} {trajectory : ℝ → State}
    (hcheck : checkStep bits h initial tube thrustIv = .ok endpoint)
    (hi : ∀ i, Mem bits (initialState i) (initial i))
    (ht : Mem bits thrust thrustIv)
    (hsol : IsClassicalSolution h thrust initialState trajectory) :
    ∀ i, Mem bits (trajectory (h : ℝ) i) (endpoint i) := by
  have hh := checkStep_positive hcheck
  have htube := picard_tube_encloses hcheck hi ht hsol
  have hendpoint := checkStep_endpoint hcheck
  generalize hfield : burnFieldIv bits tube thrustIv = result at hendpoint
  cases result with
  | error error => simp [endpointBox, hfield] at hendpoint
  | ok field =>
  have hdout := burnFieldIv_ok_iff.mp hfield
  have hfeq := hdout.2
  subst field
  simp [endpointBox, hfield] at hendpoint
  cases hendpoint
  have htraj : ContinuousOn trajectory (Set.Icc (0 : ℝ) (h : ℝ)) :=
    HasDerivWithinAt.continuousOn hsol.hasDeriv
  have hfieldCont : ContinuousOn (fun s => burnField thrust (trajectory s))
      (Set.Icc (0 : ℝ) (h : ℝ)) := by
    apply (burnField_contDiffOn_of_domain thrust hdout.1).continuousOn.comp htraj
    intro s hs
    exact htube s hs
  have hfmem : ∀ s ∈ Set.Icc (0 : ℝ) (h : ℝ), ∀ i,
      Mem bits (burnField thrust (trajectory s) i)
        ((burnFieldIvCore bits tube thrustIv) i) := by
    intro s hs
    exact fieldEnclosed hdout.1 (mem_tubeSet_iff.mp (htube s hs)) ht
  have hintegral : ∀ i, Mem bits
      (∫ s in (0 : ℝ)..(h : ℝ), burnField thrust (trajectory s) i)
      ((scaleBox bits (pointRat bits h)
        (burnFieldIvCore bits tube thrustIv)) i) := by
    intro i
    apply intervalIntegral_mem_mul (pointRat_sound bits h) hh.le
    · apply ContinuousOn.intervalIntegrable
      rw [Set.uIcc_of_le hh.le]
      exact (continuous_apply i).continuousOn.comp hfieldCont
        (fun _ _ => Set.mem_univ _)
    · exact fun s hs => hfmem s hs i
  have hsum := addBox_sound hi hintegral
  have hpicard := classicalSolution_picard_eq hsol ⟨hh.le, le_rfl⟩ hdout.1 htube
  intro i
  rw [← hpicard]
  have hvecInt : IntervalIntegrable (fun s => burnField thrust (trajectory s))
      (MeasureTheory.volume : MeasureTheory.Measure ℝ) 0 (h : ℝ) :=
    ContinuousOn.intervalIntegrable (by
      rw [Set.uIcc_of_le hh.le]
      exact hfieldCont)
  have hproj : (∫ s in (0 : ℝ)..(h : ℝ), burnField thrust (trajectory s)) i =
      ∫ s in (0 : ℝ)..(h : ℝ), burnField thrust (trajectory s) i := by
    exact (((ContinuousLinearMap.proj i : State →L[ℝ] ℝ)).intervalIntegral_comp_comm
      hvecInt).symm
  simp only [ODE.picard_apply, Pi.add_apply]
  rw [hproj]
  simpa only [captureBox_toBox_eq, Pi.add_apply] using hsum i

/-- A physically continuous finite-step burn: each local classical solution
starts at the exact endpoint of the preceding local solution.  The witness
steps index the chain, so disconnected or missing trajectories cannot inhabit
this proposition. -/
inductive ClassicalSolutionChain (h : ℚ) (thrust : ℝ) :
    State → List StepWitness → State → Prop where
  | nil (state : State) : ClassicalSolutionChain h thrust state [] state
  | cons {initial terminal : State} {step : StepWitness}
      {steps : List StepWitness} (trajectory : ℝ → State)
      (solution : IsClassicalSolution h thrust initial trajectory)
      (tail : ClassicalSolutionChain h thrust (trajectory (h : ℝ)) steps terminal) :
      ClassicalSolutionChain h thrust initial (step :: steps) terminal

/-- The proof-carrying counterpart of `ClassicalSolutionChain`.  It records
the checked tube enclosure for every concrete trajectory in the same chain. -/
inductive EnclosedSolutionChain (bits : Nat) (h : ℚ) (thrust : ℝ) :
    State → List StepWitness → State → Prop where
  | nil (state : State) : EnclosedSolutionChain bits h thrust state [] state
  | cons {initial terminal : State} {step : StepWitness}
      {steps : List StepWitness} (trajectory : ℝ → State)
      (solution : IsClassicalSolution h thrust initial trajectory)
      (enclosed : ∀ t ∈ Set.Icc (0 : ℝ) (h : ℝ),
        trajectory t ∈ tubeSet bits step.tube)
      (tail : EnclosedSolutionChain bits h thrust
        (trajectory (h : ℝ)) steps terminal) :
      EnclosedSolutionChain bits h thrust initial (step :: steps) terminal

theorem checked_steps_compose {bits : Nat} {h : ℚ} {branch expected : Nat}
    {thrustIv : DInterval} {current final : Box} {steps : List StepWitness}
    {initialState terminalState : State} {thrust : ℝ}
    (hcheck : checkBranchSteps bits h branch thrustIv current expected steps = .ok final)
    (hi : ∀ i, Mem bits (initialState i) (current i))
    (ht : Mem bits thrust thrustIv)
    (hchain : ClassicalSolutionChain h thrust initialState steps terminalState) :
    EnclosedSolutionChain bits h thrust initialState steps terminalState ∧
      ∀ i, Mem bits (terminalState i) (final i) := by
  induction hchain generalizing current expected final with
  | nil state =>
      simp only [checkBranchSteps] at hcheck
      cases hcheck
      exact ⟨.nil state, hi⟩
  | @cons initial terminal step tail trajectory solution chain ih =>
      simp only [checkBranchSteps] at hcheck
      by_cases horder : step.branch ≠ branch ∨ step.step ≠ expected
      · simp only [if_pos horder] at hcheck
        contradiction
      · simp only [if_neg horder] at hcheck
        generalize hstep : checkStep bits h current step.tube thrustIv = result at hcheck
        cases result with
        | error error =>
          change Except.error error = Except.ok final at hcheck
          contradiction
        | ok endpoint =>
          change checkBranchSteps bits h branch thrustIv endpoint
            (expected + 1) tail = .ok final at hcheck
          have henclosed := picard_tube_encloses hstep hi ht solution
          have hiNext := picard_endpoint_encloses hstep hi ht solution
          have htail := ih hcheck hiNext
          exact ⟨.cons trajectory solution henclosed htail.1, htail.2⟩

/-- Executable acceptance constructs a nonempty, physically continuous chain
of classical solutions over every checked step. -/
theorem checked_steps_nonvacuous {bits : Nat} {h : ℚ} {branch expected : Nat}
    {thrustIv : DInterval} {current final : Box} {steps : List StepWitness}
    {initialState : State} {thrust : ℝ}
    (hcheck : checkBranchSteps bits h branch thrustIv current expected steps = .ok final)
    (hi : ∀ i, Mem bits (initialState i) (current i))
    (ht : Mem bits thrust thrustIv) :
    ∃ terminalState,
      ClassicalSolutionChain h thrust initialState steps terminalState ∧
        ∀ i, Mem bits (terminalState i) (final i) := by
  induction steps generalizing current expected initialState with
  | nil =>
      simp only [checkBranchSteps] at hcheck
      cases hcheck
      exact ⟨initialState, .nil initialState, hi⟩
  | cons step tail ih =>
      simp only [checkBranchSteps] at hcheck
      by_cases horder : step.branch ≠ branch ∨ step.step ≠ expected
      · simp only [if_pos horder] at hcheck
        contradiction
      · simp only [if_neg horder] at hcheck
        generalize hstep : checkStep bits h current step.tube thrustIv = result at hcheck
        cases result with
        | error error =>
          change Except.error error = Except.ok final at hcheck
          contradiction
        | ok endpoint =>
          change checkBranchSteps bits h branch thrustIv endpoint
            (expected + 1) tail = .ok final at hcheck
          obtain ⟨trajectory, hsolution⟩ :=
            exists_classicalSolution_of_checkStep hstep hi ht
          have hiNext := picard_endpoint_encloses hstep hi ht hsolution
          obtain ⟨terminalState, htail, hfinal⟩ := ih hcheck hiNext
          exact ⟨terminalState, .cons trajectory hsolution htail, hfinal⟩

end JackalIv.Spacecraft
