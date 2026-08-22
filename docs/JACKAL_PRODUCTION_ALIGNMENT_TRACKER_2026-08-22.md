# JACKAL Production Alignment Tracker — 2026-08-22

Checkpoint state: `AUTHORIZED_RELEASE_PROMOTION`.

The architect explicitly approved both previously blocked trust-surface
decisions and instructed Codex to merge and finish the release work. The
authorization record is
`release/evidence/architect_release_authorization_v173.json`, SHA-256
`f81446a5e115d99690c125d806d3406565ea83b6626c802e666f1cea3791cc94`.
This checkpoint binds the final reproducible package and release pins; merge,
tag, GitHub-release read-back, Hermes promotion, installation, and upstream
PR disposition remain subsequent recorded actions, not claims of this row.

## Authority and repository binding

| Surface | Exact identity | State |
|---|---|---|
| Architect goal | 12,611 bytes; 172 lines; SHA-256 `8025fb5570587258ec3cf6c808df71451af5b8815a7a5778f7d1e48e296dad7d` | VERIFIED |
| JACKAL public base | `AnubisQuantumCipher/jackal` `master` at `73854110cb82d78b2843d5028e1e0d5970b0ad5a` | latest public release line |
| JACKAL package-producing source | `mission/jackal-unified-completion-20260820` commit `aaf7058ce98bf84ecd7b587f1ffff5f6a923f878`, tree `e5f02743d121acbc1d9128d6c3ceaaf81542d583` | clean source; package reproduced twice |
| JACKAL release-pin closure | descendant of `aaf7058…` | package receipt, Codex pins, and this intentionally non-self-referential tracker |
| JACKAL PR | [AnubisQuantumCipher/jackal#12](https://github.com/AnubisQuantumCipher/jackal/pull/12) | open and mergeable at this checkpoint; authorization resolved |
| Hermes v6 candidate | `AnubisQuantumCipher/hermes-jackal-verified` `mission/production-alignment-v6` at `936dab4458d4618f4ecf56c2da5c9f5cdbb9aef4`, tree `6315b680be8e5d3b109014910b774b84b565040d` | pushed; no tag or release |
| Hermes upstream index | `AnubisQuantumCipher/hermes-agent` `feat/index-jackal-verified` at `28f5455001ce4784d8e584fbb521c442740f8e64`, tree `bce913a075326a5c32eb1d50bc5010b51b08a540` | [NousResearch/hermes-agent#88446](https://github.com/NousResearch/hermes-agent/pull/88446), open and mergeable; one tracked file changed |
| Public README clarification | docs head `798b63148cdc01b0c17fb2bd888478cbbe037ffd`; merged as `6a42656df135eab1b2abfdf2b873b02df8efb6e9` | [plugin PR #4](https://github.com/AnubisQuantumCipher/hermes-jackal-verified/pull/4) merged after both CI runs passed |

Ambient JACKAL and Hermes checkouts under `$HOME` contain user-owned state and
were not mutation targets. Source builds, package checks, and candidate work
used isolated worktrees and fresh temporary roots.

## Canonical capability surface

`release/capability_inventory_v1.json` has SHA-256
`19930922418aa0f751c8ee3476f31677368e0c29c5f1c5ea8942ea7fb597d60c`.
It contains 41 rows and 41 unique names. Kernel catalog, profiles, package,
Hermes schemas/discovery, Codex schemas/discovery, and skill-name gates agree
on this ordered roster:

```text
jackal_range_bound
jackal_gaussian_integral
jackal_integrate_bound_cert
jackal_verify_receipt
jackal_sqrt_rat_bound
jackal_exp_rat_bound
jackal_ln_rat_bound
jackal_sin_rat_bound
jackal_cos_rat_bound
jackal_atan_rat_bound
jackal_tanh_rat_bound
jackal_exact
jackal_evaluate
jackal_diff
jackal_integrate
jackal_integrate_adaptive
jackal_integrate_bound
jackal_solve
jackal_canon
jackal_poly_canon
jackal_poly_eq
jackal_poly_gcd
jackal_ratfunc_canon
jackal_roots_isolate
jackal_alg_sign
jackal_alg_cmp
jackal_xgcd
jackal_mod_pow
jackal_mod_inv
jackal_crt
jackal_divides
jackal_prime_cert
jackal_claim
jackal_verify_bundle
jackal_test_exists
jackal_claim_cites_test
jackal_decision_rank
jackal_decision_rank_v2
jackal_anubis_check_program
jackal_anubis_verify_program
jackal_anubis_verify_program_receipt
```

The inventory distinguishes exact, checked, estimated, bounded,
formal-bounded, model-based, structural-exact, verified,
verified-program-evidence, verified-program-receipt, indeterminate, and
refused outcomes. Unsupported strong requests refuse; no adapter silently
substitutes a weaker lane.

## Reproducible v1.7.3 release package

| Property | Exact value |
|---|---|
| Builder SHA-256 | `686be8b66b7fccef3419eb032be8c8632619814b51f74814d1b85449f25cb58d` |
| Release manifest SHA-256 | `ac52dafc0e9edbf74dde56b358c3c55ab5b705d3b66811558156c480b3530509` |
| Program verifier SHA-256 | `4b80e29bdffc0737f05a6e215fce8cce3b6b828c24afbf55c68443399e5119dc` |
| Package | `jackal-v1.7.3-macos-arm64.tar.gz` |
| Package SHA-256 | `68b0e7850fcb60358633908f70ffcf405cbbef103b04d3d93dd1298789e505ae` |
| Package bytes | `158363786` |
| Regular files | `106` |
| Complete extracted tree entries | `119` |
| Extracted regular-file bytes | `555511970` |
| Root `SHA256SUMS` SHA-256 | `a78fc05e2ebd56f31263d54ccdbf7fcc2ff92d270758720c3e235d5a3121568a` |
| Mode/size/digest roster aggregate | `f88ba8a9988afe4b41ab247d5c75cb3da03159defba1bd8985c37190fa595654` |
| Alignment receipt SHA-256 | `c15a3d174b847b02226f62ad26b217b887aa7102c9c21a7f392a9642e4e9a7bb` |

Two distinct clean detached source worktrees at source commit `aaf7058…`, each
with its own destination, produced byte-identical tarballs, checksum lists,
complete extracted trees, and file rosters. `cmp` and the directory comparison
both exited 0. The approved compiler SHA-256 was
`a733565f237df171e7cf93b9b37700a42d8713576818fd92f8cd23a8ad7a69e2`;
the builder requires the operator to provide its path explicitly.

Pinned runtime inputs were:

| Input | SHA-256 |
|---|---|
| `jackal-native` | `f11f3a429aa64dc0f09eb930e82bc3250e19eeb5a8a74b26b86683fafd72a655` |
| range checker | `f7a82524d082b51a8d66f9bed653b9c8da51b5424386659c9048b9c0ae276545` |
| Gaussian checker | `ccac690bf916f71a4e3baeb0622dac19aa47e3ca4af858c0800c295581ecfacb` |
| composed-integral checker | `f8347cbd18d520852aff56920d41f5e5b496ff192f584e41d84d1a818ff29617` |

These are the authorized release bytes. At this checkpoint, publication and
download read-back have not yet been claimed. Offline provisioning of this
exact tarball passed, after which the isolated Codex live gate discovered 41
tools and passed exact, formal, refusal, claim-bundle, and receipt replay.

## Verification ledger

Every command below exited 0 unless the row explicitly describes an expected
refusal.

| Command or gate | Result | Boundary |
|---|---|---|
| `python3 -B tools/capability_inventory.py --check` | `tools=41 unique=41` | generated inventory |
| `python3 -B tools/capability_drift_gate.py` | `tools=41 unique=41 codex=41 package=v1.7.3` | marked current surfaces; historical releases excluded |
| inventory plus drift unittests | 31/31 pass | positive and mutation controls |
| `release/tools/repin_v173.py --compiler-path <approved-compiler> --check` | 49 rows pass | fixed compiler identity; no machine fallback |
| program-verifier suite | 15/15 pass | verifier-owned compiler snapshot, Z3/RUP replay, path and pin refusals |
| `tools/lean_admission_audit.py --source-check` plus Lean tests | source pass; 26/26 tests | tracked sources, theorem output, mutation controls |
| package-unification suite over a fresh package root | 15/15 pass; zero skips | complete closure and package semantics |
| `tests/claim_package_parity_test.py` | 60/60 pass | rebuild twice, every packaged tool family, receipt replay, tamper refusal |
| Codex repository discovery suite | 218/218 pass | repository candidate |
| isolated Codex live acceptance | 41 tools; accepted | exact=`exact`; formal=`formal-bounded`; claim bundle and formal receipt=`verified`; unsupported formal=`producer-refused` |
| Codex wrapper identity | eight files; aggregate `a1d04cf92b1c56cd5833c43fb87ab8d129a6115d645ad98ddfa47e5e38f1c8dc` | verified candidate wrapper |
| claim hostile matrix | 108 rows pass | complete 64-character roots and refusal boundaries |
| claim A-to-B-to-A campaign | 7 layers pass | mutation restoration and identity binding |
| plugin smoke | pass | manifest-current Hermes bundle `c6a27483077b89d899d8c73c03bfeb3191f25db2a22f8021254a7dec763ba5fe` |
| JACKAL hosted workflows | runs [32583685425](https://github.com/AnubisQuantumCipher/jackal/actions/runs/32583685425), [32583685444](https://github.com/AnubisQuantumCipher/jackal/actions/runs/32583685444), [32583687658](https://github.com/AnubisQuantumCipher/jackal/actions/runs/32583687658), and [32583687710](https://github.com/AnubisQuantumCipher/jackal/actions/runs/32583687710) all success | exact head `0bca7da…`; push and PR events |
| Hermes epoch generation | 41 tools, 53 selected package identities | package-derived |
| Hermes production/unit/poison suites | 7/7; 22/22; 48/48 normal; 48/48 optimized | candidate adapter |
| Hermes split/ABA controls | 8/8; 4/4 | part discovery and four forgeries |
| Hermes fresh install and doctor | pass; 41 tools, zero hooks | exact vendored candidate |
| Hermes manifest/release audit | manifest pass; zero forbidden paths or secret matches | manifest SHA-256 `bd67cb69c6a1ee15c0fa38ad7d01111e181722744fe623367584fbe14b58a7e0` |
| Hermes hosted CI | [run 32584006653](https://github.com/AnubisQuantumCipher/hermes-jackal-verified/actions/runs/32584006653) success | exact candidate head `936dab4…` |
| upstream plugin-index suite | 38/38 pass through `scripts/run_tests.sh` | PR #88446 one-file JSON diff |
| public README PR CI | [push 32584187543](https://github.com/AnubisQuantumCipher/hermes-jackal-verified/actions/runs/32584187543) and [PR 32584190455](https://github.com/AnubisQuantumCipher/hermes-jackal-verified/actions/runs/32584190455) success | docs plus required manifest reseal |

An earlier broad upstream Hermes wrapper attempt reported 78 failures across 21
unrelated test files plus one collection timeout/error from missing providers
or baseline environment assumptions. No unrelated upstream file was changed to
mask those results. The focused 38-test index suite is the applicable diff-level
gate; no full-upstream-green claim is made.

## Lean admission and axiom audit

| Property | Result |
|---|---|
| Audit artifact SHA-256 | `7c14c616dabdaa1e1424b04b647be79dddfab7861c61e2d8a0b28064d10fea3d` |
| Semantic audit digest | `264701eaa4c4721d0b734653cd8082d20e1b57d252e80e6dd9394ac50010af98` |
| Tracked Lean files | 42 |
| Audited theorem names | 27 unique |
| Logical admissions | 0 |
| Repository axiom declarations | 0 |
| Unexpected constructs | 0 |
| Exact observed theorem axioms | `propext`, `Classical.choice`, `Quot.sound` |
| Classified runtime substitutions | two allowlisted dump-only `implemented_by` mirrors outside current checker acceptance |

The byte-compared audit record contains platform-neutral Lean 4.32.0 and
mathlib identities rather than host triples or resolved shim identities. This
is a checker-source and named-theorem audit. It does not prove compiler
correctness, source-to-native refinement, operating-system correctness,
arbitrary-expression mathematics, or universal language soundness.

## Skill census

| Skill surface | SHA-256 / disposition |
|---|---|
| Personal Codex `jackal-assurance-oracle` | `69fe32e1212c42c77f96ceee81a0040ac5daaa8ee3760cbf41c261b3148e2454`; current claim, receipt, program, and refuse-never-downgrade routing |
| Personal Hermes `jackal-verified-computation` | `d8445e050c5e7cc333f493117aa42216dfa27e812224e022f23c1a72b7da765e`; default plus four profile copies byte-equal |
| Personal Hermes `jackal-trust-boundary-reseal` | `3c00bcf75a10197b112bbbf26d3338fd8ce029e0a74ed6f95fa3c3b310d5732b`; default plus four profile copies byte-equal |
| `gbrain-evidence-memory` | `27a921cdb7f4da025a67183b7531b72d4efa81d02db7983096a4ed8c9a951f30`; incidental integration, no count/version/pin claim |
| `adversarial-calculator-audit` | `bbbcc1a6389b6fd521833d81cf82d3ade319e15fb880cc3a3d15a2987930e92b`; no stale count or pin |
| `independent-oracle-mutation-audit` | `941d6ae02742bb78febcdf8c1f239c455651742381ce082404800b8dc57b8e9e`; no stale count or pin |
| `receipt-semantic-replay-verification` | `f5e1c7adc556d8739c7f39de2185750d927454130271f7523509c50d0d10a8fc`; no stale count or pin |
| `rigorous-evidence-report` | default `a755564d8dd0e09e0573f287d9ee3778bf94d53d6ca6ef92fa23457340cd0b00`; four profile copies `8592f6f2d203afc71ba413702f00acab6da228d3e62bafffe88e6f78fde3f1c5`; pre-existing PDF-rendering guidance difference only, with identical JACKAL wording and no count/version/pin claim |
| Repository Codex router | `1fb8f70356bd022daf9fc36b739c9ce671b2ba59d303542393d01e15cdb4070a` |
| Hermes v6 bundled router | `7536b78eddf7d72e4d392cdac3977253ac381097b360af8e65d1b9741201e4c1` |
| Normally installed Hermes v5 router | `a5e2fcf14c2a775acb776b5ae63a3be38515d0af16236c6466f9846f8239f31f`; intentionally historical until authorized promotion |

Repository contract tests bind current skill tool names and routing facts to
the canonical inventory. Local skill files were read and hashed directly;
`hermes skills audit` output for an unrelated hub-installed copy is not used as
evidence.

## Independent review ledger

The hosted CodeRabbit review on PR #12 posted 14 actionable findings at
[review 5000442938](https://github.com/AnubisQuantumCipher/jackal/pull/12#pullrequestreview-5000442938).
Every finding was verified against source, fixed in `957ac893…` or rebound in
`0bca7da…`, answered with exact evidence, acknowledged by the bot, and resolved.
The accepted fixes include:

- removal of workstation paths from committed documentation;
- final package-pin alignment;
- verifier-owned compiler execution snapshots;
- unpublished-release network refusal;
- early cross-filesystem package refusal;
- complete evidence roots;
- regenerated Lean and Hermes evidence;
- correct repin documentation and diagnostics;
- complete transcript-to-summary binding;
- NUL-safe tracked-file parsing;
- deterministic Lean axiom output and platform-neutral audit bytes.

Selected low-risk nitpicks were also fixed: CI credential persistence,
deterministic Lean fixtures and symlink controls, raw-string scanning,
configurable bounded audit timeouts, derived audit counts, profile-count and
runtime-literal test independence, wrapper symlink resolution, parsed package
status, explicit compiler authority, durable manifest replacement, one-read
repin hashing, and early termination after a derived empty RUP clause.

The following suggestions were not silently folded into this candidate:

- widening the approved Z3 path is a trust-surface decision;
- redesigning `unit_conflict` around an index/queue is a large performance
  refactor outside this bounded correctness patch;
- duplicate packaged registry paths remain compatibility surfaces;
- streaming the large checker hash and other broad test-oracle refactors were
  not required to close an observed correctness gap.

Five earlier local CodeRabbit passes also produced fixes. A further local pass
could not start because the account review allowance was exhausted. Hermes
local CodeRabbit attempts ended in WebSocket/quota failures. Green tests are not
presented as a substitute for those unavailable extra reviews, and no
zero-finding second full review is claimed.

## Public metadata and PR state

- JACKAL repository description now leads with the mechanically aligned
  41-tool v1.7.3 candidate and states that public sign-off is pending.
- Hermes repository description now leads with the 41-tool v6 candidate and
  states that v5.0.0 remains latest.
- The default Hermes README at merge commit `6a42656…` leads with the immutable
  41-tool candidate. Every remaining 34-tool section is explicitly under
  `Published release reference — v5.0.0 (34 tools)`.
- JACKAL latest release remains v1.7.2. Hermes latest release remains v5.0.0
  with 34 tools. Historical release records were not rewritten.
- The normal installed Hermes plugin remains v5.0.0 with 34 tools; candidate
  verification used isolated state.
- PR #88446 title/body/index use neutral 41-tool candidate language and pin
  exact plugin commit `936dab4458d4618f4ecf56c2da5c9f5cdbb9aef4`.
- PR #88446 verification comment:
  [issuecomment-5381364416](https://github.com/NousResearch/hermes-agent/pull/88446#issuecomment-5381364416).
- PR #88446 is open and mergeable, changes only
  `hermes_cli/data/plugin_index.json`, reports no hosted checks, and was not
  merged.

## Authorization resolution and remaining promotion steps

The architect approved the `inventory-safe-v1` accept conditions, status
meaning, v1.7.3 domain-pack compatibility minimum, and promotion boundary.
The durable authorization receipt records the exact user instructions and
explicitly does not override third-party permissions or branch protection.
The remaining work is mechanical: merge and read back JACKAL v1.7.3; repin,
merge, release, and install Hermes v6; then update and exhaust the permitted
actions on upstream PR #88446.

## Final nonclaims

- At this checkpoint, no public JACKAL v1.7.3 or Hermes v6 release read-back is
  asserted; later tracker revisions must bind those identities if published.
- No upstream maintainer approval or merge is asserted.
- No arbitrary-expression, compiler-correctness, source-native-refinement, or
  unrestricted formal-correctness claim is made.
- The architect authorization is an operator record, not a cryptographic
  signature, proof of third-party authority, or expansion of formal coverage.
