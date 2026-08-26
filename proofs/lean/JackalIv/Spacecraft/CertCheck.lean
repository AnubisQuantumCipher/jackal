/- The single executable decision used by the spacecraft burn release lane. -/
import JackalIv.Spacecraft.CertCodec
import JackalIv.Spacecraft.Orbit

namespace JackalIv.Spacecraft

def spacecraftRequestDigest : String :=
  "03bcad618ad60114007c74a384eb8c9432e3755b817e74bd5bdc9bd1ba6df3e7"

def spacecraftModelId : String := "jackal-spacecraft-finite-burn-ode-v2"
def spacecraftReleaseEpoch : String := "v1.7.5"

structure CertifiedBurnRequest where
  witness : BurnWitness
  model : ModelRequest
  requestDigest : String
  modelId : String
  epoch : String

structure AcceptedBurnCert where
  request : CertifiedBurnRequest
  margin : DInterval

def mergeMargin : Option DInterval → DInterval → Option DInterval
  | none, margin => some margin
  | some aggregate, margin => some (hull aggregate margin)

def checkOrbitSteps (bits first expected : Nat) :
    List StepWitness → Except String (Option DInterval)
  | [] => pure none
  | step :: tail => do
      let rest ← checkOrbitSteps bits first (expected + 1) tail
      if expected < first then pure rest else
        let orbit ← orbitPostprocess bits step.tube
        if 0 < orbit.margin.lo then pure (mergeMargin rest orbit.margin)
        else throw "nonpositive-margin"

def checkBranchCert (bits : Nat) (h : ℚ) (first : Nat)
    (branch : BranchWitness) : Except String (Option DInterval) := do
  let _ ← checkBranchSteps bits h branch.branch branch.thrust
    branch.initial 0 branch.steps
  checkOrbitSteps bits first 0 branch.steps

def checkBranchesCert (bits : Nat) (h : ℚ) (first : Nat) :
    List BranchWitness → Except String (Option DInterval)
  | [] => pure none
  | branch :: tail => do
      let branchMargin ← checkBranchCert bits h first branch
      let tailMargin ← checkBranchesCert bits h first tail
      match branchMargin, tailMargin with
      | none, other => pure other
      | other, none => pure other
      | some left, some right => pure (some (hull left right))

def checkBurnWitness (witness : BurnWitness) : Except String DInterval := do
  checkCutoffCoverage witness
  let h : ℚ := witness.stepNum / witness.stepDen
  let result ← checkBranchesCert witness.scaleBits h witness.firstCutoffStep
    witness.branches
  match result with
  | none => throw "no-cutoff-cells"
  | some margin =>
      if 0 < margin.lo then pure margin else throw "nonpositive-margin"

def checkBurnCert (raw requestDigest modelId epoch : String) :
    Except String AcceptedBurnCert :=
  if requestDigest = spacecraftRequestDigest then
    if modelId = spacecraftModelId then
      if epoch = spacecraftReleaseEpoch then
        match parseBurnWitness raw with
        | .error error => .error error
        | .ok witness =>
          match checkBurnWitness witness with
          | .error error => .error error
          | .ok margin => .ok {
              request := {
                witness := witness
                model := pinnedModelRequest
                requestDigest := requestDigest
                modelId := modelId
                epoch := epoch
              }
              margin := margin
            }
      else .error "release-epoch"
    else .error "model-id"
  else .error "request-digest"

end JackalIv.Spacecraft
