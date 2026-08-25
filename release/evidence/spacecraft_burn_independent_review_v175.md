# JACKAL v1.7.5 spacecraft-burn internal independent review

Review schema: jackal-spacecraft-independent-review-v175
Status: complete
Reviewed commit: `54c9af66405c445d17735c92ee177cd652fc34b9`
Producer source SHA-256: `d6e98c03e74847b8aea05600c3bae3681e59579506f2a0661504f6ea96e1c38a`
Completed review passes: 37
Resolved findings: 17
Invalid findings: 1
Unresolved release-blocking findings: 0
Review class: internal independent code review, not external peer review

## Review scope

Five independent lenses reviewed evidence-bearing candidate `8b9f5876b9228a5ab3590d1829c8f741c8647411`: full-file Picard producer and witness codec; Lean theorem/checker and proof identity; outer verifier and hostile-input boundaries; deterministic packaging and hosted workflow; and claim/evidence/plugin integration. CodeRabbit independently reviewed the same committed range.

The review-fix cycle then used four adversarial security refutation passes and one separate code-quality pass. Every surviving issue received a failing regression before the implementation change. After evidence regeneration, five fresh independent lenses and a fresh CodeRabbit pass reviewed exact commit `04fd09e1921d94df944697b06a6eef58e4b21b16`; all six final passes returned zero new findings.

The first full package smoke then exposed one additional integration defect: isolated Python removed the private validator's sibling import path. A failing regression preceded the two-file launcher fix. Three independent lenses and a fresh CodeRabbit pass reviewed exact commit `746c16d6fade9d173fe71ab884d137dd238def06`; all four returned zero new findings.

The first hosted full-certificate run then exposed a platform-boundary defect: a macOS-14 runner correctly produced different checker build-attestation bytes from the owning platform, while the owning-platform byte test was guarded only by architecture. The first proposed matcher failed open on malformed records and incomplete inspection; adversarial review caught both issues before repush. Independent launcher-security, integration, and CodeRabbit passes reviewed the final test-only correction at exact commit `62c5cd7a6b8190f78eef685e65aa4e2d4ae2416a`.

The second hosted run reached package tests and correctly refused the non-owning publication runtime, exposing test expectations that still required owning-platform success and an unbounded traceback envelope at the direct entrypoint. Security and integration review rejected permissive refusal codes, normalized stderr, weak runner classification, and the traceback surface. The final production/test correction was independently re-reviewed and CodeRabbit reviewed exact commit `17eb525e0cc87b717d231b275abf1d01c19f3973`.

The third hosted run passed the corrected unit and claim gates, then spent the remaining job budget generating a fresh platform-local proof identity and was canceled at 4h00. The full campaign was preserved and moved to the 360-minute hosted maximum; feature-branch push duplication was removed while PR, master, tag, and manual campaigns remain. Security, integration, and two CodeRabbit passes reviewed the final workflow/test correction at exact commit `54c9af66405c445d17735c92ee177cd652fc34b9`.

Files read in full or through their complete release closure included:

- `spacecraft_burn_cert/certify.py`, `witness_codec.py`, `verify_receipt.py`, `mutation_aba.py`, `release_evidence.py`, and `validate.py`;
- all `proofs/lean/JackalIv/Spacecraft/*.lean` modules reachable from `JackalIv.Spacecraft.CertMain`, `proofs/lean/JackalIv.lean`, and `proofs/lean/lakefile.toml`;
- `release/tools/spacecraft_burn_proof_identity.py`, `release/tools/package_spacecraft_v175.py`, proof identity, current receipt/witness manifest, replay, validation, mutation, and checksum evidence;
- the spacecraft, release-package, claim-gate, proof-identity, workflow, capability, and plugin-impact tests; and
- `README.md`, `spacecraft_burn_cert/README.md`, `spacecraft_burn_cert/REPORT.md`, the v1.7.5 release notes/metadata, the implementation plan, and the JACKEL skill/identity surfaces.

The review did not treat tests as proof of implementation correctness. Reviewers traced the implementation and cross-file bindings directly. The later local/hosted gate results remain separate release evidence.

## Findings and dispositions

Disposition: R-001 | status: resolved | `tools/spacecraft_burn_release_gate.py:26-29,306` now keeps detection case-insensitive while requiring the qualified text and structured verdict to use exact canonical case and spacing.

Disposition: R-002 | status: resolved | `spacecraft_burn_cert/mutation_aba.py:469-518,738-795` now snapshots receipt, request, witness, checker, proof identity, and outer verifier once, binds checker bytes, and requires exact mutation-specific checker refusal lines.

