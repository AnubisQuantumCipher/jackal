# JACKAL Production Alignment Design

**Architect-approved source:** `JACKAL_PRODUCTION_ALIGNMENT_CODEX_GOAL_2026-08-22.md`
**Source identity:** 12,611 bytes, 172 lines, SHA-256 `8025fb5570587258ec3cf6c808df71451af5b8815a7a5778f7d1e48e296dad7d`
**Initial tool-containing implementation ref:** `d25bcd9818e0d106f337798f80527ae611cc3acc`
**Live candidate authority:** `AnubisQuantumCipher/jackal` PR #12; its moving head is bound in `docs/JACKAL_PRODUCTION_ALIGNMENT_TRACKER_2026-08-22.md` rather than duplicated here.

## Objective and non-negotiable boundary

Align the current JACKAL kernel, Hermes plugin, Codex plugin, every JACKAL-routing skill, release metadata, public repository metadata, and NousResearch Hermes PR #88446 to one mechanically verified capability surface. The expected full surface is 41 unique tools, but the count is accepted only when current registry bytes, Hermes discovery, and Codex discovery independently agree.

No alignment change may alter what a verifier accepts, expand a proof checker trust assumption, weaken a refusal, or silently promote `estimated`, `bounded`, `structural-exact`, `verified-program-evidence`, `indeterminate`, or `refused`. An accept-condition change is isolated from release work and reported as `BLOCKED_TRUST_SURFACE` until explicit sign-off exists.

## Approaches considered

1. **Extend the clean PR #12 candidate and derive downstream surfaces from it — selected.** This preserves the already reviewed 41-tool implementation, exact v1.7.3 package bytes, Codex adapter, program-evidence residuals, and existing gates. New work adds canonical inventory and anti-drift enforcement before updating downstream releases.
2. **Rebuild from public `master`.** Public `master` exposes the merged 38-tool line, so this would replay three existing candidate commits and increase the chance of a second, divergent v1.7.3 implementation.
3. **Edit only public metadata and PR prose.** Rejected because the public Hermes plugin still contains v1.7.0/34-tool executable bytes, tests, schemas, skills, and release pins. Prose-only alignment would make the catalog claim false.

## Repository topology and ownership

- **Kernel plus Codex plugin:** `AnubisQuantumCipher/jackal`. The existing clean PR #12 worktree is the integration source. The stale dirty Desktop checkout is evidence only and remains untouched.
- **Hermes plugin:** `AnubisQuantumCipher/hermes-jackal-verified`. The installed detached v5.0.0 checkout is immutable evidence; implementation occurs in a fresh isolated clone or worktree from public `main`.
- **Hermes upstream index PR:** `NousResearch/hermes-agent#88446`, backed by the architect-owned fork branch `feat/index-jackal-verified`. The dirty local Hermes main checkout is not used for changes; the PR branch is edited in a fresh isolated checkout.
- **Skills:** in-repository Codex and Hermes plugin skills are released with their plugins. Personal Hermes/Codex JACKAL skills are audited separately and changed only when they actually route JACKAL work or make current capability claims.

## Canonical capability inventory

Add a deterministic generator and committed JSON artifact with one record per exported tool in `plugin/hermes/tools.json` declaration order. Each record contains:

- tool name and SHA-256 of its canonical schema record;
- kernel, Hermes, and Codex exposure expectations;
- admitted result/status classes and consequence ceiling;
- checker/proof dependency or an explicit `none` value;
- supported fragment summary and explicit refusal/non-coverage summary;
- profile membership and the candidate/release identity containing the tool.

The generator reads current catalog, profile, manifest, proof-identity, and integration bytes. It rejects missing or duplicate tools, unknown status vocabulary, unknown checker identities, unbound tool facts, wrong profile membership, and any output not in catalog order. A `--check` mode reproduces the committed artifact byte-for-byte. It never rewrites proof evidence or release manifests.

