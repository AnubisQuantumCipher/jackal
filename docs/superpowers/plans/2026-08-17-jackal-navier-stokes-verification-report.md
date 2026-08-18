# JACKAL Navier–Stokes Verification Pack and Evidence Report Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> `superpowers:subagent-driven-development` task by task and
> `superpowers:test-driven-development` for every behavior change. Use the
> installed `rigorous-evidence-report` skill for the research bundle. Every task
> receives specification review before code-quality review.

**Goal:** Build a macOS-only, Anubis-authoritative, fail-closed research pack
that certifies explicitly localized Navier–Stokes inequalities and conditional
regularity criteria without claiming to solve the three-dimensional global
existence and smoothness problem. Deliver a reproducible professional report
bundle whose first page states the open status.

**Architecture:** An untrusted producer supplies an approximate field, exact
PDE residuals, an initial mismatch, a divergence defect, exact-rational
interval enclosures for named continuum observables, and every numerical
remainder. Mandatory Gate S first applies an admitted a-posteriori theorem to
link those artifacts to an exact Navier–Stokes solution on the named scope. The
Anubis pack then validates schema, domain, cutoffs, theorem applicability,
interval relations, gate transitions, and refusal reasons. Independent Python
replay is a second implementation for testing/report verification, not the
product authority. Without Gate S, an arithmetic comparison can be reported
only as `ARITHMETIC_CHECKED`; it cannot become a PDE claim. No finite grid,
cutoff, time cover, or successful ratio is promoted to a continuum/all-time
theorem.

**Supported domains:** `R3_schwartz_decay` and `T3_periodic`, each with
`nu > 0`, constant density normalized to one, exactly zero external force, a
smooth divergence-free initial velocity field, and explicit normalization,
pressure-gauge, mass, and momentum conventions. No bounded-domain boundary conditions,
compressible flow, Euler flow, stochastic forcing, or non-Newtonian model is
admitted in v1.

**Primary source status:** As of 2026-08-17, Clay still lists the problem as
unsolved. The original Beale–Kato–Majda theorem is for Euler. A Navier–Stokes
continuation gate must cite the applicable Kato–Ponce or other explicitly
audited viscous theorem; it cannot relabel the Euler paper.

## Formal core

For velocity `u`, pressure `p`, viscosity `nu`, and vorticity
`omega = curl u`, the pack records:

```text
partial_t u + (u dot grad)u = -grad p + nu Delta u
div u = 0
u(x,0) = u0(x)
```

For sufficiently smooth solutions, with the declared decay or periodic
boundary convention:

```text
||u(t)||_2^2 + 2 nu integral_0^t ||grad u(s)||_2^2 ds <= ||u0||_2^2

0.5 d/dt ||omega||_2^2 + nu ||grad omega||_2^2
  = integral omega dot S(u) omega dx
```

where `S(u) = 0.5 (grad u + grad u^T)`. The energy inequality is a weak-solution
bound; the enstrophy equality is a smooth-solution identity and cannot be
asserted across a singular time without additional justification.

Constant density is normalized to `rho_0 = 1`, so mass conservation reduces to
`div u = 0`, and external force is exactly zero. On `T3`, the certificate binds
the conserved spatial mean of velocity; a zero-mean a-posteriori theorem lane
must either prove that premise or bind the exact mean-removal/Galilean map. On
`R3`, total momentum is not inferred from `L2` data: it is an admitted
observable only with `L1` and decay evidence sufficient for the integral and
integration by parts. Pressure uses zero spatial mean on `T3` or an explicitly
declared whole-space gauge.

## Claim classes and fail-closed states

- `bounded`: a named finite interval/cutoff inequality is enclosed with all
  declared errors.
- `model-based`: a numerical/physical model conclusion whose assumptions remain
  explicit; never used to assert PDE regularity.
- `indeterminate`: well-formed evidence does not close a requested gate.
- `refused`: malformed, unsupported, identity-mismatched, or semantically
  inadmissible input.
- Gate register: `OPEN`, `PARTIAL`, or `VERIFIED` inside the research report.

