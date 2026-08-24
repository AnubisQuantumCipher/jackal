/- Kernel-checked meaning of an accepted spacecraft burn certificate. -/
import JackalIv.Spacecraft.CertCheck

namespace JackalIv.Spacecraft

def TubeOrbitSafe (bits : Nat) (tube : Box) : Prop :=
  ∀ state, (∀ i, Mem bits (state i) (tube i)) → 0 < apoapsisMargin state

def CutoffTubesSafe (bits first expected : Nat) : List StepWitness → Prop
  | [] => True
  | step :: tail =>
      (if expected < first then True else TubeOrbitSafe bits step.tube) ∧
      CutoffTubesSafe bits first (expected + 1) tail

def BranchModelSafe (bits : Nat) (h : ℚ) (first : Nat)
    (branch : BranchWitness) : Prop :=
  ∀ initialState thrust,
    (∀ i, Mem bits (initialState i) (branch.initial i)) →
    Mem bits thrust branch.thrust →
    (∃ terminalState,
      ClassicalSolutionChain h thrust initialState branch.steps terminalState) ∧
    (∀ terminalState,
      ClassicalSolutionChain h thrust initialState branch.steps terminalState →
      ∃ _ : EnclosedSolutionChain bits h thrust initialState
          branch.steps terminalState,
        CutoffTubesSafe bits first 0 branch.steps)

def ModelConditionalSafe (request : CertifiedBurnRequest)
    (margin : DInterval) : Prop :=
  request.model = pinnedModelRequest ∧
  request.requestDigest = spacecraftRequestDigest ∧
  request.modelId = spacecraftModelId ∧
  request.epoch = spacecraftReleaseEpoch ∧
  ExactCutoffCoverage request.witness ∧
  0 < margin.lo ∧
  ∀ branch ∈ request.witness.branches,
    BranchModelSafe request.witness.scaleBits
      (request.witness.stepNum / request.witness.stepDen)
      request.witness.firstCutoffStep branch

theorem orbit_margin_lo_positive_safe {bits : Nat} {tube : Box}
    {orbit : OrbitIntervals}
    (hcheck : orbitPostprocess bits tube = .ok orbit)
    (hpositive : 0 < orbit.margin.lo) :
    TubeOrbitSafe bits tube := by
  intro state hstate
  have hmem := orbitPostprocess_margin_sound hcheck hstate
  have hlower : 0 < lower bits orbit.margin := by
    apply div_pos
    · exact_mod_cast hpositive
    · exact scale_real_pos bits
  exact hlower.trans_le hmem.1

theorem checkOrbitSteps_sound {bits first expected : Nat}
    {steps : List StepWitness} {margin : Option DInterval}
    (hcheck : checkOrbitSteps bits first expected steps = .ok margin) :
    CutoffTubesSafe bits first expected steps ∧
      ∀ value, margin = some value → 0 < value.lo := by
  induction steps generalizing expected margin with
  | nil =>
      change Except.ok none = Except.ok margin at hcheck
      cases hcheck
      simp [CutoffTubesSafe]
  | cons step tail ih =>
      simp only [checkOrbitSteps] at hcheck
      generalize htail : checkOrbitSteps bits first (expected + 1) tail = result at hcheck
      cases result with
      | error error => contradiction
      | ok rest =>
        have ihs := ih htail
        by_cases hpre : expected < first
        · change (if expected < first then Except.ok rest else do
              let orbit ← orbitPostprocess bits step.tube
              if 0 < orbit.margin.lo then
                pure (mergeMargin rest orbit.margin)
              else throw "nonpositive-margin") = .ok margin at hcheck
          rw [if_pos hpre] at hcheck
          cases hcheck
          exact ⟨by simp [CutoffTubesSafe, hpre, ihs.1], ihs.2⟩
        · change (if expected < first then Except.ok rest else do
              let orbit ← orbitPostprocess bits step.tube
              if 0 < orbit.margin.lo then
                pure (mergeMargin rest orbit.margin)
              else throw "nonpositive-margin") = .ok margin at hcheck
          rw [if_neg hpre] at hcheck
          generalize horbit : orbitPostprocess bits step.tube = orbitResult at hcheck
          cases orbitResult with
          | error error => contradiction
          | ok orbit =>
            by_cases hp : 0 < orbit.margin.lo
            · change (if 0 < orbit.margin.lo then
                  Except.ok (mergeMargin rest orbit.margin)
                else Except.error "nonpositive-margin") = .ok margin at hcheck
              rw [if_pos hp] at hcheck
              cases hcheck
              constructor
              · exact ⟨by simpa [hpre] using
                    orbit_margin_lo_positive_safe horbit hp, ihs.1⟩
              · intro value hvalue
                cases rest with
                | none =>
                  simp only [mergeMargin, Option.some.injEq] at hvalue
                  subst value
                  exact hp
                | some restMargin =>
                  simp only [mergeMargin, Option.some.injEq] at hvalue
                  subst value
                  have hr := ihs.2 restMargin rfl
                  simpa [hull] using lt_min hr hp
            · change (if 0 < orbit.margin.lo then
                  Except.ok (mergeMargin rest orbit.margin)
                else Except.error "nonpositive-margin") = .ok margin at hcheck
              rw [if_neg hp] at hcheck
              contradiction

