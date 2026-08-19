# JACKAL Codex Plugin Implementation Plan (legacy ID `jackel`)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build, provision, install, and verify the repo-local JACKAL Codex
plugin, retaining the legacy package ID `jackel`, while exposing all 34 JACKAL
v1.7.0 tools without changing their arguments, results, assurance classes, or
refusal semantics.

**Architecture:** The repo-local plugin contains metadata, an operational skill, a standard MCP adapter, a pinned macOS-arm64 runtime provisioner, and an integrity verifier. Before advertising tools, the adapter copies the validated v1.7.0 package into an owned private snapshot, revalidates and selftests that snapshot, and invokes only its unchanged `jackal_hermes call` backend. One process group per call keeps timeout and cancellation from wedging later requests.

**Tech Stack:** Python 3 standard library, `unittest`, line-delimited MCP JSON-RPC, Codex plugin manifests/marketplace CLI, SHA-256, macOS process groups, JACKAL v1.7.0 release artifacts.

**Authority boundary:** Never modify the existing
`/Users/sicarii/Desktop/Projects/jackal-calc` checkout, `plugin/hermes`, or the
sealed v1.7.0 runtime bytes. Work only in
`/Users/sicarii/Worktrees/jackal-codex-plugin`. This publication-blocker
checkpoint authorizes one named-path local commit after all gates pass. Push,
pull request, merge, installation into the real Codex home, and publication
remain separate operator-authorized actions.

---

## File Map

- `.agents/plugins/marketplace.json`: repo-local marketplace metadata.
- `plugins/jackel/.codex-plugin/plugin.json`: publishable plugin manifest.
- `plugins/jackel/.mcp.json`: starts the MCP adapter and permits `JACKAL_HOME` inheritance.
- `plugins/jackel/PLUGIN_IDENTITY.sha256`: sorted integrity inventory for the wrapper bytes.
- `plugins/jackel/mcp/server.py`: MCP lifecycle, schema mapping, one-shot backend calls, cancellation, and runtime resolution.
- `plugins/jackel/scripts/launch_mcp.zsh`: Mac-only, fail-closed interpreter
  capability launcher used by both Codex configuration and acceptance.
- `plugins/jackel/scripts/provision_runtime.py`: pinned v1.7.0 download/offline install and safe extraction.
- `plugins/jackel/scripts/verify_plugin.py`: source/cache wrapper identity validation.
- `plugins/jackel/skills/jackel/SKILL.md`: full-power routing and assurance/refusal guardrails.
- `tests/codex_plugin/test_plugin_metadata.py`: manifest, marketplace, skill, and identity contract tests.
- `tests/codex_plugin/__init__.py`: test package marker.
- `tests/codex_plugin/test_plugin_identity.py`: wrapper inventory tests.
- `tests/codex_plugin/test_runtime_provisioner.py`: platform, download, extraction, atomicity, and locator tests.
- `tests/codex_plugin/test_mcp_adapter.py`: MCP lifecycle, full inventory, forwarding, cancellation, and recovery tests.
- `tests/codex_plugin/live_acceptance.py`: real installed-plugin acceptance driver.

### Task 1: Scaffold and metadata contracts

**Files:**
- Create: `tests/codex_plugin/__init__.py`
- Create: `tests/codex_plugin/test_plugin_metadata.py`
- Create: `plugins/jackel/.codex-plugin/plugin.json`
- Create: `plugins/jackel/.mcp.json`
- Create: `plugins/jackel/skills/jackel/SKILL.md`
- Create: `.agents/plugins/marketplace.json`

- [ ] **Step 1: Write the failing metadata test**

Create a `unittest` module that loads the three JSON files and asserts:

```python
class PluginMetadataTests(unittest.TestCase):
    def test_manifest_and_marketplace_are_aligned(self):
        manifest = load_json(PLUGIN / ".codex-plugin" / "plugin.json")
        marketplace = load_json(ROOT / ".agents" / "plugins" / "marketplace.json")
        entry = marketplace["plugins"][0]
        self.assertEqual("jackel", PLUGIN.name)
        self.assertEqual("jackel", manifest["name"])
        self.assertEqual("jackel", entry["name"])
        self.assertEqual("./plugins/jackel", entry["source"]["path"])
        self.assertEqual("AVAILABLE", entry["policy"]["installation"])
        self.assertEqual("ON_INSTALL", entry["policy"]["authentication"])
        self.assertEqual("Productivity", entry["category"])
        self.assertEqual(["Interactive"], manifest["interface"]["capabilities"])
        self.assertFalse(any("[TODO:" in value for value in walk_strings(manifest)))
```

Also assert the manifest points to `./skills/` and `./.mcp.json`, contains the approved descriptions/default prompts, and omits apps, hooks, nonexistent assets, product gating, and placeholder strings.

- [ ] **Step 2: Run the test and verify RED**

Run:

```bash
python3 -m unittest tests.codex_plugin.test_plugin_metadata -v
```

Expected: `FileNotFoundError` for `plugins/jackel/.codex-plugin/plugin.json`.

- [ ] **Step 3: Run the Plugin Creator scaffold**

Run from the repository root:

```bash
python3 /Users/sicarii/.agents/skills/plugin-creator/scripts/create_basic_plugin.py jackel \
  --path ./plugins \
  --with-skills \
  --with-scripts \
  --with-mcp \
  --with-marketplace \
  --marketplace-path ./.agents/plugins/marketplace.json \
  --category Productivity
```

Do not use `--force`.

- [ ] **Step 4: Replace scaffold placeholders with the approved metadata**

Write version `0.1.0`, author/developer `Anubis Quantum Cipher`, MIT license, repository/homepage URLs, `Interactive` capability, three approved prompts, `mcpServers: "./.mcp.json"`, and `skills: "./skills/"`. Set the marketplace name/display name and keep `AVAILABLE`, `ON_INSTALL`, `Productivity`, and `./plugins/jackel`.

Write `.mcp.json` with:

```json
{
  "mcpServers": {
    "jackel": {
      "command": "python3",
      "args": ["./mcp/server.py"],
      "cwd": ".",
      "env_vars": ["JACKAL_HOME"],
      "tool_timeout_sec": 3700
    }
  }
}
```

Write `skills/jackel/SKILL.md` with valid frontmatter and explicit rules for full inventory access, `jackal_claim`/`jackal_verify_bundle` routing, caller-pinned expectations, exact status preservation, and no silent downgrade.

- [ ] **Step 5: Run metadata and canonical plugin validation**

Run:

```bash
python3 -m unittest tests.codex_plugin.test_plugin_metadata -v
python3 /Users/sicarii/.codex/skills/.system/plugin-creator/scripts/validate_plugin.py plugins/jackel
```

Expected: metadata tests pass. If the validator's interpreter lacks PyYAML, create a temporary venv, install only `PyYAML`, and rerun the same validator from that venv; do not add a runtime dependency.

### Task 2: Wrapper identity verifier

**Files:**
- Create: `tests/codex_plugin/test_plugin_identity.py`
- Create: `plugins/jackel/scripts/verify_plugin.py`
- Create: `plugins/jackel/PLUGIN_IDENTITY.sha256`

- [ ] **Step 1: Write failing identity tests**

Tests must require `parse_manifest`, `verify_manifest`, and `aggregate_digest` APIs and cover a valid sorted manifest, missing file, digest mismatch, duplicate path, unsafe path, unsorted entries, and stable aggregate digest. Use temporary directories and real file bytes.

```python
records = verify_manifest(plugin_root, plugin_root / "PLUGIN_IDENTITY.sha256")
self.assertEqual([".mcp.json", "mcp/server.py"], [r.path for r in records])
self.assertEqual(expected, aggregate_digest(records))
```

- [ ] **Step 2: Run identity tests and verify RED**

Run:

```bash
python3 -m unittest tests.codex_plugin.test_plugin_identity -v
```

