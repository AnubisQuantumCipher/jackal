# JACKAL PROVENANCE

Every link in the chain from source to shipped binary to test receipts,
either mechanically derived or measured — and anything that failed
measurement stated as failed rather than papered over.

```text
source → compiler pin → deterministic build → binary hash → gate receipts → adjudication
```

## Seal v1.1.1 — 2026-08-14 (current) — public package identity repair

Preserves the v1.1.0 formal-status code, evaluator, checker, theorem set, and
certificate schema while moving the corrected public package labels into a new
immutable release epoch. The original v1.1.0 release identity remains a
historical scar: its archive was initially published with stale v1.0.4/private
text and was later replaced in place. v1.1.1 is the first release intended to
bind the corrected public labels to its own tag and archive digest without
rewriting a predecessor asset.

The evaluator remains `820c0722e46a0800115c404ea1c9251c6f72fe8c6897bdabe437f342f9310b6c`;
the proved checker remains `2186b43f8e45b7b3e55e189d64e92f15999664f5194caed929d14b29b006f59b`.
The package is unsigned/ad-hoc macOS arm64; SHA-256 identifies bytes but does
not authenticate an author. All formal claim boundaries below remain unchanged.

## Seal v1.1.0 — 2026-08-14 (formal-status predecessor)

Adds the completion-program formal core on top of the sealed v1.0.4 release
bindings: a machine-validated coverage inventory, the canonical formal-status
gate, and the assurance lattice wired into the release path. Certificate
schema advanced to **v2** (checker requires `schema_version=2`; v1 certs are
rejected — epoch separation). This is the "formal-plugin input package" the
Hermes plugin v2 consumes.

### Source / build (byte-reproducible, verified)
- `jackal_calc.anb` SHA-256: `5d43df8de01adb86bb10a0a6cea28fb79faf03cd58be51654c3fa88c653e4a40`
- `jackal-native` SHA-256: `820c0722e46a0800115c404ea1c9251c6f72fe8c6897bdabe437f342f9310b6c` (two clean builds identical)
- `jackal_cert_check` SHA-256: `2186b43f8e45b7b3e55e189d64e92f15999664f5194caed929d14b29b006f59b`
- deterministic package root: `9f28472dbaa516be8534c7e52548463328d4571eb06ba8b241f115a7cf4bc111`
- compiler pin `anubis-a733565f237d` (unchanged).

### What v1.1.0 adds
- **Coverage inventory** (`release/coverage/formal_coverage_inventory.json`,
  `tools/coverage_inventory.py`): 18 FORMAL operators (num/var/const/neg/add/
  sub/mul/div/pow-n≥0/sin/cos/abs/floor/ceil/round/trunc/min/max) wired
  engine→cert→checker→`Runs`→`cert_check_sound`; 15 REFUSED
  (transcendentals/general-neg-pow/mod, fail closed); weaker lanes kept at
  their honest class. Cross-checked against the live `Runs` constructors.
- **Formal-status gate** (`tools/formal_status_gate.py`): the ONE authority
  that assigns `formal-exact`/`formal-bounded`, derived only from a real
  checker ACCEPT over a live-verified FORMAL operator + matching theorem id +
  request binding. Repo/CI recomputes the FORMAL set from the live trees
  (tamper → `inventory-integrity`); the shipped package trusts the inventory
  via the `SHA256SUMS` seal.
- **Release path** now derives `status=formal-bounded` through the gate
  (`cert-status=bounded` kept distinct), refusing formal status for any
  operator outside the fragment.

### Gate receipts (2026-08-14, all green vs this epoch)
| Gate | Result |
|---|---|
| `lake build` | 8679 jobs; `cert_check_sound`/`cert_encloses`/`certified_release` axioms `[propext, Classical.choice, Quot.sound]` only |
| self-test / suite / campaign / iv / parser | 83/83 · 200/200 · 250 (0-viol) · 300 (0-viol) · 78/78 |
| executed negative controls | 30/30 at intended layer (+ `python3 -O`) |
| positive corpus | 20/20 `formal-bounded` through the shared validator (full fragment) |
| fresh-extraction package smokes | 7/7 |
| formal-status gate mutation (§382) | caught as `inventory-integrity` |
| evidence independent verifier | PASS |

