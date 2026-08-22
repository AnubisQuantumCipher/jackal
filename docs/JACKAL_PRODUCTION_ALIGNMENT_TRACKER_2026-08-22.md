# JACKAL Production Alignment Tracker — 2026-08-22

Terminal state: `PARTIAL_JACKAL_PRODUCTION_ALIGNMENT`.

All architect-owned JACKAL, Codex, and Hermes source, merge, release,
description, installation, and read-back work is complete. The one remaining
item is third-party: [NousResearch/hermes-agent#88446](https://github.com/NousResearch/hermes-agent/pull/88446)
is open, mechanically mergeable, and blocked by the upstream base-branch
policy with no maintainer review. An ordinary merge attempt exited 1; neither
auto-merge nor administrator bypass was used.

The machine-readable companion receipt is
`release/evidence/production_alignment_release_readback_20260822.json`.

## Authority and exact repository binding

The architect goal is 12,611 bytes and 172 lines, SHA-256
`8025fb5570587258ec3cf6c808df71451af5b8815a7a5778f7d1e48e296dad7d`.
The durable release authorization record is
`release/evidence/architect_release_authorization_v173.json`, SHA-256
`f81446a5e115d99690c125d806d3406565ea83b6626c802e666f1cea3791cc94`.

| Surface | Branch / reviewed head | Merged or released identity |
|---|---|---|
| JACKAL kernel + Codex plugin | `mission/jackal-unified-completion-20260820`; package source `aaf7058ce98bf84ecd7b587f1ffff5f6a923f878`; reviewed head `91d0684bb28e0ac54c98058b53ba4147569b4b6f` | PR [#12](https://github.com/AnubisQuantumCipher/jackal/pull/12), merge `a43919e83fe141320fbc041f9be649b5ebe9e82c`, annotated tag `v1.7.3` object `45a2534e3288d9b43ff453161e567d0158ea0ea6` |
| Hermes standalone plugin | `mission/production-alignment-v6`; reviewed head `ceb491f77ea040f82df20f759d5fb456f989bd12`, tree `6cb4e953e8df43bacf6fbc5e652245784abe3af8` | PR [#5](https://github.com/AnubisQuantumCipher/hermes-jackal-verified/pull/5), merge `dab507a521406a69d308025bed380401eff967b9`, annotated tag `v6.0.0` object `ad0eaad6733a3ea04f63a91f9073026caca4afe3` |
| Hermes upstream index | `AnubisQuantumCipher:feat/index-jackal-verified`; head `eea6b2bec7cf1bb36f49dd7518e272e2300c7546`, tree `b14075dca1414e0ed73f6c6665fd5eeaa4dfaeb7` | PR [#88446](https://github.com/NousResearch/hermes-agent/pull/88446), base `0cde4dd93aa794c65fee6cc85b0b5e4eee77e8e2`; open and policy-blocked |
| Post-release receipt | `docs/jackal-production-alignment-release-readback-20260822`, based on `a43919e83fe141320fbc041f9be649b5ebe9e82c` | non-self-referential follow-up documentation |

No unrelated dirty checkout was overwritten. Package construction used two
clean detached worktrees and distinct output roots.

## Canonical 41-tool surface

`release/capability_inventory_v1.json` has SHA-256
`e2a4984329b3fd2fecc8de738dce20a5f046e0a876119569e72e41a04192a8f5`.
It records 41 rows and 41 unique names. The kernel catalog, profiles, packaged
catalog, Hermes schemas/discovery, Codex schemas/discovery, and skill-name
gates agree on this ordered roster:

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

The inventory distinguishes `exact`, `checked`, `estimated`, `bounded`,
`formal-bounded`, `model-based`, `structural-exact`, `verified`,
`verified-program-evidence`, `verified-program-receipt`, `indeterminate`, and
`refused`. Unsupported strong requests refuse; neither host adapter silently
substitutes a weaker lane.

## JACKAL v1.7.3 release and asset read-back

The public release is
[JACKAL v1.7.3 — Unified 41-Tool Evidence Surface](https://github.com/AnubisQuantumCipher/jackal/releases/tag/v1.7.3),
published at `2026-08-22T17:54:12Z`. It is neither draft nor prerelease. The
annotated tag object `45a2534e…` dereferences to merge `a43919e…`.

| Asset | Bytes | SHA-256 |
|---|---:|---|
| `jackal-v1.7.3-macos-arm64.tar.gz` | 158,363,786 | `68b0e7850fcb60358633908f70ffcf405cbbef103b04d3d93dd1298789e505ae` |
| `jackal-v1.7.3-evidence.tar.gz` | 562,653 | `32c0ceffdfb347f25bcb57f2f4fefc7a688dc048a10e64312d65930a675d7e90` |
| `jackal-v1.7.3-release-receipt.json` | 5,828 | `fef6a8ba3ab99c27f67e8d901d852ea52ef35c0474683bbd6daa4f229fe4f372` |
| `SHA256SUMS` | 296 | `1c5fd0526231f462028917be3d802de39ec73ddce9c2b11806e86983370c09ba` |

All four assets were downloaded into a fresh directory and compared against
the locally staged release bytes with `cmp`; all four comparisons exited 0.
`shasum -a 256 -c SHA256SUMS` passed all three payload rows. GitHub reports
release immutability disabled, so the annotated tag object and downloaded
asset digests are recorded separately rather than claiming an immutable
GitHub Release setting.

Package construction and internal identities:

| Property | Exact value |
|---|---|
| Source commit / tree | `aaf7058ce98bf84ecd7b587f1ffff5f6a923f878` / `e5f02743d121acbc1d9128d6c3ceaaf81542d583` |
| Builder SHA-256 | `686be8b66b7fccef3419eb032be8c8632619814b51f74814d1b85449f25cb58d` |
| Release manifest SHA-256 | `ac52dafc0e9edbf74dde56b358c3c55ab5b705d3b66811558156c480b3530509` |
| Root `SHA256SUMS` SHA-256 | `a78fc05e2ebd56f31263d54ccdbf7fcc2ff92d270758720c3e235d5a3121568a` |
| Regular files / tree entries | 106 / 119 excluding the package root |
| Extracted regular-file bytes | 555,511,970 |
| Roster aggregate SHA-256 | `f88ba8a9988afe4b41ab247d5c75cb3da03159defba1bd8985c37190fa595654` |
| Alignment receipt SHA-256 | `c15a3d174b847b02226f62ad26b217b887aa7102c9c21a7f392a9642e4e9a7bb` |
| Approved compiler SHA-256 | `a733565f237df171e7cf93b9b37700a42d8713576818fd92f8cd23a8ad7a69e2` |
| `jackal-native` SHA-256 | `f11f3a429aa64dc0f09eb930e82bc3250e19eeb5a8a74b26b86683fafd72a655` |
| Range / Gaussian / integral checker SHA-256 | `f7a82524d082b51a8d66f9bed653b9c8da51b5424386659c9048b9c0ae276545` / `ccac690bf916f71a4e3baeb0622dac19aa47e3ca4af858c0800c295581ecfacb` / `f8347cbd18d520852aff56920d41f5e5b496ff192f584e41d84d1a818ff29617` |
| Program verifier SHA-256 | `4b80e29bdffc0737f05a6e215fce8cce3b6b828c24afbf55c68443399e5119dc` |

Two clean builds were byte-identical at both tarball and extracted-directory
levels. Offline provisioning of the exact package passed before live Codex
acceptance.

## Codex integration

The Codex-facing plugin remains inside the JACKAL repository while all sealed
backend names remain `jackal_*`. Its eight-file aggregate identity is
`d4b6cdc32e55335eade1ca6d7cbc385c133c2dbecf4296a894877fe297fe27c3`.
Repository tests passed 218/218. Isolated live discovery reported exactly 41
tools and exercised:

- `exact` on the exact lane;
- `formal-bounded` on an admitted formal request;
- `producer-refused` for an unsupported formal request;
- `verified` claim-bundle replay;
- `verified` formal-receipt replay.

The first raw-extraction live attempt refused `runtime package metadata`
because it intentionally lacked the provisioner-owned marker. Offline
provisioning created the required marker and the unchanged code then passed;
no verifier was weakened to turn that refusal green.

## Hermes v6.0.0 release and installed state

The public release is
[JACKAL Verified v6.0.0 — 41-tool JACKAL v1.7.3 release](https://github.com/AnubisQuantumCipher/hermes-jackal-verified/releases/tag/v6.0.0),
published at `2026-08-22T18:16:36Z`. It is neither draft nor prerelease and
has no custom binary assets, matching prior plugin release convention. The
annotated tag object `ad0eaad6…` dereferences to merge `dab507a…`.

The v6 manifest SHA-256 is
`d28808bb21f5f27f57fb884292586e053da5bd07f1b84607188e8936b84e59aa`.
Its vendored parts reconstruct the downloaded JACKAL asset byte-for-byte.
`EPOCH.json` records release state `published`, tag `v1.7.3`, the public URL,
41 tools, package SHA-256 `68b0e785…`, and internal root `a78fc05e…`.

The normal Hermes profile was upgraded from installed v5.0.0/34 tools to the
exact v6 merge commit `dab507a521406a69d308025bed380401eff967b9` with:

```text
hermes plugins install AnubisQuantumCipher/hermes-jackal-verified \
  --force --ref dab507a521406a69d308025bed380401eff967b9 --enable
hermes plugins doctor jackal-verified --ci
```

Doctor passed runtime discovery, manifest parsing, import, and registration:
41 tools, zero hooks. The supervised gateway was then reloaded and returned on
a new PID. The installed checkout is detached at the exact release commit and
clean.

## Verification ledger

Every row exited 0 unless marked as an expected refusal or policy blocker.

| Gate | Result |
|---|---|
| `python3 -B tools/capability_inventory.py --check` | 41 rows, 41 unique |
| `python3 -B tools/capability_drift_gate.py` plus unit tests | kernel=41, Hermes=41, Codex=41; 31/31 |
| release authorization test | 1/1 |
| `release/tools/repin_v173.py ... --check` | 49 manifest rows |
| Lean admission source audit and tests | source pass; 26/26 |
| program verifier / hostile program controls | 15/15; 15/15 |
| skill contracts | 5/5 |
| clean package suite / rebuild-and-parity | 15/15 with zero skips; 60/60 |
| Codex repository / live acceptance | 218/218; 41-tool live acceptance passed |
| JACKAL hosted push + PR checks at `91d0684…` | runs `32588788485`, `32588788491`, `32588791633`, `32588791694`; all pass |
| JACKAL release read-back | four byte comparisons and three checksum rows pass |
| Hermes production alignment / unit | 7/7; 22/22 |
| Hermes poison battery | 48/48 normal; 48/48 optimized |
| Hermes split / A→B→A controls | 8/8; 4/4 |
| Hermes fresh install / manifest / release audit | 41 tools; 32 manifest files; zero forbidden paths or secret matches |
| Hermes hosted branch push / PR / merged main | runs `32589797976`, `32589818664`, `32590042317`; all pass |
| installed Hermes doctor | v6.0.0; 41 tools; zero hooks |
| upstream index JSON + focused wrapper | valid JSON; 38/38 via `scripts/run_tests.sh` |
| upstream ordinary merge attempt | expected blocker: exit 1, base-branch policy prohibits merge |

An earlier broad upstream wrapper run on the old base reported unrelated
baseline/provider failures. No unrelated upstream source was changed to hide
them. The refreshed branch merges current upstream `main`, changes one JSON
file relative to that base, and passes the repository-mandated 38-test index
suite; no full-upstream-green claim is made.

## Lean admission and axiom audit

| Property | Result |
|---|---|
| Audit artifact SHA-256 | `cabda2a1fb8c021ce384d9c2267f52f98e6799bb50b6b828e7d9eefa55bf2b2e` |
| Semantic digest SHA-256 | `5e33809e2d8f73d8b554313bc9ea71a8b8d3c657810f0b37d4db3dd945578f29` |
| Tracked Lean files | 42 |
| Named release theorems | 27 unique |
| Logical admissions | 0 |
| Repository axiom declarations | 0 |
| Unexpected constructs | 0 |
| Exact observed theorem axioms | `Classical.choice`, `Quot.sound`, `propext` |
| Allowlisted runtime substitutions | two dump-only `implemented_by` mirrors outside checker roots |

This is a checker-source and named-theorem audit, not proof of the compiler,
Lean kernel, native extraction, operating system, hardware, supply chain, or
arbitrary expressions.

## Skill inventory and drift control

| Skill surface | SHA-256 / result |
|---|---|
| Repository Codex router `plugins/jackel/skills/jackel/SKILL.md` | `75211a141c502c2f6c4ca54f88f07b2d13b87475f4837b3335f43c15f7da42dc` |
| Personal Codex `jackal-assurance-oracle` | `69fe32e1212c42c77f96ceee81a0040ac5daaa8ee3760cbf41c261b3148e2454` |
| Released and installed Hermes v6 router | `4e7475e444251e1449de2b8a312ab5eb3288259e48ce54466a4555a1f88b739a` |
| Personal Hermes `jackal-verified-computation` copies | `d8445e050c5e7cc333f493117aa42216dfa27e812224e022f23c1a72b7da765e`, byte-equal across default and four profiles |
| Personal Hermes `jackal-trust-boundary-reseal` copies | `3c00bcf75a10197b112bbbf26d3338fd8ce029e0a74ed6f95fa3c3b310d5732b`, byte-equal across default and four profiles |

The repository skill contract tests bind referenced names and routing facts to
the canonical inventory. Both host skills direct mixed/consequential work
through claim compilation and replay, require caller-pinned expectations for
verification, preserve refusal/indeterminate outcomes, and forbid silent
downgrade.

## Public metadata and upstream PR

- JACKAL’s public description now identifies the released 41-tool v1.7.3
  surface; the default README does the same.
- Hermes’ public description now identifies the released 41-tool adapter; the
  default README contains neither current `candidate` wording nor `34 tools`.
- Historical release notes remain historical and were not rewritten.
- PR #88446 is titled `index: add released jackal-verified v6.0.0 (41 tools)`
  and pins exact plugin merge `dab507a…`.
- PR #88446 head is `eea6b2b…`; its diff against current upstream `main` is
  only `hermes_cli/data/plugin_index.json`.
- The focused index suite passes 38/38. The PR currently reports no hosted
  checks and no reviews.
- Verification comment:
  [issuecomment-5381898802](https://github.com/NousResearch/hermes-agent/pull/88446#issuecomment-5381898802).
- GitHub reports `mergeable=true`, `mergeStateStatus=BLOCKED`. The ordinary
  squash-merge attempt returned: `the base branch policy prohibits the merge`.
  Auto-merge was not enabled and administrator privileges were not used.

## Independent review dispositions

CodeRabbit’s hosted review on JACKAL PR #12 produced 14 actionable threads.
All 14 were source-verified, fixed, answered with evidence, acknowledged, and
resolved before the reviewed head. The fixes covered workstation-path leaks,
package and compiler pin closure, network refusal before publication,
cross-filesystem refusal, evidence-root completeness, Lean determinism,
manifest replacement, wrapper path resolution, and parser/test hardening.

The review did not silently widen the approved Z3 identity, redesign the
`unit_conflict` algorithm, remove compatibility registry copies, or claim
streaming/hash refactors as correctness requirements. CodeRabbit reported pass
or review-skipped status on the final owned PR checks; no unavailable second
full review is represented as completed.

## Residuals and non-claims

- No NousResearch maintainer approval or upstream merge is claimed.
- GitHub release immutability is disabled for both owned repositories;
  annotated tag objects and fresh asset read-backs are the recorded evidence.
- SHA-256 identifies bytes; it is not by itself authorship, authentication, or
  mathematical correctness.
- JACKAL and the Hermes plugin are Apple Silicon macOS only, unsigned, and
  unnotarized.
- `formal-bounded` applies only to checker-admitted fragments and not arbitrary
  expressions.
- `inventory-safe-v1` does not establish policy-construct totality,
  source-to-VC, SMT-to-CNF, source-native refinement, runtime behavior, or
  universal language soundness.
- Green tests and reproducible bytes do not expand these stated assurance
  boundaries.
