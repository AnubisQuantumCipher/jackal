# Spacecraft Burn Formal Certification v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a source-visible, Lean-checked spacecraft finite-burn certificate whose only positive public verdict is model-conditional `CERTIFIED SAFE`, with Python removed from the mathematical trusted base.

**Architecture:** The existing Python program becomes an untrusted complete-witness producer. A canonical bounded codec feeds a narrow Lean executable that checks every interval, Picard tube, branch, cutoff cell, orbital transformation, and lower-margin decision; a proved soundness theorem connects acceptance to the stated ODE-model safety proposition. An outer Python verifier binds request, witness, checker, proof identity, and receipt bytes and refuses every mismatch without downgrade.

**Tech Stack:** Python 3 standard library, Lean 4.32.0, Mathlib v4.32.0 (`Mathlib.Analysis.ODE.PicardLindelof` and `Mathlib.Analysis.ODE.ExistUnique`), GitHub Actions on Ubuntu and macOS, SHA-256 artifact identities.

---

## File Map

Create or modify these focused units:

```text
spacecraft_burn_cert/
  README.md                         public runbook and assurance boundary
  REPORT.md                         current v2 result and non-claims
  certify.py                        untrusted witness/receipt producer
  witness_codec.py                  canonical bounded witness writer/parser
  verify_receipt.py                 outer caller-pinned verification authority
  validate.py                       instrument controls at correct classes
  mutation_aba.py                   exact A-B-A adversarial campaign
  evidence/
    legacy-v1/                      immutable supplied v1 evidence and manifest
    baseline_witness_v2.txt         complete formal witness
    baseline_receipt_v2.json        model-conditional receipt
    independent_verification_v2.json
    instrument_validation_v2.json
    mutation_aba_v2.json
    SHA256SUMS
  tests/
    test_claim_vocabulary.py
    test_witness_codec.py
    test_certifier.py
    test_verifier.py
    test_validation.py
    test_mutations.py
proofs/lean/JackalIv/Spacecraft/
  Types.lean                        request, interval, box, witness types
  Interval.lean                     executable dyadic ops and soundness
  VectorField.lean                  ODE model and regularity/domain proofs
  Picard.lean                       enclosure, endpoint, existence, composition
  Orbit.lean                        orbital algebra and safety-margin soundness
  CertCodec.lean                    canonical bounded witness parser
  CertCheck.lean                    Boolean/Except acceptance checker
  CertSound.lean                    acceptance-to-safety theorem
  CertMain.lean                     narrow checker CLI
proofs/lean/JackalIv.lean            import spacecraft proof surface
proofs/lean/lakefile.toml            add checker executable target
release/tools/spacecraft_burn_proof_identity.py
release/evidence/spacecraft_burn_proof_identity_v1.json
release/evidence/spacecraft_burn_independent_review_v1.md
tests/spacecraft_burn_proof_identity_test.py
tests/spacecraft_burn_release_gate_test.py
tools/spacecraft_burn_release_gate.py
.github/workflows/spacecraft-burn-proof-gate.yml
plugins/jackel/skills/jackel/SKILL.md
README.md
```

The supplied v1 evidence is copied byte-for-byte into `evidence/legacy-v1/` and
never regenerated. All current evidence uses new v2 filenames.

### Task 1: Import and quarantine the supplied v1 package

**Files:**
- Create: `spacecraft_burn_cert/` from the supplied review directory
- Create: `spacecraft_burn_cert/evidence/legacy-v1/MANIFEST.sha256`
- Modify: `spacecraft_burn_cert/README.md`
- Test: `spacecraft_burn_cert/tests/test_claim_vocabulary.py`

- [ ] **Step 1: Copy the supplied package without changing its source bytes**

Use `cp -pR` from the attached review directory, then move the five supplied
JSON evidence files and `SHA256SUMS` under `evidence/legacy-v1/`. Record the
pre-copy and post-copy SHA-256 values and require exact equality.

- [ ] **Step 2: Write the failing legacy-quarantine test**

```python
def test_v1_evidence_is_quarantined_and_not_current():
    root = Path(__file__).resolve().parents[1]
    legacy = root / "evidence" / "legacy-v1"
    assert (legacy / "baseline_receipt.json").is_file()
    assert not (root / "evidence" / "baseline_receipt.json").exists()
    assert json.loads((legacy / "baseline_receipt.json").read_text())["verdict"] == "PROVED SAFE"
```

