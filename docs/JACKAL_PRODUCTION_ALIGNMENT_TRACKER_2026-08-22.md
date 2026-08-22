# JACKAL Production Alignment Tracker — 2026-08-22

This is the restart-safe evidence ledger for the architect-approved production-alignment mission. `OPEN` means unproven, not failed. `BLOCKED_TRUST_SURFACE` is reserved for an item whose completion would change or promote verifier accept conditions without explicit sign-off.

## Authority binding

| Item | Exact identity | State |
|---|---|---|
| Architect goal | 12,611 bytes; 172 lines; SHA-256 `8025fb5570587258ec3cf6c808df71451af5b8815a7a5778f7d1e48e296dad7d` | VERIFIED |
| Screenshot | `/Users/sicarii/.hermes/cache/images/img_799223020982.png`; visually matches GitHub comment `5376459953` | VERIFIED |
| JACKAL candidate | `AnubisQuantumCipher/jackal` PR #12 head `d25bcd9818e0d106f337798f80527ae611cc3acc`, base `73854110cb82d78b2843d5028e1e0d5970b0ad5a` | VERIFIED CURRENT 2026-08-22 |
| Hermes upstream PR | `NousResearch/hermes-agent#88446` head `08eb5173033e15117f51ac5abc9ca3d8bab313fe` | VERIFIED CURRENT 2026-08-22 |

## Repository and worktree inventory before edits

| Surface | Path or remote | Branch / HEAD | Dirty and ownership boundary | Release/public state |
|---|---|---|---|---|
| JACKAL ambient checkout | `/Users/sicarii/Desktop/Projects/jackal-calc` | `feat/mathematical-evidence-kernel-v1.6.0` / `57739317b24250ff62fd9b23f67c760d9066ab94` | User-owned untracked `jackal_calc.anb.zip`, `jackal_calc.md`, `website/`; DO NOT EDIT | stale local branch |
| JACKAL integration candidate | `/Users/sicarii/Worktrees/jackal-unified-completion-20260820` | `mission/jackal-unified-completion-20260820`; initial tool-containing ref `d25bcd9818e0d106f337798f80527ae611cc3acc`; latest pushed checkpoint `f6ffe749040118587471e146b90d93a56a20f8a3` | named-path alignment commits only | PR #12 draft; no final review decision |
| JACKAL public default | `AnubisQuantumCipher/jackal` | `master` / `73854110cb82d78b2843d5028e1e0d5970b0ad5a` | architect-owned public repo | latest release v1.7.2; repository description says 34 tools |
| Installed Hermes plugin | `/Users/sicarii/.hermes/plugins/jackal-verified` | detached `86596e2b0e2679db68eca16bd102378c5bfa27b7`, annotated tag v5.0.0 | clean installed evidence; DO NOT EDIT | 34 tools; pins JACKAL v1.7.0 |
| Hermes plugin public default | `AnubisQuantumCipher/hermes-jackal-verified` | `main` / `e157e4dc98ffc127bb9abca4ae2ea6cdd699db56` | architect-owned public repo | latest v5.0.0 at `86596e2…`; description says 34 tools |
| Hermes core ambient checkout | `/Users/sicarii/.hermes/hermes-agent` | `main` / `e02d1e41fc6104187e20af9eac8b2820566e3508`, ahead 1/behind 1 at census | extensive user-owned tracked and untracked changes; DO NOT EDIT | upstream is `NousResearch/hermes-agent` |
| Codex plugin candidate | `plugins/jackel` inside JACKAL PR #12 | current generated eight-file identity aggregate `321344d89a8de3db17a18ed37eddd4789ca65e58754ebb0aadea415fff218885`; prior PR record `f5102843…` | named-path candidate changes only | version `0.1.0+codex.20260820135554`; pins fresh v1.7.3 candidate package `cafab155…` |
| Installed Codex plugin | `/Users/sicarii/.codex/plugins/cache/anubis-quantum-cipher/jackel/0.1.0+codex.20260820135554` | exact seven-file identity manifest | installed cache evidence; DO NOT EDIT | wrapper requires 41 tools; package SHA-256 `b2c0819b2c631939217583dc420cc67ba9e4acf613b4b49c208f020ba1bd1175` |
| Hermes PR branch | architect fork branch `feat/index-jackal-verified` | `08eb5173033e15117f51ac5abc9ca3d8bab313fe` | edit only in a fresh isolated checkout | PR title/body/index pin v5.0.0/34 tools; no hosted checks |

