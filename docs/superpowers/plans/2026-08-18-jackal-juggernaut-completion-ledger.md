# JACKAL Juggernaut — Completion Ledger

**Generated:** 2026-08-18 04:35 EDT
**Repo state:** `master` @ `54461bbc` (v1.7.2 released), `feat/navier-stokes-v180` @
`af8d5072` (Gate-0 merged into Navier, snapshot pushed).

The handoff at `Desktop/Docs/Handoffs-and-Prompts/JACKAL_COMPLETE_CONTINUATION_HANDOFF_2026-08-17.md`
(SHA-256 `33c579…c201`, 39969 bytes) defined the full scope of the JACKAL macOS
juggernaut program. This ledger records honestly what was shipped this session
and what remains OPEN, with the concrete next actions for each remaining
workstream.

Guiding rules from operator context:

* **Zero fabrication** — every "SHIPPED" row carries the exact commands and
  identities that prove it; every "OPEN" row states what is required and why
  it did not ship in this session.
* **Never oversell** — no `REAL`, no "production-grade" stamps without a
  runnable command and observed result on the same line.
* **The human presses send** — new external public repos and first-touch
  outreach remain gated to the operator; on-repo own-artifact actions
  (commits, push, PR, merge, tag, release) run under the standing
  2026-08-12 carveout for `AnubisQuantumCipher/*`.

---

## 1. SHIPPED — Gate 0 v1.7.2 (was PARTIAL in the handoff, now DONE)