**Claim boundary.** `formal-bounded` means: the released interval is a
checker-accepted, `Runs`-derived enclosure of the exact semantics for the
exact request over the modeled fragment, under the recorded TCB (libm ≤ 2 ulp
for the const node, Lean kernel + checker build toolchain, canonical rational
codec). NOT claimed: universal correctness, transcendental operators,
`bound_step`, source→native, emitter-faithfulness theorem, Apple signing, or
artifact authorship authentication by SHA-256. The repository is public; that
visibility does not strengthen the mathematical claim.

## Seal v1.0.4 — 2026-08-14 (formal-binding predecessor)

Corrective **release-binding** epoch. v1.0.3 proved the checker core and a
working certificate path, but its *runtime release seal* lacked exact
request/evaluator bindings and shipped partly documentary controls and
`/tmp`-only evidence (independent Hermes audit). v1.0.4 supersedes that runtime
seal — the Lean proof core is unchanged and un-weakened — without erasing the
scar.

### The v1.0.3 runtime-seal defect (preserved scar, mission §460)
Hermes reproduced these on v1.0.3 and they are now closed:
- **A** — the certificate's `source` field was empty and unchecked; a forged
  base64 source still produced checker ACCEPT.
- **B** — the certificate's `exe` field was empty and unchecked; a forged
  evaluator identity still produced checker ACCEPT.
- **C** — the release receipt labeled the **launcher** hash
  (`de049b95…`) as `engine.sha256`; the real engine is `jackal-native`.
- **D** — several mandatory controls were documentary `True` rows, not executed.
- **E** — the positive corpus lived only under `/tmp`, not shipped.
- **F** — the release was called "publicly downloadable"; the repository is
  PRIVATE and the asset requires authenticated access.

The checker soundness was never the defect (`JACKAL_BRIDGE2_PROOF_CORE_PASS`);
the runtime release seal was (`JACKAL_V1.0.3_RUNTIME_RELEASE_SEAL_BLOCKED`).

### Source / compiler / build (schema v2 epoch)
- `jackal_calc.anb` SHA-256: `5d43df8de01adb86bb10a0a6cea28fb79faf03cd58be51654c3fa88c653e4a40`
- pin `anubis-a733565f237d` (`a733565f237df171e7cf93b9b37700a42d8713576818fd92f8cd23a8ad7a69e2`).
- `jackal-native` SHA-256: `820c0722e46a0800115c404ea1c9251c6f72fe8c6897bdabe437f342f9310b6c` (two clean builds identical).
- `jackal_cert_check` SHA-256: `2186b43f8e45b7b3e55e189d64e92f15999664f5194caed929d14b29b006f59b` (compiled from the proved `checkCert`).
- Package root (`SHA256SUMS`): `bd6dc77bbfe46f1ce83df3536118b43f7848a1ed205f0c06584548a78401a086` (deterministic; two builds identical).

### What changed
- **Cert schema v2**: the checker now requires `schema_version = 2`; old v1
  empty-field certificates are REJECTED (epoch separation). Proof core
  unchanged — `cert_check_sound`/`cert_encloses`/`certified_release` still
  audit to `[propext, Classical.choice, Quot.sound]` only.
- **Exact bindings in the certificate**: non-empty `exe` (evaluator identity,
  passed via an explicit non-ambient argument) and `source` (an injective,
  length-delimited request commitment).
- **One shared release validator** (`tests/release_validate.py`), used by both
  production and the adversarial controls, binding: exact request commitment
  vs argv; exact evaluator+checker executable identity (pinned in
  `release/MANIFEST.sha256`, pre/post-hashed, TOCTOU); canonical parse; the
  checker's ACCEPT protocol; cert-bytes-checked == released; 0600 temp; no
  status escalation; no stale success receipt. No `assert` on load-bearing
  gates; `python3` and `python3 -O` verdicts identical.
- **The wrapper invokes `jackal-native` directly** (not the launcher — C fixed).

