/-
JackalIv/GaussianCert.lean — canonical certificate codec, executable checker,
and checker soundness theorem for the admitted Gaussian integration fragment.
-/
import JackalIv.CertCodec
import JackalIv.GaussianIntegral

namespace JackalIv.GaussianCert

open JackalIv.Cert
open JackalIv.Gaussian

structure Cert where
  operation : String
  assurance : String
  family : String
  expression : String
  lower : ℚ
  upper : ℚ
  tolerance : ℚ
  aToken : String
  muToken : String
  amplitude : ℚ
  μ : ℚ
  scale : ℚ
  method : String
  core : ℚ
  degree : Nat
  sqrtPiLower : ℚ
  sqrtPiUpper : ℚ
  outputLo : ℚ
  outputHi : ℚ
  deriving Repr, DecidableEq

private def parseRatKV (key : String) (line : List Char) : Except String ℚ :=
  match stripPrefix (key.toList ++ [' ']) line with
  | some rest => match parseRatCanon rest with
      | some value => .ok value
      | none => .error ("bad canonical rational for key '" ++ key ++ "'")
  | none => .error ("expected key '" ++ key ++ "'")

def parseDecimalCanon (cs : List Char) : Option ℚ :=
  match splitOn '.' cs with
  | [whole] => (parseNatCanon whole).map fun n => (n : ℚ)
  | [whole, frac] =>
      if frac.isEmpty || frac.getLast? = some '0' then none
      else
        (parseNatCanon whole).bind fun w =>
          (parseDigitsL frac).map fun f =>
            (w : ℚ) + (f : ℚ) / ((10 ^ frac.length : Nat) : ℚ)
  | _ => none

private def parseDecimalKV (key : String) (line : List Char) :
    Except String (String × ℚ) :=
  match stripPrefix (key.toList ++ [' ']) line with
  | some rest => match parseDecimalCanon rest with
      | some value => .ok (String.ofList rest, value)
      | none => .error ("bad canonical decimal for key '" ++ key ++ "'")
  | none => .error ("expected key '" ++ key ++ "'")

private def parseNatKVLocal (key : String) (line : List Char) : Except String Nat :=
  parseNatKV key line

private def parseOutput (line : List Char) : Except String (ℚ × ℚ) :=
  parseRatPairKV "output" line

def parseCert (input : String) : Except String Cert :=
  match splitOn '\n' input.toList with
  | [magic, opLine, assuranceLine, familyLine, expressionLine,
      lowerLine, upperLine, toleranceLine, aLine, muLine, scaleLine,
      methodLine, coreLine, degreeLine, sqrtLoLine, sqrtHiLine, outputLine,
      endLine, []] => do
      if String.ofList magic != "jackal-gaussian-integral-cert v1" then
        throw "bad gaussian certificate magic"
      if String.ofList endLine != "end" then throw "expected terminal end line"
      let operation ← parseStrKV "operation" opLine
      let assurance ← parseStrKV "assurance" assuranceLine
      let family ← parseStrKV "family" familyLine
      let expression ← parseStrKV "expression" expressionLine
      let lower ← parseRatKV "lower" lowerLine
      let upper ← parseRatKV "upper" upperLine
      let tolerance ← parseRatKV "tolerance" toleranceLine
      let (aToken, amplitude) ← parseDecimalKV "A-token" aLine
      let (muToken, μ) ← parseDecimalKV "mu-token" muLine
      let scale ← parseRatKV "scale" scaleLine
      let method ← parseStrKV "method" methodLine
      let core ← parseRatKV "core" coreLine
      let degree ← parseNatKVLocal "degree" degreeLine
      let sqrtPiLower ← parseRatKV "sqrt-pi-lower" sqrtLoLine
      let sqrtPiUpper ← parseRatKV "sqrt-pi-upper" sqrtHiLine
      let (outputLo, outputHi) ← parseOutput outputLine
      pure (Cert.mk operation assurance family expression lower upper tolerance
        aToken muToken amplitude μ scale method core degree sqrtPiLower sqrtPiUpper
        outputLo outputHi)
  | _ => .error "gaussian certificate must have exactly 18 canonical lines and a trailing newline"

def renderExpression (aToken muToken : String) : String :=
  "exp(-" ++ aToken ++ "*(x-" ++ muToken ++ ")^2)"

