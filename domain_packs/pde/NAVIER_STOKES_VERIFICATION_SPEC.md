# JACKAL Navier--Stokes v1 Fail-Closed Verification Specification

Status: **UNSOLVED / PARTIAL INSTRUMENT**. This pack checks bounded evidence
and conditional theorem applicability. It does not solve the three-dimensional
Navier--Stokes existence and smoothness problem.

## 1. Governing system and admitted scope

The admitted equation has unit density, exactly zero external force, and exact
positive rational kinematic viscosity `nu`:

```text
partial_t u - nu Delta u + (u dot grad)u + grad p = 0
div u = 0
u(0) = u0
```

The only domain identifiers are `T3_periodic` and `R3_schwartz_decay`. The
periodic lane binds a cubic period, physical-volume measure, a zero-mean
pressure gauge, and a zero spatial mean for velocity. The whole-space lane
binds Schwartz decay and a decay-at-infinity pressure gauge. Whole-space total
momentum is not inferred from `L2` data. No bounded boundary, forcing,
compressible, Euler, stochastic, or non-Newtonian lane is admitted.

Every request binds the initial field, approximate field, reconstruction,
domain, gauge, interval, norm convention, theorem bytes, and all numerical
remainder identities by digest. Real computed quantities are canonical exact
rationals. Integers are written without `/1`; nonintegers are reduced `p/q`
with a positive denominator. NaN, infinity, signed zero, leading zeros,
nonreduced fractions, reversed intervals, and floating JSON numbers refuse.

## 2. Claim classes and state separation

The only result statuses are `bounded`, `indeterminate`, and `refused`.
Internal evidence states are recorded separately:

- `ARITHMETIC_CHECKED`
- `CONTINUUM_ENCLOSURE_VERIFIED`
- `SOLUTION_LINK_VERIFIED`
- `THEOREM_APPLICABLE`
- `BOUNDED_ON_SCOPE`

An arithmetic success is never upgraded by copying a producer label. Gate S
must establish the exact-solution dependency on the identical domain, field,
and time scope before Gates A--D can emit a PDE conclusion.

The v1 assurance ceiling is `bounded`. Nothing in this pack is
`formal-bounded`: the Anubis policy kernel is executable exact arithmetic and
closed policy logic, not a proved checker for continuum analysis.

## 3. Gate S: exact-solution linkage

Gate S binds

```text
r   = partial_t u_a - nu Delta u_a + P((u_a dot grad)u_a)
e_0 = u_a(0) - u_0
div u_a
```

including the Leray projector, basis, normalization, interpolation,
quadrature, rounding, and tail evidence. Missing residual, initial mismatch,
divergence, theorem, or dependency evidence refuses. Downstream arithmetic
may still be reported as `ARITHMETIC_CHECKED`, but no PDE conclusion follows.

### Zero-solution identity

The sole enabled solution-link lane is
`JACKAL_T3_ZERO_SOLUTION_IDENTITY_V1`. It accepts only the canonical
`T3_ZERO_FOURIER_FIELD_V1` representation whose committed bytes are:

```text
jackal-navier-stokes-zero-field-v1
u0=0
ua=0
forcing=0
```

SHA-256:
`c9ca77221d998a4dadc654091bb27776c2a5e461debe3e88e98f7c1bbba06bcf`.
For this exact representation, the initial mismatch, PDE residual,
divergence defect, and every continuum remainder are identically zero. This is
a narrow positive control, not a general a-posteriori numerical lane.

The theorem identity is a separate canonical object:

```text
jackal-navier-stokes-zero-theorem-v1
claim=the-zero-field-solves-unforced-incompressible-navier-stokes
domain=T3_periodic
```

Its SHA-256 is
`4a26df4e465412aca24de29aeb882fb5c6c36148d16422ffd09f03fd8f3cdc09`.
All theorem-derived zero facts are honestly collapsed into one proof object,
not represented as five distinct artifacts that happen to share bytes:

```text
jackal-navier-stokes-zero-proof-object-v1
theorem=JACKAL_T3_ZERO_SOLUTION_IDENTITY_V1
representation=T3_ZERO_FOURIER_FIELD_V1
u0=0
ua=0
forcing=0
initial_mismatch=0
pde_residual=0
divergence=0
continuum_remainders=0
dependency_graph=exact_identity
```

The proof-object identifier is `JACKAL_T3_ZERO_PROOF_OBJECT_V1` and its
SHA-256 is
`42ac530f66869eafa2e1f82441ef1c47617fb2ee23a8b05e7d13a7aba4eb1e1f`.
The request schema binds the theorem, representation, and this single proof
object independently. Their exact bytes live respectively under
`domain_packs/pde/representations/`, `domain_packs/pde/identities/`, and
`domain_packs/pde/certificates/`; manifest loading performs bounded,
descriptor-anchored reads and verifies all three digests before any receipt is
accepted.

### CCRT lane remains disabled

