# JACKAL Hermes plugin — proof-carrying range and Gaussian bounds

A load-bearing Hermes / MCP-style plugin exposing exactly three tools:

| Tool | Effect |
|---|---|
| `jackal_range_bound` | Emits a `jackal-formal-receipt-v1` JSON receipt with the certificate embedded, or a stable refusal class. |
| `jackal_gaussian_integral` | Accepts only canonical `exp(-A*(x-mu)^2)` requests in the theorem-covered fragment, emits a zero-libm formal receipt, and re-runs the pinned Gaussian checker before returning it. |
| `jackal_verify_receipt` | Selects and re-runs the matching pinned range or Gaussian checker over an embedded certificate; returns `verified` or a stable refusal class. |

The range tool threads requests through the same pinned executables and shared
validator as `jackal-cert-release`. The Gaussian tool uses the separately pinned
untrusted producer plus `jackal_gaussian_check`, then independently rehydrates
the emitted receipt and runs that checker again before returning a result. Both
lanes use the same formal-status gate and coverage inventory. The plugin adds no
new trust root: it is a strictly narrower adapter that binds the plugin's
OWN bundle hash into the receipt's `identities.plugin_sha256` slot, and it
refuses any request whose parsed operators fall outside the declared
formal fragment.

## Invocation modes

The plugin ships one Python entry-point (`plugin/hermes/server.py`) with
three interchangeable frontends — pick the one your Hermes runtime uses:

* `plugin/hermes/jackal_hermes stdio` — line-delimited JSON-RPC 2.0
  over stdin/stdout (the MCP transport most Hermes runtimes speak).
* `plugin/hermes/jackal_hermes call <tool> <json-args>` — one-shot
  call, prints the JSON reply to stdout.
* `plugin/hermes/jackal_hermes http --port 8181` — tiny HTTP server
  wrapping the same three tools (POST `/tools/<name>` with a JSON body).

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
* `evaluator-refused`           the evaluator refused (returns detail)
* `formal-status-refused`       formal-status gate refused
* `request-*`, `cert-*`,        as raised by the shared validator
  `evaluator-*`, `checker-*`
* `receipt-*`                   as raised by the independent verifier

Every refusal is a JSON object `{"status":"refused","reason":<class>,
"detail":<string>}` — never a bounded fallback, never an implicit weaker
label.

## Fresh-session smoke

    python3 plugin/hermes/jackal_hermes call jackal_range_bound \
        '{"expression":"sin(x)","input_lo":"0","input_hi":"1"}'
    # -> {"status":"formal-bounded","receipt":{...}}

    python3 plugin/hermes/jackal_hermes call jackal_gaussian_integral \
        '{"expression":"exp(-10000000000*(x-0.5000123456789)^2)","input_lo":"0","input_hi":"1","tolerance":"1/1000000000000"}'
    # -> {"status":"formal-bounded","checker_rerun":"ACCEPT","receipt":{...}}

    python3 plugin/hermes/jackal_hermes call jackal_verify_receipt \
        "$(< /tmp/formal-receipt.json)"
    # -> {"status":"verified", "checker_verdict":"ACCEPT", ...}