Expected: import failure because `verify_plugin.py` does not exist.

- [ ] **Step 3: Implement the minimal verifier**

Use `hashlib.sha256`, `dataclasses.dataclass`, and `pathlib.PurePosixPath`. Accept only canonical lines `<64 lowercase hex><two spaces><relative POSIX path>`, reject absolute/parent/duplicate/unsorted paths, hash files in streaming chunks, and compute the aggregate as SHA-256 over canonical verified lines joined with a final newline.

CLI behavior:

```text
plugin_identity=verified files=<n> aggregate_sha256=<digest>
```

Exit nonzero with one bounded diagnostic on any mismatch.

- [ ] **Step 4: Generate and verify the real wrapper inventory**

After all current plugin files exist, generate a sorted inventory covering `.codex-plugin/plugin.json`, `.mcp.json`, `mcp/server.py`, `scripts/launch_mcp.zsh`, `scripts/provision_runtime.py`, `scripts/verify_plugin.py`, and `skills/jackel/SKILL.md`. Regenerate it whenever one of those files changes, and reject every recursive entry other than those exact records plus the self-excluded identity manifest and their implied directories.

- [ ] **Step 5: Run identity tests and verify GREEN**

Run:

```bash
python3 -m unittest tests.codex_plugin.test_plugin_identity -v
python3 plugins/jackel/scripts/verify_plugin.py
```

Expected: all tests pass and CLI prints `plugin_identity=verified`.

### Task 3: Pinned macOS runtime provisioner

**Files:**
- Create: `tests/codex_plugin/test_runtime_provisioner.py`
- Create: `plugins/jackel/scripts/provision_runtime.py`

- [ ] **Step 1: Write failing provisioner tests**

Require functions `validate_host`, `stream_download`, `safe_members`, `verify_sha256sums`, `validate_runtime`, and `provision`. Tests use tiny fixture archives with injected expected size/digest and cover:

- Darwin/arm64 acceptance and all other hosts refusal;
- declared/streamed oversize rejection before unbounded write;
- exact-size and SHA-256 enforcement;
- absolute path, `..`, device, symlink, and hardlink escape rejection;
- internal `SHA256SUMS` verification;
- staging cleanup after failure;
- atomic runtime and locator install;
- idempotent matching install; and
- divergent destination refusal without overwrite.

- [ ] **Step 2: Run provisioner tests and verify RED**

Run:

```bash
python3 -m unittest tests.codex_plugin.test_runtime_provisioner -v
```

Expected: import failure because `provision_runtime.py` does not exist.

- [ ] **Step 3: Implement safe download and extraction**

Pin epoch `v1.7.0`, filename, HTTPS release URL, size `118862060`, and SHA-256 `21c7ede586f30a58772f321f7dbb36ab66213e199785489f99133710ac56096e`. Use `urllib.request`, `tempfile`, `tarfile`, `hashlib`, `os.replace`, and `Path` only. Stream in bounded chunks, abort on `bytes_seen > expected_size`, and verify size/digest before opening the tar.

Reject all non-file/non-directory entries and any member whose resolved extraction path escapes staging. Extract into staging, verify internal checksums, run `plugin/hermes/jackal_hermes selftest`, write `.jackal-package.json`, and atomically install the runtime and locator.

- [ ] **Step 4: Add CLI modes**

Support:

```text
/bin/zsh launch_mcp.zsh provision
/bin/zsh launch_mcp.zsh provision --tarball /absolute/path/to/jackal-v1.7.0-macos-arm64.tar.gz
/bin/zsh launch_mcp.zsh provision --check
```

Default install root is `~/Library/Application Support/JACKAL/runtimes/v1.7.0`; `--check` is read-only. Tests may override roots through explicit function arguments, not hidden production environment variables.

- [ ] **Step 5: Run provisioner tests and verify GREEN**

Run:

```bash
python3 -m unittest tests.codex_plugin.test_runtime_provisioner -v
```

Expected: all tests pass with no network access.