- [ ] **Step 3: Run the test and verify the expected failure**

Run:

```sh
/opt/homebrew/bin/python3 -B -m unittest spacecraft_burn_cert.tests.test_claim_vocabulary -v
```

Expected: failure because the evidence has not yet been quarantined.

- [ ] **Step 4: Generate the legacy manifest mechanically**

Use a small checked helper inside the test module to sort relative paths and
derive SHA-256 rows from bytes. The committed manifest must reproduce exactly;
no digest is typed by hand.

- [ ] **Step 5: Run the supplied 13-test baseline and quarantine test**

Expected: 14 tests pass with no v2 assurance claim yet.

- [ ] **Step 6: Commit the immutable import**

```sh
git add spacecraft_burn_cert/README.md spacecraft_burn_cert/REPORT.md \
  spacecraft_burn_cert/certify.py spacecraft_burn_cert/validate.py \
  spacecraft_burn_cert/verify_receipt.py spacecraft_burn_cert/mutation_aba.py \
  spacecraft_burn_cert/tests/test_certifier.py \
  spacecraft_burn_cert/tests/test_verifier.py \
  spacecraft_burn_cert/tests/test_validation.py \
  spacecraft_burn_cert/tests/test_mutations.py \
  spacecraft_burn_cert/tests/test_claim_vocabulary.py \
  spacecraft_burn_cert/evidence/legacy-v1
git commit -m "test(spacecraft): import and quarantine v1 evidence"
```

### Task 2: Migrate the public claim and receipt schema to v2

**Files:**
- Modify: `spacecraft_burn_cert/certify.py`
- Modify: `spacecraft_burn_cert/verify_receipt.py`
- Modify: `spacecraft_burn_cert/validate.py`
- Modify: `spacecraft_burn_cert/mutation_aba.py`
- Modify: `spacecraft_burn_cert/tests/test_claim_vocabulary.py`
- Modify: `spacecraft_burn_cert/tests/test_certifier.py`
- Modify: `spacecraft_burn_cert/tests/test_verifier.py`

- [ ] **Step 1: Write failing vocabulary tests**

```python
SAFE = "CERTIFIED SAFE"
QUALIFIER = (
    "under the stated finite-burn ODE model, supplied input bounds, "
    "and machine-checked interval-certificate assumptions"
)

def test_positive_result_is_model_conditional():
    c = load_certifier(self)
    result = c.classify_margin(c.DInterval.point(Fraction(1)))
    self.assertEqual(result["verdict"], SAFE)
    self.assertEqual(result["qualifier"], QUALIFIER)

def test_unsafe_label_is_not_implemented_in_v2():
    c = load_certifier(self)
    result = c.classify_margin(c.DInterval.point(Fraction(-1)))
    self.assertEqual(result["verdict"], "INDETERMINATE")
```

- [ ] **Step 2: Verify RED**

Expected: `classify_margin` is missing and the old code returns
`PROVED SAFE`/`PROVED UNSAFE`.

- [ ] **Step 3: Implement the v2 vocabulary**

```python
SCHEMA_V2 = "spacecraft-finite-burn-formal-receipt-v2"
VERDICT_CERTIFIED_SAFE = "CERTIFIED SAFE"
VERDICT_INDETERMINATE = "INDETERMINATE"
MODEL_QUALIFIER = (
    "under the stated finite-burn ODE model, supplied input bounds, "
    "and machine-checked interval-certificate assumptions"
)

def classify_margin(margin: DInterval) -> dict[str, str]:
    if reported_lower_bound(margin) > 0:
        return {"verdict": VERDICT_CERTIFIED_SAFE, "qualifier": MODEL_QUALIFIER}
    return {"verdict": VERDICT_INDETERMINATE, "qualifier": MODEL_QUALIFIER}
```

The producer must also record `producer_assurance = "candidate-only"` and
`formal_checker_status = "NOT_EXECUTED"`; it cannot set `formal-bounded`.

- [ ] **Step 4: Make the verifier refuse v1**

Add an early exact-schema check returning
`legacy-unproved-verdict-schema` for v1 and `receipt-schema-mismatch` for every
other unsupported schema.

- [ ] **Step 5: Run vocabulary, certifier, and verifier tests**

Expected: all pass; a source scan outside `evidence/legacy-v1/` finds no old
verdict token.

- [ ] **Step 6: Commit**

