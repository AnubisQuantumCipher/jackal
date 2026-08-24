import JackalIv.Spacecraft.Orbit
import JackalIv.Spacecraft.PicardFixtures

namespace JackalIv.Spacecraft

def coverageSkeleton : BurnWitness where
  scaleBits := 80
  stepNum := 1
  stepDen := 32
  partitionCounts := [4, 1, 1, 2, 2, 2]
  stepsPerBranch := 3888
  firstCutoffStep := 3792
  declaredBranches := 32
  declaredTubes := 124416
  declaredCutoffCells := 3072
  branches := []

def fixtureCutoffTube : Box := ![
  ⟨7996692967253656154912680939, 7997495368914738561360803235⟩,
  ⟨1117566577919511907199421446, 1118011259970155443343688157⟩,
  ⟨-1293550950458489924508194, -1292505140290696927807744⟩,
  ⟨9494294976974404252668535, 9495794532568183404730784⟩,
  ⟨1383855405641459524928248281, 1386047512018664621966943298⟩]

#guard checkCutoffCoverage coverageSkeleton = .error "cutoff-coverage"
#guard expectedInitialBox 80 0 = fixtureInitial
#guard (expectedThrust 80 0).lo = fixtureThrust.lo
#guard match orbitPostprocess 80 fixtureCutoffTube with
  | .ok _ => true
  | .error _ => false
#guard match orbitPostprocess 80 fixtureCutoffTube with
  | .ok result => 0 < result.margin.lo
  | .error _ => false
#guard match orbitPostprocess 80 ![⟨0, 0⟩, ⟨0, 0⟩, ⟨0, 0⟩, ⟨0, 0⟩, ⟨1, 1⟩] with
  | .error _ => true
  | .ok _ => false

example (x y vx vy : ℝ) :
    (vx ^ 2 + vy ^ 2) * (x ^ 2 + y ^ 2) - (x * vx + y * vy) ^ 2 =
      (x * vy - y * vx) ^ 2 := angular_momentum_lagrange_identity x y vx vy

#print axioms checkCutoffCoverage_sound
#print axioms angular_momentum_lagrange_identity
#print axioms energy_definition_substitution
#print axioms apoapsis_plus_expansion
#print axioms eccentricity_vector_reduction
#print axioms orbitPostprocess_sound
#print axioms orbit_margin_positive_implies_safe

end JackalIv.Spacecraft
