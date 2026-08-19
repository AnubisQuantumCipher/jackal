# JACKAL juggernaut — W3 / W4 / W6 / W10 completion record

**Date:** 2026-08-19
**Branch:** `feat/domain-pack-protocol`
**Engine source digest at close:** `jackal_calc.anb` =
`982d53110f6c92d788625482b8133a0fd605e0ef0e5d55fa1e2e44c0b01ee7a0`
**Anubis compiler pin:** `anubis-a733565f237d`
(`a733565f237df171e7cf93b9b37700a42d8713576818fd92f8cd23a8ad7a69e2`)

Scope closed against the governing plan
`docs/superpowers/plans/2026-08-17-jackal-macos-juggernaut-program.md` and the
status ledger `.../2026-08-18-jackal-juggernaut-completion-ledger.md`, which
recorded W3, W6 and W10 as OPEN and W4 as PARTIAL.

Every row below carries the command that produced it. Rows without a re-runnable
command are marked `[NEEDS-HUMAN]` and are not claimed as done.

---

## 0. Engine defect closed — `lcm` was a mislabeled epistemic class

`maturity` declares `lcm` as `class=exact` with
`residual=none-observed-within-grammar-and-budgets`. The implementation was
`positive_abs(a / gcd_safe(a, b) * b)` evaluated in `i64`, which **wraps** once
the true lcm exceeds `2^63 - 1`. Observed on two separately-built binaries before
the fix:

```
lcm 4611686018427387904 3  ->  4611686018427387904      (smaller than an input)
lcm 9223372036854775807 3  ->  9223372036854775805
```

Both are refuted by the engine's own arbitrary-precision lane:

```
$ run jackal_calc.anb -- rat "4611686018427387904*3"
exact=13835058055282163712
$ run jackal_calc.anb -- rat "(9223372036854775807/1)*3"
exact=27670116110564327421
```

A command that declares `exact` and silently returns a wrapped value is the
precise failure this engine exists to prevent, so this was fixed rather than
documented. The quotient `a / g` is still reduced in `i64` (always exact, since
`|a/g| <= |a|`) and the final product is formed in the same arbitrary-precision
lane that backs `big-mul`. No `i64` product remains on the path.

Observed after the fix:

```
lcm 4611686018427387904 3   ->  13835058055282163712
lcm 9223372036854775807 3   ->  27670116110564327421
lcm 12 18 -> 36     lcm 4 6 -> 12      lcm 8 12 -> 24     lcm 6 15 -> 30
lcm 0 5  -> 0       lcm 0 0 -> 0       lcm 7 7  -> 7      lcm 1 1  -> 1
lcm -12 18 -> 36    lcm 12 -18 -> 36
```

Guard: `tools/lcm_differential_gate.py`, a 40-case frozen boundary corpus that
compares the engine's `lcm` against the engine's own `rat` lane, plus Python's
`math.lcm` as a **test-only** third opinion (never an assurance source, per
`PACK_SPEC` §1). The gate refuses to report PASS if no corpus row exceeded `i64`
(`overflow_rows == 0` is itself a failure), so it cannot become a rubber stamp.

The gate also caught an error in its own corpus on first run: a row annotated
`overflow` measured `fits`. The band cross-check reports the measurement as
authoritative and the annotation as a comment, which is why the mistake surfaced
as a FAIL rather than being absorbed.

`gcd` is unaffected: its result cannot exceed its inputs, so it cannot overflow.

---

## 1. W4 — versioned domain-pack protocol, second and third evidence contracts

The blocker recorded in `PACK_SPEC` §4 was that exactly **one** evidence contract
was admissible (`exact-cert / jackal-exact-cert-v1 / tools/exact_verify.py`), so
no programming or decision pack could be built.

Now admitted, three contracts:

| evidence kind | schema | checker | assurance ceiling | consequence ceiling |
|---|---|---|---|---|
| `exact-cert` | `jackal-exact-cert-v1` | `tools/exact_verify.py` | `exact` | `safety-critical` |
| `test-exists-cert` | `jackal-test-exists-cert-v1` | `tools/test_exists_verify.py` | `exact` | `informational` |
| `decision-cert` | `jackal-decision-cert-v1` | `tools/decision_verify.py` | `exact` | `decision-boundary` |

`release/claim/inference_registry_v1.json` bumped `registry_version` 1 -> 2. The
bump is **additive**: no rule, axis order, consequence class, budget, or
`producer_emittable` entry changed semantics. That reasoning is recorded in the
registry's own `notes` field so a later reader need not re-derive it.