Positive progress is recorded with scoped states:
`ARITHMETIC_CHECKED`, `CONTINUUM_ENCLOSURE_VERIFIED`,
`SOLUTION_LINK_VERIFIED`, `THEOREM_APPLICABLE`, and `BOUNDED_ON_SCOPE`.
The report gate register remains `OPEN`, `PARTIAL`, or `VERIFIED` only for the
named obligation, never for the Clay problem as a whole.

The v1 pack has no output state named `global_regular`, `smooth_for_all_time`,
or `millennium_solved`. A request for any equivalent claim returns
`status: refused`, `reason: global_regular_claim_not_admitted`.

## File map

- `domain_packs/pde/navier_stokes_v1.anb`: authoritative parsing, canonical
  intervals, gate logic, statuses, and refusals.
- `domain_packs/pde/navier_stokes_v1.json`: pack manifest, theorem IDs,
  operation IDs, resources, compatibility, and assurance ceiling.
- `domain_packs/pde/NAVIER_STOKES_VERIFICATION_SPEC.md`: human-readable schema,
  equations, quantifiers, applicability, and non-claims.
- `tools/navier_stokes_certificate_producer.py`: explicitly untrusted fixture/
  certificate producer.
- `tools/navier_stokes_receipt_verify.py`: independent replay used by reports
  and differential tests.
- `tests/navier_stokes_gate_test.py`: positives, refusals, threshold behavior,
  continuum-bound requirements, and no-global-claim controls.
- `tests/navier_stokes_semantic_mutations.py`: A-to-B-to-A gate/identity/
  theorem/cutoff/tail/status mutations.
- `release/evidence/navier_stokes_claim_audit.json`: supplied-claim audit and
  exact correction registry.
- `release/evidence/navier_stokes_fixture_receipts/`: localized fixture
  receipts only; no global proof receipt.
- `~/Desktop/Projects/Navier_Stokes_Report_2026-08-17/`: rendered report bundle,
  archived sources, source manifest, receipts, and verifier.

### Task 1: Freeze and archive the evidence question

**Bundle files outside Git:**

- `Navier_Stokes_Rigorous_Status_Report.md`
- `Navier_Stokes_Rigorous_Status_Report.pdf`
- `SOURCE_MANIFEST.json`
- `sources/`
- `receipts/`
- `verify_report.py`
- `VERIFICATION_RECEIPT.txt`

- [ ] **Step 1: Freeze the question**

Use this exact objective sentence on page one:

> Determine whether the supplied four-gate/JACKAL procedure constitutes a
> proof that every admitted smooth divergence-free initial field on
> `R^3` or `T^3` has a global smooth solution, and specify the strongest
> finite/local claims it can certify.

Definition of done for the report is an unambiguous `UNSOLVED / PARTIAL
INSTRUMENT` verdict, a claim audit, exact gate obligations, archived primary
sources, and a mechanical bundle PASS. It is not a proof of global regularity.

- [ ] **Step 2: Archive primary sources**

Retrieve and retain at minimum:

1. Clay/Fefferman official problem description;
2. Clay's current unsolved problem page or unsolved archive;
3. Leray's 1934 whole-space weak-solution paper or a faithful hosted
   translation with bibliographic identity;
4. Serrin's 1962 regularity paper metadata/full text where lawfully available;
5. Escauriaza–Seregin–Šverák's 2003 English paper;
6. Beale–Kato–Majda's 1984 Euler paper metadata/full text;
7. Kato–Ponce's 1988 Euler/Navier–Stokes paper, retained as metadata-only and
   disabled until its exact theorem text and assumptions are audited;
8. Chernyshenko–Constantin–Robinson–Titi's primary periodic a-posteriori
   regularity paper, including the exact theorem or corollary admitted by Gate
   S;
9. Morosi–Pizzocchero's primary a-posteriori control framework, to delimit
   what rigorous finite computation can and cannot prove.

For each retained response record canonical URL, retrieval UTC time, media
type, byte count, SHA-256, title, authors, DOI/identifier, and local path in
`SOURCE_MANIFEST.json`. Search-result pages are discovery only and are not
cited as evidence.

