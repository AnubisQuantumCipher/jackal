# JACKAL Number Theory 1.0 — certified Diophantine workflows

Status: shipped on the additive adapter surface (ten `jackal_nt_*` tools).
Scope: this document records the design decisions, the trust architecture, the
verification map for every tool, and the boundary of what is and is not
claimed.

## Why this layer exists

The JACKAL roadmap identified structural discovery — not faster division — as
the missing capability between a high-assurance computational kernel and a
mathematics laboratory: a conjecture-and-proof pipeline that can recognize a
quadratic in disguise, compute a companion root, prove integrality and
positivity, and descend a minimal counterexample. The chosen first milestone
was **Number Theory 1.0 plus a Vieta-jumping proof schema**, with IMO 1988
Problem 6 as the flagship.

The architecture follows de Bruijn's criterion, the same separation principle
that underpins contemporary formally verified mathematics systems (Lean's
small trusted kernel; AlphaProof-style untrusted search over a trusted
checker):

- **Untrusted discovery.** Python may search creatively: trial division,
  Pollard rho, Miller-Rabin screening, Tonelli-Shanks, continued fractions,
  Vieta jumping, exhaustive residue scans. Nothing this layer computes is ever
  load-bearing.
- **Trusted verification.** Every arithmetic claim that reaches a reported
  field is verified by delegated calls into the sealed v1.7.3 runtime
  (`jackal_exact`, `jackal_divides`, `jackal_xgcd`, `jackal_prime_cert`,
  `jackal_mod_pow` — the closed `NUMBER_THEORY_KERNEL_TOOLS` allowlist).
  The adapter refuses any other delegation target.

A refusal is an answer. When discovery exhausts a budget or a kernel check
fails, the tool refuses with a named reason; it never substitutes local
arithmetic and never weakens the lane to obtain *some* number.

## Tool-by-tool verification map

| Tool | Discovery (untrusted) | Kernel-verified claims |
|---|---|---|
| `jackal_nt_factor` | trial division, Pollard rho | each prime factor carries a sealed Pratt certificate; `n = sign * prod(p^e)` recomposition is a kernel zero |
| `jackal_nt_lcm` | none | Bezout gcd certificate; `gcd*lcm = |a*b|` kernel zero; `a | lcm` and `b | lcm` kernel verdicts |
| `jackal_nt_valuation` | repeated division | `p` prime by sealed certificate; `n = p^v * cofactor` by kernel-exact division; `p` does not divide cofactor by kernel verdict |
| `jackal_nt_is_square` | `isqrt` | `root^2 = n` kernel zero, or strict sandwich `floor^2 < n < (floor+1)^2` by kernel sign checks |
| `jackal_nt_congruence` | local residues | verdict is the kernel divisibility decision on `a-b`; each residue kernel-verified congruent and in range |
| `jackal_nt_sqrt_mod` | Tonelli-Shanks | `p` prime by sealed certificate; each root's `r^2 = a (mod p)` and the Euler criterion value are sealed `mod-pow` certificates |
| `jackal_nt_linear_diophantine` | none | Bezout certificate; `a*x0+b*y0 = c` kernel zero; homogeneous step kernel zero; insolvability = kernel gcd non-divisibility |
| `jackal_nt_pell` | continued fractions | `x^2 - d*y^2 = 1` kernel zero; `d` nonsquare sandwich kernel-checked; minimality exhaustively kernel-checked for small `y`, otherwise labeled `checked` |
| `jackal_nt_mod_obstruction` | none (exhaustive) | every residue-class value computed by `jackal_exact` and its divisibility decided by `jackal_divides`; nothing sampled |
| `jackal_nt_vieta_descent` | Vieta jumping | initial divisibility, quotient `k`, every companion root, every Vieta product identity `A*c = B^2 - k`, every state invariant `A^2+B^2 = k(AB+1)`, strict descent gaps, and the terminal `k = root^2` are all kernel zeros/verdicts |

