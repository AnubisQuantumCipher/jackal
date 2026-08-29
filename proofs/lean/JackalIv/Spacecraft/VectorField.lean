/- The exact five-state finite-burn model and its accepted regularity domain. -/
import Mathlib.Analysis.ODE.ExistUnique
import Mathlib.Analysis.Calculus.ContDiff.RCLike
import Mathlib.Analysis.SpecialFunctions.Sqrt
import JackalIv.Spacecraft.Interval

namespace JackalIv.Spacecraft

structure ModelRequest where
  dimension : Nat
  mu : ℚ
  g0 : ℚ
  isp : ℚ
  thrustKmScale : ℚ
  deriving DecidableEq, Repr

def pinnedModelRequest : ModelRequest := {
  dimension := 5
  mu := 1993002209 / 5000
  g0 := 196133 / 20000
  isp := 450
  thrustKmScale := 1 / 1000
}

def modelMatches (request : ModelRequest) : Bool := request == pinnedModelRequest

abbrev State := Fin 5 → ℝ

noncomputable def radiusSq (state : State) : ℝ := state 0 ^ 2 + state 1 ^ 2
noncomputable def speedSq (state : State) : ℝ := state 2 ^ 2 + state 3 ^ 2

noncomputable def burnField (thrust : ℝ) (state : State) : State :=
  let x := state 0
  let y := state 1
  let vx := state 2
  let vy := state 3
  let mass := state 4
  let r2 := radiusSq state
  let v2 := speedSq state
  let radius := Real.sqrt r2
  let speed := Real.sqrt v2
  let mu : ℝ := (pinnedModelRequest.mu : ℝ)
  let g0 : ℝ := (pinnedModelRequest.g0 : ℝ)
  let isp : ℝ := (pinnedModelRequest.isp : ℝ)
  let thrustScale : ℝ := (pinnedModelRequest.thrustKmScale : ℝ)
  let thrustAccel := thrust / mass * thrustScale
  let gravityDenom := r2 * radius
  fun i =>
    if i = 0 then vx
    else if i = 1 then vy
    else if i = 2 then -mu * x / gravityDenom + thrustAccel * vx / speed
    else if i = 3 then -mu * y / gravityDenom + thrustAccel * vy / speed
    else -thrust / (isp * g0)

def radiusSqIv (bits : Nat) (box : Box) : DInterval :=
  add (square bits (box 0)) (square bits (box 1))

def speedSqIv (bits : Nat) (box : Box) : DInterval :=
  add (square bits (box 2)) (square bits (box 3))

def domainAccepts (bits : Nat) (box : Box) : Bool :=
  0 < (radiusSqIv bits box).lo ∧ 0 < (speedSqIv bits box).lo ∧ 0 < (box 4).lo

def muIv (bits : Nat) : DInterval := pointRat bits pinnedModelRequest.mu
def g0Iv (bits : Nat) : DInterval := pointRat bits pinnedModelRequest.g0
def ispIv (bits : Nat) : DInterval := pointRat bits pinnedModelRequest.isp
def thrustScaleIv (bits : Nat) : DInterval :=
  pointRat bits pinnedModelRequest.thrustKmScale

def radiusIv (bits : Nat) (box : Box) : DInterval :=
  sqrtUnchecked bits (radiusSqIv bits box)

def speedIv (bits : Nat) (box : Box) : DInterval :=
  sqrtUnchecked bits (speedSqIv bits box)

def gravityDenomIv (bits : Nat) (box : Box) : DInterval :=
  mul bits (radiusSqIv bits box) (radiusIv bits box)

def ispG0Iv (bits : Nat) : DInterval := mul bits (ispIv bits) (g0Iv bits)

structure FieldDomain (bits : Nat) (box : Box) : Prop where
  radiusSqLo : 0 < (radiusSqIv bits box).lo
  speedSqLo : 0 < (speedSqIv bits box).lo
  massLo : 0 < (box 4).lo
  radiusLo : 0 < (radiusIv bits box).lo
  speedLo : 0 < (speedIv bits box).lo
  gravityDenomLo : 0 < (gravityDenomIv bits box).lo
  ispG0Lo : 0 < (ispG0Iv bits).lo

def burnFieldIvCore (bits : Nat) (box : Box) (thrust : DInterval) : Box :=
  let r2 := radiusSqIv bits box
  let speed2 := speedSqIv bits box
  let radius := sqrtUnchecked bits r2
  let speed := sqrtUnchecked bits speed2
  let thrustAccel := mul bits (divUnchecked bits thrust (box 4)) (thrustScaleIv bits)
  let gravityDenom := mul bits r2 radius
  let ax := add
    (divUnchecked bits (mul bits (neg (muIv bits)) (box 0)) gravityDenom)
    (divUnchecked bits (mul bits thrustAccel (box 2)) speed)
  let ay := add
    (divUnchecked bits (mul bits (neg (muIv bits)) (box 1)) gravityDenom)
    (divUnchecked bits (mul bits thrustAccel (box 3)) speed)
  let dm := divUnchecked bits (neg thrust) (ispG0Iv bits)
  fun i =>
    if i = 0 then box 2
    else if i = 1 then box 3
    else if i = 2 then ax
    else if i = 3 then ay
    else dm