- [ ] **Step 3: RED source-manifest verifier**

Before sources exist, write `verify_report.py` checks for exact manifest schema,
unique source IDs, safe relative paths, actual byte size/digest/media signature,
required identifiers, and no unmanifested source file. Run it and confirm RED
on missing sources.

### Task 2: Define the exact request and certificate schema

**Files:**

- Create: `domain_packs/pde/navier_stokes_v1.json`
- Create: `domain_packs/pde/NAVIER_STOKES_VERIFICATION_SPEC.md`
- Create: `tests/navier_stokes_gate_test.py`

- [ ] **Step 1: RED schema/refusal tests**

Require refusal for absent/duplicate/unknown fields; noncanonical rationals;
`nu <= 0`; reversed time intervals; negative or nonfinite cutoff; unsupported
domain; missing initial-field digest; unproved divergence-free or smoothness
precondition; missing approximate-field/residual/solution-link evidence;
missing projection/quadrature/rounding/tail bounds; inconsistent norm
convention; unknown or disabled theorem ID; and a global-regularity target.

- [ ] **Step 2: Specify canonical data**

All real intervals use exact canonical rational endpoint strings:

```json
{"lower": "p/q", "upper": "r/s"}
```

with positive denominators, reduced fractions, and `lower <= upper`. Infinity
is allowed only in explicitly enumerated exponent fields, never in a computed
quantity enclosure.

Every request binds:

- schema and pack version, dimension, equation/sign convention, density one,
  and exactly zero forcing;
- `R3_schwartz_decay` or `T3_periodic`, including torus lattice/period/volume/
  measure normalization or the exact whole-space decay class;
- an exact positive viscosity in v1; a nondegenerate viscosity interval is
  refused until a theorem explicitly quantifies over the resulting family of
  solutions;
- initial-field decoder, artifact digest, representation, units, smoothness,
  divergence, decay/periodicity, and mean evidence;
- approximate-field/reconstruction digest and explicit velocity, pressure,
  curl, strain, and pressure-gauge conventions;
- time endpoints, open/closed topology, terminal-time role, quadrature
  partition, cutoff kind/value/operator/units/lattice/projection/de-aliasing,
  and a strictly ordered duplicate-free cutoff sequence;
- projection, quadrature, rounding, interpolation, tail theorem, constants,
  method digests, numerical precision, and resource bounds;
- integral versus volume-average norms, homogeneous versus inhomogeneous
  Sobolev norms, mixed-norm order, and essential-supremum semantics;
- theorem ID, full theorem-source digest, theorem/page, domain, scaling map,
  assumptions, and conclusion;
- exact observable definitions, units/dimensions, producer/oracle identities,
  requested scoped status, explicit nonclaims, and `allow_fallback: false`.

Every certificate binds the initial mismatch, divergence defect, PDE residual,
solution-link proof, every observable interval and one-sided continuum
remainder, the dependency graph from source artifact through observable and
comparison, the theorem-assumption matrix, the exact arithmetic transcript and
margins, and separate statuses for arithmetic validity, continuum enclosure,
solution linkage, theorem applicability, and mathematical conclusion.

- [ ] **Step 3: Set assurance ceilings**

Each v1 operation's maximum output is `bounded` on the exact finite scope.
Conditional theorem applicability is reported separately. No operation may
mint `formal-bounded` until a proved checker exists for this pack.

### Task 3: Implement mandatory Gate S exact-solution linkage

**Files:**

- Create: `domain_packs/pde/navier_stokes_v1.anb`
- Extend: `domain_packs/pde/navier_stokes_v1.json`
- Extend: `tests/navier_stokes_gate_test.py`

- [ ] **Step 1: RED arbitrary-observable laundering test**

Construct producer-supplied `E_t`, `D_grad`, `U_stretch`, and mixed-norm
intervals that satisfy every downstream rational comparison but have no field,
PDE residual, or solution-link proof. Every Gate A–D PDE conclusion must refuse
with `solution_link_not_verified`. Only a scoped `ARITHMETIC_CHECKED` result is
permitted.

