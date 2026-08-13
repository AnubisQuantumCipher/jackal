# JACKAL PROVENANCE — sealed 2026-08-13

The chain the 2026-08-13 field assessment asked for, with every link either
mechanically derived or measured — and the one link that failed measurement
stated as failed rather than papered over.

```text
source commit → compiler hash → build recipe → shipped-binary hash → gate receipts → adjudication
```

## Source

- git commit: `8a71540` (branch `master`, this repository)
- `jackal_calc.anb` SHA-256: `b74d078db6acc7b73f81001ed823643df037e4770b6062c15de411ff571f5384`

## Compiler

- pin: `$HOME/anubis-lang/vm/pins/anubis-51f4a964347a`
- pin SHA-256: `51f4a964347a4a0f3ea2833331eb313315aa502c96c9d7a71fc3b20414eca027`

## Build recipe

```bash
JACKAL_FORCE_SOURCE=1 JACKAL_OUT=./.build ./jackal self-test
cp ./.build/anubis_run ./jackal-native && chmod +x ./jackal-native
```

- shipped `jackal-native` SHA-256: `c37a256c38c5819e24b31c405152fb61fe06bcf4f05550dee9e5c4e8e080c2c2`

### Build determinism — diagnosed precisely (2026-08-13)

Successive builds of identical source produce different binary SHA-256s. The
divergence was traced through the pipeline stage by stage:

1. **Anubis → Rust transpile: byte-deterministic.** Every build of source
   `b74d078d…` emits an identical `anubis_run.rs`, SHA-256
   `3e4fde1eb205242343d9fd62a9401acd5c14592d81e59e0e01921193202ac4ad`.
   This is a verifiable deterministic link: rebuild and compare the `.rs`
   hash in the out-dir.
2. **rustc → binary: nondeterministic layout, identical behavior.** Final
   binaries differ in static/string-pool ordering (plus per-link `LC_UUID`
   and `__LINKEDIT` metadata) across runs of the *same* command — the
   signature of an unpinned rustc compilation-session input
   (`-C metadata`-class) inside the pinned compiler, not of the program
   changing. Machine code behavior is identical: every build passes the
   83-invariant self-test and the external suites.
3. `tests/content_hash.py` hashes only the code/data segments (excluding
   Mach-O headers and linker metadata); repeated builds fall into a small
   family of layout-permuted content hashes. Once the toolchain pins its
   rustc session inputs (upstream anubis-lang fix, filed 2026-08-13), that
   content hash becomes the rebuild-and-verify reproducibility check.

Until that upstream fix lands, the chain binds the exact shipped binary
above — the artifact every gate receipt was produced against — plus the
deterministic transpile hash in (1).

## Gate receipts (2026-08-13, all green)

| Gate | Result |
|---|---|
| `anubis check jackal_calc.anb` (pinned compiler) | passed |
| Native self-test | 83/83 invariants |
| Black-box acceptance suite (`tests/test_calculator.py`, source-built via pin) | TOTAL 198/198, includes 7 enclosure-contains-independent-oracle checks |
| Seeded containment campaign (`tests/bound_campaign.py 250 20260813`, run against `jackal-native` `c37a256c…`) | BOUND_OK=246 REFUSED=4 ORACLE_SKIP=0 **CONTAINMENT_VIOLATION=0 WIDTH_VIOLATION=0** |
| Campaign JSONL (`/tmp/jackal-bound-campaign.jsonl`) SHA-256 | `4473208f8e15715f67734fc14a322afca9c52687448f93f2357768e1d36186fa` |
| Adversarial multi-lens review (4 lenses, 20 agents, adversarial verify per finding) | 11 confirmed findings (2 critical soundness, 2 major honesty, 7 minor) — all fixed in commit `8a71540` with regression coverage; 2 findings refuted |

## zk-receipt binding (reconciled)

`guest_source_sha256` in `proofs/zk-receipt/risc0_metadata.json` digests the
deterministic transpiled Rust guest (`guest_source.rs`), not the `.anb`
bytes. Re-derived 2026-08-13 from the committed
`proofs/jackal_proof_guest.anb`: transpile hash identical
(`2d11f1bf…`), guest ELF byte-identical (`d363e61d…`), ImageID identical,
fresh receipt verifies with the same journal (`8`). Details in
`proofs/zk-receipt/VERIFY.md`.

## Prior frozen baseline

The 1,402-case behavioral campaign of 2026-08-13 (adjudicated
`NO_UNEXPLAINED_MISMATCHES`) bound to artifact
`211c614b46f986d826b1e3272a4190b63178d83fb389bbf1d910162420c4295b` — the
engine as it existed *before* the certified lane. That receipt remains valid
for that artifact; this seal supersedes it for the current tree.

## Non-claims

Finite campaigns do not establish universal correctness. The certified lane's
enclosures are conditional on the stated f64 rounding model (correctly
rounded basic ops; libm within 2 ulp) and on the correctness of an
implementation that is campaign-tested, not mechanized. `jackal maturity`
prints the per-command epistemic grades.

## Regenerate

```bash
shasum -a 256 jackal_calc.anb jackal-native
ANUBIS_BIN=$HOME/anubis-lang/vm/pins/anubis-51f4a964347a python3 tests/test_calculator.py
python3 tests/bound_campaign.py 250 20260813
```
