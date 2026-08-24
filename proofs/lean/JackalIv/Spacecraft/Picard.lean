/- Executable Picard step decisions and their interval-algebra boundary. -/
import Mathlib.Analysis.ODE.PicardLindelof
import JackalIv.Spacecraft.VectorField

namespace JackalIv.Spacecraft

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
  pure (addBox initial (scaleBox bits (pointRat bits h) field))

def checkStep (bits : Nat) (h : ℚ) (initial tube : Box)
    (thrust : DInterval) : Except String Box :=
  if h ≤ 0 then .error "step-size" else do
    let mapped ← picardMap bits h initial tube thrust
    if strictInsideBox mapped tube then
      endpointBox bits h initial tube thrust
    else .error "picard-strict-interior"

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
  by_cases hh : h ≤ 0
  · simp_all [checkStep]
  · simp only [checkStep, if_neg hh] at hcheck
    generalize hmap : picardMap bits h initial tube thrustIv = result at hcheck
    cases result with
    | error error =>
      change Except.error error = Except.ok endpoint at hcheck
      contradiction
    | ok mapped =>
      change (if strictInsideBox mapped tube then
        endpointBox bits h initial tube thrustIv
        else Except.error "picard-strict-interior") = Except.ok endpoint at hcheck
      by_cases hstrict : strictInsideBox mapped tube = true
      · exact picard_tube_encloses_core hmap hstrict hi ht hsol
      · have hsfalse : strictInsideBox mapped tube = false :=
          Bool.eq_false_of_not_eq_true hstrict
        simp [hsfalse] at hcheck

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
  exact hsum

theorem checkStep_positive {bits : Nat} {h : ℚ} {initial tube endpoint : Box}
    {thrustIv : DInterval}
    (hcheck : checkStep bits h initial tube thrustIv = .ok endpoint) :
    (0 : ℝ) < (h : ℝ) := by
  have hq : 0 < h := by
    by_contra hn
    have hle : h ≤ 0 := le_of_not_gt hn
    simp [checkStep, hle] at hcheck
  exact_mod_cast hq

theorem checkStep_endpoint {bits : Nat} {h : ℚ} {initial tube endpoint : Box}
    {thrustIv : DInterval}
    (hcheck : checkStep bits h initial tube thrustIv = .ok endpoint) :
    endpointBox bits h initial tube thrustIv = .ok endpoint := by
  have hh : ¬h ≤ 0 := not_le_of_gt (by
    have := checkStep_positive hcheck
    exact_mod_cast this)
  simp only [checkStep, if_neg hh] at hcheck
  generalize hmap : picardMap bits h initial tube thrustIv = result at hcheck
  cases result with
  | error error =>
    change Except.error error = Except.ok endpoint at hcheck
    contradiction
  | ok mapped =>
    change (if strictInsideBox mapped tube then
      endpointBox bits h initial tube thrustIv
      else Except.error "picard-strict-interior") = Except.ok endpoint at hcheck
    by_cases hs : strictInsideBox mapped tube = true
    · simpa [hs] using hcheck
    · have hsfalse := Bool.eq_false_of_not_eq_true hs
      simp [hsfalse] at hcheck

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
  exact hsum i

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

end JackalIv.Spacecraft
