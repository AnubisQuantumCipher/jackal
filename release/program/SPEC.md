# JACKAL Anubis program-evidence contract v1

## Status vocabulary

A successful program operation returns only `verified-program-evidence` or
`verified-program-receipt`. These statuses describe the checks in this document.
They are not universal soundness, source-native refinement, or runtime claims.

## Public tools

- `jackal_anubis_check_program`: invoke a caller-pinned, policy-approved Anubis
  compiler as `build --evidence`, never run the compiled artifact, then verify
  the emitted evidence.
- `jackal_anubis_verify_program`: verify caller-selected source and evidence
  bytes.
- `jackal_anubis_verify_program_receipt`: recompute the receipt from those
  underlying bytes and independent caller pins.

CLI: `jackal-anubis-program check|verify|verify-receipt`.

## Admitted producer contract

Only `anubis.program-evidence.v3`, `version=3`, and `mode=safe` are admitted.
PCA v2 alone, Research/Exploit modes, partial or unknown stages, zero
obligations, unsupported DRAT/RAT features, and unregistered files refuse
without downgrade.

The admitted profile is `inventory-safe-v1`. The prototype name
`contracted-safe-v1` is refused. The v3 producer exports a whole-function roster
and producer-attested policy-consumer rows, but it does not export independently
checkable construct-total walker coverage. Naming that stronger profile would
therefore outrun the evidence.

The profile admits one sealed source leaf. Multi-source Merkle programs refuse
`multi-source-unsupported` until every source leaf can be independently replayed
against caller-selected bytes.

## Filesystem and manifest

The verifier canonicalizes a bounded regular-file tree and refuses symlinks,
devices, traversal, case-collision aliases, duplicate manifest rows, malformed
hashes, missing files, unlisted files, and registered files outside the closed
roster. `MANIFEST.sha256` must cover every admitted evidence file except itself
exactly once, and every digest must match.

The original evidence tree is copied into a private snapshot after its manifest
is checked. Verification uses the snapshot. Before returning, the original tree
is walked and manifest-verified again; closing drift refuses `snapshot-drift`.

## Caller pins

The caller supplies, rather than copying from the receipt:

- exact source SHA-256;
- Anubis producer executable SHA-256;
- compiled artifact SHA-256;
- `inventory-safe-v1` policy digest;
- profile, nonce, and verification time.

`check` hashes the approved Anubis executable before and after producer
execution, writes only to a new output root, and invokes `build --evidence`.
Neither `check`, `verify`, nor `verify-receipt` executes the compiled artifact.

## Required stage roster

Exactly these twelve rows, in order, all `PASS`:

1. `parse`
2. `typecheck`
3. `monomorphization`
4. `policy-effects`
5. `policy-capability`
6. `policy-information-flow`
7. `policy-declassification`
8. `symbolic`
9. `solver`
10. `source-binding`
11. `artifact-binding`
12. `evidence-closure`

## Policy inventory

The verifier recomputes function IDs from strict HIR JSON and requires the exact
consumer roster:

`effects, capability, information-flow, declassification, mode, contracts`.

Every consumer must be `PASS`. Function-oriented consumers bind the complete
function-ID list. Taint, monomorphization, MIR, declassification, capability,
and contract counts reconcile with their sealed artifacts. These checks bind a
producer-attested inventory; they do not independently establish Anubis policy
semantics or construct-total walker coverage.

The policy document is `release/program/inventory_safe_v1.json`, copied to
`program/inventory_safe_v1.json` in the package. Its self-digest, file digest,
verifier digest, and compatibility floor are release-manifest bound.

## Solver and proof replay

`solver.json`, `analysis/proofs.json`, and the v3 obligation inventory must have
the same nonzero length and exact row order. Names, statuses, unique paths,
SHA-256 digests, content-derived obligation IDs, and counters must match.
Duplicate paths and duplicate `(SMT, CNF, proof)` digest tuples refuse.

Every proof kind is `rup_refutation`. The approved, byte-pinned Z3 executable
must parse each exact SMT file and report only UNSAT (including the producer's
known `get-model`-after-UNSAT diagnostic shape). A trailing error or additional
output refuses.

The dependency-free checker parses bounded DIMACS CNF and independently replays
each proof addition by reverse unit propagation. Each addition must be RUP under
the accumulated clauses and the proof must derive the empty clause. Deletion
lines, RAT-only steps, malformed or tautological clauses, oversized inputs, and
proofs without an empty clause refuse.

Z3 replay and RUP replay do not prove the producer's SMT-to-CNF translation or
its source-to-VC lowering. Both remain explicit residuals.

## Producer-summary reconciliation

The verifier cross-checks `evidence.json`, its byte-identical `manifest.json`,
`pca.json`, the exact program inventory, and the sealed artifacts. Source,
artifact, tool, mode, verdict, required check names/details, build-log,
environment, source-tree, SARIF, bounty-report, manifest-summary, parse/typecheck,
and obligation totals must reconcile. A producer-written `PASS` is never enough
on its own.

## Receipt

`jackal-anubis-program-receipt-v1` binds source/compiler/artifact identities,
evidence-manifest and program-evidence hashes, policy digest and file identity,
stage/policy/proof counters, caller nonce, verification time, assurance vector,
and residuals. `receipt_digest_sha256` is SHA-256 over canonical receipt bytes
with that digest field omitted.

Receipt replay first validates the supplied outer digest, then recomputes the
entire expected receipt from caller-selected source/evidence bytes and caller
pins. An assurance edit with a recomputed outer digest refuses
`receipt-semantic-mismatch`.

## Mandatory residuals

Every successful receipt carries:

- `no-source-to-vc-proof`
- `no-smt-to-cnf-proof`
- `policy-construct-totality-not-established`
- `no-source-native-refinement`
- `no-universal-language-soundness`
- `policy-semantics-producer-attested`
- `runtime-not-observed`
- `derived-confinement-is-not-os-enforcement`

The tool cannot emit `formal-bounded`, `source-native-refined`,
`runtime-verified`, or universal safety language.
