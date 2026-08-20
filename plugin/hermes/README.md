# JACKAL Hermes plugin — proof-carrying range, Gaussian, composed-integral, and pure-ℚ transcendental bounds

A load-bearing Hermes / MCP-style plugin exposing **thirty-eight tools** —
eleven proof-carrying formal tools, twenty-one honest weaker-lane adapters
(status passthrough, never inflated), the two v1.6.0 claim-kernel
front doors (`jackal_claim`, `jackal_verify_bundle`), and four domain-pack
lanes that carry the same refusal discipline outside mathematics.

## Formal (checker-attested) tools

| Tool | Effect |
|---|---|
| `jackal_range_bound` | Emits a `jackal-formal-receipt-v1` JSON receipt with the certificate embedded, or a stable refusal class.  Routes through the pinned `jackal-native` evaluator + `jackal_cert_check`. |
| `jackal_gaussian_integral` | Accepts only canonical `exp(-A*(x-mu)^2)` requests in the theorem-covered fragment, emits a zero-libm formal receipt, and re-runs the pinned Gaussian checker before returning it. |
| `jackal_integrate_bound_cert` (v1.7.2) | Emits a `status=formal-bounded` composed definite-integral receipt (variant `int_cert`): the untrusted exact-rational producer `tools/int_cert_producer.py` mirrors the engine's adaptive subdivision and emits a `jackal-int-cert v1` certificate, and the compiled Lean-proved `jackal_int_cert_check` (checker pin `jackal-iv-bound-step-v1`) binds the exact raw expression/bounds/tolerance and re-checks the whole subdivision tree — theorem `int_cert_sound`. The request-unbound v1.7.0 epoch is revoked and cannot replay. Certified fragment: `num`/`var`/`neg`/`add`/`sub`/`mul`/`div`/`pow` (exponent 0..4096)/`sin`/`cos`/`abs` in `x`; everything else refuses. The weaker float lane `jackal_integrate_bound` stays `bounded` (see the weaker-lane table below). |
| `jackal_sqrt_rat_bound` (v1.4.0) | Emits a pure-ℚ formal-bounded enclosure of `sqrt(x)` on a canonical rational interval.  Producer `tools/sqrt_rat_producer.py` is untrusted; the compiled Lean-proved `jackal_cert_check` validates a rational Newton square bracket.  **NO libm on the proof-decision path.** Admits ONLY the exact form `sqrt(x)`. |
| `jackal_exp_rat_bound` (v1.4.1; general-sign v1.5.0) | Emits a pure-ℚ formal-bounded enclosure of `exp(x)` on ANY canonical rational interval (negative arguments via the exact reciprocal identity, §490).  Producer `tools/exp_rat_producer.py` is untrusted (uses exact `fractions.Fraction`, never `math.exp`); the compiled Lean-proved `jackal_cert_check` validates sign-aware rational Taylor bounds.  **NO libm on the proof-decision path.** Admits ONLY the exact form `exp(x)`. |
| `jackal_verify_receipt` | Selects and re-runs the matching pinned range, Gaussian, or current request-bound composed-integral (`int_cert`) checker over an embedded `jackal-formal-receipt-v1` certificate; returns `verified` or a stable refusal class. Dispatches on the receipt's `variant` and epoch so range-family archival v1.5.0 receipts remain replay-only, current v1.7.2 `int_cert` receipts re-run `jackal_int_cert_check`, and request-unbound v1.7.0 `int_cert` receipts refuse. |
| `jackal_ln_rat_bound` (v1.5.0) | Emits a pure-ℚ formal-bounded enclosure of `ln(x)` on a canonical rational interval with `0 < lo`.  Producer `tools/ln_rat_producer.py` is untrusted; the checker validates the INVERSE exponential bracket (`expUBQ(out_lo) ≤ lo`, `hi ≤ expLBQ(out_hi)`) in ℚ.  **NO libm on the proof-decision path.** Admits ONLY `ln(x)`. |
| `jackal_sin_rat_bound` (v1.5.0) | Pure-ℚ enclosure of `sin(x)` when the interval midpoint satisfies `|m| ≤ 1`: Mathlib `Real.sin_bound` midpoint Taylor + Lipschitz-1 widening, recomputed by the checker.  **NO libm.** Admits ONLY `sin(x)`. |
| `jackal_cos_rat_bound` (v1.5.0) | Pure-ℚ enclosure of `cos(x)` (same shape, `Real.cos_bound`).  **NO libm.** Admits ONLY `cos(x)`. |
| `jackal_atan_rat_bound` (v1.5.0) | Pure-ℚ enclosure of `atan(x)` on ANY canonical rational interval via cap / tan-bracket / reciprocal strategies over the Mathlib 20-digit rational π bounds.  **NO libm.** Admits ONLY `atan(x)`. |
| `jackal_tanh_rat_bound` (v1.5.0) | Pure-ℚ enclosure of the composite `1-2/(exp(2*x)+1)` — mathematically `tanh(x)` — on `|x| ≤ 20`, as an 8-node zero-libm certificate DAG.  The receipt binds the composite expression string; the tanh reading is a documented identity, never a checker claim. |