### Gate receipts (2026-08-14, against this epoch, all green)
| Gate | Result |
|---|---|
| `lake build` + axiom audit | green (8679 jobs); the three theorems `[propext, Classical.choice, Quot.sound]` only |
| native self-test / suite / campaign / iv / parser gate | 83/83 · 200/200 · 250 0-viol · 300 0-viol · 78/78 |
| Executed negative controls (`tests/cert_controls.py`) | **30/30** each failing at its intended layer; JSONL sha256 `2f8f65676c55a37387e1015207f18bd52071534f0d21b62fc070e0fe023f6b87`; identical under `python3 -O` |
| Positive corpus (`tests/cert_positive_corpus.py`, through the shared validator) | **20/20 bounded**, full 18/18 fragment coverage; JSONL sha256 `ff844db9c4f26889ebac996365ae2fe9c8601d4ec68b4d197f497506ad03e04f` |
| Independent evidence verifier (`tests/cert_evidence_verify.py`) | PASS — non-vacuous, complete, no documentary rows |
| A→B→A mutations M1/M2 (`tests/cert_aba_mutations.py`) | PASS — refuse → admit-on-disable → refuse, restored by hash; receipt sha256 `6bbfaf1af6b9504ab8d312f676a8728284b7a1644b48549fc12d58fffa7c75d2` |
| Fresh-extraction package smokes (`tests/package_smoke.py`) | 7/7 — valid bounded; unsupported/forged-request/forged-evaluator/forged-checker/missing-checker/manifest-tamper all refuse; output identifies exact packaged hashes |

### Claim boundary (unchanged, §189/§629)
For every admitted request in the certified fragment, a released
`status=bounded` result carries a checker-accepted certificate AND passes the
shared validator's request/evaluator/checker/TOCTOU bindings. Checker
acceptance mechanically implies a `Runs` derivation (enclosure under
`ModelTCB`); the validator adds the runtime provenance the theorem does not
prove (§270). NOT claimed: universal correctness, unsupported operators,
bigint/rational proofs, `bound_step`, source→native, emitter-faithfulness
theorem, Apple Developer ID signing / notarization, or **public** access — the
repository and release are **PRIVATE / authenticated-only**.

## Seal v1.0.3 — 2026-08-14 (superseded by v1.0.4; runtime seal was overstated)

Adds implementation-correspondence bridge #2: a PROOF-CARRYING `ieval` → `Runs`
certificate. Certified `range-bound-cert` results carry a machine-checkable
witness; the Lean-proved checker accepting it mechanically implies a true
enclosure under the named model TCB.

### Source
- `jackal_calc.anb` SHA-256: `a6dc3619cf46ea806c487294ee80d39a51b986499372559d100b3f328785734a`
- Git: the commit tagged `v1.0.3`.
- Change vs v1.0.2: a new `range-bound-cert` command — an EXACT-RATIONAL
  interval evaluator (reusing the big-rational engine) that emits a canonical
  evaluation certificate for its actual computation — plus the fail-closed
  release wrapper `jackal-cert-release`. No existing command changes.

### Compiler
- pin `anubis-a733565f237d` (unchanged), SHA-256 `a733565f237df171e7cf93b9b37700a42d8713576818fd92f8cd23a8ad7a69e2`.

### Build — byte-reproducible, verified
- shipped `jackal-native` SHA-256: `b70c22f11463cd07d963ebe5dae4b9f558eae60ba635b28ee8bd89cadcde0239`
  (two clean builds identical).

### Gate receipts (2026-08-14, against this binary/pin, all green)

| Gate | Result |
|---|---|
| `anubis check` + native self-test | passed; 83/83 |
| Black-box acceptance suite | 200/200 |
| Containment campaign (`bound_campaign.py 250 20260813`) | 246 bounded, 4 refused, **0 violations** |
| mpmath.iv differential (`iv_differential.py 300 20260813`) | 300 OK, **0 violations** |
| Lean mechanization (`proofs/lean`, 24 modules) | `lake build` green (8679 jobs); zero `sorry`; bridge-#2 theorems `cert_check_sound`/`cert_encloses`/`certified_release` audit to `[propext, Classical.choice, Quot.sound]` only |
| **Certificate positive corpus** (`range-bound-cert` → `jackal_cert_check`) | 18/18 ACCEPT across the certified fragment; JSONL sha256 `69beae32d196d23198435b882c081b786723a14c6edf3795c17b4a87e5f8a6e2` |
| **24 negative controls** (`tests/cert_controls.py`) | 31/31 poison cases fail for the intended semantic reason (CHECK_REJECT / PARSE_REJECT / ENGINE_REFUSE / RELEASE_REFUSE); JSONL sha256 `6c4db75da081bcea5e73f967fe706e871536a9d97a9c8f6ed57a2b9b6f1b4cd3` |
| **A→B→A tamper** (`tests/cert_tamper.sh`) | PASS — a non-enclosing emitter mutation (still compiles+runs) is REJECTED by the checker; restore hash-verified (`7a73425f…` canonical), stale build purged; gate green again |