```sh
git add spacecraft_burn_cert/certify.py spacecraft_burn_cert/verify_receipt.py \
  spacecraft_burn_cert/validate.py spacecraft_burn_cert/mutation_aba.py \
  spacecraft_burn_cert/tests/test_claim_vocabulary.py \
  spacecraft_burn_cert/tests/test_certifier.py \
  spacecraft_burn_cert/tests/test_verifier.py
git commit -m "fix(spacecraft): make safety verdict model conditional"
```

### Task 3: Add the canonical complete witness codec

**Files:**
- Create: `spacecraft_burn_cert/witness_codec.py`
- Create: `spacecraft_burn_cert/tests/test_witness_codec.py`
- Modify: `spacecraft_burn_cert/certify.py`

- [ ] **Step 1: Write failing canonical-codec tests**

Cover exact header magic `jackal-spacecraft-burn-cert v2`, ASCII-only tokens,
canonical signed decimal integers, fixed five-component boxes, exact field
counts, branch/step ordering, record and byte ceilings, duplicate terminal
records, truncated input, trailing bytes, and round-trip byte equality.

```python
def test_canonical_round_trip_is_byte_exact(self):
    encoded = codec.encode_witness(minimal_witness())
    self.assertEqual(codec.encode_witness(codec.decode_witness(encoded)), encoded)

def test_duplicate_terminal_record_refuses(self):
    encoded = codec.encode_witness(minimal_witness())
    with self.assertRaisesRegex(codec.WitnessRefusal, "duplicate-terminal"):
        codec.decode_witness(encoded + encoded.splitlines(keepends=True)[-1])
```

- [ ] **Step 2: Verify RED**

Expected: import failure for missing `witness_codec.py`.

- [ ] **Step 3: Implement one canonical line grammar**

Use length-prefixed ASCII records rather than JSON. Define frozen dataclasses
`Interval`, `Box`, `StepWitness`, `BranchWitness`, `OrbitWitness`, and
`BurnWitness`. Decode with explicit aggregate limits before allocation. Reject
`+0`, `-0`, leading zeros, non-ASCII, blank records, and unknown tags.

- [ ] **Step 4: Emit every accepted Picard witness**

Change `certify()` to return `(receipt, BurnWitness)`. Record every branch's
initial sub-box and every step's initial, tube, endpoint, denominator lower
bounds, cutoff membership, and post-processing intervals. Reconcile exactly:
`branches = 32`, `steps_per_branch = 3888`, `steps = 124416`, and cutoff cells
`= 3072`.

- [ ] **Step 5: Verify determinism and complete coverage**

Generate twice in separate temporary directories and require `cmp` success.
Delete one step and verify decode or semantic validation refuses.

- [ ] **Step 6: Commit**

```sh
git add spacecraft_burn_cert/witness_codec.py \
  spacecraft_burn_cert/tests/test_witness_codec.py spacecraft_burn_cert/certify.py
git commit -m "feat(spacecraft): emit canonical complete Picard witnesses"
```

### Task 4: Define Lean witness types and a strict codec

**Files:**
- Create: `proofs/lean/JackalIv/Spacecraft/Types.lean`
- Create: `proofs/lean/JackalIv/Spacecraft/CertCodec.lean`
- Create: `proofs/lean/JackalIv/Spacecraft/CodecFixtures.lean`
- Modify: `proofs/lean/JackalIv.lean`

- [ ] **Step 1: Add failing Lean codec fixtures**

Define `minimalBytes`, `duplicateTerminalBytes`, `noncanonicalIntegerBytes`,
and `trailingBytes`, then assert with `example` that only `minimalBytes`
parses. Importing the missing modules must fail.

- [ ] **Step 2: Verify RED**

Run:

```sh
cd proofs/lean && lake env lean JackalIv/Spacecraft/CodecFixtures.lean
```

Expected: missing-module failure.

- [ ] **Step 3: Define exact types**

```lean
namespace JackalIv.Spacecraft

structure DInterval where lo hi : Int deriving DecidableEq, Repr
abbrev Box := Fin 5 → DInterval

structure StepWitness where
  branch step : Nat
  initial tube endpoint : Box
  r2Lo v2Lo massLo : Int
  cutoff : Bool
  deriving DecidableEq, Repr

structure BurnWitness where
  scaleBits : Nat
  stepNum stepDen : Nat
  branches steps cutoffCells : Nat
  stepWitnesses : List StepWitness
  deriving DecidableEq, Repr

end JackalIv.Spacecraft
```