Disposition: R-003 | status: resolved | `spacecraft_burn_cert/verify_receipt.py:844-1000,2856-2866` now rejects a source hash mismatch before parsing and replaces whole-file AST materialization with a bounded streaming tokenizer for six simple top-level contract literals.

Disposition: R-004 | status: resolved | `release/tools/package_spacecraft_v175.py:1867-1932` now requires `checker_sha256` in every witness-mutation record and compares it with the receipt-authoritative checker binding.

Disposition: R-005 | status: resolved | `spacecraft_burn_cert/mutation_aba.py:485-565,601-687` now snapshots `certify.py`, `witness_codec.py`, `tests/test_certifier.py`, and the legacy baseline fixture into one private repository-shaped source-mutation closure.

Disposition: R-006 | status: resolved | `spacecraft_burn_cert/mutation_aba.py:23-27,521-565` now resolves the legacy fixture only at `evidence/legacy-v1/baseline_receipt.json`; the previously referenced current-evidence path does not exist by design.

Disposition: R-007 | status: resolved | `spacecraft_burn_cert/mutation_aba.py:392-404,798-814` strictly parses the snapshotted formal receipt and refuses before mutation unless its `source_sha256` equals the private producer snapshot digest.

Disposition: R-008 | status: resolved | `spacecraft_burn_cert/mutation_aba.py:469-518,570-582` adds a backward-compatible defaulted verifier path to `FormalInputs`, snapshots `verify_receipt.py`, and routes every baseline and witness-mutation outer replay through that private byte copy.

Disposition: R-009 | status: resolved | `spacecraft_burn_cert/evidence/mutation_aba_v2.json:203-260` and `spacecraft_burn_cert/evidence/SHA256SUMS:1-5` were regenerated twice after the schema changes; all three witness records bind checker SHA-256 `2e08149b735ff70a1f1b6606aeca46c9e4dbf2a7d12db2cdc0e80d37f325fa59`.

Disposition: R-010 | status: invalid | CodeRabbit suggested restoring `engine.CHECKER_TARGET` in `tests/spacecraft_burn_proof_identity_test.py:269-284`, but `load_wrapper()` at lines 23-35 creates a new wrapper and engine module for every call, so the assignment cannot leak into another test instance.

Disposition: R-011 | status: resolved | `release/tools/package_spacecraft_v175.py:1936-1946,2028-2042` launches only the private instrument validator with `-E -s -S -B`, restoring its snapshotted sibling import while excluding environment, user-site, site-package, and bytecode effects.

Disposition: R-012 | status: resolved | `tests/spacecraft_burn_proof_identity_test.py:22-66,133-153` independently pins the committed identity bytes and runs the checker/build-byte test only on an exact owning launcher platform; hosted macOS retains unconditional proof/source/axiom checks and labels its checker build platform-local.

Disposition: R-013 | status: resolved | `tests/spacecraft_burn_proof_identity_test.py:67-131` rejects malformed launcher records and inspection errors, observes every launcher before classification, skips a complete mismatch only on exact GitHub Actions macOS, and fails ordinary Darwin/arm64 drift.

Disposition: R-014 | status: resolved | `tests/spacecraft_burn_release_package_v175_test.py:36-100,350-535` treats owning-compatible success as authoritative on any host, but permits a mismatch only on exact GitHub-hosted macOS and only as the canonical publication-runtime refusal.

Disposition: R-015 | status: resolved | `tests/spacecraft_burn_release_package_v175_test.py:36-100,555-705` requires `RUNNER_ENVIRONMENT=github-hosted`, return code 2, empty stdout, exact one-line stderr, no output, and exact Git path/SHA binding on success; alternate codes, whitespace, traceback, and local spoofing refuse.

Disposition: R-016 | status: resolved | `release/tools/package_spacecraft_v175.py:2357-2405` catches only publication-startup `RuntimeError`, emits one closed or generic bounded line with return code 2, and leaves argument parsing and build failures outside the handler.

Disposition: R-017 | status: resolved | `.github/workflows/spacecraft-burn-proof-gate.yml:3-21,149-155` uses the 360-minute GitHub-hosted maximum, runs feature work once through pull requests, retains master and `v*` tag campaigns, and warns rather than masking an earlier failure when no log artifact exists.

Disposition: R-018 | status: resolved | `tests/spacecraft_burn_workflow_test.py:31-145` anchors the exact timeout scalar and scopes always/warn/upload assertions to the unique non-publication artifact step while retaining every proof, certificate, mutation, evidence, and byte-comparison command.

No finding changed the Lean theorem, checker executable, witness, request, model, epoch, nonce, or qualified verdict. R-001 through R-009 and R-011 through R-018 closed publication integrity and bounded-refusal defects around the existing formal result.

## Full-file Picard/source review