### The laundering that was refused

Admitting the kinds changed the registry's bytes
(`e7c999c3...` -> `97fb22c1...`). That digest was pinned in five places, three of
which are **frozen v1.6.0 evidence** that records the registry digest inside its
own signed body. "Updating the pin" there would mean rewriting recorded evidence
so it asserts a replay against bytes that did not exist at v1.6.0 — the exact
defect this program exists to catch.

Resolution: the `registry_version 1` bytes were archived to
`release/claim/archive/inference_registry_v1__registry_version_1.json`, verified
byte-identical to `git show HEAD:release/claim/inference_registry_v1.json` and
hashing to `e7c999c3...`, and only the v1.6.0 historical replay in
`release/tools/ci_claim_admission.py` was re-pointed at the archive. The live
registry path is free to evolve. `release/evidence/**` was not touched.

```
BEFORE archive:  FAIL positive-replay  reason=registry-inference-mismatch   exit 1
AFTER  archive:  CI_CLAIM_ADMISSION_PASS checks=3                           exit 0
                 (tamper-refusal still genuinely refuses: node-id-mismatch)
```

A regression guard `tests/ci_claim_archive_pin_test.py` (5 tests) fails if anyone
later re-points that replay at the live registry. It includes a **mutation
control** that re-points the constant in-process and asserts the gate then fails,
so the guard cannot pass while it has stopped being load-bearing.

### The anti-laundering boundary, enforced mechanically

`tools/domain_pack_verify.py` enforces the **consequence** ceiling, not only the
assurance ceiling. Full observed matrix:

| declared ceiling | `test-exists-cert` (bound `informational`) | `decision-cert` (bound `decision-boundary`) |
|---|---|---|
| `informational` | ACCEPTED | ACCEPTED |
| `advisory` | REFUSED | ACCEPTED |
| `decision-boundary` | REFUSED | ACCEPTED |
| `safety-critical` | REFUSED | REFUSED |

Validated as load-bearing rather than incidental: with the bound at
`informational` a fully digest-coherent laundering tree is REFUSED; flipping only
the bound to `safety-critical` makes the identical tree ACCEPTED. So the guard is
what refuses it, not a side-effect of a digest check.

```
$ python3 -I -S -B tools/domain_pack_verify.py
{"pack_count":3,"operation_count":4,"status":"accepted",
 "anubis_execution_status":"NOT_EXECUTED","assurance_status":"NOT_MINTED", ...}
```

Note the verifier's own honesty: it records that Anubis was not executed and that
assurance was not minted. A manifest ceiling is an upper bound, never a grant.

---

## 2. W6 — programming and decision packs

### `jackal.programming.source`

The generalization past mathematics. Two operations:

- `programming.source.test_exists.v1` (5 args) — asserts a declaration-shaped
  occurrence of a named symbol exists in a file at a claimed content hash, at a
  claimed line, with a claimed declaration count.
- `programming.source.claim_cites_test.v1` (6 args) — asserts a documentation
  claim occurs verbatim in a doc file AND that the test it cites actually exists.

Byte-parity verified for the route (a `PACK_SPEC` §2 requirement):

```
$ run ... -- pack-route jackal.programming.source programming.source.test_exists.v1 <path> <sha> <sym> <line> <count>
$ run ... -- test-exists <path> <sha> <sym> <line> <count>
        -> identical stdout, including the certificate envelope
```

**Soundness: the caller cannot mint a true claim by lying.** The engine validates
only canonical *form*; `tools/test_exists_verify.py` recomputes every field from
the real bytes. Observed:

```
$ python3 tools/test_exists_verify.py --cert <cert with an invented symbol> --root .
REFUSE cert-symbol-absent: no declaration-shaped occurrence of '...' in ...
exit=2
```

**Why this operation exists.** In a session on 2026-08-19 an agent's own
documentation claimed a test verified every polynomial moment through degree 23.
The test checked degree 0. The claim cited a real file, was never fabricated, and
was still false — and a certified arithmetic oracle could not see it, because
nothing about it is arithmetic. `claim_cites_test` is the first operation that can.