- [ ] **Step 4: Implement the proved parser**

Follow the existing `CertCodec.lean` pattern: total `Except String`, no
`unsafe`, no `native_decide`, no `@[implemented_by]`, and no alternate release
parser. Enforce all Python codec ceilings and canonicality in the same
definition used by the executable checker.

- [ ] **Step 5: Verify GREEN and admission scan**

Run the fixture file, `lake build`, and `tools/lean_admission_audit.py
--source-check`.

- [ ] **Step 6: Commit**

```sh
git add proofs/lean/JackalIv/Spacecraft/Types.lean \
  proofs/lean/JackalIv/Spacecraft/CertCodec.lean \
  proofs/lean/JackalIv/Spacecraft/CodecFixtures.lean proofs/lean/JackalIv.lean
git commit -m "feat(proof): define spacecraft witness codec"
```

### Task 5: Prove dyadic interval arithmetic sound

**Files:**
- Create: `proofs/lean/JackalIv/Spacecraft/Interval.lean`
- Create: `proofs/lean/JackalIv/Spacecraft/IntervalFixtures.lean`

- [ ] **Step 1: Write failing containment fixtures**

Exercise negative and positive endpoints for add, negation, subtraction,
multiplication, division with sign-separated denominator, square, hull,
intersection, and integer square root. Add a deliberate inward-rounded fixture
that must be rejected.

- [ ] **Step 2: Verify RED**

Expected: missing definitions such as `mem_add` and `sqrt_contains`.

- [ ] **Step 3: Implement executable operations over scaled integers**

Use `scale : Int := 2 ^ scaleBits`; define floor/ceiling division explicitly.
Every operation returns `Except Refusal DInterval` when its domain check can
fail. Keep executable arithmetic over `Int`; use casts to `ℚ` and `ℝ` only in
soundness statements.

- [ ] **Step 4: Prove the operator lemmas**

The exported theorem set must include:

```lean
theorem add_sound      : x ∈ᵢ a → y ∈ᵢ b → x + y ∈ᵢ add a b
theorem mul_sound      : x ∈ᵢ a → y ∈ᵢ b → x * y ∈ᵢ mul a b
theorem div_sound      : 0 ∉ᵢ b → x ∈ᵢ a → y ∈ᵢ b → x / y ∈ᵢ div a b
theorem square_sound   : x ∈ᵢ a → x ^ 2 ∈ᵢ square a
theorem sqrt_sound     : 0 ≤ x → x ∈ᵢ a → Real.sqrt x ∈ᵢ sqrt a
theorem hull_sound_left  : x ∈ᵢ a → x ∈ᵢ hull a b
theorem hull_sound_right : x ∈ᵢ b → x ∈ᵢ hull a b
```

Each theorem is proved from integer inequalities; none is a checker
hypothesis.

- [ ] **Step 5: Run fixtures, build, and `#print axioms`**

Expected theorem dependencies are limited to standard Lean foundations.

- [ ] **Step 6: Commit**

```sh
git add proofs/lean/JackalIv/Spacecraft/Interval.lean \
  proofs/lean/JackalIv/Spacecraft/IntervalFixtures.lean
git commit -m "proof(spacecraft): verify dyadic interval arithmetic"
```

### Task 6: Formalize the ODE vector field and regularity domain

**Files:**
- Create: `proofs/lean/JackalIv/Spacecraft/VectorField.lean`
- Create: `proofs/lean/JackalIv/Spacecraft/VectorFieldFixtures.lean`

- [ ] **Step 1: Write failing domain and unit fixtures**

Assert the exact constants, thrust N-to-km conversion `1/1000`, mass loss
`-T/(Isp*g0)`, five state coordinates, and refusal whenever `r²`, `v²`, or
mass can contain zero. A meters-as-kilometers mutation must not satisfy the
request matcher.

- [ ] **Step 2: Verify RED**

Expected: missing `burnField`, `modelMatches`, and `fieldEnclosed`.

- [ ] **Step 3: Define the real model and interval extension**

Use `Fin 5 → ℝ` for the state and a time-independent field during each branch.
Define the exact ODE formula from the supplied constants and a separate
executable interval extension. Prove `fieldEnclosed` from Task 5 operator
lemmas.

- [ ] **Step 4: Prove continuity and local Lipschitz obligations**

