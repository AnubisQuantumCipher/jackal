# Shadow proof flow — request to verdict

**Status: research-shadow. Non-authoritative.** v1.7 `bound_step` composition
(roadmap item 4), baseline v1.6.0 = 19b763e.

## Flow diagram

```mermaid
flowchart TD
    REQ["request: expr sexp, req_lo, req_hi, tol  (exact ℚ)"] --> PROD
    PROD["UNTRUSTED producer\ntools/bound_step_shadow_producer.py\n(bound_step mirror: float midpoints,\nexact-ℚ acceptance, budget 60000, depth 60)"] --> ART
    ART["artifact: jackal-int-cert shadow-v1\nheader pins + subdivision tree +\nper-leaf embedded jackal-eval-cert v2"] --> PARSE
    PARSE["parseIntCert  (ShadowCertCodec)\ncanonical-ℚ grammar, kind-aware roles,\nembedded blocks -> PROVED Cert.parseCertLines"] -->|malformed-artifact / noncanonical-value| REFUSE
    PARSE --> CHK
    CHK["checkIntCert  (ShadowCertCheck)\nheader pins -> structural tree pass ->\nper-node semantic pass -> release binding"] -->|14 stable reason classes| REFUSE
    CHK --> ACC["SHADOW-ACCEPT status=research-shadow\ntheorem=int_cert_sound output lo hi"]
    REFUSE["SHADOW-REFUSE reason=class:detail  exit 1"]

    subgraph leaf premises (per accepted leaf)
        EC["Cert.checkCert = true\n(existing proved checker)"] --> CCS["cert_check_sound\n(bridge #2, v1.5/v1.6)"]
        QX["qexprOf = DQiter k of root integrand\n+ qexprOf_embed + embedQ_DQ"] --> CCS
        CCS --> RUNS["Runs (D^k e) (input) (output)"]
        RUNS --> RE["runs_encloses:\nDefinedOn + pointwise enclosure"]
    end

    subgraph soundness theorem int_cert_sound
        RE --> RANGE["range leaf:\nsem_measurable + Integrable.mono' +\nintegral_mono_on  (ShadowMeasure)"]
        RE --> T2["taylor2 leaf:\nDeriv.taylor2_enclosure_of_evaluable\n+ exact-midpoint instantiation"]
        RE --> T4["taylor4 leaf:\nDeriv.taylor4_enclosure_of_evaluable\n+ exact-midpoint instantiation ×2"]
        RANGE --> SPLIT
        T2 --> SPLIT
        T4 --> SPLIT
        SPLIT["split node: IntervalIntegrable.trans +\nintegral_add_adjacent_intervals +\nexact partition equalities + sum conservativity"]
        SPLIT --> ROOT["root: released ⊇ root claim, width ≤ tol\n⇒ out_lo ≤ ∫ f ≤ out_hi  under TreeTCB"]
    end

    ACC -. meaning fixed by .-> ROOT
```

## Theorem identities (all at proofs/lean/JackalIv/)

| object | location | axioms |
|---|---|---|
| `int_cert_sound` (flagship) | ShadowCertSound.lean | propext, Classical.choice, Quot.sound |
| `range_leaf_sound` | ShadowCertSound.lean | same |
| `taylor2_leaf_sound` / `taylor4_leaf_sound` | ShadowCertSound.lean | same |
| `split_sound` | ShadowCertSound.lean | same |
| `sem_measurable` (+ rpow measurability) | ShadowMeasure.lean | same |
| `embedQ_DQ`, `qexprOf_embed` | ShadowQExpr.lean | same |
| `checkIntCert` (computable checker) | ShadowCertCheck.lean | — (def) |
| `parseIntCert` (codec) | ShadowCertCodec.lean | — (def) |
| build-time twins (`#guard`) | ShadowCertFixtures.lean | evaluated, not kernel |

Named TCB of `int_cert_sound`: `TreeTCB` = `Cert.ModelTCB` (LibmModel ∧
ConstTCB) per embedded evaluation certificate — a `Prop` hypothesis, never an
axiom; vacuously dischargeable when every embedded certificate stays in the
pure-ℚ fragment (all shadow-producer artifacts do).

## Mechanized / tested / trusted / unknown

| claim | register |
|---|---|
| Accepted artifact ⇒ released interval encloses ∫ of the reconstructed integrand (model) | MECHANIZED (`int_cert_sound`) |
| Per-leaf enclosure + evaluability premises | MECHANIZED (via existing `cert_check_sound`, `runs_encloses`, Taylor/Deriv bridges) |
| Exact partition, order binding, no dup/orphan/cycle, budget 60001, depth 60, local tolerance, released width ≤ tol | MECHANIZED as checker refusals; policy meaning documented |
| Checker behavior on concrete twins (accept + 4 exact refusal reasons) | TESTED (build-time `#guard`, interpreter-evaluated) + 31-row executable matrix |
| Producer mirrors the shipped `bound_step` control flow | TESTED (matrix refusal classes) + DISCLOSED divergences (D4-D6): Lean-`D` chains without `simplify_bound`, exact-ℚ acceptance, exact midpoint point-intervals |
| Producer-emitted artifact ↔ engine `integrate-bound` output consistency | TESTED differentially (overlap/containment, see evidence/differential_engine.json) |
| Lean toolchain, `Rat` codec, `lake env lean --run` interpreter | TRUSTED (same TCB class as bridge #2's compiled checker; disclosed) |
| Platform libm / const rounding for transcendental embedded certificates | TRUSTED via `TreeTCB` hypothesis (vacuous for pure-ℚ artifacts) |
| Engine f64 execution equals the model | UNKNOWN here — inherited residual (Ledger: implementation-tested-not-mechanized); untouched |
| Source→native refinement (roadmap 5) | UNKNOWN/OPEN — untouched |

## Supported / refused mode matrix (shadow fragment)

| leaf mode | integrand ops (producer) | premises consumed | verdict lane |
|---|---|---|---|
| range | num var neg add sub mul div pow(0..4096) sin cos abs | F cert (`runs_encloses` + measurable-bounded) | ACCEPT if claim ⊇ exact range ideal |
| taylor2 | smooth core (D-chain evaluates) | F,F1,F2 over [a,b]; Fm ∋ exact midpoint | ACCEPT if claim ⊇ range∩taylor2 ideal |
| taylor4 | smooth core, D⁴-chain evaluates (pow-free chains; e.g. sin/cos) | F,F1..F4; Fm,F2m ∋ exact midpoint | ACCEPT if claim ⊇ range∩taylor4 ideal |
| split | — | two children, exact partition, sum conservativity | composed |
| anything else (`tan`, `%`, non-integer literals/exponents, unknown calls) | — | — | REFUSE (`unsupported-expression` / `unsupported-leaf-mode`) |

Checker-side refusal classes (16): malformed-artifact, noncanonical-value,
stale-identity, malformed-tree, invalid-interval, request-mismatch,
unsupported-leaf-mode, missing-premise, forged-enclosure,
child-partition-mismatch, forged-parent-sum, budget-exhausted,
depth-exhausted, policy-violation, tolerance-unmet,
released-interval-mismatch.  Producer-side refusal classes (8, mirroring the
engine's fail-closed panics): unsupported-expression, invalid-domain,
invalid-tolerance, budget-exhausted, depth-exhausted, float-resolution,
cannot-certify, tolerance-unmet.