- [ ] **Step 2: Bind the approximate problem exactly**

For approximate field `u_a`, certify enclosures for

```text
r = partial_t u_a - nu Delta u_a
    + P((u_a dot grad)u_a) - P f
e_0 = u_a(0) - u_0
div u_a
```

and every representation, projection, interpolation, quadrature, rounding,
and continuum-tail error. Bind the Leray projector `P`, domain, basis,
normalization, pressure convention, initial datum, and exact time scope.

- [ ] **Step 3: Admit one exact a-posteriori theorem lane**

Start with the periodic, zero-mean Chernyshenko–Constantin–Robinson–Titi
lane. For the exact admitted theorem/corollary and its declared `m >= 3`,
machine-check every assumption and rigorously enclose

```text
eta = ||u_a(0) - u_0||_(H^m)
    + integral_0^T ||partial_t u_a + nu A u_a
        + B(u_a,u_a) - f||_(H^m) dt

eta < (1 / (c_m * T))
      * exp(-c_m * integral_0^T
          (||u_a(t)||_(H^m) + ||u_a(t)||_(H^(m+1))) dt)
```

The theorem-source bytes, theorem number/page, domain scaling, constant
definition, norm conventions, zero-mean premise, and strict comparison margin
are caller-pinned. If any premise or bound is missing, Gate S is
`indeterminate` or `refused`; it never silently substitutes a heuristic.

- [ ] **Step 4: Emit separated assurance states**

The certificate independently records arithmetic validity, continuum
enclosure, exact-solution linkage, theorem applicability, and scoped
conclusion. Only a successful Gate S may emit `SOLUTION_LINK_VERIFIED`; Gates
A–D depend on that exact node and scope.

### Task 4: Implement Gate A energy certification in Anubis

**Files:**

- Create: `domain_packs/pde/navier_stokes_v1.anb`
- Extend: `tests/navier_stokes_gate_test.py`

- [ ] **Step 1: RED sufficient-interval test**

For v1, restrict the Leray–Hopf weak-solution lane to prefix intervals with
`t0 = 0`. Given enclosures `E_t`, `D_grad`, `E_0`, and exact positive `nu`,
certify only when exact rational arithmetic proves:

```text
upper(E_t) + 2 * nu * upper(D_grad) <= lower(E_0)
```

This is a sufficient interval condition for the claimed inequality. An overlap
or failed comparison returns `indeterminate`, not a claim that the PDE violates
the energy inequality. A future general interval `[t1,t2]` lane must check

```text
upper(E_t2) + 2 * nu * upper(D_grad_[t1,t2]) <= lower(E_t1)
```

and additionally bind a strong-energy start-time admissibility proof; it may
not assume the Leray–Hopf inequality holds from every positive representative
time.

- [ ] **Step 2: Bind every term**

Reject negative energy/dissipation, mismatched time/field/domain digests,
omitted forcing declaration, and norm normalization drift. Return the exact
comparison residual and all source intervals. Passing Gate A proves only
energy consistency on the linked scope; it does not prove existence,
uniqueness, smoothness, or absence of singularities.

- [ ] **Step 3: Differential replay**

Implement the same rational comparison independently in Python and require
deep equality over seeded positive, boundary (`=`), overlap, and malformed
cases. Python disagreement stops release; it does not override Anubis.

### Task 5: Implement Gate B enstrophy and vortex-stretching ratio

**Files:**

- Extend: `domain_packs/pde/navier_stokes_v1.anb`
- Extend: `tests/navier_stokes_gate_test.py`
- Create: `tests/navier_stokes_semantic_mutations.py`

- [ ] **Step 1: Define the exact continuum objects and only admitted ratio**

For `I = [t1,t2]`, bind physical-volume or normalized-torus measure and define

```text
E_omega(t) = integral |omega(x,t)|^2 dx
D_I = integral_I integral |grad omega|^2 dx dt
W_I = integral_I integral omega^T S(u) omega dx dt

0.5 * (E_omega(t2) - E_omega(t1)) + nu * D_I = W_I
```

