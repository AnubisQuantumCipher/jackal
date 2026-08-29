# SPARK fixed-scale HELLGATE interval envelope

This repository-side component independently specifies and proves a narrow
integer interval decision boundary used to sanity-check the admitted HELLGATE
energy envelope. Because the energy is negative, the demo represents its
absolute magnitudes on a fixed `10^18` scale.

The requirements-complete component claim covers `JCK-INT-001` through
`JCK-INT-004`. Its total decision function is quantified over every value of
the public fixed-scale input types. GNATprove establishes deterministic
rejection precedence, exact ordered width, midpoint/ceiling-radius endpoint
coverage, strict admission equivalence, zeroed rejection outputs, termination,
and absence of targeted run-time errors.

The target conversion was routed through JACKAL exact arithmetic:
`status=exact`, `parsed=2/10^12*10^18`, `exact=2000000`.  That exact result is
outside the Lean certificate chain and is not `formal-bounded`.

Run:

```sh
./prove.sh
```

The proof gate runs at level 3 with proof warnings treated as errors and refuses
unproved checks, justified checks, `pragma Assume`, `pragma Annotate`, or a
report that skipped the expected package. The requirement and whole-surface
closure source is `assurance/requirements.json`.

The proof boundary is deliberately limited. This component does not prove the
nonlinear Barta theorem, the density strong-convexity theorem, certificate
parsing, the Python checker's rational integration, Python-to-SPARK refinement,
source-to-object equivalence, compiler or run-time correctness, or any
mission/safety claim.  It is not DO-178C, ECSS, NASA, or launch-provider
qualification evidence.