On every accepted tube with positive `r²`, `v²`, and mass lower bounds, prove
the vector field is `ContDiffOn ℝ 1` and derive the `LipschitzOnWith` and norm
bounds required by `ODE.IsPicardLindelof`.

- [ ] **Step 5: Run fixtures, build, and axiom audit**

Import `Mathlib.Analysis.ODE.ExistUnique` directly so the exact upstream
existence theorem is in the source closure.

- [ ] **Step 6: Commit**

```sh
git add proofs/lean/JackalIv/Spacecraft/VectorField.lean \
  proofs/lean/JackalIv/Spacecraft/VectorFieldFixtures.lean
git commit -m "proof(spacecraft): verify burn vector-field domain"
```

### Task 7: Prove the Picard enclosure and finite-step composition

**Files:**
- Create: `proofs/lean/JackalIv/Spacecraft/Picard.lean`
- Create: `proofs/lean/JackalIv/Spacecraft/PicardFixtures.lean`

- [ ] **Step 1: Write failing one-step and broken-chain fixtures**

Create one accepted constant-field step, one tube whose mapping touches the
outer boundary, one incorrect endpoint, and two individually valid steps with
a broken chain. Only the first may check.

- [ ] **Step 2: Verify RED**

Expected: missing `checkStep`, `picard_tube_encloses`, and
`checked_steps_compose`.

- [ ] **Step 3: Implement the exact step decision**

`checkStep` must recompute `hull(initial, initial + [0,h] * field(tube))`,
require strict interior inclusion, recompute the endpoint enclosure using
`[h,h]`, check denominator domains, and require exact branch/step continuity.

- [ ] **Step 4: Prove enclosure without a project-local Picard axiom**

Use `ODE.picard_eq_of_hasDerivAt` for arbitrary classical solutions and a
first-exit argument over the strict tube interior. Separately instantiate
`ODE.IsPicardLindelof.exists_eq_forall_mem_Icc_hasDerivWithinAt` to prove local
existence from the Task 6 regularity and norm bounds. Export:

```lean
theorem picard_tube_encloses
    (hcheck : checkStep request step = .ok ())
    (hsol : IsClassicalSolution request step.initial α) :
    ∀ t ∈ Set.Icc (0 : ℝ) request.h, α t ∈ᵦ step.tube

theorem picard_endpoint_encloses
    (hcheck : checkStep request step = .ok ())
    (hsol : IsClassicalSolution request step.initial α) :
    α request.h ∈ᵦ step.endpoint

theorem checked_steps_compose
    (hcheck : checkSteps request steps = .ok ()) :
    EveryAdmissibleTrajectoryIsEnclosed request steps
```

- [ ] **Step 5: Prove non-vacuity**

Export an existence theorem for each accepted step and prove the checked chain
constructs at least one solution over the full burn interval. The universal
safety theorem must not be true merely because `IsClassicalSolution` is empty.

- [ ] **Step 6: Run fixtures, full build, and theorem axiom output**

Reject any `sorryAx`, project-local axiom, or theorem that assumes the desired
enclosure conclusion.

- [ ] **Step 7: Commit**

```sh
git add proofs/lean/JackalIv/Spacecraft/Picard.lean \
  proofs/lean/JackalIv/Spacecraft/PicardFixtures.lean
git commit -m "proof(spacecraft): verify Picard tube composition"
```

### Task 8: Prove cutoff coverage and orbital post-processing

**Files:**
- Create: `proofs/lean/JackalIv/Spacecraft/Orbit.lean`
- Create: `proofs/lean/JackalIv/Spacecraft/OrbitFixtures.lean`

- [ ] **Step 1: Write failing coverage and orbital mutations**

Cover missing cutoff cells, duplicated branch IDs, wrong energy factor,
`a(1-e)`, empty eccentricity intersection, unit mismatch, and upward-rounded
margin. Include the exact four polynomial identities checked by the Python v1
verifier.

- [ ] **Step 2: Verify RED**

Expected: missing coverage and orbital checker definitions.

- [ ] **Step 3: Implement exact coverage decisions**

Require the exact Cartesian partition `(4,1,1,2,2,2)`, 32 branches, 3,888
steps per branch, 96 cutoff cells per branch, and complete coverage of
`[118.5,121.5]` at `h=1/32`.

- [ ] **Step 4: Prove the orbital chain**