The prompt's phrase "H1 norm evolution for vorticity" is rejected as
incorrect: this identity controls `||omega||_2`, equivalently the homogeneous
`H1` seminorm of divergence-free velocity under the declared boundary/decay
conditions, not the `H1` norm of vorticity.

For cutoff `Lambda`, require one-sided reconstruction certificates

```text
W_I <= W_[I,Lambda] + R_W_[I,Lambda]
D_I >= D_[I,Lambda] - R_D_[I,Lambda]

u_plus = max(0, upper(W_[I,Lambda]) + upper(R_W_[I,Lambda]))
d_minus = lower(D_[I,Lambda]) - upper(R_D_[I,Lambda])
```

Thus `u_plus` is a certified nonnegative majorant of `max(W_I, 0)`, not merely
an enclosure of a truncated integral. Only when exact `nu > 0` and
`d_minus > 0` may the engine define

```text
R_upper = u_plus / (nu * d_minus)
```

The primary exact check is the cross-multiplied inequality
`u_plus <= nu * d_minus`; the quotient is a diagnostic. If `d_minus <= 0`, do
not clamp it: return `indeterminate`, reason
`dissipation_lower_bound_not_positive`.

Dimension checks are mandatory: `[nu D_I] = [W_I] = L^3/T^2`, so `R_upper` is
dimensionless. The cutoff certificate binds mode number versus physical
wavenumber, lattice, Fourier normalization, basis, projection, de-aliasing,
interpolation, quadrature, exact tail theorem/constants, and all method and
artifact digests.

- [ ] **Step 2: RED threshold tests**

- `R_upper < 1`: with Gate S and the full continuum identity, localized
  enstrophy nonincrease is `bounded` on the exact interval/cutoff only;
- `R_upper = 1`: the same localized conclusion, boundary retained exactly;
- `R_upper > 1`: halt the run and return `indeterminate`, reason
  `uncertified_potential_blowup_vortex_stretching`;
- any missing tail/remainder: `refused`, reason
  `continuum_remainder_not_certified`.

An upper bound above one may be loose. Even actual `W_I > nu D_I` would mean
only net enstrophy growth. The alert is a requested policy trigger and carries
`mathematical_implication: none` and
`nonclaim: not_evidence_of_singularity`. Human wording must state that it does
not establish enstrophy growth, loss of regularity, or blow-up.

- [ ] **Step 3: Lock `Lambda` fail-closed behavior**

For a list of cutoffs, evaluate in canonical order and halt on the first
`R_upper > 1`. The result binds that `Lambda` and retains all previously
completed localized receipts. It never skips the failing cutoff or reports a
later success as overriding it. The cutoff sequence is strictly ordered and
duplicate-free.

V1 admits only global spatial integrals reconstructed from the cutoff. A
spatially localized enstrophy balance is refused until its separate cutoff
identity and all transport/diffusion flux terms are implemented; spectral
truncation alone does not inherit the continuum identity.

- [ ] **Step 4: A-to-B-to-A mutations**

Mutate threshold `1` to another value, `>` to `>=`, viscosity lower to upper,
dissipation lower to upper, tail included to omitted, cutoff identity, status,
and reason. Every B form must fail; canonical hashes and behavior must return in
A/post.

### Task 6: Implement conditional Gates C and D without theorem transfer

**Files:**

- Extend: `domain_packs/pde/navier_stokes_v1.anb`
- Extend: `domain_packs/pde/navier_stokes_v1.json`
- Extend: `tests/navier_stokes_gate_test.py`

- [ ] **Step 1: Distinguish Euler BKM from Navier–Stokes continuation**

The theorem registry records the 1984 BKM paper as `euler_only` and makes it
inadmissible for a Navier–Stokes continuation receipt. Gate C accepts only an
audited viscous theorem ID whose exact assumptions include the solution class,
domain, Sobolev regularity, and finite bound on
`integral ||omega(t)||_infinity dt`. Kato–Ponce remains disabled until the full
paper, exact theorem number/page, and theorem text are archived and audited.
The registry must separately bind domain, viscosity normalization/rescaling,
forcing, initial/solution spaces, maximal-strong-solution definition, interval
topology, and exact conclusion. No theorem is transferred silently between
`R3` and `T3`.

