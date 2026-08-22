# JACKAL Production Alignment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce one mechanically consistent 41-tool JACKAL candidate across kernel, Hermes, Codex, skills, releases, public metadata, and NousResearch PR #88446 without changing verifier accept conditions or overstating an unapproved release.

**Architecture:** `plugin/hermes/tools.json` remains the executable roster. A deterministic capability-inventory generator binds each catalog record to profiles, schemas, proof/checker dependencies, supported fragments, refusal boundaries, and integration exposure. A semantic drift gate makes that inventory the shared contract for kernel/Codex, the standalone Hermes plugin, and routing skills. Release and PR mutation occur only after clean package replay, independent review, and explicit trust-surface authority are evidenced.

**Tech Stack:** Python 3.14 at `/opt/homebrew/bin/python3`, JSON, unittest, Lean 4/Lake, Anubis pinned compiler, Bash/Zsh release builders, Git/GitHub CLI, Hermes native plugin API, Codex portable plugin/MCP.

---

## Execution rules

- Work only in clean isolated worktrees/clones. Never edit the dirty Desktop JACKAL checkout, dirty Hermes main checkout, installed Hermes v5.0.0 checkout, or installed Codex cache.
- Add behavior tests first and record the expected red output before implementation.
- Never hand-edit `release/MANIFEST.sha256`, `PLUGIN_IDENTITY.sha256`, `MANIFEST.json`, evidence JSON, or package hashes. Use the owning generator and its `--check` mode.
- Stage named files only. Every pushed checkpoint is a new commit; never amend or force-push.
- Treat `inventory-safe-v1` promotion, checker accept conditions, release identity, and tag creation as sign-off surfaces.

### Task 1: Canonical 41-tool capability inventory

**Files:**
- Create: `tests/capability_inventory_test.py`
- Create: `tools/capability_inventory.py`
- Create: `release/capability_inventory_v1.json`
- Modify: `.github/workflows/gaussian-proof-gate.yml`

- [ ] **Step 1: Write the failing inventory contract tests**

Add tests that import `tools/capability_inventory.py` and assert:

```python
document = inventory.build_inventory(ROOT)
records = document["tools"]
catalog = json.loads((ROOT / "plugin/hermes/tools.json").read_text())["tools"]
self.assertEqual([row["name"] for row in records], [row["name"] for row in catalog])
self.assertEqual(len(records), 41)
self.assertEqual(len({row["name"] for row in records}), 41)
self.assertEqual({row["schema_sha256"] for row in records}, {
    hashlib.sha256(inventory.canonical_bytes(row)).hexdigest() for row in catalog
})
for row in records:
    self.assertEqual(row["exposure"], {"kernel": True, "hermes": True, "codex": True})
    self.assertTrue(row["status_classes"])
    self.assertIn("refused", row["status_classes"])
    self.assertTrue(row["supported_fragment"])
    self.assertTrue(row["refusal_boundary"])
    self.assertIn(row["release_state"], {"v1.7.3-candidate", "v1.7.3"})
```

Add mutation tests for duplicate catalog names, an unmapped tool, unknown status vocabulary, missing checker identity, and a committed artifact differing from generated canonical bytes.

- [ ] **Step 2: Run RED and preserve the expected failure**

Run:

```bash
/opt/homebrew/bin/python3 -B -m unittest tests.capability_inventory_test -v
```

Expected: import/file failure because the generator and artifact do not exist.

- [ ] **Step 3: Implement the deterministic generator**

Implement the public API `canonical_bytes(value)`, `build_inventory(root)`,
`render_inventory(root)`, `check_committed(root)`, and `main(argv)`. The status
vocabulary is exactly:

```python
ALLOWED_STATUSES = frozenset({
    "ok", "exact", "structural-exact", "formal-bounded", "bounded",
    "checked", "estimated", "model-based", "verified",
    "verified-program-evidence", "verified-program-receipt",
    "indeterminate", "refused",
})

def canonical_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")
```

Parse each tool's `returns.status` by exact ` | ` tokens. Use complete named sets for the three Lean checker families, exact-cert verifier family, structural checkers, decision checker, claim verifier, and program verifier. Reject any tool that belongs to zero or multiple incompatible dependency families. Derive profile membership from the three profile JSON files and schema identity from canonical catalog-record bytes.