### Task 4: Standard MCP adapter

**Files:**
- Create: `tests/codex_plugin/test_mcp_adapter.py`
- Create: `plugins/jackel/mcp/server.py`

- [ ] **Step 1: Write failing schema/result tests**

Require functions that map JACKAL `arguments` to JSON Schema and backend JSON to MCP output. Assert all required fields, nested objects, no dropped tool names, semantic deep equality in `structuredContent`, stable JSON text content, and ordinary tool results for `refused`/`indeterminate`.

- [ ] **Step 2: Run focused tests and verify RED**

Run:

```bash
python3 -m unittest tests.codex_plugin.test_mcp_adapter.AdapterPureFunctionTests -v
```

Expected: import failure because `mcp/server.py` does not exist.

- [ ] **Step 3: Implement pure MCP mapping**

Implement `initialize`, `ping`, `tools/list`, and `tools/call` shapes. Convert tool argument records into Draft-07 object schemas, keep backend objects untouched in `structuredContent`, and use compact sorted JSON for the text block.

- [ ] **Step 4: Write failing subprocess/cancellation tests**

Create a fake runtime package in a temporary directory with a fake executable `plugin/hermes/jackal_hermes`, package marker, internal checksum inventory, and two tools. Drive the adapter over stdin/stdout and assert:

- initialize and full tools/list discovery;
- successful and refused tool calls;
- stderr never corrupts stdout;
- matching request-ID cancellation kills child/grandchild processes;
- stale/unknown cancellation does not kill the active request;
- malformed input and backend invalid JSON fail closed;
- a call after cancellation succeeds; and
- source/cache-relative adapter paths resolve the same provisioned runtime.

- [ ] **Step 5: Run integration-focused adapter tests and verify RED**

Run:

```bash
python3 -m unittest tests.codex_plugin.test_mcp_adapter.AdapterProcessTests -v
```

Expected: failures for absent subprocess, cancellation, and recovery behavior.

- [ ] **Step 6: Implement async process control**

Use `asyncio` for the MCP reader/writer and active call task. Spawn one backend per call with `start_new_session=True`; on matching cancellation or timeout, send `SIGTERM` to its process group, wait briefly, then `SIGKILL` if necessary. Serialize calls with an `asyncio.Lock`, bound captured stderr, validate backend JSON, and correlate every response to the originating MCP request ID.

On startup, verify `PLUGIN_IDENTITY.sha256`, resolve only provisioner-validated `JACKAL_HOME` or locator runtimes, recheck package identities, run backend selftest, and load the runtime's 34-tool inventory.

- [ ] **Step 7: Run all adapter tests and verify GREEN**

Run:

```bash
python3 -m unittest tests.codex_plugin.test_mcp_adapter -v
```

Expected: all pure and process tests pass; no leaked fake backend processes remain.

### Task 5: Live acceptance driver and complete local suite

**Files:**
- Create: `tests/codex_plugin/live_acceptance.py`
- Modify: `tests/codex_plugin/test_plugin_metadata.py`
- Regenerate: `plugins/jackel/PLUGIN_IDENTITY.sha256`

- [ ] **Step 1: Write the acceptance driver in dry-run/testable units**

The driver must provide commands/functions to:

- verify wrapper identity;
- verify the pinned runtime and backend selftest;
- send MCP `initialize`, `tools/list`, and `tools/call` messages;
- compare discovered names to runtime `tools.json` exactly;
- directly invoke the same backend and deep-compare results;
- use a temporary `CODEX_HOME` for marketplace add/install/list; and
- locate and verify the installed cache copy.

The live claim path must call `jackal_claim` then `jackal_verify_bundle` with separately supplied expectations. The receipt path must call a supported formal tool then `jackal_verify_receipt` with separately supplied expected epoch, command, expression, bounds, and tolerance where required.

- [ ] **Step 2: Add metadata assertions for every shipped path**

Require all manifest references, MCP command paths, scripts, skill, identity inventory entries, and marketplace fields to exist and agree. Ensure no untracked runtime tarball or extracted runtime is placed in the repository.