**Permanent nonclaims** (in the manifest and in the checker's docstring):
`no_input_truth`, `test_existence_is_not_correctness`,
`citation_resolution_is_not_coverage`. Resolving a citation is not validating it:
a document may cite a real test that checks something entirely different, and this
checker cannot see that. It says so rather than implying otherwise.

### `jackal.decision.matrix`

One operation, `decision.matrix.rank.v1` -> `decision-rank`. Selects argmax/argmin
of caller-declared integer scores under a caller-declared criterion and records
the margin to the runner-up. Observed:

```
$ run ... -- decision-rank vendor_pick latency_ms min alpha 120 beta 95 gamma 210
status=exact selected=beta margin=25
consequence=decision-boundary note=the-declared-criterion-remains-the-callers-...
decision-cert={"claim":{"criterion":"latency_ms","decision_id":"vendor_pick",
  "margin":"25","options":[...],"runner_up":"alpha","selected":"beta","sense":"min"},...}
```

Byte-identical via `pack-route`. All five refusal paths observed firing:

```
decision-value-judgment    criterion `best_option`   -> refused
decision-margin-zero       top-two tie              -> refused
decision-duplicate-label   duplicate option label   -> refused
decision-sense-unknown     sense `sideways`         -> refused
pack-request-arity         odd label/value pairing  -> refused
```

`tools/decision_verify.py` independently recomputes selection, runner-up and
margin from the certificate's own option array and refuses on disagreement:

```
REFUSE cert-selection-mismatch: selected claims 'gamma' but the min of {...} is 'beta'
REFUSE cert-margin-mismatch: margin claimed 400 but recomputes to 25
REFUSE cert-margin-zero: 'alpha' and 'beta' tie on latency_ms: a tie is not a decision
REFUSE cert-value-judgment: criterion 'best_overall' contains 'best'
```

**What the decision pack refuses to do, permanently.** It will order options by a
stated, recomputable numeric criterion. It will not rank them on preference,
goodness or worth, and accepting a caller's numeric criterion is **not** a claim
that the criterion is the right one to optimise. That sentence is in the pack
source, the certificate's own `consequence` line, and the manifest nonclaims.

**Known limitation, stated rather than hidden:** the value-judgment screen is a
substring blocklist of 20 words. A blocklist is inherently incomplete — a
criterion spelled `optimal`, `preference_score`, or `b3st` will pass. It raises
the cost of laundering a value judgment; it does not close it. Closing it properly
needs a declared unit or measurement provenance on the criterion, which is a
protocol change, not a word-list change. `[NEEDS-HUMAN]` for a future protocol
revision.

**Arity encoding, a deliberate judgement call.** `decision-rank` is variadic
(7..15 operation arguments) but the protocol's `argument_schema` has no notion of
optional positions and the verifier requires
`len(argument_schema) == resources.max_arguments`. The manifest therefore declares
`max_arguments = 15` with 15 enumerated positions. Declaring the minimum instead
would set a resource bound the engine legitimately exceeds, which is strictly
worse. Growing the protocol an explicit min/max arity is the correct long-term
fix and was **not** done here, because it is a schema change.

---

## 3. W3 — agent-native profiles

Three immutable profiles, `schema: jackal-agent-profile-v1`, each carrying a
`profile_digest_sha256` over the canonical JSON with that field omitted.

```
$ python3 tools/profile_verify.py
profile=core   tools=3  digest=6957117f... OK
profile=formal tools=13 digest=dfd876ef... OK
profile=full   tools=34 digest=f90e6838... OK
profile_verification=verified tools_declared=34 nesting=core<=formal<=full OK
```

`core` is `jackal_verify_receipt`, `jackal_claim`, `jackal_verify_bundle` — the
only three of the 34 tools that are claim/verification front doors rather than
producers of a fresh number. An agent restricted to `core` must verify before it
can speak, and cannot silently reach a weaker lane because no weaker lane is
exposed; widening is an explicit operator act.

`formal` is `core` ∪ the 10 tools whose lane terminates in a Lean-proved checker.
The plan's enumeration of the formal lane (11 tools) excluded `jackal_claim` and
`jackal_verify_bundle`, but the same plan requires `core ⊆ formal ⊆ full`. The
tension was resolved by layering, on the reasoning that a profile able to *produce*
a formal receipt but unable to *replay* one would let an agent emit assurance it
cannot itself re-check. `jackal_integrate_bound` is deliberately excluded: its
enclosure is conditional on a stated f64/libm model and is campaign-tested, not
machine-proved.

```
$ python3 -m unittest tests.profile_contract_test -v
Ran 26 tests — OK        case_census positive=9 refusal=16
```

`evals/v2/protocol.md` defines the metric names and the forced/autonomous modes,
and states explicitly that it defines names only and measures nothing itself.

---

## 4. W10 — eval v2

50-item corpus, aggregate digest
`41f4cbded9f2c6cb8f5b4ec95833e246364b6c45f6704dabe7e7c7dc189ff573`, frozen into
`evals/v2/hidden_set_v1.json` by `--emit-hidden-set` (never hand-written).
Categories: 28 `exact_integer`, 4 `rational`, 4 `enclosure`, 8 `refusal_expected`,
4 `programming_status`; 19 items `eligible_for_verifier`.

```
$ python3 evals/v2/runner.py --mode forced --out /tmp/eval_v2_full.json
items_run 50 of 50; passed 50; failed 0; refused 8; model_invoked: False

$ python3 evals/v2/metrics.py --verify-receipts /tmp/eval_v2_full.json
corpus_digest_match: True
accuracy, false_strong_claim_rate, refusal_precision, refusal_recall,
verifier_use_rate, silent_downgrade_count, latency_ms_p50, latency_ms_p95
RECEIPT_VERIFY_OK
```

Honesty properties worth naming:
- `refusal_precision` / `refusal_recall` return **`None`** on an empty
  denominator, not `1.0`. A vacuous `1.0` would be a dishonest metric.
- The runner invokes **no model**. `verifier_use_rate` in `autonomous` mode
  reflects a supplied `--transcript`, not a live model, and the file says so at
  the top.

`[NEEDS-HUMAN]` — the plan's W10 goal of comparing model-only vs Python vs
conventional CAS vs JACKAL across model families is **not** met by this harness.
What exists is the deterministic JACKAL arm plus the frozen hidden set. The
model arms require live model sessions, which this offline runner deliberately
does not perform. The `>= 90% verifier use on eligible autonomous tasks`
requirement from W3 likewise cannot be measured without those sessions.

---

## 5. Honest status against the plan

| workstream | state | evidence |
|---|---|---|
| engine `lcm` defect | **closed** | before/after outputs + differential gate |
| W4 protocol + evidence contracts | **closed** | verifier accepts 3 packs / 4 ops; ceiling matrix; archival fix |
| W6 programming pack | **closed** | parity + soundness refusals + nonclaims |
| W6 decision pack | **closed** | parity + 5 refusal paths + independent checker |
| W6 other packs (units, linear algebra, statistics, ODE/PDE) | **NOT DONE** | out of scope this wave |
| W3 profiles | **closed** | verifier + 26 tests |
| W3 `>=90%` autonomous verifier-use enforcement | **NOT MEASURED** | needs live model sessions |
| W10 harness + frozen hidden set | **closed** | 50/50 forced run |
| W10 cross-system comparison | **NOT DONE** | needs live model sessions |
| `release/MANIFEST.sha256` | **STALE, deliberately** | generator needs build artifacts absent here |

Two `MANIFEST.sha256` rows need a seal-time repin on a machine with the built
engine and Lean binaries: `source jackal_calc.anb` and
`claim_inference_registry`. Neither was hand-edited; hand-editing a manifest row
to make a gate green is the same class of act as repinning frozen evidence.

W7/W8/W9/W11 are untouched and remain OPEN.
---

## 6. Digest appendix — generated from disk at close, not transcribed

Every value below was read from the working tree by hashing the file, so this
section cannot drift from the artifacts the way a hand-copied digest can.

| artifact | sha256 |
|---|---|
| `jackal_calc.anb` | `982d53110f6c92d788625482b8133a0fd605e0ef0e5d55fa1e2e44c0b01ee7a0` |
| `domain_packs/PACK_SPEC.md` | `b0a015b3aa6c6428a0f11bd5746dfe45e4d81b12fd9fe97c16ef7b8342b218a4` |
| `domain_packs/PACK_SCHEMA.json` | `ae15411cff7b126d1365d5fe8857bba9da5f6ef21d50dcdfab279e9634bc0073` |
| `domain_packs/registry_v1.json` | `3c97272f92297826c7b2a3aa78cf4625854cbf54ce641d036674acc32f9e10fb` |
| `domain_packs/core/manifest.json` | `6672a6e238923fbca4aa599770b8e9d0b47744f05ba9b5398f701f5e0028b2dd` |
| `domain_packs/programming/manifest.json` | `75516d97b67e170fead12813596ae9ccfc93ec3daf2d2c82a5c09140139c3f9b` |
| `domain_packs/decision/manifest.json` | `96d34b288886b3bdeba470a5cb63dba7d57cb33e0041e3e4421c38d29bdd0ea7` |
| `domain_packs/core/core_pack.anb` | `5c9e23ce102366c3e7bb2aa01c78ace6d4bc20bd2d35e0813fd62bd3c324d405` |
| `domain_packs/programming/programming_pack.anb` | `f590ed33b757fda476db5b2771e0f0a50addc838721a97b562471cc75f2153f6` |
| `domain_packs/decision/decision_pack.anb` | `55e4083ce1711e0ee40d2aeb939d7806877dddef67ccb782ae061b0d0b26fb75` |
| `tools/domain_pack_verify.py` | `814792976b448f33f736cc215afaa8278612f921616dc904fa192bb3c30b5445` |
| `tools/test_exists_verify.py` | `598cb99e1eb70c9410ca87345efee346f73e43aaf3625427dca17ea04231caea` |
| `tools/decision_verify.py` | `bc3471352c2685dbf4848b0a2ba7daab63ace443cca043c258f36642a70e5af4` |
| `tools/exact_verify.py` | `2c07e6257ce1524de3e31374371c6d5859dce710767156de2566ec77fa1883a7` |
| `tools/profile_verify.py` | `3af6f11df5ff2b6bc9582ff162660286224f3cf74cce8f57b68d86140f34c3c7` |
| `tools/lcm_differential_gate.py` | `dad22643e8ab913e91a3689463f5b392cb0dc9071cefb9023f45ef19ff4ff119` |
| `release/claim/inference_registry_v1.json` | `97fb22c14e7a76d8edc7875df14725f7c4edeb47ad70903c2a10e7ed46a45efd` |
| `release/claim/archive/inference_registry_v1__registry_version_1.json` | `e7c999c34312288fc35d4e1ecab2cef244dd447174283f0e132e8ebee7277672` |

Self-digests and profile digests, read from inside the files:

| field | value |
|---|---|
| `registry_v1.json` `registry_digest_sha256` | `c42371afa320d5e8d97e205fccdccfe34affca2b9f306d6ef097745450d2504b` |
| `jackal.core.exact` `manifest_digest_sha256` | `5f39360199285272177ae80a67eaba775ab32c4c412ca4ecc10b1225e6abe684` |
| `jackal.decision.matrix` `manifest_digest_sha256` | `d16c16809177909258eb4a284d28f051b60f459ce6a643ba3c24c9b105969a17` |
| `jackal.programming.source` `manifest_digest_sha256` | `688d46f0f0b3eb5a26ba6fc21094a2897854f91801bcc3b317e6d4b21d30d8b1` |
| profile `core` `profile_digest_sha256` | `6957117f0401e87e38e9e616ba4ecdd100ad5a6882be3d7b8a899ae7658407ea` |
| profile `formal` `profile_digest_sha256` | `dfd876efed154ba40f223115b4cdd9c7f30cc29bcdce63bfff025f0f58f9f0b6` |
| profile `full` `profile_digest_sha256` | `f90e6838c0facbafa89329462451e167fcb4a251d75d328c7a6f12ead2aa0c7a` |
| eval corpus `aggregate_digest` | `41f4cbded9f2c6cb8f5b4ec95833e246364b6c45f6704dabe7e7c7dc189ff573` |

The archived registry hashes to `e7c999c34312288fc35d4e1ecab2cef244dd447174283f0e132e8ebee7277672`,
byte-identical to `git show HEAD:release/claim/inference_registry_v1.json`, which is what
keeps the frozen v1.6.0 replay honest.

### Gate results at close

```
domain_pack_verify: exit=0
profile_verify: exit=0
ci_claim_admission: exit=0
lcm_differential_gate: LCM_DIFFERENTIAL_GATE_PASS  cases=39 passed=39 overflow_rows=10
our four suites (domain_pack, profile, eval_v2, ci_claim_archive_pin): 130 tests, OK
```

### Pre-existing failures NOT caused by this branch

`python3 -m unittest discover -s tests` reports 12 errors and 1 failure in
suites that require build artifacts absent from this worktree — measured as
3 x missing `jackal-native`, 6 x missing `jackal_cert_check`, 3 x missing
`jackal_gaussian_check`. Those binaries are untracked. The same two
`release/MANIFEST.sha256` rows (`source jackal_calc.anb`,
`claim_inference_registry`) need a seal-time repin on a machine that has them.
Neither was hand-edited: hand-editing a manifest row to make a gate green is
the same class of act as repinning frozen evidence.
