# JACKAL v1.7 `bound_step` composition — final mission receipt

**Terminal state: READY_FOR_TRUST_SIGNOFF.**
**Status: research-shadow. NON-AUTHORITATIVE. No trust-surface promotion applied.**

Contract: `JACKAL_V170_BOUND_STEP_COMPOSITION_SHADOW_MISSION.md`
(sha256 be1dd3db83ce8d970575e6f6fa232e047dcb75539afeec3f9a364a2a89c52ee8,
verified 433 lines / 2618 words / 19129 bytes on 2026-08-16).

## Baseline identity

| fact | authorized | freshly observed | verdict |
|---|---|---|---|
| `origin/master` | 19b763e9451276e72c7511ec8ba42bf828d096f6 | same (after `git fetch origin --tags --prune`) | MATCH |
| `v1.6.0^{}` | 19b763e9451276e72c7511ec8ba42bf828d096f6 | same | MATCH |
| worktree | /Users/sicarii/Worktrees/jackal-v170-bound-step @ 19b763e, clean, `website/` absent | — | ISOLATED |
| ambient checkout | untouched except read-only git ops + read-only `.lake` clone source + read-only pinned `jackal-native` copy source (sha-verified) | — | UNTOUCHED |
| protected `website/` | never read/staged/modified/packaged/cleaned; absent from worktree and from every staging set | — | UNTOUCHED |

## Branch and checkpoints

Branch `feat/bound-step-composition-v1.7`, upstream
`origin/feat/bound-step-composition-v1.7`.

| checkpoint | commit | content |
|---|---|---|
| 1+2 (non-final) | 4d423e2 | research + red matrix + machine-checked composition theorem stack |
| 3 (non-final) | 3c40086 | codec + driver + producer + 31/31 matrix + A→B→A + 5/5 differential + evidence |
| final (non-final) | recorded in git (this commit) | receipt, command table, final gates |

Changed-file inventory vs baseline: 21 files, +4696 insertions, 0 deletions
of legacy content (the only modified legacy files are
`proofs/lean/JackalIv.lean` — additive imports, outside both pinned proof-
identity closures — and `tests/bound_step_shadow_test.py`-family files that
are new).  Everything else is new: 8 Lean shadow modules, 1 producer,
3 test gates, 7 research/evidence artifacts.

## Theorem and checker identity

| object | source (sha256 prefix) |
|---|---|
| `JackalIv.Shadow.int_cert_sound` (flagship) | ShadowCertSound.lean 30aa62a3eb3b2e0d |
| `range/taylor2/taylor4_leaf_sound`, `split_sound` | ShadowCertSound.lean |
| `sem_measurable`, `measurable_rpow_pair` | ShadowMeasure.lean efc65786e7ad5902 |
| `embedQ_DQ`, `embedQ_DQiter`, `qexprOf_embed`, `qbuild_embed` | ShadowQExpr.lean db1252b57f8339fd |
| `checkIntCert` (computable, reason-carrying) | ShadowCertCheck.lean 3857724975629b23 |
| `parseIntCert` (codec) | ShadowCertCodec.lean a65164d5ba35cc57 |
| driver (`lake env lean --run`) | ShadowCertMain.lean 3cff239c13a91211 |
| build-time `#guard` twins | ShadowCertFixtures.lean bc3c3fdca3c1abb8 |
| artifact schema/types + `TreeTCB` | ShadowCertTypes.lean de6f12ca0353c727 |
| untrusted producer | tools/bound_step_shadow_producer.py 02259649452da98c |

`#print axioms` (evidence/axiom_audit.txt): 15/15 audited theorems —
all 11 shadow theorems plus the four reused bridges (`cert_check_sound`,
`runs_encloses`, `taylor2/4_enclosure_of_evaluable`) — report exactly
`[propext, Classical.choice, Quot.sound]`.  Zero `sorry`, zero project
axioms, zero `native_decide`, zero `@[implemented_by]`, zero `unsafe`/
`partial` in the shadow sources (grep receipt in command table).

Checker/proof identity pins inside every artifact: schema
`jackal-int-cert shadow-v1`, model `jackal-iv-model-v1`, checker
`jackal-iv-bound-step-shadow-v1`, status `research-shadow`.

## Command outcome table

All commands run in /Users/sicarii/Worktrees/jackal-v170-bound-step on
2026-08-16/17 (America/New_York), exact bytes of the final checkpoints.

