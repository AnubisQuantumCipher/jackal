# JACKAL Hermes plugin — proof-carrying range, Gaussian, and pure-Q sqrt/exp bounds

A load-bearing Hermes / MCP-style plugin exposing **twelve tools** — five
proof-carrying formal tools and seven honest weaker-lane adapters
(status passthrough, never inflated).

## Formal (checker-attested) tools

| Tool | Effect |
|---|---|
| `jackal_range_bound` | Emits a `jackal-formal-receipt-v1` JSON receipt with the certificate embedded, or a stable refusal class.  Routes through the pinned `jackal-native` evaluator + `jackal_cert_check`. |
| `jackal_gaussian_integral` | Accepts only canonical `exp(-A*(x-mu)^2)` requests in the theorem-covered fragment, emits a zero-libm formal receipt, and re-runs the pinned Gaussian checker before returning it. |
| `jackal_sqrt_rat_bound` (v1.4.0) | Emits a pure-ℚ formal-bounded enclosure of `sqrt(x)` on a canonical rational interval.  Producer `tools/sqrt_rat_producer.py` is untrusted; the compiled Lean-proved `jackal_cert_check` validates a rational Newton square bracket.  **NO libm on the proof-decision path.** Admits ONLY the exact form `sqrt(x)`. |
| `jackal_exp_rat_bound` (v1.4.1) | Emits a pure-ℚ formal-bounded enclosure of `exp(x)` on `[lo, hi]` with `lo >= 0`.  Producer `tools/exp_rat_producer.py` is untrusted (uses exact `fractions.Fraction`, never `math.exp`); the compiled Lean-proved `jackal_cert_check` validates a rational Taylor partial + certified remainder.  **NO libm on the proof-decision path.** Admits ONLY the exact form `exp(x)`. |
| `jackal_verify_receipt` | Selects and re-runs the matching pinned range or Gaussian checker over an embedded `jackal-formal-receipt-v1` certificate; returns `verified` or a stable refusal class.  Dispatches on the receipt's `variant` field so `sqrt_rat` and `exp_rat` receipts round-trip verbatim (v1.4.2). |

The `sqrt_rat` and `exp_rat` tools now return a full `jackal-formal-receipt-v1`
envelope (with `variant = "sqrt_rat"` or `"exp_rat"`) that
`jackal_verify_receipt` re-executes end-to-end — the standalone Python
producer's SHA-256 fills the `evaluator_sha256`/`producer_sha256` slot,
`source_anb_sha256` is `null` (the engine is not on the proof-decision
path), and the fragment lock restricts `admitted_operators` to
`{sqrt}` / `{exp}` (plus the `var` leaf).  Downstream can archive the
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
| `jackal_integrate_bound` | `integrate-bound` — certified interval enclosure (`bounded`; NOT formal, conditional on the stated f64/libm rounding model) |
| `jackal_solve` | `solve` — bisection root with residual + conditioning (`estimated`) |

Every weaker-lane row derives its epistemic class VERBATIM from the
`release/coverage/formal_coverage_inventory.json` row for that lane.
`formal-*` is structurally impossible on these tools.  The engine's own
printed `status=` line must equal the inventory row; divergence refuses
with `plugin-lane-status-divergence` rather than picking one.

`jackal_exact` additionally replays the restricted rational AST through an
independent stdlib `Fraction` implementation and refuses with
`exact-replay-divergence` if the two exact results differ. This is an
independent implementation check, not a Lean proof; that distinction is
carried in the returned `exact_replay` object and non-claims.

## Invocation modes

The plugin ships one Python entry-point (`plugin/hermes/server.py`) with
three interchangeable frontends — pick the one your Hermes runtime uses:

* `plugin/hermes/jackal_hermes stdio` — line-delimited JSON-RPC 2.0
  over stdin/stdout (the MCP transport most Hermes runtimes speak).
* `plugin/hermes/jackal_hermes call <tool> <json-args>` — one-shot
  call, prints the JSON reply to stdout.
* `plugin/hermes/jackal_hermes http --port 8181` — tiny HTTP server
  wrapping the same twelve tools (POST `/tools/<name>` with a JSON body).

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
* `evaluator-domain-singularity` denominator interval contains zero
* `evaluator-unsupported-fragment` operator is outside the formal fragment
* `evaluator-unbound-variable`  formal request contains an unbound variable
* `evaluator-budget`            declared compute budget was exhausted
* `exact-replay-parser`         independent replay could not parse the exact witness
* `exact-replay-fragment`       independent replay hit an unsupported AST form
* `exact-replay-domain`         independent replay found exact division by zero
* `exact-replay-budget`         independent replay exceeded its exponent guard
* `exact-replay-missing`        engine emitted no `exact=` field for `jackal_exact`
* `exact-replay-divergence`     exact engine and independent replay disagree
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

    plugin/hermes/jackal_hermes call jackal_verify_receipt \
        "$(< /tmp/formal-receipt.json)"
    # -> {"status":"verified", "checker_verdict":"ACCEPT", ...}