## Initial mechanical surface evidence

Supported interpreter validation:

```text
/opt/homebrew/bin/python3
python=/opt/homebrew/opt/python@3.14/bin/python3.14 version=3.14.6 machine=arm64
popen_contract=['process_group', 'start_new_session'] present=True
```

Independent counts from current candidate bytes:

```text
/opt/homebrew/bin/python3 -B tools/profile_verify.py --json
core=3 formal=13 full=41 tools_declared=41

jq '[.tools[].name] | {count:length,unique:(unique|length)}' plugin/hermes/tools.json
count=41 unique=41 first=jackal_range_bound last=jackal_anubis_verify_program_receipt
```

Instrument and baseline gates:

| Command | Exit / observation | Scope boundary |
|---|---|---|
| `/opt/homebrew/bin/python3 -B -m unittest tests.profile_contract_test tests.unified_surface_contract_test tests.package_unified_v173_test -v` | exit 0; 43 tests; 5 skipped | skipped rows require a fresh package root and remain OPEN |
| `/opt/homebrew/bin/python3 -B release/tools/repin_v173.py --check` | exit 0; `REPIN_V173_CHECK_PASS rows=47` | verifies current source manifest derivation, not public release identity |
| `/opt/homebrew/bin/python3 -B -m unittest discover -s tests/codex_plugin -v` | exit 0; 215 tests | repo-local Codex plugin suite on supported Python; fresh-package live discovery remains separate |
| `tests.profile_contract_test` mutation controls | 12 positive and 16 refusal cases within the 43-test run | validates count/profile instrument can turn red |

## Alignment implementation evidence