- [ ] **Step 3: Run the complete local suite**

Run:

```bash
python3 -m unittest discover -s tests/codex_plugin -v
python3 plugins/jackel/scripts/verify_plugin.py
git diff --check
```

Expected: all tests pass, wrapper identity verifies, and diff check is clean.

- [ ] **Step 4: Run canonical plugin validation**

Run the system Plugin Creator validator under a temporary Python environment containing PyYAML:

```bash
python3 /Users/sicarii/.codex/skills/.system/plugin-creator/scripts/validate_plugin.py plugins/jackel
```

Expected: `Plugin validation passed`.

### Task 6: Provision, install, and execute real JACKAL gates

**Files:**
- Runtime state: `~/Library/Application Support/JACKAL/runtimes/v1.7.0/`
- Locator: `~/Library/Application Support/JACKAL/codex-plugin/runtime.json`
- Temporary isolated Codex home under `mktemp -d`
- No repository source changes beyond Tasks 1-5

- [ ] **Step 1: Inspect existing runtime state read-only**

Resolve the exact target and locator. If either exists, run `--check`; reuse only when all pinned identities match. Never overwrite divergent bytes.

- [ ] **Step 2: Provision the pinned public runtime**

Run:

```bash
/bin/zsh plugins/jackel/scripts/launch_mcp.zsh provision
```

Expected: exact 118862060-byte asset, SHA-256 `21c7ede...`, safe extraction, internal checksum pass, backend selftest pass, and atomic locator creation.

- [ ] **Step 3: Install from the repo-local marketplace in isolation**

Create a temporary Codex home and run:

```bash
CODEX_HOME=<temp> codex plugin marketplace add /Users/sicarii/Worktrees/jackal-codex-plugin --json
CODEX_HOME=<temp> codex plugin add jackel@anubis-quantum-cipher --json
CODEX_HOME=<temp> codex plugin list --json
```

Expected: marketplace and plugin install succeed; the installed wrapper identity matches source.

- [ ] **Step 4: Run real MCP discovery and tool controls**

Run `tests/codex_plugin/live_acceptance.py` against the installed copy. Require exactly 34 discovered tools, a successful `jackal_exact`, a successful checker-attested formal call, a named unsupported-formal refusal with no fallback, claim generation + caller-pinned bundle verification, and formal receipt + caller-pinned receipt verification.

- [ ] **Step 5: Run repository evidence verification**

Run:

```bash
python3 release/verify_evidence.py
```

Expected: no named evidence or identity failure. A nominal summary line does not override a later failure marker.

- [ ] **Step 6: Re-run final verification on the exact installed bytes**

Run the full local suite, canonical validator, wrapper identity comparison, backend selftest, and live acceptance again without changing files between commands. Record the source revision, dirty diff, wrapper digest, package digest, backend bundle digest, discovered tool count, and each decisive result.

Do not call the plugin ready if any required live gate is unavailable or if only source/unit tests passed.

### Task 7: Close publication-blocking fidelity and identity gaps

**Files:**

- Modify: `tests/codex_plugin/test_plugin_metadata.py`
- Modify: `tests/codex_plugin/test_plugin_identity.py`
- Modify: `tests/codex_plugin/test_runtime_provisioner.py`
- Modify: `tests/codex_plugin/test_mcp_adapter.py`
- Modify: `tests/codex_plugin/test_live_acceptance.py`
- Modify: `tests/codex_plugin/live_acceptance.py`
- Modify: `plugins/jackel/.codex-plugin/plugin.json`
- Modify: `plugins/jackel/.mcp.json`
- Modify: `plugins/jackel/mcp/server.py`
- Modify: `plugins/jackel/scripts/provision_runtime.py`
- Modify: `plugins/jackel/scripts/verify_plugin.py`
- Create: `plugins/jackel/scripts/launch_mcp.zsh`
- Modify: `plugins/jackel/skills/jackel/SKILL.md`
- Modify: `docs/superpowers/specs/2026-08-17-jackel-codex-plugin-design.md`
- Regenerate: `plugins/jackel/PLUGIN_IDENTITY.sha256`