Use `v1.7.3-candidate` as release state until an annotated public v1.7.3 tag is verified. Record the containing candidate commit `d25bcd9818e0d106f337798f80527ae611cc3acc` and input-tree digests; do not introduce a self-referential final commit hash.

- [ ] **Step 4: Generate the artifact with the owning tool**

Run:

```bash
/opt/homebrew/bin/python3 -B tools/capability_inventory.py --write
/opt/homebrew/bin/python3 -B tools/capability_inventory.py --check
```

Expected: `CAPABILITY_INVENTORY_PASS tools=41 unique=41` and byte-identical `--check`.

- [ ] **Step 5: Add the engine-free CI invocation**

Add this before claim-bundle admission replay:

```yaml
- name: Canonical capability inventory
  run: |
    /opt/homebrew/bin/python3 -B tools/capability_inventory.py --check
    /opt/homebrew/bin/python3 -B -m unittest tests.capability_inventory_test -v
```

Use `python3` rather than the Homebrew absolute path in Ubuntu jobs; keep the fixed path only in macOS plugin jobs.

- [ ] **Step 6: Run GREEN and regression gates**

```bash
/opt/homebrew/bin/python3 -B -m unittest \
  tests.capability_inventory_test \
  tests.profile_contract_test \
  tests.unified_surface_contract_test -v
/opt/homebrew/bin/python3 -B tools/capability_inventory.py --check
```

- [ ] **Step 7: Commit and push the non-final inventory checkpoint**

Stage the four named paths and use a receipt body containing the exact test count, inventory digest, and `tools=41 unique=41` output.

### Task 2: Semantic documentation, plugin, and skill drift gate

**Files:**
- Create: `tests/capability_drift_gate_test.py`
- Create: `tools/capability_drift_gate.py`
- Modify: `docs/superpowers/specs/2026-08-17-jackel-codex-plugin-design.md`
- Modify: `README.md`
- Modify: `GETTING-STARTED.md`
- Modify: `PROVENANCE.md`
- Modify: `plugins/jackel/.codex-plugin/plugin.json`
- Modify: `plugins/jackel/skills/jackel/SKILL.md`
- Modify: `.github/workflows/jackal-codex-plugin.yml`

- [ ] **Step 1: Write RED tests against known live drift**

Create fixtures that replace a current count with 34, add an unknown `jackal_*` name to a skill, replace the package SHA, and introduce an unknown status word. Require stable refusal names:

```python
with self.assertRaisesRegex(DriftError, "current-tool-count"):
    drift.verify_surface(fixture_root)
with self.assertRaisesRegex(DriftError, "unknown-skill-tool"):
    drift.verify_surface(fixture_root)
with self.assertRaisesRegex(DriftError, "package-pin-mismatch"):
    drift.verify_surface(fixture_root)
with self.assertRaisesRegex(DriftError, "status-vocabulary"):
    drift.verify_surface(fixture_root)
```

The positive test must initially fail on the stale 34-tool sentence in the 2026-08-17 Codex design spec.

- [ ] **Step 2: Run RED**

```bash
/opt/homebrew/bin/python3 -B -m unittest tests.capability_drift_gate_test -v
```

Expected: `current-tool-count` identifies the exact stale current-surface file and line.

- [ ] **Step 3: Implement the drift verifier**

The verifier must:

```python
CURRENT_SURFACES = (
    "README.md", "GETTING-STARTED.md", "PROVENANCE.md",
    "plugins/jackel/skills/jackel/SKILL.md",
    "docs/superpowers/specs/2026-08-17-jackel-codex-plugin-design.md",
)

def skill_tool_names(markdown: str) -> set[str]:
    return set(re.findall(r"`(jackal_[a-z0-9_]+)`", markdown))
```

Check structured JSON semantically. For Markdown, require current count/version/package identity in named current-surface sections, verify every referenced tool exists, and allow explicitly labeled migration/historical paragraphs. Do not globally ban `34`, v1.7.0, or old tag names.

- [ ] **Step 4: Correct current-surface drift**

Replace the Codex design's current 34-tool statement with the generated 41-tool roster contract. Remove promotional self-assessment wording from current metadata and state the adapter mechanism: it returns the runtime result object unchanged except for the adapter-local `plugin-busy` refusal.

