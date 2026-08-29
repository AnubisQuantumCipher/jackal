import JackalIv.Spacecraft.Picard

namespace JackalIv.Spacecraft

def fixtureInitial : Box := ![
  ⟨8073206018923583821373255974, 8073810784064846039617902740⟩,
  ⟨-604462909807314587354, 604462909807314587354⟩,
  ⟨-24178516392292583495, 24178516392292583495⟩,
  ⟨9339919097178702077944974, 9340160882342625003779916⟩,
  ⟨1448897594808133065885351936, 1450710983537555009647411200⟩]

def fixtureTube : Box := ![
  ⟨8073175779835384209475966077, 8073841023153045651515192637⟩,
  ⟨-15258910579448397614496, 307138938152655428982619⟩,
  ⟨-381178402019938641373, 43481226792875022775⟩,
  ⟨9339903855653087702359029, 9340239169216603965249811⟩,
  ⟨1448788947603308133960482459, 1450802509058233432299169712⟩]

def fixtureEndpoint : Box := ![
  ⟨8073206007011758758250173431, 8073810785423634376895247202⟩,
  ⟨291267532579351676111365, 292486936947826188501411⟩,
  ⟨-361883161010858777201, -313411974898425715923⟩,
  ⟨9339981885589345906096875, 9340223933663175564970978⟩,
  ⟨1448880473123986556612240971, 1450693904657618866647483014⟩]

def fixtureThrust : DInterval :=
  ⟨2411807010131185203538821120, 2417851639229258349412352000⟩

def fixtureStep0 : StepWitness where
  branch := 0
  step := 0
  tube := fixtureTube

def fixtureBrokenStep : StepWitness where
  branch := 0
  step := 2
  tube := fixtureTube

def fixtureWideInitial : Box := Function.update fixtureInitial 4
  ⟨(fixtureInitial 4).lo, (fixtureInitial 4).lo + 3 * scale 80⟩

def fixtureFastInitial : Box := Function.update fixtureInitial 3 (pointRat 80 100)

def refused {α : Type} : Except String α → Bool
  | .error _ => true
  | .ok _ => false

#guard strictInsideIv ⟨2, 4⟩ ⟨1, 5⟩
#guard !strictInsideIv ⟨1, 4⟩ ⟨1, 5⟩
#guard subsetIv ⟨1, 5⟩ ⟨1, 5⟩
#guard checkStep 80 (1 / 32) fixtureInitial fixtureTube fixtureThrust =
  .ok fixtureEndpoint
#guard checkStep 80 0 fixtureInitial fixtureTube fixtureThrust =
  .error "step-size"
#guard refused (checkStep 80 (1 / 32) fixtureInitial
  ![⟨0, 0⟩, ⟨0, 0⟩, ⟨0, 0⟩, ⟨0, 0⟩, ⟨0, 0⟩] fixtureThrust)
#guard checkBranchSteps 80 (1 / 32) 0 fixtureThrust fixtureInitial 0
  [fixtureStep0] = .ok fixtureEndpoint
#guard refused (checkBranchSteps 80 (1 / 32) 0 fixtureThrust fixtureInitial 0
  [fixtureStep0, fixtureBrokenStep])
#guard existenceGuard 80 1 fixtureInitial fixtureThrust =
  .error "existence-time-radius"
#guard existenceGuard 80 (1 / 32) fixtureWideInitial fixtureThrust =
  .error "existence-initial-radius"
#guard existenceGuard 80 (1 / 32) fixtureFastInitial fixtureThrust =
  .error "existence-field-norm"

example {bits : Nat} {h : ℚ} {initial tube : Box}
    {thrustIv : DInterval} {endpoint : Box}
    {initialState state : State} {thrust : ℝ}
    (hendpoint : endpointBox bits h initial tube thrustIv = .ok endpoint)
    (hi : ∀ i, Mem bits (initialState i) (initial i))
    (hs : ∀ i, Mem bits (state i) (tube i))
    (ht : Mem bits thrust thrustIv) :
    ∀ i, Mem bits
      ((initialState + (h : ℝ) • burnField thrust state) i)
      (endpoint i) :=
  endpointBox_sound hendpoint hi hs ht

#print axioms endpointBox_sound
#print axioms intervalIntegral_mem_mul
#print axioms classicalSolution_picard_eq
#print axioms picard_tube_encloses
#print axioms picard_endpoint_encloses
#print axioms checked_steps_compose
#print axioms exists_classicalSolution_of_checkStep
#print axioms checked_steps_nonvacuous

end JackalIv.Spacecraft
