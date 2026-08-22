# JACKAL Codex Plugin Design (legacy ID `jackel`)

Date: 2026-08-17

Base repository: `https://github.com/AnubisQuantumCipher/jackal`

Original design base: `7d9b5bee0ce52fb6bbe24e4c50f5661f5bad2318`

Current publication base: `c3ec10f5b446b28a04f9bd19606fc8b329ac43f5`

<!-- JACKAL_CURRENT_SURFACE_V1_BEGIN -->
The current `v1.7.3-candidate` exposes the ordered 41-tool catalog recorded in
`release/capability_inventory_v1.json`, with tool-containing implementation
ref `d25bcd9818e0d106f337798f80527ae611cc3acc`. Candidate state does not assert
an annotated public v1.7.3 tag or release.
<!-- JACKAL_CURRENT_SURFACE_V1_END -->

## Objective

Add a repo-local, publishable Codex plugin with migration-preserved package ID
`jackel` and public display name JACKAL. It exposes JACKAL's complete
mathematical evidence-kernel tool inventory on macOS. The plugin must make the
full engine available without weakening JACKAL's epistemic classes, refusal
semantics, checker boundaries, or pinned runtime identity.

The plugin is installed from a JACKAL repository checkout. Its computation
runtime is the separately pinned JACKAL v1.7.3 candidate macOS package, not a
copy assembled from source-tree fragments. Until authorized publication, the
operator provisions the exact local candidate tarball rather than treating the
future release URL as proof that a release exists. The plugin does not duplicate or
modify `plugin/hermes`; an explicit provisioner installs the hash-pinned
release package in the user's macOS Application Support directory. The first
verified platform is Apple Silicon macOS. Intel macOS remains unsupported
until JACKAL publishes and seals a corresponding runtime.

## Goals

- Expose every tool declared by `plugin/hermes/tools.json`; the current base
  revision declares 41 tools in catalog order with no duplicate aliases.
- Make `jackal_claim` and `jackal_verify_bundle` the preferred front doors for
  general structured claims while retaining every exact, checked, estimated,
  bounded, formal-bounded, model-based, and verification lane.
- Preserve backend JSON values losslessly as structured MCP output.
- Keep named refusals first-class. A refusal is a valid epistemic result, not a
  reason to retry silently through a weaker lane.
- Add complete Codex plugin metadata and a repo-local marketplace entry.
- Require no hosted service, OAuth flow, network connection, or third-party
  Python package during calculation. A separate, explicit provisioning
  command may download the pinned release package before first use.
- Detect missing repository files, runtime artifacts, pins, or backend startup
  failures and fail closed with actionable diagnostics.

## Non-goals

- Reimplementing any JACKAL calculation, proof checker, claim router, receipt
  verifier, or bundle verifier.
- Copying `plugin/hermes` or any pinned runtime file into `plugins/jackel`.
- Editing the load-bearing Hermes bundle, which would change its pinned bundle
  identity.
- Presenting a checker-admitted formal fragment as whole-system formal
  assurance.
- Adding a hosted connector, `.app.json`, HTTP service, hooks, branding assets,
  screenshots, or an automatic first-run download in version 0.1.0.
- Supporting Linux, Windows, or Intel macOS in the initial release.

## Repository Layout

The implementation adds only the following plugin-facing paths:

```text
.agents/plugins/marketplace.json
plugins/jackel/
  .codex-plugin/plugin.json
  .mcp.json
  PLUGIN_IDENTITY.sha256
  README.md
  mcp/server.py
  scripts/launch_mcp.zsh
  scripts/provision_runtime.py
  scripts/verify_plugin.py
  skills/jackel/SKILL.md
tests/codex_plugin/
  test_mcp_adapter.py
  test_plugin_metadata.py
  test_runtime_provisioner.py
```

`plugins/jackel/mcp/server.py` is a transport adapter, not a mathematical
backend. It locates a separately sealed runtime and invokes the unchanged
`plugin/hermes/jackal_hermes` launcher shipped in that package.

## Plugin Manifest

`plugins/jackel/.codex-plugin/plugin.json` uses:

- `name`: `jackel`
- `version`: `0.1.0+codex.<14-digit timestamp>`
- `description`: `Expose JACKAL's claim-aware computation, domain-pack, and program-evidence kernel to Codex.`
- `author.name`: `Anubis Quantum Cipher`
- `author.url`: `https://github.com/AnubisQuantumCipher`
- `homepage` and `repository`:
  `https://github.com/AnubisQuantumCipher/jackal`
- `license`: `MIT`
- `skills`: `./skills/`
- `mcpServers`: `./.mcp.json`
- `interface.displayName`: `JACKAL`
- `interface.shortDescription`: `Claim-aware computation with explicit evidence classes`
- `interface.longDescription`: `Expose JACKAL's 41-tool v1.7.3 candidate runtime through Codex. The MCP adapter copies the parsed runtime result object into structuredContent unchanged; its only adapter-local tool result is status=refused reason=plugin-busy. Runtime result and assurance vocabulary: ok, exact, structural-exact, formal-bounded, bounded, checked, estimated, model-based, verified, verified-program-evidence, verified-program-receipt, indeterminate, and refused. Formal-bounded is limited to checker-admitted fragments; program evidence leaves construct-totality, source, and runtime residuals open. Requires Apple Silicon macOS and Python >=3.10 at /opt/homebrew/bin/python3 (install with brew install python).`
- `interface.developerName`: `Anubis Quantum Cipher`
- `interface.category`: `Productivity`
- `interface.capabilities`: `["Interactive"]`
- `interface.websiteURL`: `https://github.com/AnubisQuantumCipher/jackal`
- `keywords`: `jackel`, `mathematics`, `numerical-trust`, `formal-verification`,
  `evidence`, `mcp`

The short description identifies JACKAL as an evidence kernel, not a generic
calculator. The long description names the mathematical, domain-pack, and
program-evidence classes; it keeps formal fragments and program residuals
explicit.
The initial manifest omits app, hook, asset, privacy-policy, and terms fields
rather than publishing broken paths or invented policies.

Starter prompts:

1. `Classify and verify this numerical claim with JACKAL.`
2. `Find the strongest supported bound and refuse any silent downgrade.`
3. `Verify this receipt or claim bundle against my pinned expectations.`
4. `Verify this Anubis Safe program-evidence package without executing its artifact.`

## Marketplace Entry

`.agents/plugins/marketplace.json` is rooted in the JACKAL repository and
contains:

- top-level `name`: `anubis-quantum-cipher`
- `interface.displayName`: `Anubis Quantum Cipher`
- plugin name: `jackel`
- source: local `./plugins/jackel`
- installation policy: `AVAILABLE`
- authentication policy: `ON_INSTALL`
- category: `Productivity`

No product gating is added. The marketplace source is repo-local. Runtime
artifacts are provisioned separately from the pinned public release package so
that Codex's installed/cache layout cannot accidentally change which engine or
checker bytes execute.

## Runtime Provisioning

`plugins/jackel/scripts/provision_runtime.py` is an explicit operator command,
not an automatic install hook. Version 0.1.0 candidate pins:

- release epoch: `v1.7.3`
- asset: `jackal-v1.7.3-macos-arm64.tar.gz`
- release URL:
  `https://github.com/AnubisQuantumCipher/jackal/releases/download/v1.7.3/jackal-v1.7.3-macos-arm64.tar.gz`
- package SHA-256:
  `b2c0819b2c631939217583dc420cc67ba9e4acf613b4b49c208f020ba1bd1175`
- package size: `158353643` bytes
- extracted `SHA256SUMS` SHA-256:
  `2c1605dc1b0ad01801418f741d54c92a4a44d1362a35a09a47fcf0752aee3a42`

The provisioner:

1. Refuses unless the host is macOS on `arm64`.
2. Downloads into a newly created temporary directory or accepts an explicit
   local tarball path for offline installation.
3. Rejects a declared or streamed body larger than 158353643 bytes, then
   requires exactly that size and the fixed package SHA-256 before extraction.
   The per-operation network timeout is supplemented by a monotonic total download deadline,
   so a peer cannot keep the transfer alive indefinitely
   by returning one small chunk inside each socket timeout.
4. Rejects absolute paths, parent traversal, device entries, and escaping
   links in the archive.
5. Extracts to a staging directory and verifies the package's own
   `SHA256SUMS` and `MANIFEST.sha256`-governed selftest.