The rational-fragment tools return a full `jackal-formal-receipt-v1`
envelope (with the matching `variant` tag) that `jackal_verify_receipt`
re-executes end-to-end — the standalone Python producer's SHA-256 fills the
`evaluator_sha256`/`producer_sha256` slot, `source_anb_sha256` is `null`
(the engine is not on the proof-decision path), and the fragment lock
restricts `admitted_operators` to the variant's operator set (plus the
`var` leaf; the tanh composite admits exactly
`{exp, mul, sub, add, div, num, var}`).  Downstream can archive the
receipt, later reverify with `jackal-receipt-verify`, and the pinned
Lean-proved checker will re-execute the exact certificate bytes on the
destination machine.

## Weaker-lane adapters (never inflated)

| Tool | Lane / Class |
|---|---|
| `jackal_exact` | `rat` — exact big-rational (`exact`) |
| `jackal_evaluate` | `eval` — IEEE f64 (`estimated`) |
| `jackal_diff` | `diff` — symbolic + numeric check (`checked`) |
| `jackal_integrate` | `integrate` — fixed Simpson + Richardson (`estimated`) |
| `jackal_integrate_adaptive` | `integrate-adaptive` — adaptive Simpson (`estimated`) |
| `jackal_integrate_bound` | `integrate-bound` — certified interval enclosure (`bounded`; NOT formal, conditional on the stated f64/libm rounding model).  For a Lean-checked `formal-bounded` composed enclosure over the certified fragment, use `jackal_integrate_bound_cert` (formal table above). |
| `jackal_solve` | `solve` — bisection root with residual + conditioning (`estimated`) |
| `jackal_canon` | `canon` — canonical s-expression + SHA-256 (`exact`) |
| `jackal_poly_canon` / `jackal_poly_eq` / `jackal_poly_gcd` / `jackal_ratfunc_canon` | dense ℚ[x] canonical form / decidable identity / monic gcd / P÷Q with side condition (`exact`, `jackal-exact-cert-v1` certificate) |
| `jackal_roots_isolate` / `jackal_alg_sign` / `jackal_alg_cmp` | Sturm real-root isolation / exact sign / algebraic order decision (`exact`) |
| `jackal_xgcd` / `jackal_mod_pow` / `jackal_mod_inv` / `jackal_crt` / `jackal_divides` / `jackal_prime_cert` | number-theory kernel with Bezout / recompute / product / residue / divisor / Pratt witnesses (`exact`) |

Every weaker-lane row derives its epistemic class VERBATIM from the
`release/coverage/formal_coverage_inventory.json` row for that lane.
`formal-*` is structurally impossible on these tools.  The engine's own
printed `status=` line must equal the inventory row; divergence refuses
with `plugin-lane-status-divergence` rather than picking one.

## Claim-kernel front doors (v1.6.0, additive)