| Command / artifact | Exit / observation | Scope boundary |
|---|---|---|
| `tools/capability_inventory.py --write` then `--check` | exit 0; `CAPABILITY_INVENTORY_PASS tools=41 unique=41`; current artifact SHA-256 `3c58bd162625fdab22803a020592bf1acfeb31dab0d395a5f50b810f249d1c75` | binds candidate implementation ref `d25bcd…`, semantic integration bytes, and additive Lean-audit manifest rows; provisioner and package-receipt delivery pins are independently bound by the drift gate to avoid a package/inventory self-hash cycle |
| `tests.capability_inventory_test` | 14 tests pass, including duplicate/unmapped/status/checker/artifact mutation controls and an acyclic package-delivery graph assertion | catalog/profile/manifest/proof-identity/semantic-integration contract; delivery pin remains a separate drift-gate contract |
| `tools/capability_drift_gate.py` | exit 0; `CAPABILITY_DRIFT_PASS tools=41 unique=41 codex=41 package=v1.7.3` | current marked surfaces only; historical 34-tool prose remains legal |
| `tests.capability_drift_gate_test` | 12 tests pass, including current count, unknown skill tool, status vocabulary, dedicated package receipt/pin, wrapper count, marker, and plugin-identity refusals | semantic anti-drift instrument |
| `tools/capability_drift_gate.py --write-plugin-identity` then `plugins/jackel/scripts/verify_plugin.py` | eight files; aggregate SHA-256 `321344d89a8de3db17a18ed37eddd4789ca65e58754ebb0aadea415fff218885`; verifier exit 0 | includes the candidate installation/operation README and freshly pinned provisioner; tamper evidence, not author authentication |
| combined inventory/drift/profile/unified suite | exit 0; 60 tests | repository surface, mutation controls, acyclic package-delivery graph, and dedicated alignment-receipt binding |
| `/opt/homebrew/bin/python3 -B -m unittest discover -s tests/codex_plugin -v` | exit 0; 216 tests | repo-local plugin; fresh release-pin discovery remains open |
| `lake build jackal_gaussian_check jackal_cert_check jackal_int_cert_check` | exit 0; 17,369 jobs from an absent local build library; three release checkers rebuilt | existing non-fatal style/deprecation linter output remains; no kernel/build failure |
| three full proof-identity checks | exit 0 for Gaussian, range, and int-cert; exact identity/checker digests revalidated | current checker-accepted fragments only; no source-to-native or builder-authentication claim |
| `tools/lean_admission_audit.py --check` | exit 0; `files=42 theorems=27 admissions=0`; artifact SHA-256 `4c680a6817ccfe27da254c5244e5ffc06469ed37a910ea61303abf8125bb3459`; semantic digest `c4d4440b8aa472f3fa2db682e4cff1144683b003e815e41d795a831b9fda57cf` | all tracked Lean sources; exact current release theorem set; 37 `noncomputable` occurrences classified as non-admissions; two dump-only `implemented_by` mirrors explicitly retained |
| `tests.lean_admission_audit_test` | 12 tests pass, including injected `sorry`, `admit`, plain/modifier-prefixed axiom, `unsafe`, `partial`, `extern`, `native_decide`, and unclassified `implemented_by` refusals | comments/strings are excluded from executable-token findings; mutation fixtures never touch live sources |
| `release/tools/repin_v173.py --check` and `release/build_package_v173.sh --dry-run` | exit 0; 49 manifest rows; package plan carries and semantically validates the Lean audit | staged package execution/double-build remains later release work |
| two clean-source `release/build_package_v173.sh --build` invocations from `a281a6c…` | both exit 0; tarball and extracted-tree `diff`/`cmp` exit 0; SHA-256 `cafab1555d3ea7cf207fd5564464fbe35dfa9288cdd650fe226d9f7633254196`; 158362119 bytes; 106 files; extracted bytes 555504965; `SHA256SUMS` SHA-256 `df2d71627cbd02a2dfd45beec4c87efc35753de17b98a8e0d76baf7cf13c9cd6` | candidate bytes only; no public v1.7.3 tag/release assertion |
| `tests.package_unified_v173_test` with fresh package root | exit 0; 11/11 pass with zero skips | package inventory, complete checksums, live 41-tool discovery, isolation/refusal mutations, and exact candidate receipt |
| `tests/claim_package_parity_test.py` | exit 0; `CLAIM_PACKAGE_PARITY_PASS rows=60 failures=0` after two additional byte-identical builds | every self-contained calculator/claim/domain/program route plus receipt and tamper replay |
| fresh offline Codex provision plus `live_acceptance.py --live` in an isolated Codex home | exit 0; 41 discovered; exact=`exact`, formal=`formal-bounded`, unsupported formal=`producer-refused`, claim bundle/formal receipt=`verified`; wrapper `321344d8…`; package `cafab155…`; tree `df2d7162…` | candidate package bytes and temporary installation only; not public-release-pin evidence |
| `tests.jackal_skill_contract_test` | exit 0; 5 tests on this Mac | canonical-name and routing clauses pass for repo Codex router, personal Codex oracle, personal Hermes router, four profile copies, and reseal procedure |
| `hermes skills audit` / named local audits | generic command exit 0 but audited only the one hub-installed skill; named local JACKAL skills report `not a hub-installed skill` | Hermes audit command does not inspect local skills; repository hostile fixtures plus complete manual read/hash census are the applicable evidence |

## Requirement matrix

