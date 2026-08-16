# JACKAL v1.6.0 — migration guide (10-tool and 31-tool epochs → 33 tools)

v1.6.0 is the Mathematical Evidence Kernel release: the intact v1.5.0
31-tool surface plus two additive claim-kernel front doors
(`jackal_claim`, `jackal_verify_bundle`), for exactly 33 tools.

## Where you might be starting from

| Installed surface | Epoch | Tools | Migration effect |
|---|---|---|---|
| Hermes plugin pinned to a v1.4.2-era release | v1.4.2 | 10 | strict superset; no caller breaks |
| Hermes plugin/skill describing v1.5.0 | v1.5.0 | 31 | strict superset; no caller breaks |
| This release | v1.6.0 | 33 | current |

The v1.4.2-era 10-tool surface is a strict subset of the 31-tool
surface, which is a strict subset of the 33-tool surface — mechanically
locked by `release/compat/v150_floor.json` + `tools/compat_floor.py
--check` (tool names, required/optional arguments, return keys, engine
commands, gate list, coverage rows, epistemic classes, and wrappers are
additive-only).

## What migration to v1.6.0 delivers

- All 31 v1.5.0 tools, unchanged names/arguments/returns/statuses.
- Two additive front-door tools: `jackal_claim` (deterministic policy
  router → `jackal-claim-bundle-v1`) and `jackal_verify_bundle`
  (independent caller-pinned replay).
- Legacy `jackal-formal-receipt-v1` receipts continue to verify under
  their original expected epoch/request — the coverage inventory and
  proof identities are byte-identical to the v1.5.0 seal, so previously
  emitted receipts keep verifying.

## Install from the immutable public release

1. Download `jackal-v1.6.0-macos-arm64.tar.gz` and `SHA256SUMS` from the
   v1.6.0 GitHub release of this repository (Apple Silicon macOS).
2. Verify before extracting:
   `shasum -a 256 -c SHA256SUMS` (and compare the tarball hash against
   the release notes and `PROVENANCE.md`).
3. Extract and run the packaged smoke path (`./jackal self-test`, then
   any wrapper); every packaged wrapper re-verifies its pinned
   identities from the packaged `MANIFEST.sha256` before producing a
   formal or exact status.

The trust chain is acyclic: this core release seals the package hash;
the separate `hermes-jackal-verified` plugin release then pins that
exact public package hash and is itself installed by full 40-character
commit. The core package never embeds a future plugin commit.

## Hermes plugin migration

1. Install/upgrade the plugin from its own repository release, pinned to
   the exact full release commit (see
   `AnubisQuantumCipher/hermes-jackal-verified` release notes for the
   command).
2. Reconcile any local edits in an existing plugin checkout before
   overwriting (a dirty `MANIFEST.json` or bundled `SKILL.md` means
   local changes predate the upgrade).
3. **Start a NEW Hermes session after installation** — tool schemas are
   loaded once per session, and the plugin startup gate hashes its
   bundle once per process; a live session keeps the old epoch until
   restarted.
4. In the fresh session the registered inventory is exactly 33 tools;
   `jackal_claim`/`jackal_verify_bundle` appear alongside every legacy
   tool.

## Parity evidence (mechanical, sealed with this release)

- `tests/claim_package_parity_test.py`: the same claim request through
  the repo CLI, the fresh-extracted package CLI, and the plugin `call`
  frontend returns the SAME canonical root hash and bundle digest, and
  replays `verified`; a tampered bundle refuses (`node-id-mismatch`).
- `tests/plugin_smoke.py` S8: the plugin stdio inventory is EXACTLY the
  33 intended tools.
- `tests/plugin_bundle_identity_test.py`: 27 runtime logical names
  (22 v1.5.0 + 5 claim-kernel files) are bundle-hash-bound; any byte
  mutation refuses `plugin-bundle-mismatch`.

## Unchanged trust boundaries

- No existing verifier acceptance rule changed in this migration.
- Verifier `PASS`/`verified` semantics are identical to v1.5.0 for all
  legacy lanes; the claim kernel adds new fail-closed surfaces only.
- Residual non-claims are unchanged and enumerated in `PROVENANCE.md`
  and `release/claim/SPEC.md`.