The producer review read all of `spacecraft_burn_cert/certify.py` and `spacecraft_burn_cert/witness_codec.py`. Fixed-denominator interval addition, subtraction, multiplication, division, squaring, square root, hull, and intersection remain outward-rounded. Domain guards refuse nonpositive radius-squared, speed-squared, or mass intervals. The producer constructs a strict-interior Picard self-map tube, derives chained endpoint boxes, emits the complete canonical witness, covers the exact cutoff partition, and applies the two independently derived eccentricity enclosures before the final margin intersection.

The reviewed source continues to state the actual boundary at `spacecraft_burn_cert/certify.py:15-17`: the implementation is rigorous interval computation, not a mechanized proof of the nonlinear ODE algorithm or of the Python source. The producer remains `candidate-only`; only the pinned Lean checker can authorize `formal-bounded`, and the outer verifier must reproduce that decision.

The final mutation harness uses a single private snapshot for every decisive input. It binds the producer snapshot to the formal receipt, the checker snapshot to the accepted baseline binding, every source A-before/A-after digest to the same producer digest, every witness mutation to the same witness digest, and every outer replay to the private verifier. The regenerated report records six caught source mutations and three exact checker/outer-verifier witness refusals without promoting those tests into proof evidence.

## Lean correspondence

The formal review traced the canonical codec, dyadic operator lemmas, vector-field constants and units, regularity domain, Picard enclosure and endpoint lemmas, existence/non-vacuity, finite-step composition, exact cutoff coverage, orbital identities, and the universal model-conditional safety theorem.

`JackalIv.Spacecraft.spacecraft_burn_certified_safe` remains the release theorem. Its accepted-certificate implication includes supplied-input coverage, existence of a classical solution chain, and universal positive apoapsis margin for admitted cutoff states. The exact checker, proof identity, request, model ID, release epoch, and witness remain unchanged by the review fixes.

The recorded axiom inventory for load-bearing spacecraft theorems is exactly `propext`, `Classical.choice`, and `Quot.sound`. No project-local `sorry`, `admit`, `axiom`, `native_decide`, `implemented_by`, `extern`, `partial`, or `unsafe` release construct was found in the admitted source closure. This is a Lean-kernel result for the encoded model and accepted witness; it is not a claim that supplied inputs are true or that the model includes every physical effect.

## Final zero-finding pass

Passes 1-6 reviewed the first evidence-bearing candidate through five independent lenses plus CodeRabbit. Passes 7-11 adversarially re-reviewed each repair and exposed the packager, source-closure, receipt-binding, verifier-path, and stale-evidence integrations before clearance. Pass 12 performed a separate maintainability and compatibility review.

Passes 13-18 reviewed exact commit `04fd09e1921d94df944697b06a6eef58e4b21b16`: CodeRabbit, holistic integration, hostile-input security, mathematical/proof correspondence, deterministic package/release binding, and public-claim integrity. Each returned zero new findings. The final security pass recomputed all five tracked evidence digests and cross-checked receipt, witness, checker, request, producer, and proof-identity bindings. The final package pass confirmed the fixed twelve-asset contract and review-admin-only post-review diff. The final claims pass confirmed exact model-conditional wording and no JACKEL plugin-byte impact.

Passes 19-22 reviewed exact commit `746c16d6fade9d173fe71ab884d137dd238def06`: CodeRabbit, launcher hostile-input security, launcher maintainability, and full package integration. Each returned zero new findings. The private validator can resolve only its snapshotted sibling module under the sanitized private working tree; the independent verifier remains on the stricter isolated path.

Passes 23-28 reviewed the hosted platform-boundary correction: initial CodeRabbit, adversarial security and integration passes, corrected security and integration re-reviews, and final CodeRabbit on exact commit `62c5cd7a6b8190f78eef685e65aa4e2d4ae2416a`. The final matcher independently pins the identity, fails closed on malformed or incomplete observation, and distinguishes hosted platform-local mismatch from owning-host drift.

Passes 29-33 reviewed the hosted publication-runtime correction: adversarial package security and integration passes, corrected zero-finding re-reviews, and final CodeRabbit on exact commit `17eb525e0cc87b717d231b275abf1d01c19f3973`. The final packager keeps non-owning hosted bytes non-publication while making its startup refusal exact, bounded, and independently testable.

Passes 34-37 reviewed the hosted runtime-budget correction: workflow security and integration passes, the first CodeRabbit test-oracle findings, and final zero-finding CodeRabbit on exact commit `54c9af66405c445d17735c92ee177cd652fc34b9`. The full campaign remains intact at the maximum hosted duration with non-duplicated feature execution.

Final pass result: pass 37 completed with zero new findings.