- [ ] **Step 5: Add the gate to both workflows**

Run `capability_inventory.py --check` and `capability_drift_gate.py` in the engine-free proof job and the macOS Codex plugin job.

- [ ] **Step 6: Run GREEN**

```bash
/opt/homebrew/bin/python3 -B tools/capability_drift_gate.py
/opt/homebrew/bin/python3 -B -m unittest \
  tests.capability_drift_gate_test tests.codex_plugin.test_plugin_metadata -v
```

- [ ] **Step 7: Commit and push named files**

The receipt must distinguish corrected live claims from intentionally preserved historical migration facts.

### Task 3: Lean/admission and trust-assumption audit artifact

**Files:**
- Create: `tests/lean_admission_audit_test.py`
- Create: `tools/lean_admission_audit.py`
- Create: `release/evidence/lean_admission_audit_v173.json`
- Modify: `release/tools/repin_v173.py`
- Modify: `release/build_package_v173.sh`
- Modify: `release/MANIFEST.sha256` only through `repin_v173.py --write`

- [ ] **Step 1: Write RED tests**

Require the audit to enumerate every tracked `.lean` file, reject `sorry`, `admit`, `axiom`, and `unsafe` outside an explicit classification, and bind the exact output of theorem axiom queries. Mutation fixtures must insert `sorry` and a new axiom declaration and observe named failures.

- [ ] **Step 2: Run RED**

```bash
/opt/homebrew/bin/python3 -B -m unittest tests.lean_admission_audit_test -v
```

- [ ] **Step 3: Implement read-only audit generation**

The artifact schema must contain source file SHA-256 values, token-scan findings, theorem names, `#print axioms` output, checker build identities, explicit trusted assumptions, and residual non-claims. It must distinguish Lean standard axioms from repository declarations and admitted snapshot inputs.

- [ ] **Step 4: Run Lean build and theorem queries**

```bash
cd proofs/lean
lake build jackal_gaussian_check jackal_cert_check jackal_int_cert_check
cd ../..
python3 release/tools/gaussian_proof_identity.py check --lane gaussian --proof-only
python3 release/tools/range_proof_identity.py check --lane range --proof-only
python3 release/tools/range_proof_identity.py check --lane int-cert --proof-only
/opt/homebrew/bin/python3 -B tools/lean_admission_audit.py --write
/opt/homebrew/bin/python3 -B tools/lean_admission_audit.py --check
```

These are the exact checker build targets and engine-free proof-identity commands
used by `.github/workflows/gaussian-proof-gate.yml`. The full macOS release gate
later reruns the same identity scripts without `--proof-only`.

- [ ] **Step 5: Repin through the generator and re-check**

```bash
/opt/homebrew/bin/python3 -B release/tools/repin_v173.py \
  --compiler-path "<PINNED_ANUBIS_COMPILER>" --write
/opt/homebrew/bin/python3 -B release/tools/repin_v173.py \
  --compiler-path "<PINNED_ANUBIS_COMPILER>" --check
```

Any change to checker identity or accepted theorem set is a trust-surface blocker, not an automatic repin.

- [ ] **Step 6: Run GREEN and commit**

Run the new audit tests plus the existing Gaussian/range source-closure workflow commands. Commit only after exact axiom and `sorry`/admission observations are recorded.

### Task 4: In-repository and personal skill alignment

**Files:**
- Create: `tests/jackal_skill_contract_test.py`
- Modify: `plugins/jackel/skills/jackel/SKILL.md`
- Audit/update: `<CODEX_SKILLS_DIR>/jackal-assurance-oracle/`
- Audit/update: `<HERMES_HOME>/skills/software-development/jackal-verified-computation/`
- Audit/update: `<HERMES_HOME>/skills/software-development/jackal-trust-boundary-reseal/`
- Audit/classify without forced edits: the five other JACKAL-mentioning personal Hermes skills listed in the tracker

- [ ] **Step 1: Read every selected `SKILL.md` and referenced JACKAL file completely**

Record SHA-256, version, classification (`direct-router`, `claim-router`, `audit-procedure`, `incidental`), every referenced tool name, and every current version/count/pin claim in the tracker.

- [ ] **Step 2: Write RED fixtures for real tool names and routing rules**

Require direct/claim routers to reference only inventory names and to contain these semantic clauses:

```python
REQUIRED_ROUTING = {
    "jackal_claim", "jackal_verify_bundle", "jackal_verify_receipt",
    "jackal_anubis_verify_program", "jackal_anubis_verify_program_receipt",
}
REQUIRED_WORDING = {
    "caller-pinned", "refused", "indeterminate", "no silent downgrade",
}
```

Tests must fail on the personal Hermes v1.7.0/34-tool router before it is updated.

- [ ] **Step 3: Update routers and reseal procedure**

Use neutral capability facts from `release/capability_inventory_v1.json`. Preserve host-specific install instructions. Update the reseal procedure to the current repo name, all three checker families, program verifier residuals, package v1.7.3 candidate state, and generated-manifest rules.

- [ ] **Step 4: Run skill tests and Hermes skill audit**

```bash
/opt/homebrew/bin/python3 -B -m unittest tests.jackal_skill_contract_test -v
cd "$HOME/.hermes/hermes-agent"
python -m hermes_cli.main skills audit
```

If the local Hermes command shape differs, use `hermes skills audit` as documented and record the exact installed command/version.

- [ ] **Step 5: Commit repository skill changes and separately receipt personal-file changes**

Never sweep unrelated personal skills into a Git commit. Record before/after hashes and exact paths in the central tracker.

### Task 5: Fresh v1.7.3 package and Codex release-pin replay

**Files:**
- Modify generated package/manifest files only through `release/build_package_v173.sh` and `release/tools/repin_v173.py`
- Update: `docs/JACKAL_PRODUCTION_ALIGNMENT_TRACKER_2026-08-22.md`

- [ ] **Step 1: Freeze source inputs and record pre-build hashes**

Record `git rev-parse HEAD`, worktree status, builder digest, repin digest, checker identities, catalog digest, inventory digest, and current package digest.

- [ ] **Step 2: Build twice in separate clean output roots**

```bash
env -i PATH=/opt/homebrew/bin:/usr/bin:/bin HOME="$HOME" \
  JACKAL_ANUBIS_COMPILER_PATH="<PINNED_ANUBIS_COMPILER>" \
  JACKAL_DIST="<TEMP_ROOT>/jackal-v173-build-a" \
  /bin/zsh release/build_package_v173.sh --build
env -i PATH=/opt/homebrew/bin:/usr/bin:/bin HOME="$HOME" \
  JACKAL_ANUBIS_COMPILER_PATH="<PINNED_ANUBIS_COMPILER>" \
  JACKAL_DIST="<TEMP_ROOT>/jackal-v173-build-b" \
  /bin/zsh release/build_package_v173.sh --build
```

Use the builder's actual supported output argument discovered from its source. If it has no output option, run in two fresh clones rather than editing the builder.

- [ ] **Step 3: Compare complete outputs**

Require identical tarball SHA-256, byte size, extracted file roster, per-file SHA256SUMS, and aggregate inventory. Do not treat matching tarballs alone as sufficient.

- [ ] **Step 4: Run the five previously skipped package tests**

```bash
JACKAL_TEST_PACKAGE_ROOT="<TEMP_ROOT>/jackal-v173-build-a/jackal-v1.7.3-macos-arm64" \
  /opt/homebrew/bin/python3 -B -m unittest tests.package_unified_v173_test -v
```

Expected: zero skips.

- [ ] **Step 5: Run exact Codex install/discovery/call/skill tests**

Provision only into an isolated temporary Codex home, list exactly 41 MCP tools, exercise every family, replay a program receipt, tamper it, and replay the pristine receipt again. Verify wrapper and runtime pins before and after.

- [ ] **Step 6: Update tracker and commit only generated, derived changes**

If package bytes differ from the candidate pins, regenerate every dependent plugin identity and repeat all dependent gates.

### Task 6: Build the production-equivalent Hermes plugin candidate

**Files in fresh `AnubisQuantumCipher/hermes-jackal-verified` checkout:**
- Modify: `plugin.yaml`, `__init__.py`, `schemas.py`, `tools.py`
- Modify: `README.md`, `PROVENANCE.md`, `SECURITY.md`, `CHANGELOG.md`, `THIRD_PARTY_NOTICES.md`
- Modify: `skills/jackal-verified-computation/SKILL.md`, `skills/AGENTS-SNIPPET.md`
- Modify: `tests/test_plugin.py`, `tests/test_plugin_v2.py`, `tests/aba_recheck_gate.py`
- Modify: `scripts/gen_schemas.py`, `scripts/fresh_install_smoke.py`, `scripts/release_audit.py`
- Regenerate: `EPOCH.json`, `MANIFEST.json`, split package parts through owning scripts

