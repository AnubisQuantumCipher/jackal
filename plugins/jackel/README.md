# JACKAL for Codex (legacy package ID `jackel`)

This repo-local Codex plugin exposes the JACKAL v1.7.3 release runtime. The
installer supports Darwin/arm64 and Linux/aarch64; only the macOS-arm64 release
asset is published today, so Linux hosts must supply a locally built runtime and
its own pins. Its current source contract is the ordered 41-tool inventory in
`release/capability_inventory_v1.json`; the package receipt and downloaded
release asset must bind the same exact bytes.

The MCP server is a transport adapter. It loads schemas from the admitted
runtime and copies each parsed runtime result into `structuredContent`. The
adapter's only local result is `status=refused reason=plugin-busy`; other
statuses and fields come from the runtime.

## Install and provision

Add the JACKAL repository as a local marketplace, install
`jackel@anubis-quantum-cipher`, and provision the pinned release runtime. The
default command downloads the fixed release asset; pass `--tarball` with an
absolute path for an offline installation:

```bash
codex plugin marketplace add /absolute/path/to/jackal
codex plugin add jackel@anubis-quantum-cipher
cd /absolute/path/to/the/installed/jackel/plugin
/bin/sh scripts/launch_mcp.sh provision
# Offline alternative:
# /bin/sh scripts/launch_mcp.sh provision --tarball \
#   /absolute/path/to/jackal-v1.7.3-macos-arm64.tar.gz
/bin/sh scripts/launch_mcp.sh provision --check
codex mcp list --json
```

Require exactly 41 unique JACKAL tool names and an MCP working directory bound
to the installed plugin copy. Python 3.10 or newer at
`/opt/homebrew/bin/python3` (macOS) or `/usr/bin/python3` (Linux) is the
supported prerequisite; the launcher accepts any of its three fixed absolute
candidates that pass the full capability probe, which includes the host's
atomic no-replace rename symbol. It never searches caller `PATH`.

## Routing

- Use `jackal_claim` for mixed or policy-bearing claim graphs and
  `jackal_verify_bundle` for caller-pinned independent replay.
- Use `jackal_verify_receipt` for formal receipt replay against independent
  request and identity expectations.
- Use direct typed tools for one exact, checked, estimated, bounded,
  formal-bounded, structural, or decision operation.
- Use `jackal_anubis_verify_program` for caller-selected Safe source/evidence
  bytes, `jackal_anubis_verify_program_receipt` for receipt recomputation, and
  `jackal_anubis_check_program` only with the caller-pinned approved compiler.
  None executes the artifact.

No silent downgrade is permitted. `refused` and `indeterminate` are terminal
outcomes unless the caller explicitly requests a separate weaker lane. Never
copy an `expected_*` value from the receipt or bundle being verified.

Program evidence under `inventory-safe-v1` must retain
`policy-construct-totality-not-established`, `no-source-to-vc-proof`,
`no-smt-to-cnf-proof`, `no-source-native-refinement`, `runtime-not-observed`,
and `no-universal-language-soundness`. It is not `formal-bounded` and does not
establish runtime behavior.

## Verify source bytes

From the JACKAL repository root:

```bash
python3 -B plugins/jackel/scripts/verify_plugin.py
python3 -B tools/capability_drift_gate.py
python3 -B -m unittest discover -s tests/codex_plugin -v
```

The wrapper identity manifest is tamper evidence bound to a separately trusted
Git revision or plugin snapshot. SHA-256 alone is not author authentication or
mathematical proof.