6. Writes a package marker binding the epoch, original tarball digest, and
   verified internal identities, then atomically installs the package at
   `~/Library/Application Support/JACKAL/runtimes/v1.7.3/`.
7. Atomically writes a locator containing the release epoch, runtime path, and
   package digest at
   `~/Library/Application Support/JACKAL/codex-plugin/runtime.json`.

An existing valid runtime makes provisioning an idempotent success. An
existing divergent runtime is never overwritten silently; the operator must
remove or relocate it explicitly.

The installed `.jackal-package.json` marker is read through a no-follow,
directory-descriptor anchor with an explicit byte ceiling, stable descriptor
and current-path identity checks, a parent-directory mutation epoch,
duplicate-key rejection and canonical JSON enforcement. Oversized metadata,
regular replacement, or a coordinated replace-and-restore race refuses before
the runtime can be reused.

The MCP adapter resolves runtime roots in this order:

1. `JACKAL_HOME`, when explicitly inherited by the MCP configuration; and
2. the provisioner's macOS locator.

Every candidate must be a provisioner-verified extraction with the package
marker, identify epoch v1.7.3, match the pinned original package digest, pass
all internal `SHA256SUMS`/manifest identities, and pass the backend bundle
selftest. A source checkout containing a few untracked binaries is not a valid
runtime candidate. Ambiguous or divergent candidates refuse and require an
explicit `JACKAL_HOME` choice.

## MCP Architecture

### Why an adapter is required

The existing backend describes itself as MCP-style JSON-RPC and supports
`list_tools` plus direct method names. Codex MCP clients use the standard
`initialize`, `tools/list`, and `tools/call` lifecycle. Pointing `.mcp.json`
directly at the backend would therefore advertise a protocol it does not
currently implement.

The adapter is scoped only to this transport gap. Faithful forwarding of
JACKAL tool arguments, results, assurance classes, and refusal classes is a
tested invariant; the adapter is explicitly included in the fidelity TCB.

### Process model

`plugins/jackel/.mcp.json` launches:

```json
{
  "mcpServers": {
    "jackel": {
      "command": "/bin/zsh",
      "args": ["./scripts/launch_mcp.zsh"],
      "cwd": ".",
      "env_vars": ["JACKAL_HOME"],
      "tool_timeout_sec": 3700
    }
  }
}
```

The Mac launcher selects only an absolute, allowlisted Python interpreter that
passes the Python-version and process-supervision capability probes required by
the adapter and provisioner. It does not trust an inherited `PATH`. It always
executes with `-I -S -B`; if no candidate passes, it emits one bounded refusal
line and exits `126` before loading the adapter. Provisioning instructions use
the same launcher contract, so installation documentation, MCP startup, and
live acceptance cannot disagree about the interpreter.

The supported clean-machine prerequisite is Python >=3.10 at
`/opt/homebrew/bin/python3`; `brew install python` is the documented recovery.
Existing `/usr/local/bin/python3` and `/usr/bin/python3` installations are
accepted only when the same complete capability probe passes.

After the probe, both runtime selftest and every tool call receive the same
minimal environment: `PATH` begins with the selected interpreter's directory
and then only fixed macOS system directories, and `JACKAL_HOME` is the sole
allowlisted inherited JACKAL variable. Caller `PATH`, Python injection
variables, dynamic-loader variables, and unrelated process state are not
forwarded to the sealed launcher's bare `python3` lookup.

The installed-config live adapter and its direct-backend comparator use the
same provisioner-owned sanitized environment. Hostile caller `PATH`, Python
startup variables, dynamic-loader variables, and unrelated `CODEX_HOME`
state therefore cannot make the direct comparison exercise different backend
bytes from the installed MCP path.

The 3,700-second host ceiling covers the backend's current longest documented
operation (3,600 seconds for bundle verification) plus bounded transport
overhead. JACKAL's own lane-specific time and work budgets remain authoritative.