| Tool | Effect |
|---|---|
| `jackal_claim` | Compiles a structured `jackal-claim-request-v1` into a canonical, content-addressed `jackal-claim-bundle-v1` evidence graph through the deterministic policy router (subprocess-isolated, manifest-pinned `claim_router.py`).  Emits a per-step route trace naming candidate lanes and refusal reasons; `allow_fallback` defaults false and the router refuses rather than silently downgrading. |
| `jackal_verify_bundle` | Independently replays a bundle through the standalone dependency-free `claim_bundle_verify.py` under caller-pinned expectations (epoch, root proposition, policy hash, verification time, optional nonce; registries/checker/inventory pins come from `MANIFEST.sha256`).  Recomputes every canonical byte, hash, DAG property, inference rule, assurance-axis propagation, consequence-class floor, policy verdict, and the deterministic rendering.  Returns `verified` / `refused` / `indeterminate` with a stable reason class — never a bare badge. |

Both tools are additive: embedded legacy evidence (formal receipts,
exact certificates) is dispatched to the EXISTING independent verifiers
with the pinned Lean checker; no existing tool, schema, status, or
refusal class changed.

## Domain-pack lanes (jackal-domain-pack-protocol v1, additive)

Not mathematical and **not formal**: assurance ceiling `exact`, consequence
ceiling strictly below it.  Each tool is one operation declared by
`domain_packs/registry_v1.json`, invoked through the pack protocol's own route
ABI `pack-route <pack_id> <operation_id> <args...>` (byte-identical to the
direct engine command, and it buys the engine's pack-id/operation-id admission
gate for free).

| Tool | Operation | Assurance / consequence |
|---|---|---|
| `jackal_test_exists` | `programming.source.test_exists.v1` | `structural-exact` / **`informational`** — a declaration-shaped occurrence of a symbol exists at a claimed line in a file with a claimed content hash. NEVER evidence the code under test is correct, executes, is collected, or asserts anything. |
| `jackal_claim_cites_test` | `programming.source.claim_cites_test.v1` | `structural-exact` / **`informational`** — a claim sentence occurs verbatim in a document and the cited symbol is declared in the cited test. Resolution only: the cited test may check something entirely different. |
| `jackal_decision_rank` | `decision.matrix.rank.v1` | `exact` / **`decision-boundary`** — orders 2..6 labelled options by a caller-declared numeric criterion, naming selected, runner-up and exact margin. Criterion admissibility is decided by the engine against a fixed word list. |
| `jackal_decision_rank_v2` | `decision.matrix.rank.v2` | `exact` / **`decision-boundary`** — same, plus a REQUIRED unit from the closed vocabulary of `release/claim/unit_registry_v1.json` (65 canonical ids; the dimensionless `one` is excluded). Exact-token, case-sensitive: `ms` is admitted, `millisecond` and `MS` refuse `decision-unit-unknown`. |

The consequence ceiling does **not** rise with the assurance class, and each
response repeats that in `non_claims`.  A `test-exists-cert` is an exact
statement about bytes and an `informational` statement about correctness; citing
one in support of a correctness claim is the defect this lane exists to bound.

Two honest residuals, stated rather than hidden:

* **A declared unit is not a measurement.** `_v2`'s closed vocabulary forces
  the caller to name a dimension and nothing more.  A value-judgment criterion
  that survives the engine's word list is still accepted when a real unit is
  declared — `criterion=most_elegant unit=ms` ranks — and the option values
  remain caller-declared.
* **The pack surface is not manifest-pinned.** `release/MANIFEST.sha256` has no
  row for the domain-pack registry, so the registry bytes are this lane's root
  of trust.  The plugin cross-checks its own registry digest against the
  verifier's reported one and its own verifier digest against the registry's
  declared one, both from real bytes, and returns
  `registry_file_sha256` / `registry_digest_sha256` / `pack_verifier_sha256` /
  `pack_manifest_sha256` so a caller can pin them out of band.  A coordinated
  tamper of registry + verifier together is NOT excluded here.

Per call, in order: the manifest-pinned `tools/domain_pack_verify.py` runs as an
external identity-hashed subprocess and must accept the whole chain (registry
self-digest, `PACK_SCHEMA`/`PACK_SPEC` bindings, every manifest digest, every
declared ceiling against the pinned inference registry, mandatory nonclaims);
the request is bounded by the operation's own pinned arity/size limits; the
engine is routed; the printed `status=` and `consequence=` must match the
manifest's pinned ceilings; and the operation's own checker
(`tools/test_exists_verify.py` / `tools/decision_verify.py`, path AND digest
from the manifest) is re-run over the emitted certificate.  **Only an `ACCEPT`
verdict returns success.**  That last step is load-bearing: the engine validates
the canonical FORM of a caller-supplied fact, so without the rerun an agent
could read `status=structural-exact` off a certificate whose claimed line, count
or content hash is false.