Prove the radius, energy, semimajor axis, angular momentum, both eccentricity
routes, intersection, apoapsis, altitude, and margin enclosures. Derive the
four polynomial identities within Lean rather than trusting recorded booleans.

- [ ] **Step 5: Prove the conditional safety theorem**

```lean
theorem orbit_margin_positive_implies_safe
    (hcheck : checkOrbit request witness = .ok margin)
    (hpositive : 0 < margin.lo) :
    ∀ trajectory, AdmissibleTrajectory request trajectory →
      ApoapsisAltitude trajectory ≥ 1000
```

- [ ] **Step 6: Run fixtures, build, and axiom audit**

Expected: every deliberate mutation refuses and theorem dependencies remain
within the approved foundation set.

- [ ] **Step 7: Commit**

```sh
git add proofs/lean/JackalIv/Spacecraft/Orbit.lean \
  proofs/lean/JackalIv/Spacecraft/OrbitFixtures.lean
git commit -m "proof(spacecraft): verify cutoff and orbital safety"
```

### Task 9: Build the release checker and central soundness theorem

**Files:**
- Create: `proofs/lean/JackalIv/Spacecraft/CertCheck.lean`
- Create: `proofs/lean/JackalIv/Spacecraft/CertSound.lean`
- Create: `proofs/lean/JackalIv/Spacecraft/CertMain.lean`
- Modify: `proofs/lean/lakefile.toml`
- Modify: `proofs/lean/JackalIv.lean`

- [ ] **Step 1: Write failing checker acceptance/refusal tests**

The release CLI accepts exactly:

```text
jackal_spacecraft_burn_check <witness> <request-digest> <model-id> <epoch>
```

Success output is one canonical line beginning
`ACCEPT theorem=spacecraft_burn_certified_safe`; every other path writes one
bounded `REJECT <reason>` line to stderr and exits nonzero.

- [ ] **Step 2: Verify RED**

Expected: missing lake target and executable.

- [ ] **Step 3: Implement `checkBurnCert` and the CLI**

The checker must use the exact proved parser and decisions. It may not call
Python, use an alternate parser, use `native_decide`, or use an
`@[implemented_by]` release path.

- [ ] **Step 4: Prove the central theorem**

```lean
theorem spacecraft_burn_certified_safe
    (h : checkBurnCert raw requestDigest modelId epoch = .ok accepted) :
    ModelConditionalSafe accepted.request accepted.margin
```

`ModelConditionalSafe` must include existence and universal safety of all
admissible classical solutions, not only checker bookkeeping.

- [ ] **Step 5: Build the exact executable and print axioms**

```sh
cd proofs/lean
lake build jackal_spacecraft_burn_check
lake env lean JackalIv/Spacecraft/CertSound.lean
```

The source file ends with `#print axioms` for the central theorem and all
load-bearing subtheorems.

- [ ] **Step 6: Commit**

```sh
git add proofs/lean/JackalIv/Spacecraft/CertCheck.lean \
  proofs/lean/JackalIv/Spacecraft/CertSound.lean \
  proofs/lean/JackalIv/Spacecraft/CertMain.lean \
  proofs/lean/lakefile.toml proofs/lean/JackalIv.lean
git commit -m "feat(proof): add spacecraft burn release checker"
```

### Task 10: Bind proof identity and outer verification

**Files:**
- Create: `release/tools/spacecraft_burn_proof_identity.py`
- Create: `release/evidence/spacecraft_burn_proof_identity_v1.json`
- Create: `tests/spacecraft_burn_proof_identity_test.py`
- Modify: `spacecraft_burn_cert/verify_receipt.py`
- Modify: `spacecraft_burn_cert/tests/test_verifier.py`

- [ ] **Step 1: Write failing identity and outer-verifier tests**

Mutate checker bytes, one Lean dependency, theorem name, witness bytes,
request digest, model ID, epoch, qualifier, result line, and receipt digest.
Every mutation must refuse with a distinct stable reason.

- [ ] **Step 2: Verify RED**

Expected: missing proof-identity lane and absent caller pins.

- [ ] **Step 3: Add the proof-identity lane**

Reuse the existing proof-identity engine with root module
`JackalIv.Spacecraft.CertMain`, executable
`jackal_spacecraft_burn_check`, Boolean/Except checker
`JackalIv.Spacecraft.checkBurnCert`, and soundness theorem
`JackalIv.Spacecraft.spacecraft_burn_certified_safe`. List every load-bearing
theorem and require no unlisted local trust construct.

