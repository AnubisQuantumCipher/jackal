# Spacecraft finite-burn formal certificate

Commit-scoped publication state: this source snapshot is the v1.7.5 candidate
prepared before publication. It does not by itself establish current GitHub
release state. Consult the
[v1.7.5 release metadata](https://github.com/AnubisQuantumCipher/jackal/releases/tag/v1.7.5)
and the postpublication readback on `master`; use release assets only when those
current checks bind their exact bytes.

This lane certifies a universal lower bound for the finite-duration periapsis
burn challenge. The publication verdict is:

> CERTIFIED SAFE under the stated finite-burn ODE model, supplied input bounds, and machine-checked interval-certificate assumptions.

The Python producer constructs a candidate certificate using exact integer,
outward-rounded dyadic intervals. It cannot mint `formal-bounded`. The pinned
Lean checker derives the step chain, Picard self-enclosures, cutoff coverage,
orbital bounds, and positive safety margin before an accepted receipt can be
written. The outer verifier independently binds the receipt, witness, checker,
proof identity, request, model, release epoch, and nonce, then replays the
interval calculation.

## Current evidence

- `evidence/baseline_receipt_v2.json`: checker-accepted receipt.
- `evidence/baseline_witness_v2.manifest.json`: digest, size, and counts for the
  full witness release asset. The 35.9 MB witness is intentionally not tracked.
- `evidence/independent_verification_v2.json`: exact outer replay and artifact
  binding.
- `evidence/instrument_validation_v2.json`: arithmetic controls, analytic mass
  reconciliation, step-size cross-checks, and diagnostic trajectories.
- `evidence/mutation_aba_v2.json`: six source mutations plus witness corruption,
  broken chaining, and broken coverage.
- `evidence/SHA256SUMS`: hashes of all committed v2 evidence.
- `evidence/legacy-v1/`: immutable historical evidence; never current authority.

Run the local tests and claim-language gate from the repository root:

```sh
/usr/bin/python3 -E -s -S -B -m unittest discover -s spacecraft_burn_cert/tests -p 'test_*.py' -v
/usr/bin/python3 -E -s -S -B tools/spacecraft_burn_release_gate.py
/usr/bin/python3 -E -s -S -B spacecraft_burn_cert/release_evidence.py \
  --staging-dir /absolute/path/to/release-staging --check
```

The complete pinned checker and verifier commands, assurance boundary, hashes,
and non-claims are recorded in [REPORT.md](REPORT.md).