- [ ] **Step 2: Keep continuation localized**

A rigorous bound on an arbitrary closed interior interval does not establish a
continuation premise. To cross a candidate terminal time `T`, the checker must
bind the full prefix

```text
integral_0^T ||omega||_infinity dt
  <= B_prefix + B_terminal < infinity
```

where the terminal certificate covers `[t1,T)` and the earlier strong-solution
segment is justified. It does not establish a uniform all-time vorticity
bound. Failure to certify the integral is not evidence of blow-up.

- [ ] **Step 3: Encode Serrin and endpoint lanes separately**

For `q > 3`, exact exponent arithmetic checks
`2/p + 3/q <= 1`; the certificate must enclose the actual continuum mixed norm,
not samples. The endpoint is a distinct ESS theorem lane requiring
`u in L^infinity(0,T; L^3(R^3))`. It is not accepted by pretending `q > 3`.
For strict exponent inequality on a finite interval, bind the reduction to the
equality exponent and its exact time-embedding factor. ESS is enabled only for
its audited `R3`, viscosity-normalized Cauchy setting; it is not a periodic
theorem. Periodic Serrin/endpoint lanes remain refused until separately
audited theorem artifacts exist.

- [ ] **Step 4: Reject finite-sample laundering**

A field sampled on a finite grid, a spectral truncation without a tail theorem,
or per-time norm samples without a time-continuum enclosure must refuse with
`continuum_norm_not_certified`.

### Task 7: Build independent receipt replay and no-global closure

**Files:**

- Create: `tools/navier_stokes_receipt_verify.py`
- Create: `tools/navier_stokes_certificate_producer.py`
- Create: `release/evidence/navier_stokes_fixture_receipts/`
- Extend tests and mutation harness.

- [ ] **Step 1: Caller-pinned expectations**

Replay requires the entire caller-pinned canonical request, or its independently
trusted digest. That binds pack version, Anubis checker, theorem registry,
arithmetic kernel, domain, viscosity, initial/approximate-field and evidence
digests, interval topology, cutoff model, gate, theorem artifact, and requested
scoped status. Never copy expectations from the receipt under review.

- [ ] **Step 2: Preserve exact status and non-claims**

The verifier deep-compares canonical request commitment, arithmetic result,
reason, assumptions, solution-link dependency graph, PDE residual and initial/
divergence defects, continuum remainders, theorem-assumption matrix, exact
arithmetic transcript/margins, tail model, identities, and residual non-claims.
It separately validates arithmetic, continuum enclosure, solution linkage,
theorem applicability, and mathematical conclusion. A valid `indeterminate`
alert verifies as an authentic policy alert; it does not become a positive
mathematical result.

- [ ] **Step 3: Permanent global negative control**

Attempt to alter any finite receipt into `global_regular`, remove its cutoff,
replace `[t1,t2]` with `[0,infinity)`, or set the Clay register to `VERIFIED`.
Each mutation must refuse even if all finite arithmetic remains unchanged.

Use this exact boundary in the spec and report:

> Within `navier_stokes_v1`, a certificate whose quantified scope is a bounded
> time interval or finite cutoff shall never mint a global conclusion,
> regardless of how many such certificates pass. A global conclusion would
> require a separately admitted, checker-accepted theorem whose conclusion
> itself closes every future-time and continuum quantifier. For the positive
> Clay statement it must also quantify over every admissible initial field. No
> v1 operation admits such a conclusion.

Do not claim that a finite proof object can never imply global existence for a
particular datum: admitted a-posteriori theorems may do so for special data.
That is categorically different from the universal Clay statement.

### Task 8: Write, render, and mechanically verify the rigorous report

- [ ] **Step 1: Use the required section order**

