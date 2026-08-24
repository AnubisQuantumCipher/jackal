# Spacecraft burn independent review record

Date: 2026-08-24

Reviewer: CodeRabbit CLI 0.7.5 in agent mode, authenticated through the
AnubisQuantumCipher GitHub organization. This is an internal independent code
review, not external peer review.

Base: `origin/master` at `4789adc949d47fd1d1e00eaa9532dd5ca0dbff70`

## Pass 1

Reviewed detached commit: `4ee6aa5a10a11683d09508710b450ab36c70e6a8`

CodeRabbit raised 9 issues. Eight were confirmed and resolved in
`2834e366457c91be63ab81e0b9b98b55e3a9d65b`:

- bounded the Lean witness record envelope before line materialization;
- rejected non-newline ASCII controls in the Python codec;
- stopped treating source-test timeouts as caught mutations;
- moved source mutation tests to isolated copies;
- closed the v2 evidence directory against stale entries;
- added full macOS hosted execution alongside Ubuntu;
- reconciled the 57-file repository audit with the 23-file generated closure;
- removed stale producer-only version language and regenerated all evidence.

The request-digest warning was not valid. The workflow value, Lean
`spacecraftRequestDigest`, proof-identity fragment, and SHA-256 of
`spacecraft_burn_cert/request_v2.json` all equal
`03bcad618ad60114007c74a384eb8c9432e3755b817e74bd5bdc9bd1ba6df3e7`.

## Pass 2

Reviewed detached commit: `2834e366457c91be63ab81e0b9b98b55e3a9d65b`

CodeRabbit raised 8 issues, all confirmed and resolved in
`9aa26381a83b81537fa8c35dc60f095299d275b2`:

- made receipt hashing portable to macOS;
- made the action-pin test non-vacuous;
- used a cross-platform tolerance for floating-point diagnostics;
- derived validation counts from the receipt step and required exact division;
- refused malformed replay sections without traceback;
- skipped checker-byte mutation tests when the binary is not built;
- normalized wrapped qualified verdicts without losing line positions;
- rejected caller-supplied symlinks before resolution.

## Pass 3

Reviewed commit: `9aa26381a83b81537fa8c35dc60f095299d275b2`

CodeRabbit raised 8 issues. Five were confirmed and resolved in
`f5091fd65d1d91a384ba8f049e21ef74e177d224`:

- removed the workstation-local source-package path from the design;
- prevented witness-checker timeouts from counting as refusals;
- parsed complete verifier output rather than a reporting excerpt;
- replaced a tautological symbolic check with a cleared-denominator vis-viva
  expansion identity;
- made qualified and unqualified verdict detection case-insensitive.

The repeated request-digest issue was again invalid for the byte evidence
listed above. Two legacy-v1 observations are classified
`residual-non-claim`: the quarantined historical `SHA256SUMS` names the v1
source hashes, and the historical mutation JSON contains old local path text.
Those bytes are deliberately immutable, excluded from current claim surfaces,
and never used as v2 authority. Rewriting them would destroy the preserved v1
artifact identity.

## Pass 4

Reviewed detached commit: `eb3031abebaa72294a1d0c8d97b3cfb16cfcc842`

CodeRabbit completed a full review and raised 10 issues. Seven were confirmed
and resolved in the next candidate:

- restored candidate wording until publication is complete;
- required a sentence boundary after the approved model-conditional verdict;
- hashed proof-identity and producer-source bytes from the same reads used for
  parsing;
- added explicit installation and verification of the optional full witness;
- derived release-verification request/model/epoch/nonce text from the bound
  receipt and validated the release binding;
- replaced machine-specific Python shebangs across the spacecraft lane; and
- made the reproduction commands portable.

The request-digest warning was again invalid: the workflow, Lean constant,
proof identity, receipt binding, and SHA-256 of `request_v2.json` are exactly
the same value recorded in Pass 1. The two legacy-v1 findings repeated the
previous request to rewrite quarantined historical bytes; they remain
`residual-non-claim` because changing them would invalidate the preserved v1
artifact identity.

## Pass 5 status

The final clean-worktree retry is pending on the post-Pass-4 fix commit.

## Current disposition

| Class | Count | Status |
|---|---:|---|
| resolved | 28 | fixed with tests; final push pending |
| invalid | 3 | request digest independently matched |
| residual-non-claim | 2 | immutable legacy-v1 historical text only |
| unresolved release-blocking | 0 known | final independent retry pending |

No publication or merge may use this record as a final clearance until the
Pass 5 section records a completed review result.
