# Spacecraft Burn Formal Certification v2 Design

Date: 2026-08-24

Repository: `https://github.com/AnubisQuantumCipher/jackal`

Design base: `4789adc949d47fd1d1e00eaa9532dd5ca0dbff70`

Source review package:
`/Users/sicarii/Desktop/Inbox/JACKAL-Spacecraft-Burn-Certification-Review`

## Objective

Integrate the finite-duration spacecraft-burn certificate into JACKAL as a
source-visible, independently checkable formal-certification lane. Remove the
ambiguous public labels `PROVED SAFE` and `PROVED UNSAFE`. A positive result
must instead read:

> `CERTIFIED SAFE under the stated finite-burn ODE model, supplied input bounds, and machine-checked interval-certificate assumptions.`

The Python producer is an untrusted witness generator. It cannot mint a
`formal-bounded` result. Only a caller-pinned Lean checker whose soundness
theorem and exact source closure have passed the proof-identity gate may
produce the formal result. Physical-model adequacy, supplied constants, input
truth, and correspondence between the mathematical model and a real
spacecraft remain explicit assumptions.

## Current Evidence and Defect

The supplied v1 package uses exact-integer outward-rounded dyadic intervals,
checks a Picard self-map at every ODE step, independently replays the
calculation in a second Python implementation, and records a positive lower
margin. Its 13 local tests passed in the attached review directory during the
design audit. The package correctly
states that its nonlinear ODE result is rigorously interval-bounded rather
than formal-bounded.

However, `PROVED SAFE` and `PROVED UNSAFE` appear in the report, producer,
verifier, validation program, unit tests, mutation evidence, and baseline
receipt. The receipt stores a digest of the Picard trace rather than the
complete witnesses needed by an independently proved checker. Consequently,
the Picard algorithm and both Python implementations are part of the current
trusted implementation base. Documentation alone cannot close that gap.

## Chosen Architecture

The v2 lane uses proof-carrying computation:

1. Python partitions the uncertainty box and emits a complete deterministic
   witness stream containing the interval state, Picard tube, endpoint,
   cutoff coverage record, and orbital post-processing witnesses.
2. A strict codec parses the stream with bounded sizes, canonical integers,
   canonical ordering, exact dimensions, and no ignored or duplicate fields.
3. A Lean checker recomputes every interval operation needed for acceptance,
   checks every Picard inclusion and endpoint enclosure, checks step-to-step
   chaining and cutoff coverage, checks the orbital identities and interval
   compositions, and checks that the decisive lower endpoint is positive.
4. A Lean soundness theorem connects checker acceptance to the model-level
   conditional safety proposition.
5. An outer verifier binds the request, witness, checker executable, theorem,
   proof identity, model contract, receipt epoch, and caller expectations.
6. User-facing code renders the model-conditional certification only after
   the outer verifier independently replays the accepted checker path.

`certify.py` may be wrong, malicious, or replaced and still cannot cause an
accepted formal result unless it supplies a witness that the Lean checker
accepts. Formalizing Python semantics is therefore outside the trusted proof
path and is not required for the v2 claim.

## Formal Statement

The central theorem will have the following semantic shape, with concrete
Lean names fixed in the implementation plan:

```text
spacecraft_burn_check request witness = accept
  -> request satisfies the v2 model contract
  -> every classical solution of the stated ODE whose initial state,
     thrust, mass, and cutoff time satisfy the supplied bounds
     has apoapsis altitude at least 1000 km
```

The theorem is conditional on existence of a classical solution of the stated
ODE over the burn interval. The formal tranche must prove the regularity and
local uniqueness obligations required by the Picard enclosure argument on
every accepted tube, using the accepted positive lower bounds for position
norm, velocity norm, and mass. If the pinned Mathlib revision lacks a suitable
ODE theorem, JACKAL must prove the required theorem from Mathlib's analysis
foundations. Introducing an axiom that states the Picard enclosure conclusion
is forbidden.

The accepted theorem may depend on Lean's ordinary logical foundations such
as `propext`, `Classical.choice`, and `Quot.sound`. It may not depend on
project-local axioms, `sorryAx`, unproved declarations, native-code
evaluation axioms, or a theorem that merely mirrors the checker output.

## Formal Modules

The proof surface will be isolated under:

```text
proofs/lean/JackalIv/Spacecraft/
  Types.lean
  Interval.lean
  VectorField.lean
  Picard.lean
  Orbit.lean
  CertCodec.lean
  CertCheck.lean
  CertSound.lean
  CertMain.lean
```

- `Types` defines model inputs, dyadic intervals, boxes, steps, witnesses,
  results, and refusal classes.
- `Interval` proves enclosure soundness for every arithmetic operator used by
  the lane, including integer square-root endpoint inequalities.
- `VectorField` defines the finite-burn ODE and proves denominator-domain and
  differentiability obligations on accepted tubes.
- `Picard` proves the self-map enclosure and endpoint theorems and their
  finite step composition.
- `Orbit` proves the energy, angular-momentum, eccentricity, apoapsis, and
  safety-margin transformations used by the accepted checker.
- `CertCodec` implements the canonical bounded witness codec.
- `CertCheck` implements the executable Boolean/decision checker.
- `CertSound` proves that checker acceptance implies the formal statement.
- `CertMain` provides the narrow `jackal_spacecraft_burn_check` executable.

The top-level `JackalIv.lean`, `lakefile.toml`, proof ledger, and proof-identity
tools will include this surface only after its theorem and audit gates pass.

## Witness and Receipt v2

The witness format is canonical, versioned, and bounded. It records:

- exact model constants and units;
- exact initial, thrust, mass, and cutoff-time bounds;
- step size and partition definition;
- every branch identifier and its exact input sub-box;
- every step's initial box, Picard tube, endpoint box, and inclusion data;
- positive denominator-domain witnesses;
- exact cutoff-time coverage membership;
- orbital interval witnesses and both eccentricity routes;
- the decisive global lower endpoint; and
- an exact terminal count reconciliation.

The checker rejects missing, extra, duplicate, out-of-order, oversized,
noncanonical, dimensionally invalid, or discontinuous records. Hashes are
artifact bindings, never substitutes for the witnesses they identify.

The receipt schema becomes
`spacecraft-finite-burn-formal-receipt-v2`. Its result vocabulary is:

- `CERTIFIED SAFE` when the accepted lower margin is strictly positive;
- `CERTIFIED UNSAFE` only when an independently specified unsafe proposition
  is checker-proved, not merely when one interval upper endpoint is nonpositive;
- `INDETERMINATE` when the certificate cannot decide; and
- `REFUSED` with a stable named reason for malformed, unsupported, mismatched,
  or unverified requests.

The initial v2 release is required to support `CERTIFIED SAFE`,
`INDETERMINATE`, and `REFUSED`. It must not emit `CERTIFIED UNSAFE` until the
unsafe proposition and its consequence semantics receive a separate theorem
and review. This prevents a symmetric-looking label from overstating what the
current safety requirement establishes.

Legacy v1 receipts remain immutable historical artifacts. The v2 verifier
refuses them with `legacy-unproved-verdict-schema`; it never rewrites or
silently promotes them. New evidence is generated under new filenames.

## User-Facing Claim Contract

Every public surface—including CLI output, JSON, Markdown, examples, tests,
release notes, plugin skill text, and generated evidence—must use the v2
claim vocabulary. The release gate scans the current publication surface for
`PROVED SAFE`, `PROVED UNSAFE`, and unqualified variants of `formally proved`.
Historical evidence may retain those bytes only when quarantined by an
explicit legacy manifest and excluded from current examples and results.

The primary result must display the model and assumption qualifier adjacent
to the verdict. A footnote elsewhere is insufficient. `formal-bounded` means
only that the caller-pinned Lean checker accepted the stated mathematical
certificate. It does not prove:

- the supplied constants or uncertainty bounds are true;
- the ODE is an adequate physical model of a real spacecraft;
- thrust direction, engine behavior, environmental effects, or cutoff logic
  omitted by the model are physically absent;
- the exact lower endpoint is the mathematical infimum; or
- JACKAL is a universal theorem prover.

## Fail-Closed Boundaries

The lane refuses rather than downgrades when any of the following occurs:

- proof identity, checker, theorem, witness, request, epoch, or model mismatch;
- a noncanonical or oversized witness;
- a failed interval operation or denominator-domain obligation;
- a missing branch, step, cutoff cell, or terminal count;
- a failed Picard self-map, endpoint, or step-chain check;
- an unsupported ODE/model construct;
- an empty eccentricity intersection or failed orbital identity;
- a nonpositive or nonexact decisive lower endpoint;
- a legacy verdict schema; or
- a checker timeout, crash, extra output, or ambiguous result.