- [ ] **Step 1: RED public-name tests**

Keep `jackel` only for the plugin directory, package/server identifier, skill
frontmatter name, marketplace entry, and migration keyword. Require JACKAL in
all public descriptions, display names, prompts, instructions, and headings.
Run the focused metadata test and confirm it fails on the legacy public-name
misspelling.

Run the named metadata test with a fixed absolute interpreter only after it
passes the exact `launch_mcp.zsh` capability probe. The hosted `macos-14`
workflow repeats the complete repository plugin suite on Darwin/arm64; this
historical plan does not bypass the launcher contract with a hard-coded direct
Python invocation.

- [ ] **Step 2: GREEN public-name metadata**

Change only public-facing prose to JACKAL. Do not rename the install ID or
paths; that would break the already installed plugin identity. Update the
operational skill and server instructions consistently.

- [ ] **Step 3: RED clean-Mac launcher tests**

Tests must prove:

- `.mcp.json` starts an absolute macOS system launcher (`/bin/zsh`) rather than
  a machine-specific Homebrew path or inherited `PATH` lookup;
- the launcher selects only explicit absolute interpreter candidates;
- each candidate must pass the adapter's real process-supervision capability
  probe before execution;
- a missing/inadequate interpreter yields one bounded refusal line and exit
  `126` without a traceback;
- `-I -S -B` is always used, so neither user packages nor bytecode caches enter
  the adapter TCB;
- provisioning instructions invoke the same capability contract; and
- the live acceptance driver parses and executes the installed `.mcp.json`
  command/args instead of substituting `sys.executable`.

Confirm RED against the current `/opt/homebrew/bin/python3` configuration and
manual live launch.

- [ ] **Step 4: GREEN allowlisted launcher**

Implement `scripts/launch_mcp.zsh` with bounded input and an ordered list of
absolute Mac interpreter candidates. Do not use `command -v`, an arbitrary
`PATH`, `eval`, or a caller-supplied executable. Probe the exact Python/OS APIs
used by both `server.py` and `provision_runtime.py`, then `exec` the selected
interpreter in isolated/no-site/no-bytecode mode. `.mcp.json` invokes this
script through `/bin/zsh` from the plugin root.

Use one provisioner-owned minimal subprocess environment for selftest and tool
calls: the selected interpreter directory followed only by fixed macOS system
directories in `PATH`, plus the explicit `JACKAL_HOME` allowlist. Do not pass
through caller `PATH`, Python injection variables, or dynamic-loader state.

The initial supported dependency may be the Apple-Silicon Homebrew Python at
`/opt/homebrew/bin/python3`, but absence must be a documented, deterministic
refusal rather than an installation that succeeds and cannot launch. The later
native Mac runtime manager may eliminate this dependency; this checkpoint must
state it honestly.

- [ ] **Step 5: RED backend-refusal fidelity tests**

For a known tool, send argument objects with a missing field, unknown field,
and backend-wrong value type. Directly invoke the same backend bytes and require
the MCP `structuredContent` result to be semantically identical, including
`status: refused` and `reason: plugin-args-schema`. Confirm current code fails by
returning JSON-RPC `-32602` before backend invocation.

Continue to reject non-object `arguments`, non-JSON values, unknown MCP tool
names, and malformed JSON-RPC envelopes as transport errors.

- [ ] **Step 6: GREEN envelope-only adapter validation**

Make `_validate_arguments` enforce only a strict JSON object suitable for the
backend. Do not duplicate required/unknown/property-type decisions from the
JACKAL catalog. Forward the object unchanged and preserve the backend result.

- [ ] **Step 7: RED wrapper completeness and pycache tests**

