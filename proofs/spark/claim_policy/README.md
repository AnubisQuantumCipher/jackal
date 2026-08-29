# SPARK claim-assurance policy kernel

This component specifies JACKAL's finite assurance-axis algebra for
`JCK-CLAIM-001`, `JCK-CLAIM-002`, and `JCK-CLAIM-003`.

It proves the canonical mathematical meet including the shared-rank
`estimated`/`model-based` tie, the provenance/model/implementation meets,
interval-rule mathematical caps, derived-rule implementation caps, preservation
rules, artifact-flag conjunction, termination, and targeted run-time safety.
The mathematical meet is also proved commutative, associative, and idempotent,
so arbitrary parent folds have a stable pairwise foundation.

Run:

```sh
./prove.sh
python3 -B -m unittest tests.claim_policy_conformance_test -v
```

The Python test exhaustively compares every finite vector with the shipped
producer-side claim kernel. That bridge is exhaustive tested conformance, not a
formal Python refinement theorem. JSON parsing, registry-to-rule-category
mapping, hashing, rendering, Python execution, compiler correctness, and the
independent verifier remain separate obligations.