The adapter uses only the Python standard library. On startup it reads each
wrapper module once with no-follow semantics and compiles exactly the bytes
matched by the caller-pinned identity record. It then calls the provisioner's
single host-policy authority before locator, `JACKAL_HOME`, runtime, or tool
discovery. After validating the sealed runtime, it builds a private temporary
snapshot by no-follow regular-file copies, revalidates the completed snapshot
against the pinned package-tree digest, and selftests it. Tool discovery and
every `tools/call` use only that owned snapshot. Each call starts a fresh
`jackal_hermes call <tool> <json-args>` subprocess in a new process group.
Per-call processes avoid a timed-out calculation wedging a shared backend and
ensure the backend startup/identity gate runs for every invocation.

Runtime preflight and snapshot validation bound checksum-manifest bytes and
records, recursive entries, depth, UTF-8 path bytes, individual file bytes,
and aggregate file bytes before expensive hashing or copying. They compare
stable descriptor metadata, current no-follow path identity, exact tree
membership, and parent-directory mutation epochs before accepting a tree.

The MCP reader remains responsive while a worker owns the active calculation.
On `notifications/cancelled` whose `params.requestId` matches the active call,
host timeout, stdin closure, or adapter shutdown, the adapter terminates the
whole request process group, waits for it to exit, and returns to a usable
state. Cancellation for a queued, stale, completed, or unknown request ID must
not affect the active calculation. Version 0.1.0 serializes calculations; a
second call waits behind the active call rather than sharing mutable backend
state. At most eight calls may be active or queued; additional valid calls
return the ordinary JACKAL-shaped `status: refused`, `reason: plugin-busy`
result. The stdio reader applies backpressure at sixteen handler tasks, so
input cannot create an unbounded task set. Capacity is released after success,
backend failure, timeout, or cancellation. Responses enter a bounded response-byte queue
drained through the event loop's nonblocking write-pipe
transport, so a client that stops reading stdout cannot freeze cancellation,
EOF cleanup, or the input loop. Deeply nested JSON is bounded per request;
`RecursionError` and unexpected handler-task failures become one bounded
protocol error without terminating stdio service. Backend stderr is captured
as a bounded diagnostic and never mixed into MCP stdout. On startup refusal,
a partially completed snapshot is closed; snapshot cleanup failure is a named startup refusal rather than a silently suppressed residue; normal
close or stdin EOF closes it only after active workers are reaped. A cancelled
call reaps its process group but retains the snapshot while the server remains
available for later calls.

Only `ESRCH` or `ProcessLookupError` is treated as proof that a process group
is absent. `EPERM` is a bounded named failure unless a bounded re-observation
independently proves quiescence. On macOS, a completed group containing the
retained leader plus only zombie members can make signalling return `EPERM`;
the adapter and provisioner accept that case only after WNOWAIT retains the
exited leader and a separate process-table observation affirmatively shows
that the leader is present and every observed member is a zombie. An observer failure cannot suppress an otherwise permitted process-group signal and
cannot excuse `EPERM`. They never reinterpret a permission error itself as proof of absence.

The private directory and independent copies bind execution against later
changes to the original provisioned runtime. They are not an OS immutability
claim: a hostile process running as the same UID can still target the private
snapshot while the server owns it or alter a same-UID-writable interpreter
installation after its capability probe. Defending that residual requires a
stronger OS isolation boundary outside this plugin checkpoint.

### Protocol mapping

The adapter implements these MCP methods:

- `initialize`: returns the negotiated protocol version, server identity
  `jackel-codex`, and tool capability.
- `notifications/initialized`: accepted without a response.
- `ping`: returns an empty result.
- `tools/list`: translates every tool in the selftested runtime's `tools.json`
  into JSON Schema. Required arguments populate the schema's `required` array.
  No JACKAL tool is filtered out.
- `tools/call`: validates only the MCP envelope and that `arguments` is a strict
  JSON object, then forwards `params.name` and `params.arguments` through the
  unchanged one-shot backend launcher. Missing/unknown JACKAL arguments and
  JACKAL argument value types are decided by the backend and retain its normal
  `status: refused` result rather than being rewritten as transport errors.

Successful backend JSON becomes both:

- `structuredContent`: the exact parsed backend object; and
- one text content block containing a stable JSON serialization for clients
  that do not consume structured content.

A JACKAL result with `status: refused` or `status: indeterminate` remains a
normal MCP tool result. It is not marked as a transport error, because the
status is part of the engine's answer. Malformed MCP requests, unknown MCP
methods, a dead backend, invalid backend JSON, or JSON-RPC correlation errors
are protocol errors and use JSON-RPC error responses.

