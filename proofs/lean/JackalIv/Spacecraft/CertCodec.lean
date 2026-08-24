/- Strict, bounded parser for the canonical spacecraft witness grammar. -/
import JackalIv.CertCodec
import JackalIv.Spacecraft.Types

namespace JackalIv.Spacecraft

open JackalIv

def maxWitnessBytes : Nat := 64 * 1024 * 1024
def maxBranches : Nat := 1024
def maxStepsPerBranch : Nat := 1000000
def maxTubeRecords : Nat := 200000

private def refuse (reason : String) : Except String α := .error reason

private def natOr (reason : String) (token : List Char) : Except String Nat :=
  match Cert.parseNatCanon token with
  | some value => .ok value
  | none => refuse reason

private def intOr (token : List Char) : Except String Int :=
  match Cert.parseIntCanon token with
  | some value => .ok value
  | none => refuse "noncanonical-integer"

private def intervalOr (loToken hiToken : List Char) : Except String DInterval := do
  let lo ← intOr loToken
  let hi ← intOr hiToken
  if lo ≤ hi then return ⟨lo, hi⟩ else refuse "interval-order"

private def boxOfList (values : List DInterval) : Except String Box :=
  if h : values.length = 5 then
    .ok (fun index => values.get ⟨index.val, by simp [h, index.isLt]⟩)
  else refuse "box-dimension"

private def parseBox : List (List Char) → Except String Box
  | [a0, b0, a1, b1, a2, b2, a3, b3, a4, b4] => do
      boxOfList [← intervalOr a0 b0, ← intervalOr a1 b1,
        ← intervalOr a2 b2, ← intervalOr a3 b3, ← intervalOr a4 b4]
  | _ => refuse "box-dimension"

private structure Config where
  scaleBits : Nat
  stepNum : Nat
  stepDen : Nat
  partitionCounts : List Nat
  stepsPerBranch : Nat
  firstCutoffStep : Nat
  declaredBranches : Nat
  declaredTubes : Nat
  declaredCutoffCells : Nat

private def parseConfig (line : List Char) : Except String Config := do
  match Cert.splitOn ' ' line with
  | [tag, scale, sn, sd, p0, p1, p2, p3, p4, p5, steps, cutoff,
      branches, tubes, cutoffCells] =>
      if tag ≠ "config".toList then refuse "config-record" else do
        let scaleBits ← natOr "scale-bits" scale
        let stepNum ← natOr "step-rational" sn
        let stepDen ← natOr "step-rational" sd
        let partitionCounts ← [p0, p1, p2, p3, p4, p5].mapM
          (natOr "partition-count")
        let stepsPerBranch ← natOr "steps-per-branch" steps
        let firstCutoffStep ← natOr "first-cutoff-step" cutoff
        let declaredBranches ← natOr "branch-count" branches
        let declaredTubes ← natOr "tube-count" tubes
        let declaredCutoffCells ← natOr "cutoff-count" cutoffCells
        return {
          scaleBits := scaleBits
          stepNum := stepNum
          stepDen := stepDen
          partitionCounts := partitionCounts
          stepsPerBranch := stepsPerBranch
          firstCutoffStep := firstCutoffStep
          declaredBranches := declaredBranches
          declaredTubes := declaredTubes
          declaredCutoffCells := declaredCutoffCells
        }
  | _ => refuse "config-record"

private def validateConfig (cfg : Config) : Except String Unit := do
  if cfg.scaleBits = 0 ∨ 4096 < cfg.scaleBits then refuse "scale-bits" else pure ()
  if cfg.stepNum = 0 ∨ cfg.stepDen = 0 then refuse "step-rational" else pure ()
  if Nat.gcd cfg.stepNum cfg.stepDen ≠ 1 then
    refuse "step-rational-not-reduced" else pure ()
  if cfg.partitionCounts.any (· = 0) then refuse "partition-count" else pure ()
  if cfg.stepsPerBranch = 0 ∨ maxStepsPerBranch < cfg.stepsPerBranch then
    refuse "steps-per-branch" else pure ()
  if cfg.stepsPerBranch < cfg.firstCutoffStep then refuse "first-cutoff-step" else pure ()
  let computedBranches := cfg.partitionCounts.foldl (· * ·) 1
  let computedTubes := computedBranches * cfg.stepsPerBranch
  let computedCutoffs := computedBranches * (cfg.stepsPerBranch - cfg.firstCutoffStep)
  if maxBranches < computedBranches then refuse "branch-count-limit" else pure ()
  if maxTubeRecords < computedTubes then refuse "tube-count-limit" else pure ()
  if cfg.declaredBranches ≠ computedBranches then refuse "branch-count" else pure ()
  if cfg.declaredTubes ≠ computedTubes then refuse "tube-count" else pure ()
  if cfg.declaredCutoffCells ≠ computedCutoffs then refuse "cutoff-count" else pure ()