- [ ] **Step 4: Make the outer verifier authoritative**

Require explicit caller arguments for witness, source, checker, proof identity,
expected proof file digest, expected internal identity digest, expected request
digest, model ID, epoch, and nonce. Recompute every file digest, invoke the
checker once with a sanitized environment, require its exact output, and
compare the receipt to checker-authoritative fields.

- [ ] **Step 5: Generate identity mechanically and check reproduction**

```sh
python3 release/tools/spacecraft_burn_proof_identity.py generate
python3 release/tools/spacecraft_burn_proof_identity.py check
```

- [ ] **Step 6: Commit**

```sh
git add release/tools/spacecraft_burn_proof_identity.py \
  release/evidence/spacecraft_burn_proof_identity_v1.json \
  tests/spacecraft_burn_proof_identity_test.py \
  spacecraft_burn_cert/verify_receipt.py \
  spacecraft_burn_cert/tests/test_verifier.py
git commit -m "feat(spacecraft): bind formal checker receipts"
```

### Task 11: Regenerate v2 evidence and adversarial controls

**Files:**
- Modify: `spacecraft_burn_cert/validate.py`
- Modify: `spacecraft_burn_cert/mutation_aba.py`
- Modify: `spacecraft_burn_cert/tests/test_validation.py`
- Modify: `spacecraft_burn_cert/tests/test_mutations.py`
- Create: `spacecraft_burn_cert/evidence/baseline_witness_v2.txt`
- Create: `spacecraft_burn_cert/evidence/baseline_receipt_v2.json`
- Create: `spacecraft_burn_cert/evidence/independent_verification_v2.json`
- Create: `spacecraft_burn_cert/evidence/instrument_validation_v2.json`
- Create: `spacecraft_burn_cert/evidence/mutation_aba_v2.json`
- Create: `spacecraft_burn_cert/evidence/SHA256SUMS`

- [ ] **Step 1: Write failing full-campaign tests**

Require true-answer controls to pass 100%, per-case wrong answers to pass 0%,
all six original mutations plus witness corruption and chain/coverage mutations
to refuse, exact source A-B-A restoration, and baseline acceptance before and
after the campaign.

- [ ] **Step 2: Verify RED**

Expected: current validation still expects old verdicts and lacks formal
checker evidence.

- [ ] **Step 3: Route every decisive result through the Lean checker**

Nominal RK4 and corner samples remain diagnostics. Step-size variants remain
rigorous interval cross-checks unless each has its own accepted formal witness.

- [ ] **Step 4: Generate all evidence into a temporary directory**

Run producer, checker, outer verifier, validation, and mutations. Only after
every command exits zero, atomically replace the new v2 evidence files and
derive `SHA256SUMS` from bytes.

- [ ] **Step 5: Reproduce every committed artifact in `--check` mode**

Run generation twice and require exact byte equality, including the complete
124,416-step witness.

- [ ] **Step 6: Commit**

Stage each named source, test, and v2 evidence file explicitly and commit with
exact test totals, checker digest, proof-identity digests, witness digest, and
decisive lower-bound receipt digest.

### Task 12: Align documentation, plugin skill, and claim surfaces

**Files:**
- Modify: `spacecraft_burn_cert/README.md`
- Modify: `spacecraft_burn_cert/REPORT.md`
- Modify: `README.md`
- Modify: `plugins/jackel/skills/jackel/SKILL.md`
- Create: `tools/spacecraft_burn_release_gate.py`
- Create: `tests/spacecraft_burn_release_gate_test.py`

- [ ] **Step 1: Write the failing claim-surface gate tests**

The scanner excludes only `spacecraft_burn_cert/evidence/legacy-v1/` and its
explicit legacy manifest. Inject each forbidden phrase into a temporary copy
of every publication class and verify the gate detects it.

- [ ] **Step 2: Verify RED against the current imported prose**

Expected: current report and README contain forbidden unqualified language.

- [ ] **Step 3: Rewrite current prose to the exact v2 contract**

Put the model qualifier adjacent to every positive verdict. Add a table that
separates formal theorem, executable checker, artifact binding, independent
review, model assumptions, and real-world non-claims.

- [ ] **Step 4: Update the JACKEL routing skill**