The inventory records `v1.7.3-candidate` until a v1.7.3 annotated tag and release are authorized, created, and read back. It must not describe an untagged candidate as a public release.

## Drift prevention

Add one repository drift gate that consumes the canonical inventory and checks:

- kernel catalog count and unique name set;
- Hermes profile/discovery roster;
- Codex MCP discovery roster and wrapper expected count;
- plugin manifests, schemas, compatibility floors, release builders, and pinned package identities;
- in-repository skills and user-facing docs for real tool names, current count/version, status vocabulary, and forbidden stale pins/counts;
- generated inventory and plugin identity manifests in `--check` mode.

The gate is semantic where possible. It does not ban the text `34` globally because migration history and tests can truthfully mention old epochs. Current-surface files have an explicit allowlist and exact expected values; historical files are labeled historical rather than rewritten.

## Hermes plugin alignment

Build a new Hermes plugin version from the exact verified v1.7.3 package candidate rather than modifying v5.0.0 or its tag. Generate the Hermes schema set from the package catalog, expose exactly the same 41 names, preserve raw result JSON/statuses, and update the bundled skill, manifest, provenance, security boundary, tests, and release audit.

The plugin release remains unsealed while the kernel candidate is untagged or while the `inventory-safe-v1` trust-surface sign-off is not proven. A non-final branch may contain prepared bytes and passing gates; its metadata must say candidate, not release.

## Skills alignment

Every JACKAL-routing skill is classified as one of:

- **direct router:** names typed tools and must be checked against the inventory;
- **claim router:** sends mixed/policy-bearing/consequential work through `jackal_claim` and independent replay through dedicated verifiers;
- **audit procedure:** discusses JACKAL but does not advertise a live tool roster;
- **incidental mention:** no routing/capability claim and no update required.

Direct and claim routers receive fixtures that parse every backticked `jackal_*` name and require it to exist in the canonical inventory. They must preserve status, refusal, residual, expected-identity independence, and host-specific installation steps.

## Release and PR state machine

The release sequence is `candidate -> audited -> independently reviewed -> sign-off proven -> tagged -> published -> read-back verified`. A stage does not imply the next stage.

After kernel and plugin release identities are immutable, update the existing PR #88446 branch rather than opening another PR. The index entry, PR title/body, capabilities, and exact 40-character plugin ref must match the reviewed release. The verification comment records commands, exits, counts, Lean axiom/admission evidence, skill audit, hashes, and non-claims. Upstream merge remains outside authorization.

## Error handling and evidence

- A surface mismatch is a failing gate, not a prose warning.
- A missing checker or unverified pin is `refused`/blocked, never a weaker success.
- A non-measurable evaluation remains exit 3 and is not counted as pass or fail.
- Package tests skipped for lack of a fresh package root stay open until run against a fresh build.
- Every long tranche ends in a named-path commit with command-derived receipts; no blanket staging or pushed-history rewrite.

## Testing and independent review

Implementation follows red-green TDD. New drift and inventory tests must fail against the current stale surfaces before production changes. Existing mutation suites validate that the instruments can turn red.

Final gates cover unique roster equality, positive family smoke, hostile/refusal controls, claim A-to-B-to-A tamper replay, Lean build and axiom/admission scan, fresh-package Hermes and Codex discovery, deterministic repin/build checks, clean-checkout replay, and an independent adversarial review of code, skills, public wording, pins, receipts, and trust-surface non-claims.

## Design self-review

- **Placeholder scan:** no deferred implementation placeholder is present.
- **Consistency:** 41 is an expected value that must be recomputed; it is not used as a prose-only override.
- **Scope:** kernel/Codex, Hermes plugin, skills, release metadata, and PR #88446 are separate tranches joined by one canonical inventory.
- **Ambiguity:** existing `inventory-safe-v1` accept conditions are audited but not promoted through merge/tag/release unless explicit sign-off is evidenced.
