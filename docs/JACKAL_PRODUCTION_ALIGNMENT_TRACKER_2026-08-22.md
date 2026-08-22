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
| JACKAL integration candidate | `/Users/sicarii/Worktrees/jackal-unified-completion-20260820` | `mission/jackal-unified-completion-20260820` / `d25bcd9818e0d106f337798f80527ae611cc3acc`; upstream equal | clean before this tracker | PR #12 draft; hosted checks green on old head; no review decision |
| JACKAL public default | `AnubisQuantumCipher/jackal` | `master` / `73854110cb82d78b2843d5028e1e0d5970b0ad5a` | architect-owned public repo | latest release v1.7.2; repository description says 34 tools |
| Installed Hermes plugin | `/Users/sicarii/.hermes/plugins/jackal-verified` | detached `86596e2b0e2679db68eca16bd102378c5bfa27b7`, annotated tag v5.0.0 | clean installed evidence; DO NOT EDIT | 34 tools; pins JACKAL v1.7.0 |
| Hermes plugin public default | `AnubisQuantumCipher/hermes-jackal-verified` | `main` / `e157e4dc98ffc127bb9abca4ae2ea6cdd699db56` | architect-owned public repo | latest v5.0.0 at `86596e2…`; description says 34 tools |
| Hermes core ambient checkout | `/Users/sicarii/.hermes/hermes-agent` | `main` / `e02d1e41fc6104187e20af9eac8b2820566e3508`, ahead 1/behind 1 at census | extensive user-owned tracked and untracked changes; DO NOT EDIT | upstream is `NousResearch/hermes-agent` |
| Codex plugin candidate | `plugins/jackel` inside JACKAL PR #12 | identity aggregate `f5102843b8112302ebfdc7bfa1dc7665a4194835fad360523c50fda9abe3983d` from PR record | clean with JACKAL worktree | version `0.1.0+codex.20260820135554`; pins v1.7.3 candidate package |
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

## Requirement matrix

| ID | Requirement | Evidence required | State |
|---|---|---|---|
| R1 | Canonical machine-readable per-tool inventory | deterministic generator, committed artifact, `--check`, 41 unique ordered rows with schema/status/checker/fragment/refusal/exposure/release fields | OPEN |
| R2 | Kernel/Hermes/Codex name-set equality | independent discovery outputs and exact set diff | PARTIAL: kernel and Codex candidate show 41; public Hermes plugin is 34 |
| R3 | Eliminate current stale counts, versions, pins, theorem/status claims | semantic drift gate plus reviewed current-surface allowlist | OPEN; known stale public descriptions, Hermes bytes, PR #88446, and Codex design spec line 515 |
| R4 | Production-equivalent Hermes plugin | 41 generated schemas, install/discovery/call/skill tests, refusal parity, exact package pin | OPEN |
| R5 | Production-equivalent Codex plugin | exact installed discovery and call parity from release pin | PARTIAL: 215 repo-local tests pass; fresh release-pin gates open |
| R6 | Complete JACKAL skills audit | classified inventory, exact hashes, real-name/schema fixtures, corrected routers | OPEN |
| R7 | Lean build and admission/axiom audit | `lake build`, exact theorem axiom output, `sorry`/admit scan, trusted snapshot report | OPEN |
| R8 | Positive and hostile family coverage | all exported families plus wrong epoch/policy/proposition/unit/cert/pin controls | OPEN |
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
5. `docs/superpowers/specs/2026-08-17-jackel-codex-plugin-design.md` still says the runtime has 34 tools even though the current Codex plugin wrapper enforces 41.
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

## Checkpoint log

| Checkpoint | Commit / evidence | Status |
|---|---|---|
| C0 current-state binding | this tracker, derived from live local/GitHub inspection on 2026-08-22 | NON-FINAL |
