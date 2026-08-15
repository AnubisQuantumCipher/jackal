# Trust-surface patch proposal: proof-carrying Gaussian integration

Status: **AUTHORIZED 2026-08-15 — implementation in progress; not sealed until all gates pass**

## Finding

The current `integrate-bound` path is a conditional floating-point/libm enclosure whose implementation is tested but not mechanically checked. The Lean tree proves the real Taylor-2/Taylor-4 enclosure theorems and symbolic-derivative facts, but `proofs/lean/JackalIv/Ledger.lean` still records the composition of the shipped `bound_step` acceptance policy as open. The released formal range path intentionally refuses `exp`.

No finite calculator can produce a formal result for every arbitrary expression. The strongest sound contract is:

> Every released formal result is accepted by a theorem-covered checker for the exact request; every unsupported or unchecked strong request refuses without downgrade.

Literal unqualified “universal correctness for anything thrown at it” is rejected as an impossible acceptance condition.

## Proposed public behavior

1. Add a distinct `formal-bounded` assurance to `jackal_integrate`; do **not** relabel or silently upgrade the existing `bounded` lane.
2. Admit one initial exact family:

   `exp(-A*(x-mu)^2)`

   where `A`, `mu`, the integration bounds, and tolerance are canonical rationals; `A = s^2` for a checker-verified positive rational `s`; and the transformed interval contains the checker’s certified central interval.
3. Release `formal-bounded` only when the new checker accepts the exact request and computed enclosure and the enclosure width is no greater than the requested tolerance.
4. Refuse every other `formal-bounded` integration request. Existing estimate and conditional bounded lanes retain their present weaker labels and non-claims.

This initial family includes both documented challenges:

- `A=10^8`, `mu=0.500012345`, `[0,1]`;
- `A=10^10`, `mu=0.5000123456789`, `[0,1]`, requested width `10^-12`.

## Proposed proof/checker construction

### Exact normalization

The checker parses a byte-canonical request envelope and accepts only the exact Gaussian grammar above. It derives `A`, `mu`, `a`, `b`, and `tol`; verifies canonical rational encodings, `a < b`, `tol > 0`, `s > 0`, and `s^2 = A`; and rejects duplicate fields, trailing bytes, alternate spellings, malformed framing, or request/certificate mismatch.

### Change of variables

Mechanize

`integral_a^b exp(-A*(x-mu)^2) dx = (1/s) * integral_{s(a-mu)}^{s(b-mu)} exp(-t^2) dt`

for `A=s^2`, `s>0`.

### Pure-rational exponential enclosure

Do not use platform `exp` or the existing `LibmModel` on the formal lane. For rational `z >= 0`, check exact rational partial sums

`S_n(z) = sum_{k=0}^{n-1} z^k/k!`.

Use the machine-proved inequalities:

- `S_n(z) <= exp(z)`;
- when `z/(n+1) <= 1/2`,
  `exp(z) <= S_n(z) + 2*z^n/n!` (the real specialization of
  Mathlib's proved `Complex.exp_bound'`);
- reciprocation gives a rational enclosure of `exp(-z)`.

Every arithmetic operation in this checker path is exact integer/rational arithmetic.

### Full Gaussian integral and finite-domain subtraction

The accepted implementation uses Mathlib's proved identity

`integral_R exp(-t^2) dt = sqrt(pi)`

instead of a larger Taylor-cell certificate. The checker binds compact exact-rational lower and upper bounds for `sqrt(pi)`; Lean proves those bounds from Mathlib's rational `pi` bounds. The finite requested interval is enclosed by subtracting two proved tails from the full integral for the lower bound and using the full integral for the upper bound. This is a proof-mechanism refinement, not a broader acceptance condition: the grammar, exact-square scale, covered-domain requirement, zero-libm policy, and fail-closed behavior are unchanged.

### Tails

Mechanize, for `T>0`,

`0 <= integral_T^infinity exp(-t^2) dt <= exp(-T^2)/(2T)`

and its left-tail symmetric form. Bound finite outer pieces by these infinite tails. The checker computes the tail upper bound from the same pure-rational exponential certificate.

### Executable checker and theorem

Add a total checker and codec with a theorem of the shape:

`gaussianIntegralCheck request certificate = true ->`
`request.lowerResult <= integral request.integrand <= request.upperResult`

Expected axiom inventory: only Lean/Mathlib standard logical axioms already disclosed by the project; no `sorry`, no project axiom, no `native_decide` trust shortcut, no `@[implemented_by]` on the checker path, and no floating-point/libm assumption.

Compile a separate pinned executable checker. Treat the evaluator/certificate producer as untrusted.

## Receipt and release boundary

Create a versioned formal-integration receipt carrying and mutually binding:

- exact raw/canonical request and operation;
- normalized Gaussian parameters;
- result enclosure and tolerance;
- complete compact certificate and certificate digest;
- theorem and coverage-row IDs;
- checker `ACCEPT` result;
- Lean/checker/evaluator/package/plugin identities;
- assumptions, TCB, and non-claims;
- release epoch and outer digest.

Independent receipt verification must rehydrate the certificate and rerun the pinned checker. Recomputing the outer digest must not bypass semantic, coverage, theorem, status, request, result, or identity checks.

## Coverage row

Add one formal row, initially:

`integrate.gaussian-exp-square.v1`

All other integration operator/family rows remain `REFUSED` for `formal-bounded`. The existing conditional `bounded` coverage remains separate and must never satisfy this formal row.

## Required RED controls before production code

1. The exact `A=10^10` challenge requests `formal-bounded`; the initial tracer test failed before the family existed and now passes only through the pinned checker.
2. A forged `formal-bounded` integration receipt with recomputed outer digest is rejected.
3. A Gaussian certificate with one changed bound is rejected.
4. Swapped bounds, changed tolerance, changed `mu`, changed `A`, changed `n/T/pi bounds`, wrong checker, wrong theorem, wrong coverage row, trailing bytes, and noncanonical rationals are rejected.
5. `exp(x)`, a non-square `A`, a domain not covering the certified core, and a non-Gaussian integrand refuse without bounded fallback.
6. Empty/zero-work certificates and stale-success artifacts fail.

Then implement one vertical RED→GREEN slice at a time.

## Verification and release finish line

- Lean build and explicit axiom audit;
- positive checker corpus and semantic negative controls with nonzero counts;
- A→B→A request/result/certificate/checker/theorem/coverage mutations;
- exact extreme Gaussian acceptance at width `<=10^-12`;
- independent high-precision oracle containment as regression evidence only;
- deterministic certificate and byte-identical package rebuilds;
- clean-extraction package smoke;
- plugin unit/poison/manifest/release audit;
- installed-plugin byte equality and Plugin Doctor;
- genuinely fresh Hermes session producing `formal-bounded` and independently verifying the carried receipt;
- unsupported formal requests observed refusing without downgrade.

Checkpoint commits/pushes are non-final. Tags/releases/install promotion occur only after all gates pass on the final exact heads.

## Feasibility probe (not proof)

A checker-matched exact-`Fraction` producer using `T=6`, exponential degree `n=96`, proved rational `sqrt(pi)` bounds, and the full-minus-tails theorem produces width

`100387/1000000000000000000000000` (about `1.00387e-19`)

for `s=100000` (`A=10^10`), below the requested `10^-12`. The numerical width is feasibility evidence; formal soundness comes only from `gaussian_integral_check_sound` and authoritative checker rerun.

## Resulting honest claim

If every gate above passes, the strongest claim is:

> Formally mechanized for checker-accepted requests in the declared Gaussian integration fragment, under the recorded Lean/checker/runtime/packaging TCB; unsupported formal integration requests refuse, and weaker lanes retain explicit non-claims.

It is not unrestricted universal correctness, not a proof of arbitrary `exp` expressions, and not zero-TCB mathematics.