No fallback may convert a failed formal check into a rigorous, sampled,
estimated, or nominal success in the same request.

## Testing and Adversarial Validation

Implementation follows strict red-green-refactor cycles. Tests are divided by
what they establish:

1. Codec tests: canonical round-trip, bounds, duplicate keys, ordering,
   truncation, extra records, integer limits, and path safety.
2. Arithmetic tests: exhaustive small-domain and randomized rational
   containment checks for every dyadic operation, plus negative controls.
3. Picard checker tests: valid one-step witnesses and mutations of every box
   endpoint, inclusion relation, endpoint, domain guard, and chain link.
4. Coverage tests: omitted, duplicated, reordered, and overlapping branches,
   steps, and cutoff cells must refuse.
5. Orbital tests: sign, unit, energy factor, eccentricity identity,
   intersection, apoapsis, and decision-rounding mutations must refuse.
6. Proof tests: `lake build`, theorem-specific `#print axioms`, source-closure
   identity reproduction, and deliberate theorem/checker drift.
7. End-to-end tests: Python witness generation followed by the exact built
   Lean checker and independent outer verification.
8. A-B-A mutation tests: exact source restoration and baseline acceptance
   before and after every mutation.
9. Instrument validation: true-answer and per-case wrong-answer controls,
   analytic mass containment, step-size cross-checks, and nominal/sample
   diagnostics retained at their weaker epistemic classes.

The full 124,416-tube baseline must be checked by the release executable.
Small fixtures alone cannot support the published result.

## Independent Review

Before release, a reviewer isolated from the implementation pass will audit:

- theorem statements against the English claim;
- whether checker acceptance reaches the theorem rather than a model mirror;
- every project-local axiom and admitted declaration in the source closure;
- codec ambiguity, resource bounds, and fail-closed behavior;
- interval-operation soundness and integer endpoint conventions;
- the Picard existence, regularity, inclusion, endpoint, and composition
  arguments;
- cutoff-time coverage and branch completeness;
- orbital algebra and the decisive inequality;
- request, checker, proof, and artifact identity binding; and
- every user-facing assurance statement and non-claim.

The review produces a committed report with findings, dispositions, exact
reviewed commit, commands, and artifact hashes. An internal independent review
is not represented as journal peer review or third-party endorsement.

## CI and Release Gates

A dedicated macOS workflow will:

1. build the pinned Lean project;
2. run theorem-specific axiom/admission and source-closure gates;
3. run all spacecraft Python and checker tests;
4. generate the full witness twice in isolated directories and require
   byte-identical output;
5. run the built Lean checker on both outputs;
6. run the independent outer verifier with caller-pinned expectations;
7. run all adversarial A-B-A mutations;
8. reproduce evidence and manifest files byte-for-byte in `--check` mode;
9. scan current user-facing surfaces for forbidden claim language; and
10. retain existing JACKAL proof, capability, package, and plugin gates.

Release publication requires a clean branch, green hosted checks, an
independent review report with no unresolved high-severity findings, an
annotated tag bound to the merge commit, checksum-governed assets, and fresh
download/readback proving that the published bytes equal the locally verified
bytes. The next release version is selected only after implementation impact
and compatibility are known; this design does not predeclare a version.

## Completion Criteria

The tranche is complete only when all of the following are true:

- no current user-facing surface emits or endorses `PROVED SAFE` or
  `PROVED UNSAFE`;
- the v2 model-conditional wording is adjacent to every positive verdict;
- legacy v1 evidence is immutable and explicitly quarantined;
- the complete witness is accepted by the built Lean checker;
- the central soundness theorem has only the approved Lean foundation axiom
  set and no project-local admission;
- the outer verifier binds and replays the exact checker/proof/request tuple;
- the complete baseline, negative controls, mutations, and existing JACKAL
  gates pass locally and in hosted CI;
- the independent review is complete with all release-blocking findings
  resolved;
- source, receipts, proof identities, manifests, documentation, plugin skill,
  and release artifacts agree mechanically; and
- the merged tag and downloaded GitHub release assets pass exact readback.

Until every criterion holds, the nonlinear ODE result remains
`rigorously interval-bounded; not formal-bounded`, and no release may claim the
formal tranche is complete.
