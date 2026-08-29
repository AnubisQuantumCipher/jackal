# JACKAL STEM Engineering — certified workflows across mathematics and engineering

Status: shipped on the additive adapter surface (six tools in
`plugins/jackel/mcp/engineering.py`), alongside Number Theory 1.0
(`docs/NUMBER_THEORY_1_0_DESIGN.md`). Scope: design decisions, the trust
architecture, the verification map, and the claim boundary for the
engineering layer that extends JACKAL toward full STEM coverage.

## Trust architecture

Identical to the number-theory layer (de Bruijn's criterion): the wrapper may
select closed workflows, parse structure, and search, but every reported
arithmetic claim is verified by delegated calls into the sealed v1.7.3
runtime through the closed `ENGINEERING_KERNEL_TOOLS` allowlist
(`jackal_exact`, `jackal_poly_canon`, `jackal_poly_gcd`,
`jackal_roots_isolate`, `jackal_sqrt_rat_bound`, `jackal_ln_rat_bound`,
`jackal_atan_rat_bound`). Physical models additionally declare their
assumptions and are capped at the `advisory` consequence ceiling; pure
mathematics stays `informational`.

## Tool-by-tool verification map

| Tool | Status | Kernel-verified content |
|---|---|---|
| `jackal_complex` | exact | every Gaussian-rational component from `jackal_exact`; modulus squared exact; modulus enclosure is a Lean-checked `sqrt` receipt |
| `jackal_poly_solve` | exact | kernel-canonical coefficients; every rational root evaluates to the kernel zero and is kernel-checked inside its isolating interval; Sturm certificate for the distinct-real-root count and intervals; squarefreeness via kernel gcd with the power-rule derivative |
| `jackal_routh_stability` | exact | every Routh entry is a delegated kernel-exact rational; signs are read from kernel canonicals; zero pivots refuse (`routh-singular`) instead of epsilon heuristics |
| `jackal_circuit` | model-based (advisory) | series/parallel/divider/time-constant/power fields kernel-exact; resonant omega and RLC impedance magnitude carry Lean-checked `sqrt` enclosures; phase carries a Lean-checked `atan` enclosure |
| `jackal_beam` | model-based (advisory) | closed-form Euler-Bernoulli deflection/moment/reactions computed kernel-exact inside the declared model |
| `jackal_chem` | model-based (advisory) | molar masses are kernel-exact sums over the declared IUPAC 2021 table; the gas constant is kernel-computed from the SI-exact defining constants k and N_A; the pH interval composes two Lean-checked `ln` receipts through kernel-exact endpoint arithmetic and is labeled `bounded`, never `formal-bounded` |

## Honesty rules specific to this layer

- **Graded solve claims.** `jackal_poly_solve` claims an unmatched isolating
  interval is irrational ONLY when the rational-root enumeration completed
  within budget over kernel-verified scaled integer coefficients; otherwise it
  reports `rational_root_search=incomplete-budget` and withholds the claim.
  The non-real count is emitted only for kernel-certified squarefree
  polynomials, where the fundamental theorem of algebra applies to distinct
  roots.
- **Named inference rules.** The Routh-Hurwitz criterion, the power-rule
  derivative construction, the rational root theorem, reduction rules, and
  monotone interval division are named in `non_claims` wherever they carry a
  step; kernel facts and schema rules are never blurred.
- **Enclosure composition is `bounded`.** Dividing one Lean-checked enclosure
  by another (pH) uses kernel-exact endpoint arithmetic plus a monotonicity
  rule; the composed interval is honest `bounded`, and the underlying
  formal-bounded receipts ride along unmodified.
- **Physical models never certify designs.** Beam and circuit results state
  Euler-Bernoulli/ideal-lumped assumptions, exclude tolerances, buckling,
  parasitics, and safety factors, and cap at `advisory`.
- **Declared data stays declared.** Atomic weights cite the IUPAC 2021 table
  (conventional values for interval elements); component values, loads, and
  concentrations are caller-declared inputs, never measurements.
- **`pi` has no admitted lane**, so cyclic frequency f0 = omega/(2*pi) is
  explicitly not reported rather than approximated.

## Budgets (fail closed)

- tokens 512 bytes; built expressions 8 KiB; complex exponent <= 64;
- solve degree <= 32; rational-candidate enumeration <= 512 divisor pairs over
  constants <= 10^12;
- Routh degree <= 24; circuit arrays <= 32 values;
- formulas <= 256 bytes, nesting <= 8, group counts <= 9999, atoms <= 10^6.

## Refusal reasons

`args`, `domain`, `operation-unknown`, `expression-budget`, `poly-zero`,
`poly-budget`, `routh-degree`, `routh-budget`, `routh-singular`,
`chem-formula`, `chem-element-unknown`, `engineering-internal`,
`kernel-refused:<reason>`, `kernel-unavailable`, `kernel-timeout`,
`kernel-error`, `tool-unknown`, `engineering-error`.

## Surface contracts

- Module identity-pinned in `plugins/jackel/PLUGIN_IDENTITY.sha256`; loaded
  only after digest verification; group constants
  (`ENGINEERING_TOOL_NAMES`, `EXPECTED_ENGINEERING_TOOL_COUNT = 6`) bound by
  `tools/capability_drift_gate.py`.
- Unified adapter surface: 74 tools (41 sealed + 7 measurement + 3 advanced +
  7 STEM + 10 number theory + 6 engineering). The sealed runtime is unchanged.
- Behavior battery: `tests/codex_plugin/test_engineering.py` (sympy is used
  only as a test-side oracle, never in shipped code); benchmark scenarios:
  `evals/mcp/jackal_engineering_v1.xml`.