Faithful forwarding is a required adapter invariant, not a theorem. Except for the adapter-local `plugin-busy` admission refusal, the adapter must not manufacture
`formal-bounded`, `verified`, `exact`, or any other JACKAL status, and release
acceptance compares its structured result by semantic deep equality with a
direct invocation of the same backend bytes.

## Trust and Artifact Identity

The MCP adapter and operational skill are new trusted presentation components:
they can select a tool, rewrite a request, hide a field, or misstate a result
if defective or malicious. They are not part of JACKAL's mathematical checker
TCB, but they are part of the end-to-end Codex request/result fidelity TCB.

`plugins/jackel/PLUGIN_IDENTITY.sha256` records a stable, sorted digest
inventory for the plugin manifest, MCP manifest, installation/operation
README, launcher, adapter, provisioner, verification script, and operational
skill. The manifest excludes only itself. `scripts/verify_plugin.py` performs a bounded descriptor-relative,
no-follow traversal and rejects every unlisted file, link, special entry,
directory, bytecode cache, oversized manifest/file set, path-identity change,
or parent-directory mutation before printing a deterministic
aggregate wrapper digest. The source Git revision and marketplace snapshot are
the external trust anchors; the self-check is tamper evidence, not author
authentication.

Acceptance compares the source plugin identity to the actual Codex-installed
cache copy and records the wrapper digest alongside the backend package digest.
Any adapter or skill edit therefore moves the wrapper identity even when the
separately pinned Hermes bundle and proof checkers remain unchanged.

## Operational Skill

`plugins/jackel/skills/jackel/SKILL.md` teaches Codex how to use the full tool
surface without flattening its trust model.

Required behavior:

- Use `jackal_claim` for a structured claim that may require routing across
  evidence lanes.
- Use `jackal_verify_bundle` for independent bundle replay and
  `jackal_verify_receipt` for formal receipt replay.
- Use direct tools when the user requests a specific computation or assurance
  lane, or when the claim router identifies the appropriate lane.
- Preserve `status`, assurance metadata, assumptions, non-claims, residuals,
  fingerprints, and refusal details in the response.
- Never describe `bounded` as `formal-bounded`, `checked` as proved,
  `estimated` as bounded, or a successful fragment as whole-system soundness.
- Never silently retry a refused strong request through a weaker tool. Offer a
  weaker lane only with an explicit change in claim class.
- For bundle verification, take release epoch, policy digest, root proposition,
  nonce, and verification time from the caller or a separately trusted source;
  never copy expected values from the untrusted bundle being verified.
- For receipt verification, apply the same rule to expected release epoch,
  command, expression, input bounds, and tolerance when the variant requires
  it. Never derive caller expectations from the receipt under review.
- Treat bundle-identity and pin mismatches as safety failures that require
  operator attention.
- Explain that formal producers can be untrusted because the pinned checker
  replays the certificate, while runtime provenance remains a separate
  enforced boundary.

The skill may summarize long receipts for the user, but must retain the full
structured tool result in the task context and must not omit a refusal reason
or residual non-claim that changes interpretation.

## Data Flow

```text
User request
  -> JACKAL operational skill selects a tool
  -> Codex MCP tools/call
  -> installed, identity-recorded transport adapter
  -> unchanged one-shot plugin/hermes backend from the sealed runtime package
  -> pinned evaluator / producer / checker / verifier path
  -> backend JSON with an explicit status
  -> semantically identical structuredContent returned to Codex
  -> user-facing explanation at the same epistemic class
```

The operational skill influences tool selection and explanation only. The MCP
adapter is intended to influence protocol shape only, but is explicitly part
of the request/result fidelity TCB and is tested accordingly. The existing
JACKAL backend remains the authority that computes and assigns assurance
status; the adapter is not authorized to create or promote that status.

## Error and Refusal Handling

- Missing or divergent runtime/locator: adapter startup fails with the pinned
  provisioning command and no tool inventory is advertised.
- Backend startup-gate failure: preserve the backend reason, such as a missing
  manifest row or bundle mismatch, and stop the adapter.