Document the new lane only if its command is actually exposed through the
41-tool surface. If no tool is added in this release, document the repo-local
CLI without claiming plugin reachability. Any tool addition requires a
separate mechanically derived capability-inventory update and cachebuster.

- [ ] **Step 5: Run the claim gate and plugin validation**

Expected: forbidden current-surface count zero, plugin validator pass, skill
validator pass, capability drift pass at its mechanically derived count.

- [ ] **Step 6: Commit**

```sh
git add spacecraft_burn_cert/README.md spacecraft_burn_cert/REPORT.md README.md \
  plugins/jackel/skills/jackel/SKILL.md tools/spacecraft_burn_release_gate.py \
  tests/spacecraft_burn_release_gate_test.py
git commit -m "docs(spacecraft): publish model-conditional assurance boundary"
```

### Task 13: Add hosted gates and complete an independent review

**Files:**
- Create: `.github/workflows/spacecraft-burn-proof-gate.yml`
- Modify: `.github/workflows/gaussian-proof-gate.yml`
- Create: `release/evidence/spacecraft_burn_independent_review_v1.md`

- [ ] **Step 1: Write failing workflow-mechanics tests**

Assert the workflow builds the exact checker target, runs identity and axiom
gates, executes full witness generation/checking, runs mutation controls,
checks evidence reproduction, and runs the claim-surface gate.

- [ ] **Step 2: Verify RED**

Expected: workflow file is absent.

- [ ] **Step 3: Add the bounded hosted workflow**

Use pinned action SHAs and explicit timeouts. Upload evidence logs only; do
not modify committed evidence in CI.

- [ ] **Step 4: Run an isolated independent review**

The reviewer receives the approved design, exact candidate commit, proof
closure, checker, witness, tests, and claim surfaces. The report records each
finding as `resolved`, `release-blocking`, or `residual-non-claim`, with exact
file/line evidence and commands. Internal review must not be called external
peer review.

- [ ] **Step 5: Fix every release-blocking finding with new tests first**

Each fix is a new commit; do not amend a pushed review checkpoint.

- [ ] **Step 6: Rerun the independent review on the final candidate**

The final report must bind the exact reviewed commit and record zero unresolved
release-blocking findings.

- [ ] **Step 7: Commit and push the review checkpoint**

Stage the workflows, workflow tests, and review report by name; push the branch
as explicitly non-final.

### Task 14: Full completion audit, PR, merge, tag, and release readback

**Files:**
- Modify only mechanically derived release/version files identified by the
  compatibility and release audit
- Create release assets in a temporary directory outside the repository

- [ ] **Step 1: Audit every design completion criterion**

Build a requirement-to-evidence table from the approved design. Mark missing,
weak, or indirect evidence as incomplete and continue work until every row has
authoritative current-state proof.

- [ ] **Step 2: Run all local gates fresh**

At minimum: full Lean build; theorem axiom/identity checks; admission audit;
all spacecraft tests; full witness/checker/verifier replay; mutation campaign;
evidence reproduction; claim-surface gate; capability drift; full Codex plugin
suite; plugin and skill validators; `git diff --check`; clean status.

- [ ] **Step 3: Freeze exact bytes and select the version from impact**

Inspect compatibility. Derive any manifest, package, plugin cachebuster, and
release version through owning tools. Never type pinned digests by hand.

- [ ] **Step 4: Push, open the PR, and wait for every hosted check**

The PR body lists exact theorem names, axiom sets, test totals, artifact hashes,
assumptions, non-claims, and independent-review disposition. Do not merge with
pending or red checks.

- [ ] **Step 5: Merge using repository convention**

Re-query mergeability and checks immediately before merging. Record the merge
commit and fast-forward the clean local `master` worktree only.

- [ ] **Step 6: Create an annotated tag and release assets**

Bind the tag to the merge commit. Assets include the witness, receipt, proof
identity, checker/verifier package as appropriate, independent review,
verification instructions, and `SHA256SUMS`.

- [ ] **Step 7: Publish and read back**

Download every GitHub asset into a fresh temporary directory, compare bytes
and SHA-256 values to the locally verified artifacts, verify the tag resolves
to the merge commit, and confirm release metadata and Latest status are
intentional.

- [ ] **Step 8: Final state audit**

Confirm implementation and `master` worktrees are clean, remote refs are
coherent, the historical dirty checkout still contains only its protected
untracked material plus the pre-existing review copy, and the installed plugin
state matches any deliberately published cachebuster.
