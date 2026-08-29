import JackalIv.Spacecraft.CertSound
import JackalIv.Spacecraft.OrbitFixtures

namespace JackalIv.Spacecraft

#guard match checkBurnCert "" "wrong" spacecraftModelId spacecraftReleaseEpoch with
  | .error reason => reason == "request-digest"
  | .ok _ => false
#guard match checkBurnCert "" spacecraftRequestDigest "wrong" spacecraftReleaseEpoch with
  | .error reason => reason == "model-id"
  | .ok _ => false
#guard match checkBurnCert "" spacecraftRequestDigest spacecraftModelId "wrong" with
  | .error reason => reason == "release-epoch"
  | .ok _ => false
#guard match checkBurnCert "" spacecraftRequestDigest spacecraftModelId
    spacecraftReleaseEpoch with
  | .error reason => reason == "missing-terminal"
  | .ok _ => false
#guard checkBurnWitness coverageSkeleton = .error "cutoff-coverage"

#check supplied_inputs_covered
#check supplied_cutoff_time_covered
#check spacecraft_burn_universal_safe

#print axioms supplied_inputs_covered
#print axioms supplied_cutoff_time_covered
#print axioms checked_chain_state_safe
#print axioms checked_chain_state_margin_bound
#print axioms checkBurnWitness_margin_bound
#print axioms spacecraft_burn_certificate_sound
#print axioms spacecraft_burn_certified_safe

end JackalIv.Spacecraft
