#!/usr/bin/env python3
"""Generate or verify the spacecraft-burn Lean proof/build identity."""

from __future__ import annotations

from pathlib import Path
import sys

import gaussian_proof_identity as engine


SPACECRAFT_LANE = engine.LaneConfig(
    schema="jackal-spacecraft-burn-proof-identity-v1",
    identity_name="spacecraft_burn_proof_identity_v1.json",
    checker_path="proofs/lean/.lake/build/bin/jackal_spacecraft_burn_check",
    checker_target="jackal_spacecraft_burn_check",
    root_modules=("JackalIv.Spacecraft.CertMain",),
    fragment={
        "assurance": "formal-bounded",
        "certificate_magic": "jackal-spacecraft-burn-cert v2",
        "checker_boolean_definition": "JackalIv.Spacecraft.checkBurnCert",
        "checker_entrypoint_definition": "main (Spacecraft.CertMain)",
        "checker_executable": "jackal_spacecraft_burn_check",
        "family": "spacecraft-finite-burn-model-conditional-v2",
        "lane": "spacecraft-burn",
        "model_id": "jackal-spacecraft-finite-burn-ode-v2",
        "parser_definition": "JackalIv.Spacecraft.parseBurnWitness",
        "release_epoch": "v1.7.4",
        "request_digest": "03bcad618ad60114007c74a384eb8c9432e3755b817e74bd5bdc9bd1ba6df3e7",
        "runtime_alternate_implementation_boundary": (
            "none in the local source closure; no native_decide or implemented_by"
        ),
        "soundness_theorem": "JackalIv.Spacecraft.spacecraft_burn_certified_safe",
        "theorem_premises": [
            "checkBurnCert raw requestDigest modelId epoch = .ok accepted (runtime checked)"
        ],
        "premises_not_discharged_by_checker": [],
    },
    theorems=(
        "JackalIv.Spacecraft.spacecraft_burn_certified_safe",
        "JackalIv.Spacecraft.checkBurnWitness_sound",
        "JackalIv.Spacecraft.checkBranchesCert_sound",
        "JackalIv.Spacecraft.checkBranchCert_sound",
        "JackalIv.Spacecraft.checkOrbitSteps_sound",
        "JackalIv.Spacecraft.checked_steps_nonvacuous",
        "JackalIv.Spacecraft.checked_steps_compose",
        "JackalIv.Spacecraft.exists_classicalSolution_of_checkStep",
        "JackalIv.Spacecraft.orbitPostprocess_sound",
        "JackalIv.Spacecraft.checkCutoffCoverage_sound",
        "JackalIv.Spacecraft.fieldEnclosed",
        "JackalIv.Spacecraft.burnField_contDiffOn_of_domain",
        "JackalIv.Spacecraft.burnField_locallyLipschitzOn_of_domain",
    ),
    allowed_local_constructs={},
)


def main() -> int:
    engine.LANES["spacecraft-burn"] = SPACECRAFT_LANE
    engine.__file__ = str(Path(__file__).resolve())
    if len(sys.argv) < 2 or sys.argv[1] not in {"generate", "check"}:
        print("usage: spacecraft_burn_proof_identity.py {generate|check} [options]", file=sys.stderr)
        return 2
    if any(argument == "--lane" or argument.startswith("--lane=") for argument in sys.argv[2:]):
        print("--lane is fixed to spacecraft-burn by this wrapper", file=sys.stderr)
        return 2
    sys.argv[2:2] = ["--lane", "spacecraft-burn"]
    return engine.main()


if __name__ == "__main__":
    raise SystemExit(main())
