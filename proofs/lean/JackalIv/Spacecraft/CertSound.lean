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

def OptionMarginBounds (bits : Nat) (margin : Option DInterval)
    (value : ℝ) : Prop :=
  match margin with
  | none => False
  | some bound => Mem bits value bound

def CutoffTubesMarginBound (bits first expected : Nat)
    (margin : Option DInterval) : List StepWitness → Prop
  | [] => True
  | step :: tail =>
      (if expected < first then True else
        ∀ state, (∀ i, Mem bits (state i) (step.tube i)) →
          OptionMarginBounds bits margin (apoapsisMargin state)) ∧
      CutoffTubesMarginBound bits first (expected + 1) margin tail

theorem optionMarginBounds_hull_left {bits : Nat} {left right : DInterval}
    {value : ℝ}
    (h : OptionMarginBounds bits (some left) value) :
    OptionMarginBounds bits (some (hull left right)) value := by
  exact hull_sound_left h

theorem optionMarginBounds_hull_right {bits : Nat} {left right : DInterval}
    {value : ℝ}
    (h : OptionMarginBounds bits (some right) value) :
    OptionMarginBounds bits (some (hull left right)) value := by
  exact hull_sound_right h

theorem cutoffTubesMarginBound_mono {bits first expected : Nat}
    {source target : Option DInterval} {steps : List StepWitness}
    (hmono : ∀ value, OptionMarginBounds bits source value →
      OptionMarginBounds bits target value)
    (hbound : CutoffTubesMarginBound bits first expected source steps) :
    CutoffTubesMarginBound bits first expected target steps := by
  induction steps generalizing expected with
  | nil => trivial
  | cons step tail ih =>
      simp only [CutoffTubesMarginBound] at hbound ⊢
      constructor
      · by_cases hpre : expected < first
        · simp [hpre]
        · simp only [hpre, if_false] at hbound ⊢
          intro state hstate
          exact hmono _ (hbound.1 state hstate)
      · exact ih hbound.2

inductive ChainStateAt (h : ℚ) (thrust : ℝ) :
    State → List StepWitness → State → Nat → ℝ → State → Prop where
  | head {initial terminal : State} {step : StepWitness}
      {steps : List StepWitness} (trajectory : ℝ → State)
      (solution : IsClassicalSolution h thrust initial trajectory)
      (tail : ClassicalSolutionChain h thrust (trajectory (h : ℝ)) steps terminal)
      {localTime : ℝ} (htime : localTime ∈ Set.Icc (0 : ℝ) (h : ℝ)) :
      ChainStateAt h thrust initial (step :: steps) terminal 0 localTime
        (trajectory localTime)
  | tail {initial terminal : State} {step : StepWitness}
      {steps : List StepWitness} (trajectory : ℝ → State)
      (solution : IsClassicalSolution h thrust initial trajectory)
      (tailChain : ClassicalSolutionChain h thrust
        (trajectory (h : ℝ)) steps terminal)
      {index : Nat} {localTime : ℝ} {state : State}
      (atTail : ChainStateAt h thrust (trajectory (h : ℝ)) steps terminal
        index localTime state) :
      ChainStateAt h thrust initial (step :: steps) terminal
        (index + 1) localTime state

def AbsoluteCutoffStateAt (h : ℚ) (first : Nat) (thrust : ℝ)
    (initial : State) (steps : List StepWitness) (terminal : State)
    (absoluteTime : ℝ) (state : State) : Prop :=
  ∃ index localTime,
    first ≤ index ∧ index < steps.length ∧
    localTime ∈ Set.Icc (0 : ℝ) (h : ℝ) ∧
    absoluteTime = index * (h : ℝ) + localTime ∧
    ChainStateAt h thrust initial steps terminal index localTime state