### Bridge #2 — what is proved vs tested vs open

- PROVED (Lean): `cert_check_sound` — an accepted certificate (checked by the
  COMPUTABLE `checkCert`, compiled DIRECTLY into `jackal_cert_check`, no
  `@[implemented_by]` on the trust path) induces a `Runs` derivation; composed
  to `cert_encloses` / `certified_release` (the §189 statement). The whole-tree
  induction `runs_of_check` reconstructs all 31 `Runs` constructors. Named TCB:
  `ModelTCB = LibmModel ∧ ConstTCB` (8 transcendental libm bounds + the
  const-rounding declared-value facts — Prop hypotheses, never axioms).
- TESTED, not proved: that the Anubis `range-bound-cert` emitter faithfully
  produces the certificate for the computation it performed (positive corpus +
  24 controls + A→B→A tamper). The canonical ℚ codec and the Lean
  compiler/runtime that builds `jackal_cert_check` are in the TCB.
- FAIL-CLOSED (outside the bridge): the true-transcendental operators
  (sqrt/exp/ln/atan/asin/acos/hypot/atan2/tan/cbrt/log10/log2/%) and negative
  integer powers — the emitter refuses them (a soundness decision: routing them
  through ℚ→f64→libm→decimal→ℚ could exceed δlib and make `LibmModel` false).
- OPEN, unclaimed: `bound_step` release-policy composition and source→native
  refinement remain the last two bridges.

**Claim boundary (verbatim §189).** For every admitted request in the
mechanically defined certified fragment, any `range-bound-cert` result released
as certified carries a checker-accepted certificate; checker acceptance
mechanically implies a `Runs` derivation and therefore the released interval
encloses the exact semantics under the stated model and TCB. NOT claimed:
universal correctness, all operators, bigint/rational proofs, `bound_step`,
source→native, or libm/hardware beyond the stated TCB.

## Seal v1.0.2 — 2026-08-14 (superseded by v1.0.3)

Adds implementation-correspondence bridge #1: the engine's parser and lowering
lifted onto a single canonical Lean `Expr`, with a machine-checked
correspondence theorem and a parser differential gate.

### Source
- `jackal_calc.anb` SHA-256: `6fb22d3df4f6940d4b1734ce9be13f86bd322b98a74a639310fafca3746a29bb`
- Git: the commit tagged `v1.0.2`.
- Change vs v1.0.1: two inert diagnostic commands, `parse-dump` and
  `lower-dump`, emitting the real parse tree / certified-lane lowering in
  canonical s-expression form (via a new `ast_sexp`). No existing command's
  behavior changes.

### Compiler
- pin `anubis-a733565f237d` (unchanged), SHA-256 `a733565f237df171e7cf93b9b37700a42d8713576818fd92f8cd23a8ad7a69e2`.

### Build — byte-reproducible, verified
- shipped `jackal-native` SHA-256: `f83af0793e897d07cae02e3a0fac0feab6cf079606a27180cee2da239d9fe1eb`
  (two clean builds identical).

### Gate receipts (2026-08-14, against this binary/pin, all green)

| Gate | Result |
|---|---|
| `anubis check` + native self-test | passed; 83/83 |
| Black-box acceptance suite | 200/200 (incl. Kepler-conditioning and Fresnel-certification cases) |
| Containment campaign (`bound_campaign.py 250 20260813`) | BOUND_OK=246 REFUSED=4 **0 violations**; JSONL sha256 `28e834552271105cd367225d779caa0d09f629f553b1b6466d6b684cd8bdf32f` |
| mpmath.iv differential (`iv_differential.py 300 20260813`) | OK=300 **0 violations**; median width ratio 1.000; JSONL sha256 `60fe6093bd015849609586fc374be448139ab2293a5a07109dc84a802ed89f6a` |
| **Parser correspondence gate** (`parser_differential.py`) | **78/78** (30 accepted MATCH, 9 refused BOTH_REFUSE, 3 parser-only), all case IDs unique; green against both source and the shipped binary; `--tamper` self-test PASS |
| **Parser tamper cycle** (recorded) | a semantic mutation of the runnable `Dump` mirror's power rule (base↔exponent) that still COMPILES and RUNS produced an observable `PARSE_DRIFT` + nonzero gate; restore verified by hash equality to canonical `Parser.lean` `3a219bc3…` and `Dump.lean` `3baba941…`; stale exe purged; gate green again |
| Lean mechanization (`proofs/lean`, 20 modules, ~6,200 lines) | `lake build` green; 170+ theorems, zero `sorry`; flagship theorems audited to `[propext, Classical.choice, Quot.sound]` only |

