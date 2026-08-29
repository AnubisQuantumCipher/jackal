/- Exact wire types for the spacecraft finite-burn certificate. -/
import Mathlib.Data.Fin.Basic

namespace JackalIv.Spacecraft

structure DInterval where
  lo : Int
  hi : Int
  deriving DecidableEq, Repr

abbrev Box := Fin 5 → DInterval

structure StepWitness where
  branch : Nat
  step : Nat
  tube : Box

structure BranchWitness where
  branch : Nat
  initial : Box
  thrust : DInterval
  steps : List StepWitness

structure BurnWitness where
  scaleBits : Nat
  stepNum : Nat
  stepDen : Nat
  partitionCounts : List Nat
  stepsPerBranch : Nat
  firstCutoffStep : Nat
  declaredBranches : Nat
  declaredTubes : Nat
  declaredCutoffCells : Nat
  branches : List BranchWitness

end JackalIv.Spacecraft