theorem chain_state_at_exists {h : ℚ} {thrust : ℝ}
    {initial terminal : State} {steps : List StepWitness}
    (chain : ClassicalSolutionChain h thrust initial steps terminal)
    {index : Nat} {localTime : ℝ}
    (hindex : index < steps.length)
    (htime : localTime ∈ Set.Icc (0 : ℝ) (h : ℝ)) :
    ∃ state, ChainStateAt h thrust initial steps terminal index localTime state := by
  induction chain generalizing index with
  | nil state => simp at hindex
  | @cons initial terminal step tail trajectory solution chain ih =>
      cases index with
      | zero => exact ⟨trajectory localTime, .head trajectory solution chain htime⟩
      | succ index =>
          have htailIndex : index < tail.length := by
            simpa using hindex
          obtain ⟨state, hstate⟩ := ih htailIndex
          exact ⟨state, .tail trajectory solution chain hstate⟩

theorem checked_chain_state_safe {bits first expected branch : Nat} {h : ℚ}
    {thrustIv : DInterval} {current final : Box} {steps : List StepWitness}
    {initialState terminalState state : State} {thrust localTime : ℝ}
    {index : Nat}
    (hcheck : checkBranchSteps bits h branch thrustIv current expected steps = .ok final)
    (hcutoff : CutoffTubesSafe bits first expected steps)
    (hi : ∀ i, Mem bits (initialState i) (current i))
    (ht : Mem bits thrust thrustIv)
    (hat : ChainStateAt h thrust initialState steps terminalState index localTime state)
    (hindex : first ≤ expected + index) :
    0 < apoapsisMargin state := by
  induction hat generalizing current expected final with
  | @head initial terminal step tail trajectory solution tailChain localTime htime =>
      simp only [checkBranchSteps] at hcheck
      by_cases horder : step.branch ≠ branch ∨ step.step ≠ expected
      · simp only [if_pos horder] at hcheck
        contradiction
      · simp only [if_neg horder] at hcheck
        generalize hstep : checkStep bits h current step.tube thrustIv = result at hcheck
        cases result with
        | error error => contradiction
        | ok endpoint =>
            have hnotPre : ¬ expected < first := by omega
            simp only [CutoffTubesSafe, hnotPre, if_false] at hcutoff
            have htube := picard_tube_encloses hstep hi ht solution localTime htime
            exact hcutoff.1 (trajectory localTime) (mem_tubeSet_iff.mp htube)
  | @tail initial terminal step tail trajectory solution tailChain
      index localTime state atTail ih =>
      simp only [checkBranchSteps] at hcheck
      by_cases horder : step.branch ≠ branch ∨ step.step ≠ expected
      · simp only [if_pos horder] at hcheck
        contradiction
      · simp only [if_neg horder] at hcheck
        generalize hstep : checkStep bits h current step.tube thrustIv = result at hcheck
        cases result with
        | error error => contradiction
        | ok endpoint =>
            change checkBranchSteps bits h branch thrustIv endpoint
              (expected + 1) tail = .ok final at hcheck
            have hiNext := picard_endpoint_encloses hstep hi ht solution
            have htailCutoff : CutoffTubesSafe bits first (expected + 1) tail :=
              hcutoff.2
            apply ih hcheck htailCutoff hiNext
            omega

