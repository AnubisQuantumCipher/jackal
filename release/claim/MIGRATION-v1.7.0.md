# JACKAL v1.7.0 — migration guide (33 tools → 34 tools)

v1.7.0 is the certified bound_step composition release: the intact
v1.6.0 33-tool surface plus one additive proof-carrying formal tool
(`jackal_integrate_bound_cert`), for exactly 34 tools — eleven formal,
twenty-one weaker-lane adapters, and the two claim-kernel front doors.

## Where you might be starting from

| Installed surface | Epoch | Tools | Migration effect |
|---|---|---|---|
| Hermes plugin pinned to a v1.4.2-era release | v1.4.2 | 10 | strict superset; no caller breaks |
| Hermes plugin/skill describing v1.5.0 | v1.5.0 | 31 | strict superset; no caller breaks |
| Hermes plugin/skill describing v1.6.0 | v1.6.0 | 33 | strict superset; no caller breaks |
| This release | v1.7.0 | 34 | current |

Each earlier surface is a strict subset of the next — mechanically
locked by `release/compat/v150_floor.json` + `tools/compat_floor.py
--check` (tool names, required/optional arguments, return keys, engine
commands, gate list, coverage rows, epistemic classes, and wrappers are
additive-only).

## What migration to v1.7.0 delivers

- All 33 v1.6.0 tools, byte-frozen at the schema level: unchanged
  names/arguments/returns/statuses.
- One additive formal tool: `jackal_integrate_bound_cert` — a certified
  composed definite-integral enclosure.  The untrusted exact-rational
  producer mirrors the engine's adaptive subdivision and emits a
  `jackal-int-cert v1` certificate; the compiled Lean-proved checker
  `jackal_int_cert_check` (checker pin `jackal-iv-bound-step-v1`)
  re-checks the whole subdivision tree under theorem `int_cert_sound`,
  and the resulting `jackal-formal-receipt-v1` receipt (variant
  `int_cert`) is `status=formal-bounded`.
- A matching release wrapper:
  `./jackal-int-cert-release "<expr>" <lo> <hi> <tol> <receipt.json>`.
- `jackal_verify_receipt` additionally dispatches `int_cert` receipts to
  the pinned `jackal_int_cert_check`; range/Gaussian/rational-fragment
  receipt verification is unchanged, and previously emitted receipts
  keep verifying under their original expected epoch/request.

## New pinned identities (from `release/MANIFEST.sha256`)

| Row | Path | SHA-256 |
|---|---|---|
| `int-cert-producer` | `tools/int_cert_producer.py` | `b4240fdac3c77b2abd751595303b2b3a0e4bebd492b2ae57fa5ccf052cd50af4` |
| `int-cert-checker` | `jackal_int_cert_check` | `c858e3bfc0ff2809a808170caabbf090077cb54996e76f065dbcd26ffb067d49` |
| `int-cert-proof-identity` | `release/evidence/int_cert_proof_identity.json` | `f0323e312d8b0e05a7200546fd819fc191d5f146d359bb14efec5b1575f16844` |
| `int-cert-proof-digest` | — | `01d0641e94ce53feb62a5b9667777fe6c526318491f4f3ea157e84d3e90b953e` |

The engine identities are untouched: `jackal_calc.anb` and
`jackal-native` carry the same pinned hashes as the v1.6.0 seal
(`source` and `evaluator` rows in `MANIFEST.sha256`).

## Old → new guidance

Users of `jackal_integrate_bound` (or the `integrate-bound` CLI lane)
who want a proof-carrying enclosure should call
`jackal_integrate_bound_cert` (or `./jackal-int-cert-release`) instead:

- The certified fragment is
  `num`/`var`/`neg`/`add`/`sub`/`mul`/`div`/`pow` (exponent 0..4096)/
  `sin`/`cos`/`abs` in the single variable `x`.  Everything else
  refuses with a stable class — never a bounded fallback.
- `jackal_integrate_bound` itself is unchanged: same arguments, same
  outputs, same `status=bounded`, still conditional on the stated
  f64/libm rounding model, still never labeled formal.  Callers that
  need the wider float fragment keep using it and keep getting the
  honest weaker label.

## What did NOT change

- Float-lane semantics: `integrate-bound` / `jackal_integrate_bound`
  print byte-identical outputs and the same `bounded` class; the float
  lane never inherits the formal status.
- The 33 existing tools are byte-frozen at the schema level — no name,
  argument, return key, status, or refusal class changed.
- The compat floor: `release/compat/v150_floor.json` +
  `tools/compat_floor.py --check` still enforce the additive-only lock;
  v1.7.0 only extends the surface.
- No existing verifier acceptance rule changed; verifier
  `PASS`/`verified` semantics are identical to v1.6.0 for all legacy
  lanes.

## Hermes plugin migration

1. Install/upgrade the plugin from its own repository release, pinned to
   the exact full release commit (see
   `AnubisQuantumCipher/hermes-jackal-verified` release notes for the
   command).
2. Reconcile any local edits in an existing plugin checkout before
   overwriting.
3. **Start a NEW Hermes session after installation** — tool schemas are
   loaded once per session, and the plugin startup gate hashes its
   bundle once per process; a live session keeps the old epoch until
   restarted.
4. In the fresh session the registered inventory is exactly 34 tools;
   `jackal_integrate_bound_cert` appears alongside every legacy tool.

## Residual non-claims

- **Producer fidelity is tested, not proved.**  The trust anchor is the
  compiled proved checker, which recomputes the entire certificate; an
  unfaithful producer can only cause refusal, never a wrong accepted
  enclosure — but the producer's faithfulness to the engine's
  subdivision is campaign-tested, not mechanized.
- **Source→native refinement remains OPEN.**  The Lean theorem covers
  the certificate model, not the Anubis-to-native compilation of the
  engine; the engine's printed `implementation-tested-not-mechanized`
  residual stays accurate.
- **No universal soundness claim.**  `int_cert_sound` covers exactly the
  certified fragment above; the claim kernel's own hull arithmetic still
  caps at `mathematical=bounded`, and `int_cert` receipts enter claim
  graphs at `formal-bounded` only as direct receipt evidence.