structure BurnFieldValues where
  dx : DInterval
  dy : DInterval
  dvx : DInterval
  dvy : DInterval
  dm : DInterval

def burnFieldValues (bits : Nat) (box : Box) (thrust : DInterval) :
    BurnFieldValues :=
  let r2 := radiusSqIv bits box
  let speed2 := speedSqIv bits box
  let radius := sqrtUnchecked bits r2
  let speed := sqrtUnchecked bits speed2
  let thrustAccel := mul bits (divUnchecked bits thrust (box 4)) (thrustScaleIv bits)
  let gravityDenom := mul bits r2 radius
  let ax := add
    (divUnchecked bits (mul bits (neg (muIv bits)) (box 0)) gravityDenom)
    (divUnchecked bits (mul bits thrustAccel (box 2)) speed)
  let ay := add
    (divUnchecked bits (mul bits (neg (muIv bits)) (box 1)) gravityDenom)
    (divUnchecked bits (mul bits thrustAccel (box 3)) speed)
  let dm := divUnchecked bits (neg thrust) (ispG0Iv bits)
  ⟨box 2, box 3, ax, ay, dm⟩

def BurnFieldValues.toBox (values : BurnFieldValues) : Box := ![
  values.dx, values.dy, values.dvx, values.dvy, values.dm]

theorem burnFieldValues_toBox (bits : Nat) (box : Box) (thrust : DInterval) :
    (burnFieldValues bits box thrust).toBox = burnFieldIvCore bits box thrust := by
  funext i
  fin_cases i <;> rfl

def burnFieldIv (bits : Nat) (box : Box) (thrust : DInterval) :
    Except String Box :=
  let r2 := radiusSqIv bits box
  let v2 := speedSqIv bits box
  let radius := radiusIv bits box
  let speed := speedIv bits box
  let gravity := gravityDenomIv bits box
  let ispG0 := ispG0Iv bits
  if 0 < r2.lo ∧ 0 < v2.lo ∧ 0 < (box 4).lo ∧ 0 < radius.lo ∧
      0 < speed.lo ∧ 0 < gravity.lo ∧ 0 < ispG0.lo then
    let values := burnFieldValues bits box thrust
    .ok values.toBox
  else .error "vector-field-domain"

theorem burnFieldIv_ok_iff {bits : Nat} {box : Box} {thrust : DInterval}
    {out : Box} : burnFieldIv bits box thrust = .ok out ↔
      FieldDomain bits box ∧ out = burnFieldIvCore bits box thrust := by
  constructor
  · intro h
    simp only [burnFieldIv] at h
    split at h
    · rename_i hd
      cases h
      exact ⟨⟨hd.1, hd.2.1, hd.2.2.1, hd.2.2.2.1, hd.2.2.2.2.1,
        hd.2.2.2.2.2.1, hd.2.2.2.2.2.2⟩, burnFieldValues_toBox _ _ _⟩
    · contradiction
  · rintro ⟨hd, rfl⟩
    simp [burnFieldIv, hd.radiusSqLo, hd.speedSqLo, hd.massLo,
      hd.radiusLo, hd.speedLo, hd.gravityDenomLo, hd.ispG0Lo,
      burnFieldValues_toBox]