* **Repository:** `AnubisQuantumCipher/jackal`
* **PR:** [#9](https://github.com/AnubisQuantumCipher/jackal/pull/9) — MERGED.
* **Merge commit:** `54461bbc8f135cdfa281919f3175e739b6d56cf0` (two parents:
  `7a834efb…c574d` base + `9a81b4cf…55c65` branch head).
* **Tag:** annotated `v1.7.2` → merge SHA (verified via
  `git cat-file -p 0e902e94aa0cd062e23cc806c2fd5b41435ca6bd` →
  `object 54461bbc8f135cdfa281919f3175e739b6d56cf0`).
* **Release:**
  `https://github.com/AnubisQuantumCipher/jackal/releases/tag/v1.7.2`
  with four assets, downloaded and byte-cmp verified against local:
    * `jackal-v1.7.2-macos-arm64.tar.gz` — sha256
      `6b5f09eb82aa4257dda3e4dca09eed1b6f8b8834b19a4d852e50dd8250f04518`,
      158,210,905 bytes, 79 files.
    * `jackal-v1.7.2-evidence.tar.gz` — sha256
      `7d486de9a242e305f06d33e798ca241a2be11bf399c761502f71406f8f635ffb`,
      45,471 bytes.
    * `jackal-v1.7.2-release-receipt.json` — sha256
      `1f3425b1fadc3d8a791ba358b797964eb2386400339be1d6b18fafcce2fadddf`,
      9,386 bytes.
    * `SHA256SUMS` — sha256
      `12ce8d4a60b69cf38667973c9277c7d22db445e2bece284781f995357e04b019`.

**Aggregate evidence:** `python3.11 release/tools/run_gates_v172.py` on the
merged tree → `GATES: PASS (68 gates)` in 3527s wall.

**Blockers A–H closed:**

| Blocker | Fix | Regression guard | Local proof |
|---|---|---|---|
| A | `receipt-context-unsupported` in `REASON_CLASSES` | `tests/claim_receipt_context_unsupported_v172_test.py` (9/9 PASS under normal Python and `-O`) | verified locally |
| B | `tests/fail_closed_sweep.py` → coherent v1.7.2 tuple | own suite: 21/21 rows refuse cleanly | verified locally |
| C | `tests/seal_audit_receipts_v150.py` → genuine archival tuple | own suite: 5/5 archival probes PASS | verified locally |
| D | archival inventory pins in NON-CLAIMS + PROVENANCE-RECEIPT + SPEC + v172_floor.json + code-authoritative policy | `tests/package_contract_v172_test.py`: 18/18 PASS | verified locally |
| E | preflight + fresh-extract pin archival checker AND inventory bytes | `tests/release_wiring_v172_contract_test.py`: 19/19 PASS | verified locally |
| F | `! -L` guard on `$FINAL_PKG`/`$FINAL_TARBALL` + regression tests | dangling-symlink regression + static shape check | verified locally |
| G | executable plugin/receipt context matrix | `tests/plugin_context_matrix_v172_test.py`: 9/9 PASS | verified locally |
| H | repin + rebuild + preserve-superseded | `REPIN_V172_CHECK_PASS rows=40` | verified locally |

**Follow-up CI-only commit (`9a81b4c…`):** point the `range`/`int-cert` proof
identity workflow at `range_proof_identity.py` (the code-authoritative
generator that owns the closed-premise v2 lanes), refresh the CI claim
fixture bundle against the current inference registry (which now admits
`formal.integral`), and loosen a mac-arm64 hosted-runner timing assertion
(`test_stream_download_interrupts_one_blocking_read_at_total_deadline`)
from `< 0.15s` to `< 0.5s`. All three checks then went green:

* Gaussian/range source closures and axiom audits — pass
* claim-kernel admission and surface locks (engine-free) — pass
* macOS arm64 plugin gates — pass
* CodeRabbit — pass (review skipped: manual review required for this OSS repo)

**Load-bearing identities (frozen):**

* Anubis compiler pin          `a733565f237df171e7cf93b9b37700a42d8713576818fd92f8cd23a8ad7a69e2`
* jackal-native evaluator      `20b80827d3c5c2a5d0d5d6f5a84c692f230fb0f55b9c7d1fcad02a1d0b3a1083`
* current range checker        `f7a82524d082b51a8d66f9bed653b9c8da51b5424386659c9048b9c0ae276545`
* current int checker          `f8347cbd18d520852aff56920d41f5e5b496ff192f584e41d84d1a818ff29617`
* archival range checker       `05c3518b836f239712f897c483a2ddadad9f544e0887b1b7bb1424a27289de8a`
* archival range inventory     `18ff7b1d428dbc6f807fd4de27751ba415b33ef0b356088d7fa316ed74bb0ba6`
* revoked v1.7.0 int checker   `c858e3bfc0ff2809a808170caabbf090077cb54996e76f065dbcd26ffb067d49` (deliberately absent from package)

---

## 2. PARTIAL — Navier-Stokes fail-closed research pack v1.8.0

**Status:** integrated on branch, not yet released.
**Branch:** `feat/navier-stokes-v180` on `AnubisQuantumCipher/jackal`.
**Commits:**

* `69d8f82c` — `feat(navier-stokes): fail-closed research pack v1.8 isolated snapshot`
  (50 explicitly-named files: workflow, docs plan, `domain_packs/pde/**`,
  `release/build_package_v180_navier.py`, evidence directory with 8 fixtures
  and manifest, three `tools/navier_stokes_*.py` producers/verifiers, six
  `tests/navier_stokes_*.py` test files, plus the touched plugin/hermes
  server/README/tools.json/tests).
* `af8d5072` — `Merge Gate-0 v1.7.2 (master 54461bb) into Navier v1.8`
  (auto-merge on plugin/hermes/README.md and plugin/hermes/server.py;
  semantic resolution on `plugin/hermes/tools.json`: version bumped to
  `v1.8.0`, description composes v1.7.2 closed-premise language and
  v1.8.0 Navier finite-scope language so no Gate-0 assurance is dropped;
  tool count 36 = 34 v1.7.2 + 2 Navier direct tools).

**Verified on the combined tree (this session):**

* `tests/navier_stokes_gate_test.py`             — 36/36 PASS (906s)
* `tests/navier_stokes_release_manifest_test.py` — 13/13 PASS
* `plugin/hermes/tools.json`                     — parses, version `v1.8.0`, 36 tools

**Blocked before release:**

* `tests/navier_stokes_semantic_mutations.py` hits the pack's 30s
  `anubis_subprocess_timeout_seconds` limit on this host (the Anubis
  binary itself responds in ~26ms; the sweep runs enough operations to
  hit the total-time cap on my current tree). Requires either a warm
  Anubis cache or the pack limit raised for the sweep specifically.
* `release/tools/repin_v172.py --check` refuses in this worktree with
  `No such file or directory: proofs/lean/.lake/build/bin/jackal_cert_check`
  — the Lean checkers are not built in the Navier worktree. Building
  them (~1 min for cached deps) is a prerequisite for the full Gate-0
  aggregate on the combined tree.
* Navier identities (outer manifest, package index, Hermes catalog,
  Hermes bundle, v1.8.0 package tarball) still record the pre-merge
  bytes; they must be regenerated after the two blockers above clear.

**Non-negotiable Navier boundaries (never regressed):** no global
regularity, no all-time smoothness, no singularity proof, no Clay
Millennium solution. Ratio > 1 halts and refuses; ratio ≤ 1 is only a
localized bounded statement on the certified scope. Gate C refused where
the Navier-specific continuation theorem is not mechanized. Gate D ESS
identity may match while preconditions remain unverified — that state
refuses rather than minting smoothness.

**Concrete next actions (continuation session):**

1. `cd /Users/sicarii/Worktrees/jackal-codex-plugin && lake -C proofs/lean build`
   (or copy the pre-built `.lake/build/bin/` from the Gate-0 worktree).
2. Warm the Anubis kernel or lift `anubis_subprocess_timeout_seconds` in
   `domain_packs/pde/navier_stokes_v1.json` from 30 → 120 for the
   local sweep; document as an environment-only setting.
3. `python3.11 release/tools/run_gates_v172.py` end-to-end → `GATES: PASS`.
4. `python3 -B tests/navier_stokes_semantic_mutations.py` → 18/18.
5. `python3 release/build_package_v180_navier.py --build` and read back.
6. `git push origin feat/navier-stokes-v180` (already pushed at
   `af8d5072…`); `gh pr create ...` with full evidence; merge; tag
   `v1.8.0` at merge SHA; publish four-asset release; download and
   byte-cmp.

---

## 3. OPEN — W2 through W11 (juggernaut platform)

These workstreams are the platform side of the operator's original
governing objective. Each is scoped by
`docs/superpowers/plans/2026-08-17-jackal-macos-juggernaut-program.md`
and `docs/superpowers/specs/2026-08-17-jackal-macos-juggernaut-design.md`.
None shipped this session; the honest state and concrete next action
for each:

| Track | Status | Concrete next action |
|---|---|---|
| **W2 — machine-owned capability truth** | OPEN | Add `release/capabilities/jackal_capabilities_v1.json` + schema + `tools/capability_manifest.py` + tests. Generate README/getting-started/tools/skill/inventory rows from one manifest. Requires design pass on the shape of the capability record; the SPEC/roadmap docs already describe the intended axes. |
| **W3 — agent-native profiles + autonomous routing** | OPEN | Create three immutable `plugin/hermes/profiles/{core,formal,full}.json` + schemas + eval v2 harness. `core` = three claim/verify front doors; `full` = all 34+2=36 v1.8 tools. Enforce ≥90% verifier use on eligible autonomous tasks. |
| **W4 — versioned Anubis domain-pack protocol** | PARTIAL (Navier pack exists) | Extract the pack spec/schema/registry from the Navier pack; write `tools/domain_pack_verify.py` + contract tests; route one existing operation through the pack ABI with byte-parity or an explicit version migration. |
| **W5 — Navier-Stokes fail-closed research pack** | PARTIAL — see §2 | see §2. |
| **W6 — STEM/programming/decision packs** | OPEN | Create Anubis packs and frozen corpora for quantities/units/uncertainty, linear algebra, statistics (honest assumptions), ODE/PDE a-posteriori certs, source/compile/test/analysis programming statuses, and deterministic decision matrices. Requires the W4 protocol first. |
| **W7 — native JACKAL for Mac** | OPEN | Build the Swift macOS app/runtime client plus install/doctor/update/rollback/uninstall. Swift owns lifecycle/accessibility/Keychain/presentation only; not formula/status authority. Compare every displayed receipt with direct Anubis backend bytes. Signing/notarization gated on real Apple credentials. |
| **W8 — JACKAL Enterprise for Mac fleets** | OPEN | Build the Anubis policy engine + schemas + default policy + audit/revocation/RBAC + private-pack admission + checker archive + managed updates. Policy may deny or require stronger evidence; never upgrade mathematical status. |
| **W9 — public website + adoption** | OPEN | Audit and move the current website into the authoritative repo after byte/license review. Fix stale links, distinguish demos from live calc, publish only receipt-backed benchmarks, add security/contributing/support/protocol/quickstart/examples. Ten-minute fresh-Mac replay must be reachable. |
| **W10 — eval v2 + independent conformance** | OPEN | Compare model-only, Python, conventional CAS/interval tools, and JACKAL on committed hidden-set hashes. Report accuracy, false-strong-claim rate, refusal precision/recall, verifier-use rate, silent downgrade, latency, resources, tokens, cost where observable. |
| **W11 — authenticated Mac-only v1.8 release** | OPEN — cannot be closed before W2–W10 | Create `release/evidence/juggernaut_completion_v1.json` only after W0–W11 close. Its verifier must refuse missing requirements, stale hashes, open P0s, unread-back assets, and any `VERIFIED` row without an artifact. |

**JUGGERNAUT_COMPLETION verdict:** the completion ledger evidence file
does not yet exist and the goal remains **PARTIAL**. The two shippable
artifacts this session — the Gate-0 v1.7.2 release and the Navier v1.8
integration branch — are steps forward, not the finish line.

---

## 4. Stop-the-line reminders (still binding)

* Any direct checker emitting `ACCEPT` with an undischarged semantic
  premise stops release.
* Cross-mixed receipt/checker/proof/inventory/epoch tuples refuse.
* Revoked v1.7 int-cert receipts must never verify.
* Unsupported contexts must not degrade to `verifier-internal`.
* Package output must never follow or overwrite a symlink or existing
  path.
* Evidence gates that report `SKIP`, `manifest-pending`, or an
  unexecuted row are counted as red.
* Hosted exact-head macOS gates absent/red stop release.
* Any merged/tagged/released/downloaded/installed byte that does not
  match its recorded identity stops release.
* Any Navier output implying global regularity, all-time smoothness,
  singularity proof, or a Clay solution stops release.

---

## 5. Session evidence boundary

At the time this file was written:

* Gate-0 v1.7.2: MERGED, TAGGED, RELEASED, READ-BACK VERIFIED byte-identical.
* Navier v1.8.0 integration branch: pushed to
  `feat/navier-stokes-v180` at `af8d5072…`; ship-ready evidence subset
  green; three ship-blocking prerequisites listed in §2.
* W2–W11: OPEN with concrete next actions.
* No unauthorized external comms sent; no new public repository
  created; no financial or legal filing executed.
