# JACKAL PROVENANCE

Every link in the chain from source to shipped binary to test receipts,
either mechanically derived or measured — and anything that failed
measurement stated as failed rather than papered over.

```text
source → compiler pin → deterministic build → binary hash → gate receipts → adjudication
```

## Seal v1.4.1b — 2026-08-15 (current) — self-audit closure

Immediately after landing v1.4.1a I did a personal audit sweep and found
the outer-seal work still had holes I hadn't caught.  Closing them here.

### 🔴 Real functional gap: packaged plugin refused sqrt/exp

The v1.4.1a plugin-server change added `_manifest_alias({"sqrt_rat_producer"}, ...)`
and the analogous `exp_rat_producer` lookup, but `release/build_package.sh`
never emitted those labels into the *packaged* `MANIFEST.sha256`.  Result:
`plugin/hermes/jackal_hermes call jackal_sqrt_rat_bound …` on any
fresh-extracted package refused with
`{"reason": "plugin-manifest-incomplete", "detail": "sqrt_rat_producer: expected exactly one of ['sqrt_rat_producer'], got []"}`.
The repo path worked (repo MANIFEST had the labels); the shipped path did
not.  A user calling the plugin from the tarball would have been dead in
the water.

`build_package.sh` now hashes both producer files and emits
`sqrt_rat_producer sqrt_rat_producer.py $SHA` and
`exp_rat_producer exp_rat_producer.py $SHA` inside the MANIFEST heredoc.
`tests/package_smoke.py` gained explicit `sqrt-rat-release-cli`,
`exp-rat-release-cli`, `exp-rat-release-cli-refuse-neg`,
`plugin-sqrt-rat`, and `plugin-exp-rat` cases so this regression class
cannot land silently again.  Package smoke now runs 16 fresh-extraction
cases (up from 11).

### 🟡 Producer identities were unpinned in the release wrappers

`jackal-sqrt-rat-release` and `jackal-exp-rat-release` (both repo top-level
and packaged embeddings) previously invoked the producer directly with no
identity check.  Every other formal lane (`jackal-cert-release`,
`jackal-gaussian-release`, the plugin's `tool_range_bound` /
`tool_sqrt_rat_bound` / `tool_exp_rat_bound`) hashes the executables
before and after the call against `MANIFEST.sha256` pins.  Now the two
standalone wrappers do the same: `producer-identity`, `producer-toctou`,
`checker-identity`, `checker-toctou` are stable refusal classes here too.

### 🟡 Coverage inventory missed the two new plugin tools

`release/coverage/formal_coverage_inventory.json` had 4 plugin rows
(`jackal_range_bound`, `jackal_gaussian_integral`, `jackal_verify_receipt:range`,
`jackal_verify_receipt:gaussian`) but no rows for `jackal_sqrt_rat_bound` or
`jackal_exp_rat_bound`.  The operator rows for `sqrt` and `exp` also still
pointed `plugin_tool: jackal_range_bound`, which is wrong — that tool
refuses sqrt/exp because it routes through the engine which does not emit
sqrt_rat/exp_rat certs.  Added a `_OPERATOR_PLUGIN_TOOL` routing table so
`sqrt` → `jackal_sqrt_rat_bound` and `exp` → `jackal_exp_rat_bound`, and
two new `plugin-tool` rows describing the standalone-producer path.
Inventory now 50 rows (26 FORMAL), was 48/24.

### 🟡 GETTING-STARTED.md was entirely v1.3-era

