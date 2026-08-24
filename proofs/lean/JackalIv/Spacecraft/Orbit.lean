/- Exact cutoff coverage and orbital post-processing for finite-burn certificates. -/
import JackalIv.Spacecraft.Picard

namespace JackalIv.Spacecraft

def partitionIv (bits : Nat) (lo hi : ℚ) (count index : Nat) : DInterval :=
  let width := (hi - lo) / count
  ⟨(pointRat bits (lo + index * width)).lo,
   (pointRat bits (lo + (index + 1) * width)).hi⟩

def expectedInitialBox (bits branch : Nat) : Box := ![
  partitionIv bits (66779995 / 10000) (66800005 / 10000) 4 ((branch / 8) % 4),
  partitionIv bits (-5 / 10000) (5 / 10000) 1 0,
  partitionIv bits (-2 / 100000) (2 / 100000) 1 0,
  partitionIv bits (77258 / 10000) (77262 / 10000) 2 ((branch / 4) % 2),
  partitionIv bits (11985 / 10) (12015 / 10) 2 ((branch / 2) % 2)]

def expectedThrust (bits branch : Nat) : DInterval :=
  partitionIv bits 1995 2005 2 (branch % 2)

def stepsCovered (branch expected : Nat) : List StepWitness → Bool
  | [] => true
  | step :: tail =>
      step.branch == branch && step.step == expected &&
        stepsCovered branch (expected + 1) tail

def branchesCovered (bits expected stepsPerBranch : Nat) :
    List BranchWitness → Bool
  | [] => true
  | branch :: tail =>
      branch.branch == expected &&
      branch.initial == expectedInitialBox bits expected &&
      branch.thrust == expectedThrust bits expected &&
      branch.steps.length == stepsPerBranch &&
      stepsCovered expected 0 branch.steps &&
      branchesCovered bits (expected + 1) stepsPerBranch tail

def ExactCutoffCoverage (witness : BurnWitness) : Prop :=
  witness.scaleBits = 80 ∧
  witness.stepNum = 1 ∧ witness.stepDen = 32 ∧
  witness.partitionCounts = [4, 1, 1, 2, 2, 2] ∧
  witness.stepsPerBranch = 3888 ∧
  witness.firstCutoffStep = 3792 ∧
  witness.declaredBranches = 32 ∧
  witness.declaredTubes = 124416 ∧
  witness.declaredCutoffCells = 3072 ∧
  witness.branches.length = 32 ∧
  branchesCovered witness.scaleBits 0 witness.stepsPerBranch witness.branches = true

instance (witness : BurnWitness) : Decidable (ExactCutoffCoverage witness) :=
  inferInstanceAs (Decidable (
    witness.scaleBits = 80 ∧
    witness.stepNum = 1 ∧ witness.stepDen = 32 ∧
    witness.partitionCounts = [4, 1, 1, 2, 2, 2] ∧
    witness.stepsPerBranch = 3888 ∧
    witness.firstCutoffStep = 3792 ∧
    witness.declaredBranches = 32 ∧
    witness.declaredTubes = 124416 ∧
    witness.declaredCutoffCells = 3072 ∧
    witness.branches.length = 32 ∧
    branchesCovered witness.scaleBits 0 witness.stepsPerBranch witness.branches = true))

def checkCutoffCoverage (witness : BurnWitness) : Except String Unit :=
  if ExactCutoffCoverage witness then .ok () else .error "cutoff-coverage"

theorem checkCutoffCoverage_sound {witness : BurnWitness}
    (hcheck : checkCutoffCoverage witness = .ok ()) :
    ExactCutoffCoverage witness := by
  simp only [checkCutoffCoverage] at hcheck
  split at hcheck
  · assumption
  · contradiction

structure OrbitIntervals where
  radius : DInterval
  speedSquared : DInterval
  energy : DInterval
  semimajorAxis : DInterval
  angularMomentum : DInterval
  eccentricitySquared : DInterval
  eccentricity : DInterval
  eccentricityVectorSquared : DInterval
  eccentricityVector : DInterval
  eccentricityIntersection : DInterval
  apoapsis : DInterval
  altitude : DInterval
  margin : DInterval
  deriving DecidableEq, Repr

def oneIv (bits : Nat) : DInterval := pointRat bits 1
def twoIv (bits : Nat) : DInterval := pointRat bits 2
def thousandIv (bits : Nat) : DInterval := pointRat bits 1000
def earthRadiusIv (bits : Nat) : DInterval := pointRat bits (63781363 / 10000)