private def parseBranchLine (expected : Nat) (line : List Char) :
    Except String (Box × DInterval) := do
  match Cert.splitOn ' ' line with
  | tag :: branch :: rest =>
      if tag ≠ "branch".toList ∨ rest.length ≠ 12 then refuse "unexpected-record" else do
        let observed ← natOr "branch-order" branch
        if observed ≠ expected then refuse "branch-order" else do
          let initial ← parseBox (rest.take 10)
          let thrust ← match rest.drop 10 with
            | [lowToken, highToken] => intervalOr lowToken highToken
            | _ => refuse "unexpected-record"
          return (initial, thrust)
  | _ => refuse "unexpected-record"

private def parseTubeLine (branch step : Nat) (line : List Char) :
    Except String StepWitness := do
  match Cert.splitOn ' ' line with
  | tag :: branchToken :: stepToken :: rest =>
      if tag ≠ "tube".toList ∨ rest.length ≠ 10 then refuse "unexpected-record" else do
        let observedBranch ← natOr "step-order" branchToken
        let observedStep ← natOr "step-order" stepToken
        if observedBranch ≠ branch ∨ observedStep ≠ step then refuse "step-order" else
          return ⟨branch, step, ← parseBox rest⟩
  | _ => refuse "unexpected-record"

private def parseSteps : Nat → Nat → Nat → List (List Char) →
    Except String (List StepWitness × List (List Char))
  | 0, _, _, lines => return ([], lines)
  | remaining + 1, branch, step, line :: lines => do
      let witness ← parseTubeLine branch step line
      let (tail, rest) ← parseSteps remaining branch (step + 1) lines
      return (witness :: tail, rest)
  | _ + 1, _, _, [] => refuse "step-count"

private def parseBranches : Nat → Nat → Nat → List (List Char) →
    Except String (List BranchWitness × List (List Char))
  | 0, _, _, lines => return ([], lines)
  | remaining + 1, branch, stepsPerBranch, line :: lines => do
      let (initial, thrust) ← parseBranchLine branch line
      let (steps, rest) ← parseSteps stepsPerBranch branch 0 lines
      let (tail, terminal) ← parseBranches remaining (branch + 1) stepsPerBranch rest
      return (⟨branch, initial, thrust, steps⟩ :: tail, terminal)
  | _ + 1, _, _, [] => refuse "branch-count"

private def parseTerminal (cfg : Config) (lines : List (List Char)) : Except String Unit := do
  match lines with
  | [line, []] =>
      match Cert.splitOn ' ' line with
      | [tag, branches, tubes, cutoffs] =>
          if tag ≠ "end".toList then refuse "unexpected-record" else do
            let b ← natOr "terminal-count" branches
            let t ← natOr "terminal-count" tubes
            let c ← natOr "terminal-count" cutoffs
            if (b, t, c) = (cfg.declaredBranches, cfg.declaredTubes,
                cfg.declaredCutoffCells) then pure () else refuse "terminal-count"
      | _ => refuse "unexpected-record"
  | [] => refuse "missing-terminal"
  | _ => refuse "trailing-record"

def parseBurnWitness (s : String) : Except String BurnWitness := do
  if maxWitnessBytes < s.toUTF8.size then refuse "witness-too-large" else pure ()
  if s.toList.any (fun c => c = '\r') then refuse "noncanonical-line-ending" else pure ()
  if s.toList.any (fun c => 127 < c.toNat) then refuse "non-ascii" else pure ()
  match (s.splitOn "\n").map String.toList with
  | magic :: configLine :: rest =>
      if magic ≠ "jackal-spacecraft-burn-cert v2".toList then refuse "witness-magic" else do
        let cfg ← parseConfig configLine
        validateConfig cfg
        let (branches, terminal) ← parseBranches cfg.declaredBranches 0 cfg.stepsPerBranch rest
        parseTerminal cfg terminal
        return {
          scaleBits := cfg.scaleBits
          stepNum := cfg.stepNum
          stepDen := cfg.stepDen
          partitionCounts := cfg.partitionCounts
          stepsPerBranch := cfg.stepsPerBranch
          firstCutoffStep := cfg.firstCutoffStep
          declaredBranches := cfg.declaredBranches
          declaredTubes := cfg.declaredTubes
          declaredCutoffCells := cfg.declaredCutoffCells
          branches := branches
        }
  | _ => refuse "missing-terminal"

end JackalIv.Spacecraft