theorem checkBranchCert_sound {bits first : Nat} {h : ℚ}
    {branch : BranchWitness} {margin : Option DInterval}
    (hcheck : checkBranchCert bits h first branch = .ok margin) :
    BranchModelSafe bits h first branch ∧
      ∀ value, margin = some value → 0 < value.lo := by
  simp only [checkBranchCert] at hcheck
  generalize hsteps : checkBranchSteps bits h branch.branch branch.thrust
    branch.initial 0 branch.steps = stepResult at hcheck
  cases stepResult with
  | error error => contradiction
  | ok final =>
    have horbit := checkOrbitSteps_sound hcheck
    constructor
    · intro initialState thrust hi ht
      constructor
      · obtain ⟨terminal, chain, _⟩ := checked_steps_nonvacuous hsteps hi ht
        exact ⟨terminal, chain⟩
      · intro terminal chain
        have enclosed := (checked_steps_compose hsteps hi ht chain).1
        exact ⟨enclosed, horbit.1⟩
    · exact horbit.2

theorem checkBranchesCert_sound {bits first : Nat} {h : ℚ}
    {branches : List BranchWitness} {margin : Option DInterval}
    (hcheck : checkBranchesCert bits h first branches = .ok margin) :
    (∀ branch ∈ branches, BranchModelSafe bits h first branch) ∧
      ∀ value, margin = some value → 0 < value.lo := by
  induction branches generalizing margin with
  | nil =>
      change Except.ok none = Except.ok margin at hcheck
      cases hcheck
      simp
  | cons branch tail ih =>
      simp only [checkBranchesCert] at hcheck
      generalize hb : checkBranchCert bits h first branch = branchResult at hcheck
      cases branchResult with
      | error error => contradiction
      | ok branchMargin =>
        generalize ht : checkBranchesCert bits h first tail = tailResult at hcheck
        cases tailResult with
        | error error => contradiction
        | ok tailMargin =>
          have hbs := checkBranchCert_sound hb
          have hts := ih ht
          constructor
          · intro candidate hmem
            simp only [List.mem_cons] at hmem
            rcases hmem with heq | htailmem
            · rw [heq]
              exact hbs.1
            · exact hts.1 candidate htailmem
          · intro value hvalue
            cases branchMargin with
            | none =>
              cases tailMargin with
              | none =>
                change Except.ok none = Except.ok margin at hcheck
                cases hcheck
                contradiction
              | some right =>
                change Except.ok (some right) = Except.ok margin at hcheck
                cases hcheck
                exact hts.2 value hvalue
            | some left =>
              cases tailMargin with
              | none =>
                change Except.ok (some left) = Except.ok margin at hcheck
                cases hcheck
                exact hbs.2 value hvalue
              | some right =>
                change Except.ok (some (hull left right)) =
                  Except.ok margin at hcheck
                cases hcheck
                simp only [Option.some.injEq] at hvalue
                subst value
                have hl := hbs.2 left rfl
                have hr := hts.2 right rfl
                simpa [hull] using lt_min hl hr

theorem checkBurnWitness_sound {witness : BurnWitness} {margin : DInterval}
    (hcheck : checkBurnWitness witness = .ok margin) :
    ExactCutoffCoverage witness ∧ 0 < margin.lo ∧
      ∀ branch ∈ witness.branches,
        BranchModelSafe witness.scaleBits
          (witness.stepNum / witness.stepDen)
          witness.firstCutoffStep branch := by
  simp only [checkBurnWitness] at hcheck
  generalize hcoverage : checkCutoffCoverage witness = coverageResult at hcheck
  cases coverageResult with
  | error error => contradiction
  | ok checkedUnit =>
    cases checkedUnit
    generalize hbranches : checkBranchesCert witness.scaleBits
      (witness.stepNum / witness.stepDen) witness.firstCutoffStep
      witness.branches = branchResult at hcheck
    cases branchResult with
    | error error => contradiction
    | ok result =>
      cases result with
      | none => contradiction
      | some aggregate =>
        by_cases hp : 0 < aggregate.lo
        · change (if 0 < aggregate.lo then Except.ok aggregate
              else Except.error "nonpositive-margin") = .ok margin at hcheck
          rw [if_pos hp] at hcheck
          cases hcheck
          have hbs := checkBranchesCert_sound hbranches
          exact ⟨checkCutoffCoverage_sound hcoverage, hp, hbs.1⟩
        · change (if 0 < aggregate.lo then Except.ok aggregate
              else Except.error "nonpositive-margin") = .ok margin at hcheck
          rw [if_neg hp] at hcheck
          contradiction

theorem spacecraft_burn_certified_safe
    {raw requestDigest modelId epoch : String} {accepted : AcceptedBurnCert}
    (h : checkBurnCert raw requestDigest modelId epoch = .ok accepted) :
    ModelConditionalSafe accepted.request accepted.margin := by
  simp only [checkBurnCert] at h
  by_cases hrequest : requestDigest = spacecraftRequestDigest
  · simp only [hrequest, if_true] at h
    by_cases hmodel : modelId = spacecraftModelId
    · simp only [hmodel, if_true] at h
      by_cases hepoch : epoch = spacecraftReleaseEpoch
      · simp only [hepoch, if_true] at h
        generalize hparse : parseBurnWitness raw = parseResult at h
        cases parseResult with
        | error error => simp at h
        | ok witness =>
          generalize hburn : checkBurnWitness witness = burnResult at h
          cases burnResult with
          | error error => simp [hburn] at h
          | ok margin =>
            simp [hburn] at h
            cases h
            have hs := checkBurnWitness_sound hburn
            exact ⟨rfl, rfl, rfl, rfl,
              hs.1, hs.2.1, hs.2.2⟩
      · simp [hepoch] at h
    · simp [hmodel] at h
  · simp [hrequest] at h

#print axioms orbitPostprocess_sound
#print axioms checked_steps_nonvacuous
#print axioms checked_steps_compose
#print axioms checkBurnWitness_sound
#print axioms spacecraft_burn_certified_safe

end JackalIv.Spacecraft