## Invocation modes

The plugin ships one Python entry-point (`plugin/hermes/server.py`) with
three interchangeable frontends — pick the one your Hermes runtime uses:

* `plugin/hermes/jackal_hermes stdio` — line-delimited JSON-RPC 2.0
  over stdin/stdout (the MCP transport most Hermes runtimes speak).
* `plugin/hermes/jackal_hermes call <tool> <json-args>` — one-shot
  call, prints the JSON reply to stdout.
* `plugin/hermes/jackal_hermes http --port 8181` — tiny HTTP server
  wrapping the same thirty-eight tools (POST `/tools/<name>` with a JSON body).

## Bundle identity

The plugin binary identity IS the SHA-256 of the deterministic
concatenation of every shipped plugin file in a stable order (documented
in `plugin/hermes/tools.json` and enforced by
`plugin/hermes/bundle_hash.py`).  A recomputed bundle hash MUST equal the
value pinned in `release/MANIFEST.sha256` under `plugin_hermes` before the
plugin will accept any request.  Any drift refuses fail-closed at
startup.

## Refusal classes (stable, machine-readable)

* `plugin-bundle-mismatch`      bundle hash != pinned value
* `plugin-manifest-missing`     no plugin manifest row
* `plugin-args-schema`          bad tool arguments (shape/type)
* `plugin-operator-refused`     expression uses a non-formal operator
* `plugin-fragment`             sqrt_rat / exp_rat tool called with a non-admitted expression
* `producer-refused`            standalone producer (sqrt_rat / exp_rat) refused
* `producer-identity`           standalone producer SHA-256 != pinned value
* `producer-toctou`             standalone producer bytes changed across the call
* `evaluator-refused`           the evaluator refused (returns detail)
* `checker-rejected`            `jackal_cert_check` REJECT
* `checker-no-accept`           `jackal_cert_check` printed no ACCEPT line
* `formal-status-refused`       formal-status gate refused
* `request-*`, `cert-*`,        as raised by the shared validator
  `evaluator-*`, `checker-*`
* `receipt-*`                   as raised by the independent verifier

Domain-pack lanes, in addition (a `pack-*` class raised by the plugin from the
PINNED registry/manifest carries the same name as the engine's own class for
the same fact, because it is the same fact established from the same pin):

* `pack-surface-absent`         this distribution ships no `domain_packs/` tree
* `pack-registry-refused`       `tools/domain_pack_verify.py` did not accept
* `pack-registry-identity`      verifier and plugin read different registry bytes
* `pack-verifier-identity`      executed verifier != the registry's declared digest
* `pack-verifier-toctou`        verifier bytes changed across the call
* `pack-manifest-identity`      manifest bytes != the registry's pin
* `pack-id-unknown`             pack id absent from the verified registry
* `pack-operation-unknown`      operation id absent from the verified pack
* `pack-request-arity`          request exceeds the operation's pinned bounds
* `pack-args-shape`             plugin-layer option pairing guard (see below)
* `pack-response-shape`         engine stdout is not one certificate + metadata
* `pack-lane-status`            printed `status=` outside the pack-lane class set
* `pack-lane-status-divergence` printed class != the manifest's assurance ceiling
* `pack-consequence-divergence` printed `consequence=` != the pinned ceiling
* `pack-checker-identity`       checker SHA-256 != the manifest's pin
* `pack-checker-toctou`         checker bytes changed across the call
* `pack-refusal-unregistered`   engine refused with a class the manifest does not declare
* `prog-*`, `decision-*`        the engine's own pack refusal classes, passed through by name
* `checker-rejected`            the operation's checker printed `REFUSE <class>`

`pack-args-shape` exists because argv is flat: `options` arrives as one
`label value label value ...` string, so a label containing whitespace would
shift the pairing.  The plugin refuses that instead of silently re-pairing it,
which means a label must be a whitespace-free token on this surface.

