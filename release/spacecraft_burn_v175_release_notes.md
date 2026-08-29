# JACKAL v1.7.5 - Spacecraft finite-burn certification

This corrective release publishes the review-cleared spacecraft finite-burn
certificate, its pinned Lean checker identity, the full witness, independent
outer replay, adversarial mutation evidence, and a self-contained macOS arm64
verification archive.

## Qualified result

**CERTIFIED SAFE under the stated finite-burn ODE model, supplied input bounds,
and machine-checked interval-certificate assumptions.**

The checker-accepted exact dyadic safety-margin interval has a strictly positive
lower endpoint. The result is conditional on the encoded model and supplied
input intervals; it is not a claim that the model captures every physical
spacecraft effect or that the inputs are true for a mission.

## Verification boundary

- The pinned Lean checker independently validates every accepted tube, cutoff
  cell, orbital bound, and final positive margin.
- The Python Picard witness generator and its source are not formally verified.
  They remain trusted for termination, witness search, completeness, and
  reproducible generation, but cannot authorize `formal-bounded` without the
  checker and outer-verifier gates.
- The proof identity binds the admitted Lean source closure, pinned dependency
  trees, complete private Lean toolchain tree, checker bytes, and generator
  closure. Platform/runtime and physical-model assumptions remain explicit.
- `VERIFICATION.md` and `SHA256SUMS` describe the exact offline replay for all
  twelve release assets.

Publication is complete only when fresh public downloads reproduce the tagged
commit, asset roster, sizes, checksums, checker result, outer replay, and this
exact release title and notes body.