### Bridge #1 — what is proved vs gated vs open

- PROVED (Lean, this seal): one canonical `Syntax.Expr` unifying enclosure and
  differentiation; `Parser.parse` (determinism + structural rejection lemmas)
  mirroring the recursive-descent grammar; `Lower.lower` mirroring
  `simplify_bound` with **`lower_preserves_sem`** and `lower_preserves_defined`;
  and the composition `parse_lower_denotes` (the admitted source denotes
  `sem ast`, preserved by lowering) / `parse_lower_encloses` (that denotation,
  threaded through `runs_encloses`, is enclosed at every point). ~30 operators
  wired into `Runs`.
  `#print axioms parse_lower_denotes` = `#print axioms parse_lower_encloses` =
  `[propext, Classical.choice, Quot.sound]` — the `@[implemented_by]` runnable
  mirror is a compiler directive, NOT an axiom, and is excluded from theorem
  trust (it lives only in the differential gate's TCB).
- GATED, not proved: byte-for-byte identity of the Lean parser to the SHIPPED
  engine parser (the differential gate over a finite corpus).
- OPEN, unclaimed: still-fail-closed operators tan/cbrt/log10/log2/mod; the
  actual `ieval`→`Runs` bridge; `bound_step` release-policy composition; and
  source→native refinement. The exact target claim is unchanged — universal
  correctness over the precisely admitted certified fragment and its stated TCB,
  never unqualified.

**Claim boundary (unchanged, cross-audited).** The certified fragment's
mathematical model is universally mechanized under stated assumptions, and the
front-end correspondence now ties the admitted *source string* to it; the
shipped implementation is tested, differential-gated, reproducible, and sealed
— NOT mechanically proved to refine the model. Neither half quoted without the
other.

## Seal v1.0.1 — 2026-08-13 (superseded by v1.0.2)

### Source

- `jackal_calc.anb` SHA-256: `43810ce5b8e5fe05be7c3411067b00d0aaa74b8083accdbca6e840ecfa10e2b9`
- Git: the commit tagged `v1.0.1` in this repository.
- Change vs v1.0.0: `solve` conditioning diagnostics (derivative-estimate,
  condition-amplification, first-order root-error-estimate) — field-adjudicated
  the same day on a near-parabolic Kepler equation where a 2.3e-20 residual
  accompanied a 1.3e-12 root error (amplification ~6.06e7; the printed estimate
  matched the independently measured error to two significant figures).

### Compiler

- pin: `anubis-a733565f237d` (content-addressed snapshot; anubis-lang commit `b3390c7c`)
- pin SHA-256: `a733565f237df171e7cf93b9b37700a42d8713576818fd92f8cd23a8ad7a69e2`

### Build — byte-reproducible, verified

Same recipe as v1.0.0. Two clean builds of this source: byte-identical.

- shipped `jackal-native` SHA-256: `d8dd82a23f0b5f920c2f26bab734d45b050d2219007eef573ae69313daaa7d22`

### Gate receipts (2026-08-13, all against this binary/pin, all green)

| Gate | Result |
|---|---|
| `anubis check jackal_calc.anb` | passed |
| Native self-test | 83/83 invariants |
| Black-box acceptance suite | TOTAL **200/200** — now includes the Kepler-conditioning case and the Fresnel integral (~796 oscillations) certified-enclosure case |
| Seeded containment campaign (`tests/bound_campaign.py 250 20260813`) | BOUND_OK=246 REFUSED=4 ORACLE_SKIP=0 **CONTAINMENT_VIOLATION=0 WIDTH_VIOLATION=0**; JSONL sha256 `28e834552271105cd367225d779caa0d09f629f553b1b6466d6b684cd8bdf32f` (the harness oracle may legitimately choose antiderivative vs quadrature per run, so campaign JSONLs are not byte-stable across runs; counts and verdict are the receipt) |
| Cross-implementation differential gate (`tests/iv_differential.py 300 20260813`) | OK=300 **POINT_VIOLATION=0 DISJOINT_IMPLEMENTATIONS=0**; median width ratio vs mpmath.iv = 1.000; JSONL sha256 `60fe6093bd015849609586fc374be448139ab2293a5a07109dc84a802ed89f6a` — byte-identical to the v1.0.0 runs (range-bound behavior unchanged) |
| Lean 4 mechanization (`proofs/lean`, 14 modules, ~4,000 lines) | `lake build` green (8,670 jobs); **121+ theorems, zero `sorry`**; 42 flagship theorems axiom-audited to exactly `[propext, Classical.choice, Quot.sound]`; independently cross-audited read-only the same day (fresh-snapshot rebuild: clean; `runs_encloses` axiom audit: clean) |

### What the Lean development now covers

Pad model; add/sub/neg/mul/div; integer, negative, and positive-base general
powers; exact ops (abs/min/max/floor-family/hypot/atan2); monotone rule with
exp/sqrt/log/arctan/arcsin/arccos; sin/cos hulls across all widening branches;
**float critical-point-test conservativity** on the engine's parameter range;
bisection bracket soundness and the backward-error bound behind `solve`'s new
diagnostics; float-midpoint containment; Taylor-2/4 midpoint enclosures; the
**deep-embedded composition theorem** `runs_encloses` (every modeled execution
over every interval encloses the exact semantics at every point — universal
quantifiers, no sampling); and the **evaluability-certifies-smoothness chain**
composing end-to-end into the Taylor theorems. The target claim, stated
exactly: universal correctness over the precisely admitted certified fragment
and its stated TCB — never "universal correctness" unqualified. Residuals and
the next-wave bridge roadmap (parser→Expr, ieval→Runs, bound_step composition,
source-to-native refinement) are enumerated in `proofs/lean/JackalIv/Ledger.lean`.

**Claim boundary (cross-audited 2026-08-13).** The certified fragment's
mathematical *model* is universally mechanized under its stated assumptions.
The shipped *implementation* passed the stated tests, differential and
containment gates, reproducibility checks, and this seal — it is **not**
mechanically proved to refine that model; implementation refinement is the
future work named above. Neither half of that sentence should be quoted
without the other.

## Seal v1.0.0 — 2026-08-13 (superseded by v1.0.1)

### Source

- `jackal_calc.anb` SHA-256: `b74d078db6acc7b73f81001ed823643df037e4770b6062c15de411ff571f5384`
- Git: the commit tagged `v1.0.0` in this repository.

### Compiler

- pin: `anubis-a733565f237d` (content-addressed snapshot; anubis-lang commit `b3390c7c`)
- pin SHA-256: `a733565f237df171e7cf93b9b37700a42d8713576818fd92f8cd23a8ad7a69e2`

### Build — byte-reproducible, verified

```bash
ANUBIS_BIN=$HOME/anubis-lang/vm/pins/anubis-a733565f237d \
  JACKAL_FORCE_SOURCE=1 JACKAL_OUT=./.build ./jackal self-test
cp ./.build/anubis_run ./jackal-native && chmod +x ./jackal-native
```

- shipped `jackal-native` SHA-256: `609de1035be62a5183ad6555b97402567c9e4539b41806a5b52974f6be9030ae`
- **Byte-reproducibility: verified.** Repeated clean builds of the committed
  source with this pin are fully byte-identical (same SHA-256, linker UUID
  included), across differing out-dir paths including one containing spaces.
  Anyone holding the pin can rebuild and compare. The GitHub release for
  `v1.0.0` ships this exact binary with a `SHA256SUMS` file.

### Gate receipts (2026-08-13, all against this binary/pin, all green)

| Gate | Result |
|---|---|
| `anubis check jackal_calc.anb` | passed |
| Native self-test | 83/83 invariants |
| Black-box acceptance suite (`tests/test_calculator.py`, source-built via pin) | TOTAL 198/198, includes 7 enclosure-contains-independent-oracle checks |
| Seeded containment campaign (`tests/bound_campaign.py 250 20260813`) | BOUND_OK=246 REFUSED=4 **CONTAINMENT_VIOLATION=0 WIDTH_VIOLATION=0**; JSONL sha256 `4473208f8e15715f67734fc14a322afca9c52687448f93f2357768e1d36186fa` — byte-identical to the pre-pin-swap run, a determinism receipt in itself |
| Cross-implementation differential gate (`tests/iv_differential.py 300 20260813`, vs mpmath.iv + 40-digit point sampling) | OK=300 **POINT_VIOLATION=0 DISJOINT_IMPLEMENTATIONS=0**; median width ratio vs mpmath.iv = 1.000; JSONL sha256 `60fe6093bd015849609586fc374be448139ab2293a5a07109dc84a802ed89f6a` — also byte-identical across binaries |
| Lean 4 mechanization of the interval model (`proofs/lean`, Mathlib v4.32.0) | `lake build` green; 60+ theorems, zero `sorry`; `#print axioms` on all flagship theorems (incl. `taylor2/4_midpoint_enclosure`) = `[propext, Classical.choice, Quot.sound]` only; unproven residuals enumerated in `JackalIv/Ledger.lean` |
| Adversarial multi-lens review (4 lenses, 20 agents, adversarial verify per finding) | 11 confirmed findings (2 critical soundness, 2 major honesty, 7 minor) — all fixed in commit `8a71540` with regression coverage; 2 findings refuted |

### zk-receipt binding (reconciled)

`guest_source_sha256` in `proofs/zk-receipt/risc0_metadata.json` digests the
deterministic transpiled Rust guest (`guest_source.rs`), not the `.anb`
bytes. Re-derived 2026-08-13 from the committed
`proofs/jackal_proof_guest.anb`: transpile hash identical (`2d11f1bf…`),
guest ELF byte-identical (`d363e61d…`), ImageID identical, fresh receipt
verifies with the same journal (`8`). Details in
`proofs/zk-receipt/VERIFY.md`.

## Build-determinism history (how the reproducibility claim was earned)

Earlier pins were **not** byte-reproducible: repeated builds of identical
source produced distinct binaries. The divergence was diagnosed stage by
stage on 2026-08-13:

1. Anubis → Rust transpile: byte-deterministic all along (every build of
   source `b74d078d…` emits `anubis_run.rs` with SHA-256 `3e4fde1e…`).
2. rustc → binary: layout permuted per build. Root cause: the compiler
   generated a randomized per-build Cargo package name, which cargo folds
   into the crate metadata hash, which decides symbol mangling and
   codegen-unit layout.
3. Fix (anubis-lang commit `b3390c7c`): content-derived package name
   `anubis_run_<sha256(generated .rs)[..12]>` — reproducible for identical
   source, unique across programs, and same-name collisions under the shared
   target dir became benign (same name now implies same bytes).

`tests/content_hash.py` (hashes only code/data segments, excluding Mach-O
headers and linker metadata) remains available for comparing binaries across
toolchains.

## Prior seal — 2026-08-13, superseded

- Compiler pin `anubis-51f4a964347a`
  (`51f4a964347a4a0f3ea2833331eb313315aa502c96c9d7a71fc3b20414eca027`),
  non-reproducible builds; chain bound the exact gate-tested binary
  `c37a256c38c5819e24b31c405152fb61fe06bcf4f05550dee9e5c4e8e080c2c2`
  (commits `8a71540`/`11cac9b`). All gates were green against that binary
  with the same source hash; the v1.0.0 seal reproduces those results.
- The original 1,402-case behavioral campaign (adjudicated
  `NO_UNEXPLAINED_MISMATCHES`, 2026-08-13) bound to artifact
  `211c614b46f986d826b1e3272a4190b63178d83fb389bbf1d910162420c4295b` — the
  engine as it existed *before* the certified lane. That receipt remains
  valid for that artifact.

## Non-claims

Finite campaigns do not establish universal correctness. The certified
lane's enclosures are conditional on the stated f64 rounding model
(correctly rounded basic ops; libm within 2 ulp) and on an implementation
that is campaign-tested — its mathematical *model* is machine-checked in
`proofs/lean/`, the implementation itself is not. `jackal maturity` prints
the per-command epistemic grades.

## Regenerate

```bash
shasum -a 256 jackal_calc.anb jackal-native
ANUBIS_BIN=$HOME/anubis-lang/vm/pins/anubis-a733565f237d python3 tests/test_calculator.py
python3 tests/bound_campaign.py 250 20260813
python3 tests/iv_differential.py 300 20260813
cd proofs/lean && lake exe cache get && lake build
```