| ID | Requirement | Evidence required | State |
|---|---|---|---|
| R1 | Canonical machine-readable per-tool inventory | deterministic generator, committed artifact, `--check`, 41 unique ordered rows with schema/status/checker/fragment/refusal/exposure/release fields | VERIFIED: current artifact `3c58bd16…`; 14 tests; both delivery-pin sources remain independently enforced without a self-hash cycle |
| R2 | Kernel/Hermes/Codex name-set equality | independent discovery outputs and exact set diff | PARTIAL: kernel and Codex candidate show 41; public Hermes plugin is 34 |
| R3 | Eliminate current stale counts, versions, pins, theorem/status claims | semantic drift gate plus reviewed current-surface allowlist | PARTIAL: JACKAL/Codex repository current blocks and design repaired; public descriptions, Hermes bytes, and PR #88446 remain open |
| R4 | Production-equivalent Hermes plugin | 41 generated schemas, install/discovery/call/skill tests, refusal parity, exact package pin | OPEN |
| R5 | Production-equivalent Codex plugin | exact installed discovery and call parity from release pin | PARTIAL: 216 repo-local tests, eight-file identity, fresh offline provisioning, isolated install, exact 41-tool discovery, and five acceptance gates pass on candidate bytes; public release/tag pin remains gated |
| R6 | Complete JACKAL skills audit | classified inventory, exact hashes, real-name/schema fixtures, corrected routers | PARTIAL: repo and personal routers/reseal are corrected and tested; public Hermes bundled skill remains Task 6 |
| R7 | Lean build and admission/axiom audit | `lake build`, exact theorem axiom output, `sorry`/admit scan, trusted snapshot report | VERIFIED: 17,369-job clean-room build; 42 tracked files; 27 unique theorems with exactly `propext`, `Classical.choice`, `Quot.sound`; zero logical admissions/repository axioms; artifact `4c680a68…`; 12 tests |
| R8 | Positive and hostile family coverage | all exported families plus wrong epoch/policy/proposition/unit/cert/pin controls | PARTIAL: 60-row fresh-package parity covers every exported family and tamper replay; full repository hostile aggregate remains a final gate |
| R9 | Claim A-to-B-to-A replay | pristine pass, semantic tamper refusal, pristine re-pass with exact identities | OPEN |
| R10 | Reproducible package and release | clean double-build, byte equality, manifest and tag binding, release asset read-back | OPEN |
| R11 | Independent adversarial review | exact base/head/diff digest, findings and dispositions across code/skills/wording/pins/receipts | OPEN |
| R12 | Resolve PR #88446 | branch diff, neutral index metadata, immutable plugin pin, focused+broad tests, verification comment URL, hosted state | OPEN |
| R13 | Public repository descriptions/metadata | read-back of JACKAL and Hermes plugin descriptions after executable reality is released | OPEN |
| R14 | Trust-surface authority | explicit evidence approving `inventory-safe-v1` accept conditions and release promotion, or separate blocked disposition | OPEN AUTHORITY; do not infer from green tests |

## Known drift and review findings

1. `AnubisQuantumCipher/jackal` public description says 34 tools while PR #12 candidate bytes produce 41.
2. `AnubisQuantumCipher/hermes-jackal-verified` public main/release/description, installed plugin, tests, and bundled skill are v5.0.0/v1.7.0/34-tool surfaces.
3. NousResearch PR #88446 pins `86596e2…`, says 34 tools, and contains promotional self-assessment wording.
4. The PR reviewer requires human verification of the pinned Lean/admission/tool-count claims and equally rigorous skills review.
5. The Codex design's live 34-tool/v1.7.0 provisioner claims were corrected to the exact v1.7.3 candidate package; a semantic gate now fails if those marked current surfaces regress. Historical release facts were not rewritten.
6. PR #12 itself says two architect decisions remain required. Green checks and `READY_FOR_SIGNOFF` are not sign-off.

## Skill census to classify

The following local `SKILL.md` files mention JACKAL/JACKEL and require classification before any claim of complete audit:

- `/Users/sicarii/.codex/skills/jackal-assurance-oracle/SKILL.md`
- `/Users/sicarii/.hermes/skills/productivity/gbrain-evidence-memory/SKILL.md`
- `/Users/sicarii/.hermes/skills/research/rigorous-evidence-report/SKILL.md`
- `/Users/sicarii/.hermes/skills/software-development/adversarial-calculator-audit/SKILL.md`
- `/Users/sicarii/.hermes/skills/software-development/independent-oracle-mutation-audit/SKILL.md`
- `/Users/sicarii/.hermes/skills/software-development/jackal-trust-boundary-reseal/SKILL.md`
- `/Users/sicarii/.hermes/skills/software-development/jackal-verified-computation/SKILL.md`
- `/Users/sicarii/.hermes/skills/software-development/receipt-semantic-replay-verification/SKILL.md`
- `plugins/jackel/skills/jackel/SKILL.md` in the JACKAL candidate
- `skills/jackal-verified-computation/SKILL.md` in the Hermes plugin

### Skill census disposition

| Skill | Classification | SHA-256 / action |
|---|---|---|
| personal Codex `jackal-assurance-oracle` | claim/assurance router | `9bbc50f9…` → `69fe32e1…`; added current claim/bundle/receipt/program routing and no-silent-downgrade rule; command reference now `ea589447…` |
| personal Hermes `jackal-verified-computation` | direct/claim router | `e4cf10c1…` → `d8445e05…`; v1.7.3 candidate/41 tools, four domain tools, three program tools, caller pins, residuals, install/discovery guidance |
| four Hermes profile copies of `jackal-verified-computation` | direct/claim routers | byte-equal to reviewed personal router `d8445e05…`; referenced receipt contracts byte-equal at `433980d5…` |
| personal Hermes `jackal-trust-boundary-reseal` plus four profile copies | audit/release procedure | `63014d9e…` → `3c00bcf7…`; all three Lean checkers, inventory/drift, v1.7.3 double-build, program residuals, and authority boundary |
| personal `gbrain-evidence-memory` | incidental integration mention | unchanged `27a921cd…`; no tool/count/version/pin claim |
| personal `rigorous-evidence-report` | audit procedure | unchanged `a755564d…`; status-preservation guidance only |
| personal `adversarial-calculator-audit` | audit procedure | unchanged `bbbcc1a6…`; no current tool/count/version/pin claim |
| personal `independent-oracle-mutation-audit` | audit procedure | unchanged `941d6ae0…`; no current tool/count/version/pin claim |
| personal `receipt-semantic-replay-verification` | audit procedure | unchanged `f5e1c7ad…`; no current tool/count/version/pin claim |
| repo Codex `plugins/jackel/skills/jackel` | direct/claim router | `64907dd4…` → `1fb8f703…`; canonical-name contract passes; eight-file plugin identity including README and provisioner is `321344d8…` |
| public Hermes bundled router | direct/claim router | current public `a5e2fcf1…`; still v1.7.0/34 and remains open for the v6 candidate |

## Checkpoint log

| Checkpoint | Commit / evidence | Status |
|---|---|---|
| C0 current-state binding | `282551a7101f4303797e8bb3068d9eb7435e5406` | NON-FINAL, PUSHED |
| C0b executable plan | `5b50578e27211a1d8f0132634c11ebdee64a907f` | NON-FINAL, PUSHED |
| C1 canonical inventory | `bbe43f9d5072a932d0b144919f263e9515af004e`; 41 unique; 46 tests at commit | NON-FINAL, PUSHED |
| C2 semantic drift and Codex metadata | `41d0d341855b7ca6493ae1afea5fed268c7f3c29`; 58 surface tests + 215 Codex tests; identity `2a025bb5…` | NON-FINAL, PUSHED |
| C3 Lean admission and axiom audit | `af149778a3d7e2c4991f39aef44d51e55cbf3b99`; 42 sources; 27 theorems; zero admissions; 12 audit tests; 49-row manifest | NON-FINAL, PUSHED |
| C4 package carries canonical inventory | `f6ffe749040118587471e146b90d93a56a20f8a3`; package-source and staged semantic binding; 10 package tests with 5 live-build skips | NON-FINAL, PUSHED |