- [ ] **Step 1: Clone/isolate and record exact state**

Create `mission/jackal-production-alignment-20260822` from public `main` `e157e4dc98ffc127bb9abca4ae2ea6cdd699db56`, then record status, remotes, tags, releases, and prior package-part convention.

- [ ] **Step 2: Write RED tests for 41 tools and new families**

Change no production bytes yet. Tests must expect exact inventory equality with the new package, three program tools, four domain-pack tools, neutral metadata wording, and real skill tool names. Run them against v5.0.0 and observe the expected 34-versus-41 failures.

- [ ] **Step 3: Import the exact verified package and generate schemas**

Split only because GitHub's per-blob limit requires it. Record whole-package SHA-256 and part SHA-256 values. Generate schemas from the package catalog; do not retype schemas.

- [ ] **Step 4: Update adapter and bundled skill without changing status semantics**

The handler returns the parsed runtime object as JSON. The only plugin-local admission outcome remains the bounded busy/refusal path. Add program-evidence residual preservation and current installation/discovery commands.

- [ ] **Step 5: Regenerate all identities**

Run schema generator, epoch generator, manifest generator, and each `--check`/verify mode. Typed hashes are forbidden.

- [ ] **Step 6: Run full Hermes plugin gates**

```bash
python -m unittest discover -s tests -v
python scripts/verify_manifest.py
python scripts/release_audit.py
python scripts/fresh_install_smoke.py
hermes plugins doctor . --ci
```

Also install the exact commit into a temporary `HERMES_HOME`, verify discovery of 41 tools and one reviewed namespaced skill, exercise every family, and run pristine→tamper→pristine receipt replay.

- [ ] **Step 7: Commit and push non-final candidate**

Do not tag or publish while the kernel is untagged or trust-surface sign-off is unproven.

### Task 7: Independent adversarial review and trust-surface disposition

**Files:**
- Create: `release/evidence/production_alignment_review_v173.json`
- Modify: central tracker with every finding and disposition

- [ ] **Step 1: Freeze exact review bytes**

Record base/head for kernel and Hermes plugin and SHA-256 of `git diff --binary BASE..HEAD` for each.

- [ ] **Step 2: Obtain an independent read-only review**

Review tools, schemas, skills, neutral wording, package pins, proof/admission evidence, receipt replay, and release commands. The reviewer must not edit the worktree and must receive exact base/head/diff identities.

- [ ] **Step 3: Reproduce every actionable finding**

For each finding, run a focused command or construct a hostile fixture. False positives receive evidence-backed dispositions; real defects enter a new TDD red-green cycle and a new commit.

- [ ] **Step 4: Decide the trust-surface lane**

Search current user/architect authority for explicit approval of `inventory-safe-v1` accept conditions and v1.7.3 release promotion. A 41-tool count correction, green checks, or `READY_FOR_SIGNOFF` is not by itself approval. If absent, mark release/tag/merge rows `BLOCKED_TRUST_SURFACE` and continue orthogonal PR preparation without publishing a false release.

`BLOCKED_TRUST_SURFACE` is an internal row status, not a competing terminal
label. When it is the only residual at completion, map it exactly to the
prompt-defined terminal label `BLOCKED_JACKAL_TRUST_SURFACE`.

### Task 8: Seal and read back authorized releases

**Files:**
- Release artifacts and generated evidence only after Task 7 authorizes the lane

- [ ] **Step 1: Re-probe both repositories and GitHub immediately before mutation**

Fetch tags/prune, confirm clean trees, exact candidate heads, no newly landed conflicting PR, and hosted check state.

- [ ] **Step 2: Merge/tag kernel in repository convention only if authorized**

Use the observed merge style. Create an annotated `v1.7.3` tag, verify `tag^{commit}`, publish assets plus SHA256SUMS, download them to a fresh directory, and compare every byte/hash to the local sealed artifacts.

- [ ] **Step 3: Rebind and rerun the Hermes plugin after the kernel tag**