`CCRT2007_COROLLARY_5_T3_APOSTERIORI` binds Chernyshenko--Constantin--
Robinson--Titi, Corollary 5 and equation (21), source SHA-256
`e815cbcdba8303dc03fb763bb0d10ce33660502ebd075b817359b9d05c89d76b`.
It remains disabled because v1 has no admitted checker for the continuum
Sobolev norms or the numerical value of the source's constant `c_m`. A digest
and a Boolean saying that a remainder was certified cannot close that gap.

## 4. Gate A: Leray--Hopf energy inequality

V1 admits only a prefix `[0,t]`. With exact positive `nu`, exact interval
arithmetic checks the sufficient condition

```text
upper(E_t) + 2 nu upper(D_grad) <= lower(E_0).
```

`D_grad` is the unweighted integral of the squared spatial gradient. The
kernel applies the exact positive viscosity once through `2*nu*D_grad`; a
caller must not supply an already viscosity-weighted value in this field.

Because viscosity is exact in v1, this is equivalent to using `upper(nu)` in
the interval enclosure. If the intervals overlap the boundary in the wrong
direction, the result is `indeterminate`; it is not evidence that a PDE
solution violates the energy inequality. A passing Gate A says only that the
linked observables satisfy the energy inequality on the named prefix. It does
not prove existence, uniqueness, smoothness, or global regularity.

## 5. Gate B: enstrophy and vortex stretching

For a smooth linked solution on `I=[t1,t2]`, the admitted global identity is

```text
0.5 (||omega(t2)||_2^2 - ||omega(t1)||_2^2)
  + nu integral_I ||grad omega||_2^2 dt
  = integral_I integral omega^T S(u) omega dx dt.
```

This controls `L2` vorticity, equivalently the homogeneous `H1` seminorm of a
divergence-free velocity under the admitted boundary convention. It is not an
`H1`-vorticity identity.

For each strictly increasing cutoff `Lambda`, the certificate supplies

```text
u_plus = max(0, upper(W_truncated) + upper(W_tail))
d_minus = lower(D_truncated) - upper(D_tail)
R_upper = u_plus / (nu d_minus).
```

Both `D_truncated` and `D_tail` are unweighted dissipation enclosures. The
kernel multiplies `d_minus` by exact `nu` exactly once.

The primary comparison is `u_plus <= nu*d_minus`. `d_minus <= 0` is
`indeterminate` and is never clamped. A missing tail theorem, tail receipt,
method digest, or reconstruction binding refuses.

The only v1 tail identity, `TEST_FIXTURE_EXACT_FINITE_SUPPORT_V1`, is an
arithmetic test fixture. V1 does not dereference and validate a general
finite-support reconstruction artifact, so this lane retains
`continuum_status: NOT_VERIFIED` even when its exact rational comparison is
checked. Its digests prevent accidental omission and exercise identity
mutations; digest shape alone is not continuum evidence. Consequently the v1
Gate-B lane cannot emit `BOUNDED_ON_SCOPE`.

- `R_upper <= 1`: arithmetic closes. A future PDE-level
  `BOUNDED_ON_SCOPE` result would additionally require both an admitted
  continuum reconstruction checker and the identical Gate-S link; neither is
  available for nonzero v1 fixtures.
- `R_upper > 1`: processing halts at the first offending cutoff and returns
  `uncertified_potential_blowup_vortex_stretching` with
  `mathematical_implication: none` and
  `nonclaim: not_evidence_of_singularity`.

An upper bound can be loose. Even actual net enstrophy growth would not by
itself prove loss of regularity or singularity.

## 6. Gate C: continuation criteria

`BKM1984_EULER_ONLY` always refuses as a Navier--Stokes theorem.
`KATO_PONCE_1988_NS_CONTINUATION_DISABLED` also refuses until the exact
theorem number, text, solution class, domain, interval topology, and
normalization are audited from the primary paper. V1 therefore emits no
positive Gate-C continuation conclusion. Failure to certify a prefix
vorticity integral is not evidence of blow-up.

## 7. Gate D: Serrin and ESS endpoint

The theorem registry distinguishes:

- `ESS2003_THEOREM_1_2_R3_SERRIN`: `3<q<=infinity` and exact
  `2/p + 3/q <= 1` arithmetic;
- `ESS2003_THEOREM_1_3_R3_ENDPOINT`: the separate
  `L-infinity(0,T;L3(R3))` endpoint.

Both are bound to source SHA-256
`2712fad880a7c626c5b7cdb678052585f502f0bd53594b03e51ea16b149fcc19`
and the `R3_schwartz_decay` Cauchy setting. They are not transferred to the
periodic domain. A finite grid, finite spectral truncation without a tail
theorem, or time samples without a time-continuum enclosure refuses.