Every refusal is a JSON object `{"status":"refused","reason":<class>,
"detail":<string>}` — never a bounded fallback, never an implicit weaker
label.

## Fresh-session smoke

    plugin/hermes/jackal_hermes call jackal_range_bound \
        '{"expression":"sin(x)","input_lo":"0","input_hi":"1"}'
    # -> {"status":"formal-bounded","receipt":{...}}

    plugin/hermes/jackal_hermes call jackal_sqrt_rat_bound \
        '{"expression":"sqrt(x)","input_lo":"2","input_hi":"3"}'
    # -> {"status":"formal-bounded","variant":"sqrt_rat",
    #     "enclosure":["353553.../250...","173205.../100..."],
    #     "checker_verdict":"ACCEPT", ...}

    plugin/hermes/jackal_hermes call jackal_exp_rat_bound \
        '{"expression":"exp(x)","input_lo":"0","input_hi":"1"}'
    # -> {"status":"formal-bounded","variant":"exp_rat",
    #     "enclosure":["1","979/360"], "checker_verdict":"ACCEPT", ...}

    plugin/hermes/jackal_hermes call jackal_gaussian_integral \
        '{"expression":"exp(-10000000000*(x-0.5000123456789)^2)","input_lo":"0","input_hi":"1","tolerance":"1/1000000000000"}'
    # -> {"status":"formal-bounded","checker_rerun":"ACCEPT","receipt":{...}}

    plugin/hermes/jackal_hermes call jackal_integrate_bound_cert \
        '{"expression":"sin(x)","input_lo":"0","input_hi":"1","tolerance":"1/100"}'
    # -> {"status":"formal-bounded","checker_rerun":"ACCEPT",
    #     "receipt":{..."variant":"int_cert"...}}

    plugin/hermes/jackal_hermes call jackal_verify_receipt \
        "$(< /tmp/formal-receipt.json)"
    # -> {"status":"verified", "checker_verdict":"ACCEPT", ...}

    plugin/hermes/jackal_hermes call jackal_test_exists \
        '{"file_path":"tests/corpus/fixtures/genuine_python_decls.py","file_sha256":"eaa70efea4ea4009e98657fcf112fc2b8fa71a55f31a9100df4bf27948d2ef19","symbol":"corpus_python_target","declaration_line":"13","declaration_count":"1"}'
    # -> {"status":"structural-exact","checker_rerun":"ACCEPT",
    #     "assurance_ceiling":"exact","consequence_ceiling":"informational",
    #     "certificate":"test-exists-cert={...}", ...}

    plugin/hermes/jackal_hermes call jackal_claim_cites_test \
        '{"doc_path":"tests/corpus/fixtures/claim_source_doc.md","doc_sha256":"41c5a28f456166c2d5b73c9e03391cbf2c438741e459893cbb34919b7db233ad","claim_text":"The fixture module declares a Python helper named corpus_python_target.","test_path":"tests/corpus/fixtures/genuine_python_decls.py","test_sha256":"eaa70efea4ea4009e98657fcf112fc2b8fa71a55f31a9100df4bf27948d2ef19","symbol":"corpus_python_target"}'
    # -> {"status":"structural-exact","checker_rerun":"ACCEPT",
    #     "consequence_ceiling":"informational", ...}

    plugin/hermes/jackal_hermes call jackal_decision_rank \
        '{"decision_id":"runtime_choice_2026_08","criterion":"latency_ms","sense":"min","options":"alpha 42 beta 77 gamma 91"}'
    # -> {"status":"exact","checker_rerun":"ACCEPT",
    #     "consequence_ceiling":"decision-boundary",
    #     "fields":{"selected":"alpha","margin":"35"}, ...}

    plugin/hermes/jackal_hermes call jackal_decision_rank_v2 \
        '{"decision_id":"runtime_choice_2026_08","criterion":"latency","unit":"ms","sense":"min","options":"alpha 42 beta 77 gamma 91"}'
    # -> {"status":"exact","checker_rerun":"ACCEPT",
    #     "fields":{"selected":"alpha","margin":"35","unit":"ms"}, ...}

    # ...and the same call with unit "millisecond":
    # -> {"status":"refused","reason":"decision-unit-unknown", ...}