def orbitPostprocess (bits : Nat) (box : Box) : Except String OrbitIntervals := do
  let r2 := radiusSqIv bits box
  let radius ← sqrt bits r2
  let v2 := speedSqIv bits box
  let halfSpeed ← div bits v2 (twoIv bits)
  let potential ← div bits (muIv bits) radius
  let energy := sub halfSpeed potential
  if 0 ≤ energy.hi then throw "orbit-nonelliptic"
  let twoEnergy := mul bits (twoIv bits) energy
  let axis ← div bits (neg (muIv bits)) twoEnergy
  let angular := sub (mul bits (box 0) (box 3)) (mul bits (box 1) (box 2))
  let muSquared := square bits (muIv bits)
  let eccentricitySquared := add (oneIv bits)
    (← div bits (mul bits twoEnergy (square bits angular)) muSquared)
  if eccentricitySquared.lo < 0 then throw "eccentricity-radicand"
  let eccentricity ← sqrt bits eccentricitySquared
  let radialProduct := add (mul bits (box 0) (box 2)) (mul bits (box 1) (box 3))
  let common := sub v2 potential
  let eccentricityX ← div bits
    (sub (mul bits common (box 0)) (mul bits radialProduct (box 2))) (muIv bits)
  let eccentricityY ← div bits
    (sub (mul bits common (box 1)) (mul bits radialProduct (box 3))) (muIv bits)
  let eccentricityVectorSquared := add
    (square bits eccentricityX) (square bits eccentricityY)
  let eccentricityVector ← sqrt bits eccentricityVectorSquared
  let eccentricityIntersection ← match intersection eccentricity eccentricityVector with
    | some value => pure value
    | none => throw "eccentricity-intersection"
  /- The vector route drives the safety margin; the independent scalar route
  and nonempty intersection remain mandatory consistency checks. -/
  let apoapsis := mul bits axis (add (oneIv bits) eccentricityVector)
  let altitude := sub apoapsis (earthRadiusIv bits)
  let margin := sub altitude (thousandIv bits)
  pure ⟨radius, v2, energy, axis, angular, eccentricitySquared, eccentricity,
    eccentricityVectorSquared, eccentricityVector, eccentricityIntersection,
    apoapsis, altitude, margin⟩

noncomputable def orbitalEnergy (state : State) : ℝ :=
  speedSq state / 2 - (pinnedModelRequest.mu : ℝ) / Real.sqrt (radiusSq state)

noncomputable def orbitalAngularMomentum (state : State) : ℝ :=
  state 0 * state 3 - state 1 * state 2

noncomputable def orbitalEccentricityFormula (state : State) : ℝ :=
  Real.sqrt (1 + 2 * orbitalEnergy state * orbitalAngularMomentum state ^ 2 /
    (pinnedModelRequest.mu : ℝ) ^ 2)

noncomputable def orbitalRadialProduct (state : State) : ℝ :=
  state 0 * state 2 + state 1 * state 3

noncomputable def orbitalEccentricityX (state : State) : ℝ :=
  let common := speedSq state - (pinnedModelRequest.mu : ℝ) /
    Real.sqrt (radiusSq state)
  (common * state 0 - orbitalRadialProduct state * state 2) /
    (pinnedModelRequest.mu : ℝ)

noncomputable def orbitalEccentricityY (state : State) : ℝ :=
  let common := speedSq state - (pinnedModelRequest.mu : ℝ) /
    Real.sqrt (radiusSq state)
  (common * state 1 - orbitalRadialProduct state * state 3) /
    (pinnedModelRequest.mu : ℝ)

noncomputable def orbitalEccentricity (state : State) : ℝ :=
  Real.sqrt (orbitalEccentricityX state ^ 2 + orbitalEccentricityY state ^ 2)

noncomputable def apoapsisRadius (state : State) : ℝ :=
  (-(pinnedModelRequest.mu : ℝ) / (2 * orbitalEnergy state)) *
    (1 + orbitalEccentricity state)

noncomputable def apoapsisMargin (state : State) : ℝ :=
  apoapsisRadius state - (63781363 / 10000 : ℝ) - 1000

theorem sqrt_ok_data {bits : Nat} {a out : DInterval}
    (h : sqrt bits a = .ok out) :
    0 ≤ a.lo ∧ out = sqrtUnchecked bits a := by
  simp only [sqrt] at h
  split at h
  · contradiction
  · rename_i hn
    cases h
    exact ⟨le_of_not_gt hn, rfl⟩

