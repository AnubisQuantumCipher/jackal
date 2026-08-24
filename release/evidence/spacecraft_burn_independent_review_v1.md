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

## Pass 5

Reviewed detached commit: `bf202c74c8d10e7ee0667b83affddd6c716a6d68`

CodeRabbit raised 14 issues. Twelve were confirmed and resolved in the next
candidate:

- gave each hosted OS matrix job a unique evidence-artifact name;
- accepted terminal Markdown emphasis without accepting appended assurance;
- asserted every deterministic archive member mode;
- repaired the oversized-record fixture so it reaches the intended size gate;
- compared both thrust-interval endpoints in the orbital fixture;
- reused one baseline read for validation parsing and hashing;
- rejected certifier input symlinks before resolution;
- required the named expected reason for every source mutation;
- reused formal-binding digests in verifier output;
- made report reproduction commands portable;
- updated the report to the regenerated receipt digest; and
- made the wrapped-qualifier test non-vacuous.

The request-digest warning repeated the exact already-present value and is
invalid. The legacy-v1 mutation request again targets deliberately immutable,
quarantined historical bytes and remains `residual-non-claim`.

## Pass 6

Reviewed detached commit: `fce64c2f59e6879f3a47d68d9399779e6c6c141f`

CodeRabbit raised 7 issues. Four were confirmed and resolved in the next
candidate:

- applied model-conditional claim validation to generated verification text;
- rejected inverted intervals in the Lean square-root decision before
  evaluation and added a kernel-checked fixture;
- rejected proof-closure paths outside `proofs/lean`; and
- read the checker executable once for both digest validation and packaging.

The request-digest warning again conflicts with the exact current value and is
invalid. The two legacy-v1 findings again target deliberately immutable,
quarantined historical bytes and remain `residual-non-claim`.

The square-root hardening changed the checker and proof closure. The candidate
therefore regenerated the proof identity, checker binding, receipt, verifier,
validation, mutation evidence, and manifests rather than carrying old hashes
forward.

## Pass 7

Reviewed detached commit: `5bc9cc19ba7d682530c4fcf896d07751d4ab6880`

CodeRabbit raised 5 issues. Three were confirmed and resolved in the next
candidate:

- normalized inline Markdown before static and generated assurance scanning;
- verified every packaged proof-closure file against its identity byte count
  and SHA-256 before archiving; and
- rejected caller attempts to override the fixed spacecraft proof lane.

The request-digest warning is the same invalid mismatch claim. The legacy-v1
path finding again targets immutable quarantined evidence and remains
`residual-non-claim`. Because the lane wrapper is part of the generator
identity, the proof identity and all receipt-dependent evidence were
regenerated; the checker and witness bytes remained unchanged.

## Pass 8

Reviewed detached commit: `bee0cf89814b176243b7d56abbcd7fb8feb109dd`

CodeRabbit raised 5 issues. Three were confirmed and resolved in the next
candidate:

- normalized inline Markdown so formatting cannot hide assurance language;
- verified packaged proof-closure bytes and hashes against every identity row;
  and
- made the spacecraft identity wrapper reject lane overrides.

The request-digest finding remains invalid. The legacy-v1 finding again
targets immutable quarantined evidence and remains `residual-non-claim`.

Hosted proof-closure execution independently exposed cross-lane configuration
drift: adding the spacecraft executable changed `lakefile.toml`, so the older
Gaussian, range, and int-cert identities correctly refused. Their identities
and the combined Lean admission audit are regenerated by their owning tools in
the next candidate.

## Pass 9

Reviewed detached commit: `abfcf249ae97f0ca489b6e286e44c0cb8a24b283`

CodeRabbit raised 5 issues. Three were confirmed and resolved in the next
candidate:

- normalized rendered Markdown links and HTML emphasis before assurance
  matching;
- cleaned temporary mutation-evidence files after failed atomic writes; and
- read proof identity, checker, and witness inputs once for binding, then
  required checker and witness bytes to remain unchanged after execution.

The request-digest finding again proposes the already-present exact value and
is invalid. The legacy-v1 path finding remains an immutable historical
`residual-non-claim`.

## Pass 10

Reviewed clean committed branch head:
`a6f8da1fb17f0665c2b11bf95fd862d5b4d8cf9c`.