theorem checked_chain_state_margin_bound
    {bits first expected branch : Nat} {h : ℚ}
    {thrustIv : DInterval} {current final : Box} {steps : List StepWitness}
    {margin : Option DInterval}
    {initialState terminalState state : State} {thrust localTime : ℝ}
    {index : Nat}
    (hcheck : checkBranchSteps bits h branch thrustIv current expected steps = .ok final)
    (hcutoff : CutoffTubesMarginBound bits first expected margin steps)
    (hi : ∀ i, Mem bits (initialState i) (current i))
    (ht : Mem bits thrust thrustIv)
    (hat : ChainStateAt h thrust initialState steps terminalState index localTime state)
    (hindex : first ≤ expected + index) :
    OptionMarginBounds bits margin (apoapsisMargin state) := by
  induction hat generalizing current expected final with
  | @head initial terminal step tail trajectory solution tailChain localTime htime =>
      simp only [checkBranchSteps] at hcheck
      by_cases horder : step.branch ≠ branch ∨ step.step ≠ expected
      · simp only [if_pos horder] at hcheck
        contradiction
      · simp only [if_neg horder] at hcheck
        generalize hstep : checkStep bits h current step.tube thrustIv = result at hcheck
        cases result with
        | error error => contradiction
        | ok endpoint =>
            have hnotPre : ¬ expected < first := by omega
            simp only [CutoffTubesMarginBound, hnotPre, if_false] at hcutoff
            have htube := picard_tube_encloses hstep hi ht solution localTime htime
            exact hcutoff.1 (trajectory localTime) (mem_tubeSet_iff.mp htube)
  | @tail initial terminal step tail trajectory solution tailChain
      index localTime state atTail ih =>
      simp only [checkBranchSteps] at hcheck
      by_cases horder : step.branch ≠ branch ∨ step.step ≠ expected
      · simp only [if_pos horder] at hcheck
        contradiction
      · simp only [if_neg horder] at hcheck
        generalize hstep : checkStep bits h current step.tube thrustIv = result at hcheck
        cases result with
        | error error => contradiction
        | ok endpoint =>
            change checkBranchSteps bits h branch thrustIv endpoint
              (expected + 1) tail = .ok final at hcheck
            have hiNext := picard_endpoint_encloses hstep hi ht solution
            have htailCutoff : CutoffTubesMarginBound bits first (expected + 1)
                margin tail := hcutoff.2
            apply ih hcheck htailCutoff hiNext
            omega

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

def BranchUniversalSafe (bits : Nat) (h : ℚ) (first : Nat)
    (branch : BranchWitness) : Prop :=
  ∀ initialState thrust,
    (∀ i, Mem bits (initialState i) (branch.initial i)) →
    Mem bits thrust branch.thrust →
    (∃ terminalState,
      ClassicalSolutionChain h thrust initialState branch.steps terminalState) ∧
    ∀ terminalState,
      ClassicalSolutionChain h thrust initialState branch.steps terminalState →
      ∀ index localTime,
        first ≤ index → index < branch.steps.length →
        localTime ∈ Set.Icc (0 : ℝ) (h : ℝ) →
        (∃ state, ChainStateAt h thrust initialState branch.steps terminalState
          index localTime state) ∧
        ∀ state, ChainStateAt h thrust initialState branch.steps terminalState
          index localTime state → 0 < apoapsisMargin state

def BranchMarginBound (bits : Nat) (h : ℚ) (first : Nat)
    (branch : BranchWitness) (margin : Option DInterval) : Prop :=
  ∀ initialState thrust,
    (∀ i, Mem bits (initialState i) (branch.initial i)) →
    Mem bits thrust branch.thrust →
    ∀ terminalState,
      ClassicalSolutionChain h thrust initialState branch.steps terminalState →
      ∀ index localTime,
        first ≤ index → index < branch.steps.length →
        localTime ∈ Set.Icc (0 : ℝ) (h : ℝ) →
        ∀ state, ChainStateAt h thrust initialState branch.steps terminalState
          index localTime state →
          OptionMarginBounds bits margin (apoapsisMargin state)

theorem branchMarginBound_mono {bits first : Nat} {h : ℚ}
    {branch : BranchWitness} {source target : Option DInterval}
    (hmono : ∀ value, OptionMarginBounds bits source value →
      OptionMarginBounds bits target value)
    (hbound : BranchMarginBound bits h first branch source) :
    BranchMarginBound bits h first branch target := by
  intro initialState thrust hi ht terminalState chain index localTime
    hfirst hlength htime state hstate
  exact hmono _ (hbound initialState thrust hi ht terminalState chain index
    localTime hfirst hlength htime state hstate)

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