The Markdown/PDF includes status declaration, executive answer, formal core,
precision corrections, claim audit, why hard, scope-limited comparisons,
proof-obligation gates, bounded research program, JACKAL verification
supplement, final verdict, method/evidence boundary, and numbered sources.

- [ ] **Step 2: Audit the supplied gates**

At minimum correct these points:

- Gate S must link every observable to an exact solution through a fully
  checked a-posteriori theorem; otherwise only arithmetic was checked;
- Gate A is necessary weak-solution control, not global smoothness;
- the enstrophy identity controls `L2` vorticity/the homogeneous `H1` velocity
  seminorm, not the `H1` norm of vorticity;
- Gate B exposes the supercritical vortex-stretching obstruction but a finite
  ratio calculation is localized;
- original BKM is Euler, while Navier–Stokes uses a separately sourced analogue;
- `q > 3` Serrin and `L^infinity_t L^3_x` ESS endpoint are distinct;
- finite cutoffs and intervals never close the `Lambda -> infinity` or
  `t -> infinity` quantifiers;
- `R_upper > 1` is an uncertified alert, not proof of a singularity;
- `R_upper <= 1` on finitely many scopes is not proof of global regularity.
- density is one, forcing is exactly zero, torus mean momentum is conserved,
  whole-space total momentum requires additional `L1`/decay assumptions, and
  the pressure gauge is explicit.

- [ ] **Step 3: Render reproducibly**

```bash
/opt/homebrew/bin/pandoc \
  Navier_Stokes_Rigorous_Status_Report.md \
  --pdf-engine=/opt/homebrew/bin/typst \
  -o Navier_Stokes_Rigorous_Status_Report.pdf
/opt/homebrew/bin/pdftotext \
  Navier_Stokes_Rigorous_Status_Report.pdf \
  Navier_Stokes_Rigorous_Status_Report.pdf.txt
/opt/homebrew/bin/qpdf --check Navier_Stokes_Rigorous_Status_Report.pdf
```

Render representative pages to PNG with `mutool draw`, inspect them visually,
and repair raw markup, clipped tables, broken glyphs, or overflowing hashes.

- [ ] **Step 4: Mechanical report checks**

`verify_report.py` must rehash every source and receipt, parse all JSON,
independently replay fixture receipts, verify required claim-boundary sentences
in both Markdown and extracted PDF text, run PDF structure checks, reject a
forbidden solved/global claim, and print exactly one final
`NAVIER_STOKES_REPORT_VERIFICATION=PASS` line.

- [ ] **Step 5: Freeze final receipt**

Record the PDF SHA-256, Markdown SHA-256, source-manifest SHA-256, verifier
SHA-256, receipt aggregate, commands, tool versions, and representative-page
inspection results in `VERIFICATION_RECEIPT.txt`.

### Task 9: Review and publish the bounded deliverable

- [ ] Obtain independent mathematical/specification review first.
- [ ] Fix every incorrect theorem attribution, quantifier, inequality direction,
  status transition, or missing non-claim and repeat review.
- [ ] Obtain code-quality/security review for parser, exact rational arithmetic,
  resource bounds, source archiving, and verifier.
- [ ] Run the Anubis compiler check, all focused tests, mutation harness,
  independent receipt replay, report verifier, PDF text/structure/visual gates,
  and full repository evidence suite on unchanged bytes.
- [ ] Commit only repository source/spec/test/evidence fixtures; do not commit
  downloaded copyrighted source PDFs unless licensing and repository policy
  permit it. The Desktop bundle retains lawful audit copies.
- [ ] Push an evidence-rich PR, wait exact-head CI, merge by the repository's
  observed merge convention, and read the merged files back.

## Completion definition

This workstream is complete only when Gate S prevents arbitrary-observable
laundering; the pack can reproduce every positive, boundary, refusal, and
poison result; no finite receipt can be laundered into a global claim; the
report bundle verifier prints PASS; and the final verdict remains `UNSOLVED /
PARTIAL INSTRUMENT`. A successful localized bound is useful evidence, but it is
not completion of the Clay Millennium Problem.
