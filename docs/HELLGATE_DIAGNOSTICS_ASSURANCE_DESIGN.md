# HELLGATE diagnostic and transfer assurance design

Status: implemented and locally replayed in the additive Codex plugin
worktree; this is not a release-qualification statement.

## Objective

Extend the fixed `hellgate-v1` replay without changing its problem, Barta
theorem, top-level `bounded` status, or refusal behavior.  The extension must
answer two different questions without conflating them:

1. What can the exact-rational checker enclose about the normalized certificate
   trial `phi`?
2. What, if anything, can be transferred from that trial to the true positive
   normalized ground state `u0`?

The existing eigenvalue enclosure remains the primary result.  New fields are
additive and are rejected at startup if the same identity-pinned checker cannot
recompute them.

## Trial diagnostics

For every interior polynomial piece the checker already proves a uniform
enclosure

```
abs(exp(q(s)) - p(s)) <= eta,  0 <= s <= 1.
```

The diagnostic extension shall:

- convert the power-basis density polynomial to exact Bernstein coefficients;
- refuse unless `p - eta` is pointwise positive on every piece;
- integrate exact polynomial lower and upper bounds for `exp(q)`, `exp(2*q)`,
  `x^k exp(q)`, and `q'(x)^2 exp(q)`;
- enclose all omitted half-line tails with the already checked decreasing
  logarithmic derivative and exact exponential-moment formulae;
- divide only by the positive exact-rational normalization enclosure;
- return intervals for the trial quartic norm, moments 2/4/6, kinetic energy,
  energy functional, energy/eigenvalue-identity residual, and virial residual.

Every one of these fields is about `phi`, not `u0`.  The result must carry a
subject identifier and non-claims that make this distinction machine-visible.

## Ground-state quartic-norm transfer

Write `rho_phi = phi^2` and `rho_0 = u0^2`.  On mass-one positive densities,

```
F(rho) = epsilon^2/4 * integral(rho'^2/rho)
         + integral(V rho) + lambda/2 * integral(rho^2)
```

is `lambda`-strongly convex in `L2`: the Fisher term is convex, the potential
term is linear, and the final term supplies the strong-convexity modulus.  Its
first variation at `rho_phi` is the nonlinear quotient `R_phi`.

If the checker proves `abs(R_phi - c) <= delta` globally, normalization gives
`integral(rho_phi-rho_0)=0`, and strong convexity plus
`norm(rho_phi-rho_0, L1) <= 2` gives

```
norm(rho_phi-rho_0, L2)^2 <= 4*delta/lambda.
```

The checker shall enclose the square root by exact integer/rational arithmetic
and transfer the trial `L2`-norm interval to

```
(max(0, norm(rho_phi, L2) - d))^2
  <= integral(u0^4)
  <= (norm(rho_phi, L2) + d)^2.
```

This transfer does not enclose polynomial moments, the lambda derivative, the
Bogoliubov spectrum, or the tunnelling split.  Those residuals remain explicit.

## SPARK boundary

The SPARK component is deliberately smaller than the mathematical checker. It
implements a total fixed-scale nonnegative interval decision kernel with
requirements `JCK-INT-001` through `JCK-INT-004`. The contracts cover exact
ordered width, midpoint/ceiling-radius endpoint coverage, strict admission
equivalence, deterministic rejection precedence, accepted derived outputs, and
zeroed rejection outputs over every value of the declared public input types.
The level-3 gate refuses warnings, unproved checks, justified checks, a skipped
unit, `pragma Assume`, or `pragma Annotate`.

SPARK establishes absence of run-time errors and the stated arithmetic
postconditions for this component.  It does not prove:

- the nonlinear Barta theorem;
- the strong-convexity transfer theorem;
- Python-to-SPARK refinement or parser correctness;
- source-to-object equivalence;
- compiler, run-time, floating-point, or physical-model qualification.

The SPARK executable is a repository-side independent proof/test artifact.  It
is not inserted into the cross-platform MCP startup path until separately
packaged, identity-pinned binaries and source-to-input binding are designed.

## Acceptance gates

- The original compressed certificate remains byte-identical.
- Existing eigenvalue endpoints remain byte-identical.
- Coherently repinned mutations of density, tail, normalization, parity,
  continuity, or non-claims refuse.
- Trial diagnostic intervals are ordered and contain direct high-precision
  producer values used only as test oracles.
- The energy-identity and virial residual intervals contain zero and satisfy
  their declared exact-rational width gates.
- The transferred ground-state quartic interval contains the trial quartic
  interval enlarged by the proved density-distance bound.
- The full plugin suite, plugin identity gate, capability drift gate, and live
  acceptance remain green.
- The SPARK proof gate and runtime boundary tests both pass.

## Reproduction commands

```sh
python3 -B -m unittest tests.codex_plugin.test_hellgate -v
python3 -B -m unittest tests.codex_plugin.test_spark_interval -v
python3 -B -m unittest discover -s tests/codex_plugin -v
python3 -B plugins/jackel/scripts/verify_plugin.py
python3 -B tools/capability_drift_gate.py
proofs/spark/hellgate_interval/prove.sh
```

`tools/hellgate_trial_oracle.py` is an explicitly untrusted mpmath
differential path. Its high-precision values must land inside the bounded
exact-rational trial intervals, but agreement never upgrades the result.