def UniversalModelSafe (request : CertifiedBurnRequest)
    (margin : DInterval) : Prop :=
  request.model = pinnedModelRequest ∧
  request.requestDigest = spacecraftRequestDigest ∧
  request.modelId = spacecraftModelId ∧
  request.epoch = spacecraftReleaseEpoch ∧
  ExactCutoffCoverage request.witness ∧
  0 < margin.lo ∧
  ∀ initialState thrust,
    SuppliedInitialState initialState → SuppliedThrust thrust →
    ∃ branch ∈ request.witness.branches,
      (∀ i, Mem request.witness.scaleBits (initialState i) (branch.initial i)) ∧
      Mem request.witness.scaleBits thrust branch.thrust ∧
      (∃ terminalState,
        ClassicalSolutionChain
          (request.witness.stepNum / request.witness.stepDen)
          thrust initialState branch.steps terminalState) ∧
      ∀ terminalState,
        ClassicalSolutionChain
          (request.witness.stepNum / request.witness.stepDen)
          thrust initialState branch.steps terminalState →
        ∀ absoluteTime, SuppliedCutoffTime absoluteTime →
          (∃ state, AbsoluteCutoffStateAt
            (request.witness.stepNum / request.witness.stepDen)
            request.witness.firstCutoffStep thrust initialState branch.steps
            terminalState absoluteTime state) ∧
          ∀ state, AbsoluteCutoffStateAt
            (request.witness.stepNum / request.witness.stepDen)
            request.witness.firstCutoffStep thrust initialState branch.steps
            terminalState absoluteTime state →
              Mem request.witness.scaleBits (apoapsisMargin state) margin ∧
              0 < apoapsisMargin state

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

theorem checkOrbitSteps_margin_bound {bits first expected : Nat}
    {steps : List StepWitness} {margin : Option DInterval}
    (hcheck : checkOrbitSteps bits first expected steps = .ok margin) :
    CutoffTubesMarginBound bits first expected margin steps := by
  induction steps generalizing expected margin with
  | nil =>
      change Except.ok none = Except.ok margin at hcheck
      cases hcheck
      trivial
  | cons step tail ih =>
      simp only [checkOrbitSteps] at hcheck
      generalize htail : checkOrbitSteps bits first (expected + 1) tail = result at hcheck
      cases result with
      | error error => contradiction
      | ok rest =>
        have ihb := ih htail
        by_cases hpre : expected < first
        · change (if expected < first then Except.ok rest else do
              let orbit ← orbitPostprocess bits step.tube
              if 0 < orbit.margin.lo then
                pure (mergeMargin rest orbit.margin)
              else throw "nonpositive-margin") = .ok margin at hcheck
          rw [if_pos hpre] at hcheck
          cases hcheck
          exact ⟨by simp [hpre], ihb⟩
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
              · simp only [hpre, if_false]
                intro state hstate
                have hcell : OptionMarginBounds bits (some orbit.margin)
                    (apoapsisMargin state) :=
                  orbitPostprocess_margin_sound horbit hstate
                cases rest with
                | none => exact hcell
                | some restMargin => exact optionMarginBounds_hull_right hcell
              · cases rest with
                | none =>
                    apply cutoffTubesMarginBound_mono _ ihb
                    intro value hvalue
                    exact False.elim hvalue
                | some restMargin =>
                    apply cutoffTubesMarginBound_mono _ ihb
                    intro value hvalue
                    exact optionMarginBounds_hull_left hvalue
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

theorem checkBranchCert_universal_sound {bits first : Nat} {h : ℚ}
    {branch : BranchWitness} {margin : Option DInterval}
    (hcheck : checkBranchCert bits h first branch = .ok margin) :
    BranchUniversalSafe bits h first branch := by
  simp only [checkBranchCert] at hcheck
  generalize hsteps : checkBranchSteps bits h branch.branch branch.thrust
    branch.initial 0 branch.steps = stepResult at hcheck
  cases stepResult with
  | error error => contradiction
  | ok final =>
      have horbit := (checkOrbitSteps_sound hcheck).1
      intro initialState thrust hi ht
      constructor
      · obtain ⟨terminal, chain, _⟩ := checked_steps_nonvacuous hsteps hi ht
        exact ⟨terminal, chain⟩
      · intro terminal chain index localTime hfirst hlength htime
        constructor
        · exact chain_state_at_exists chain hlength htime
        · intro state hat
          exact checked_chain_state_safe hsteps horbit hi ht hat (by simpa using hfirst)