V1 never reports `THEOREM_APPLICABLE` for Gate D. A matching theorem digest,
locator, domain, and exponent condition yields only
`THEOREM_IDENTITY_MATCHED_PRECONDITIONS_UNVERIFIED`, with top-level `refused`,
reason `theorem_preconditions_not_verified`, and
`continuum_status: NOT_VERIFIED`. The supplied Boolean is a declared request
field, not a mixed-norm artifact checker. V1 also has no `R3` Gate-S lane, so
the theorem's solution-class, time-continuum norm, and solution linkage remain
unverified and no PDE-level regularity conclusion can be emitted.

## 8. Closed JSON and Anubis protocol boundary

`tools/navier_stokes_certificate_producer.py` is an untrusted orchestration
layer. It rejects duplicate/missing/unknown JSON fields and encodes a fixed
45-line protocol because Anubis v0.1 has no general JSON parser. Closed-codec
refusals commit the exact raw request bytes and replay under the distinct
`closed_json_codec` authority, without first requiring an admitted request.
The Anubis
source validates field order, exact rationals, domain and theorem identities,
dependencies, comparisons, and state transitions. Generated native artifacts
used by the untrusted producer live in a fresh private per-request macOS
temporary directory and are never reused or written to the Git worktree.

`tools/navier_stokes_receipt_verify.py` does not import the producer. It
requires the repository manifest at its exact pinned digest, rejects
nonregular or changed-during-read authority files, and obtains a fixed
macOS account-home-relative locator plus the exact Anubis binary digest, size,
and read-only mode from that manifest. The located host path is not receipt
authority and is never serialized. A mutable `target/release/anubis` locator
is inadmissible, even if a caller supplies that file's current digest. Because
Darwin provides neither `fexecve` nor an
executable `/dev/fd` path, the verifier captures the already verified binary
and Anubis source descriptor bytes into private read/execute-only snapshots,
checks their identities before and after use, and executes those snapshots.
It runs the caller-pinned request in a sanitized,
bounded subprocess with a fresh temporary native-output directory. It then
deep-compares the runtime result, independently reconstructs the protocol and
rational policy transition, and deep-compares that replay too. An environment
variable or caller-selected binary can never define its own expected hash.

## 9. Repository/report semantic crosswalk

The separately generated evidence report uses a different receipt schema and
status vocabulary. The authoritative mapping is recorded in
`release/evidence/navier_stokes_report_crosswalk.json`; the two receipt types
are not bytewise or schema-equivalent. The pinned external bundle and all
three transition fixtures are rechecked by
`tests/navier_stokes_report_crosscheck.py`.

- report `ARITHMETIC_CHECKED` for a nonzero Gate-S-missing ratio maps to
  repository Gate B top-level `refused`, reason
  `solution_link_not_verified`, with internal `ARITHMETIC_CHECKED`;
- report `refused` with reason
  `uncertified_potential_blowup_vortex_stretching` maps to repository Gate B
  `indeterminate` plus
  `halt: true`; both are policy alerts and neither is singularity evidence;
- report `BOUNDED_ON_SCOPE` maps only to the exact-zero Gate-S identity.

The report's `dissipation_lower` is already viscosity-weighted. Repository
`d_truncated` and `d_tail_upper` are unweighted, and the repository computes
`nu*(lower(d_truncated)-upper(d_tail_upper))`. Direct field equivalence would
double-weight viscosity and is forbidden. Likewise, report
`tail_bound_included: true` records a declared input; it does not map to
repository `CONTINUUM_ENCLOSURE_VERIFIED`.

## 10. Permanent global boundary

Within `navier_stokes_v1`, a certificate whose quantified scope is a bounded
time interval or finite cutoff shall never mint a global conclusion,
regardless of how many such certificates pass. A global conclusion would
require a separately admitted, checker-accepted theorem whose conclusion
itself closes every future-time and continuum quantifier. For the positive
Clay statement it must also quantify over every admissible initial field. No
v1 operation admits such a conclusion.

A finite proof object may establish a global result for a special datum when
an admitted theorem actually has that conclusion. That is categorically
different from the universal Clay statement, and no such lane is enabled here.

## 11. Resource limits and refusal behavior

Rational numerators and denominators are bounded by `10^9`; cutoff sequences
are bounded by 128; protocol atoms are bounded by 4096 UTF-8 bytes. The closed
request codec additionally enforces 4 MiB, depth 32, and 4096 nodes. Receipts
are bounded by 16 MiB, depth 36, and 4352 nodes. The flat protocol is bounded
by 1 MiB, 45 lines, and 2048 semantic nodes. Authoritative output is bounded
by 65536 bytes, each identity artifact by 65536 bytes, and the subprocess by
30 seconds with child CPU, file-size, descriptor, core-dump, and process-group
limits. Every parsed and computed rational intermediate is reduced and
rechecked against the `10^9` bounds.
Overflow, process failure, compiler failure, malformed output, identity
mismatch, independent replay disagreement, or a status mutation refuses.
There is no fallback or silent downgrade.
