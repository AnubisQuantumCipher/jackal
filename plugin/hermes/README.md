# JACKAL Hermes plugin — proof-carrying range, Gaussian, composed-integral, and pure-ℚ transcendental bounds

A load-bearing Hermes / MCP-style plugin exposing **thirty-four tools** —
eleven proof-carrying formal tools, twenty-one honest weaker-lane adapters
(status passthrough, never inflated), and the two v1.6.0 claim-kernel
front doors (`jackal_claim`, `jackal_verify_bundle`).

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

## Invocation modes

The plugin ships one Python entry-point (`plugin/hermes/server.py`) with
three interchangeable frontends — pick the one your Hermes runtime uses:

* `plugin/hermes/jackal_hermes stdio` — line-delimited JSON-RPC 2.0
  over stdin/stdout (the MCP transport most Hermes runtimes speak).
* `plugin/hermes/jackal_hermes call <tool> <json-args>` — one-shot
  call, prints the JSON reply to stdout.
* `plugin/hermes/jackal_hermes http --port 8181` — tiny HTTP server
  wrapping the same thirty-four tools (POST `/tools/<name>` with a JSON body).

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