theorem div_ok_data {bits : Nat} {a b out : DInterval}
    (h : div bits a b = .ok out) :
    (0 < lower bits b ∨ upper bits b < 0) ∧ out = divUnchecked bits a b := by
  simp only [div] at h
  split at h
  · contradiction
  · rename_i hn
    cases h
    have hz : b.hi < 0 ∨ 0 < b.lo := by
      by_cases hlo : b.lo ≤ 0
      · exact Or.inl (lt_of_not_ge fun hhi => hn ⟨hlo, hhi⟩)
      · exact Or.inr (lt_of_not_ge hlo)
    constructor
    · rcases hz with hneg | hpos
      · exact Or.inr (by
          apply div_neg_of_neg_of_pos
          · exact_mod_cast hneg
          · exact scale_real_pos bits)
      · exact Or.inl (lower_pos_of_lo_pos hpos)
    · rfl

theorem except_bind_ok {α β : Type} {result : Except String α}
    {next : α → Except String β} {value : β}
    (h : (result >>= next) = .ok value) :
    ∃ item, result = .ok item ∧ next item = .ok value := by
  cases result with
  | error error => contradiction
  | ok item => exact ⟨item, rfl, h⟩

theorem orbitPostprocess_sound {bits : Nat} {box : Box}
    {out : OrbitIntervals} {state : State}
    (hcheck : orbitPostprocess bits box = .ok out)
    (hs : ∀ i, Mem bits (state i) (box i)) :
    Mem bits (apoapsisMargin state) out.margin ∧
    Mem bits (orbitalEccentricityFormula state) out.eccentricity ∧
    Mem bits (orbitalEccentricity state) out.eccentricityVector := by
  simp only [orbitPostprocess] at hcheck
  obtain ⟨radius, hradius, hafterRadius⟩ := except_bind_ok hcheck
  obtain ⟨halfSpeed, hhalf, hafterHalf⟩ := except_bind_ok hafterRadius
  obtain ⟨potential, hpotential, hafterPotential⟩ := except_bind_ok hafterHalf
  let energy := sub halfSpeed potential
  by_cases helliptic : 0 ≤ energy.hi
  · have hbad : 0 ≤ (sub halfSpeed potential).hi := by simpa [energy] using helliptic
    simp only [hbad, if_true] at hafterPotential
    change Except.error "orbit-nonelliptic" = .ok out at hafterPotential
    contradiction
  · have hgood : ¬0 ≤ (sub halfSpeed potential).hi := by simpa [energy] using helliptic
    simp only [hgood, if_false] at hafterPotential
    let twoEnergy := mul bits (twoIv bits) energy
    obtain ⟨axis, haxis, hafterAxis⟩ := except_bind_ok hafterPotential
    let angular := sub (mul bits (box 0) (box 3))
      (mul bits (box 1) (box 2))
    let muSquared := square bits (muIv bits)
    obtain ⟨eccTerm, heccTerm, hafterEccTerm⟩ := except_bind_ok hafterAxis
    let eccentricitySquared := add (oneIv bits) eccTerm
    by_cases heradicand : eccentricitySquared.lo < 0
    · have hbad : (add (oneIv bits) eccTerm).lo < 0 := by
        simpa [eccentricitySquared] using heradicand
      simp only [hbad, if_true] at hafterEccTerm
      change Except.error "eccentricity-radicand" = .ok out at hafterEccTerm
      contradiction
    · have hgood : ¬(add (oneIv bits) eccTerm).lo < 0 := by
        simpa [eccentricitySquared] using heradicand
      simp only [hgood, if_false] at hafterEccTerm
      obtain ⟨eccentricity, hecc, hafterEcc⟩ := except_bind_ok hafterEccTerm
      let radialProduct := add (mul bits (box 0) (box 2))
        (mul bits (box 1) (box 3))
      let common := sub (speedSqIv bits box) potential
      obtain ⟨eccentricityX, hex, hafterEx⟩ := except_bind_ok hafterEcc
      obtain ⟨eccentricityY, hey, hafterEy⟩ := except_bind_ok hafterEx
      let eccentricityVectorSquared := add
        (square bits eccentricityX) (square bits eccentricityY)
      obtain ⟨eccentricityVector, hev, hafterEv⟩ := except_bind_ok hafterEy
      generalize hinter : intersection eccentricity eccentricityVector = intResult at hafterEv
      cases intResult with
      | none => contradiction
      | some eccentricityIntersection =>
        cases hafterEv
        have hr2 : Mem bits (radiusSq state) (radiusSqIv bits box) := by
          simpa [radiusSq, radiusSqIv] using
            add_sound (square_sound (hs 0)) (square_sound (hs 1))
        have hrdata := sqrt_ok_data hradius
        have hradiusMem : Mem bits (Real.sqrt (radiusSq state)) radius := by
          rw [hrdata.2]
          exact sqrt_sound hrdata.1 (by simp [radiusSq]; positivity) hr2
        have hv2 : Mem bits (speedSq state) (speedSqIv bits box) := by
          simpa [speedSq, speedSqIv] using
            add_sound (square_sound (hs 2)) (square_sound (hs 3))
        have htwo := pointRat_sound bits (2 : ℚ)
        have hhalfData := div_ok_data hhalf
        have hhalfMem : Mem bits (speedSq state / 2) halfSpeed := by
          rw [hhalfData.2]
          exact div_sound hv2 htwo hhalfData.1
        have hmu := pointRat_sound bits pinnedModelRequest.mu
        have hpotentialData := div_ok_data hpotential
        have hpotentialMem : Mem bits
            ((pinnedModelRequest.mu : ℝ) / Real.sqrt (radiusSq state))
            potential := by
          rw [hpotentialData.2]
          exact div_sound hmu hradiusMem hpotentialData.1
        have henergyMem : Mem bits (orbitalEnergy state) energy := by
          simpa [orbitalEnergy, energy] using
            sub_sound hhalfMem hpotentialMem
        have htwoEnergyMem : Mem bits (2 * orbitalEnergy state) twoEnergy := by
          simpa [twoEnergy, twoIv] using mul_sound htwo henergyMem
        have haxisData := div_ok_data haxis
        have haxisMem : Mem bits
            (-(pinnedModelRequest.mu : ℝ) / (2 * orbitalEnergy state)) axis := by
          rw [haxisData.2]
          exact div_sound (neg_sound hmu) htwoEnergyMem haxisData.1
        have hradialMem : Mem bits (orbitalRadialProduct state) radialProduct := by
          simpa [orbitalRadialProduct, radialProduct] using
            add_sound (mul_sound (hs 0) (hs 2))
              (mul_sound (hs 1) (hs 3))
        have hcommonMem : Mem bits
            (speedSq state - (pinnedModelRequest.mu : ℝ) /
              Real.sqrt (radiusSq state)) common := by
          simpa [common] using sub_sound hv2 hpotentialMem
        have hexData := div_ok_data hex
        have hexMem : Mem bits (orbitalEccentricityX state)
            eccentricityX := by
          rw [hexData.2]
          simpa [orbitalEccentricityX, common, radialProduct, muIv] using div_sound
            (sub_sound (mul_sound hcommonMem (hs 0))
            (mul_sound hradialMem (hs 2))) hmu (by simpa [muIv] using hexData.1)
        have heyData := div_ok_data hey
        have heyMem : Mem bits (orbitalEccentricityY state)
            eccentricityY := by
          rw [heyData.2]
          simpa [orbitalEccentricityY, common, radialProduct, muIv] using div_sound
            (sub_sound (mul_sound hcommonMem (hs 1))
            (mul_sound hradialMem (hs 3))) hmu (by simpa [muIv] using heyData.1)
        have hevSqMem : Mem bits
            (orbitalEccentricityX state ^ 2 +
              orbitalEccentricityY state ^ 2)
            eccentricityVectorSquared := by
          simpa [eccentricityVectorSquared] using
            add_sound (square_sound hexMem) (square_sound heyMem)
        have hevData := sqrt_ok_data hev
        have hevMem : Mem bits (orbitalEccentricity state)
            eccentricityVector := by
          rw [hevData.2]
          simpa [orbitalEccentricity, sqrtUnchecked] using sqrt_sound hevData.1
            (by positivity) hevSqMem
        have hapoMem : Mem bits (apoapsisRadius state)
            (mul bits axis (add (oneIv bits) eccentricityVector)) := by
          simpa [apoapsisRadius, oneIv] using mul_sound haxisMem
            (add_sound (pointRat_sound bits (1 : ℚ)) hevMem)
        have haltitudeMem : Mem bits
            (apoapsisRadius state - (63781363 / 10000 : ℝ))
            (sub (mul bits axis (add (oneIv bits) eccentricityVector))
              (earthRadiusIv bits)) := by
          exact sub_sound hapoMem (by
            simpa [earthRadiusIv] using
              pointRat_sound bits (63781363 / 10000 : ℚ))
        have hmarginMem : Mem bits (apoapsisMargin state)
            (sub (sub (mul bits axis (add (oneIv bits) eccentricityVector))
              (earthRadiusIv bits)) (thousandIv bits)) := by
          simpa [apoapsisMargin, earthRadiusIv, thousandIv] using
            sub_sound haltitudeMem (pointRat_sound bits (1000 : ℚ))
        have hangularMem : Mem bits (orbitalAngularMomentum state) angular := by
          simpa [orbitalAngularMomentum, angular] using
            sub_sound (mul_sound (hs 0) (hs 3)) (mul_sound (hs 1) (hs 2))
        have hmuSquaredMem : Mem bits ((pinnedModelRequest.mu : ℝ) ^ 2)
            muSquared := by
          simpa [muSquared, muIv] using square_sound hmu
        have heccNumeratorMem : Mem bits
            ((2 * orbitalEnergy state) * orbitalAngularMomentum state ^ 2)
            (mul bits twoEnergy (square bits angular)) :=
          mul_sound htwoEnergyMem (square_sound hangularMem)
        have heccTermData := div_ok_data heccTerm
        have heccTermMem : Mem bits
            ((2 * orbitalEnergy state) * orbitalAngularMomentum state ^ 2 /
              (pinnedModelRequest.mu : ℝ) ^ 2) eccTerm := by
          rw [heccTermData.2]
          exact div_sound heccNumeratorMem hmuSquaredMem heccTermData.1
        have heccSquaredMem : Mem bits
            (1 + (2 * orbitalEnergy state) * orbitalAngularMomentum state ^ 2 /
              (pinnedModelRequest.mu : ℝ) ^ 2) eccentricitySquared := by
          simpa [eccentricitySquared, oneIv] using
            add_sound (pointRat_sound bits (1 : ℚ)) heccTermMem
        have heccData := sqrt_ok_data hecc
        have heccNonneg : 0 ≤
            1 + (2 * orbitalEnergy state) * orbitalAngularMomentum state ^ 2 /
              (pinnedModelRequest.mu : ℝ) ^ 2 :=
          (show 0 ≤ lower bits eccentricitySquared by
            exact div_nonneg (by exact_mod_cast heccData.1)
              (scale_real_pos bits).le).trans heccSquaredMem.1
        have heccMem : Mem bits (orbitalEccentricityFormula state) eccentricity := by
          rw [heccData.2]
          simpa [orbitalEccentricityFormula, sqrtUnchecked] using
            sqrt_sound heccData.1 heccNonneg heccSquaredMem
        exact ⟨hmarginMem, heccMem, hevMem⟩