theorem checkBranchCert_margin_bound {bits first : Nat} {h : ℚ}
    {branch : BranchWitness} {margin : Option DInterval}
    (hcheck : checkBranchCert bits h first branch = .ok margin) :
    BranchMarginBound bits h first branch margin := by
  simp only [checkBranchCert] at hcheck
  generalize hsteps : checkBranchSteps bits h branch.branch branch.thrust
    branch.initial 0 branch.steps = stepResult at hcheck
  cases stepResult with
  | error error => contradiction
  | ok final =>
      have horbit := checkOrbitSteps_margin_bound hcheck
      intro initialState thrust hi ht terminalState chain index localTime
        hfirst hlength htime state hat
      exact checked_chain_state_margin_bound hsteps horbit hi ht hat
        (by simpa using hfirst)

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

theorem checkBranchesCert_universal_sound {bits first : Nat} {h : ℚ}
    {branches : List BranchWitness} {margin : Option DInterval}
    (hcheck : checkBranchesCert bits h first branches = .ok margin) :
    ∀ branch ∈ branches, BranchUniversalSafe bits h first branch := by
  induction branches generalizing margin with
  | nil => simp
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
              intro candidate hmem
              simp only [List.mem_cons] at hmem
              rcases hmem with rfl | htail
              · exact checkBranchCert_universal_sound hb
              · exact ih ht candidate htail

theorem checkBranchesCert_margin_bound {bits first : Nat} {h : ℚ}
    {branches : List BranchWitness} {margin : Option DInterval}
    (hcheck : checkBranchesCert bits h first branches = .ok margin) :
    ∀ branch ∈ branches, BranchMarginBound bits h first branch margin := by
  induction branches generalizing margin with
  | nil => simp
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
          have hhead := checkBranchCert_margin_bound hb
          have htail := ih ht
          cases branchMargin with
          | none =>
            cases tailMargin with
            | none =>
              change Except.ok none = Except.ok margin at hcheck
              cases hcheck
              intro candidate hmem
              rcases List.mem_cons.mp hmem with rfl | hmem
              · exact hhead
              · exact htail candidate hmem
            | some right =>
              change Except.ok (some right) = Except.ok margin at hcheck
              cases hcheck
              intro candidate hmem
              rcases List.mem_cons.mp hmem with rfl | hmem
              · apply branchMarginBound_mono _ hhead
                intro value hvalue
                exact False.elim hvalue
              · exact htail candidate hmem
          | some left =>
            cases tailMargin with
            | none =>
              change Except.ok (some left) = Except.ok margin at hcheck
              cases hcheck
              intro candidate hmem
              rcases List.mem_cons.mp hmem with rfl | hmem
              · exact hhead
              · apply branchMarginBound_mono _ (htail candidate hmem)
                intro value hvalue
                exact False.elim hvalue
            | some right =>
              change Except.ok (some (hull left right)) = Except.ok margin at hcheck
              cases hcheck
              intro candidate hmem
              rcases List.mem_cons.mp hmem with rfl | hmem
              · apply branchMarginBound_mono _ hhead
                intro value hvalue
                exact optionMarginBounds_hull_left hvalue
              · apply branchMarginBound_mono _ (htail candidate hmem)
                intro value hvalue
                exact optionMarginBounds_hull_right hvalue

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

theorem checkBurnWitness_universal_sound {witness : BurnWitness} {margin : DInterval}
    (hcheck : checkBurnWitness witness = .ok margin) :
    ∀ branch ∈ witness.branches,
      BranchUniversalSafe witness.scaleBits
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
              exact checkBranchesCert_universal_sound hbranches