CodeRabbit raised 9 issues. Six were confirmed and resolved in the next
candidate:

- excluded comments before workflow command, action, condition, artifact, and
  ordering assertions;
- normalized HTML-comment delimiters, HTML entities, and Markdown escapes
  before assurance matching;
- marked the README verdict explicitly candidate-only until review, audit,
  hosted gates, and release readback complete;
- executed the outer checker and witness from private byte snapshots bound to
  the hashes used for acceptance;
- required staged auxiliary evidence bytes to match the committed evidence
  checksum manifest before packaging; and
- required the packaged witness digest to match both the receipt witness row
  and the formal-checker binding.

The request-digest warning again quotes the exact already-present 64-character
value and is invalid. The two legacy-v1 findings target deliberately immutable,
quarantined historical evidence and remain `residual-non-claim`; altering those
bytes would destroy their recorded historical identity.

## Pass 11

Reviewed clean committed branch head:
`6c2b452dc6edbdab6c993d7164e49fa5f866948e`.

CodeRabbit raised 2 issues. Both were confirmed and resolved in the next
candidate:

- bound the packaged request to the fixed digest accepted by the Lean checker,
  so mutually editing request bytes and receipt metadata cannot redefine the
  proof statement; and
- required machine-readable completed independent-review clearance before the
  packager can create release-named assets.

## Pass 12

Reviewed clean committed branch head:
`1b8d33e263b6283d784c266172aa05ff7f0834e5`.

CodeRabbit raised one issue: the workflow request digest was only 60
characters and omitted the `c9` pair present in the 64-character request,
Lean, receipt, and packager binding. Hosted checker execution independently
confirmed `REJECT request-digest`. The finding is valid and is resolved in the
next candidate with a test derived from the actual request bytes. This pass
also reviewed the platform-bound hosted campaign and mechanically derived
57-file audit-count fixes added after Pass 11.

### Digest-disposition correction

The Pass 1 through Pass 10 paragraphs that label the repeated workflow
request-digest finding `invalid` are superseded by Pass 12 and this section.
The workflow value was 60 characters, not 64, and hosted checker execution
returned `REJECT request-digest`. All ten repeated findings are therefore
reclassified as valid and resolved by the mechanically checked 64-character
workflow binding in the Pass-12 fix candidate.

## Pass 13

Reviewed clean committed branch head:
`f7193b247c64757b0cd2da1ed02dc1240c285b55`.

CodeRabbit raised 3 issues. All three were confirmed and resolved in the next
candidate:

- added this explicit correction so the earlier digest narratives cannot be
  mistaken for the superseding disposition;
- replaced tautological vis-viva/apoapsis expansion comparisons with residual
  identities linking energy, semimajor axis, eccentricity squared, angular
  momentum, radius, speed squared, and gravitational parameter; and
- independently required the exact positive checker acceptance-line grammar,
  positive ordered margins, bound model, and bound epoch before comparing the
  checker output with the receipt line. A request-digest rejection cannot match
  that grammar.

The regenerated independent-verification and mutation evidence accepts with
the new residual identity names and exact checker-output contract.

## Pass 14

Reviewed clean committed branch head:
`9d299899b3293b643bfc805f0e10cf4effc9ffb6`.

CodeRabbit raised one issue. It was confirmed and resolved in the next
candidate: the mutation harness now normalizes byte-valued timeout stdout and
stderr to UTF-8 replacement-decoded text before hashing and recording complete
failure evidence. Timeout remains a refusal and can never count as a caught
mutation. A regression covers byte-valued partial stdout and stderr.

## Pass 15 status

The clean-worktree review of the Pass-14 timeout-evidence fix is pending. The
machine-readable clearance remains pending and packaging remains fail-closed.

## Current disposition

| Class | Count | Status |
|---|---:|---|
| resolved | 75 | fixed with tests; digest repetitions reclassified valid |
| invalid | 0 | none |
| residual-non-claim | 2 | immutable legacy-v1 historical text only |
| unresolved release-blocking | 0 known | Pass 15 retry pending |

No merge or publication may proceed until Pass 15 records zero unresolved
release-blocking findings and machine-readable clearance returns to complete.