## The flagship: IMO 1988 Problem 6 as a schema instance

`jackal_nt_vieta_descent` certifies, for a supplied positive pair `(a, b)`
with `(a*b+1) | (a^2+b^2)`, the full descent

```
(112, 30) -> (30, 8) -> (8, 2) -> (2, 0)      k = 4 = 2^2
```

with every transition kernel-checked. The terminal state alone proves that the
quotient is a perfect square for this instance; the chain additionally
exhibits every intermediate certified solution sharing the same `k`. The false
pair `(8, 57)` is decided `not-a-solution` by the kernel's divisibility
verdict rather than by wrapper arithmetic.

Non-claim, stated on every result: one descent certifies the supplied instance
and its chain; the universal theorem over all solutions is a proof schema,
not claimed by any single computation.

## Statuses and honesty rules

- Top-level `status=exact` is used only when every load-bearing claim was
  kernel-decided. `formal` is always `False`: this surface is identity-pinned
  and tested, not Lean-proved.
- `jackal_nt_pell` grades fundamentality: `field_status.fundamental` is
  `exact` only after exhaustive kernel-checked minimality (small `y`), else
  `checked` with an explicit non-claim.
- `consequence_ceiling` is `informational` for the whole surface. A certified
  factorization is still not a safety argument.
- Refusal reasons are stable strings: `args`, `int-budget`, `factor-budget`,
  `factor-cert-budget`, `valuation-not-prime`, `sqrt-mod-not-prime`,
  `obstruction-budget`, `obstruction-fragment`, `pell-domain`, `pell-budget`,
  `descent-budget`, `nt-internal`, `kernel-refused:<reason>`,
  `kernel-unavailable`, `kernel-timeout`, `kernel-error`, `tool-unknown`.
- `delegated_to` records every sealed-runtime call as reproducibility
  metadata; it is not itself a certificate.

## Budgets (fail closed, never guess)

- integer tokens: 512 digits (`MAX_NT_INT_DIGITS`);
- factorization: 400k Pollard iterations, 64 distinct primes, prime
  certificates bounded by the sealed 10^60 Pratt budget;
- valuation exponent: 2^20;
- obstruction: modulus <= 128 and <= 256 kernel-decided residue classes;
- Pell: d <= 14 digits, period <= 200k, solution <= 2000 digits, exhaustive
  minimality only for y <= 32;
- descent: <= 128 steps.

## Where this sits in the surface contracts

- Module: `plugins/jackel/mcp/numbertheory.py`, identity-pinned in
  `plugins/jackel/PLUGIN_IDENTITY.sha256` and loaded only after digest
  verification.
- Adapter: `NUMBER_THEORY_TOOL_NAMES` / `NUMBER_THEORY_KERNEL_TOOLS` /
  `EXPECTED_NUMBER_THEORY_TOOL_COUNT = 10`; unified surface is 68 tools
  (41 sealed + 7 measurement + 3 advanced + 7 STEM + 10 number theory).
- Gates: `tools/capability_drift_gate.py` binds the group constants, the
  identity roster, and the doc surfaces; `tests/codex_plugin/test_numbertheory.py`
  carries the behavior battery; `evals/mcp/jackal_number_theory_v1.xml` carries
  the benchmark scenarios.
- The sealed 41-tool runtime is unchanged: this layer adds no second
  calculator and no new arithmetic authority.

## Roadmap position and non-goals

This ships the roadmap's stage-2/stage-3 slice: a benchmark-carrying
number-theory layer plus reusable proof schemas (Vieta jumping / descent,
modular obstruction, gcd obstruction, Euler witnesses). Explicit non-goals of
this revision: no general Diophantine decision procedure, no Lean/Mathlib
export bridge (stage 4), no claim that any schema instance proves a universal
theorem, and no relaxation of the sealed runtime's own budgets.