| # | command | outcome | evidence |
|---|---|---|---|
| 1 | `git fetch origin --tags --prune` + identity probes | PASS (baseline match) | transcript; §Baseline |
| 2 | `lake build JackalIv jackal_cert_check jackal_gaussian_check jackal_parse_dump` (baseline, cloned cache) | PASS exit 0 | transcript |
| 3 | focused shadow module elaborations (`lake env lean JackalIv/Shadow*.lean`) | PASS exit 0 each | transcript |
| 4 | `lake build JackalIv` (with all shadow modules + `#guard` twins) | PASS exit 0 | transcript; final rerun below |
| 5 | axiom audit (`#print axioms`, 15 theorems) | PASS — 15/15 exactly propext/Classical.choice/Quot.sound | evidence/axiom_audit.txt |
| 6 | forbidden-construct grep over shadow sources | PASS — 0 hits (one doc-comment mention) | transcript |
| 7 | `python3 tests/bound_step_shadow_test.py` (focused matrix) | PASS 31/31 | evidence/shadow_matrix.json |
| 8 | `python3 tests/bound_step_shadow_aba.py` (A→B→A) | PASS | evidence/aba_shadow.json |
| 9 | `python3 tests/bound_step_shadow_differential.py` | PASS 5/5 | evidence/differential_engine.json |
| 10 | `python3 tools/compat_floor.py --check` | PASS — `COMPAT_FLOOR_PASS frozen_tools=31 live_tools=33 frozen_gates=32 errors=0` | transcript |
| 11 | `python3 tools/formal_status_gate.py` (selftest) | PASS ok=11 bad=0 | transcript |
| 12 | `python3 tests/formal_status_gate_test.py` | PASS (mutation caught: inventory-integrity) | transcript |
| 13 | `python3 release/tools/gaussian_proof_identity.py check --lane range --proof-only` | PASS | transcript |
| 14 | same, `--lane gaussian` | PASS | transcript |
| 15 | `python3 tests/plugin_bundle_identity_test.py` | PASS (27 runtime files, all mutation guards bound) | transcript |
| 16 | `python3 tests/plugin_smoke.py` | PASS (S1–S20; weak lanes honest; regenerated release/evidence/plugin_smoke.jsonl BYTE-IDENTICAL to the committed file — determinism confirmed, no overwrite) | transcript + clean `git status release/` |
| 17 | `python3 release/tools/ci_claim_admission.py` | PASS checks=3 (tamper refused: node-id-mismatch) | transcript |
| 18 | `python3 tests/test_calculator.py` (black-box, pinned Anubis compiler a733565f…) | PASS TOTAL 200/200 | transcript (2439 s) |
| 19 | `python3 tests/parser_differential.py` | PASS checked=78 failures=0 | transcript (727 s, run solo; see BACKLOG #4 for the concurrent-run timeout) |
| 20 | binary identity: rebuilt `proofs/lean/.lake/build/bin/jackal_cert_check` | PASS — sha256 05c3518b836f239712f897c483a2ddadad9f544e0887b1b7bb1424a27289de8a == MANIFEST pin | transcript |
| 21 | source identity: `jackal_calc.anb` | PASS — 34870c66… == MANIFEST pin (untouched) | transcript |
| 22 | staged `jackal-native` copy | PASS — 8617ad08… == MANIFEST pin; gitignored | transcript |
| 23 | `git diff --check` + changed-file review + final tree state | PASS (final section below) | transcript |
| 24 | final push + remote equality | PASS (final section below) | transcript |

SKIPPED with reason: `release/tools/run_gates_v160.py` full 38-gate
aggregate was NOT run as one monolith — its heavy members were run
individually above (lake-build, compat-floor, formal-status, plugin gates,
black-box, parser-differential, ci-claim-admission) and the remainder
(7× `jackal-*-rat-release`, gaussian release lanes, seal audits, campaign
suites, package build) exercise ONLY files this mission provably did not
touch (MANIFEST-pinned binaries byte-identical; `release/` tree clean in
git). Re-running them would re-emit release evidence, which the mission
forbids overwriting; the package builder was additionally avoided to honor
"explicitly avoiding a v1.6 repin or publication".

## Focused matrix (mission §8)

Positive (6): P1 range leaf (abs); P2 taylor2 leaf (x², degree cap 2);
P3 taylor4 leaf (sin); P4 multi-level recursive tree (abs kink, ≥2 splits);
P5 nontrivial signed left/right sums (x³−x, range mode); P6 exact replay of
one artifact through two fresh checker processes (identical accept lines).

Boundary/refusal (7): unsupported-expression (tan), budget-exhausted
(60000-entry mirror), cannot-certify (1/x through 0), float-resolution
(sub-ulp domain), invalid-domain (reversed), tolerance-unmet (pad-dominated
large-magnitude integral), noncanonical-value (unreduced rational at the
artifact layer).

Semantic poisons (18): expression changed / bounds changed / tolerance
changed / epoch changed / mode relabel (wire-layer AND semantic-layer
variants) / leaf narrowed / child omitted / child duplicated / child order
swapped / partition gap / partition overlap / forged parent total / orphan
node / forward-self reference / root changed / rehash-after-tamper /
stale checker pin.  Every poison passed byte/schema layers where semantics
was the intended rejector and refused with the EXACT expected class
(evidence rows carry observed reason lines).

Totals: 31 rows, 31 PASS; 6 positive, 25 hostile (7 refusal + 18 poison).

## A→B→A receipt (evidence/aba_shadow.json)

- gate: `tolerance-unmet` released-width guard; poison: released interval
  widened beyond the bound tolerance (sha256 dac67d7e…).
- A/pre: clean ACCEPT; poison REFUSE `tolerance-unmet`.
  source_hash_pre 3857724975629b23….
- B: one compiling, runnable guard mutation (source_hash_mutated
  4925d194e9445d85…); poison ADMITTED (exit 0) through the mutated driver —
  the checker is load-bearing.  Defense-in-depth recorded: the FULL library
  build under B fails (`#guard` tolerance twin fires at build time).
- A/post: bytes restored, hash-verified equal to pre (3857724975629b23…);
  rebuild green; poison REFUSES again with the ORIGINAL reason; clean
  artifact accepts.
- B-strong (supplementary): disabling the `forged-enclosure:lower` guard
  does not compile — `int_cert_sound` consumes it; the enclosure guards are
  PROOF-load-bearing.  Never committed; final source hash equals pre.

## Public-surface confirmation

- Public tool inventory: exactly **33** (compat floor + plugin bundle
  identity + plugin smoke all PASS; `plugin/hermes/tools.json` untouched).
- v1.6 tag/release/assets: untouched (no tag ops, no release ops; `git
  fetch` only).
- `release/`, `MANIFEST.sha256`, coverage inventory, claim registries,
  receipts, compatibility fixtures: byte-identical (git status clean over
  `release/`; MANIFEST pins re-verified).
- Existing acceptance semantics: `jackal_cert_check` REBUILT from this
  branch is byte-identical to the pinned release binary — no public
  verifier's accepted set can have changed.
- The six "bound_step … remains OPEN" surfaces: byte-identical.
- No Hermes plugin installed or published; no lakefile/lean-toolchain/
  lake-manifest edits; no new `lean_exe`.
- Proposed promotion recorded UNAPPLIED in PROMOTION_PROPOSAL.md.

## Registers

**VERIFIED** (ran on exact bytes, outputs above): baseline identities; all
command-table rows; theorem axiom footprints; matrix/ABA/differential
results; binary/source identity pins; 33-tool floor; clean release tree.

**BELIEVED** (tested, not proved): the producer faithfully mirrors the
shipped `bound_step` control flow on the shared fragment (matrix refusal
classes + 5/5 engine differential, incl. byte-identical enclosures on the
two abs cases); deterministic evidence regeneration (plugin_smoke.jsonl
byte-equal); the engine would emit checker-acceptable artifacts if wired
per PROMOTION_PROPOSAL (its float midpoint intervals satisfy the checker's
exact containment rule by `float_midpoint_in_padded` — argued, not run).

**UNKNOWN / OPEN** (inherited, untouched): engine f64 execution vs model
(implementation-tested-not-mechanized); platform libm ≤ 2 ulp; Anubis
compiler/hardware faithfulness; source→native refinement (roadmap 5);
decimal→f64 request parsing upstream of any artifact.

## Residual non-claims after this slice

1. Public `integrate-bound` remains `bounded` / CONDITIONAL; roadmap item
   (4) remains OPEN on every public surface — this mission produced the
   shadow mechanization and the unapplied promotion proposal only.
2. `int_cert_sound` binds the artifact to the exact ℚ request under
   `TreeTCB`; it does NOT prove emitter faithfulness, executable identity,
   or request provenance (same honest boundary as bridge #2's
   runtime-provenance note in Ledger.lean:254-267).
3. The certified derivative chains are Lean's `D` (no `simplify_bound`
   interleave): integer-power integrands refuse taylor4 through domains
   containing 0 (BACKLOG #3) — fail closed, never unsound.
4. The per-leaf acceptance policy is checked in exact ℚ; the engine
   evaluates it in f64 — marginal disagreements are refusals, never
   acceptance widening.
5. `source-native-refined` was not granted, referenced, or approached.
6. The shadow `#guard` twins are build-time evaluated (interpreter), not
   kernel theorems — kernel `decide` on concrete ℚ arithmetic is blocked at
   this Mathlib revision (BACKLOG #1); the SOUNDNESS theorem is unaffected.