- Backend death during a request: terminate its process group, return a
  JSON-RPC internal error containing a bounded diagnostic, and remain usable
  for a later independent call. Do not retry the calculation automatically.
- Invalid tool arguments: return JACKAL's `plugin-args-schema` refusal when the
  backend produced it.
- Unsupported formal request: return the named JACKAL refusal unchanged and do
  not call a weaker lane.
- Checker rejection, identity mismatch, or TOCTOU detection: return the
  backend's refusal unchanged.
- Matching-request cancellation or timeout: terminate the active request
  process group and discard any late output. A cancellation for another
  request is ignored for the active process. A cancelled or timed-out call is
  never converted into a successful result.

## Validation and Acceptance

### Metadata checks

- Parse `plugin.json`, `.mcp.json`, and `marketplace.json` as JSON.
- Run the canonical Plugin Creator `validate_plugin.py` with a development
  Python environment that supplies its PyYAML dependency.
- Assert plugin folder name, manifest name, marketplace name, and marketplace
  source path agree.
- Assert marketplace policies and category are present.
- Assert manifest paths resolve and no placeholder or missing asset path is
  published.
- Verify `PLUGIN_IDENTITY.sha256`, compute the aggregate wrapper digest, and
  require the installed cache copy to match the source plugin identity.

### Provisioner tests

- Reject non-macOS and non-arm64 hosts before downloading.
- Verify the fixed v1.7.3 URL, epoch, filename, exact 158353643-byte length,
  bounded streaming download, and expected package SHA-256.
- Exercise offline local-tarball provisioning with a fixture archive.
- Reject digest mismatch, path traversal, absolute paths, device entries,
  escaping links, missing package files, failed package checksums, and failed
  backend selftest.
- Verify staging cleanup, atomic install/locator updates, idempotent reuse, and
  refusal to overwrite divergent runtime bytes.

### Adapter unit tests

- Exercise `initialize`, `ping`, `tools/list`, and `tools/call` against a fake
  one-shot backend using line-delimited MCP JSON-RPC.
- Verify every source tool is exposed exactly once and argument schemas retain
  required/optional distinctions.
- Verify arbitrary nested backend JSON is preserved in `structuredContent`.
- Verify `refused` and `indeterminate` remain ordinary structured tool results.
- Verify malformed client input, mismatched backend IDs, invalid backend JSON,
  and premature backend exit fail closed.
- Verify cancellation and timeout kill the entire request process group,
  discard late output, and leave the adapter usable for the next call.
- Verify only a cancellation carrying the active MCP request ID can terminate
  that request; queued, stale, completed, and unknown IDs cannot cross-cancel.
- Compare every supported status shape and a refusal shape by semantic deep
  equality against direct one-shot backend invocation.

### Live installed-plugin checks

Using the pinned v1.7.3 candidate runtime and an isolated temporary `CODEX_HOME`:

The installer derives forbidden state roots from both the passwd account home
and the process home, canonicalizes them independently of caller `HOME`, and
refuses a selected directory that is equal to, an ancestor or descendant of,
either real Codex state root. The plan carries that authority into execution.
Execution requires the selected home to remain the same canonical non-symlink
directory inode and rechecks it before every Codex install command and after
the final command. This prevents forged-`HOME`, symlink-alias, overlapping
temporary-root, and between-command replacement from redirecting the isolated
flow into account state; it is not an OS isolation claim against a same-UID
process racing inside one validation-to-exec interval.

1. Provision the runtime from the downloaded asset and again from an offline
   local tarball; require the package and bundle identities to match.
2. Add the repository as a local marketplace with
   `codex plugin marketplace add <repo>`.
3. Install `jackel@anubis-quantum-cipher` with `codex plugin add`.
4. Locate the actual installed/cache copy and require its wrapper identity to
   match the source plugin.
5. Parse the installed copy's `.mcp.json` and launch its exact configured
   absolute command, arguments, and installed-copy working directory. Perform
   a real MCP `initialize` and `tools/list`; require the discovered names to
   equal the pinned runtime's ordered 41-tool `plugin/hermes/tools.json` inventory.
6. Call `jackal_exact` on a supported rational expression and require
   `status: exact`.