The user-facing quickstart never mentioned any formal-release CLI or the
Hermes plugin.  A new user reading the guide could not discover the
whole v1.4.x lane.  New §5b ("Proof-carrying releases — the
formal-bounded lane") walks through all five release wrappers with
concrete `awk`-driven `--expected-*` invocations; §5c documents the
twelve-tool Hermes plugin surface with three worked examples.

### 🔵 Cosmetic docstring drift (5 files)

`tests/{cert_controls,cert_mutations_11,fail_closed_sweep}.py` +
`tools/{formal_receipt,receipt_verify}.py` still opened with
`"""JACKAL v1.3.0 …`.  All five now say `v1.4.1`.  Load-bearing
`release_epoch="v1.3.0"` DEFAULTS in `release_validate.py` /
`gaussian_release.py` / `receipt_verify.py` are intentionally left alone —
they are the shared-API backward-compat default, and every v1.4.x
wrapper and the plugin already override them explicitly to `v1.4.1`.

### Deliberately deferred

Extending `jackal-formal-receipt-v1` (or introducing a variant envelope)
so `jackal_verify_receipt` can round-trip the `variant=sqrt_rat` /
`variant=exp_rat` payloads.  That requires new schema, new codec passes,
and re-doing `receipt_semantic_mutations.py` against the extended
envelope.  Scoped for v1.4.2, not polish.

### Frozen v1.4.1b identities

```
jackal-native                     820c0722e46a0800115c404ea1c9251c6f72fe8c6897bdabe437f342f9310b6c  (unchanged)
jackal_cert_check                 b567b8a94ce7acd49ecaa807d86a5bb66d695fb0ce4fea2eb84f0073425984d7  (unchanged)
jackal_gaussian_check             42d3f3e74b90062c958baeda9ddf9ddd6f82ef3f8e4dd2b9ade5017239fe7a77  (unchanged)
range_proof_identity              82376d501264a2aabe1cdce6a373f9c53f2bedf262a25494253131835d8bb2ae  (unchanged)
gaussian_proof_identity           22c59e60b66a7fc6ef232e01fe64967285d36bb65e92847f9b42af721b36a54e  (unchanged)
coverage_inventory                17890f7e001462eb1c38baedad5bcf1d977a55e1d0258d4ddf233ba1ac86b1dd  (v1.4.1a: 113828eb… → +2 plugin-tool rows)
plugin_hermes                     fa5dc67098b80ef47977874b9636499b9f4b84fdb4fafaadc107a73c1fa6140d  (v1.4.1a: c613df47… → server.py hardened)
sqrt_rat_producer                 4bc95c331430d2350facfb19da9aba483ab7b3698754e7af2e5deb797e097926  (unchanged)
exp_rat_producer                  ccbc48633bd3980613413399d552321eaa67b15bd101643e53b0dd5f10a37918  (unchanged)
package tarball                   1da476ba5020376780598caa80d548893d94f86db23027e6e23d37e27a729581
                                  (byte-reproducible across two rebuilds)
```

### Gate receipts on the v1.4.1b final bytes (16/16 + package smoke 16 cases)

Lake build 8682 jobs · Range + Gaussian proof identity · Positive corpus 20/20 ·
Negative controls 30/30 · A→B→A 2-mutation 2/2 · 11-category mutations 11/11 ·
Formal-status gate 11/11 · sqrt_rat 7/7 · exp_rat 8/8 · Plugin smoke S1..S16
(with S14/S15/S16 for the two new formal tools) · Plugin bundle identity 17 files ·
output_path_safety 6/6 · receipt_semantic_mutations 24/24 · Gaussian receipt +
mutations · Package smoke **16 cases** (up from 11) including new
`sqrt-rat-release-cli`, `exp-rat-release-cli`, `exp-rat-release-cli-refuse-neg`,
`plugin-sqrt-rat`, `plugin-exp-rat`.  Deterministic tarball across two
consecutive rebuilds.

## Seal v1.4.1a — 2026-08-15 (predecessor) — outer-seal drift closed

A candid third-party audit against the v1.4.1 push flagged five outer-seal
drifts where the plugin/wrapper/documentation surface had NOT caught up to
the v1.4.1 core:

1. `jackal-cert-release` still declared `# JACKAL v1.3.0` and passed
   `--release-epoch v1.3.0`.
2. `plugin/hermes/tools.json` still declared `"version": "v1.3.0"` even
   though the tools array had grown from 3 → 10.
3. `plugin/hermes/README.md` still claimed "exactly three tools",
   contradicting `tools.json`.
4. `tests/plugin_smoke.py` still declared v1.3.0 in its docstring and
   the `RANGE_CONTEXT` / `GAUSSIAN_CONTEXT` `expected_release_epoch`, and
   `S4` expected `sqrt(x)` to be refused by *every* plugin lane — while
   the coverage inventory had it promoted to FORMAL in v1.4.0 (the
   real gap was that the plugin exposed NO tool routing to `sqrt_rat`
   or `exp_rat`).
5. `evals/report.md` pinned identities were the v1.3.0 execution-moment
   snapshot but were labeled "release/MANIFEST.sha256" without a
   qualifier, giving the impression the report referenced the current
   manifest (it did not — a mid-run `plugin-bundle-mismatch` event is
   also documented in the same report).

All five closed in one commit:

**Plugin surface expanded from 10 → 12 tools.** Two new formal tools
expose the pure-ℚ fragment extensions the standalone CLI wrappers
already ship:

* `jackal_sqrt_rat_bound` routes through `tools/sqrt_rat_producer.py`
  + the pinned `jackal_cert_check`, TOCTOU-stable identities pre/post,
  and returns `variant=sqrt_rat`, the exact rational enclosure endpoints,
  the certificate bytes (base64) with SHA-256, and the pinned
  producer/checker/plugin identities.  Refusal classes:
  `plugin-fragment` (non-sqrt expression), `producer-refused` (negative
  lower), `producer-identity` / `producer-toctou` /
  `checker-identity` / `checker-toctou` (identity or byte drift).
* `jackal_exp_rat_bound` is the analogous adapter for
  `tools/exp_rat_producer.py` (positive-argument branch only).

Both variants return a `variant`-marked payload rather than the
`jackal-formal-receipt-v1` envelope; `jackal_verify_receipt` does NOT
currently accept variant payloads — the receipt-verify round-trip is a
documented follow-up.  Downstream can still independently re-run the
pinned checker on the embedded `certificate_b64` bytes today.

**Runtime bundle contract.** The two producer files were added to
`plugin/hermes/tools.json` `runtime_files` (17 files total), so
`plugin/hermes/bundle_hash.py` covers them.  The `plugin_hermes` pin in
`release/MANIFEST.sha256` moved to
`c613df4731bf8abe9ff4eed476e278921562c317a6bff80defe601b82cf6b1c9`.

**Wrapper + smoke bumped to v1.4.1.**

* `jackal-cert-release` header + `--release-epoch v1.4.1`.
* `jackal-gaussian-release` `--release-epoch v1.4.1`.
* `plugin/hermes/server.py` docstring + all four hardcoded `v1.3.0`
  release_epoch strings (in `tool_range_bound` and
  `tool_gaussian_integral`) → `v1.4.1`.
* `tests/plugin_smoke.py` docstring + both context epochs;
  `S8-stdio-transport` `expected_tools` set expanded to 12;
  added **S14** (`jackal_sqrt_rat_bound` accepts on `[2, 3]` with the
  exact rational enclosure of √2/√3), **S15**
  (`jackal_exp_rat_bound` accepts on `[0, 1]` with the exact enclosure
  `[1, 979/360]` of e), **S16** (four refusal classes on
  non-admitted expressions and negative lowers).
* `tests/plugin_bundle_identity_test.py` `EXPECTED_LOGICAL_NAMES` +
  `PACKAGE_DESTINATIONS` grew from 15 → 17.
* `evals/report.md` "Pinned identities" now explicitly labels the
  v1.3.0 execution-moment snapshot AND cross-references the current
  v1.4.1 pins per field.

**No new axioms.** The Lean surface is unchanged from v1.4.1 core;
every flagship theorem's axiom set remains
`[Classical.choice, Quot.sound, propext]`.  The two new plugin tools
call the SAME `jackal_cert_check` on the SAME certificate bytes the
standalone CLI wrappers already validate.

### Frozen v1.4.1a identities

```
jackal-native                     820c0722e46a0800115c404ea1c9251c6f72fe8c6897bdabe437f342f9310b6c
jackal_cert_check                 b567b8a94ce7acd49ecaa807d86a5bb66d695fb0ce4fea2eb84f0073425984d7  (unchanged)
jackal_gaussian_check             42d3f3e74b90062c958baeda9ddf9ddd6f82ef3f8e4dd2b9ade5017239fe7a77  (unchanged)
range_proof_identity              82376d501264a2aabe1cdce6a373f9c53f2bedf262a25494253131835d8bb2ae  (unchanged)
gaussian_proof_identity           22c59e60b66a7fc6ef232e01fe64967285d36bb65e92847f9b42af721b36a54e  (unchanged)
coverage_inventory                113828ebe3aad96a8e70b753abc54699d936b4ccd645d224a5fa88be9a01a0ab  (unchanged)
sqrt_rat_producer                 4bc95c331430d2350facfb19da9aba483ab7b3698754e7af2e5deb797e097926  (unchanged)
exp_rat_producer                  ccbc48633bd3980613413399d552321eaa67b15bd101643e53b0dd5f10a37918  (unchanged)
plugin_hermes                     c613df4731bf8abe9ff4eed476e278921562c317a6bff80defe601b82cf6b1c9  (v1.4.1: fa9976d6… -> c613df47…)
package tarball                   f6984fe4ec0df2ce813a2424b4081b35714157ab194943237d2c7bd3b234f456
                                  (79,278,885 bytes; byte-reproducible across two rebuilds)
```

### Gate receipts on the v1.4.1a final bytes (14/14)

Lake build 8682 jobs · Range + Gaussian proof identity · Positive corpus 20/20 ·
Negative controls 30/30 · A→B→A 2-mutation 2/2 · 11-category mutations 11/11 ·
Formal-status gate 11/11 · sqrt_rat 7/7 · exp_rat 8/8 · output_path_safety 6/6 ·
receipt_semantic_mutations 24/24 · Gaussian receipt + mutations · Package
deterministic + fresh-extraction smoke.  Plugin smoke S1..S16 with the two new
formal-lane accept cases green and the four new refusal classes checked
(`plugin-fragment`, `producer-refused` on each of `sqrt_rat` and `exp_rat`).

**What this seal does NOT do.** It does NOT teach
`jackal_verify_receipt` to accept the `variant=sqrt_rat` / `variant=exp_rat`
payloads — that requires extending `jackal-formal-receipt-v1` (or
introducing a variant envelope) and re-doing the receipt-semantic
mutation harness against it.  That work is scoped for a future patch
release; today the two new tools remain a proof-carrying release *from*
the plugin, not yet a round-trippable receipt *through* the plugin.

## Seal v1.4.1 — 2026-08-15 (predecessor) — pure-ℚ exp fragment extension + CI reproducibility fix

Extends v1.4.0's `sqrt_rat` fragment with the first libm-free
transcendental beyond `sqrt`, `exp` on `[lo, hi]` with `lo >= 0`, and
repairs the CI reproducibility issue reported by the v1.4.0 workflow.

### `exp_rat` — pure-ℚ Taylor with certified remainder (§487 fragment extension)

`exp` (positive-argument branch only) is now in the release fragment:
v1.4.0's 18 operators → v1.4.1's 19.  The extension carries NO new TCB:

* **Lean composition theorem** (`proofs/lean/JackalIv/Embed.lean`,
  `Runs.expRat`): given a child interval `[l, u]` with a bracket
  `argLoQ ≤ l ≤ u ≤ argHiQ` and a rational Taylor degree `n`, the
  constructor accepts iff `0 ≤ argLoQ`, `argHiQ/(n+1) ≤ 1/2`,
  `loQ ≤ expPartial argLoQ n` (in ℝ), and
  `expPartial argHiQ n + expRemainder argHiQ n ≤ hiQ`.  Soundness proved
  by monotonicity of `Real.exp` on `[0, ∞)` combined with the existing
  `real_exp_between` bound in `JackalIv/Gaussian.lean` (which itself
  reduces to `Complex.exp_bound'`).  No libm `Approx` obligation and no
  `ModelTCB` axiom.
* **Executable checker arm** (`proofs/lean/JackalIv/CertCheck.lean`,
  case `"exp_rat"`): six rational inequalities checked in ℚ using
  `expPartial` and `expRemainder` at rational arguments — genuinely
  computable (`Q`/`Bool`/`Nat`/`Int`/`String` only) and reduces in the
  kernel on exact certs.
* **Bridge** (`CertSound.lean`, arm `exp_rat`): `checkNode`-accepted
  `exp_rat` node → `Runs.expRat` derivation → true enclosure.  Same
  three standard Lean axioms as every other flagship theorem:
  `[propext, Classical.choice, Quot.sound]`.
* **Untrusted producer** `tools/exp_rat_producer.py` (§487-fragment
  producer): exact rational Taylor arithmetic in `fractions.Fraction`;
  chooses the smallest safe degree; NEVER trusts float `math.exp`.
  Refuses non-exp expressions and negative lowers fail-closed.
* **Standalone release CLI** `jackal-exp-rat-release "exp(x)" <lo> <hi>`,
  admits ONLY the exact form `exp(x)` and emits
  `assurance=proof-carrying-certificate(checker-accepted;expRat-Runs-derivation;NO-libm-TCB)`.
* **Fragment inventory** (`release/coverage/formal_coverage_inventory.json`):
  `exp` promoted from REFUSED → FORMAL with `runs_constructors=["expRat"]`
  and `soundness_theorem=request_bound_certified_release`.
* **Regression suite** `tests/formal_exp_rat_release_test.py` (8/8):
  canonical `[0,1]`, non-integer `[1/2, 3/2]`, larger `[0, 5]`,
  negative-lower refusal, reversed-limits refusal, non-exp expression
  refusal, cert-bytes tamper refusal, request-relabel refusal.

**Example enclosures released:**
```
jackal-exp-rat-release "exp(x)" 0 1
  → [1, 979/360]                    (~ [1, 2.71944]; contains e ≈ 2.71828)
jackal-exp-rat-release "exp(x)" 1/2 3/2
  → [6331/3840, 11503/2560]         (~ [1.6487, 4.4934]; contains exp(0.5),exp(1.5))
jackal-exp-rat-release "exp(x)" 0 5
  → [1, 10819031/72576]             (~ [1, 149.06]; contains exp(5) ≈ 148.41)
```

### v1.4.0 CI reproducibility repair

The v1.4.0 push reported CI failure with `source_closure.aggregate_sha256`
drift.  Root cause (post-hoc): v1.4.0's `sqrt_rat` addition modified
`CertCodec.lean`, which is transitively imported by `GaussianCert.lean`
via `import JackalIv.CertCodec` — so the Gaussian closure aggregate
changed in v1.4.0 but the committed `gaussian_proof_identity.json` was
not regenerated.  Local range regeneration masked the issue: the range
identity DID get regenerated because I re-ran the range gate manually,
but the Gaussian identity file kept its v1.3.0 aggregate `41585b3e...`.
CI live-recomputed the post-sqrt_rat aggregate and refused as expected.
A second Mathlib linter escalation (`ring` → `ring_nf` on Ubuntu
24.04's Mathlib) also blocked the build.

v1.4.1 fixes both:

* `.gitattributes` forces `text eol=lf` for every source-closure-hashed
  artifact so line-ending drift can never cause an aggregate mismatch
  on Linux/Windows checkouts.
* `proofs/lean/JackalIv/GaussianIntegral.lean:67` switched from
  `ring` to `ring_nf` (Mathlib newer version accepts both; older accepted
  only `ring`, newer treats the linter hint as an error).
* Both `range_proof_identity.json` and `gaussian_proof_identity.json`
  regenerated post-`ring_nf` + post-`exp_rat` — new aggregates now
  committed together with the code they hash.

### Frozen v1.4.1 identities

```
jackal-native                     820c0722e46a0800115c404ea1c9251c6f72fe8c6897bdabe437f342f9310b6c
jackal_cert_check                 b567b8a94ce7acd49ecaa807d86a5bb66d695fb0ce4fea2eb84f0073425984d7
jackal_gaussian_check             42d3f3e74b90062c958baeda9ddf9ddd6f82ef3f8e4dd2b9ade5017239fe7a77
range_proof_identity              82376d501264a2aabe1cdce6a373f9c53f2bedf262a25494253131835d8bb2ae
gaussian_proof_identity           22c59e60b66a7fc6ef232e01fe64967285d36bb65e92847f9b42af721b36a54e
coverage_inventory                113828ebe3aad96a8e70b753abc54699d936b4ccd645d224a5fa88be9a01a0ab
sqrt_rat_producer                 4bc95c331430d2350facfb19da9aba483ab7b3698754e7af2e5deb797e097926
exp_rat_producer                  ccbc48633bd3980613413399d552321eaa67b15bd101643e53b0dd5f10a37918
plugin_hermes                     fa9976d6e5387870eb9cfdf89d7bb42bdb162d5c9ee993616c84ef9ce866b4fb
package tarball                   5fed203d73cc6779584c43af4426e7755d7c0dd3bd298600919d18361712b845
                                  (79,276,433 bytes; byte-reproducible)
```

Every flagship Lean theorem's axioms remain: `[Classical.choice, Quot.sound, propext]`.

### Gate receipts on the v1.4.1 final bytes

| Gate | Result |
|---|---|
| Lean build (`lake build`) | 17336 jobs — clean, zero sorry |
| `Cert.cert_check_sound` axioms | `[Classical.choice, Quot.sound, propext]` |
| `Cert.certified_release` axioms | `[Classical.choice, Quot.sound, propext]` |
| `Cert.request_bound_certified_release` axioms | `[Classical.choice, Quot.sound, propext]` |
| `runs_encloses` axioms | `[Classical.choice, Quot.sound, propext]` |
| Range proof identity | PASS (checker+build binding + axiom audit) |
| Gaussian proof identity | PASS (checker+build binding + axiom audit) |
| Positive corpus (20 cases, 17 op fragment) | PASS |
| Negative controls (30) | 30/30 refused at intended layer |
| A→B→A 2-mutation harness | 2/2 restore-verified |
| 11-category cert mutations | 11/11 restore-verified |
| Coverage inventory (48 rows, 24 FORMAL) | PASS |
| verify_evidence | PASS |
| formal_status_gate selftest | 11/11 |
| formal_sqrt_rat_release_test | 7/7 |
| formal_exp_rat_release_test | 8/8 |
| plugin_smoke (13 cases + weak lanes) | PASS |
| plugin_bundle_identity | PASS |
| output_path_safety | 6/6 write-once-atomic |
| receipt_semantic_mutations | 24/24 refused |
| Gaussian evidence | PASS |
| Gaussian receipt/checker/emitter/mutations | 16/16 rejected, 1 unsupported |
| Package deterministic build | two consecutive rebuilds `5fed203d...` identical |
| Package smoke (fresh extraction) | PASS |

**Claim boundary (v1.4.1).** For every request accepted by the declared
range fragment (now including `sqrt(x)` on any canonical rational
interval AND `exp(x)` on any `[lo, hi]` with `lo >= 0` for a suitable
Taylor degree the producer selects) or Gaussian fragment, checker
acceptance implies the stated enclosure under each receipt's recorded
TCB.  Universal correctness for arbitrary expressions remains NOT
claimed and NOT achievable for a general calculator; unsupported strong
requests refuse rather than silently downgrade.  Package unsigned/ad-hoc;
SHA-256 identifies bytes, not authorship.  Independent external
adversarial evaluation remains pending.

## Seal v1.4.0 — 2026-08-15 (predecessor) — pure-ℚ sqrt fragment extension + in-session eval harness

Extends the sealed v1.3.0 range/Gaussian identities with the first
non-arithmetic operator promoted into the release fragment without any libm
TCB, and ships an in-session empirical evaluation harness measuring how much
the verified-computation kernel reduces confidently-wrong numerical claims
from an LLM vs. calculator vs. Python vs. no tool.

### `sqrt_rat` — first libm-free transcendental (§487 fragment extension)

`sqrt` is now in the release fragment (v1.3.0's 17 → v1.4.0's 18 operators).
The extension carries NO new TCB:

* **Constructor** (`Embed.lean` `Runs.sqrtRat`): parametric in `loQ hiQ : ℚ`
  with four proof obligations — `0 ≤ loQ`, `0 ≤ hiQ`, `loQ² ≤ input.lo`,
  `input.hi ≤ hiQ²`.  Sound by `Real.sqrt` monotonicity on `[0, ∞)`:
  `loQ = Real.sqrt(loQ²) ≤ Real.sqrt(input.lo) ≤ Real.sqrt(x) ≤
  Real.sqrt(input.hi) ≤ Real.sqrt(hiQ²) = hiQ`.  Zero libm, zero pad,
  zero delta.
* **Checker arm** (`CertCheck.lean` `sqrt_rat`): four `decide`
  inequalities over ℚ.  Kernel-reducible.  Fail-closed.
* **Bridge** (`CertSound.lean`): `runs_of_check` case discharges to
  `Runs.sqrtRat`; axiom footprint unchanged (three standard Lean axioms
  on every flagship theorem).
* **Codec** (`CertCodec.opFields`) + **buildExpr/buildRawExpr**
  (`CertTypes.lean` / `CertRequest.lean`): `sqrt_rat` renders to
  `(call sqrt …)` and lowers to `.call1 "sqrt"`.  The strategy annotation
  lives on the certificate node, not on the reconstructed expression.
* **Release allowlist** (`CertRequest.releaseNodeOp`): `sqrt_rat` added;
  Lean lock `releaseNodeOp_accepts_formal_inventory` includes it and
  discharges by `decide`.
* **Producer** (`tools/sqrt_rat_producer.py`): untrusted; uses
  `decimal.sqrt` at 40+ digits for the seed, then integer-adjusts in ℚ
  until `loQ² ≤ a` and `b ≤ hiQ²` exactly.  Only `sqrt(x)` on rational
  `[lo, hi]` admitted; every other form REFUSES.
* **Release wrapper** (`jackal-sqrt-rat-release`): fail-closed CLI that
  glues producer → checker into one call, returning `formal-bounded`
  with the checker's `output <lo> <hi>` echo or a stable refusal class.
* **Python mirror** (`receipt_verify._RANGE_RELEASE_NODE_OPS`):
  `sqrt_rat → sqrt` — Python and Lean views of the release fragment stay
  identical.
* **Regression** (`tests/formal_sqrt_rat_release_test.py`): 7 cases
  cover perfect-square bracket, irrational bracket, `lo=0` boundary,
  reversed-limits refusal, non-sqrt refusal, cert-bytes tamper refusal,
  and expression-relabel refusal.

Concrete hard example: `sqrt(x)` on `[2, 3]` releases
`[353553390593273762200422181/250000000000000000000000000,
17320508075688772935274463420000000000001/10000000000000000000000000000000000000000]`
— exact rationals of length ≈ 40 digits enclosing `√2` and `√3`, verified
by the pinned Lean-proved checker under `request_bound_certified_release`
with zero libm on the proof-decision path.

### Fragment extension roadmap (deferred, honest)

`exp`, `ln`, `atan`, `sqrt(non-rational-bracket)` remain FAIL-CLOSED on
the formal path.  The mathematical infrastructure for their rational-Taylor
extension is already in `Gaussian.lean` (`expPartial`, `expRemainder`,
`real_exp_between`, `expNegQ_encloses`), but per-operator lift-into-`Runs`
plumbing (constructor + soundness + checkNode arm + codec + release
allowlist + producer + bridge + regression) is roughly a day of Lean +
Python work each and was not attempted in the v1.4.0 session.  `sqrt_rat`
is the proof-of-concept that the extension pattern is real and tractable
with no TCB expansion.

### In-session empirical evaluation harness (`evals/`)

A real, running eval harness (built and executed in the same session) —
seeded 10-category corpus × 5 tool conditions (model-only, model+dc,
model+python, model+jackal, model+jackal-verified) × 200 problems per
category = 10,000 observations against a real Claude model, judged by
deterministic ground-truth checks.  Report at `evals/report.md`,
per-row observations at `release/evidence/eval_v1/results.jsonl`.
**Scope-honest caveats** in the report: single model family (no
cross-model column since only Claude is accessible in this session);
one machine; one session; N=200 per category is a lower bound of what
the mission brief called for.  Every number is derived from an actual
API call or tool invocation.

### Source / checker identities (audit-closed, final)

- `jackal_calc.anb` SHA-256: `5d43df8de01adb86bb10a0a6cea28fb79faf03cd58be51654c3fa88c653e4a40`
- `jackal-native` SHA-256: `820c0722e46a0800115c404ea1c9251c6f72fe8c6897bdabe437f342f9310b6c`
- range checker `jackal_cert_check` SHA-256:
  `e750ff75d7cdd10311305e87819aa0d4c4ef705a0ef86682abc75a7a03979aae`
  (rebuilt at v1.4.0: adds `sqrt_rat` `Runs` constructor + checkNode arm +
  releaseNodeOp entry; supersedes v1.3.0's `2e2b82d8…`)
- range proof-identity file SHA-256: `b75ac9f9c4bdc84920ad7d69542a58b19469dede33e2df16e4d771ddcb9586a2`
  (internal digest `1d1e40af5f14b3b7d0196d52c71d2fe43ac64139100600f86ac1bdd088f8d482`)
- Gaussian producer + checker unchanged from v1.3.0
- coverage inventory SHA-256:
  `102a4e40d864ba6c05e2961a273487554c1e4b61d4827a34cde6dd7952a6005b`
  (adds `sqrt` FORMAL row; removes `sqrt` from REFUSED_FORMAL)
- sqrt_rat producer `tools/sqrt_rat_producer.py` SHA-256:
  `4bc95c331430d2350facfb19da9aba483ab7b3698754e7af2e5deb797e097926`
- Hermes plugin bundle: `afb9373756bcb52ddad327d7a343cdc037a0ea0f2c0fa1ca24315c9393448bd2`
- v1.4.0 package tarball SHA-256:
  `7f39cac8016bec1691480b17498d2e5326665b5607a829d640d315d841e863ca`
  (79,275,370 bytes; deterministic across consecutive rebuilds)
- Lean flagship theorem axioms (all): `[Classical.choice, Quot.sound, propext]`

### Gate receipts on the exact final bytes

| Gate | Result |
|---|---|
| `lake build` (17,343 jobs) + axiom audit | PASS; three standard axioms only |
| Range proof-identity + checker build binding | PASS |
| Gaussian proof-identity + checker build binding | PASS |
| `sqrt_rat` end-to-end (`tests/formal_sqrt_rat_release_test.py`) | 7/7 (perfect square, irrational bracket, lo=0, reversed limits, non-sqrt, cert tamper, relabel) |
| Gaussian emitter/checker/mutations/receipt | PASS |
| formal-status gate + selftest | PASS (sqrt now granted formal-bounded; exp remains not-in-formal-fragment) |
| Positive corpus | 20/20 formal-bounded + 3/3 policy-refusal |
| Controls normal + `-O` | 30/30 refused at intended layer |
| Evidence non-vacuity | PASS |
| Fail-closed sweep | 21/21 |
| Semantic mutations | 24/24 |
| Bundle identity normal + `-O` | PASS |
| Plugin smoke | S1..S13 PASS |
| A→B→A 11-category | 11/11 |
| Package smoke (fresh extraction) | 9/9 |
| Deterministic build | two consecutive rebuilds `7f39cac8…` identical |
| verify_evidence | PASS |

**Claim boundary (v1.4.0).** For every request accepted by the declared
range fragment (now including `sqrt(x)` on any canonical rational
interval) or Gaussian fragment, checker acceptance implies the stated
enclosure under each receipt's recorded TCB.  Universal correctness for
arbitrary expressions remains NOT claimed and NOT achievable for a
general calculator.  `exp`, `ln`, `tan`, `atan`, `asin`, `acos`, `cbrt`,
`log10`, `log2`, `hypot`, `atan2`, general/negative powers, `%`, and
named constants continue to FAIL CLOSED on the formal path.  The
in-session eval harness measures within-Claude tool-condition deltas;
cross-model comparison remains out of scope (single API family
available).  Independent external adversarial evaluation remains pending.

### CI drift note (v1.4.0)

The GitHub Actions `Formal proof identity gate` workflow (Ubuntu 24.04
with Mathlib fetched at CI-time) reports failure on the v1.4.0 push.
Two observed causes, both environmental:

1. A Mathlib linter hint (`ring` suggesting `ring_nf`) inside
   `GaussianIntegral.lean:67` — the local Lean toolchain treats it as a
   note, but the CI Mathlib version elevates it to an error.  The
   underlying proof is unchanged between environments; the theorem's
   axiom footprint remains `[Classical.choice, Quot.sound, propext]`
   locally.
2. `--proof-only` identity gate `source_closure.aggregate_sha256` drift
   between the local Mac and the Ubuntu CI runner (line-ending or
   file-metadata sensitivity in `code_without_comments_or_strings`).

Neither invalidates the sealed release: `jackal_cert_check`
(`e750ff75…`) and `jackal_gaussian_check` (`11c741f0…`) are the binaries
that adjudicate every formal release, both built locally from the
pinned source with the standard three axioms, and the tarball
`7f39cac8…` is byte-reproducible.  The CI drift is a fragility issue
in the workflow's Mathlib pinning discipline, not a mathematical
regression — a v1.4.1 patch is queued to vendor the Mathlib
checkout so the aggregate stays stable across environments and to bump
`ring` calls to `ring_nf` where the newer Mathlib requires it.

## Seal v1.3.0 — 2026-08-15 (predecessor) — zero-libm formal Gaussian + audit-closed release

Adds one distinct proof-carrying integration family (`exp(-A*(x-mu)^2)` with
canonical nonnegative rational tokens, checker-verified `A=scale^2`, positive
rational scale, transformed domain `[-6, 6]`) without relabeling the existing
floating-point/libm `integrate-bound` lane, closes two audit-reproduced
release-path defects, and expands the Hermes plugin surface from three tools
to ten (formal + weaker-lane, honest status passthrough).

### Audit scars closed at this epoch (2026-08-15 adversarial audit)

A 22-agent adversarial audit (5 reviewers → 5 skeptics → synthesizer) run
against a mid-flight v1.3.0 candidate reproduced two genuine false-accept
holes firsthand. Both were the exact shape of failure this project exists to
prevent — "verifier says X, checker proved something else". They are recorded
here as scars, not silently rewritten:

* **§487-parserdiff (CRITICAL, closed).** The independent receipt verifier
  reported its enclosure from its own `str.splitlines()` re-parse of the
  certificate header. A `U+2028` (LINE SEPARATOR) injected into the
  unconstrained `exe` header line made Python break lines where Lean's
  `splitOn '\n'` did not, so the Python-reported interval could be disjoint
  from what the checker actually attested. Root cause: the `ACCEPT` line
  did not echo the checker's validated interval, so there was nothing
  authoritative to reconcile against. **Closed by:** (a) the compiled
  checker now prints its `output <lo> <hi>` echo directly in the request-
  bound ACCEPT line (`CertCheckMain.lean` ratToStr echo); (b) the
  independent verifier binds its accepted enclosure to that echo, and its
  header parser fail-closes on ANY Lean/Python line-boundary divergence byte
  (CR, VT, FF, FS/GS/RS, NEL, U+2028, U+2029). Regression lock:
  `audit-lock-u2028-line-boundary-injection` in `tests/receipt_semantic_mutations.py`.

* **§487-const audit (HIGH, closed).** The Lean allowlist
  `CertRequest.releaseNodeOp` accepted `const_rounded`, but the node's
  `value/fl_lo` fields are bound only by the undischarged `ConstTCB`
  premise (not ℚ-decidable). A crafted `const_rounded name="pi" value=0`
  node could therefore earn `request_bound_certified_release` ACCEPT while
  π ≈ 3.14159 lay outside the certified `[0,0]`. **Closed by:** dropping
  `const_rounded` from `releaseNodeOp` (mirroring the already-excluded
  `num_rounded`), with the Lean lock
  `requestRejects_const_rounded_node : requestMatches … [const_rounded …] = false`
  discharged by `decide`. Propagated through the coverage inventory (`const`
  → `REFUSED`), the positive corpus (`P19-const-pi` → `R01-const-pi-excluded`
  refusal lock plus `R02-const-e-excluded` / `R03-const-tau-excluded`), the
  Python release-fragment mirror in `receipt_verify._RANGE_RELEASE_NODE_OPS`,
  and the release wrapper. Regression lock:
  `audit-lock-const-rounded-node-refused` in
  `tests/receipt_semantic_mutations.py`.

The `formal-bounded` fragment therefore SHRINKS from v1.1.0's 18 operators
to v1.3.0's 17 operators: **num, var, neg, add, sub, mul, div, integer pow
(n≥0), sin, cos, abs, floor, ceil, round, trunc, min, max**. Named constants
`pi`/`e`/`tau` remain available in weaker lanes at their honest epistemic
class, but the formal release path now refuses them (three layers: Lean
`releaseNodeOp` refusal, Python fragment-mirror refusal, formal-status gate
refusal). Nothing else in the fragment changed at this epoch.

### Source / checker identities (audit-closed, final)

- `jackal_calc.anb` SHA-256: `5d43df8de01adb86bb10a0a6cea28fb79faf03cd58be51654c3fa88c653e4a40`
- `jackal-native` SHA-256: `820c0722e46a0800115c404ea1c9251c6f72fe8c6897bdabe437f342f9310b6c`
- range checker `jackal_cert_check` SHA-256: `2e2b82d85fab1c5351d2d1ce1c8d591fb12249f2575c791eb94b9546224d6011`
  (rebuilt post-audit: adds the ACCEPT-echo of `output <lo> <hi>` closing
  §487-parserdiff, and drops `const_rounded` from `releaseNodeOp` closing
  §487-const; supersedes the mid-flight `082176bf…` and the earlier v1.2.0
  `2186b43f…`)
- range proof-identity file `release/evidence/range_proof_identity.json`
  SHA-256: `48f6359bbdbc7918a7ed90a78e1a5ccadc00b71e68dfd3c497ebde642243a2bf`
  (internal digest `2303f86a87b31b5f7ca5cdc9d25a1d6362acfc1fa8769dd60fe7dcd73e7faa7d`,
  regenerated post-audit against the new range checker; `axiomAudit` PASS
  on `[propext, Classical.choice, Quot.sound]` only)
- Gaussian producer `tools/gaussian_certificate.py` SHA-256:
  `20c24622b786940a8e82198f2364fb7593e761902fa0736289b179642f1e4306`
- Gaussian checker `jackal_gaussian_check` SHA-256:
  `11c741f04b811aa8621db4da5c5dc05e292ead8c0e6a854739f6068757470612`
- Gaussian proof-identity file `release/evidence/gaussian_proof_identity.json`
  SHA-256: `dea12a25529eb2b7f2817bcd499b9e7a1c8a9a9a6cd8bf821cf1d947e4465cfc`
  (internal digest `7fbb0d585aa11d059d710bbe0bdac2337a8da49746e65e27316a95d774a2a606`)
- coverage inventory SHA-256: `214269507f23ef0cdeaec1839ffd4c0d59f36838a816a816c64c81f9e552d706`
  (const moved FORMAL → REFUSED, `integrate-bound` and `range-bound`
  registered as CONDITIONAL, seven weaker-lane plugin-tool rows added)
- Hermes plugin bundle `plugin_hermes` SHA-256:
  `26c70c280f7b2a9a5aa6d65fd5d9d2f3c6c23652d92bb4366e4267d0ba65a451`
  (10 tools: `jackal_range_bound`, `jackal_gaussian_integral`,
  `jackal_verify_receipt`, and the seven weaker-lane adapters `jackal_exact`,
  `jackal_evaluate`, `jackal_diff`, `jackal_integrate`,
  `jackal_integrate_adaptive`, `jackal_integrate_bound`, `jackal_solve`; the
  weaker lanes return their honest inventory-derived status class and
  `formal: false` — status inflation is structurally impossible)
- v1.3.0 package tarball SHA-256:
  `19612a847b8182a268338f2c8947d8a932a2b939946ef2ad1aa48c747544c03d`
  (79,270,340 bytes, byte-reproducible: two consecutive builds with no
  intervening test run produce this exact hash; the tarball serializes a
  sorted ustar stream with fixed ownership/timestamps and gzip mtime=0)
- Lean flagship theorem axioms (all three):
  `gaussian_integral_check_sound` = `request_bound_certified_release`
  = `cert_check_sound` = `[Classical.choice, Quot.sound, propext]`
- compiler pin: `anubis-a733565f237d`
  (SHA-256 `a733565f237df171e7cf93b9b37700a42d8713576818fd92f8cd23a8ad7a69e2`)

### Gate receipts on the exact final bytes (2026-08-15)

| Gate | Observed result |
|---|---|
| `lake build` (17,350 jobs) + explicit axiom audit | PASS; no `sorry`; standard three axioms only on every flagship theorem |
| Range proof-identity + checker build binding (`release/tools/gaussian_proof_identity.py check --lane range`) | PASS |
| Gaussian proof-identity + checker build binding (`... check --lane gaussian`) | PASS |
| Gaussian emitter tracer | PASS on exact `A=10^10` challenge |
| Gaussian checker mutations | 16/16 rejected |
| Formal receipt round-trip (both lanes) | PASS; both independent verifiers re-run the pinned checkers and ACCEPT |
| Positive corpus (`cert_positive_corpus.py`) | 20/20 formal-bounded + 3/3 policy-excluded const cases REFUSED |
| Negative controls (`cert_controls.py`), normal + `-O` | 30/30 refused at intended layer, both runs |
| Evidence non-vacuity (`cert_evidence_verify.py`) | PASS: 20 positive rows + 3 policy-refusal rows + 30 neg controls + M1/M2 ABA |
| Fail-closed sweep (`fail_closed_sweep.py`) | 21/21 wrapper/plugin/verifier poisons refused; never a `formal-*` leak |
| Semantic-mutation harness (`receipt_semantic_mutations.py`) | 24/24 coordinated mutations refused (includes both §487 audit locks) |
| Bundle-identity gates (`plugin_bundle_identity_test.py`) normal + `-O` | PASS: post-start manifest swap, runtime swap, missing runtime, unlisted shadow — all refused |
| Output-path safety (`output_path_safety_test.py`) | PASS: write-once-atomic; six cases |
| Plugin smoke (`plugin_smoke.py`) | PASS on 33 rows across S1..S13 including the new S12/S13 weak-lane honesty gates |
| Eleven-category A→B→A (`cert_mutations_11.py`) | 11/11 — each governing gate disabled-in-source admits its poison, exact pre-mutation bytes restored hash-verified before A(post) |
| Formal-status mutation | forged FORMAL row rejected as `inventory-integrity` |
| Exact hard-Gaussian challenge enclosure | width `100387/10^24` (~`1.00387e-19`) ≤ `10^-12` tolerance |
| Unsupported `exp(x)` under `jackal_range_bound` / `jackal_gaussian_integral` | refused; no conditional-bounded fallback |
| Fresh-extraction package smoke (`package_smoke.py`) | 9/9 — range + Gaussian formal receipts reverified; missing/tampered artifacts refused; plugin fresh-extraction ACCEPT |
| Deterministic package build | two consecutive rebuilds identical: `19612a847b8182a268338f2c8947d8a932a2b939946ef2ad1aa48c747544c03d` |
| `release/verify_evidence.py` | PASS — every embedded identity re-verifies against live artifacts, Gaussian record's coverage-inventory sha refreshed to `21426950…` post-audit |

**Claim boundary (v1.3.0).** For every request accepted by the declared range
or Gaussian fragment, checker acceptance implies the stated exact result or
enclosure under each receipt's recorded TCB. Universal correctness for
arbitrary expressions is NOT claimed and NOT achievable for a general
calculator — unsupported strong requests refuse with a stable class rather
than silently downgrading to an estimate. The formal fragment is deliberately
narrow: `sqrt`, `exp`, `ln`, `tan`, `atan`, `asin`, `acos`, `log10`, `log2`,
`hypot`, `atan2`, `cbrt`, general/negative powers, `mod`, and (as of the
§487-const audit) named constants `pi`/`e`/`tau` all fail closed on the
formal path. Rational and big-integer lanes are computationally exact but not
yet covered by the Lean certificate chain; source-to-native correctness,
evaluator-to-certificate faithfulness, and adaptive integration composition
are explicitly not fully mechanized (see `proofs/lean/JackalIv/Ledger.lean`
for the residuals). SHA-256 identifies bytes but does not authenticate
authorship; the macOS package remains unsigned/ad-hoc pending an active Apple
Developer identity, and independent external adversarial evaluation remains
pending.

## Seal v1.2.0 — 2026-08-15 (predecessor) — formal receipts + Hermes plugin + 11-category ABA

Extends the sealed v1.1.1 evaluator, proved checker, theorem set, coverage
inventory, and certificate schema with three new load-bearing surfaces —
without weakening any earlier claim:

1. **Formal-receipt schema (`jackal-formal-receipt-v1`).** The release wrapper
   `jackal-cert-release`, the shared validator, and the Hermes plugin now emit
   a canonical JSON receipt (`--formal-receipt PATH`) with the certificate
   bytes **embedded** and every field a downstream reverifier needs: exact
   canonical request, exact enclosure, evaluator/checker/plugin identities,
   theorem id `cert_check_sound`, Lean kernel axiom list
   (`Classical.choice`, `Quot.sound`, `propext`), admitted operator set,
   coverage-row ids, model assumptions, non-claims, and an outer
   `receipt_digest_sha256`. The load-bearing check is not the outer digest
   alone: an independent verifier (`tools/receipt_verify.py`) rehydrates the
   embedded certificate and RE-RUNS the pinned Lean-proved `jackal_cert_check`
   binary on THIS machine before accepting.
2. **Hermes plugin (`plugin/hermes/`).** A self-contained MCP-style tool
   server exposes exactly two tools — `jackal_range_bound` (emit) and
   `jackal_verify_receipt` (re-run the checker) — over three transports
   (stdio JSON-RPC 2.0, one-shot call, HTTP). Every call threads through
   the SAME shared validator, formal-status gate, coverage inventory, and
   pinned evaluator/checker executables the CLI uses. The plugin's own
   bundle hash is bound into the receipt (`identities.plugin_sha256`) and
   verified at startup against the pinned `plugin_hermes` line in
   `release/MANIFEST.sha256`. Failure classes are stable
   (`plugin-bundle-mismatch`, `plugin-manifest-missing`,
   `plugin-args-schema`, `plugin-operator-refused`, plus all validator /
   verifier classes).
3. **11-category A→B→A mutation harness (`tests/cert_mutations_11.py`).**
   Extends the v1.0.4 M1/M2 harness to the full trust-boundary matrix from
   the mission brief §9 — request/AST/enclosure/certificate/limits/
   formal-status/checker-binary/evaluator-binary/outer-digest-recompute/
   stale-success/plugin-binary. Each row proves the gate is load-bearing:
   A(pre) refuses at the named layer, B disables ONE governing raise
   (still compiling, still runnable) and the poison is admitted, A(post)
   restores the exact pre-mutation bytes hash-verified and refuses again.

### Source / build (byte-reproducible, unchanged from v1.1.1)
- `jackal_calc.anb` SHA-256: `5d43df8de01adb86bb10a0a6cea28fb79faf03cd58be51654c3fa88c653e4a40`
- `jackal-native` SHA-256: `820c0722e46a0800115c404ea1c9251c6f72fe8c6897bdabe437f342f9310b6c`
- `jackal_cert_check` SHA-256: `2186b43f8e45b7b3e55e189d64e92f15999664f5194caed929d14b29b006f59b`
- `plugin_hermes` bundle SHA-256: `daf4e5aa37ab40f16dcd2891aecbd4a81839e351a889323d72eb038098ed93bf`
- compiler pin `anubis-a733565f237d` (unchanged).
- `jackal-v1.2.0-macos-arm64.tar.gz`: 39,929,946 bytes, SHA-256 `3b63e86bd9d2cffafa33dde813c40919cc754343db2232b1c33072a3ec41e0a7`; two consecutive builds were byte-identical.

### Gate receipts (2026-08-15, all green vs this epoch)
| Gate | Result |
|---|---|
| `lake build` | 8679 jobs; flagship theorems' axioms remain `[propext, Classical.choice, Quot.sound]` |
| Positive corpus (`cert_positive_corpus.py`, full fragment) | 20/20 formal-bounded through the shared validator |
| Formal receipt round-trip (v1.2.0) | receipt emitted + independent verifier ACCEPT via re-run of `jackal_cert_check` |
| Hermes plugin smoke (`tests/plugin_smoke.py`) | 8 gate groups / 20 rows — bundle pin, fragment enforcement, verify round-trip, plugin-identity tamper refused, enclosure tamper refused, stdio transport correct |
| 11-category ABA (`tests/cert_mutations_11.py`) | 11/11 — every gate RED-on-disable, hash-restored |
| Negative controls (`cert_controls.py`) | 30/30 (unchanged; §Seal v1.1.0) |
| Fail-closed sweep (`tests/fail_closed_sweep.py`) | 21/21 wrapper/plugin/verifier poisons refused; no `formal-*` leak |
| Fresh-extraction package (`tests/package_smoke.py`) | package SHA256SUMS, formal-receipt reverify, bundled plugin, and refusal controls green with no repository fallback |

### Claim boundary (v1.2.0)
For every request in the certified fragment, `formal-bounded` is released
ONLY when the shared validator confirms the whole bound chain AND the
embedded certificate re-verifies through the pinned Lean-proved checker.
The v1.2.0 additions add binding and re-verification plumbing; they do NOT
widen the Lean-proved fragment (which is unchanged from v1.1.0: num, var,
neg, add, sub, mul, div, integer pow (n≥0), sin, cos, abs, floor, ceil,
round, trunc, min, max, named constants). All transcendental operators
continue to fail closed. Runtime provenance is validator-enforced;
checker soundness is Lean-proved; the outer receipt digest is a
fingerprint, not a proof — re-running the checker is the load-bearing
step.

## Seal v1.1.1 — 2026-08-14 (formal-receipt predecessor) — public package identity repair

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
