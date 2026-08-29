# JACKAL functional-proof baseline

`requirements.json` is the machine-readable source for allocated functional
requirements, component claims, and whole-surface closure status.

The current universally quantified proof applies to the total SPARK interval
decision kernel and its complete declared input types. The whole JACKAL product
target is in progress. The closure matrix deliberately exposes every sealed
runtime dependency family and every additive Codex tool group; it cannot become
a whole-product claim until all discovered entries are `proved-universal` and
all requirements are proved.

Run:

```sh
python3 -B tools/check_assurance_traceability.py
proofs/spark/hellgate_interval/prove.sh
```

The traceability gate rejects duplicate JSON keys, missing or one-way links,
unknown public surface families, and premature whole-product claims. The proof
gate rejects missing tools, warnings, unproved or justified checks, a skipped
interval unit, and proof assumptions or annotations.

SPARK Platinum is used only for SPARK components whose contracts fully cover
their allocated functional requirements. Lean mathematical soundness, Anubis
program evidence, independent checker replay, and empirical tests are recorded
as different evidence forms rather than relabeled as SPARK Platinum.