theorem fieldEnclosed {bits : Nat} {box : Box} {thrustIv : DInterval}
    {thrust : ℝ} {state : State}
    (hd : FieldDomain bits box)
    (hs : ∀ i, Mem bits (state i) (box i))
    (ht : Mem bits thrust thrustIv) :
    ∀ i, Mem bits ((burnField thrust state) i)
      ((burnFieldIvCore bits box thrustIv) i) := by
  have hr2 : Mem bits (radiusSq state) (radiusSqIv bits box) := by
    simpa [radiusSq, radiusSqIv] using
      add_sound (square_sound (hs 0)) (square_sound (hs 1))
  have hv2 : Mem bits (speedSq state) (speedSqIv bits box) := by
    simpa [speedSq, speedSqIv] using
      add_sound (square_sound (hs 2)) (square_sound (hs 3))
  have hr2nonneg : 0 ≤ radiusSq state := by
    simp [radiusSq]; positivity
  have hv2nonneg : 0 ≤ speedSq state := by
    simp [speedSq]; positivity
  have hradius : Mem bits (Real.sqrt (radiusSq state)) (radiusIv bits box) := by
    exact sqrt_sound hd.radiusSqLo.le hr2nonneg hr2
  have hspeed : Mem bits (Real.sqrt (speedSq state)) (speedIv bits box) := by
    exact sqrt_sound hd.speedSqLo.le hv2nonneg hv2
  have hthrustMass : Mem bits (thrust / state 4)
      (divUnchecked bits thrustIv (box 4)) :=
    div_sound ht (hs 4) (Or.inl (lower_pos_of_lo_pos hd.massLo))
  have hthrustAccel : Mem bits
      (thrust / state 4 * (pinnedModelRequest.thrustKmScale : ℝ))
      (mul bits (divUnchecked bits thrustIv (box 4)) (thrustScaleIv bits)) := by
    exact mul_sound hthrustMass (pointRat_sound bits pinnedModelRequest.thrustKmScale)
  have hgravityDenom : Mem bits
      (radiusSq state * Real.sqrt (radiusSq state))
      (gravityDenomIv bits box) := by
    exact mul_sound hr2 hradius
  have hnegMu : Mem bits (-(pinnedModelRequest.mu : ℝ)) (neg (muIv bits)) := by
    exact neg_sound (pointRat_sound bits pinnedModelRequest.mu)
  have hgravityX : Mem bits
      (-(pinnedModelRequest.mu : ℝ) * state 0 /
        (radiusSq state * Real.sqrt (radiusSq state)))
      (divUnchecked bits (mul bits (neg (muIv bits)) (box 0))
        (gravityDenomIv bits box)) := by
    exact div_sound (mul_sound hnegMu (hs 0)) hgravityDenom
      (Or.inl (lower_pos_of_lo_pos hd.gravityDenomLo))
  have hgravityY : Mem bits
      (-(pinnedModelRequest.mu : ℝ) * state 1 /
        (radiusSq state * Real.sqrt (radiusSq state)))
      (divUnchecked bits (mul bits (neg (muIv bits)) (box 1))
        (gravityDenomIv bits box)) := by
    exact div_sound (mul_sound hnegMu (hs 1)) hgravityDenom
      (Or.inl (lower_pos_of_lo_pos hd.gravityDenomLo))
  have hthrustX : Mem bits
      ((thrust / state 4 * (pinnedModelRequest.thrustKmScale : ℝ)) * state 2 /
        Real.sqrt (speedSq state))
      (divUnchecked bits
        (mul bits
          (mul bits (divUnchecked bits thrustIv (box 4)) (thrustScaleIv bits))
          (box 2))
        (speedIv bits box)) := by
    exact div_sound (mul_sound hthrustAccel (hs 2)) hspeed
      (Or.inl (lower_pos_of_lo_pos hd.speedLo))
  have hthrustY : Mem bits
      ((thrust / state 4 * (pinnedModelRequest.thrustKmScale : ℝ)) * state 3 /
        Real.sqrt (speedSq state))
      (divUnchecked bits
        (mul bits
          (mul bits (divUnchecked bits thrustIv (box 4)) (thrustScaleIv bits))
          (box 3))
        (speedIv bits box)) := by
    exact div_sound (mul_sound hthrustAccel (hs 3)) hspeed
      (Or.inl (lower_pos_of_lo_pos hd.speedLo))
  have hax := add_sound hgravityX hthrustX
  have hay := add_sound hgravityY hthrustY
  have hispG0 : Mem bits
      ((pinnedModelRequest.isp : ℝ) * (pinnedModelRequest.g0 : ℝ))
      (ispG0Iv bits) := by
    exact mul_sound (pointRat_sound bits pinnedModelRequest.isp)
      (pointRat_sound bits pinnedModelRequest.g0)
  have hdm : Mem bits
      (-thrust / ((pinnedModelRequest.isp : ℝ) * (pinnedModelRequest.g0 : ℝ)))
      (divUnchecked bits (neg thrustIv) (ispG0Iv bits)) := by
    exact div_sound (neg_sound ht) hispG0
      (Or.inl (lower_pos_of_lo_pos hd.ispG0Lo))
  intro i
  fin_cases i
  · simpa [burnField, burnFieldIvCore] using hs 2
  · simpa [burnField, burnFieldIvCore] using hs 3
  · simpa [burnField, burnFieldIvCore, radiusIv, speedIv, gravityDenomIv,
      muIv, thrustScaleIv] using hax
  · simpa [burnField, burnFieldIvCore, radiusIv, speedIv, gravityDenomIv,
      muIv, thrustScaleIv] using hay
  · simpa [burnField, burnFieldIvCore, ispG0Iv] using hdm

def tubeSet (bits : Nat) (box : Box) : Set State :=
  Set.univ.pi fun i => Set.Icc (lower bits (box i)) (upper bits (box i))

theorem tubeSet_convex (bits : Nat) (box : Box) : Convex ℝ (tubeSet bits box) := by
  exact convex_pi fun _ _ => convex_Icc _ _

