# Proposed trust-surface promotion — NOT APPLIED

**Status: research-shadow. This document is a proposal only.  Nothing below
is implemented on any public surface.  Applying any part requires architect
sign-off (mission §13); the mission ends at READY_FOR_TRUST_SIGNOFF.**

## 1. Exact current behavior

- `integrate-bound` prints `status=bounded … assurance=certified-bound(…;
  implementation-tested-not-mechanized)` (jackal_calc.anb:4759) and its
  coverage row is `verdict: CONDITIONAL`, `soundness_theorem: n/a`
  (release/coverage/formal_coverage_inventory.json:940-957).
- `release/claim/SPEC.md` and `release/claim/inference_registry_v1.json` cap
  every composed interval graph at mathematical class `bounded`; the
  registry's `interval_*` rules never emit `formal-bounded` for compositions
  (release/evidence/release_review_v160.json:72).
- Six public surfaces state "bound_step release composition … remains OPEN"
  (tools/formal_receipt.py:162; proofs/lean/JackalIv/Ledger.lean:192-194,
  243-245; release/evidence/release_review_v160.json:72;
  release/build_package_v160.sh; release/build_package.sh; README.md).
- The 33-tool public inventory has no integrate-bound certificate tool; the
  only cert-emitting engine command is `range-bound-cert`.

## 2. Exact proposed diff (unapplied)

A later, signed-off v1.7+ wave could promote the shadow lane as follows:

1. **Engine emitter** (`jackal_calc.anb`): add `integrate-bound-cert
   <expr> <lo> <hi> <tol>` — an exact-ℚ twin of `bound_step` that emits the
   `jackal-int-cert` artifact (subdivision tree + per-leaf embedded
   `jackal-eval-cert v2` blocks) for its real computation, mirroring how
   `range-bound-cert` twins `range-bound`.  Fail closed outside the
   certified fragment.
2. **Checker executable** (`proofs/lean/lakefile.toml`): add
   `[[lean_exe]] jackal_int_cert_check` with root
   `JackalIv.ShadowCertMain` (renamed `JackalIv.IntCertMain`), compiled
   directly from the proved `parseIntCert`/`checkIntCert` (no
   `@[implemented_by]`, no `native_decide`).  NOTE: this invalidates the
   sha256-pinned `proofs/lean/lakefile.toml` in
   release/evidence/{range,gaussian}_proof_identity.json — both identities
   must be regenerated and re-pinned in the same signed-off wave.
3. **Release lane**: a `jackal-int-cert-release` wrapper mirroring
   `jackal-cert-release` (request-commitment binding, TOCTOU executable
   identity, no status escalation) via `tests/release_validate.py`
   extensions; new receipt variant + verifier rows; MANIFEST.sha256 rows for
   the emitter/checker/proof identity.
4. **Claim surface**: `release/claim/SPEC.md` §5 gains an inference rule
   `interval_integral_composed_formal` raising an accepted
   `jackal-int-cert` from `bounded` to `formal-bounded` with the theorem id
   `JackalIv.Shadow.int_cert_sound` (renamed), consequence floors unchanged;
   `inference_registry_v1.json` gains the matching machine row.
5. **Coverage inventory**: the integrate-bound row splits into the legacy
   CONDITIONAL row (float engine lane, unchanged) and a new FORMAL row for
   the certificate lane, keyed to the new theorem and checker identity.
6. **Ledger**: roadmap item (4) marked CLOSED for the certified fragment,
   with the same residual discipline as bridge #2 (emitter faithfulness
   tested not proved; codec + Lean runtime in TCB).

## 3. Theorem/checker evidence supporting it

- `JackalIv.Shadow.int_cert_sound` — axioms exactly
  `[propext, Classical.choice, Quot.sound]`; TCB = `TreeTCB`
  (= existing `Cert.ModelTCB` per embedded certificate).
- 31-row focused matrix (6 positive, 7 refusal, 18 semantic poisons) —
  research/v170-bound-step-shadow/evidence/shadow_matrix.json.
- A→B→A load-bearing receipt —
  research/v170-bound-step-shadow/evidence/aba_shadow.json — including the
  supplementary result that the enclosure guards cannot be weakened without
  breaking the compile of the soundness theorem.

## 4. New TCB and residuals after promotion

- Adds: the `jackal_int_cert_check` compiled binary identity (same class as
  `jackal_cert_check`), the `jackal-int-cert` codec, and — until item (5) of
  the roadmap — emitter faithfulness of the new engine command (testing, not
  proof).
- Unchanged: platform libm ≤ 2 ulp model, const rounding facts, Anubis
  compiler/hardware execution, decimal→f64 request parsing.
- The engine's own float `bound_step` lane keeps
  `implementation-tested-not-mechanized`; only the CERTIFICATE lane earns
  the formal class (exactly the `range-bound` / `range-bound-cert` split).

## 5. Compatibility impact

- Additive: new engine command, new executable, new wrapper, new receipt
  variant, new claim rule, new coverage row, new MANIFEST rows.
- Rebinds (requires regeneration + re-pinning, hence architect sign-off):
  lakefile.toml sha in both proof identities; a new 34th public tool would
  break the 33-tool inventory lock unless the plugin surface is versioned in
  the same wave (alternative: keep the tool non-plugin, CLI-only, leaving
  the 33-tool inventory intact).
- No existing PASS, verifier accepted set, receipt, or fixture changes
  meaning.

## 6. Negative controls proving the change is load-bearing

Already exercised in shadow: the 18-poison matrix and the A→B→A gate.  At
promotion time, rerun both against the compiled checker binary plus the
receipt-layer controls (R1-R11 analogue) for the new wrapper.

## 7. Rollback plan

The lane is additive end to end: rollback = remove the new command/exe/
wrapper/rows and re-pin the two proof identities at their previous values
(kept in git history).  No legacy surface depends on the new lane.