The kernel pin bump invalidates previous dependent evidence. Regenerate plugin identities, rerun every plugin gate, merge in convention, create a new annotated plugin tag/version, publish, download, and compare.

- [ ] **Step 4: Update repository descriptions from executable reality**

Use neutral descriptions with the verified count and explicit formal/program boundaries. Read back both repository descriptions and release metadata through GitHub.

### Task 9: Update existing NousResearch PR #88446

**Files in fresh architect-fork Hermes checkout:**
- Modify: `hermes_cli/data/plugin_index.json`
- Add/modify focused tests only if the index schema or search expectations require them

- [ ] **Step 1: Clone the exact fork branch and record state**

Bind fork remote, upstream remote, branch `feat/index-jackal-verified`, head `08eb5173033e15117f51ac5abc9ca3d8bab313fe`, upstream base, status, and current PR metadata.

- [ ] **Step 2: Write RED index assertions**

Require the exact new immutable plugin commit, neutral description, mechanically verified tool count, `capabilities.tools == True`, `capabilities.skills == True`, and search/resolve behavior. Run against the old entry and observe failure.

- [ ] **Step 3: Update only the existing entry and generated timestamp**

Do not broaden the PR beyond the index seed unless upstream tests require a focused fixture. Preserve schema shape.

- [ ] **Step 4: Run focused and broader applicable tests**

```bash
python -m pytest tests/hermes_cli/test_plugin_index_search.py -q
python -m pytest tests/hermes_cli -q
python -m json.tool hermes_cli/data/plugin_index.json >/dev/null
git diff --check
```

If the broader suite has environment failures, isolate and record them; do not call it green.

- [ ] **Step 5: Commit and push a new PR-branch commit**

Never amend the existing pushed commit. Read back the PR head.

- [ ] **Step 6: Update title/body and add the reproducible verification comment**

The comment must include exact plugin ref, kernel tag/commit, tool-count commands, Lean axiom/admission commands and results, skills audit hash/count, package/manifest hashes, test counts, and explicit non-claims. Record the comment URL.

- [ ] **Step 7: Recheck PR diff, mergeability, review threads, and hosted checks**

Do not claim maintainer approval and do not merge NousResearch upstream.

### Task 10: Completion audit and terminal receipt

**Files:**
- Update: `docs/JACKAL_PRODUCTION_ALIGNMENT_TRACKER_2026-08-22.md`
- Create: `release/evidence/JACKAL_PRODUCTION_ALIGNMENT_RECEIPT_2026-08-22.md`

- [ ] **Step 1: Re-read all 172 lines of the architect goal**

Map every imperative, named artifact, gate, release, metadata surface, and terminal field to tracker evidence.

- [ ] **Step 2: Run the complete clean-checkout gate battery**

Run inventory/drift, full test families, Lean/admission, claim hostile/ABA, fresh package, Hermes install, Codex install, deterministic build, manifests, independent review, and GitHub read-back. Record command, exit, count, hash, and scope for every row.

- [ ] **Step 3: Audit residuals and authority**

Any missing evidence remains incomplete. If the only residual is the unapproved trust surface, use `BLOCKED_JACKAL_TRUST_SURFACE`; otherwise choose the exact permitted partial/blocked status. Use `COMPLETE_JACKAL_PRODUCTION_ALIGNMENT` only if every requirement is current and proven.

- [ ] **Step 4: Commit/push the final receipt where authorized**

The receipt lists every repo/branch/commit/tag/release, 41-tool roster evidence, Hermes/Codex equality, Lean/admission result, commands/exits/counts/hashes, skills, PR #88446 head/comment/checks, public descriptions, independent review, residuals, and non-claims.

## Plan self-review

- **Spec coverage:** Tasks 1–10 cover all prompt sections, all 11 minimum gates, release/pin identity, skills, public descriptions, PR #88446, independent review, and terminal receipt fields.
- **Placeholder scan:** every task names concrete files, behavior, commands, expected observations, and terminal evidence; no deferred implementation marker remains.
- **Type consistency:** canonical inventory is always a JSON object with ordered `tools`; schema identity is `schema_sha256`; integration exposure is the three-key `exposure` object.
- **Authority consistency:** no task equates candidate, green checks, signoff, tag, release, and read-back.