theorem checkBurnWitness_margin_bound {witness : BurnWitness} {margin : DInterval}
    (hcheck : checkBurnWitness witness = .ok margin) :
    ∀ branch ∈ witness.branches,
      BranchMarginBound witness.scaleBits
        (witness.stepNum / witness.stepDen)
        witness.firstCutoffStep branch (some margin) := by
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
          exact checkBranchesCert_margin_bound hbranches
        · change (if 0 < aggregate.lo then Except.ok aggregate
              else Except.error "nonpositive-margin") = .ok margin at hcheck
          rw [if_neg hp] at hcheck
          contradiction

theorem spacecraft_burn_certificate_sound
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

theorem spacecraft_burn_certified_safe
    {raw requestDigest modelId epoch : String} {accepted : AcceptedBurnCert}
    (h : checkBurnCert raw requestDigest modelId epoch = .ok accepted) :
    UniversalModelSafe accepted.request accepted.margin := by
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
            have hu := checkBurnWitness_universal_sound hburn
            have hb := checkBurnWitness_margin_bound hburn
            refine ⟨rfl, rfl, rfl, rfl, hs.1, hs.2.1, ?_⟩
            intro initialState thrust hinitial hthrust
            obtain ⟨branch, hmem, hstateMem, hthrustMem⟩ :=
              supplied_inputs_covered hs.1 hinitial hthrust
            have hsafe := hu branch hmem initialState thrust hstateMem hthrustMem
            have hbound := hb branch hmem initialState thrust hstateMem hthrustMem
            refine ⟨branch, hmem, hstateMem, hthrustMem, hsafe.1, ?_⟩
            intro terminalState chain absoluteTime habsolute
            obtain ⟨index, hfirst, hindex, hleft, hright⟩ :=
              supplied_cutoff_time_covered habsolute
            rcases hs.1 with
              ⟨hbits, hnum, hden, hparts, hsteps, hfirstStep, hdeclared,
                htubes, hcutoffs, hbranchCount, hcovered⟩
            have hlength : branch.steps.length = 3888 := by
              have := branchesCovered_member_length hcovered hmem
              simpa [hsteps] using this
            let localTime : ℝ := absoluteTime - (index : ℝ) / 32
            have hlocal : localTime ∈ Set.Icc (0 : ℝ) (1 / 32 : ℝ) := by
              dsimp [localTime]
              constructor
              · linarith
              · norm_num [Nat.cast_add, Nat.cast_one] at hright ⊢
                linarith
            have hindexFirst : witness.firstCutoffStep ≤ index := by
              simpa [hfirstStep] using hfirst
            have hindexLength : index < branch.steps.length := by
              simpa [hlength] using hindex
            have hlocalStep : localTime ∈ Set.Icc (0 : ℝ)
                ((witness.stepNum / witness.stepDen : ℚ) : ℝ) := by
              simpa [hnum, hden] using hlocal
            have hselected := hsafe.2 terminalState chain index localTime
              hindexFirst hindexLength hlocalStep
            constructor
            · obtain ⟨state, hat⟩ := hselected.1
              refine ⟨state, index, localTime, hindexFirst, hindexLength,
                hlocalStep, ?_, hat⟩
              dsimp [localTime]
              rw [hnum, hden]
              norm_num
              ring
            · intro state habs
              rcases habs with ⟨otherIndex, otherTime, hotherFirst,
                hotherLength, hotherTime, _habsoluteEq, hotherState⟩
              have hlower := hbound terminalState chain otherIndex otherTime
                hotherFirst hotherLength hotherTime state hotherState
              have hpositive := (hsafe.2 terminalState chain otherIndex otherTime
                hotherFirst hotherLength hotherTime).2 state hotherState
              exact ⟨hlower, hpositive⟩
      · simp [hepoch] at h
    · simp [hmodel] at h
  · simp [hrequest] at h

theorem spacecraft_burn_universal_safe
    {raw requestDigest modelId epoch : String} {accepted : AcceptedBurnCert}
    (h : checkBurnCert raw requestDigest modelId epoch = .ok accepted) :
    UniversalModelSafe accepted.request accepted.margin :=
  spacecraft_burn_certified_safe h

end JackalIv.Spacecraft