7. Call a supported formal fragment and require semantic deep equality with a
   direct invocation of the same checker-attested backend bytes.
8. Call an intentionally unsupported formal request and require a named
   refusal with no weaker fallback.
9. Generate a structured claim with `jackal_claim`, then independently replay
   it with `jackal_verify_bundle` using separately caller-pinned expectations.
10. Generate a formal receipt and replay it separately with
    `jackal_verify_receipt`, again using caller-pinned expectations.
11. Run `python3 release/verify_evidence.py`; a general green line does not
   override any named identity failure.

The repository also supplies `live_acceptance.py` with `--host-live` for the separate
fresh Codex host-discovery gate. It first binds the source and installed cache
identities and uses bounded `codex mcp list --json` reads before and after the
task to require the exact active `jackel` MCP declaration and resolved cache cwd
to match that verified installed copy. Before and after the task it also
resolves and no-follow reads the selected host executable, binds its canonical
path, byte count, SHA-256, stable file/parent identities, and strict
`codex-cli` version line, and reports the selection as a caller-supplied external trust anchor.
This tamper-evident path/version/digest record does not authenticate an official Codex binary;
fresh-host acceptance therefore depends on the operator separately trusting
the supplied executable anchor. It then generates an internal nonce,
launches a new ephemeral read-only Codex task with a neutral prompt that names
no plugin, server, or tool, and records a bounded no-overwrite JSONL transcript.
Acceptance requires the global event order thread-start, turn-start, claim-start, claim-complete, verify-start, verify-complete, turn-complete
for exactly `jackal_claim` followed by `jackal_verify_bundle`, exact
nonce/request/bundle/caller-pin binding, and a verified structured result. The
validator inspects `item.started`, `item.updated`, and `item.completed`, and
refuses any unknown top-level or active-capability event, including shell,
file, web, collaboration, or unrelated MCP activity. It requires canonical event and item keys,
including nonempty string identifiers and passive item text, before it performs
exact MCP state validation from `in_progress` to `completed`, requires each
update between its correlated start and completion, and requires turn usage
with nonnegative `input_tokens`, `cached_input_tokens`, and `output_tokens`.
`cache_write_input_tokens` and `reasoning_output_tokens` are the only permitted optional counters.
Every passive `reasoning` or `agent_message` lifecycle must stay inside the
turn, carry nonempty passive item identifiers, and be either a fully correlated
start/update/complete sequence or a terminal-only passive completion emitted
by the host. Each required MCP completion must contain one strict-JSON text
block, and the host text content and structured content must compare by
semantic deep equality; missing, malformed, or divergent fallbacks refuse.
The hook also requires exact successful claim and verifier result key sets,
recomputes the self-excluding claim-bundle digest, binds the returned root,
rendering, policy, proposition, and selected route, and requires verifier report
lines `claim-verify=verified`, `bundle.digest=`, the caller-pinned proposition,
and v1.6.0 freshness with the host nonce bound.
Host subprocess supervision retains the unreaped leader anchor,
cleans the whole process group before reaping, and refuses boundedly if selector
allocation, stream handling, or group cleanup fails; a leader exit cannot hide
a resistant descendant.
It then performs post-task identity and active-MCP rechecks. Synthetic event
fixtures test the validator, but that does not itself constitute fresh-host evidence.

The hosted `.github/workflows/jackal-codex-plugin.yml` job runs on `macos-14`,
asserts Darwin/arm64, runs the complete repository plugin suite, exact identity
verifier, repository metadata/skill checks, and offline installed-config smoke.
It pins every action by full commit SHA and neither downloads nor provisions a
runtime. Hosted CI is regression protection; the runtime-backed and fresh-host
gates remain separate evidence requirements.

### Completion standard

Scaffold creation, JSON validity, or successful tool discovery alone is not
completion. Version 0.1.0 is ready only when canonical plugin validation,
wrapper-identity checks, provisioner tests, adapter unit tests, real
marketplace installation, fresh-task MCP discovery, one supported computation,
one checker-attested call, one fail-closed control, backend selftest, and the
repository evidence verifier all pass against the same source revision and
pinned v1.7.3 candidate runtime bytes.

If sealed runtime artifacts are absent, source and unit work may be complete,
but the plugin must be reported as integration-blocked rather than ready.
