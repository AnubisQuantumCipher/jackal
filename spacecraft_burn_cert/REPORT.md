# Finite-duration periapsis burn certification report

Commit-scoped publication state: this source snapshot records the v1.7.5
candidate prepared before publication. Neither this source snapshot nor a tag
alone proves the current GitHub release state. Consult the
[releases index](https://github.com/AnubisQuantumCipher/jackal/releases) and
the postpublication readback committed on `master`; the v1.7.5 tag page exists
only after publication. Only those current checks establish publication and
bind the released bytes.

## Decisive result

**CERTIFIED SAFE under the stated finite-burn ODE model, supplied input bounds, and machine-checked interval-certificate assumptions.**

The pinned Lean checker accepted the certificate with the exact dyadic margin
interval

```text
[51450379597827184853505075, 97148190212754394888777802] / 2^80 km
```

whose lower endpoint is
`42.5587565118164884375971897689535... km > 0`. The separately kernel-checked
theorem `spacecraft_burn_certified_safe` proves that this acceptance entails
that every trajectory admitted by the encoded model and supplied bounds has an
apoapsis altitude strictly above 1000 km. This is a lower bound, not the exact
mathematical infimum and not a statement about model adequacy for a physical
mission.

## What is machine checked

The certificate covers 32 initial/thrust branches, 124,416 ODE tube records,
and 3,072 cutoff cells over `[118.5, 121.5] s`. The Lean development checks:

- strict canonical parsing and bounded witness structure;
- exact dyadic interval arithmetic and domain non-zeroness;
- the finite-burn vector field and its interval extension;
- continuity and local Lipschitz obligations on admitted tubes;
- non-vacuous Picard self-enclosure and exact step composition;
- initial partition and cutoff-time coverage;
- orbital energy, angular momentum, eccentricity, apoapsis, and margin bounds;
- full membership of every admitted apoapsis margin in the accepted exact
  dyadic interval, and strict positivity of that interval.

The central theorem has only Lean's standard `propext`, `Classical.choice`, and
`Quot.sound` dependencies in its printed axiom set. The source admission audit
found zero `axiom`, `sorry`, `admit`, or `unsafe` declarations across the
57-file repository-wide Lean audit; the generated spacecraft source closure
contains 23 files.

## Assurance boundary

| Layer | Current evidence | What it establishes | What remains trusted or unclaimed |
|---|---|---|---|
| Formal theorem | `JackalIv.Spacecraft.spacecraft_burn_certified_safe` | Accepted witness implies every admitted margin belongs to the accepted exact interval, whose lower endpoint is positive | Lean kernel and declared standard axioms |
| Executable checker | `jackal_spacecraft_burn_check` plus proof identity | Parses and decides the exact bounded certificate; publication generation binds the complete private Lean toolchain tree and build inputs | Python, Git, macOS kernel/sandbox, dyld, libSystem, hardware, and supply-chain correctness remain trusted and unproved |
| Artifact binding | proof identity plus outer verifier | Recomputes receipt, witness, checker, model, request, epoch, nonce, and theorem identities | caller must supply independent pins |
| Independent replay | `independent_verification_v2.json` | Replays interval and orbital operations without importing producer code | independent implementation is review evidence, not a second theorem prover |
| Model assumptions | finite-burn ODE and supplied intervals | Exact conditional proposition checked by Lean | physical fidelity, omitted perturbations, actuator behavior, and input truth |
| Diagnostics | RK4 nominal/corners and step variants | Instrument cross-checks | no diagnostic sample supports the universal verdict |

The Python producer is candidate-only. A receipt with
`formal_checker_status=NOT_EXECUTED` is refused. Only the pinned Lean checker
can authorize `formal-bounded`, and the outer verifier must reproduce its exact
single-line acceptance result.

The Python Picard witness generator and its source are not formally verified.
They are outside the mathematical soundness base because the pinned Lean
checker independently checks every accepted tube, but remain trusted for
termination, witness search/completeness, and reproducible generation. A
producer defect may cause refusal, nontermination, or failure to find a
witness, but cannot yield formal `ACCEPT` absent a defect in the pinned Lean
checker or outer verification gate.

The hosted macOS campaign is deliberately platform-local source/checker
verification and labels its uploaded logs `NON-PUBLICATION`. It does not claim
byte identity with a checker built on another macOS release. Exact publication
bytes must instead be checked on the owning platform from a clean merge/tag
checkout, reproduced twice, clean-extracted, and then checked again from fresh
public downloads. The authoritative producer and outer-verifier paths execute
private snapshots of already bounded and hashed checker/witness bytes; a raw
direct checker invocation is diagnostic, not the publication binding.

## Exact identities

| Artifact | SHA-256 |
|---|---|
| Full witness release asset | `27d5b16e08dd9f1b39774adb455a43e129bb390b9c7462f87ba93cdade87204c` |
| Baseline receipt | `a7537a9d55b8c7ebfbff5c2baa00d6be713e6194d82cd6f7700fa302c40b4314` |
| Lean checker executable | `2e08149b735ff70a1f1b6606aeca46c9e4dbf2a7d12db2cdc0e80d37f325fa59` |
| Proof identity file | `5140d819410533245bac47451c1ae07c3230c2a8172997c9172c4572bad14cd7` |
| Proof identity internal digest | `5041533e12ab62a442791c37de69104ab6b08df54011c64b05161a777c83377b` |
| Request | `03bcad618ad60114007c74a384eb8c9432e3755b817e74bd5bdc9bd1ba6df3e7` |

Model ID is `jackal-spacecraft-finite-burn-ode-v2`; release epoch is `v1.7.5`;
publication nonce is `spacecraft-burn-v2-publication-20260825`.

Two complete producer/checker runs generated byte-identical 35,939,138-byte
witnesses and byte-identical receipts. The committed witness manifest binds the
release asset without placing the large witness in Git history.

## Adversarial controls

The v2 validation evidence records 4/4 true-answer controls accepted and 0/4
per-case wrong answers accepted. All six original source mutations were caught
and their A→B→A cycles restored the exact producer bytes. Formal witness
mutations refused as follows:

| Mutation | Checker refusal |
|---|---|
| trailing-byte corruption | `noncanonical-control-character` |
| broken tube chain | `picard-strict-interior` |
| broken initial coverage | `cutoff-coverage` |

The baseline outer verifier accepted both before and after the mutation
campaign. The 1/16 and 1/48 step runs are rigorous interval cross-checks, not
separately accepted formal witnesses and not a convergence theorem. Nominal
RK4 and corner trajectories are diagnostic only.

## Reproduction

Use new output paths for generated files. From the repository root:

```sh
set -eu
RUN_DIR=/absolute/new/path/to/spacecraft-v175-run
mkdir -p "$RUN_DIR"
/usr/bin/python3 -I -B release/tools/spacecraft_burn_proof_identity.py generate \
  --output "$RUN_DIR/spacecraft_burn_proof_identity_v1.json"
PROOF_FILE_SHA=$(shasum -a 256 "$RUN_DIR/spacecraft_burn_proof_identity_v1.json" | awk '{print $1}')
PROOF_IDENTITY_SHA=$(/usr/bin/python3 -E -s -S -B -c \
  'import json,sys; print(json.load(open(sys.argv[1]))["identity_digest_sha256"])' \
  "$RUN_DIR/spacecraft_burn_proof_identity_v1.json")
/usr/bin/python3 -E -s -S -B spacecraft_burn_cert/certify.py \
  --output "$RUN_DIR/baseline_receipt_v2.json" \
  --witness "$RUN_DIR/baseline_witness_v2.cert" \
  --checker proofs/lean/.lake/build/bin/jackal_spacecraft_burn_check \
  --proof-identity "$RUN_DIR/spacecraft_burn_proof_identity_v1.json" \
  --request-digest 03bcad618ad60114007c74a384eb8c9432e3755b817e74bd5bdc9bd1ba6df3e7 \
  --model-id jackal-spacecraft-finite-burn-ode-v2 --epoch v1.7.5 \
  --nonce spacecraft-burn-v2-publication-20260825
RECEIPT_SHA=$(shasum -a 256 "$RUN_DIR/baseline_receipt_v2.json" | awk '{print $1}')
# Diagnostic only; the outer verifier below is authoritative.
proofs/lean/.lake/build/bin/jackal_spacecraft_burn_check \
  "$RUN_DIR/baseline_witness_v2.cert" \
  03bcad618ad60114007c74a384eb8c9432e3755b817e74bd5bdc9bd1ba6df3e7 \
  jackal-spacecraft-finite-burn-ode-v2 v1.7.5
/usr/bin/python3 -E -s -S -B spacecraft_burn_cert/verify_receipt.py \
  "$RUN_DIR/baseline_receipt_v2.json" --source spacecraft_burn_cert/certify.py \
  --request spacecraft_burn_cert/request_v2.json \
  --witness "$RUN_DIR/baseline_witness_v2.cert" \
  --checker proofs/lean/.lake/build/bin/jackal_spacecraft_burn_check \
  --proof-identity "$RUN_DIR/spacecraft_burn_proof_identity_v1.json" \
  --expected-receipt-sha256 "$RECEIPT_SHA" \
  --expected-proof-file-sha256 "$PROOF_FILE_SHA" \
  --expected-proof-identity-sha256 "$PROOF_IDENTITY_SHA" \
  --expected-request-digest 03bcad618ad60114007c74a384eb8c9432e3755b817e74bd5bdc9bd1ba6df3e7 \
  --expected-model-id jackal-spacecraft-finite-burn-ode-v2 \
  --expected-epoch v1.7.5 --nonce spacecraft-burn-v2-publication-20260825 \
  --output "$RUN_DIR/independent_verification_v2.json"
/usr/bin/python3 -E -s -S -B spacecraft_burn_cert/validate.py \
  --baseline "$RUN_DIR/baseline_receipt_v2.json" \
  --output "$RUN_DIR/instrument_validation_v2.json"
/usr/bin/python3 -E -s -S -B tools/spacecraft_burn_release_gate.py
```

Release publication must include the full witness asset and verify downloaded
bytes against the committed manifest and release `SHA256SUMS`.
