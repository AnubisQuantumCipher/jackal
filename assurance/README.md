# JACKAL functional-proof baseline

`requirements.json` is the machine-readable source for allocated functional
requirements, component claims, and whole-surface closure status.

The current universally quantified proofs apply to the total SPARK interval
decision kernel and to the finite claim-assurance policy kernel over their
complete declared input types. The claim-policy bridge also exhaustively checks
the current producer and independent verifier registries against the proved
SPARK truth table. The whole JACKAL product target is in progress. The closure
matrix deliberately exposes every sealed
runtime dependency family and every additive Codex tool group; it cannot become
a whole-product claim until all discovered entries are `proved-universal` and
all requirements are proved.

Run:

```sh
python3 -B tools/check_assurance_traceability.py
proofs/spark/hellgate_interval/prove.sh
proofs/spark/claim_policy/prove.sh
python3 -B -m unittest tests.claim_policy_conformance_test -v
```

The traceability gate rejects duplicate JSON keys, missing or one-way links,
unknown public surface families, and premature whole-product claims. The proof
gates reject missing tools, warnings, unproved or justified checks, skipped
allocated units, and proof assumptions or annotations.

SPARK Platinum is used only for SPARK components whose contracts fully cover
their allocated functional requirements. Lean mathematical soundness, Anubis
program evidence, independent checker replay, and empirical tests are recorded
as different evidence forms rather than relabeled as SPARK Platinum.