theorem mem_tubeSet_iff {bits : Nat} {box : Box} {state : State} :
    state ∈ tubeSet bits box ↔ ∀ i, Mem bits (state i) (box i) := by
  constructor
  · intro h i
    exact h i (Set.mem_univ i)
  · intro h
    exact fun i _ => h i

theorem domain_positive_on_tube {bits : Nat} {box : Box}
    (hd : FieldDomain bits box) {state : State} (hs : state ∈ tubeSet bits box) :
    0 < radiusSq state ∧ 0 < speedSq state ∧ 0 < state 4 := by
  rw [mem_tubeSet_iff] at hs
  have hr2 : Mem bits (radiusSq state) (radiusSqIv bits box) := by
    simpa [radiusSq, radiusSqIv] using
      add_sound (square_sound (hs 0)) (square_sound (hs 1))
  have hv2 : Mem bits (speedSq state) (speedSqIv bits box) := by
    simpa [speedSq, speedSqIv] using
      add_sound (square_sound (hs 2)) (square_sound (hs 3))
  exact ⟨(lower_pos_of_lo_pos hd.radiusSqLo).trans_le hr2.1,
    (lower_pos_of_lo_pos hd.speedSqLo).trans_le hv2.1,
    (lower_pos_of_lo_pos hd.massLo).trans_le (hs 4).1⟩

theorem burnField_contDiffAt (thrust : ℝ) (state : State)
    (hr : 0 < radiusSq state) (hv : 0 < speedSq state) (hm : 0 < state 4) :
    ContDiffAt ℝ 1 (burnField thrust) state := by
  have hr2 : ContDiffAt ℝ 1 radiusSq state := by
    unfold radiusSq
    fun_prop
  have hv2 : ContDiffAt ℝ 1 speedSq state := by
    unfold speedSq
    fun_prop
  have hrs : ContDiffAt ℝ 1 (fun s => Real.sqrt (radiusSq s)) state :=
    hr2.sqrt hr.ne'
  have hvs : ContDiffAt ℝ 1 (fun s => Real.sqrt (speedSq s)) state :=
    hv2.sqrt hv.ne'
  have hrsne : Real.sqrt (radiusSq state) ≠ 0 := (Real.sqrt_pos.2 hr).ne'
  have hvsne : Real.sqrt (speedSq state) ≠ 0 := (Real.sqrt_pos.2 hv).ne'
  have hrdne : radiusSq state * Real.sqrt (radiusSq state) ≠ 0 :=
    mul_ne_zero hr.ne' hrsne
  rw [contDiffAt_pi]
  intro i
  fin_cases i <;> simp [burnField, radiusSq, speedSq] <;>
    fun_prop (disch := aesop)

theorem burnField_contDiffOn (thrust : ℝ) (bits : Nat) (box : Box)
    (hr : ∀ state ∈ tubeSet bits box, 0 < radiusSq state)
    (hv : ∀ state ∈ tubeSet bits box, 0 < speedSq state)
    (hm : ∀ state ∈ tubeSet bits box, 0 < state 4) :
    ContDiffOn ℝ 1 (burnField thrust) (tubeSet bits box) := by
  intro state hs
  exact (burnField_contDiffAt thrust state (hr state hs) (hv state hs) (hm state hs)).contDiffWithinAt

theorem burnField_locallyLipschitzOn (thrust : ℝ) (bits : Nat) (box : Box)
    (hr : ∀ state ∈ tubeSet bits box, 0 < radiusSq state)
    (hv : ∀ state ∈ tubeSet bits box, 0 < speedSq state)
    (hm : ∀ state ∈ tubeSet bits box, 0 < state 4) :
    LocallyLipschitzOn (tubeSet bits box) (burnField thrust) :=
  (burnField_contDiffOn thrust bits box hr hv hm).locallyLipschitzOn
    (tubeSet_convex bits box)

theorem burnField_contDiffOn_of_domain (thrust : ℝ) {bits : Nat} {box : Box}
    (hd : FieldDomain bits box) :
    ContDiffOn ℝ 1 (burnField thrust) (tubeSet bits box) := by
  apply burnField_contDiffOn thrust bits box
  · intro state hs
    exact (domain_positive_on_tube hd hs).1
  · intro state hs
    exact (domain_positive_on_tube hd hs).2.1
  · intro state hs
    exact (domain_positive_on_tube hd hs).2.2

theorem burnField_locallyLipschitzOn_of_domain (thrust : ℝ)
    {bits : Nat} {box : Box} (hd : FieldDomain bits box) :
    LocallyLipschitzOn (tubeSet bits box) (burnField thrust) :=
  (burnField_contDiffOn_of_domain thrust hd).locallyLipschitzOn
    (tubeSet_convex bits box)

end JackalIv.Spacecraft