Create temporary plugin trees with an unlisted regular file, symlink, FIFO,
extra directory, and `__pycache__/*.pyc`. Require identity verification to
refuse each one without blocking. Assert the installed cache contains exactly
the declared plugin file set plus the identity manifest, with no generated
bytecode. Confirm current verifier misses extras.

- [ ] **Step 8: GREEN complete-tree identity**

Extend `verify_plugin.py` to compare the complete safe plugin tree to the
manifest, allowing only the identity manifest itself outside its self-excluding
record set. Use descriptor-relative, no-follow traversal and bounded counts/
sizes. Reject hidden or ignored extras rather than relying on Git status.
Regenerate the inventory to include `scripts/launch_mcp.zsh`.

- [ ] **Step 9: RED production host-guard test**

Patch the production adapter's platform/machine observations to Linux,
Darwin/x86_64, and unknown values while supplying an otherwise valid runtime.
Each startup must refuse before runtime discovery, selftest, or tools-list
advertisement. Confirm current server starts because only the provisioner calls
`validate_host`.

- [ ] **Step 10: GREEN production host guard**

Call the provisioner's single `validate_host` authority from
`build_production_server` before reading a locator or `JACKAL_HOME`. Do not
reimplement a subtly different platform test in the adapter.

- [ ] **Step 11: RED verified-byte module-load race**

During startup, replace `scripts/verify_plugin.py` or
`scripts/provision_runtime.py` after its digest is checked but before module
execution. The adapter must never execute the replacement. Confirm the current
verify-then-reread loader is vulnerable.

- [ ] **Step 12: GREEN exact-byte module loading**

Open each wrapper module with no-follow semantics, read/hash/fstat it once
against the caller-pinned inventory record, and compile exactly those verified
bytes. Do not close and reopen the path between identity decision and `exec`.
Keep module diagnostics bounded and ensure `.pyc` is never loaded or written.

- [ ] **Step 13: RED post-start runtime replacement**

Start a production server against a valid fake runtime, replace
`plugin/hermes/jackal_hermes` and at least one backend source after startup with
bytes that fabricate a stronger result, then issue a call. The fabricated
result must never reach `structuredContent`. Confirm current server executes
the changed path.

- [ ] **Step 14: GREEN private runtime snapshot binding**

Before tools are advertised, construct a private temporary runtime snapshot
from the validated package, using no-follow regular-file copies and exact
manifest membership. Validate the completed snapshot again against the
caller-pinned package-tree digest and run selftest from it. `MCPServer` retains
ownership of the snapshot for its lifetime and executes only the snapshot
launcher. Original-runtime replacement after startup can neither affect a call
nor fabricate a status. Close and EOF must delete the snapshot after all
workers are reaped. Per-call cancellation reaps the affected process group but
retains the snapshot while the server remains available for subsequent calls.

The snapshot must not silently accept symlinks, special files, extra paths,
partial copies, or a mixed source race. Tests must cover cleanup after startup
failure and normal close. This is an adapter containment measure, not a new
calculation authority or an OS immutability claim. A hostile same-UID process
can still target the owned snapshot; stronger isolation remains outside this
checkpoint.

Bound checksum-manifest bytes/records, recursive entry count, depth, UTF-8 path
bytes, per-file bytes, and aggregate bytes before expensive hashing or copying.
Anchor descriptor and parent-directory identities across verification. Bound
active-plus-queued calls and stdio handler tasks; excess valid calls return an
ordinary deterministic `plugin-busy` refusal, and capacity must recover after
success, cancellation, timeout, and backend error.

- [ ] **Step 15: Run focused GREEN gates**

Run the five focused modules, full `tests/codex_plugin` discovery, and
`plugins/jackel/scripts/verify_plugin.py` with the exact fixed interpreter that
has passed `launch_mcp.zsh`'s complete capability probe. Run repository
module-name unittest gates with `-B`; `-I -S -B` remains mandatory for
launcher-controlled adapter and provisioner execution, where the launcher
supplies the verified source path explicitly. The pinned `macos-14` workflow is
the hosted reproduction of these commands and also runs the offline
installed-config smoke. Do not substitute a caller-`PATH` interpreter merely
to make this historical checklist portable.

