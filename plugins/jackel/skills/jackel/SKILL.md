---
name: jackel
description: Route claim-aware computation, domain-pack, and Anubis program evidence through JACKAL without overstating assurance.
---

# JACKAL numerical-trust operator

<!-- JACKAL_CURRENT_SURFACE_V1_BEGIN -->
The v1.7.3 release exposes the ordered 41-tool full inventory recorded in
`release/capability_inventory_v1.json`. Treat that generated file as the
capability-name and status source; the release tag, package receipt, and asset
must bind the same exact bytes.
<!-- JACKAL_CURRENT_SURFACE_V1_END -->

JACKAL exposes the full tool inventory on Apple Silicon macOS. Use it to
classify a quantitative claim, select the strongest admitted evidence lane,
and preserve the exact assurance boundary returned by the runtime.

## Choose the front door

- Use `jackal_claim` for multi-step, unit-aware, model-conditioned, or
  consequential claims that need a content-addressed evidence graph and route
  trace. Keep fallback disabled; never enable it merely to obtain an answer.
- Use `jackal_verify_bundle` to independently replay an existing claim bundle
  against caller-pinned epoch, policy digest, root proposition, verification
  time, and nonce.
- Use `jackal_verify_receipt` to re-run the pinned checker over an existing
  formal receipt against caller-authorized request values.
- Use a direct tool when the caller needs one narrow operation rather than a
  claim graph; direct tools remain available and must retain their returned
  epistemic class.
- Use `jackal_test_exists` / `jackal_claim_cites_test` only for structural
  source facts. Preserve their `informational` consequence ceiling: existence
  and citation resolution are not correctness or coverage.
- Use `jackal_decision_rank_v2` for a caller-declared numeric criterion with a
  canonical unit. A declared unit is not a measurement; never present the
  selected option as an intrinsic value judgment.
- Use `jackal_anubis_verify_program` for caller-selected Safe source/evidence
  bytes, `jackal_anubis_verify_program_receipt` to recompute a receipt, and
  `jackal_anubis_check_program` only when the caller supplies the approved
  compiler and a new output root. None executes the compiled artifact.

Verification expectations are authorization, not data discovery. Expected
bundle and receipt values must come from the caller or separately trusted source, not evidence under review.
Never copy an `expected_*` value from the bundle or receipt being verified. A
bundle/pin identity mismatch is a safety failure.

For receipt replay, the exact expected command depends on the receipt:

- range and pure-Q fragment receipts: `range-bound-cert`
- Gaussian receipts: `integrate`
- composed `int_cert` receipts: `integrate-bound-cert`

Current formal range and composed-integral receipts use release epoch v1.7.2;
the additive package/runtime epoch is v1.7.3.

## Select the assurance lane

- `exact`: `jackal_exact` and the exact algebra/number-theory tools. Exact
  integer or rational computation is not a Lean-formal claim.
- `checked`: `jackal_diff`. Sampled numeric agreement is a check, not an
  identity proof.
- `estimated`: `jackal_evaluate`, `jackal_integrate`,
  `jackal_integrate_adaptive`, and `jackal_solve`; an error estimate is not a bound.
- `bounded`: `jackal_integrate_bound`. Its enclosure is conditional on the
  stated f64/libm rounding model and is never formal.
- `formal-bounded`: only the checker-admitted tools below, and only after the
  pinned checker accepts.
- `model-based`: use a structured `jackal_claim` model step. Preserve every
  model assumption; mathematical exactness does not establish model validity.
- `verified`: a replay verdict against fixed expectations, not a replacement
  for the evidence graph's mathematical class, assumptions, or non-claims.
- `structural-exact`: byte-exact source structure, consequence-capped at
  `informational`; never code correctness.
- `verified-program-evidence` / `verified-program-receipt`: inventory-safe-v1
  program evidence or its replay. These statuses are not formal-bounded and do
  not close policy-construct totality, source-to-VC, SMT-to-CNF,
  source-native, runtime, or universal-soundness residuals.

## Formal-bounded admitted fragments

- `jackal_range_bound`: the certified range fragment.
- `jackal_gaussian_integral`: only canonical `exp(-A*(x-mu)^2)` requests.
- `jackal_integrate_bound_cert`: composed integrals over
  `num/var/neg/add/sub/mul/div/pow(0..4096)/sin/cos/abs` in `x`.
- `jackal_{sqrt,exp,ln,sin,cos,atan}_rat_bound`: only the exact named unary
  form and its documented rational domain.
- `jackal_tanh_rat_bound`: only `1-2/(exp(2*x)+1)` on the documented domain;
  `tanh(x)` itself is not admitted.

JACKAL's formal-bounded applies only to checker-admitted fragments. Do not claim
formal coverage for arbitrary expressions or material outside that admitted
fragment. Source-to-native refinement remains open and unclaimed.

## Anubis program-evidence boundary

Require profile `inventory-safe-v1`, Safe mode, one exact source leaf, strict
v3 stage/file/consumer rosters, nonzero one-to-one proof paths, approved Z3
UNSAT replay, and independent RUP replay. Always preserve:

- `no-source-to-vc-proof`
- `no-smt-to-cnf-proof`
- `policy-construct-totality-not-established`
- `no-source-native-refinement`
- `runtime-not-observed`
- `no-universal-language-soundness`

Refuse `contracted-safe-v1`; the producer-attested whole-function roster is not
independent construct-total walker coverage. Never execute the compiled
artifact to strengthen the status.

## Preserve refusal and residuals

No silent downgrade is permitted.
You must preserve every returned status/assumption/non-claim/residual/refusal verbatim.
You must never promote assurance or silently downgrade a requested claim. If a
strong lane refuses, return its named reason. Run a weaker lane only when the caller explicitly requests one,
and present it as a separate weaker result.

Do not turn `refused` or `indeterminate` into an MCP error or a plausible
number. Do not summarize away route traces, assumptions, receipt identities,
checker verdicts, or residual non-claims.

## macOS runtime

This plugin supports Apple Silicon macOS only and uses the pinned v1.7.3
candidate macOS-arm64 runtime. Until that candidate is published, provision it
from the separately verified local tarball path.
Do not bypass the Darwin/arm64 host guard or substitute another platform build.

Python >=3.10 at `/opt/homebrew/bin/python3` is the supported fixed-path
prerequisite on Apple Silicon. If it is absent or fails the launcher's
capability probe, install it with `brew install python`, then rerun the same
launcher command. The launcher also probes `/usr/local/bin/python3` and
`/usr/bin/python3` when either already satisfies the complete contract; it
never searches caller `PATH`.

When provisioning is requested, run from the plugin root:

```bash
/bin/zsh scripts/launch_mcp.zsh provision
/bin/zsh scripts/launch_mcp.zsh provision --check
/bin/zsh scripts/launch_mcp.zsh provision --tarball /absolute/path/to/jackal-v1.7.3-macos-arm64.tar.gz
```

The default MCP bridge reads the verified runtime locator. Set `JACKAL_HOME`
only to an independently verified, canonical absolute runtime directory.