theorem orbitPostprocess_margin_sound {bits : Nat} {box : Box}
    {out : OrbitIntervals} {state : State}
    (hcheck : orbitPostprocess bits box = .ok out)
    (hs : ∀ i, Mem bits (state i) (box i)) :
    Mem bits (apoapsisMargin state) out.margin :=
  (orbitPostprocess_sound hcheck hs).1

theorem orbit_margin_positive_implies_safe {bits : Nat} {box : Box}
    {out : OrbitIntervals} {state : State}
    (hcheck : orbitPostprocess bits box = .ok out)
    (hpositive : 0 < out.margin.lo)
    (hs : ∀ i, Mem bits (state i) (box i)) :
    apoapsisRadius state - (63781363 / 10000 : ℝ) ≥ 1000 := by
  have hmargin := orbitPostprocess_margin_sound hcheck hs
  have hlower : 0 < lower bits out.margin := lower_pos_of_lo_pos hpositive
  have : 0 < apoapsisMargin state := hlower.trans_le hmargin.1
  simp only [apoapsisMargin] at this
  linarith

theorem angular_momentum_lagrange_identity (x y vx vy : ℝ) :
    (vx ^ 2 + vy ^ 2) * (x ^ 2 + y ^ 2) - (x * vx + y * vy) ^ 2 =
      (x * vy - y * vx) ^ 2 := by ring

theorem energy_definition_substitution (energy speedSq potential : ℝ)
    (henergy : energy = speedSq / 2 - potential) :
    2 * energy = speedSq - 2 * potential := by rw [henergy]; ring

theorem apoapsis_plus_expansion (axis eccentricity : ℝ) :
    axis * (1 + eccentricity) = axis + axis * eccentricity := by ring

theorem eccentricity_vector_reduction (velocity q radiusSq radialSq hSq : ℝ)
    (hlagrange : velocity * radiusSq - radialSq = hSq) :
    (velocity - q) ^ 2 * radiusSq + (2 * q - velocity) * radialSq =
      q ^ 2 * radiusSq + (velocity - 2 * q) * hSq := by
  rw [← hlagrange]
  ring

end JackalIv.Spacecraft