Require zero warnings, no leaked processes/snapshots, and no `__pycache__` under
the source or isolated installed plugin.

### Task 8: Final exact-byte acceptance, review, and publication

- [ ] Re-run the complete plugin suite and canonical Plugin Creator validator.
- [ ] Run the live driver through the installed `.mcp.json` launch command.
- [ ] After installing the final frozen wrapper into the explicitly selected
  real Codex home, run the separate fresh-task discovery hook. The exact
  operator command is:

  ```bash
  set -o pipefail
  cd /Users/sicarii/Worktrees/jackal-codex-plugin
  /Users/sicarii/.local/bin/codex plugin add jackel@anubis-quantum-cipher --json
  JACKAL_PROBED_PYTHON=/opt/homebrew/bin/python3
  HOST_EVIDENCE="/private/tmp/jackal-codex-host-$(/bin/date -u +%Y%m%dT%H%M%SZ)-$$.jsonl"
  HOST_REPORT="${HOST_EVIDENCE%.jsonl}.report.json"
  "$JACKAL_PROBED_PYTHON" -I -S -B tests/codex_plugin/live_acceptance.py \
    --host-live \
    --codex-home /Users/sicarii/.codex \
    --codex-binary /Users/sicarii/.local/bin/codex \
    --runtime-root '/Users/sicarii/Library/Application Support/JACKAL/runtimes/v1.7.0' \
    --host-evidence "$HOST_EVIDENCE" | /usr/bin/tee "$HOST_REPORT"
  ```

  `JACKAL_PROBED_PYTHON` must first pass the unchanged launcher probe. This
  command intentionally targets real Codex state and is outside the present
  isolated remediation run. Until its nonce-bound raw JSONL and canonical
  report are captured from the frozen installed identity, fresh-task host acceptance remains unproven.
  The hook records the canonical host executable path, size, SHA-256, and
  strict version before and after the task as a caller-supplied external trust anchor.
  This tamper-evident provenance does not authenticate an official Codex binary;
  the operator must separately trust the executable selected for the gate.
  Its fail-closed transcript validator requires canonical event and item keys,
  passive item text, exact MCP lifecycle state, and deep equality between each
  MCP completion's strict-JSON text content and structured content.
  It also requires exact successful claim and verifier result key sets and
  binds the self-excluding bundle digest, route/root/rendering/policy/proposition,
  `claim-verify=verified`, `bundle.digest=`, and epoch-plus-nonce freshness.
  Process-group cleanup treats only `ESRCH` as absence. Before or after a
  transient `EPERM`, the separate bounded observer may affirm quiescence only
  when WNOWAIT retains the exited leader and every observed group member is a
  zombie; the permission error itself is never reclassified as absence.
- [ ] Require exactly 34 full-profile tools, direct/MCP parity for success and
  backend refusal, formal acceptance, unsupported-formal refusal without
  fallback, bundle replay, and receipt replay.
- [ ] Mutate the original runtime after server startup in a disposable fixture
  and prove the private snapshot prevents result substitution.
- [ ] Run `release/verify_evidence.py`; separately report the known v1.7.0
  direct-checker interval-ordering gap as a v1.7.2 Gate 0 blocker, not as a
  plugin regression or a solved condition.
- [ ] Assert the sealed v1.7.0 package digest before and after every gate.
- [ ] Obtain independent specification-compliance approval, then independent
  code-quality approval; fix and re-review every Important/Critical finding.
- [ ] Stage only the explicit plugin/docs/test paths, inspect the staged diff,
  and commit with exact test totals and identities. Push, pull request, CI,
  merge, and hosted read-back belong to a later explicitly authorized
  publication run.

Progressive `core`/`formal`/`full` profiles remain an additive Gate 2 workstream.
The initial checkpoint may expose all 34 tools because this preserves the
existing backend surface, but it must not claim that the full catalog improves
autonomous verifier selection until eval v2 measures that result.