def Conditions (c : Cert) : Prop :=
  c.operation = "integrate" ∧
  c.assurance = "formal-bounded" ∧
  c.family = "gaussian-exp-square-v1" ∧
  c.method = "gaussian-total-minus-tails-v1" ∧
  c.expression = renderExpression c.aToken c.muToken ∧
  parseDecimalCanon c.aToken.toList = some c.amplitude ∧
  parseDecimalCanon c.muToken.toList = some c.μ ∧
  0 < c.scale ∧
  c.scale ^ 2 = c.amplitude ∧
  c.lower < c.upper ∧
  0 < c.tolerance ∧
  c.core = checkerCoreQ ∧
  c.degree = checkerDegree ∧
  c.sqrtPiLower = sqrtPiLoQ ∧
  c.sqrtPiUpper = sqrtPiHiQ ∧
  c.scale * (c.lower - c.μ) ≤ -c.core ∧
  c.core ≤ c.scale * (c.upper - c.μ) ∧
  c.outputLo ≤ c.outputHi ∧
  c.outputLo ≤ checkerCoreLoQ / c.scale ∧
  checkerCoreHiQ / c.scale ≤ c.outputHi ∧
  c.outputHi - c.outputLo ≤ c.tolerance

instance conditionsDecidable (c : Cert) : Decidable (Conditions c) := by
  unfold Conditions
  infer_instance

def checkCert (c : Cert) : Bool := decide (Conditions c)

lemma checkCert_iff (c : Cert) : checkCert c = true ↔ Conditions c := by
  simp [checkCert]

/-- End-to-end semantic theorem for every certificate accepted by the
executable Boolean checker.  The theorem binds the exact source string to its
decimal parameters and encloses the corresponding finite real integral. -/
theorem gaussian_integral_check_sound (c : Cert) (hcheck : checkCert c = true) :
    c.expression = renderExpression c.aToken c.muToken ∧
    parseDecimalCanon c.aToken.toList = some c.amplitude ∧
    parseDecimalCanon c.muToken.toList = some c.μ ∧
    ((c.outputLo : ℚ) : ℝ) ≤
        (∫ x in (c.lower : ℝ)..(c.upper : ℝ),
          Real.exp (-((c.amplitude : ℚ) : ℝ) * (x - ((c.μ : ℚ) : ℝ)) ^ 2)) ∧
    (∫ x in (c.lower : ℝ)..(c.upper : ℝ),
          Real.exp (-((c.amplitude : ℚ) : ℝ) * (x - ((c.μ : ℚ) : ℝ)) ^ 2))
        ≤ ((c.outputHi : ℚ) : ℝ) := by
  have hc := (checkCert_iff c).1 hcheck
  rcases hc with ⟨_, _, _, _, hexpression, haBinding, hmuBinding,
    hscale, hamplitude, _, _, hcore, _, _, _, hleft, hright, _,
    houtputLo, houtputHi, _⟩
  have hsReal : 0 < ((c.scale : ℚ) : ℝ) := by exact_mod_cast hscale
  rw [hcore] at hleft hright
  norm_num [checkerCoreQ] at hleft hright
  have hleftReal : ((c.scale : ℚ) : ℝ) *
      (((c.lower : ℚ) : ℝ) - ((c.μ : ℚ) : ℝ)) ≤ -6 := by
    exact_mod_cast hleft
  have hrightReal : 6 ≤ ((c.scale : ℚ) : ℝ) *
      (((c.upper : ℚ) : ℝ) - ((c.μ : ℚ) : ℝ)) := by
    exact_mod_cast hright
  have hsemantic := scaled_gaussian_enclosed
    ((c.scale : ℚ) : ℝ) ((c.μ : ℚ) : ℝ) ((c.lower : ℚ) : ℝ)
    ((c.upper : ℚ) : ℝ) hsReal hleftReal hrightReal
  have hamplitudeReal : ((c.scale : ℚ) : ℝ) ^ 2 = ((c.amplitude : ℚ) : ℝ) := by
    exact_mod_cast hamplitude
  have hsemantic' :
      ((checkerCoreLoQ : ℚ) : ℝ) / ((c.scale : ℚ) : ℝ) ≤
          (∫ x in (c.lower : ℝ)..(c.upper : ℝ),
            Real.exp (-((c.amplitude : ℚ) : ℝ) * (x - ((c.μ : ℚ) : ℝ)) ^ 2)) ∧
        (∫ x in (c.lower : ℝ)..(c.upper : ℝ),
            Real.exp (-((c.amplitude : ℚ) : ℝ) * (x - ((c.μ : ℚ) : ℝ)) ^ 2))
          ≤ ((checkerCoreHiQ : ℚ) : ℝ) / ((c.scale : ℚ) : ℝ) := by
    simpa [hamplitudeReal] using hsemantic
  have houtputLoReal : ((c.outputLo : ℚ) : ℝ) ≤
      ((checkerCoreLoQ : ℚ) : ℝ) / ((c.scale : ℚ) : ℝ) := by
    exact_mod_cast houtputLo
  have houtputHiReal : ((checkerCoreHiQ : ℚ) : ℝ) / ((c.scale : ℚ) : ℝ) ≤
      ((c.outputHi : ℚ) : ℝ) := by
    exact_mod_cast houtputHi
  exact ⟨hexpression, haBinding, hmuBinding,
    houtputLoReal.trans hsemantic'.1, hsemantic'.2.trans houtputHiReal⟩

end JackalIv.GaussianCert
